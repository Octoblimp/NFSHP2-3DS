#pragma once
#include <stdint.h>

#include "bmenu.h"
#include "gameflow.h"

// Options' Credits (TASKS 71a), retail's in three callbacks:
//
//   "Credits"               CreditsScreen (0x001f1f38 .. 0x001f21b0): the
//                           menu. Electronic Arts, Black Box Games, View
//                           Intro Movie, The Making of HP2, View Reward
//                           Movie -- the last hidden until both trees'
//                           Ultimates are won (0x002026f8).
//   "EACredits"             CreditsScroller (0x001f2e80 .. 0x001f3320):
//   "BBGCredits"            the names rolling up the panel over a
//                           crossfading slideshow, CREDITS_BG1..8.
//   "Credits FE Movie"      the movie player (0x001f2240 .. 0x001f2470),
//   "Credits Reward movie"  on the title screen's planes: the intro, the
//   "BBG Creation movie"    reward, the making-of, and Black Box's logo,
//   "BBG Credits movie"     which goes on to its scroller.
//
// docs/formats/credits.md has the details.

// FlailerScreenConfig's hashes.
#define CREDITS_SCREEN          0xfd8a3b6du   // "Credits"
#define CREDITS_SCROLLER_SCREEN 0x39c4c62cu   // "EACredits", "BBGCredits"

// Callback (0x001f21b0), for "Credits".
void credits_screen_callback(BGameFlow* gf, BScreenMessage msg,
                             BScreenCallbackData* data);

// Callback (0x001f3320), for "EACredits" and "BBGCredits".
void credits_scroller_callback(BGameFlow* gf, BScreenMessage msg,
                               BScreenCallbackData* data);

// Callback (0x001f2470), for the four movie screens.
void credits_movie_callback(BGameFlow* gf, BScreenMessage msg,
                            BScreenCallbackData* data);

// The markup parser (0x001f2808), for the checker: `src` with its $RGB(..)
// and $FONT(..) tags taken out into `buf` (`len` bytes, zeroed first),
// and the colour and the font's hash they named (each left as it was when
// its tag is absent). "$$" is a dollar.
void credits_parse(uint32_t* color, uint32_t* font, char* buf, int len,
                   const char* src);
