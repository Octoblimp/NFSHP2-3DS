// stomper -- the render eggs (TASKS 50b): the Stomper, retail 0x0024b918
// to 0x0024c420, and the five picture codes it carries out.
//
// A Stomper "stomps" globals: a render egg is a list of StompEntry, each a
// global and the value to put in it, or a function to call with 1 and a
// value, or another list. Set walks its egg's list, keeping each old value
// (or what the function returned) on its stack, 1 KB, a word an entry;
// Clear walks the list again in the same order and puts them back (a
// function is called with 0 and what it returned). There is one Stomper,
// pStomper (gp-14932), which InitStomper makes in InitializeEverything.
//
//   0x0024b918  StompEntry::Set (0x0024ba38 Clear, 0x0024bb20 SetAll,
//               0x0024bb78 ClearAll)
//   0x0024bbd0  InitStomper; 0x0024bc08 CloseStomper, which nothing calls
//   0x0024bc30  Stomper's constructor; 0x0024bc80 its destructor
//   0x0024bcd0  Stomper::Clear; 0x0024bd20 Set; 0x0024c3e8 ClearSet
//   0x0024bd78  Suspend (the egg's values back, the egg kept); 0x0024bdb0
//               Resume
//   0x0024bdc0  ResetRenderEggs (BeginGameFlowUnloadingTrackSpecific)
//   0x0024bf18  the port's name: the egg of the first picture code that is
//               on (EndGameFlowLoadingTrackSpecific, not for a demo)
//   0x0024bfc0  SuspendRenderEggs and 0x0024bfe0 ResumeRenderEggs, around
//               eDisplayFrame's mirror and HUD
//   0x0024c000  DisableRenderEggs (the AI demo's InitForRace); 0x0024c030
//               EnableRenderEggs, which nothing calls
//   0x0024c048  _GLOBAL_$I$StomperRenderEggs: the lists, built at boot; the
//               port's are initialised data
//
// The eggs, by eStomper, and their codes (eastereggs.h):
//    8  Motion Blur (code 0): RadialBlurOnOff (radialblur.h) on player 0,
//       so each frame's Resume turns the blur on again at 0 and 160
//    9  Black & White (1) and Video Mode (4): ForceBlackAndWhite (eview.h)
//   10  Heavy Fog (2): WeatherHeavyFog (weatherman.h)
//   11  R/C Car (3): CarRenderMatrix (carrenderinfo.h) at half size, and
//       the driver's big head, which needs the AnimatedDriver the port does
//       not have
//   12  Chrome Cars (8): the environment pass's ALPHA_2 (eview.h)
// 1 to 7 are the demo's eggs (CARTOON, WIRE_ORANGE, NEGATIVE_BLUE_FOG,
// NEGATIVE_CREAM_FOG, FLAT_ORANGE, BLUE_NIGHT, HOT_MAGENTA), which only
// RandomRenderEgg (0x0024bde0) sets, and nothing calls it: neither it nor
// their lists are ported, and their StomperTable slots are an empty list.
// UpdateStomper (0x0024bdb8) is empty.
//
// tools/stomper_check.py runs retail's code on the same scripts.
// Write-up: docs/formats/stomper.md.

#ifndef STOMPER_H
#define STOMPER_H

#include <stdint.h>

// eStomperTypes.
#define STOMP_INT8           0
#define STOMP_INT16          1
#define STOMP_INT32          2
#define STOMP_FLOAT          3
#define STOMP_FUNCTION_INT   4
#define STOMP_FUNCTION_FLOAT 5
#define STOMP_NESTED         6
#define STOMP_END            7

// eStomper. 1 to 7 are the demo's names; 8 to 12 are retail's and the
// port's.
#define STOMPER_NONE            0
#define STOMPER_MOTION_BLUR     8
#define STOMPER_BLACK_AND_WHITE 9
#define STOMPER_HEAVY_FOG       10
#define STOMPER_RC_CAR          11
#define STOMPER_CHROME          12
#define STOMPER_NUM             13

#define STOMPER_STACK_SIZE 1024

typedef int32_t (*StompFuncInt)(int32_t set, int32_t value);
typedef float   (*StompFuncFloat)(int32_t set, float value);

typedef struct StompEntry {
    int32_t nType;                          // 0  STOMP_*
    union {
        void                    *pData;
        StompFuncInt             pFuncInt;
        StompFuncFloat           pFuncFloat;
        const struct StompEntry *pNested;
    } u;                                    // 4
    union {
        int32_t nData;
        float   fData;
    } v;                                    // 8
} StompEntry;                               // 12 on the 3DS

typedef struct Stomper {
    int32_t  bEnabled;                      // 0  read by RandomRenderEgg only
    uint8_t *pStack;                        // 4  STOMPER_STACK_SIZE
    int32_t  nCurrent;                      // 8  the egg that is set
} Stomper;

// 0x0031d718, by eStomper; 0 is NULL.
extern const StompEntry *const StomperTable[STOMPER_NUM];

// gp-14932: InitStomper's.
extern Stomper *pStomper;

// The R/C Car's big head: what AnimatedDriver::Render (0x001a9a30) and
// the driver's bones read (animdriver.c, eanim.c). By the demo's names:
// OverrideAnimatedDriverLOD, gp-19244 (1: the driver's LOD no coarser
// than 1); nBoneScale, gp-19408 (-1); vBoneScale, 0x003110d0, whose x, y
// and z eAnimation.obj's static initialiser (0x001a71b0) sets to 1.
extern int32_t OverrideAnimatedDriverLOD;
extern int32_t nBoneScale;
extern float   vBoneScale[4];

// A StompEntry, or a list up to STOMP_END: each returns where the next
// save goes. An entry of any other type does nothing.
uint8_t *stompentry_set(const StompEntry *s, uint8_t *save);
uint8_t *stompentry_clear(const StompEntry *s, uint8_t *save);
uint8_t *stompentry_set_all(const StompEntry *s, uint8_t *save);
uint8_t *stompentry_clear_all(const StompEntry *s, uint8_t *save);

// The constructor: on, its stack bMalloc'd ("Stomper Stack", pool 16),
// no egg. The destructor frees the stack, and with bit 0 of `flags` the
// Stomper.
Stomper *stomper_construct(Stomper *s);
void     stomper_destroy(Stomper *s, int32_t flags);

// Clear puts back the egg's values, if one of 1 to 12 is set, and leaves
// none set. Set sets egg `e` from the stack's start, if it is 1 to 12;
// it does not clear the one set before. ClearSet is the two.
void stomper_clear(Stomper *s);
void stomper_set(Stomper *s, int32_t e);
void stomper_clear_set(Stomper *s, int32_t e);
// The egg's values back, and the egg still the one set; and set again.
void stomper_suspend(Stomper *s);
void stomper_resume(Stomper *s);

// InitStomper: pStomper, bMalloc'd ("Stomper", pool 16). CloseStomper.
void InitStomper(void);
void CloseStomper(void);

// Each does nothing with no pStomper.
void ResetRenderEggs(void);
// Eggs 0, 1, 2, 3, 4 and 8 in turn: the first that is on sets 8, 9, 10,
// 11, 9 or 12.
void SetRenderEggFromEasterEggs(void);
void SuspendRenderEggs(void);
void ResumeRenderEggs(void);
// Clear, and bEnabled 0.
void DisableRenderEggs(void);
void EnableRenderEggs(void);

#endif
