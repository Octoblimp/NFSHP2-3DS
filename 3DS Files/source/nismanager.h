// nismanager -- the NisManager's state: how a player's NIS starts, how
// long it plays and how it stops (retail 0x001b0fe0 .. 0x001b175c).
//
// Each player has one, bMalloc(320) in the Player constructor and named
// "Player%d" for the other player's number. A pullover that plays a NIS
// (Player::PlayNextNis, playernis.h) Starts it with the NIS's number from
// the NisInfo table, a camera and the two cars; it plays from
// WorldTimeFrames for twice the NIS's NumFrames (the table counts at 30 a
// second, WorldTimeFrames at 60), and Player::ServiceNis Stops it once
// WorldTimeFrames reaches EndTime, which is what ends the pullover.
//
// What is ported is the record and the calls that keep it: the
// constructor and destructor, Start, Stop, AllowDebugLooping, the load
// check Start makes (0x001b16e0), EnsureNisIsLoaded and Unload
// (0x001b1658). The rest -- loading the NIS's .BIN and .CAM files, posing
// the cars and the two characters, animating them, the NIS's camera
// coordinator, its sound events and its replay snapshot -- is the NIS
// player's, which the port does not have yet: those calls are the seams
// below, and with them unbound a NIS plays for its time with nothing to
// show but the camcorder overlay (hudnis.h).
//
// See docs/formats/nis.md; tools/nis_check.py runs these against retail.

#ifndef NISMANAGER_H
#define NISMANAGER_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bvector.h"
#include "scenery.h"

struct Car;
struct ResourceFile;

// NisModelInfo, 48 bytes (.mdebug type#3354): a character's animation and
// where it stands.
typedef struct NisModelInfo {
    void     *pAnimation;                   //  0
    uint8_t   _pad4[12];                    //  4
    bVector3  Offset;                       // 16
    struct Car *pCarWeStoleAnimationFrom;   // 32
    uint8_t   _pad36[12];                   // 36
} NisModelInfo;

// NisRenderInfo, 112 bytes (.mdebug type#3360).
typedef struct NisRenderInfo {
    int32_t   NumFrames;                    //  0
    float     fElevation;                   //  4
    uint8_t   _pad8[8];                     //  8
    NisModelInfo PlayerModelInfo;           // 16
    NisModelInfo OtherModelInfo;            // 64
} NisRenderInfo;

// NisManager, 320 bytes. The demo's (.mdebug type#3375) names the fields;
// retail added the player's number at 32, which moves Name through
// PlayerCarMovementModeBeforeNIS on by four into the demo's hole at 108.
typedef struct NisManager {
    bNode     Node;                         //   0  on NisManagerList
    int32_t   PrevSoundEventFrame;          //   8
    int32_t   LoadedNisNumber;              //  12  -1 for none
    int32_t   LoadingNisNumber;             //  16  -1 for none
    int32_t   LoadNisNumber;                //  20  -1 for none
    struct ResourceFile *NisResourceFile;   //  24
    struct ResourceFile *CamResourceFile;   //  28
    int32_t   PlayerNumber;                 //  32  retail's
    char      Name[32];                     //  36  "Player%d"
    int32_t   Playing;                      //  68
    int32_t   StartTime;                    //  72  WorldTimeFrames
    int32_t   EndTime;                      //  76  WorldTimeFrames
    int32_t   NisNumber;                    //  80  -1 for none
    int32_t   CamNumber;                    //  84
    struct Car *PlayerCar;                  //  88
    struct Car *OtherCar;                   //  92
    int32_t   Animating;                    //  96
    int32_t   ViewsWatchingNis;             // 100
    int32_t   OtherCarMovementModeBeforeNIS;    // 104
    int32_t   PlayerCarMovementModeBeforeNIS;   // 108
    NisRenderInfo NisRendInfo;              // 112
    eModel    PlayerCharProps[2];           // 224
    eModel    OtherCharProps[2];            // 272
} NisManager;                               // 320

#if UINTPTR_MAX == 0xffffffffu
_Static_assert(sizeof(NisManager) == 320, "NisManager is 320 bytes");
_Static_assert(offsetof(NisManager, Playing) == 68
               && offsetof(NisManager, EndTime) == 76
               && offsetof(NisManager, CamNumber) == 84
               && offsetof(NisManager, NisRendInfo) == 112
               && offsetof(NisManager, PlayerCharProps) == 224
               && offsetof(NisManager, OtherCharProps) == 272,
               "NisManager's offsets are retail's");
#endif

// NisManager::NisManagerList, gp-18840: every manager, in the order they
// were made.
extern bNode NisManagerList;

// The constructor, 0x001b0fe0, on `mem`: the four ResourceFile and load
// numbers cleared (the numbers to -1), PlayerNumber, the name copied
// unbounded (bStrCpy), NisNumber -1, everything else Start and the
// renderer read 0 -- the render info's frame count, the two characters'
// animations, offsets and cars, and the four props' name hash and solid --
// and the manager added at the tail of NisManagerList.
// InitSoundEvents (0x001b0fd0) is empty. PrevSoundEventFrame and the
// render info's fElevation are left as the memory was. Returns `mem`.
NisManager *nismanager_construct(void *mem, const char *name,
                                 int32_t number);

// The destructor, 0x001b1110: StopAnimating, EnsureNisIsLoaded, Unload
// when a NIS is loaded, off NisManagerList, the four props destroyed from
// the last (eModel's destructor with 0), and with bit 0 of `flags` the
// memory freed. The players' destructor passes 3.
void nismanager_destruct(NisManager *m, int32_t flags);

// gNewNisManagerFn and gDeleteNisManagerFn's shapes (playerinit.h).
NisManager *nismanager_new(void *mem, const char *name, int32_t number);
void nismanager_delete(NisManager *m);

// Start(int nis, int camera, Car *player, Car *other), 0x001b1318.
// StartTime is WorldTimeFrames and EndTime that plus twice the NIS's
// NumFrames, read from NisInfoTable at nis * 160 untested; Playing 1, and
// the NIS, the camera and the two cars kept. Then the load check
// (0x001b16e0: Load when the NIS is not the loaded one, then
// EnsureNisIsLoaded), SetupCarsBeforeNIS and StartAnimating.
void nismanager_start(NisManager *m, int32_t nis, int32_t camera,
                      struct Car *player, struct Car *other);

// Stop, 0x001b1388. While Playing: StopAnimating, RestoreCarsAfterNIS,
// and the record back to idle -- the cars NULL, the NIS and camera -1,
// Playing, StartTime and EndTime 0.
void nismanager_stop(NisManager *m);

// IsPlaying: the word at +68, which retail's callers read in place.
int32_t nismanager_is_playing(const NisManager *m);

// AllowDebugLooping, 0x001b13e8: always 0 in retail.
int32_t nismanager_allow_debug_looping(const NisManager *m);

// Unload, 0x001b1658: EnsureNisIsLoaded, then with a NIS loaded both its
// files unloaded (UnloadResourceFile on NisResourceFile, then
// CamResourceFile) and LoadedNisNumber -1. Player::ServiceNis calls it
// after Stop.
void nismanager_unload(NisManager *m);

// EnsureNisIsLoaded, 0x001b16a0: ServiceResourceLoading until
// LoadingNisNumber goes negative.
void nismanager_ensure_nis_is_loaded(NisManager *m);

// The NIS player's, unported. Load(int), 0x001b1568, which queues the
// NIS's two files and sets LoadingNisNumber. SetupCarsBeforeNIS
// (0x001b2718), StartAnimating (0x001b2840), StopAnimating (0x001b2a70)
// and RestoreCarsAfterNIS (0x001b27c0). UnloadResourceFile (0x00199728)
// and ServiceResourceLoading (0x00199788) are resource.h's, which the port
// binds; NULL skips each.
extern void (*gNisManagerLoadFn)(NisManager *m, int32_t nis);
extern void (*gNisSetupCarsBeforeNisFn)(NisManager *m);
extern void (*gNisStartAnimatingFn)(NisManager *m);
extern void (*gNisStopAnimatingFn)(NisManager *m);
extern void (*gNisRestoreCarsAfterNisFn)(NisManager *m);
extern void (*gNisUnloadResourceFileFn)(struct ResourceFile *rf);
extern int32_t (*gNisServiceResourceLoadingFn)(void);

// NisManager::DoSnapshot, 0x001b11f8, section "NisManager" (TASKS 72d).
// A restore stops the animation first. StartTime, EndTime and NisNumber
// go in four bytes, both cars as their driver numbers, Playing and
// CamNumber in one, and the two movement modes as their first byte. A
// restore that left it Playing loads the NIS if it is not the loaded one
// (0x001b16e0, as Start does) and starts the animation again.
struct ReplaySnapshot;
void nismanager_do_snapshot(NisManager *m, struct ReplaySnapshot *s);

#endif
