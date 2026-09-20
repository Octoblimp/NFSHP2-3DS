#include "movie.h"

#include <stdlib.h>
#include <string.h>

// -- little-endian readers, so the file is byte-order independent and none of
// -- this needs the frame buffer to be aligned.

static uint16_t rd16(const uint8_t* p)
{
    return (uint16_t)(p[0] | (p[1] << 8));
}

static uint32_t rd32(const uint8_t* p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

bool m3v_parse_header(const uint8_t* buf, size_t len, M3VInfo* out)
{
    if (!buf || !out || len < M3V_HEADER_SIZE) return false;
    if (rd32(buf) != M3V_MAGIC) return false;

    memset(out, 0, sizeof(*out));
    out->width         = rd16(buf + 0x04);
    out->height        = rd16(buf + 0x06);
    out->frames        = rd16(buf + 0x08);
    out->fps           = rd16(buf + 0x0A);
    out->format        = rd16(buf + 0x0C);
    out->tileBytes     = rd16(buf + 0x0E);
    out->maxFrameLen   = rd32(buf + 0x10);
    out->frameTableOff = rd32(buf + 0x14);
    out->audioOff      = rd32(buf + 0x18);
    out->audioLen      = rd32(buf + 0x1C);
    out->audioRate     = rd32(buf + 0x20);
    out->audioChannels = rd16(buf + 0x24);
    out->audioBits     = rd16(buf + 0x26);

    if (out->format != M3V_FMT_RGB565_TILED) return false;
    if (out->tileBytes != M3V_TILE_PIXELS * 2) return false;
    if (out->frames == 0 || out->fps == 0) return false;
    if (out->width == 0 || out->height == 0) return false;
    if ((out->width % M3V_TILE) || (out->height % M3V_TILE)) return false;
    if (out->frameTableOff < M3V_HEADER_SIZE) return false;
    if (out->maxFrameLen == 0) return false;
    return true;
}

// -- the RLE16 reader --------------------------------------------------------
//
// A u16 control word: bit 15 set means "the next pixel, (ctrl & 0x7fff) + 1
// times"; clear means "ctrl + 1 literal pixels follow". The reader keeps the
// remainder of a run across calls, because the baker lets runs cross tile
// boundaries -- a black band spanning eight tiles costs one control word, not
// eight.

typedef struct {
    const uint8_t* p;
    const uint8_t* end;
    uint32_t       left;     // pixels still owed by the current run
    uint16_t       px;       // its pixel, when it is a repeat
    bool           literal;
} M3VRle;

static bool rle_pull(M3VRle* r, uint16_t* dst, uint32_t count)
{
    while (count) {
        if (r->left == 0) {
            uint16_t ctrl;
            if ((size_t)(r->end - r->p) < 2) return false;
            ctrl = rd16(r->p);
            r->p += 2;
            if (ctrl & 0x8000) {
                if ((size_t)(r->end - r->p) < 2) return false;
                r->px      = rd16(r->p);
                r->p      += 2;
                r->left    = (uint32_t)(ctrl & 0x7FFF) + 1;
                r->literal = false;
            } else {
                r->left    = (uint32_t)ctrl + 1;
                r->literal = true;
                if ((size_t)(r->end - r->p) < (size_t)r->left * 2) return false;
            }
        }
        {
            uint32_t n = r->left < count ? r->left : count;
            uint32_t i;
            if (r->literal) {
                for (i = 0; i < n; i++) { dst[i] = rd16(r->p); r->p += 2; }
            } else {
                for (i = 0; i < n; i++) dst[i] = r->px;
            }
            dst   += n;
            count -= n;
            r->left -= n;
        }
    }
    return true;
}

bool m3v_apply(const uint8_t* body, size_t len, uint16_t* surface,
               uint32_t numTiles)
{
    M3VRle   rle;
    uint32_t bitmapLen, i;
    const uint8_t* bitmap = NULL;

    if (!body || !surface || len < 1) return false;

    if (body[0] == 0) {                       // full frame: every tile follows
        rle.p = body + 1;
    } else if (body[0] == 1) {                // delta: a changed-tile bitmap
        bitmapLen = (numTiles + 7) / 8;
        if (len < 1 + bitmapLen) return false;
        bitmap = body + 1;
        rle.p  = body + 1 + bitmapLen;
    } else {
        return false;
    }
    rle.end     = body + len;
    rle.left    = 0;
    rle.px      = 0;
    rle.literal = false;

    for (i = 0; i < numTiles; i++) {
        if (bitmap && !(bitmap[i >> 3] & (1 << (i & 7)))) continue;
        if (!rle_pull(&rle, surface + (size_t)i * M3V_TILE_PIXELS,
                      M3V_TILE_PIXELS))
            return false;
    }
    return true;
}

// -- the movie ---------------------------------------------------------------

bool m3v_open(M3VMovie* m, const char* path, uint16_t* surface)
{
    uint8_t  head[M3V_HEADER_SIZE];
    size_t   tableBytes;

    if (!m || !path) return false;
    memset(m, 0, sizeof(*m));

    m->file = fopen(path, "rb");
    if (!m->file) return false;

    if (fread(head, 1, sizeof(head), m->file) != sizeof(head)
        || !m3v_parse_header(head, sizeof(head), &m->info)) {
        m3v_close(m);
        return false;
    }

    m->numTiles = (uint32_t)(m->info.width / M3V_TILE)
                * (uint32_t)(m->info.height / M3V_TILE);

    tableBytes = (size_t)m->info.frames * 8;
    m->table   = (uint32_t*)malloc(tableBytes);
    m->frameBuf = (uint8_t*)malloc(m->info.maxFrameLen);
    if (!m->table || !m->frameBuf) { m3v_close(m); return false; }

    if (fseek(m->file, (long)m->info.frameTableOff, SEEK_SET) != 0) {
        m3v_close(m);
        return false;
    }
    {
        // Read the table as bytes so the file stays little-endian everywhere.
        uint8_t* raw = (uint8_t*)m->table;
        size_t   i;
        if (fread(raw, 1, tableBytes, m->file) != tableBytes) {
            m3v_close(m);
            return false;
        }
        for (i = 0; i < (size_t)m->info.frames * 2; i++)
            m->table[i] = rd32(raw + i * 4);
    }

    if (surface) {
        m->surface    = surface;
        m->ownSurface = false;
    } else {
        m->surface = (uint16_t*)calloc((size_t)m->info.width * m->info.height,
                                       sizeof(uint16_t));
        m->ownSurface = true;
        if (!m->surface) { m3v_close(m); return false; }
    }
    return true;
}

void m3v_close(M3VMovie* m)
{
    if (!m) return;
    if (m->file) fclose(m->file);
    free(m->table);
    free(m->frameBuf);
    if (m->ownSurface) free(m->surface);
    memset(m, 0, sizeof(*m));
}

bool m3v_next(M3VMovie* m)
{
    uint32_t off, len;

    if (!m || !m->file || m->nextFrame >= m->info.frames) return false;

    off = m->table[m->nextFrame * 2];
    len = m->table[m->nextFrame * 2 + 1];
    if (len == 0 || len > m->info.maxFrameLen) return false;

    if (fseek(m->file, (long)off, SEEK_SET) != 0) return false;
    if (fread(m->frameBuf, 1, len, m->file) != len) return false;
    if (!m3v_apply(m->frameBuf, len, m->surface, m->numTiles)) return false;

    m->nextFrame++;
    return true;
}

bool m3v_finished(const M3VMovie* m)
{
    if (!m || !m->file) return true;
    return m->nextFrame >= m->info.frames
        && m->clock >= m3v_duration(m);
}

float m3v_duration(const M3VMovie* m)
{
    if (!m || m->info.fps == 0) return 0.0f;
    return (float)m->info.frames / (float)m->info.fps;
}

bool m3v_drive(M3VMovie* m, float dt)
{
    uint32_t want;

    if (!m || !m->file) return true;
    if (dt > 0.0f) m->clock += dt;

    // Frame N is on screen from N/fps onwards, so the frame the clock asks
    // for is floor(clock * fps) + 1 frames' worth of decoding. Falling behind
    // decodes the gap rather than skipping it: at three seconds and 90 frames
    // a dropped frame is more visible than a late one.
    want = (uint32_t)(m->clock * (float)m->info.fps) + 1u;
    if (want > m->info.frames) want = m->info.frames;
    while (m->nextFrame < want) {
        if (!m3v_next(m)) {
            m->nextFrame = m->info.frames;   // malformed: stop, and finish
            break;
        }
    }
    return m3v_finished(m);
}

bool m3v_baked_path(const char* ps2Path, char* out, size_t cap)
{
    size_t n, i, dot;

    if (!ps2Path || !out || cap == 0) return false;
    n = strlen(ps2Path);
    if (n + 1 > cap) return false;

    for (i = 0; i < n; i++)
        out[i] = (ps2Path[i] == '\\') ? '/' : ps2Path[i];
    out[n] = '\0';

    // Swap the extension in place; every entry of TitleMoviesToPlay is a
    // `.AVI`, but do not assume it.
    dot = n;
    for (i = n; i > 0; i--) {
        if (out[i - 1] == '/') break;
        if (out[i - 1] == '.') { dot = i - 1; break; }
    }
    if (dot + 4 + 1 > cap) return false;
    memcpy(out + dot, ".M3V", 4);
    out[dot + 4] = '\0';
    return true;
}

// -- the 3DS half ------------------------------------------------------------

#ifdef __3DS__
bool m3v_tex_open(M3VMovie* m, C3D_Tex* tex, const char* path)
{
    M3VMovie probe;

    if (!m || !tex || !path) return false;

    // The header has to be read before the texture can be sized, and the
    // texture has to exist before the movie can decode into it, so open once
    // to learn the size and again to keep.
    if (!m3v_open(&probe, path, NULL)) return false;
    {
        u16 w = probe.info.width, h = probe.info.height;
        m3v_close(&probe);
        if (!C3D_TexInit(tex, w, h, GPU_RGB565)) return false;
    }

    if (!m3v_open(m, path, (uint16_t*)tex->data)) {
        C3D_TexDelete(tex);
        return false;
    }
    C3D_TexSetFilter(tex, GPU_LINEAR, GPU_LINEAR);
    C3D_TexSetWrap(tex, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);

    // Frame 0 is a full frame, so the texture is never shown uninitialised.
    memset(tex->data, 0, (size_t)tex->size);
    m3v_next(m);
    C3D_TexFlush(tex);
    return true;
}

void m3v_tex_close(M3VMovie* m, C3D_Tex* tex)
{
    if (m) m3v_close(m);
    if (tex && tex->data) C3D_TexDelete(tex);
}

bool m3v_tex_drive(M3VMovie* m, C3D_Tex* tex, float dt)
{
    uint32_t before = m ? m->nextFrame : 0;
    bool done = m3v_drive(m, dt);
    if (m && tex && m->nextFrame != before) C3D_TexFlush(tex);
    return done;
}
#endif
