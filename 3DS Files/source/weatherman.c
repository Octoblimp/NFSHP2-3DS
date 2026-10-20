// weatherman -- see weatherman.h.

#include "weatherman.h"

#include <math.h>
#include <string.h>

#include "bchunk.h"
#include "bmath.h"
#include "eefpu.h"
#include "realtime.h"

bNode WeatherRegionLists[WEATHER_NUM_TYPES] = {
    { &WeatherRegionLists[0], &WeatherRegionLists[0] },
    { &WeatherRegionLists[1], &WeatherRegionLists[1] },
    { &WeatherRegionLists[2], &WeatherRegionLists[2] },
    { &WeatherRegionLists[3], &WeatherRegionLists[3] },
};
bNode WeatherRegionInactiveList = {
    &WeatherRegionInactiveList, &WeatherRegionInactiveList
};

bNode *WeatherRainList = &WeatherRegionLists[WEATHER_RAIN];
bNode *WeatherFogList  = &WeatherRegionLists[WEATHER_FOG];
bNode *WeatherSnowList = &WeatherRegionLists[WEATHER_SNOW];
bNode *WeatherWindList = &WeatherRegionLists[WEATHER_WIND];

int32_t WeatherUseTweakerValues;
float   WeatherFog;
float   WeatherFogStart;
int32_t WeatherFogColourR;
int32_t WeatherFogColourG;
int32_t WeatherFogColourB;
int32_t WeatherHeavyFog;

WeatherQuery CachedWeatherQueries[EVIEW_NUM_VIEWS];

// What the query starts its nearest root at, 0x00321838.
#define WEATHER_FAR 9999999.0f

void WeatherManInit(void)
{
}

void WeatherManClose(void)
{
}

// ------------------------------------------------------------ the lists

static void add_tail(bNode *list, bNode *n)
{
    bNode *tail = list->prev;

    tail->next = n;
    list->prev = n;
    n->next    = list;
    n->prev    = tail;
}

void WeatherAddRegion(WeatherRegion *r)
{
    if ((uint32_t)r->Type < WEATHER_NUM_TYPES) {
        add_tail(&WeatherRegionLists[r->Type], &r->Node);
    } else {
        r->Node.next = &r->Node;
        r->Node.prev = &r->Node;
    }
}

void WeatherRemoveRegion(WeatherRegion *r)
{
    bNode *prev = r->Node.prev;
    bNode *next = r->Node.next;

    prev->next = next;
    next->prev = prev;
}

void WeatherSetRegionState(WeatherRegion *r, int32_t state)
{
    bNode *next = r->Node.next;
    bNode *prev = r->Node.prev;

    prev->next = next;
    next->prev = prev;
    add_tail(state ? &WeatherRegionLists[r->Type]
                   : &WeatherRegionInactiveList, &r->Node);
}

// The regions of the group on one list, each moved by SetRegionState. The
// next region is read before the move.
static void set_list_state(bNode *list, uint32_t group_hash, int32_t state)
{
    bNode *n = list->next;

    while (n != list) {
        WeatherRegion *r    = (WeatherRegion *)n;
        bNode         *next = n->next;

        if (group_hash == 0 || r->GroupNameHash == group_hash) {
            WeatherSetRegionState(r, state);
        }
        n = next;
    }
}

void WeatherSetGroupState(uint32_t group_hash, int32_t state)
{
    int i;

    if (state) {
        set_list_state(&WeatherRegionInactiveList, group_hash, state);
        return;
    }
    for (i = 0; i < WEATHER_NUM_TYPES; i++) {
        set_list_state(&WeatherRegionLists[i], group_hash, state);
    }
}

// ----------------------------------------------------------- the loader

// The chunk's pack, at the next 16 after its header.
static WeatherRegionPack *chunk_pack(uint8_t *chunk)
{
    return (WeatherRegionPack *)(((uintptr_t)chunk + 8 + 15)
                                 & ~(uintptr_t)15);
}

int loader_weather_man(uint8_t *chunk)
{
    WeatherRegionPack *pack;
    WeatherRegion     *r;
    int32_t            n;

    if (bchunk_u32(chunk) != WEATHER_CHUNK_ID) {
        return 0;
    }
    pack = chunk_pack(chunk);
    if (pack->Version != WEATHER_PACK_VERSION) {
        return 1;
    }
    r = (WeatherRegion *)(pack + 1);
    for (n = pack->NumRegions; n > 0; n--) {
        WeatherAddRegion(r++);
    }
    return 1;
}

int unloader_weather_man(uint8_t *chunk)
{
    WeatherRegionPack *pack;
    WeatherRegion     *r;
    int32_t            n;

    if (bchunk_u32(chunk) != WEATHER_CHUNK_ID) {
        return 0;
    }
    pack = chunk_pack(chunk);
    if (pack->Version != WEATHER_PACK_VERSION) {
        return 1;
    }
    r = (WeatherRegion *)(pack + 1);
    for (n = pack->NumRegions; n > 0; n--) {
        WeatherRemoveRegion(r++);
    }
    return 1;
}

// ------------------------------------------------------------ the query

// One region's share of the fog: the colour's three bytes, the start and
// the amount, each scaled by the region's weight. The colour is also
// written to the query, from the scaled bytes, unmasked.
typedef struct FogShare {
    float r, g, b, start, amount;
} FogShare;

static FogShare fog_share(const WeatherRegion *reg, float w,
                          const char **name, uint32_t *colour,
                          float *start, float *scale)
{
    uint32_t c = reg->FogColour;
    FogShare s;

    s.amount = reg->Intensity * w;
    s.r      = (float)(c & 0xffu) * w;
    s.g      = (float)(c >> 8 & 0xffu) * w;
    s.b      = (float)(c >> 16 & 0xffu) * w;
    s.start  = reg->FogStart * w;
    *colour  = (uint32_t)ee_trunc_w(s.b) << 16
             | (uint32_t)ee_trunc_w(s.g) << 8
             | (uint32_t)ee_trunc_w(s.r);
    *name    = reg->Name;
    *scale   = w;
    *start   = s.start;
    return s;
}

void WeatherManQuery(WeatherQuery *q, const bVector3 *pos)
{
    float x = pos->x, y = pos->y, z = pos->z;
    int   type;

    // Retail 0x001a84f0's first test.
    if (WeatherHeavyFog) {
        float s1, s2, s3;

        q->Fog = 0.957753f;
        s1 = bSinF((float)WorldTimeFrames * 0.02f);
        s2 = bSinF((float)WorldTimeFrames * 0.001f);
        s3 = bSinF((float)WorldTimeFrames * 0.01f);
        q->FogColour = 0x00887062;
        q->FogStart  = s1 * 200.0f + -1000.0f + s2 * 150.0f + s3 * 100.0f;
        return;
    }
    if (WeatherUseTweakerValues) {
        q->Fog       = WeatherFog;
        q->FogStart  = WeatherFogStart;
        q->FogColour = (uint32_t)WeatherFogColourB << 16
                     | (uint32_t)WeatherFogColourG << 8
                     | (uint32_t)WeatherFogColourR;
        q->Snow = 0.0f;
        q->Rain = 0.0f;
        q->Wind = 0.0f;
        return;
    }
    // Two 16-byte locals are cleared as well, and never read.
    memset(q, 0, sizeof *q);

    for (type = 0; type < WEATHER_NUM_TYPES; type++) {
        bNode         *list    = &WeatherRegionLists[type];
        bNode         *n       = list->next;
        WeatherRegion *root    = NULL;
        float          nearest = WEATHER_FAR;
        WeatherRegion *hit[3]  = { NULL, NULL, NULL };
        float          scale[3] = { 0.0f, 0.0f, 0.0f };
        int            hits    = 0;
        float          sum, root_scale, hit_scale, value;

        while (n != list) {
            WeatherRegion *r  = (WeatherRegion *)n;
            float          r2 = r->Radius * r->Radius;
            float          dx = fabsf(x - r->PositionX);
            float          dy = fabsf(y - r->PositionY);
            float          dz = fabsf(z - r->PositionZ);
            float          d2 = dx * dx + dy * dy + dz * dz;

            if (d2 < r2) {
                float f2 = r->FarFalloffStart * r->FarFalloffStart;

                if (r2 == f2) {
                    if (d2 < nearest) {
                        nearest = d2;
                        root    = r;
                    }
                } else {
                    float s = 1.0f - (d2 - f2) / (r2 - f2);

                    if (0.0f < s) {
                        scale[hits] = s;
                        hit[hits]   = r;
                        hits++;
                    }
                }
            }
            n = n->next;
            if (hits >= 3) {
                break;
            }
        }

        sum        = scale[0] + scale[1] + scale[2];
        root_scale = 1.0f - sum;
        hit_scale  = 1.0f;
        if (1.0f < sum) {
            hit_scale  = 1.0f / sum;
            root_scale = 0.0f;
        }
        q->RootScale = root_scale;
        q->HitScale  = hit_scale;

        if (type == WEATHER_FOG) {
            FogShare t = { 0.0f, 0.0f, 0.0f, 0.0f, 0.0f };
            int      k;

            if (root != NULL) {
                FogShare s = fog_share(root, root_scale, &q->RegionR,
                                       &q->RegionR_Colour,
                                       &q->RegionR_FogStart,
                                       &q->RegionR_Scale);
                t.r      += s.r;
                t.g      += s.g;
                t.b      += s.b;
                t.start  += s.start;
                t.amount += s.amount;
            }
            for (k = 0; k < 3; k++) {
                const char **name;
                uint32_t    *colour;
                float       *start, *sc;
                FogShare     s;

                if (hit[k] == NULL) {
                    continue;
                }
                name   = k == 0 ? &q->Region0 : k == 1 ? &q->Region1
                                                       : &q->Region2;
                colour = k == 0 ? &q->Region0_Colour
                       : k == 1 ? &q->Region1_Colour : &q->Region2_Colour;
                start  = k == 0 ? &q->Region0_FogStart
                       : k == 1 ? &q->Region1_FogStart
                                : &q->Region2_FogStart;
                sc     = k == 0 ? &q->Region0_Scale
                       : k == 1 ? &q->Region1_Scale : &q->Region2_Scale;
                s = fog_share(hit[k], scale[k] * hit_scale, name, colour,
                              start, sc);
                t.amount += s.amount;
                t.r      += s.r;
                t.g      += s.g;
                t.b      += s.b;
                t.start  += s.start;
            }
            q->FogColour = ((uint32_t)ee_trunc_w(t.b) & 0xffu) << 16
                         | ((uint32_t)ee_trunc_w(t.g) & 0xffu) << 8
                         | ((uint32_t)ee_trunc_w(t.r) & 0xffu);
            q->Fog      = t.amount;
            q->FogStart = t.start;
            continue;
        }

        // The rest weight each hit's intensity by HitScale alone.
        value = 0.0f;
        if (root != NULL) {
            value = root->Intensity * root_scale;
        }
        for (hits = 0; hits < 3; hits++) {
            if (hit[hits] != NULL) {
                value += hit[hits]->Intensity * hit_scale;
            }
        }
        if (type == WEATHER_RAIN) {
            q->Rain = value;
        } else if (type == WEATHER_SNOW) {
            q->Snow = value;
        } else {
            q->Wind = value;
        }
    }
}

// ------------------------------------------------------------- the view

WeatherQuery *eview_get_weather_query(eView *view)
{
    WeatherQuery *q = &CachedWeatherQueries[view->ID];

    if (view->WeatherQueryCounter != eFrameCounter) {
        WeatherManQuery(q, &view->pCamera->CurrentKey.Position);
        view->WeatherQueryCounter = eFrameCounter;
    }
    return q;
}

void WeatherTest(void)
{
}
