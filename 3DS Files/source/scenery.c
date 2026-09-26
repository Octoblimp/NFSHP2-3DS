// scenery -- see scenery.h.

#include "scenery.h"

#include <stdio.h>
#include <stdlib.h>

#include "bchunk.h"
#include "bmath.h"
#include "bmem.h"
#include "eefpu.h"
#include "emath.h"
#include "race.h"

BSlotPool *eModelSlotPool;
void (*gEModelInitFn)(eModel *m, uint32_t name_hash);
void (*gEModelDestroyFn)(eModel *m, int32_t flags);

ScenerySectionHeader *ScenerySectionHeaderTable[SCENERY_MAX_SECTIONS];
bNode ScenerySectionHeaderList;
bNode VisibleZoneList;
eModel *pVisibleZoneBoundaryModel;
int32_t CurrentZoneNumber = -1;        // none yet, in the image's .sdata
int32_t AdvanceFastBlinkSectionNumber;

static void model_init(eModel *m, uint32_t name_hash)
{
    if (gEModelInitFn == NULL) {
        fprintf(stderr, "eModel::Init reached with no seam set\n");
        abort();
    }
    gEModelInitFn(m, name_hash);
}

static void model_destroy(eModel *m, int32_t flags)
{
    if (gEModelDestroyFn == NULL) {
        fprintf(stderr, "~eModel reached with no seam set\n");
        abort();
    }
    gEModelDestroyFn(m, flags);
}

// bOMalloc(eModelSlotPool) and the inline constructor's two stores.
static eModel *model_new(void)
{
    eModel *m = (eModel *)bSlotOMalloc(eModelSlotPool);

    m->NameHash = 0;
    m->Solid = NULL;
    return m;
}

static uint8_t *payload16(uint8_t *chunk)
{
    return (uint8_t *)(((uintptr_t)chunk + 8 + 15) & ~(uintptr_t)15);
}

static uint8_t *next_chunk(uint8_t *chunk)
{
    return chunk + 8 + bchunk_u32(chunk + 4);
}

static void add_head(bNode *list, bNode *n)
{
    bNode *first = list->next;

    list->next = n;
    first->prev = n;
    n->prev = list;
    n->next = first;
}

static void add_tail(bNode *list, bNode *n)
{
    bNode *last = list->prev;

    last->next = n;
    list->prev = n;
    n->prev = last;
    n->next = list;
}

static void unlink_node(bNode *n)
{
    n->prev->next = n->next;
    n->next->prev = n->prev;
}

void scenery_static_init(void)
{
    ScenerySectionHeaderList.prev = &ScenerySectionHeaderList;
    VisibleZoneList.prev = &VisibleZoneList;
    ScenerySectionHeaderList.next = &ScenerySectionHeaderList;
    VisibleZoneList.next = &VisibleZoneList;
}

// bTList<T>'s destructor: each node unlinked and deleted, which for a bNode
// is __builtin_delete, bFree.
static void close_list(bNode *list)
{
    while (list->next != list) {
        bNode *n = list->next;

        unlink_node(n);
        bFree(n);
    }
}

void scenery_static_close(void)
{
    close_list(&VisibleZoneList);
    close_list(&ScenerySectionHeaderList);
}

int32_t scenery_loader(uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);

    if (type == SCENERY_CONTAINER_ID) {
        ScenerySectionHeader *h = NULL;
        uint8_t *c, *end = next_chunk(chunk);
        int32_t i, k;

        for (c = chunk + 8; c != end; c = next_chunk(c)) {
            uint32_t id = bchunk_u32(c), size = bchunk_u32(c + 4);

            if (id == SCENERY_HEADER_ID) {
                h = (ScenerySectionHeader *)(void *)payload16(c);
                ScenerySectionHeaderTable[h->SectionNumber] = h;
                if (h->SectionNumber < 90)
                    add_tail(&ScenerySectionHeaderList, &h->Node);
                else
                    add_head(&ScenerySectionHeaderList, &h->Node);
            } else if (id == SCENERY_INFO_ID) {
                h->pSceneryInfo = (SceneryInfo *)(void *)(c + 8);
                h->NumSceneryInfo = (int32_t)(size / sizeof(SceneryInfo));
            } else if (id == SCENERY_INSTANCE_ID) {
                uint8_t *a = payload16(c);

                h->pSceneryInstance = (SceneryInstance *)(void *)a;
                h->NumSceneryInstances = (int32_t)(
                    (size - (uint32_t)(a - (c + 8)))
                    / sizeof(SceneryInstance));
            } else if (id == SCENERY_TREE_ID) {
                h->SceneryTreeNodeTable = (SceneryTreeNode *)(void *)(c + 8);
                h->NumSceneryTreeNodes =
                    (int32_t)(size / sizeof(SceneryTreeNode));
            }
        }
        // The pointer is stored before Init is called; a LOD with no name
        // keeps the disc's 0.
        for (i = 0; i < h->NumSceneryInfo; i++) {
            SceneryInfo *info = &h->pSceneryInfo[i];

            for (k = 0; k < 3; k++) {
                if (info->NameHash[k] != 0) {
                    eModel *m = model_new();

                    info->pModel[k] = m;
                    model_init(m, info->NameHash[k]);
                }
            }
        }
        if (RaceParametersTrackDirection == TRACK_DIRECTION_BACKWARD)
            scenery_flip_objects_on_backwards_track(h);
        return 1;
    }
    if (type == VISIBLE_ZONE_ID) {
        int32_t n = (int32_t)(bchunk_u32(chunk + 4) / sizeof(VisibleZone));
        int32_t i;

        for (i = 0; i < n; i++) {
            VisibleZone *z = (VisibleZone *)(void *)(chunk + 8) + i;

            add_tail(&VisibleZoneList, &z->Node);
            z->pCaffeineObj = NULL;
        }
        return 1;
    }
    return 0;
}

int32_t scenery_unloader(uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);

    if (type == SCENERY_CONTAINER_ID) {
        ScenerySectionHeader *h =
            (ScenerySectionHeader *)(void *)payload16(chunk + 8);
        int32_t i, k;

        unlink_node(&h->Node);
        ScenerySectionHeaderTable[h->SectionNumber] = NULL;
        for (i = 0; i < h->NumSceneryInfo; i++) {
            SceneryInfo *info = &h->pSceneryInfo[i];

            for (k = 0; k < 3; k++)
                if (info->pModel[k] != NULL)
                    model_destroy(info->pModel[k], 3);
        }
        return 1;
    }
    if (type == VISIBLE_ZONE_ID) {
        int32_t n = (int32_t)(bchunk_u32(chunk + 4) / sizeof(VisibleZone));
        int32_t i;

        for (i = 0; i < n; i++)
            unlink_node(&((VisibleZone *)(void *)(chunk + 8) + i)->Node);
        return 1;
    }
    return 0;
}

SceneryInfo *scenery_find_info(uint32_t name_hash)
{
    bNode *n;
    int32_t i;

    for (n = ScenerySectionHeaderList.next; n != &ScenerySectionHeaderList;
         n = n->next) {
        ScenerySectionHeader *h = (ScenerySectionHeader *)(void *)n;

        for (i = 0; i < h->NumSceneryInfo; i++)
            if (h->pSceneryInfo[i].NameHash[0] == name_hash)
                return &h->pSceneryInfo[i];
    }
    return NULL;
}

SceneryInstance *scenery_find_instance_by_hash(uint32_t name_hash)
{
    bNode *n;
    int32_t i;

    for (n = ScenerySectionHeaderList.next; n != &ScenerySectionHeaderList;
         n = n->next) {
        ScenerySectionHeader *h = (ScenerySectionHeader *)(void *)n;

        for (i = 0; i < h->NumSceneryInstances; i++) {
            SceneryInstance *s = &h->pSceneryInstance[i];

            if (h->pSceneryInfo[s->SceneryInfoNumber].NameHash[0]
                == name_hash)
                return s;
        }
    }
    return NULL;
}

SceneryInstance *scenery_find_instance(int32_t section, int32_t index)
{
    ScenerySectionHeader *h = ScenerySectionHeaderTable[section];

    if (h == NULL)
        return NULL;
    return &h->pSceneryInstance[index];
}

// Both halves of the test are `a <= y && y < b`, so a vertex on the line
// counts for the edge above it and not the one below, and a NaN counts for
// neither.
int32_t scenery_is_point_in_poly(const bVector2 *pt, const bVector2 *poly,
                                 int32_t n)
{
    float x = pt->x, y = pt->y;
    int32_t i, j = n - 1, c = 0;

    for (i = 0; i < n; j = i++) {
        const bVector2 *pi = &poly[i], *pj = &poly[j];

        if ((pi->y <= y && y < pj->y) || (pj->y <= y && y < pi->y)) {
            float xc = (pj->x - pi->x) * (y - pi->y) / (pj->y - pi->y)
                       + pi->x;

            if (x < xc)
                c = !c;
        }
    }
    return c;
}

VisibleZone *scenery_find_visible_zone(const bVector2 *pt)
{
    bNode *n;

    for (n = VisibleZoneList.next; n != &VisibleZoneList; n = n->next) {
        VisibleZone *z = (VisibleZone *)(void *)n;

        if (scenery_is_point_in_poly(pt, z->PerimeterPoints,
                                     z->NumPerimeterPoints)) {
            unlink_node(n);
            add_head(&VisibleZoneList, n);
            return z;
        }
    }
    return NULL;
}

// A count past 64 reads on into NumPerimeterPoints and the corners, as the
// image does. The shorts are reached from the zone, not through the array,
// so the compiler cannot take the array's length as a bound on the count.
int32_t visible_zone_find_index_to(const VisibleZone *z, int32_t section)
{
    const int16_t *s = (const int16_t *)(const void *)((const uint8_t *)z
        + offsetof(VisibleZone, VisibleScenerySections));
    int32_t i;

    for (i = 0; i < z->NumVisibleScenerySections; i++)
        if (s[i] == section)
            return i;
    return -1;
}

int32_t visible_zone_find_next_free_index(VisibleZone *z)
{
    int32_t i = visible_zone_find_index_to(z, -1);

    if (i >= 0)
        return i;
    i = z->NumVisibleScenerySections;
    if (i == VISIBLE_ZONE_MAX_SECTIONS)
        return -1;
    z->NumVisibleScenerySections = i + 1;
    return i;
}

void scenery_init_visible_zones(void)
{
    eModel *m = model_new();

    model_init(m, bchunk_hash("MARKER_BOUNDARY"));
    pVisibleZoneBoundaryModel = m;
}

void scenery_close_visible_zones(void)
{
    if (pVisibleZoneBoundaryModel != NULL)
        model_destroy(pVisibleZoneBoundaryModel, 3);
    pVisibleZoneBoundaryModel = NULL;
}

void scenery_handle_joystick_blink_section(int32_t step)
{
    if (step == 1 || step == -1)
        AdvanceFastBlinkSectionNumber = step;
}

int32_t scenery_get_current_zone_number(void)
{
    return CurrentZoneNumber;
}

int32_t scenery_is_in_table(const int16_t *table, int32_t n, int32_t value)
{
    int32_t i;

    for (i = 0; i < n; i++)
        if (table[i] == value)
            return i;
    return -1;
}

// A value already there is struck out with -1 and the count stays; a new
// one goes in at n mod max, over whatever was there once the table is full.
int32_t scenery_toggle_is_in_table(int16_t *table, int32_t n, int32_t max,
                                   int32_t value)
{
    int32_t i = scenery_is_in_table(table, n, value);

    if (i >= 0) {
        table[i] = -1;
        return n;
    }
    table[n % max] = (int16_t)value;
    return n + 1;
}

void scenery_create_facade_matrix(bMatrix4 *m, const bVector3 *pos,
                                  const bVector3 *eye)
{
    int32_t a = bATan(pos->x - eye->x, pos->y - eye->y);

    eRotateZ(m, &eMathIdentityMatrix, (uint16_t)a);
    m->v3.x = pos->x;
    m->v3.y = pos->y;
    m->v3.z = pos->z;
    m->v3.w = 1.0f;
}

// Each flagged object's rotation is turned half round about z. The listing
// then copies the position into the matrix and straight back, which leaves
// it as it was, so the objects turn where they stand.
void scenery_flip_objects_on_backwards_track(ScenerySectionHeader *h)
{
    int32_t i, r, k;

    for (i = 0; i < h->NumSceneryInstances; i++) {
        SceneryInstance *s = &h->pSceneryInstance[i];
        bMatrix4 m;
        float *row[3];

        if (!(s->ExcludeFlags & SCENERY_FLIP_ON_BACKWARDS))
            continue;
        row[0] = &m.v0.x;
        row[1] = &m.v1.x;
        row[2] = &m.v2.x;
        for (r = 0; r < 3; r++) {
            for (k = 0; k < 3; k++)
                row[r][k] = (float)s->Rotation[3 * r + k] * (1.0f / 16384.0f);
            row[r][3] = 0.0f;
        }
        m.v3.x = 0.0f;
        m.v3.y = 0.0f;
        m.v3.z = 0.0f;
        m.v3.w = 1.0f;
        eRotateZ(&m, &m, 0x8000);
        for (r = 0; r < 3; r++)
            for (k = 0; k < 3; k++)
                s->Rotation[3 * r + k] =
                    (int16_t)ee_trunc_w(row[r][k] * 16384.0f);
    }
}
