#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// bWare fonts -- chunk 0x00015010, the one the game actually ships.
// (LoaderFontInfo also accepts 0x00030200 and then ignores it; no chunk of
// that type exists on this disc. Layout: docs/formats/bchunk.md.)
//
// A font is a glyph table plus a kerning table, both addressed by byte
// offsets from the chunk header, and its glyph sheet is a texture of the same
// name in a texture pack -- mPosX/mPosY/mWidth/mHeight are pixel coordinates
// into that sheet. Eleven chunks ship, across the three UI bundles.
//
// Checked against tools/font_dump.py by tools/bfont_check.py.
//
// Host-buildable: no <3ds.h> here.

#define BFONT_CHUNK 0x00015010u

typedef struct {
    uint16_t id;          // the character code
    uint16_t kernPairs;
    float    posX, posY;  // top-left in the glyph sheet, pixels
    float    width, height;
    float    advance;     // pen movement, what GetScaledWidth sums
    float    offset;      // vertical offset from the pen line
    uint32_t kernFirst;   // index of this glyph's first kerning pair
} BGlyph;

typedef struct {
    uint32_t       hash;        // bStringHash of the font name -- FindFont's key
    uint32_t       numGlyphs;
    uint32_t       numKerning;
    const uint8_t* chunk;       // the chunk header, which offsets are relative to
    const uint8_t* glyphs;      // numGlyphs 32-byte tTTGlyph records
    const uint8_t* kerning;     // numKerning 8-byte tTTKerningPair records
    size_t         chunkSize;   // header + payload, for bounds checks
    int16_t        lookup[256]; // character -> glyph index, -1 when absent
    float          height;      // tallest glyph, used as the line height
} BFont;

// Parses the font chunk whose *payload* is `payload` and whose Size is `size`.
// The two words before the payload are mChunkID/mChunkSize and the offsets
// inside are relative to them, so the caller must pass the payload pointer of
// a real chunk, not a copy of the payload alone.
bool bfont_parse(BFont* f, const uint8_t* payload, uint32_t size);

// Fills `out` with the glyph for character `ch`, or returns false when the
// font has no such glyph. This is Font::CharacterLookupTable[] -- built here
// from the glyph IDs, exactly as Font::Font() does at load.
bool bfont_glyph(const BFont* f, int ch, BGlyph* out);

// Kerning adjustment to apply before drawing `ch` when it follows `prev`,
// in font pixels. 0 when the pair is not listed. Font::GetKerning: the
// pairs are `ch`'s and match the low byte of `prev`.
float bfont_kerning(const BFont* f, int prev, int ch);

// Width of a NUL-terminated string in font pixels, before the object's
// ScaleX is applied: the advances of the characters with a glyph, no
// kerning. This is Font::GetScaledWidth()'s sum.
float bfont_measure(const BFont* f, const char* s, size_t len);
