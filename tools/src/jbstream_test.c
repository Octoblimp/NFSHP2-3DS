// Decodes a jukebox tune through jbstream.c's decoder, pair by pair as the
// stream reads them, `step` frames a call, for tools/jbstream_check.py.
//
//   jbstream_test file out.pcm offset size step
//
// The PCM is the decoder's interleaved stereo; the last line says where it
// stopped.
#include <stdio.h>
#include <stdlib.h>

#include "jbstream.h"

int main(int argc, char** argv)
{
    if (argc < 6) {
        fprintf(stderr, "usage: jbstream_test file out.pcm offset size step\n");
        return 2;
    }
    FILE* f = fopen(argv[1], "rb");
    FILE* o = fopen(argv[2], "wb");
    if (!f || !o) {
        fprintf(stderr, "cannot open\n");
        return 2;
    }
    uint32_t offset = (uint32_t)strtoul(argv[3], NULL, 0);
    uint32_t left = (uint32_t)strtoul(argv[4], NULL, 0);
    uint32_t step = (uint32_t)strtoul(argv[5], NULL, 0);
    fseek(f, (long)offset, SEEK_SET);

    uint8_t* pair = malloc(JBS_PAIR);
    int16_t* out = malloc((size_t)step * JBS_SAMPLES * 4);
    JBSDecoder d;
    jbs_decoder_reset(&d);
    bool have = false;
    uint32_t pairs = 0, calls = 0;
    unsigned long samples = 0;
    while (!d.ended) {
        if (!have || d.frame >= JBS_FRAMES) {
            if (left < JBS_PAIR || fread(pair, 1, JBS_PAIR, f) != JBS_PAIR) {
                break;
            }
            left -= JBS_PAIR;
            have = true;
            d.frame = 0;
            pairs++;
        }
        uint32_t n = jbs_decode(&d, pair, out, step);
        calls++;
        fwrite(out, 4, n, o);
        samples += n;
    }
    printf("pairs=%u calls=%u samples=%lu ended=%d frame=%u\n", pairs, calls,
           samples, d.ended ? 1 : 0, d.frame);
    fclose(o);
    fclose(f);
    return 0;
}
