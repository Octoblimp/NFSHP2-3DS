// fredevent_test -- tools/fredevent_check.py's harness.
//
// Runs fredevent.c over the checker's script and its data file (the event
// trees of tools/eventtree_check.py), with eventtree.c, eventrace.c,
// raceevent.c and bprintf.c under it, as retail's FrontendDatabase.obj runs
// on EventTree.obj and RaceEvent.obj. What the port calls outside them is a
// stub here that logs and answers as the model's stubs do: GetTrackInfo,
// IsTrackUnlocked, bRandom, FrontendPlayerInfo's SetCarAvailability,
// AssignCarOfType and GetSelectedRideInfo, StartRace, and
// GetTranslatedString by id and by text for SetRace.
//
//     fredevent_test script.txt data.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "bmem.h"
#include "car.h"
#include "cartypeinfo.h"
#include "characterinfo.h"
#include "configitems.h"
#include "copmanager.h"
#include "eventrace.h"
#include "eventtree.h"
#include "fred.h"
#include "fredend.h"
#include "fredevent.h"
#include "fredrace.h"
#include "playersettings.h"
#include "quickrace.h"
#include "raceevent.h"
#include "raceinit.h"
#include "raceparams.h"
#include "racesplit.h"
#include "replay.h"
#include "startrace.h"
#include "timer.h"
#include "track.h"

#define QN       64
#define NBLOCKS  4096
#define WINDOW   0x24000
#define NTRACKS  40
#define NDESCS   64
#define TEXT     1100
#define PAD      0x2000

// ---------------------------------------------------- what the port reads

FrontendDatabase Fred;
RaceParameters   TheRaceParameters;
tCopManager     *pCopManager;
uint32_t         bDefaultSeed;
int32_t          bVersionE3;
int32_t          HighestTrackNumber;
const CarTypeInfo *CarTypeInfoArray;
const char    *(*gFredTranslateFn)(int32_t id);
int32_t        (*gCurrLanguageFn)(void);
EggIsOnFn        gEggIsOnFn;
void          *(*gGetTextureInfoFn)(uint32_t name_hash, int use_default,
                                    int include_unloaded);
int32_t SkipFERearView, SkipFESpeedoMode, SkipFEEnableJumpCam,
        SkipFEEnableZoneCam;

// The event's bytes from aOldState on, and the race parameters' up to the
// driver table, are retail's on any host.
typedef char layout_check[
    (sizeof(RaceEvent) - offsetof(RaceEvent, aOldState) == 424
     && offsetof(RaceParameters, BoostScale) == 764
     && sizeof(EventGoal) == 8 && sizeof(EventReward) == 8
     && sizeof(CarStatus) == 24)
    ? 1 : -1];

static uint8_t    *data;
static size_t      ndata;
static void       *blocks[NBLOCKS];
static int         nblocks;
static CarTypeInfo ctinfo[256];
static CarSpecs    specs[256];
static TrackInfo   tinfo[NTRACKS];
static uint8_t     unl[64];
static RideInfo    ride;
static EventGoal   goal;

static struct {
    int32_t id;
    char    text[TEXT];
} descs[NDESCS];
static int ndescs;

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
    const uint8_t *ev = (const uint8_t *)&TheRaceEvent;
    const uint8_t *ol = (const uint8_t *)&TheEventsOpened;
    int i;

    if (p == NULL)
        return "-";
    for (i = 0; i < nblocks; i++) {
        if (blocks[i] == p) {
            snprintf(s, 32, "M%d", i);
            return s;
        }
    }
    if (b >= (const uint8_t *)&Fred && b < (const uint8_t *)&Fred + sizeof Fred) {
        snprintf(s, 32, "F%d", (int)(b - (const uint8_t *)&Fred));
        return s;
    }
    // Retail's offsets: the tree and the state are 4 bytes each there.
    if (b >= ev && b < ev + sizeof TheRaceEvent) {
        const uint8_t *old = TheRaceEvent.aOldState;

        snprintf(s, 32, "E%d", b >= old ? (int)(8 + (b - old))
                               : b >= (const uint8_t *)&TheRaceEvent.pState
                               ? 4 : 0);
        return s;
    }
    if (b >= ol && b < ol + sizeof TheEventsOpened) {
        snprintf(s, 32, "O%d", (int)(b - ol));
        return s;
    }
    if (p == &ride)
        return "RIDE";
    if (b + WINDOW >= data && b < data + ndata + WINDOW) {
        snprintf(s, 32, "B%ld", (long)(b - data));
        return s;
    }
    snprintf(s, 32, "?%x", (unsigned)(uintptr_t)p);
    return s;
}

static void hex(const void *p, int n)
{
    const uint8_t *b = (const uint8_t *)p;
    int i;

    for (i = 0; i < n; i++)
        printf("%02x", b[i]);
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

void bFree(void *p)
{
    printf("  free %s\n", P(p));
}

static void *tex_stub(uint32_t hash, int use_default, int include_unloaded)
{
    static uint32_t ntex;
    uint32_t r = 0x0f000000u + 16u * ntex++;

    printf("  tex %08x %d %d -> %x\n", (unsigned)hash, use_default,
           include_unloaded, (unsigned)r);
    return (void *)(uintptr_t)r;
}

static char *ring(void)
{
    static char r[8][TEXT];
    static int k;

    return r[k++ & 7];
}

// GetTranslatedString(int): a script's text for its id, else "S" and the
// id.
static const char *translate(int32_t id)
{
    char *s = ring();
    int i;

    printf("  tr %d\n", (int)id);
    for (i = 0; i < ndescs; i++) {
        if (descs[i].id == id) {
            strcpy(s, descs[i].text);
            return s;
        }
    }
    snprintf(s, TEXT, "S%d", (int)id);
    return s;
}

// GetTranslatedString(const char *): "Q" and the first 20 characters.
static const char *translate_string(const char *t)
{
    char *s = ring();

    printf("  trs %s\n", t);
    snprintf(s, TEXT, "Q%.20s", t);
    return s;
}

static int32_t language(void)
{
    return 3;
}

// "T" and the time, after two spaces for a time divisible by 3.
void timer_print_to_string(const Timer *t, char *b, int32_t flags,
                           int32_t lang)
{
    printf("  timer %d %d%s\n", (int)t->PackedTime, (int)flags,
           lang == 3 ? "" : " ?lang");
    sprintf(b, "%sT%d", t->PackedTime % 3 == 0 ? "  " : "",
            (int)t->PackedTime);
}

// The queue's next answer, held under the range.
int32_t bRandomI(int32_t range, uint32_t *seed)
{
    uint32_t q = next(&randq);
    int32_t r = range > 0 ? (int32_t)(q % (uint32_t)range) : (int32_t)q;

    printf("  random%s %d -> %d\n", seed == &bDefaultSeed ? "" : " ?seed",
           (int)range, (int)r);
    return r;
}

static int32_t egg_is_on(int32_t n)
{
    (void)n;
    return 0;
}

const CarTypeInfo *cartypeinfo_get(int32_t type)
{
    return &ctinfo[type & 255];
}

TrackInfo *track_get_info(int i)
{
    printf("  trackinfo %d\n", i);
    return (unsigned)i < NTRACKS ? &tinfo[i] : NULL;
}

// The script's mask: bit 2 x track + direction.
int32_t is_track_unlocked(int32_t track, int32_t direction)
{
    int bit = (track & 0xff) * 2 + (direction & 1);
    int32_t r = unl[bit >> 3] >> (bit & 7) & 1;

    printf("  unlocked %d %d -> %d\n", (int)track, (int)direction, (int)r);
    return r;
}

void fpi_set_car_availability(FrontendPlayerInfo *p, int32_t status,
                              int32_t type, int32_t skin, int32_t dash)
{
    printf("  avail %s %d %d %d %d\n", P(p), (int)status, (int)type,
           (int)skin, (int)dash);
}

void fpi_assign_car_of_type(FrontendPlayerInfo *p, int32_t mode,
                            int32_t type, uint32_t skin, int32_t dash)
{
    printf("  assign %s %d %d %d %d\n", P(p), (int)mode, (int)type,
           (int)skin, (int)dash);
}

RideInfo *fpi_get_selected_ride_info(FrontendPlayerInfo *p, int32_t gameType)
{
    printf("  ride %s %d\n", P(p), (int)gameType);
    return &ride;
}

void fred_start_race(FrontendDatabase *f)
{
    printf("  startrace %s\n", P(f));
}

// startrace.c's, which the harness does not link.
int32_t get_the_right_track_language_id(const TrackInfo *t, int32_t dir)
{
    if (dir == TRACK_DIRECTION_FORWARD)
        return t->TrackLanguageID;
    if (dir == TRACK_DIRECTION_BACKWARD)
        return t->ReverseTrackLanguageID;
    return 0;
}

// What raceevent.c and raceparams.c reach for, none of it run here.
int32_t config_skip_fe(void)
{
    return 0;
}

void player_settings_reset_to_defaults(cPlayerSettings *ps)
{
    memset(ps, 0, sizeof *ps);
}

int32_t fred_race_was_aborted(const FrontendDatabase *f)
{
    return f->bRaceWasAborted;
}

void fred_calculate_starting_positions(FrontendDatabase *f)
{
    (void)f;
    printf("  csp\n");
}

Timer *racingcar_get_last_best_lap_time(struct RacingCar *rc)
{
    static Timer t;

    (void)rc;
    return &t;
}

void timer_set_time(Timer *t, float seconds)
{
    t->PackedTime = (int32_t)seconds;
}

// ------------------------------------------------------------- the script

#define NFIELDS (QN + 8)

static char *fields[NFIELDS];
static int   nfields;

static int split(char *s)
{
    nfields = 0;
    while (nfields < NFIELDS) {
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

static EventTree *tree_at(int32_t k)
{
    bNode *n;

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

static void fill(uint8_t *p, int n, int seed, int step)
{
    int i;

    for (i = 0; i < n; i++)
        p[i] = (uint8_t)(seed + step * i);
}

static void rp_dump(void)
{
    const uint8_t *r = (const uint8_t *)&TheRaceParameters;

    printf("  rp0 ");
    hex(r, 84);
    printf("\n  obj %s\n  objx ", TheRaceParameters.sObjective);
    hex(r + 84, 512);
    printf("\n  rp1 ");
    hex(r + 596, 176);
    printf(" %d %d %d\n", (int)TheRaceParameters.NumDriverInfo,
           (int)TheRaceParameters.New780, (int)TheRaceParameters.New784);
}

static void ev_dump(const EventTree *t, const EventInfo *e)
{
    const RaceEvent *ev = &TheRaceEvent;
    const uint8_t *s = event_info_state(e);

    printf("  cur %s ce %d\n", P(t->pCurrentEvent), (int)Fred.nCurrentEvent);
    printf("  ev %s %s ", P(ev->pTree), P(ev->pState));
    hex(ev->aOldState, 96);
    printf("\n  ev1 ");
    hex(&ev->nNumber, 328);
    printf("\n  st ");
    if (s == NULL)
        printf("-");
    else
        hex(s, 16);
    printf("\n");
}

// TheRaceEvent from aOldState on.
static void tre_dump(void)
{
    printf("  ev %s %s ", P(TheRaceEvent.pTree), P(TheRaceEvent.pState));
    hex(TheRaceEvent.aOldState, 424);
    printf("\n");
}

// Both players' car statuses.
static void status_dump(void)
{
    int p, i;

    for (p = 0; p < 2; p++) {
        printf("  st%d ", p);
        for (i = 0; i < FRED_NUM_CAR_TYPES; i++)
            printf("%08x", (unsigned)Fred.FrontendPlayers[p].aCarStatus[i]
                                          .nStatus);
        printf("\n");
    }
}

static void list_dump(void)
{
    printf("  list ");
    hex(&TheEventsOpened, sizeof TheEventsOpened);
    printf("\n");
}

// The record `rec` of a tree's table, and its bytes when it is in the data.
static void rec_print(const uint8_t *rec)
{
    printf("%s", P(rec));
    if (rec != NULL && rec >= data && rec + 4 <= data + ndata) {
        printf(" ");
        hex(rec, 4);
    }
    printf("\n");
}

// The tree and event the select screen chose, as both sides find them.
static EventInfo *selected(EventTree **tp)
{
    EventTree *t = fred_get_event_tree(&Fred);

    *tp = t;
    if (t == NULL)
        return NULL;
    return event_tree_get_event_number(
        t, data_event_select_get_selected_event(Fred.SelectedEventData,
                                                t->nType));
}

// Whether the selected event is a knockout or a tournament without a state,
// whose selected car retail reads from the bottom of memory and the port
// does not.
static int stateless_multi(const EventInfo *e)
{
    return e != NULL && (e->nType == 3 || e->nType == 4)
           && event_info_state(e) == NULL;
}

static void run(void)
{
    const char *o = fields[0];

    if (!strcmp(o, "e3")) {
        bVersionE3 = I(1);
    } else if (!strcmp(o, "all")) {
        gUnlockAllEvents = I(1);
    } else if (!strcmp(o, "ult")) {
        Fred.pUltimateState = U(1);
    } else if (!strcmp(o, "gl") && !strcmp(fields[1], "unlock")) {
        printf("gl unlock\n");
        unlock_events();
    } else if (!strcmp(o, "ev") && (!strcmp(fields[1], "put")
                                    || !strcmp(fields[1], "reset"))) {
        EventInfo *e = (EventInfo *)(data + I(2));
        uint8_t *s = event_info_state(e);

        printf("ev %s %s", fields[1], P(e));
        if (fields[1][0] == 'r')
            event_info_reset_state(e);
        else if (s != NULL)
            unhex(3, s, 16);
        printf(" | ");
        if (s == NULL)
            printf("-");
        else
            hex(s, 16);
        printf("\n");
    } else if (!strcmp(o, "fredclr")) {
        memset(Fred.ChampionshipState, 0, sizeof Fred.ChampionshipState);
        memset(Fred.HotPursuitState, 0, sizeof Fred.HotPursuitState);
        Fred.pUltimateState = 0;
    } else if (!strcmp(o, "fred")) {
        unhex(2, (uint8_t *)&Fred + I(1), 512);
    } else if (!strcmp(o, "randq")) {
        int j;

        randq.n = 0;
        randq.i = 0;
        for (j = 1; j < nfields && randq.n < QN; j++)
            randq.q[randq.n++] = U(j);
    } else if (!strcmp(o, "rand")) {
        randq.answer = U(1);
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
    } else if (!strcmp(o, "desc")) {
        if (!strcmp(fields[1], "clr")) {
            ndescs = 0;
        } else if (ndescs < NDESCS) {
            int i;

            for (i = 0; i < ndescs; i++)
                if (descs[i].id == I(1))
                    return;
            descs[ndescs].id = I(1);
            snprintf(descs[ndescs].text, TEXT, "%s", fields[2]);
            ndescs++;
        }
    } else if (!strcmp(o, "rpfill")) {
        RaceParameters *rp = &TheRaceParameters;

        fill((uint8_t *)rp, 772, I(1), 7);
        rp->NumDriverInfo = I(1) * 101;
        rp->New780 = I(1) * 103;
        rp->New784 = I(1) * 107;
    } else if (!strcmp(o, "evfill")) {
        TheRaceEvent.pTree = NULL;
        TheRaceEvent.pState = NULL;
        fill(TheRaceEvent.aOldState, 424, I(1), 3);
    } else if (!strcmp(o, "set")) {
        EventTree *t = tree_at(I(1));
        EventInfo *e = (EventInfo *)(data + I(2));

        printf("set %s %s", P(t), P(e));
        if (e->nCars > 20 || e->nTracks > 8 || e->nRewards > 8
            || e->nOpponents > 7
            || ((e->nType == 3 || e->nType == 4)
                && event_info_state(e) == NULL)) {
            printf(" skip\n");
            return;
        }
        printf("\n");
        event_tree_set_race(t, &TheRaceParameters, e);
        ev_dump(t, e);
        rp_dump();
    } else if (!strcmp(o, "tinfo")) {
        TrackInfo *t = &tinfo[I(1) % NTRACKS];

        t->TrackNumber = (int8_t)I(2);
        t->SameAsTrackNumber = (int8_t)I(3);
        t->Point2Point = (int8_t)I(4);
        t->TimeOfDay = (int16_t)I(5);
    } else if (!strcmp(o, "unl")) {
        memset(unl, 0, sizeof unl);
        unhex(1, unl, 64);
    } else if (!strcmp(o, "highest")) {
        HighestTrackNumber = I(1);
    } else if (!strcmp(o, "gt")) {
        Fred.GameType = I(1);
    } else if (!strcmp(o, "ncur")) {
        Fred.nCurrentEvent = I(1);
    } else if (!strcmp(o, "np")) {
        Fred.NumPlayerCars = I(1);
    } else if (!strcmp(o, "sel")) {
        int j;

        for (j = 0; j < 4; j++)
            Fred.SelectedEventData[j] = I(1 + j);
    } else if (!strcmp(o, "ko5")) {
        Fred.RaceKnockoutSetupData[5] = I(1);
    } else if (!strcmp(o, "ride")) {
        ride.Type = I(1);
        ride.InstanceIndex = (int8_t)I(2);
        ride.SkinNumber = (int8_t)I(3);
        ride.HasDash = (int8_t)I(4);
    } else if (!strcmp(o, "rpk")) {
        RaceParameters *rp = &TheRaceParameters;
        uint32_t d = U(6), c = U(7);

        rp->TrackNumber = I(1);
        rp->TrackWeather = I(2);
        rp->TrackTimeOfDay = I(3);
        rp->TrackDirection = (eTrackDirection)I(4);
        rp->NumLapsInRace = I(5);
        memcpy(&rp->TrafficDensity, &d, 4);
        memcpy(&rp->TrafficOncoming, &c, 4);
        rp->NumAICars = I(8);
    } else if (!strcmp(o, "ctnull")) {
        CarTypeInfoArray = I(1) ? NULL : ctinfo;
    } else if (!strcmp(o, "pfill")) {
        fill((uint8_t *)&Fred.FrontendPlayers[0].aCarStatus, 1536, I(1), 5);
        fill((uint8_t *)&Fred.FrontendPlayers[1].aCarStatus, 1536, I(1) + 1,
             5);
    } else if (!strcmp(o, "pad")) {
        unhex(2, data + ndata + I(1), 256);
    } else if (!strcmp(o, "ptab")) {
        // A tree's car table: the zeros after the data at an offset, none
        // (-1), or its own again (-2).
        static const uint8_t *own[16];
        static int saved[16];
        EventTree *t = tree_at(I(1));
        int k = I(1) & 15;

        if (!saved[k]) {
            own[k] = t->pCars;
            saved[k] = 1;
        }
        if (I(2) == -2) {
            t->pCars = own[k];
            saved[k] = 0;
        } else {
            t->pCars = I(2) == -1 ? NULL : data + ndata + I(2);
        }
    } else if (!strcmp(o, "tree")) {
        printf("tree -> %s\n", P(fred_get_event_tree(&Fred)));
    } else if (!strcmp(o, "getsel")) {
        printf("getsel %d -> %d\n", (int)I(1),
               (int)data_event_select_get_selected_event(
                   Fred.SelectedEventData, I(1)));
    } else if (!strcmp(o, "setsel") || !strcmp(o, "settype")) {
        int32_t *d = Fred.SelectedEventData;

        if (!strcmp(o, "setsel"))
            data_event_select_set_selected_event(d, I(1), I(2));
        else
            data_event_select_set_tree_type(d, I(1));
        printf("%s -> %d %d %d %d\n", o, (int)d[0], (int)d[1], (int)d[2],
               (int)d[3]);
    } else if (!strcmp(o, "flush")) {
        printf("flush %d\n", (int)I(1));
        fpi_flush_available_cars(&Fred.FrontendPlayers[I(1) & 1]);
        status_dump();
    } else if (!strcmp(o, "cars")) {
        EventTree *t = tree_at(I(1));
        EventInfo *e = (EventInfo *)(data + I(2));
        int i;

        // A record outside the data and its zeros is skipped, and without
        // a table an index under 0 (retail's would read past the top of
        // memory, the port's its zeros).
        printf("cars %s %s", P(t), P(e));
        for (i = 0; i < e->nCars; i++) {
            int16_t idx;
            const uint8_t *rec;

            memcpy(&idx, (const uint8_t *)e + 68 + 2 * i, 2);
            rec = t->pCars + 4 * idx;
            if (t->pCars == NULL ? idx < 0
                : rec < data || rec + 4 > data + ndata + PAD) {
                printf(" skip\n");
                return;
            }
        }
        printf("\n");
        fred_make_event_cars_available(&Fred, t, e);
        status_dump();
    } else if (!strcmp(o, "maybe")) {
        EventTree *t;
        EventInfo *e = selected(&t);

        printf("maybe");
        if (fred_use_tree_event(&Fred) && stateless_multi(e)) {
            printf(" skip\n");
            return;
        }
        printf("\n");
        fred_maybe_set_selected_car_for_multi_track_event(&Fred);
        printf("  states ");
        hex(Fred.ChampionshipState, 256);
        hex(Fred.HotPursuitState, 256);
        printf("\n");
    } else if (!strcmp(o, "cont")) {
        EventTree *t;
        EventInfo *e = selected(&t);

        printf("cont");
        if (fred_use_tree_event(&Fred)
            && (t == NULL || e == NULL || (e->nType != 3 && e->nType != 4)
                || stateless_multi(e))) {
            printf(" skip\n");
            return;
        }
        printf("\n");
        fred_continue_multi_track_event(&Fred);
    } else if (!strcmp(o, "pick")) {
        printf("pick\n");
        fred_pick_random_tracks_for_challenge_knockout(&Fred);
        printf("  tracks ");
        hex(TheRaceEvent.aTracks, 32);
        printf("\n");
    } else if (!strcmp(o, "fake")) {
        printf("fake\n");
        fred_setup_fake_race_event_for_challenge_knockout(&Fred);
        tre_dump();
    } else if (!strcmp(o, "word")) {
        EventTree *t = fred_get_event_tree(&Fred);

        printf("word ");
        if (t != NULL
            && event_tree_get_event_number(t, Fred.nCurrentEvent) == NULL)
            printf("none\n");
        else
            printf("-> %d\n", (int)fred_event_word(&Fred));
    } else if (!strcmp(o, "opp")) {
        printf("opp %d -> ", (int)I(1));
        rec_print(fred_event_opponent(&Fred, I(1)));
    } else if (!strcmp(o, "oclr")) {
        printf("oclr\n");
        events_opened_clear(&TheEventsOpened);
        list_dump();
    } else if (!strcmp(o, "oadd")) {
        goal.nType = (uint16_t)I(1);
        goal.nEvent = (uint16_t)I(2);
        goal.nData = U(3);
        printf("oadd %d\n", (int)I(4));
        events_opened_add(&TheEventsOpened, &goal, I(4));
        list_dump();
    } else if (!strcmp(o, "olist")) {
        unhex(1, (uint8_t *)&TheEventsOpened, (int)sizeof TheEventsOpened);
    } else if (!strcmp(o, "opassed")) {
        int32_t out[8];
        int32_t n, j;

        for (j = 0; j < 8; j++)
            out[j] = -99;
        n = events_opened_passed(&TheEventsOpened, out, 8, &TheRaceEvent);
        printf("opassed -> %d", (int)n);
        for (j = 0; j < 8; j++)
            printf(" %d", (int)out[j]);
        printf("\n");
    } else if (!strcmp(o, "onum")) {
        printf("onum -> %d\n",
               (int)events_opened_num_passed(&TheEventsOpened,
                                             &TheRaceEvent));
    } else if (!strcmp(o, "tredump")) {
        printf("tredump\n");
        tre_dump();
    } else {
        fprintf(stderr, "unknown op %s\n", o);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[8192];
    uint8_t *raw;
    FILE *f;
    long n;
    int i;

    if (argc != 3) {
        fprintf(stderr, "usage: fredevent_test script.txt data.bin\n");
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
    // 16-aligned, as the model's copy is, with the model's zeros after.
    raw = (uint8_t *)calloc(1, ndata + 16 + PAD);
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
    for (i = 0; i < 256; i++) {
        specs[i].FullName = 5000 + i;
        ctinfo[i].pCarSpecs = &specs[i];
    }
    CarTypeInfoArray = ctinfo;
    for (i = 0; i < NTRACKS; i++) {
        static const int8_t p2p[4] = { 0, 1, -1, 2 };

        tinfo[i].Point2Point = p2p[i & 3];
        tinfo[i].TrackLanguageID = 3000 + 2 * i;
        tinfo[i].ReverseTrackLanguageID = 3001 + 2 * i;
    }
    gFredTranslateFn = translate;
    gEventRaceTranslateFn = translate;
    gEventRaceTranslateStringFn = translate_string;
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

// ----------------------------------------------- the snapshots, unreached
// raceparams.c's replay snapshots (TASKS 72d) call these; nothing here
// takes a snapshot.

static void snapshot_unreached_72d(const char *f)
{
    fprintf(stderr, "%s reached\n", f);
    exit(3);
}

void ReplaySnapshot_MoveData(ReplaySnapshot *s, void *p, int32_t stored,
                             int32_t size, int32_t is_signed)
{
    (void)s; (void)p; (void)stored; (void)size; (void)is_signed;
    snapshot_unreached_72d("ReplaySnapshot_MoveData");
}

void ReplaySnapshot_BeginSection(ReplaySnapshot *s, void *object,
                                 const char *name)
{
    (void)s; (void)object; (void)name;
    snapshot_unreached_72d("ReplaySnapshot_BeginSection");
}

void ReplaySnapshot_EndSection(ReplaySnapshot *s)
{
    (void)s;
    snapshot_unreached_72d("ReplaySnapshot_EndSection");
}

void player_settings_do_snapshot(cPlayerSettings *ps,
                                 struct ReplaySnapshot *s)
{
    (void)ps; (void)s;
    snapshot_unreached_72d("player_settings_do_snapshot");
}

CharacterInfo *get_character_info(int32_t i)
{
    (void)i;
    snapshot_unreached_72d("get_character_info");
    return NULL;
}
