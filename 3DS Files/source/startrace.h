// startrace -- the screens over the fly-by before a race: retail's
// PRERACE_STATS module (0x001e27b8 to 0x001e3b40).
//
// RCSTATE_CAMERA_FLYBY's ACTIVATE calls EnableStartRaceScreens and its
// UNACTIVATE DisableStartRaceScreens (rcstates.c). Enable picks the
// screens this race wants, at most four, and changes to the first:
//
//   "Pre Race Blurb"        the objective, when the race has one; for
//                           You're The Cop, when one player is the cop
//   "Pre Race 2P Be A Cop"  You're The Cop with two players
//   "Pre Race Stats"        the Starting Grid, for every race but You're
//                           The Cop and the challenges' Free Run (game
//                           type 6)
//   "Pre Race Letterbox"    only when none of the three is wanted
//
// The grid (PRERACE_STATS in INGAMEB, 0x89b2fc0f) is a PreRaceStats: a
// line for each racer by starting position, the track's name and, in a
// multi-track event, "Race n of m". Its MENUITEM_1 is off the screen and
// there only to take the pad: SELECT posts RC_SKIP to the coordinator,
// which ends the fly-by; START, which reaches it as a SELECT whose Param
// is JOY_EVENT_START, does not. BACK steps to the screen before it.
//
//   NeedToSeeObjective                      0x001e27b8
//   (2P You're The Cop, no symbol)          0x001e27e8
//   NeedToSeePreRaceStats                   0x001e2810
//   AddScreen                               0x001e2848
//   Enable                                  0x001e2870
//   Disable                                 0x001e2910
//   RaceKnockoutInfoShouldBeDisplayed       0x001e2920
//   TournamentStandingsShouldBeDisplayed    0x001e2980
//   PreRaceStats::BuildStatsDefault         0x001e29d0
//   PreRaceStats::BuildStatsTournament      0x001e2ae8
//   PreRaceStats::BuildStatsRaceKnockout    0x001e2b90
//   PreRaceStats::GetStatsForRacePosition   0x001e2d00
//   PreRaceStats::PreRaceStats              0x001e2d40
//   PreRaceStats::~PreRaceStats             0x001e3128
//   PreRaceStats::HandleEvent               0x001e3148
//   PreRaceStats::Callback                  0x001e31d8
//   PreRaceLetterboxCallback                0x001e3968
//   EnableStartRaceScreens                  0x001e39b0
//   DisableStartRaceScreens                 0x001e39c0
//   StartRaceScreensReadyToSkip             0x001e39d0
//
// and from the frontend's track select, which the grid shares:
//
//   GetTheRightTrackLanguageID(TrackInfo *, eTrackDirection)  0x001dc580
//   (the track name and "Race %d of %d", no symbol)           0x001dc5d8
//
// The Blurb (PRERACE_BLURB) heads the screen with "Objective:", "Event %d
// Objective:" in an event, or "You're The Cop", and wraps the objective
// into its box each frame, on RENDER. The objective is the race's own,
// or for You're The Cop out of an event, the cop's controls for the pad
// and transmission (the %c in it is the nitro button's character). The
// two-player You're The Cop screen wraps each player's lines into two
// boxes. On both, SELECT steps to the next screen, and past the last
// skips the fly-by; START does nothing.
//
//   PreRaceBlurb::PreRaceBlurb                     0x001e3270
//   (the blurb's text, no symbol)                  0x001e3320
//   PreRaceBlurb::HandleEvent                      0x001e34a8
//   (the Blurb's destructor, no symbol)            0x001e35e0
//   (the Blurb's callback, no symbol)              0x001e3640
//   (PreRace2PBeACop's constructor, no symbol)     0x001e36f0
//   (its destructor; the image names it
//    PreRaceBlurb::~PreRaceBlurb)                  0x001e3730
//   (its HandleEvent, no symbol)                   0x001e3750
//   (its callback, no symbol)                      0x001e38b8

#ifndef STARTRACE_H
#define STARTRACE_H

#include <stddef.h>
#include <stdint.h>

#include "bmenu.h"
#include "bvector.h"

struct BGameFlow;
struct TrackInfo;

// The four names, retail's gp-17444 to gp-17432. Enable stores these
// pointers and BACK compares them, so a screen is its name's address.
extern const char kPreRaceStatsScreen[];        // "Pre Race Stats"
extern const char kPreRaceBlurbScreen[];        // "Pre Race Blurb"
extern const char kPreRace2PBeACopScreen[];     // "Pre Race 2P Be A Cop"
extern const char kPreRaceLetterboxScreen[];    // "Pre Race Letterbox"

// Their screens in INGAMEB, by the hashes FlailerScreenConfig registers
// them under (_GLOBAL_$I$PRERACE_STATS, 0x001e3a40).
#define STARTRACE_SCREEN_STATS      0x89b2fc0fu  // PRERACE_STATS
#define STARTRACE_SCREEN_BLURB      0x887b4d37u  // PRERACE_BLURB
#define STARTRACE_SCREEN_LETTERBOX  0xa3e1bc36u
#define STARTRACE_SCREEN_2P_BEACOP  0xb5ecd7a0u

// PRERACE_STATS' objects that are not a line's.
#define STARTRACE_OBJ_TRACK_NAME    0xf601f2d4u
#define STARTRACE_OBJ_RACE_OF       0xd0ced2e2u  // "Race %d of %d"
#define STARTRACE_OBJ_STATUS_HEAD   0xdc289a64u  // "Status"
#define STARTRACE_OBJ_PREVIOUS      0xaf6f1cdcu  // "\x87 previous"
#define STARTRACE_OBJ_NEXT          0x0019de3eu  // NEXT, "\x86 next"

// PRERACE_BLURB's and the 2P screen's. Each text object is INVISIBLE and
// only lends RenderTextIntoRectangle its font, place and colour; the box
// is the bitmap the text is wrapped into.
#define STARTRACE_OBJ_HEADING       0x6a77af98u  // "Objective:"
#define STARTRACE_OBJ_BLURB_TEXT    0xaefe36d8u
#define STARTRACE_OBJ_BLURB_BOX     0xcccf9a75u
#define STARTRACE_OBJ_2P_TEXT_1     0x8ec51608u
#define STARTRACE_OBJ_2P_BOX_1      0x232320f5u
#define STARTRACE_OBJ_2P_TEXT_2     0x8ec51609u
#define STARTRACE_OBJ_2P_BOX_2      0x232320f6u

// The LanguageIDs.
#define STARTRACE_LANG_OBJECTIVE    63000        // "Objective:"
#define STARTRACE_LANG_EVENT_OBJECTIVE 63001     // "Event %d Objective:"
#define STARTRACE_LANG_YOURE_THE_COP 970000      // "You're The Cop"
// "Be on the lookout for speeders!" and the cop's controls: for a pad
// with manual gears (TransmissionType 1 or 2), where the calls take a
// held button too, or automatic (0); the same for a pad of type 0x41; a
// wheel, which has only the first two lines; a wheel of type 22.
#define STARTRACE_LANG_COP_PAD      970001
#define STARTRACE_LANG_COP_PAD_AUTO 970016
#define STARTRACE_LANG_COP_WHEEL    970017
#define STARTRACE_LANG_COP_PAD41    970018
#define STARTRACE_LANG_COP_PAD41_AUTO 970019
#define STARTRACE_LANG_COP_WHEEL22  970020
#define STARTRACE_LANG_2P_COP       970010       // "The speeder's in ..."
#define STARTRACE_LANG_2P_SPEEDER   970011       // "The cops know ..."
#define STARTRACE_LANG_INSERT_CONTROLLER 900011  // "Please insert a ..."
#define STARTRACE_LANG_RACE_OF      0x3a983      // "Race %d of %d"
#define STARTRACE_LANG_KO_HEAD      0x3a982
#define STARTRACE_LANG_TOURNEY_HEAD 0x3ad6b
#define STARTRACE_LANG_KO_ELIMINATED 0x3ad69
#define STARTRACE_LANG_KO_RACING    0x3ad6a

#define STARTRACE_MAX_SCREENS 4
#define PRERACE_STATS_LINES   8

// tStartRaceScreenManager, 24 bytes; TheStartRaceScreenManager is retail's
// 0x0031a3e0.
typedef struct tStartRaceScreenManager {
    const char *Screens[STARTRACE_MAX_SCREENS];  //  0
    int32_t     NumScreens;                      // 16
    int32_t     CurrentScreen;                   // 20
} tStartRaceScreenManager;                       // 24

extern tStartRaceScreenManager TheStartRaceScreenManager;

// One line of the grid, 48 bytes.
typedef struct PreRaceStatsLine {
    int32_t     StartPosition;                   //  0  1 to 8, 0 unused
    const char *CharacterName;                   //  4
    int32_t     CarTypeNumber;                   //  8
    int32_t     KOStatus;                        // 12  a LanguageID
    int32_t     Points;                          // 16
    int32_t     _pad20[3];                       // 20
    bVector4    Color;                           // 32
} PreRaceStatsLine;                              // 48

// PreRaceStats, 400 bytes.
typedef struct PreRaceStats {
    uint32_t         ScreenHash;                 //  0
    int32_t          _pad4[3];                   //  4
    PreRaceStatsLine StatsLines[PRERACE_STATS_LINES];  // 16
} PreRaceStats;                                  // 400

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char startrace_layout_check[
    (offsetof(tStartRaceScreenManager, NumScreens) == 16
     && sizeof(tStartRaceScreenManager) == 24
     && offsetof(PreRaceStatsLine, KOStatus) == 12
     && offsetof(PreRaceStatsLine, Color) == 32
     && sizeof(PreRaceStatsLine) == 48
     && offsetof(PreRaceStats, StatsLines) == 16
     && sizeof(PreRaceStats) == 400) ? 1 : -1];
#endif

// The grid's colours. PlayerTextColors (0x00319fd0) and DefaultTextColor
// (0x00319ff0) belong to the end-game screens' file, whose static init
// (0x001e1ea0) makes them; the knockout's red (0x0031a2f0) is this file's.
extern const bVector4 PlayerTextColors[2];
extern const bVector4 DefaultTextColor;
extern const bVector4 PreRaceKnockoutColor;

// PreRaceStats::pInstance, retail's gp-17428: the grid while its screen
// is up.
extern PreRaceStats *PreRaceStatsInstance;

// PreRaceBlurb and PreRace2PBeACop, 4 bytes each.
typedef struct PreRaceBlurb {
    uint32_t ScreenHash;                         //  0
} PreRaceBlurb;

typedef struct PreRace2PBeACop {
    uint32_t ScreenHash;                         //  0
} PreRace2PBeACop;

// Their instances while their screens are up, gp-17380 and gp-17372.
extern PreRaceBlurb *PreRaceBlurbInstance;
extern PreRace2PBeACop *PreRace2PBeACopInstance;

// gp-17376, 0x89 in the image: the nitro button's character, which RENDER
// puts in the blurb's %c. It is asked again each frame a pad is plugged
// in, and kept from the last one otherwise.
extern int32_t PreRaceBlurbButtonChar;

// ------------------------------------------------------------ the manager

int32_t start_race_need_to_see_objective(const tStartRaceScreenManager *m);
int32_t start_race_need_to_see_2p_be_a_cop(const tStartRaceScreenManager *m);
int32_t start_race_need_to_see_pre_race_stats(
    const tStartRaceScreenManager *m);
void start_race_add_screen(tStartRaceScreenManager *m, const char *name);
void start_race_enable(tStartRaceScreenManager *m);
void start_race_disable(tStartRaceScreenManager *m);

// The three free functions on TheStartRaceScreenManager. The first two
// are rcstates.c's gEnableStartRaceScreensFn and gDisableStartRaceScreensFn.
void enable_start_race_screens(void);
void disable_start_race_screens(void);
int32_t start_race_screens_ready_to_skip(void);

// ---------------------------------------------------------------- the grid

int32_t race_knockout_info_should_be_displayed(void);
int32_t tournament_standings_should_be_displayed(void);

PreRaceStats *pre_race_stats_construct(PreRaceStats *s, uint32_t screen);
void pre_race_stats_destroy(PreRaceStats *s, int32_t flags);
int32_t pre_race_stats_build_stats_default(PreRaceStats *s);
void pre_race_stats_build_stats_tournament(PreRaceStats *s);
void pre_race_stats_build_stats_race_knockout(PreRaceStats *s);
PreRaceStatsLine *pre_race_stats_get_stats_for_race_position(
    PreRaceStats *s, int32_t pos);
void pre_race_stats_handle_event(PreRaceStats *s, BScreenMessage msg,
                                 BScreenCallbackData *data);

// GetTheRightTrackLanguageID(TrackInfo *, eTrackDirection): the forward
// name for 0, the reverse for 1, 0 for anything else.
int32_t get_the_right_track_language_id(const struct TrackInfo *t,
                                        int32_t dir);

// 0x001dc5d8: the track's name on `trackObj`, and "Race %d of %d" on
// `raceObj` in a multi-track event (the race's number plus `add`, held to
// the count), hidden otherwise.
void set_track_name_and_race_number(uint32_t screen, uint32_t trackObj,
                                    uint32_t raceObj, int32_t add);

// --------------------------------------------------------------- the blurb

PreRaceBlurb *pre_race_blurb_construct(PreRaceBlurb *b, uint32_t screen);
void pre_race_blurb_destroy(PreRaceBlurb *b, int32_t flags);
void pre_race_blurb_handle_event(PreRaceBlurb *b, BScreenMessage msg,
                                 BScreenCallbackData *data);

// 0x001e3320: the text for `player`. The race's objective, unless this is
// You're The Cop out of an event; then for one player the cop's controls
// for player 0's pad and gearbox, or "Please insert a controller.", and
// for two the cop's or the speeder's lines by player. NULL for a
// TransmissionType past 2, a third player, or a count of players that is
// neither.
const char *pre_race_blurb_text(int32_t player);

PreRace2PBeACop *pre_race_2p_be_a_cop_construct(PreRace2PBeACop *b,
                                                uint32_t screen);
void pre_race_2p_be_a_cop_destroy(PreRace2PBeACop *b, int32_t flags);
void pre_race_2p_be_a_cop_handle_event(PreRace2PBeACop *b,
                                       BScreenMessage msg,
                                       BScreenCallbackData *data);

// ------------------------------------------------------------ the screens

// The FlailerScreenConfig callbacks, in the flow's shape: `gf` is not
// read.
void pre_race_stats_callback(struct BGameFlow *gf, BScreenMessage msg,
                             BScreenCallbackData *data);
void pre_race_blurb_callback(struct BGameFlow *gf, BScreenMessage msg,
                             BScreenCallbackData *data);
void pre_race_2p_be_a_cop_callback(struct BGameFlow *gf, BScreenMessage msg,
                                   BScreenCallbackData *data);
void pre_race_letterbox_callback(struct BGameFlow *gf, BScreenMessage msg,
                                 BScreenCallbackData *data);

// ---------------------------------------------------------------- seams

// GetTranslatedString(int) (0x0021e560); NULL, or a NULL answer, is the
// image's "NOT TRANSLATED PROPERLY".
extern const char *(*gStartRaceTranslateFn)(int32_t id);
// GetTranslatedString(const char *) (0x0021e508): the string for the
// English text's hash; NULL, or a NULL answer, is the text itself.
extern const char *(*gStartRaceTranslateStringFn)(const char *s);
// RaceEvent::GetRaceCount (0x00202088) on TheRaceEvent. NULL answers 0.
extern int32_t (*gRaceEventGetRaceCountFn)(void);
// RaceEvent::GetTournamentState (0x00201880): the tournament's points,
// a byte for each racer by RacerIndexFromDriverNumber. NULL, or a NULL
// answer, reads every racer's points as 0.
extern const uint8_t *(*gRaceEventGetTournamentStateFn)(void);

#endif
