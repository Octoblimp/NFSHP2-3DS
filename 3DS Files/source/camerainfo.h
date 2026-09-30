// camerainfo -- a car's drive-camera points of view: CameraInfo, which
// CarTypeInfo carries at 960 and the drive camera reads in place, and its
// POV records.
//
// Apart from cammover.h because CarTypeInfo holds one: cartypeinfo.h and
// cammover.h both include this, and neither the other.

#ifndef CAMERAINFO_H
#define CAMERAINFO_H

#include <stddef.h>
#include <stdint.h>

// A POV's Type. IsCameraPOVInCar asks for POV_INCAR, and the drive camera
// counts POV_OUTSIDE as an exterior view.
#define POV_BUMPER   0
#define POV_INCAR    1
#define POV_OUTSIDE  2

// A drive camera's point of view, 32 bytes (.mdebug type#1891).
typedef struct POV {
    int32_t  Type;          //  0  POV_*
    float    Lag;           //  4
    float    Height;        //  8
    float    LatOffset;     // 12
    uint16_t Angle;         // 16
    uint16_t MaxAngle;      // 18
    char     Pad[12];       // 20
} POV;                      // 32

// 272 bytes (.mdebug type#1897). Four points of view for a full screen and
// four for a split one; GetPOV picks the set by the view mode.
typedef struct CameraInfo {
    int32_t NumFullScreenPOVs;        //   0
    int32_t NumSplitScreenPOVs;       //   4
    int32_t Padding[2];               //   8
    POV     FullScreenPOVArray[4];    //  16
    POV     SplitScreenPOVArray[4];   // 144
} CameraInfo;                         // 272

typedef char camerainfo_layout_check[
    (sizeof(POV) == 32 && sizeof(CameraInfo) == 272
     && offsetof(CameraInfo, FullScreenPOVArray) == 16
     && offsetof(CameraInfo, SplitScreenPOVArray) == 144) ? 1 : -1];

#endif
