#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <citro3d.h>

#include "camera.h"
#include "geometry.h"
#include "georender.h"
#include "scenerycull.h"
#include "texsrc.h"

// The track viewer: TRACKB12.BUN's scenery on the top screen, through the
// port of the game's own cull, from a camera flown with the circle pad.
//
// This is roadmap step 1, and it is the first mode that draws anything the
// game decides to draw. The geometry viewer shows a car because the viewer
// picked it; here the ported Scenery.obj picks. The bundle is read whole
// and the scenery works on it in place, as LoaderScenery does: its 122
// sections and 23 visible zones go to scenery_loader, eModel::Init (now
// emodel.c) connects each kind's models to the solids by name, and every
// frame runs eDisplayFrame's order on view 1 -- the view's matrices, the
// cull infos, DoCulling, StuffScenery -- with eModel::Render being this
// file's draw over georender.
//
// What stands in for the game, and should not be read as the game:
//
//   * LoaderSolidList. The bundle's 1,135 eSolids are linked onto
//     SolidList in place, which is the part of it eFindSolid needs, and
//     nothing else is fixed up: the strip, texture and light-material
//     pointers stay the file's zeros. The LoaderTable (step 2) ports it.
//   * SetScreenBuffers. Only the three things the matrices read are set:
//     MainDraw0Context's scissor (ScreenWidth by ScreenHeight) and player
//     1's aspect ratios, which are the image's NTSC pair.
//   * The camera mover. The camera is Player1Camera, and nothing is on
//     view 1's mover list: the viewer builds the matrix itself with
//     eCreateLookAtMatrix and hands it to SetCameraMatrix. The disc's free
//     camera is DebugWorldCameraMover, which is not ported yet.
//   * The lighting. Scenery is prelit -- 80% of its strips carry no normal
//     -- and the port has no light materials yet, so everything draws in
//     its vertex colour alone.
//   * The render lists. The engine puts each strip on its texture's DMA
//     list or the frame's alpha list and draws them all at eDisplayFrame's
//     end; the port draws an opaque order-0 batch at once and holds the
//     rest back, then draws them in the attach loops' order. A batch is a
//     texture's strips in one solid, so the alpha sort is per batch where
//     the engine's is per strip.
//   * The sky. StuffSky is step 3; until then the SKYDOME and
//     SKYDOME_ENVMAP instances in section 99 draw in the main view, from
//     wherever the cull puts them.
//
// The cull runs in the PS2's pixels, 512 by 448 with H from the field of
// view, and the projection here is cut so that the top screen's width is
// the cull's: the 3DS screen is wider than 8:7, so its height is inside the
// cull's rather than past it, and nothing the cull drops can be on screen.

#define TRACKVIEW_MAX_SOLIDS   1280     // TRACKB12 has 1,135
#define TRACKVIEW_MAX_TEXTURES 512      // its solids name 415 hashes
#define TRACKVIEW_NUM_PACKS    3
#define TRACKVIEW_ROUTE        1        // the racing route the stops are on
#define TRACKVIEW_STOPS        24       // how many stops round it
#define TRACKVIEW_MAX_DEFERRED 1024     // batches held back for the alpha pass

typedef struct {
    uint32_t hash;
    C3D_Tex  tex;
    bool     valid;
    uint8_t  level;             // the mip level uploaded, 0 when there was room
    float    uvScale[2];

    // From its TextureInfo, zero for a texture no pack holds.
    GeoPass  pass;
    uint8_t  order;             // RenderingOrder, 0 to 7
    bool     sorted;            // ApplyAlphaSorting
    uint32_t stamp;             // the frame that last used it,
    uint16_t firstUse;          // and where in that frame it was first used
} TrackTex;

// The port's render data for one eSolid, beside GeoSolid storage[i].
typedef struct {
    GeoMesh     mesh;
    GeoTexture* slot;           // numTextures entries
    TrackTex**  tex;            // the same entries' TrackTex, NULL for none
    float     (*centre)[3];     // per batch, the centre of its box
    bool        baked;
    bool        failed;
} TrackSolid;

// A batch the frame holds back for the attach loops' order: its texture is
// not an opaque order-0 one. See trackview_draw.
typedef struct {
    C3D_Mtx  modelView;
    float    depth;             // the centre's view z, +z forward
    uint16_t solid;
    uint8_t  batch;
    uint8_t  order;
    bool     sorted;
    uint16_t texUse;
    uint16_t seq;
} TrackDeferred;

typedef struct {
    TexSource pack[TRACKVIEW_NUM_PACKS];
    bool      hasPack[TRACKVIEW_NUM_PACKS];
    bool      hasBundle;

    // --- the bundle, resident for as long as the scenery points into it.
    uint8_t*     data;
    size_t       len;
    bool         dataLinear;    // from linearMemAlign, not memalign
    GeoSolidList list;
    GeoSolid*    solid;         // sorted by header address, as geo_open walks
    TrackSolid*  info;
    int          numSolids;
    int          linkedSolids;
    TrackTex*    texture;
    int          numTextures;

    // --- what the scenery loader made. The zones are counted from their
    // chunk rather than from VisibleZoneList, which FindVisibleZone
    // reorders every time the camera changes zone.
    uint8_t* zoneChunk;
    int numSections;
    int numZones;
    int numModels;
    int modelsWithoutSolid;

    // --- the camera: Player1Camera, from these.
    float pos[3];
    float yaw;                  // radians, from +x toward +y
    float pitch;                // radians, up positive
    float speed;                // metres a second
    int   stop;                 // the stop along the route the D-pad last chose
    int   numStops;             // 0 when the bundle has no route 1

    // --- the frame.
    GrandSceneryCullInfo cull;
    int  drawn;
    int  drawnTris;
    int  drawInfos;
    int  frameMallocFails;
    int  drawnInPlace;          // of `drawn`, objects with no matrix of their own
    int  deferredSorted;        // of numDeferred, the ApplyAlphaSorting ones
    int  deferredDropped;       // past TRACKVIEW_MAX_DEFERRED, not drawn
    int  numDeferred;
    uint32_t frameStamp;
    uint16_t texUses;
    TrackDeferred deferred[TRACKVIEW_MAX_DEFERRED];
    int  cmdSkipped;            // draws left out because the GPU list was full
    bool listPending;           // the next frame lists what it draws
    bool listFrame;             // this one did, into drawList
    char drawList[2048];
    int  cmdPeakWords;          // the most of the GPU list a frame has used

    // --- counters for the bring-up overlay.
    bool loaded;
    int  bakedSolids;
    int  bakedTris;
    int  skippedStrips;
    int  missingTextures;
    int  reducedTextures;       // uploaded below level 0 for want of room
    int  loadMs;
    char note[64];
} TrackView;

// Opens the texture packs and notes whether TRACKS\TRACKB12.BUN is there.
// Nothing is read yet.
bool trackview_init(TrackView* v);

// Reads the bundle, links its solids, runs the scenery and route loaders
// over it, bakes every solid a model names and uploads its textures, and
// puts the camera at the start of route 1. False leaves the viewer empty
// but usable, with `note` saying why. A second call does nothing.
bool trackview_load(TrackView* v);

// Unloads the scenery, takes the solids off SolidList and frees it all.
void trackview_free(TrackView* v);

// One frame of the fly camera, into Player1Camera. `kDown` and `kHeld` are
// hidKeysDown() and hidKeysHeld(), `cpx`/`cpy` the circle pad.
void trackview_input(TrackView* v, uint32_t kDown, uint32_t kHeld, int cpx,
                     int cpy, float dt);

// The frame: view 1's matrices, the cull, and StuffScenery into the bound
// render target, which must have a depth buffer.
void trackview_draw(TrackView* v);
