#include "bfont.h"

#include <string.h>

#include "bchunk.h"

#define GLYPH_SIZE 32
#define KERN_SIZE  8

static void read_glyph(const uint8_t* g, BGlyph* out)
{
    out->id         = bchunk_u16(g + 0);
    out->kernPairs  = bchunk_u16(g + 2);
    out->posX       = bchunk_f32(g + 4);
    out->posY       = bchunk_f32(g + 8);
    out->width      = bchunk_f32(g + 12);
    out->height     = bchunk_f32(g + 16);
    out->advance    = bchunk_f32(g + 20);
    out->offset     = bchunk_f32(g + 24);
    out->kernFirst  = bchunk_u32(g + 28);
}

bool bfont_parse(BFont* f, const uint8_t* payload, uint32_t size)
{
    if (!payload || size < 20) return false;

    memset(f, 0, sizeof(*f));
    // The chunk header is mChunkID/mChunkSize, so everything the file
    // addresses is relative to 8 bytes before the payload.
    f->chunk     = payload - 8;
    f->chunkSize = (size_t)size + 8;

    f->hash       = bchunk_u32(payload + 0);
    f->numGlyphs  = bchunk_u32(payload + 4);
    f->numKerning = bchunk_u32(payload + 8);
    uint32_t glyphOff = bchunk_u32(payload + 12);
    uint32_t kernOff  = bchunk_u32(payload + 16);

    if (f->numGlyphs == 0) return false;
    if (glyphOff + (size_t)f->numGlyphs * GLYPH_SIZE > f->chunkSize)
        return false;
    if (f->numKerning &&
        kernOff + (size_t)f->numKerning * KERN_SIZE > f->chunkSize)
        return false;

    f->glyphs  = f->chunk + glyphOff;
    f->kerning = f->numKerning ? f->chunk + kernOff : NULL;

    for (int i = 0; i < 256; i++) f->lookup[i] = -1;
    for (uint32_t i = 0; i < f->numGlyphs; i++) {
        BGlyph g;
        read_glyph(f->glyphs + (size_t)i * GLYPH_SIZE, &g);
        if (g.id < 256 && f->lookup[g.id] < 0) f->lookup[g.id] = (int16_t)i;
        if (g.height > f->height) f->height = g.height;
    }
    return true;
}

bool bfont_glyph(const BFont* f, int ch, BGlyph* out)
{
    if (ch < 0 || ch > 255) return false;
    int16_t idx = f->lookup[ch];
    if (idx < 0) return false;
    read_glyph(f->glyphs + (size_t)idx * GLYPH_SIZE, out);
    return true;
}

float bfont_kerning(const BFont* f, int prev, int ch)
{
    if (!f->kerning) return 0.0f;

    BGlyph g;
    if (!bfont_glyph(f, prev, &g)) return 0.0f;
    if (g.kernPairs == 0) return 0.0f;
    if ((size_t)g.kernFirst + g.kernPairs > f->numKerning) return 0.0f;

    // mKerningTable holds a pair *index*, not a byte offset: the runs are
    // laid out in glyph order and each glyph's mKerningTable is the running
    // total of the pairs before it. Verified on all 11 fonts on disc.
    // (FONT_EVENTNUMBERS and FONT_POSITION declare pairs in the header that
    // no glyph claims -- reserved space, which per-glyph counts step over.)
    //
    // tTTKerningPair is { u32 mGlyph; f32 mXOffset; } and mGlyph is the
    // *following* character, so a run hangs off the glyph that precedes it.
    const uint8_t* k = f->kerning + (size_t)g.kernFirst * KERN_SIZE;
    for (uint32_t i = 0; i < g.kernPairs; i++) {
        if ((int)bchunk_u32(k + (size_t)i * KERN_SIZE) == ch)
            return bchunk_f32(k + (size_t)i * KERN_SIZE + 4);
    }
    return 0.0f;
}

float bfont_measure(const BFont* f, const char* s, size_t len)
{
    float total = 0.0f;
    int   prev  = -1;
    for (size_t i = 0; i < len && s[i]; i++) {
        int ch = (unsigned char)s[i];
        BGlyph g;
        if (!bfont_glyph(f, ch, &g)) { prev = -1; continue; }
        if (prev >= 0) total += bfont_kerning(f, prev, ch);
        total += g.advance;
        prev = ch;
    }
    return total;
}
