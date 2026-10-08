// frameprof -- the race's frame, phase by phase, a line a second in the log
// (step 13b-2). The port's own: retail's per-phase print, PrintTimingStat
// and MaybePrintTiming, is compiled out of both images (mainloop.h).
//
// main.c stamps MainLoopTiming's ten ticks through each frame, as MainLoop
// does, at the port's own phase ends. The port's loop runs the phases in
// another order than MainLoop's, and folds some together:
//
//   StartTime           the top of the frame
//   UpdateSound         after the sound, which the port runs first
//   ServiceGameFlow     after bgf_frame: the clocks, the pads, the flow
//   MenuSystemTick        and the menus' tick, which is bgf_frame's
//   GenerateJoyEvents   after raceFrame's coordinator and the events
//   WorldDoTimestep     after the world's step
//   UpdateCameraMovers  after the players and the cameras
//   DisplayFrame        after C3D_FrameEnd: the waits and the draw
//   ServiceFileSystem   after the resource loading
//   LimitFrameRate      the frame's end
//
// With no race, the three race stamps are ServiceGameFlow's. The wait for
// the vertical blank, which MainLoop does last, is at the start of the
// port's draw, in C3D_FrameSync. It and the wait for the GPU (citro3d's in
// C3D_FrameBegin) are timed apart and taken out of the draw.
//
// The draw is split further, by FrameProfDraw's ticks, which main.c and
// trackview.c stamp with FRAMEPROF_STAMP at each stage's end:
//
//   prep     UpdateCameraMovers to the waits: the track's attach, the log,
//            the blurb
//   cull     after the waits: the sun's Z rects read back, then
//            trackview's begin_frame: the frame memory, the views'
//            matrices, and scenery_do_culling for every view
//   envmap   the six cube views drawn, and the fold to the sphere map
//   mirror   the rear-view mirror's view, 3, drawn into its target, and
//            its frame
//   sky      StuffSky and its lists
//   models   scenery_stuff_scenery: eModel::Render for each model the
//            cull kept, its batches drawn or put on the lists
//   scenery  StuffSun and the scenery's solid list drawn
//   cars     RenderCars, the cars' solids, and both alpha lists
//   hud      the rest of trackview_draw and the top screen's Flailer layers
//   bottom   the bottom screen: its Flailer layers and the minimap
//   submit   C3D_FrameEnd
//
// A stage not stamped in a frame takes no time in it.
//
// The jukebox's worker shares core 0 with the game and preempts it
// wherever it wakes, so its time is inside the phases. main.c hands its
// decode and its reads for the frame to frameprof (jbstream_busy). Only
// the decode is CPU time: a read sleeps in the kernel (step 13b-3).
//
// trackview's render_model, eModel::Render, counts what it draws (step
// 13b-4): FrameProfDraw.models, the player's view's [0], the envmap's
// faces' [1] and the mirror's [2]. Its line follows the frame's. Timing its parts cost 5 ms a
// frame on Azahar, a system tick read being an SVC, so it is not timed.
//
// A line has the frame rate, the mean frame and the longest, each phase's
// mean in milliseconds, the draw's stages, the two waits, citro3d's own two
// times (the CPU's from C3D_FrameBegin to C3D_FrameEnd, and the GPU's), and
// retail's two rates from CalculateFrameRate. The milliseconds are the EE
// tick's exactly, 294912 to the millisecond, and not bGetTickerDifference's,
// which are 1.7% short.
//
// Write-up: docs/formats/frame-profiler.md.

#ifndef FRAMEPROF_H
#define FRAMEPROF_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "bticker.h"
#include "mainloop.h"

enum {
    FRAMEPROF_SOUND,
    FRAMEPROF_FLOW,
    FRAMEPROF_RACE,
    FRAMEPROF_WORLD,
    FRAMEPROF_CAMERAS,
    FRAMEPROF_DRAW,
    FRAMEPROF_VSYNC,
    FRAMEPROF_GPU_WAIT,
    FRAMEPROF_LOADS,
    FRAMEPROF_PHASES
};

// The draw's stages, stamped at their ends.
enum {
    FRAMEPROF_CULL,
    FRAMEPROF_ENVMAP,
    FRAMEPROF_MIRROR,
    FRAMEPROF_SKY,
    FRAMEPROF_MODELS,
    FRAMEPROF_SCENERY,
    FRAMEPROF_CARS,
    FRAMEPROF_HUD,
    FRAMEPROF_BOTTOM,
    FRAMEPROF_STAMPED
};

// render_model's counts in a frame, for one view or the envmap's faces.
enum {
    FRAMEPROF_M_MODELS,     // models drawn
    FRAMEPROF_M_NOW,        // batches drawn at once
    FRAMEPROF_M_LIT,        // lit or environment-mapped batches, each alone
    FRAMEPROF_M_HELD,       // batches put on the lists
    FRAMEPROF_M_WORDS,      // GPU command words written
    FRAMEPROF_M_INDICES,    // the batches' indices, three a triangle,
                            // held ones too
    FRAMEPROF_M_COUNT
};

// One frame's draw: the ticks around the two waits, and each stamped
// stage's end (0 when it was not stamped).
typedef struct FrameProfTicks {
    uint32_t sync;      // before the wait for the blank
    uint32_t gpu;       // after it, before C3D_FrameBegin's wait
    uint32_t draw;      // after C3D_FrameBegin
    uint32_t end[FRAMEPROF_STAMPED];
    uint32_t jukeboxDecode;     // the jukebox worker's, this frame
    uint32_t jukeboxRead;
    uint32_t models[3][FRAMEPROF_M_COUNT];  // the view's, the envmap's,
                                            // the mirror's
} FrameProfTicks;

extern FrameProfTicks FrameProfDraw;

#define FRAMEPROF_STAMP(stage) (FrameProfDraw.end[(stage)] = bGetTicker())

// The draw's stages in the sums: prep, the nine stamped, and submit.
#define FRAMEPROF_DRAW_STAGES (FRAMEPROF_STAMPED + 2)

typedef struct FrameProf {
    uint32_t frames;
    uint64_t total;                     // EE ticks, StartTime to the end
    uint64_t phase[FRAMEPROF_PHASES];   // EE ticks
    uint64_t stage[FRAMEPROF_DRAW_STAGES];
    uint64_t jukeboxDecode;
    uint64_t jukeboxRead;
    uint64_t models[3][FRAMEPROF_M_COUNT];
    uint32_t worst;                     // the longest frame, EE ticks
    float    c3dCpuMs;                  // summed
    float    c3dGpuMs;
} FrameProf;

void frameprof_reset(FrameProf *fp);

// A frame's draw is starting: the stamped ends are cleared, so a stage the
// frame skips takes no time.
void frameprof_begin_draw(uint32_t sync, uint32_t gpu, uint32_t draw);

// One frame, from its ten ticks, FrameProfDraw, and citro3d's two times in
// milliseconds.
void frameprof_add(FrameProf *fp, const MainLoopTimingStats *t,
                   float c3dCpuMs, float c3dGpuMs);

// Once the frames add up to a second: the line into buf, the sums reset,
// and true. The models' line follows the frame's, after a newline.
bool frameprof_line(FrameProf *fp, char *buf, size_t n);

#endif
