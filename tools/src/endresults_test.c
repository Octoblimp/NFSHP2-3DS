// Drives endresults.c for tools/endresults_check.py. A script of ops, one
// per line, fields split on '|':
//
//   lang|L             the language
//   time|T             RealTimer
//   game|G             Fred.GameType
//   units|U            Fred.DisplayOptionsData.Units
//   np|N               Fred.NumPlayerCars
//   rp|TYPE|P2P|LAPS|COPS|NEW784  TheRaceParameters' RaceType,
//                      Point2Point, NumLapsInRace, nMaxCops and New784
//   ev|NUMBER|REWARDS  TheRaceEventFields' Number and NumRewards
//   rew|I|TYPE|EARNED  reward I's first byte, and what 0x00200b30 answers
//   ts|NUM|POINTS|TASK TransientStats' NumStats, PointsRewardEarned and
//                      TaskRewardEarned
//   row|I|POS|UNIQUE|REASON|TIME|LAP|PTS|TOTAL|BONUS|TICKETS|TOP|AVG
//                      TransientStats' row I; TOP and AVG are float bits
//   chr|I|NAME         character I's name
//   drv|I|UNIQUE|TYPE|RIDE|CHAR  driver I; CHAR -1 has no CharacterInfo
//   car|N|D            GetCarByNumber(N) answers a car driven by driver D;
//                      D -1 forgets N
//   player|UNIQUE|NUM|NAME  the car GetCarByDriverNumber(UNIQUE) answers,
//                      with its player's number and name
//   ct|I|USAGE|INIT|COP  car type I's UsageType, InitialLockStatus and
//                      BeACopLockStatus
//   unl|I|G|V          IsCarUnlocked(I, G) answers V
//   prs|I|V            Fred.PointsRewardStates[I]
//   egs|ROOT|Z0|Z1     the screens' list: AtRoot's answer and the two
//                      speech flags
//   not6|V, tourney|V, rmenu|V  the end game's tests' answers
//   miss|ID            GetTranslatedString(ID) has no string
//   trs|MODE           GetTranslatedString(const char *): 0 the text
//                      itself, 1 the text after an X
//   rr, pr, tr         a Race Results, Points Rewards or Task Rewards
//                      screen made, the screen hash given after
//   scroll|MSG, tick, render  the screen's vtable's Scroll, Tick, Render
//   dtor|FLAGS         its destructor
//   dump               the screen and the speech flags
//   count|COP, clear   the reward screens' car count, and it emptied
//   nre                GetNumPointsRewardsEarned
//   task|T             the task's blurb, reward and game type
//   avail              the car counts
//   ptimer|PACKED|FLAGS  0x001dc500's text
//
// Every call out of endresults.c prints what it was asked, as the model's
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
#include "endgame.h"
#include "endresults.h"
#include "flailer.h"
#include "fred.h"
#include "fredend.h"
#include "fredrace.h"
#include "player.h"
#include "race.h"
#include "realtime.h"
#include "startrace.h"
#include "world.h"

#define MAX_TYPES   64
#define MAX_DRIVERS 16
#define MAX_CARS    16
#define MAX_MISSING 16
#define MAX_BLOCKS  4096
#define MAX_UNL     64
#define MAX_REWARDS 16

// What endresults.c reads.
FrontendDatabase Fred;
RaceParameters TheRaceParameters;
RaceEventFields TheRaceEventFields;
World *pCurrentWorld;
int32_t RealTimer;
const CarTypeInfo *CarTypeInfoArray;
EndGameScreens *pEndGameScreens;
int32_t (*gIsCarUnlockedFn)(int32_t carType, int32_t gameType);
int32_t (*gCurrLanguageFn)(void);
const char *(*gStartRaceTranslateFn)(int32_t id);
const char *(*gStartRaceTranslateStringFn)(const char *s);
const bVector4 PlayerTextColors[2] = {
    { 134.0f, 96.0f, 48.0f, 128.0f },
    { 0.0f, 128.0f, 0.0f, 128.0f },
};
const bVector4 DefaultTextColor = { 128.0f, 128.0f, 128.0f, 128.0f };

static CarTypeInfo ctinfo[MAX_TYPES];
static CarSpecs specs[MAX_TYPES];
static DriverInfo drivers[MAX_DRIVERS];
static CharacterInfo chars[8];
static Car cars[MAX_CARS];
static int32_t carNumber[MAX_CARS];
static int numCars;
static Car playerCars[8];
static Player players[8];
static int32_t playerUnique[8];
static int numPlayerCars;
static EndGameScreens egs;
static int32_t atRoot, not6, tourney, rmenu;
static int32_t language;
static uint32_t missing[MAX_MISSING];
static int numMissing;
static int trsMode;
static struct { int32_t car, game, v; } unl[MAX_UNL];
static int numUnl;
static uint8_t rewardType[MAX_REWARDS];
static int32_t rewardEarned[MAX_REWARDS];
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

// A pointer as the dump spells it: #N for a block, "head" for the list
// head, else its low 32 bits.
static const char *ptr_name(const void *p, const void *head)
{
    static char ring[8][24];
    static int at;
    char *s = ring[at++ & 7];
    int i;

    if (p == head) {
        snprintf(s, 24, "head");
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

static void *new_block(size_t size)
{
    void *p = malloc(size);

    memset(p, 0xcd, size);
    block_add(p);
    return p;
}

// ------------------------------------------------------------ the stubs

const CarTypeInfo *cartypeinfo_get(int32_t carType)
{
    return &CarTypeInfoArray[carType & (MAX_TYPES - 1)];
}

struct Car *world_get_car_by_number(const World *w, int32_t n)
{
    int i;

    (void)w;
    printf("  carnum %d\n", (int)n);
    for (i = 0; i < numCars; i++)
        if (carNumber[i] == n)
            return &cars[i];
    return NULL;
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

TransientStatsElement *transient_stats_get_driver(TransientStats *ts,
                                                  int32_t driver)
{
    int32_t i;

    for (i = 0; i < ts->NumStats; i++)
        if (ts->Stats[i].UniqueDriveNumber == driver)
            return &ts->Stats[i];
    return NULL;
}

int32_t fred_use_the_race_event(const FrontendDatabase *f)
{
    int32_t t = f->GameType;

    return t == 4 || (t >= 8 && t < 10);
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

int32_t endgame_screens_at_root(const EndGameScreens *s)
{
    (void)s;
    printf("  atroot\n");
    return atRoot;
}

int32_t endgame_is_not_game_type_6(void)
{
    printf("  not6\n");
    return not6;
}

int32_t endgame_should_see_tourney(void)
{
    printf("  tourney\n");
    return tourney;
}

int32_t endgame_should_see_reward_menu(void)
{
    printf("  rmenu\n");
    return rmenu;
}

void set_track_name_and_race_number(uint32_t screen, uint32_t trackObj,
                                    uint32_t raceObj, int32_t add)
{
    printf("  tname %08x %08x %08x %d\n", screen, trackObj, raceObj,
           (int)add);
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

void flailer_clear_text_format_option(uint32_t screen, uint32_t object,
                                      uint32_t f)
{
    printf("  clropt %08x %08x %d\n", screen, object, (int)f);
}

void flailer_set_alpha(uint32_t screen, uint32_t object, int32_t a)
{
    printf("  alpha %08x %08x %d\n", screen, object, (int)a);
}

void flailer_set_group_visibility(uint32_t screen, uint32_t group,
                                  int32_t v)
{
    printf("  gvis %08x %08x %d\n", screen, group, (int)v);
}

void flailer_set_group_alpha(uint32_t screen, uint32_t group, int32_t a)
{
    printf("  galpha %08x %08x %d\n", screen, group, (int)a);
}

float flailer_get_top_left_x(uint32_t screen, uint32_t object)
{
    printf("  topx %08x %08x\n", screen, object);
    return 12.5f;
}

float flailer_get_top_left_y(uint32_t screen, uint32_t object)
{
    printf("  topy %08x %08x\n", screen, object);
    return -7.25f;
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

// The two nodes are wider on a 64-bit host; they print as retail's sizes.
void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *p = malloc((size_t)size);
    int shown = size;

    if ((size_t)size == sizeof(tStatsColumn))
        shown = 76;
    else if ((size_t)size == sizeof(tPointsThingy))
        shown = 16;
    memset(p, 0xcd, (size_t)size);
    printf("  malloc %s %d %d %d #%d\n", name, shown, flags, pool,
           block_add(p));
    return p;
}

void bFree(void *p)
{
    printf("  free %s\n", ptr_name(p, NULL));
}

static void render_text(uint32_t screen, uint32_t group, const char *str)
{
    printf("  render %08x %08x [%s]\n", screen, group, str);
}

static void reward_car_speech(int32_t car)
{
    printf("  carspeech %d\n", (int)car);
}

static void points_screen_speech(int32_t bonus)
{
    printf("  ptspeech %d\n", (int)bonus);
}

static int32_t reward_type(int32_t i)
{
    return rewardType[i & (MAX_REWARDS - 1)];
}

static int32_t reward_earned(int32_t i)
{
    printf("  earned %d 0\n", (int)i);
    return rewardEarned[i & (MAX_REWARDS - 1)];
}

static int32_t is_car_unlocked(int32_t car, int32_t game)
{
    int i;

    printf("  unl %d %d\n", (int)car, (int)game);
    for (i = 0; i < numUnl; i++)
        if (unl[i].car == car && unl[i].game == game)
            return unl[i].v;
    return 0;
}

static int32_t curr_language(void)
{
    return language;
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
    switch (id) {
    case RR_LANG_EVENT_RESULTS:             return "E%dR";
    case END_REWARD_LANG_POINTS_BLURB:      return "P[%s]";
    case END_REWARD_LANG_POINTS_BLURB_LAST: return "L[%s]";
    case END_REWARD_LANG_COUNT:             return "C%d/%d";
    case END_REWARD_LANG_COUNT_COP:         return "K%d/%d";
    }
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

// ---------------------------------------------------------------- the dump

static const char *vt_name(const EndGameMenusVTable *vt)
{
    if (vt == &kRaceResultsVTable)
        return "RR";
    if (vt == &kPointsRewardsVTable)
        return "PR";
    if (vt == &kTaskRewardsVTable)
        return "TR";
    if (vt == &kEndGameMenusBaseVTable)
        return "BASE";
    return "?";
}

static void dump(void)
{
    printf("  egs %d %d\n", (int)egs.Zeroed[0], (int)egs.Zeroed[1]);
    if (screen == NULL) {
        printf("  screen none\n");
        return;
    }
    printf("  screen %s %08x\n", vt_name(screen->vt), screen->ScreenHash);
    if (screen->vt == &kRaceResultsVTable) {
        const RaceResultsScreen *s = (const RaceResultsScreen *)screen;
        const tSlideshowStats *ss = &s->Stats;
        const tPointsResults *p = &s->Points;
        const bNode *n;
        int k;

        printf("  ss %08x cur %s anim %d refresh %08x\n", ss->ScreenHash,
               ptr_name(ss->CurrentColumn, &ss->Columns),
               (int)ss->AnimTimer, (unsigned)ss->Refresh);
        for (n = ss->Columns.next; n != &ss->Columns; n = n->next) {
            const tStatsColumn *c = (const tStatsColumn *)n;

            printf("  col %s %#x", ptr_name(c, NULL), (unsigned)c->Title);
            for (k = 0; k < RACE_RESULTS_ROWS; k++)
                printf(" %08x/%d", (unsigned)c->Data[k].Value.Int,
                       (int)c->Data[k].Type);
            printf("\n");
        }
        printf("  pts %08x timer %d cur %s tl %08x %08x\n", p->ScreenHash,
               (int)p->Timer, ptr_name(p->Current, &p->Lines),
               fbits(p->TopLeftX), fbits(p->TopLeftY));
        for (n = p->Lines.next; n != &p->Lines; n = n->next) {
            const tPointsThingy *l = (const tPointsThingy *)n;

            printf("  line %s %#x %d\n", ptr_name(l, NULL),
                   (unsigned)l->Label, (int)l->Points);
        }
    }
}

int main(int argc, char **argv)
{
    static char line[512];
    FILE *sc;
    int i;

    if (argc < 2) {
        fprintf(stderr, "usage: endresults_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (sc == NULL)
        return 2;

    for (i = 0; i < MAX_TYPES; i++) {
        specs[i].FullName = 0x40000 + i;
        ctinfo[i].pCarSpecs = &specs[i];
    }
    for (i = 0; i < 8; i++)
        playerCars[i].pPlayer = &players[i];
    CarTypeInfoArray = ctinfo;
    pEndGameScreens = &egs;
    gIsCarUnlockedFn = is_car_unlocked;
    gCurrLanguageFn = curr_language;
    gStartRaceTranslateFn = translate;
    gStartRaceTranslateStringFn = translate_string;
    gRenderTextIntoGroupFn = render_text;
    gRewardCarSpeechFn = reward_car_speech;
    gPointsScreenSpeechFn = points_screen_speech;
    gRaceEventRewardTypeFn = reward_type;
    gRaceEventRewardEarnedFn = reward_earned;

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
        if (!strcmp(op, "lang")) {
            language = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "time")) {
            RealTimer = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "game")) {
            Fred.GameType = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "units")) {
            Fred.DisplayOptionsData.Units = (int8_t)num(arg[1]);
        } else if (!strcmp(op, "np")) {
            Fred.NumPlayerCars = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "rp")) {
            TheRaceParameters.RaceType = (int32_t)num(arg[1]);
            TheRaceParameters.Point2Point = (int32_t)num(arg[2]);
            TheRaceParameters.NumLapsInRace = (int32_t)num(arg[3]);
            TheRaceParameters.nMaxCops = (int32_t)num(arg[4]);
            TheRaceParameters.New784 = (int32_t)num(arg[5]);
        } else if (!strcmp(op, "ev")) {
            TheRaceEventFields.Number = (int16_t)num(arg[1]);
            TheRaceEventFields.NumRewards = (int16_t)num(arg[2]);
        } else if (!strcmp(op, "rew")) {
            i = (int)num(arg[1]);
            rewardType[i] = (uint8_t)num(arg[2]);
            rewardEarned[i] = (int32_t)num(arg[3]);
        } else if (!strcmp(op, "ts")) {
            Fred.TransientStatsTable.NumStats = (int32_t)num(arg[1]);
            Fred.TransientStatsTable.PointsRewardEarned = (int32_t)num(arg[2]);
            Fred.TransientStatsTable.TaskRewardEarned = (int32_t)num(arg[3]);
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
            e->FinishBonus = (int32_t)num(arg[9]);
            e->NumTickets = (int32_t)num(arg[10]);
            e->TopSpeed = bitsf((uint32_t)num(arg[11]));
            e->AverageSpeed = bitsf((uint32_t)num(arg[12]));
        } else if (!strcmp(op, "chr")) {
            snprintf(chars[num(arg[1])].CharacterName,
                     sizeof chars[0].CharacterName, "%s", arg[2]);
        } else if (!strcmp(op, "drv")) {
            DriverInfo *d = &drivers[num(arg[1])];
            int32_t c = (int32_t)num(arg[5]);

            d->UniqueDriverNumber = (int8_t)num(arg[2]);
            d->TheDriverType = (DriverType)num(arg[3]);
            d->CurrentRideInfo.Type = (int32_t)num(arg[4]);
            d->pCharacterInfo = c < 0 ? NULL : &chars[c];
        } else if (!strcmp(op, "car")) {
            int32_t cn = (int32_t)num(arg[1]);
            int32_t dn = (int32_t)num(arg[2]);

            for (i = 0; i < numCars && carNumber[i] != cn; i++)
                ;
            if (i == numCars)
                carNumber[numCars++] = cn;
            if (dn < 0)
                carNumber[i] = 0x7fffffff;
            else
                cars[i].MyDriver = &drivers[dn];
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
        } else if (!strcmp(op, "ct")) {
            CarTypeInfo *c = &ctinfo[num(arg[1])];

            c->UsageType = (int32_t)num(arg[2]);
            c->InitialLockStatus = (int32_t)num(arg[3]);
            c->BeACopLockStatus = (int32_t)num(arg[4]);
        } else if (!strcmp(op, "unl")) {
            int32_t c = (int32_t)num(arg[1]), g = (int32_t)num(arg[2]);

            for (i = 0; i < numUnl && !(unl[i].car == c && unl[i].game == g);
                 i++)
                ;
            if (i == numUnl)
                numUnl++;
            unl[i].car = c;
            unl[i].game = g;
            unl[i].v = (int32_t)num(arg[3]);
        } else if (!strcmp(op, "prs")) {
            Fred.PointsRewardStates[num(arg[1])] = (int32_t)num(arg[2]);
        } else if (!strcmp(op, "egs")) {
            atRoot = (int32_t)num(arg[1]);
            egs.Zeroed[0] = (int32_t)num(arg[2]);
            egs.Zeroed[1] = (int32_t)num(arg[3]);
        } else if (!strcmp(op, "not6")) {
            not6 = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "tourney")) {
            tourney = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "rmenu")) {
            rmenu = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "miss")) {
            missing[numMissing++] = (uint32_t)num(arg[1]);
        } else if (!strcmp(op, "trs")) {
            trsMode = (int)num(arg[1]);
        } else if (!strcmp(op, "rr")) {
            screen = race_results_construct(
                new_block(sizeof(RaceResultsScreen)), (uint32_t)num(arg[1]),
                NULL);
        } else if (!strcmp(op, "pr")) {
            screen = points_rewards_construct(
                new_block(sizeof(EndGameMenusBase)), (uint32_t)num(arg[1]),
                NULL);
        } else if (!strcmp(op, "tr")) {
            screen = task_rewards_construct(
                new_block(sizeof(EndGameMenusBase)), (uint32_t)num(arg[1]),
                NULL);
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
        } else if (!strcmp(op, "count")) {
            end_reward_show_car_count((uint32_t)num(arg[1]),
                                      (int32_t)num(arg[2]));
        } else if (!strcmp(op, "clear")) {
            end_reward_clear_car_count((uint32_t)num(arg[1]));
        } else if (!strcmp(op, "nre")) {
            printf("  nre %d\n", (int)nfs_get_num_points_rewards_earned());
        } else if (!strcmp(op, "task")) {
            int32_t tn = (int32_t)num(arg[1]);
            int32_t id = nfs_get_language_id_for_task_reward(tn);
            int32_t rw = nfs_get_reward_for_task(tn);
            int32_t gt = nfs_get_unlocked_game_type_for_task(tn);

            printf("  task %#x %d %d\n", (unsigned)id, (int)rw, (int)gt);
        } else if (!strcmp(op, "avail")) {
            int32_t a = end_reward_num_available_cars();
            int32_t u0 = end_reward_num_cars_of_usage(0);
            int32_t u1 = end_reward_num_cars_of_usage(1);
            int32_t ca = end_reward_num_cop_cars_available();
            int32_t cc = end_reward_num_cop_cars();

            printf("  avail %d %d %d %d %d\n", (int)a, (int)u0, (int)u1,
                   (int)ca, (int)cc);
        } else if (!strcmp(op, "ptimer")) {
            char buf[64];
            Timer tm;

            tm.PackedTime = (uint32_t)num(arg[1]);
            end_game_print_timer(buf, tm, (int32_t)num(arg[2]));
            printf("  ptimer [%s]\n", buf);
        } else {
            fprintf(stderr, "bad op %s\n", op);
            return 3;
        }
        fflush(stdout);
    }
    fclose(sc);
    return 0;
}
