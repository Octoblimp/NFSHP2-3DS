// vclip -- see vclip.h.
//
// Every vector here is a VU0 quadword in the original, and the arithmetic
// is lane-wise in the order the listing does it: a dot product is
// ((x*x' + y*y') + z*z') with each step rounded, a transform is the ACC
// chain ((r0*x + r1*y) + r2*z) [+ r3] on all four lanes, and a negation
// is `vsub.xyz vf, vf00, vf` -- 0 - x, which is +0 for a +0 where a true
// negation would give -0. The fourth lane is carried where the original
// stores it and a reader could see it: the transformed features' Head and
// Edge, and the contact points.
//
// Three contact-point writes store a quadword whose fourth lane was never
// written -- a vertex position assembled on the stack with swc1 x3 and
// moved with sqc2. The lane is whatever the frame held, which the port
// cannot reproduce; it writes 0 there. They are CheckVertexVertex's two
// points and CheckVertexEdge's vertex point when it penetrates. Nothing in
// the image reads a contact point's fourth lane.
//
// docs/formats/vclip.md has the decode.

#include "vclip.h"

#include <math.h>
#include <stdint.h>

#include "bmem.h"
#include "eefpu.h"
#include "replay.h"

int32_t       PrintThisTime;
int32_t       PlotClosestFeatures;
VCPolyhedron *pPrintingPolygon;
int32_t     (*gVClipWorldRandomFn)(int32_t range);

uint32_t VClipCalls;
uint32_t VClipSteps;
uint32_t VClipRestarts;

// ---------------------------------------------------------------- helpers

// A vertex's position as the listing loads it: three lwc1s packed with
// pextlw/pcpyld over a zero, so the fourth lane is 0.
static bVector3 vpos(const VCFeature *f)
{
    const VCVertex *v = (const VCVertex *)f;
    bVector3 r;

    r.x = v->CompressedPosition[0];
    r.y = v->CompressedPosition[1];
    r.z = v->CompressedPosition[2];
    r.pad = 0.0f;
    return r;
}

// An edge's direction: each int16 through cvt.s.w and a multiply by 2^-13.
static bVector3 edge_dir(const VCEdge *e)
{
    bVector3 r;

    r.x = (float)e->CompressedDirection[0] * VC_DIRECTION_SCALE;
    r.y = (float)e->CompressedDirection[1] * VC_DIRECTION_SCALE;
    r.z = (float)e->CompressedDirection[2] * VC_DIRECTION_SCALE;
    r.pad = 0.0f;
    return r;
}

// vmul.xyz, vaddy.x, vaddz.x.
static float dot3(const bVector3 *a, const bVector3 *b)
{
    return (a->x * b->x + a->y * b->y) + a->z * b->z;
}

static float normal_dot(const VCPlane *pl, const bVector3 *v)
{
    return (pl->CompressedNormal[0] * v->x + pl->CompressedNormal[1] * v->y)
        + pl->CompressedNormal[2] * v->z;
}

// ... and vsubx.x of the plane distance, broadcast by pextlw twice.
static float plane_dist(const VCPlane *pl, const bVector3 *p)
{
    return normal_dot(pl, p) - pl->CompressedPlaneDistance;
}

static float len_sq(const bVector3 *d)
{
    return (d->x * d->x + d->y * d->y) + d->z * d->z;
}

static bVector3 sub3(const bVector3 *a, const bVector3 *b)
{
    bVector3 r;

    r.x = a->x - b->x;
    r.y = a->y - b->y;
    r.z = a->z - b->z;
    r.pad = 0.0f;
    return r;
}

static void set_normal(VCPlane *pl, const bVector3 *n)
{
    pl->CompressedNormal[0] = n->x;
    pl->CompressedNormal[1] = n->y;
    pl->CompressedNormal[2] = n->z;
}

static bVector3 plane_normal(const VCPlane *pl)
{
    bVector3 r;

    r.x = pl->CompressedNormal[0];
    r.y = pl->CompressedNormal[1];
    r.z = pl->CompressedNormal[2];
    r.pad = 0.0f;
    return r;
}

// vsub.xyz vf, vf00, vf: the fourth lane is kept, and is 0 everywhere this
// is used.
static bVector3 zero_minus(const bVector3 *v)
{
    bVector3 r;

    r.x = 0.0f - v->x;
    r.y = 0.0f - v->y;
    r.z = 0.0f - v->z;
    r.pad = v->pad;
    return r;
}

// base + dir*s on xyz, vmuli/vmulx then vadd.xyz: the fourth lane is the
// base's.
static bVector3 along(const bVector3 *base, const bVector3 *dir, float s)
{
    bVector3 r;

    r.x = base->x + dir->x * s;
    r.y = base->y + dir->y * s;
    r.z = base->z + dir->z * s;
    r.pad = base->pad;
    return r;
}

// Edge*lambda + Tail, vmulx.xyzw then vadd.xyzw.
static bVector3 point_at(const VCTransformedFeature *xe, float lambda)
{
    bVector3 r;

    r.x = xe->Edge.x * lambda + xe->Tail.x;
    r.y = xe->Edge.y * lambda + xe->Tail.y;
    r.z = xe->Edge.z * lambda + xe->Tail.z;
    r.pad = xe->Edge.pad * lambda + xe->Tail.pad;
    return r;
}

static float lane_combine(float r0, float r1, float r2, const bVector3 *v)
{
    return (r0 * v->x + r1 * v->y) + r2 * v->z;
}

// The first feature of a check is the one on the polyhedron x12 carries out
// of, the second the one it carries into. SwitchState 1 means F1 is first,
// 2 that F1 is second.
static VCFeature *first(const VCWitness *w)
{
    return w->SwitchState == 1 ? w->F1 : w->F2;
}

static VCFeature *second(const VCWitness *w)
{
    return w->SwitchState == 2 ? w->F1 : w->F2;
}

static void set_first(VCWitness *w, VCFeature *f)
{
    if (w->SwitchState == 1)
        w->F1 = f;
    else
        w->F2 = f;
}

static void set_second(VCWitness *w, VCFeature *f)
{
    if (w->SwitchState == 2)
        w->F1 = f;
    else
        w->F2 = f;
}

// The contact points follow the features: the first feature's point is
// CP1 when SwitchState is 1, the second's is CP1 when it is 2.
static bVector3 *first_cp(VCWitness *w)
{
    return w->SwitchState == 1 ? &w->CP1 : &w->CP2;
}

static bVector3 *second_cp(VCWitness *w)
{
    return w->SwitchState == 2 ? &w->CP1 : &w->CP2;
}

static void set_xyz(bVector3 *dst, const bVector3 *src)
{
    dst->x = src->x;
    dst->y = src->y;
    dst->z = src->z;
}

// ---------------------------------------------------------------- transform

// 0x001c5d90.
float vc_dist_between(const bVector3 *v1, const bVector3 *v2)
{
    bVector3 d = sub3(v1, v2);

    return sqrtf(len_sq(&d));
}

// 0x001c5dc8. The translation row is summed on all four lanes, and the
// fourth then set to 1 by the swc1 in bTransposeMatrix's delay slot.
void vctransform_init(VCTransform *x, const bMatrix4 *endr,
                      const bVector3 *endt, const bMatrix4 *startr,
                      const bVector3 *startt)
{
    bMatrix4 m = *startr;
    bMatrix4 inv;

    m.v3.x = (m.v3.x + startt->x) - endt->x;
    m.v3.y = (m.v3.y + startt->y) - endt->y;
    m.v3.z = (m.v3.z + startt->z) - endt->z;
    m.v3.w = 1.0f;
    bTransposeMatrix(&inv, endr);
    bMulMatrix(&x->Matrix, &inv, &m);
}

// 0x001c5e60. The matrix with its translation row replaced by (0,0,0,1),
// through the vector overload of bMulMatrix -- which is bMulMatrixVec3.
void vctransform_transform_vector_p(const VCTransform *x, bVector3 *out,
                                    const bVector3 *in)
{
    bMatrix4 m = x->Matrix;

    m.v3.x = 0.0f;
    m.v3.y = 0.0f;
    m.v3.z = 0.0f;
    m.v3.w = 1.0f;
    bMulMatrixVec3(out, &m, in);
}

// 0x001c5ec8. vmulax, vmadday, vmaddz: the translation row plays no part.
// The listing also packs (0, 0, 1, 0) onto the stack and never reads it.
bVector3 vctransform_transform_vector(const VCTransform *x, bVector3 v)
{
    const bMatrix4 *m = &x->Matrix;
    bVector3 r;

    r.x = lane_combine(m->v0.x, m->v1.x, m->v2.x, &v);
    r.y = lane_combine(m->v0.y, m->v1.y, m->v2.y, &v);
    r.z = lane_combine(m->v0.z, m->v1.z, m->v2.z, &v);
    r.pad = lane_combine(m->v0.w, m->v1.w, m->v2.w, &v);
    return r;
}

// 0x001c5f20. The same with vmaddw of the translation row by vf00w's 1.
bVector3 vctransform_transform_point(const VCTransform *x, bVector3 v)
{
    const bMatrix4 *m = &x->Matrix;
    bVector3 r;

    r.x = lane_combine(m->v0.x, m->v1.x, m->v2.x, &v) + m->v3.x;
    r.y = lane_combine(m->v0.y, m->v1.y, m->v2.y, &v) + m->v3.y;
    r.z = lane_combine(m->v0.z, m->v1.z, m->v2.z, &v) + m->v3.z;
    r.pad = lane_combine(m->v0.w, m->v1.w, m->v2.w, &v) + m->v3.w;
    return r;
}

// 0x001c5f68.
void vctf_transform_vertex(VCTransformedFeature *tf, const VCTransform *x,
                           VCVertex *v)
{
    tf->pFeature = &v->Feature;
    tf->Head = vctransform_transform_point(x, vpos(&v->Feature));
}

// 0x001c5fd8. Head is the edge's plane-1 vertex and Tail its plane-0
// vertex; Edge is vsub.xyz of the two into Head's register, so its fourth
// lane is Head's.
void vctf_transform_edge(VCTransformedFeature *tf, const VCTransform *x,
                         VCEdge *e)
{
    bVector3 h, t;

    tf->pFeature = &e->Feature;
    h = vctransform_transform_point(x, vpos(e->pPlanes[1].Neighbor));
    t = vctransform_transform_point(x, vpos(e->pPlanes[0].Neighbor));
    tf->Head = h;
    tf->Tail = t;
    tf->Edge.x = h.x - t.x;
    tf->Edge.y = h.y - t.y;
    tf->Edge.z = h.z - t.z;
    tf->Edge.pad = h.pad;
}

// ---------------------------------------------------------------- clipping

// 0x001c6098.
void vcclip_init(VCVoronoiClip *c)
{
    c->LambdaMin = 0.0f;
    c->LambdaMax = 1.0f;
    c->NeighborMin = NULL;
    c->NeighborMax = NULL;
    c->Penetration = 0;
}

// 0x001c60c0. Clips the transformed edge Tail->Head against each plane,
// narrowing [LambdaMin, LambdaMax] and remembering the plane's neighbour
// at each end. 0 once the interval is empty -- both ends outside one plane,
// or the ends crossed. Each divide is by (dt - dh) with dt and dh of
// opposite signs, which cannot be zero.
int32_t vcclip_clip_planes(VCVoronoiClip *c, VCTransformedFeature *xedge,
                           VCVoronoiPlane *planes, int32_t n)
{
    int32_t i;

    for (i = 0; i < n; i++) {
        VCVoronoiPlane *pl = &planes[i];
        float dt = plane_dist(&pl->Plane, &xedge->Tail);
        float dh = plane_dist(&pl->Plane, &xedge->Head);
        float lambda;

        if (dt < 0.0f) {
            if (dh < 0.0f) {
                c->NeighborMin = pl->Neighbor;
                c->NeighborMax = pl->Neighbor;
                return 0;
            }
            lambda = dt / (dt - dh);
            if (c->LambdaMin < lambda) {
                c->LambdaMin = lambda;
                c->NeighborMin = pl->Neighbor;
                if (c->LambdaMax < lambda)
                    return 0;
            }
        } else if (dh < 0.0f) {
            lambda = dt / (dt - dh);
            if (lambda < c->LambdaMax) {
                c->LambdaMax = lambda;
                c->NeighborMax = pl->Neighbor;
                if (lambda < c->LambdaMin)
                    return 0;
            }
        }
    }
    return 1;
}

// 0x001c6228. The clip, then which neighbouring vertex region the edge
// runs into: the one at an end if the edge heads away from its vertex
// there. `vert` stands in for both neighbours' positions when given. The
// clip's own answer is not read.
VCFeature *vcclip_clip_vertex_planes(VCVoronoiClip *c,
                                     VCTransformedFeature *xedge,
                                     const bVector3 *vert,
                                     VCVoronoiPlane *planes, int32_t n)
{
    VCFeature *nmin, *nmax;
    bVector3 p, vp, d;

    (void)vcclip_clip_planes(c, xedge, planes, n);
    nmin = c->NeighborMin;
    if (nmin != NULL && nmin == c->NeighborMax)
        return nmin;

    if (nmin != NULL) {
        p = point_at(xedge, c->LambdaMin);
        vp = vert != NULL ? *vert : vpos(nmin);
        d = sub3(&p, &vp);
        if (len_sq(&d) < VC_VERTEX_MIN_TOUCH)
            c->Penetration = 1;
        else if (0.0f < dot3(&xedge->Edge, &d))
            return nmin;
    }

    nmax = c->NeighborMax;
    if (nmax == NULL)
        return NULL;
    p = point_at(xedge, c->LambdaMax);
    vp = vert != NULL ? *vert : vpos(nmax);
    d = sub3(&p, &vp);
    if (len_sq(&d) < VC_VERTEX_MAX_TOUCH) {
        c->Penetration = 1;
        return NULL;
    }
    if (dot3(&xedge->Edge, &d) < 0.0f)
        return nmax;
    return NULL;
}

// 0x001c6430. The same for the two face planes of an edge's region: which
// face the edge runs into. When the clip emptied with a face at one end,
// that face is the fallback answer at the other.
VCFeature *vcclip_clip_face_planes(VCVoronoiClip *c,
                                   VCTransformedFeature *xedge, VCFace *face,
                                   VCVoronoiPlane *planes, int32_t n)
{
    int32_t r = vcclip_clip_planes(c, xedge, planes, n);
    VCFeature *nmin = c->NeighborMin;
    VCFeature *nmax;
    const VCFace *f;
    bVector3 p;
    float dist;
    int32_t fallback = 0;

    if (nmin != NULL && nmin == c->NeighborMax)
        return nmin;

    // An empty clip leaves both neighbours set: each exit from the loop
    // stores the one it tests against.
    if (r == 0) {
        if (nmin->Type == VCFEATURE_FACE) {
            fallback = 1;
            if (c->NeighborMax->Type == VCFEATURE_EDGE)
                return nmin;
        } else if (c->NeighborMax->Type == VCFEATURE_FACE) {
            fallback = 1;
            if (nmin->Type == VCFEATURE_EDGE)
                return c->NeighborMax;
        }
    }

    if (nmin != NULL && nmin->Type == VCFEATURE_FACE) {
        f = face != NULL ? face : (const VCFace *)nmin;
        p = point_at(xedge, c->LambdaMin);
        dist = plane_dist(&f->Plane, &p);
        if (fabsf(dist) < VC_FACE_MIN_TOUCH) {
            c->Penetration = 1;
        } else {
            if (0.0f < dist * normal_dot(&f->Plane, &xedge->Edge))
                return nmin;
            if (fallback)
                return c->NeighborMax;
        }
    }

    nmax = c->NeighborMax;
    if (nmax == NULL || nmax->Type != VCFEATURE_FACE)
        return NULL;
    f = face != NULL ? face : (const VCFace *)nmax;
    p = point_at(xedge, c->LambdaMax);
    dist = plane_dist(&f->Plane, &p);
    if (fabsf(dist) < VC_FACE_MAX_TOUCH) {
        c->Penetration = 1;
        return NULL;
    }
    if (dist * normal_dot(&f->Plane, &xedge->Edge) < 0.0f)
        return nmax;
    return fallback ? nmin : NULL;
}

// ---------------------------------------------------------------- witness

// 0x001c6700. The contact points' xyz are zeroed and their fourth lanes
// left alone. Each polyhedron starts from its first vertex.
void vcwitness_init(VCWitness *w, VCPolyhedron *p1, VCPolyhedron *p2)
{
    w->CP1.x = 0.0f;
    w->CP1.y = 0.0f;
    w->CP1.z = 0.0f;
    w->CP2.x = 0.0f;
    w->CP2.y = 0.0f;
    w->CP2.z = 0.0f;
    w->F1 = (VCFeature *)p1->pVertices;
    w->F2 = (VCFeature *)p2->pVertices;
    w->P1 = p1;
    w->P2 = p2;
    w->SwitchState = 0;
    w->Distance = 0.0f;
    w->pCaffeineObj1 = NULL;
    w->pCaffeineObj2 = NULL;
}

// 0x001c6750. The two plot objects are made together, so only the first
// is tested before both are deleted.
void vcwitness_destroy(VCWitness *w, int32_t flags)
{
    if (w->pCaffeineObj1 != NULL) {
        esp_delete_object(w->pCaffeineObj1);
        esp_delete_object(w->pCaffeineObj2);
        w->pCaffeineObj1 = NULL;
        w->pCaffeineObj2 = NULL;
    }
    if (flags & 1)
        bFree(w);
}

// 0x001c68a0.
// 0x001d0948.
void vcwitness_do_snapshot(VCWitness *w, ReplaySnapshot *s)
{
    uint32_t code1, code2;

    ReplaySnapshot_BeginSection(s, w, "VCWitness");
    code1 = vcpoly_get_feature_code(w->P1, w->F1);
    code2 = vcpoly_get_feature_code(w->P2, w->F2);
    ReplaySnapshot_MoveUInt(s, &code1, 4);
    ReplaySnapshot_MoveUInt(s, &code2, 4);
    if (s->RestoringSnapshotFlag) {
        w->F1 = vcpoly_get_feature(w->P1, code1);
        w->F2 = vcpoly_get_feature(w->P2, code2);
    }
    ReplaySnapshot_MoveInt(s, &w->SwitchState, 4);
    ReplaySnapshot_MoveVector3(s, &w->CP1);
    ReplaySnapshot_MoveVector3(s, &w->CP2);
    ReplaySnapshot_MoveFloat(s, &w->Distance);
    ReplaySnapshot_EndSection(s);
}

void vcwitness_print_state(VCWitness *w)
{
    (void)w;
}

// 0x001c68a8. Each vertex tested against the other's region; if both lie
// in it, they are the closest pair.
int32_t vcwitness_check_vertex_vertex(VCWitness *w, VCTransform *x12,
                                      VCTransform *x21,
                                      VCTransformedFeature *xf1,
                                      VCTransformedFeature *xf2)
{
    VCVertex *a = (VCVertex *)first(w);
    VCVertex *b = (VCVertex *)second(w);
    bVector3 pa, d;
    int32_t i;

    vctf_transform_vertex(xf1, x12, a);
    for (i = 0; i < b->Feature.NumPlanes; i++) {
        if (plane_dist(&b->pPlanes[i].Plane, &xf1->Head) < 0.0f) {
            set_second(w, b->pPlanes[i].Neighbor);
            return 0;
        }
    }
    vctf_transform_vertex(xf2, x21, b);
    for (i = 0; i < a->Feature.NumPlanes; i++) {
        if (plane_dist(&a->pPlanes[i].Plane, &xf2->Head) < 0.0f) {
            set_first(w, a->pPlanes[i].Neighbor);
            return 0;
        }
    }

    // The fourth lane of both points is the frame's: see the top of the
    // file.
    pa = vpos(&a->Feature);
    d = sub3(&pa, &xf2->Head);
    w->Distance = sqrtf(len_sq(&d));
    *first_cp(w) = pa;
    *second_cp(w) = vpos(&b->Feature);
    return VC_VV_TOUCH < w->Distance ? 1 : 2;
}

// 0x001c6ba0. The vertex against the edge's four planes, then the edge
// against the vertex's. The closest point on the edge is the projection
// onto its line, unclamped: the edge's vertex planes already put the vertex
// between its ends.
int32_t vcwitness_check_vertex_edge(VCWitness *w, VCTransform *x12,
                                    VCTransform *x21,
                                    VCTransformedFeature *xf1,
                                    VCTransformedFeature *xf2)
{
    VCVertex *v = (VCVertex *)first(w);
    VCEdge *e = (VCEdge *)second(w);
    VCVoronoiClip clip;
    VCFeature *r;
    bVector3 vp, tail, dir, d, q;
    float t;
    int32_t i;

    vctf_transform_vertex(xf1, x12, v);
    for (i = 0; i < 4; i++) {
        if (plane_dist(&e->pPlanes[i].Plane, &xf1->Head) < 0.0f) {
            set_second(w, e->pPlanes[i].Neighbor);
            return 0;
        }
    }

    vctf_transform_edge(xf2, x21, e);
    vcclip_init(&clip);
    vp = vpos(&v->Feature);
    r = vcclip_clip_vertex_planes(&clip, xf2, &vp, v->pPlanes,
                                  v->Feature.NumPlanes);
    if (r != NULL) {
        set_first(w, r);
        return 0;
    }
    if (clip.Penetration) {
        w->Distance = 0.0f;
        *first_cp(w) = vp;          // the frame's fourth lane in the image
        *second_cp(w) = xf1->Head;
        return 2;
    }

    *first_cp(w) = vpos(&v->Feature);
    tail = vpos(e->pPlanes[0].Neighbor);
    dir = edge_dir(e);
    d = sub3(&xf1->Head, &tail);
    t = dot3(&d, &dir);
    q = along(&tail, &dir, t);
    *second_cp(w) = q;
    d = sub3(&xf1->Head, second_cp(w));
    w->Distance = sqrtf(len_sq(&d));
    return 1;
}

// 0x001c6ed8. The vertex against the face's region; then, if it lies over
// the face, whether an edge at the vertex leads closer to the face's plane.
// A vertex behind the plane and inside every edge's region has gone
// through: every face of the polyhedron is searched for the one it is
// least deep behind. x21 and xf2 are not used.
int32_t vcwitness_check_vertex_face(VCWitness *w, VCTransform *x12,
                                    VCTransform *x21,
                                    VCTransformedFeature *xf1,
                                    VCTransformedFeature *xf2)
{
    VCVertex *v = (VCVertex *)first(w);
    VCFace *f = (VCFace *)second(w);
    VCPolyhedron *p;
    const VCFace *bf;
    bVector3 pv, n, q;
    float least = 0.0f, h, best;
    int32_t i, worst = -1, count;

    (void)x21;
    (void)xf2;

    vctf_transform_vertex(xf1, x12, v);
    for (i = 0; i < f->Feature.NumPlanes; i++) {
        float d = plane_dist(&f->pPlanes[i].Plane, &xf1->Head);

        if (d < least) {
            least = d;
            worst = i;
        }
    }
    if (worst != -1) {
        set_second(w, f->pPlanes[worst].Neighbor);
        return 0;
    }

    pv = vpos(&v->Feature);
    h = plane_dist(&f->Plane, &xf1->Head);
    if (fabsf(h) < VC_VF_TOUCH) {
        w->Distance = 0.0f;
        set_xyz(first_cp(w), &pv);
        *second_cp(w) = xf1->Head;
        return 2;
    }

    for (i = 0; i < v->Feature.NumPlanes; i++) {
        VCEdge *e = (VCEdge *)v->pPlanes[i].Neighbor;
        VCFeature *other = e->pPlanes[0].Neighbor;
        VCTransformedFeature tf;
        float o;

        if (other == &v->Feature)
            other = e->pPlanes[1].Neighbor;
        tf.pFeature = NULL;
        vctf_transform_vertex(&tf, x12, (VCVertex *)other);
        o = plane_dist(&f->Plane, &tf.Head);
        if ((h < 0.0f && h < o) || (0.0f < h && o < h)) {
            set_first(w, &e->Feature);
            return 0;
        }
    }

    if (0.0f < h) {
        set_xyz(first_cp(w), &pv);
        n = plane_normal(&f->Plane);
        q = xf1->Head;
        q.pad = 0.0f;
        *second_cp(w) = along(&q, &n, -h);
        w->Distance = h;
        return 1;
    }

    p = w->SwitchState == 2 ? w->P1 : w->P2;
    count = p->NumFaces;
    bf = f;
    best = h;
    for (i = 0; i < count; i++) {
        VCFace *face = &p->pFaces[i];
        float fd = plane_dist(&face->Plane, &xf1->Head);

        if (best < fd) {
            best = fd;
            bf = face;
            set_second(w, &face->Feature);
        }
    }
    w->Distance = best;
    set_xyz(first_cp(w), &pv);
    n = plane_normal(&bf->Plane);
    q = xf1->Head;
    q.pad = 0.0f;
    *second_cp(w) = along(&q, &n, -best);
    return best < 0.0f ? 2 : 1;
}

// 0x001c7498. The transformed edge against another edge's two vertex
// planes, then -- on the same clip, not reset -- its two face planes.
// `which` is the SwitchState under which the moving feature is F1.
int32_t vcwitness_sub_check_edge_edge(VCWitness *w,
                                      VCTransformedFeature *xf, VCEdge *edge,
                                      int32_t which)
{
    VCVoronoiClip clip;
    VCFeature *r;

    vcclip_init(&clip);
    r = vcclip_clip_vertex_planes(&clip, xf, NULL, edge->pPlanes, 2);
    if (r != NULL) {
        if (which == w->SwitchState)
            w->F1 = r;
        else
            w->F2 = r;
        return 0;
    }
    if (clip.Penetration) {
        w->Distance = 0.0f;
        return 2;
    }
    r = vcclip_clip_face_planes(&clip, xf, NULL, &edge->pPlanes[2], 2);
    if (r != NULL) {
        if (which == w->SwitchState)
            w->F1 = r;
        else
            w->F2 = r;
        return 0;
    }
    if (clip.Penetration) {
        w->Distance = 0.0f;
        return 2;
    }
    return 1;
}

// The closest point on edge `a` (in its own frame, from tail to head) to
// the line through `otail` along `odir`, both already in a's frame. The
// parameter is clamped to the edge, and a parallel pair takes whichever
// end the offset leans towards. CheckEdgeEdge and CheckEdgeFace each have
// this inline, instruction for instruction.
static bVector3 closest_on_edge(const VCEdge *a, const bVector3 *otail,
                                const bVector3 *odir, float parallel)
{
    bVector3 tail = vpos(a->pPlanes[0].Neighbor);
    bVector3 head = vpos(a->pPlanes[1].Neighbor);
    bVector3 da = edge_dir(a);
    bVector3 ot = *otail;
    bVector3 diff, dbc, perp;
    float c, c2, num, den, lambda, len;

    ot.pad = 0.0f;
    diff = sub3(&ot, &tail);
    c = dot3(odir, &da);
    dbc.x = odir->x * c;
    dbc.y = odir->y * c;
    dbc.z = odir->z * c;
    c2 = c * c;
    perp = sub3(&da, &dbc);
    num = dot3(&diff, &perp);
    den = 1.0f - c2;
    if (den < parallel)
        return 0.0f < num ? head : tail;
    lambda = num / den;
    if (lambda < 0.0f) {
        lambda = 0.0f;
    } else {
        len = vc_dist_between(&head, &tail);
        if (len < lambda)
            lambda = len;
    }
    return along(&tail, &da, lambda);
}

// The foot of the perpendicular from p onto edge b's line, in b's frame.
static bVector3 foot_on_line(const VCEdge *b, const bVector3 *p)
{
    bVector3 bt = vpos(b->pPlanes[0].Neighbor);
    bVector3 dir = edge_dir(b);
    bVector3 d = sub3(p, &bt);

    return along(&bt, &dir, dot3(&d, &dir));
}

// 0x001c7578. Each edge against the other's region; if both hold, the
// closest points are the classic segment-segment ones -- clamped on the
// first edge, projected unclamped onto the second.
int32_t vcwitness_check_edge_edge(VCWitness *w, VCTransform *x12,
                                  VCTransform *x21,
                                  VCTransformedFeature *xf1,
                                  VCTransformedFeature *xf2)
{
    VCEdge *a = (VCEdge *)first(w);
    VCEdge *b = (VCEdge *)second(w);
    bVector3 db, cp, p;
    bVector3 *cpa, *cpb;
    int32_t r;

    vctf_transform_edge(xf1, x12, a);
    r = vcwitness_sub_check_edge_edge(w, xf1, b, 2);
    if (r != 1)
        return r;
    vctf_transform_edge(xf2, x21, b);
    r = vcwitness_sub_check_edge_edge(w, xf2, a, 1);
    if (r != 1)
        return r;

    db = vctransform_transform_vector(x21, edge_dir(b));
    cpa = first_cp(w);
    *cpa = closest_on_edge(a, &xf2->Tail, &db, VC_EE_PARALLEL);

    cp = *first_cp(w);
    cp.pad = 0.0f;
    p = vctransform_transform_point(x12, cp);
    cpb = second_cp(w);
    *cpb = foot_on_line(b, &p);
    cp = *second_cp(w);
    cp.pad = 0.0f;
    w->Distance = vc_dist_between(&p, &cp);
    return 1;
}

// 0x001c7ab0. The edge clipped against the face's region. Clipped to a
// piece over the face, it either crosses the plane (touching) or leads
// towards it through one end. Clipped away entirely, it is closest to one
// of the face's edges: the one nearest it by the edge-edge closest points,
// or the region that edge's vertex planes send it to. xf2 is not used.
int32_t vcwitness_check_edge_face(VCWitness *w, VCTransform *x12,
                                  VCTransform *x21,
                                  VCTransformedFeature *xf1,
                                  VCTransformedFeature *xf2)
{
    VCEdge *e = (VCEdge *)first(w);
    VCFace *f = (VCFace *)second(w);
    VCVoronoiClip clip;
    VCFeature *best_r2 = NULL;
    VCEdge *best_g = NULL;
    float least = 0.0f;
    int32_t i;

    (void)xf2;

    vctf_transform_edge(xf1, x12, e);
    vcclip_init(&clip);
    if (vcclip_clip_planes(&clip, xf1, f->pPlanes, f->Feature.NumPlanes)) {
        bVector3 pmin = point_at(xf1, clip.LambdaMin);
        bVector3 pmax = point_at(xf1, clip.LambdaMax);
        float dmin = plane_dist(&f->Plane, &pmin);
        float dmax = plane_dist(&f->Plane, &pmax);

        if (dmin * dmax <= 0.0f) {
            w->Distance = 0.0f;
            return 2;
        }
        if (0.0f < dmin * normal_dot(&f->Plane, &xf1->Edge)) {
            if (clip.NeighborMin != NULL)
                set_second(w, clip.NeighborMin);
            else
                set_first(w, e->pPlanes[0].Neighbor);
        } else {
            if (clip.NeighborMax != NULL)
                set_second(w, clip.NeighborMax);
            else
                set_first(w, e->pPlanes[1].Neighbor);
        }
        return 0;
    }

    for (i = 0; i < f->Feature.NumPlanes; i++) {
        VCEdge *g = (VCEdge *)f->pPlanes[i].Neighbor;
        VCTransformedFeature tf;
        VCVoronoiClip clip2;
        VCFeature *r2;
        bVector3 dg, q, p, qg;
        float dist;

        tf.pFeature = NULL;
        vctf_transform_edge(&tf, x21, g);
        dg = vctransform_transform_vector(x21, edge_dir(g));
        q = closest_on_edge(e, &tf.Tail, &dg, VC_EF_PARALLEL);
        q.pad = 0.0f;
        p = vctransform_transform_point(x12, q);
        qg = foot_on_line(g, &p);
        dist = vc_dist_between(&p, &qg);

        vcclip_init(&clip2);
        r2 = vcclip_clip_vertex_planes(&clip2, xf1, NULL, g->pPlanes, 2);
        if (clip2.Penetration)
            return 2;               // Distance is left as it was
        if (i == 0 || dist < least) {
            best_r2 = r2;
            least = dist;
            best_g = g;
        }
    }
    if (best_r2 != NULL)
        set_second(w, best_r2);
    else
        set_second(w, (VCFeature *)best_g);
    return 0;
}

// Retail's 0x001d2778, VClip's own: puts the pair the witness holds at `n`
// in the two lists, and answers 1 if one of the ten before it was the same
// pair. Most steps that settle move neither feature, so most walks of two
// steps or more end with a yes. CheckVertexFace's search for the deepest
// face moves the face as it settles, and that ends with a no.
static int32_t vclip_pair_seen(const VCWitness *w, VCFeature **l1,
                               VCFeature **l2, int32_t n)
{
    int32_t i, k;

    l1[n] = w->F1;
    l2[n] = w->F2;
    for (i = n - 1, k = 0; i >= 0 && k < VC_CYCLE_LOOKBACK; i--, k++)
        if (l1[i] == w->F1 && l2[i] == w->F2)
            return 1;
    return 0;
}

static VCFeature *vclip_random_vertex(VCPolyhedron *p)
{
    int32_t r = gVClipWorldRandomFn != NULL
        ? gVClipWorldRandomFn(p->NumVertices) : 0;

    return &p->pVertices[r].Feature;
}

// Retail's 0x001d2390 (the demo's 0x001c8200). The two transforms, then up
// to 80 steps of whichever check the pair of feature types calls for. The
// first-listed type of each check is the "first" feature, so SwitchState
// says which of F1 and F2 that is, and the transforms and transformed
// features are passed swapped when it is F2.
//
// Retail added the restart. After each step the pair goes in two lists of
// 80, and a pair one of the ten steps before it held starts the walk again
// from a random vertex of P1 and then of P2, World::Random's on each
// polyhedron's vertex count, with the lists and the step count from 0.
// That is tested before the status, so a step that settles without moving
// a feature, after one that did, is a repeat too: the answer stands (the
// contact points and the distance are the check's), but the witness keeps
// the two random vertices, the next call walks from them, and the world's
// seed has moved twice. A walk stops at a status, at its third restart, or after 80
// steps. A pair no check handles (a bad Type) repeats at its second step.
//
// PlotClosestFeatures, when set, has the original build the two placement
// matrices and then use neither: the plot call is compiled out. PrintMatrix
// (retail's 0x0019c160) is a bare `jr ra`.
int32_t vcwitness_vclip(VCWitness *w, bMatrix4 *r1, bVector3 *t1,
                        bMatrix4 *r2, bVector3 *t2)
{
    VCTransformedFeature xf1, xf2;
    VCTransform x12, x21;
    VCFeature *seen1[VC_MAX_ITERATIONS], *seen2[VC_MAX_ITERATIONS];
    int32_t status = 0;
    int32_t restarts = 0;
    int32_t i = 0;

    VClipCalls++;
    if (PrintThisTime) {
        vcpoly_print(w->P1);
        vcpoly_print(w->P2);
    }
    xf1.pFeature = NULL;
    xf2.pFeature = NULL;
    vctransform_init(&x12, r2, t2, r1, t1);
    vctransform_init(&x21, r1, t1, r2, t2);

    for (;;) {
        uint32_t code = (uint32_t)(int32_t)w->F1->Type
            + ((uint32_t)(int32_t)w->F2->Type << 16);

        switch (code) {
        case 0x00000u:
            w->SwitchState = 1;
            vcwitness_print_state(w);
            status = vcwitness_check_vertex_vertex(w, &x12, &x21, &xf1, &xf2);
            break;
        case 0x10000u:
            w->SwitchState = 1;
            vcwitness_print_state(w);
            status = vcwitness_check_vertex_edge(w, &x12, &x21, &xf1, &xf2);
            break;
        case 0x00001u:
            w->SwitchState = 2;
            vcwitness_print_state(w);
            status = vcwitness_check_vertex_edge(w, &x21, &x12, &xf2, &xf1);
            break;
        case 0x20000u:
            w->SwitchState = 1;
            vcwitness_print_state(w);
            status = vcwitness_check_vertex_face(w, &x12, &x21, &xf1, &xf2);
            break;
        case 0x00002u:
            w->SwitchState = 2;
            vcwitness_print_state(w);
            status = vcwitness_check_vertex_face(w, &x21, &x12, &xf2, &xf1);
            break;
        case 0x10001u:
            w->SwitchState = 1;
            vcwitness_print_state(w);
            status = vcwitness_check_edge_edge(w, &x12, &x21, &xf1, &xf2);
            break;
        case 0x20001u:
            w->SwitchState = 1;
            vcwitness_print_state(w);
            status = vcwitness_check_edge_face(w, &x12, &x21, &xf1, &xf2);
            break;
        case 0x10002u:
            w->SwitchState = 2;
            vcwitness_print_state(w);
            status = vcwitness_check_edge_face(w, &x21, &x12, &xf2, &xf1);
            break;
        default:
            break;
        }
        VClipSteps++;
        if (vclip_pair_seen(w, seen1, seen2, i)) {
            restarts++;
            i = 0;
            w->F1 = vclip_random_vertex(w->P1);
            w->F2 = vclip_random_vertex(w->P2);
            VClipRestarts++;
        } else {
            i++;
        }
        if (status != 0 || !(restarts < VC_MAX_RESTARTS)
            || !(i < VC_MAX_ITERATIONS))
            return status;
    }
}

// 0x001c9730. No callers. F1 as one mesh face placed by m1, F2 by m2, each
// on its own object.
void vcwitness_plot_to_caffeine(VCWitness *w, bMatrix4 *m1, bMatrix4 *m2)
{
    // Four corners is all the image's buffer holds; a face with more
    // overruns its frame there. The port's buffer takes any face's corners
    // and the call still passes the first four.
    FloatVector buf[VC_MESH_FACE_CORNERS];

    if (w->pCaffeineObj1 == NULL) {
        w->pCaffeineObj1 = esp_create_object("ClosestFeatures",
                                             "ClosestFeature");
        esp_create_user_mesh(w->pCaffeineObj1, 1);
        w->pCaffeineObj2 = esp_create_object("ClosestFeatures",
                                             "ClosestFeature");
        esp_create_user_mesh(w->pCaffeineObj2, 1);
        if (w->pCaffeineObj1 == NULL)
            return;
    }
    vcfeature_create_user_mesh_face(w->F1, buf, m1);
    esp_set_user_mesh_face(w->pCaffeineObj1, 0, buf);
    esp_set_object_position(w->pCaffeineObj1, (bVector3 *)&m1->v3);
    vcfeature_create_user_mesh_face(w->F2, buf, m2);
    esp_set_user_mesh_face(w->pCaffeineObj2, 0, buf);
    esp_set_object_position(w->pCaffeineObj2, (bVector3 *)&m2->v3);
}

// ---------------------------------------------------------------- features

// 0x001c8548. One plane per edge at the vertex, facing along the edge away
// from the vertex: the edge's direction if the vertex is its head, the
// reverse if it is its tail. Distance measured at the vertex.
void vcvertex_set_voronoi_planes(VCVertex *v)
{
    int32_t i;

    for (i = 0; i < v->Feature.NumPlanes; i++) {
        VCVoronoiPlane *pl = &v->pPlanes[i];
        VCEdge *e = (VCEdge *)pl->Neighbor;
        bVector3 n = edge_dir(e);
        bVector3 p;

        if (e->pPlanes[1].Neighbor != &v->Feature)
            n = zero_minus(&n);
        set_normal(&pl->Plane, &n);
        p = vpos(&v->Feature);
        pl->Plane.CompressedPlaneDistance = dot3(&p, &n);
    }
}

// 0x001c8698. The edge at v, other than `last`, that also bounds `face`.
VCEdge *vcvertex_get_next_edge_in_face(VCVertex *v, VCEdge *last,
                                       VCFace *face)
{
    int32_t i, j, nv = v->Feature.NumPlanes;

    for (i = 0; i < nv; i++) {
        VCFeature *e = v->pPlanes[i].Neighbor;
        int32_t nf;

        if (e == (VCFeature *)last)
            continue;
        nf = face->Feature.NumPlanes;
        for (j = 0; j < nf; j++) {
            if (face->pPlanes[j].Neighbor == e)
                return (VCEdge *)e;
        }
    }
    return NULL;
}

// 0x001c8730.
void vcvertex_move(VCVertex *v, const bVector3 *d)
{
    v->CompressedPosition[0] = v->CompressedPosition[0] + d->x;
    v->CompressedPosition[1] = v->CompressedPosition[1] + d->y;
    v->CompressedPosition[2] = v->CompressedPosition[2] + d->z;
}

// Plane `k` of an edge's region, from the face across it: the reverse of
// that face's plane for this edge, its distance measured at the edge's
// head. Left alone if the face does not list the edge.
static void edge_face_plane(VCEdge *e, int32_t k, const bVector3 *head)
{
    VCVoronoiPlane *pl = &e->pPlanes[k];
    VCFace *face = (VCFace *)pl->Neighbor;
    int32_t i, nf = face->Feature.NumPlanes;

    for (i = 0; i < nf; i++) {
        if (face->pPlanes[i].Neighbor == &e->Feature) {
            bVector3 fn = plane_normal(&face->pPlanes[i].Plane);
            bVector3 n = zero_minus(&fn);

            set_normal(&pl->Plane, &n);
            pl->Plane.CompressedPlaneDistance = dot3(head, &n);
            return;
        }
    }
}

// 0x001c8790. Plane 0 faces along the edge from its tail, plane 1 back
// from its head, and planes 2 and 3 out of the two faces' edge planes.
void vcedge_set_voronoi_planes(VCEdge *e)
{
    VCVoronoiPlane *pl = e->pPlanes;
    bVector3 d = edge_dir(e);
    bVector3 nd = zero_minus(&d);
    bVector3 tail, head;

    set_normal(&pl[0].Plane, &d);
    tail = vpos(pl[0].Neighbor);
    pl[0].Plane.CompressedPlaneDistance = dot3(&tail, &d);
    set_normal(&pl[1].Plane, &nd);
    head = vpos(pl[1].Neighbor);
    pl[1].Plane.CompressedPlaneDistance = dot3(&head, &nd);
    edge_face_plane(e, 2, &head);
    edge_face_plane(e, 3, &head);
}

// 0x001c8b08. One plane per edge around the face: the face normal crossed
// with the edge's direction (vopmula/vopmsub), through the edge's tail, and
// turned round if the next vertex along the face lies behind it. The next
// edge is used without a test for none.
void vcface_set_voronoi_planes(VCFace *f)
{
    int32_t i;

    for (i = 0; i < f->Feature.NumPlanes; i++) {
        VCVoronoiPlane *pl = &f->pPlanes[i];
        VCEdge *e = (VCEdge *)pl->Neighbor;
        VCVertex *tail = (VCVertex *)e->pPlanes[0].Neighbor;
        bVector3 fn = plane_normal(&f->Plane);
        bVector3 d = edge_dir(e);
        bVector3 c, tp, op;
        VCEdge *e2;
        VCFeature *other;

        c.x = fn.y * d.z - d.y * fn.z;
        c.y = fn.z * d.x - d.z * fn.x;
        c.z = fn.x * d.y - d.x * fn.y;
        c.pad = 0.0f;
        set_normal(&pl->Plane, &c);
        tp = vpos(&tail->Feature);
        pl->Plane.CompressedPlaneDistance = dot3(&c, &tp);

        e2 = vcvertex_get_next_edge_in_face(tail, e, f);
        other = e2->pPlanes[0].Neighbor;
        if (other == &tail->Feature)
            other = e2->pPlanes[1].Neighbor;
        op = vpos(other);
        if (plane_dist(&pl->Plane, &op) < 0.0f) {
            bVector3 n = zero_minus(&c);

            set_normal(&pl->Plane, &n);
            pl->Plane.CompressedPlaneDistance = dot3(&n, &tp);
        }
    }
}

// 0x001c8df0.
void vcface_move(VCFace *f, const bVector3 *d)
{
    f->Plane.CompressedPlaneDistance = f->Plane.CompressedPlaneDistance
        + ((d->x * f->Plane.CompressedNormal[0]
            + d->y * f->Plane.CompressedNormal[1])
           + d->z * f->Plane.CompressedNormal[2]);
}

// The transform CreateUserMeshFace gives each corner: bMulMatrixVec3, then
// the translation row taken back off, so the corner is placed relative to
// m's origin and the object's position supplies the rest.
static void mesh_corner(FloatVector *out, const VCFeature *vert,
                        const bMatrix4 *m)
{
    bVector3 v = vpos(vert);

    bMulMatrixVec3(&v, m, &v);
    out->x = v.x - m->v3.x;
    out->y = v.y - m->v3.y;
    out->z = v.z - m->v3.z;
}

// 0x001c92f8. A vertex is one corner, an edge its tail and head, a face
// its vertices in the order its edges first name them. The corners are
// then padded to four by repeating the last. The image gathers a face's
// vertices into eight stack words with no bound; the port's gather holds
// any face's. A feature of no known type has no corners, and the image's
// pad then copies from the word before `out` -- the port pads nothing.
void vcfeature_create_user_mesh_face(VCFeature *f, FloatVector *out,
                                     bMatrix4 *m)
{
    int32_t count = 0;
    int32_t k;

    if (f->Type == VCFEATURE_EDGE) {
        const VCEdge *e = (const VCEdge *)f;

        mesh_corner(&out[0], e->pPlanes[0].Neighbor, m);
        mesh_corner(&out[1], e->pPlanes[1].Neighbor, m);
        count = 2;
    } else if (f->Type == VCFEATURE_VERTEX) {
        mesh_corner(&out[0], f, m);
        count = 1;
    } else if (f->Type == VCFEATURE_FACE) {
        const VCFace *face = (const VCFace *)f;
        const VCFeature *verts[VC_MESH_FACE_CORNERS];
        int32_t nv = 0, i, j, np = face->Feature.NumPlanes;

        for (i = 0; i < np; i++) {
            const VCEdge *e = (const VCEdge *)face->pPlanes[i].Neighbor;
            const VCFeature *head = e->pPlanes[1].Neighbor;
            const VCFeature *tail = e->pPlanes[0].Neighbor;

            for (j = 0; j < nv && verts[j] != tail; j++)
                ;
            if (j == nv)
                verts[nv++] = tail;
            for (j = 0; j < nv && verts[j] != head; j++)
                ;
            if (j == nv)
                verts[nv++] = head;
        }
        for (i = 0; i < face->Feature.NumPlanes; i++)
            mesh_corner(&out[i], verts[i], m);
        count = face->Feature.NumPlanes;
    } else {
        return;
    }
    for (k = count; k < 4; k++)
        out[k] = out[k - 1];
}

// ---------------------------------------------------------------- polyhedron

// 0x001c8e48. Link is left to the bTNode constructor, which is empty.
VCPolyhedron *vcpoly_init(VCPolyhedron *p)
{
    p->MaxVertices = 0;
    p->MaxEdges = 0;
    p->MaxFaces = 0;
    p->MaxPlanes = 0;
    p->DynamicallyAllocated = 1;
    p->NumVertices = 0;
    p->NumEdges = 0;
    p->NumFaces = 0;
    p->NumPlanes = 0;
    p->pVertices = NULL;
    p->pEdges = NULL;
    p->pFaces = NULL;
    p->pPlanes = NULL;
    p->pCaffeineObj = NULL;
    return p;
}

// 0x001c8e90. bMalloc__Fii(n * size, 16) for each array, sized from the
// stored (int16) maxima. The two-argument bMalloc takes no name; the port
// passes one for its own diagnostics.
void vcpoly_init_alloc(VCPolyhedron *p, int32_t max_vertices,
                       int32_t max_edges, int32_t max_faces,
                       int32_t max_planes)
{
    p->NumVertices = 0;
    p->NumEdges = 0;
    p->NumFaces = 0;
    p->NumPlanes = 0;
    p->MaxVertices = (int16_t)max_vertices;
    p->MaxEdges = (int16_t)max_edges;
    p->MaxFaces = (int16_t)max_faces;
    p->MaxPlanes = (int16_t)max_planes;
    p->pVertices = (VCVertex *)bMalloc(
        p->MaxVertices * (int)sizeof(VCVertex), "VCPolyhedron", 0, 16);
    p->pEdges = (VCEdge *)bMalloc(
        p->MaxEdges * (int)sizeof(VCEdge), "VCPolyhedron", 0, 16);
    p->pFaces = (VCFace *)bMalloc(
        p->MaxFaces * (int)sizeof(VCFace), "VCPolyhedron", 0, 16);
    p->pPlanes = (VCVoronoiPlane *)bMalloc(
        p->MaxPlanes * (int)sizeof(VCVoronoiPlane), "VCPolyhedron", 0, 16);
    p->DynamicallyAllocated = 1;
}

// 0x001c8f48. Arrays the caller owns.
void vcpoly_init_arrays(VCPolyhedron *p, VCVertex *vertices,
                        int32_t max_vertices, VCEdge *edges,
                        int32_t max_edges, VCFace *faces, int32_t max_faces,
                        VCVoronoiPlane *planes, int32_t max_planes)
{
    p->MaxVertices = (int16_t)max_vertices;
    p->MaxEdges = (int16_t)max_edges;
    p->MaxFaces = (int16_t)max_faces;
    p->MaxPlanes = (int16_t)max_planes;
    p->pVertices = vertices;
    p->pEdges = edges;
    p->pFaces = faces;
    p->pPlanes = planes;
    p->DynamicallyAllocated = 0;
    p->NumVertices = 0;
    p->NumEdges = 0;
    p->NumFaces = 0;
    p->NumPlanes = 0;
}

// 0x001c8f88. Close, then the bTNode destructor (0x001ca000), which frees
// the node when told to.
void vcpoly_destroy(VCPolyhedron *p, int32_t flags)
{
    vcpoly_close(p);
    if (flags & 1)
        bFree(p);
}

// 0x001c8fc0. __builtin_vec_delete for each array that is there; all four
// pointers are cleared either way.
void vcpoly_close(VCPolyhedron *p)
{
    if (p->DynamicallyAllocated) {
        if (p->pVertices != NULL)
            bFree(p->pVertices);
        if (p->pEdges != NULL)
            bFree(p->pEdges);
        if (p->pFaces != NULL)
            bFree(p->pFaces);
        if (p->pPlanes != NULL)
            bFree(p->pPlanes);
        p->pVertices = NULL;
        p->pEdges = NULL;
        p->pFaces = NULL;
        p->pPlanes = NULL;
        p->DynamicallyAllocated = 0;
    }
    if (p->pCaffeineObj != NULL) {
        esp_delete_object(p->pCaffeineObj);
        p->pCaffeineObj = NULL;
    }
}

// 0x001c9068. A loaded image: the arrays full, each pointer an index.
void vcpoly_memory_image_load(VCPolyhedron *p, VCVertex *vertices,
                              int32_t num_vertices, VCEdge *edges,
                              int32_t num_edges, VCFace *faces,
                              int32_t num_faces, VCVoronoiPlane *planes,
                              int32_t num_planes)
{
    vcpoly_init_arrays(p, vertices, num_vertices, edges, num_edges, faces,
                       num_faces, planes, num_planes);
    p->NumVertices = (int16_t)num_vertices;
    p->NumEdges = (int16_t)num_edges;
    p->NumFaces = (int16_t)num_faces;
    p->NumPlanes = (int16_t)num_planes;
    vcpoly_convert_to_pointers(p);
}

// 0x001c90d8.
void vcpoly_memory_image_unload(VCPolyhedron *p)
{
    vcpoly_close(p);
}

// 0x001c90e0. n planes off the end of the pool, each facing +z at the
// origin with no neighbour. Padding is not written. n <= 0 still answers
// the slot it would have started at.
VCVoronoiPlane *vcpoly_new_voronoi_planes(VCPolyhedron *p, int32_t n)
{
    VCVoronoiPlane *r;
    int32_t i;

    if (p->MaxPlanes < p->NumPlanes + n)
        return NULL;
    r = &p->pPlanes[p->NumPlanes];
    p->NumPlanes = (int16_t)(p->NumPlanes + n);
    for (i = 0; i < n; i++) {
        r[i].Plane.CompressedNormal[0] = 0.0f;
        r[i].Plane.CompressedNormal[1] = 0.0f;
        r[i].Plane.CompressedNormal[2] = 1.0f;
        r[i].Neighbor = NULL;
        r[i].Plane.CompressedPlaneDistance = 0.0f;
    }
    return r;
}

// 0x001c9178.
VCVertex *vcpoly_new_vertex(VCPolyhedron *p, const bVector3 *pos,
                            int32_t n, VCVoronoiPlane *planes)
{
    VCVertex *v;

    if (!(p->NumVertices < p->MaxVertices))
        return NULL;
    v = &p->pVertices[p->NumVertices];
    p->NumVertices = (int16_t)(p->NumVertices + 1);
    v->Feature.Type = VCFEATURE_VERTEX;
    v->pPlanes = planes;
    v->CompressedPosition[0] = pos->x;
    v->CompressedPosition[1] = pos->y;
    v->CompressedPosition[2] = pos->z;
    v->Feature.NumPlanes = (int8_t)n;
    return v;
}

// 0x001c91e0. The direction in units of 2^-13, by cvt.w.s -- which the EE
// truncates.
VCEdge *vcpoly_new_edge(VCPolyhedron *p, const bVector3 *dir, int32_t n,
                        VCVoronoiPlane *planes)
{
    VCEdge *e;

    if (!(p->NumEdges < p->MaxEdges))
        return NULL;
    e = &p->pEdges[p->NumEdges];
    p->NumEdges = (int16_t)(p->NumEdges + 1);
    e->Feature.Type = VCFEATURE_EDGE;
    e->pPlanes = planes;
    e->CompressedDirection[0] =
        (int16_t)ee_trunc_w(dir->x * VC_DIRECTION_UNSCALE);
    e->CompressedDirection[1] =
        (int16_t)ee_trunc_w(dir->y * VC_DIRECTION_UNSCALE);
    e->CompressedDirection[2] =
        (int16_t)ee_trunc_w(dir->z * VC_DIRECTION_UNSCALE);
    e->Feature.NumPlanes = (int8_t)n;
    return e;
}

// 0x001c9288.
VCFace *vcpoly_new_face(VCPolyhedron *p, const bVector3 *normal, float d,
                        int32_t n, VCVoronoiPlane *planes)
{
    VCFace *f;

    if (!(p->NumFaces < p->MaxFaces))
        return NULL;
    f = &p->pFaces[p->NumFaces];
    p->NumFaces = (int16_t)(p->NumFaces + 1);
    f->Feature.Type = VCFEATURE_FACE;
    f->pPlanes = planes;
    f->Plane.CompressedNormal[0] = normal->x;
    f->Plane.CompressedNormal[1] = normal->y;
    f->Plane.CompressedNormal[2] = normal->z;
    f->Plane.CompressedPlaneDistance = d;
    f->Feature.NumPlanes = (int8_t)n;
    return f;
}

// 0x001c9650. No callers. One mesh face per face, placed by m. The mesh
// is sized before the object is tested, as in the image.
void vcpoly_plot_to_caffeine(VCPolyhedron *p, bMatrix4 *m)
{
    FloatVector buf[VC_MESH_FACE_CORNERS];   // see vcwitness_plot_to_caffeine
    int32_t i;

    if (p->pCaffeineObj == NULL) {
        p->pCaffeineObj = esp_create_object("VCPolyhedrons", "VCPolyhedron");
        esp_create_user_mesh(p->pCaffeineObj, p->NumFaces);
        if (p->pCaffeineObj == NULL)
            return;
    }
    for (i = 0; i < p->NumFaces; i++) {
        vcfeature_create_user_mesh_face(&p->pFaces[i].Feature, buf, m);
        esp_set_user_mesh_face(p->pCaffeineObj, i, buf);
    }
    esp_set_object_position(p->pCaffeineObj, (bVector3 *)&m->v3);
}

// 0x001c9830. Vertices, then faces, then edges: an edge's face planes are
// built from its faces' edge planes, so faces must come first.
void vcpoly_set_voronoi_planes(VCPolyhedron *p)
{
    int32_t i;

    for (i = 0; i < p->NumVertices; i++)
        vcvertex_set_voronoi_planes(&p->pVertices[i]);
    for (i = 0; i < p->NumFaces; i++)
        vcface_set_voronoi_planes(&p->pFaces[i]);
    for (i = 0; i < p->NumEdges; i++)
        vcedge_set_voronoi_planes(&p->pEdges[i]);
}

// 0x001c98f0. (index << 4) | type. The image divides the byte offset by
// the record size with a multiply by the inverse, which is exact for a
// feature in its array.
uint32_t vcpoly_get_feature_code(VCPolyhedron *p, VCFeature *f)
{
    if (f == NULL)
        return VC_NO_FEATURE;
    switch (f->Type) {
    case VCFEATURE_VERTEX:
        return ((uint32_t)((VCVertex *)f - p->pVertices) << 4)
            | VCFEATURE_VERTEX;
    case VCFEATURE_EDGE:
        return ((uint32_t)((VCEdge *)f - p->pEdges) << 4) | VCFEATURE_EDGE;
    case VCFEATURE_FACE:
        return ((uint32_t)((VCFace *)f - p->pFaces) << 4) | VCFEATURE_FACE;
    default:
        return VC_NO_FEATURE;
    }
}

// 0x001c99a8.
VCFeature *vcpoly_get_feature(VCPolyhedron *p, uint32_t code)
{
    uint32_t idx;

    if (code == VC_NO_FEATURE)
        return NULL;
    idx = code >> 4;
    switch (code & 0xfu) {
    case VCFEATURE_VERTEX:
        return &p->pVertices[idx].Feature;
    case VCFEATURE_EDGE:
        return &p->pEdges[idx].Feature;
    case VCFEATURE_FACE:
        return &p->pFaces[idx].Feature;
    default:
        return NULL;
    }
}

// A plane pointer as the index it is stored as, and back. The index fills
// the pointer's field; on the handheld that is the image's word exactly.
static VCVoronoiPlane *plane_index(const VCPolyhedron *p,
                                   const VCVoronoiPlane *pl)
{
    intptr_t d = (intptr_t)((uintptr_t)pl - (uintptr_t)p->pPlanes);

    return (VCVoronoiPlane *)(uintptr_t)(uint32_t)(int32_t)
        (d / (intptr_t)sizeof(VCVoronoiPlane));
}

static VCVoronoiPlane *plane_pointer(const VCPolyhedron *p,
                                     const VCVoronoiPlane *idx)
{
    return &p->pPlanes[(int32_t)(uint32_t)(uintptr_t)idx];
}

// 0x001c9a28. The vertex, edge and face counts are read once, before any
// loop; the plane loop reads NumPlanes each time round.
void vcpoly_convert_to_indicies(VCPolyhedron *p)
{
    int32_t nv = p->NumVertices, ne = p->NumEdges, nf = p->NumFaces;
    int32_t i;

    for (i = 0; i < nv; i++)
        p->pVertices[i].pPlanes = plane_index(p, p->pVertices[i].pPlanes);
    for (i = 0; i < ne; i++)
        p->pEdges[i].pPlanes = plane_index(p, p->pEdges[i].pPlanes);
    for (i = 0; i < nf; i++)
        p->pFaces[i].pPlanes = plane_index(p, p->pFaces[i].pPlanes);
    for (i = 0; i < p->NumPlanes; i++) {
        uint32_t code = vcpoly_get_feature_code(p, p->pPlanes[i].Neighbor);

        p->pPlanes[i].Neighbor = (VCFeature *)(uintptr_t)code;
    }
}

// 0x001c9bb0. The same four loops the other way.
void vcpoly_convert_to_pointers(VCPolyhedron *p)
{
    int32_t nv = p->NumVertices, ne = p->NumEdges, nf = p->NumFaces;
    int32_t i;

    for (i = 0; i < nv; i++)
        p->pVertices[i].pPlanes = plane_pointer(p, p->pVertices[i].pPlanes);
    for (i = 0; i < ne; i++)
        p->pEdges[i].pPlanes = plane_pointer(p, p->pEdges[i].pPlanes);
    for (i = 0; i < nf; i++)
        p->pFaces[i].pPlanes = plane_pointer(p, p->pFaces[i].pPlanes);
    for (i = 0; i < p->NumPlanes; i++) {
        uint32_t code = (uint32_t)(uintptr_t)p->pPlanes[i].Neighbor;

        p->pPlanes[i].Neighbor = vcpoly_get_feature(p, code);
    }
}

// ---------------------------------------------------------------- print

// 0x001c9d18.
void vcpoly_print_feature(VCPolyhedron *p, VCFeature *f)
{
    (void)p;
    (void)f;
}

// 0x001c9d20. Everything below prints nothing; what survives is the walk
// and the one store.
void vcpoly_print(VCPolyhedron *p)
{
    int32_t i;

    pPrintingPolygon = p;
    for (i = 0; i < p->NumVertices; i++) {
        vcpoly_print_feature(p, &p->pVertices[i].Feature);
        vcvertex_print(&p->pVertices[i]);
    }
    for (i = 0; i < p->NumEdges; i++) {
        vcpoly_print_feature(p, &p->pEdges[i].Feature);
        vcedge_print(&p->pEdges[i]);
    }
    for (i = 0; i < p->NumFaces; i++) {
        vcpoly_print_feature(p, &p->pFaces[i].Feature);
        vcface_print(&p->pFaces[i]);
    }
}

// 0x001c9e38.
void vcvoronoiplane_print(VCVoronoiPlane *p)
{
    vcpoly_print_feature(pPrintingPolygon, p->Neighbor);
}

// 0x001c9e70.
void vcvertex_print(VCVertex *v)
{
    int32_t i;

    for (i = 0; i < v->Feature.NumPlanes; i++)
        vcvoronoiplane_print(&v->pPlanes[i]);
}

// 0x001c9ee8. An edge's four planes, whatever its NumPlanes says.
void vcedge_print(VCEdge *e)
{
    vcvoronoiplane_print(&e->pPlanes[0]);
    vcvoronoiplane_print(&e->pPlanes[1]);
    vcvoronoiplane_print(&e->pPlanes[2]);
    vcvoronoiplane_print(&e->pPlanes[3]);
}

// 0x001c9f88.
void vcface_print(VCFace *f)
{
    int32_t i;

    for (i = 0; i < f->Feature.NumPlanes; i++)
        vcvoronoiplane_print(&f->pPlanes[i]);
}
