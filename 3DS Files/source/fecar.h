// fecar -- FrontEndRenderingCar, a car the frontend draws: the car
// select's turntable car and its reflection. CarRender.obj's; the
// addresses are retail's.
//
// This is step 16, SC-2: the constructor (0x0011e5c0), ReInit
// (0x0011e758), the destructor (0x0011e7d8), RenderFrontEndCar
// (0x00123c90) and RenderFrontEndCars (0x00123d28).
//
// Each one is on FrontEndRenderingCarList and belongs to one view. It
// holds its own copy of a RideInfo and a CarRenderInfo built from it with
// no Car, and draws through CarRenderInfo::Render with the matrices its
// owner sets, or, when it has an eModel of its own, draws that instead.
// eDisplayFrame calls RenderFrontEndCars four times a frame: twice for the
// environment map's faces, once for the reflections and once for the
// cars.
//
// Written up in docs/formats/car-select.md, "The turntable car"; checked
// on retail's image by tools/fecar_check.py.

#ifndef FECAR_H
#define FECAR_H

#include <stdint.h>

#include "blist.h"
#include "bmatrix.h"
#include "bvector.h"
#include "car.h"
#include "carrenderinfo.h"
#include "emodel.h"
#include "eview.h"

// 648 bytes on the disc.
typedef struct FrontEndRenderingCar {
    bNode          Node;                //   0  on FrontEndRenderingCarList
    CarRenderInfo *pRenderInfo;         //   8  NULL until a ride is given
    RideInfo       Ride;                //  12  the copy pRenderInfo uses
    int32_t        ViewID;              //  20
    uint32_t       pad24[2];            //  24
    bVector3       Position;            //  32  pad never written
    bMatrix4       BodyMatrix;          //  48
    bMatrix4       TireMatrices[4];     // 112
    bMatrix4       BrakeMatrices[4];    // 368
    eModel        *pModel;              // 624  drawn instead, when set
    int32_t        Enabled;             // 628
    int32_t        Unused632;           // 632  1; RenderFrontEndCar's
                                        //      seventh argument, unread
    int32_t        Reflection;          // 636  drawn upside down, below
    int32_t        Headlights;          // 640  head and brake lights on
    int32_t        CopLights;           // 644
} FrontEndRenderingCar;

// gp-23656, the list's head; the constructor adds at the tail.
extern bNode FrontEndRenderingCarList;

// 0x0011e5c0, in place. The ride is a NULL-type one (Type -1, the rest
// 0) until `ride`, which may be NULL, is handed to ReInit; then every
// matrix is the identity, the position 0, Enabled 1, the rest 0.
void fecar_init(FrontEndRenderingCar *f, RideInfo *ride, int32_t view_id);

// 0x0011e758. Deletes the CarRenderInfo, if any; with a ride, copies it
// and builds a new one from the copy, with no Car.
void fecar_reinit(FrontEndRenderingCar *f, RideInfo *ride);

// 0x0011e7d8, the deleting destructor: waits for the renderer, deletes
// the CarRenderInfo and the eModel (each with 3), and leaves the list.
// With bit 0 of `flags`, bFree(f).
void fecar_delete(FrontEndRenderingCar *f, int32_t flags);

// 0x00123c90. CarRenderInfo::Render with ForceCarLOD and ForceTireLOD at
// 0, or 1 for a reflection, and each put back afterwards unless Render
// changed it. `unused` is retail's and unread.
void render_front_end_car(CarRenderInfo *ri, eView *view,
                          bVector3 *position, bMatrix4 *body_matrix,
                          bMatrix4 *tire_matrices, bMatrix4 *brake_matrices,
                          int32_t unused, int32_t reflection, uint32_t flags,
                          uint32_t forced_lights);

// 0x00123d28. Every enabled car of `view` with a CarRenderInfo: the
// reflections when `reflections` is set and the view mode is 1, the
// others when `cars` is. Flag 8 joins the render flags when `pass8` is 0,
// and 16 when `pass16` is (eDisplayFrame passes 0 for the first with the
// cars and for the second with the environment map's faces);
// a reflection starts from 17. A car is drawn centred across its body's
// box in x.
void render_front_end_cars(eView *view, int32_t cars, int32_t reflections,
                           int32_t pass8, int32_t pass16);

// gp-23596 and gp-23600: force flags 8 and 16 on every car. 0.
extern int32_t FrontEndCarForceFlag8;
extern int32_t FrontEndCarForceFlag16;

#endif
