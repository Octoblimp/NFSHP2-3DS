// Host harness for the 3DS texture-pack decoder.
//
// Builds "3DS Files/source/texpack.c" and "bchunk.c" for the host and prints
// one line per texture:
//
//     <index> <hash> <name> <width> <height> <bpp> <levels> <scroll> <crc32>
//
// plus one `scroll ...` line per UV-scrolling texture -- see scrollline.h.
// With --chain the line is the PICA200 mip chain texpack_upload_chain()
// builds from level N instead: the padded size, the number of levels, and
// one CRC over every level in order, read back out of the GPU's tiles.
// With --packed too, the chain is built in the format texpack_format()
// picks and read back as the PICA200 reads that format, and the CRC is
// "<format>:<crc>".
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
// Usage: texpack_test <file.BIN> [pack-index] [--level N] [--chain [--packed]]

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "texpack.h"
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

static const char* const FORMAT_NAME[] = { "RGBA8", "RGB8", "LA8", "L8" };

static size_t s_bytesRgba8, s_bytesPacked;

// The chain from level `base` as texpack_chain_tiled() lays it out, read
// back into RGBA8888 rows, every level one after another in one buffer.
// `packed`: as texpack_chain_tiled_as() lays it out in texpack_format()'s
// format, read back as the PICA200 reads that format.
static void print_chain(const TexPack* tp, const TexInfo* ti, uint32_t i,
                        int base, int packed)
{
    uint32_t      pw = 0, ph = 0;
    int           n = texpack_chain(ti, base, &pw, &ph);
    TexPackFormat f = packed ? texpack_format(tp, ti, base)
                             : TEXPACK_FMT_RGBA8;
    uint32_t      tb = texpack_format_bytes(f);
    size_t        total = 0;
    for (int l = 0; l < n; l++)
        total += (size_t)(pw >> l) * (ph >> l) * 4;
    size_t    cap = texpack_decode_size(ti, base);
    uint8_t*  all = n ? (uint8_t*)malloc(total) : NULL;
    uint8_t*  tiled = n ? (uint8_t*)malloc(total) : NULL;
    uint8_t*  scratch = cap ? (uint8_t*)malloc(cap) : NULL;
    uint8_t*  level[TEXPACK_CHAIN_MAX];
    uint32_t* words[TEXPACK_CHAIN_MAX];
    int       ok = all && tiled && scratch;
    size_t    at = 0;
    for (int l = 0; l < n; l++) {
        level[l] = tiled + at;
        words[l] = (uint32_t*)(tiled + at);
        at += (size_t)(pw >> l) * (ph >> l) * tb;
    }
    if (packed)
        ok = ok && texpack_chain_tiled_as(tp, ti, base, f, level, scratch,
                                          cap);
    else
        ok = ok && texpack_chain_tiled(tp, ti, base, words, scratch, cap);
    if (ok) {
        s_bytesRgba8  += total;
        s_bytesPacked += at;
    }
    for (int l = 0, k = 0; ok && l < n; l++) {
        uint32_t cw = pw >> l, ch = ph >> l;
        for (uint32_t y = 0; y < ch; y++) {
            for (uint32_t x = 0; x < cw; x++, k += 4) {
                uint32_t t = texpack_texel_get(level[l],
                                               texpack_tiled_index(x, y, cw),
                                               f);
                all[k + 0] = (uint8_t)(t >> 24);
                all[k + 1] = (uint8_t)(t >> 16);
                all[k + 2] = (uint8_t)(t >> 8);
                all[k + 3] = (uint8_t)t;
            }
        }
    }
    free(tiled);
    free(scratch);
    if (!ok)
        printf("%u %08x %s - - %u %d %d skip\n", i, ti->hash, ti->name,
               ti->bpp, n, (int)ti->scrollType);
    else if (packed)
        printf("%u %08x %s %u %u %u %d %d %s:%08x\n", i, ti->hash,
               ti->name, pw, ph, ti->bpp, n, (int)ti->scrollType,
               FORMAT_NAME[f], crc32_buf(all, total));
    else
        printf("%u %08x %s %u %u %u %d %d %08x\n", i, ti->hash, ti->name,
               pw, ph, ti->bpp, n, (int)ti->scrollType,
               crc32_buf(all, total));
    free(all);
}

int main(int argc, char** argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <file.BIN> [pack-index] [--level N]"
                " [--chain [--packed]]\n", argv[0]);
        return 2;
    }
    uint32_t packIndex = 0;
    int      level     = 0;
    int      chain     = 0;
    int      packed    = 0;
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--level") && i + 1 < argc)
            level = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--chain"))
            chain = 1;
        else if (!strcmp(argv[i], "--packed"))
            packed = 1;
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
        print_scroll_line(i, &ti);
        if (chain) {
            print_chain(&tp, &ti, i, level, packed);
            continue;
        }

        size_t need = texpack_decode_size(&ti, level);
        if (need == 0) {
            printf("%u %08x %s - - %u %u %d skip\n",
                   i, ti.hash, ti.name, ti.bpp, ti.levels,
                   (int)ti.scrollType);
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
            printf("%u %08x %s %u %u %u %u %d skip\n",
                   i, ti.hash, ti.name, w, h, ti.bpp, ti.levels,
                   (int)ti.scrollType);
            continue;
        }
        printf("%u %08x %s %u %u %u %u %d %08x\n", i, ti.hash, ti.name, w,
               h, ti.bpp, ti.levels, (int)ti.scrollType,
               crc32_buf(rgba, need));
    }
    if (chain)
        fprintf(stderr, "chains: %zu KB as RGBA8, %zu KB as stored\n",
                s_bytesRgba8 >> 10, s_bytesPacked >> 10);
    free(rgba);
    free(buf);
    return 0;
}
