// startrace.c -- the screens over the fly-by before a race; see
// startrace.h.

#include "startrace.h"

#include <stdio.h>
#include <string.h>

#include "bchunk.h"
#include "bmem.h"
#include "car.h"
#include "cartypeinfo.h"
#include "characterinfo.h"
#include "flailer.h"
#include "flailerwrap.h"
#include "fred.h"
#include "fredrace.h"
#include "joyevent.h"
#include "joystick.h"
#include "player.h"
#include "race.h"
#include "racecoord.h"
#include "raceevent.h"
#include "rcpost.h"
#include "track.h"
#include "world.h"

// GameTypes, the .mdebug enum's.
#define FRED_CHALLENGE_GAME_KNOCKOUT  4
#define FRED_CHALLENGE_GAME_FREE_RUN  6
#define FRED_ULTIMATE_GAME            8
#define FRED_HOTPURSUIT_GAME          9

// TheRaceEvent's types the grid tests (RaceEvent+106).
#define RACE_EVENT_KNOCKOUT    3
#define RACE_EVENT_TOURNAMENT  4

// JOY_EVENT_START, which FlailerMenuItem::JoyHandler (0x00169d98) puts in
// a SELECT's Param when START made it.
#define JOY_EVENT_START 7

const char kPreRaceStatsScreen[] = "Pre Race Stats";
const char kPreRaceBlurbScreen[] = "Pre Race Blurb";
const char kPreRace2PBeACopScreen[] = "Pre Race 2P Be A Cop";
const char kPreRaceLetterboxScreen[] = "Pre Race Letterbox";

tStartRaceScreenManager TheStartRaceScreenManager;
PreRaceStats *PreRaceStatsInstance;
PreRaceBlurb *PreRaceBlurbInstance;
PreRace2PBeACop *PreRace2PBeACopInstance;
int32_t PreRaceBlurbButtonChar = 0x89;

const bVector4 PlayerTextColors[2] = {
    { 134.0f, 96.0f, 48.0f, 128.0f },
    { 0.0f, 128.0f, 0.0f, 128.0f },
};
const bVector4 DefaultTextColor = { 128.0f, 128.0f, 128.0f, 128.0f };
const bVector4 PreRaceKnockoutColor = { 128.0f, 0.0f, 0.0f, 128.0f };

const char *(*gStartRaceTranslateFn)(int32_t id);
const char *(*gStartRaceTranslateStringFn)(const char *s);
int32_t (*gRaceEventGetRaceCountFn)(void);
const uint8_t *(*gRaceEventGetTournamentStateFn)(void);

// ---------------------------------------------------------- the helpers

static void change_to_screen(const char *name, int32_t push)
{
    if (gChangeToScreenFn != NULL)
        gChangeToScreenFn(name, push);
}

static const char *get_translated_string(int32_t id)
{
    const char *s = gStartRaceTranslateFn != NULL ? gStartRaceTranslateFn(id)
                                                  : NULL;

    return s != NULL ? s : "NOT TRANSLATED PROPERLY";
}

static const char *get_translated_string_by_name(const char *s)
{
    const char *t = gStartRaceTranslateStringFn != NULL
                        ? gStartRaceTranslateStringFn(s) : NULL;

    return t != NULL ? t : s;
}

// CarTypeInfo::GetShortName, 0x00187eb8: the string for pCarSpecs' +20,
// which the port calls FullName (cartypeinfo.h).
static const char *car_type_info_get_short_name(const CarTypeInfo *ct)
{
    return get_translated_string(ct->pCarSpecs->FullName);
}

// DriverInfo::GetName, 0x00188770: the character's name, or "" for none.
static const char *driver_info_get_name(const DriverInfo *d)
{
    if (d->pCharacterInfo == NULL)
        return "";
    return d->pCharacterInfo->CharacterName;
}

// SprintfAndHash, 0x001dc4d0: bStringHash of fmt with n, into 32 bytes.
static uint32_t sprintf_and_hash(const char *fmt, int32_t n)
{
    char buf[32];

    snprintf(buf, sizeof buf, fmt, (int)n);
    return bchunk_hash(buf);
}

static int32_t race_event_get_race_index(void)
{
    return gRaceEventGetRaceIndexFn != NULL ? gRaceEventGetRaceIndexFn() : 0;
}

static int32_t race_event_get_race_count(void)
{
    return gRaceEventGetRaceCountFn != NULL ? gRaceEventGetRaceCountFn() : 0;
}

// RaceEvent::RacerIndexFromDriverNumber, 0x00201558: an AI's number is
// past the players'.
static int32_t race_event_racer_index_from_driver_number(int32_t n)
{
    if (n < 100)
        return n;
    return TheRaceEvent.nInitialPlayers + n - 100;
}

// ------------------------------------------------------------ the manager

int32_t start_race_need_to_see_objective(const tStartRaceScreenManager *m)
{
    (void)m;
    if (TheRaceParameters.BeACop)
        return TheRaceParameters.NumPlayerCars == 1;
    return TheRaceParameters.HasObjective;
}

int32_t start_race_need_to_see_2p_be_a_cop(const tStartRaceScreenManager *m)
{
    (void)m;
    if (!TheRaceParameters.BeACop)
        return 0;
    return TheRaceParameters.NumPlayerCars == 2;
}

int32_t start_race_need_to_see_pre_race_stats(
    const tStartRaceScreenManager *m)
{
    (void)m;
    if (TheRaceParameters.BeACop)
        return 0;
    return Fred.GameType != FRED_CHALLENGE_GAME_FREE_RUN;
}

void start_race_add_screen(tStartRaceScreenManager *m, const char *name)
{
    if (m->NumScreens < STARTRACE_MAX_SCREENS)
        m->Screens[m->NumScreens++] = name;
}

void start_race_enable(tStartRaceScreenManager *m)
{
    // Screens 2 and 3 are left as they were.
    m->NumScreens = 0;
    m->CurrentScreen = 0;
    m->Screens[0] = NULL;
    m->Screens[1] = NULL;
    if (start_race_need_to_see_objective(m))
        start_race_add_screen(m, kPreRaceBlurbScreen);
    if (start_race_need_to_see_2p_be_a_cop(m))
        start_race_add_screen(m, kPreRace2PBeACopScreen);
    if (start_race_need_to_see_pre_race_stats(m))
        start_race_add_screen(m, kPreRaceStatsScreen);
    if (m->NumScreens == 0)
        start_race_add_screen(m, kPreRaceLetterboxScreen);
    change_to_screen(m->Screens[m->CurrentScreen], 1);
}

void start_race_disable(tStartRaceScreenManager *m)
{
    (void)m;
    change_to_screen(NULL, 0);
}

void enable_start_race_screens(void)
{
    start_race_enable(&TheStartRaceScreenManager);
}

void disable_start_race_screens(void)
{
    start_race_disable(&TheStartRaceScreenManager);
}

int32_t start_race_screens_ready_to_skip(void)
{
    const tStartRaceScreenManager *m = &TheStartRaceScreenManager;

    return m->CurrentScreen == m->NumScreens - 1;
}

// ------------------------------------------------------- the track's name

int32_t get_the_right_track_language_id(const TrackInfo *t, int32_t dir)
{
    if (dir == TRACK_DIRECTION_FORWARD)
        return t->TrackLanguageID;
    if (dir == TRACK_DIRECTION_BACKWARD)
        return t->ReverseTrackLanguageID;
    return 0;
}

void set_track_name_and_race_number(uint32_t screen, uint32_t trackObj,
                                    uint32_t raceObj, int32_t add)
{
    flailer_set_language_id(screen, trackObj,
                            (uint32_t)get_the_right_track_language_id(
                                CurrentTrackInfo,
                                TheRaceParameters.TrackDirection));
    if (fred_use_the_race_event(&Fred) && fred_is_multi_track(&Fred)) {
        int32_t race = race_event_get_race_index() + add;
        int32_t count = race_event_get_race_count();

        if (count < race)
            race = count;
        flailer_printf(screen, raceObj,
                       get_translated_string(STARTRACE_LANG_RACE_OF),
                       (int)race, (int)count);
        flailer_set_visibility(screen, raceObj, FLAILER_OBJECT_VISIBLE);
    } else {
        flailer_set_visibility(screen, raceObj, FLAILER_OBJECT_INVISIBLE);
    }
}

// ---------------------------------------------------------------- the grid

int32_t race_knockout_info_should_be_displayed(void)
{
    int32_t t = Fred.GameType;

    if (t == FRED_CHALLENGE_GAME_KNOCKOUT)
        return 1;
    if (t != FRED_ULTIMATE_GAME && t != FRED_HOTPURSUIT_GAME)
        return 0;
    return TheRaceEvent.nType == RACE_EVENT_KNOCKOUT;
}

int32_t tournament_standings_should_be_displayed(void)
{
    int32_t t = Fred.GameType;

    if (t != FRED_ULTIMATE_GAME && t != FRED_HOTPURSUIT_GAME)
        return 0;
    return TheRaceEvent.nType == RACE_EVENT_TOURNAMENT;
}

// A line for each racing car, at most eight, in the race's order. A
// player's name is its PlayerSettings', in its player's colour.
int32_t pre_race_stats_build_stats_default(PreRaceStats *s)
{
    PreRaceStatsLine *line = s->StatsLines;
    int32_t n = pCurrentRace->NumRacingCars;
    int32_t count = 0;
    int32_t i;

    for (i = 0; i < n && i < PRERACE_STATS_LINES; i++, line++) {
        const DriverInfo *d = pCurrentRace->pRacingCars[i]->pCar->MyDriver;

        if (d->TheDriverType == DRIVER_TYPE_PLAYER) {
            const Player *p =
                world_get_car_by_driver_number(d->UniqueDriverNumber)
                    ->pPlayer;

            line->CharacterName = p->PlayerSettings.PlayerName;
            line->Color = PlayerTextColors[p->PlayerNumber];
        } else {
            line->CharacterName = driver_info_get_name(d);
            line->Color = DefaultTextColor;
        }
        line->StartPosition = d->StartingPosition;
        line->CarTypeNumber = d->CurrentRideInfo.Type;
        line->KOStatus = 0;
        line->Points = 0;
        count++;
    }
    return count;
}

// The default lines with each racer's points. The loop runs to the race's
// count, not to eight, as retail's does.
void pre_race_stats_build_stats_tournament(PreRaceStats *s)
{
    const uint8_t *state;
    int32_t i;

    pre_race_stats_build_stats_default(s);
    state = gRaceEventGetTournamentStateFn != NULL
                ? gRaceEventGetTournamentStateFn() : NULL;
    for (i = 0; i < pCurrentRace->NumRacingCars; i++) {
        const DriverInfo *d = pCurrentRace->pRacingCars[i]->pCar->MyDriver;
        int32_t r = race_event_racer_index_from_driver_number(
            d->UniqueDriverNumber);

        s->StatsLines[i].Points = state != NULL ? state[r] : 0;
    }
}

// The default lines, each still racing; then a red line for each driver
// already knocked out, at the place it went out in. Retail first reads
// GetKoState and does nothing with it. The added lines are not held to
// eight.
void pre_race_stats_build_stats_race_knockout(PreRaceStats *s)
{
    int32_t n = pre_race_stats_build_stats_default(s);
    int32_t i;

    for (i = 0; i < n; i++)
        s->StatsLines[i].KOStatus = STARTRACE_LANG_KO_RACING;
    for (i = 0; i < TheRaceParameters.NumDriverInfo; i++) {
        const DriverInfo *d = race_parameters_get_driver_info(i);
        PreRaceStatsLine *line;

        if (d->EliminatedRank <= 0)
            continue;
        line = &s->StatsLines[n++];
        line->CarTypeNumber = d->CurrentRideInfo.Type;
        line->CharacterName = driver_info_get_name(d);
        if (d->TheDriverType == DRIVER_TYPE_PLAYER)
            line->CharacterName = TheRaceParameters
                .PlayerSettings[d->UniqueDriverNumber].PlayerName;
        line->Color = PreRaceKnockoutColor;
        line->KOStatus = STARTRACE_LANG_KO_ELIMINATED;
        line->Points = 0;
        line->StartPosition = d->EliminatedRank;
    }
}

PreRaceStatsLine *pre_race_stats_get_stats_for_race_position(
    PreRaceStats *s, int32_t pos)
{
    int32_t i;

    for (i = 0; i < PRERACE_STATS_LINES; i++)
        if (s->StatsLines[i].StartPosition == pos)
            return &s->StatsLines[i];
    return NULL;
}

PreRaceStats *pre_race_stats_construct(PreRaceStats *s, uint32_t screen)
{
    int32_t ko, tour, i;

    s->ScreenHash = screen;
    set_track_name_and_race_number(screen, STARTRACE_OBJ_TRACK_NAME,
                                   STARTRACE_OBJ_RACE_OF, 1);
    memset(s->StatsLines, 0, sizeof s->StatsLines);
    ko = race_knockout_info_should_be_displayed();
    tour = tournament_standings_should_be_displayed();
    if (ko) {
        flailer_set_visibility(s->ScreenHash, STARTRACE_OBJ_STATUS_HEAD,
                               FLAILER_OBJECT_VISIBLE);
        flailer_set_language_id(s->ScreenHash, STARTRACE_OBJ_STATUS_HEAD,
                                STARTRACE_LANG_KO_HEAD);
        pre_race_stats_build_stats_race_knockout(s);
    } else if (tour) {
        flailer_set_visibility(s->ScreenHash, STARTRACE_OBJ_STATUS_HEAD,
                               FLAILER_OBJECT_VISIBLE);
        flailer_set_language_id(s->ScreenHash, STARTRACE_OBJ_STATUS_HEAD,
                                STARTRACE_LANG_TOURNEY_HEAD);
        pre_race_stats_build_stats_tournament(s);
    } else {
        flailer_set_visibility(s->ScreenHash, STARTRACE_OBJ_STATUS_HEAD,
                               FLAILER_OBJECT_INVISIBLE);
        pre_race_stats_build_stats_default(s);
    }

    // The grid, by starting position: POS_n, NAME_n, TYPE_n and STATUS_n.
    for (i = 1; i <= PRERACE_STATS_LINES; i++) {
        uint32_t pos = sprintf_and_hash("POS_%d", i);
        uint32_t name = sprintf_and_hash("NAME_%d", i);
        uint32_t type = sprintf_and_hash("TYPE_%d", i);
        uint32_t status = sprintf_and_hash("STATUS_%d", i);
        PreRaceStatsLine *line = pre_race_stats_get_stats_for_race_position(
            s, i);

        if (line != NULL) {
            const CarTypeInfo *ct = cartypeinfo_get(line->CarTypeNumber);

            flailer_set_visibility(s->ScreenHash, pos,
                                   FLAILER_OBJECT_VISIBLE);
            flailer_set_visibility(s->ScreenHash, name,
                                   FLAILER_OBJECT_VISIBLE);
            flailer_set_visibility(s->ScreenHash, type,
                                   FLAILER_OBJECT_VISIBLE);
            flailer_printf(s->ScreenHash, pos, "%2d",
                           (int)line->StartPosition);
            flailer_printf(s->ScreenHash, name, "%s", line->CharacterName);
            flailer_printf(s->ScreenHash, type, "%s",
                           get_translated_string_by_name(
                               car_type_info_get_short_name(ct)));
            if (ko) {
                flailer_set_visibility(s->ScreenHash, status,
                                       FLAILER_OBJECT_VISIBLE);
                flailer_set_language_id(s->ScreenHash, status,
                                        (uint32_t)line->KOStatus);
            } else if (tour) {
                flailer_set_visibility(s->ScreenHash, status,
                                       FLAILER_OBJECT_VISIBLE);
                flailer_printf(s->ScreenHash, status, "%d",
                               (int)line->Points);
            } else {
                flailer_set_visibility(s->ScreenHash, status,
                                       FLAILER_OBJECT_INVISIBLE);
            }
            flailer_set_object_color(s->ScreenHash, pos, &line->Color);
            flailer_set_object_color(s->ScreenHash, name, &line->Color);
            flailer_set_object_color(s->ScreenHash, type, &line->Color);
            flailer_set_object_color(s->ScreenHash, status, &line->Color);
        } else {
            flailer_set_visibility(s->ScreenHash, pos,
                                   FLAILER_OBJECT_INVISIBLE);
            flailer_set_visibility(s->ScreenHash, name,
                                   FLAILER_OBJECT_INVISIBLE);
            flailer_set_visibility(s->ScreenHash, type,
                                   FLAILER_OBJECT_INVISIBLE);
            flailer_set_visibility(s->ScreenHash, status,
                                   FLAILER_OBJECT_INVISIBLE);
        }
    }

    // "Previous" only when there is a screen before the grid.
    if (start_race_need_to_see_objective(&TheStartRaceScreenManager)
        || start_race_need_to_see_2p_be_a_cop(&TheStartRaceScreenManager))
        flailer_set_visibility(s->ScreenHash, STARTRACE_OBJ_PREVIOUS,
                               FLAILER_OBJECT_VISIBLE);
    else
        flailer_set_visibility(s->ScreenHash, STARTRACE_OBJ_PREVIOUS,
                               FLAILER_OBJECT_INVISIBLE);
    flailer_set_visibility(s->ScreenHash, STARTRACE_OBJ_NEXT,
                           FLAILER_OBJECT_VISIBLE);
    return s;
}

void pre_race_stats_destroy(PreRaceStats *s, int32_t flags)
{
    if (flags & 1)
        bFree(s);
}

// Up and down are silent. BACK steps to the screen before, silently when
// there is none. SELECT skips the fly-by, unless START made it.
void pre_race_stats_handle_event(PreRaceStats *s, BScreenMessage msg,
                                 BScreenCallbackData *data)
{
    tStartRaceScreenManager *m = &TheStartRaceScreenManager;

    (void)s;
    if (msg == BMSG_MENUITEM_PAD_UP || msg == BMSG_MENUITEM_PAD_DOWN) {
        data->noise = 0;
    } else if (msg == BMSG_SCREEN_BACK_BUTTON) {
        const char *was;

        data->param = 0;
        was = m->Screens[m->CurrentScreen];
        if (m->CurrentScreen > 0)
            m->CurrentScreen--;
        if (m->Screens[m->CurrentScreen] == was)
            data->noise = 0;
        else
            change_to_screen(m->Screens[m->CurrentScreen], 0);
    } else if (msg == BMSG_MENUITEM_SELECT) {
        if (data->param == JOY_EVENT_START)
            data->noise = 0;
        else
            racecoordinator_post_message(pRaceCoordinator, RC_SKIP, 0);
    }
}

// --------------------------------------------------------------- the blurb

// The joystick types the cop's controls tell apart: a wheel of type 22
// and a pad of type 0x41. The 3DS's is 0, a pad of neither.
#define JOYSTICK_TYPE_WHEEL_22  22
#define JOYSTICK_TYPE_PAD_41    0x41

// The frontend sound SELECT asks for when it steps to the next screen.
#define STARTRACE_NOISE_NEXT    5

// SELECT on the Blurb and on the 2P screen (0x001e3548, 0x001e3808):
// nothing when START made it; otherwise the next screen, silently changed
// to with the noise set to 5, or from the last the fly-by skipped.
// Retail posts to pRaceCoordinator without testing it.
static void start_race_step_to_next_screen(BScreenCallbackData *data)
{
    tStartRaceScreenManager *m = &TheStartRaceScreenManager;
    const char *was;

    if (data->param == JOY_EVENT_START)
        return;
    data->param = 0;
    data->noise = 0;
    was = m->Screens[m->CurrentScreen];
    if (m->CurrentScreen < m->NumScreens - 1)
        m->CurrentScreen++;
    if (m->Screens[m->CurrentScreen] == was) {
        racecoordinator_post_message(pRaceCoordinator, RC_SKIP, 0);
    } else {
        change_to_screen(m->Screens[m->CurrentScreen], 0);
        data->noise = STARTRACE_NOISE_NEXT;
    }
}

const char *pre_race_blurb_text(int32_t player)
{
    if (!TheRaceParameters.BeACop || TheRaceParameters.EventTreeRace)
        return TheRaceParameters.sObjective;
    if (TheRaceParameters.NumPlayerCars == 1) {
        int32_t pad41, t;

        if (!IsJoystickPluggedIn(0))
            return get_translated_string(STARTRACE_LANG_INSERT_CONTROLLER);
        if (IsJoystickTypeWheel(0))
            return get_translated_string(
                GetJoystickType(0) == JOYSTICK_TYPE_WHEEL_22
                    ? STARTRACE_LANG_COP_WHEEL22 : STARTRACE_LANG_COP_WHEEL);
        pad41 = GetJoystickType(0) == JOYSTICK_TYPE_PAD_41;
        t = PlayerPlayersByNumber[player]->PlayerSettings.TransmissionType;
        if (t >= 3 || t < 0)
            return NULL;
        if (t == 0)
            return get_translated_string(pad41 ? STARTRACE_LANG_COP_PAD41_AUTO
                                               : STARTRACE_LANG_COP_PAD_AUTO);
        return get_translated_string(pad41 ? STARTRACE_LANG_COP_PAD41
                                           : STARTRACE_LANG_COP_PAD);
    }
    if (TheRaceParameters.NumPlayerCars == 2) {
        if (player == 0)
            return get_translated_string(STARTRACE_LANG_2P_COP);
        if (player == 1)
            return get_translated_string(STARTRACE_LANG_2P_SPEEDER);
    }
    return NULL;
}

// The heading: "Event %d Objective:" with the event's number in an event,
// the cop's own heading for the cop, "Objective:" otherwise.
PreRaceBlurb *pre_race_blurb_construct(PreRaceBlurb *b, uint32_t screen)
{
    b->ScreenHash = screen;
    if (TheRaceParameters.EventTreeRace)
        flailer_printf(screen, STARTRACE_OBJ_HEADING,
                       get_translated_string(STARTRACE_LANG_EVENT_OBJECTIVE),
                       (int)TheRaceEvent.nNumber);
    else if (TheRaceParameters.BeACop)
        flailer_set_language_id(screen, STARTRACE_OBJ_HEADING,
                                STARTRACE_LANG_YOURE_THE_COP);
    else
        flailer_set_language_id(screen, STARTRACE_OBJ_HEADING,
                                STARTRACE_LANG_OBJECTIVE);
    flailer_set_visibility(b->ScreenHash, STARTRACE_OBJ_NEXT,
                           FLAILER_OBJECT_VISIBLE);
    return b;
}

void pre_race_blurb_destroy(PreRaceBlurb *b, int32_t flags)
{
    flailer_set_visibility(b->ScreenHash, STARTRACE_OBJ_NEXT,
                           FLAILER_OBJECT_INVISIBLE);
    if (flags & 1)
        bFree(b);
}

// RENDER prints the text, its %c the horn's button character (the cop's
// target), into 512 bytes (bSPrintf has no bound; the port's stops at the
// end), and wraps it into the box. A NULL text is printed as nothing, where retail hands
// bSPrintf the NULL.
void pre_race_blurb_handle_event(PreRaceBlurb *b, BScreenMessage msg,
                                 BScreenCallbackData *data)
{
    if (msg == BMSG_MENUITEM_PAD_UP || msg == BMSG_MENUITEM_PAD_DOWN) {
        data->noise = 0;
    } else if (msg == BMSG_SCREEN_RENDER) {
        char buf[512];
        const char *fmt;

        // Retail passes 126, JOY_EVENT_HONK_HORN.
        if (IsJoystickPluggedIn(0))
            PreRaceBlurbButtonChar =
                GetJoystickButtonChar(0, JOY_EVENT_HONK_HORN);
        fmt = pre_race_blurb_text(0);
        snprintf(buf, sizeof buf, fmt != NULL ? fmt : "",
                 (int)PreRaceBlurbButtonChar);
        flailer_render_text_into_rectangle(b->ScreenHash,
                                           STARTRACE_OBJ_BLURB_TEXT,
                                           STARTRACE_OBJ_BLURB_BOX, buf,
                                           1.0f);
    } else if (msg == BMSG_MENUITEM_SELECT) {
        start_race_step_to_next_screen(data);
    }
}

PreRace2PBeACop *pre_race_2p_be_a_cop_construct(PreRace2PBeACop *b,
                                                uint32_t screen)
{
    b->ScreenHash = screen;
    flailer_set_visibility(screen, STARTRACE_OBJ_NEXT,
                           FLAILER_OBJECT_VISIBLE);
    return b;
}

// NEXT is left as it is.
void pre_race_2p_be_a_cop_destroy(PreRace2PBeACop *b, int32_t flags)
{
    if (flags & 1)
        bFree(b);
}

// RENDER wraps each player's lines into their box as they are: no
// printf.
void pre_race_2p_be_a_cop_handle_event(PreRace2PBeACop *b,
                                       BScreenMessage msg,
                                       BScreenCallbackData *data)
{
    if (msg == BMSG_MENUITEM_PAD_UP || msg == BMSG_MENUITEM_PAD_DOWN) {
        data->noise = 0;
    } else if (msg == BMSG_SCREEN_RENDER) {
        flailer_render_text_into_rectangle(b->ScreenHash,
                                           STARTRACE_OBJ_2P_TEXT_1,
                                           STARTRACE_OBJ_2P_BOX_1,
                                           pre_race_blurb_text(0), 1.0f);
        flailer_render_text_into_rectangle(b->ScreenHash,
                                           STARTRACE_OBJ_2P_TEXT_2,
                                           STARTRACE_OBJ_2P_BOX_2,
                                           pre_race_blurb_text(1), 1.0f);
    } else if (msg == BMSG_MENUITEM_SELECT) {
        start_race_step_to_next_screen(data);
    }
}

// ------------------------------------------------------------ the screens

void pre_race_stats_callback(struct BGameFlow *gf, BScreenMessage msg,
                             BScreenCallbackData *data)
{
    (void)gf;
    if (msg == BMSG_SCREEN_ACTIVATE) {
        PreRaceStats *mem = (PreRaceStats *)bMalloc(sizeof(PreRaceStats),
                                                    "PreRaceStats", 0, 16);

        PreRaceStatsInstance = pre_race_stats_construct(mem, data->itemHash);
    } else if (msg == BMSG_SCREEN_UNACTIVATE) {
        if (PreRaceStatsInstance != NULL)
            pre_race_stats_destroy(PreRaceStatsInstance, 3);
        PreRaceStatsInstance = NULL;
    } else {
        pre_race_stats_handle_event(PreRaceStatsInstance, msg, data);
    }
}

// BACK on the blurb and the 2P screen is silent and goes nowhere.
void pre_race_blurb_callback(struct BGameFlow *gf, BScreenMessage msg,
                             BScreenCallbackData *data)
{
    (void)gf;
    if (msg == BMSG_SCREEN_ACTIVATE) {
        PreRaceBlurb *mem = (PreRaceBlurb *)bMalloc(sizeof(PreRaceBlurb),
                                                    "PreRaceBlurb", 0, 16);

        PreRaceBlurbInstance = pre_race_blurb_construct(mem, data->itemHash);
    } else if (msg == BMSG_SCREEN_UNACTIVATE) {
        if (PreRaceBlurbInstance != NULL)
            pre_race_blurb_destroy(PreRaceBlurbInstance, 3);
        PreRaceBlurbInstance = NULL;
    } else if (msg == BMSG_SCREEN_BACK_BUTTON) {
        data->noise = 0;
        data->param = 0;
    } else {
        pre_race_blurb_handle_event(PreRaceBlurbInstance, msg, data);
    }
}

void pre_race_2p_be_a_cop_callback(struct BGameFlow *gf, BScreenMessage msg,
                                   BScreenCallbackData *data)
{
    (void)gf;
    if (msg == BMSG_SCREEN_ACTIVATE) {
        PreRace2PBeACop *mem = (PreRace2PBeACop *)bMalloc(
            sizeof(PreRace2PBeACop), "PreRace2PBeACop", 0, 16);

        PreRace2PBeACopInstance = pre_race_2p_be_a_cop_construct(
            mem, data->itemHash);
    } else if (msg == BMSG_SCREEN_UNACTIVATE) {
        if (PreRace2PBeACopInstance != NULL)
            pre_race_2p_be_a_cop_destroy(PreRace2PBeACopInstance, 3);
        PreRace2PBeACopInstance = NULL;
    } else if (msg == BMSG_SCREEN_BACK_BUTTON) {
        data->noise = 0;
        data->param = 0;
    } else {
        pre_race_2p_be_a_cop_handle_event(PreRace2PBeACopInstance, msg, data);
    }
}

// The letterbox has nothing on it but NEXT. SELECT, START's too, skips.
void pre_race_letterbox_callback(struct BGameFlow *gf, BScreenMessage msg,
                                 BScreenCallbackData *data)
{
    (void)gf;
    if (msg == BMSG_MENUITEM_SELECT) {
        if (pRaceCoordinator != NULL)
            racecoordinator_post_message(pRaceCoordinator, RC_SKIP, 0);
    } else if (msg == BMSG_SCREEN_BACK_BUTTON) {
        data->noise = 0;
        data->param = 0;
    } else if (msg == BMSG_MENUITEM_PAD_UP
               || msg == BMSG_MENUITEM_PAD_DOWN) {
        data->noise = 0;
    }
}
