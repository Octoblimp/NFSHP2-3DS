// hudscore -- the race's bonus scores: what earns one, its sound, and the
// two texts that fly in and count it into the total.
//
//   PlayScoreSound(eScoring)                       0x00175100    212 bytes
//   Player::StartScoreAnimation                    0x0017d370   1108 bytes
//   Player::GetFinishBonus                         0x0017e2d0    128 bytes
//   Player::StartScore(eScoring)                   0x0017e3b0    420 bytes
//   Player::StartScore(eScoring, int)              0x0017e558    400 bytes
//   Player::UpdateScoring                          0x0017e820   1228 bytes
//
// A score is a ScoreInfoTable entry (hudrender.h): its title, translated,
// goes into strEventTitle and its "+2000" into strEventScore, and
// StartScoreAnimation flies both in on the HUD screen's event texts in
// slots 10 and 11. When slot 10's text ends, HudDoAnimations adds its
// score to TotalScore; a score that starts while one is still flying adds
// the old one at once.
//
// UpdateScoring runs every frame from UpdateHud and hands out the scores
// the HUD earns itself: a clean lap, leading a lap, a clean segment, a new
// top speed, air time, and each place taken. The car's own collisions,
// read from its body, decide what is clean. The cops (tCopManager,
// tPursuit) and the frontend's bonus points call StartScore and
// GetFinishBonus too, when they come.
//
// Retail's StartScore() (0x0017e6e8), the animation at the default place
// with no text set, has no caller and no data names it; the port leaves it
// out.
//
// Step 8m-4b. Written up in docs/formats/hud-score.md; checked on retail's
// image by tools/hudscore_check.py.

#ifndef HUDSCORE_H
#define HUDSCORE_H

#include <stdint.h>

#include "bvector.h"

struct Player;

// eScoring, ScoreInfoTable's order. Retail keeps no names for them; these
// are the table's English ones.
#define SCORING_BEAT_THE_COPS       0
#define SCORING_RESET_CAR           1
#define SCORING_HIT_COP_CAR         2
#define SCORING_CLEAN_LAP           3
#define SCORING_LED_FIRST_LAP       4
#define SCORING_LED_A_LAP           5
#define SCORING_TOP_SPEED           6
#define SCORING_CLEAN_SEGMENT       7
#define SCORING_DODGE_ROADBLOCK     8
#define SCORING_SMASH_ROADBLOCK     9
#define SCORING_SMACK              10
#define SCORING_AIR                11
#define SCORING_BIG_AIR            12
#define SCORING_HUGE_AIR           13
#define SCORING_DRIFT              14
// SCORING_START_BONUS, 15, is hudrender.h's.
#define SCORING_TOOK_1ST_PLACE     16   // to 22, TOOK 7TH PLACE
#define SCORING_1ST_PLACE_BONUS    23
#define SCORING_2ND_PLACE_BONUS    24
#define SCORING_3RD_PLACE_BONUS    25
#define SCORING_SPEED_BUSTED       26
#define SCORING_QUOTA_FILLED       27
#define SCORING_BLEW_THE_TIRES     28
#define SCORING_BLEW_YOUR_TIRES    29

// PlayScoreSound: "ScorePoints" for BEAT THE COPS, TOOK 1ST PLACE, TOP
// SPEED and QUOTA FILLED, when the sound is on, the race is not in a
// replay, the post-race or a replay demo, and the sample is not playing
// already. Retail reads pRaceCoordinator with no test; the port plays
// nothing without one.
void play_score_sound(int32_t scoring);

// Player::StartScoreAnimation: strEventScore's text (slot 10) from pos by
// dpos, then on by dpos2, and strEventTitle's (slot 11) 20 above it, each
// at scale, faded in from 0 by 128 and out from 64 by -64, coloured from
// colour by dcolour, over half a second, half a second and a second. A
// running slot 10 first adds strPrevScore to the total, and strPrevScore
// becomes strEventScore. With two players each half's y is halved, and
// moved down 40 for the first player and 280 for the second. Stamps
// tScoreAnimation with WorldTimer.
void player_start_score_animation(struct Player *p, const bVector2 *pos,
                                  const bVector2 *dpos,
                                  const bVector2 *dpos2,
                                  const bVector2 *scale,
                                  const bVector2 *dscale,
                                  const bVector4 *colour,
                                  const bVector4 *dcolour);

// Player::GetFinishBonus: the 1ST, 2ND and 3RD PLACE BONUS scores for
// places 1 to 3 (10000, 5000, 2500), and 0 for any other.
int32_t player_get_finish_bonus(struct Player *p, int32_t place);

// Player::StartScore(eScoring): the sound, the entry's score and title,
// and the animation from (530, 236) toward (620, 136) at 0.7.
void player_start_score(struct Player *p, int32_t scoring);

// Player::StartScore(eScoring, int): the same with strEventScore as the
// caller left it. The value is not read.
void player_start_score_value(struct Player *p, int32_t scoring,
                              int32_t value);

// Player::UpdateScoring: see docs/formats/hud-score.md. While the car
// blinks (a reset), only HangTime cleared and bResetGlare set.
void player_update_scoring(struct Player *p);

#endif
