/* dspenc.c - host-side Nintendo DSPADPCM (GC-ADPCM) encoder for NFSU2-3DS.
 *
 * Reads a PCM16 RIFF/WAVE file and writes a ".dspm" streaming container that the
 * 3DS port feeds straight to NDSP hardware channels (NDSP_FORMAT_ADPCM), so no
 * sample mixing or decoding ever runs on the ARM11.
 *
 * DSPADPCM is 4 bits/sample: 14 samples per 8-byte frame (1 header byte holding
 * scale in the low nibble and predictor index in the high nibble, then 7 data
 * bytes).  That is a 4x saving over PCM16 for both SD storage and read bandwidth.
 *
 * The coefficient search is the standard Nintendo DSPCorrelateCoefs algorithm:
 * autocorrelation per 14-sample frame, then a 2-pass k-means style clustering
 * down to the 8 coefficient pairs the DSP holds per channel.
 *
 * Container layout (little-endian, matches source/audio.c DspmHeader):
 *   0x00 u32 magic 'DSPM'          0x10 u32 totalSamples (per channel)
 *   0x04 u32 version = 1           0x14 u32 framesPerBlock
 *   0x08 u32 sampleRate            0x18 u32 blockCount
 *   0x0C u32 channels (1 or 2)     0x1C u32 dataOffset
 *   0x20 u32 loopStart  (samples, 0 = none)
 *   0x24 u32 loopEnd    (samples, 0 = none)
 *   0x28 s16 coefs[channels][16]
 *   ...  block index: blockCount * channels * { u16 index; s16 hist0; s16 hist1; }
 *   dataOffset: blockCount blocks, each = channels * framesPerBlock * 8 bytes,
 *               channel-major within the block (all of ch0, then all of ch1).
 *
 * The per-block history lets every NDSP waveBuf be submitted with an exact
 * ndspAdpcmData, which makes buffer boundaries seamless and seeking possible.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include <float.h>

#define FRAME_SAMPLES 14
#define FRAME_BYTES    8

typedef int16_t  s16;
typedef uint16_t u16;
typedef int32_t  s32;
typedef uint32_t u32;
typedef uint8_t  u8;

static double dmax(double a, double b) { return a > b ? a : b; }

/* ---------------------------------------------------------------- coef search */

static void InnerProductMerge(double vecOut[3], const s16 pcmBuf[14])
{
    for (int i = 0; i <= 2; i++) {
        vecOut[i] = 0.0;
        for (int x = 0; x < 14; x++)
            vecOut[i] -= (double)pcmBuf[x - i] * (double)pcmBuf[x];
    }
}

static void OuterProductMerge(double mtxOut[3][3], const s16 pcmBuf[14])
{
    for (int x = 1; x <= 2; x++)
        for (int y = 1; y <= 2; y++) {
            mtxOut[x][y] = 0.0;
            for (int z = 0; z < 14; z++)
                mtxOut[x][y] += (double)pcmBuf[z - x] * (double)pcmBuf[z - y];
        }
}

static int AnalyzeRanges(double mtx[3][3], int vecIdxsOut[3])
{
    double recips[3];
    double val, tmp, min, max;

    for (int x = 1; x <= 2; x++) {
        val = dmax(fabs(mtx[x][1]), fabs(mtx[x][2]));
        if (val < DBL_EPSILON)
            return 1;
        recips[x] = 1.0 / val;
    }

    int maxIndex = 0;
    for (int i = 1; i <= 2; i++) {
        for (int x = 1; x < i; x++) {
            tmp = mtx[x][i];
            for (int y = 1; y < x; y++)
                tmp -= mtx[x][y] * mtx[y][i];
            mtx[x][i] = tmp;
        }

        val = 0.0;
        for (int x = i; x <= 2; x++) {
            tmp = mtx[x][i];
            for (int y = 1; y < i; y++)
                tmp -= mtx[x][y] * mtx[y][i];
            mtx[x][i] = tmp;
            tmp = fabs(tmp) * recips[x];
            if (tmp >= val) { val = tmp; maxIndex = x; }
        }

        if (maxIndex != i) {
            for (int y = 1; y <= 2; y++) {
                tmp = mtx[maxIndex][y];
                mtx[maxIndex][y] = mtx[i][y];
                mtx[i][y] = tmp;
            }
            recips[maxIndex] = recips[i];
        }

        vecIdxsOut[i] = maxIndex;
        if (mtx[i][i] == 0.0)
            return 1;

        if (i != 2) {
            tmp = 1.0 / mtx[i][i];
            for (int x = i + 1; x <= 2; x++)
                mtx[x][i] *= tmp;
        }
    }

    min = 1.0e10;
    max = 0.0;
    for (int i = 1; i <= 2; i++) {
        tmp = fabs(mtx[i][i]);
        if (tmp < min) min = tmp;
        if (tmp > max) max = tmp;
    }
    return (min / max < 1.0e-10) ? 1 : 0;
}

static void BidirectionalFilter(double mtx[3][3], const int vecIdxs[3], double vecOut[3])
{
    double tmp;

    for (int i = 1, x = 0; i <= 2; i++) {
        int index = vecIdxs[i];
        tmp = vecOut[index];
        vecOut[index] = vecOut[i];
        if (x != 0)
            for (int y = x; y <= i - 1; y++)
                tmp -= vecOut[y] * mtx[i][y];
        else if (tmp != 0.0)
            x = i;
        vecOut[i] = tmp;
    }

    for (int i = 2; i > 0; i--) {
        tmp = vecOut[i];
        for (int y = i + 1; y <= 2; y++)
            tmp -= vecOut[y] * mtx[i][y];
        vecOut[i] = tmp / mtx[i][i];
    }

    vecOut[0] = 1.0;
}

static int QuadraticMerge(double inOutVec[3])
{
    double v0, v1, v2 = inOutVec[2];
    double tmp = 1.0 - (v2 * v2);

    if (tmp == 0.0)
        return 1;

    v0 = (inOutVec[0] - (v2 * v2)) / tmp;
    v1 = (inOutVec[1] - (inOutVec[1] * v2)) / tmp;

    inOutVec[0] = v0;
    inOutVec[1] = v1;
    return fabs(v1) > 1.0;
}

static void FinishRecord(double in[3], double out[3])
{
    for (int z = 1; z <= 2; z++) {
        if (in[z] >= 1.0)        in[z] =  0.9999999999;
        else if (in[z] <= -1.0)  in[z] = -0.9999999999;
    }
    out[0] = 1.0;
    out[1] = (in[2] * in[1]) + in[1];
    out[2] = in[2];
}

static void MatrixFilter(const double src[3], double dst[3])
{
    double mtx[3][3];

    mtx[2][0] = 1.0;
    for (int i = 1; i <= 2; i++)
        mtx[2][i] = -src[i];

    for (int i = 2; i > 0; i--) {
        double val = 1.0 - (mtx[i][i] * mtx[i][i]);
        for (int y = 1; y <= i; y++)
            mtx[i - 1][y] = ((mtx[i][i] * mtx[i][y]) + mtx[i][y]) / val;
    }

    dst[0] = 1.0;
    for (int i = 1; i <= 2; i++) {
        dst[i] = 0.0;
        for (int y = 1; y <= i; y++)
            dst[i] += mtx[i][y] * dst[i - y];
    }
}

static void MergeFinishRecord(const double src[3], double dst[3])
{
    double tmp[3];
    double val = src[0];

    dst[0] = 1.0;
    for (int i = 1; i <= 2; i++) {
        double v2 = 0.0;
        for (int y = 1; y < i; y++)
            v2 += dst[y] * src[i - y];

        dst[i] = (val > 0.0) ? -(v2 + src[i]) / val : 0.0;
        tmp[i] = dst[i];

        for (int y = 1; y < i; y++)
            dst[y] += dst[i] * dst[i - y];

        val *= 1.0 - (dst[i] * dst[i]);
    }
    FinishRecord(tmp, dst);
}

static double ContrastVectors(const double source1[3], const double source2[3])
{
    double val  = (source2[2] * source2[1] + -source2[1]) / (1.0 - source2[2] * source2[2]);
    double val1 = (source1[0] * source1[0]) + (source1[1] * source1[1]) + (source1[2] * source1[2]);
    double val2 = (source1[0] * source1[1]) + (source1[1] * source1[2]);
    double val3 = source1[0] * source1[2];
    return val1 + (2.0 * val * val2) + (2.0 * (-source2[1] * val + -source2[2]) * val3);
}

static void FilterRecords(double vecBest[8][3], int exp, double (*records)[3], int recordCount)
{
    double bufferList[8][3];
    int    buffer1[8];
    double buffer2[3];

    for (int x = 0; x < 2; x++) {
        for (int y = 0; y < exp; y++) {
            buffer1[y] = 0;
            for (int i = 0; i <= 2; i++)
                bufferList[y][i] = 0.0;
        }
        for (int z = 0; z < recordCount; z++) {
            int index = 0;
            double value = 1.0e30;
            for (int i = 0; i < exp; i++) {
                double tempVal = ContrastVectors(vecBest[i], records[z]);
                if (tempVal < value) { value = tempVal; index = i; }
            }
            buffer1[index]++;
            MatrixFilter(records[z], buffer2);
            for (int i = 0; i <= 2; i++)
                bufferList[index][i] += buffer2[i];
        }

        for (int i = 0; i < exp; i++)
            if (buffer1[i] > 0)
                for (int y = 0; y <= 2; y++)
                    bufferList[i][y] /= buffer1[i];

        for (int i = 0; i < exp; i++)
            MergeFinishRecord(bufferList[i], vecBest[i]);
    }
}

static void DSPCorrelateCoefs(const s16* source, int samples, s16* coefsOut)
{
    int numFrames = (samples + FRAME_SAMPLES - 1) / FRAME_SAMPLES;
    int frameSamples;

    s16* blockBuffer = calloc(0x3800, sizeof(s16));
    /* pcmHistBuffer[n][0..1] are the two samples preceding the 14-sample window,
     * so the analysis routines index pcmHistBuffer[n]+2 with x-1 and x-2. */
    s16 pcmHistBuffer[2][16];
    memset(pcmHistBuffer, 0, sizeof(pcmHistBuffer));

    double vec1[3], vec2[3];
    double mtx[3][3];
    int    vecIdxs[3];

    double (*records)[3] = calloc((size_t)numFrames * 2 + 8, sizeof(double[3]));
    int recordCount = 0;
    double vecBest[8][3];

    const s16* srcPos = source;
    for (int x = samples; x > 0;) {
        if (x > 0x3800) { frameSamples = 0x3800; x -= 0x3800; }
        else            { frameSamples = x;      x = 0; }

        memset(blockBuffer, 0, 0x3800 * sizeof(s16));
        memcpy(blockBuffer, srcPos, (size_t)frameSamples * sizeof(s16));
        srcPos += frameSamples;

        for (int i = 0; i < frameSamples;) {
            int s = (frameSamples - i > FRAME_SAMPLES) ? FRAME_SAMPLES : frameSamples - i;

            /* shift the window: previous frame becomes the history slot */
            memcpy(pcmHistBuffer[0], pcmHistBuffer[1], sizeof(pcmHistBuffer[0]));
            pcmHistBuffer[1][0] = pcmHistBuffer[0][14];
            pcmHistBuffer[1][1] = pcmHistBuffer[0][15];
            for (int y = 0; y < FRAME_SAMPLES; y++)
                pcmHistBuffer[1][y + 2] = (y < s) ? blockBuffer[i + y] : 0;
            i += s;

            InnerProductMerge(vec1, pcmHistBuffer[1] + 2);
            if (fabs(vec1[0]) <= 10.0) continue;

            OuterProductMerge(mtx, pcmHistBuffer[1] + 2);
            if (!AnalyzeRanges(mtx, vecIdxs)) {
                BidirectionalFilter(mtx, vecIdxs, vec1);
                if (!QuadraticMerge(vec1)) {
                    FinishRecord(vec1, records[recordCount]);
                    recordCount++;
                }
            }
        }
    }

    vec1[0] = 1.0; vec1[1] = 0.0; vec1[2] = 0.0;

    for (int z = 0; z < recordCount; z++) {
        MatrixFilter(records[z], vecBest[0]);
        for (int y = 1; y <= 2; y++)
            vec1[y] += vecBest[0][y];
    }
    for (int y = 1; y <= 2; y++)
        vec1[y] /= recordCount ? recordCount : 1;

    MergeFinishRecord(vec1, vecBest[0]);

    int exp = 1;
    for (int w = 0; w < 3;) {
        vec2[0] = 0.0; vec2[1] = -1.0; vec2[2] = 0.0;
        for (int i = 0; i < exp; i++)
            for (int y = 0; y <= 2; y++)
                vecBest[exp + i][y] = (0.01 * vec2[y]) + vecBest[i][y];
        ++w;
        exp = 1 << w;
        FilterRecords(vecBest, exp, records, recordCount);
    }

    for (int z = 0; z < 8; z++) {
        double d;
        d = -vecBest[z][1] * 2048.0;
        coefsOut[z * 2]     = (s16)((d > 32767.0) ? 32767 : (d < -32768.0) ? -32768 : lround(d));
        d = -vecBest[z][2] * 2048.0;
        coefsOut[z * 2 + 1] = (s16)((d > 32767.0) ? 32767 : (d < -32768.0) ? -32768 : lround(d));
    }

    free(records);
    free(blockBuffer);
}

/* -------------------------------------------------------------- frame encoder */

static s16 clamp16(int v)
{
    if (v > 32767)  return 32767;
    if (v < -32768) return -32768;
    return (s16)v;
}

/* pcmInOut[0..1] = history (yn2, yn1), [2..] = sampleCount input samples.
 * On return [0..1] hold the new history taken from the *decoded* output, so the
 * encoder stays in lockstep with what the DSP will actually produce. */
static void DSPEncodeFrame(s16 pcmInOut[16], int sampleCount, u8 adpcmOut[8], const s16 coefsIn[8][2])
{
    int inSamples[8][16];
    int outSamples[8][14];
    int bestIndex = 0;
    int scale[8];
    double distAccum[8];

    for (int i = 0; i < 8; i++) {
        int v1, v2, v3;
        int distance, index = 0;

        inSamples[i][0] = pcmInOut[0];
        inSamples[i][1] = pcmInOut[1];

        distance = 0;
        for (int s = 0; s < sampleCount; s++) {
            v1 = ((pcmInOut[s] * coefsIn[i][1]) + (pcmInOut[s + 1] * coefsIn[i][0])) / 2048;
            v2 = pcmInOut[s + 2] - v1;
            v3 = clamp16(v2);
            if (abs(v3) > abs(distance))
                distance = v3;
        }

        for (scale[i] = 0; (scale[i] <= 12) && ((distance > 7) || (distance < -8)); scale[i]++, distance /= 2)
            ;
        scale[i] = (scale[i] <= 1) ? -1 : scale[i] - 2;

        do {
            scale[i]++;
            distAccum[i] = 0;
            index = 0;

            for (int s = 0; s < sampleCount; s++) {
                v1 = ((inSamples[i][s] * coefsIn[i][1]) + (inSamples[i][s + 1] * coefsIn[i][0]));
                v2 = ((pcmInOut[s + 2] << 11) - v1) / 2048;
                v3 = (v2 > 0) ? (int)((double)v2 / (1 << scale[i]) + 0.4999999)
                              : (int)((double)v2 / (1 << scale[i]) - 0.4999999);

                /* Clamp to a nibble; `index` accumulates how far the value had to
                 * be clamped, which is what drives the scale search below. */
                if (v3 < -8) {
                    if (index < (v3 = -8 - v3)) index = v3;
                    v3 = -8;
                } else if (v3 > 7) {
                    if (index < (v3 -= 7)) index = v3;
                    v3 = 7;
                }

                outSamples[i][s] = v3;

                v1 = (v1 + ((v3 * (1 << scale[i])) << 11) + 1024) >> 11;
                inSamples[i][s + 2] = v2 = clamp16(v1);

                v3 = pcmInOut[s + 2] - v2;
                distAccum[i] += (double)v3 * (double)v3;
            }

            for (int x = index + 8; x > 256; x >>= 1)
                if (++scale[i] >= 12)
                    scale[i] = 11;
        } while ((scale[i] < 12) && (index > 1));
    }

    double smallest = 1.0e30;
    for (int i = 0; i < 8; i++)
        if (distAccum[i] < smallest) { smallest = distAccum[i]; bestIndex = i; }

    for (int s = 0; s < sampleCount; s++)
        pcmInOut[s + 2] = (s16)inSamples[bestIndex][s + 2];

    pcmInOut[0] = pcmInOut[sampleCount];
    pcmInOut[1] = pcmInOut[sampleCount + 1];

    adpcmOut[0] = (u8)((bestIndex << 4) | (scale[bestIndex] & 0xF));
    for (int y = 0; y < 7; y++)
        adpcmOut[y + 1] = (u8)(((outSamples[bestIndex][y * 2] & 0xF) << 4) |
                                (outSamples[bestIndex][y * 2 + 1] & 0xF));
}

/* ------------------------------------------------------------------- decoder */
/* Mirrors the DSP so the encoder can be verified by round-trip SNR. */
static void dspDecode(const u8* adpcm, int frames, const s16 coefs[16], s16 yn1, s16 yn2, s16* out)
{
    int o = 0;
    for (int f = 0; f < frames; f++) {
        const u8* fr = adpcm + (size_t)f * FRAME_BYTES;
        int ps    = fr[0];
        int scale = 1 << (ps & 0xF);
        int pred  = (ps >> 4) & 0x7;
        int c0 = coefs[pred * 2], c1 = coefs[pred * 2 + 1];
        for (int s = 0; s < FRAME_SAMPLES; s++) {
            int nib = (s & 1) ? (fr[1 + s / 2] & 0xF) : (fr[1 + s / 2] >> 4);
            if (nib >= 8) nib -= 16;
            int sample = (((nib * scale) << 11) + 1024 + (c0 * yn1 + c1 * yn2)) >> 11;
            s16 v = clamp16(sample);
            yn2 = yn1; yn1 = v;
            out[o++] = v;
        }
    }
}

/* ---------------------------------------------------------------- WAV loading */

static int readWav(const char* path, s16** outPcm, int* outCh, int* outRate, int* outFrames)
{
    FILE* f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "dspenc: cannot open %s\n", path); return 0; }

    char riff[12];
    if (fread(riff, 1, 12, f) != 12 || memcmp(riff, "RIFF", 4) || memcmp(riff + 8, "WAVE", 4)) {
        fprintf(stderr, "dspenc: %s is not RIFF/WAVE\n", path); fclose(f); return 0;
    }

    int ch = 0, rate = 0, bits = 0;
    s16* pcm = NULL; long frames = 0;

    for (;;) {
        char id[4]; u32 sz;
        if (fread(id, 1, 4, f) != 4) break;
        if (fread(&sz, 4, 1, f) != 1) break;

        if (!memcmp(id, "fmt ", 4)) {
            u16 fmt, nch, blockAlign, bps; u32 sr, br;
            if (fread(&fmt, 2, 1, f) != 1) break;
            if (fread(&nch, 2, 1, f) != 1) break;
            if (fread(&sr, 4, 1, f) != 1) break;
            if (fread(&br, 4, 1, f) != 1) break;
            if (fread(&blockAlign, 2, 1, f) != 1) break;
            if (fread(&bps, 2, 1, f) != 1) break;
            ch = nch; rate = (int)sr; bits = bps;
            if (sz > 16) fseek(f, (long)sz - 16, SEEK_CUR);
            if (fmt != 1 && fmt != 0xFFFE) {
                fprintf(stderr, "dspenc: %s is not PCM (fmt=%u)\n", path, fmt);
                fclose(f); return 0;
            }
        } else if (!memcmp(id, "data", 4)) {
            if (bits != 16 || ch < 1) {
                fprintf(stderr, "dspenc: need 16-bit PCM, got %d-bit %dch\n", bits, ch);
                fclose(f); return 0;
            }
            frames = (long)sz / (2 * ch);
            pcm = malloc((size_t)frames * ch * sizeof(s16));
            if (!pcm) { fclose(f); return 0; }
            if (fread(pcm, sizeof(s16), (size_t)frames * ch, f) != (size_t)frames * ch)
                fprintf(stderr, "dspenc: warning: short read on data chunk\n");
            break;
        } else {
            fseek(f, (long)sz + (sz & 1), SEEK_CUR);
        }
    }
    fclose(f);

    if (!pcm) { fprintf(stderr, "dspenc: no data chunk in %s\n", path); return 0; }
    *outPcm = pcm; *outCh = ch; *outRate = rate; *outFrames = (int)frames;
    return 1;
}

/* ---------------------------------------------------------------------- main */

static void put32(FILE* f, u32 v) { fwrite(&v, 4, 1, f); }

int main(int argc, char** argv)
{
    const char* inPath = NULL;
    const char* outPath = NULL;
    int framesPerBlock = 512;
    int verify = 0;
    u32 loopStart = 0, loopEnd = 0;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-o") && i + 1 < argc)           outPath = argv[++i];
        else if (!strcmp(argv[i], "--block") && i + 1 < argc) framesPerBlock = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--loop") && i + 2 < argc)  { loopStart = strtoul(argv[++i], 0, 10); loopEnd = strtoul(argv[++i], 0, 10); }
        else if (!strcmp(argv[i], "--verify"))                verify = 1;
        else if (!inPath)                                     inPath = argv[i];
    }

    if (!inPath || !outPath) {
        fprintf(stderr, "usage: dspenc <in.wav> -o <out.dspm> [--block N] [--loop S E] [--verify]\n");
        return 1;
    }

    s16* pcm; int ch, rate, frames;
    if (!readWav(inPath, &pcm, &ch, &rate, &frames)) return 1;
    if (ch > 2) { fprintf(stderr, "dspenc: %d channels unsupported\n", ch); free(pcm); return 1; }

    int samplesPerBlock = framesPerBlock * FRAME_SAMPLES;
    int totalFrames = (frames + FRAME_SAMPLES - 1) / FRAME_SAMPLES;
    int blockCount  = (totalFrames + framesPerBlock - 1) / framesPerBlock;
    if (blockCount < 1) blockCount = 1;

    s16** chan = malloc(ch * sizeof(s16*));
    for (int c = 0; c < ch; c++) {
        chan[c] = calloc((size_t)blockCount * samplesPerBlock, sizeof(s16));
        for (int i = 0; i < frames; i++)
            chan[c][i] = pcm[(size_t)i * ch + c];
    }
    free(pcm);

    s16 (*coefs)[16] = malloc(ch * sizeof(s16[16]));
    for (int c = 0; c < ch; c++)
        DSPCorrelateCoefs(chan[c], frames, coefs[c]);

    u8** enc = malloc(ch * sizeof(u8*));
    u16* bIdx = calloc((size_t)blockCount * ch, sizeof(u16));
    s16* bH0  = calloc((size_t)blockCount * ch, sizeof(s16));
    s16* bH1  = calloc((size_t)blockCount * ch, sizeof(s16));

    for (int c = 0; c < ch; c++) {
        enc[c] = calloc((size_t)blockCount * framesPerBlock, FRAME_BYTES);
        s16 conv[16];
        memset(conv, 0, sizeof(conv));
        size_t outFrame = 0;
        for (int b = 0; b < blockCount; b++) {
            /* history as the DSP will have it entering this block */
            bH0[(size_t)b * ch + c] = conv[1];   /* yn1 */
            bH1[(size_t)b * ch + c] = conv[0];   /* yn2 */
            bIdx[(size_t)b * ch + c] = 0;
            for (int fr = 0; fr < framesPerBlock; fr++, outFrame++) {
                size_t base = (size_t)b * samplesPerBlock + (size_t)fr * FRAME_SAMPLES;
                for (int s = 0; s < FRAME_SAMPLES; s++)
                    conv[s + 2] = chan[c][base + s];
                DSPEncodeFrame(conv, FRAME_SAMPLES, enc[c] + outFrame * FRAME_BYTES,
                               (const s16 (*)[2])coefs[c]);
            }
        }
    }

    if (verify) {
        for (int c = 0; c < ch; c++) {
            s16* dec = malloc((size_t)blockCount * samplesPerBlock * sizeof(s16));
            /* Decode block-by-block off the stored per-block history, exactly the
             * way the 3DS submits one ndspWaveBuf per block.  A mismatch here would
             * be an audible click at every block boundary. */
            for (int b = 0; b < blockCount; b++)
                dspDecode(enc[c] + (size_t)b * framesPerBlock * FRAME_BYTES, framesPerBlock,
                          coefs[c], bH0[(size_t)b * ch + c], bH1[(size_t)b * ch + c],
                          dec + (size_t)b * samplesPerBlock);
            double se = 0, sig = 0;
            for (int i = 0; i < frames; i++) {
                double d = (double)chan[c][i] - (double)dec[i];
                se  += d * d;
                sig += (double)chan[c][i] * (double)chan[c][i];
            }
            double snr = (se > 0) ? 10.0 * log10(sig / se) : 99.0;
            fprintf(stderr, "  ch%d round-trip SNR = %.2f dB\n", c, snr);
            free(dec);
        }
    }

    FILE* o = fopen(outPath, "wb");
    if (!o) { fprintf(stderr, "dspenc: cannot write %s\n", outPath); return 1; }

    u32 idxBytes = (u32)blockCount * ch * 6;
    u32 hdr      = 0x28 + (u32)ch * 32;
    u32 dataOff  = (hdr + idxBytes + 31) & ~31u;   /* keep block data 32-byte aligned */

    fwrite("DSPM", 1, 4, o);
    put32(o, 1);
    put32(o, (u32)rate);
    put32(o, (u32)ch);
    put32(o, (u32)frames);
    put32(o, (u32)framesPerBlock);
    put32(o, (u32)blockCount);
    put32(o, dataOff);
    put32(o, loopStart);
    put32(o, loopEnd);

    for (int c = 0; c < ch; c++)
        fwrite(coefs[c], sizeof(s16), 16, o);

    for (int b = 0; b < blockCount; b++)
        for (int c = 0; c < ch; c++) {
            fwrite(&bIdx[(size_t)b * ch + c], 2, 1, o);
            fwrite(&bH0[(size_t)b * ch + c], 2, 1, o);
            fwrite(&bH1[(size_t)b * ch + c], 2, 1, o);
        }

    while ((u32)ftell(o) < dataOff) fputc(0, o);

    for (int b = 0; b < blockCount; b++)
        for (int c = 0; c < ch; c++)
            fwrite(enc[c] + (size_t)b * framesPerBlock * FRAME_BYTES, 1,
                   (size_t)framesPerBlock * FRAME_BYTES, o);

    fclose(o);

    fprintf(stderr, "dspenc: %s -> %s  %d Hz %dch %d samples, %d blocks, %.1f KB\n",
            inPath, outPath, rate, ch, frames, blockCount,
            (dataOff + (double)blockCount * ch * framesPerBlock * FRAME_BYTES) / 1024.0);
    return 0;
}
