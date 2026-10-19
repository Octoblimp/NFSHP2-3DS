// Host harness for 3DS Files/source/eventmgr.c (the event manager),
// fernshaker.c (the fern shakers), emodelanim.c (eModel's rigid animation
// timing) and carevents.c (Car::TriggerEvents) (TASKS 73). Runs the op
// script tools/eventmgr_check.py writes and prints the transcript it diffs
// against the retail image, run in mipsemu over the same script.
//
// The slot pools, bMalloc and bFree, the ticker, vAABBTree::QueryLeaf, the
// WorldObject, the effects, the replay and VisibleDrivingLine's
// constructor are stand-ins that print what they are given, as the model's
// are. The four handlers print the event they are given and then do what
// the script asks of them through the port's own functions.
//
// A float prints as its bits.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "acidsys.h"
#include "bmem.h"
#include "bslotpool.h"
#include "bticker.h"
#include "car.h"
#include "carstate.h"
#include "elight.h"
#include "emodel.h"
#include "esolid.h"
#include "eventmgr.h"
#include "fernshaker.h"
#include "player.h"
#include "race.h"
#include "racecoord.h"
#include "realtime.h"
#include "replay.h"
#include "scenery.h"
#include "worldobject.h"

#define MAX_POOLS     8
#define POOL_SLOTS    64
#define SLOT_BYTES    256
#define MAX_BLOCKS    8
#define BLOCK_BYTES   0x1000
#define MAX_CHUNKS    16
#define CHUNK_BYTES   0x1000
#define MAX_RECS      4
#define NUM_EM        64
#define NUM_MODELS    16
#define NUM_SOLIDS    8
#define NUM_ANIMS     8
#define NUM_SECTS     8
#define SECT_INFOS    25
#define SECT_INSTS    85
#define NUM_HANDLERS  4
#define MAX_ACTIONS   8
#define MAX_PENDING   16
#define MAX_DEFINED   128
#define WALK_CAP      80

// The globals of files the harness does not link.
int32_t               WorldTimeFrames;
int32_t               WorldLoopCounter;
ScenerySectionHeader *ScenerySectionHeaderTable[SCENERY_MAX_SECTIONS];
BSlotPool            *WorldObjectSlotPool;
AcidEffectSystem      WorldEffects;
RaceParameters        TheRaceParameters;
RaceCoordinator      *pRaceCoordinator;
ReplayManager        *pReplayManager;

typedef struct HPool {
    int  size, n, mem;
    char name[32];
    int  used[POOL_SLOTS];
} HPool;

typedef struct HChunk {
    uint8_t *base;
    int      npacks, ntrees, narrays;
    void    *packs[MAX_RECS];
    void    *trees[MAX_RECS];
    void    *arrays[MAX_RECS];
    int      narray[MAX_RECS];
    int      has_leaf[MAX_RECS];
    vAABB    leaf[MAX_RECS];
} HChunk;

static BSlotPool s_handle[MAX_POOLS];
static HPool     s_pool[MAX_POOLS];
static int       s_npools;
static uint8_t   s_arena[MAX_POOLS][POOL_SLOTS][SLOT_BYTES]
                 __attribute__((aligned(16)));
static uint8_t   s_block[MAX_BLOCKS][BLOCK_BYTES] __attribute__((aligned(16)));
static int       s_nblocks;
static uint8_t   s_chunkmem[MAX_CHUNKS][CHUNK_BYTES]
                 __attribute__((aligned(16)));
static HChunk    s_chunk[MAX_CHUNKS];
static int       s_nchunks;
static uint32_t  s_ticks;
static AcidEmitter s_em[NUM_EM];
static int       s_nem;
static eModel    s_model[NUM_MODELS];
static int       s_model_defined[NUM_MODELS];
static eSolid    s_solid[NUM_SOLIDS];
static eRigidAnimation s_anim[NUM_ANIMS];
static ScenerySectionHeader s_sect[NUM_SECTS];
static SceneryInfo     s_info[NUM_SECTS][SECT_INFOS];
static SceneryInstance s_inst[NUM_SECTS][SECT_INSTS];
static int       s_sect_num[NUM_SECTS];
static int       s_nsects;
static int       s_defined_sec[MAX_DEFINED], s_defined_inst[MAX_DEFINED];
static int       s_ndefined;
static Car       s_car[2];
static Player    s_player;
static uint8_t   s_oldline[16];
static ReplayManager   s_replay;
static RaceCoordinator s_rc;
static bVector3  s_vel, s_at;
static EventTrigger s_pending[MAX_PENDING];
static int       s_npending;
static char      s_action[NUM_HANDLERS][MAX_ACTIONS][32];
static int       s_naction[NUM_HANDLERS];

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

static void put32(uint8_t *p, uint32_t v)
{
    memcpy(p, &v, 4);
}

// ------------------------------------------------------------- the labels

static void handler0(emEvent *e);
static void handler1(emEvent *e);
static void handler2(emEvent *e);
static void handler3(emEvent *e);
static const EmHandlerFn s_fn[NUM_HANDLERS] = {
    handler0, handler1, handler2, handler3
};

static int pool_of(const BSlotPool *h)
{
    return (int)(h - s_handle);
}

static const char *pool_label(const BSlotPool *h)
{
    static char buf[4][16];
    static int  k;
    char       *b = buf[k++ & 3];

    if (h == NULL)
        return "NULL";
    snprintf(b, 16, "pool%d", pool_of(h));
    return b;
}

static const char *fn_label(EmHandlerFn f)
{
    static char buf[4][16];
    static int  k;
    char       *b = buf[k++ & 3];
    int         i;

    if (f == NULL)
        return "NULL";
    for (i = 0; i < NUM_HANDLERS; i++)
        if (f == s_fn[i]) {
            snprintf(b, 16, "h%d", i);
            return b;
        }
    return "?fn";
}

static int in(const void *p, const void *base, size_t size)
{
    return (const uint8_t *)p >= (const uint8_t *)base
           && (const uint8_t *)p < (const uint8_t *)base + size;
}

static const char *label(const void *p)
{
    static char buf[16][40];
    static int  k;
    char       *b = buf[k++ & 15];
    const uint8_t *a = (const uint8_t *)p;
    int         c, j;

    if (p == NULL)
        return "NULL";
    if (in(a, s_arena, sizeof s_arena)) {
        size_t      o = (size_t)(a - &s_arena[0][0][0]);
        int         pk = (int)(o / (POOL_SLOTS * SLOT_BYTES));
        int         i = (int)(o % (POOL_SLOTS * SLOT_BYTES));
        const char *n = s_pool[pk].name, *pre = "?";

        if (i % SLOT_BYTES == 0) {
            if (strcmp(n, "EventSlotPool") == 0)
                pre = "e";
            else if (strcmp(n, "EventHandlerSlotPool") == 0)
                pre = "hs";
            else if (strcmp(n, "FernShakerSlotPool") == 0)
                pre = "fs";
            else if (strcmp(n, "WorldObjects") == 0)
                pre = "wo";
            snprintf(b, 40, "%s%d", pre, i / SLOT_BYTES);
            return b;
        }
    }
    if (pFernShakerInfoTable != NULL
        && in(a, pFernShakerInfoTable, 4 * sizeof(FernShakerInfo))
        && (size_t)(a - (const uint8_t *)pFernShakerInfoTable)
               % sizeof(FernShakerInfo) == 0) {
        snprintf(b, 40, "fi%d",
                 (int)((const FernShakerInfo *)p - pFernShakerInfoTable));
        return b;
    }
    if (in(a, s_block, sizeof s_block)) {
        size_t o = (size_t)(a - &s_block[0][0]);

        snprintf(b, 40, "blk%d+%d", (int)(o / BLOCK_BYTES),
                 (int)(o % BLOCK_BYTES));
        return b;
    }
    for (c = 0; c < s_nchunks; c++) {
        const HChunk *ch = &s_chunk[c];

        for (j = 0; j < ch->npacks; j++)
            if (p == ch->packs[j]) {
                snprintf(b, 40, "c%d.p%d", c, j);
                return b;
            }
        for (j = 0; j < ch->ntrees; j++)
            if (p == ch->trees[j]) {
                snprintf(b, 40, "c%d.t%d", c, j);
                return b;
            }
        for (j = 0; j < ch->narrays; j++) {
            int    n = ch->narray[j] > 0 ? ch->narray[j] : 1;
            size_t o = (size_t)(a - (const uint8_t *)ch->arrays[j]);

            if (in(a, ch->arrays[j], n * sizeof(EventTrigger))
                && o % sizeof(EventTrigger) == 0) {
                snprintf(b, 40, "c%d.a%d.t%d", c, j,
                         (int)(o / sizeof(EventTrigger)));
                return b;
            }
        }
    }
    if (in(a, s_em, sizeof s_em)
        && (size_t)(a - (const uint8_t *)s_em) % sizeof(AcidEmitter) == 0) {
        snprintf(b, 40, "em%d", (int)((const AcidEmitter *)p - s_em));
        return b;
    }
    if (in(a, s_model, sizeof s_model)) {
        snprintf(b, 40, "m%d", (int)((const eModel *)p - s_model));
        return b;
    }
    if (in(a, s_anim, sizeof s_anim)) {
        snprintf(b, 40, "an%d", (int)((const eRigidAnimation *)p - s_anim));
        return b;
    }
    for (j = 0; j < s_nsects; j++)
        if (in(a, s_inst[j], sizeof s_inst[j])
            && (size_t)(a - (const uint8_t *)s_inst[j])
                   % sizeof(SceneryInstance) == 0) {
            snprintf(b, 40, "s%d.%d", s_sect_num[j],
                     (int)((const SceneryInstance *)p - s_inst[j]));
            return b;
        }
    if (p == &s_car[0] || p == &s_car[1]) {
        snprintf(b, 40, "car%d", (int)((const Car *)p - s_car));
        return b;
    }
    if (p == &s_player)
        return "player";
    if (p == s_oldline)
        return "oldline";
    if (p == &s_replay)
        return "replay";
    if (p == &WorldEffects)
        return "world";
    return "?";
}

// ------------------------------------------------------------- the pools

static const char *size_label(int size)
{
    static char b[16];

    if (size == (int)sizeof(emEvent))
        return "event";
    if (size == (int)sizeof(emEventHandler))
        return "handler";
    if (size == (int)sizeof(FernShaker))
        return "fernshaker";
    if (size == (int)sizeof(WorldObject))
        return "wo";
    snprintf(b, sizeof b, "%d", size);
    return b;
}

static BSlotPool *new_pool(int size, int n, const char *name, int mem)
{
    int k = s_npools++;

    if (k >= MAX_POOLS || n > POOL_SLOTS || size > SLOT_BYTES) {
        fprintf(stderr, "pool table full\n");
        exit(3);
    }
    memset(&s_pool[k], 0, sizeof s_pool[k]);
    s_pool[k].size = size;
    s_pool[k].n = n;
    s_pool[k].mem = mem;
    snprintf(s_pool[k].name, sizeof s_pool[k].name, "%s", name);
    printf("newpool pool%d name=%s n=%d size=%s mem=%d\n", k, name, n,
           size_label(size), mem);
    return &s_handle[k];
}

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *name,
                        int memoryPool)
{
    return new_pool(slotSize, numSlots, name, memoryPool);
}

void bDeleteSlotPool(BSlotPool *pool)
{
    printf("delpool %s\n", pool_label(pool));
    if (pool != NULL)
        memset(s_pool[pool_of(pool)].used, 0, sizeof s_pool[0].used);
}

static void *alloc(BSlotPool *h, const char *how)
{
    int    k = pool_of(h), i;
    HPool *p = &s_pool[k];

    for (i = 0; i < p->n; i++)
        if (!p->used[i]) {
            p->used[i] = 1;
            memset(s_arena[k][i], 0xcd, (size_t)p->size);
            printf("alloc%s pool%d slot=%d\n", how, k, i);
            return s_arena[k][i];
        }
    printf("alloc%s pool%d full\n", how, k);
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

static void free_slot(BSlotPool *h, void *slot, int quiet)
{
    int k = pool_of(h);

    if (!quiet)
        printf("free %s %s\n", pool_label(h), label(slot));
    if (in(slot, s_arena[k], sizeof s_arena[k])) {
        size_t o = (size_t)((uint8_t *)slot - &s_arena[k][0][0]);

        if (o % SLOT_BYTES == 0)
            s_pool[k].used[o / SLOT_BYTES] = 0;
    }
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    free_slot(pool, slot, 0);
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

static const char *block_label(int size)
{
    static char b[16];

    if (size == 16 + 2 * (int)sizeof(FernShakerInfo))
        return "fstable";
    snprintf(b, sizeof b, "%d", size);
    return b;
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    int k = s_nblocks++;

    if (k >= MAX_BLOCKS || size > BLOCK_BYTES) {
        fprintf(stderr, "block table full\n");
        exit(3);
    }
    printf("bMalloc size=%s name=%s flags=%d pool=%d -> blk%d\n",
           block_label(size), name, flags, pool, k);
    memset(s_block[k], 0xab, (size_t)size);
    return s_block[k];
}

void bFree(void *p)
{
    printf("bFree %s\n", label(p));
}

// ------------------------------------------------------------- the clock

uint32_t bGetTicker(void)
{
    s_ticks += 1024u * (1u + (s_ticks / 1024u) % 3u);
    return s_ticks;
}

float bGetTickerDifference(uint32_t from, uint32_t to)
{
    return (float)((to - from) / 1024u);
}

// -------------------------------------------------------------- the tree

vAABB *vaabbtree_query_leaf(const vAABBTree *t, float x, float y, float z)
{
    int c, j;

    printf("query %s x=%08x y=%08x z=%08x na=%s\n", label(t), bits(x),
           bits(y), bits(z),
           t->NodeArray == (const vAABB *)(t + 1) ? "ok" : "bad");
    for (c = 0; c < s_nchunks; c++)
        for (j = 0; j < s_chunk[c].ntrees; j++)
            if (s_chunk[c].trees[j] == (const void *)t)
                return s_chunk[c].has_leaf[j] ? &s_chunk[c].leaf[j] : NULL;
    return NULL;
}

// ------------------------------------------- the world objects, the effects

static void print_words(const float *f, int n)
{
    int i;

    for (i = 0; i < n; i++)
        printf("%s%08x", i ? " " : "", bits(f[i]));
}

WorldObject *worldobject_construct(WorldObject *o, uint32_t name_hash,
                                   const bMatrix4 *matrix,
                                   int32_t add_lighting)
{
    int i;

    printf("wo new %s hash=%08x light=%d m=", label(o), name_hash,
           (int)add_lighting);
    print_words(&matrix->v0.x, 16);
    printf("\n");
    if (o != NULL) {
        o->pModel = NULL;
        for (i = 0; i < NUM_MODELS; i++)
            if (s_model_defined[i] && s_model[i].NameHash == name_hash) {
                o->pModel = &s_model[i];
                break;
            }
    }
    return o;
}

void worldobject_destruct(WorldObject *o, int32_t flags)
{
    printf("wo delete %s flags=%d\n", label(o), (int)flags);
    if ((flags & 1) != 0)
        free_slot(WorldObjectSlotPool, o, 1);
}

static void add_tail(bNode *list, bNode *n)
{
    bNode *tail = list->prev;

    tail->next = n;
    list->prev = n;
    n->prev = tail;
    n->next = list;
}

void afx_get_emitters(bNode *list, uint32_t group_hash)
{
    int n = 1 + (int)((group_hash & 3u) % 3u), i;

    printf("afx list=%s hash=%08x n=%d\n",
           label((uint8_t *)list - offsetof(FernShakerInfo, EmitterList)),
           group_hash, n);
    for (i = 0; i < n; i++)
        add_tail(list, (bNode *)&s_em[s_nem++]);
}

void acid_system_trigger_emitter(AcidEffectSystem *s, AcidEmitter *e,
                                 float time_step, void *car)
{
    printf("trigger sys=%s e=%s step=%08x car=%s lw=", label(s), label(e),
           bits(time_step), label(car));
    print_words(&e->LocalWorld.v0.x, 16);
    printf(" iv=");
    print_words(&e->InheritVelocity.x, 4);
    printf("\n");
}

void acid_emitter_delete(AcidEmitter *e, int32_t flags)
{
    printf("emitter delete %s flags=%d\n", label(e), (int)flags);
}

void ReplayManager_RegisterInterestingEvent(ReplayManager *rm, float value,
                                            const char *description)
{
    printf("interesting rm=%s value=%08x what=%s\n", label(rm), bits(value),
           description);
}

static struct VisibleDrivingLine *vdl_ctor(void *mem, Player *p, int32_t line,
                                    float seconds)
{
    printf("vdl new mem=%s player=%s line=%d secs=%08x\n", label(mem),
           label(p), (int)line, bits(seconds));
    return (struct VisibleDrivingLine *)mem;
}

static void init_emitter(int i)
{
    float *lw = &s_em[i].LocalWorld.v0.x;
    int    k;

    for (k = 0; k < 16; k++)
        lw[k] = 0.25f * (float)((i * 7 + k * 3) % 11) - 1.0f;
    s_em[i].InheritVelocity.x = 5.0f;
    s_em[i].InheritVelocity.y = 6.0f;
    s_em[i].InheritVelocity.z = 7.0f;
    s_em[i].InheritVelocity.w = 8.0f;
}

// ---------------------------------------------------------- the handlers

static emEvent *event_addr(int slot)
{
    return (emEvent *)(void *)s_arena[pool_of(EventSlotPool)][slot];
}

static void handle(int k, emEvent *e)
{
    char acts[MAX_ACTIONS][32];
    int  n = s_naction[k], i;

    printf("handler h%d ev=%s id=%08x\n", k, label(e), e->ID);
    memcpy(acts, s_action[k], sizeof acts);
    for (i = 0; i < n; i++) {
        char *act = acts[i], *f1, *f2;

        if (strncmp(act, "once:", 5) == 0) {
            int j;

            for (j = 0; j < s_naction[k]; j++)
                if (strcmp(s_action[k][j], act) == 0)
                    break;
            if (j < s_naction[k]) {
                memmove(s_action[k][j], s_action[k][j + 1],
                        (size_t)(s_naction[k] - j - 1) * 32);
                s_naction[k]--;
            }
            act += 5;
        }
        f1 = strchr(act, ':');
        f2 = f1 != NULL ? strchr(f1 + 1, ':') : NULL;
        if (strcmp(act, "lock") == 0) {
            em_lock_event(e);
        } else if (strcmp(act, "unlock") == 0) {
            em_unlock_event(e);
        } else if (strncmp(act, "add:", 4) == 0) {
            emEvent *v = em_add_event(hex(act + 4));

            printf("  added %s\n", label(v));
        } else if (strncmp(act, "rm:", 3) == 0) {
            em_remove_event(strcmp(act + 3, "self") == 0
                            ? e : event_addr(atoi(act + 3)));
        } else if (strncmp(act, "rmh:", 4) == 0) {
            em_remove_handler(s_fn[atoi(act + 4)]);
        } else if (strncmp(act, "addh:", 5) == 0 && f2 != NULL) {
            int32_t v = em_add_handler(s_fn[atoi(act + 5)], hex(f2 + 1));

            printf("  addh -> %d\n", (int)v);
        } else {
            fprintf(stderr, "bad action %s\n", act);
            exit(3);
        }
    }
}

static void handler0(emEvent *e) { handle(0, e); }
static void handler1(emEvent *e) { handle(1, e); }
static void handler2(emEvent *e) { handle(2, e); }
static void handler3(emEvent *e) { handle(3, e); }

// ------------------------------------------------------------ the chunks

static int build_chunk(int version, int ntrig, const char *order)
{
    int      c = s_nchunks++;
    uint8_t *base = s_chunkmem[c];
    HChunk  *ch = &s_chunk[c];
    size_t   o = 8;
    const char *q;

    if (c >= MAX_CHUNKS) {
        fprintf(stderr, "chunk table full\n");
        exit(3);
    }
    memset(base, 0, CHUNK_BYTES);
    memset(ch, 0, sizeof *ch);
    ch->base = base;
    for (q = order; *q != '\0'; q++) {
        size_t   r = (o + 8 + 15) & ~(size_t)15, len;
        uint32_t type;

        switch (*q) {
        case 'h':
        case 'H': {
            EventTriggerPack *pk = (EventTriggerPack *)(void *)(base + r);

            type = EVENT_PACK_HEADER_ID;
            len = sizeof *pk;
            pk->Version = *q == 'h' ? version : 1;
            pk->NumEventTriggers = ntrig;
            ch->packs[ch->npacks++] = pk;
            break;
        }
        case 't':
            type = EVENT_TREE_ID;
            len = sizeof(vAABBTree) + 48;
            ch->trees[ch->ntrees++] = base + r;
            break;
        case 'a':
            type = EVENT_TRIGGERS_ID;
            len = (size_t)s_npending * sizeof(EventTrigger);
            memcpy(base + r, s_pending, len);
            ch->narray[ch->narrays] = s_npending;
            ch->arrays[ch->narrays++] = base + r;
            break;
        default:
            type = *q == 'x' ? 0x36004u : *q == 'y' ? 0x00036000u
                                                    : 0x80036002u;
            len = 8;
            memset(base + r, 0x5a, 8);
            break;
        }
        put32(base + o, type);
        put32(base + o + 4, (uint32_t)(r - (o + 8) + len));
        o = r + len;
    }
    put32(base, EVENT_MANAGER_ID);
    put32(base + 4, (uint32_t)(o - 8));
    return c;
}

// -------------------------------------------------------------- the dump

static void walk_print(const bNode *head, const char *(*f)(const bNode *))
{
    const bNode *n;
    int          i = 0;

    for (n = head->next; n != head && i < WALK_CAP; n = n->next, i++)
        printf("%s%s", i ? " " : "", f(n));
}

static const char *handler_item(const bNode *n)
{
    static char b[96];
    const emEventHandler *h = (const emEventHandler *)n;

    snprintf(b, sizeof b, "%s:%s/%08x/%d/%08x", label(h),
             fn_label(h->HandlerFunction), h->StreamMask,
             (int)h->ReferenceCount, bits(h->TotalTime));
    return b;
}

static const char *event_item(const bNode *n)
{
    static char b[160];
    const emEvent *e = (const emEvent *)n;

    snprintf(b, sizeof b, "%s/%08x/%d/%s/%s/%08x/%08x/%08x", label(e), e->ID,
             (int)e->ReferenceCount, label(e->pEventTrigger),
             label(e->CarPtr), (uint32_t)e->Parameter0,
             (uint32_t)e->Parameter1, (uint32_t)e->Parameter2);
    return b;
}

static const char *plain_item(const bNode *n)
{
    return label(n);
}

static const char *shaker_item(const bNode *n)
{
    static char b[128];
    const FernShaker *s = (const FernShaker *)n;

    snprintf(b, sizeof b, "%s/%08x/%d/%s/%s/%s", label(s), s->SceneryCode,
             (int)s->StartTime, label(s->pSceneryInstance),
             label(s->pWorldObject), label(s->pFernShakerInfo));
    return b;
}

static uint32_t fnv(uint32_t h, uint32_t w)
{
    return (h ^ w) * 16777619u;
}

static void dump(void)
{
    const emEventManagerStats *st = &EventManagerStats;
    uint32_t h = 0x811c9dc5u;
    int      i, j, first = 1;

    printf("  st ne=%d nh=%d ppt=%08x hwq=%d hwh=%d cq=%s cur=%s "
           "pools=%s,%s\n", (int)st->NumEvents, (int)st->NumEventHandlers,
           bits(st->PreviousProcessTime), (int)st->EventQueueHighWaterMark,
           (int)st->EventHandlersHighWaterMark,
           CurrentEventQueue == &MasterEventQueue ? "master" : "?",
           label(CurrentlyHandlingEvent), pool_label(EventSlotPool),
           pool_label(EventHandlerSlotPool));
    printf("  hl ");
    walk_print(&EventHandlerList, handler_item);
    printf("\n  mq ");
    walk_print(&MasterEventQueue, event_item);
    printf("\n  pk ");
    walk_print(&EventTriggerPackList, plain_item);
    printf(" | ");
    walk_print(&EmptyEventTriggerPackList, plain_item);
    printf("\n  fs pool=%s n=%d table=%s ", pool_label(FernShakerSlotPool),
           (int)NumFernShakerInfos, label(pFernShakerInfoTable));
    walk_print(&FernShakerList, shaker_item);
    printf("\n");
    if (pFernShakerInfoTable != NULL && 0 < NumFernShakerInfos
        && NumFernShakerInfos <= 4) {
        printf("  fi ");
        for (i = 0; i < NumFernShakerInfos; i++) {
            const FernShakerInfo *fi = &pFernShakerInfoTable[i];

            printf("%s%08x/%08x/[", i ? " " : "", fi->RigidAnimationNameHash,
                   fi->EmitterGroupNameHash);
            walk_print(&fi->EmitterList, plain_item);
            printf("]");
        }
        printf("\n");
    }
    printf("  fx ");
    for (i = 0; i < s_ndefined; i++) {
        int sj = -1;

        for (j = 0; j < s_nsects; j++)
            if (s_sect_num[j] == s_defined_sec[i])
                sj = j;
        printf("%s%x", first ? "" : " ",
               (unsigned)s_inst[sj][s_defined_inst[i]].ExcludeFlags);
        first = 0;
    }
    for (i = 0; i < NUM_MODELS; i++)
        if (s_model_defined[i]) {
            printf("%sm%d=%04x", first ? "" : " ", i,
                   (unsigned)(uint16_t)s_model[i].RigidAnimationStartTime);
            first = 0;
        }
    printf("\n");
    for (i = 0; i < s_nem; i++) {
        const float *lw = &s_em[i].LocalWorld.v0.x;
        const float *iv = &s_em[i].InheritVelocity.x;

        for (j = 0; j < 16; j++)
            h = fnv(h, bits(lw[j]));
        for (j = 0; j < 4; j++)
            h = fnv(h, bits(iv[j]));
    }
    printf("  em %d %08x\n", s_nem, h);
}

// ------------------------------------------------------------- the state

static void self_link(bNode *n)
{
    n->next = n;
    n->prev = n;
}

static void reset(void)
{
    int i;

    memset(s_pool, 0, sizeof s_pool);
    memset(s_arena, 0, sizeof s_arena);
    memset(s_block, 0, sizeof s_block);
    memset(s_chunkmem, 0, sizeof s_chunkmem);
    memset(s_chunk, 0, sizeof s_chunk);
    memset(s_em, 0, sizeof s_em);
    memset(s_model, 0, sizeof s_model);
    memset(s_model_defined, 0, sizeof s_model_defined);
    memset(s_solid, 0, sizeof s_solid);
    memset(s_anim, 0, sizeof s_anim);
    memset(s_sect, 0, sizeof s_sect);
    memset(s_info, 0, sizeof s_info);
    memset(s_inst, 0, sizeof s_inst);
    memset(s_car, 0, sizeof s_car);
    memset(&s_player, 0, sizeof s_player);
    memset(&s_rc, 0, sizeof s_rc);
    memset(s_action, 0, sizeof s_action);
    memset(s_naction, 0, sizeof s_naction);
    s_npools = s_nblocks = s_nchunks = s_nem = s_nsects = s_ndefined = 0;
    s_npending = 0;
    s_ticks = 0;
    self_link(&EmptyEventTriggerPackList);
    self_link(&EventTriggerPackList);
    self_link(&EventHandlerList);
    self_link(&MasterEventQueue);
    EventSlotPool = NULL;
    EventHandlerSlotPool = NULL;
    CurrentlyHandlingEvent = NULL;
    pFernShakerInfoTable = NULL;
    NumFernShakerInfos = 0;
    FernShakerSlotPool = NULL;
    WorldTimeFrames = 0;
    WorldLoopCounter = 0;
    CurrentEventQueue = &MasterEventQueue;
    memset(&EventManagerStats, 0, sizeof EventManagerStats);
    memset(TriggerEventArray, 0, sizeof TriggerEventArray);
    self_link(&FernShakerList);
    memset(ScenerySectionHeaderTable, 0, sizeof ScenerySectionHeaderTable);
    memset(&TheRaceParameters, 0, sizeof TheRaceParameters);
    pReplayManager = &s_replay;
    pRaceCoordinator = &s_rc;
    WorldObjectSlotPool = new_pool((int)sizeof(WorldObject), 40,
                                   "WorldObjects", 0);
    for (i = 0; i < NUM_EM; i++)
        init_emitter(i);
}

static int sect_index(int sec)
{
    int j;

    for (j = 0; j < s_nsects; j++)
        if (s_sect_num[j] == sec)
            return j;
    fprintf(stderr, "no section %d\n", sec);
    exit(3);
}

// --------------------------------------------------------------- the ops

static void vec4(bVector3 *v, char **t)
{
    v->x = fl(hex(t[0]));
    v->y = fl(hex(t[1]));
    v->z = fl(hex(t[2]));
    v->pad = fl(hex(t[3]));
}

static void op(char **t, int n)
{
    const char *c = t[0];
    int         i;

    if (strcmp(c, "Z") == 0) {
        reset();
    } else if (strcmp(c, "I") == 0) {
        em_event_manager_init();
    } else if (strcmp(c, "IX") == 0) {
        em_event_manager_close();
    } else if (strcmp(c, "H") == 0) {
        printf("add handler -> %d\n",
               (int)em_add_handler(s_fn[atoi(t[1])], hex(t[2])));
    } else if (strcmp(c, "HN") == 0) {
        printf("add handler -> %d\n", (int)em_add_handler(NULL, hex(t[1])));
    } else if (strcmp(c, "R") == 0) {
        em_remove_handler(s_fn[atoi(t[1])]);
    } else if (strcmp(c, "E") == 0) {
        printf("add event -> %s\n", label(em_add_event(hex(t[1]))));
    } else if (strcmp(c, "X") == 0) {
        em_remove_event(event_addr(atoi(t[1])));
    } else if (strcmp(c, "LK") == 0) {
        em_lock_event(event_addr(atoi(t[1])));
    } else if (strcmp(c, "UL") == 0) {
        em_unlock_event(event_addr(atoi(t[1])));
    } else if (strcmp(c, "P") == 0) {
        em_process_all_events();
    } else if (strcmp(c, "AC") == 0) {
        int k = atoi(t[1]);

        s_naction[k] = 0;
        for (i = 2; i < n && s_naction[k] < MAX_ACTIONS; i++)
            snprintf(s_action[k][s_naction[k]++], 32, "%s", t[i]);
    } else if (strcmp(c, "D") == 0) {
    } else if (strcmp(c, "T") == 0) {
        EventTrigger *tr = &s_pending[s_npending];

        tr->NameHash = 0x1234u + (uint32_t)s_npending;
        tr->EventID = hex(t[1]);
        tr->Parameter = hex(t[2]);
        tr->pad = 0xdead;
        tr->PositionX = fl(hex(t[3]));
        tr->PositionY = fl(hex(t[4]));
        tr->PositionZ = fl(hex(t[5]));
        tr->Radius = fl(hex(t[6]));
        s_npending++;
    } else if (strcmp(c, "K") == 0) {
        int k = build_chunk(atoi(t[1]), atoi(t[2]), t[3]);

        s_npending = 0;
        printf("load c%d -> %d\n", k,
               loader_event_manager(s_chunk[k].base));
    } else if (strcmp(c, "KN") == 0 || strcmp(c, "K0") == 0) {
        int k = build_chunk(0, 0, "");

        if (c[1] == 'N')
            put32(s_chunk[k].base, 0x80036001u);
        printf("load c%d -> %d\n", k,
               loader_event_manager(s_chunk[k].base));
    } else if (strcmp(c, "U") == 0) {
        printf("unload c%s -> %d\n", t[1],
               unloader_event_manager(s_chunk[atoi(t[1])].base));
    } else if (strcmp(c, "Q") == 0) {
        int     cc = atoi(t[1]), j = atoi(strchr(t[1], '.') + 1);
        HChunk *ch = &s_chunk[cc];
        vAABB  *leaf = &ch->leaf[j];

        memset(leaf, 0, sizeof *leaf);
        if (strcmp(t[2], "none") == 0) {
            ch->has_leaf[j] = 0;
        } else {
            ch->has_leaf[j] = 1;
            if (strcmp(t[2], "parent") == 0) {
                leaf->NumChildren = 2;
            } else {
                leaf->NumChildren = (int16_t)-atoi(t[2]);
                for (i = 3; i < n; i++)
                    leaf->ChildrenIndicies[i - 3] = (int16_t)atoi(t[i]);
            }
        }
    } else if (strcmp(c, "TE") == 0) {
        emEvent **r;

        s_at.x = fl(hex(t[1]));
        s_at.y = fl(hex(t[2]));
        s_at.z = fl(hex(t[3]));
        s_at.pad = 0.0f;
        r = em_trigger_events(&s_at);
        printf("trigger events -> %s [",
               r == TriggerEventArray ? "array" : label(r));
        for (i = 0; i <= EM_MAX_TRIGGERED_EVENTS; i++)
            printf("%s%s", i ? " " : "", label(TriggerEventArray[i]));
        printf("]\n");
    } else if (strcmp(c, "CS") == 0) {
        Car *car = &s_car[atoi(t[1])];

        vec4(&car->State.GeometryPosition, &t[2]);
        vec4(&car->State.Velocity, &t[6]);
        car->State.VelocityMagnitude = fl(hex(t[10]));
        car->pPlayer = atoi(t[11]) ? &s_player : NULL;
    } else if (strcmp(c, "CT") == 0) {
        car_trigger_events(&s_car[atoi(t[1])]);
    } else if (strcmp(c, "PL") == 0) {
        s_player.pVisibleDrivingLine =
            atoi(t[1]) ? (struct VisibleDrivingLine *)(void *)s_oldline : NULL;
        s_player.bWrongWay = atoi(t[2]);
    } else if (strcmp(c, "RP") == 0) {
        TheRaceParameters.TrackDirection = atoi(t[1]);
        TheRaceParameters.TrainingLinesEnabled = atoi(t[2]);
    } else if (strcmp(c, "RC") == 0) {
        s_rc.CurrentRCState = atoi(t[1]);
    } else if (strcmp(c, "WL") == 0) {
        WorldLoopCounter = atoi(t[1]);
    } else if (strcmp(c, "WT") == 0) {
        WorldTimeFrames = atoi(t[1]);
    } else if (strcmp(c, "VD") == 0) {
        player_trigger_visible_driving_line(&s_player, atoi(t[1]),
                                            fl(hex(t[2])));
        printf("line %s\n", label(s_player.pVisibleDrivingLine));
    } else if (strcmp(c, "FA") == 0) {
        eRigidAnimation *a = &s_anim[atoi(t[1])];

        memset(a, 0, sizeof *a);
        a->NumFrames = (uint16_t)atoi(t[2]);
        a->FrameRateScale = (uint8_t)atoi(t[3]);
        a->NameHash = hex(t[4]);
    } else if (strcmp(c, "FS") == 0) {
        eSolid *s = &s_solid[atoi(t[1])];
        int     an = atoi(t[2]);

        memset(s, 0, sizeof *s);
        s->pRigidAnimation = an < 0 ? NULL : (uint8_t *)&s_anim[an];
    } else if (strcmp(c, "FM") == 0) {
        int     k = atoi(t[1]), so = atoi(t[3]);
        eModel *m = &s_model[k];

        memset(m, 0, sizeof *m);
        m->NameHash = hex(t[2]);
        m->Solid = so < 0 ? NULL : &s_solid[so];
        m->RigidAnimationStartTime = (int16_t)atoi(t[4]);
        s_model_defined[k] = 1;
    } else if (strcmp(c, "MS") == 0) {
        s_model[atoi(t[1])].RigidAnimationStartTime = (int16_t)hex(t[2]);
    } else if (strcmp(c, "FH") == 0) {
        int sec = atoi(t[1]), ninfo = atoi(t[2]), ninst = atoi(t[3]);
        int j = s_nsects++;
        ScenerySectionHeader *h = &s_sect[j];

        s_sect_num[j] = sec;
        memset(h, 0, sizeof *h);
        memset(s_info[j], 0, sizeof s_info[j]);
        memset(s_inst[j], 0, sizeof s_inst[j]);
        h->pSceneryInfo = s_info[j];
        h->NumSceneryInfo = ninfo;
        h->pSceneryInstance = ninst ? s_inst[j] : NULL;
        h->NumSceneryInstances = ninst;
        ScenerySectionHeaderTable[sec] = h;
    } else if (strcmp(c, "FI") == 0) {
        int m = atoi(t[3]);

        s_info[sect_index(atoi(t[1]))][atoi(t[2])].pModel[0] =
            m < 0 ? NULL : &s_model[m];
    } else if (strcmp(c, "FN") == 0) {
        int sec = atoi(t[1]), k = atoi(t[2]);
        SceneryInstance *inst = &s_inst[sect_index(sec)][k];

        memset(inst, 0, sizeof *inst);
        inst->SceneryInfoNumber = (int16_t)atoi(t[3]);
        inst->ExcludeFlags = (uint16_t)hex(t[16]);
        for (i = 0; i < 3; i++)
            inst->Position[i] = fl(hex(t[4 + i]));
        for (i = 0; i < 9; i++)
            inst->Rotation[i] = (int16_t)atoi(t[7 + i]);
        s_defined_sec[s_ndefined] = sec;
        s_defined_inst[s_ndefined++] = k;
    } else if (strcmp(c, "F") == 0) {
        init_fern_shakers();
    } else if (strcmp(c, "FF") == 0) {
        flush_fern_shakers();
    } else if (strcmp(c, "FX") == 0) {
        close_fern_shakers();
    } else if (strcmp(c, "FL") == 0) {
        flatten_fern(hex(t[1]));
    } else if (strcmp(c, "SF") == 0) {
        vec4(&s_vel, &t[2]);
        shake_fern(hex(t[1]), &s_vel);
    } else if (strcmp(c, "GA") == 0) {
        printf("anim %s\n",
               label(emodel_get_rigid_animation(&s_model[atoi(t[1])])));
    } else if (strcmp(c, "GT") == 0) {
        printf("time %d\n",
               (int)emodel_get_rigid_animation_time(&s_model[atoi(t[1])]));
    } else if (strcmp(c, "SN") == 0) {
        emodel_set_rigid_animation_frame_number(&s_model[atoi(t[1])],
                                                atoi(t[2]));
    } else {
        fprintf(stderr, "bad op %s\n", c);
        exit(3);
    }
}

int main(int argc, char **argv)
{
    char  line[4096];
    FILE *f;

    if (argc < 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: eventmgr_test SCRIPT\n");
        return 2;
    }
    gVisibleDrivingLineCtorFn = vdl_ctor;
    reset();
    while (fgets(line, sizeof line, f) != NULL) {
        char *tok[64];
        int   n = 0;
        char *p;

        line[strcspn(line, "\r\n")] = '\0';
        if (line[0] == '\0')
            continue;
        if (line[0] == 'B' && line[1] == ' ') {
            if (atoi(line + 2) > 0)
                reset();
            printf("%s\n", line);
            continue;
        }
        printf("> %.60s\n", line);
        for (p = strtok(line, " "); p != NULL && n < 64; p = strtok(NULL, " "))
            tok[n++] = p;
        op(tok, n);
        dump();
    }
    fclose(f);
    return 0;
}
