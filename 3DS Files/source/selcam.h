// selcam -- SelectCarCameraMover (CM_SELECT_CAR), the camera of the car
// select's turntable. CameraMover.obj's; the addresses are retail's.
//
// This is step 16, SC-2: the constructor (0x0015a698), the destructor
// (0x0015a880), the setters (0x0015a940 .. 0x0015a9f8 and 0x0015fab8 ..
// 0x0015fad8), SetMode (0x0015aa08), Update (0x0015abb0) and the three
// quaternion helpers it calls: MyQuaternionMultiply (0x0015aab0),
// NormalizeQuaternion (0x0015ab58) and Slerp (0x001a7280).
//
// The mover blends between two views of the car. The stats view is still:
// a fixed heading and tilt, RadiusStats away, looking past OffsetStats.
// The orbit view turns: the car select's sticks set the three desired
// speeds, Update ramps toward them, and the tilt and the radius bounce off
// their stops with a bump. Blend walks 0.03 a frame toward the mode, and
// a cosine of it picks the point between the two views.
//
// Written up in docs/formats/car-select.md, "The turntable camera";
// checked on retail's image by tools/selcam_check.py.

#ifndef SELCAM_H
#define SELCAM_H

#include <stdint.h>

#include "bquat.h"
#include "bvector.h"
#include "cammover.h"

// The four bSamples, by their place from 176.
enum {
    SELCAM_SND_ON     = 0,   // 176 "MenuCarDisplayOn"
    SELCAM_SND_OFF    = 1,   // 180 "MenuCarDisplayOff"
    SELCAM_SND_ACTIVE = 2,   // 184 "MenuCarDisplayActive", the orbit's hum
    SELCAM_SND_BUMP   = 3,   // 188 "MenuCarOrbitBump"
    SELCAM_SND_COUNT  = 4,
};

// The bSample calls, with the sample's index. The constructor makes the
// four only while SoundEnabled (gp-23056) is set, in the "FrontEnd" region
// at category 3; the destructor deletes those it made. Play's three floats
// are bSample::Play's: the first is the volume, the other two are always 0
// here. SetPitch's is an offset in bSample's units, 0 the patch's own.
// NULL, or a NULL entry, is silence.
typedef struct SelCamSoundFns {
    void (*create)(int sample);
    void (*destroy)(int sample);
    void (*play)(int sample, float volume, float a, float b);
    void (*stop)(int sample);
    void (*set_volume)(int sample, float volume);
    void (*set_pitch)(int sample, float pitch);
} SelCamSoundFns;

extern const SelCamSoundFns *gSelCamSound;

// 192 bytes on the disc.
typedef struct SelectCarCameraMover {
    CameraMover base;

    int32_t     Mode;               // 44  0 the stats view, 1 the orbit
    float       Blend;              // 48  0 .. 1, toward Mode
    int32_t     Unused52;           // 52  0, never read
    uint16_t    AngleZ;             // 56  SetOrientationStats' heading
    uint16_t    Unused58;           // 58  0, never read
    uint16_t    TiltStats;          // 60  minus SetOrientationStats' tilt
    uint16_t    TiltOrbit;          // 62
    float       RadiusStats;        // 64
    bVector3    OffsetStats;        // 80
    bVector3    OffsetOrbit;        // 96
    bQuaternion QuatStats;          // 112
    bQuaternion QuatOrbit;          // 128
    uint16_t    FOVStats;           // 144 stored, never read
    uint16_t    FOVOrbit;           // 146 stored, never read
    float       HorizSpeed;         // 148 BAMs a second round the car
    float       DesiredHorizSpeed;  // 152
    float       VertSpeed;          // 156 BAMs a second of tilt
    float       DesiredVertSpeed;   // 160
    float       OrbitRadius;        // 164
    float       RadiusSpeed;        // 168
    float       DesiredRadiusSpeed; // 172
    int32_t     Samples[SELCAM_SND_COUNT]; // 176 1 where a bSample was made
} SelectCarCameraMover;

// The modes, SelCarCamMode.
#define SELCAM_MODE_STATS 0
#define SELCAM_MODE_ORBIT 1

// Retail's vtable, 0x002b1950: the base's but for the destructor, Update
// and GetCarToFollow, whose own (0x0015fad0) returns NULL as the base's
// does.
extern const CameraMoverVtbl SelectCarCameraMoverVtbl;

// Update's frame counter (gp-21664), shared by every mover: the orbit's
// quaternion is renormalised when it is a multiple of 60 before the step.
extern int32_t SelCamNormalizeCount;

// 0x0015a698.
void selcam_init(SelectCarCameraMover *o, int viewID);

// 0x0015a880. Deletes the samples (without stopping them first), then the
// base's.
void selcam_destroy(SelectCarCameraMover *o);

// 0x0015abb0. One frame, timed by RealTimeElapsed.
void selcam_update(SelectCarCameraMover *o);

// 0x0015aa08. Stores the mode. With sound, the stats view plays Off and
// stops the hum; the orbit starts the hum silent and plays On.
void selcam_set_mode(SelectCarCameraMover *o, int32_t mode);

// The setters.
void selcam_set_radius_stats(SelectCarCameraMover *o, float r);
void selcam_set_offset_stats(SelectCarCameraMover *o, const bVector3 *v);
void selcam_set_offset_orbit(SelectCarCameraMover *o, const bVector3 *v);
void selcam_set_fov_stats(SelectCarCameraMover *o, uint16_t fov);
void selcam_set_fov_orbit(SelectCarCameraMover *o, uint16_t fov);
// 0x0015a978. The heading and the tilt (stored negated), and QuatStats
// from RotX 0, RotY 0x8000, RotZ heading.
void selcam_set_orientation_stats(SelectCarCameraMover *o, uint16_t angle,
                                  uint16_t tilt);
// 0x0015a9f8. TiltOrbit = -tilt.
void selcam_set_vert_angle_orbit(SelectCarCameraMover *o, uint16_t tilt);
void selcam_set_desired_radius_speed(SelectCarCameraMover *o, float s);
void selcam_set_desired_vert_orbit_speed(SelectCarCameraMover *o, float s);
void selcam_set_desired_horiz_orbit_speed(SelectCarCameraMover *o, float s);
// 0x0015fad8. Blend.
float selcam_get_mode_param(const SelectCarCameraMover *o);

// The quaternion helpers. MyQuaternionMultiply's *o = *a * *b, with
// o free to be either; NormalizeQuaternion divides each lane by the
// length, with no zero guard.
void selcam_quat_multiply(bQuaternion *o, const bQuaternion *a,
                          const bQuaternion *b);
void selcam_quat_normalize(bQuaternion *q);

// 0x001a7280, Slerp(bQuaternion &, bQuaternion &, bQuaternion &, float).
// Not bQuaternion's bSlerp: this one flips `a` in place when the two point
// apart, and when they are within 0.05 of opposite it overwrites `b` with
// a quaternion at right angles to `a`. Both writes stay.
void selcam_slerp(bQuaternion *o, bQuaternion *a, bQuaternion *b, float t);

#endif
