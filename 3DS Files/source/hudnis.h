// hudnis -- the rest of NISOverlayManager: the camcorder overlay a
// ticket, an arrest or a bust plays under, with its REC light, its date
// and time, BUSTED! and the bounty's points.
//
//   NISOverlayManager::Start                      0x00182488    360 bytes
//   NISOverlayManager::Update(bool)               0x001825f0    344 bytes
//   NISOverlayManager::UpdateDateAndTime          0x00182748    512 bytes
//   NISOverlayManager::SetVisible(int)            0x00182a48    368 bytes
//   NISOverlayManager::StartArrest                0x001832f8     16 bytes
//   NISOverlayManager::StartTicket                0x00183308     16 bytes
//   NISOverlayManager::StartBusted                0x00228f10     16 bytes
//
// nisoverlay.c has the constructor, the destructor, SetScreen and Finish.
// RenderHud (hudrender.c) calls Update through gNisOverlayUpdateFn, and
// SetHudFeatures (playerhud.c) SetVisible through gNisOverlaySetVisibleFn.
// Player::PlayNextNis calls StartTicket and StartArrest, and
// Player::StartBustedDisplay StartBusted; they come with the NIS.
//
// The two functions retail placed after SetVisible (0x00182bb8 and
// 0x00182c18, which lay out Player's pFlailerScore texts) are called from
// nowhere, and no data holds their addresses, so they are left out.
//
// Step 8m-4c-2. Written up in docs/formats/hud-nis.md; checked on
// retail's image by tools/hudnis_check.py.

#ifndef HUDNIS_H
#define HUDNIS_H

#include <stdint.h>

#include "nisoverlay.h"

// The overlay screen's objects, besides NISOVERLAY_BUSTED_OBJECT.
#define NISOVERLAY_POINTS_OBJECT 0x233dfbe1u   // "+2000", the bounty
#define NISOVERLAY_DATE_OBJECT   0x001450ddu
#define NISOVERLAY_TIME_OBJECT   0x001d380eu
#define NISOVERLAY_REC_LIGHT     0x61cb41dfu   // the bitmap that blinks
#define NISOVERLAY_FRAME         0x9aba325eu   // the bitmap over it all
#define NISOVERLAY_GROUP         0x97f9252au

// sceCdCLOCK, in BCD as the drive's clock gives it.
typedef struct NisClock {
    uint8_t stat;
    uint8_t second;
    uint8_t minute;
    uint8_t hour;
    uint8_t pad;
    uint8_t day;
    uint8_t month;
    uint8_t year;
} NisClock;

// 0x00182488. Nothing without a screen. Otherwise LastDateTimeUpdate is
// cleared and the date and time printed; the screen is shown; BustedDisplay
// and PointsDisplay are found; sx, sy, ScaleX and ScaleY take BUSTED!'s
// top left and scale; and the two tracks start: the scale from 5 to ScaleX
// and the alpha from 0 to 128, each over a quarter second.
void nisoverlay_start(NISOverlayManager *o);

// 0x001825f0. With BustedDisplay: its top to sy, its y scale to ScaleY,
// then scaled about its centre by the scale track, and both it and
// PointsDisplay given the alpha track's value. Both tracks then step by
// WorldTimeElapsed. The date and time are printed again 31 frames on. The
// REC light shows only while playing and while WorldTimeFrames has bit 3
// clear; the frame shows only while playing.
void nisoverlay_update(NISOverlayManager *o, int32_t playing);

// 0x00182748. Reads the clock; when that fails, or its status is not 0,
// nothing else. Otherwise prints the date, "%s %d 20%02d" in English and
// "%d %s 20%02d" in any other language, with the month's name from the
// language tables (0xe86c to 0xe877), and the time "%02d:%02d:%02d".
// LastDateTimeUpdate takes RealTimeFrames.
void nisoverlay_update_date_and_time(NISOverlayManager *o);

// 0x00182a48. Nothing without a screen, nor in a replay (INSTANT_REPLAY,
// AUTO_REPLAY, POSTRACE or a replay demo). `on` 0 hides the group. Shown
// for a ticket or an arrest, the group shows; for a bust, the group hides
// and BUSTED! shows. Either way the points show only to the cop of a
// one-player race. Idle shows nothing.
void nisoverlay_set_visible(NISOverlayManager *o, uint32_t on);

// 0x001832f8, 0x00183308 and 0x00228f10: State, then Start.
void nisoverlay_start_arrest(NISOverlayManager *o);
void nisoverlay_start_ticket(NISOverlayManager *o);
void nisoverlay_start_busted(NISOverlayManager *o);

// sceCdReadClock (0x0028dc48): 1 with the clock read, 0 without. NULL is
// 0, and nothing is printed.
extern int32_t (*gCdReadClockFn)(NisClock *c);
// sceScfGetLocalTimefromRTC (0x002961d8): the PS2's clock, kept in Japan's
// time, moved to the console's zone. NULL leaves the clock as read, which
// is right for the 3DS, whose clock is local already.
extern void (*gScfGetLocalTimeFn)(NisClock *c);

#endif
