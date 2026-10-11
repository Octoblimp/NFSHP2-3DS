// Drives startrace.c for tools/startrace_check.py. A script of ops, one per
// line, fields split on '|':
//
//   rp|DIR|TYPE|CARS|OBJ|COP  TheRaceParameters' TrackDirection, RaceType,
//                      NumPlayerCars, HasObjective and BeACop
//   game|T             Fred.GameType
//   event|TYPE|PLAYERS TheRaceEvent's type and player count
//   track|FWD|REV      CurrentTrackInfo's two LanguageIDs
//   ridx|N, rcount|N   what GetRaceIndex and GetRaceCount answer
//   tour|B0|B1|...     the tournament's points, a byte for each racer
//   miss|ID            GetTranslatedString(ID) has no string
//   trs|MODE           GetTranslatedString(const char *): 0 the text
//                      itself, 1 the text after an X
//   rc|N               pRaceCoordinator set (1) or NULL (0)
//   chr|I|NAME         character I's name
//   drv|I|UNIQUE|START|TYPE|RIDE|CHAR|ELIM  TheRaceParameters' driver I;
//                      CHAR -1 has no CharacterInfo
//   ndrv|N             NumDriverInfo
//   race|N|D0|D1|...   the race's N cars, each driving driver Dn
//   player|UNIQUE|NUM|NAME  the car GetCarByDriverNumber(UNIQUE) answers,
//                      with its player's number and name
//   pset|I|NAME        TheRaceParameters.PlayerSettings[I].PlayerName
//   mgr|N|CUR|A|B|C|D  TheStartRaceScreenManager, each screen 0 for NULL,
//                      1 Stats, 2 Blurb, 3 2P Be A Cop, 4 Letterbox
//   add|K              AddScreen on the manager, K as mgr's
//   enable, disable    EnableStartRaceScreens, DisableStartRaceScreens
//   ready              StartRaceScreensReadyToSkip
//   need               the three NeedToSee answers
//   kod                the knockout's and the tournament's tests
//   tname|SCREEN|TRACK|RACE|ADD  the track's name and the race's number
//   getpos|P           GetStatsForRacePosition(P) on the grid up
//   stats|MSG|ITEM|PORT|PARAM|NOISE   the grid's callback
//   letter|MSG|ITEM|PORT|PARAM|NOISE  the letterbox's
//   dump               the manager and the grid
//
// Every call out of startrace.c prints what it was asked, as the model's
// stubs at retail's addresses do.
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "car.h"
#include "cartypeinfo.h"
#include "characterinfo.h"
#include "flailer.h"
#include "fred.h"
#include "fredrace.h"
#include "player.h"
#include "race.h"
#include "racecoord.h"
#include "rcpost.h"
#include "startrace.h"
#include "track.h"
#include "world.h"

#define MAX_DRIVERS 16
#define MAX_TYPES   64
#define MAX_MISSING 16

// What startrace.c reads.
Race *pCurrentRace;
RaceCoordinator *pRaceCoordinator;
RaceParameters TheRaceParameters;
FrontendDatabase Fred;
TrackInfo *CurrentTrackInfo;
RaceEvent TheRaceEvent;
int32_t (*gRaceEventGetRaceIndexFn)(void);
void (*gChangeToScreenFn)(const char *name, int32_t push);

static Race race;
static RacingCar rcars[RACE_MAX_RACING_CARS];
static Car cars[RACE_MAX_RACING_CARS];
static DriverInfo drivers[MAX_DRIVERS];
static CharacterInfo chars[8];
static TrackInfo track;
static CarTypeInfo ctinfo[MAX_TYPES];
static CarSpecs specs[MAX_TYPES];
static Car playerCars[8];
static Player players[8];
static int32_t playerUnique[8];
static int numPlayerCars;
static RaceCoordinator *theRc;
static uint8_t tourState[32];
static int32_t raceIndex, raceCount;
static uint32_t missing[MAX_MISSING];
static int numMissing;
static int trsMode;
static void *lastMalloc;

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

static const char *name_or_null(const char *s)
{
    return s != NULL ? s : "NULL";
}

static const char *screen_name(int32_t code)
{
    switch (code) {
    case 1: return kPreRaceStatsScreen;
    case 2: return kPreRaceBlurbScreen;
    case 3: return kPreRace2PBeACopScreen;
    case 4: return kPreRaceLetterboxScreen;
    }
    return NULL;
}

// ------------------------------------------------------------ the stubs

const CarTypeInfo *cartypeinfo_get(int32_t carType)
{
    return &ctinfo[carType & (MAX_TYPES - 1)];
}

struct Car *world_get_car_by_driver_number(int32_t n)
{
    int i;

    printf("  car %d\n", (int)n);
    for (i = 0; i < numPlayerCars; i++)
        if (playerUnique[i] == n)
            return &playerCars[i];
    return NULL;
}

void racecoordinator_post_message(RaceCoordinator *rc, RCMessage msg,
                                  int32_t param)
{
    printf("  post %d %d %d\n", rc != NULL, (int)msg, (int)param);
}

DriverInfo *race_parameters_get_driver_info(int32_t i)
{
    return &drivers[i];
}

int32_t fred_use_the_race_event(const FrontendDatabase *f)
{
    int32_t t = f->GameType;

    return t == 4 || (t >= 8 && t < 10);
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

int32_t flailer_printf(uint32_t screen, uint32_t object, const char *fmt,
                       ...)
{
    char buf[128];
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    printf("  printf %08x %08x [%s]\n", screen, object, buf);
    return (int32_t)strlen(buf);
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *p = malloc((size_t)size);

    memset(p, 0xcd, (size_t)size);
    if (size == (int)sizeof(PreRaceStats))
        printf("  malloc %s 400 %d %d\n", name, flags, pool);
    else
        printf("  malloc %s %d %d %d\n", name, size, flags, pool);
    lastMalloc = p;
    return p;
}

void bFree(void *p)
{
    printf("  free %d\n", p != NULL && p == lastMalloc);
    if (p == lastMalloc)
        lastMalloc = NULL;
    free(p);
}

static void change_to_screen(const char *name, int32_t push)
{
    printf("  change %s %d\n", name_or_null(name), (int)push);
}

static const char *translate(int32_t id)
{
    static char ring[8][32];
    static int at;
    char *s;
    int i;

    printf("  tr %#x\n", (unsigned)id);
    for (i = 0; i < numMissing; i++)
        if (missing[i] == (uint32_t)id)
            return NULL;
    if (id == STARTRACE_LANG_RACE_OF)
        return "R%d/%d";
    s = ring[at++ & 7];
    snprintf(s, 32, "T%x", (unsigned)id);
    return s;
}

static const char *translate_string(const char *t)
{
    static char ring[8][48];
    static int at;
    char *s;

    printf("  trs %s\n", t);
    if (trsMode == 0)
        return NULL;
    s = ring[at++ & 7];
    snprintf(s, 48, "X%s", t);
    return s;
}

static int32_t get_race_index(void)
{
    printf("  raceidx\n");
    return raceIndex;
}

static int32_t get_race_count(void)
{
    printf("  racecount\n");
    return raceCount;
}

static const uint8_t *get_tournament_state(void)
{
    printf("  tourstate\n");
    return tourState;
}

// ---------------------------------------------------------------- the dump

static void dump(void)
{
    const tStartRaceScreenManager *m = &TheStartRaceScreenManager;
    const PreRaceStats *s = PreRaceStatsInstance;
    int i;

    printf("  mgr %d %d [%s] [%s] [%s] [%s]\n", (int)m->NumScreens,
           (int)m->CurrentScreen, name_or_null(m->Screens[0]),
           name_or_null(m->Screens[1]), name_or_null(m->Screens[2]),
           name_or_null(m->Screens[3]));
    if (s == NULL) {
        printf("  inst 0\n");
        return;
    }
    printf("  inst 1 %08x\n", s->ScreenHash);
    for (i = 0; i < PRERACE_STATS_LINES; i++) {
        const PreRaceStatsLine *l = &s->StatsLines[i];

        printf("  line %d %d [%s] %d %#x %d %08x %08x %08x %08x\n", i,
               (int)l->StartPosition, name_or_null(l->CharacterName),
               (int)l->CarTypeNumber, (unsigned)l->KOStatus, (int)l->Points,
               fbits(l->Color.x), fbits(l->Color.y), fbits(l->Color.z),
               fbits(l->Color.w));
    }
}

static void callback(void (*fn)(struct BGameFlow *, BScreenMessage,
                                BScreenCallbackData *),
                     char **arg)
{
    BScreenCallbackData d;

    d.itemHash = (uint32_t)num(arg[2]);
    d.port = (int32_t)num(arg[3]);
    d.param = (int32_t)num(arg[4]);
    d.noise = (int32_t)num(arg[5]);
    fn(NULL, (BScreenMessage)num(arg[1]), &d);
    printf("  data %d %d\n", (int)d.param, (int)d.noise);
}

int main(int argc, char **argv)
{
    static char line[512];
    static RaceCoordinator rcMem;
    FILE *sc;
    int i;

    if (argc < 2) {
        fprintf(stderr, "usage: startrace_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (sc == NULL)
        return 2;

    for (i = 0; i < MAX_TYPES; i++) {
        specs[i].FullName = 0x40000 + i;
        ctinfo[i].pCarSpecs = &specs[i];
    }
    for (i = 0; i < RACE_MAX_RACING_CARS; i++) {
        rcars[i].pCar = &cars[i];
        race.pRacingCars[i] = &rcars[i];
    }
    for (i = 0; i < 8; i++)
        playerCars[i].pPlayer = &players[i];
    pCurrentRace = &race;
    CurrentTrackInfo = &track;
    theRc = &rcMem;
    gChangeToScreenFn = change_to_screen;
    gStartRaceTranslateFn = translate;
    gStartRaceTranslateStringFn = translate_string;
    gRaceEventGetRaceIndexFn = get_race_index;
    gRaceEventGetRaceCountFn = get_race_count;
    gRaceEventGetTournamentStateFn = get_tournament_state;

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
            TheRaceParameters.TrackDirection = (int32_t)num(arg[1]);
            TheRaceParameters.RaceType = (int32_t)num(arg[2]);
            TheRaceParameters.NumPlayerCars = (int32_t)num(arg[3]);
            TheRaceParameters.HasObjective = (int32_t)num(arg[4]);
            TheRaceParameters.BeACop = (int32_t)num(arg[5]);
        } else if (!strcmp(op, "game")) {
            Fred.GameType = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "event")) {
            TheRaceEvent.nType = (int16_t)num(arg[1]);
            TheRaceEvent.nInitialPlayers = (int16_t)num(arg[2]);
        } else if (!strcmp(op, "track")) {
            track.TrackLanguageID = (int32_t)num(arg[1]);
            track.ReverseTrackLanguageID = (int32_t)num(arg[2]);
        } else if (!strcmp(op, "ridx")) {
            raceIndex = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "rcount")) {
            raceCount = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "tour")) {
            memset(tourState, 0, sizeof tourState);
            for (i = 1; i < n; i++)
                tourState[i - 1] = (uint8_t)num(arg[i]);
        } else if (!strcmp(op, "miss")) {
            missing[numMissing++] = (uint32_t)num(arg[1]);
        } else if (!strcmp(op, "trs")) {
            trsMode = (int)num(arg[1]);
        } else if (!strcmp(op, "rc")) {
            pRaceCoordinator = num(arg[1]) ? theRc : NULL;
        } else if (!strcmp(op, "chr")) {
            snprintf(chars[num(arg[1])].CharacterName,
                     sizeof chars[0].CharacterName, "%s", arg[2]);
        } else if (!strcmp(op, "drv")) {
            DriverInfo *d = &drivers[num(arg[1])];
            int32_t c = (int32_t)num(arg[6]);

            d->UniqueDriverNumber = (int8_t)num(arg[2]);
            d->StartingPosition = (int8_t)num(arg[3]);
            d->TheDriverType = (DriverType)num(arg[4]);
            d->CurrentRideInfo.Type = (int32_t)num(arg[5]);
            d->pCharacterInfo = c < 0 ? NULL : &chars[c];
            d->EliminatedRank = (int8_t)num(arg[7]);
        } else if (!strcmp(op, "ndrv")) {
            TheRaceParameters.NumDriverInfo = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "race")) {
            race.NumRacingCars = (int32_t)num(arg[1]);
            for (i = 2; i < n; i++)
                cars[i - 2].MyDriver = &drivers[num(arg[i])];
        } else if (!strcmp(op, "player")) {
            int32_t u = (int32_t)num(arg[1]);

            for (i = 0; i < numPlayerCars && playerUnique[i] != u; i++)
                ;
            if (i == numPlayerCars)
                playerUnique[numPlayerCars++] = u;
            players[i].PlayerNumber = (int32_t)num(arg[2]);
            snprintf(players[i].PlayerSettings.PlayerName,
                     sizeof players[i].PlayerSettings.PlayerName, "%s",
                     arg[3]);
        } else if (!strcmp(op, "pset")) {
            cPlayerSettings *p = &TheRaceParameters.PlayerSettings[num(arg[1])];

            snprintf(p->PlayerName, sizeof p->PlayerName, "%s", arg[2]);
        } else if (!strcmp(op, "mgr")) {
            tStartRaceScreenManager *m = &TheStartRaceScreenManager;

            m->NumScreens = (int32_t)num(arg[1]);
            m->CurrentScreen = (int32_t)num(arg[2]);
            for (i = 0; i < 4; i++)
                m->Screens[i] = screen_name((int32_t)num(arg[3 + i]));
        } else if (!strcmp(op, "add")) {
            start_race_add_screen(&TheStartRaceScreenManager,
                                  screen_name((int32_t)num(arg[1])));
        } else if (!strcmp(op, "enable")) {
            enable_start_race_screens();
        } else if (!strcmp(op, "disable")) {
            disable_start_race_screens();
        } else if (!strcmp(op, "ready")) {
            printf("  ready %d\n", (int)start_race_screens_ready_to_skip());
        } else if (!strcmp(op, "need")) {
            const tStartRaceScreenManager *m = &TheStartRaceScreenManager;

            printf("  need %d %d %d\n",
                   (int)start_race_need_to_see_objective(m),
                   (int)start_race_need_to_see_2p_be_a_cop(m),
                   (int)start_race_need_to_see_pre_race_stats(m));
        } else if (!strcmp(op, "kod")) {
            printf("  kod %d %d\n", (int)race_knockout_info_should_be_displayed(),
                   (int)tournament_standings_should_be_displayed());
        } else if (!strcmp(op, "tname")) {
            set_track_name_and_race_number((uint32_t)num(arg[1]),
                                           (uint32_t)num(arg[2]),
                                           (uint32_t)num(arg[3]),
                                           (int32_t)num(arg[4]));
        } else if (!strcmp(op, "getpos")) {
            PreRaceStatsLine *l = pre_race_stats_get_stats_for_race_position(
                PreRaceStatsInstance, (int32_t)num(arg[1]));

            printf("  getpos %d\n",
                   l == NULL ? -1
                             : (int)(l - PreRaceStatsInstance->StatsLines));
        } else if (!strcmp(op, "stats")) {
            callback(pre_race_stats_callback, arg);
        } else if (!strcmp(op, "letter")) {
            callback(pre_race_letterbox_callback, arg);
        } else if (!strcmp(op, "dump")) {
            dump();
        } else {
            fprintf(stderr, "bad op %s\n", op);
            return 3;
        }
        fflush(stdout);
    }
    fclose(sc);
    return 0;
}
