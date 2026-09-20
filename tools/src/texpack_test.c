// Host harness for the 3DS texture-pack decoder.
//
// Builds "3DS Files/source/texpack.c" and "bchunk.c" for the host and prints
// one line per texture:
//
//     <index> <hash> <name> <width> <height> <bpp> <levels> <crc32>
//
// tools/texpack_check.py prints the same table from tools/texture_convert.py
// and diffs the two, so the C decoder that will run on the 3DS is checked
// against the Python one pixel for pixel rather than by eye. Any difference
// in the swizzle, the CLUT or the alpha convention shows up as a CRC mismatch.
//
// Build (see tools/texpack_check.py, which does this for you):
//   cc -O2 -I"3DS Files/source" -o texpack_test tools/src/texpack_test.c
//      "3DS Files/source/texpack.c" "3DS Files/source/bchunk.c"
//
// Usage: texpack_test <file.BIN> [pack-index] [--level N]

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "texpack.h"

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
    uint32_t packIndex = 0;
    int      level     = 0;
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--level") && i + 1 < argc)
            level = atoi(argv[++i]);
        else
            packIndex = (uint32_t)strtoul(argv[i], NULL, 10);
    }

    FILE* f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 1; }
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t* buf = (uint8_t*)malloc((size_t)len);
    if (!buf || fread(buf, 1, (size_t)len, f) != (size_t)len) {
        fprintf(stderr, "read failed\n");
        return 1;
    }
    fclose(f);

    TexPack tp;
    if (!texpack_open_nth(&tp, buf, 0, (size_t)len, packIndex)) {
        fprintf(stderr, "no texture pack %u in %s\n", packIndex, argv[1]);
        return 1;
    }
    fprintf(stderr, "pack '%s': %u textures, %u bytes of data\n",
            tp.name, tp.count, tp.dataSize);

    size_t   cap = 0;
    uint8_t* rgba = NULL;
    for (uint32_t i = 0; i < tp.count; i++) {
        TexInfo ti;
        if (!texpack_get(&tp, i, &ti)) continue;

        size_t need = texpack_decode_size(&ti, level);
        if (need == 0) {
            printf("%u %08x %s - - %u %u skip\n",
                   i, ti.hash, ti.name, ti.bpp, ti.levels);
            continue;
        }
        if (need > cap) {
            rgba = (uint8_t*)realloc(rgba, need);
            if (!rgba) { fprintf(stderr, "oom\n"); return 1; }
            cap = need;
        }
        uint32_t w = 0, h = 0;
        texpack_level(&ti, level, &w, &h, NULL, NULL);
        if (!texpack_decode(&tp, &ti, level, rgba, cap)) {
            printf("%u %08x %s %u %u %u %u skip\n",
                   i, ti.hash, ti.name, w, h, ti.bpp, ti.levels);
            continue;
        }
        printf("%u %08x %s %u %u %u %u %08x\n", i, ti.hash, ti.name, w, h,
               ti.bpp, ti.levels, crc32_buf(rgba, need));
    }
    free(rgba);
    free(buf);
    return 0;
}
