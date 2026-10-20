// capture -- the top screen as the device drew it, onto the card. See
// capture.h.

#include "capture.h"

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <3ds.h>

#include "configitems.h"
#include "hangwatch.h"

#define CAP_W       400
#define CAP_H       240
#define CAP_LEGEND  (512 * 1024)

// The pause's pictures: the 240 by 400 buffer halved each way, RGB565.
#define PF_W        120
#define PF_H        200
#define PF_BYTES    (PF_W * PF_H * 2)
#define PF_SLOT     0xC000      // a picture's room, 4 KB pages
#define PF_FILES    8           // a boot's most; the rest are only logged

static uint8_t*       s_pfRing;     // linear: PAUSE_FRAMES pictures
static PauseFrameNote s_pfNote[PAUSE_FRAMES];
static int            s_pfNext;     // the slot the next picture goes in
static int            s_pfCount;    // the pictures kept
static PauseFrameNote s_pfLast;     // the frame just drawn, its picture next
static bool           s_pfNoted;
static int            s_pfState;    // 0 keeping, 1 to write, 2 written
static int            s_pfFiles;

static bool     s_racing;
static bool     s_armed;
static int      s_state;        // 0 waiting, 1 drawn, 2 numbered, 3 level 0, 4 done
static u64      s_start;
static int      s_seconds = CAPTURE_SECONDS;
static bool     s_ids;
static bool     s_lod0;
static bool     s_offscreen;
static int      s_nextId;
static char*    s_legend;
static size_t   s_legendLen;
static size_t   s_legendCap;
static int      s_legendDropped;

void capture_race(bool racing)
{
    FILE* f;

    if (racing == s_racing) {
        return;
    }
    s_racing = racing;
    s_armed  = false;
    s_ids    = false;
    s_lod0   = false;
    if (!racing) {
        // The ring goes at capture_pause_frame, once the GPU is done.
        return;
    }
    if (ConfigPauseLog && s_pfRing == NULL) {
        s_pfRing = (uint8_t*)linearMemAlign(PAUSE_FRAMES * PF_SLOT, 0x1000);
        hangwatch_log("pause frames: %s %d frames of %dx%d (%d KB)",
                      s_pfRing ? "keeping" : "no linear heap to keep",
                      PAUSE_FRAMES, PF_H, PF_W,
                      PAUSE_FRAMES * PF_SLOT / 1024);
    }
    s_pfNext  = 0;
    s_pfCount = 0;
    s_pfNoted = false;
    s_pfState = 0;
    f = fopen(CAPTURE_FLAG, "r");
    if (f == NULL) {
        return;
    }
    s_seconds = CAPTURE_SECONDS;
    if (fscanf(f, "%d", &s_seconds) != 1 || s_seconds < 0) {
        s_seconds = CAPTURE_SECONDS;
    }
    fclose(f);
    s_armed = true;
    s_state = 0;
    s_start = osGetTime();
    hangwatch_log("capture: armed, the frame %d s in", s_seconds);
}

// A top-screen pixel's word in the 240 by 400 buffers citro3d renders to,
// as trackview.c's tiled_index finds it.
static uint32_t tiled_index(int x, int y)
{
    uint32_t bx = (uint32_t)(239 - y);
    uint32_t by = (uint32_t)x;
    uint32_t m  = (bx & 1u) | ((by & 1u) << 1) | ((bx & 2u) << 1)
                | ((by & 2u) << 2) | ((bx & 4u) << 2) | ((by & 4u) << 3);

    return ((by >> 3) * (240u / 8u) + (bx >> 3)) * 64u + m;
}

static void put16(uint8_t* p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}

static void put32(uint8_t* p, uint32_t v)
{
    put16(p, v);
    put16(p + 2, v >> 16);
}

// A buffer's 400 by 240 words as a 24-bit BMP, each word's bits 23 to 16
// red, 15 to 8 green and 7 to 0 blue, `shift` to the right first. A row
// at a time: in a race the heap may not have the whole picture's 288 KB.
static bool write_bmp(const char* path, const uint32_t* buf, int shift)
{
    const size_t row  = CAP_W * 3;
    const size_t size = 54 + row * CAP_H;
    uint8_t      head[54];
    uint8_t      line[CAP_W * 3];
    FILE*        f;
    bool         ok;
    int          x, y;

    if (buf == NULL) {
        return false;
    }
    memset(head, 0, sizeof head);
    head[0] = 'B';
    head[1] = 'M';
    put32(head + 2, (uint32_t)size);
    put32(head + 10, 54);
    put32(head + 14, 40);
    put32(head + 18, CAP_W);
    put32(head + 22, CAP_H);
    put16(head + 26, 1);
    put16(head + 28, 24);
    put32(head + 34, (uint32_t)(row * CAP_H));
    f  = fopen(path, "wb");
    ok = f != NULL && fwrite(head, 1, sizeof head, f) == sizeof head;
    // The BMP's rows go from the bottom up.
    for (y = CAP_H - 1; ok && y >= 0; y--) {
        uint8_t* p = line;

        for (x = 0; x < CAP_W; x++) {
            uint32_t w = buf[tiled_index(x, y)] >> shift;

            *p++ = (uint8_t)w;
            *p++ = (uint8_t)(w >> 8);
            *p++ = (uint8_t)(w >> 16);
        }
        ok = fwrite(line, 1, row, f) == row;
    }
    if (f != NULL) {
        ok = fclose(f) == 0 && ok;
    }
    return ok;
}

static bool write_legend(const char* path)
{
    FILE* f = fopen(path, "w");
    bool  ok;

    if (f == NULL) {
        return false;
    }
    ok = s_legend == NULL
      || fwrite(s_legend, 1, s_legendLen, f) == s_legendLen;
    if (s_legendDropped) {
        fprintf(f, "(%d lines more did not fit)\n", s_legendDropped);
    }
    return fclose(f) == 0 && ok;
}

bool capture_read(C3D_RenderTarget* top)
{
    const uint32_t* colour;
    bool            ok;

    if (!s_armed || top == NULL || top->frameBuf.width != 240
        || top->frameBuf.height != 400) {
        return false;
    }
    colour = (const uint32_t*)top->frameBuf.colorBuf;
    switch (s_state) {
    case 0:
        // The frame about to be drawn is the one, read once it is.
        if (osGetTime() - s_start >= (u64)s_seconds * 1000u) {
            s_state = 1;
        }
        break;
    case 1:
        // The colour words are RGBA, red on top; the depth's are the
        // stencil over the 24 bits.
        ok = write_bmp("sdmc:/nfshp2_cap_colour.bmp", colour, 8);
        ok = write_bmp("sdmc:/nfshp2_cap_depth.bmp",
                       (const uint32_t*)top->frameBuf.depthBuf, 0) && ok;
        hangwatch_log("capture: the frame %s", ok ? "written" : "NOT written");
        free(s_legend);
        // As much of the legend as the heap has room for.
        s_legendCap = CAP_LEGEND;
        s_legend    = (char*)malloc(s_legendCap);
        while (s_legend == NULL && s_legendCap > 16 * 1024) {
            s_legendCap /= 2;
            s_legend = (char*)malloc(s_legendCap);
        }
        s_legendLen     = 0;
        s_legendDropped = 0;
        s_nextId        = 0;
        s_ids           = true;
        s_state         = 2;
        return true;
    case 2:
        s_ids = false;
        ok    = write_bmp("sdmc:/nfshp2_cap_ids.bmp", colour, 8);
        ok    = write_legend("sdmc:/nfshp2_cap_ids.txt") && ok;
        hangwatch_log("capture: %d draws numbered, %s", s_nextId,
                      ok ? "written" : "NOT written");
        free(s_legend);
        s_legend = NULL;
        s_lod0   = true;
        s_state  = 3;
        break;
    case 3:
        s_lod0 = false;
        ok     = write_bmp("sdmc:/nfshp2_cap_lod0.bmp", colour, 8);
        hangwatch_log("capture: the frame at level 0 %s",
                      ok ? "written" : "NOT written");
        s_state = 4;
        s_armed = false;
        break;
    default:
        break;
    }
    return false;
}

bool capture_ids_on(void)
{
    return s_ids && !s_offscreen;
}

bool capture_lod0_on(void)
{
    return s_lod0 && !s_offscreen;
}

void capture_offscreen(bool on)
{
    s_offscreen = on;
}

int capture_next_id(void)
{
    return ++s_nextId;
}

// ------------------------------------------------------- the pause's frames

static void put_le32(FILE* f, uint32_t v, bool* ok)
{
    uint8_t b[4];

    put32(b, v);
    *ok = *ok && fwrite(b, 1, 4, f) == 4;
}

// The ring to the card, oldest first: "NFSHP2PF", a version, the count,
// the buffer's width and height, each picture's frame and world time,
// then the pictures as the transfer engine wrote them, and the notes to
// the log.
static void pause_write(void)
{
    char     path[40];
    FILE*    f    = NULL;
    bool     ok   = true;
    int      from = (s_pfNext - s_pfCount + PAUSE_FRAMES) % PAUSE_FRAMES;
    uint64_t t0   = osGetTime();
    int      i;

    if (s_pfCount == 0) {
        hangwatch_log("pause frames: none kept yet");
        return;
    }
    if (s_pfFiles >= PF_FILES) {
        hangwatch_log("pause frames: %d kept, not written (%d files "
                      "already this boot)", s_pfCount, PF_FILES);
        return;
    }
    snprintf(path, sizeof path, "sdmc:/nfshp2_pause_%d.bin", ++s_pfFiles);
    // The transfer engine wrote them past the CPU's cache.
    GSPGPU_InvalidateDataCache(s_pfRing, PAUSE_FRAMES * PF_SLOT);
    f  = fopen(path, "wb");
    ok = f != NULL && fwrite("NFSHP2PF", 1, 8, f) == 8;
    if (ok) {
        put_le32(f, 1, &ok);
        put_le32(f, (uint32_t)s_pfCount, &ok);
        put_le32(f, PF_W, &ok);
        put_le32(f, PF_H, &ok);
    }
    for (i = 0; ok && i < s_pfCount; i++) {
        const PauseFrameNote* n = &s_pfNote[(from + i) % PAUSE_FRAMES];
        uint32_t              w;

        memcpy(&w, &n->world, 4);
        put_le32(f, n->frame, &ok);
        put_le32(f, w, &ok);
    }
    for (i = 0; ok && i < s_pfCount; i++) {
        const uint8_t* p = s_pfRing
                         + (size_t)((from + i) % PAUSE_FRAMES) * PF_SLOT;

        ok = fwrite(p, 1, PF_BYTES, f) == PF_BYTES;
    }
    if (f != NULL) {
        ok = fclose(f) == 0 && ok;
    }
    hangwatch_log("pause frames: %d to %s, %s in %lu ms; picture k is the "
                  "frame of pause frame k's line", s_pfCount, path,
                  ok ? "written" : "NOT written",
                  (unsigned long)(osGetTime() - t0));
    for (i = 0; i < s_pfCount; i++) {
        const PauseFrameNote* n = &s_pfNote[(from + i) % PAUSE_FRAMES];

        hangwatch_log("pause frame %d: frame %lu, world %.3f s, camera "
                      "%.2f %.2f %.2f looking %.3f %.3f %.3f, zone %ld; "
                      "track drew %ld of %ld (%ld sky), %ld tris, %ld "
                      "skipped; sun %ld quads alpha %ld, %ld sky; strips "
                      "%ld, sprites %ld; cpu %.1f ms, gpu %.1f ms",
                      i, (unsigned long)n->frame, (double)n->world,
                      (double)n->pos[0], (double)n->pos[1],
                      (double)n->pos[2], (double)n->dir[0],
                      (double)n->dir[1], (double)n->dir[2], (long)n->zone,
                      (long)n->drawn, (long)n->infos, (long)n->sky,
                      (long)n->tris, (long)n->skipped, (long)n->sunQuads,
                      (long)n->sunAlpha, (long)n->sunSky, (long)n->strips,
                      (long)n->sprites, (double)n->cpuMs, (double)n->gpuMs);
    }
}

void capture_pause_frame(C3D_RenderTarget* top, bool paused)
{
    if (s_pfRing == NULL) {
        return;
    }
    if (!s_racing) {
        linearFree(s_pfRing);
        s_pfRing = NULL;
        return;
    }
    switch (s_pfState) {
    case 1:
        // C3D_FrameBegin has waited for the last picture's transfer.
        pause_write();
        s_pfState = 2;
        return;
    case 2:
        // Back from the pause: a new ring for the next one.
        if (!paused) {
            s_pfState = 0;
            s_pfCount = 0;
            s_pfNoted = false;
        }
        return;
    default:
        break;
    }
    // The last frame's picture, before this frame's clear: queued first,
    // so the GPU takes it before the first send's commands.
    if (s_pfNoted && top != NULL && top->frameBuf.width == 240
        && top->frameBuf.height == 400) {
        GX_DisplayTransfer((u32*)top->frameBuf.colorBuf,
                           GX_BUFFER_DIM(240, 400),
                           (u32*)(s_pfRing + (size_t)s_pfNext * PF_SLOT),
                           GX_BUFFER_DIM(240, 400),
                           GX_TRANSFER_FLIP_VERT(0) | GX_TRANSFER_OUT_TILED(0)
                           | GX_TRANSFER_RAW_COPY(0)
                           | GX_TRANSFER_IN_FORMAT(GX_TRANSFER_FMT_RGBA8)
                           | GX_TRANSFER_OUT_FORMAT(GX_TRANSFER_FMT_RGB565)
                           | GX_TRANSFER_SCALING(GX_TRANSFER_SCALE_XY));
        s_pfNote[s_pfNext] = s_pfLast;
        s_pfNext           = (s_pfNext + 1) % PAUSE_FRAMES;
        if (s_pfCount < PAUSE_FRAMES) {
            s_pfCount++;
        }
    }
    s_pfNoted = false;
    if (paused) {
        s_pfState = 1;
    }
}

void capture_pause_note(const PauseFrameNote* n)
{
    if (s_pfRing != NULL && s_pfState == 0) {
        s_pfLast  = *n;
        s_pfNoted = true;
    }
}

void capture_note(const char* fmt, ...)
{
    va_list ap;
    int     n;

    if (!s_ids || s_legend == NULL) {
        return;
    }
    if (s_legendCap - s_legendLen < 256) {
        s_legendDropped++;
        return;
    }
    va_start(ap, fmt);
    n = vsnprintf(s_legend + s_legendLen, s_legendCap - s_legendLen - 1, fmt,
                  ap);
    va_end(ap);
    if (n < 0) {
        return;
    }
    if ((size_t)n > s_legendCap - s_legendLen - 2) {
        n = (int)(s_legendCap - s_legendLen - 2);
    }
    s_legendLen += (size_t)n;
    s_legend[s_legendLen++] = '\n';
}
