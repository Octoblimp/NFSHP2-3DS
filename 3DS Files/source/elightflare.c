// elightflare -- see elightflare.h.

#include "elightflare.h"

#include <math.h>
#include <string.h>

#include "camera.h"
#include "eefpu.h"
#include "emath.h"
#include "epoly.h"
#include "trackflow.h"

// 1.0f's bits, as a float: the fast power's bias.
#define ONE_BITS 1065353216.0f

const eLightFlarePart SingleLightFlareParameters[9] = {
    // 0x002d6080: the headlights' inner flare.
    { 0.0f, 64.0f, { 0.0f, 0.0f, 0.0f, 0.0f },
      { 100.0f, 120.0f, 170.0f, 80.0f }, 1.45f, 0.8f, 0.01f, 0.015f, 0 },
    // 0x002d60bc: their outer ring.
    { 28.0f, 28.0f, { 0.0f, 0.0f, 0.0f, 0.0f },
      { 100.0f, 120.0f, 140.0f, 20.0f }, 3.0f, 0.8f, 0.01f, 0.015f, 1 },
    // 0x002d60f8: a brake light.
    { 20.0f, 30.0f, { 0.0f, 0.0f, 0.0f, 0.0f },
      { 128.0f, 0.0f, 0.0f, 80.0f }, 1.0f, 0.2f, 0.01f, 0.02f, 2 },
    // 0x002d6134: a reverse light.
    { 20.0f, 20.0f, { 0.0f, 0.0f, 0.0f, 0.0f },
      { 255.0f, 255.0f, 255.0f, 128.0f }, 1.2f, 0.2f, 0.005f, 0.01f, 2 },
    // 0x002d6170: type 3's.
    { 20.0f, 20.0f, { 0.0f, 0.0f, 0.0f, 0.0f },
      { 128.0f, 128.0f, 128.0f, 128.0f }, 1.0f, 0.2f, 0.005f, 0.01f, 2 },
    // 0x002d61ac: a cop's red.
    { 30.0f, 40.0f, { 128.0f, 64.0f, 64.0f, 48.0f },
      { 128.0f, 64.0f, 64.0f, 128.0f }, 1.0f, 1.0f, 0.01f, 0.02f, 0 },
    // 0x002d61e8: blue.
    { 30.0f, 40.0f, { 64.0f, 64.0f, 128.0f, 48.0f },
      { 64.0f, 64.0f, 128.0f, 128.0f }, 1.0f, 1.0f, 0.01f, 0.02f, 0 },
    // 0x002d6224: white.
    { 30.0f, 40.0f, { 128.0f, 128.0f, 128.0f, 32.0f },
      { 128.0f, 128.0f, 128.0f, 128.0f }, 1.0f, 1.0f, 0.01f, 0.02f, 0 },
    // 0x002d6260: a tunnel's lamp.
    { 30.0f, 50.0f, { 110.0f, 100.0f, 75.0f, 96.0f },
      { 110.0f, 100.0f, 75.0f, 110.0f }, 1.0f, 4.0f, 0.001f, 0.1f, 2 },
};

#define P(i) (&SingleLightFlareParameters[i])

const eLightFlarePart *const
    LightFlareParameterIndicies[NUM_LIGHT_FLARE_TYPES][2] = {
    { P(0), P(1) }, { P(2), NULL }, { P(3), NULL }, { P(4), NULL },
    { P(5), NULL }, { P(6), NULL }, { P(7), NULL }, { P(0), P(1) },
    { P(0), P(1) }, { P(8), NULL },
};

static const uint32_t kTextureHashes[NUM_LIGHT_FLARE_TEXTURES] = {
    0x8868656fu,                        // HEADLIGHTFLAREINNER
    0x88d8e8a2u,                        // HEADLIGHTFLAREOUTER
    0x3394fe62u,                        // HEADLIGHTGLOW
};

TextureInfo *eLightFlareTextures[NUM_LIGHT_FLARE_TEXTURES];

void el_update_textures(void)
{
    int i;

    for (i = 0; i < NUM_LIGHT_FLARE_TEXTURES; i++)
        eLightFlareTextures[i] = GetTextureInfo(kTextureHashes[i], 0, 0);
}

// 0x00116118: one part, at `pos` (the flare in the world) with `to_cam`
// the unit vector to the eye, and `right` and `up` the view's axes in the
// world. `facing` is the cosine between the flare's direction and the
// eye's, and `scale` the flare's depth over the view's H: world units a
// pixel there.
static void render_part(const eLightFlarePart *p, const bVector4 *pos,
                        const bVector4 *to_cam, const bVector3 *right,
                        const bVector3 *up, float intensity, float facing,
                        float scale)
{
    TextureInfo *tex = eLightFlareTextures[p->Texture];
    float d, k, size, ext, cx, cy, cz, rx, ry, rz, ux, uy, uz;
    int32_t bits, i;
    uint8_t r, g, b, a;
    ePoly poly;

    if (tex == NULL)
        return;
    // pow(facing, Power), from the float's bits: the bits less 1.0's,
    // times Power, plus 1.0's, taken as a float again.
    d = facing < 0.01f ? 0.01f : facing;
    memcpy(&bits, &d, sizeof bits);
    bits = ee_trunc_w((float)bits * p->Power
                      + (ONE_BITS - p->Power * ONE_BITS));
    memcpy(&k, &bits, sizeof k);
    k = k * intensity;
    size = p->MinSize + (p->MaxSize - p->MinSize) * k;
    if (size <= 0.0f)
        return;
    cx = to_cam->x * p->TowardCamera + pos->x;
    cy = to_cam->y * p->TowardCamera + pos->y;
    cz = to_cam->z * p->TowardCamera + pos->z;
    if (scale < p->MinScale)
        scale = p->MinScale;
    if (p->MaxScale < scale)
        scale = p->MaxScale;
    ext = size * scale;

    epoly_init(&poly);
    rx = right->x * ext;
    ry = right->y * ext;
    rz = right->z * ext;
    ux = up->x * ext;
    uy = up->y * ext;
    uz = up->z * ext;
    r = (uint8_t)ee_trunc_w(p->MinColour[0]
                            + (p->MaxColour[0] - p->MinColour[0]) * k);
    g = (uint8_t)ee_trunc_w(p->MinColour[1]
                            + (p->MaxColour[1] - p->MinColour[1]) * k);
    b = (uint8_t)ee_trunc_w(p->MinColour[2]
                            + (p->MaxColour[2] - p->MinColour[2]) * k);
    a = (uint8_t)ee_trunc_w(p->MinColour[3]
                            + (p->MaxColour[3] - p->MinColour[3]) * k);
    poly.UVs[0][0] = 0.0f;
    poly.UVs[0][1] = 0.0f;
    poly.UVs[1][0] = 1.0f;
    poly.UVs[1][1] = 0.0f;
    poly.UVs[2][0] = 1.0f;
    poly.UVs[2][1] = 1.0f;
    poly.UVs[3][0] = 0.0f;
    poly.UVs[3][1] = 1.0f;
    for (i = 0; i < 4; i++) {
        poly.Colours[i][0] = r;
        poly.Colours[i][1] = g;
        poly.Colours[i][2] = b;
        poly.Colours[i][3] = a;
    }
    // Up and left, up and right, down and right, down and left.
    poly.Vertices[0].x = (cx - rx) + ux;
    poly.Vertices[0].y = (cy - ry) + uy;
    poly.Vertices[0].z = (cz - rz) + uz;
    poly.Vertices[1].x = (cx + rx) + ux;
    poly.Vertices[1].y = (cy + ry) + uy;
    poly.Vertices[1].z = (cz + rz) + uz;
    poly.Vertices[2].x = (cx + rx) - ux;
    poly.Vertices[2].y = (cy + ry) - uy;
    poly.Vertices[2].z = (cz + rz) - uz;
    poly.Vertices[3].x = (cx - rx) - ux;
    poly.Vertices[3].y = (cy - ry) - uy;
    poly.Vertices[3].z = (cz - rz) - uz;
    if (gEPolyRender3DFn != NULL)
        gEPolyRender3DFn(&poly, tex, &eMathIdentityMatrix, 0);
}

int el_render_light_flare(eView *view, eLightFlare *flare,
                          bMatrix4 *local_world, float intensity)
{
    const Camera *cam = view->pCamera;
    const bMatrix4 *m = local_world;
    const bMatrix4 *c, *v;
    const eLightFlarePart *const *parts;
    float px, py, pz, dx, dy, dz, wdx, wdy, wdz;
    float clx, cly, clz, clw, lim, len2, q, facing, depth;
    bVector4 wp, to_cam;
    bVector3 right, up;

    if (flare == NULL || local_world == NULL || cam == NULL)
        return 0;
    if (flare->Enabled == 0)
        return 0;
    px = flare->PositionX;
    py = flare->PositionY;
    pz = flare->PositionZ;
    dx = flare->DirectionX;
    dy = flare->DirectionY;
    dz = flare->DirectionZ;
    wp.x = m->v0.x * px + m->v1.x * py + m->v2.x * pz + m->v3.x;
    wp.y = m->v0.y * px + m->v1.y * py + m->v2.y * pz + m->v3.y;
    wp.z = m->v0.z * px + m->v1.z * py + m->v2.z * pz + m->v3.z;
    wp.w = 0.0f;

    // vclipw: off the screen when any of x, y and z is past |w|.
    c = view->WorldClipMatrix;
    clx = c->v0.x * wp.x + c->v1.x * wp.y + c->v2.x * wp.z + c->v3.x;
    cly = c->v0.y * wp.x + c->v1.y * wp.y + c->v2.y * wp.z + c->v3.y;
    clz = c->v0.z * wp.x + c->v1.z * wp.y + c->v2.z * wp.z + c->v3.z;
    clw = c->v0.w * wp.x + c->v1.w * wp.y + c->v2.w * wp.z + c->v3.w;
    lim = fabsf(clw);
    if (lim < clx || clx < -lim || lim < cly || cly < -lim
        || lim < clz || clz < -lim)
        return 0;

    wdx = m->v0.x * dx + m->v1.x * dy + m->v2.x * dz;
    wdy = m->v0.y * dx + m->v1.y * dy + m->v2.y * dz;
    wdz = m->v0.z * dx + m->v1.z * dy + m->v2.z * dz;
    to_cam.x = cam->CurrentKey.Position.x - wp.x;
    to_cam.y = cam->CurrentKey.Position.y - wp.y;
    to_cam.z = cam->CurrentKey.Position.z - wp.z;
    to_cam.w = 0.0f;
    len2 = to_cam.x * to_cam.x + to_cam.y * to_cam.y + to_cam.z * to_cam.z;
    q = ee_div(1.0f, sqrtf(len2));
    to_cam.x = to_cam.x * q;
    to_cam.y = to_cam.y * q;
    to_cam.z = to_cam.z * q;
    facing = to_cam.x * wdx + to_cam.y * wdy + to_cam.z * wdz;
    // Flags bit 0: lit both ways, as the cops' red and blue are.
    if (flare->Flags & 1)
        facing = fabsf(facing);

    v = view->WorldViewMatrix;
    right.x = v->v0.x;
    right.y = v->v1.x;
    right.z = v->v2.x;
    up.x = v->v0.y;
    up.y = v->v1.y;
    up.z = v->v2.y;
    m = &cam->CurrentKey.Matrix;
    depth = m->v0.z * wp.x + m->v1.z * wp.y + m->v2.z * wp.z + m->v3.z;
    depth = depth / view->H;

    if ((uint8_t)flare->Type >= NUM_LIGHT_FLARE_TYPES)
        return 1;
    parts = LightFlareParameterIndicies[flare->Type];
    if (parts[0] != NULL)
        render_part(parts[0], &wp, &to_cam, &right, &up, intensity, facing,
                    depth);
    if (parts[1] != NULL)
        render_part(parts[1], &wp, &to_cam, &right, &up, intensity, facing,
                    depth);
    return 1;
}

void el_render_world_light_flares(eView *view)
{
    bNode *h, *n;

    if (InGameFlag == 0)
        return;
    for (h = eLightFlarePackList.next; h != &eLightFlarePackList;
         h = h->next) {
        bNode *list = &((eLightFlarePackHeader *)h)->LightFlareList;

        for (n = list->next; n != list; n = n->next)
            el_render_light_flare(view, (eLightFlare *)n,
                                  &eMathIdentityMatrix, 1.0f);
    }
}
