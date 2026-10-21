#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <citro3d.h>

#include "camera.h"
#include "geometry.h"
#include "georender.h"
#include "scenerycull.h"
#include "texturepack.h"

// The track viewer: a track's scenery on the top screen, through the port
// of the game's own cull, from a camera flown with the circle pad. The
// track is a number, as RaceParameters.TrackNumber is the game's, and
// every file of the track's is named from it: TRACKB12.BUN, the one the
// demo has, first, and then any of the retail disc's 30 on the card.
//
// This is roadmap step 1, and it is the first mode that draws anything the
// game decides to draw. The geometry viewer shows a car because the viewer
// picked it; here the ported Scenery.obj picks. The bundle is read whole
// and loaded in place, as ResourceFile's load does it: LoadChunks hands
// every top-level chunk to the LoaderTable (bchunkload.c), so its 65 solid
// lists go to LoaderSolidList, its 122 sections and 23 visible zones to
// LoaderScenery -- where eModel::Init connects each kind's models to the
// solids by name -- and its routes, path, topology and collision volumes
// to theirs, and then PostLoadFixup runs. Every frame runs eDisplayFrame's
// order on view 1 -- the view's matrices, the cull infos, DoCulling,
// StuffSky with the Z writes off, StuffScenery -- with eModel::Render
// being this file's draw over georender.
//
// The loads go in the game's order. GLOBALB.BUN's texture packs are the
// boot's (main.c's LoadGlobalChunks); INGAMEB.BUN's, which main() already
// holds for the UI and shares here, go through slot 2 first, as
// LOADING_TRACK_COMMON leaves them.
// Then, as BeginGameFlowLoadingTrackSpecific does, eDisableFixUpTables is
// set and the bundle loads, and TEX<n>TRACK.BIN and TEX<n>LOCATION.BIN
// after it, each read whole; and EndGameFlowLoadingTrackSpecific (trackflow.c)
// clears it, runs eFixUpTables once, and starts the track's systems --
// the collision pools, InitTree, InitPhysics, SkyLoader (sky.c, which takes
// SKYDOME out of the scenery and draws it itself), SunTrackLoader, the
// visible zones' boundary model, the track paths and routes. The sun's
// chunk goes to slot 14 (sun.c) with the rest. eFixUpTables finds each solid's
// textures by GetTextureInfo, the default one for a name no pack has, and
// a solid's texture is the TextureInfo its table points at: the viewer
// uploads the pixels its ImageData and PaletteData point at, and uploads
// again when UpdateTextureAnimations moves them to a flipbook's next frame.
// trackview_free runs BeginGameFlowUnloadingTrackSpecific, which closes
// all of it and hands the three files back newest first.
//
// What stands in for the game, and should not be read as the game:
//
//   * The GS's texture memory. The engine sends a texture's pixels to VRAM
//     each frame it draws; the port uploads each TextureInfo once, and each
//     flipbook frame once, as RGBA8, and keeps them. The light lists are
//     not ported, and the light-material pointers stay NULL.
//   * GLOBALB's other chunks. The game loads the whole bundle at boot; the
//     boot offers slots 2 and 16 its texture packs and car data (main.c),
//     and the viewer hands only INGAMEB's two texture chunks to slot 2,
//     because the UI reads the rest of both as they are on the disc.
//     So InitVisibleZones' MARKER_BOUNDARY, whose solid is INGAMEB's,
//     has none here.
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

#define TRACKVIEW_TRACK        12       // the first track the viewer loads
#define TRACKVIEW_NAME_MAX     32       // "TRACKS/TEX66LOCATION.BIN" and its 0
#define TRACKVIEW_MAX_SOLIDS   1536     // retail's TRACKB61 and B64 have 1,345
#define TRACKVIEW_MAX_OTHER    512      // solids drawn that are not the track's
#define TRACKVIEW_MAX_TEXTURES 1024     // its solids name 415 hashes; then the cars
#define TRACKVIEW_TEX_BUCKET_BITS 11    // find_texture's buckets, twice the list
#define TRACKVIEW_TEX_BUCKETS  (1 << TRACKVIEW_TEX_BUCKET_BITS)
#define TRACKVIEW_NUM_TEXFILES 2        // TEX<n>TRACK.BIN, TEX<n>LOCATION.BIN
#define TRACKVIEW_MAX_SHARED   2        // GLOBALB.BUN, INGAMEB.BUN
#define TRACKVIEW_MAX_SHARED_CHUNKS 8   // their packs and flipbooks: 4
#define TRACKVIEW_MAX_FRAMES   64       // flipbook frames past the first: 46
#define TRACKVIEW_ROUTE        1        // the racing route the stops are on
#define TRACKVIEW_MIRROR_W     256      // the rear-view mirror's target, 7
#define TRACKVIEW_MIRROR_H     64
#define TRACKVIEW_FLAILER_POLYS 128     // a frame's minimap; one race's is ~60
#define TRACKVIEW_STOPS        24       // how many stops round it
#define TRACKVIEW_MAX_DEFERRED 1024     // batches held back for the alpha pass
#define TRACKVIEW_MAX_STRIPS   256      // eBeginStrip's strips in a view
#define TRACKVIEW_MAX_STRIP_VERTS 4096  // and their vertices: the skids'
#define TRACKVIEW_FOG_SAMPLES  5        // depths the fog's fraction is logged at

// One TextureInfo a solid's table points at. `tex` is what the solids'
// slots draw with, a copy of `own` or of one of the flipbook frames'.
typedef struct {
    const TextureInfo* info;
    C3D_Tex  tex;
    C3D_Tex  own;               // the pixels it had when it was first used
    const uint8_t* ownImage;    // and where they were,
    const uint8_t* ownPalette;
    const uint8_t* image;       // and where the ones in `tex` are
    const uint8_t* palette;
    bool     valid;
    uint8_t  level;             // the mip level uploaded, 0 when there was room
    float    uvScale[2];

    // From its TextureInfo, zero for a texture that did not upload.
    GeoPass  pass;
    uint8_t  order;             // RenderingOrder, 0 to 7
    bool     sorted;            // ApplyAlphaSorting
    uint32_t stamp;             // the frame that last used it,
    uint16_t firstUse;          // and where in that frame it was first used
    uint32_t lastUse;           // the texture cache's clock when last drawn
    bool     evicted;           // let go of for room: uploaded again when
                                // next asked for (trackview.c's cache)
    uint32_t retryAt;           // found no room: tried again from this clock
} TrackTex;

// A flipbook frame's pixels, uploaded for `owner` the first time it
// showed them.
typedef struct {
    const void*    owner;       // the TrackTex
    const uint8_t* image;
    const uint8_t* palette;
    C3D_Tex        tex;
} TrackFrame;

// The port's render data for one eSolid, beside GeoSolid storage[i].
typedef struct {
    GeoMesh     mesh;
    GeoTexture* slot;           // numTextures entries
    TrackTex**  tex;            // the same entries' TrackTex, NULL for none
    float     (*centre)[3];     // per batch, the centre of its box
    bool        baked;
    bool        failed;
    bool        dirty;          // trackview_solid_changed since the bake
} TrackSolid;

// A batch the frame holds back for the attach loops' order: its texture is
// not an opaque order-0 one. See trackview_draw. `light` is the model's
// eLightContext, in the frame memory, and `flags` RenderStrips' for the
// batch; see strip_flags. Or one of eBeginStrip's strips, which always
// wait, with `strip` its index in the view's strips; or one of
// RenderEffects' packets, its sprites set `sprites` of trackview.c's.
// `vbo` is a posed model's vertices in the skin ring (georender.h), which
// the batch draws from in place of its solid's; NULL for the solid's.
typedef struct {
    C3D_Mtx     modelView;
    const void* light;
    const GeoRenderVertex* vbo;
    float       depth;          // the centre's view z, +z forward
    uint16_t    solid;
    uint8_t     batch;
    uint8_t     order;
    bool        sorted;
    uint16_t    texUse;
    uint16_t    seq;
    uint16_t    flags;
    int16_t     strip;          // -1 for a batch
    int16_t     sprites;        // -1 but for RenderEffects' packets
} TrackDeferred;

// One of eBeginStrip's strips: its texture, and its vertices in the
// view's store.
typedef struct {
    const TrackTex* tex;
    uint16_t        first;
    uint16_t        count;
} TrackStrip;

typedef struct {
    // --- the track, and its files' names on the card.
    int       track;
    char      bundleName[TRACKVIEW_NAME_MAX];
    char      texName[TRACKVIEW_NUM_TEXFILES][TRACKVIEW_NAME_MAX];
    bool      hasBundle;
    bool      hasTexFile[TRACKVIEW_NUM_TEXFILES];

    // --- the texture packs: the bundles main() shares, which stay its, and
    // the chunks of theirs slot 2 loaded, and the texture files, read whole
    // and resident while their records point into them.
    uint8_t* shared[TRACKVIEW_MAX_SHARED];
    size_t   sharedLen[TRACKVIEW_MAX_SHARED];
    int      numShared;
    uint8_t* sharedChunk[TRACKVIEW_MAX_SHARED_CHUNKS];
    int      numSharedChunks;
    uint8_t* texData[TRACKVIEW_NUM_TEXFILES];
    size_t   texLen[TRACKVIEW_NUM_TEXFILES];
    size_t   texChunkLen[TRACKVIEW_NUM_TEXFILES];
    bool     texLinear[TRACKVIEW_NUM_TEXFILES];
    int      numPacks;          // on TexturePackList once all are loaded
    int      numAnims;          // flipbooks, across TextureAnimPackList

    // --- the bundle, resident for as long as the scenery points into it.
    uint8_t*     data;
    size_t       len;
    size_t       chunkLen;      // what whole top-level chunks cover of len
    bool         dataLinear;    // from linearMemAlign, not memalign
    GeoSolidList list;
    GeoSolid*    solid;         // sorted by header address, as geo_open walks
    TrackSolid*  info;
    int          numSolids;
    // Past the track's, the other solids a model drew: the cars', and the
    // copies eDuplicateSolid made. See render_model.
    int          numOther;
    int          otherDropped;  // past TRACKVIEW_MAX_OTHER, not drawn
    int          otherFailed;   // that geo_open_in_place would not take
    int          linkedSolids;
    TrackTex*    texture;
    int          numTextures;
    // The entries by their TextureInfo: each bucket an entry's index plus
    // one, 0 for none (TASKS 46). Emptied with the list.
    uint16_t     texBucket[TRACKVIEW_TEX_BUCKETS];
    TrackFrame   frame[TRACKVIEW_MAX_FRAMES];
    int          numFrames;

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
    int  skinned;               // of `drawn`, models posed by their bones
    int  skinsDropped;          // posed models the skin ring had no room for
    int  skyDrawn;              // of `drawn`, StuffSky's: the dome, or none
    int  deferredSorted;        // of numDeferred, the ApplyAlphaSorting ones
    int  deferredDropped;       // past TRACKVIEW_MAX_DEFERRED, not drawn
    int  numDeferred;
    uint16_t deferredSeq;       // the next one's seq, for the whole frame
    uint32_t frameStamp;
    uint32_t cacheClock;        // a frame each, for the texture cache
    uint16_t texUses;
    TrackDeferred deferred[TRACKVIEW_MAX_DEFERRED];
    TrackStrip      strips[TRACKVIEW_MAX_STRIPS];
    GeoRenderVertex stripVerts[TRACKVIEW_MAX_STRIP_VERTS];
    int  numStrips;
    int  numStripVerts;
    int  stripsDropped;         // that found the store or the lists full
    int  stripsJoined;          // that went on the end of the one before
    int  stripsDrawn;           // in the frame just drawn
    int  spritesDrawn;          // RenderEffects' sprites, the frame just drawn
    int  spritesDropped;        // that found the store, the lists or the ring full
    int  spritesRefused;        // packets that were not RenderEffects' shape
    int  cmdSkipped;            // draws left out because the GPU list was full
    bool listPending;           // the next frame lists what it draws
    bool listFrame;             // this one did, into drawList
    char drawList[2048];
    int  cmdPeakWords;          // the most of the GPU list a frame has used
    bool frameBegun;            // trackview_draw_envmap began this frame
    int  envFaces;              // environment views drawn this frame
    int  envDrawn;              // and the models drawn into them
    bool mirrorDrawn;           // the mirror's view drew this frame
    int  mirrorModels;          // the models drawn into it
    int  blurBlends;            // radial blur frames blended, since the load
    int  blurFailed;            // and ones with no RADIALBLUR or no room
    int  greyDrawn;             // black and white frames, since the load
    int  greyFailed;            // and ones with no copy or no room

    // --- the sun: what StuffSun drew and asked for, the frame just drawn.
    int   sunQuads;             // quads ePoly::Render drew
    int   sunQuadsFailed;       // and the ones it could not
    float sunAt[2];             // the last quad's middle, the target's pixels
    int   sunAlpha;             // and its alpha, of the GS's 0x80
    int   sunRectX, sunRectY;   // the last Z rect asked for
    int   sunRects;             // rects trackview_read_depth read back
    int   sunSky;               // of their pixels, the ones under 2

    // --- the Flailer polys: TrackMap's, the frame just drawn.
    int   flailerPolys;         // quads trackview_draw_flailer_polys drew
    int   flailerFailed;        // and the ones it could not, or had no room for
    bool  probePending;         // the next read-back logs the probe
    char  probe[512];           // what it found, for main() to log; "" if not

    // --- the fog: eAttachFog's palette for the view, as the PICA's fog.
    int         fogViews;       // views eAttachFog made a palette for
    int         fogUnfit;       // of them, ones the PICA's fog cannot be
    bool        fogOn;          // the frame drew with the fog
    int         fogMode;        // FogMode1
    uint32_t    fogColour;      // the fog's colour, red in the low byte
    float       fogAmount;      // the view's query: its Fog,
    float       fogStart;       // its FogStart,
    const char* fogRegion;      // its root region, or NULL,
    int         fogHits;        // and how many that fade it holds
    uint32_t    fogFrame;       // eFrameCounter as the frame drew
    float       fogKeep[TRACKVIEW_FOG_SAMPLES]; // of the colour, at depths
    float       fogSkyKeep;     // and the sky's

    // --- the frontend's view (trackview_attach_frontend): no track, every
    // solid an other one, and what is to go when the next frame begins.
    bool frontend;
    bool forgetPending;         // trackview_forget_later
    bool freePending;           // trackview_free_later

    // --- counters for the bring-up overlay.
    bool loaded;
    bool attached;              // trackview_attach's: the flow owns `data`
    int  bakedSolids;
    int  bakedTris;
    int  skippedStrips;
    int  missingTextures;       // no TextureInfo, or one that would not upload
    int  reducedTextures;       // uploaded below level 0 for want of room
    int  unchainedTextures;     // uploads with no mip chain, for want of room
    int  evictedTextures;       // let go of for room, least recently drawn first
    int  defaultedHashes;       // table names GetTextureInfo gave the default
    uint32_t defaulted[TRACKVIEW_MAX_TEXTURES];
    int  frameUploads;          // flipbook frames uploaded so far
    int  frameFails;            // and the ones that would not
    // Every bake and upload so far, with its time in system ticks and the
    // longest one's: what a race makes after trackview_prepare is a
    // hitch, and its line says what each second made (2026-10-08).
    int      bakes;
    int      bakesFailed;       // never drawn: a car with none of its body
    int      uploads;
    uint64_t bakeTicks;
    uint64_t uploadTicks;
    uint64_t worstTicks;
    // The editable meshes made to match their solids after CarDamage's
    // walk (trackview_solid_changed), and the time they took.
    int      refreshes;
    uint64_t refreshTicks;
    // trackview_prepare's: the models it went over, the textures it
    // uploaded past theirs, and the ones it left for want of room.
    int  preparedModels;
    int  preparedTextures;
    int  preparedSkipped;
    uint32_t preparedSkippedKB; // their chains at level 0
    bool prepared;
    bool vramOk;                // the prepare's uploads may go to VRAM,
    int  vramTextures;          // and these did,
    uint32_t vramKB;            // in this much of it
    // The names of what was uploaded after it, for the race's line to log
    // and empty: "" when nothing was.
    char lateNames[256];
    int  loadMs;
    char note[64];
} TrackView;

// Names track `track`'s files, TRACKS\TRACKB<track>.BUN and its two
// texture files, and notes whether they are there. Nothing is read yet.
bool trackview_init(TrackView* v, int track);

// The next track past `track` whose bundle is on the card, `step` 1 for
// the one after and -1 for the one before, wrapping; `track` when there is
// no other. The numbers tried are the disc's: a location 1 to 6, then a
// track 1 to 6.
int trackview_next_track(int track, int step);

// Unloads the track the viewer holds, as trackview_free does, and loads
// `track` in its place, keeping the bundles shared with it. The result is
// trackview_load's.
bool trackview_switch(TrackView* v, int track);

// A bundle main() holds resident, 128-aligned, whose texture packs the
// track needs and nothing has loaded: INGAMEB.BUN. (GLOBALB.BUN's, with
// the default texture, are loaded at boot and stay.) After trackview_init;
// the bundle must outlive trackview_free. False when there is no room.
bool trackview_share_bundle(TrackView* v, uint8_t* data, size_t len);

// Loads the shared packs, the bundle and the two texture files through
// the LoaderTable, runs the End of loading, bakes every solid a model names
// and uploads its textures, and puts the camera at the start of route 1.
// False leaves the viewer empty but usable, with `note` saying why. A
// second call does nothing.
bool trackview_load(TrackView* v);

// The race's way in: the track the game flow has already loaded, its
// bundle `data` (the ResourceFile's chunks, `len` bytes) and its texture
// files, and EndGameFlowLoadingTrackSpecific already run. Nothing is read
// or loaded; the solids are found in `data` and baked as trackview_load
// bakes them, and the camera is left to the race's movers.
bool trackview_attach(TrackView* v, uint8_t* data, size_t len);

// The race's whole load of drawing, made before its first frame: every
// model on ModelList baked, its replacement table applied and its
// textures uploaded, as its first draw would; then every texture with
// pixels in every pack, a car's other skins, lights and damage and the
// HUD's and the effects' among them, while the linear heap and the table
// have room to spare. What is left is made as it is drawn, as before. A
// bake or upload mid-race was a hitch: 237 ms for one car (2026-10-08).
void trackview_prepare(TrackView* v);

// The frontend's view, which has no track: every solid it draws is an
// other one (the car select's platform, out of FRONTB.BUN, and the
// frontend's cars), found as a model draws it. Nothing is read or
// loaded. Free it with trackview_free_later.
bool trackview_attach_frontend(TrackView* v);

// A resource or a texture pack is going: the frontend view's solids and
// textures may be over memory that is about to hold something else, so
// they are all forgotten when the next frame begins, before anything
// draws, and found again as they are drawn. A frame the GPU may still be
// drawing is done with by then.
void trackview_forget_later(TrackView* v);

// The frontend is unloading: the frontend view goes, all of it, when the
// next frame begins.
void trackview_free_later(TrackView* v);

// Call it after C3D_FrameBegin, which waits for the GPU, and before
// anything draws: what forget_later and free_later put off happens here,
// and a changed solid that did not bake editable is let go, to bake
// again as it is now when it next draws.
void trackview_frame_begun(TrackView* v);

// CarDamage's walk changed `solid`'s strips (estripdata.h's
// gESolidVerticesChangedFn): an other solid baked from it is dirty. An
// editable one (georender_bake_editable) is refreshed as it next draws;
// any other bakes again after the next trackview_frame_begun. A car's
// solid that BodyDamage walks bakes editable.
void trackview_solid_changed(TrackView* v, const void* solid);

// The frontend's eDisplayFrame (0x00112a38) for view 1 into the bound
// render target, which must have a depth buffer and has had its Flailer
// back layers, 24 to 20, drawn: the cars' solid strips, `render(user)`
// for FlailerScreenList::RenderFlailerModels' RENDER, which draws the car
// select's platform, AttachSolidPolys; the reflections and the cars'
// alpha strips, AttachSolidPolys and AttachAlphaPolys. The environment
// passes read CARSELECTENVMAP. No cull, no sky, no fog. citro2d is to be
// flushed first and prepared again after. False when nothing was drawn.
bool trackview_draw_frontend(TrackView* v, void (*render)(void*),
                             void* user);

// Runs the Begin of unloading, which unloads the track's three files
// through the UnloaderTable newest first; then the shared packs, and frees
// it all. An attached track is the flow's to unload: only the viewer's own
// tables and textures go.
void trackview_free(TrackView* v);

// One frame of the fly camera, into Player1Camera. `kDown` and `kHeld` are
// hidKeysDown() and hidKeysHeld(), `cpx`/`cpy` the circle pad.
void trackview_input(TrackView* v, uint32_t kDown, uint32_t kHeld, int cpx,
                     int cpy, float dt);

// The frame: view 1's matrices, the cull, and StuffScenery into the bound
// render target, which must have a depth buffer; then StuffSun; then the
// rear-view mirror, when trackview_draw_mirror drew it; then, as
// eDisplayFrame ends, the flipbooks' next frames.
void trackview_draw(TrackView* v);

// The Flailer polys ePoly::Render was handed since the last call -- the
// minimap's, from Player::RenderTrackMap -- drawn on the bound target,
// `width` by `height`, which takes the Flailer's 640 by 480; then the
// queue starts again. The PS2 attaches them at eDisplayFrame's end, after
// the HUD's Flailer layers, with each one's GS Z from its z; here they
// draw in the order of those Zs, the lowest first, and in the order given
// within one. Each vertex is first moved to x * scale + dx and y * scale
// + dy in the 640 by 480 (hudsplit_map_place; 1, 0, 0 for where Render
// put it). citro2d is flushed first and is to be prepared again after, as
// for georender_draw_hud_quad.
void trackview_draw_flailer_polys(TrackView* v, float width, float height,
                                  float scale, float dx, float dy);

// The environment map's targets, and the fold's triangles from the sample
// table, which eenvmap_init has to have built. False if there is no room.
bool trackview_envmap_init(void);

// The frame's start, which trackview_draw makes itself when this has not
// -- UpdateEnvironmentMapCameras, the views' matrices and the cull -- and
// then the environment views that are active this frame, each into its
// face of the cube, and those folded into the sphere map the cars'
// environment passes read (see eenvmap.h). Call it between C3D_FrameBegin
// and the top target's C3D_FrameDrawOn, before trackview_draw; it leaves
// the sphere map's target, or a face's, bound.
void trackview_draw_envmap(TrackView* v);

// The rear-view mirror's target, 256 by 64 as retail's target 7. False if
// there is no room; the race then has no mirror.
bool trackview_mirror_init(void);

// The rear-view mirror's view, 3, into its target, when the view and the
// target are active -- with a RearViewMirrorCameraMover on it, view mode 2
// -- and then the mirror's frame over it (DisplayRVMImages). After
// trackview_draw_envmap and before the top target's C3D_FrameDrawOn;
// trackview_draw puts the mirror on the top screen (DisplayRVMs).
void trackview_draw_mirror(TrackView* v);

// The Z rects StuffSun asked for in the frame before, out of `target`'s
// depth buffer and into their SunZBuffers, the way the PS2's transfer
// queue fills them once the frame is drawn. Call it between
// C3D_FrameBegin, which waits for the GPU, and the target's clear.
void trackview_read_depth(TrackView* v, C3D_RenderTarget* target);

// The capture's legend (capture.h): each texture's C3D_Tex, as a numbered
// draw names it, and the name and size of what it holds.
void trackview_capture_names(const TrackView* v);
