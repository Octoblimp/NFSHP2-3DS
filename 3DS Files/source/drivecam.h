// drivecam -- DriveCameraMover (CM_DRIVE), the chase camera a player drives
// behind: CameraMover.obj's biggest class. The addresses are retail's.
//
// This is step 7b: the whole class -- the constructor, the destructor,
// ResetState, the virtuals with Update (0x0015c880), GetLookbackCar, the
// two retail-only wall helpers Update calls (0x00157930, 0x00157b60), the
// corrections, CalculateLookbackAngle and the accessors. The demo's
// GetBoomDistToWall and its two line-segment helpers are still in the image
// with no caller. Nothing builds a drive camera before
// Player::ChangeCameraMover (7c).
//
// Retail against the demo:
// - The TopologyCoordinate the mover carries is retail's 704 bytes, not the
//   demo's 560, so every field after it is 144 further on (DisableLag 884,
//   PerfectFocus 992).
// - Update keeps the eye off the walls with a push out of every polygon
//   within the wall gap (0x00157930) and turns the look-at to hold the car
//   where the boom would have put it on screen (0x00157b60); the demo's
//   shortened the boom to the nearest wall.
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
// bytes); the offsets are retail's, and the port's are the same.
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

// The tuning Update reads, retail's gp words with their values. The Drive*
// set stands in for the POV when DriveUseTweakables is set; the Cam* set
// shapes the acceleration lag. CamGlobalMultiplier is set to 1 on every
// Update.
extern int32_t  DriveUseTweakables;         // gp-21760, 0
extern float    DriveLag;                   // gp-21756, 7.3
extern float    DriveHeight;                // gp-21752, 2.3
extern float    DriveLatOffset;             // gp-21748, 0
extern uint16_t DriveAngle;                 // gp-21744, 0
extern uint16_t DriveMaxAngle;              // gp-21742, 2000
extern float    CamGlobalMultiplier;        // gp-21636, 1
extern float    CamAdjustment;              // gp-21632, 0.03
extern float    CamBackAdjust;              // gp-21628, 0.012
extern float    CamHoldTimeout;             // gp-21624, 2
extern float    CamYawAdjuster;             // gp-21608, 6
extern float    CamAccelScaleRatio;         // gp-21604, 0.6
extern float    CamDecelScaleRatio;         // gp-21600, 0.045
extern float    CamRangeCheckA;             // gp-21596, 0.7
extern float    CamRangeCheckD;             // gp-21592, -0.3
extern float    CamLagMultiplier;           // gp-21588, 1
extern float    CamSpeedAdjust;             // gp-21580, 500
extern float    CamHeightMultiplierD;       // gp-21564, 0.2
extern float    CamAccelCap;                // gp-21560, 6
extern float    CamDecelCap;                // gp-21556, -1
extern float    CamDisableAdjust;           // gp-21552, 0.4
extern float    CamBackAdjustQuicker;       // gp-21548, 3
extern float    RoadNoiseAmplitude;         // gp-21536, 250

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

// 0x0015c880, the vtable's Update: the camera one frame on. The car is
// CarToFollow, or CameraFollowThisCarInstead's while CameraFollowDefaultCar
// is 0. The boom hangs off the car's heading outside and its body inside,
// trails its yaw and pitch by the corrections, lengthens with the
// acceleration lag, swings round for a look back, and outside is kept off
// the walls and out of the car; then the shake and camera_set_matrix.
void drive_cam_update(CameraMover *m);

// 0x0015c680. The car a cop's look back turns to: a cop's chased car, and
// *isCop set, or the cop chasing a car. NULL, with *isCop 0, when there is
// no cop manager or no cop either way.
struct Car *get_lookback_car(struct Car *car, int32_t *isCop);

// 0x00157930. How far to move `eye` off the walls, into `out` (its fourth
// lane 0). First ConstrainToTopology from `from` to the eye (0.01, lift 1);
// then up to three times, every polygon in tc's table that the camera may
// not go through and whose shaft holds the pushed eye within the gap --
// the mover's GetWallGap for a polygon flagged 2, 0.7 for the rest --
// pushes it out along its normal by what is left of the gap, averaged over
// those polygons. The fourth lanes carry the planes' distances along.
void camera_wall_offset(CameraMover *m, TopologyCoordinate *tc,
                        const bVector3 *from, const bVector3 *eye,
                        bVector3 *out);

// 0x00157b60. The look-at matrix from `eye` to `target`, with the target
// moved by `off` times its depth in the look-at's own frame (-x by off.x,
// -y by off.y), up (0, 0, 1). The image passes the mover first and never
// reads it.
void camera_look_at_offset(bMatrix4 *out, const bVector3 *eye,
                           const bVector3 *target, const bVector2 *off);

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
