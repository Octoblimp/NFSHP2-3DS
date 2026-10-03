// hudrender -- the HUD's every frame: Player::UpdateHud and RenderHud.
//
//   Player::UpdateHud                 0x0017ecf0   848 bytes
//   Player::RenderHud                 0x0017f040  6812 bytes (no symbol)
//   the score's fade                  0x0017d7c8   564 bytes (no symbol)
//   Player::GetCurrentBestLapRecord   0x0017ef60   224 bytes
//   Player::ConvertScoreString        0x0017e220   180 bytes
//   Player::DisplayDebugInfo          0x00181230   808 bytes
//   GetLetterForGear                  0x00178b70    56 bytes
//   TriggerTimerWarningSound          0x001afb80   112 bytes
//
// UpdateHud keeps the HUD's features up to date (playerhud.c), runs the
// animations, fades the score, gives the player the places it starts
// ahead of on the first frame of the race, and draws the HUD when it has
// anything to show. RenderHud writes the frame's numbers into the Flailer
// objects SetHudFeatures found: the speedo and the tach, the lead in a
// two-player race, the lap time, the best lap, the splits, the live
// leaderboard, the lap counter and race position, the tyres, the pursuit
// meter and the radar, Be The Cop's panel, the NIS overlay and the
// trackers, and last the debug strings.
//
// Step 8m-3. Written up in docs/formats/hud-render.md; checked on retail's
// image by tools/hudrender_check.py.

#ifndef HUDRENDER_H
#define HUDRENDER_H

#include <stdint.h>

#include "nisoverlay.h"
#include "timer.h"

struct Car;
struct FlailerTextChunk;
struct Player;

// Player::UpdateHud. UpdateHud's head (player_update_hud_features), then
// HudDoAnimations and the score's fade; in a race at stage 4 whose
// coordinator is in none of pause, instant replay, post-race, auto replay
// or a replay demo, the first frame's start bonus and UpdateScoring; and
// RenderHud whenever CurrentHudFeatures is not 0.
//
// The start bonus, once a race (New2736): with two players and no driver
// knocked out, the places behind the player's RacePosition are marked
// reached in baPlaceReached, the one just behind the last left out when
// the player is last; otherwise each place from last up to the player's
// is marked and scores its ScoreInfoTable "TOOK Nth PLACE" entry, and a
// total that is not 0 goes to StartScore as SCORING_START_BONUS.
void player_update_hud(struct Player *p);

// Player::RenderHud: see docs/formats/hud-render.md. The car is the
// camera's when CameraFollowDefaultCar is 0 and its driver is there, else
// the player's; the HUD's numbers (the gauges' ranges and angles, the
// engine's red line) are always the player's own car's.
void player_render_hud(struct Player *p);

// 0x0017d7c8, the port's name: the score title and total faded in over
// half a second from tScoreAnimation, held to four and a half, faded out
// by five and hidden, when tScoreAnimation goes back to 0x7fffffff.
void player_fade_score(struct Player *p);

// The best lap the HUD compares with: the player's record (the total time
// on a point-to-point race, the lap otherwise), or in a race of laps that
// is not a time trial the car's BestRunningTimes at the finish line
// (PreviousBestRunningTimes with `previous`) when that is set and either
// the record is not or the time is lower.
uint32_t player_get_current_best_lap_record(struct Player *p,
                                            int32_t previous);

// "+2000" as 2000, "-1000" as -1000: a leading sign, then the digits.
int32_t player_convert_score_string(struct Player *p, const char *s);

// The four debug strings, found on the HUD screen the first time; shown
// with DisplayPlayerDebugInfo, as the frame rates, the car's place and
// zone and its odometer, and hidden without it.
void player_display_debug_info(struct Player *p);

// The letter the HUD shows for a gear: A, R, N and 1 to 7 for -1 to 8,
// from the ten pairs at 0x002fbaf8, and X for anything else.
char get_letter_for_gear(int32_t gear);

// The countdown's tick: "TimerCountdown" played once each time the
// timer's whole seconds change.
void trigger_timer_warning_sound(const Timer *t);

// ------------------------------------------------------------- the data

// ScoreInfo, 36 bytes, the thirty at 0x002fbbf0 (eScoring order): the
// string id, the English name and the score as text. UpdateHud reads the
// score of entries 16 to 22, "TOOK 1ST PLACE" to "TOOK 7TH PLACE".
typedef struct ScoreInfo {
    int32_t NameId;                     //  0
    char    Name[20];                   //  4
    char    Score[12];                  // 24
} ScoreInfo;                            // 36

#define NUM_SCORE_INFOS     30
#define SCORING_START_BONUS 15
extern const ScoreInfo ScoreInfoTable[NUM_SCORE_INFOS];

// The tunables, at retail's values.
extern float   SpeedMinFactor;          // gp-20912  0.7
extern int32_t LiveUpdateSplitTimeRate; // gp-20944  0
extern float   TachTestRpm;             // gp-18380  100 means the car's
extern int32_t DisplayPlayerDebugInfo;  // gp-20700  0
// The two frame rates DisplayDebugInfo prints, 0x0032fe28 and 0x0032fe2c;
// the port's names. Nothing writes them.
extern float   DebugCpuFps;
extern float   DebugGpuFps;

// ----------------------------------------------------------------- seams
//
// The callees not yet ported (8m-4). NULL skips the call.

// GetTranslatedString(int), 0x0021e560. NULL, or a NULL answer, is "".
extern const char *(*gHudTranslateFn)(int32_t id);
// Player::HudDoAnimations (0x0017e038) and UpdateScoring (0x0017e820).
extern void (*gHudDoAnimationsFn)(struct Player *p);
extern void (*gUpdateScoringFn)(struct Player *p);
// Player::StartScore(eScoring, int), 0x0017e558.
extern void (*gStartScoreFn)(struct Player *p, int32_t scoring,
                             int32_t value);
// HudStartSpeedAnimation (0x0017cd30) and HudStartGrowAnimation
// (0x0017cb18): the two texts, the time and the flag.
extern void (*gHudStartSpeedAnimationFn)(struct Player *p,
                                         struct FlailerTextChunk *a,
                                         struct FlailerTextChunk *b,
                                         uint32_t time, int32_t flag);
extern void (*gHudStartGrowAnimationFn)(struct Player *p,
                                        struct FlailerTextChunk *a,
                                        struct FlailerTextChunk *b,
                                        uint32_t time, int32_t flag);
// UpdatePursuitMeter (0x0017c380), UpdateRadarDetector (0x0017be70) and
// DrawTracker (0x0017c278).
extern void (*gUpdatePursuitMeterFn)(struct Player *p, int32_t level);
extern void (*gUpdateRadarDetectorFn)(struct Player *p);
extern void (*gDrawTrackerFn)(struct Player *p, struct Car *c,
                              int32_t index);
// NISOverlayManager::Update(bool), 0x001825f0.
extern void (*gNisOverlayUpdateFn)(NISOverlayManager *o, int32_t playing);

#endif
