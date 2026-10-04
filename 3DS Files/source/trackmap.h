// trackmap -- TrackMap, the minimap (step 8m-6). The addresses are
// retail's (SLES_507.31); the names and the fields are the demo's .mdebug
// record (176 bytes), and retail's offsets are the same.
//
// SetHudFeatures makes one per player when the HUD's TRACK_MAP feature
// comes on (`new TrackMap`, playerhud.h's gNewTrackMapFn) and deletes it
// when the feature goes off. SetTrackMapMode writes CurrentMode, and
// Render (8m-6c) draws the mode CurrentlyDisplayedMode names.
//
// This part (8m-6a) holds the mode table and what Render reads the map's
// place and turn from:
// - InitTrackMapModeInfo (0x001bd1f8) fills TrackMapModeInfo, eleven
//   modes, and TrackMapMarkerInfo, nine marker colours. Every
//   constructor runs it again.
// - The constructor (0x001babb8) looks the seven textures up and says in
//   SufficientDataToRenderMe whether the map can be drawn.
// - GetAngle (0x001bb678) eases the map's turn after the camera with
//   EvalCubic (0x001bdad0), from the direction GetCameraDirection
//   (0x001bd0b0) gives.
// - GetCarUVPosition (0x001bca50) takes a point in the world to the map
//   texture's UVs, and GetBoxOnMap (0x001bcae8) turns a box about a point
//   on the map.
//
// Written up in docs/formats/trackmap.md; checked on retail's image by
// tools/trackmap_check.py.

#ifndef TRACKMAP_H
#define TRACKMAP_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "car.h"
#include "player.h"
#include "texturepack.h"
#include "track.h"

// The modes, TrackMapModeNames' order (the demo's 0x0030c0a8). 6 is
// playerhud.h's TRACKMAP_MODE_OFF.
#define TRACKMAP_MODE_3D                 0
#define TRACKMAP_MODE_3D_NO_ROTATION     1
#define TRACKMAP_MODE_2D                 2
#define TRACKMAP_MODE_2D_NO_ROTATION     3
#define TRACKMAP_MODE_FIXED              4
#define TRACKMAP_MODE_MAXIMUM_SIZE       5
#define TRACKMAP_MODE_2_PLAYER           7
#define TRACKMAP_MODE_COP_SMALL          8
#define TRACKMAP_MODE_COP_LARGE          9
#define TRACKMAP_MODE_COP_TARGETING      10
#define TRACKMAP_NUM_MODES               11

// TrackMapModeInformation, 68 bytes: where a mode draws the map and how.
// The places are in the HUD's 640x480.
typedef struct TrackMapModeInformation {
    uint16_t AngleX;                       //  0  the tilt, a BAM
    uint8_t  _pad2[2];                     //  2
    float    H;                            //  4  the projection's distance
    int16_t  X;                            //  8
    int16_t  Y;                            // 10
    float    Width;                        // 12
    float    Height;                       // 16
    int16_t  ClippingX;                    // 20
    int16_t  ClippingY;                    // 22
    float    ClippingWidth;                // 24
    float    ClippingHeight;               // 28
    float    ViewDistanceForward;          // 32  of the map's width
    float    ViewDistanceBackward;         // 36
    uint8_t  ZoomToKeepPursuedCarInView;   // 40
    uint8_t  _pad41[3];                    // 41
    float    CarDotSize;                   // 44
    float    StartFinishLineWidth;         // 48
    float    StartFinishLineHeight;        // 52
    uint8_t  HasRotation;                  // 56
    uint8_t  HasScrolling;                 // 57
    uint8_t  HasRotatingCarDots;           // 58
    uint8_t  _pad59;                       // 59
    float    Alpha;                        // 60
    uint8_t  IsDrawn;                      // 64
    uint8_t  HasBorder;                    // 65
    uint8_t  _pad66[2];                    // 66
} TrackMapModeInformation;                 // 68

// TrackMapMarkerColour, 3 bytes.
typedef struct TrackMapMarkerColour {
    uint8_t Red, Green, Blue;
} TrackMapMarkerColour;

#define TRACKMAP_NUM_MARKER_COLOURS 9

// Retail's 0x003140b8 and 0x003143a8 (the demo's TrackMapModeInfo and
// TrackMapMarkerInfo). Filled by trackmap_init_mode_info.
extern TrackMapModeInformation TrackMapModeInfo[TRACKMAP_NUM_MODES];
extern TrackMapMarkerColour    TrackMapMarkerInfo[TRACKMAP_NUM_MARKER_COLOURS];

typedef struct TrackMap {
    bVector2     PreviousCameraDirection;     //   0  eased, GetAngle's
    bVector2     CurrentCameraSpeed;          //   8  the ease's speed
    uint32_t     PreviousTime;                //  16  WorldTimer then
    uint8_t      _pad20[12];                  //  20  to align the matrix
    bMatrix4     MapRotationMatrix;           //  32  the calibration's turn
    TextureInfo *TrackMapTexture;             //  96  TRACK%d_MAP
    TextureInfo *CarMarkerNonrotatingTexture; // 100  CAR_MARKER
    TextureInfo *CarMarkerRotatingTexture;    // 104  CAR_MARKERB
    TextureInfo *OverlayTexture;              // 108  TRACKMAPFRAME
    TextureInfo *UnderlayTexture;             // 112  MAPBACK
    TextureInfo *StartLineTexture;            // 116  never set
    TextureInfo *FinishLineTexture;           // 120  never set
    TextureInfo *StartFinishLineTexture;      // 124  START_LINE
    TextureInfo *RoadblockTexture;            // 128  BKGBMP
    Car         *CarToTrack;                  // 132
    Player      *PlayerToTrack;               // 136
    TrackInfo   *CurrentTrack;                // 140
    Car         *CurrentlyPursuedCar;         // 144
    float        CurrentViewDistanceForward;  // 148
    float        CurrentViewDistanceBackward; // 152
    int32_t      SufficientDataToRenderMe;    // 156
    int32_t      CurrentMode;                 // 160  SetTrackMapMode's
    int32_t      CurrentlyDisplayedMode;      // 164
    uint8_t      _pad168[8];                  // 168  quadword round-up
} TrackMap;                                   // 176

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char trackmap_layout_check[
    (sizeof(TrackMap) == 176
     && offsetof(TrackMap, MapRotationMatrix) == 32
     && offsetof(TrackMap, TrackMapTexture) == 96
     && offsetof(TrackMap, RoadblockTexture) == 128
     && offsetof(TrackMap, CurrentTrack) == 140
     && offsetof(TrackMap, SufficientDataToRenderMe) == 156
     && offsetof(TrackMap, CurrentMode) == 160
     && offsetof(TrackMap, CurrentlyDisplayedMode) == 164) ? 1 : -1];
#endif
typedef char trackmap_mode_layout_check[
    (sizeof(TrackMapModeInformation) == 68
     && offsetof(TrackMapModeInformation, ClippingWidth) == 24
     && offsetof(TrackMapModeInformation, CarDotSize) == 44
     && offsetof(TrackMapModeInformation, Alpha) == 60
     && offsetof(TrackMapModeInformation, HasBorder) == 65
     && sizeof(TrackMapMarkerColour) == 3) ? 1 : -1];

// 0x001bd1f8, a static member: it reads no TrackMap.
void trackmap_init_mode_info(void);

// The constructor, 0x001babb8. With no track, car or player it only
// clears PreviousTime and SufficientDataToRenderMe.
void trackmap_construct(TrackMap *m, TrackInfo *track, Car *car,
                        Player *player);

// `new TrackMap` as SetHudFeatures has it (0x0017abd4): bMalloc(176,
// "TrackMap", 0, 16) and the constructor. gNewTrackMapFn's shape.
TrackMap *trackmap_new(TrackInfo *track, Car *car, Player *player);

// The deleting destructor, 0x001badc8: the destructor does nothing, so
// this is bFree. gDeleteTrackMapFn's shape.
void trackmap_delete(TrackMap *m);

// 0x001bb678. The map's turn as a BAM in *angle: 0x8000 for a mode
// without rotation, and otherwise half a turn from the camera's eased
// direction. Answers GetCameraDirection's answer, which is always 1.
int32_t trackmap_get_angle(TrackMap *m, uint16_t *angle);

// 0x001bd0b0. The way the player looks, in *dir's x and y: the drive
// camera's direction turned by its look back; with another camera,
// the eased direction once the race is on, and the car's before. The
// drive camera's direction also starts the ease when it is near zero.
// z is set only with the drive camera. Always answers 1.
int32_t trackmap_get_camera_direction(TrackMap *m, bVector3 *dir);

// 0x001bca50. A world point's place on the map texture, by the track's
// calibration: out = ((x - left) / width, (top - y) / width), turned by
// MapRotationMatrix.
void trackmap_get_car_uv_position(TrackMap *m, bVector2 *out,
                                  const bVector3 *pos);

// 0x001bcae8. The four corners of a box about `centre`, turned by `angle`:
// out[0] (right, forward), out[1] (-left, forward), out[2] (-left,
// -backward), out[3] (right, -backward), before the turn.
void trackmap_get_box_on_map(TrackMap *m, const bVector2 *centre,
                             float forward, float backward, float left,
                             float right, uint16_t angle, bVector2 out[4]);

// EvalCubic, 0x001bdad0: one step of the cubic ease GetAngle runs on each
// of the direction's two parts. *x moves toward `target` over `t`, and *v
// is its speed.
void eval_cubic(float *x, float *v, float target, float t);

#endif  // TRACKMAP_H
