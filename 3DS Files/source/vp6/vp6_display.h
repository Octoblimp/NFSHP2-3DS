/*
 * vp6_display.h -- glues ea_demux + the vendored VP6 decoder + a citro2d/
 * citro3d GPU texture together so a real decoded EA boot-movie frame can be
 * drawn on screen, replacing the black-screen placeholder in main.c.
 */
#ifndef VP6_DISPLAY_H
#define VP6_DISPLAY_H

#include <3ds.h>
#include <citro2d.h>
#include <stdbool.h>
#include "vp6_api.h"
#include "ea_demux.h"

typedef struct Vp6Player {
    EaDemuxer       demux;
    AVCodecContext  ctx;
    AVFrame        *frame;

    int      vid_w, vid_h;   /* real (visible) decoded frame size, AFTER downscaleDiv */
    int      tex_w, tex_h;   /* power-of-2 texture size the frame is tiled into */
    int      downscaleDiv;   /* 2 or 4 -- see vp6_player_open() */

    /* Double-buffered so a worker thread (see vp6_set_decode_core()) can
     * decode+convert the NEXT frame into one buffer while the GPU is still
     * reading the other (last-uploaded) buffer, overlapping VP6 bitstream
     * decode -- by far the most expensive per-frame step -- with this
     * frame's on-screen display time instead of paying for it serially in
     * the render loop. Falls back to using only tiled_rgba[0] and decoding
     * fully synchronously inside vp6_player_advance() when no worker thread
     * could be started (threaded == false), so playback is correct either
     * way, just without the pipelining speedup. */
    uint8_t *tiled_rgba[2];
    int      dispBuf;        /* index currently bound to tex / last uploaded */
    int      workBuf;        /* index the worker is decoding into (threaded only) */

    Thread     decodeThread;
    LightEvent evStart;      /* main -> worker: "decode a frame into workBuf" */
    LightEvent evDone;       /* worker -> main: that decode finished */
    bool       threaded;
    bool       pipelineStarted;
    volatile bool decodeOk;         /* result of the worker's last decode */
    volatile bool decodeWroteFrame; /* false for duplicate/empty EA chunks */
    volatile bool decodeInFlight;   /* true between request_decode() and the
                                        matching evDone wait -- lets close()
                                        know whether it must drain one more
                                        result before it's safe to stop the
                                        worker */
    volatile bool shouldStop;

    /* #64 fix: one GPU texture object PER tiled_rgba[] buffer, indexed the
     * same way (tex[dispBuf] is always the one currently bound for drawing,
     * matching tiled_rgba[dispBuf]'s contents). Previously a single shared
     * C3D_Tex was re-uploaded from alternating CPU buffers every frame;
     * even with the upload moved after C3D_FrameBegin(SYNCDRAW) (see
     * main.c), PSA still reliably corrupted to a thin top strip by ~frame
     * 30 while EA/THX never did (same code path, same 1024x1024 texture --
     * only difference is PSA's ~5-7x higher frame count giving far more
     * chances to hit whatever the real hazard is). Giving each buffer index
     * its own texture object means a texture is only ever written once
     * every OTHER displayed frame, so even if TexUpload's completion isn't
     * as synchronous as expected relative to a queued draw, that draw is
     * always sampling the texture object nothing has touched since it was
     * last fully live. */
    C3D_Tex          tex[2];
    Tex3DS_SubTexture subtex[2];
    C2D_Image        image[2];
    bool             tex_ready;

    double fps;
    unsigned nb_frames;
    unsigned frames_decoded;
} Vp6Player;

/* Sets which CPU core new Vp6Players' decode worker threads should be
 * pinned to: 2 on New3DS (a real extra core, not shared with the main
 * render/game thread on core1 or the O3DS-compatible system core0), 0 on
 * Old3DS (the system core -- requires the caller to have already granted
 * this app extra time on it via APT_SetAppCpuTimeLimit()), or -1 to disable
 * threaded decode entirely and always use the old fully-synchronous path.
 * Call once at startup, before any vp6_player_open(); affects players opened
 * afterward. See main.c's platform-detection block. */
void vp6_set_decode_core(int coreId);

/* Opens 'path' (a real EA MVhd/.../MV0K container, e.g. ealogo.vp6) and
 * initializes the vendored VP6 decoder. Starts a decode worker thread
 * (pinned per vp6_set_decode_core()) if one was requested and could be
 * created; otherwise falls back to synchronous decoding transparently.
 * Returns false on any failure (missing file, malformed container, decoder
 * init failure).
 *
 * downscaleDiv is the factor each dimension of the real decoded bitstream
 * frame (VP6 itself can't be told to decode at a reduced resolution -- this
 * only affects the CPU convert+tile pass and the resulting GPU texture size,
 * same lever as the #63 fix) is divided by before conversion. Must be 2 or 4
 * (yuv420p_to_tiled_rgba's chroma sampling assumes an even divisor, and all
 * three real boot clips are 768x512 -- evenly divisible by either). Pass 2
 * for the existing #63 behavior; 4 halves the conversion pass's pixel count
 * again (and the GPU texture size 4x further) for clips that are still
 * running behind their own audio even at divisor 2 -- see the EA logo perf
 * note in main.c's kVideoStages[] handling. */
bool vp6_player_open(Vp6Player *p, const char *path, int downscaleDiv);

/* Decodes the next video frame and, on success, converts+tiles it into the
 * GPU texture and updates p->image to reference the new contents. Returns
 * false when the clip has ended (no more frames) or on decode error. */
bool vp6_player_advance(Vp6Player *p);

/* Draws the current decoded frame scaled (preserving aspect ratio) to fit
 * within a maxW x maxH box, centered within it at (boxX, boxY). Boot clips
 * are 768x512, larger than the 3DS's 400x240 top screen, so this always
 * scales down rather than drawing at the texture's native 1:1 pixel size.
 * No-op if no frame has been decoded yet. */
void vp6_player_draw(Vp6Player *p, float boxX, float boxY, float maxW, float maxH);

void vp6_player_close(Vp6Player *p);

#endif /* VP6_DISPLAY_H */
