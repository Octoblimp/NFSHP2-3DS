// Host harness for the 3DS `.M3V` movie player.
//
// Builds "3DS Files/source/movie.c" for the host and prints one line per
// decoded frame:
//
//     frame <index> <crc32 of the whole surface>
//
// plus a header line and, at the end, the path-rewriting cases. The surface
// is the RGB565 tile-order buffer the 3DS decodes straight into VRAM, so a
// CRC over it catches any disagreement about the RLE, the changed-tile
// bitmap, the tile order or the pixel format -- not just about the picture.
//
// tools/movie_check.py prints the same table from an independent Python
// decoder and diffs the two.
//
// Build (movie_check.py does this for you):
//   cc -O2 -I"3DS Files/source" -o movie_test tools/src/movie_test.c
//      "3DS Files/source/movie.c"
//
// Usage: movie_test <file.M3V>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "movie.h"

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
    {
        uint32_t c = 0xffffffffu;
        size_t i;
        for (i = 0; i < n; i++)
            c = table[(c ^ p[i]) & 0xff] ^ (c >> 8);
        return c ^ 0xffffffffu;
    }
}

// The surface is u16 in host order; serialise little-endian so the CRC means
// the same thing on any host and matches what Python computes.
static uint32_t crc_surface(const uint16_t* s, size_t count, uint8_t* scratch)
{
    size_t i;
    for (i = 0; i < count; i++) {
        scratch[i * 2]     = (uint8_t)(s[i] & 0xff);
        scratch[i * 2 + 1] = (uint8_t)(s[i] >> 8);
    }
    return crc32_buf(scratch, count * 2);
}

static void path_cases(void)
{
    static const char* const kCases[] = {
        "MOVIES\\INTRO\\EALOGO_EN.AVI",
        "MOVIES\\INTRO\\NFSINTRO_EN.AVI",
        "MOVIES\\ATTRACT\\ATTRACT1.avi",
        "NOEXTENSION",
        "MOVIES\\DIR.WITH.DOTS\\CLIP.AVI",
    };
    size_t i;
    for (i = 0; i < sizeof(kCases) / sizeof(kCases[0]); i++) {
        char out[128];
        if (m3v_baked_path(kCases[i], out, sizeof(out)))
            printf("path %s -> %s\n", kCases[i], out);
        else
            printf("path %s -> FAIL\n", kCases[i]);
    }
    {
        // A buffer that cannot hold the rewrite must fail rather than truncate.
        char tiny[8];
        printf("path tiny -> %s\n",
               m3v_baked_path("MOVIES\\INTRO\\EALOGO_EN.AVI", tiny,
                              sizeof(tiny)) ? tiny : "FAIL");
    }
}

int main(int argc, char** argv)
{
    M3VMovie m;
    size_t   pixels;
    uint8_t* scratch;
    uint32_t n = 0;

    if (argc < 2) {
        fprintf(stderr, "usage: %s <file.M3V>\n", argv[0]);
        return 2;
    }

    if (!m3v_open(&m, argv[1], NULL)) {
        fprintf(stderr, "cannot open %s\n", argv[1]);
        return 1;
    }

    printf("movie %ux%u frames %u fps %u tiles %u maxframe %u\n",
           m.info.width, m.info.height, m.info.frames, m.info.fps,
           m.numTiles, m.info.maxFrameLen);
    printf("audio %u bytes %u Hz %u ch %u bit\n",
           m.info.audioLen, m.info.audioRate, m.info.audioChannels,
           m.info.audioBits);
    printf("duration %.4f\n", (double)m3v_duration(&m));

    pixels  = (size_t)m.info.width * m.info.height;
    scratch = (uint8_t*)malloc(pixels * 2);
    if (!scratch) { m3v_close(&m); return 1; }

    while (m3v_next(&m)) {
        printf("frame %u %08x\n", n, crc_surface(m.surface, pixels, scratch));
        n++;
    }
    printf("frames decoded %u\n", n);

    // m3v_drive at a 3DS-ish 60 fps: the movie must land on exactly the same
    // frame count and finish when its running time has elapsed, not before.
    m3v_close(&m);
    if (m3v_open(&m, argv[1], NULL)) {
        int    steps = 0;
        bool   done  = false;
        while (!done && steps < 100000) {
            done = m3v_drive(&m, 1.0f / 60.0f);
            steps++;
        }
        printf("drive steps %d frames %u done %d\n",
               steps, m.nextFrame, (int)done);
        printf("drive crc %08x\n", crc_surface(m.surface, pixels, scratch));
        m3v_close(&m);
    }

    path_cases();
    free(scratch);
    return 0;
}
