// carrender -- CarRenderInfo::Render and what it calls: see carrenderinfo.h.

#include "carrenderinfo.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "bmatrix.h"
#include "cardriver.h"
#include "collisionbody.h"
#include "eframe.h"
#include "emath.h"
#include "gameflow.h"
#include "realtime.h"
#include "scenerycull.h"
#include "sun.h"
#include "topology.h"
#include "track.h"
#include "trackflow.h"

bMatrix4 CarRenderMatrix = {
    { 1.0f, 0.0f, 0.0f, 0.0f }, { 0.0f, 1.0f, 0.0f, 0.0f },
    { 0.0f, 0.0f, 1.0f, 0.0f }, { 0.0f, 0.0f, 0.0f, 1.0f },
};

int32_t EnableEnvMap = 1;
int32_t PrintQueryLightMat;
int32_t QueryLightMat;
int32_t CarPartCullerNormalise;
int32_t ForceHeadlights;
int32_t ForceBrakelights;
int32_t ForceReverselights;
int32_t ForceCoplights;
int32_t ForceRenderDriver;
int32_t ForceCarLOD = -1;
int32_t ForceTireLOD = -1;

float FancyCarShadowEdgeMult = 1.1f;
float CarShadowElevationFE = 0.01f;

uint8_t CopLightsHeadlights[16] = { 1, 1, 1, 1, 1, 1, 1, 1,
                                    0, 0, 0, 0, 0, 0, 0, 0 };
uint8_t CopLightsRed[8]   = { 1, 1, 1, 1, 0, 0, 0, 0 };
uint8_t CopLightsBlue[8]  = { 0, 0, 1, 1, 1, 1, 0, 0 };
uint8_t CopLightsWhite[8] = { 1, 1, 1, 1, 0, 0, 0, 0 };
uint8_t CopLightsRedSlow[16]   = { 1, 1, 0, 0, 0, 0, 0, 0,
                                   1, 1, 0, 0, 0, 0, 0, 0 };
uint8_t CopLightsBlueSlow[16]  = { 0, 0, 0, 0, 0, 0, 1, 1,
                                   0, 0, 0, 0, 0, 0, 1, 1 };
uint8_t CopLightsWhiteSlow[16] = { 0, 0, 1, 1, 0, 0, 0, 0,
                                   0, 0, 1, 1, 0, 0, 0, 0 };

const float CarLodPixelSizes[4] = { 120.0f, 45.0f, 20.0f, 0.0f };

float     cs_OneOverZ;
bVector3  cs_lightV;
bVector3  hull_Normal;
bVector3  hull_Origin;
bVector3  hullVertArray3[3 * HULL_MAX_POINTS];
bVector3  hullVertArray2[HULL_MAX_POINTS];
bVector3  hullVertArray1[HULL_MAX_POINTS];
bVector3 *hullVertPointers[HULL_MAX_POINTS + 1];

eStripFns gEStripFns;
eStripFns gExStripFns;
void (*gERenderLightFlareFn)(eView *view, eLightFlare *flare,
                             bMatrix4 *local_world, float intensity);
void (*gAnimatedDriverRenderFn)(AnimatedDriver *d, bMatrix4 *m,
                                eLightContext *lc, uint32_t flags,
                                int32_t lod);
int32_t (*gAnimatedDriverQueuedFn)(AnimatedDriver *d);

// 0x002ace08: the wheel nearest each of the grid shadow's sixteen points,
// whose ground the point borrows when it finds none of its own.
static const int32_t kGridNearestWheel[16] = {
    2, 2, 1, 1, 2, 2, 1, 1, 3, 3, 0, 0, 3, 3, 0, 0,
};

// bStringHash of the flares' names.
#define HASH_FLARE_HEADLIGHT_LEFT     0xacec665cu
#define HASH_FLARE_HEADLIGHT_RIGHT    0x4ae7f96fu
#define HASH_FLARE_BRAKELIGHT_LEFT    0x7efcf06fu
#define HASH_FLARE_BRAKELIGHT_MIDDLE  0x34970013u
#define HASH_FLARE_BRAKELIGHT_RIGHT   0x5f09c5e2u
#define HASH_FLARE_REVERSELIGHT_LEFT  0xbea9aee6u
#define HASH_FLARE_REVERSELIGHT_RIGHT 0x944e5339u
#define HASH_HEADLIGHT_LEFT           0xa7e6ea53u
#define HASH_HEADLIGHT_RIGHT          0xa532fc46u
#define HASH_COPLIGHTRED              0x1e4150b4u
#define HASH_COPLIGHTBLUE             0xe662c161u
#define HASH_COPLIGHTWHITE            0xb4348dbau
// CARSKIN, the light material the body, the mirrors and the dash share.
#define HASH_CARSKIN                  0xd6d6080au

// ------------------------------------------------------------- helpers

static int in_front_end(void)
{
    return gTrackFlowGameFlow != NULL
        && gTrackFlowGameFlow->current == BGF_IN_FRONTEND;
}

// TimeOfDay 2, 4 or 3: the three with the lights on.
static int lights_on_time_of_day(void)
{
    int16_t t;

    if (CurrentTrackInfo == NULL)
        return 0;
    t = CurrentTrackInfo->TimeOfDay;
    return t == 2 || t == 4 || t == 3;
}

// eModel::Render, through the seam.
static void model_render(eModel *m, bMatrix4 *matrix, void *light,
                         uint32_t flags)
{
    if (gEModelRenderFn != NULL)
        gEModelRenderFn(m, matrix, light, flags);
}

// eModel::ReplaceLightMaterial(unsigned int, eLightMaterial *), 0x0010caa0:
// a jump to the solid's, when there is one.
static void model_replace_light_material(eModel *m, uint32_t old_hash,
                                         void *material)
{
    if (m->Solid != NULL)
        esolid_replace_light_material(m->Solid, old_hash, material);
}

static void set_up_light_context(eLightContext *lc, const bMatrix4 *m,
                                 const bMatrix4 *hack, const bVector4 *eye,
                                 eView *view)
{
    if (gElSetupLightContextFn != NULL)
        gElSetupLightContextFn(lc, m, hack, eye, view);
}

static int32_t strip_begin(const eStripFns *s, void *texture, int32_t n,
                           bMatrix4 *m)
{
    return s->Begin != NULL ? s->Begin(texture, n, m) : 0;
}

static void strip_vertex(const eStripFns *s, const bVector3 *v)
{
    if (s->AddVertex != NULL)
        s->AddVertex(v);
}

static void strip_colour(const eStripFns *s, uint32_t c)
{
    if (s->AddColour != NULL)
        s->AddColour(c);
}

static void strip_uv(const eStripFns *s, float u, float v)
{
    if (s->AddUV != NULL)
        s->AddUV(u, v);
}

static void strip_end(const eStripFns *s)
{
    if (s->End != NULL)
        s->End();
}

// 0x00124d38 on the car's damage: item i's level, the two bits at 2i.
static uint32_t item_level(const CarDamage *cd, int32_t item)
{
    return (cd->BreakableCarItemDamageAmounts >> (2 * item)) & 3;
}

// The two lanes' dot, VU0's vmul.xyz, vaddy.x, vaddz.x.
static float dot3(const bVector3 *a, const bVector3 *b)
{
    return (a->x * b->x + a->y * b->y) + a->z * b->z;
}

// The word at +100 of the animated driver, which is not ported: nonzero
// and the driver is not drawn.
static int32_t animated_driver_hidden(const AnimatedDriver *d)
{
    int32_t w;

    memcpy(&w, (const uint8_t *)d + 100, sizeof w);
    return w;
}

// -------------------------------------------------- the light textures

void carrenderinfo_update_light_state_textures(CarRenderInfo *ri)
{
    const UsedCarTextureInfo *u = &ri->UsedTextureInfos;
    eReplacementTextureTable *t = ri->DamageableSkinReplacementTextureTable;
    Car     *car = ri->pCar;
    int      night = lights_on_time_of_day();
    uint32_t frame = ri->CarTimebaseStart + (uint32_t)WorldTimeFrames;
    int      changed = 0;
    int32_t  left, right, brake;
    uint32_t h;

    // A cop's headlights wig-wag while its lights are on, the right out of
    // step with the left.
    left = right = 0;
    if (car != NULL) {
        int32_t on = car->HeadlightsState;

        if (car->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)
            on ^= 1;
        if (on) {
            left = right = 1;
        } else if (car->CopLights != 0) {
            int wig = CopLightsHeadlights[frame & 15] != 0;

            left = wig;
            right = !wig;
        }
    }
    if (night || ForceHeadlights)
        left = right = 1;

    // Entry 2 is the broken lamp's: an entry showing it is left alone.
    h = u->ReplaceHeadlightHash[left];
    if (t[8].NewNameHash != u->ReplaceHeadlightHash[2]
        && t[8].NewNameHash != h) {
        t[8].NewNameHash = h;
        changed = 1;
    }
    h = u->ReplaceHeadlightHash[right];
    if (t[9].NewNameHash != u->ReplaceHeadlightHash[2]
        && t[9].NewNameHash != h) {
        t[9].NewNameHash = h;
        changed = 1;
    }

    brake = ForceBrakelights
         || (car != NULL && car->pCarDriver != NULL
             && 0.05f < car->pCarDriver->Brake);
    h = u->ReplaceBrakelightHash[brake];
    if (t[10].NewNameHash != u->ReplaceBrakelightHash[2]
        && t[10].NewNameHash != h) {
        t[10].NewNameHash = h;
        changed = 1;
    }
    if (t[11].NewNameHash != u->ReplaceBrakelightHash[2]
        && t[11].NewNameHash != h) {
        t[11].NewNameHash = h;
        changed = 1;
    }

    if (changed) {
        emodel_reconnect_texture_table(&ri->Body[0]);
        emodel_reconnect_texture_table(&ri->Body[1]);
        emodel_reconnect_texture_table(&ri->Body[2]);
    }
}

float carrenderinfo_calculate_tire_blur(const CarRenderInfo *ri,
                                        int32_t wheel)
{
    float b;

    if (ri->pCar == NULL)
        return 0.0f;
    // max.s with 0, then min.s with 1.
    b = fabsf(ri->pCar->State.WheelAngularVelocity[wheel]) * 0.02f;
    if (b < 0.0f)
        b = 0.0f;
    if (1.0f < b)
        b = 1.0f;
    return b;
}

// ------------------------------------------------------------ the culler

void carrenderinfo_cull_parts(CarPartCullerPart *culler, const bVector3 *eye)
{
    int32_t i, k;

    for (i = 0; i < NUM_CULLABLE_CAR_PARTS; i++) {
        const CarPartCullInfo *info = &CarPartCullInfoTable[i];
        CarPartCullerPart *part = &culler[i];
        int32_t n = info->NumPlanes;
        uint32_t seen = 1;

        if (n > 0) {
            bVector3 d;
            const float *extra = &info->Extra.x;

            d.x = eye->x - part->Point.x;
            d.y = eye->y - part->Point.y;
            d.z = eye->z - part->Point.z;
            d.pad = eye->pad - part->Point.w;

            if (info->Flag8 == 0 || info->Flag8 == 1) {
                // Flag8 0: seen from any plane's back; 1: from all of
                // theirs. The loop leaves on the first that decides.
                seen = info->Flag8 == 0 ? 0 : 1;
                for (k = 0; k < n; k++) {
                    bVector3 p;
                    float s;

                    p.x = info->Planes[k].x;
                    p.y = info->Planes[k].y;
                    p.z = info->Planes[k].z;
                    p.pad = info->Planes[k].w;
                    if (CarPartCullerNormalise) {
                        float r = 1.0f / sqrtf(dot3(&p, &p));

                        p.x *= r;
                        p.y *= r;
                        p.z *= r;
                        p.pad *= r;
                    }
                    s = dot3(&d, &p) - extra[k];
                    if (info->Flag8 == 0) {
                        if (s < 0.0f) {
                            seen = 1;
                            break;
                        }
                    } else if (0.0f <= s) {
                        seen = 0;
                        break;
                    }
                }
            }
        }
        part->State[2] = seen;
        if (seen)
            part->State[1]++;
        else
            part->State[0]++;
    }
}

// ------------------------------------------------------ the hull shadow

void car_shadow_setup(const bVector3 *pos)
{
    float sx, sy, sz, s, c, len;
    int32_t a;

    if (SunInfo == NULL) {
        sx = -16384.0f;
        sy = 0.0f;
        sz = 7000.0f;
    } else {
        sx = SunInfo->CarShadowPositionX;
        sy = SunInfo->CarShadowPositionY;
        sz = SunInfo->CarShadowPositionZ;
    }
    // The fourth lane is the position's less a word of the stack retail
    // never writes; nothing reads it.
    cs_lightV.x = pos->x - sx;
    cs_lightV.y = pos->y - sy;
    cs_lightV.z = pos->z - sz;
    cs_lightV.pad = pos->pad;

    a = bATan(sqrtf(cs_lightV.x * cs_lightV.x + cs_lightV.y * cs_lightV.y),
              -cs_lightV.z);
    if ((uint32_t)a < 4600u) {
        float x = cs_lightV.x, y, f;

        bSinCos(&s, &c, 4600);
        len = sqrtf(dot3(&cs_lightV, &cs_lightV));
        cs_lightV.z = -len * s;
        y = cs_lightV.y;
        f = fabsf(x) + fabsf(y);
        cs_lightV.y = ((y / f) * len) * c;
        cs_lightV.x = ((x / f) * len) * c;
    }
    cs_OneOverZ = cs_lightV.z == 0.0f ? 0.0f : 1.0f / cs_lightV.z;
}

// cmpl, 0x001207a8: by x rising, then y falling.
static int cmp_low(const void *pa, const void *pb)
{
    const bVector3 *a = *(bVector3 *const *)pa;
    const bVector3 *b = *(bVector3 *const *)pb;
    float d = a->x - b->x;

    if (0.0f < d)
        return 1;
    if (d < 0.0f)
        return -1;
    d = b->y - a->y;
    if (0.0f < d)
        return 1;
    if (d < 0.0f)
        return -1;
    return 0;
}

// cmph, 0x00120828: cmpl the other way round.
static int cmp_high(const void *pa, const void *pb)
{
    return cmp_low(pb, pa);
}

// make_chain, 0x00120850: V sorted, then the chain kept in V[0..s].
static int32_t make_chain(bVector3 **V, int32_t n,
                          int (*cmp)(const void *, const void *))
{
    int32_t i, j, s = 1;

    qsort(V, (size_t)n, sizeof *V, cmp);
    for (i = 2; i < n; i++) {
        bVector3 *t;

        for (j = s; j >= 1; j--) {
            const bVector3 *vi = V[i], *vj = V[j], *vk = V[j - 1];

            if (!((vi->x - vj->x) * (vk->y - vj->y)
                  - (vi->y - vj->y) * (vk->x - vj->x) <= 0.0f))
                break;
        }
        s = j + 1;
        t = V[s];
        V[s] = V[i];
        V[i] = t;
    }
    return s;
}

int32_t car_shadow_ch2d(bVector3 **P, int32_t n)
{
    int32_t u = make_chain(P, n, cmp_low);

    P[n] = P[0];
    return u + make_chain(P + u, n - u + 1, cmp_high);
}

void car_shadow_convex_hull(bVector3 *pts, int32_t *count,
                            TopologyCoordinate *tc, float z, float lift)
{
    bVector3 *out = hullVertArray2;
    int32_t i, n, dropped = 0;

    for (i = 0; i < *count; i++)
        hullVertPointers[i] = &pts[i];
    n = car_shadow_ch2d(hullVertPointers, *count);
    *count = n;

    for (i = 0; i < n; i++) {
        int32_t found;
        float e;

        out->x = hullVertPointers[i]->x;
        out->y = hullVertPointers[i]->y;
        out->z = z;
        e = topology_get_elevation(tc, out, NULL, NULL, &found) + lift;
        out->z = e;
        if (found && fabsf(e - z) <= 4.0f) {
            bVector3 d;
            float s;

            d.x = out->x - hull_Origin.x;
            d.y = out->y - hull_Origin.y;
            d.z = out->z - hull_Origin.z;
            s = dot3(&d, &hull_Normal);
            if (s < 0.0f)
                s = -s;
            if (s < 1.5f) {
                out++;
                continue;
            }
        }
        dropped++;
    }
    *count = n - dropped;
}

int32_t car_shadow_smooth_corners(int32_t n)
{
    const bVector3 *h = hullVertArray2;
    bVector3 *sm = hullVertArray3;
    bVector3 e[2];
    int32_t i, out = 0;

    if (n <= 0)
        return 0;
    // e[1] starts as the edge into corner 0; the two swap as they go.
    e[1].x = (h[0].x - h[n - 1].x) * 0.333f;
    e[1].y = (h[0].y - h[n - 1].y) * 0.333f;
    e[1].z = (h[0].z - h[n - 1].z) * 0.333f;
    e[1].pad = (h[0].pad - h[n - 1].pad) * 0.333f;
    for (i = 0; i < n; i++) {
        int32_t j = i + 1 == n ? 0 : i + 1;
        bVector3 *cur = &e[i & 1];
        const bVector3 *prev = &e[(i & 1) ^ 1];
        bVector3 d;

        cur->x = (h[j].x - h[i].x) * 0.333f;
        cur->y = (h[j].y - h[i].y) * 0.333f;
        cur->z = (h[j].z - h[i].z) * 0.333f;
        cur->pad = (h[j].pad - h[i].pad) * 0.333f;
        d.x = cur->x - prev->x;
        d.y = cur->y - prev->y;
        d.z = cur->z - prev->z;
        d.pad = cur->pad - prev->pad;

        sm[out].x = h[i].x - prev->x;
        sm[out].y = h[i].y - prev->y;
        sm[out].z = h[i].z - prev->z;
        sm[out].pad = h[i].pad - prev->pad;
        sm[out + 2].x = h[i].x + cur->x;
        sm[out + 2].y = h[i].y + cur->y;
        sm[out + 2].z = h[i].z + cur->z;
        sm[out + 2].pad = h[i].pad + cur->pad;
        sm[out + 1].x = d.x * 0.333f + h[i].x;
        sm[out + 1].y = d.y * 0.333f + h[i].y;
        sm[out + 1].z = d.z * 0.333f + h[i].z;
        sm[out + 1].pad = d.pad * 0.333f + h[i].pad;
        out += 3;
    }
    return out;
}

// The hull shadow's soft edge: p pushed out from the centre by the
// multiplier, x and y only.
static void shadow_edge_point(bVector3 *o, const bVector3 *p,
                              const bVector3 *c)
{
    float k = FancyCarShadowEdgeMult;

    o->x = k * (p->x - c->x) + c->x;
    o->y = k * (p->y - c->y) + c->y;
    o->z = p->z;
    o->pad = 0.0f;
}

static void shadow_edge_pair(const bVector3 *p, const bVector3 *c,
                             uint32_t colour)
{
    bVector3 l;

    shadow_edge_point(&l, p, c);
    strip_vertex(&gExStripFns, p);
    strip_vertex(&gExStripFns, &l);
    strip_colour(&gExStripFns, colour);
    strip_colour(&gExStripFns, colour);
    strip_uv(&gExStripFns, 0.155f, 0.0f);
    strip_uv(&gExStripFns, 1.0f, 0.0f);
}

// The hull shadow, in game: the collision body's points, shrunk a little
// and lifted, cast along the light onto the car's plane, their hull laid
// on the ground, its corners cut, and a fan of quads from the centre with
// a soft edge round it in three strips.
static void render_hull_shadow(CarRenderInfo *ri, const bVector3 *position,
                               const bMatrix4 *local_world,
                               bMatrix4 *biased_identity,
                               const eLightContext *light_context,
                               CarCollisionBody *colbody,
                               TopologyCoordinate *topo, float size,
                               int32_t body_lod)
{
    const VCPolyhedron *poly = colbody->Dynamic.Body.pPoly;
    const VCVertex *v = poly->pVertices;
    int32_t count = poly->NumVertices;
    int32_t i, n, seg, first, a;
    float k, alpha, s;
    uint32_t colour;
    bVector3 centre;

    // Retail takes the solid's bounding box through local_world here and
    // never reads it; the port leaves it out.
    if (count > HULL_MAX_POINTS)
        count = HULL_MAX_POINTS;
    car_shadow_setup(position);
    k = cs_OneOverZ;
    for (i = 0; i < count; i++) {
        bVector3 q, p;
        float h;

        q.x = v[i].CompressedPosition[0] * 0.85f;
        q.y = v[i].CompressedPosition[1] * 0.85f;
        q.z = (v[i].CompressedPosition[2] + 0.275f) * 1.0f;
        q.pad = 0.0f;
        bMulMatrixVec3(&p, local_world, &q);
        h = 0.0f + (0.0f - (p.z - position->z)) * k;
        hullVertArray1[i].x = p.x + h * cs_lightV.x;
        hullVertArray1[i].y = p.y + h * cs_lightV.y;
    }

    car_shadow_convex_hull(hullVertArray1, &count, topo,
                           hull_Origin.z + 0.06f, 0.06f);
    count = car_shadow_smooth_corners(count);
    if (count < 3)
        return;

    {
        const bVector3 *a0 = &hullVertArray3[0];
        const bVector3 *a1 = &hullVertArray3[count / 2];

        centre.x = (a1->x + a0->x) * 0.5f;
        centre.y = (a1->y + a0->y) * 0.5f;
        centre.z = (a1->z + a0->z) * 0.5f;
        centre.pad = (a1->pad + a0->pad) * 0.5f;
    }

    // Faint to none with the sun low, and wider.
    s = light_context->SunlightIntensity;
    alpha = 90.0f;
    if (s < 0.4f) {
        FancyCarShadowEdgeMult = 1.4f;
        alpha = 0.0f;
    } else if (1.0f < s) {
        FancyCarShadowEdgeMult = 1.1f;
    } else {
        float f = (s - 0.4f) / 0.6f;

        FancyCarShadowEdgeMult = f * -0.29999995f + 1.4f;
        alpha = f * alpha;
    }
    // At the last level with a body, faded out towards the next.
    if (body_lod == 2) {
        float f = (size - CarLodPixelSizes[2])
                / (CarLodPixelSizes[1] - CarLodPixelSizes[2]);

        if (1.0f < f)
            f = 1.0f;
        else if (f < 0.0f)
            f = 0.0f;
        alpha *= f;
    }
    a = (int32_t)alpha;
    if (!(a < 256))
        a = 255;
    colour = (uint32_t)a << 24 | 0x808080u;

    for (i = 0; i < (count & ~1) - 1; i += 2) {
        if (!strip_begin(&gEStripFns, ri->ShadowRampTexture, 4,
                         biased_identity))
            continue;
        strip_vertex(&gEStripFns, &hullVertArray3[i]);
        strip_vertex(&gEStripFns, &centre);
        strip_vertex(&gEStripFns, &hullVertArray3[i + 1]);
        strip_vertex(&gEStripFns, &hullVertArray3[(i + 2) % count]);
        strip_colour(&gEStripFns, colour);
        strip_colour(&gEStripFns, colour);
        strip_colour(&gEStripFns, colour);
        strip_colour(&gEStripFns, colour);
        strip_uv(&gEStripFns, 0.155f, 0.0f);
        strip_uv(&gEStripFns, 0.0f, 0.0f);
        strip_uv(&gEStripFns, 0.155f, 0.0f);
        strip_uv(&gEStripFns, 0.155f, 0.0f);
        strip_end(&gEStripFns);
    }
    if ((count & 1)
        && strip_begin(&gEStripFns, ri->ShadowRampTexture, 3,
                       biased_identity)) {
        strip_vertex(&gEStripFns, &hullVertArray3[count - 1]);
        strip_vertex(&gEStripFns, &centre);
        strip_vertex(&gEStripFns, &hullVertArray3[0]);
        strip_colour(&gEStripFns, colour);
        strip_colour(&gEStripFns, colour);
        strip_colour(&gEStripFns, colour);
        strip_uv(&gEStripFns, 0.155f, 0.0f);
        strip_uv(&gEStripFns, 0.0f, 0.0f);
        strip_uv(&gEStripFns, 0.155f, 0.0f);
        strip_end(&gEStripFns);
    }

    // The edge in three strips, a third of the corners each and the last
    // what is left, each closed on the next one's first corner.
    n = count / 3;
    first = 0;
    for (seg = 1; seg <= 3; seg++) {
        int32_t len = seg < 3 ? n : count - first;
        int32_t j;

        if (!strip_begin(&gExStripFns, ri->ShadowRampTexture, (len + 1) * 2,
                         biased_identity)) {
            first += n;
            continue;
        }
        for (j = first; j < first + len; j++)
            shadow_edge_pair(&hullVertArray3[j], &centre, colour);
        first += n;
        shadow_edge_pair(&hullVertArray3[j < count ? j : 0], &centre,
                         colour);
        strip_end(&gExStripFns);
    }
}

// The grid shadow: the box's footprint, a little smaller in game, as a
// 4x4 grid laid on the ground point by point. A point with no ground of
// its own borrows its nearest wheel's plane; one too far off the car's
// plane sits at the last good height, and a row pair with four such is
// not drawn.
static void render_grid_shadow(CarRenderInfo *ri, const bVector3 *position,
                               const bMatrix4 *local_world,
                               bMatrix4 *biased_identity,
                               const eLightContext *light_context,
                               TopologyCoordinate *topo, int fe)
{
    bVector3 mn = ri->AABBMin, mx = ri->AABBMax;
    bVector3 P[16], centre;
    float uv[16][2];
    int32_t fails[4] = { 0, 0, 0, 0 };
    float fy = fe ? 1.0f : 0.95f, fx = fe ? 1.115f : 0.95f;
    const float third = 0.33333334f;
    float dx, dy, x, y, u, v, lo, hi, s, a;
    int32_t r, c, i;
    uint32_t colour;

    mn.y *= fy;
    mx.y *= fy;
    mn.x *= fx;
    mx.x *= fx;

    dy = (mx.y - mn.y) * third;
    dx = (mx.x - mn.x) * third;
    y = mn.y;
    v = 0.0f;
    for (r = 0; r < 4; r++) {
        float ny = y + dy, nv = v + third;

        x = mn.x;
        u = 0.0f;
        for (c = 0; c < 4; c++) {
            bVector3 *p = &P[r * 4 + c];

            p->x = x;
            p->y = y;
            p->z = 0.0f;
            p->pad = 0.0f;
            x += dx;
            uv[r * 4 + c][0] = u;
            uv[r * 4 + c][1] = v;
            eMulVector3(p, local_world, p);
            u += third;
            p->z = position->z;
        }
        y = ny;
        v = nv;
    }
    centre.x = centre.y = centre.z = centre.pad = 0.0f;
    eMulVector3(&centre, local_world, &centre);

    if (!fe && topo != NULL) {
        const CarTypeInfo *cti = ri->pCarTypeInfo;
        bVector3 wp[4], nrm[4];
        int32_t found[4];

        for (i = 0; i < 4; i++) {
            float rz;

            eMulVector3(&wp[i], local_world,
                        (const bVector3 *)&cti->Wheels[i].PositionX);
            wp[i].z = topology_get_elevation(topo, &wp[i], NULL, &nrm[i],
                                             &found[i]);
            rz = -1.0f / nrm[i].z;
            nrm[i].x *= rz;
            nrm[i].y *= rz;
            nrm[i].z *= rz;
            nrm[i].pad *= rz;
        }
        for (i = 0; i < 16; i++) {
            bVector3 *p = &P[i];
            int32_t f;

            p->z = topology_get_elevation(topo, p, NULL, NULL, &f);
            if (!f) {
                int32_t w = kGridNearestWheel[i];

                if (found[w]) {
                    p->z = (wp[w].z + (p->x - wp[w].x) * nrm[w].x)
                         + (p->y - wp[w].y) * nrm[w].y;
                    f = 1;
                }
            }
            // The four inner points, a little higher.
            if (((i ^ (i >> 1)) & 5) == 5)
                p->z += 0.08f;
            if (f && fabsf(p->z - hull_Origin.z) <= 4.0f) {
                bVector3 d;
                float t;

                d.x = p->x - hull_Origin.x;
                d.y = p->y - hull_Origin.y;
                d.z = p->z - hull_Origin.z;
                t = dot3(&d, &hull_Normal);
                if (t < 0.0f)
                    t = -t;
                if (t < 1.5f) {
                    centre.z = p->z;
                    p->z += 0.04f;
                    continue;
                }
            }
            p->z = centre.z + 0.04f;
            fails[i / 4]++;
        }
    } else {
        for (i = 0; i < 16; i++) {
            P[i].z = CarShadowElevationFE;
            if (((i ^ (i >> 1)) & 5) == 5)
                P[i].z = CarShadowElevationFE + 0.08f;
        }
    }

    lo = fe ? 92.0f : 70.0f;
    hi = fe ? 92.0f : 140.0f;
    s = light_context->SunlightIntensity;
    if (s < 0.4f)
        a = lo;
    else if (1.0f < s)
        a = hi;
    else
        a = lo + (hi - lo) * ((s - 0.4f) / 0.6f);
    {
        uint32_t ai = (uint32_t)(int32_t)a;

        // sltiu: unsigned, so a negative one is 255 too.
        if (!(ai < 256u))
            ai = 255;
        colour = ai << 24 | 0x808080u;
    }

    for (r = 0; r < 3; r++) {
        if (!(fails[r] + fails[r + 1] < 4))
            continue;
        if (!strip_begin(&gExStripFns, ri->ShadowTexture, 8,
                         biased_identity))
            continue;
        for (c = 0; c < 4; c++) {
            strip_vertex(&gExStripFns, &P[r * 4 + c]);
            strip_colour(&gExStripFns, colour);
            strip_uv(&gExStripFns, uv[r * 4 + c][0], uv[r * 4 + c][1]);
            strip_vertex(&gExStripFns, &P[(r + 1) * 4 + c]);
            strip_colour(&gExStripFns, colour);
            strip_uv(&gExStripFns, uv[(r + 1) * 4 + c][0],
                     uv[(r + 1) * 4 + c][1]);
        }
        strip_end(&gExStripFns);
    }
}

// ------------------------------------------------------------ Render

// A cop's flares: the headlights wig-wag, and the red, blue and white
// run their patterns. 0 for any other name.
static float cop_flare(uint32_t hash, uint32_t frame, uint32_t broken,
                       const Car *car)
{
    int wig = CopLightsHeadlights[frame & 15] != 0;
    int fast = car != NULL && car->CopLights == 2;
    const uint8_t *table;

    if (hash == HASH_HEADLIGHT_LEFT && wig)
        return (broken & 1) ? 0.0f : 1.0f;
    if (hash == HASH_HEADLIGHT_RIGHT && !wig)
        return (broken & 2) ? 0.0f : 1.0f;
    if (hash == HASH_COPLIGHTRED)
        table = fast ? CopLightsRed : CopLightsRedSlow;
    else if (hash == HASH_COPLIGHTBLUE)
        table = fast ? CopLightsBlue : CopLightsBlueSlow;
    else if (hash == HASH_COPLIGHTWHITE)
        table = fast ? CopLightsWhite : CopLightsWhiteSlow;
    else
        return 0.0f;
    return table[fast ? (frame & 7) : ((frame >> 1) & 15)] ? 1.0f : 0.0f;
}

static void render_light_flares(CarRenderInfo *ri, eView *view,
                                bMatrix4 *local_world, Car *car,
                                CarDriver *driver, uint32_t forced)
{
    float base_rear = 0.0f, base_front = 0.0f;
    float hl_left, hl_right, bl, bm, br, rl, rr;
    uint32_t frame, broken;
    int cop;
    bNode *n;

    if (car != NULL && car->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)
        base_rear = 0.7f;
    else if (lights_on_time_of_day())
        base_front = 0.75f;

    if (ForceHeadlights)
        forced |= 1;
    if (ForceBrakelights)
        forced |= 2;
    if (ForceReverselights)
        forced |= 4;
    if (ForceCoplights)
        forced |= 8;
    frame = ri->CarTimebaseStart + (uint32_t)WorldTimeFrames;

    hl_right = hl_left = base_front;
    bm = bl = br = base_rear;
    rr = rl = 0.0f;
    if (forced & 1) {
        hl_right += 1.0f;
        hl_left = hl_right;
    } else if (car != NULL) {
        int32_t on = car->HeadlightsState;

        if (car->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)
            on ^= 1;
        if (on) {
            hl_right = base_front + 1.0f;
            hl_left = hl_right;
        }
    }
    if (forced & 2) {
        bm = base_rear + 1.0f;
        br += 1.0f;
        bl = bm;
    } else if (driver != NULL && 0.05f < driver->Brake) {
        float x = driver->Brake * 16.0f;

        bm = base_rear + x;
        br += x;
        bl = bm;
    }
    // Gear 0 is reverse.
    if ((forced & 4) || (car != NULL && car->State.CurrentGear == 0)) {
        rr += 1.0f;
        rl = rr;
    }
    cop = (forced & 8) || (car != NULL && car->CopLights != 0);

    broken = ri->BrokenLightFlags;
    if (broken & 1)
        hl_left = 0.0f;
    if (broken & 2)
        hl_right = 0.0f;
    if (broken & 4)
        bl = 0.0f;
    if (broken & 8)
        br = 0.0f;
    if (broken & 16)
        bm = 0.0f;
    if (broken & 4)
        rl = 0.0f;
    if (broken & 8)
        rr = 0.0f;

    for (n = ri->LightFlareList.next; n != &ri->LightFlareList; n = n->next) {
        eLightFlare *flare = (eLightFlare *)n;
        float f = 0.0f;

        switch (flare->NameHash) {
        case HASH_FLARE_HEADLIGHT_LEFT:     f = hl_left;  break;
        case HASH_FLARE_HEADLIGHT_RIGHT:    f = hl_right; break;
        case HASH_FLARE_BRAKELIGHT_LEFT:    f = bl;       break;
        case HASH_FLARE_BRAKELIGHT_MIDDLE:  f = bm;       break;
        case HASH_FLARE_BRAKELIGHT_RIGHT:   f = br;       break;
        case HASH_FLARE_REVERSELIGHT_LEFT:  f = rl;       break;
        case HASH_FLARE_REVERSELIGHT_RIGHT: f = rr;       break;
        default:
            if (cop)
                f = cop_flare(flare->NameHash, frame, broken, car);
            break;
        }
        if (0.0f < f) {
            if (1.0f < f)
                f = 1.0f;
            if (gERenderLightFlareFn != NULL)
                gERenderLightFlareFn(view, flare, local_world, f);
        }
    }
}

// The animated driver, from far enough in, and at the finer level only
// close up -- closer still when seen from behind.
static void render_driver(CarRenderInfo *ri, eView *view, Car *car,
                          bMatrix4 *biased_local_world,
                          eLightContext *light_context, float size)
{
    const CarTypeInfo *cti = ri->pCarTypeInfo;
    AnimatedDriver *drv = car->pAnimatedDriver;
    const bVector3 *cam = &view->pCamera->CurrentKey.Position;
    float need = 50.0f;
    bMatrix4 *m, rot;
    bVector3 off, cd;
    bVector4 behind;
    float along, r;
    int32_t queued, lod;

    if (!cti->OpenTop)
        need = eGetCurrentViewMode() == 3 ? 100.0f : 75.0f;
    if (!ForceRenderDriver && !(need < size))
        return;
    if (animated_driver_hidden(drv) != 0)
        return;
    m = eframe_malloc(64);
    if (m == NULL)
        return;

    *m = *biased_local_world;
    rot = *biased_local_world;
    rot.v3.x = rot.v3.y = rot.v3.z = 0.0f;
    eMulVector3(&off, &rot, &cti->DriverRenderingOffset);
    m->v3.x += off.x;
    m->v3.y += off.y;
    m->v3.z += off.z;
    m->v3.w += off.pad;
    m->v3.w = 1.0f;

    behind.x = -1.0f;
    behind.y = behind.z = behind.w = 0.0f;
    eMulVector4(&behind, &rot, &behind);

    cd.x = cam->x - car->State.Position.x;
    cd.y = cam->y - car->State.Position.y;
    cd.z = cam->z - car->State.Position.z;
    cd.pad = cam->pad - car->State.Position.pad;
    r = 1.0f / sqrtf(dot3(&cd, &cd));
    cd.x *= r;
    cd.y *= r;
    cd.z *= r;
    along = (behind.x * cd.x + behind.y * cd.y) + behind.z * cd.z;
    queued = gAnimatedDriverQueuedFn != NULL ? gAnimatedDriverQueuedFn(drv)
                                             : 0;

    lod = 2;
    if (0.9f < along) {
        if (999.0f < size || (300.0f < size && queued))
            lod = 1;
    } else {
        if (300.0f < size || (150.0f < size && queued))
            lod = 1;
    }
    if (gAnimatedDriverRenderFn != NULL)
        gAnimatedDriverRenderFn(drv, m, light_context, 0, lod);
}

// A tyre or a brake: its matrix into the car and its own light context.
static void render_wheel_part(eModel *model, bMatrix4 *m, eLightContext *lc,
                              const bMatrix4 *pre, const bMatrix4 *part,
                              const bMatrix4 *biased_local_world,
                              eView *view, const bVector4 *eye,
                              uint32_t flags)
{
    if (pre != NULL) {
        bMatrix4 t;

        eMulMatrix(&t, pre, part);
        eMulMatrix(m, &t, biased_local_world);
    } else {
        eMulMatrix(m, part, biased_local_world);
    }
    set_up_light_context(lc, m, view->WorldViewMatrix, eye, view);
    model_render(model, m, lc, flags);
}

void carrenderinfo_render(CarRenderInfo *ri, eView *view,
                          const bVector3 *position,
                          const bMatrix4 *body_matrix,
                          bMatrix4 *tire_matrices, bMatrix4 *brake_matrices,
                          uint32_t extra_render_flags,
                          uint32_t forced_lights)
{
    Car *car;
    CarDriver *driver;
    CarDamage *car_damage;
    CarCollisionBody *colbody;
    TopologyCoordinate *topo;
    Camera *camera;
    eLightContext *light_context;
    bMatrix4 *local_world, *biased_local_world, *biased_identity;
    bMatrix4 local_to_screenclip, world_local, pre_translate;
    bVector4 eye4;
    bVector3 eye;
    int32_t pixels, body_lod, tire_lod, fe, turned;
    uint32_t disable_env, disable_env_tires, body_flags;
    float size, dist, bias, dx, dy, dz;
    void *body0_solid;

    pixels = eview_get_pixel_size_sphere(view, position, 3.0f);
    if (eGetCurrentViewMode() == 3)
        pixels = (int32_t)((float)pixels * 0.7f);
    if (pixels < 4)
        return;

    car = ri->pCar;
    driver = car != NULL ? car->pCarDriver : NULL;
    fe = in_front_end();
    camera = view->pCamera;

    // All four are asked for before any is tested.
    light_context = eframe_malloc(288);
    local_world = eframe_malloc(64);
    biased_local_world = eframe_malloc(64);
    biased_identity = eframe_malloc(64);
    if (light_context == NULL || local_world == NULL
        || biased_local_world == NULL || biased_identity == NULL)
        return;

    *local_world = *body_matrix;
    eMulMatrix(local_world, &CarRenderMatrix, local_world);
    local_world->v3.x = position->x;
    local_world->v3.y = position->y;
    local_world->v3.z = position->z;
    local_world->v3.w = 1.0f;

    eMulMatrix(&local_to_screenclip, local_world, view->WorldScreenClipMatrix);
    if (scenery_classify_aabb((const bVector4 *)&ri->AABBMin,
                              (const bVector4 *)&ri->AABBMax,
                              &local_to_screenclip) == 0)
        return;

    eye4.x = camera->CurrentKey.Position.x;
    eye4.y = camera->CurrentKey.Position.y;
    eye4.z = camera->CurrentKey.Position.z;
    eye4.w = 1.0f;
    if (PrintQueryLightMat)
        QueryLightMat = 1;
    set_up_light_context(light_context, local_world, &hack_man_matrix, &eye4,
                         view);
    if (PrintQueryLightMat)
        QueryLightMat = 0;

    carrenderinfo_update_light_state_textures(ri);
    car_damage = car != NULL ? car->pCarDamage : NULL;
    // Asked for and not used.
    (void)cartypeinfo_get_skin_info(ri->pCarTypeInfo->Type,
                                    ri->pRideInfo->SkinNumber, 1);

    size = (float)pixels;
    disable_env = disable_env_tires = (EnableEnvMap == 0 || size < 18.0f);

    body_lod = tire_lod = 0;
    if (size < CarLodPixelSizes[0] && ri->Body[1].Solid != NULL) {
        do {
            body_lod++;
            tire_lod++;
        } while (size < CarLodPixelSizes[body_lod]
                 && ri->Body[body_lod + 1].Solid != NULL);
    }
    // A car in the air, seen from under, keeps a body with an underside.
    if (body_lod >= 3 && car != NULL && car->State.nWheelsTouchingGround == 0
        && ri->PartCuller[CULLABLE_CAR_PART_UNDERNEATH].State[2])
        body_lod = 2;
    if (ForceCarLOD != -1)
        body_lod = ForceCarLOD;
    if (ForceTireLOD != -1)
        tire_lod = ForceTireLOD;

    bInvertMatrix(&world_local, local_world);
    bMulMatrixVec3(&eye, &world_local, &camera->CurrentKey.Position);
    dx = camera->CurrentKey.Position.x - local_world->v3.x;
    dy = camera->CurrentKey.Position.y - local_world->v3.y;
    dz = camera->CurrentKey.Position.z - local_world->v3.z;
    dist = sqrtf((dx * dx + dy * dy) + dz * dz);
    // Player one's camera inside the car draws nothing.
    if (body_lod == 0 && dist < 4.0f && view->ID == 1) {
        eye.z += 0.5f;
        if (bBoundingBoxIsInside3(&ri->AABBMin, &ri->AABBMax, &eye, 0.0f))
            return;
        eye.z -= 0.5f;
    }

    *biased_local_world = *local_world;
    biased_identity->v0 = eMathIdentityMatrix.v0;
    biased_identity->v1 = eMathIdentityMatrix.v1;
    biased_identity->v2 = eMathIdentityMatrix.v2;
    biased_identity->v3.x = position->x;
    biased_identity->v3.y = position->y;
    biased_identity->v3.z = position->z;
    biased_identity->v3.w = 1.0f;
    // dist / dist: 1, or NaN with the camera on the car.
    bias = dist / dist;
    biased_local_world->v3.z += 0.01f;
    eview_bias_matrix_for_z_sorting(view, biased_local_world, bias);
    eview_bias_matrix_for_z_sorting(view, biased_identity, bias);
    bIdentity(&pre_translate);
    pre_translate.v3.x = -position->x;
    pre_translate.v3.y = -position->y;
    pre_translate.v3.z = -position->z;
    eMulMatrix(biased_identity, &pre_translate, biased_identity);
    carrenderinfo_cull_parts(ri->PartCuller, &eye);

    render_light_flares(ri, view, local_world, car, driver, forced_lights);
    body_flags = disable_env | extra_render_flags;

    if (car != NULL && car->pAnimatedDriver != NULL && view->ID != 3
        && car->DriverRenderingEnabled)
        render_driver(ri, view, car, biased_local_world, light_context, size);

    // ---- the shadows
    body0_solid = ri->Body[0].Solid;
    hull_Origin = *position;
    topo = car != NULL ? &car->TheTopologyCoordinate : NULL;
    if (topo != NULL)
        hull_Origin.z = topology_get_elevation(topo, &hull_Origin, NULL,
                                               &hull_Normal, NULL);
    colbody = car != NULL ? car->pDynamicCollisionBody : NULL;
    if (body_lod < 3 && !fe && colbody != NULL && body0_solid != NULL
        && ri->ShadowRampTexture != NULL && view->ID != 3)
        render_hull_shadow(ri, position, local_world, biased_identity,
                           light_context, colbody, topo, size, body_lod);
    if (body0_solid != NULL && ri->ShadowTexture != NULL
        && !(car != NULL && car->State.nWheelsTouchingGround == 4
             && !ri->PartCuller[CULLABLE_CAR_PART_SHADOW].State[2]))
        render_grid_shadow(ri, position, local_world, biased_identity,
                           light_context, topo, fe);

    // ---- the body, the mirrors, the plates and the scuffs
    {
        eModel *m = &ri->Body[body_lod];

        model_replace_light_material(m, HASH_CARSKIN,
                                     ri->pCarSkinLightMaterial);
        model_render(m, biased_local_world, light_context, body_flags);
    }
    if (body_lod < 2) {
        int32_t k;

        for (k = 0; k < 2; k++) {
            if (car_damage != NULL && !(item_level(car_damage, k) < 2))
                continue;
            model_replace_light_material(&ri->SideMirrors[k], HASH_CARSKIN,
                                         ri->pCarSkinLightMaterial);
            model_render(&ri->SideMirrors[k], biased_local_world,
                         light_context, body_flags);
        }
    }
    if (body_lod < 3) {
        int32_t k;

        for (k = 0; k < 2; k++) {
            if (!ri->PartCuller[CULLABLE_CAR_PART_SIDE_FRONT + k].State[2])
                continue;
            if (car_damage != NULL && !(item_level(car_damage, 2 + k) < 2))
                continue;
            model_render(&ri->LicensePlates[k], biased_local_world,
                         light_context, body_flags);
        }
    }
    if (body_lod < 2 && car_damage != NULL
        && 0.02f < bodydamage_get_visible_total_damage(&car_damage->TheBodyDamage))
        model_render(&ri->Scuffs, biased_local_world, NULL,
                     extra_render_flags);

    // Front wheels turned between 6 and 354 degrees are seen whatever the
    // culler says.
    turned = 0;
    if (driver != NULL) {
        float deg = (float)(int32_t)driver->Steering * 0.0054931640625f;

        turned = 6.0f < deg && deg < 354.0f;
    }

    // ---- the tyres and their blur
    if (body_lod < 3) {
        bMatrix4 *M = eframe_malloc(256);
        eLightContext *LC = eframe_malloc(1152);

        if (M != NULL && LC != NULL) {
            uint32_t v0 = ri->PartCuller[CULLABLE_CAR_PART_TIRE_FL].State[2];
            uint32_t v1 = ri->PartCuller[CULLABLE_CAR_PART_TIRE_FR].State[2];
            uint32_t v2 = ri->PartCuller[CULLABLE_CAR_PART_TIRE_RR].State[2];
            uint32_t v3 = ri->PartCuller[CULLABLE_CAR_PART_TIRE_RL].State[2];
            uint32_t tflags = disable_env_tires | extra_render_flags;
            int32_t tl;
            bMatrix4 R;

            if (fe)
                v0 = v1 = v2 = v3 = 1;
            if (turned)
                v0 = v1 = 1;
            tl = tire_lod < 3 ? tire_lod : 2;
            // The left side's tyres are the right's turned round.
            eIdentity(&R);
            eRotateZ(&R, &R, 0x8000);
            if (v0)
                render_wheel_part(&ri->Tires[tl][0], &M[0], &LC[0], &R,
                                  &tire_matrices[0], biased_local_world,
                                  view, &eye4, tflags);
            if (v1)
                render_wheel_part(&ri->Tires[tl][0], &M[1], &LC[1], NULL,
                                  &tire_matrices[1], biased_local_world,
                                  view, &eye4, tflags);
            if (v2)
                render_wheel_part(&ri->Tires[tl][1], &M[2], &LC[2], NULL,
                                  &tire_matrices[2], biased_local_world,
                                  view, &eye4, tflags);
            if (v3)
                render_wheel_part(&ri->Tires[tl][1], &M[3], &LC[3], &R,
                                  &tire_matrices[3], biased_local_world,
                                  view, &eye4, tflags);

            // The blur is drawn with a copy of the tyres' light contexts,
            // its alpha in each copy's +60.
            if (tl < 2 && !in_front_end()) {
                eLightContext *B = eframe_malloc(1152);

                if (B != NULL) {
                    uint32_t bflags = extra_render_flags | 1;

                    memcpy(B, LC, 1152);
                    if (ri->PartCuller[CULLABLE_CAR_PART_TIRE_BLURS_LEFT].State[2]) {
                        float b0 = carrenderinfo_calculate_tire_blur(ri, 0) * 90.0f;
                        float b3 = carrenderinfo_calculate_tire_blur(ri, 3) * 90.0f;

                        if (v0 && 0.1f < b0) {
                            B[0].LocalColourMatrix.v3.w = b0;
                            model_render(&ri->TireBlur[0], &M[0], &B[0], bflags);
                        }
                        if (v3 && 0.1f < b3) {
                            B[3].LocalColourMatrix.v3.w = b3;
                            model_render(&ri->TireBlur[1], &M[3], &B[3], bflags);
                        }
                    }
                    if (ri->PartCuller[CULLABLE_CAR_PART_TIRE_BLURS_RIGHT].State[2]) {
                        float b1 = carrenderinfo_calculate_tire_blur(ri, 1) * 90.0f;
                        float b2 = carrenderinfo_calculate_tire_blur(ri, 2) * 90.0f;

                        if (v1 && 0.1f < b1) {
                            B[1].LocalColourMatrix.v3.w = b1;
                            model_render(&ri->TireBlur[0], &M[1], &B[1], bflags);
                        }
                        if (v2 && 0.1f < b2) {
                            B[2].LocalColourMatrix.v3.w = b2;
                            model_render(&ri->TireBlur[1], &M[2], &B[2], bflags);
                        }
                    }
                }
            }
        }
    }

    // ---- the brakes
    if (ri->Brakes[0].Solid != NULL && body_lod < 2) {
        uint32_t w0 = ri->PartCuller[CULLABLE_CAR_PART_BRAKE_FL].State[2];
        uint32_t w1 = ri->PartCuller[CULLABLE_CAR_PART_BRAKE_FR].State[2];
        uint32_t w2 = ri->PartCuller[CULLABLE_CAR_PART_BRAKE_RR].State[2];
        uint32_t w3 = ri->PartCuller[CULLABLE_CAR_PART_BRAKE_RL].State[2];

        if (turned || in_front_end())
            w0 = w1 = 1;
        if (w0 | w3 | w2 | w1) {
            bMatrix4 *M = eframe_malloc(256);
            eLightContext *LC = eframe_malloc(1152);

            if (M != NULL && LC != NULL) {
                // The left side's are the right's mirrored in y.
                if (w0 | w3) {
                    bMatrix4 F;

                    eIdentity(&F);
                    F.v2.z = 1.0f;
                    F.v1.y = -1.0f;
                    F.v0.x = 1.0f;
                    if (w0)
                        render_wheel_part(&ri->Brakes[0], &M[0], &LC[0], &F,
                                          &brake_matrices[0],
                                          biased_local_world, view, &eye4,
                                          extra_render_flags);
                    if (w3)
                        render_wheel_part(&ri->Brakes[1], &M[3], &LC[3], &F,
                                          &brake_matrices[3],
                                          biased_local_world, view, &eye4,
                                          extra_render_flags);
                }
                if (w1)
                    render_wheel_part(&ri->Brakes[0], &M[1], &LC[1], NULL,
                                      &brake_matrices[1], biased_local_world,
                                      view, &eye4, extra_render_flags);
                if (w2)
                    render_wheel_part(&ri->Brakes[1], &M[2], &LC[2], NULL,
                                      &brake_matrices[2], biased_local_world,
                                      view, &eye4, extra_render_flags);
            }
        }
    }

    // ---- the wipers, while they run
    if (40.0f < size && car != NULL
        && (car->WiperState
            || ((int32_t)car->WiperOnTime <= WorldTimeFrames
                && WorldTimeFrames < (int32_t)car->WiperOffTime))) {
        int32_t k;

        for (k = 0; k < 2; k++) {
            eModel *w = &ri->Wipers[k];
            eSolid *solid = w->Solid;
            bMatrix4 *m;

            if (solid == NULL || solid->pRigidAnimation == NULL)
                continue;
            w->RigidAnimationStartTime =
                (int16_t)((car->WiperOnTime & 0x3fff) | 0xc000);
            m = eframe_malloc(64);
            if (m == NULL)
                continue;
            bMulMatrix(m, biased_local_world, &solid->PivotMatrix);
            model_render(w, m, NULL, 0);
        }
    }
}
