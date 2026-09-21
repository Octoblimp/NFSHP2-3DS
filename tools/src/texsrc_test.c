// Host harness for the streaming texture-pack reader.
//
// Prints exactly the table tools/src/texpack_test.c prints:
//
//     <index> <hash> <name> <width> <height> <bpp> <levels> <scroll> <crc32>
//
// plus one `scroll ...` line per UV-scrolling texture -- see scrollline.h.
//
// -- but produced by reading the pack off disk a texture at a time through
// texsrc.c instead of holding the whole file in memory. tools/texsrc_check.py
// runs both harnesses over the same pack and diffs the two transcripts, so
// the streaming path is checked against the one texpack_check.py has already
// checked against tools/texture_convert.py.
//
// What that actually tests is the arithmetic streaming adds and nothing else:
// where the 0x30300004 payload starts in the file, the 128-byte round-up
// applied to it, and which two ranges one texture needs. Every one of those
// rolls a texture sideways or fills it with a neighbour's bytes when it is
// wrong, and none of them is visible in a decode that has the whole file
// mapped.
//
// Build (see tools/texsrc_check.py, which does this for you):
//   cc -O2 -I"3DS Files/source" -o texsrc_test tools/src/texsrc_test.c
//      "3DS Files/source/texsrc.c" "3DS Files/source/texpack.c"
//      "3DS Files/source/bchunk.c"
//
// Usage: texsrc_test <file.BIN> [pack-index] [--level N]

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "texsrc.h"
#include "scrollline.h"

static uint32_t crc32_buf(const uint8_t* p, size_t n)
{
    static uint32_t table[256];
    static int built = 0;
    if (!built) {
        for (uint32_t i = 0; i < 256; i++) {
            uint32_t c = i;
            for (int k = 0; k < 8; k++)
                c = (c & 1) ? 0xedb88320u ^ (c >> 1) : c >> 1;
            table[i] = c;
        }
        built = 1;
    }
    uint32_t c = 0xffffffffu;
    for (size_t i = 0; i < n; i++)
        c = table[(c ^ p[i]) & 0xff] ^ (c >> 8);
    return c ^ 0xffffffffu;
}

int main(int argc, char** argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <file.BIN> [pack-index] [--level N]\n",
                argv[0]);
        return 2;
    }
    int packIndex = 0;
    int level     = 0;
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--level") && i + 1 < argc)
            level = atoi(argv[++i]);
        else
            packIndex = atoi(argv[i]);
    }

    TexSource ts;
    if (!texsrc_open(&ts, argv[1])) {
        fprintf(stderr, "no texture pack in %s\n", argv[1]);
        return 1;
    }
    if (packIndex < 0 || packIndex >= ts.numPacks) {
        fprintf(stderr, "no texture pack %d in %s\n", packIndex, argv[1]);
        return 1;
    }

    // texsrc_at() indexes across every pack in the file; texpack_test's index
    // is within one pack, so walk from this pack's base to print the same
    // numbers on both sides.
    uint32_t base = 0;
    for (int i = 0; i < packIndex; i++) base += ts.pack[i].count;
    uint32_t count = ts.pack[packIndex].count;

    fprintf(stderr, "pack '%s': %u textures, %u bytes of data\n",
            ts.pack[packIndex].name, count, ts.pack[packIndex].dataSize);

    size_t   cap  = 0;
    uint8_t* rgba = NULL;
    for (uint32_t i = 0; i < count; i++) {
        TexSrcEntry e;
        if (!texsrc_at(&ts, base + i, &e)) continue;
        const TexInfo* ti = &e.info;
        print_scroll_line(i, ti);

        size_t need = texpack_decode_size(ti, level);
        if (need == 0) {
            printf("%u %08x %s - - %u %u %d skip\n",
                   i, ti->hash, ti->name, ti->bpp, ti->levels,
                   (int)ti->scrollType);
            continue;
        }
        if (need > cap) {
            rgba = (uint8_t*)realloc(rgba, need);
            if (!rgba) { fprintf(stderr, "oom\n"); return 1; }
            cap = need;
        }
        uint32_t w = 0, h = 0;
        texpack_level(ti, level, &w, &h, NULL, NULL);

        uint8_t* stage = NULL;
        TexPack  tp;
        TexInfo  local;
        if (!texsrc_stage(&ts, &e, level, &stage, &tp, &local)
            || !texpack_decode(&tp, &local, level, rgba, cap)) {
            free(stage);
            printf("%u %08x %s %u %u %u %u %d skip\n",
                   i, ti->hash, ti->name, w, h, ti->bpp, ti->levels,
                   (int)ti->scrollType);
            continue;
        }
        free(stage);
        printf("%u %08x %s %u %u %u %u %d %08x\n", i, ti->hash, ti->name, w,
               h, ti->bpp, ti->levels, (int)ti->scrollType,
               crc32_buf(rgba, need));
    }
    free(rgba);
    texsrc_close(&ts);
    return 0;
}
