// shake -- tEnvelope and the camera shake: the half of one object file that
// is not the pad's rumble (retail 0x00155948 .. 0x00156b88, the demo's
// 0x00152860 .. 0x001539f4).
//
// A tEnvelope is a piecewise-linear curve through its points. A tShaker
// holds one camera's shake: a vector, the envelope its size follows, and
// a clock that runs from 0 to 1 over the shake's duration. There are two
// shakers, one for each player's camera. A hard hit on a player's car
// starts its shaker (MaybeCameraShake), World::DoTimestep asks each
// player's car once a step (Car::MaybeCameraShake), MainLoop runs the clocks
// (UpdateCameraShakers), and the drive and rear-view-mirror cameras tip their
// matrices by it (ApplyCameraShake).
//
// The shake is a square wave, not a sine: GetValue gives the vector times
// the envelope on an even step of fTime * fFrequency and zero on an odd
// one. At 17 steps over the duration, it is on for nine of them.
//
// The rumble half (tRumbler, PortRumble and its seven envelopes) drives the
// pad's motors and is not ported. Nor is the replay's SnapshotCameraShakers.
//
// Retail's only changes here are ApplyCameraShake's slow-motion test,
// MaybeCameraShake's Player offsets, and a reset and a tShaker constructor
// made out of line. Written up in docs/formats/camera.md, "The camera
// shake"; checked on retail's image by tools/shake_check.py.

#ifndef SHAKE_H
#define SHAKE_H

#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"

struct Car;

// ---------------------------------------------------------------- tEnvelope

// 8 bytes (.mdebug type#2214).
typedef struct sEnvelopePoint {
    float fTime;                //  0
    float fValue;               //  4
} sEnvelopePoint;

// 8 bytes (.mdebug type#2228). The points run in order of fTime.
typedef struct tEnvelope {
    sEnvelopePoint *pPoints;    //  0
    int32_t         nPoints;    //  4
} tEnvelope;

// 0x00155948. The last point at or before t: the first point whose time is
// past t, less one, and 0 before the first point or when there are none.
// A NaN is past no point, so it gives the last.
int32_t tenvelope_get_index(const tEnvelope *e, float t);

// 0x001559a8. Before the first point, or at or past the last. A NaN is
// neither. The count is not tested: the points must not be empty.
int32_t tenvelope_out_of_range(const tEnvelope *e, float t);

// 0x001559f0, GetSlope(int). The segment from point i to point i + 1, or 0
// when there is no such segment.
float tenvelope_get_slope_at(const tEnvelope *e, int32_t i);

// 0x00155a40, GetSlope(float). 0 out of range.
float tenvelope_get_slope(const tEnvelope *e, float t);

// 0x00155aa0. 0 out of range -- at the last point's time too, whatever its
// value.
float tenvelope_get_value(const tEnvelope *e, float t);

// 0x00155b28. The area under the curve from a to b, swapped into order and
// clamped to the points, by the trapezium on each segment. Each end is
// read through GetValue, so the last point's value counts as 0. The loop
// runs at least once, and its first segment ends at the point after a's:
// when a is at the last point, that is one past the end, and the image
// reads it.
float tenvelope_get_integral(const tEnvelope *e, float a, float b);

// ------------------------------------------------------------------ tShaker

// 32 bytes (.mdebug type#2256).
typedef struct tShaker {
    bVector3   vShake;          //  0  the shake's direction and size, negated
    tEnvelope *pAmplitude;      // 16  NULL while still
    float      fTime;           // 20  0 to 1 over the duration
    float      fDuration;       // 24  seconds
    float      fFrequency;      // 28  on-and-off steps over the duration
} tShaker;

// 0x00156b10, retail's constructor, which the static initialiser calls for
// each shaker: still, with a duration of 1 and a frequency of 17. The
// fourth lane of vShake is left as it was.
void tshaker_init(tShaker *s);

// 0x001562b0. The envelope at fTime, or 0 while still.
float tshaker_get_amplitude(const tShaker *s);

// 0x001562e8. vShake is -v, all four lanes. The envelope is always
// ShakeAmplitudeEnvelope, and fTime starts at 0.
void tshaker_start_shaking(tShaker *s, const bVector3 *v, float duration,
                           float frequency);

// 0x00156320. The clock moves on by dt over the duration, and the shaker
// stops once it leaves the envelope.
void tshaker_update(tShaker *s, float dt);

// 0x00156370. vShake times the envelope on an even step, and zero on an
// odd one or while still. All four lanes are written.
void tshaker_get_value(const tShaker *s, bVector3 *out);

// ------------------------------------------------------------ the globals

// The two players' shakers, 0x002fa820 (the demo's CameraShakers,
// 0x002f2830).
extern tShaker CameraShakers[2];

// bShakeTest, gp-21912: a debug switch. When set, the next
// UpdateCameraShakers clears it and starts player 1's shaker along
// vShakeTest, for 0.6 seconds.
extern int32_t  bShakeTest;
extern bVector3 vShakeTest;                // 0x002fa6e0: (0, 0, 0.3)

// ShakeAmplitudeEnvelope, gp-21848, over ShakeAmplitudePoints (0x002fa7a0):
// 1 at the start, falling through 0.7, 0.5 and 0.4 to 0 at the end.
extern sEnvelopePoint ShakeAmplitudePoints[5];
extern tEnvelope      ShakeAmplitudeEnvelope;

// vShakeAccelBias, 0x00334080: how much each axis of a car's acceleration
// counts toward a shake -- (0.7, 0.5, 2.0). vShakeRotation, 0x00334090:
// the BAMs each axis of the shake, in the camera's space, tips the camera by
// -- (-1200, 2000, 0).
extern bVector3 vShakeAccelBias;
extern bVector3 vShakeRotation;

// fShakeIntensityCoeffs, 0x002b13f0 (the demo's 0x00294ea0): an
// acceleration's range, 250 to 600, and the amplitudes, 0.08 to 0.16, and
// durations, 0.3 to 0.7 seconds, across it.
extern const float fShakeIntensityCoeffs[6];

// The camera-shake share of _GLOBAL_$I$bShakeTest, retail's 0x00156958 (the
// demo's 0x001537b8): vShakeTest, vShakeRotation, vShakeAccelBias, the
// amplitude envelope, and each shaker's constructor. The seven rumble
// envelopes and the four tRumblers it fills too are the rumble's.
void shake_static_init(void);

// Retail's 0x00156480, which the World constructor and its DoSnapshot call:
// both shakers still, as tshaker_init leaves them. Retail inlines the stores.
void reset_camera_shakers(void);

// 0x00156400. MainLoop calls it once a frame. The debug shake first, then
// both clocks, by WorldTimeElapsed.
void update_camera_shakers(void);

// 0x00156528 and 0x00156540: shaker i's value, and whether it is shaking.
void    get_shake(int32_t i, bVector3 *out);
int32_t is_shake_active(int32_t i);

// 0x00156560 (changed). Tips a camera matrix by its player's shake. View 1
// and the rear-view mirror, view 3, take player 1's, view 2 player 2's, and
// any other view none. Retail adds the first test: nothing while the world
// runs slower than real time -- pCurrentWorld->fTimeScale below 1, the jump
// cam's slow motion -- and pCurrentWorld is not tested for NULL.
//
// The shake is taken into the camera's space by the matrix (a direction:
// its fourth lane is 0) and becomes the translation of a matrix that then
// turns about x by the sum of its y and z, about y by its x, and about z by
// the sum of its x and y, each scaled by vShakeRotation. That matrix is
// multiplied onto the camera's, so the camera moves by the shake as well
// as tipping. The translation turns with each rotation, and each angle
// reads it as the rotations before it left it: the turn about x keeps x,
// so y's angle reads the shake's own x, and z's reads an x and a y that
// both have moved.
void apply_camera_shake(int32_t view, bMatrix4 *m);

// 0x001566c0 (changed: the Player's offsets). A shake for player `player`
// from an acceleration: its size, each axis weighed by vShakeAccelBias,
// against fShakeIntensityCoeffs. Nothing below 250, and nothing when the
// player's camera is in the car or the shaker is already shaking harder.
// In the zone after a long jump (Player::nZoneCurrent 7), the amplitude is
// 0.8 of it and the duration 1.2. The player is not tested for NULL before
// IsCameraPOVInCar reads it.
void maybe_camera_shake(int32_t player, const bVector3 *accel);

// Car::MaybeCameraShake, 0x001346b0 (the demo's 0x001329e8): a player's car
// passes its acceleration and its player's number. It lives here rather
// than in car.c for what it links.
void car_maybe_camera_shake(struct Car *c);

#endif
