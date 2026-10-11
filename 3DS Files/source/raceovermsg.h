// raceovermsg -- Player.obj from retail: the race-over overlay's message,
// the line under the race's name when the player's race is over.
//
//   FormatFinishPositionForRaceOverOverlay   0x00181498   100 bytes
//   FormatTimeForRaceOverOverlay             0x00181500    88 bytes
//   Player::FillInRaceOverMessages           0x00181558   876 bytes
//
// SetHudFeatures (playerhud.c) runs FillInRaceOverMessages when the HUD's
// RACE_OVER feature comes on. Slice RE-2c. docs/formats/race-over-overlay.md
// has the decode, and tools/raceover_check.py checks it on retail's image.

#ifndef RACEOVERMSG_H
#define RACEOVERMSG_H

#include <stdint.h>

#include "timer.h"

struct Player;

// The overlay's message group on the HUD's screen.
#define RACE_OVER_MESSAGE_GROUP 0xc707e093u

// The place's word ("0th", "1st" .. "8th", the table at 0x002fc028) put
// into the string `id` by bSPrintf. Retail reads past the table for a place
// outside 0 to 8; the port puts "" in.
void race_over_format_finish_position(char *buf, int32_t place, int32_t id);

// The time, rounded to the hundredth by PrintToString(char *, float, int),
// put into the string `id` by bSPrintf.
void race_over_format_time(char *buf, const Timer *t, int32_t id);

// The message for the player's car's RacingCar, by RaceType and the car's
// FinishReason (docs/formats/race-over-overlay.md has the table), wrapped
// into RACE_OVER_MESSAGE_GROUP on the player's HudScreenHash. Where retail
// has no message it renders its stack's leftovers; the port renders "".
void player_fill_in_race_over_messages(struct Player *p);

// --------------------------------------------------------------- the seams

// GetTranslatedString(int) (0x0021e560). NULL, or a NULL answer, is "".
extern const char *(*gRaceOverTranslateFn)(int32_t id);

// MaybeDoKnockoutRaceOverSpeech(Player *, bool) (0x00207018), with 1 when
// the player goes on to the next race. 14-10c's; NULL says nothing.
extern void (*gMaybeDoKnockoutRaceOverSpeechFn)(struct Player *p,
                                                int32_t advances);

#endif
