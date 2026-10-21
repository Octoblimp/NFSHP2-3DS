// eviewmatrix -- the matrix half of eView.obj and the three helpers it calls
// in EcstasyE.obj. See eviewmatrix.h.
//
// A matrix is built as sixteen floats, k = 4 * row + column, and copied out
// whole, which is what the listings' four quadword stores are. Every
// multiply and divide is the listing's, in its order.

#include <math.h>
#include <string.h>

#include "acidfx.h"
#include "bmath.h"
#include "cammover.h"
#include "eefpu.h"
#include "emath.h"
#include "eframe.h"
#include "eviewmatrix.h"

eRenderTargetMatrixPack DefaultMatrixPack;
bMatrix4 hack_man_matrix;
bVector3 SunPosition;

void (*gElSetupLightContextFn)(eLightContext *lc, const bMatrix4 *local_world,
                               const bMatrix4 *hack, const bVector4 *eye,
                               eView *view);

static float tan_bam(uint16_t fov)
{
    uint16_t half = (uint16_t)(fov >> 1);

    return bSinBam(half) / bCosBam(half);
}

static void identity16(float m[16])
{
    memset(m, 0, 16 * sizeof m[0]);
    m[0] = m[5] = m[10] = m[15] = 1.0f;
}

float CalculateH(uint16_t fov)
{
    float t = tan_bam(fov);

    if (t == 0.0f)
        return 10.0f;
    return (float)(ScreenWidth >> 1) / t;
}

void CreateViewMatricies(eView *view, bMatrix4 *a, bMatrix4 *b, bMatrix4 *c,
                         bMatrix4 *d, bMatrix4 *d2, bMatrix4 *e, float nearz,
                         float farz, float e_farz)
{
    Camera *cam = view->pCamera;
    eRenderTarget *rt0 = view->pRenderTarget0, *rt1 = view->pRenderTarget1;
    float near = cam->CurrentKey.NearZ, far = cam->CurrentKey.FarZ;
    float bias, nf, h, invh, span, w, hs, gx, gy, cx, cy, p, q;
    float ma[16], ml[16], m2[16], mm[16], mn[16];
    const eZRange *z;
    bNode *first;
    int fixed = 0;

    bias = tan_bam(aBaselineFovMip) / tan_bam(cam->CurrentKey.FieldOfView);
    rt0->FovBias = bias;
    if (rt1 != 0)
        rt1->FovBias = bias;

    first = view->CameraMoverList.next != &view->CameraMoverList
          ? view->CameraMoverList.next : 0;
    if (first != 0 && (((CameraMover *)first)->Type == CM_DRIVE
                       || ((CameraMover *)first)->Type == CM_BUMPER))
        fixed = 1;
    if ((uint32_t)view->ID - 1u < 2u && !fixed) {
        float depth = far - near;
        float s = tan_bam(aBaselineFovZ) / tan_bam(cam->CurrentKey.FieldOfView);

        near = near * s;
        far = near + depth;
    }
    if (nearz != 0.0f)
        near = nearz;
    if (farz != 0.0f)
        far = farz;

    view->NearZ = near;
    nf = far * near;
    view->FarZ = far;
    h = CalculateH(cam->CurrentKey.FieldOfView);
    span = far - near;
    view->H = h;
    invh = 1.0f / h;
    view->FovDegrees = (float)(int32_t)cam->CurrentKey.FieldOfView * 0.0054931640625f;
    view->ViewDirection = cam->CurrentKey.Direction;

    // a, view to screen, and its twins for the second and third depth
    // ranges, all three from the first target's Z buffer's.
    z = eview_z_range(rt0);
    memset(ma, 0, sizeof ma);
    ma[0] = rt0->AspectRatioX;
    ma[5] = rt0->AspectRatioY;
    ma[8] = CenterX / h;
    ma[9] = CenterY / h;
    ma[10] = (-z->ZMax * near + z->ZMin * far) / span / h;
    ma[11] = invh;
    ma[14] = nf * (z->ZMax - z->ZMin) / span / h;
    memcpy(a, ma, sizeof ma);

    memcpy(ml, ma, sizeof ml);
    ml[10] = (-z->ZMax1 * near + z->ZMin1 * far) / span / h;
    ml[14] = nf * (z->ZMax1 - z->ZMin1) / span / h;
    memcpy(m2, ma, sizeof m2);
    m2[10] = (-z->ZMax2 * near + z->ZMin2 * far) / span / h;
    m2[14] = nf * (z->ZMax2 - z->ZMin2) / span / h;

    // The clip volume: the scissor scaled by ClipVolumeScale, and for e no
    // more than half of it.
    w = (float)rt0->ScissorW;
    hs = (float)rt0->ScissorH;
    gx = w * ClipVolumeScaleX;
    cx = w * 0.5f;
    if (gx < cx)
        cx = gx;
    gy = hs * ClipVolumeScaleY;
    cy = hs * 0.5f;
    if (gy < cy)
        cy = gy;

    if (b != 0) {
        p = near * gy / h;
        q = near * gx / h;
        identity16(mm);
        mm[0] = (near + near) / (q + q);
        mm[5] = (near + near) / (p + p);
        mm[10] = (far + near) / (far - near);
        mm[11] = 1.0f;
        mm[14] = nf * -2.0f / (far - near);
        mm[15] = 0.0f;
        memcpy(b, mm, sizeof mm);

        // d2 is made only alongside c or d.
        if (c != 0 || d != 0) {
            bMatrix4 n, l, l2;

            identity16(mn);
            mn[0] = 1.0f / mm[0];
            mn[5] = 1.0f / mm[5];
            mn[10] = 0.0f;
            mn[11] = 1.0f / mm[14];
            mn[14] = 1.0f;
            mn[15] = -mm[10] / mm[14];
            memcpy(&n, mn, sizeof n);
            memcpy(&l, ml, sizeof l);
            memcpy(&l2, m2, sizeof l2);
            if (c != 0)
                eMulMatrix(c, &n, a);
            if (d != 0)
                eMulMatrix(d, &n, &l);
            if (d2 != 0)
                eMulMatrix(d2, &n, &l2);
        }
    }

    if (e != 0) {
        float ef = far;

        p = near * cx / h;
        q = near * cy / h;
        if (e_farz != 0.0f)
            ef = e_farz;
        identity16(mm);
        mm[0] = (near + near) / (p + p);
        mm[5] = (near + near) / (q + q);
        mm[10] = (ef + near) / (ef - near);
        mm[11] = 1.0f;
        mm[14] = ef * near * -2.0f / (ef - near);
        mm[15] = 0.0f;
        memcpy(e, mm, sizeof mm);
    }

    eMulMatrix(a, b, c);
}

// VUClipScreen: m's diagonal and row 3, then its inverse's, one word zero
// after each diagonal.
static void vu_clip_screen(bMatrix4 *o, const bMatrix4 *m, const bMatrix4 *mi)
{
    float s[16], si[16], v[16];

    memcpy(s, m, sizeof s);
    memcpy(si, mi, sizeof si);
    v[0] = s[0];
    v[1] = s[5];
    v[2] = s[10];
    v[3] = 0.0f;
    v[4] = s[12];
    v[5] = s[13];
    v[6] = s[14];
    v[7] = s[15];
    v[8] = si[0];
    v[9] = si[5];
    v[10] = si[10];
    v[11] = 0.0f;
    v[12] = si[12];
    v[13] = si[13];
    v[14] = si[14];
    v[15] = si[15];
    memcpy(o, v, sizeof v);
}

static void set_target(eRenderTarget *rt, bMatrix4 *const p[9])
{
    rt->WorldClip = p[1];
    rt->WorldView = p[0];
    rt->ClipScreen = p[4];
    rt->VUClipScreen = p[6];
    rt->VUClipScreen1 = p[7];
    rt->VUClipScreen2 = p[8];
    erender_setup_matrix_packs(rt);
}

void eview_calculate_view_matrices(eView *view, float nearz, float farz,
                                   float e_farz)
{
    bMatrix4 a, b, c, d, d2, e, ci, di, d2i;
    Camera *cam = view->pCamera;
    bMatrix4 *blk, *p[9];
    eRenderTarget *rt0, *rt1;
    int i;

    CreateViewMatricies(view, &a, &b, &c, &d, &d2, &e, nearz, farz, e_farz);
    blk = eframe_malloc(9 * sizeof(bMatrix4));
    if (blk == 0) {
        for (i = 0; i < 9; i++)
            p[i] = &eMathIdentityMatrix;
    } else {
        for (i = 0; i < 9; i++)
            p[i] = &blk[i];
        fInvertMatrix(&ci, &c);
        fInvertMatrix(&di, &d);
        fInvertMatrix(&d2i, &d2);
        vu_clip_screen(&blk[6], &c, &ci);
        vu_clip_screen(&blk[7], &d, &di);
        vu_clip_screen(&blk[8], &d2, &d2i);
        blk[0] = cam->CurrentKey.Matrix;
        blk[4] = c;
        eMulMatrix(&blk[1], &blk[0], &b);
        eMulMatrix(&blk[2], &blk[0], &a);
        eMulMatrix(&blk[3], &blk[0], &e);
    }

    view->WorldScreenMatrix = p[2];
    view->WorldScreenClipMatrix = p[3];
    view->WorldViewMatrix = p[0];
    view->ViewScreenMatrix = p[5];
    view->WorldClipMatrix = p[1];
    view->ClipScreenMatrix = p[4];
    view->VUClipScreenMatrix = p[6];
    view->VUClipScreenMatrix1 = p[7];
    view->VUClipScreenMatrix2 = p[8];

    rt0 = view->pRenderTarget0;
    rt1 = view->pRenderTarget1;
    if (rt0 != 0)
        set_target(rt0, p);
    if (rt1 != 0)
        set_target(rt1, p);
}

// A pack from frame memory, or DefaultMatrixPack when there was none.
static eRenderTargetMatrixPack *fill_pack(eRenderTargetMatrixPack *p,
                                          const eRenderTarget *rt,
                                          const bMatrix4 *vu)
{
    if (p == 0)
        return &DefaultMatrixPack;
    p->WorldClip = *rt->WorldClip;
    p->VUClipScreen = *vu;
    eTransposeMatrix(&p->WorldViewT, rt->WorldView);
    return p;
}

void erender_setup_matrix_packs(eRenderTarget *rt)
{
    eRenderTargetMatrixPack *p0 = eframe_malloc(sizeof *p0);
    eRenderTargetMatrixPack *p1 = eframe_malloc(sizeof *p1);
    eRenderTargetMatrixPack *p2 = eframe_malloc(sizeof *p2);

    rt->MatrixPack0 = fill_pack(p0, rt, rt->VUClipScreen);
    rt->MatrixPack1 = fill_pack(p1, rt, rt->VUClipScreen1);
    rt->MatrixPack2 = fill_pack(p2, rt, rt->VUClipScreen2);
}

void eview_local_to_screen_clip(eView *view, bMatrix4 *o,
                                const bMatrix4 *local)
{
    eMulMatrix(o, local, view->WorldScreenClipMatrix);
}

void eview_local_to_clip(eView *view, bMatrix4 *o, const bMatrix4 *local)
{
    eMulMatrix(o, local, view->WorldClipMatrix);
}

void eview_bias_matrix_for_z_sorting(eView *view, bMatrix4 *m, float scale)
{
    Camera *cam = view->pCamera;
    bMatrix4 s;
    bVector4 d;

    if (cam == 0)
        return;
    bIdentity(&s);
    s.v0.x = scale;
    s.v1.y = scale;
    s.v2.z = scale;
    d.x = (m->v3.x - cam->CurrentKey.Position.x) * scale + cam->CurrentKey.Position.x;
    d.y = (m->v3.y - cam->CurrentKey.Position.y) * scale + cam->CurrentKey.Position.y;
    d.z = (m->v3.z - cam->CurrentKey.Position.z) * scale + cam->CurrentKey.Position.z;
    m->v3.x = 0.0f;
    m->v3.w = 1.0f;
    m->v3.y = 0.0f;
    m->v3.z = 0.0f;
    s.v3.x = d.x;
    s.v3.y = d.y;
    s.v3.z = d.z;
    s.v3.w = 1.0f;
    eMulMatrix(m, m, &s);
}

int32_t eview_get_pixel_size(eView *view, float r, float d)
{
    float s;

    if (r * 0.5f < d)
        s = r * view->H / d;
    else
        s = view->H + view->H;
    return ee_trunc_w(s);
}

int32_t eview_get_pixel_size_sphere(eView *view, const bVector3 *p, float r)
{
    Camera *cam = view->pCamera;
    float dx = p->x - cam->CurrentKey.Position.x;
    float dy = p->y - cam->CurrentKey.Position.y;
    float dz = p->z - cam->CurrentKey.Position.z;
    float dot = dx * cam->CurrentKey.Direction.x + dy * cam->CurrentKey.Direction.y
              + dz * cam->CurrentKey.Direction.z;
    float dist, s;

    if (dot < -r)
        return 0;
    dist = sqrtf(dx * dx + dy * dy + dz * dz) - r;
    if (r * 0.5f < dist)
        s = r * view->H / dist;
    else
        s = view->H + view->H;
    return ee_trunc_w(s);
}

int32_t eview_get_pixel_size_box(eView *view, const bVector3 *mn,
                                 const bVector3 *mx)
{
    Camera *cam = view->pCamera;
    float ex = mn->x - mx->x, ey = mn->y - mx->y, ez = mn->z - mx->z;
    float r = sqrtf(ex * ex + ey * ey + ez * ez) * 0.5f;
    float dx = (mn->x + mx->x) * 0.5f - cam->CurrentKey.Position.x;
    float dy = (mn->y + mx->y) * 0.5f - cam->CurrentKey.Position.y;
    float dz = (mn->z + mx->z) * 0.5f - cam->CurrentKey.Position.z;
    float dot = dx * cam->CurrentKey.Direction.x + dy * cam->CurrentKey.Direction.y
              + dz * cam->CurrentKey.Direction.z;
    float dist, s;

    if (dot < -r)
        return 0;
    dist = sqrtf(dx * dx + dy * dy + dz * dz) - r;
    s = view->H;
    if (r < dist)
        s = r * view->H / dist;
    return ee_trunc_w(s);
}

void eview_get_screen_position(eView *view, bVector3 *o, const bVector3 *p)
{
    eRenderTarget *rt = view->pRenderTarget0;
    bVector4 v, s;

    v.x = p->x;
    v.y = p->y;
    v.z = p->z;
    v.w = 1.0f;
    eRotTransPers(&s, view->WorldScreenMatrix, &v);
    o->z = s.z;
    o->x = (s.x - 2048.0f) + (float)(rt->ScissorW / 2);
    o->y = (s.y - 2048.0f) + (float)(rt->ScissorH / 2);
}

float eview_get_screen_width(eView *view)
{
    return (float)view->pRenderTarget0->ScissorW;
}

float eview_get_screen_height(eView *view)
{
    return (float)view->pRenderTarget0->ScissorH;
}

void eview_setup_world_light_context(eView *view)
{
    Camera *cam;
    eLightContext *lc;
    const bMatrix4 *m;
    bVector4 eye;
    bVector3 origin = {0.0f, 0.0f, 0.0f, 0.0f};
    bVector3 up = {0.0f, 0.0f, 1.0f, 0.0f};
    bMatrix4 look, unit;

    view->WorldLightContext = 0;
    cam = view->pCamera;
    if (cam == 0)
        return;
    lc = eframe_malloc(sizeof *lc);
    view->WorldLightContext = lc;
    if (lc == 0)
        return;

    m = &cam->CurrentKey.Matrix;
    eye.x = cam->CurrentKey.Position.x - m->v0.z * 10.0f;
    eye.y = cam->CurrentKey.Position.y - m->v1.z * 10.0f;
    eye.w = 1.0f;
    eye.z = cam->CurrentKey.Position.z - m->v2.z * 10.0f + 4.0f;
    if (gElSetupLightContextFn != 0)
        gElSetupLightContextFn(lc, &eMathIdentityMatrix, &hack_man_matrix,
                               &eye, view);
    // Retail's look-at goes through an identity and into
    // LocalLightPositions (+128), which no VU1 program reads; the demo's
    // went into EnvMapMatrix. So the world's environment pass keeps the
    // matrix elSetupLightContext made from hack_man_matrix, as a car's does.
    eCreateLookAtMatrix(&look, &SunPosition, &origin, &up);
    eIdentity(&unit);
    eMulMatrix(&look, &unit, &look);
    lc->LocalLightPositions = look;
}
