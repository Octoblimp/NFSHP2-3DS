// fredrace_test -- the port side of tools/fredrace_check.py.
//
// Reads the checker's script and runs it over the port's race start
// (fredrace.c) and RaceParameters' driver methods (raceparams.c), printing
// what each op leaves in the same lines the model prints from the retail
// image. The ops are the checker's; its docstring and Model.run list them.
// The race events' calls are the seams in fredrace.h, which print
// themselves here as the model's stubs do.
//
// After every op but F and the event answers the state that changed since
// it was last printed.

#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "cartypeinfo.h"
#include "characterinfo.h"
#include "configitems.h"
#include "difficultyinfo.h"
#include "fred.h"
#include "fredrace.h"
#include "playercam.h"
#include "playersettings.h"
#include "quickrace.h"
#include "raceparams.h"
#include "realtime.h"
#include "track.h"

const int *gPlayerCamSkipFE;
RaceEvent TheRaceEvent;          // raceevent.c's, not linked

#define SPAN      0x40000
#define NSLOTS    4
#define NREC_CARS 64
#define CAR_REC   1376
#define TRK_REC   164
#define RP_COMMON 772             // the bytes before pDriverInfoTable
#define HIGH_SCORES 1720
#define NUM_TOTAL_TIMES 7200
#define NUM_LAP_TIMES 800

static uint8_t chunkmem[NSLOTS][SPAN] __attribute__((aligned(16)));
static uint8_t cars[NREC_CARS * CAR_REC] __attribute__((aligned(16)));
static CarTypeInfo hostcars[NREC_CARS];
static uint8_t trackchunk[SPAN] __attribute__((aligned(16)));
static uint8_t skinchunk[SPAN] __attribute__((aligned(16)));
static uint8_t diffchunk[4096] __attribute__((aligned(16)));

static FrontendDatabase alt;      // the second FrontendDatabase
static RideInfo scrRide;
static DriverInfo scrDriver;
static int32_t scrList[8];

static int skipfe;
static int32_t lang;
static int32_t flowState;
static int32_t replay;

// What the race events answer.
static int32_t evStatus, evRaceIndex, evUserRank, evWord, evReward;
static int32_t evKo[2];
static int evTree;
static int16_t oppIndex[8];
static uint8_t opp[16][4];
#define NELIM 16
static struct { int32_t number, rank; } elim[NELIM];
static int nelim;

static int quiet;

static void emit(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void emit(const char *fmt, ...)
{
    va_list ap;

    if (quiet)
        return;
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    putchar('\n');
}

static const char *flabel(const FrontendDatabase *f)
{
    return f == &Fred ? "Fred" : f == &alt ? "alt" : "?";
}

// ---------------------------------------------------------------- the seams

static int32_t currLanguage(void) { return lang; }
static int32_t isCarUnlocked(int32_t type, int32_t game)
{
    (void)type;
    (void)game;
    return 0;
}
static const char *translate(int32_t id) { (void)id; return NULL; }

static void audioDefaults(uint8_t *ao)
{
    int i;

    for (i = 0; i < 176; i++)
        ao[i] = (uint8_t)(i * 7);
}

static void fakeKo(FrontendDatabase *f) { emit("fake %s", flabel(f)); }

// The event trees' answers, by tree, the track's byte and the direction's
// low bit, as the model's stubs keep them.
#define NTREES 8
static int32_t treeReward[NTREES][256][2];
static int32_t treeUnlocked[NTREES][256][2];

static int32_t trackIsAReward(int32_t tree, int32_t track, int32_t dir)
{
    int32_t v = treeReward[tree][(uint8_t)track][dir & 1];

    emit("ta %d %d %d -> %d", (int)tree, (int)track, (int)dir, (int)v);
    return v;
}

static int32_t treeIsTrackUnlocked(int32_t tree, int32_t track, int32_t dir)
{
    int32_t v = treeUnlocked[tree][(uint8_t)track][dir & 1];

    emit("tu %d %d %d -> %d", (int)tree, (int)track, (int)dir, (int)v);
    return v;
}

// eventtree.c's IsTrackAnEventReward and EventTreeIsTrackUnlocked, as
// retail runs them over its list, here over the script's trees by place;
// eventtree_check has the port's own against retail's.
static int32_t numTrees;

int32_t is_track_an_event_reward(int32_t track, int32_t direction)
{
    int32_t tree;

    for (tree = 0; tree < numTrees; tree++)
        if (trackIsAReward(tree, track, direction))
            return 1;
    return 0;
}

int32_t event_tree_is_track_unlocked_any(int32_t track, int32_t direction)
{
    int32_t tree;

    for (tree = 0; tree < numTrees; tree++)
        if (trackIsAReward(tree, track, direction))
            return treeIsTrackUnlocked(tree, track, direction) != 0;
    return 1;
}

static void stopMovie(void) { emit("sm"); }

static int32_t status(void)
{
    emit("st -> %d", (int)evStatus);
    return evStatus;
}

static void resetState(void) { emit("rs"); }

static int32_t raceIndex(void)
{
    emit("ri -> %d", (int)evRaceIndex);
    return evRaceIndex;
}

static void setRace(int32_t index, RaceParameters *rp)
{
    emit("sr %d %s", (int)index, rp == &TheRaceParameters ? "RP" : "?");
}

static int32_t koStart(int32_t p)
{
    int32_t v = p == 0 || p == 1 ? evKo[p] : 0;

    emit("ko %d -> %d", (int)p, (int)v);
    return v;
}

static int32_t userRank(void)
{
    emit("ur -> %d", (int)evUserRank);
    return evUserRank;
}

static int32_t eventWord(FrontendDatabase *f)
{
    if (!evTree)
        return 0;
    emit("en %d", (int)f->nCurrentEvent);
    emit("ew -> %d", (int)evWord);
    return evWord;
}

static int find_elim(int32_t n)
{
    int i;

    for (i = 0; i < nelim; i++)
        if (elim[i].number == n)
            return i;
    return -1;
}

static int32_t driverEliminated(int32_t n)
{
    int32_t r = find_elim(n) >= 0;

    emit("de %d -> %d", (int)n, (int)r);
    return r;
}

static int32_t eliminatedRank(int32_t n)
{
    int i = find_elim(n);
    int32_t r = i >= 0 ? elim[i].rank : 0;

    emit("rk %d -> %d", (int)n, (int)r);
    return r;
}

static void startingPositions(void) { emit("esp"); }

static const uint8_t *eventOpponent(FrontendDatabase *f, int32_t i)
{
    emit("en %d", (int)f->nCurrentEvent);
    return opp[oppIndex[i]];
}

static void multiTrack(FrontendDatabase *f) { emit("ms %s", flabel(f)); }

static void replayStartRace(void)
{
    if (replay) {
        emit("dr");
        emit("du");
    }
}

static int32_t rewardCars(void)
{
    emit("rw -> %d", (int)evReward);
    return evReward;
}

static int32_t gameFlowState(void) { return flowState; }
static void changeGameFlow(int32_t s) { emit("cg %d %d", (int)s, 0); }

// ---------------------------------------------------------------- the prints

static const char *label(const void *p)
{
    static char buf[4][48];
    static int n;
    const uint8_t *a = (const uint8_t *)p;
    char *s = buf[n++ & 3];
    int k;

    if (p == NULL)
        return "NULL";
    for (k = 0; k < NSLOTS; k++)
        if (a >= chunkmem[k] && a < chunkmem[k] + SPAN) {
            snprintf(s, 48, "k%d+%d", k, (int)(a - chunkmem[k]));
            return s;
        }
    if (a >= (const uint8_t *)hostcars
        && a < (const uint8_t *)hostcars + sizeof hostcars) {
        snprintf(s, 48, "cars+%d", (int)(a - (const uint8_t *)hostcars));
        return s;
    }
    if (a >= trackchunk && a < trackchunk + SPAN) {
        snprintf(s, 48, "trk+%d", (int)(a - trackchunk));
        return s;
    }
    if (a >= (const uint8_t *)DriverInfoTable
        && a < (const uint8_t *)(DriverInfoTable
                                 + RACE_PARAMETERS_MAX_DRIVERS)
        && (a - (const uint8_t *)DriverInfoTable) % sizeof(DriverInfo) == 0) {
        snprintf(s, 48, "DIT[%d]", (int)((const DriverInfo *)p
                                         - DriverInfoTable));
        return s;
    }
    return "?";
}

static void hex(char *out, const uint8_t *p, int n)
{
    int i;

    for (i = 0; i < n; i++)
        sprintf(out + 2 * i, "%02x", p[i]);
    out[2 * n] = 0;
}

static uint8_t shownFred[sizeof(FrontendDatabase)];
static uint8_t shownAlt[sizeof(FrontendDatabase)];
static uint8_t shownRP[RP_COMMON];
static char    shownDI[RACE_PARAMETERS_MAX_DRIVERS][128];
#define NLINES 8
static char    shownLine[NLINES][256];

static void print_rows(char tag, const uint8_t *cur, uint8_t *shown,
                       int size, int width)
{
    char h[2 * 64 + 1];
    int off;

    for (off = 0; off < size; off += 32) {
        int n = size - off < 32 ? size - off : 32;

        if (memcmp(cur + off, shown + off, n) == 0)
            continue;
        hex(h, cur + off, n);
        if (width == 5)
            emit("%c %05x %s", tag, off, h);
        else
            emit("%c %03x %s", tag, off, h);
        memcpy(shown + off, cur + off, n);
    }
}

static void di_text(char *s, size_t cap, const DriverInfo *d)
{
    char h[17];

    hex(h, (const uint8_t *)&d->CurrentRideInfo, 8);
    snprintf(s, cap, "%d %d %d %d %d %d %s %s", d->EliminatedRank,
             d->UniqueDriverNumber, d->CharacterNumber, d->SkillLevel,
             d->StartingPosition, (int)d->TheDriverType, h,
             label(d->pCharacterInfo));
}

static void line_once(int k, const char *s)
{
    if (strcmp(s, shownLine[k]) != 0) {
        emit("%s", s);
        snprintf(shownLine[k], sizeof shownLine[k], "%s", s);
    }
}

static void print_state(void)
{
    const RaceParameters *rp = &TheRaceParameters;
    char s[256], t[200];
    int i;

    print_rows('f', (const uint8_t *)&Fred, shownFred,
               (int)sizeof(FrontendDatabase), 5);
    print_rows('a', (const uint8_t *)&alt, shownAlt,
               (int)sizeof(FrontendDatabase), 5);
    print_rows('r', (const uint8_t *)rp, shownRP, RP_COMMON, 3);
    snprintf(s, sizeof s, "rp %s %d %08x %08x",
             rp->pDriverInfoTable == DriverInfoTable ? "DIT"
             : label(rp->pDriverInfoTable),
             (int)rp->NumDriverInfo, (unsigned)rp->New780,
             (unsigned)rp->New784);
    line_once(0, s);
    for (i = 0; i < RACE_PARAMETERS_MAX_DRIVERS; i++) {
        di_text(t, sizeof t, &DriverInfoTable[i]);
        snprintf(s, sizeof s, "d %d %s", i, t);
        if (strcmp(s, shownDI[i]) != 0) {
            emit("%s", s);
            strcpy(shownDI[i], s);
        }
    }
    di_text(t, sizeof t, &scrDriver);
    snprintf(s, sizeof s, "y %s", t);
    line_once(1, s);
    hex(t, (const uint8_t *)&scrRide, 8);
    snprintf(s, sizeof s, "x %s", t);
    line_once(2, s);
    snprintf(s, sizeof s, "l %d %d %d %d %d %d %d %d", (int)scrList[0],
             (int)scrList[1], (int)scrList[2], (int)scrList[3],
             (int)scrList[4], (int)scrList[5], (int)scrList[6],
             (int)scrList[7]);
    line_once(3, s);
    snprintf(s, sizeof s, "e %d %d %d %d", TheRaceEvent.nType,
             TheRaceEvent.nTracks, TheRaceEvent.nInitialPlayers,
             (int)TheRaceEvent.bIsLastOpen);
    line_once(4, s);
    snprintf(s, sizeof s, "g seed=%08x", (unsigned)bDefaultSeed);
    line_once(5, s);
}

// ---------------------------------------------------------------- the ops

static int unhex(uint8_t *out, const char *h, int cap)
{
    int n = 0;

    while (h[0] && h[1] && n < cap) {
        unsigned v;

        sscanf(h, "%2x", &v);
        out[n++] = (uint8_t)v;
        h += 2;
    }
    return n;
}

static void put_le(uint8_t *p, int n, long long v)
{
    int i;

    for (i = 0; i < n; i++)
        p[i] = (uint8_t)((unsigned long long)v >> (8 * i));
}

// The records as the image lays them out, 1376 bytes each, into the
// port's: pCarSpecs is a host pointer, so the host record is wider and
// everything from it on is placed by field.
static void sync_cars(void)
{
    int t;

    for (t = 0; t < NREC_CARS; t++) {
        const uint8_t *r = cars + CAR_REC * t;

        memcpy(&hostcars[t], r, offsetof(CarTypeInfo, pCarSpecs));
        hostcars[t].pCarSpecs = NULL;
        memcpy(&hostcars[t].Pad1, r + 1372, 4);
    }
}

static FrontendDatabase *fk(int k)
{
    return k ? &alt : &Fred;
}

static int32_t *var(const char *name)
{
    static int32_t pov;

    if (!strcmp(name, "track")) return &TrackSelectedInConfigFile;
    if (!strcmp(name, "e3")) return &bVersionE3;
    if (!strcmp(name, "skipfe")) return (int32_t *)&skipfe;
    if (!strcmp(name, "np")) return &SkipFENumPlayerCars;
    if (!strcmp(name, "nai")) return &SkipFENumAICars;
    if (!strcmp(name, "laps")) return &SkipFENumLaps;
    if (!strcmp(name, "cops")) return &SkipFEMaxCops;
    if (!strcmp(name, "tickets")) return &SkipFETickets;
    if (!strcmp(name, "roadblocks")) return &SkipFERoadBlocks;
    if (!strcmp(name, "heli")) return &SkipFEHelicopter;
    if (!strcmp(name, "spikes")) return &SkipFESpikeStrips;
    if (!strcmp(name, "new624")) return &SkipFENew624;
    if (!strcmp(name, "beacop")) return &SkipFEBeACop;
    if (!strcmp(name, "pov")) return &pov;
    if (!strcmp(name, "density")) return (int32_t *)&SkipFETrafficDensity;
    if (!strcmp(name, "oncoming")) return (int32_t *)&SkipFETrafficOncoming;
    if (!strcmp(name, "racetype")) return &SkipFERaceType;
    if (!strcmp(name, "diff")) return &SkipFEDifficulty;
    if (!strcmp(name, "dp1type")) return &DefaultPlayer1CarType;
    if (!strcmp(name, "dp2type")) return &DefaultPlayer2CarType;
    if (!strcmp(name, "dp1skin")) return &DefaultPlayer1SkinIndex;
    if (!strcmp(name, "dp2skin")) return &DefaultPlayer2SkinIndex;
    if (!strcmp(name, "force")) return &ForceAllAICarsToBeThisType;
    if (!strcmp(name, "maxai")) return &MaximumNumAICars;
    if (!strcmp(name, "lang")) return &lang;
    if (!strcmp(name, "video")) return &CurrentVideoMode;
    if (!strcmp(name, "seed")) return (int32_t *)&bDefaultSeed;
    if (!strcmp(name, "state")) return &flowState;
    if (!strcmp(name, "replay")) return &replay;
    fprintf(stderr, "no variable %s\n", name);
    exit(2);
}

static void op_fill(int b)
{
    memset(&Fred, b, sizeof Fred);
    memset(&alt, b, sizeof alt);
    memset(&TheRaceParameters, b, sizeof TheRaceParameters);
    memset(DriverInfoTable, b, sizeof DriverInfoTable);
    memset(&scrRide, b, sizeof scrRide);
    memset(&scrDriver, b, sizeof scrDriver);
    memset(scrList, b, sizeof scrList);
    memset(&TheRaceEvent, b, sizeof TheRaceEvent);
    quiet = 1;
    print_state();
    quiet = 0;
}

// DriverInfo by the retail field name the script uses.
static void put_driver(DriverInfo *d, const char *field, long long v)
{
    if (!strcmp(field, "rank")) d->EliminatedRank = (int8_t)v;
    else if (!strcmp(field, "uniq")) d->UniqueDriverNumber = (int8_t)v;
    else if (!strcmp(field, "char")) d->CharacterNumber = (int8_t)v;
    else if (!strcmp(field, "skill")) d->SkillLevel = (int8_t)v;
    else if (!strcmp(field, "start")) d->StartingPosition = (int8_t)v;
    else if (!strcmp(field, "type")) d->TheDriverType = (DriverType)v;
    else if (!strcmp(field, "rt")) d->CurrentRideInfo.Type = (int32_t)v;
    else if (!strcmp(field, "ri"))
        d->CurrentRideInfo.InstanceIndex = (int8_t)v;
    else if (!strcmp(field, "rs")) d->CurrentRideInfo.SkinNumber = (int8_t)v;
    else if (!strcmp(field, "rd")) d->CurrentRideInfo.HasDash = (int8_t)v;
    else if (!strcmp(field, "rv"))
        d->CurrentRideInfo.CanBeVertexDamaged = (int8_t)v;
    else {
        fprintf(stderr, "no field %s\n", field);
        exit(2);
    }
}

// `salt` moves the totals' times, so two databases' differ.
static void high_score_pattern(FrontendDatabase *f, int salt)
{
    uint8_t *p = (uint8_t *)f + HIGH_SCORES;
    int i;

    for (i = 0; i < NUM_TOTAL_TIMES; i++, p += 8) {
        put_le(p, 4, 7L * i + 1 + 0x1000L * salt);
        put_le(p + 4, 2, i);
        put_le(p + 6, 2, -i);
    }
    for (i = 0; i < NUM_LAP_TIMES; i++, p += 8) {
        put_le(p, 4, 0x10000L + 3L * i);
        put_le(p + 4, 2, -i);
        put_le(p + 6, 2, i);
    }
}

static char line[1 << 21];

int main(int argc, char **argv)
{
    FILE *f;

    if (argc < 2 || !(f = fopen(argv[1], "r"))) {
        fprintf(stderr, "usage: fredrace_test script\n");
        return 2;
    }
    // race.c starts it at four of InitWithDefaults' values; the image's is
    // zero until its constructor runs.
    memset(&TheRaceParameters, 0, sizeof TheRaceParameters);
    gPlayerCamSkipFE = &skipfe;
    gCurrLanguageFn = currLanguage;
    gIsCarUnlockedFn = isCarUnlocked;
    gFredTranslateFn = translate;
    gFredAudioOptionsDefaultsFn = audioDefaults;
    gSetupFakeRaceEventForChallengeKnockoutFn = fakeKo;
    gRaceEventGetStatusFn = status;
    gRaceEventResetStateFn = resetState;
    gRaceEventGetRaceIndexFn = raceIndex;
    gEventTrackSetRaceFn = setRace;
    gRaceEventKoStartPositionFn = koStart;
    gRaceEventTournamentUserRankFn = userRank;
    gFredEventWordFn = eventWord;
    gRaceEventDriverEliminatedFn = driverEliminated;
    gRaceEventEliminatedRankFn = eliminatedRank;
    gRaceEventStartingPositionsFn = startingPositions;
    gFredEventOpponentFn = eventOpponent;
    gFredMaybeSetSelectedCarForMultiTrackEventFn = multiTrack;
    gDemoModeReplayStartRaceFn = replayStartRace;
    gEventRewardCarsUnlockedFn = rewardCars;
    gFredGameFlowStateFn = gameFlowState;
    gFredChangeGameFlowFn = changeGameFlow;
    gQuickRaceStopMovieFn = stopMovie;

    while (fgets(line, sizeof line, f)) {
        char op[8] = "";
        char a1[64] = "";
        int p = 0, q = 0, r = 0, s = 0, t = 0;
        long long v = 0;
        char *rest;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        sscanf(line, "%7s", op);
        rest = line + strlen(op);
        while (*rest == ' ')
            rest++;
        if (!strcmp(op, "B")) {
            printf("%s\n", line);
            continue;
        }
        printf("> %.40s\n", line);
        if (!strcmp(op, "F")) {
            sscanf(rest, "%x", &p);
            op_fill(p);
            continue;
        } else if (!strcmp(op, "K")) {
            int k;

            sscanf(rest, "%d", &k);
            memset(chunkmem[k], 0, SPAN);
            unhex(chunkmem[k], strchr(rest, ' ') + 1, SPAN);
            continue;
        } else if (!strcmp(op, "L")) {
            sscanf(rest, "%d", &p);
            emit("L %d -> %d", p, loader_character_info(chunkmem[p]));
        } else if (!strcmp(op, "KC")) {
            memset(cars, 0, sizeof cars);
            unhex(cars, rest, (int)sizeof cars);
            sync_cars();
            CarTypeInfoArray = hostcars;
        } else if (!strcmp(op, "KT")) {
            memset(trackchunk, 0, SPAN);
            unhex(trackchunk, rest, SPAN);
            emit("KT -> %d", track_loader_geometry(trackchunk));
        } else if (!strcmp(op, "KS")) {
            int n;

            memset(skinchunk, 0, SPAN);
            n = unhex(skinchunk, rest, SPAN);
            SkinInfoTable = (SkinInfo *)(skinchunk + 8);
            NumSkinInfo = (n - 8) >> 6;
        } else if (!strcmp(op, "KD")) {
            memset(diffchunk, 0, sizeof diffchunk);
            unhex(diffchunk, rest, (int)sizeof diffchunk);
            loader_difficulty_info(diffchunk);
        } else if (!strcmp(op, "NS")) {
            sscanf(rest, "%d", &p);
            NumSkinInfo = p;
        } else if (!strcmp(op, "cr")) {
            sscanf(rest, "%d %d %d %lld", &p, &q, &r, &v);
            put_le(cars + CAR_REC * p + q, r, v);
            sync_cars();
        } else if (!strcmp(op, "tr")) {
            sscanf(rest, "%d %d %d %lld", &p, &q, &r, &v);
            put_le(trackchunk + 8 + TRK_REC * (p - 1) + q, r, v);
        } else if (!strcmp(op, "sk")) {
            sscanf(rest, "%d %d %d %lld", &p, &q, &r, &v);
            put_le(skinchunk + 8 + 64 * p + q, r, v);
        } else if (!strcmp(op, "fr")) {
            sscanf(rest, "%d %d %d %lld", &p, &q, &r, &v);
            put_le((uint8_t *)fk(p) + q, r, v);
        } else if (!strcmp(op, "rp")) {
            sscanf(rest, "%d %d %lld", &q, &r, &v);
            put_le((uint8_t *)&TheRaceParameters + q, r, v);
        } else if (!strcmp(op, "rq")) {
            sscanf(rest, "%63s %lli", a1, &v);
            if (a1[0] == 'n')
                TheRaceParameters.NumDriverInfo = (int32_t)v;
            else if (a1[0] == 's')
                TheRaceParameters.New780 = (int32_t)v;
            else
                TheRaceParameters.New784 = (int32_t)v;
        } else if (!strcmp(op, "dt")) {
            char field[16] = "";

            sscanf(rest, "%d %15s %lld", &p, field, &v);
            put_driver(&DriverInfoTable[p], field, v);
        } else if (!strcmp(op, "v")) {
            sscanf(rest, "%63s %lli", a1, &v);
            *var(a1) = (int32_t)v;
            if (!strcmp(a1, "pov"))
                PlayerSkipFEPOVIndex = (uint8_t)v;
        } else if (!strcmp(op, "cp")) {
            memcpy(&alt, &Fred, sizeof alt);
        } else if (!strcmp(op, "hs")) {
            if (sscanf(rest, "%d %d", &p, &q) < 2)
                q = 0;
            high_score_pattern(fk(p), q);
        } else if (!strcmp(op, "rd")) {
            sscanf(rest, "%d %d %d %d %d", &p, &q, &r, &s, &t);
            scrRide.Type = p;
            scrRide.InstanceIndex = (int8_t)q;
            scrRide.SkinNumber = (int8_t)r;
            scrRide.HasDash = (int8_t)s;
            scrRide.CanBeVertexDamaged = (int8_t)t;
        } else if (!strcmp(op, "ls")) {
            sscanf(rest, "%d %d %d %d %d %d %d %d", &scrList[0], &scrList[1],
                   &scrList[2], &scrList[3], &scrList[4], &scrList[5],
                   &scrList[6], &scrList[7]);
        } else if (!strcmp(op, "es")) {
            sscanf(rest, "%d", &evStatus);
            continue;
        } else if (!strcmp(op, "ei")) {
            sscanf(rest, "%d", &evRaceIndex);
            continue;
        } else if (!strcmp(op, "ek")) {
            sscanf(rest, "%d %d", &evKo[0], &evKo[1]);
            continue;
        } else if (!strcmp(op, "eu")) {
            sscanf(rest, "%d", &evUserRank);
            continue;
        } else if (!strcmp(op, "ew")) {
            sscanf(rest, "%d", &evWord);
            continue;
        } else if (!strcmp(op, "et")) {
            sscanf(rest, "%d", &evTree);
            continue;
        } else if (!strcmp(op, "ee")) {
            int i;

            sscanf(rest, "%d %d", &p, &q);
            i = find_elim(p);
            if (i < 0)
                i = nelim++;
            elim[i].number = p;
            elim[i].rank = q;
            continue;
        } else if (!strcmp(op, "ex")) {
            nelim = 0;
            continue;
        } else if (!strcmp(op, "er")) {
            sscanf(rest, "%d", &evReward);
            continue;
        } else if (!strcmp(op, "eo")) {
            sscanf(rest, "%d %d", &p, &q);
            oppIndex[p] = (int16_t)q;
            continue;
        } else if (!strcmp(op, "ec")) {
            sscanf(rest, "%d %d %d %d", &p, &q, &r, &s);
            opp[p][0] = (uint8_t)q;
            opp[p][1] = (uint8_t)r;
            opp[p][2] = (uint8_t)s;
            opp[p][3] = 0;
            continue;
        } else if (!strcmp(op, "ev")) {
            sscanf(rest, "%d %d", &p, &q);
            TheRaceEvent.nType = (int16_t)p;
            TheRaceEvent.nTracks = (int16_t)q;
        } else if (!strcmp(op, "SF")) {
            fred_static_init();
        } else if (!strcmp(op, "I")) {
            init_fred();
        } else if (!strcmp(op, "R")) {
            race_parameters_init_with_defaults(&TheRaceParameters);
        } else if (!strcmp(op, "SS")) {
            sscanf(rest, "%d", &p);
            fred_start_skip_fe_game(fk(p));
        } else if (!strcmp(op, "SR")) {
            sscanf(rest, "%d", &p);
            fred_start_race(fk(p));
        } else if (!strcmp(op, "SC")) {
            sscanf(rest, "%d", &p);
            fred_setup_cars_for_race(fk(p));
        } else if (!strcmp(op, "CP")) {
            sscanf(rest, "%d", &p);
            fred_calculate_starting_positions(fk(p));
        } else if (!strcmp(op, "RT")) {
            sscanf(rest, "%d %d", &p, &q);
            fred_set_record_times_to_beat(fk(p), q);
        } else if (!strcmp(op, "RA")) {
            sscanf(rest, "%d", &p);
            fred_set_all_record_times_to_beat(fk(p));
        } else if (!strcmp(op, "GR")) {
            sscanf(rest, "%d %d", &p, &q);
            emit("GR -> %d", (int)generate_random_ride_info(&scrRide, p, q));
        } else if (!strcmp(op, "GS")) {
            sscanf(rest, "%d", &p);
            emit("GS -> %d", (int)car_type_info_get_random_skin(
                                 cartypeinfo_get(p)));
        } else if (!strcmp(op, "PN")) {
            sscanf(rest, "%d %d", &p, &q);
            emit("PN -> %d", (int)pick_character_number_that_isnt_racing(
                                 scrList, p, q));
        } else if (!strcmp(op, "PK")) {
            emit("PK -> %d", (int)pick_cop_character_number(0));
        } else if (!strcmp(op, "AT")) {
            sscanf(rest, "%d", &p);
            emit("AT -> %d", (int)are_there_any_cars_of_type(p));
        } else if (!strcmp(op, "AC")) {
            sscanf(rest, "%d %d", &p, &q);
            emit("AC -> %d", (int)are_there_any_cars_of_colour(p, q));
        } else if (!strcmp(op, "PU")) {
            sscanf(rest, "%d", &p);
            emit("PU -> %d", (int)pick_unused_skin(p));
        } else if (!strcmp(op, "hu")) {
            sscanf(rest, "%d", &p);
            emit("h -> %d", (int)high_score_table_get_unique_track_index(p));
        } else if (!strcmp(op, "hl")) {
            sscanf(rest, "%d", &p);
            emit("h -> %d", (int)high_score_table_get_unique_lap_index(p));
        } else if (!strcmp(op, "ht")) {
            sscanf(rest, "%d %d %d %d", &p, &q, &r, &s);
            emit("h -> %d", (int)high_score_table_get_total_times_index(
                                p, q, r, s));
        } else if (!strcmp(op, "hp")) {
            sscanf(rest, "%d %d %d", &p, &q, &r);
            emit("h -> %d", (int)high_score_table_get_lap_times_index(
                                p, q, r));
        } else if (!strcmp(op, "DC")) {
            sscanf(rest, "%d %d %d %d %d", &p, &q, &r, &s, &t);
            driver_info_init(&scrDriver, p, (DriverType)q, &scrRide, r, s, t);
        } else if (!strcmp(op, "AD")) {
            race_parameters_add_driver_info(&TheRaceParameters, &scrDriver);
        } else if (!strcmp(op, "FD")) {
            sscanf(rest, "%d", &p);
            emit("FD -> %s",
                 label(race_parameters_find_driver(&TheRaceParameters, p)));
        } else if (!strcmp(op, "RE")) {
            race_parameters_restore_eliminated(&TheRaceParameters);
        } else if (!strcmp(op, "EL")) {
            sscanf(rest, "%d %d", &p, &q);
            emit("EL -> %s", label(race_parameters_eliminate_driver(
                                 &TheRaceParameters, p, q)));
        } else if (!strcmp(op, "TM")) {
            emit("TM -> %d", (int)race_parameters_too_many_models(
                                 &TheRaceParameters, &scrRide));
        } else if (!strcmp(op, "LI")) {
            emit("LI -> %d",
                 (int)race_parameters_get_location_index(&TheRaceParameters));
        } else if (!strcmp(op, "RI")) {
            sscanf(rest, "%d %d %d %d", &p, &q, &r, &s);
            ride_info_init(&scrRide, p, q, r, s);
        } else if (!strcmp(op, "tn")) {
            sscanf(rest, "%d", &p);
            numTrees = p;
            continue;
        } else if (!strcmp(op, "ta") || !strcmp(op, "tu")) {
            sscanf(rest, "%d %d %d %lld", &p, &q, &r, &v);
            if (op[1] == 'a')
                treeReward[p][(uint8_t)q][r & 1] = (int32_t)v;
            else
                treeUnlocked[p][(uint8_t)q][r & 1] = (int32_t)v;
            continue;
        } else if (!strcmp(op, "QR")) {
            sscanf(rest, "%d", &p);
            start_quick_race(p);
        } else if (!strcmp(op, "PT")) {
            ExpressTrack pick;

            pick_track_number_for_express_game(&pick);
            emit("PT -> %d %d", (int)pick.Track, (int)pick.Direction);
        } else if (!strcmp(op, "IU")) {
            // In turn: the seams print as they are asked.
            sscanf(rest, "%d %d", &p, &q);
            r = (int)is_track_unlocked(p, q);
            s = (int)is_track_an_event_reward(p, q);
            t = (int)event_tree_is_track_unlocked_any(p, q);
            emit("IU -> %d %d %d", r, s, t);
        } else if (!strcmp(op, "CS")) {
            sscanf(rest, "%d", &p);
            emit("CS -> %d",
                 (int)fpi_get_car_status(&Fred.FrontendPlayers[0], p));
        } else if (!strcmp(op, "GT")) {
            sscanf(rest, "%d", &p);
            emit("GT -> %d %d %d", (int)fred_use_the_race_event(fk(p)),
                 (int)fred_is_challenge_game(fk(p)),
                 (int)fred_is_event_game(fk(p)));
        } else {
            fprintf(stderr, "bad op %s\n", line);
            return 2;
        }
        print_state();
    }
    return 0;
}
