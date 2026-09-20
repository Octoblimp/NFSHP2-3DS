// Host harness for the 3DS font reader.
//
// Builds "3DS Files/source/bfont.c" for the host and prints, for every
// 0x00015010 chunk in a bundle, a header line and then one line per glyph:
//
//     font <hash> <numGlyphs> <numKerning> <height>
//     g <id> <pairs> <x> <y> <w> <h> <advance> <offset> <sumKerning>
//
// sumKerning is this glyph's mXOffset summed over every character it kerns
// against, which exercises the kerning walk without printing 10,932 lines.
// tools/bfont_check.py prints the same from tools/font_dump.py and diffs it.
//
// Usage: bfont_test <file.BUN>

#include <stdio.h>
#include <stdlib.h>

#include "bchunk.h"
#include "bfont.h"

static int on_chunk(uint32_t type, const uint8_t* payload, uint32_t size,
                    int depth, void* user)
{
    (void)depth; (void)user;
    if (BCHUNK_IS_CONTAINER(type)) return BCHUNK_ENTER;
    if (type != BFONT_CHUNK) return BCHUNK_SKIP;

    BFont f;
    if (!bfont_parse(&f, payload, size)) {
        printf("font PARSE-FAILED\n");
        return BCHUNK_SKIP;
    }
    printf("font %08x %u %u %g\n", f.hash, f.numGlyphs, f.numKerning,
           (double)f.height);

    for (uint32_t i = 0; i < f.numGlyphs; i++) {
        BGlyph g;
        // Go through the character lookup, not the raw array, so the lookup
        // table itself is part of what gets compared.
        uint16_t id = bchunk_u16(f.glyphs + (size_t)i * 32);
        if (!bfont_glyph(&f, (int)id, &g)) { printf("g %u MISSING\n", id); continue; }

        float sum = 0.0f;
        for (int ch = 0; ch < 256; ch++) sum += bfont_kerning(&f, (int)id, ch);

        printf("g %u %u %g %g %g %g %g %g %g\n", g.id, g.kernPairs,
               (double)g.posX, (double)g.posY, (double)g.width,
               (double)g.height, (double)g.advance, (double)g.offset,
               (double)sum);
    }
    return BCHUNK_SKIP;
}

int main(int argc, char** argv)
{
    if (argc < 2) { fprintf(stderr, "usage: %s <file.BUN>\n", argv[0]); return 2; }
    FILE* fh = fopen(argv[1], "rb");
    if (!fh) { perror(argv[1]); return 1; }
    fseek(fh, 0, SEEK_END);
    long len = ftell(fh);
    fseek(fh, 0, SEEK_SET);
    uint8_t* buf = (uint8_t*)malloc((size_t)len);
    if (!buf || fread(buf, 1, (size_t)len, fh) != (size_t)len) {
        fprintf(stderr, "read failed\n"); return 1;
    }
    fclose(fh);

    bchunk_walk(buf, 0, (size_t)len, (BChunkVisitor)on_chunk, NULL);
    free(buf);
    return 0;
}
