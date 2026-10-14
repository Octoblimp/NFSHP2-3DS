// The debug menu's two screens (debugmenu.h), lists of settings and actions
// in Be The Cop Setup's look. Debug Menu has the save's rows and leads to
// Debug Race, whose rows set up a race and start it.
//
// Each screen has MENUITEM_1..n, and bmenu moves between them. Debug
// Race's list is longer than its seven, so the callback scrolls it: PAD_UP
// on the first row and PAD_DOWN on the last come here before bmenu moves
// (bmenu.c, menu_joy), and the callback scrolls the rows under the
// highlight, or wraps to the other end, and claims the event, which leaves
// bmenu silent -- so the sound is played here. LEFT and RIGHT change the
// current row's value, and A acts on it.
//
// Whatever the rows change in the save (the NFS points, the career, the
// rewards) is held against a copy taken on the way in. Leaving with B, or
// starting a race, while they differ asks first: Yes saves through the
// Autosave screen, the end of a race's, No puts the copy back, and B stays.

#include "debugmenu.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "bpopup.h"
#include "bscreens.h"
#include "bsetup.h"
#include "cartypeinfo.h"
#include "eventtree.h"
#include "fesound.h"
#include "flailer.h"
#include "fred.h"
#include "fredrace.h"
#include "nfsrewards.h"
#include "race.h"
#include "raceparams.h"
#include "track.h"

// Be The Cop Setup's rows: its masks are all kept (debugmenu_patch.c).
#define MAX_SLOTS 7

// The screens' objects: Be The Cop Setup's.
#define LABEL(n) BSCR_ITEM_MENUITEM(n)
#define VALUE(n) (0x69a2c756u + (uint32_t)(n))   // LINE_n

// Where a row's text may reach before it is squeezed: the labels stop
// short of the left arrow, the values between the two arrows.
#define LABEL_MAX_W 228.0f
#define VALUE_MAX_W 170.0f

#define GAME_TYPE_EXPRESS 2   // quickrace.c's

// The save prompt: memcard.c's popup, titled "Save" (150000), with its Yes
// and No (150103, 150104).
#define LANG_SAVE 0x249f0
#define LANG_YES  0x24a57
#define LANG_NO   0x24a58

// The screen the end of a race saves on (main.c's kScreens).
#define AUTOSAVE_SCREEN "Autosave"

#define NFS_POINTS_MAX 99990000

enum {
    // Debug Menu's.
    ROW_DEBUG_RACE,
    ROW_POINTS,
    ROW_FULL,
    ROW_UNLOCK,
    ROW_LOCK,
    // Debug Race's.
    ROW_START,
    ROW_MODE,
    ROW_TRACK,
    ROW_TOD,
    ROW_DIRECTION,
    ROW_CAR,
    ROW_COLOUR,
    ROW_OPPONENTS,
    ROW_LAPS,
    ROW_TRAFFIC,
    ROW_DIFFICULTY,
    ROW_GEARBOX,
    NUM_ROWS
};

enum { MODE_HOT_PURSUIT, MODE_SINGLE_RACE, MODE_BE_THE_COP, NUM_MODES };

// No apostrophes: the bottom screen's font may not have one.
static const struct {
    const char* label;
    const char* help;
} kRows[NUM_ROWS] = {
    { "Start Debug Race",
      "Set up a race on any track with any car, then start it." },
    { "NFS Points",
      "Left and Right change your NFS points by 10,000, A adds 100,000. "
      "Their rewards come at the end of the next race." },
    { "Set Save to 100%",
      "Press A to win every event of both careers and earn every task "
      "and points reward. Your NFS points stay as they are." },
    { "Unlock Everything",
      "Press A to unlock every event, car and track. Results you already "
      "have are kept." },
    { "Lock Everything",
      "Press A to lock everything again, as on a new profile. Your NFS "
      "points stay as they are." },
    { "Start Race",
      "Press A to start a race with the settings below." },
    { "Mode",
      "Hot Pursuit races with the cops, Single Race without them. "
      "In Be The Cop you drive the cop car." },
    { "Track",
      "Any track, locked or not. Be The Cop has no point to point tracks." },
    { "Time Of Day", "The times of day this track has." },
    { "Direction", "Forwards or backwards." },
    { "Car",
      "Any car, locked or not. In Be The Cop, the cop cars." },
    { "Colour", "The colours this car comes in." },
    { "Opponents",
      "How many cars you race, or chase in Be The Cop. "
      "Eight cars at most take part: more racers, fewer cops." },
    { "Laps",
      "Laps in the race. A point to point track is run once, "
      "and Be The Cop has a clock instead." },
    { "Traffic", "None, light, medium or heavy traffic." },
    { "Difficulty", "How good the racers and the cops are." },
    { "Gearbox", "Automatic or manual." },
};

static const int kMenuRows[] = {
    ROW_DEBUG_RACE, ROW_POINTS, ROW_FULL, ROW_UNLOCK, ROW_LOCK,
};
static const int kRaceRows[] = {
    ROW_START, ROW_MODE, ROW_TRACK, ROW_TOD, ROW_DIRECTION, ROW_CAR,
    ROW_COLOUR, ROW_OPPONENTS, ROW_LAPS, ROW_TRAFFIC, ROW_DIFFICULTY,
    ROW_GEARBOX,
};

// A screen's list: its rows, how many show at once, the first shown and
// the current, both indices into `rows`.
typedef struct {
    uint32_t   screen;
    const int* rows;
    int        numRows;
    int        numSlots;
    int        top, cur;
} Page;

static Page sMenu = { DEBUGMENU_SCREEN, kMenuRows,
                      (int)(sizeof kMenuRows / sizeof kMenuRows[0]),
                      DEBUGMENU_ROWS, 0, 0 };
static Page sRace = { DEBUGMENU_RACE_SCREEN, kRaceRows,
                      (int)(sizeof kRaceRows / sizeof kRaceRows[0]),
                      MAX_SLOTS, 0, 0 };

static const char* const kModeNames[NUM_MODES] = {
    "Hot Pursuit", "Single Race", "Be The Cop",
};
static const int kModeOpponents[NUM_MODES] = { 3, 7, 4 };
static const char* const kTrafficNames[4] = {
    "None", "Light", "Medium", "Heavy",
};
// The setup screens' four densities (fredrace.c, kSetupTrafficDensity).
static const float kTrafficDensity[4] = { 0.0f, 0.33f, 0.667f, 1.0f };
// Select Track's time of day and difficulty names (btracksel.c), with
// English for a missing row.
static const int32_t kTODLang[5] = { 0xd6e0, 0xd6e1, 0xd6e2, 0xd6e3, 0xd70a };
static const char* const kTODNames[5] = {
    "Day", "Overcast", "Sunset", "Night", "Dawn",
};
static const int32_t kDifficultyLang[3] = { 0xd6dc, 0xd6dd, 0xd6de };
static const char* const kDifficultyNames[3] = {
    "Beginner", "Advanced", "Expert",
};

#define MAX_LIST 64

typedef struct {
    int mode;
    int track;        // the base track: its own SameAsTrackNumber
    int tod;          // a TimeOfDay the base track has
    int backwards;
    int car;          // CarType
    int skin;         // an index into the car's skins
    int opponents;
    int laps;
    int traffic;
    int difficulty;
    int manual;
} Settings;

// What of Fred the rows change: the two careers' events (the Ultimate's
// state is in the first), the tasks' and the points' rewards, and the
// players, whose car list is made from those and who hold the points.
typedef struct {
    uint8_t            champ[256];
    uint8_t            hotPursuit[256];
    int32_t            tasks[10];
    int32_t            pointsRewards[18];
    FrontendPlayerInfo players[2];
} SaveCopy;

static DebugMenuHooks sHooks;
static Settings       sSet;
static int            sHaveSet;
static char           sDone[NUM_ROWS];  // an action row done this visit
static int            sVisit;           // between entering and leaving
static SaveCopy       sCopy;            // the save as the visit found it

// What the answer to the save prompt goes on to.
enum { AFTER_LEAVE, AFTER_RACE };
enum { ANSWER_STAY, ANSWER_DISCARD, ANSWER_SAVE };
static int        sAfter;
static uint32_t   sAsking;  // the screen hidden under the prompt
static BGameFlow* sFlow;    // for the Autosave screen's callback

void debugmenu_init(const DebugMenuHooks* hooks)
{
    memset(&sHooks, 0, sizeof sHooks);
    if (hooks) sHooks = *hooks;
}

static void say(const char* fmt, ...)
{
    char    line[128];
    va_list ap;
    if (!sHooks.log) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    sHooks.log(sHooks.user, line);
}

static const char* tr(int32_t id, const char* fallback)
{
    const char* s = gFredTranslateFn ? gFredTranslateFn(id) : NULL;
    return s && s[0] ? s : fallback;
}

static int32_t lang(void)
{
    return gCurrLanguageFn ? gCurrLanguageFn() : 0;
}

static int32_t* points(void)
{
    return &Fred.FrontendPlayers[0].AccumulatedPoints;
}

// ------------------------------------------------------------ the lists

// The base tracks, in number order: each track that is its own
// SameAsTrackNumber. Be The Cop runs no point to point track
// (btracksel.c, isTrackUnavailable).
static int baseTracks(int* out, int mode)
{
    int n = 0;
    for (int i = 1; i <= HighestTrackNumber && n < MAX_LIST; i++) {
        const TrackInfo* ti = track_get_info(i);
        if (!ti || !ti->IsValid || ti->SameAsTrackNumber != ti->TrackNumber)
            continue;
        if (mode == MODE_BE_THE_COP && ti->Point2Point) continue;
        out[n++] = ti->TrackNumber;
    }
    return n;
}

// The track to load for a base track at a time of day
// (CalculateTrackNumberToLoad), or the base track.
static int trackVariant(int base, int tod)
{
    for (int i = 1; i <= HighestTrackNumber; i++) {
        const TrackInfo* ti = track_get_info(i);
        if (ti && ti->IsValid && ti->SameAsTrackNumber == base
            && ti->TimeOfDay == tod)
            return ti->TrackNumber;
    }
    return base;
}

// The times of day a base track has, in TimeOfDay order.
static int trackTODs(int base, int* out)
{
    int n = 0;
    for (int tod = 0; tod < 5; tod++) {
        const TrackInfo* ti = track_get_info(trackVariant(base, tod));
        if (ti && ti->TimeOfDay == tod) out[n++] = tod;
    }
    return n;
}

// The cars a mode drives: racers, or the cops in Be The Cop, with geometry
// and a skin, as GenerateRandomRideInfo's iterator has them (fredrace.c).
static int carList(int* out, int mode)
{
    int usage = mode == MODE_BE_THE_COP ? CAR_USAGE_TYPE_COP
                                        : CAR_USAGE_TYPE_RACING;
    int n     = 0;
    if (!CarTypeInfoArray) return 0;
    for (int i = 0; i < 64 && n < MAX_LIST; i++) {
        const CarTypeInfo* ct = cartypeinfo_get(i);
        if (!ct || ct->UsageType != usage || ct->GeometryFilename[0] == 0)
            continue;
        if (cartypeinfo_get_num_skins(ct) <= 0) continue;
        out[n++] = i;
    }
    return n;
}

static int indexOf(const int* list, int n, int v)
{
    for (int i = 0; i < n; i++)
        if (list[i] == v) return i;
    return -1;
}

static int wrapStep(int v, int dir, int lo, int hi)
{
    v += dir;
    if (v > hi) v = lo;
    if (v < lo) v = hi;
    return v;
}

// Step through a list from the value `cur`, or start at its head.
static int listStep(const int* list, int n, int cur, int dir)
{
    int i = indexOf(list, n, cur);
    if (n <= 0) return cur;
    if (i < 0) return list[0];
    return list[wrapStep(i, dir, 0, n - 1)];
}

static int isPointToPoint(void)
{
    const TrackInfo* ti = track_get_info(trackVariant(sSet.track, sSet.tod));
    return ti && ti->Point2Point;
}

// Whatever the mode no longer allows, put back in range.
static void validate(void)
{
    int list[MAX_LIST], n;

    n = baseTracks(list, sSet.mode);
    if (n > 0 && indexOf(list, n, sSet.track) < 0) sSet.track = list[0];
    n = trackTODs(sSet.track, list);
    if (n > 0 && indexOf(list, n, sSet.tod) < 0) sSet.tod = list[0];
    n = carList(list, sSet.mode);
    if (n > 0 && indexOf(list, n, sSet.car) < 0) {
        sSet.car  = list[0];
        sSet.skin = 0;
    }
    if (sSet.opponents < (sSet.mode == MODE_BE_THE_COP ? 1 : 0))
        sSet.opponents = 1;
}

static void defaults(void)
{
    memset(&sSet, 0, sizeof sSet);
    sSet.mode       = MODE_HOT_PURSUIT;
    sSet.track      = 11;
    sSet.opponents  = kModeOpponents[sSet.mode];
    sSet.laps       = 2;
    sSet.traffic    = 1;
    sSet.difficulty = 1;
    sSet.car        = -1;
    validate();
}

// --------------------------------------------------------- the save copy

static void takeCopy(void)
{
    memcpy(sCopy.champ, Fred.ChampionshipState, sizeof sCopy.champ);
    memcpy(sCopy.hotPursuit, Fred.HotPursuitState, sizeof sCopy.hotPursuit);
    memcpy(sCopy.tasks, Fred.TaskRewardStates, sizeof sCopy.tasks);
    memcpy(sCopy.pointsRewards, Fred.PointsRewardStates,
           sizeof sCopy.pointsRewards);
    memcpy(sCopy.players, Fred.FrontendPlayers, sizeof sCopy.players);
}

static void putCopyBack(void)
{
    memcpy(Fred.ChampionshipState, sCopy.champ, sizeof sCopy.champ);
    memcpy(Fred.HotPursuitState, sCopy.hotPursuit, sizeof sCopy.hotPursuit);
    memcpy(Fred.TaskRewardStates, sCopy.tasks, sizeof sCopy.tasks);
    memcpy(Fred.PointsRewardStates, sCopy.pointsRewards,
           sizeof sCopy.pointsRewards);
    memcpy(Fred.FrontendPlayers, sCopy.players, sizeof sCopy.players);
}

// The save differs from the copy: the players' car lists follow the rest,
// so only their points are held against it.
static int changed(void)
{
    return memcmp(sCopy.champ, Fred.ChampionshipState, sizeof sCopy.champ)
        || memcmp(sCopy.hotPursuit, Fred.HotPursuitState,
                  sizeof sCopy.hotPursuit)
        || memcmp(sCopy.tasks, Fred.TaskRewardStates, sizeof sCopy.tasks)
        || memcmp(sCopy.pointsRewards, Fred.PointsRewardStates,
                  sizeof sCopy.pointsRewards)
        || sCopy.players[0].AccumulatedPoints != *points();
}

// ------------------------------------------------------------- the rows

static int rowAt(const Page* p, int i)
{
    return i >= 0 && i < p->numRows ? p->rows[i] : -1;
}

static int rowHasValue(int row)
{
    switch (row) {
        case ROW_POINTS:
        case ROW_MODE:
        case ROW_TRACK:
        case ROW_TOD:
        case ROW_DIRECTION:
        case ROW_CAR:
        case ROW_COLOUR:
        case ROW_OPPONENTS:
        case ROW_TRAFFIC:
        case ROW_DIFFICULTY:
        case ROW_GEARBOX:
            return 1;
        case ROW_LAPS:
            return sSet.mode != MODE_BE_THE_COP && !isPointToPoint();
        default:
            return 0;
    }
}

static void valueText(int row, char* out, size_t cap)
{
    const CarTypeInfo* ct;
    const TrackInfo*   ti;
    out[0] = '\0';
    switch (row) {
        case ROW_MODE:
            snprintf(out, cap, "%s", kModeNames[sSet.mode]);
            break;
        case ROW_TRACK:
            ti = track_get_info(sSet.track);
            if (ti)
                snprintf(out, cap, "%s",
                         tr(sSet.backwards ? ti->ReverseTrackLanguageID
                                           : ti->TrackLanguageID,
                            ti->Name));
            break;
        case ROW_TOD:
            if (sSet.tod >= 0 && sSet.tod < 5)
                snprintf(out, cap, "%s",
                         tr(kTODLang[sSet.tod], kTODNames[sSet.tod]));
            break;
        case ROW_DIRECTION:
            snprintf(out, cap, "%s", sSet.backwards ? "Backwards" : "Forwards");
            break;
        case ROW_CAR:
            ct = sSet.car >= 0 ? cartypeinfo_get(sSet.car) : NULL;
            if (ct)
                snprintf(out, cap, "%s",
                         ct->pCarSpecs ? tr(ct->pCarSpecs->FullName,
                                            ct->CarTypeName)
                                       : ct->CarTypeName);
            break;
        case ROW_COLOUR: {
            const SkinInfo* si;
            int             skin;
            ct = sSet.car >= 0 ? cartypeinfo_get(sSet.car) : NULL;
            if (!ct) break;
            skin = cartypeinfo_get_skin_number(ct, sSet.skin);
            si   = cartypeinfo_get_skin_info(sSet.car, skin, 0);
            if (si && si->PrettyName[0])
                snprintf(out, cap, "%s", si->PrettyName);
            else
                snprintf(out, cap, "Colour %d", sSet.skin + 1);
            break;
        }
        case ROW_OPPONENTS:
            snprintf(out, cap, "%d", sSet.opponents);
            break;
        case ROW_LAPS:
            if (sSet.mode == MODE_BE_THE_COP)
                snprintf(out, cap, "Clock");
            else if (isPointToPoint())
                snprintf(out, cap, "1");
            else
                snprintf(out, cap, "%d", sSet.laps);
            break;
        case ROW_TRAFFIC:
            snprintf(out, cap, "%s", kTrafficNames[sSet.traffic]);
            break;
        case ROW_DIFFICULTY:
            snprintf(out, cap, "%s",
                     tr(kDifficultyLang[sSet.difficulty],
                        kDifficultyNames[sSet.difficulty]));
            break;
        case ROW_GEARBOX:
            snprintf(out, cap, "%s", sSet.manual ? "Manual" : "Automatic");
            break;
        case ROW_POINTS:
            nfs_format_points(out, (int)cap, *points(), lang());
            break;
        case ROW_FULL:
        case ROW_UNLOCK:
        case ROW_LOCK:
            if (sDone[row]) snprintf(out, cap, "Done");
            break;
        default:
            break;
    }
}

// A row's value moved by `dir`; 1 if it changed.
static int changeRow(int row, int dir)
{
    Settings old = sSet;
    int      list[MAX_LIST], n;

    switch (row) {
        case ROW_MODE:
            sSet.mode      = wrapStep(sSet.mode, dir, 0, NUM_MODES - 1);
            sSet.opponents = kModeOpponents[sSet.mode];
            validate();
            break;
        case ROW_TRACK:
            n          = baseTracks(list, sSet.mode);
            sSet.track = listStep(list, n, sSet.track, dir);
            validate();
            break;
        case ROW_TOD:
            n        = trackTODs(sSet.track, list);
            sSet.tod = listStep(list, n, sSet.tod, dir);
            break;
        case ROW_DIRECTION:
            sSet.backwards = !sSet.backwards;
            break;
        case ROW_CAR:
            n        = carList(list, sSet.mode);
            sSet.car = listStep(list, n, sSet.car, dir);
            if (sSet.car != old.car) sSet.skin = 0;
            break;
        case ROW_COLOUR: {
            const CarTypeInfo* ct =
                sSet.car >= 0 ? cartypeinfo_get(sSet.car) : NULL;
            n = ct ? cartypeinfo_get_num_skins(ct) : 0;
            if (n > 1) sSet.skin = wrapStep(sSet.skin, dir, 0, n - 1);
            break;
        }
        case ROW_OPPONENTS:
            sSet.opponents =
                wrapStep(sSet.opponents, dir,
                         sSet.mode == MODE_BE_THE_COP ? 1 : 0, 7);
            break;
        case ROW_LAPS:
            if (rowHasValue(ROW_LAPS))
                sSet.laps = wrapStep(sSet.laps, dir, 1, 10);
            break;
        case ROW_TRAFFIC:
            sSet.traffic = wrapStep(sSet.traffic, dir, 0, 3);
            break;
        case ROW_DIFFICULTY:
            sSet.difficulty = wrapStep(sSet.difficulty, dir, 0, 2);
            break;
        case ROW_GEARBOX:
            sSet.manual = !sSet.manual;
            break;
        case ROW_POINTS: {
            int32_t p = *points() + dir * 10000;
            if (p < 0) p = 0;
            if (p > NFS_POINTS_MAX) p = NFS_POINTS_MAX;
            if (p == *points()) return 0;
            *points() = p;
            say("points %d", (int)p);
            return 1;
        }
        default:
            return 0;
    }
    return memcmp(&old, &sSet, sizeof sSet) != 0;
}

// --------------------------------------------------------- the display

// A text's ScaleX back to 1, then down to fit `maxW` if it is wider.
static void fitWidth(const Page* p, uint32_t object, float maxW)
{
    int32_t w;
    flailer_set_scale_x(p->screen, object, 1.0f);
    w = flailer_get_width(p->screen, object);
    if ((float)w > maxW && w > 0) {
        float s = maxW / (float)w;
        flailer_set_scale_x(p->screen, object, s < 0.5f ? 0.5f : s);
    }
}

static void showRows(const Page* p)
{
    char value[64];
    for (int k = 0; k < p->numSlots; k++) {
        int row = rowAt(p, p->top + k);
        if (row < 0) {
            flailer_printf(p->screen, LABEL(k + 1), "%s", "");
            flailer_printf(p->screen, VALUE(k + 1), "%s", "");
            continue;
        }
        flailer_printf(p->screen, LABEL(k + 1), "%s", kRows[row].label);
        fitWidth(p, LABEL(k + 1), LABEL_MAX_W);
        valueText(row, value, sizeof value);
        flailer_printf(p->screen, VALUE(k + 1), "%s", value);
        fitWidth(p, VALUE(k + 1), VALUE_MAX_W);
    }
}

// What a highlight shows: every mask but the current row's (IndicatorMode
// 1's look; a screen of fewer rows keeps the rest darkened), the brackets
// round its mask (SetupHighlight: under its bottom - 3, over its top - 6),
// the arrows on its value if it has one, the scroll arrows when there are
// rows off either end, and its help line on the bottom screen.
static void showHighlight(const Page* p)
{
    int     slot = p->cur - p->top;
    int     row  = rowAt(p, p->cur);
    int32_t l = 0, t = 0, r = 0, b = 0, y;
    int     arrows = rowHasValue(row);

    for (int k = 0; k < MAX_SLOTS; k++)
        flailer_set_visibility(p->screen, BSCR_MI_MASK(k + 1),
                               k == slot ? FLAILER_OBJECT_INVISIBLE
                                         : FLAILER_OBJECT_VISIBLE);
    flailer_get_bounding_box(p->screen, BSCR_MI_MASK(slot + 1), &l, &t, &r,
                             &b);
    flailer_set_top_left_y(p->screen, BSCR_OBJ_MI_UNDERSCORE, b - 3);
    flailer_set_top_left_y(p->screen, BSCR_OBJ_MI_OVERSCORE, t - 6);

    y = flailer_get_center_y(p->screen, VALUE(slot + 1));
    flailer_set_center_y(p->screen, BSETUP_OBJ_LEFT_ARROW, y);
    flailer_set_center_y(p->screen, BSETUP_OBJ_RIGHT_ARROW, y);
    flailer_set_visibility(p->screen, BSETUP_OBJ_LEFT_ARROW, arrows);
    flailer_set_visibility(p->screen, BSETUP_OBJ_RIGHT_ARROW, arrows);

    flailer_set_visibility(p->screen, BSETUP_OBJ_UP_ARROW, p->top > 0);
    flailer_set_visibility(p->screen, BSETUP_OBJ_DOWN_ARROW,
                           p->top + p->numSlots < p->numRows);

    flailer_set_language_id(p->screen, BSCR_OBJ_SCROLLING_TEXT, 0);
    flailer_printf(p->screen, BSCR_OBJ_SCROLLING_TEXT, "%s",
                   row >= 0 ? kRows[row].help : "");
}

// ------------------------------------------------------------- actions

static void setRewards(int32_t earned)
{
    for (int i = 0; i < 10; i++) Fred.TaskRewardStates[i] = earned;
    for (int i = 0; i < 18; i++) Fred.PointsRewardStates[i] = earned;
}

// Every event of a tree whose result falls short: not passed, or a reward
// not earned. Their results are made the best, as UnlockState makes them.
static int unlockShort(EventTree* t)
{
    int n = 0;
    if (!t) return 0;
    for (int i = 0; i < t->nEvents; i++) {
        EventInfo* e       = &t->pEvents[i];
        int        missing = event_info_get_status(e, NULL) != EVENT_PASSED;
        for (int j = 0; j < e->nRewards && !missing; j++)
            missing = !event_info_reward_earned(e, j);
        if (!missing) continue;
        event_info_unlock_state(e);
        n++;
    }
    return n;
}

// Set Save to 100%: retail's UnlockEvents, which nothing on the disc calls
// (every event of both trees won, the Ultimate's too), and every task and
// points reward taken. Unlock Everything: the events that fall short only.
// Lock Everything: retail's LockEvents and the rewards cleared. Each makes
// the car lists again from that, and none touches the points.
static void act(int row)
{
    switch (row) {
        case ROW_FULL:
            unlock_events();
            setRewards(1);
            say("save set to 100%%");
            break;
        case ROW_UNLOCK: {
            int n = unlockShort(gChampionshipTree);
            n += unlockShort(gHotPursuitTree);
            setRewards(1);
            say("unlocked, %d events filled in", n);
            break;
        }
        case ROW_LOCK:
            lock_events();
            setRewards(0);
            say("locked");
            break;
        default:
            return;
    }
    fred_make_challenge_cars_available(&Fred);
    memset(sDone, 0, sizeof sDone);
    sDone[row] = 1;
}

// StartQuickRace (quickrace.c) with the choices in it, or for Be The Cop
// what its setup, car select and track select leave behind (bsetup.c's
// beACopSelect, btracksel.c's startRace).
static void startRace(BGameFlow* gf)
{
    RaceParameters*     rp  = &TheRaceParameters;
    FrontendDatabase*   f   = &Fred;
    FrontendPlayerInfo* p0  = &f->FrontendPlayers[0];
    int                 trk = trackVariant(sSet.track, sSet.tod);
    const TrackInfo*    ti  = track_get_info(trk);
    const CarTypeInfo*  ct  = cartypeinfo_get(sSet.car);
    int                 p2p = ti ? ti->Point2Point : 0;
    int                 cops;

    sVisit = 0;
    if (!ti || sSet.car < 0 || !ct) {
        say("no race: track %d car %d", trk, sSet.car);
        return;
    }
    say("race: %s, track %d, car %d", kModeNames[sSet.mode], trk, sSet.car);
    race_parameters_init_with_defaults(rp);
    bgf_stop_movie(gf);
    if (sSet.mode == MODE_BE_THE_COP) {
        cops                      = 1;
        f->MainMenuOpts[1]        = 1;
        f->GameType               = GAME_TYPE_BE_A_COP;
        f->NumPlayerCars          = 1;
        f->ChallengeScreenData[0] = 1;
        f->ChallengeScreenData[4] = sSet.difficulty;
        RaceParametersNumPlayerCars = 1;
        RaceParametersNFSRaceMode   = 1;
        fred_make_challenge_cars_available(f);
        fred_setup_race_parameters_after_race_setup(f);
        rp->NumLapsInRace = 0;
    } else {
        cops               = sSet.mode == MODE_HOT_PURSUIT;
        f->MainMenuOpts[1] = cops;
        f->GameType        = GAME_TYPE_EXPRESS;
        f->NumPlayerCars   = 1;
        rp->BoostScale[0]  = 1.0f;
        rp->BoostScale[1]  = 1.0f;
        rp->nMaxCops                = cops ? 4 : 0;
        rp->nNumTicketsBeforeArrest = cops ? 2 : 0;
        rp->TrafficOncoming         = 0.5f;
        rp->CopStrength             = sSet.difficulty;
        rp->OpponentStrength        = sSet.difficulty;
        rp->Boost                   = 1;
        rp->NumPlayerCars           = 1;
        rp->bRoadBlocks             = cops;
        rp->bSpikeStrips            = cops;
        rp->New624                  = cops;
        rp->bHelicopter             = cops;
        rp->bTickets                = cops;
        rp->nNumBeACopRoadBlocks    = 0;
        rp->nNumBeACopChoppers      = 0;
        rp->HasObjective            = 0;
        rp->sObjective[0]           = 0;
        rp->TrainingLinesEnabled    = 0;
        rp->NumLapsInRace           = p2p ? 1 : sSet.laps;
        fred_make_challenge_cars_available(f);
    }
    gf->copsOn                 = cops;
    rp->NumAICars              = sSet.opponents;
    rp->PlayerStartPosition[0] = (int8_t)(sSet.opponents + 1);
    rp->PlayerStartPosition[1] = (int8_t)(sSet.opponents + 2);
    rp->TrafficDensity         = kTrafficDensity[sSet.traffic];
    rp->RaceType               = 1;
    rp->EventTreeRace          = 0;
    rp->TrackNumber            = trk;
    rp->TrackDirection = sSet.backwards ? TRACK_DIRECTION_BACKWARD
                                        : TRACK_DIRECTION_FORWARD;
    rp->TrackTimeOfDay = ti->TimeOfDay;
    rp->Point2Point    = p2p;

    fpi_set_car_availability(p0, CAR_STATUS_AVAILABLE, sSet.car, -1, 1);
    fpi_assign_car_of_type(p0, f->GameType, sSet.car,
                           (uint32_t)cartypeinfo_get_skin_number(ct,
                                                                 sSet.skin),
                           0);
    p0->mPlayerSettings.TransmissionType = (int8_t)(sSet.manual != 0);
    if (sHooks.startRace) sHooks.startRace(sHooks.user);
}

// ---------------------------------------------------------- the prompt

static void showScreen(BGameFlow* gf, uint32_t screen, int visible)
{
    if (screen && gf->hooks.setScreenVisible)
        gf->hooks.setScreenVisible(gf->hooks.user, screen, visible);
}

// "Save your changes?" in the current screen's place, as the Pause Menu
// hides itself under its popups: the screen's callback hears the answer,
// Yes, No, or B for neither.
static void askToSave(BGameFlow* gf, const Page* p, int after)
{
    static const char kLeave[] = "Save your changes to the card?";
    static const char kRace[]  =
        "Save your changes to the card before the race?";
    BPopupConfig cfg;

    memset(&cfg, 0, sizeof cfg);
    cfg.numButtons     = 2;
    cfg.flags          = BPOPUP_HORIZONTAL | BPOPUP_CANCELABLE
                       | BPOPUP_BUTTONS_BELOW;
    cfg.parent         = gf->screen;
    cfg.screen         = BPOPUP_SCREEN_MEMCARD;
    cfg.message        = after == AFTER_RACE ? kRace : kLeave;
    cfg.button[0]      = LANG_YES;
    cfg.button[1]      = LANG_NO;
    cfg.buttonParam[0] = ANSWER_SAVE;
    cfg.buttonParam[1] = ANSWER_DISCARD;
    cfg.cancelParam    = ANSWER_STAY;
    cfg.dismissParam   = ANSWER_STAY;
    cfg.startButton    = 0;
    cfg.joyPort        = -1;
    cfg.title          = LANG_SAVE;
    sAfter             = after;
    say("asking to save");
    if (bpopup_summon(gf, &cfg) < 0) {
        say("no popup free");
        return;
    }
    sAsking = p->screen;
    showScreen(gf, sAsking, 0);
}

// The Autosave screen's end, when the save came before a race.
static void raceAfterSave(void)
{
    if (sFlow) startRace(sFlow);
}

static void answered(BGameFlow* gf, int answer)
{
    showScreen(gf, sAsking, 1);
    sAsking = 0;
    if (answer == ANSWER_STAY) {
        say("save: stay");
        return;
    }
    sVisit = 0;
    if (answer == ANSWER_SAVE) {
        say("save: yes");
        // In the Debug Menu's place, so its end moves back to the main
        // menu; before a race, its end starts it.
        bgf_change_to_screen(gf, AUTOSAVE_SCREEN, 0);
        if (sAfter == AFTER_RACE) {
            sFlow = gf;
            bgf_set_autosave_completion_callback(gf, raceAfterSave);
        }
        return;
    }
    say("save: no, changes undone");
    putCopyBack();
    if (sAfter == AFTER_RACE)
        startRace(gf);
    else
        bgf_move_back_screen(gf, 1);
}

// -------------------------------------------------------------- moving

static void setActive(int slot)
{
    if (sHooks.setActiveItem)
        sHooks.setActiveItem(sHooks.user, LABEL(slot + 1));
}

// PAD_UP and PAD_DOWN, before bmenu moves: 1 if the callback took it.
static int moveRow(Page* p, int dir)
{
    int slot = p->cur - p->top;
    if (dir < 0 && slot == 0) {
        if (p->top > 0) {
            p->top--;
            p->cur--;
            showRows(p);
            showHighlight(p);
        } else {
            p->top = p->numRows - p->numSlots;
            p->cur = p->numRows - 1;
            showRows(p);
            setActive(p->numSlots - 1);
        }
        fesound_play(BSND_MENU_UP, NULL);
        return 1;
    }
    if (dir > 0 && slot == p->numSlots - 1) {
        if (p->top + p->numSlots < p->numRows) {
            p->top++;
            p->cur++;
            showRows(p);
            showHighlight(p);
        } else {
            p->top = 0;
            p->cur = 0;
            showRows(p);
            setActive(0);
        }
        fesound_play(BSND_MENU_DOWN, NULL);
        return 1;
    }
    return 0;
}

static int slotOf(const Page* p, uint32_t itemHash)
{
    uint32_t k = itemHash - LABEL(1);
    return k < (uint32_t)p->numSlots ? (int)k : -1;
}

// What both screens do alike: the rows shown, the highlight, the scroll,
// LEFT and RIGHT, and the save prompt's answer. 1 if `msg` was one of
// those.
static int pageEvent(Page* p, BGameFlow* gf, BScreenMessage msg,
                     BScreenCallbackData* data)
{
    int slot;

    switch (msg) {
        case BMSG_SCREEN_ACTIVATE:
            if (!sHaveSet) {
                defaults();
                sHaveSet = 1;
            }
            validate();
            showRows(p);
            // The menu opens on the row it was left on.
            if (data) data->param = p->cur - p->top + 1;
            return 1;
        case BMSG_MENUITEM_HIGHLIGHT:
            slot = data ? slotOf(p, data->itemHash) : -1;
            if (slot < 0) return 1;
            p->cur = p->top + slot;
            if (p->cur >= p->numRows) p->cur = p->numRows - 1;
            showHighlight(p);
            return 1;
        case BMSG_MENUITEM_PAD_UP:
        case BMSG_MENUITEM_PAD_DOWN:
            if (data && moveRow(p, msg == BMSG_MENUITEM_PAD_UP ? -1 : 1))
                data->param = 1;
            return 1;
        case BMSG_MENUITEM_PAD_LEFT:
        case BMSG_MENUITEM_PAD_RIGHT: {
            int dir = msg == BMSG_MENUITEM_PAD_LEFT ? -1 : 1;
            int row = rowAt(p, p->cur);
            if (!data) return 1;
            data->noise = BSND_NONE;
            if (!rowHasValue(row) || !changeRow(row, dir)) return 1;
            data->noise = dir < 0 ? BSND_MENU_LEFT : BSND_MENU_RIGHT;
            showRows(p);
            showHighlight(p);
            return 1;
        }
        case BMSG_POPUP_DISMISS:
            answered(gf, data ? data->param : ANSWER_STAY);
            return 1;
        default:
            return 0;
    }
}

void debugmenu_callback(BGameFlow* gf, BScreenMessage msg,
                        BScreenCallbackData* data)
{
    Page* p = &sMenu;
    int   row;

    if (msg == BMSG_SCREEN_ACTIVATE && !sVisit) {
        // A visit from the main menu: the save as it is, to hold the rows'
        // changes against.
        sVisit = 1;
        takeCopy();
        memset(sDone, 0, sizeof sDone);
    }
    if (pageEvent(p, gf, msg, data)) return;

    switch (msg) {
        case BMSG_MENUITEM_SELECT:
            if (!data) break;
            row = rowAt(p, p->cur);
            switch (row) {
                case ROW_DEBUG_RACE:
                    bgf_change_to_screen(gf, DEBUGMENU_RACE_NAME, 1);
                    break;
                case ROW_POINTS: {
                    int32_t* pts = points();
                    *pts = *pts > NFS_POINTS_MAX - 100000 ? NFS_POINTS_MAX
                                                          : *pts + 100000;
                    say("points %d", (int)*pts);
                    showRows(p);
                    break;
                }
                default:
                    act(row);
                    showRows(p);
                    break;
            }
            break;
        case BMSG_SCREEN_BACK_BUTTON:
            if (!data) break;
            if (!changed()) {
                sVisit = 0;
                break;
            }
            // The pop waits for the answer.
            data->param = 0;
            askToSave(gf, p, AFTER_LEAVE);
            break;
        default:
            break;
    }
}

void debugmenu_race_callback(BGameFlow* gf, BScreenMessage msg,
                             BScreenCallbackData* data)
{
    Page* p = &sRace;

    if (pageEvent(p, gf, msg, data)) return;

    switch (msg) {
        case BMSG_MENUITEM_SELECT:
            if (!data) break;
            if (rowAt(p, p->cur) == ROW_START) {
                if (changed())
                    askToSave(gf, p, AFTER_RACE);
                else
                    startRace(gf);
                break;
            }
            // A on a setting steps it on, as RIGHT does.
            data->noise = BSND_NONE;
            if (changeRow(rowAt(p, p->cur), 1)) {
                data->noise = BSND_MENU_RIGHT;
                showRows(p);
                showHighlight(p);
            }
            break;
        default:
            break;
    }
}
