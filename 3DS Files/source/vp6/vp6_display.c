/*
 * vp6_display.c -- see vp6_display.h.
 *
 * Texture upload uses the real PICA200 8x8-tile swizzle format documented
 * on 3dbrew.org's "Texture Format" page (standard, publicly-documented GPU
 * hardware layout, not proprietary): within each 8x8 tile the 64 texels are
 * addressed by a Z-order (Morton) interleave of the low 3 bits of the
 * tile-local x/y coordinate, LSB first:
 *   index = x0 | (y0<<1) | (x1<<2) | (y1<<3) | (x2<<4) | (y2<<5)
 * (x0/x1/x2 = bits 0/1/2 of x, y0/y1/y2 = bits 0/1/2 of y). Tiles themselves
 * are stored row-major, top row of the image first.
 *
 * C3D_TexUpload()/C3D_TexLoadImage() does NOT re-tile a linear source for
 * you -- a same-session experiment that fed a plain row-major RGBA buffer
 * straight to C3D_TexUpload (skipping the manual swizzle below) produced
 * WORSE on-hardware corruption than this (repeated/tiled ghost copies of
 * the frame across the screen), confirming the GPU reads texture memory
 * pre-tiled and this manual swizzle is required. Do not remove it again
 * without on-hardware (not just Azahar) verification.
 *
 * An earlier version of this file had the bit order scrambled
 * (x0|x2<<1|y1<<2|x1<<3|y0<<4|y2<<5) -- a host-side round-trip test (encode
 * with this formula, decode with the same formula) came back "clean" since
 * it only proves internal self-consistency, not a match to what the real
 * PICA200 texture unit expects. On real hardware/Azahar this produced a
 * fine blocky/interleaved corruption pattern across every video (worse on
 * higher-detail content like PSA.vp6, subtle but present on ealogo/THX),
 * because whole sub-blocks of each 8x8 tile were being read from the wrong
 * source pixel.
 */
#include "vp6_display.h"
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

/* Open+write+close per call, same rationale as main.c's dlog() -- avoids
 * corrupting/reordering output against other short-lived log writers to the
 * same file from other threads (this file now has one: the decode worker). */
static void perflog(const char *msg) {
    FILE *f = fopen("sdmc:/nfshp2_debug.txt", "a");
    if (f) { fprintf(f, "[vp6-thread] %s\n", msg); fclose(f); }
}

/* Set by main.c via vp6_set_decode_core() before any players are opened. */
static int g_decode_core_id = -1;

void vp6_set_decode_core(int coreId) {
    g_decode_core_id = coreId;
    char b[64];
    snprintf(b, sizeof(b), "decode core set to %d", coreId);
    perflog(b);
}

#define VP6_DECODE_THREAD_STACK_SIZE (64 * 1024)
#define VP6_DECODE_THREAD_PRIO 0x30

static int execute2_single_thread(AVCodecContext *avctx,
                                   int (*func)(AVCodecContext *c2, void *arg, int jobnr, int threadnr),
                                   void *arg, int *ret, int count) {
    for (int i = 0; i < count; i++) {
        int r = func(avctx, arg, i, 0);
        if (ret) ret[i] = r;
    }
    return 0;
}

/* Strictly greater than v, not just >= -- see the #57 fix note in
 * ensure_texture() for why a POT input (e.g. 512, which is exactly one of
 * our boot clips' real decoded heights) must still get padding above it. */
static int next_pow2(int v) {
    int p = 1;
    while (p <= v) p <<= 1;
    return p < 8 ? 8 : p;
}

/* Lookup-table clamp: a branch-per-pixel clamp is branch-predictor-unfriendly
 * on the 3DS's simple in-order ARM11 core, and this runs 3x per pixel every
 * frame. Covers the full range r/g/b can reach (Y in [0,255] plus/minus a
 * chroma contribution of up to ~230). */
static uint8_t g_clip_lut[768];
static bool g_clip_lut_ready = false;

static void init_clip_lut(void) {
    if (g_clip_lut_ready)
        return;
    for (int i = 0; i < 768; i++) {
        int v = i - 256;
        g_clip_lut[i] = (uint8_t)(v < 0 ? 0 : (v > 255 ? 255 : v));
    }
    g_clip_lut_ready = true;
}

static inline uint8_t clip_u8(int v) {
    int idx = v + 256;
    if (idx < 0) idx = 0;
    else if (idx > 767) idx = 767;
    return g_clip_lut[idx];
}

/* BT.601 YUV420P -> RGBA8 (linear, row-major, top row first).
 *
 * Integer fixed-point (16.16) instead of per-pixel double math: the 3DS's
 * ARM11 VFP handles double precision very slowly, and this function runs
 * over every pixel of every frame, so the original floating-point version
 * (1.402 * V, etc.) was costing ~100ms/frame on real hardware -- by far the
 * single biggest cost in the whole decode+display pipeline, badly starving
 * frame throughput and making 30fps video play back at ~5fps. */
#define FP_SHIFT 16
#define FP_R_V   91881   /* round(1.402    * 65536) */
#define FP_G_U   22554   /* round(0.344136 * 65536) */
#define FP_G_V   46802   /* round(0.714136 * 65536) */
#define FP_B_U  116130   /* round(1.772    * 65536) */

/* Combined YUV420P->RGBA8 convert + PICA200 8x8-tile swizzle, in one pass.
 * Doing these as two separate full-frame passes (convert to a linear RGBA
 * scratch buffer, then re-read that whole buffer to swizzle it) means every
 * pixel is written once and read+written again -- a full extra frame's worth
 * of memory traffic and loop/index-math overhead for no reason, since the
 * swizzled destination address is just as cheap to compute per-source-pixel
 * as the linear one. Fusing them removes that whole second pass. */
/* out_w/out_h are the real decoded frame size divided by `div` (2 or 4, see
 * the #63 perf fix note in ensure_texture() and vp6_display.h's
 * downscaleDiv doc) -- every output pixel is a nearest-neighbor downsample,
 * sampled at the source luma's (px*div, py*div). Chroma is already
 * 2x2-subsampled relative to luma, so at div==2 out_w x out_h is exactly the
 * chroma plane's own resolution (chromaStep==1, urow[px]/vrow[px] directly,
 * same as the original #63 code); at div==4 chroma still needs a further 2x
 * nearest-neighbor step (chromaStep==2, urow[px*2]/vrow[px*2]). */
static void yuv420p_to_tiled_rgba(const AVFrame *f, int out_w, int out_h, int div,
                                   uint8_t *tiled, int tex_w, int tex_h) {
    int chromaStep = div / 2;
    const uint8_t *y_plane = f->data[0];
    /* Plain BT.601, standard ffmpeg data[1]=U/data[2]=V plane convention, no
     * swap or sign inversion. An earlier version of this function swapped
     * AND negated both chroma planes based on a comparison against the boot
     * logo's near-neutral badge, which "looked plausible either way" and
     * masked the real bug. A later, pixel-exact check (pinning the actual
     * "EA"/"GAMES" letter pixels -- the only part of the frame with strongly
     * differing chroma -- against ffmpeg's own from-scratch decode of the
     * same real ealogo.vp6 file, then trying all 8 swap/negate combinations
     * against those pinned raw Y/U/V samples) showed the swap+negate
     * transform reproduces almost exactly the *wrong*, teal/blue-swapped
     * colors this port was actually displaying, while plain/unswapped
     * BT.601 reproduces the correct blue-EA/teal-GAMES split to within a few
     * intensity units. So the vendored VP6 decoder's data[1]/data[2] planes
     * already match ffmpeg's own convention -- the swap+negate "fix" was a
     * misdiagnosis of a bug that lived elsewhere (see git history around
     * this comment for the exact host-side A/B script). */
    const uint8_t *u_plane = f->data[1];
    const uint8_t *v_plane = f->data[2];
    int y_stride = f->linesize[0];
    int u_stride = f->linesize[1];
    int v_stride = f->linesize[2];
    int blocks_x = tex_w >> 3;

    /* No per-frame clear here: every tile cell inside [0,out_w)x[0,out_h) is
     * fully overwritten by the loop below every single frame (out_w/out_h
     * are exact multiples of 8 for all three boot clips, so no partial-tile
     * remainder is ever left stale), and the POT-padding region outside that
     * is cleared once in ensure_texture() and never touched again. Clearing
     * the whole (possibly 4x larger, post-#57-fix) tex_w*tex_h buffer here
     * every frame was pure wasted memory bandwidth. */

    for (int py = 0; py < out_h; py++) {
        const uint8_t *yrow = y_plane + (py * div) * y_stride;
        const uint8_t *urow = u_plane + (py * chromaStep) * u_stride;
        const uint8_t *vrow = v_plane + (py * chromaStep) * v_stride;
        int ty_block = py >> 3, ly = py & 7;

        for (int px = 0; px < out_w; px++) {
            int U = urow[px * chromaStep] - 128;
            int V = vrow[px * chromaStep] - 128;
            int dr = (FP_R_V * V) >> FP_SHIFT;
            int dg = -((FP_G_U * U + FP_G_V * V) >> FP_SHIFT);
            int db = (FP_B_U * U) >> FP_SHIFT;
            int Y = yrow[px * div];

            int tx_block = px >> 3, lx = px & 7;
            int local = (lx & 1) | ((ly & 1) << 1) | (((lx >> 1) & 1) << 2) |
                        (((ly >> 1) & 1) << 3) | (((lx >> 2) & 1) << 4) | (((ly >> 2) & 1) << 5);
            uint8_t *dest = tiled + ((size_t)(ty_block * blocks_x + tx_block) * 64 + local) * 4;
            /* PICA200's GPU_RGBA8 format stores each texel in memory as
             * bytes [A,B,G,R], not [R,G,B,A] -- a well-documented 3DS GPU
             * quirk (the format name describes the bit-packed word read
             * MSB-first, but bytes land in memory in the reverse order).
             * Writing naive RGBA byte order here uploads fine but
             * displays with R/A swapped and G/B shifted, which is what
             * was producing the red/pink cast even after the chroma
             * decode fix above was verified correct in isolation (that
             * fix was checked against a raw PPM dump, which never goes
             * through this GPU texture format at all). */
            dest[0] = 255;
            dest[1] = clip_u8(Y + db);
            dest[2] = clip_u8(Y + dg);
            dest[3] = clip_u8(Y + dr);
        }
    }
}

bool vp6_player_open(Vp6Player *p, const char *path, int downscaleDiv) {
    memset(p, 0, sizeof(*p));
    init_clip_lut();
    p->downscaleDiv = (downscaleDiv == 4) ? 4 : 2;

    if (!ea_demux_open(&p->demux, path))
        return false;

    p->fps = p->demux.fps;
    p->nb_frames = p->demux.nb_frames;

    p->ctx.priv_data = av_mallocz(sizeof(VP56Context));
    if (!p->ctx.priv_data) {
        ea_demux_close(&p->demux);
        return false;
    }
    p->ctx.codec_id = AV_CODEC_ID_VP6;
    static const AVCodecDesc vp6_codec_desc = { AV_CODEC_ID_VP6 };
    p->ctx.codec = &vp6_codec_desc;
    p->ctx.execute2 = execute2_single_thread;

    if (vp6_decode_init(&p->ctx) < 0) {
        av_free(p->ctx.priv_data);
        ea_demux_close(&p->demux);
        return false;
    }

    p->frame = av_frame_alloc();
    if (!p->frame) {
        vp6_decode_free(&p->ctx);
        av_free(p->ctx.priv_data);
        ea_demux_close(&p->demux);
        return false;
    }

    p->dispBuf = 0;
    p->workBuf = 0;
    /* Actual thread creation is deferred to vp6_player_advance()'s first
     * call, after the first frame's synchronous decode has determined
     * vid_w/vid_h and allocated both tiled_rgba[] buffers via
     * ensure_texture() -- threadCreate() itself is cheap and fine to call
     * per-clip rather than once globally. */
    p->threaded = false;
    p->pipelineStarted = false;
    p->decodeInFlight = false;
    p->shouldStop = false;

    return true;
}

static bool ensure_texture(Vp6Player *p) {
    if (p->tex_ready)
        return true;
    if (p->ctx.width <= 0 || p->ctx.height <= 0)
        return false;

    /* #63 perf fix (session 24): decode at the real bitstream resolution
     * (needed -- VP6 can't be told to decode at half-res) but only convert
     * +tile+display at a FRACTION of it in each dimension (nearest-neighbor
     * downsample, fused into yuv420p_to_tiled_rgba() below). All three boot
     * clips are 768x512 decoded but only ever drawn scaled down to fit the
     * 400x240 top screen (~360x240 at most) -- the full 768x512 conversion
     * was quality wasted on downscaling anyway. Dividing each dimension by
     * p->downscaleDiv (2, or 4 for clips that still ran behind their own
     * audio at 2 -- see the EA logo note in main.c's kVideoStages[] handling)
     * cuts the conversion loop's pixel count 4x/16x (by far the biggest
     * per-frame CPU cost after the VP6 bitstream decode itself) and the GPU
     * texture/upload size the same factor (1024x1024x4=4MB at div=2 ->
     * 512x512x4=1MB, or 256x256x4=256KB at div=4), which was suspected of
     * contributing to PSA's reported slow/desynced playback -- PSA is the
     * only one of the three clips long/heavy enough (709 frames vs 94/148)
     * for a real per-frame CPU decode-throughput shortfall to be visible as
     * sustained slow motion rather than a one-off hitch. Requires
     * ctx.width/height to be evenly divisible by downscaleDiv, true of all
     * three real boot clips (768x512) for both 2 and 4. */
    p->vid_w = p->ctx.width / p->downscaleDiv;
    p->vid_h = p->ctx.height / p->downscaleDiv;
    /* #57 fix: next_pow2() now always leaves at least one POT step of
     * padding above vid_w/vid_h, even when vid_w/vid_h is itself already a
     * power of two (true of all three boot clips' 512px height). Before this
     * fix, THX/PSA's tex_h==vid_h==512 meant the subtexture's V range spanned
     * the GPU texture's *entire* height with zero slack at the top edge --
     * the leading suspect for #57's top-of-frame noise band (see TASKS.md),
     * since the horizontal case (tex_w=1024 > vid_w=768) never had this
     * exact-match condition and never showed the artifact. tex_w/tex_h are
     * now always strictly larger than vid_w/vid_h. */
    p->tex_w = next_pow2(p->vid_w);
    p->tex_h = next_pow2(p->vid_h);

    /* #57/#55 fix: this buffer is handed straight to GSPGPU_FlushDataCache +
     * C3D_TexUpload, i.e. it's read by the GPU's transfer engine via a
     * physical address, not just CPU-side. Regular av_malloc()/malloc()
     * comes from the normal application heap, which is NOT guaranteed
     * physically contiguous or suitably aligned for GPU DMA on 3DS -- only
     * the dedicated "linear heap" (linearAlloc/linearMemAlign) is. A
     * host-side dump of this exact buffer's *pre-upload* bytes (a one-shot
     * debug hook, since removed) proved the CPU-side YUV->RGBA+tile
     * conversion was already byte-perfect for a corrupted THX frame, so the
     * bug had to be downstream of this allocation choice -- the GPU reading
     * a bad/misaligned physical address for a malloc'd buffer is the
     * textbook explanation for exactly this "garbage band"/"garbage frame"
     * signature, and switching this one allocation to linearMemAlign fixed
     * both #57 (THX top band) and #55 (PSA full-frame static) at once,
     * confirming they were the same bug. 128-byte alignment matches what
     * citro3d's own examples use for texture source buffers. */
    size_t bufBytes = (size_t)p->tex_w * p->tex_h * 4;
    p->tiled_rgba[0] = (uint8_t *)linearMemAlign(bufBytes, 128);
    p->tiled_rgba[1] = (uint8_t *)linearMemAlign(bufBytes, 128);
    if (!p->tiled_rgba[0] || !p->tiled_rgba[1]) {
        linearFree(p->tiled_rgba[0]);
        linearFree(p->tiled_rgba[1]);
        p->tiled_rgba[0] = p->tiled_rgba[1] = NULL;
        return false;
    }
    /* One-time clear of the padding region outside [0,vid_w)x[0,vid_h) --
     * see the comment in yuv420p_to_tiled_rgba() for why this doesn't need
     * to happen again every frame. Both buffers need it since either can
     * end up bound to the GPU texture. */
    memset(p->tiled_rgba[0], 0, bufBytes);
    memset(p->tiled_rgba[1], 0, bufBytes);

    for (int i = 0; i < 2; i++) {
        if (!C3D_TexInit(&p->tex[i], (u16)p->tex_w, (u16)p->tex_h, GPU_RGBA8))
            return false;
        /* GPU_LINEAR was previously blamed for a "noise band" when
         * downscaling was added, and reverted to GPU_NEAREST (blockier, but
         * clean). That band was actually the #57/#55 malloc'd-texture-buffer
         * bug above -- once the source buffer moved to linearMemAlign(), the
         * real cause was gone, so GPU_LINEAR is safe to use again and gives
         * smooth (not blocky/pixelated) scaling for these clips, which are
         * always drawn downscaled to fit the 400x240 top screen. */
        C3D_TexSetFilter(&p->tex[i], GPU_LINEAR, GPU_LINEAR);
        C3D_TexSetWrap(&p->tex[i], GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);

        p->subtex[i].width  = (u16)p->vid_w;
        p->subtex[i].height = (u16)p->vid_h;
        p->subtex[i].left   = 0.0f;
        p->subtex[i].top    = 1.0f;
        p->subtex[i].right  = (float)p->vid_w / (float)p->tex_w;
        p->subtex[i].bottom = 1.0f - (float)p->vid_h / (float)p->tex_h;

        p->image[i].tex = &p->tex[i];
        p->image[i].subtex = &p->subtex[i];
    }

    p->tex_ready = true;
    return true;
}

/* Decodes one EA video packet's VP6 bitstream into p->frame. Touches only
 * p->demux/p->ctx/p->frame -- never a tiled_rgba[] buffer or anything
 * GPU-facing -- so it's safe to run off the main thread, and safe to call
 * before ensure_texture() (i.e. before vid_w/vid_h/tex_w/tex_h are even
 * known) for the very first frame. Returns false on real EOF/decode error;
 * on success, sets *wroteFrame to false for a duplicate/empty EA chunk
 * (nothing new to convert/display) or true for a real decoded frame. */
static bool decode_bitstream_frame(Vp6Player *p, bool *wroteFrame) {
    *wroteFrame = false;

    uint8_t *data = NULL;
    int size = 0;
    bool key = false;

    if (!ea_demux_read_video_packet(&p->demux, &data, &size, &key))
        return false;

    if (size == 0)
        return true; /* duplicate/empty chunk */

    AVPacket pkt = { .data = data, .size = size };
    int got_frame = 0;
    int ret = ff_vp56_decode_frame(&p->ctx, p->frame, &got_frame, &pkt);
    av_free(data);

    if (ret < 0 || !got_frame)
        return false;

    *wroteFrame = true;
    return true;
}

/* Full per-frame step used once the tiled_rgba[] buffers exist: decodes the
 * bitstream, and (if it produced a real frame) converts+tiles it straight
 * into dstBuf. Safe to run on the decode worker thread -- see
 * decode_bitstream_frame()'s comment; the only extra thing this adds
 * (yuv420p_to_tiled_rgba) touches only p->frame (read) and dstBuf (write),
 * never anything shared/GPU-facing either. */
static bool decode_one_frame(Vp6Player *p, uint8_t *dstBuf, bool *wroteFrame) {
    if (!decode_bitstream_frame(p, wroteFrame))
        return false;
    if (*wroteFrame) {
        yuv420p_to_tiled_rgba(p->frame, p->vid_w, p->vid_h, p->downscaleDiv, dstBuf, p->tex_w, p->tex_h);
    }
    return true;
}

/* Decode worker thread body. Waits for the main thread to hand it a buffer
 * (via evStart), decodes exactly one frame into it, and reports back (via
 * evDone) -- one request/response pair per real frame, giving a strict
 * single-frame lookahead pipeline with no queue/ring-buffer bookkeeping
 * needed. Pinned to g_decode_core_id (New3DS core2, or Old3DS's system core0
 * given extra time via APT_SetAppCpuTimeLimit -- see main.c) so this
 * genuinely overlaps with the main thread's render/display/audio/input work
 * on its own core instead of time-slicing it. */
static void vp6_decode_worker(void *arg) {
    Vp6Player *p = (Vp6Player *)arg;
    for (;;) {
        LightEvent_Wait(&p->evStart);
        LightEvent_Clear(&p->evStart);
        if (p->shouldStop)
            return;

        bool wroteFrame = false;
        bool ok = decode_one_frame(p, p->tiled_rgba[p->workBuf], &wroteFrame);
        p->decodeOk = ok;
        p->decodeWroteFrame = wroteFrame;
        LightEvent_Signal(&p->evDone);
    }
}

static bool start_decode_thread(Vp6Player *p) {
    LightEvent_Init(&p->evStart, RESET_ONESHOT);
    LightEvent_Init(&p->evDone, RESET_ONESHOT);
    p->shouldStop = false;

    p->decodeThread = threadCreate(vp6_decode_worker, p, VP6_DECODE_THREAD_STACK_SIZE,
                                    VP6_DECODE_THREAD_PRIO, g_decode_core_id, false);
    if (!p->decodeThread) {
        char b[128];
        snprintf(b, sizeof(b), "threadCreate for decode worker on core %d FAILED, falling back to synchronous decode", g_decode_core_id);
        perflog(b);
        return false;
    }

    char b[64];
    snprintf(b, sizeof(b), "decode worker thread started on core %d", g_decode_core_id);
    perflog(b);
    return true;
}

/* Kicks off a decode into p->workBuf on the worker thread; caller must
 * LightEvent_Wait(&p->evDone) before reading p->decodeOk/decodeWroteFrame or
 * touching p->tiled_rgba[p->workBuf]. */
static void request_decode(Vp6Player *p) {
    p->decodeInFlight = true;
    LightEvent_Signal(&p->evStart);
}

bool vp6_player_advance(Vp6Player *p) {
    if (!p->pipelineStarted) {
        p->pipelineStarted = true;

        /* First frame is always decoded synchronously on the calling
         * (main) thread: vid_w/vid_h/tex_w/tex_h/the tiled_rgba[] buffers
         * aren't known/allocated until after the first successful decode
         * (ensure_texture(), called below, needs p->ctx.width/height which
         * the VP6 bitstream itself supplies) -- there is nothing yet for a
         * worker thread to safely write into before that point. */
        bool wroteFrame = false;
        p->dispBuf = 0;
        p->workBuf = 0;
        if (!decode_bitstream_frame(p, &wroteFrame))
            return false;
        if (!wroteFrame) {
            /* Extremely unlikely (a duplicate chunk before any real frame
             * has ever been decoded), but handle it: nothing to display or
             * pipeline yet, just report "no progress" for this tick. */
            p->pipelineStarted = false;
            p->frames_decoded++;
            return true;
        }

        if (!ensure_texture(p))
            return false;

        yuv420p_to_tiled_rgba(p->frame, p->vid_w, p->vid_h, p->downscaleDiv, p->tiled_rgba[0], p->tex_w, p->tex_h);

        GSPGPU_FlushDataCache(p->tiled_rgba[0], (u32)p->tex_w * p->tex_h * 4);
        C3D_TexUpload(&p->tex[0], p->tiled_rgba[0]);
        p->frames_decoded++;

        if (g_decode_core_id >= 0)
            p->threaded = start_decode_thread(p);

        if (p->threaded) {
            /* Kick off lookahead decode of the second frame into buffer 1
             * while this first frame is on screen. */
            p->workBuf = 1;
            request_decode(p);
        }
        return true;
    }

    if (!p->threaded) {
        /* Synchronous fallback: decode straight into the single displayed
         * buffer, exactly like the pre-threading implementation. */
        bool wroteFrame = false;
        if (!decode_one_frame(p, p->tiled_rgba[p->dispBuf], &wroteFrame))
            return false;
        if (wroteFrame) {
            GSPGPU_FlushDataCache(p->tiled_rgba[p->dispBuf], (u32)p->tex_w * p->tex_h * 4);
            C3D_TexUpload(&p->tex[p->dispBuf], p->tiled_rgba[p->dispBuf]);
        }
        p->frames_decoded++;
        return true;
    }

    /* Threaded steady state: the worker has been decoding p->workBuf in the
     * background since the previous call (or since pipeline startup). Wait
     * for it, consume the result, then immediately re-arm the worker so the
     * next frame decodes while this one is being displayed. */
    LightEvent_Wait(&p->evDone);
    LightEvent_Clear(&p->evDone);
    p->decodeInFlight = false;

    if (!p->decodeOk)
        return false;

    if (p->decodeWroteFrame) {
        GSPGPU_FlushDataCache(p->tiled_rgba[p->workBuf], (u32)p->tex_w * p->tex_h * 4);
        C3D_TexUpload(&p->tex[p->workBuf], p->tiled_rgba[p->workBuf]);
        p->dispBuf = p->workBuf;
        p->workBuf = 1 - p->dispBuf;
    }
    /* else: duplicate/empty chunk -- keep displaying p->dispBuf unchanged,
     * and keep decoding into the same p->workBuf next time too, since it
     * was never written this round. */

    p->frames_decoded++;
    request_decode(p);
    return true;
}

void vp6_player_draw(Vp6Player *p, float boxX, float boxY, float maxW, float maxH) {
    if (!p->tex_ready)
        return;
    float scale = maxW / (float)p->vid_w;
    float scaleH = maxH / (float)p->vid_h;
    if (scaleH < scale)
        scale = scaleH;
    float x = boxX + (maxW - (float)p->vid_w * scale) / 2.0f;
    float y = boxY + (maxH - (float)p->vid_h * scale) / 2.0f;
    C2D_DrawImageAt(p->image[p->dispBuf], x, y, 0.5f, NULL, scale, scale);
}

void vp6_player_close(Vp6Player *p) {
    if (p->threaded) {
        /* Wake the worker with shouldStop set so it exits its wait loop
         * instead of blocking forever on an evStart that will never come
         * again. It may currently be mid-decode from the last
         * request_decode() call (steady-state pipelining always leaves one
         * in flight) -- wait for that to actually finish before signaling
         * stop, so it isn't torn down while still touching p->frame/p->ctx. */
        if (p->decodeInFlight) {
            LightEvent_Wait(&p->evDone);
            p->decodeInFlight = false;
        }
        p->shouldStop = true;
        LightEvent_Signal(&p->evStart);
        threadJoin(p->decodeThread, U64_MAX);
        threadFree(p->decodeThread);
        p->threaded = false;
    }

    if (p->tex_ready) {
        C3D_TexDelete(&p->tex[0]);
        C3D_TexDelete(&p->tex[1]);
    }
    linearFree(p->tiled_rgba[0]);
    linearFree(p->tiled_rgba[1]);
    if (p->frame)
        av_frame_free(&p->frame);
    if (p->ctx.priv_data) {
        vp6_decode_free(&p->ctx);
        av_free(p->ctx.priv_data);
    }
    ea_demux_close(&p->demux);
    memset(p, 0, sizeof(*p));
}
