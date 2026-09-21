// Host harness for the 3DS sound-bank reader.
//
// Builds "3DS Files/source/sndbank.c" for the host and prints one line per
// patch:
//
//   patch <i> <hash> <name> <ch> <rate> <vol> <fxvol> <loop> <samples>
//         <dataOff> <dataSize> <coefCrc> <pcmCrc>
//
// plus a `bank` line for the header and a `find` line per patch, which
// exercises the hash lookup rather than only the sequential walk.
//
// tools/sndbank_check.py prints the same table from its own reader, written
// from docs/formats/sound-bank.md rather than from this file, and diffs the
// two over all 30 banks. It also mutates the bank behind the reader to check
// that a corrupt .SBK is rejected instead of decoded.
//
// Build (sndbank_check.py does this for you):
//   cc -O2 -I"3DS Files/source" -o sndbank_test tools/src/sndbank_test.c
//      "3DS Files/source/sndbank.c"
//
// Usage: sndbank_test <file.SBK> [--quiet]

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "sndbank.h"

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
        fprintf(stderr, "usage: sndbank_test <file.SBK> [--quiet]\n");
        return 2;
    }
    int quiet = (argc > 2 && !strcmp(argv[2], "--quiet"));

    FILE* f = fopen(argv[1], "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", argv[1]); return 2; }
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t* buf = malloc((size_t)size);
    if (!buf || fread(buf, 1, (size_t)size, f) != (size_t)size) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    fclose(f);

    SndBank b;
    if (!sndbank_open(&b, buf, (size_t)size)) {
        printf("reject\n");
        free(buf);
        return quiet ? 0 : 1;
    }
    printf("bank %s %08x %u %u\n", b.name, b.hash, b.count, b.dataSize);

    for (uint32_t i = 0; i < b.count; i++) {
        SndPatch p;
        if (!sndbank_get(&b, i, &p)) { printf("patch %u reject\n", i); continue; }

        uint8_t coefBytes[64];
        for (int c = 0; c < 2; c++)
            for (int k = 0; k < 16; k++) {
                coefBytes[c * 32 + k * 2]     = (uint8_t)(p.coefs[c][k] & 0xff);
                coefBytes[c * 32 + k * 2 + 1] = (uint8_t)((p.coefs[c][k] >> 8) & 0xff);
            }

        printf("patch %u %08x %s %u %u %u %u %u %u %u %u %08x %08x\n",
               i, p.hash, p.name, p.channels, p.rate, p.volume, p.effectVolume,
               p.looping ? 1u : 0u, p.samples, p.dataOff, p.dataSize,
               crc32_buf(coefBytes, 64), crc32_buf(p.pcm, p.dataSize));

        // The same patch by hash, and each channel's span, so a lookup or a
        // channel-split bug cannot hide behind a correct sequential walk.
        SndPatch q;
        int ok = sndbank_find(&b, p.hash, &q) && q.dataOff == p.dataOff;
        uint32_t n0 = 0, n1 = 0;
        const uint8_t* c0 = sndbank_channel(&p, 0, &n0);
        const uint8_t* c1 = sndbank_channel(&p, 1, &n1);
        printf("find %u %d %u %08x %u %08x\n", i, ok,
               n0, c0 ? crc32_buf(c0, n0) : 0u,
               c1 ? n1 : 0u, c1 ? crc32_buf(c1, n1) : 0u);
    }

    free(buf);
    return 0;
}
