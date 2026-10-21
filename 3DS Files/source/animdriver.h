// animdriver -- retail's AnimatedDriver.obj (0x001a8f50 .. 0x001aa6c8) and
// Car's two methods that make and free one (0x00133488, 0x001334f0): the
// drivers in the cars (TASKS 83b).
//
// Every car but traffic gets a driver when its CarRenderInfo is made: the
// body type of the car's character (CharacterInfo's BodyTypeName) names
// three models, one a level of detail, and an eAnimation is made for each
// whose solid has a bone tree (a plain eModel otherwise). Its two skins go
// on them as replacement textures.
//
// The driver's pose is DRIVER_ANIM01's frame for the steering, 15 to 45
// with 30 straight ahead, eased by a spline and wiggled by a table; over it
// two players run the animations queued: a gear change (DRIVER_SHIFT01, on
// three bones), the idle every two seconds, looking back, driving
// backwards, a flinch for a collision, and the two waves before a race.
// Some animations are blackballed for some cars and characters, where the
// arm would go through the roof or the door.
//
// The R/C Car's big head is the stomper's (nBoneScale, vBoneScale) and
// eanim.c's. Free of <3ds.h>: tools/animdriver_check.py runs it next to
// retail's code in mipsemu.

#ifndef ANIMDRIVER_H
#define ANIMDRIVER_H

#include <stddef.h>
#include <stdint.h>

#include "banim.h"
#include "bmatrix.h"
#include "bquat.h"
#include "bvector.h"
#include "eanim.h"
#include "emodel.h"
#include "scenery.h"

struct Car;
struct CharacterInfo;
struct eLightContext;
struct ReplaySnapshot;

// DriverAnimationType (.mdebug t1376).
enum {
    DRIVER_ANIM_NONE = 0,
    DRIVER_ANIM_STEERING,
    DRIVER_ANIM_IDLE,
    DRIVER_ANIM_DRIVING_BACKWARDS,
    DRIVER_ANIM_LOOKING_BACKWARDS_LEFT,
    DRIVER_ANIM_LOOKING_BACKWARDS_RIGHT,
    DRIVER_ANIM_COLLISION_LIGHT,
    DRIVER_ANIM_COLLISION_FRONT,
    DRIVER_ANIM_COLLISION_RIGHT,
    DRIVER_ANIM_COLLISION_LEFT,
    DRIVER_ANIM_COLLISION_BACK,
    DRIVER_ANIM_GEAR_CHANGE,
    DRIVER_ANIM_PRERACEG02,
    DRIVER_ANIM_PRERACEG14,
    DRIVER_ANIM_NUM
};

// AnimationInfo, 36 bytes; AnimationInfoTable is 0x003111f8, a row a type.
// InitAnimatedDriver fills SolidNameHash, and NumFrames from the solid
// when BeginFrame is 0 (0 when there is no solid).
typedef struct DriverAnimationInfo {
    int32_t     Type;                       //  0
    const char *SolidName;                  //  4
    uint32_t    SolidNameHash;              //  8
    int32_t     BeginFrame;                 // 12
    int32_t     NumFrames;                  // 16
    int32_t     PauseFrameNumber;           // 20  0 none, -1 loops
    int32_t     AllowCollisionInterruption; // 24  by a stronger one
    int32_t     BlendWithSteering;          // 28  eased in and out
    int32_t     CombineWithSteering;        // 32  on top of the steering
} DriverAnimationInfo;                      // 36

extern DriverAnimationInfo AnimationInfoTable[DRIVER_ANIM_NUM];

// AnimationPlayer, 16 bytes. Times are WorldTime's, two to a frame.
typedef struct AnimationPlayer {
    DriverAnimationInfo *pAnimationInfo;    //  0
    int32_t              StartTime;         //  4
    int32_t              EndTime;           //  8
    int32_t              PauseFrameNumber;  // 12
} AnimationPlayer;                          // 16

// AnimatedDriver, 144 bytes.
typedef struct AnimatedDriver {
    struct Car             *pCar;                       //   0
    eAnimation             *pAnimations[3];             //   4  by LOD
    eModel                 *pModels[3];                 //  16  by LOD
    BSpline                *pSteeringFrame;             //  28
    struct CharacterInfo   *pCharacterInfo;             //  32
    eReplacementTextureTable SkinReplacementTextureTable[2]; // 36 body, head
    uint32_t                ShiftAnimationNameHash;     //  92
    int32_t                 SteeringWiggleNumber;       //  96
    int32_t                 DisableRenderingFlag;       // 100
    int8_t                  LookingBackwardsFlag;       // 104
    int8_t                  DrivingBackwardsFlag;       // 105
    int32_t                 CurrentLookingBackwardsType;// 108
    AnimationPlayer         AnimationPlayers[2];        // 112
} AnimatedDriver;                                       // 144

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char animdriver_layout_check[
    (sizeof(DriverAnimationInfo) == 36 && sizeof(AnimationPlayer) == 16
     && offsetof(AnimatedDriver, pSteeringFrame) == 28
     && offsetof(AnimatedDriver, SkinReplacementTextureTable) == 36
     && offsetof(AnimatedDriver, ShiftAnimationNameHash) == 92
     && offsetof(AnimatedDriver, DisableRenderingFlag) == 100
     && offsetof(AnimatedDriver, LookingBackwardsFlag) == 104
     && offsetof(AnimatedDriver, CurrentLookingBackwardsType) == 108
     && offsetof(AnimatedDriver, AnimationPlayers) == 112
     && sizeof(AnimatedDriver) == 144) ? 1 : -1];
#endif

// gp-19248, -1 in the image and never written: a LOD every driver draws
// at, when not negative.
extern int32_t ForceAnimatedDriverLOD;

// GetDriverAnimationTypeName(DriverAnimationType), 0x001a8f60: the
// table at 0x003113f0, unchecked.
const char *animdriver_type_name(int32_t type);

// 0x001a8f78, unnamed: 1 when `type` is not to be played for the car type
// and character. Blackballed for the car type by a table of 21; for a car
// without an open top (CarTypeInfoArray's OpenTop) outside view mode 1,
// the idle and the gear change; and for a character of a body type whose
// name begins "Co" (a cop), the collisions that would go through a
// cruiser's cage.
int32_t animdriver_blackballed(int32_t type, int32_t car_type,
                               const struct CharacterInfo *ci);

// -------------------------------------------------------- AnimationPlayer

// BeginAnimation(DriverAnimationType, int), 0x001a9098: from WorldTime
// plus `delay` for NumFrames * 2, or 100000 for one that pauses. A type
// of 14 or more changes nothing.
void animplayer_begin(AnimationPlayer *p, int32_t type, int32_t delay);

// ReleasePausedFrame, 0x001a9100: the rest of the animation from the
// paused frame, from now.
void animplayer_release_paused_frame(AnimationPlayer *p);

// ReleaseAnimation, 0x001a9160: one not playing is cancelled; a paused one
// still to run is let go on.
void animplayer_release(AnimationPlayer *p);

// GetFrameNumber, 0x001a91b8: BeginFrame plus the frames since the start.
// A PauseFrameNumber of -1 loops below NumFrames; any other not 0 holds
// the frame there.
int32_t animplayer_get_frame_number(const AnimationPlayer *p);

// CancelAnimation, 0x001aa6c0: BeginAnimation(NONE, 0).
void animplayer_cancel(AnimationPlayer *p);

// ---------------------------------------------------- the global set-up

// InitAnimatedDriver, 0x001a9238: each type's solid found by its name,
// upper-cased. With AnimatedDriverNeedsFixup, the frames of each that is
// combined with the steering are made relative to frame 30, the steering's
// straight ahead (conjugate of frame 30 times the frame, normalised); then
// the flag is cleared. CloseAnimatedDriver, 0x001a9458, does nothing.
void InitAnimatedDriver(void);
void CloseAnimatedDriver(void);

// --------------------------------------------------------- AnimatedDriver

// The constructors, 0x001a94d8 (a character's, for the frontend) and
// 0x001a95c0 (a car's: its driver's character; `name` unused). Both
// players cancelled, the flags cleared, InitializeArtwork and
// SetupSteeringFrame. The destructor, 0x001a96b8: the animations and
// models deleted, the spline freed, and with bit 0 the driver.
AnimatedDriver *animdriver_construct_character(AnimatedDriver *d,
                                               struct CharacterInfo *ci);
AnimatedDriver *animdriver_construct(AnimatedDriver *d, struct Car *car,
                                     const char *name);
void            animdriver_destroy(AnimatedDriver *d, int32_t flags);

// SetupSteeringFrame, 0x001a9460: a 48-byte spline at 30, still.
void animdriver_setup_steering_frame(AnimatedDriver *d);

// InitializeArtwork, 0x001a97e8. See the file comment.
void animdriver_initialize_artwork(AnimatedDriver *d);

// DoSnapshot(ReplaySnapshot *), 0x001a9770: "AnimatedDriver", everything
// cancelled when restoring, and the two flags.
void animdriver_do_snapshot(AnimatedDriver *d, struct ReplaySnapshot *s);

// Render(bMatrix4 *, eLightContext *, unsigned int, int), 0x001a9a30: the
// LOD's animation posed by BuildQuaternionTable, or its plain model.
// OverrideAnimatedDriverLOD keeps it at 1 or finer.
void animdriver_render(AnimatedDriver *d, bMatrix4 *m,
                       struct eLightContext *light, uint32_t flags,
                       int32_t lod);

// CancelAllAnimations (0x001a9b30) and ReleaseAllAnimations (0x001a9b70):
// both players.
void animdriver_cancel_all(AnimatedDriver *d);
void animdriver_release_all(AnimatedDriver *d);

// 0x001a9bb0 .. 0x001a9e24.
void animdriver_begin_gear_change(AnimatedDriver *d);
void animdriver_begin_driving_backwards(AnimatedDriver *d);
void animdriver_end_driving_backwards(AnimatedDriver *d);
void animdriver_handle_driving_backwards(AnimatedDriver *d);
void animdriver_begin_looking_backwards(AnimatedDriver *d);
void animdriver_end_looking_backwards(AnimatedDriver *d);

// HandleLookingBackwards, 0x001a9cb8: left or right from where the cop or
// the chased car is, or else from the steering, or as it was.
void animdriver_handle_looking_backwards(AnimatedDriver *d);

// BeginCollision(DriverAnimationType, int), 0x001a9e28: nothing while a
// playing animation cannot be interrupted, or only by more than
// `strength`; otherwise everything cancelled and the type queued, or
// COLLISION_LIGHT for a blackballed one.
void animdriver_begin_collision(AnimatedDriver *d, int32_t type,
                                int32_t strength);

// QueueAnimation(DriverAnimationType), 0x001a9ef8: on the last free
// player, after the others' end. 0 for a blackballed type, a player
// paused (more than 10000 to go) or none free.
int32_t animdriver_queue_animation(AnimatedDriver *d, int32_t type);

// GetLengthOfQueuedAnimations, 0x001a9fb8: the longest still to run.
int32_t animdriver_get_length_of_queued(AnimatedDriver *d);

// FindAnimation(DriverAnimationType), 0x001a9ff0: the player with the
// type and time to run, or NULL.
AnimationPlayer *animdriver_find_animation(AnimatedDriver *d, int32_t type);

// ReleaseAnimation(DriverAnimationType), 0x001aa040: each player of the
// type released.
void animdriver_release_animation(AnimatedDriver *d, int32_t type);

// CalculateSteeringFrameNumber, 0x001aa0a0: the spline aimed at the
// steering's frame and the frame it is at.
int32_t animdriver_calculate_steering_frame_number(AnimatedDriver *d);

// QueueRandomAnimations(int, int, int), 0x001aa1e8: up to `count` of
// types `first` to `last`, never one twice running, in up to 1001 draws
// from bViewSeed (retail's bDefaultSeed; see animdriver.c).
void animdriver_queue_random_animations(AnimatedDriver *d, int32_t first,
                                        int32_t last, int32_t count);

// BuildQuaternionTable(eAnimation *, bQuaternion *, bVector3 *),
// 0x001aa2f0: the 42 bones' rotations and the root translation for the
// frame.
void animdriver_build_quaternion_table(AnimatedDriver *d, eAnimation *a,
                                       bQuaternion *q, bVector3 *t);

// BeginAPreRaceAnimation, 0x0019c078: QueueRandomAnimations(12, 13, 2).
void animdriver_begin_a_pre_race_animation(AnimatedDriver *d);

// Car::AssignAnimatedDriver(char const *), 0x00133488: a driver for any
// car but traffic. UnAssignAnimatedDriver, 0x001334f0.
void car_assign_animated_driver(struct Car *c, const char *name);
void car_unassign_animated_driver(struct Car *c);

#endif
