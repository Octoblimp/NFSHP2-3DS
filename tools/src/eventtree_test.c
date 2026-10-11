// eventtree_test -- tools/eventtree_check.py's harness.
//
// Runs eventtree.c over the checker's script and its data file: the two
// EventTree chunks of FRONTB.BUN, then the checker's own. What the port
// calls outside the module is a stub here that logs and answers as the
// model's stubs do: bMalloc and bFree (each block numbered), the race-type
// icons' GetTextureInfo, GetTranslatedString, Timer::PrintToString and
// bRandom. Pointers print by what they point into: the data (B and the
// offset), a numbered block (M), the loose tree (L), Fred (F and the
// offset), NULL (-), anything else as its low word.
//
//     eventtree_test script.txt data.bin > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "bmem.h"
#include "cartypeinfo.h"
#include "configitems.h"
#include "esolid.h"
#include "eventtree.h"
#include "fred.h"
#include "raceinit.h"
#include "timer.h"

#define QN       64
#define NBLOCKS  4096
#define WINDOW   0x24000

// ---------------------------------------------------- what the port reads

FrontendDatabase Fred;
uint32_t         bDefaultSeed;
int32_t          bVersionE3;
const char    *(*gFredTranslateFn)(int32_t id);
int32_t        (*gCurrLanguageFn)(void);
EggIsOnFn        gEggIsOnFn;
void          *(*gGetTextureInfoFn)(uint32_t name_hash, int use_default,
                                    int include_unloaded);

static uint8_t  *data;
static size_t    ndata;
static void     *blocks[NBLOCKS];
static int       nblocks;
static EventTree loose;
static int32_t   eggs[8];
static uint32_t  ntex;
static EventGoal goal;
static uint8_t   st[32];
static EventLeaf leaf;

typedef struct Queue {
    uint32_t q[QN];
    int      n, i;
    uint32_t answer;
} Queue;

static Queue randq;

static uint32_t next(Queue *q)
{
    return q->i < q->n ? q->q[q->i++] : q->answer;
}

// A pointer as both sides print it.
static const char *P(const void *p)
{
    static char ring[8][32];
    static int k;
    char *s = ring[k++ & 7];
    const uint8_t *b = (const uint8_t *)p;
    int i;

    if (p == NULL)
        return "-";
    for (i = 0; i < nblocks; i++) {
        if (blocks[i] == p) {
            snprintf(s, 32, "M%d", i);
            return s;
        }
    }
    if (p == (const void *)&loose)
        return "L";
    if (b >= (const uint8_t *)&Fred && b < (const uint8_t *)&Fred + sizeof Fred) {
        snprintf(s, 32, "F%d", (int)(b - (const uint8_t *)&Fred));
        return s;
    }
    if (b + WINDOW >= data && b < data + ndata + WINDOW) {
        snprintf(s, 32, "B%ld", (long)(b - data));
        return s;
    }
    snprintf(s, 32, "?%x", (unsigned)(uintptr_t)p);
    return s;
}

static void hex(const uint8_t *p, int n)
{
    int i;

    for (i = 0; i < n; i++)
        printf("%02x", p[i]);
}

static void state_hex(const uint8_t *s)
{
    if (s == NULL) {
        printf("-");
        return;
    }
    hex(s, 16);
}

// ---------------------------------------------------------------- stubs

void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *p = calloc(1, (size_t)size + 16);

    if (p == NULL || nblocks >= NBLOCKS) {
        fprintf(stderr, "out of blocks\n");
        exit(3);
    }
    blocks[nblocks] = p;
    if (strcmp(name, "bWare/inc/bWare.hpp") == 0)
        printf("  malloc %s %d %d %d -> M%d\n", name, flags, pool, size,
               nblocks);
    else
        printf("  malloc %s %d %d -> M%d\n", name, flags, pool, nblocks);
    nblocks++;
    return p;
}

// The block is kept: a tree once deleted is still read by retail's
// loader, and its address is never handed out again.
void bFree(void *p)
{
    printf("  free %s\n", P(p));
}

static void *tex_stub(uint32_t hash, int use_default,
                              int include_unloaded)
{
    uint32_t r = 0x0f000000u + 16u * ntex++;

    printf("  tex %08x %d %d -> %x\n", (unsigned)hash, use_default,
           include_unloaded, (unsigned)r);
    return (void *)(uintptr_t)r;
}

static const char *translate(int32_t id)
{
    static char ring[8][24];
    static int k;
    char *s = ring[k++ & 7];

    printf("  tr %d\n", (int)id);
    snprintf(s, 24, "S%d", (int)id);
    return s;
}

static int32_t language(void)
{
    return 3;
}

void timer_print_to_string(const Timer *t, char *buf, int32_t flags,
                           int32_t lang)
{
    printf("  timer %d %d%s\n", (int)t->PackedTime, (int)flags,
           lang == 3 ? "" : " ?lang");
    sprintf(buf, "T%d", (int)t->PackedTime);
}

int32_t bRandomI(int32_t range, uint32_t *seed)
{
    int32_t r = (int32_t)next(&randq);

    printf("  random%s %d -> %d\n", seed == &bDefaultSeed ? "" : " ?seed",
           (int)range, (int)r);
    return r;
}

static int32_t egg_is_on(int32_t n)
{
    return (uint32_t)n < 8u ? eggs[n] : 0;
}

// ------------------------------------------------------------- the script

static char *fields[40];
static int   nfields;

static int split(char *s)
{
    nfields = 0;
    while (nfields < 40) {
        char *bar = strchr(s, '|');

        fields[nfields++] = s;
        if (bar == NULL)
            break;
        *bar = 0;
        s = bar + 1;
    }
    return nfields;
}

static int32_t I(int j)
{
    return (int32_t)strtoll(fields[j], NULL, 0);
}

static uint32_t U(int j)
{
    return (uint32_t)strtoull(fields[j], NULL, 0);
}

// A hex field's bytes into p, at most n; the count written.
static int unhex(int j, uint8_t *p, int n)
{
    const char *s = fields[j];
    int k = 0;

    while (k < n && s[0] && s[1]) {
        unsigned v;

        sscanf(s, "%2x", &v);
        p[k++] = (uint8_t)v;
        s += 2;
    }
    return k;
}

static const char *name_arg(int j)
{
    return strcmp(fields[j], "-") == 0 ? NULL : fields[j];
}

static EventTree *tree_at(int32_t k)
{
    bNode *n;

    if (k < 0)
        return &loose;
    for (n = gEventTrees.next; n != &gEventTrees; n = n->next)
        if (k-- == 0)
            return (EventTree *)n;
    fprintf(stderr, "no tree %d\n", (int)k);
    exit(2);
}

static void globals(void)
{
    printf("  globals ch %s hp %s w %s ult %s\n", P(gChampionshipTree),
           P(gHotPursuitTree), P(gEventTreeWord16704),
           P(event_tree_ultimate_state()));
}

static void list(void)
{
    bNode *n;

    printf("list");
    for (n = gEventTrees.next; n != &gEventTrees; n = n->next)
        printf(" %s", P(n));
    printf("\n");
}

static void bits(const char *tag, const float *f, int n)
{
    int i;

    printf("  %s", tag);
    for (i = 0; i < n; i++) {
        uint32_t u;

        memcpy(&u, &f[i], 4);
        printf(" %x", (unsigned)u);
    }
    printf("\n");
}

static void dump(const EventTree *t)
{
    int i;

    printf("tree %s type %d name %s\n", P(t), (int)t->nType,
           t->pName != NULL ? t->pName : "-");
    printf("  name %s cam %s\n", P(t->pName), P(t->pCameraMover));
    printf("  cars %s %d tracks %s %d goals %s %d\n", P(t->pCars),
           (int)t->nCars, P(t->pTracks), (int)t->nTracks, P(t->pGoals),
           (int)t->nGoals);
    printf("  rewards %s %d opps %s %d\n", P(t->pRewards), (int)t->nRewards,
           P(t->pOpponents), (int)t->nOpponents);
    printf("  events %s %d leaves %s state %d\n", P(t->pEvents),
           (int)t->nEvents, P(t->pLeaves), (int)t->nStateSize);
    printf("  polys %s %d line %s leaf %s cur %s\n", P(t->pPolys),
           (int)t->nPolys, P(t->pLineTexture), P(t->pCurrentLeaf),
           P(t->pCurrentEvent));
    bits("center", t->vCenter, 3);
    printf("  lines %d pad %x %x %x\n", (int)t->bShowLines,
           (unsigned)t->pad116[0], (unsigned)t->pad116[1],
           (unsigned)t->pad116[2]);
    bits("num", t->mNumberMatrix, 16);
    bits("class", t->mClassMatrix, 16);
    printf("  tex");
    for (i = 0; i < 8; i++)
        printf(" %x", (unsigned)(uintptr_t)t->RaceTypeToTextureTable[i]);
    printf("\n");
}

static void events(const EventTree *t)
{
    int i;

    for (i = 0; i < t->nEvents; i++) {
        const EventInfo *e = &t->pEvents[i];

        printf("  ev %s #%d tree %s state %s\n", P(e), (int)e->nNumber,
               P(event_info_tree(e)), P(event_info_state(e)));
    }
}

static void fdump(void)
{
    printf("fred ");
    hex(Fred.ChampionshipState, 256);
    printf(" ");
    hex(Fred.HotPursuitState, 256);
    printf(" ult %s\n", P(event_tree_ultimate_state()));
}

static void ev(void)
{
    const char *o = fields[1];
    EventInfo *e = (EventInfo *)(data + I(2));

    printf("ev %s %s", o, P(e));
    if (!strcmp(o, "car")) {
        printf(" %d -> %s\n", (int)I(3), P(event_info_get_car(e, I(3))));
    } else if (!strcmp(o, "goal")) {
        printf(" %d -> %s\n", (int)I(3), P(event_info_get_goal(e, I(3))));
    } else if (!strcmp(o, "track")) {
        printf(" %d -> %s\n", (int)I(3), P(event_info_get_track(e, I(3))));
    } else if (!strcmp(o, "reward")) {
        printf(" %d -> %s\n", (int)I(3), P(event_info_get_reward(e, I(3))));
    } else if (!strcmp(o, "opp")) {
        printf(" %d -> %s\n", (int)I(3), P(event_info_get_opponent(e, I(3))));
    } else if (!strcmp(o, "obj")) {
        printf(" -> %s\n", P(event_info_get_objective(e)));
    } else if (!strcmp(o, "rank")) {
        printf(" -> %s\n", P(event_info_rank_state(e)));
    } else if (!strcmp(o, "tour")) {
        printf(" -> %s\n", P(event_info_tournament_state(e)));
    } else if (!strcmp(o, "ko")) {
        printf(" -> %s\n", P(event_info_ko_state(e)));
    } else if (!strcmp(o, "time")) {
        printf(" -> %s\n", P(event_info_time_state(e)));
    } else if (!strcmp(o, "earned")) {
        printf(" %d\n", (int)I(3));
        printf("  -> %d\n", (int)event_info_reward_earned(e, I(3)));
    } else if (!strcmp(o, "size")) {
        printf(" -> %d\n", (int)event_info_get_state_size(e));
    } else if (!strcmp(o, "finish")) {
        const uint8_t *s = event_info_state(e);

        // A place past GetFinishString's table is the port's own.
        if ((e->nType == EVENT_RACE || e->nType == EVENT_LAP_KNOCKOUT)
            && s != NULL && s[0] >= 16) {
            printf(" skip\n");
        } else {
            printf("\n");
            printf("  -> %s\n", event_info_get_finish_string(e));
        }
    } else if (!strcmp(o, "last")) {
        printf(" -> %d\n", (int)event_info_is_last_open(e));
    } else if (!strcmp(o, "status")) {
        printf(" -> %d\n", (int)event_info_get_status(e, NULL));
    } else if (!strcmp(o, "statusg")) {
        printf(" -> %d\n", (int)event_info_get_status(e, &goal));
    } else if (!strcmp(o, "ridx")) {
        printf(" -> %d\n", (int)event_info_get_race_index(e));
    } else if (!strcmp(o, "rcount")) {
        printf(" -> %d\n", (int)event_info_get_race_count(e));
    } else if (!strcmp(o, "reset")) {
        event_info_reset_state(e);
        printf(" | ");
        state_hex(event_info_state(e));
        printf("\n");
    } else if (!strcmp(o, "unlock")) {
        event_info_unlock_state(e);
        printf(" | ");
        state_hex(event_info_state(e));
        printf("\n");
    } else if (!strcmp(o, "multi")) {
        printf(" -> %d\n", (int)event_info_is_multi_track(e));
    } else if (!strcmp(o, "setcar")) {
        event_info_set_selected_car(e, I(3), I(4), I(5));
        printf(" %d %d %d | ", (int)I(3), (int)I(4), (int)I(5));
        state_hex(event_info_state(e));
        printf("\n");
    } else if (!strcmp(o, "getcar")) {
        int32_t c = -99, s = -99, d = -99;

        event_info_get_selected_car(e, &c, &s, &d);
        printf(" -> %d %d %d\n", (int)c, (int)s, (int)d);
    } else if (!strcmp(o, "put")) {
        uint8_t *s = event_info_state(e);

        if (s != NULL)
            unhex(3, s, 16);
        printf(" | ");
        state_hex(s);
        printf("\n");
    } else {
        fprintf(stderr, "bad ev op %s\n", o);
        exit(2);
    }
}

static void tr(void)
{
    const char *o = fields[1];
    EventTree *t = tree_at(I(2));

    printf("tr %s %s", o, P(t));
    if (!strcmp(o, "num")) {
        printf(" %d -> %s\n", (int)I(3),
               P(event_tree_get_event_number(t, I(3))));
    } else if (!strcmp(o, "idx")) {
        printf(" %d -> %d\n", (int)I(3),
               (int)event_tree_get_event_index(t, I(3)));
    } else if (!strcmp(o, "reset")) {
        printf("\n");
        event_tree_reset_state(t);
    } else if (!strcmp(o, "unlock")) {
        printf("\n");
        event_tree_unlock_state(t);
    } else if (!strcmp(o, "cur")) {
        EventInfo *e = (EventInfo *)(data + I(3));

        leaf.pTree = t;
        leaf.pInfo = e;
        t->pCurrentLeaf = &leaf;
        event_tree_unlock_current_node(t);
        printf(" %s | ", P(e));
        state_hex(event_info_state(e));
        printf("\n");
        t->pCurrentLeaf = NULL;
    } else if (!strcmp(o, "carunl")) {
        printf(" %d -> %d\n", (int)I(3),
               (int)event_tree_is_car_unlocked(t, I(3)));
    } else if (!strcmp(o, "carrew")) {
        printf(" %d -> %d\n", (int)I(3),
               (int)event_tree_car_is_a_reward(t, I(3)));
    } else if (!strcmp(o, "findcar")) {
        printf(" %d -> %s\n", (int)I(3),
               P(event_tree_find_event_car_is_a_reward_for(t, I(3))));
    } else if (!strcmp(o, "trkunl")) {
        printf(" %d %d -> %d\n", (int)I(3), (int)I(4),
               (int)event_tree_is_track_unlocked(t, I(3), I(4)));
    } else if (!strcmp(o, "trkrew")) {
        printf(" %d %d -> %d\n", (int)I(3), (int)I(4),
               (int)event_tree_track_is_a_reward(t, I(3), I(4)));
    } else if (!strcmp(o, "findtrk")) {
        printf(" %d %d -> %s\n", (int)I(3), (int)I(4),
               P(event_tree_find_event_track_is_a_reward_for(t, I(3),
                                                             I(4))));
    } else if (!strcmp(o, "calc")) {
        printf(" F%d %d\n", (int)I(3), (int)I(4));
        event_tree_calc_state_pointers(t, (uint8_t *)&Fred + I(3),
                                       EVENT_TREE_STATE_SIZE, I(4));
        printf("  state %d ult %s\n", (int)t->nStateSize,
               P(event_tree_ultimate_state()));
        events(t);
    } else if (!strcmp(o, "setname")) {
        printf(" %s\n", fields[3]);
        printf("  -> %d\n", (int)event_tree_set_name(t, name_arg(3)));
        printf("  type %d name %s\n", (int)t->nType,
               t->pName != NULL ? t->pName : "-");
        globals();
    } else if (!strcmp(o, "setevents")) {
        printf(" B%d %d\n", (int)I(3), (int)I(4));
        event_tree_set_events(t, data + I(3), I(4));
        printf("  events %s %d cur %s\n", P(t->pEvents), (int)t->nEvents,
               P(t->pCurrentEvent));
        events(t);
    } else if (!strcmp(o, "passed")) {
        printf(" -> %d\n", (int)event_goal_passed(&goal, t));
    } else {
        fprintf(stderr, "bad tr op %s\n", o);
        exit(2);
    }
}

static void gl(void)
{
    const char *o = fields[1];

    printf("gl %s", o);
    if (!strcmp(o, "carrew")) {
        printf(" %d -> %d\n", (int)I(2), (int)is_car_an_event_reward(I(2)));
    } else if (!strcmp(o, "carunl")) {
        printf(" %d -> %d\n", (int)I(2),
               (int)event_tree_is_car_unlocked_any(I(2)));
    } else if (!strcmp(o, "findcar")) {
        printf(" %d -> %s\n", (int)I(2),
               P(find_event_that_car_is_a_reward_for(I(2))));
    } else if (!strcmp(o, "findtrk")) {
        printf(" %d %d -> %s\n", (int)I(2), (int)I(3),
               P(find_event_that_track_is_a_reward_for(I(2), I(3))));
    } else if (!strcmp(o, "trkrew")) {
        printf(" %d %d -> %d\n", (int)I(2), (int)I(3),
               (int)is_track_an_event_reward(I(2), I(3)));
    } else if (!strcmp(o, "trkunl")) {
        printf(" %d %d -> %d\n", (int)I(2), (int)I(3),
               (int)event_tree_is_track_unlocked_any(I(2), I(3)));
    } else if (!strcmp(o, "numcars")) {
        printf(" -> %d\n", (int)event_trees_num_cars_unlocked());
    } else if (!strcmp(o, "lock")) {
        printf("\n");
        lock_events();
    } else if (!strcmp(o, "unlock")) {
        printf("\n");
        unlock_events();
    } else if (!strcmp(o, "both")) {
        printf(" -> %d\n", (int)event_trees_both_ultimates_passed());
    } else if (!strcmp(o, "get")) {
        printf(" %s -> %s\n", fields[2], P(get_event_tree(fields[2])));
    } else {
        fprintf(stderr, "bad gl op %s\n", o);
        exit(2);
    }
}

static void state(void)
{
    const char *o = fields[1];
    int32_t a = nfields > 2 ? I(2) : 0;
    int32_t b = nfields > 3 ? I(3) : 0;
    int32_t c = nfields > 4 ? I(4) : 0;
    int j;

    printf("state %s", o);
    for (j = 2; j < nfields; j++)
        printf(" %s", fields[j]);
    if (!strcmp(o, "rreset")) {
        rank_state_reset(st);
    } else if (!strcmp(o, "runlock")) {
        rank_state_unlock(st, &goal);
    } else if (!strcmp(o, "rstatus")) {
        printf(" -> %d", (int)rank_state_get_status(st, &goal));
    } else if (!strcmp(o, "treset")) {
        time_state_reset(st);
    } else if (!strcmp(o, "tunlock")) {
        time_state_unlock(st, &goal);
    } else if (!strcmp(o, "tstatus")) {
        printf(" -> %d", (int)time_state_get_status(st, &goal));
    } else if (!strcmp(o, "kreset")) {
        ko_state_reset(st);
    } else if (!strcmp(o, "kunlock")) {
        ko_state_unlock(st, &goal, a);
    } else if (!strcmp(o, "kidx")) {
        printf(" -> %d", (int)ko_state_get_race_index(st));
    } else if (!strcmp(o, "krank")) {
        printf(" -> %d", (int)ko_state_get_rank(st, a));
    } else if (!strcmp(o, "kset")) {
        ko_state_set_rank(st, a, b);
    } else if (!strcmp(o, "kstatus")) {
        printf(" -> %d", (int)ko_state_get_status(st, &goal));
    } else if (!strcmp(o, "ksetcar")) {
        ko_state_set_selected_car(st, a, b, c);
    } else if (!strcmp(o, "kgetcar")) {
        int32_t x = -99, y = -99, z = -99;

        ko_state_get_selected_car(st, &x, &y, &z);
        printf(" -> %d %d %d", (int)x, (int)y, (int)z);
    } else if (!strcmp(o, "kspos")) {
        ko_state_set_start_position(st, a, b);
    } else if (!strcmp(o, "kgpos")) {
        printf(" -> %d", (int)ko_state_get_start_position(st, a));
    } else if (!strcmp(o, "kseed")) {
        printf(" -> %u", (unsigned)ko_state_get_seed(st));
    } else if (!strcmp(o, "knew")) {
        printf("\n");
        ko_state_new_seed(st);
    } else if (!strcmp(o, "oreset")) {
        tournament_state_reset(st);
    } else if (!strcmp(o, "ounlock")) {
        tournament_state_unlock(st, &goal, a);
    } else if (!strcmp(o, "oidx")) {
        printf(" -> %d", (int)tournament_state_get_race_index(st, a));
    } else if (!strcmp(o, "oracer")) {
        printf(" -> %d", (int)tournament_state_racer_rank(st, a));
    } else if (!strcmp(o, "ouser")) {
        printf(" -> %d", (int)tournament_state_user_rank(st));
    } else if (!strcmp(o, "opoints")) {
        printf(" -> %d", (int)tournament_state_points_for_finish_pos(a));
    } else if (!strcmp(o, "ostatus")) {
        printf(" -> %d", (int)tournament_state_get_status(st, &goal, a, b));
    } else if (!strcmp(o, "osetcar")) {
        tournament_state_set_selected_car(st, a, b, c);
    } else if (!strcmp(o, "ogetcar")) {
        int32_t x = -99, y = -99, z = -99;

        tournament_state_get_selected_car(st, &x, &y, &z);
        printf(" -> %d %d %d", (int)x, (int)y, (int)z);
    } else if (!strcmp(o, "oseed")) {
        printf(" -> %u", (unsigned)tournament_state_get_seed(st));
    } else if (!strcmp(o, "onew")) {
        printf("\n");
        tournament_state_new_seed(st);
    } else {
        fprintf(stderr, "bad state op %s\n", o);
        exit(2);
    }
    printf(" | ");
    hex(st, 16);
    printf("\n");
}

static void run(void)
{
    const char *o = fields[0];

    if (!strcmp(o, "e3")) {
        bVersionE3 = I(1);
    } else if (!strcmp(o, "all")) {
        gUnlockAllEvents = I(1);
    } else if (!strcmp(o, "egg")) {
        eggs[I(1)] = I(2);
    } else if (!strcmp(o, "fredclr")) {
        memset(Fred.ChampionshipState, 0, sizeof Fred.ChampionshipState);
        memset(Fred.HotPursuitState, 0, sizeof Fred.HotPursuitState);
        Fred.pUltimateState = 0;
    } else if (!strcmp(o, "fred")) {
        unhex(2, (uint8_t *)&Fred + I(1), 512);
    } else if (!strcmp(o, "ult")) {
        Fred.pUltimateState = U(1);
    } else if (!strcmp(o, "fdump")) {
        fdump();
    } else if (!strcmp(o, "goal")) {
        goal.nType = (uint16_t)I(1);
        goal.nEvent = (uint16_t)I(2);
        goal.nData = U(3);
    } else if (!strcmp(o, "st")) {
        memset(st, 0, sizeof st);
        unhex(1, st, 32);
    } else if (!strcmp(o, "randq")) {
        int j;

        randq.n = 0;
        randq.i = 0;
        for (j = 1; j < nfields && randq.n < QN; j++)
            randq.q[randq.n++] = U(j);
    } else if (!strcmp(o, "rand")) {
        randq.answer = U(1);
    } else if (!strcmp(o, "glob")) {
        printf("glob\n");
        globals();
    } else if (!strcmp(o, "word")) {
        gEventTreeWord16704 = tree_at(I(1));
    } else if (!strcmp(o, "load")) {
        int r;

        printf("load B%d\n", (int)I(1));
        r = loader_event_tree(data + I(1));
        printf("  -> %d\n", r);
        globals();
    } else if (!strcmp(o, "unload")) {
        int r;

        printf("unload B%d\n", (int)I(1));
        r = unloader_event_tree(data + I(1));
        printf("  -> %d\n", r);
        globals();
    } else if (!strcmp(o, "list")) {
        list();
    } else if (!strcmp(o, "dump")) {
        dump(tree_at(I(1)));
    } else if (!strcmp(o, "events")) {
        printf("events %s\n", P(tree_at(I(1))));
        events(tree_at(I(1)));
    } else if (!strcmp(o, "ctor")) {
        printf("ctor %s\n", fields[1]);
        memset(&loose, 0, sizeof loose);
        event_tree_construct(&loose, name_arg(1));
        dump(&loose);
        globals();
    } else if (!strcmp(o, "dtor")) {
        printf("dtor %d\n", (int)I(1));
        event_tree_destruct(&loose, I(1));
    } else if (!strcmp(o, "ev")) {
        ev();
    } else if (!strcmp(o, "tr")) {
        tr();
    } else if (!strcmp(o, "gl")) {
        gl();
    } else if (!strcmp(o, "state")) {
        state();
    } else {
        fprintf(stderr, "bad op %s\n", o);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[8192];
    uint8_t *raw;
    FILE *f;
    long n;

    if (argc != 3) {
        fprintf(stderr, "usage: eventtree_test script.txt data.bin\n");
        return 2;
    }
    f = fopen(argv[2], "rb");
    if (f == NULL) {
        perror(argv[2]);
        return 2;
    }
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    ndata = (size_t)n;
    // 16-aligned, as the model's copy is.
    raw = (uint8_t *)malloc(ndata + 16);
    data = raw == NULL ? NULL
         : (uint8_t *)(((uintptr_t)raw + 15) & ~(uintptr_t)15);
    if (data == NULL || fread(data, 1, ndata, f) != ndata) {
        fprintf(stderr, "cannot read %s\n", argv[2]);
        return 2;
    }
    fclose(f);
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    gFredTranslateFn = translate;
    gCurrLanguageFn = language;
    gEggIsOnFn = egg_is_on;
    gGetTextureInfoFn = tex_stub;
    while (fgets(line, sizeof line, f) != NULL) {
        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        split(line);
        run();
        fflush(stdout);
    }
    fclose(f);
    return 0;
}
