// nisoverlay -- NISOverlayManager, the HUD overlay a ticket, an arrest or
// a bust plays over, and the four of its methods the Player's lifetime
// reaches. The addresses are retail's.
//
// Every Player holds one at 2560 (mFlailerNIS). The constructor
// (0x00182350) builds its two animation tracks, SetScreen (0x001829a8,
// new in retail) takes the overlay's Flailer screen and reads the BUSTED
// text's authored scale and top, and Finish (0x00182948) hides the screen
// and puts the text back as SetScreen found it. Start, Update,
// UpdateDateAndTime, SetVisible and the three Start* that play the overlay
// are in hudnis.c.
//
// Every Flailer call here is a seam, as these four were ported before the
// Flailer runtime; see each.
//
// Written up in docs/formats/player.md; checked on retail's image by
// tools/player_check.py.

#ifndef NISOVERLAY_H
#define NISOVERLAY_H

#include <stddef.h>
#include <stdint.h>

#include "banim.h"

struct FlailerObjectChunk;

// eFLAILER_NIS, from the demo's .mdebug.
#define FLAILER_NIS_IDLE    0
#define FLAILER_NIS_TICKET  1
#define FLAILER_NIS_ARREST  2
#define FLAILER_NIS_BUSTED  3

// The object SetScreen and Finish work on, in the overlay's screen.
#define NISOVERLAY_BUSTED_OBJECT 0x76494c5bu

// 56 bytes in retail. The demo's (.mdebug type#3487) is 40: retail added
// PointsDisplay at 24, which moved sx .. ScaleY down by 4, and the three
// words SetScreen fills. The tracks are tCubic1D, which banim.h ports as
// BSpline (48 bytes). Retail has no symbols; the new names are the port's.
typedef struct NISOverlayManager {
    uint32_t  LastDateTimeUpdate;               //  0
    uint32_t  ScreenHash;                       //  4
    int32_t   State;                            //  8  FLAILER_NIS_*
    BSpline  *ScaleAnimationTrack;              // 12
    BSpline  *AlphaAnimationTrack;              // 16
    struct FlailerObjectChunk *BustedDisplay;   // 20  the BUSTED text
    struct FlailerObjectChunk *PointsDisplay;   // 24  the bounty's "+2000"
    float     sx;                               // 28
    float     sy;                               // 32
    float     ScaleX;                           // 36
    float     ScaleY;                           // 40
    // Retail's: the BUSTED text's scale and top as SetScreen read them,
    // which Finish puts back.
    float     SavedScaleX;                      // 44
    float     SavedScaleY;                      // 48
    float     SavedTopLeftY;                    // 52
} NISOverlayManager;                            // 56

typedef char nisoverlay_layout_check[
    (sizeof(void *) != 4
     || (offsetof(NISOverlayManager, BustedDisplay) == 20
         && offsetof(NISOverlayManager, sx) == 28
         && offsetof(NISOverlayManager, ScaleY) == 40
         && offsetof(NISOverlayManager, SavedTopLeftY) == 52
         && sizeof(NISOverlayManager) == 56))
    ? 1 : -1];

// 0x00182350. Zeroes ScreenHash, State, sx and sy, makes ScaleX and ScaleY
// 1, and bMallocs the two tracks (48, "NISCubicAnimation", 0, 16), scale
// first. Each track is tCubic1D's constructor inlined: the values zeroed,
// duration and threshold 1, state 0 and flags 1; the coefficients and
// the time are left. LastDateTimeUpdate, BustedDisplay and PointsDisplay are
// left too.
NISOverlayManager *nisoverlay_init(NISOverlayManager *o);

// 0x00182430. Frees both tracks, and the overlay too when bit 0 of
// `flags` is set. Neither is tested for NULL; bFree takes it.
void nisoverlay_destroy(NISOverlayManager *o, int32_t flags);

// 0x001829a8. ScreenHash = `screen`. Then FlailerGetScale twice, each from
// a 1.0 pair, keeping the x of the first and the y of the second, and
// FlailerGetTopLeftY, all on NISOVERLAY_BUSTED_OBJECT. With the seams NULL
// the scales stay 1.0 and the top is 0.
void nisoverlay_set_screen(NISOverlayManager *o, uint32_t screen);

// 0x00182948. With a screen, hides it (SetFlailerScreenVisibility, 1 is
// INVISIBLE), then, if BustedDisplay is set, gives it back the saved
// scale and top.
void nisoverlay_finish(NISOverlayManager *o);

// ---------------------------------------------------------------- the seams

// FlailerGetScale (0x001444e8): the object's scale into the two, or the
// two left alone if there is no such object.
extern void (*gFlailerGetScaleFn)(uint32_t screen, uint32_t object,
                                  float *sx, float *sy);
// FlailerGetTopLeftY (0x00144168), the float one: 0 for no such object.
extern float (*gFlailerGetTopLeftYFn)(uint32_t screen, uint32_t object);
// FlailerObjectChunk::SetScaleX (0x001407d0), SetScaleY (0x001407f8) and
// SetTopLeftY (0x00140a48), the float one.
extern void (*gFlailerChunkSetScaleXFn)(struct FlailerObjectChunk *o,
                                        float sx);
extern void (*gFlailerChunkSetScaleYFn)(struct FlailerObjectChunk *o,
                                        float sy);
extern void (*gFlailerChunkSetTopLeftYFn)(struct FlailerObjectChunk *o,
                                          float y);

#endif
