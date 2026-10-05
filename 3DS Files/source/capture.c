// capture -- the top screen as the device drew it, onto the card. See
// capture.h.

#include "capture.h"

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <3ds.h>

#include "hangwatch.h"

#define CAP_W       400
#define CAP_H       240
#define CAP_LEGEND  (512 * 1024)

static bool     s_racing;
static bool     s_armed;
static int      s_state;        // 0 waiting, 1 drawn, 2 numbered, 3 level 0, 4 done
static u64      s_start;
static int      s_seconds = CAPTURE_SECONDS;
static bool     s_ids;
static bool     s_lod0;
static int      s_nextId;
static char*    s_legend;
static size_t   s_legendLen;
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
        return;
    }
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
// red, 15 to 8 green and 7 to 0 blue, `shift` to the right first.
static bool write_bmp(const char* path, const uint32_t* buf, int shift)
{
    const size_t row  = CAP_W * 3;
    const size_t size = 54 + row * CAP_H;
    uint8_t*     out  = (uint8_t*)malloc(size);
    FILE*        f;
    bool         ok;
    int          x, y;

    if (out == NULL || buf == NULL) {
        free(out);
        return false;
    }
    memset(out, 0, 54);
    out[0] = 'B';
    out[1] = 'M';
    put32(out + 2, (uint32_t)size);
    put32(out + 10, 54);
    put32(out + 14, 40);
    put32(out + 18, CAP_W);
    put32(out + 22, CAP_H);
    put16(out + 26, 1);
    put16(out + 28, 24);
    put32(out + 34, (uint32_t)(row * CAP_H));
    for (y = 0; y < CAP_H; y++) {
        uint8_t* p = out + 54 + row * (size_t)(CAP_H - 1 - y);

        for (x = 0; x < CAP_W; x++) {
            uint32_t w = buf[tiled_index(x, y)] >> shift;

            *p++ = (uint8_t)w;
            *p++ = (uint8_t)(w >> 8);
            *p++ = (uint8_t)(w >> 16);
        }
    }
    f  = fopen(path, "wb");
    ok = f != NULL && fwrite(out, 1, size, f) == size;
    if (f != NULL) {
        ok = fclose(f) == 0 && ok;
    }
    free(out);
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
        s_legend        = (char*)malloc(CAP_LEGEND);
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
    return s_ids;
}

bool capture_lod0_on(void)
{
    return s_lod0;
}

int capture_next_id(void)
{
    return ++s_nextId;
}

void capture_note(const char* fmt, ...)
{
    va_list ap;
    int     n;

    if (!s_ids || s_legend == NULL) {
        return;
    }
    if (CAP_LEGEND - s_legendLen < 256) {
        s_legendDropped++;
        return;
    }
    va_start(ap, fmt);
    n = vsnprintf(s_legend + s_legendLen, CAP_LEGEND - s_legendLen - 1, fmt,
                  ap);
    va_end(ap);
    if (n < 0) {
        return;
    }
    if ((size_t)n > CAP_LEGEND - s_legendLen - 2) {
        n = (int)(CAP_LEGEND - s_legendLen - 2);
    }
    s_legendLen += (size_t)n;
    s_legend[s_legendLen++] = '\n';
}
