// playerzone -- the Player's camera zones and the jump cam. The addresses
// are retail's.
//
// A zone is a spell of slow or fast time, a pause, or the jump cam, with
// its camera, a radial blur on the player's view and a sound. Car::
// FinishMovement asks for the jump cam through car.h's four Player seams,
// and the zone buttons through playerinput.c's RacingJoyHandler. Ported
// here: IsJumpCamAvailable (0x001769e8), RequestZone (0x00177c88),
// ClearZone (0x00178358), ClearZoneSound (0x00178470), PlayerClearZone
// (0x00177c80), and the jump cam's two movers, ChangeCameraMover's types
// 15 and 16 (0x00176ddc and 0x00177200), as playercam.c's
// gPlayerJumpCamMoverFn.
//
// Written up in docs/formats/camera.md, "The jump cam's route" and "The
// camera zones"; checked on retail's image by tools/prevroute_check.py
// and tools/playerzone_check.py.

#ifndef PLAYERZONE_H
#define PLAYERZONE_H

#include <stdint.h>

#include "bvector.h"

struct bSample;
struct CameraMover;
struct Car;
struct Player;
struct PreviewRoute;

// ------------------------------------------------------------- the zones

// Player::nZoneCurrent. 0 is none; car.h has 6 and 7.
#define PLAYER_ZONE_FREEZE       1   // the world paused, the freeze camera
#define PLAYER_ZONE_PREVIEW      2   // paused, the camera down the road
#define PLAYER_ZONE_SLOMO        3   // a third of the speed for 8 s
#define PLAYER_ZONE_SLOMO_SHORT  4   // a third for 2 s
#define PLAYER_ZONE_FAST         5   // twice the speed for 4 s
#define PLAYER_ZONE_COUNT        8

// The byte tables at 0x00330790 and 0x00330798, by the zone a player is
// in: whether a new request clears that zone first (the freeze and the
// preview), and whether it refuses the request (3 to 7, for any player).
extern const int8_t PlayerZoneClearedByRequest[PLAYER_ZONE_COUNT];
extern const int8_t PlayerZoneBlocksRequest[PLAYER_ZONE_COUNT];

// 0x00177c88. Asks for `zone`; yes if it began. No while an NIS plays, in
// the AI demo, while the race is not racing, for a zone of 8 or more, with
// two players, for the jump cam's zones with the JumpCams setting off and
// for 1 to 5 with ZoneCams off. Without `force`, no within 5 s of this
// zone's last start, which tAutoZoneTimers[zone] keeps; with it, no within
// 0.1 s of tAutoZoneTimers[0], which ClearZone stamps for the freeze and
// the preview. The freeze or preview it is in is cleared first, and no if
// any player is in 3 to 7. Then tIgnoreNextPovChange is RealTimer, the
// zone's timer WorldTimer (without `force`), and the HUD's animations go.
//
//   1  replays refuse it. ChangeCameraMover(13, keep), and the world
//      paused for ZoneFreezeCameraMover::Duration less this frame's time.
//   2  replays refuse it, and so do a wrong-way car or no route, with the
//      "MenuWrong" sound. pRoute from ZonePreviewCameraMover::FindRoute,
//      ChangeCameraMover(14, keep), and a camera that ViolatesTopology is
//      put back with the sound. Else the world paused for its duration
//      less this frame's, silently ("PreviewZone").
//   3  the world at 0.333 for 8 s, "SlomoZone".
//   4  at 0.333 for 2 s, "SlomoZone".
//   5  at 2 for 4 s, "Wind".
//   6  at 0.4 for 8 s, "SlomoZone" pitched to 0.9, ChangeCameraMover(15,
//      keep) unless in a replay, and CleanUpJumpCam either way.
//   7  the same with type 16.
//
// The pause or scale ends in PlayerClearZone. Then RadialBlurOn for the
// player's view, nZoneCurrent, bZoneMuffleSound from `muffle` and
// fZoneMuffleVolume 0 if it is set, else 1. With SoundEnabled and
// `sound`, and the sound's category 0 above silence, the zone's sample
// replaces pZoneSample: a new bSample from GetInGameSample's, category
// 0xffffffff, played at the volume (1, or 0 for the preview), 0 and the
// pitch less 1.
//
// The port's: a freeze or preview whose camera and calls are not ported
// (their seams below, or playercam.h's movers, NULL) is refused before
// anything changes, a dead button.
int32_t player_request_zone(struct Player *p, int32_t zone, int32_t force,
                            int32_t sound, int32_t muffle);

// 0x00178358. Nothing outside a zone. Else RadialBlurOff for the player's
// view; for the freeze and the preview, tAutoZoneTimers[0] is WorldTimer
// unless TweakerPauseWorld holds the world; for those two and the jump
// cam's, the camera saved before the zone comes back (RestoreCameraMover)
// unless in a replay. The world's time scale is reset, the zone moves to
// nZonePrevious, the muffle goes, ClearZoneSound if `sound`, and
// DetermineInputMode.
void player_clear_zone(struct Player *p, int32_t sound);

// 0x00178470. With SoundEnabled, pZoneSample deleted and cleared.
void player_clear_zone_sound(struct Player *p);

// 0x00177c80. ClearZone(p, 1), for World's pause and time scale to call
// when they run out: `param` is the Player, as a word.
void player_clear_zone_callback(int32_t param);

// ---------------------------------------------------------- the jump cam

// 0x001769e8. CleanUpJumpCam, then a PreviewRoute 50 out and 75 long from
// the player's car into pJumpCamRoute. Yes if it has five points or more;
// if not, the route is cleaned up again. On the track whose
// SameAsTrackNumber is 21 there is no jump cam within 40 of (1646, -884),
// and no route is built.
int32_t player_is_jump_cam_available(struct Player *p);

// That place, and how near counts.
#define PLAYER_NO_JUMP_CAM_TRACK 21
extern const bVector2 PlayerNoJumpCamPlace;
#define PLAYER_NO_JUMP_CAM_RADIUS 40.0f

// ChangeCameraMover's types 15 and 16, `second` telling them apart, for
// playercam.h's gPlayerJumpCamMoverFn; `car` is the one ChangeCameraMover
// chose, but both read the player's MyCar's ratio round the track.
//
// 15 (0x00176ddc) writes myCD for a camera beside the road: the eye
// locked to the car's progress from where it is to the route point near
// the end of pJumpCamRoute (n - 1 of n under 6 points, else n - 3), whose
// ratio comes from a TrackPathCoordinate there, with TrackDirection
// turning both round; two eye points; the field of view 20 degrees
// throughout, no bank, NearClip 0.5, FarClip 10000, EnterVertComp 0.2 and
// the rest 0 (the area and the shake bank are left as they were). The eye
// is that point's edge of the road whose way from the car points least
// along the car's velocity, a unit up and at least a unit above the
// ground there; the other eye point is route point 2's other edge, a unit
// up; EnterHorizComp is 0.4 for the left edge, -0.4 for the right.
//
// 16 (0x00177200) starts again from the car's progress, puts all three
// eye points at the third (raised to the car's height, then above the
// ground), turns EnterHorizComp over, narrows the field of view from 20
// by a quarter a step, and keeps the focus effects.
//
// Each then builds a TrackCarCameraMover (1136 bytes) on myCD and a shake
// of nothing with two points, and returns it.
struct CameraMover *player_jump_cam_mover(struct Player *p, struct Car *car,
                                          int second);

// ---------------------------------------------------------------- the seams
//
// ZoneFreezeCameraMover::Duration (0x00161098), static. ZonePreview
// CameraMover::FindRoute (0x00163708), ViolatesTopology (0x00164180) and
// its duration, retail's own (0x001637c8).
extern float (*gZoneFreezeDurationFn)(void);
extern struct PreviewRoute *(*gZonePreviewFindRouteFn)(struct Car *car);
extern int32_t (*gZonePreviewViolatesTopologyFn)(struct CameraMover *m);
extern float (*gZonePreviewDurationFn)(struct CameraMover *m);

// The zone's sound. bSound::GetCategoryVolume (0x00277dc0) on TheSound;
// `new bSample` (bOMalloc on the sample pool, gp-13816, and the
// constructor, 0x00272ff0); bSample::Initialize (0x00273210) and
// SetCategory (0x00273618); and CommonRegion's Sample (0x002779e0,
// 0x002719b8). Play, GetInGameSample and the virtual destructor are
// rcstates.h's and playerinit.h's. A NULL volume is silence, and nothing
// is made; the rest, NULL, are skipped.
extern float (*gSoundGetCategoryVolumeFn)(uint32_t category);
extern struct bSample *(*gNewSampleFn)(void);
extern void (*gSampleInitializeFn)(struct bSample *s, struct bSample *from);
extern void (*gSampleSetCategoryFn)(struct bSample *s, uint32_t category);
extern struct bSample *(*gCommonRegionSampleFn)(const char *name);

#endif
