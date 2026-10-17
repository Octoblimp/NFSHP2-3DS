// eventrace_test -- tools/eventrace_check.py's harness.
//
// Runs eventrace.c over the checker's script and its data file (the event
// trees of tools/eventtree_check.py), with eventtree.c's loader and
// states, raceevent.c's ResetResults and bprintf.c under it, as retail's
// EventTree.obj runs on its own. What the port calls outside them is a
// stub here that logs and answers as the model's stubs do:
// GetTranslatedString by id and by text, GetTrackInfo, Timer's
// PrintToString and bRandom. The car types and the tracks are tables made
// up by one rule on both sides.
//
//     eventrace_test script.txt data.bin > out.txt

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
#include "fredrace.h"
#include "playersettings.h"
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

// ---------------------------------------------------- what the port reads

FrontendDatabase Fred;
RaceParameters   TheRaceParameters;
tCopManager     *pCopManager;
uint32_t         bDefaultSeed;
int32_t          bVersionE3;
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
     && sizeof(EventGoal) == 8 && sizeof(EventReward) == 8)
    ? 1 : -1];

static uint8_t    *data;
static size_t      ndata;
static void       *blocks[NBLOCKS];
static int         nblocks;
static CarTypeInfo ctinfo[256];
static CarSpecs    specs[256];
static TrackInfo   tinfo[NTRACKS];
static char        buf[1024];
static EventTrack  word;

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
    if (b + WINDOW >= data && b < data + ndata + WINDOW) {
        snprintf(s, 32, "B%ld", (long)(b - data));
        return s;
    }
    if (b >= (const uint8_t *)gEventDescriptionTokens
        && b < (const uint8_t *)(gEventDescriptionTokens + EVENT_TOKEN_COUNT)) {
        snprintf(s, 32, "K%d", (int)((const EventDescriptionToken *)p
                                     - gEventDescriptionTokens));
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

int32_t bRandomI(int32_t range, uint32_t *seed)
{
    int32_t r = (int32_t)next(&randq);

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

static void run(void)
{
    const char *o = fields[0];

    if (!strcmp(o, "e3")) {
        bVersionE3 = I(1);
    } else if (!strcmp(o, "all")) {
        gUnlockAllEvents = I(1);
    } else if (!strcmp(o, "ult")) {
        Fred.pUltimateState = U(1);
    } else if (!strcmp(o, "ev") && !strcmp(fields[1], "put")) {
        EventInfo *e = (EventInfo *)(data + I(2));
        uint8_t *s = event_info_state(e);

        printf("ev put %s", P(e));
        if (s != NULL)
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
    } else if (!strcmp(o, "track")) {
        const uint8_t *r = (const uint8_t *)&TheRaceParameters;
        uint32_t w = U(1);

        word.b[0] = (uint8_t)w;
        word.b[1] = (uint8_t)(w >> 8);
        word.b[2] = (uint8_t)(w >> 16);
        word.b[3] = (uint8_t)(w >> 24);
        printf("track %08x\n", (unsigned)w);
        event_track_set_race(&word, &TheRaceParameters);
        printf("  rp0 ");
        hex(r, 84);
        printf("\n");
    } else if (!strcmp(o, "from")) {
        RaceParameters *rp = &TheRaceParameters;
        uint32_t w = U(1), d = U(6), c = U(7);

        word.b[0] = (uint8_t)w;
        word.b[1] = (uint8_t)(w >> 8);
        word.b[2] = (uint8_t)(w >> 16);
        word.b[3] = (uint8_t)(w >> 24);
        rp->TrackNumber = I(2);
        rp->TrackWeather = I(3);
        rp->TrackTimeOfDay = I(4);
        rp->TrackDirection = (eTrackDirection)I(5);
        memcpy(&rp->TrafficDensity, &d, 4);
        memcpy(&rp->TrafficOncoming, &c, 4);
        rp->NumLapsInRace = I(8);
        event_track_set_from_race(&word, rp);
        printf("from %08x %d %d %d %d %08x %08x %d -> %02x%02x%02x%02x\n",
               (unsigned)w, (int)I(2), (int)I(3), (int)I(4), (int)I(5),
               (unsigned)d, (unsigned)c, (int)I(8), word.b[3], word.b[2],
               word.b[1], word.b[0]);
    } else if (!strcmp(o, "tok")) {
        printf("tok %s -> %s\n", fields[1],
               P(get_event_description_token(fields[1])));
    } else if (!strcmp(o, "ftok")) {
        EventTree *t = tree_at(I(1));
        EventInfo *e = (EventInfo *)(data + I(2));
        int32_t id = I(3);
        EventDescriptionToken fake = { 0, "$X" };
        const EventDescriptionToken *tok =
            (uint32_t)id < EVENT_TOKEN_COUNT ? &gEventDescriptionTokens[id]
                                             : &fake;

        fake.nId = id;
        strcpy(buf, "~unchanged~");
        printf("ftok %s %s %d\n", P(t), P(e), (int)id);
        format_event_description_token(t, e, tok, buf);
        printf("  -> %s\n", buf);
    } else if (!strcmp(o, "fmt")) {
        EventTree *t = tree_at(I(1));
        EventInfo *e = (EventInfo *)(data + I(2));
        int32_t n = I(3);

        memset(buf, 0xaa, sizeof buf);
        printf("fmt %s %s %d %s\n", P(t), P(e), (int)n, fields[4]);
        format_event_description(t, e, fields[4], buf, n);
        printf("  -> %s\n", buf);
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
        fprintf(stderr, "usage: eventrace_test script.txt data.bin\n");
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
    raw = (uint8_t *)calloc(1, ndata + 16 + 0x2000);
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
