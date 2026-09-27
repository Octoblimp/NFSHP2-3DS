// sky -- Sky.obj (0x0011cc70 .. 0x0011cfdc): the sky dome.
//
// A track's sky is a scenery object like any other, SKYDOME, and on most
// tracks a second, SKYDOME_ENVMAP, which the environment-map views draw.
// SkyLoader takes each out of the scenery's draw. The object's placement
// becomes one of Sky.obj's matrices, and its model is made one of Sky.obj's
// own. The kind's three LOD models are UnInit'ed, so the cull finds no solid
// for them and draws nothing there. A track with no SKYDOME_ENVMAP gives
// the envmap views SKYDOME, at SKYDOME's placement.
//
// StuffSky draws the dome before anything else in each view. eDisplayFrame
// (0x00112a40 .. 0x00112ab8) turns the Z writes off, calls StuffSky for
// views 1 to 9 and attaches what it put on the lists, then turns the Z
// writes back on. So the dome is behind everything drawn after it.
//
// eModel::Render is the renderer's, through scenerycull.h's
// gEModelRenderFn. A NULL seam draws nothing.
//
// Cross-check: tools/sky_check.py. Write-up: docs/formats/sky-sun.md.

#ifndef SKY_H
#define SKY_H

#include <stdint.h>

#include "bmatrix.h"
#include "eview.h"
#include "scenery.h"

// The two names SkyLoader looks for: bStringHash of each.
#define SKY_HASH_SKYDOME         0xbe43edbbu
#define SKY_HASH_SKYDOME_ENVMAP  0x72923c81u

// The two models and their matrices, 0x002dc600 .. 0x002dc6c0.
extern eModel   SkydomeModel;               // 0x002dc600
extern bMatrix4 SkydomeLocalWorld;          // 0x002dc620
extern eModel   SkydomeEnvmapModel;         // 0x002dc660
extern bMatrix4 SkydomeEnvmapLocalWorld;    // 0x002dc680

// DrawSky, 0x00322c28 (gp-24520): 1 in the image, and nothing but a
// tweaker writes it. 0 draws no sky at all.
extern int32_t DrawSky;

// SkyInitModel(eModel *, bMatrix4 *, unsigned int), 0x0011cc70. With no
// object of that name the model is UnInit'ed, the matrix made the
// identity, and it returns 0. Otherwise the model is Init'ed with the
// name, the matrix is the object's rotation (2^-14 a unit) over its
// position with a 1, and the kind's LOD models are UnInit'ed. Then it
// returns 1.
int32_t SkyInitModel(eModel *model, bMatrix4 *matrix, uint32_t name_hash);

// SkyLoader, 0x0011ce18, from EndGameFlowLoadingTrackSpecific, and
// SkyUnloader, 0x0011ced8, from BeginGameFlowUnloadingTrackSpecific.
void SkyLoader(void);
void SkyUnloader(void);

// StuffSky(eView *), 0x0011cf18. With DrawSky, a player or mirror view
// (ID 1 to 3) renders SKYDOME, and every other view SKYDOME_ENVMAP, each
// at its matrix with no light context.
void StuffSky(eView *view);

// _GLOBAL_$I$SkydomeModel, 0x0011cfb8: both models' name and solid
// cleared. _GLOBAL_$D$SkydomeModel, 0x0011cf88: both destroyed with
// flags 2, the envmap's first.
void sky_static_init(void);
void sky_static_close(void);

#endif
