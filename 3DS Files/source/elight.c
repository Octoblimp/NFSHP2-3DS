// elight -- see elight.h.

#include "elight.h"

#include <math.h>
#include <string.h>

#include "bchunk.h"
#include "emath.h"

#define LIGHT_PACK_ID           0x80034015u
#define LIGHT_PACK_HEADER_ID    0x00034016u
#define LIGHT_TREE_ID           0x00034017u
#define LIGHT_ARRAY_ID          0x00034018u
#define LIGHT_FLARE_PACK_ID     0x80034019u
#define LIGHT_FLARE_HEADER_ID   0x0003401au
#define LIGHT_FLARES_ID         0x0003401bu
#define LIGHT_UNUSED_ID         0x0003401cu
#define LIGHT_MATERIALS_ID      0x0003401eu

// bStringHash("Default").
#define DEFAULT_MATERIAL_HASH   0x2c420d64u

// 1.0f's bits, as BuildDmaData has them: a float, 1065353216.0.
#define ONE_BITS                1065353216.0f

bNode eLightFlarePackList = { &eLightFlarePackList, &eLightFlarePackList };
bNode eLightPackList = { &eLightPackList, &eLightPackList };
bNode eLightMaterialList = { &eLightMaterialList, &eLightMaterialList };

static eLightMaterial s_default_material;
eLightMaterial *eDefaultLightMaterial = &s_default_material;

bVector4 elSunDir = { -0.74f, 0.0f, 0.55f, 0.0f };
bVector4 elSunColour = { 80.0f, 80.0f, 80.0f, 0.0f };
bVector4 elAmbientOverride = { 0.0f, 0.0f, 0.0f, 0.0f };

int (*gElInFrontendFn)(void);

void el_init(void)
{
    memset(eDefaultLightMaterial, 0, sizeof *eDefaultLightMaterial);
}

// ------------------------------------------------------------- the lists

static uint8_t *align16(uint8_t *chunk)
{
    return (uint8_t *)(((uintptr_t)chunk + 23u) & ~(uintptr_t)15u);
}

static uint8_t *next_chunk(uint8_t *c)
{
    return c + 8 + bchunk_u32(c + 4);
}

static void add_tail(bNode *list, bNode *n)
{
    bNode *tail = list->prev;

    tail->next = n;
    list->prev = n;
    n->prev = tail;
    n->next = list;
}

static void unlink_node(bNode *n)
{
    n->prev->next = n->next;
    n->next->prev = n->prev;
}

static void load_light_pack(uint8_t *c)
{
    uint8_t *g = c + 8;
    uint8_t *end = next_chunk(c);
    eLightPack *pack = NULL;

    for (; g != end; g = next_chunk(g)) {
        uint32_t type = bchunk_u32(g);

        if (type == LIGHT_PACK_HEADER_ID) {
            pack = (eLightPack *)align16(g);
            if (pack->Version != 1)
                return;
        } else if (type == LIGHT_TREE_ID) {
            vAABBTree *tree = (vAABBTree *)align16(g);

            pack->LightTree = tree;
            tree->NodeArray = (vAABB *)(tree + 1);
        } else if (type == LIGHT_ARRAY_ID) {
            pack->LightArray = (eLight *)align16(g);
        }
    }
    if (pack != NULL)
        add_tail(&eLightPackList, &pack->Node);
}

static void load_light_flares(uint8_t *c)
{
    uint8_t *g = c + 8;
    uint8_t *end = next_chunk(c);
    eLightFlarePackHeader *h = NULL;

    for (; g != end; g = next_chunk(g)) {
        uint32_t type = bchunk_u32(g);

        if (type == LIGHT_FLARE_HEADER_ID) {
            h = (eLightFlarePackHeader *)align16(g);
            if (h->Version == 1) {
                h->LightFlareList.next = &h->LightFlareList;
                h->LightFlareList.prev = &h->LightFlareList;
            } else {
                h = NULL;
            }
        } else if (type == LIGHT_FLARES_ID && h != NULL) {
            eLightFlare *f = (eLightFlare *)align16(g);
            uint32_t n;

            for (n = h->NumLightFlares; n > 0; n--, f++)
                add_tail(&h->LightFlareList, &f->Node);
        }
    }
    if (h != NULL)
        add_tail(&eLightFlarePackList, &h->Node);
}

int loader_light_list(uint8_t *c)
{
    uint32_t type = bchunk_u32(c);

    if (type == LIGHT_PACK_ID) {
        load_light_pack(c);
        return 1;
    }
    if (type == LIGHT_FLARE_PACK_ID) {
        load_light_flares(c);
        return 1;
    }
    if (type == LIGHT_UNUSED_ID)
        return 1;
    if (type == LIGHT_MATERIALS_ID) {
        uint8_t *h = align16(c);
        eLightMaterial *m;
        uint32_t n;

        if (bchunk_u32(h + 8) != 1)
            return 1;
        m = (eLightMaterial *)(h + 16);
        for (n = bchunk_u32(h + 12); n > 0; n--, m++) {
            el_build_material_dma_data(m);
            add_tail(&eLightMaterialList, &m->Node);
            if (m->NameHash == DEFAULT_MATERIAL_HASH)
                eDefaultLightMaterial = m;
        }
        return 1;
    }
    return 0;
}

// The first child of each pack is its header. Retail looks no further
// than that one: it tests the first child's type over and over without
// moving on, so a pack whose header came second would hang it.
int unloader_light_list(uint8_t *c)
{
    uint32_t type = bchunk_u32(c);

    if (type == LIGHT_PACK_ID || type == LIGHT_FLARE_PACK_ID) {
        uint32_t want = type == LIGHT_PACK_ID ? LIGHT_PACK_HEADER_ID
                                              : LIGHT_FLARE_HEADER_ID;
        uint8_t *g = c + 8;
        uint8_t *end = next_chunk(c);

        for (; g != end; g = next_chunk(g)) {
            if (bchunk_u32(g) == want) {
                uint8_t *h = align16(g);

                if (bchunk_u32(h + 8) == 1)
                    unlink_node((bNode *)h);
                break;
            }
        }
        return 1;
    }
    if (type == LIGHT_UNUSED_ID)
        return 1;
    if (type == LIGHT_MATERIALS_ID) {
        uint8_t *h = align16(c);
        eLightMaterial *m;
        eLightMaterial *def = eDefaultLightMaterial;
        uint32_t n;

        if (bchunk_u32(h + 8) != 1)
            return 1;
        m = (eLightMaterial *)(h + 16);
        for (n = bchunk_u32(h + 12); n > 0; n--, m++) {
            unlink_node(&m->Node);
            if (m->NameHash == DEFAULT_MATERIAL_HASH)
                def = &s_default_material;
        }
        eDefaultLightMaterial = def;
        return 1;
    }
    return 0;
}

// ------------------------------------------------------------ materials

static float bits_as_float(float f)
{
    union { float f; int32_t i; } u;

    u.f = f;
    return (float)u.i;
}

void el_build_dma_data(eLightMaterialDma *o, const eLightMaterialData *d)
{
    float m = d->SpecularMax * d->SpecularMaxScale;
    float p = d->SpecularPower * d->SpecularPowerScale;
    float bias = 0.0f;
    float gm = d->GlossMapMax * d->GlossMapMaxScale;
    float gp = d->GlossMapPower * d->GlossMapPowerScale;
    float gbias = 0.0f;
    float half = (d->FresnelMax - d->FresnelMin) * 0.5f;

    if (m == 0.0f)
        p = 0.0f;
    else
        bias = bits_as_float(m) - p * ONE_BITS;
    if (gm == 0.0f)
        gp = 0.0f;
    else
        gbias = bits_as_float(gm) - gp * ONE_BITS;

    o->SpecularPower = p;
    o->SpecularBias = bias;
    o->SpecularMinDot = 0.1f;
    o->CBVMix = d->CBVMix * (1.0f / 255.0f);
    o->DiffuseR = d->DiffuseColourScaleR;
    o->DiffuseG = d->DiffuseColourScaleG;
    o->DiffuseB = d->DiffuseColourScaleB;
    o->FresnelMid = (d->FresnelMin + half) * 128.0f;
    o->SpecularR = d->SpecularColourScaleR;
    o->SpecularG = d->SpecularColourScaleG;
    o->SpecularB = d->SpecularColourScaleB;
    o->FresnelHalf = half * -128.0f;
    o->GlossPower = gp;
    o->GlossBias = gbias;
    o->GlossAlphaMin = d->GlossMapAlphaMin;
    o->GlossAlphaRange = d->GlossMapAlphaMax - d->GlossMapAlphaMin;
}

void el_build_material_dma_data(eLightMaterial *m)
{
    el_build_dma_data(&m->feDmaData, &m->feData);
    el_build_dma_data(&m->igDmaData, &m->igData);
}

eLightMaterial *el_get_light_material(uint32_t name_hash)
{
    bNode *n;

    for (n = eLightMaterialList.next; n != &eLightMaterialList; n = n->next) {
        if (((eLightMaterial *)n)->NameHash == name_hash)
            return (eLightMaterial *)n;
    }
    return eDefaultLightMaterial;
}

eLightMaterial *el_get_default_light_material(void)
{
    return eDefaultLightMaterial;
}

// ------------------------------------------------------------- the tree

int vaabb_contains(const vAABB *b, float x, float y, float z)
{
    if (fabsf(x - b->PositionX) >= b->ExtentX
        || fabsf(y - b->PositionY) >= b->ExtentY
        || fabsf(z - b->PositionZ) >= b->ExtentZ)
        return 0;
    return 1;
}

static vAABB *query_leaf_helper(const vAABBTree *t, const vAABB *node,
                                float x, float y, float z)
{
    int i;

    for (i = 0; i < node->NumChildren; i++) {
        vAABB *child = t->NodeArray + node->ChildrenIndicies[i];

        if (!vaabb_contains(child, x, y, z))
            continue;
        if (child->NumChildren <= 0)
            return child;
        child = query_leaf_helper(t, child, x, y, z);
        if (child != NULL)
            return child;
    }
    return NULL;
}

vAABB *vaabbtree_query_leaf(const vAABBTree *t, float x, float y, float z)
{
    vAABB *root = t->NodeArray;

    if (root == NULL || !vaabb_contains(root, x, y, z))
        return NULL;
    if (root->NumChildren <= 0)
        return root;
    return query_leaf_helper(t, root, x, y, z);
}

// ------------------------------------------------------------ the query

// The colour bytes, from the bottom, and the intensity.
static void light_colour(const eLight *l, float c[4])
{
    c[0] = (float)(l->Colour & 0xffu);
    c[1] = (float)((l->Colour >> 8) & 0xffu);
    c[2] = (float)((l->Colour >> 16) & 0xffu);
    c[3] = l->Intensity;
}

int query_light_database(eLightQuery *q, const bVector3 *pos)
{
    float base[4] = { 0.0f, 0.0f, 0.0f, 1.0f };
    float accum[ELIGHTQUERY_MAX_LIGHTS][4];
    int num_accum = 0;
    float nearest = 3.40282347e38f;
    float total = 0.0f;
    float s, b;
    float out[4];
    int n = 0;
    int i, k;
    bNode *node;

    q->Lights[0] = NULL;
    q->Influences[0] = 0.0f;
    q->AmbientR = q->AmbientG = q->AmbientB = 0.0f;
    q->LightScale = 0.0f;

    for (node = eLightPackList.next;
         node != &eLightPackList && n < ELIGHTQUERY_MAX_LIGHTS
         && num_accum < ELIGHTQUERY_MAX_LIGHTS;
         node = node->next) {
        eLightPack *pack = (eLightPack *)node;
        vAABB *leaf = vaabbtree_query_leaf(pack->LightTree, pos->x, pos->y,
                                           pos->z);
        int count;

        if (leaf == NULL)
            continue;
        count = -leaf->NumChildren;
        for (i = 0; i < count && n < ELIGHTQUERY_MAX_LIGHTS; i++) {
            eLight *l = pack->LightArray + leaf->ChildrenIndicies[i];
            float dx = fabsf(pos->x - l->PositionX);
            float dy = fabsf(pos->y - l->PositionY);
            float dz = fabsf(pos->z - l->PositionZ);
            float d2 = dx * dx + dy * dy + dz * dz;
            float size2 = l->Size * l->Size;
            float infl = 1.0f;
            float fs2;
            float c[4];

            if (!(d2 < size2))
                continue;
            fs2 = l->FarStart * l->FarStart;
            if (fs2 < d2)
                infl = 1.0f - (d2 - fs2) / (size2 - fs2);
            if (l->Type != 0) {
                if (l->Type == 2) {
                    q->Lights[n] = l;
                    q->Influences[n] = infl;
                    n++;
                }
                continue;
            }
            light_colour(l, c);
            if (l->AttenuationType == 2) {
                if (num_accum >= ELIGHTQUERY_MAX_LIGHTS)
                    continue;
                for (k = 0; k < 4; k++)
                    accum[num_accum][k] = c[k] * infl;
                if (0.0f < infl) {
                    total += infl;
                    num_accum++;
                }
            } else if (d2 < nearest) {
                memcpy(base, c, sizeof base);
                nearest = d2;
            }
        }
    }

    // The blended lights are scaled by their total influence again, so a
    // lone light at half strength counts a quarter. Retail's, kept.
    if (1.0f < total) {
        s = 1.0f / total;
        b = 0.0f;
    } else {
        s = total;
        b = 1.0f - total;
    }
    for (k = 0; k < 4; k++)
        out[k] = base[k] * b;
    for (i = 0; i < num_accum; i++)
        for (k = 0; k < 4; k++)
            out[k] += accum[i][k] * s;
    q->AmbientR = out[0];
    q->AmbientG = out[1];
    q->AmbientB = out[2];
    q->LightScale = out[3];
    return n;
}

// ------------------------------------------------------ the light context

// Normalised, as the VU0 does it: every lane times 1/sqrt(x^2+y^2+z^2).
// The port leaves a zero vector at zero.
static void normalize4(bVector4 *o, const bVector4 *v)
{
    float l2 = v->x * v->x + v->y * v->y + v->z * v->z;
    float r = l2 > 0.0f ? 1.0f / sqrtf(l2) : 0.0f;

    o->x = v->x * r;
    o->y = v->y * r;
    o->z = v->z * r;
    o->w = v->w * r;
}

int el_setup_light_context(eLightContext *lc, const bMatrix4 *local_world,
                           const bMatrix4 *hack, const bVector4 *eye,
                           eView *view)
{
    bMatrix4 inv;
    eLightQuery q;
    bVector4 dir[3];
    bVector4 nrm[3];
    float px, py, pz;
    float r, g, b;
    float intensity;
    int n;
    int i;

    (void)view;
    if (lc == NULL || local_world == NULL)
        return -1;
    memset(lc, 0, sizeof *lc);
    eInvertRotationMatrix(&inv, local_world);
    n = query_light_database(&q, (const bVector3 *)&local_world->v3);

    // The directions to the sun, far off, and to the two nearest point
    // lights, into model space. The car-select screen's three fixed
    // directions (gp-21420 == 3) are not ported.
    memset(dir, 0, sizeof dir);
    px = local_world->v3.x;
    py = local_world->v3.y;
    pz = local_world->v3.z;
    dir[0].x = elSunDir.x * 10000.0f - px;
    dir[0].y = elSunDir.y * 10000.0f - py;
    dir[0].z = elSunDir.z * 10000.0f - pz;
    for (i = 0; i < n && i < 2; i++) {
        dir[i + 1].x = q.Lights[i]->PositionX - px;
        dir[i + 1].y = q.Lights[i]->PositionY - py;
        dir[i + 1].z = q.Lights[i]->PositionZ - pz;
    }
    for (i = 0; i < 3; i++) {
        eMulVector3((bVector3 *)&dir[i], &inv, (const bVector3 *)&dir[i]);
        normalize4(&nrm[i], &dir[i]);
    }

    // LocalDirectionMatrix is the three directions as columns, so that a
    // normal times it is the three dot products.
    lc->LocalDirectionMatrix.v0.x = nrm[0].x;
    lc->LocalDirectionMatrix.v0.y = nrm[1].x;
    lc->LocalDirectionMatrix.v0.z = nrm[2].x;
    lc->LocalDirectionMatrix.v1.x = nrm[0].y;
    lc->LocalDirectionMatrix.v1.y = nrm[1].y;
    lc->LocalDirectionMatrix.v1.z = nrm[2].y;
    lc->LocalDirectionMatrix.v2.x = nrm[0].z;
    lc->LocalDirectionMatrix.v2.y = nrm[1].z;
    lc->LocalDirectionMatrix.v2.z = nrm[2].z;
    lc->LocalLightPositions.v0 = dir[0];
    lc->LocalLightPositions.v1 = dir[1];
    lc->LocalLightPositions.v2 = dir[2];
    lc->LocalLightPositions.v0.w = 1.0f;
    lc->LocalLightPositions.v1.w = 1.0f;
    lc->LocalLightPositions.v2.w = 1.0f;

    // The ambient: the override when it is set, else the query's, else a
    // flat 85.
    if (elAmbientOverride.x != 0.0f || elAmbientOverride.y != 0.0f
        || elAmbientOverride.z != 0.0f) {
        r = elAmbientOverride.x;
        g = elAmbientOverride.y;
        b = elAmbientOverride.z;
    } else {
        r = q.AmbientR;
        g = q.AmbientG;
        b = q.AmbientB;
        if (r == 0.0f && g == 0.0f && b == 0.0f)
            r = g = b = 85.0f;
    }
    lc->LocalColourMatrix.v3.x = r;
    lc->LocalColourMatrix.v3.y = g;
    lc->LocalColourMatrix.v3.z = b;
    lc->LocalColourMatrix.v3.w = 128.0f;

    intensity = q.LightScale;
    if (1.0f < intensity)
        intensity = 1.0f;
    else if (intensity < 0.0f)
        intensity = 0.0f;
    lc->SunlightIntensity = intensity;

    // The sun's colour, never below 0.7 of itself, and the point lights'
    // by their influence. Their blue is left 0: retail works it out and
    // never stores it.
    if (intensity < 0.7f)
        intensity = 0.7f;
    lc->LocalColourMatrix.v0.x = intensity * elSunColour.x;
    lc->LocalColourMatrix.v0.y = intensity * elSunColour.y;
    lc->LocalColourMatrix.v0.z = intensity * elSunColour.z;
    for (i = 0; i < n && i < 2; i++) {
        bVector4 *row = &lc->LocalColourMatrix.v1 + i;
        float c[4];

        light_colour(q.Lights[i], c);
        row->x = q.Influences[i] * c[0];
        row->y = q.Influences[i] * c[1];
        row->z = 0.0f;
    }

    if (eye != NULL) {
        bVector4 d;

        d.x = eye->x - px;
        d.y = eye->y - py;
        d.z = eye->z - pz;
        d.w = 1.0f;
        eMulVector4(&lc->LocalEyePosition, &inv, &d);
    }
    if (hack != NULL && eye != NULL) {
        eMulMatrix(&lc->EnvMapMatrix, local_world, hack);
        lc->EnvMapMatrix.v0.w = 0.0f;
        lc->EnvMapMatrix.v1.w = 0.0f;
        lc->EnvMapMatrix.v2.w = 0.0f;
        lc->EnvMapMatrix.v3.x = lc->LocalEyePosition.x;
        lc->EnvMapMatrix.v3.y = lc->LocalEyePosition.y;
        lc->EnvMapMatrix.v3.z = lc->LocalEyePosition.z;
        lc->EnvMapMatrix.v3.w = 0.0f;
    }
    return 1;
}
