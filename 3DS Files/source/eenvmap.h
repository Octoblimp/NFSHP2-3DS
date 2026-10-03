#ifndef NFSHP2_EENVMAP_H
#define NFSHP2_EENVMAP_H

// eEnvMap: the six views round the car that its reflection is drawn from.
//
// Retail's eEnvMap (TheOnlyEnvMap, 0x002d6340) is six views, 4 to 9, on
// render targets 8 to 13, each a camera looking along one axis from the
// car. eDisplayFrame (0x00112a34) has UpdateEnvironmentMapCameras move
// them to the car the camera follows, once a frame, before the views'
// matrices are made; the cull and StuffScenery draw the sky and the
// scenery into the views that are active, and eCreateEnvMapPrims
// (0x00118810) folds the six into the sphere map the cars' environment
// passes read.
//
// The port draws the views into a cube map's faces instead (see
// georender_envmap_face), which the PICA reads by the reflection itself.
// The reflection reaches the map through hack_man_matrix, face 2's camera:
// the environment pass takes r = D (R * EnvMapMatrix), D negating x and z,
// so a world direction w is at D (w * hack_man_matrix). Each view's camera
// is the cube face's along the same axis as retail's: the frustum is the
// same, turned about its axis by a multiple of 90 degrees so the face's
// texels run the way the cube's do.
//
// The PICA reads a face's s and t by OpenGL's rule, but a target puts the
// top of its view at t = 0, where OpenGL's is at 1, so a face drawn the
// way the rule wants is a mirror image. No camera draws one, so the map
// is mirrored instead: the pass reads it at (-r.x, r.y, r.z), and in that
// space each face's camera looks along the face's axis with its up the
// opposite of the way t runs.

#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "camera.h"
#include "eview.h"

// TheOnlyEnvMap's Views and Cameras, which eInitEnvMap fills.
extern eView  *EnvMapViews[6];
extern Camera  EnvMapCameras[6];

// The cube face, +X to -Z as GPU_TEXFACE counts them, each view draws.
extern int32_t EnvMapCubeFace[6];

// The point the six look out from, the last UpdateCameras was given, and
// whether there has been one.
extern bVector3 EnvMapCentre;
extern int32_t  EnvMapCentreValid;

// The look-at UpdateCameras makes for each face, from the centre along the
// face's axis, which retail hands to SetCameraMatrix. The port hands over
// the cube face's instead and keeps these for hack_man_matrix.
extern bMatrix4 EnvMapFaceMatrix[6];

// gp-21072, 1: eDisplayFrame updates the cameras, and draws the six views,
// only with it set. The pause menu's debug page toggles it.
extern int32_t EnableEnvMapViews;

// eInitEnvMap(void), 0x00117508: views 4 to 9 active on targets 8 to 13,
// with TheOnlyEnvMap's cameras, and the targets set up as retail's render
// target setup (0x001064c8) leaves them. Retail first builds the sphere
// map's prims (0x00117a38), which the cube does not need. Returns 1.
int eenvmap_init(void);

// eEnvMap::UpdateCameras(bVector3 *, bVector3 *), 0x001175c8: the six
// cameras at `target`, turned by the view from `pos` to it, hack_man_matrix
// with them, and which views draw this frame.
void eenvmap_update_cameras(const bVector3 *pos, const bVector3 *target);

// UpdateEnvironmentMapCameras(void), 0x00123ba0: the cameras to the car
// view 1's first camera mover follows, or player one's, or the world's
// first, seen from view 1's camera.
void update_environment_map_cameras(void);

#endif
