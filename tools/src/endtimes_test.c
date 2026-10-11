// Drives endtimes.c and highscore.c for tools/endtimes_check.py. A script
// of ops, one per line, fields split on '|':
//
//   rp|TRACK|DIR|LAPS|NP  TheRaceParameters' TrackNumber, TrackDirection,
//                      NumLapsInRace and NumPlayerCars
//   race|LAPS|FLB      pCurrentRace's NumLapsInRace and
//                      FinishLineBoundaryNumber
//   first|RC           pCurrentRace's first racing car, -1 none
//   ct|I|TYPE|CLASS    car type I's Type and CarClass
//   car|I|CT|PLAYER    car I's car type and player (-1 none)
//   rc|I|CAR|DONE|TIME|B0|B1|B2|B3|B4  racing car I: its car (-1 none),
//                      NumLapsCompleted, RaceTime and BestRunningTimes
//   player|I|NUM|NAME  player I's PlayerNumber and name
//   pbi|A|B|N          PlayersByIndex' players (-1 none) and
//                      PlayerNumPlayers
//   recp|P|LAP|TOTAL   player P's records: lap and total table entries,
//                      -1 none
//   tidx|V, lidx|V     what the total and lap index functions answer
//   hs|T|I|TIME|NAME|CAR  entry I of the total (T 0) or lap (T 1) table
//   fill|T|I|N|TIME    N entries from I: TIME, name 0, car 0
//   name|I[|TEXT]      name slot I, zero-filled
//   hole|I             name slot I's first byte zeroed
//   ins|TEXT           InsertPlayerName, the text from a zeroed buffer
//   look|I             LookupPlayerNameFromTable
//   tab|T|I|N          N entries from I
//   names|N            the first N name slots' bytes
//   maybe|RC           MaybeRecordHighScore for racing car RC
//   ts|NUM             TransientStats' NumStats
//   row|I|POS|UNIQUE|NLAPS|L0|..|L10  TransientStats' row I
//   egs|Z7|Z8          the screens' list's record speech flags
//   blt|HASH, btt|HASH a Best Lap Times or Best Total Times screen made
//   scroll|MSG, tick, render  the screen's vtable's Scroll, Tick, Render
//   dtor|FLAGS         its destructor
//   dump               the screen and the speech flags
//   ltcb|MSG|HASH|NOISE  the Lap Times screens' callback
//
// Every call out of the two files prints what it was asked, as the
// model's stubs at retail's addresses do. Nothing allocated is given back,
// so no address is seen twice and each block keeps the number it was made
// with.
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bprintf.h"
#include "car.h"
#include "cartypeinfo.h"
#include "endgame.h"
#include "endresults.h"
#include "endtimes.h"
#include "flailer.h"
#include "fred.h"
#include "fredend.h"
#include "fredrace.h"
#include "highscore.h"
#include "player.h"
#include "race.h"
#include "racerun.h"
#include "racesplit.h"
#include "startrace.h"
#include "track.h"

#define MAX_TYPES   64
#define MAX_BLOCKS  4096
#define NUM_CARS    8
#define NUM_PLAYERS 4

// What the two files read.
FrontendDatabase Fred;
RaceParameters TheRaceParameters;
Race *pCurrentRace;
TrackInfo *CurrentTrackInfo;
const CarTypeInfo *CarTypeInfoArray;
EndGameScreens *pEndGameScreens;
int32_t PlayerNumPlayers;
struct Player *PlayerPlayersByIndex[2];
const char *(*gStartRaceTranslateFn)(int32_t id);
const char *(*gStartRaceTranslateStringFn)(const char *s);
const bVector4 PlayerTextColors[2] = {
    { 134.0f, 96.0f, 48.0f, 128.0f },
    { 0.0f, 128.0f, 0.0f, 128.0f },
};
const bVector4 DefaultTextColor = { 128.0f, 128.0f, 128.0f, 128.0f };

static CarTypeInfo ctinfo[MAX_TYPES];
static CarSpecs specs[MAX_TYPES];
static Car cars[NUM_CARS];
static struct RacingCar rcs[NUM_CARS];
static Player players[NUM_PLAYERS];
static Race race;
static TrackInfo track;
static EndGameScreens egs;
static int32_t totalIndex, lapIndex;
static uint32_t findScreen, findObject;
static uint8_t fakeObject[64];
static EndGameMenusBase *screen;

// Every block, by the number it was made with.
static const void *blocks[MAX_BLOCKS];
static int numBlocks;

static int64_t num(const char *s)
{
    return strtoll(s, NULL, 0);
}

static uint32_t fbits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static int block_add(const void *p)
{
    blocks[numBlocks] = p;
    return numBlocks++;
}

static const char *ptr_name(const void *p)
{
    static char ring[8][24];
    static int at;
    char *s = ring[at++ & 7];
    int i;

    if (p == NULL) {
        snprintf(s, 24, "none");
        return s;
    }
    for (i = numBlocks - 1; i >= 0; i--)
        if (blocks[i] == p) {
            snprintf(s, 24, "#%d", i);
            return s;
        }
    snprintf(s, 24, "%08x", (unsigned)(uintptr_t)p);
    return s;
}

static FredHighScore *entry(int32_t table, int32_t i)
{
    HighScoreTable *t = &Fred.ChallengeHighScores;

    return table ? &t->LapTimesTable[i] : &t->TotalTimesTable[i];
}

// A record pointer as the dump spells it: t<i> or l<i> in the tables.
static const char *rec_name(const FredHighScore *e)
{
    static char ring[4][24];
    static int at;
    char *s = ring[at++ & 3];
    const uint8_t *base = (const uint8_t *)&Fred.ChallengeHighScores;
    ptrdiff_t d;

    if (e == NULL)
        return "none";
    d = (const uint8_t *)e - base;
    if (d >= 0 && d < (ptrdiff_t)sizeof(HighScoreTable) && d % 8 == 0) {
        d /= 8;
        if (d < FRED_NUM_TOTAL_TIMES)
            snprintf(s, 24, "t%d", (int)d);
        else
            snprintf(s, 24, "l%d", (int)(d - FRED_NUM_TOTAL_TIMES));
        return s;
    }
    return "?";
}

// A row of TransientStats as the dump spells it.
static const char *row_name(const TransientStatsElement *e)
{
    static char s[24];

    if (e == NULL)
        return "none";
    snprintf(s, sizeof s, "r%d",
             (int)(e - Fred.TransientStatsTable.Stats));
    return s;
}

// ------------------------------------------------------------ the stubs

const CarTypeInfo *cartypeinfo_get(int32_t carType)
{
    return &CarTypeInfoArray[carType & (MAX_TYPES - 1)];
}

TransientStatsElement *transient_stats_get_driver(TransientStats *ts,
                                                  int32_t driver)
{
    int32_t i;

    for (i = 0; i < ts->NumStats; i++)
        if (ts->Stats[i].UniqueDriveNumber == driver)
            return &ts->Stats[i];
    return NULL;
}

struct Player *racingcar_get_player(const struct RacingCar *rc)
{
    return rc->pCar != NULL ? rc->pCar->pPlayer : NULL;
}

Timer *racingcar_get_last_best_lap_time(struct RacingCar *rc)
{
    return &rc->BestRunningTimes[pCurrentRace->FinishLineBoundaryNumber];
}

int32_t high_score_table_get_total_times_index(int32_t track,
                                               int32_t carClass,
                                               int32_t direction,
                                               int32_t laps)
{
    printf("  tidx %d %d %d %d\n", (int)track, (int)carClass,
           (int)direction, (int)laps);
    return totalIndex;
}

int32_t high_score_table_get_lap_times_index(int32_t track, int32_t carClass,
                                             int32_t direction)
{
    printf("  lidx %d %d %d\n", (int)track, (int)carClass, (int)direction);
    return lapIndex;
}

int32_t get_the_right_track_language_id(const struct TrackInfo *t,
                                        int32_t dir)
{
    printf("  trackid %s %d\n", t == &track ? "ti" : "?", (int)dir);
    return 0x4a000 + dir;
}

void end_game_print_timer(char *buf, Timer t, int32_t flags)
{
    printf("  ptimer %08x %d\n", t.PackedTime, (int)flags);
    sprintf(buf, "P%x", t.PackedTime);
}

static void base_nothing(EndGameMenusBase *m, BScreenMessage msg,
                         BScreenCallbackData *data)
{
    (void)m;
    (void)msg;
    (void)data;
}

const EndGameMenusVTable kEndGameMenusBaseVTable = {
    base_nothing, base_nothing, base_nothing, base_nothing,
    endgame_menus_base_destroy,
};

EndGameMenusBase *endgame_menus_base_construct(EndGameMenusBase *m,
                                               uint32_t hash)
{
    printf("  base %08x\n", hash);
    m->ScreenHash = hash;
    m->vt = &kEndGameMenusBaseVTable;
    return m;
}

void endgame_menus_base_handle_event(EndGameMenusBase *m, BScreenMessage msg,
                                     BScreenCallbackData *data)
{
    (void)m;
    (void)msg;
    (void)data;
}

void endgame_menus_base_destroy(EndGameMenusBase *m, int32_t flags)
{
    m->vt = &kEndGameMenusBaseVTable;
    if (flags & 1)
        bFree(m);
}

void flailer_set_visibility(uint32_t screen, uint32_t object, int32_t v)
{
    printf("  vis %08x %08x %d\n", screen, object, (int)v);
}

void flailer_set_language_id(uint32_t screen, uint32_t object, uint32_t id)
{
    printf("  lang %08x %08x %#x\n", screen, object, id);
}

void flailer_set_object_color(uint32_t screen, uint32_t object,
                              const bVector4 *c)
{
    printf("  color %08x %08x %08x %08x %08x %08x\n", screen, object,
           fbits(c->x), fbits(c->y), fbits(c->z), fbits(c->w));
}

void flailer_set_text_format_option(uint32_t screen, uint32_t object,
                                    uint32_t f)
{
    printf("  opt %08x %08x %d\n", screen, object, (int)f);
}

int32_t flailer_printf(uint32_t screen, uint32_t object, const char *fmt,
                       ...)
{
    char buf[128];
    va_list ap;
    int n;

    va_start(ap, fmt);
    n = b_vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    printf("  printf %08x %08x [%s]\n", screen, object, buf);
    return n;
}

struct FlailerObjectChunk *flailer_find_object(uint32_t screen,
                                               uint32_t object,
                                               int32_t type)
{
    (void)type;
    findScreen = screen;
    findObject = object;
    return (struct FlailerObjectChunk *)(void *)fakeObject;
}

void flailertext_set_string(struct FlailerTextChunk *t, const char *s)
{
    (void)t;
    printf("  printf %08x %08x [%.127s]\n", findScreen, findObject, s);
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *p = malloc((size_t)size);

    memset(p, 0xcd, (size_t)size);
    printf("  malloc %s %d %d %d #%d\n", name, size, flags, pool,
           block_add(p));
    return p;
}

void bFree(void *p)
{
    printf("  free %s\n", ptr_name(p));
}

static const char *translate(int32_t id)
{
    static char ring[8][32];
    static int at;
    char *s = ring[at++ & 7];

    printf("  tr %#x\n", (unsigned)id);
    snprintf(s, 32, "T%x", (unsigned)id);
    return s;
}

static const char *translate_string(const char *t)
{
    printf("  trs %s\n", t);
    return NULL;
}

static void lap_record(int32_t player, int32_t place,
                       TransientStatsElement *row)
{
    printf("  lapspeech %d %d %s\n", (int)player, (int)place, row_name(row));
}

static void time_record(int32_t player, int32_t place,
                        TransientStatsElement *row)
{
    printf("  timespeech %d %d %s\n", (int)player, (int)place,
           row_name(row));
}

// ---------------------------------------------------------------- the dump

static const char *vt_name(const EndGameMenusVTable *vt)
{
    if (vt == &kBestLapTimesVTable)
        return "BLT";
    if (vt == &kBestTotalTimesVTable)
        return "BTT";
    if (vt == &kEndGameMenusBaseVTable)
        return "BASE";
    return "?";
}

static void dump(void)
{
    printf("  egs %d %d\n", (int)egs.Zeroed[7], (int)egs.Zeroed[8]);
    if (screen == NULL)
        printf("  screen none\n");
    else
        printf("  screen %s %08x\n", vt_name(screen->vt), screen->ScreenHash);
}

static void dump_records(void)
{
    int i;

    for (i = 0; i < NUM_PLAYERS; i++)
        printf("  rec %d %s %s\n", i, rec_name(players[i].BestLapRecordData),
               rec_name(players[i].BestTotalRecordData));
}

static void dump_lap_times_display(const BScreenCallbackData *d)
{
    if (pLapTimesDisplay == NULL)
        printf("  ltd none noise %d\n", (int)d->noise);
    else
        printf("  ltd %s %08x noise %d\n", ptr_name(pLapTimesDisplay),
               pLapTimesDisplay->ScreenHash, (int)d->noise);
}

int main(int argc, char **argv)
{
    static char line[512];
    FILE *sc;
    int i;

    if (argc < 2) {
        fprintf(stderr, "usage: endtimes_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (sc == NULL)
        return 2;

    for (i = 0; i < MAX_TYPES; i++) {
        specs[i].FullName = 0x40000 + i;
        ctinfo[i].pCarSpecs = &specs[i];
    }
    CarTypeInfoArray = ctinfo;
    CurrentTrackInfo = &track;
    pCurrentRace = &race;
    pEndGameScreens = &egs;
    gStartRaceTranslateFn = translate;
    gStartRaceTranslateStringFn = translate_string;
    gPostGameLapRecordFn = lap_record;
    gPostGameTimeRecordFn = time_record;

    while (fgets(line, sizeof line, sc)) {
        char *arg[40];
        const char *op;
        int n = 0;
        char *t;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        printf("> %s\n", line);
        for (t = strtok(line, "|"); t && n < 40; t = strtok(NULL, "|"))
            arg[n++] = t;
        op = arg[0];
        if (!strcmp(op, "rp")) {
            TheRaceParameters.TrackNumber = (int32_t)num(arg[1]);
            TheRaceParameters.TrackDirection = (int32_t)num(arg[2]);
            TheRaceParameters.NumLapsInRace = (int32_t)num(arg[3]);
            TheRaceParameters.NumPlayerCars = (int32_t)num(arg[4]);
        } else if (!strcmp(op, "race")) {
            race.NumLapsInRace = (int32_t)num(arg[1]);
            race.FinishLineBoundaryNumber = (int8_t)num(arg[2]);
        } else if (!strcmp(op, "first")) {
            int32_t k = (int32_t)num(arg[1]);

            race.pRacingCars[0] = k < 0 ? NULL : &rcs[k];
        } else if (!strcmp(op, "ct")) {
            CarTypeInfo *c = &ctinfo[num(arg[1])];

            c->Type = (int32_t)num(arg[2]);
            c->CarClass = (int8_t)num(arg[3]);
        } else if (!strcmp(op, "car")) {
            Car *c = &cars[num(arg[1])];
            int32_t p = (int32_t)num(arg[3]);

            c->pCarTypeInfo = &ctinfo[num(arg[2])];
            c->pPlayer = p < 0 ? NULL : &players[p];
        } else if (!strcmp(op, "rc")) {
            struct RacingCar *rc = &rcs[num(arg[1])];
            int32_t c = (int32_t)num(arg[2]);

            rc->pCar = c < 0 ? NULL : &cars[c];
            rc->NumLapsCompleted = (int8_t)num(arg[3]);
            rc->RaceTime.PackedTime = (uint32_t)num(arg[4]);
            for (i = 0; i < 5; i++)
                rc->BestRunningTimes[i].PackedTime = (uint32_t)num(arg[5 + i]);
        } else if (!strcmp(op, "player")) {
            Player *p = &players[num(arg[1])];

            p->PlayerNumber = (int32_t)num(arg[2]);
            memset(p->PlayerSettings.PlayerName, 0,
                   sizeof p->PlayerSettings.PlayerName);
            if (n > 3)
                strncpy(p->PlayerSettings.PlayerName, arg[3],
                        sizeof p->PlayerSettings.PlayerName - 1);
        } else if (!strcmp(op, "pbi")) {
            int32_t a = (int32_t)num(arg[1]), b = (int32_t)num(arg[2]);

            PlayerPlayersByIndex[0] = a < 0 ? NULL : &players[a];
            PlayerPlayersByIndex[1] = b < 0 ? NULL : &players[b];
            PlayerNumPlayers = (int32_t)num(arg[3]);
        } else if (!strcmp(op, "recp")) {
            Player *p = &players[num(arg[1])];
            int32_t l = (int32_t)num(arg[2]), tt = (int32_t)num(arg[3]);

            p->BestLapRecordData = l < 0 ? NULL : entry(1, l);
            p->BestTotalRecordData = tt < 0 ? NULL : entry(0, tt);
        } else if (!strcmp(op, "tidx")) {
            totalIndex = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "lidx")) {
            lapIndex = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "hs")) {
            FredHighScore *e = entry((int32_t)num(arg[1]), (int32_t)num(arg[2]));

            e->Time.PackedTime = (uint32_t)num(arg[3]);
            e->NameIndex = (int16_t)num(arg[4]);
            e->CarType = (int16_t)num(arg[5]);
        } else if (!strcmp(op, "fill")) {
            int32_t tb = (int32_t)num(arg[1]), at = (int32_t)num(arg[2]);
            int32_t cnt = (int32_t)num(arg[3]);

            for (i = 0; i < cnt; i++) {
                FredHighScore *e = entry(tb, at + i);

                e->Time.PackedTime = (uint32_t)num(arg[4]);
                e->NameIndex = 0;
                e->CarType = 0;
            }
        } else if (!strcmp(op, "name")) {
            uint8_t *s = &Fred.HighScoreNameTable[HIGH_SCORE_NAME_SIZE
                                                  * num(arg[1])];

            memset(s, 0, HIGH_SCORE_NAME_SIZE);
            if (n > 2)
                memcpy(s, arg[2], strlen(arg[2]) < HIGH_SCORE_NAME_SIZE
                                      ? strlen(arg[2]) : HIGH_SCORE_NAME_SIZE);
        } else if (!strcmp(op, "hole")) {
            Fred.HighScoreNameTable[HIGH_SCORE_NAME_SIZE * num(arg[1])] = 0;
        } else if (!strcmp(op, "ins")) {
            char buf[32];

            memset(buf, 0, sizeof buf);
            if (n > 1)
                strncpy(buf, arg[1], sizeof buf - 1);
            printf("  ins %d\n", (int)fred_insert_player_name(&Fred, buf));
        } else if (!strcmp(op, "look")) {
            const char *s = fred_lookup_player_name_from_table(
                &Fred, (int32_t)num(arg[1]));

            if (s == NULL)
                printf("  look none\n");
            else
                printf("  look %d [%.12s]\n",
                       (int)(((const uint8_t *)s - Fred.HighScoreNameTable)
                             / HIGH_SCORE_NAME_SIZE), s);
        } else if (!strcmp(op, "tab")) {
            int32_t tb = (int32_t)num(arg[1]), at = (int32_t)num(arg[2]);
            int32_t cnt = (int32_t)num(arg[3]);
            const uint8_t *base = (const uint8_t *)&Fred.ChallengeHighScores
                                  + (tb ? 8 * FRED_NUM_TOTAL_TIMES : 0);

            for (i = 0; i < cnt; i++) {
                FredHighScore e;

                memcpy(&e, base + 8 * (at + i), 8);
                printf("  tab %d %d %08x %d %d\n", (int)tb, (int)(at + i),
                       e.Time.PackedTime, (int)e.NameIndex, (int)e.CarType);
            }
        } else if (!strcmp(op, "names")) {
            int32_t cnt = (int32_t)num(arg[1]);
            int k;

            for (i = 0; i < cnt; i++) {
                const uint8_t *s =
                    &Fred.HighScoreNameTable[HIGH_SCORE_NAME_SIZE * i];

                printf("  name %d", i);
                for (k = 0; k < HIGH_SCORE_NAME_SIZE; k++)
                    printf(" %02x", s[k]);
                printf("\n");
            }
        } else if (!strcmp(op, "maybe")) {
            int32_t r = high_score_table_maybe_record_high_score(
                &Fred.ChallengeHighScores, &race, &rcs[num(arg[1])]);

            printf("  maybe %d\n", (int)r);
            dump_records();
        } else if (!strcmp(op, "ts")) {
            Fred.TransientStatsTable.NumStats = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "row")) {
            TransientStatsElement *e =
                &Fred.TransientStatsTable.Stats[num(arg[1])];

            e->FinishPosition = (int32_t)num(arg[2]);
            e->UniqueDriveNumber = (int32_t)num(arg[3]);
            e->NumLapTimes = (int32_t)num(arg[4]);
            for (i = 0; i < 11; i++)
                e->LapTimes[i].PackedTime = (uint32_t)num(arg[5 + i]);
        } else if (!strcmp(op, "egs")) {
            egs.Zeroed[7] = (int32_t)num(arg[1]);
            egs.Zeroed[8] = (int32_t)num(arg[2]);
        } else if (!strcmp(op, "blt") || !strcmp(op, "btt")) {
            void *m = malloc(sizeof(EndGameMenusBase));

            memset(m, 0xcd, sizeof(EndGameMenusBase));
            block_add(m);
            screen = (op[1] == 'l' ? best_lap_times_construct
                                   : best_total_times_construct)(
                m, (uint32_t)num(arg[1]), NULL);
        } else if (!strcmp(op, "scroll")) {
            screen->vt->Scroll(screen, (BScreenMessage)num(arg[1]), NULL);
        } else if (!strcmp(op, "tick")) {
            screen->vt->Tick(screen, BMSG_SCREEN_TICK, NULL);
        } else if (!strcmp(op, "render")) {
            screen->vt->Render(screen, BMSG_SCREEN_RENDER, NULL);
        } else if (!strcmp(op, "dtor")) {
            screen->vt->Destroy(screen, (int32_t)num(arg[1]));
            dump();
            screen = NULL;
        } else if (!strcmp(op, "dump")) {
            dump();
        } else if (!strcmp(op, "ltcb")) {
            BScreenCallbackData d;

            d.itemHash = (uint32_t)num(arg[2]);
            d.port = 0;
            d.param = 0;
            d.noise = (int32_t)num(arg[3]);
            lap_times_display_callback(NULL, (BScreenMessage)num(arg[1]), &d);
            dump_lap_times_display(&d);
        } else {
            fprintf(stderr, "bad op %s\n", op);
            return 3;
        }
        fflush(stdout);
    }
    fclose(sc);
    return 0;
}
