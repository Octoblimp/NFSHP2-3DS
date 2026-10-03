// hudanim -- the HUD's animations: HudAnimator, and the Player functions
// that start, run and clear them.
//
//   HudAnimator::HudAnimator                       0x0023b0f8    112 bytes
//   HudAnimator::~HudAnimator                      0x0023b168     28 bytes
//   HudAnimator::StartAnimation (the scored text)  0x0023b1e0    696 bytes
//   HudAnimator::StartAnimation (text)             0x0023b498    328 bytes
//   HudAnimator::StartAnimation (bitmap)           0x0023b5e0    284 bytes
//   HudAnimator::DoAnimation(Timer)                0x0023b788    704 bytes
//   HudAnimator::DoAnimation(Timer *, char *)      0x0023bb58   1032 bytes
//   HudAnimator::FinishAnimation                   0x0023bf60    416 bytes
//   Player::ClearHudAnimations                     0x0017c7c8    192 bytes
//   Player::HudStartWrongWay                       0x0017c888    656 bytes
//   Player::HudStartGrowAnimation                  0x0017cb18    536 bytes
//   Player::HudStartSpeedAnimation                 0x0017cd30    648 bytes
//   Player::HudStartAnimation (text)               0x0017cfb8    376 bytes
//   Player::HudStartAnimation (bitmap)             0x0017d130    384 bytes
//   Player::HudDoAnimations                        0x0017e038    488 bytes
//   Player::AddToTotalScore                        0x0017e350     96 bytes
//
// A HudAnimator moves one Flailer object from a start to an end: its top
// left, its scale and its alpha, and a text's colour, each a straight line
// over the time the animation was given. The Player holds twenty, made on
// demand in pHudAnimations. A slot belongs to one effect:
//
//    0  the big race position's grow (HudStartGrowAnimation)
//    1  the speed's grow (HudStartSpeedAnimation)
//   10  the score that counts into the total (StartScoreAnimation, 8m-4b)
//   11  the score's title
//   15  WRONG WAY (HudStartWrongWay)
//
// and the pursuit meter and the radar use more (8m-4c).
//
// Nothing in retail calls HudStartBlink (0x0017d2b0), StartBlink
// (0x0023b700), DoAnimation(Timer, float) (0x0023ba48), SetVisibility
// (0x0023b188) or StartMusicTitleAnimation (0x0017da00), and no data
// holds their addresses, so the port leaves them out.
//
// Every time an animation is given is ignored. Each start reads WorldTimer
// itself (or RealTimer, for a scored text that asks), and DoAnimation(Timer)
// reads WorldTimer in place of its argument; only the scored DoAnimation
// reads the timer it is handed.
//
// Step 8m-4a. Written up in docs/formats/hud-anim.md; checked on retail's
// image by tools/hudanim_check.py.

#ifndef HUDANIM_H
#define HUDANIM_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "timer.h"

struct FlailerBitmapChunk;
struct FlailerTextChunk;
struct Player;

#define HUDANIM_SIMPLE 1    // a text or a bitmap, one phase
#define HUDANIM_BLINK  2    // StartBlink's; nothing live makes one
#define HUDANIM_SCORED 3    // a text in three phases: in, hold, out

// 288 bytes, bMalloc(288, 16). The constructor sets Colour to (128, 64, 0,
// 0) and clears DeltaColour, bHasString, New68, the two objects, bActive,
// bKeepVisible, bRealTimer and Type; the rest is the heap's.
typedef struct HudAnimator {
    char     String[64];                //   0  a scored text's own, or ""
    int32_t  bHasString;                //  64  show String, not the caller's
    int32_t  New68;                     //  68  cleared; nothing reads it
    struct FlailerTextChunk   *pText;   //  72
    struct FlailerBitmapChunk *pBitmap; //  76
    bVector2 Pos;                       //  80  the top left at the start
    bVector2 DeltaPos;                  //  88  to the end (phase 0's)
    uint8_t  _pad96[4];                 //  96
    bVector2 Scale;                     // 100
    bVector2 DeltaScale;                // 108
    uint8_t  _pad116[4];                // 116
    int32_t  Alpha;                     // 120
    float    DeltaAlpha;                // 124
    // A scored text's: phase 1 holds Pos + DeltaPos at Scale1, Alpha1 and
    // Colour3 + DeltaColour3, and phase 2 moves on from there.
    bVector2 DeltaPos2;                 // 128
    bVector2 Scale1;                    // 136
    bVector2 DeltaScale2;               // 144
    int32_t  Alpha1;                    // 152
    float    DeltaAlpha2;               // 156
    // A simple text's colour, r g b in x y z, 128 for full. A simple start
    // makes it (128, 64, 0) to (128, 128, 128).
    bVector4 Colour;                    // 160
    bVector4 DeltaColour;               // 176
    uint8_t  _pad192[16];               // 192  StartBlink's two floats
    bVector4 Colour3;                   // 208  a scored text's
    bVector4 DeltaColour3;              // 224
    float    Duration[3];               // 240  in seconds; [0] for simple
    float    StartSeconds;              // 252  the timer's, in seconds
    int32_t  Phase;                     // 256  a scored text's, 0 to 2
    int32_t  bActive;                   // 260
    int32_t  bKeepVisible;              // 264  a bitmap left up at the end
    int32_t  bRealTimer;                // 268  a scored text on RealTimer
    int32_t  Type;                      // 272  HUDANIM_*
    uint8_t  _pad276[12];               // 276
} HudAnimator;                          // 288

typedef char hudanim_layout_check[
    (sizeof(void *) != 4
     || (offsetof(HudAnimator, bHasString) == 64
         && offsetof(HudAnimator, pText) == 72
         && offsetof(HudAnimator, Pos) == 80
         && offsetof(HudAnimator, Scale) == 100
         && offsetof(HudAnimator, Alpha) == 120
         && offsetof(HudAnimator, DeltaPos2) == 128
         && offsetof(HudAnimator, DeltaAlpha2) == 156
         && offsetof(HudAnimator, Colour) == 160
         && offsetof(HudAnimator, Colour3) == 208
         && offsetof(HudAnimator, Duration) == 240
         && offsetof(HudAnimator, StartSeconds) == 252
         && offsetof(HudAnimator, Type) == 272
         && sizeof(HudAnimator) == 288))
    ? 1 : -1];

// -------------------------------------------------------------- HudAnimator

// The constructor, 0x0023b0f8.
void hudanim_init(HudAnimator *a);

// `new HudAnimator`: bMalloc(288, 16) and the constructor.
HudAnimator *hudanim_new(void);

// The deleting destructor, 0x0023b168, with 3: bFree.
void hudanim_delete(HudAnimator *a);

// StartAnimation (0x0023b1e0): a scored text in three phases of d0, d1
// and d2 seconds. Phase 0 moves from pos by dpos, scales from scale by
// dscale, fades from alpha by dalpha and colours from colour by dcolour;
// phase 1 holds the end, at scale1 and alpha1; phase 2 moves on by dpos2,
// scales from scale1 by dscale2 and fades from alpha1 by dalpha2. A string
// that is not NULL is the one shown (bounded to 63 characters; retail's
// bSPrintf has no bound), and otherwise the caller of DoAnimation names
// one. The start is RealTimer's with real_timer, WorldTimer's without.
// The text, when there is one, goes to the start at once and is shown.
void hudanim_start_scored(HudAnimator *a, struct FlailerTextChunk *t,
                          const bVector2 *pos, const bVector2 *dpos,
                          const bVector2 *dpos2, const bVector2 *scale,
                          const bVector2 *dscale, int32_t alpha,
                          float dalpha, const bVector4 *colour,
                          const bVector2 *scale1, const bVector2 *dscale2,
                          int32_t alpha1, float dalpha2,
                          const bVector4 *dcolour, float d0, float d1,
                          float d2, const char *s, int32_t real_timer);

// StartAnimation (0x0023b498): a simple text, restarted whether it runs or
// not, from pos, scale and alpha by the deltas over `duration` seconds,
// coloured from (128, 64, 0) to (128, 128, 128). The text goes to the
// start and is shown. Retail writes through a NULL text; the port skips
// the text.
void hudanim_start_text(HudAnimator *a, struct FlailerTextChunk *t,
                        const bVector2 *pos, const bVector2 *dpos,
                        const bVector2 *scale, const bVector2 *dscale,
                        int32_t alpha, float dalpha, float duration);

// StartAnimation (0x0023b5e0): a simple bitmap, unless the animator is
// already running, which leaves it be (with Type made simple). keep leaves
// the bitmap shown at the end. Retail writes through a NULL bitmap; the
// port skips the bitmap.
void hudanim_start_bitmap(HudAnimator *a, struct FlailerBitmapChunk *b,
                          const bVector2 *pos, const bVector2 *dpos,
                          const bVector2 *scale, const bVector2 *dscale,
                          int32_t alpha, float dalpha, float duration,
                          int32_t keep);

// DoAnimation(Timer), 0x0023b788: a running simple animation's frame on
// WorldTimer. A text takes the colour too; at the end a text is hidden,
// and a bitmap set to its last alpha and hidden unless kept. Answers 0.
int32_t hudanim_do(HudAnimator *a);

// DoAnimation(Timer *, char *), 0x0023bb58: a running scored text's frame
// on *time, showing String if it has one and `s` if not. Answers 1 on the
// frame phase 2 ends, when the text is hidden, and 0 otherwise.
int32_t hudanim_do_scored(HudAnimator *a, const Timer *time, const char *s);

// FinishAnimation, 0x0023bf60: a simple text hidden, a simple bitmap put
// at its end (hidden unless kept), a blink's bitmap at its first alpha, a
// scored text hidden.
void hudanim_finish(HudAnimator *a);

// ------------------------------------------------------------------ Player

// Player::ClearHudAnimations: every animation finished but 12 to 14 and
// 18. A running score (slot 10) first adds strPrevScore to the total.
void player_clear_hud_animations(struct Player *p);

// Player::HudStartWrongWay: the HUD screen's WRONG WAY bitmap (0x89af1a1e)
// in slot 15, from (258, 119) toward the top left at alpha 64 for a
// second, kept up. The end moves with a free run and with the live split
// in place of the position; two players' halves have their own.
void player_hud_start_wrong_way(struct Player *p);

// Player::HudStartGrowAnimation, slot 0: `a` from b's place, scale and
// alpha. With grow, 30 up, scaled to 2 and faded out in half a second;
// without, 100 down, scaled to 0.5 and faded in from 0 in a second.
void player_hud_start_grow_animation(struct Player *p,
                                     struct FlailerTextChunk *a,
                                     struct FlailerTextChunk *b,
                                     uint32_t time, int32_t grow);

// Player::HudStartSpeedAnimation, slot 1, with a speed string on the HUD:
// `a` from b's place and scale, faded out in a second. With grow, scaled
// to 2 about b's centre; without, 100 down and scaled to 0.5.
void player_hud_start_speed_animation(struct Player *p,
                                      struct FlailerTextChunk *a,
                                      struct FlailerTextChunk *b,
                                      uint32_t time, int32_t grow);

// Player::HudStartAnimation, the text's and the bitmap's: slot `slot`
// (made on demand) from `from` to `to`, scale_from to scale_to and
// alpha_from to alpha_to over `duration` seconds.
void player_hud_start_text_animation(struct Player *p, int32_t slot,
                                     struct FlailerTextChunk *t,
                                     const bVector2 *from,
                                     const bVector2 *to,
                                     const bVector2 *scale_from,
                                     const bVector2 *scale_to,
                                     int32_t alpha_from, int32_t alpha_to,
                                     float duration, uint32_t time);
void player_hud_start_bitmap_animation(struct Player *p, int32_t slot,
                                       struct FlailerBitmapChunk *b,
                                       const bVector2 *from,
                                       const bVector2 *to,
                                       const bVector2 *scale_from,
                                       const bVector2 *scale_to,
                                       int32_t alpha_from, int32_t alpha_to,
                                       float duration, uint32_t time,
                                       int32_t keep);

// Player::HudDoAnimations: a frame of each running animation. Slot 0 runs
// only with the race position on the HUD and slot 1 only with a gauge;
// 2 to 8, 15, 16 and 17 always. 10 to 13 are scored texts: 10 shows
// strEventScore and adds it to the total when it ends, 11 strEventTitle,
// 12 "SCORE" and 13 "". 9, 14, 18 and 19 never run.
void player_hud_do_animations(struct Player *p);

// Player::AddToTotalScore: ConvertScoreString's value added to TotalScore,
// which stops at 0, and the total printed into the HUD's score total.
void player_add_to_total_score(struct Player *p, const char *s);

#endif
