// skids -- see skids.h.

#include "skids.h"

#include <math.h>
#include <stdint.h>

#include "bchunk.h"
#include "car.h"
#include "eefpu.h"
#include "emath.h"
#include "epoly.h"
#include "eview.h"
#include "eviewmatrix.h"
#include "realtime.h"
#include "scenerycull.h"
#include "wheel.h"

bNode        SkidSetList = { &SkidSetList, &SkidSetList };
BSlotPool   *SkidSetSlotPool;
int32_t      PlotSkidsInCaffeine;
int32_t      PlotSkidPointsInCaffeine;
TextureInfo *SkidTextureInfo[NUM_TERRAIN_TYPES];
bNode        ClanList = { &ClanList, &ClanList };
BSlotPool   *ClanSlotPool;

// The .sdata floats at gp-29164, gp-29160 and gp-29152: a turn that ends a
// set and one that moves its last point, both as 1 - cos, and a byte's
// intensity back to a float.
static const float SkidTurnLimit      = 0.2f;
static const float SkidStraightLimit  = 0.002f;
static const float SkidIntensityScale = 1.0f / 255.0f;

// MaybeMakeSkids' two, gp-29264 and gp-29260 (0x3eaaaaab and 0x3e99999a):
// a pressing wheel's share of the intensity, and the least intensity.
static const float SkidPressOnly      = 1.0f / 3.0f;
static const float SkidMinIntensity   = 0.3f;

// The drawing's, gp-29156 and gp-29148 (0x3d4ccccd and 0x422aaaab): how
// far above the ground a mark is drawn, and the fade a pixel past 4.
static const float SkidRaise          = 0.05f;
static const float SkidFadeScale      = 42.666668f;

static void add_head(bNode *list, bNode *n)
{
    bNode *head = list->next;

    list->next = n;
    head->prev = n;
    n->prev = list;
    n->next = head;
}

static void add_tail(bNode *list, bNode *n)
{
    bNode *tail = list->prev;

    tail->next = n;
    list->prev = n;
    n->next = list;
    n->prev = tail;
}

static void unlink_node(bNode *n)
{
    n->prev->next = n->next;
    n->next->prev = n->prev;
}

// VisibleViewBits' players 1 and 2 (eview.h's IDs), both: `sra 1 ; andi
// 1`, and `sra 2 ; andi 1` only when that is set. The image reads the car
// whatever it is.
static int32_t visible_to_both_players(const Car *car)
{
    uint32_t bits;

    if (car == NULL)
        return 0;
    bits = car->TheOverrideRenderingPosition.VisibleViewBits;
    if (((bits >> 1) & 1u) == 0)
        return 0;
    return (int32_t)((bits >> 2) & 1u);
}

// ------------------------------------------------------------ SkidSegment

void skid_segment_set_points(SkidSegment *s, const bVector3 *pos,
                             const bVector3 *delta)
{
    s->Position[0] = pos->x;
    s->Position[1] = pos->y;
    s->Position[2] = pos->z;
    s->DeltaPosition[0] = (int8_t)ee_trunc_w(delta->x * 64.0f);
    s->DeltaPosition[1] = (int8_t)ee_trunc_w(delta->y * 64.0f);
    s->DeltaPosition[2] = (int8_t)ee_trunc_w(delta->z * 64.0f);
}

void skid_segment_get_points(const SkidSegment *s, bVector3 *pos,
                             bVector3 *delta)
{
    pos->x = s->Position[0];
    pos->y = s->Position[1];
    pos->z = s->Position[2];
    if (delta != NULL) {
        delta->x = (float)s->DeltaPosition[0] * (1.0f / 64.0f);
        delta->y = (float)s->DeltaPosition[1] * (1.0f / 64.0f);
        delta->z = (float)s->DeltaPosition[2] * (1.0f / 64.0f);
    }
}

void skid_segment_get_end_points(const SkidSegment *s, bVector3 *a,
                                 bVector3 *b)
{
    float dx = (float)s->DeltaPosition[0] * (1.0f / 64.0f);
    float dy = (float)s->DeltaPosition[1] * (1.0f / 64.0f);
    float dz = (float)s->DeltaPosition[2] * (1.0f / 64.0f);

    a->x = s->Position[0] + dx;
    a->y = s->Position[1] + dy;
    a->z = s->Position[2] + dz;
    b->x = s->Position[0] - dx;
    b->y = s->Position[1] - dy;
    b->z = s->Position[2] - dz;
}

// ---------------------------------------------------------------- SkidSet

SkidSet *skidset_construct(SkidSet *s, SkidMaker *maker, Car *car,
                           const bVector3 *pos, const bVector3 *delta,
                           int32_t terrain, float intensity)
{
    Clan   *clan;
    bPNode *node;

    s->TheTerrainType = terrain;
    s->NumSkidSegments = 0;
    s->pSkidMaker = maker;
    s->pCar = car;
    s->bVisibleToBothPlayers = visible_to_both_players(car);
    s->Position = *pos;
    bInitializeBoundingBox3At(&s->BBoxMin, &s->BBoxMax, pos);
    s->Centre = *pos;
    clan = get_clan(pos);
    s->pClan = clan;
    node = bpnode_malloc();
    s->pClanNode = node;
    add_tail(&clan->SkidSetList, &node->Node);
    node->Object = s;
    skidset_add_segment(s, pos, delta, intensity);
    return s;
}

void skidset_destroy(SkidSet *s, int32_t flags)
{
    if (s->pSkidMaker != NULL)
        skidmaker_make_no_skid(s->pSkidMaker);
    // bPList<SkidSet>::Remove: off the clan's list, and ~bPNode with 3.
    unlink_node(&s->pClanNode->Node);
    bpnode_free(s->pClanNode);
    if ((flags & 1) != 0)
        bSlotFree(SkidSetSlotPool, s);
}

int32_t skidset_add_segment(SkidSet *s, const bVector3 *pos,
                            const bVector3 *delta, float intensity)
{
    SkidSegment *seg;
    bVector3     way = { 0.0f, 0.0f, 0.0f, 0.0f };
    float        step = 0.0f;
    int32_t      n = s->NumSkidSegments;
    int32_t      merge = 0;

    if (n > 0) {
        const SkidSegment *last = &s->SkidSegments[n - 1];
        float len2, q;

        way.x = pos->x - last->Position[0];
        way.y = pos->y - last->Position[1];
        way.z = pos->z - last->Position[2];
        len2 = (way.x * way.x + way.y * way.y) + way.z * way.z;
        step = sqrtf(len2);
        // vrsqrt, whose 1/0 is FLT_MAX: a step of nothing has no way.
        q = ee_div(1.0f, sqrtf(len2));
        way.x *= q;
        way.y *= q;
        way.z *= q;
    }
    if (n >= 2) {
        float turn = 1.0f - ((way.x * s->LastNormal.x
                              + way.y * s->LastNormal.y)
                             + way.z * s->LastNormal.z);
        float len = s->LastSegmentLength + step;

        if (SkidTurnLimit < turn) {
            skidset_finished_adding_skids(s);
            return 0;
        }
        if (len < 0.25f)
            merge = 1;
        if (turn < SkidStraightLimit)
            merge = 1;
        if (3.0f < len)
            merge = 0;
    }
    if (merge) {
        seg = &s->SkidSegments[n - 1];
        s->LastSegmentLength = s->LastSegmentLength + step;
    } else {
        if (n == SKIDSET_MAX_SEGMENTS)
            return 1;
        seg = &s->SkidSegments[n];
        s->NumSkidSegments = n + 1;
        if (n + 1 >= 2)
            s->LastNormal = way;
        s->LastSegmentLength = step;
    }
    skid_segment_set_points(seg, pos, delta);
    seg->Intensity = (uint8_t)ee_trunc_w(intensity * 255.0f);
    bExpandBoundingBox3R(&s->BBoxMin, &s->BBoxMax, pos, step);
    clan_expand_bounding_box(s->pClan, &s->BBoxMin, &s->BBoxMax);
    s->Centre.x = (s->BBoxMin.x + s->BBoxMax.x) * 0.5f;
    s->Centre.y = (s->BBoxMin.y + s->BBoxMax.y) * 0.5f;
    s->Centre.z = (s->BBoxMin.z + s->BBoxMax.z) * 0.5f;
    s->Centre.pad = (s->BBoxMin.pad + s->BBoxMax.pad) * 0.5f;
    return 0;
}

void skidset_finished_adding_skids(SkidSet *s)
{
    if (s->pSkidMaker != NULL) {
        s->pSkidMaker->pSkidSet = NULL;
        s->pSkidMaker = NULL;
    }
}

void skidset_finished_adding_seam(void *s)
{
    skidset_finished_adding_skids((SkidSet *)s);
}

void skidset_get_last_points(const SkidSet *s, bVector3 *pos,
                             bVector3 *delta)
{
    skid_segment_get_points(&s->SkidSegments[s->NumSkidSegments - 1], pos,
                            delta);
}

SkidSet *create_new_skid_set(SkidMaker *maker, Car *car, const bVector3 *pos,
                             const bVector3 *delta, int32_t terrain,
                             float intensity)
{
    SkidSet *s;

    if (bIsSlotPoolFull(SkidSetSlotPool)) {
        SkidSet *tail = (SkidSet *)(void *)SkidSetList.prev;

        unlink_node(&tail->Node);
        skidset_destroy(tail, 3);
    }
    s = skidset_construct((SkidSet *)bSlotMalloc(SkidSetSlotPool), maker,
                          car, pos, delta, terrain, intensity);
    add_head(&SkidSetList, &s->Node);
    return s;
}

void skidmaker_make_skid(SkidMaker *m, Car *car, const bVector3 *pos,
                         const bVector3 *delta, int32_t terrain,
                         float intensity)
{
    SkidSet *s;
    bVector3 last_pos = { 0.0f, 0.0f, 0.0f, 0.0f };
    bVector3 last_delta = { 0.0f, 0.0f, 0.0f, 0.0f };
    float    last_intensity;

    if (car != NULL) {
        const bVector3 *g = &car->State.GeometryPosition;
        float dx = g->x - pos->x;
        float dy = g->y - pos->y;
        float dz = g->z - pos->z;

        if (4.0f < sqrtf((dx * dx + dy * dy) + dz * dz))
            return;
    }
    s = (SkidSet *)m->pSkidSet;
    if (s == NULL) {
        m->pSkidSet = create_new_skid_set(m, car, pos, delta, terrain,
                                          intensity);
        return;
    }
    if (visible_to_both_players(car) == s->bVisibleToBothPlayers
        && s->TheTerrainType == terrain
        && skidset_add_segment(s, pos, delta, intensity) == 0)
        return;
    // A new set from the last point of this one, at its last intensity.
    // The image reads the maker's set again, which is still this one: a
    // set that finished itself on a turn answered 0 and returned above.
    s = (SkidSet *)m->pSkidSet;
    skidset_get_last_points(s, &last_pos, &last_delta);
    s = (SkidSet *)m->pSkidSet;
    last_intensity = (float)s->SkidSegments[s->NumSkidSegments - 1].Intensity
                     * SkidIntensityScale;
    skidset_finished_adding_skids(s);
    s = create_new_skid_set(m, car, &last_pos, &last_delta, terrain,
                            last_intensity);
    skidset_add_segment(s, pos, delta, intensity);
    m->pSkidSet = s;
}

void skidmaker_make_no_skid(SkidMaker *m)
{
    if (m->pSkidSet != NULL)
        skidset_finished_adding_skids((SkidSet *)m->pSkidSet);
}

// The two edges' heights. GetElevation is passed no terrain, no normal
// and no bool; with no topology system the ground is at 0.
static float edge_height(const Wheel *w, const bVector3 *pos)
{
    if (gTopologyGetElevationFn == NULL)
        return 0.0f;
    return gTopologyGetElevationFn(
        ((const CarState *)w->CS)->pTopologyCoordinate, pos, NULL, NULL);
}

void skids_maybe_make_skids(Wheel *w, Car *car, float dt)
{
    static const bVector3 ahead = { 0.0f, 1.0f, 0.0f, 0.0f };
    const bVector4 *place = &w->WorldMatrix.v3;
    bVector3        across, fwd, a, b, point;
    float           len2, q, d, wide, half, ha, hb, intensity;
    int32_t         hard, blown;

    (void)dt;
    hard = 8.0f < w->ZForce * w->TractionUsage;
    // lb and srav: the bits as a signed byte.
    blown = ((int32_t)(int8_t)car->BlownTireBits >> w->WI->WheelNumber) & 1;
    if (!(w->Slipping || hard) || !w->TouchingGround || blown
        || !(1.0f < sqrtf(w->Velocity.x * w->Velocity.x
                          + w->Velocity.y * w->Velocity.y))) {
        skidmaker_make_no_skid(&w->TheSkidMaker);
        return;
    }

    // Across the wheel's way in the plane, as a unit vector: vrsqrt.
    across.x = -w->Velocity.y;
    across.y = w->Velocity.x;
    across.z = 0.0f;
    across.pad = 0.0f;
    len2 = (across.x * across.x + across.y * across.y) + across.z * across.z;
    q = ee_div(1.0f, sqrtf(len2));
    across.x *= q;
    across.y *= q;
    across.z *= q;

    // How much the wheel slides sideways: 0 rolling straight, 1 broadside.
    bRotateVector(&fwd, &w->WorldMatrix, &ahead);
    d = fabsf((fwd.x * across.x + fwd.y * across.y) + fwd.z * across.z);

    wide = d;
    if (d < 0.5f)
        wide = 0.5f;
    half = w->WI->Width * TerrainTypeInfoTable[w->Terrain].SkidWidthMultiplier;
    half = half * wide;
    half = half * 0.5f;
    bNormalize3To(&across, &across, half);

    // The two edges, on the ground under each.
    a.x = place->x + across.x;
    a.y = place->y + across.y;
    a.z = place->z + across.z;
    a.pad = place->w + across.pad;
    b.x = place->x - across.x;
    b.y = place->y - across.y;
    b.z = place->z - across.z;
    b.pad = place->w - across.pad;
    ha = edge_height(w, &a);
    hb = edge_height(w, &b);
    point.x = place->x;
    point.y = place->y;
    point.z = (ha + hb) * 0.5f;
    point.pad = 0.0f;
    across.z = ha * 0.5f - hb * 0.5f;
    bNormalize3To(&across, &across, half);

    intensity = d;
    if (!w->Slipping)
        intensity = intensity * SkidPressOnly;
    if (w->Terrain == TERRAIN_TYPE_PUDDLE)
        intensity = 0.0f;
    else if (intensity < SkidMinIntensity)
        intensity = SkidMinIntensity;
    skidmaker_make_skid(&w->TheSkidMaker, car, &point, &across, w->Terrain,
                        intensity);
}

void init_skids(void)
{
    int32_t i;

    if (SkidSetSlotPool == NULL) {
        SkidSetSlotPool = bNewSlotPool((int)sizeof(SkidSet),
                                       SKIDSET_POOL_SLOTS, "SkidSetSlotPool",
                                       16);
        bClearSlotPoolFlag(SkidSetSlotPool, BSP_OVERFLOW_IF_FULL);
    }
    for (i = 0; i < NUM_TERRAIN_TYPES; i++) {
        const char *name = TerrainTypeInfoTable[i].SkidTextureName;

        SkidTextureInfo[i] = NULL;
        if (name != NULL)
            SkidTextureInfo[i] = GetTextureInfo(bchunk_hash(name), 1, 0);
    }
    PlotSkidsInCaffeine = 0;
    PlotSkidPointsInCaffeine = 0;
}

void close_skids(void)
{
    int32_t i;

    if (SkidSetSlotPool != NULL) {
        bDeleteSlotPool(SkidSetSlotPool);
        SkidSetSlotPool = NULL;
    }
    for (i = NUM_TERRAIN_TYPES - 1; i >= 0; i--)
        SkidTextureInfo[i] = NULL;
}

void delete_this_skid(SkidSet *s)
{
    unlink_node(&s->Node);
    skidset_destroy(s, 3);
}

// ------------------------------------------------------------------ Clan

Clan *clan_construct(Clan *c, const bVector3 *pos, uint32_t hash)
{
    c->SkidSetList.next = &c->SkidSetList;
    c->SkidSetList.prev = &c->SkidSetList;
    c->Position = *pos;
    c->Hash = hash;
    bInitializeBoundingBox3At(&c->BBoxMin, &c->BBoxMax, pos);
    return c;
}

void clan_destroy(Clan *c, int32_t flags)
{
    bNode *list = &c->SkidSetList;

    while (list->next != list)
        delete_this_skid((SkidSet *)((bPNode *)(void *)list->next)->Object);
    if ((flags & 1) != 0)
        bSlotFree(ClanSlotPool, c);
}

void clan_expand_bounding_box(Clan *c, const bVector3 *mn,
                              const bVector3 *mx)
{
    bExpandBoundingBox3Box(&c->BBoxMin, &c->BBoxMax, mn, mx);
}

void init_clans(void)
{
    if (ClanSlotPool == NULL)
        ClanSlotPool = bNewSlotPool((int)sizeof(Clan), CLAN_POOL_SLOTS,
                                    "ClanSlotPool", 16);
}

void flush_clans(void)
{
    bNode *n;

    for (n = ClanList.next; n != &ClanList; n = ClanList.next) {
        unlink_node(n);
        clan_destroy((Clan *)(void *)n, 3);
    }
}

void close_clans(void)
{
    if (ClanSlotPool != NULL) {
        flush_clans();
        bDeleteSlotPool(ClanSlotPool);
        ClanSlotPool = NULL;
    }
}

Clan *get_clan(const bVector3 *pos)
{
    int32_t  x = ee_trunc_w(pos->x * 65536.0f);
    int32_t  y = ee_trunc_w(pos->y * 65536.0f);
    uint32_t hash = ((uint32_t)(y >> 22) << 16)
                    + ((uint32_t)(x >> 22) & 0xffffu);
    bNode   *n;
    Clan    *c;

    for (n = ClanList.next; n != &ClanList; n = n->next) {
        c = (Clan *)(void *)n;
        if (c->Hash == hash) {
            unlink_node(n);
            c->LastUpdateTime = WorldTime;
            add_head(&ClanList, n);
            return c;
        }
    }
    if (bIsSlotPoolFull(ClanSlotPool)) {
        bNode *tail = ClanList.prev;

        unlink_node(tail);
        clan_destroy((Clan *)(void *)tail, 3);
    }
    c = clan_construct((Clan *)bSlotOMalloc(ClanSlotPool), pos, hash);
    add_head(&ClanList, &c->Node);
    return c;
}

// ------------------------------------------------------------- the drawing

static void raised_corner(bVector4 *v, const bVector3 *p)
{
    v->x = p->x;
    v->y = p->y;
    v->z = p->z + SkidRaise;
}

// A corner's alpha, from its point's intensity: `sltu`, then the
// difference's byte, then `srl 1`.
static uint8_t faded_alpha(uint32_t intensity, uint32_t fade)
{
    uint32_t a = intensity < fade ? 0u : (intensity - fade) & 0xffu;

    return (uint8_t)(a >> 1);
}

void skidset_render(SkidSet *s, uint8_t fade)
{
    ePoly   poly;
    int32_t i;

    if (SkidTextureInfo[s->TheTerrainType] == NULL)
        return;
    epoly_init(&poly);
    for (i = 0; i < s->NumSkidSegments - 1; i++) {
        const SkidSegment *a = &s->SkidSegments[i];
        const SkidSegment *b = &s->SkidSegments[i + 1];
        bVector3           e0, e1, e2, e3;
        uint8_t            aa, ab;

        skid_segment_get_end_points(a, &e0, &e3);
        skid_segment_get_end_points(b, &e1, &e2);
        raised_corner(&poly.Vertices[0], &e0);
        raised_corner(&poly.Vertices[1], &e1);
        raised_corner(&poly.Vertices[2], &e2);
        raised_corner(&poly.Vertices[3], &e3);
        aa = faded_alpha(a->Intensity, fade);
        ab = faded_alpha(b->Intensity, fade);
        poly.Colours[0][3] = aa;
        poly.Colours[1][3] = ab;
        poly.Colours[2][3] = ab;
        poly.Colours[3][3] = aa;
        if (gEPolyRender3DFn != NULL)
            gEPolyRender3DFn(&poly, SkidTextureInfo[s->TheTerrainType],
                             &eMathIdentityMatrix, 0);
    }
}

void render_skids(Clan *c, bMatrix4 *clip, eView *view)
{
    bNode *n;

    if ((int8_t)view->OverrideRendering != 0)
        return;
    for (n = c->SkidSetList.next; n != &c->SkidSetList; n = n->next) {
        SkidSet        *s = (SkidSet *)((bPNode *)(void *)n)->Object;
        const bVector3 *eye;
        int32_t         vis;
        float           dx, dy, dz, px;
        uint8_t         fade;

        vis = scenery_is_bounding_box_visible(&s->BBoxMin, &s->BBoxMax, clip);
        if (s->pCar != NULL)
            vis &= (int32_t)((s->pCar->TheOverrideRenderingPosition
                                  .VisibleViewBits
                              >> ((uint32_t)view->ID & 31u)) & 1u);
        if (vis == 0)
            continue;
        eye = &view->pCamera->CurrentKey.Position;
        dx = s->Centre.x - eye->x;
        dy = s->Centre.y - eye->y;
        dz = s->Centre.z - eye->z;
        px = (float)eview_get_pixel_size(view, 1.0f,
                                         sqrtf((dx * dx + dy * dy) + dz * dz));
        if (!(4.0f < px))
            continue;
        fade = 0;
        if (!(10.0f < px))
            fade = (uint8_t)ee_trunc_w(256.0f - (px - 4.0f) * SkidFadeScale);
        skidset_render(s, fade);
        unlink_node(&s->Node);
        add_head(&SkidSetList, &s->Node);
    }
}

void render_clans(bMatrix4 *clip, eView *view)
{
    bNode *n, *next;

    for (n = ClanList.next; n != &ClanList; n = next) {
        Clan *c = (Clan *)(void *)n;

        next = n->next;
        if (eview_get_pixel_size_box(view, &c->BBoxMin, &c->BBoxMax) < 11)
            continue;
        if (scenery_is_bounding_box_visible(&c->BBoxMin, &c->BBoxMax, clip)
            == 0)
            continue;
        if (300 < (int32_t)((uint32_t)WorldTime
                            - (uint32_t)c->LastUpdateTime)) {
            c->LastUpdateTime = WorldTime;
            unlink_node(n);
            add_head(&ClanList, n);
        }
        render_skids(c, clip, view);
    }
}
