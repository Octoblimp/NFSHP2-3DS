// drivecam -- DriveCameraMover (CM_DRIVE), the chase camera a player drives
// behind: CameraMover.obj's biggest class. The addresses are retail's.
//
// This is step 7a-2b: the constructor, the destructor, ResetState, the
// virtuals but Update, the corrections, CalculateLookbackAngle and the
// accessors. Update (0x0015c880), GetLookbackCar and the two retail-only
// wall helpers Update calls (0x00157930, 0x00157b60) are 7b's, and until
// then the vtable's Update is the base's, which does nothing. The demo's
// GetBoomDistToWall and its two line-segment helpers are still in the image
// with no caller. Nothing builds a drive camera before
// Player::ChangeCameraMover (7c).
//
// Retail against the demo:
// - The TopologyCoordinate the mover carries is retail's 704 bytes, not the
//   demo's 560, so every field after it is 144 further on (DisableLag 884,
//   PerfectFocus 992).
// - The constructor and ResetState take LastCarSpeed from the car's
//   State.VelocityMagnitude, where the demo's took ForwardSpeed.
// - GetTarget is the car's GeometryPosition, where the demo's was its
//   Position.
// - The fallback CameraInfo is CarTypeInfoArray[0]'s, read inline; the demo
//   called GetCarTypeInfo(0).
// - Three virtuals are new: IsExteriorView (+68), IsLookingBack (+76) and
//   GetWallGap (+84). Each counts a look back only while the player's
//   PlayerSettings.Lookback is 0.
//
// Written up in docs/formats/camera.md, "The drive camera"; checked on
// retail's image by tools/drivecam_check.py.

#ifndef DRIVECAM_H
#define DRIVECAM_H

#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "camerainfo.h"
#include "cammover.h"
#include "topology.h"

struct Car;

// The fields and their names are the demo's .mdebug record (type#2542, 864
// bytes); the offsets in the comments are retail's. The port's own offsets
// differ from TheTopologyCoordinate on, since its TopologyCoordinate is
// still the demo's; nothing reads a drive camera in place.
typedef struct DriveCameraMover {
    CameraMover  base;                      //    0
    bMatrix4     TM;                        //   48
    struct Car  *CarToFollow;               //  112
    const CameraInfo *pCameraInfo;          //  116
    int32_t      POVIndex;                  //  120
    float        DesiredLookBackParam;      //  124 1 to look back, 0 ahead
    float        LookBackParam;             //  128 how far round it is
    int32_t      iLookBackParam;            //  132
    float        iLookBackHeight;           //  136
    uint16_t     LookBackAngle;             //  140
    int32_t      LastCarYaw;                //  144
    int32_t      LastBoomYaw;               //  148
    float        AmountToUseYawCorrection;  //  152
    int32_t      LastCarPitch;              //  156
    int32_t      LastBoomPitch;             //  160
    float        DesiredAccelLag;           //  164
    float        CurrentAccelLag;           //  168
    float        LastCarSpeed;              //  172
    float        TouchingGroundFactor;      //  176
    TopologyCoordinate TheTopologyCoordinate; // 180
    int32_t      DisableLag;                //  884 Player::SetCameraSpring's
    float        LookbackSpeed;             //  888
    float        CamLastAccel[20];          //  892
    float        CamCurrentAccel;           //  972
    float        CamLagAdjust;              //  976
    float        CamHoldLagTime;            //  980
    float        CamTimeFract;              //  984
    float        CamAdjustMultiplier;       //  988
    int32_t      PerfectFocus;              //  992
} DriveCameraMover;                         // 1008

// Retail's vtable, 0x002b1dd0.
extern const CameraMoverVtbl DriveCameraMoverVtbl;

// 0x0015c258. The base's constructor for `viewID` and CM_DRIVE, then the
// state off `car`, which must not be NULL. `lookBack` starts the camera
// looking back. The CameraInfo is the car type's, or CarTypeInfoArray[0]'s
// when either of its counts is 0. Unless CameraStopUpdating is set, the
// camera's CarNotToRender and RenderDash are cleared.
void drive_cam_init(DriveCameraMover *d, int viewID, struct Car *car,
                    int povIndex, float lookbackSpeed, int disableLag,
                    int lookBack, int perfectFocus);

// 0x0015c400. Unless CameraStopUpdating is set, the camera's
// CarNotToRender, FocalDistance and DepthOfField back to 0; then the
// topology's destructor and the base's. The delete is the caller's.
void drive_cam_destroy(CameraMover *m);

// 0x0015c470, the vtable's ResetState: the constructor's state again, read
// off CarToFollow, without the arguments' fields.
void drive_cam_reset_state(CameraMover *m);

// 0x0015c520.
void drive_cam_set_pov_index(DriveCameraMover *d, int index);

// 0x0015c528. The split-screen set in view mode 3 and the full-screen one
// otherwise; NULL when `index` is not below the set's count. The compare is
// signed and the index is not tested for below 0.
const POV *drive_cam_get_pov(CameraMover *m, int index);

// 0x0015fc20 and 0x0015fbf0, the vtable's GetCameraInfo and GetCarToFollow.
const CameraInfo *drive_cam_get_camera_info(CameraMover *m);
void *drive_cam_get_car_to_follow(CameraMover *m);

// 0x0015c138. The car's GeometryPosition, or the camera's target while
// there is no car.
const bVector3 *drive_cam_get_target(CameraMover *m);

// 0x0015c7a0 (+68). Outside the car: no POV at the index, a POV_OUTSIDE
// one, or a look back under way (drive_cam_is_looking_back).
int drive_cam_is_exterior_view(CameraMover *m);

// 0x0015c760 (+76). The player's Lookback is 0 and LookBackParam is above
// 0. Player::DetermineHudFeatures asks it. The mover's player may be NULL.
int drive_cam_is_looking_back(CameraMover *m);

// 0x0015c838 (+84). 0.7 (gp-31028), moving to 3 as a look back that
// drive_cam_is_looking_back would count comes round.
float drive_cam_get_wall_gap(CameraMover *m);

// 0x0015c158, 0x0015c1d0 and 0x0015c218: an angle between the car and the
// boom, as a signed BAM, turned into the correction to apply. Yaw is
// bATan(1, |a| * 0.000261) * -1.9088 with a's sign; pitch is -a within 7
// of 0 and -a / 8 past it; in-car is -a within 1 and -a / 2 past it, both
// divisions toward 0. Yaw reads 0x8000 as -32768 and the other two as
// +32768. Nothing calls the in-car one.
float   drive_cam_get_correction_yaw(uint16_t a);
int32_t drive_cam_get_correction_pitch(uint16_t a);
int32_t drive_cam_get_in_car_correction_angle(uint16_t a);

// 0x0015c5a8, CalculateLookbackAngle(Car *from, Car *to, const bMatrix4 *m).
// Which way `to` lies from `from`, in the frame of m's first two rows: 0
// ahead (past 0.7071 along the first), 0x8000 behind (below -0.7071), and
// otherwise 0x4000 to the side the second row points away from and 0xc000
// to the other. Update and AnimatedDriver::HandleLookingBackwards call it.
uint16_t calculate_lookback_angle(const struct Car *from,
                                  const struct Car *to, const bMatrix4 *m);

// The inline accessors, retail's out-of-line copies at 0x0015fbf8 ..
// 0x0015fc9c. drive_cam_looking_back is LookingBack (0x0015fc28: a look
// back is wanted), and drive_cam_look_back_full the image's non-virtual
// IsLookingBack (0x0015fc70: DesiredLookBackParam is exactly 1). Both
// read DesiredLookBackParam, where the virtual reads LookBackParam.
uint16_t drive_cam_get_lookback_angle(const DriveCameraMover *d);
float    drive_cam_get_lookback_speed(const DriveCameraMover *d);
void     drive_cam_set_lookback_speed(DriveCameraMover *d, float speed);
int32_t  drive_cam_get_disable_lag(const DriveCameraMover *d);
void     drive_cam_set_disable_lag(DriveCameraMover *d, int32_t lag);
int      drive_cam_looking_back(const DriveCameraMover *d);
void     drive_cam_set_look_back(DriveCameraMover *d, int on);
int      drive_cam_look_back_full(const DriveCameraMover *d);

#endif
