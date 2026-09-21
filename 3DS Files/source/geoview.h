#pragma once
#include <stdbool.h>
#include <stdint.h>

#include <citro3d.h>

#include "camera.h"
#include "cammover.h"
#include "geometry.h"
#include "georender.h"
#include "texsrc.h"

// The geometry bring-up viewer: one car out of CARS\*\GEOMETRY.BIN on the
// top screen, orbited with the circle pad.
//
// This is the third mode main.c's SELECT cycles through, after the boot flow
// and the screen viewer, and it exists for the same reason the screen viewer
// does -- a decoder that passes a cross-check has been shown to agree with
// another decoder, which is not the same as being shown to be right. The
// only way to find out whether a car is a car is to look at one.
//
// A car is the cheapest thing to look at: one solid list, 16 to 19 solids,
// at most 9,343 triangles, no streaming decision to make. A track bundle is
// 1,135 solids and needs one, which is task 27.
//
// What it does NOT do, and should not be read as evidence about:
//
//   * Place parts. Wheels, brakes, mirrors and wipers are stored in their
//     own local space centred on the origin -- the car's part transforms are
//     elsewhere and are not decoded yet -- so "draw everything" piles them
//     up at the middle of the car. Stepping through solids one at a time is
//     the honest view, and is the default.
//   * Pick a LOD. The body ships as four solids, _A through _D, and drawing
//     them together z-fights. The viewer opens on the largest by triangle
//     count, which is _A.
//   * Resolve every texture. 58 of the 132 hashes the car geometry refers to
//     are in no texture pack anywhere on the disc -- 9.0% of car strips --
//     and those batches draw with vertex colour alone. That is the data, not
//     this viewer; see docs/formats/solid-geometry.md.
//   * Blend anything. Glass draws opaque, white on the 911 and black on the
//     sedan, because the GS blend state has not been recovered yet. Vertex
//     alpha is not it: all 212,408 RGBA5551 vertex colours in the car set
//     have their alpha bit set.

#define GEOVIEW_MAX_CARS     48
#define GEOVIEW_NAME_LEN     32
#define GEOVIEW_MAX_SOLIDS   32     // worst cars are DIABLO/MURCIELAGO, at 19
#define GEOVIEW_MAX_SLOTS    32     // eTextureTable entries per solid; 13 max
#define GEOVIEW_MAX_TEXTURES 64     // distinct hashes in one car; 21 max

typedef struct {
    uint32_t hash;
    C3D_Tex  tex;
    bool     valid;
    float    uvScale[2];
} GeoViewTex;

typedef struct {
    // --- the texture packs, both streamed off the card rather than resident.
    // CARS\TEXTURES.BIN is 15 MB and one car uses about 400 KB of it.
    TexSource carPack;
    TexSource globalPack;
    bool      hasCarPack;
    bool      hasGlobalPack;

    // --- the car list, from the directory names under CARS\.
    char car[GEOVIEW_MAX_CARS][GEOVIEW_NAME_LEN];
    int  numCars;
    int  curCar;

    // --- the loaded model.
    uint8_t*     data;
    size_t       len;
    GeoSolidList list;
    GeoSolid     solid[GEOVIEW_MAX_SOLIDS];
    GeoMesh      mesh[GEOVIEW_MAX_SOLIDS];
    GeoTexture   slot[GEOVIEW_MAX_SOLIDS][GEOVIEW_MAX_SLOTS];
    int          numSolids;
    int          curSolid;
    bool         drawAll;

    GeoViewTex texture[GEOVIEW_MAX_TEXTURES];
    int        numTextures;

    // --- the camera. Not the viewer's own any more: this is the engine's
    // Camera (task 23) driven by a real CM_ORBIT_CAR CameraMover, orbiting
    // a CamCarView parked at the current solid's AABB centre. So what is on
    // screen is the shipped boom arm -- its acceleration limiter, its
    // elevation clamp, its 8000-BAM field of view -- and not an
    // approximation of it. The AABB still decides where the car is and how
    // long the boom starts out.
    Camera              cam;
    OrbitCarCameraMover orbit;
    CamCarView          carView;
    float               centre[3];
    float               radius;
    float               dist;
    bool                spin;
    bool                textured;

    // --- counters for the bring-up overlay.
    int  loadedTris;
    int  missingTextures;
    int  skippedStrips;
    int  loadMs;
    char note[64];
} GeoView;

// Opens the texture packs and scans CARS\ for car directories. False when
// the data directory has no cars in it; `note` says why.
bool geoview_init(GeoView* v);
void geoview_free(GeoView* v);

// Loads car `index`, bakes every solid and resolves its textures. Replaces
// whatever was loaded before. False leaves the viewer empty but usable.
bool geoview_load(GeoView* v, int index);

// One frame of input, and one frame of the camera mover -- the mover runs
// from here rather than from geoview_draw because this is where the frame
// delta arrives. `kDown` is hidKeysDown(), `kHeld` hidKeysHeld() (the zoom
// is a held button on the disc too), `cpx`/`cpy` the circle pad in its
// native -156..156.
void geoview_input(GeoView* v, uint32_t kDown, uint32_t kHeld, int cpx,
                   int cpy, float dt);

// Draws the current solid, or all of them. Assumes a render target with a
// depth buffer is already bound (C3D_FrameDrawOn).
void geoview_draw(GeoView* v);

// The name of the solid on screen, or "(all)" / "-".
const char* geoview_solid_name(const GeoView* v);
