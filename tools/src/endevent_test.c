// Drives endevent.c for tools/endevent_check.py. A script of ops, one per
// line, fields split on '|':
//
//   gt|N               Fred's GameType
//   ev|NUM|TYPE|NREW|LAST|INIT|STATE  TheRaceEvent's nNumber, nType,
//                      nRewards, bIsLastOpen, nInitialPlayers and pState
//                      (1 the state, 0 NULL)
//   goal|TYPE|DATA     its Objective's nType and nData
//   rew|I|TYPE|V1|V2|V3|DATA  its reward I
//   res|I|POS          its result I's place
//   st|B0|..|B15       the state's bytes
//   rp|DIR|RT|TTT|P2P|COP  TheRaceParameters' TrackDirection, RaceType,
//                      TimeTrialTime, Point2Point and BeACop
//   status|S, any|E, earned|E, adv|A  what GetStatus, AnyRewardEarned,
//                      RewardEarned and StatusAdvanced answer
//   ranks|R0|..|R15    what RacerRank answers for each racer index
//   urank|R            what UserRank answers
//   opened|N|E0|E1|E2|E3  what the events opened answer, and their list
//   ts|NUM             TransientStats' NumStats
//   row|I|POS|UNIQUE|REASON|TIME|BEST|PTS|TOTAL|COPTIME  row I; COPTIME
//                      is the float's bits
//   char|I|NAME        character I's name
//   drv|I|UNIQUE|TYPE|CHAR  driver I; CHAR -1 has no CharacterInfo
//   car|I|DNUM|RIDE|DRV|PLAYER  car I: its DriverNumber, its ride's car
//                      type, its driver and its player (-1 none)
//   rc|I|CAR           racing car I's car (-1 none)
//   race|N|RC0|..|RC7  pCurrentRace's NumRacingCars and racing cars (-1
//                      none); race|-1 is no race
//   byd|N|CAR          the world's car for driver number N (0 or 1)
//   player|I|NUM|NAME  player I's PlayerNumber and name
//   pbn|A|B, pbi|A|B   PlayersByNumber and PlayersByIndex (-1 none)
//   cti|T              CurrentTrackInfo: track T, -1 none
//   egs|Z2|Z3|Z6       the screens' list's speech flags
//   tourney|HASH, reward|HASH, unlocked|HASH, btc1|HASH, btc2|HASH
//                      a screen made
//   scroll|MSG, tick, render  the screen's vtable's Scroll, Tick, Render
//   dtor|FLAGS         its destructor
//   lang, rank, fmt|ID the reward screen's blurb id, the player's place
//                      and the blurb for ID
//
// Every call out of endevent.c prints what it was asked, as the model's
// stubs at retail's addresses do. Nothing allocated is given back, so no
// address is seen twice and each block keeps the number it was made with.
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bprintf.h"
#include "car.h"
#include "cartypeinfo.h"
#include "characterinfo.h"
#include "endevent.h"
#include "endgame.h"
#include "endresults.h"
#include "eventtree.h"
#include "flailer.h"
#include "fred.h"
#include "fredend.h"
#include "fredevent.h"
#include "fredrace.h"
#include "player.h"
#include "race.h"
#include "raceevent.h"
#include "racerun.h"
#include "racespeech.h"
#include "startrace.h"
#include "track.h"
#include "world.h"

#define MAX_TYPES   64
#define MAX_BLOCKS  4096
#define NUM_CARS    16
#define NUM_PLAYERS 4
#define NUM_TRACKS  8

// What the file reads.
FrontendDatabase Fred;
RaceParameters TheRaceParameters;
RaceEvent TheRaceEvent;
EventsOpened TheEventsOpened;
Race *pCurrentRace;
TrackInfo *CurrentTrackInfo;
const CarTypeInfo *CarTypeInfoArray;
EndGameScreens *pEndGameScreens;
struct Player *PlayerPlayersByNumber[2];
struct Player *PlayerPlayersByIndex[2];
const char *(*gStartRaceTranslateFn)(int32_t id);
const char *(*gStartRaceTranslateStringFn)(const char *s);
void (*gRenderTextIntoGroupFn)(uint32_t screen, uint32_t group,
                               const char *str);
const bVector4 PlayerTextColors[2] = {
    { 134.0f, 96.0f, 48.0f, 128.0f },
    { 0.0f, 128.0f, 0.0f, 128.0f },
};
const bVector4 DefaultTextColor = { 128.0f, 128.0f, 128.0f, 128.0f };

static CarTypeInfo ctinfo[MAX_TYPES];
static CarSpecs specs[MAX_TYPES];
static Car cars[NUM_CARS];
static RideInfo rides[NUM_CARS];
static DriverInfo drivers[NUM_CARS];
static CharacterInfo chars[8];
static struct RacingCar rcs[NUM_CARS];
static Player players[NUM_PLAYERS];
static Race race;
static TrackInfo tracks[NUM_TRACKS];
static EndGameScreens egs;
static uint8_t state[16];
static int32_t statusAnswer, anyAnswer, earnedAnswer, advAnswer;
static int32_t rankAnswer[16], urankAnswer;
static int32_t openedN, openedList[4];
static int32_t carByDriver[2] = { -1, -1 };
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

static float bitsf(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
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

static const char *player_name(const struct Player *p)
{
    static char s[24];

    if (p == NULL)
        return "none";
    snprintf(s, sizeof s, "p%d", (int)(p - players));
    return s;
}

static const char *state_name(const uint8_t *s)
{
    return s == state ? "st" : "none";
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

struct Car *world_get_car_by_driver_number(int32_t n)
{
    printf("  carby %d\n", (int)n);
    if (n < 0 || n > 1 || carByDriver[n] < 0)
        return NULL;
    return &cars[carByDriver[n]];
}

int32_t fred_use_the_race_event(const FrontendDatabase *f)
{
    int32_t t = f->GameType;

    return t == 4 || (t >= 8 && t < 10);
}

TrackInfo *track_get_info(int i)
{
    printf("  trackinfo %d\n", i);
    return i >= 0 && i < NUM_TRACKS ? &tracks[i] : NULL;
}

int32_t get_the_right_track_language_id(const struct TrackInfo *t,
                                        int32_t dir)
{
    printf("  trackid t%d %d\n", (int)(t - tracks), (int)dir);
    return 0x4a000 + (int32_t)(t - tracks) * 16 + dir;
}

void set_track_name_and_race_number(uint32_t screen, uint32_t trackObj,
                                    uint32_t raceObj, int32_t add)
{
    printf("  trackrace %08x %08x %08x %d\n", screen, trackObj, raceObj,
           (int)add);
}

void end_game_print_timer(char *buf, Timer t, int32_t flags)
{
    printf("  ptimer %08x %d\n", t.PackedTime, (int)flags);
    sprintf(buf, "P%x", t.PackedTime);
}

void end_reward_show_car_count(uint32_t hash, int32_t cop)
{
    printf("  showcount %08x %d\n", hash, (int)cop);
}

void end_reward_clear_car_count(uint32_t hash)
{
    printf("  clearcount %08x\n", hash);
}

int32_t raceevent_get_status(const RaceEvent *ev)
{
    printf("  status %s\n", ev == &TheRaceEvent ? "tre" : "?");
    return statusAnswer;
}

int32_t raceevent_any_reward_earned(const RaceEvent *ev)
{
    printf("  any %s\n", ev == &TheRaceEvent ? "tre" : "?");
    return anyAnswer;
}

int32_t raceevent_reward_earned(const RaceEvent *ev, int32_t i,
                                const uint8_t *s)
{
    printf("  earned %s %d %s\n", ev == &TheRaceEvent ? "tre" : "?", (int)i,
           s == NULL ? "none" : "?");
    return earnedAnswer;
}

int32_t raceevent_status_advanced(const RaceEvent *ev)
{
    printf("  adv %s\n", ev == &TheRaceEvent ? "tre" : "?");
    return advAnswer;
}

int32_t raceevent_racer_index_from_driver_number(const RaceEvent *ev,
                                                 int32_t n)
{
    printf("  ridx %d\n", (int)n);
    return n < 100 ? n : ev->nInitialPlayers + n - 100;
}

uint8_t *raceevent_get_tournament_state(const RaceEvent *ev)
{
    printf("  tstate\n");
    return ev->pState;
}

int32_t tournament_state_racer_rank(const uint8_t *s, int32_t i)
{
    printf("  rank %s %d\n", state_name(s), (int)i);
    return rankAnswer[i & 15];
}

int32_t tournament_state_user_rank(const uint8_t *s)
{
    printf("  urank %s\n", state_name(s));
    return urankAnswer;
}

int32_t tournament_state_points_for_finish_pos(int32_t pos)
{
    printf("  pts %d\n", (int)pos);
    return 100 + pos;
}

int32_t events_opened_passed(const EventsOpened *l, int32_t *out,
                             int32_t max, const RaceEvent *ev)
{
    int i;

    printf("  opened %s %d %s\n", l == &TheEventsOpened ? "teo" : "?",
           (int)max, ev == &TheRaceEvent ? "tre" : "?");
    for (i = 0; i < openedN && i < 4; i++)
        out[i] = openedList[i];
    return openedN;
}

void tournament_race_speech(int32_t b, int32_t n)
{
    printf("  tspeech %d %d\n", (int)b, (int)n);
}

void race_event_speech(struct Player *p, TransientStatsElement *row)
{
    printf("  evspeech %s %s\n", player_name(p), row_name(row));
}

void race_event_reward_speech(struct Player *p, int32_t won,
                              const uint8_t *reward)
{
    printf("  rwspeech %s %d %s\n", player_name(p), (int)won,
           reward == NULL ? "none"
           : reward == (const uint8_t *)&TheRaceEvent.aRewards[0] ? "r0"
           : "?");
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

void flailer_set_group_visibility(uint32_t screen, uint32_t group, int32_t v)
{
    printf("  gvis %08x %08x %d\n", screen, group, (int)v);
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
    int n;

    va_start(ap, fmt);
    n = b_vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    printf("  printf %08x %08x [%s]\n", screen, object, buf);
    return n;
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *p = malloc((size_t)size);
    int shown = size;

    if ((size_t)size == sizeof(TourneyPoints))
        shown = 20;
    memset(p, 0xcd, (size_t)size);
    printf("  malloc %s %d %d %d #%d\n", name, shown, flags, pool,
           block_add(p));
    return p;
}

void bFree(void *p)
{
    printf("  free %s\n", ptr_name(p));
}

// The tr stub's formats: the blurbs' directives, in short.
static const struct {
    int32_t id;
    const char *fmt;
} kFormats[] = {
    { 0xde2b0, "C1 %d" },
    { 0xde2b4, "C2 %d+%d" },
    { 0xde2b1, "C3 %d,%d,%d" },
    { 0xde2b2, "U1 %d" },
    { 0xde2b5, "U2 %d+%d" },
    { 0xde2b3, "U3 %d,%d,%d" },
    { 0xde4a4, "PASSED %d" },
    { 0xde4a5, "FAILED %d" },
    { 0xe09c0, "LAPF %s/%s" },
    { 0xe09c1, "LAPU %s/%s" },
    { 0xe09c2, "TOTF %s/%s" },
    { 0xe09c3, "TOTU %s/%s" },
    { 0xe09c4, "COPU %s" },
    { 0xe09c6, "LAPP %s" },
    { 0xe09c7, "TOTP %s" },
    { 0xe30d0, "1U %s" },
    { 0xe30d1, "2U %s" },
    { 0xe30d2, "3U %s" },
    { 0xe30d3, "PLF %s/%s" },
    { 0xe30d4, "PU %s" },
};

static const char *translate(int32_t id)
{
    static char ring[8][32];
    static int at;
    char *s = ring[at++ & 7];
    size_t i;

    printf("  tr %#x\n", (unsigned)id);
    for (i = 0; i < sizeof kFormats / sizeof kFormats[0]; i++)
        if (kFormats[i].id == id)
            return kFormats[i].fmt;
    snprintf(s, 32, "T%x", (unsigned)id);
    return s;
}

static const char *translate_string(const char *t)
{
    printf("  trs %s\n", t);
    return NULL;
}

static void render_text(uint32_t screen, uint32_t group, const char *str)
{
    printf("  rtig %08x %08x [%.200s]\n", screen, group, str);
}

// ---------------------------------------------------------------- the dump

static const char *vt_name(const EndGameMenusVTable *vt)
{
    if (vt == &kTourneyStandingsVTable)
        return "TOURNEY";
    if (vt == &kEventRewardVTable)
        return "REWARD";
    if (vt == &kEventsUnlockedVTable)
        return "UNLOCKED";
    if (vt == &kBTCResults1PVTable)
        return "BTC1";
    if (vt == &kBTCResults2PVTable)
        return "BTC2";
    if (vt == &kEndGameMenusBaseVTable)
        return "BASE";
    return "?";
}

static void dump(void)
{
    printf("  egs %d %d %d\n", (int)egs.Zeroed[2], (int)egs.Zeroed[3],
           (int)egs.Zeroed[6]);
    if (screen == NULL)
        printf("  screen none\n");
    else
        printf("  screen %s %08x\n", vt_name(screen->vt), screen->ScreenHash);
}

static Player *player_or_null(int64_t i)
{
    return i < 0 ? NULL : &players[i];
}

int main(int argc, char **argv)
{
    static char line[512];
    FILE *sc;
    int i;

    if (argc < 2) {
        fprintf(stderr, "usage: endevent_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (sc == NULL)
        return 2;

    for (i = 0; i < MAX_TYPES; i++) {
        specs[i].FullName = 0x40000 + i;
        ctinfo[i].pCarSpecs = &specs[i];
    }
    for (i = 0; i < NUM_CARS; i++)
        cars[i].pRideInfo = &rides[i];
    CarTypeInfoArray = ctinfo;
    CurrentTrackInfo = &tracks[0];
    pCurrentRace = &race;
    pEndGameScreens = &egs;
    gStartRaceTranslateFn = translate;
    gStartRaceTranslateStringFn = translate_string;
    gRenderTextIntoGroupFn = render_text;

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
        if (!strcmp(op, "gt")) {
            Fred.GameType = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "ev")) {
            RaceEvent *ev = &TheRaceEvent;

            ev->nNumber = (int16_t)num(arg[1]);
            ev->nType = (int16_t)num(arg[2]);
            ev->nRewards = (int16_t)num(arg[3]);
            ev->bIsLastOpen = (int32_t)num(arg[4]);
            ev->nInitialPlayers = (int16_t)num(arg[5]);
            ev->pState = num(arg[6]) ? state : NULL;
        } else if (!strcmp(op, "goal")) {
            TheRaceEvent.Objective.nType = (uint16_t)num(arg[1]);
            TheRaceEvent.Objective.nData = (uint32_t)num(arg[2]);
        } else if (!strcmp(op, "rew")) {
            EventReward *r = &TheRaceEvent.aRewards[num(arg[1])];

            r->nType = (uint8_t)num(arg[2]);
            r->nValue1 = (uint8_t)num(arg[3]);
            r->nValue2 = (uint8_t)num(arg[4]);
            r->nValue3 = (uint8_t)num(arg[5]);
            r->nData = (int32_t)num(arg[6]);
        } else if (!strcmp(op, "res")) {
            TheRaceEvent.aResults[num(arg[1])].nPosition = (int32_t)num(arg[2]);
        } else if (!strcmp(op, "st")) {
            for (i = 0; i < 16; i++)
                state[i] = (uint8_t)num(arg[1 + i]);
        } else if (!strcmp(op, "rp")) {
            TheRaceParameters.TrackDirection = (int32_t)num(arg[1]);
            TheRaceParameters.RaceType = (int32_t)num(arg[2]);
            TheRaceParameters.TimeTrialTime.PackedTime = (uint32_t)num(arg[3]);
            TheRaceParameters.Point2Point = (int32_t)num(arg[4]);
            TheRaceParameters.BeACop = (int32_t)num(arg[5]);
        } else if (!strcmp(op, "status")) {
            statusAnswer = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "any")) {
            anyAnswer = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "earned")) {
            earnedAnswer = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "adv")) {
            advAnswer = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "ranks")) {
            for (i = 0; i < 16; i++)
                rankAnswer[i] = (int32_t)num(arg[1 + i]);
        } else if (!strcmp(op, "urank")) {
            urankAnswer = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "opened")) {
            openedN = (int32_t)num(arg[1]);
            for (i = 0; i < 4; i++)
                openedList[i] = (int32_t)num(arg[2 + i]);
        } else if (!strcmp(op, "ts")) {
            Fred.TransientStatsTable.NumStats = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "row")) {
            TransientStatsElement *e =
                &Fred.TransientStatsTable.Stats[num(arg[1])];

            e->FinishPosition = (int32_t)num(arg[2]);
            e->UniqueDriveNumber = (int32_t)num(arg[3]);
            e->FinishReason = (int32_t)num(arg[4]);
            e->RaceTime.PackedTime = (uint32_t)num(arg[5]);
            e->BestLapTime.PackedTime = (uint32_t)num(arg[6]);
            e->PointsThisRace = (int32_t)num(arg[7]);
            e->PointsTotal = (int32_t)num(arg[8]);
            e->BeACopTime = bitsf((uint32_t)num(arg[9]));
        } else if (!strcmp(op, "char")) {
            snprintf(chars[num(arg[1])].CharacterName,
                     sizeof chars[0].CharacterName, "%s", n > 2 ? arg[2] : "");
        } else if (!strcmp(op, "drv")) {
            DriverInfo *d = &drivers[num(arg[1])];
            int32_t c = (int32_t)num(arg[4]);

            d->UniqueDriverNumber = (int8_t)num(arg[2]);
            d->TheDriverType = (DriverType)num(arg[3]);
            d->pCharacterInfo = c < 0 ? NULL : &chars[c];
        } else if (!strcmp(op, "car")) {
            Car *c = &cars[num(arg[1])];
            int32_t dv = (int32_t)num(arg[4]);

            c->DriverNumber = (int16_t)num(arg[2]);
            c->pRideInfo->Type = (int32_t)num(arg[3]);
            c->MyDriver = dv < 0 ? NULL : &drivers[dv];
            c->pPlayer = player_or_null(num(arg[5]));
        } else if (!strcmp(op, "rc")) {
            int32_t c = (int32_t)num(arg[2]);

            rcs[num(arg[1])].pCar = c < 0 ? NULL : &cars[c];
        } else if (!strcmp(op, "race")) {
            int32_t cnt = (int32_t)num(arg[1]);

            if (cnt < 0) {
                pCurrentRace = NULL;
            } else {
                pCurrentRace = &race;
                race.NumRacingCars = cnt;
                for (i = 0; i < RACE_MAX_RACING_CARS; i++) {
                    int32_t k = (int32_t)num(arg[2 + i]);

                    race.pRacingCars[i] = k < 0 ? NULL : &rcs[k];
                }
            }
        } else if (!strcmp(op, "byd")) {
            carByDriver[num(arg[1])] = (int32_t)num(arg[2]);
        } else if (!strcmp(op, "player")) {
            Player *p = &players[num(arg[1])];

            p->PlayerNumber = (int32_t)num(arg[2]);
            memset(p->PlayerSettings.PlayerName, 0,
                   sizeof p->PlayerSettings.PlayerName);
            if (n > 3)
                strncpy(p->PlayerSettings.PlayerName, arg[3],
                        sizeof p->PlayerSettings.PlayerName - 1);
        } else if (!strcmp(op, "pbn")) {
            PlayerPlayersByNumber[0] = player_or_null(num(arg[1]));
            PlayerPlayersByNumber[1] = player_or_null(num(arg[2]));
        } else if (!strcmp(op, "pbi")) {
            PlayerPlayersByIndex[0] = player_or_null(num(arg[1]));
            PlayerPlayersByIndex[1] = player_or_null(num(arg[2]));
        } else if (!strcmp(op, "cti")) {
            int32_t k = (int32_t)num(arg[1]);

            CurrentTrackInfo = k < 0 ? NULL : &tracks[k];
        } else if (!strcmp(op, "egs")) {
            egs.Zeroed[2] = (int32_t)num(arg[1]);
            egs.Zeroed[3] = (int32_t)num(arg[2]);
            egs.Zeroed[6] = (int32_t)num(arg[3]);
        } else if (!strcmp(op, "tourney") || !strcmp(op, "reward")
                   || !strcmp(op, "unlocked") || !strcmp(op, "btc1")
                   || !strcmp(op, "btc2")) {
            EndGameScreenCtor ctor =
                op[0] == 't' ? tourney_standings_construct
                : op[0] == 'r' ? event_reward_construct
                : op[0] == 'u' ? events_unlocked_construct
                : op[3] == '1' ? btc_results_1p_construct
                : btc_results_2p_construct;
            void *m = malloc(sizeof(EndGameMenusBase));

            memset(m, 0xcd, sizeof(EndGameMenusBase));
            block_add(m);
            screen = ctor(m, (uint32_t)num(arg[1]), NULL);
            dump();
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
        } else if (!strcmp(op, "lang")) {
            printf("  langid %#x\n", (unsigned)event_reward_lang_id());
        } else if (!strcmp(op, "rank")) {
            printf("  userrank %d\n", (int)event_reward_user_rank(0));
        } else if (!strcmp(op, "fmt")) {
            char buf[256];

            event_reward_format(buf, (int32_t)num(arg[1]));
            printf("  fmt [%.255s]\n", buf);
        } else {
            fprintf(stderr, "bad op %s\n", op);
            return 3;
        }
        fflush(stdout);
    }
    fclose(sc);
    return 0;
}
