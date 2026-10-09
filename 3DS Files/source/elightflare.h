// elightflare -- the drawing half of eLight.obj's flares (retail
// 0x00116118 .. 0x00116820): the glow of a car's headlights, brake
// lights, reverse lights and cop lights, and of the tunnels' lamps.
//
// A flare is a point and a direction in a model (elight.h's eLightFlare).
// eRenderLightFlare takes it to the world and drops it when it is off the
// screen. Then it draws the one or two parts its Type's row names. A part
// is a square of one of three textures, set a little toward the camera,
// facing it. Its size and colour grow with how squarely the flare faces
// the camera and with the caller's intensity: carrender.c's for a car's
// lights, 1 for the tunnels'. The size is in pixels, held between two
// depths: past the far one a flare shrinks with distance, and inside the
// near one it grows.
//
// The types: 0 a car's headlight flare, 1 a brake light, 2 a reverse
// light, 3 unused, 4 to 6 a cop's red, blue and white, 7 and 8 the
// headlights' own lamps, and 9 the tunnels' (every track's flare pack,
// "EF_TunnelA"). The headlights' are the only two-part ones.
//
// Written up in docs/formats/light-flare.md. Cross-check:
// tools/lightflare_check.py.

#ifndef ELIGHTFLARE_H
#define ELIGHTFLARE_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "elight.h"
#include "eview.h"
#include "texturepack.h"

// One part's numbers, 60 bytes; retail's nine are at 0x002d6080. The
// demo's eLightFlareParams was 64 bytes in another order. Retail is
// stripped, and these names are the port's.
typedef struct eLightFlarePart {
    float   MinSize;                    //  0  pixels at a facing of 0
    float   MaxSize;                    //  4  pixels at 1
    float   MinColour[4];               //  8  r, g, b, a; 128 is 1.0
    float   MaxColour[4];               // 24
    float   Power;                      // 40  the facing's exponent
    float   TowardCamera;               // 44  world units in front
    float   MinScale;                   // 48  world units a pixel
    float   MaxScale;                   // 52
    int32_t Texture;                    // 56  in eLightFlareTextures
} eLightFlarePart;

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char elightflare_layout_check[
    (sizeof(eLightFlarePart) == 60
     && offsetof(eLightFlarePart, MaxColour) == 24
     && offsetof(eLightFlarePart, Power) == 40
     && offsetof(eLightFlarePart, Texture) == 56) ? 1 : -1];
#endif

#define NUM_LIGHT_FLARE_TYPES    10
#define NUM_LIGHT_FLARE_TEXTURES 3

// The nine parts, and each type's two (0x002d62d8), the second NULL for
// all but the headlights.
extern const eLightFlarePart SingleLightFlareParameters[9];
extern const eLightFlarePart *const
    LightFlareParameterIndicies[NUM_LIGHT_FLARE_TYPES][2];

// HEADLIGHTFLAREINNER, HEADLIGHTFLAREOUTER and HEADLIGHTGLOW (hashes at
// 0x002d6070), all in GLOBALB; 0x002d6328, NULL until
// eLightUpdateTextures.
extern TextureInfo *eLightFlareTextures[NUM_LIGHT_FLARE_TEXTURES];

// eLightUpdateTextures (0x00116488), PostLoadFixup's second call: each of
// the three is GetTextureInfo(hash, 0, 0), loaded or NULL.
void el_update_textures(void);

// eRenderLightFlare (0x001164f0). 0 with no flare, matrix or camera, for
// a flare not Enabled, and for one off the screen; 1 when it was drawn.
// A part draws nothing without its texture or at a size of 0 or less.
//
// Retail indexes the types' table without a check. The port draws
// nothing for a Type outside 0..9, and still answers 1; no shipped flare
// has one.
int el_render_light_flare(eView *view, eLightFlare *flare,
                          bMatrix4 *local_world, float intensity);

// eRenderWorldLightFlares (0x00116778), from eDisplayFrame after
// RenderFlailerModels: while InGameFlag is set, every loaded pack's
// flares at intensity 1, through eMathIdentityMatrix.
void el_render_world_light_flares(eView *view);

#endif
