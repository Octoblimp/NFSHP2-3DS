// Host harness for 3DS Files/source/skids.c (the skid marks' sets and
// clans, TASKS 78). Runs the op script tools/skids_check.py writes and
// prints the transcript it diffs against the retail image, run in mipsemu
// over the same script.
//
// The slot pools, bPNode's nodes, GetTextureInfo and the elevation seam
// are stand-ins that print what they are given, as the model's are. After
// each op the state is hashed, and every so often printed.
//
// A float prints as its bits.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bplist.h"
#include "bslotpool.h"
#include "car.h"
#include "realtime.h"
#include "skids.h"
#include "texturepack.h"
#include "wheel.h"

#define MAX_POOLS   16
#define POOL_SLOTS  128
#define SLOT_BYTES  0x200
#define NUM_NODES   1024
#define NUM_MAKERS  8
#define NUM_CARS    4
#define NUM_TEX     4
#define NUM_WHEELS  4
#define FULL_EVERY  100
#define WALK_CAP    2000
#define MAX_LINES   4096
#define LINE_BYTES  2048

// The globals of files the harness does not link.
int32_t WorldTime = 1;

typedef struct HPool {
    int      size, n, mem;
    uint32_t flags;
    char     name[32];
    int      used[POOL_SLOTS];
} HPool;

static BSlotPool s_handle[MAX_POOLS];
static HPool     s_pool[MAX_POOLS];
static int       s_npools;
static uint8_t   s_arena[MAX_POOLS][POOL_SLOTS][SLOT_BYTES]
                 __attribute__((aligned(16)));
static bPNode    s_node[NUM_NODES];
static int       s_node_used[NUM_NODES];
static SkidMaker s_maker[NUM_MAKERS];
static Car       s_car[NUM_CARS];
static uint8_t   s_tex[NUM_TEX + 1][256] __attribute__((aligned(16)));
static Wheel     s_wheel[NUM_WHEELS];
static WheelInfo s_wi[NUM_WHEELS];
static CarState  s_cs[NUM_WHEELS];
static uint8_t   s_topo[NUM_WHEELS][16];
static uint32_t  s_height[2];
static int       s_nheight;

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float fl(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static uint32_t hex(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 16);
}

static int in(const void *p, const void *base, size_t size)
{
    const uint8_t *a = (const uint8_t *)p, *b = (const uint8_t *)base;

    return a >= b && a < b + size;
}

// ------------------------------------------------------------- the labels

static int pool_of(const BSlotPool *h)
{
    return (int)(h - s_handle);
}

static const char *pool_label(const BSlotPool *h)
{
    static char b[4][16];
    static int  r;
    char       *o;

    if (h == NULL)
        return "NULL";
    o = b[r++ & 3];
    snprintf(o, 16, "p%d", pool_of(h));
    return o;
}

static const char *pool_prefix(int k)
{
    if (strcmp(s_pool[k].name, "SkidSetSlotPool") == 0)
        return "s";
    if (strcmp(s_pool[k].name, "ClanSlotPool") == 0)
        return "c";
    return "?";
}

static const char *label(const void *p)
{
    static char b[16][24];
    static int  r;
    char       *o;
    int         k;

    if (p == NULL)
        return "NULL";
    o = b[r++ & 15];
    for (k = 0; k < s_npools; k++)
        if (in(p, s_arena[k], sizeof s_arena[k])) {
            size_t off = (size_t)((const uint8_t *)p - &s_arena[k][0][0]);

            if (off % SLOT_BYTES == 0) {
                snprintf(o, 24, "%s%d", pool_prefix(k),
                         (int)(off / SLOT_BYTES));
                return o;
            }
        }
    if (in(p, s_node, sizeof s_node)
        && ((const uint8_t *)p - (const uint8_t *)s_node) % sizeof(bPNode)
           == 0) {
        snprintf(o, 24, "n%d", (int)((const bPNode *)p - s_node));
        return o;
    }
    if (in(p, s_maker, sizeof s_maker)
        && ((const uint8_t *)p - (const uint8_t *)s_maker)
           % sizeof(SkidMaker) == 0) {
        snprintf(o, 24, "m%d", (int)((const SkidMaker *)p - s_maker));
        return o;
    }
    if (in(p, s_car, sizeof s_car)
        && ((const uint8_t *)p - (const uint8_t *)s_car) % sizeof(Car)
           == 0) {
        snprintf(o, 24, "car%d", (int)((const Car *)p - s_car));
        return o;
    }
    if (in(p, s_tex, sizeof s_tex)
        && ((const uint8_t *)p - &s_tex[0][0]) % 256 == 0) {
        snprintf(o, 24, "t%d", (int)(((const uint8_t *)p - &s_tex[0][0])
                                     / 256));
        return o;
    }
    for (k = 0; k < NUM_WHEELS; k++) {
        if (p == &s_wheel[k].TheSkidMaker) {
            snprintf(o, 24, "wm%d", k);
            return o;
        }
        if (p == s_topo[k]) {
            snprintf(o, 24, "topo%d", k);
            return o;
        }
    }
    snprintf(o, 24, "?%p", p);
    return o;
}

// ------------------------------------------------------------- the pools

static const char *size_label(int size)
{
    static char b[16];

    if (size == (int)sizeof(SkidSet))
        return "skidset";
    if (size == (int)sizeof(Clan))
        return "clan";
    snprintf(b, sizeof b, "%d", size);
    return b;
}

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *name,
                        int memoryPool)
{
    int k = s_npools++;

    if (k >= MAX_POOLS || numSlots > POOL_SLOTS || slotSize > SLOT_BYTES) {
        fprintf(stderr, "pool table full\n");
        exit(3);
    }
    memset(&s_pool[k], 0, sizeof s_pool[k]);
    s_pool[k].size = slotSize;
    s_pool[k].n = numSlots;
    s_pool[k].mem = memoryPool;
    s_pool[k].flags = BSP_DEFAULT_FLAGS;
    snprintf(s_pool[k].name, sizeof s_pool[k].name, "%s", name);
    printf("newpool p%d name=%s n=%d size=%s mem=%d\n", k, name, numSlots,
           size_label(slotSize), memoryPool);
    return &s_handle[k];
}

void bDeleteSlotPool(BSlotPool *pool)
{
    printf("delpool %s\n", pool_label(pool));
    if (pool != NULL)
        memset(s_pool[pool_of(pool)].used, 0, sizeof s_pool[0].used);
}

void bClearSlotPoolFlag(BSlotPool *pool, uint32_t flag)
{
    s_pool[pool_of(pool)].flags &= ~flag;
}

static void *alloc(BSlotPool *h, const char *how)
{
    int    k = pool_of(h), i;
    HPool *p = &s_pool[k];

    for (i = 0; i < p->n; i++)
        if (!p->used[i]) {
            int clear = how[0] == 'o'
                        && (p->flags & BSP_ZERO_ALLOCATED_MEMORY) != 0;

            p->used[i] = 1;
            memset(s_arena[k][i], clear ? 0 : 0xcd, (size_t)p->size);
            printf("alloc%s p%d slot=%d\n", how, k, i);
            return s_arena[k][i];
        }
    printf("alloc%s p%d full\n", how, k);
    return NULL;
}

void *bSlotOMalloc(BSlotPool *pool)
{
    return alloc(pool, "o");
}

void *bSlotMalloc(BSlotPool *pool)
{
    return alloc(pool, "m");
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    int k = pool_of(pool);

    printf("free %s %s\n", pool_label(pool), label(slot));
    if (in(slot, s_arena[k], sizeof s_arena[k])) {
        size_t o = (size_t)((uint8_t *)slot - &s_arena[k][0][0]);

        s_pool[k].used[o / SLOT_BYTES] = 0;
    }
}

int bIsSlotPoolFull(const BSlotPool *pool)
{
    const HPool *p = &s_pool[pool - s_handle];
    int          i;

    for (i = 0; i < p->n; i++)
        if (!p->used[i])
            return 0;
    return 1;
}

// -------------------------------------------------------------- the nodes

bPNode *bpnode_malloc(void)
{
    int i;

    for (i = 0; i < NUM_NODES; i++)
        if (!s_node_used[i]) {
            s_node_used[i] = 1;
            memset(&s_node[i], 0xcd, sizeof s_node[i]);
            return &s_node[i];
        }
    fprintf(stderr, "harness: out of nodes\n");
    exit(3);
}

void bpnode_free(void *p)
{
    s_node_used[(bPNode *)p - s_node] = 0;
}

// ---------------------------------------------------------- the textures

TextureInfo *GetTextureInfo(uint32_t hash, int use_default,
                            int include_unloaded)
{
    int          k = (int)((hash >> 3) % (NUM_TEX + 1));
    TextureInfo *t = k != 0 ? (TextureInfo *)(void *)s_tex[k] : NULL;

    printf("tex %08x def=%d unl=%d -> %s\n", (unsigned)hash, use_default,
           include_unloaded, label(t));
    return t;
}

// -------------------------------------------------------------- the state

static char     s_line[MAX_LINES][LINE_BYTES];
static int      s_nlines;

static char *new_line(void)
{
    if (s_nlines >= MAX_LINES) {
        fprintf(stderr, "harness: state too long\n");
        exit(3);
    }
    s_line[s_nlines][0] = 0;
    return s_line[s_nlines++];
}

#define ADD(o, ...) \
    snprintf((o) + strlen(o), LINE_BYTES - strlen(o), __VA_ARGS__)

static const char *vec(const bVector3 *v)
{
    static char b[8][32];
    static int  r;
    char       *o = b[r++ & 7];

    snprintf(o, 32, "%08x,%08x,%08x", (unsigned)bits(v->x),
             (unsigned)bits(v->y), (unsigned)bits(v->z));
    return o;
}

// ------------------------------------------------------------- the wheel

// GetElevation: the MM op's two heights in turn, then 0.
static float elevation(void *topology, const bVector3 *pos,
                       int32_t *terrainOut, bVector3 *normalOut)
{
    uint32_t h = s_nheight < 2 ? s_height[s_nheight++] : 0;

    printf("elev %s %s t=%s n=%s -> %08x\n", label(topology), vec(pos),
           label(terrainOut), label(normalOut), (unsigned)h);
    return fl(h);
}

TopologyGetElevationFn gTopologyGetElevationFn = elevation;

// wheel.c's, which the harness does not link (wheel_check holds it to the
// image); the model runs the image's.
void bRotateVector(bVector3 *o, const bMatrix4 *m, const bVector3 *v)
{
    float x, y, z;

    x = m->v0.x * v->x;
    x = x + m->v1.x * v->y;
    x = x + m->v2.x * v->z;
    o->x = x;

    y = m->v0.y * v->x;
    y = y + m->v1.y * v->y;
    y = y + m->v2.y * v->z;
    o->y = y;

    z = m->v0.z * v->x;
    z = z + m->v1.z * v->y;
    z = z + m->v2.z * v->z;
    o->z = z;
}

// The list's members in order, at most WALK_CAP and a NULL past them.
static int walk(bNode *head, bNode **out)
{
    int    n = 0;
    bNode *p;

    for (p = head->next; p != head; p = p->next) {
        out[n++] = p;
        if (n > WALK_CAP) {
            out[n++] = NULL;
            break;
        }
    }
    return n;
}

static bNode *s_walk[WALK_CAP + 2];
static bNode *s_walk2[WALK_CAP + 2];

static void state(void)
{
    char *o;
    int   i, k, n;

    s_nlines = 0;
    o = new_line();
    ADD(o, "makers");
    for (i = 0; i < NUM_MAKERS; i++)
        ADD(o, " m%d=%s", i, label(s_maker[i].pSkidSet));
    for (i = 0; i < NUM_WHEELS; i++)
        ADD(o, " wm%d=%s", i, label(s_wheel[i].TheSkidMaker.pSkidSet));
    o = new_line();
    ADD(o, "pools ");
    for (k = 0; k < s_npools; k++) {
        int used = 0;

        for (i = 0; i < s_pool[k].n; i++)
            used += s_pool[k].used[i];
        ADD(o, "%sp%d=%x/%d", k ? " " : "", k, (unsigned)s_pool[k].flags,
            used);
    }
    o = new_line();
    ADD(o, "globals skidpool=%s clanpool=%s plot=%d,%d",
        pool_label(SkidSetSlotPool), pool_label(ClanSlotPool),
        (int)PlotSkidsInCaffeine, (int)PlotSkidPointsInCaffeine);
    o = new_line();
    ADD(o, "tex");
    for (i = 0; i < NUM_TERRAIN_TYPES; i++)
        ADD(o, " %s", label(SkidTextureInfo[i]));

    n = walk(&SkidSetList, s_walk);
    o = new_line();
    ADD(o, "sets ");
    for (i = 0; i < n; i++)
        ADD(o, "%s%s", i ? " " : "", s_walk[i] ? label(s_walk[i]) : "LOOP");
    for (i = 0; i < n && s_walk[i] != NULL; i++) {
        const SkidSet *s = (const SkidSet *)(void *)s_walk[i];
        int            g, cnt = s->NumSkidSegments;

        o = new_line();
        ADD(o, "set %s car=%s both=%d clan=%s node=%s maker=%s terr=%d n=%d",
            label(s), label(s->pCar), (int)s->bVisibleToBothPlayers,
            label(s->pClan), label(s->pClanNode), label(s->pSkidMaker),
            (int)s->TheTerrainType, cnt);
        ADD(o, " pos=%s max=%s min=%s len=%08x centre=%s",
            vec(&s->Position), vec(&s->BBoxMax), vec(&s->BBoxMin),
            (unsigned)bits(s->LastSegmentLength), vec(&s->Centre));
        if (cnt >= 2)
            ADD(o, " normal=%s", vec(&s->LastNormal));
        for (g = 0; g < cnt && g < SKIDSET_MAX_SEGMENTS; g++) {
            const SkidSegment *seg = &s->SkidSegments[g];
            bVector3           p;

            p.x = seg->Position[0];
            p.y = seg->Position[1];
            p.z = seg->Position[2];
            o = new_line();
            ADD(o, "  seg %d pos=%s d=%02x%02x%02x int=%02x", g, vec(&p),
                (unsigned)(uint8_t)seg->DeltaPosition[0],
                (unsigned)(uint8_t)seg->DeltaPosition[1],
                (unsigned)(uint8_t)seg->DeltaPosition[2],
                (unsigned)seg->Intensity);
        }
    }

    n = walk(&ClanList, s_walk);
    o = new_line();
    ADD(o, "clans ");
    for (i = 0; i < n; i++)
        ADD(o, "%s%s", i ? " " : "", s_walk[i] ? label(s_walk[i]) : "LOOP");
    for (i = 0; i < n && s_walk[i] != NULL; i++) {
        Clan *c = (Clan *)(void *)s_walk[i];
        int   m, j;

        o = new_line();
        ADD(o, "clan %s hash=%08x t=%d", label(c), (unsigned)c->Hash,
            (int)c->LastUpdateTime);
        ADD(o, " pos=%s min=%s max=%s sets=", vec(&c->Position),
            vec(&c->BBoxMin), vec(&c->BBoxMax));
        m = walk(&c->SkidSetList, s_walk2);
        for (j = 0; j < m && s_walk2[j] != NULL; j++)
            ADD(o, "%s%s", j ? "," : "",
                label(((bPNode *)(void *)s_walk2[j])->Object));
    }
}

static uint32_t fnv(void)
{
    uint32_t h = 0x811c9dc5u;
    int      i;

    for (i = 0; i < s_nlines; i++) {
        const unsigned char *p = (const unsigned char *)s_line[i];

        for (; *p; p++)
            h = (h ^ *p) * 0x01000193u;
        h = (h ^ '\n') * 0x01000193u;
    }
    return h;
}

// ---------------------------------------------------------------- the ops

static void put_vec(bVector3 *v, char **t)
{
    v->x = fl(hex(t[0]));
    v->y = fl(hex(t[1]));
    v->z = fl(hex(t[2]));
    v->pad = 1.0f;
}

int main(int argc, char **argv)
{
    FILE *f;
    char  line[1024];
    int   k = 0;

    if (argc < 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: skids_test script\n");
        return 2;
    }
    setvbuf(stdout, NULL, _IOFBF, 1 << 16);
    // As the model starts them, so that InitSkids' clearing shows.
    PlotSkidsInCaffeine = (int32_t)0xa5a5a5a5u;
    PlotSkidPointsInCaffeine = (int32_t)0xa5a5a5a5u;
    while (fgets(line, sizeof line, f) != NULL) {
        char *t[24];
        int   n = 0, i;
        char *p;

        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        printf("> %s\n", line);
        for (p = strtok(line, " "); p != NULL && n < 24;
             p = strtok(NULL, " "))
            t[n++] = p;
        if (strcmp(t[0], "IC") == 0) {
            init_clans();
        } else if (strcmp(t[0], "IS") == 0) {
            init_skids();
        } else if (strcmp(t[0], "CC") == 0) {
            close_clans();
        } else if (strcmp(t[0], "CS") == 0) {
            close_skids();
        } else if (strcmp(t[0], "FC") == 0) {
            flush_clans();
        } else if (strcmp(t[0], "W") == 0) {
            WorldTime = atoi(t[1]);
        } else if (strcmp(t[0], "CAR") == 0) {
            Car *c = &s_car[atoi(t[1])];

            put_vec(&c->State.GeometryPosition, &t[2]);
            c->TheOverrideRenderingPosition.VisibleViewBits = hex(t[5]);
        } else if (strcmp(t[0], "MS") == 0) {
            int      m = atoi(t[1]), car = atoi(t[2]);
            bVector3 pos, delta;

            put_vec(&pos, &t[3]);
            put_vec(&delta, &t[6]);
            skidmaker_make_skid(&s_maker[m], car >= 0 ? &s_car[car] : NULL,
                                &pos, &delta, atoi(t[9]), fl(hex(t[10])));
        } else if (strcmp(t[0], "MN") == 0) {
            skidmaker_make_no_skid(&s_maker[atoi(t[1])]);
        } else if (strcmp(t[0], "WH") == 0) {
            int    j = atoi(t[1]);
            Wheel *w = &s_wheel[j];

            w->WI = &s_wi[j];
            w->CS = &s_cs[j];
            s_cs[j].pTopologyCoordinate =
                (TopologyCoordinate *)(void *)s_topo[j];
            s_wi[j].WheelNumber = atoi(t[2]);
            s_wi[j].Width = fl(hex(t[3]));
            w->Terrain = atoi(t[4]);
            w->Slipping = (uint8_t)atoi(t[5]);
            w->TouchingGround = (uint8_t)atoi(t[6]);
            w->ZForce = fl(hex(t[7]));
            w->TractionUsage = fl(hex(t[8]));
            w->Velocity.x = fl(hex(t[9]));
            w->Velocity.y = fl(hex(t[10]));
        } else if (strcmp(t[0], "WM") == 0) {
            bVector4 *r[4];
            int       j;

            r[0] = &s_wheel[atoi(t[1])].WorldMatrix.v0;
            r[1] = &s_wheel[atoi(t[1])].WorldMatrix.v1;
            r[2] = &s_wheel[atoi(t[1])].WorldMatrix.v2;
            r[3] = &s_wheel[atoi(t[1])].WorldMatrix.v3;
            for (j = 0; j < 4; j++) {
                r[j]->x = fl(hex(t[2 + 4 * j]));
                r[j]->y = fl(hex(t[3 + 4 * j]));
                r[j]->z = fl(hex(t[4 + 4 * j]));
                r[j]->w = fl(hex(t[5 + 4 * j]));
            }
        } else if (strcmp(t[0], "BL") == 0) {
            s_car[atoi(t[1])].BlownTireBits = (uint8_t)hex(t[2]);
        } else if (strcmp(t[0], "MM") == 0) {
            s_height[0] = hex(t[4]);
            s_height[1] = hex(t[5]);
            s_nheight = 0;
            skids_maybe_make_skids(&s_wheel[atoi(t[1])], &s_car[atoi(t[2])],
                                   fl(hex(t[3])));
        } else if (strcmp(t[0], "GC") == 0) {
            bVector3 pos;

            put_vec(&pos, &t[1]);
            printf("clan %s\n", label(get_clan(&pos)));
        } else if (strcmp(t[0], "DH") == 0) {
            if (SkidSetList.next != &SkidSetList) {
                SkidSet *s = (SkidSet *)(void *)SkidSetList.next;

                printf("delete %s\n", label(s));
                delete_this_skid(s);
            }
        } else if (strcmp(t[0], "D") != 0) {
            fprintf(stderr, "bad op %s\n", t[0]);
            return 2;
        }
        state();
        if (strcmp(t[0], "D") == 0 || k % FULL_EVERY == 0)
            for (i = 0; i < s_nlines; i++)
                printf("%s\n", s_line[i]);
        printf("= %08x\n", (unsigned)fnv());
        k++;
    }
    fclose(f);
    return 0;
}
