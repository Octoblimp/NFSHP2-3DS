#include "mv3.h"

#include <stdlib.h>
#include <string.h>

// Retail addresses throughout (SLES_507.31). The arithmetic is the PS2's:
// 32-bit wrapping products and sums, arithmetic shifts, and the IJG "ifast"
// AAN transform with 8-bit constants, so the IDCT works in uint32_t and
// shifts through SRA.

#define SRA(x, n) ((uint32_t)((int32_t)(x) >> (n)))

uint32_t mv3_clamp_misses;
uint32_t mv3_copy_misses;

// -- the tables -----------------------------------------------------------

// DCTBlockAdvance (0x002bdb08): a block type's coefficient count.
static const uint8_t kAdvance[4] = { 0, 1, 4, 64 };

// aanscales (0x002bda88), the IJG AAN factors at 14 bits.
static const int16_t kAan[64] = {
    16384, 22725, 21407, 19266, 16384, 12873, 8867, 4520,
    22725, 31521, 29692, 26722, 22725, 17855, 12299, 6270,
    21407, 29692, 27969, 25172, 21407, 16819, 11585, 5906,
    19266, 26722, 25172, 22654, 19266, 15137, 10426, 5315,
    16384, 22725, 21407, 19266, 16384, 12873, 8867, 4520,
    12873, 17855, 16819, 15137, 12873, 10114, 6967, 3552,
    8867, 12299, 11585, 10426, 8867, 6967, 4799, 2446,
    4520, 6270, 5906, 5315, 4520, 3552, 2446, 1247,
};

// LumaQuant (0x002bdb30) and ChromaQuant (0x002bdbb0).
static const int16_t kLumaQuant[64] = {
    12, 12, 15, 19, 25, 34, 40, 48,
    12, 12, 18, 22, 27, 44, 47, 46,
    17, 18, 21, 26, 35, 46, 52, 47,
    18, 20, 24, 28, 40, 61, 59, 51,
    20, 24, 32, 43, 50, 72, 72, 63,
    25, 31, 42, 48, 58, 72, 81, 75,
    38, 46, 54, 61, 71, 84, 88, 85,
    50, 61, 65, 68, 79, 78, 86, 91,
};
static const int16_t kChromaQuant[64] = {
    12, 16, 24, 47, 99, 99, 99, 99,
    16, 21, 26, 66, 99, 99, 99, 99,
    24, 26, 56, 99, 99, 99, 99, 99,
    47, 66, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
};

// The scan (0x0031c9a0): each natural position's index in the stream.
// DCTImage's constructor inverts it into 0x00334a68 and IDCTImageData
// scatters through the inverse; gathering through this is the same
// permutation.
static const uint8_t kZig[64] = {
    0, 1, 5, 6, 14, 15, 27, 28,
    2, 3, 7, 13, 16, 26, 29, 42,
    4, 8, 12, 17, 25, 30, 41, 43,
    9, 11, 18, 24, 31, 40, 44, 53,
    10, 19, 23, 32, 39, 45, 52, 54,
    20, 22, 33, 38, 46, 51, 55, 60,
    21, 34, 37, 47, 50, 56, 59, 61,
    35, 36, 48, 49, 57, 58, 62, 63,
};

// PrefixTab (0x002bdc48): length << 16 | code, one per magnitude class.
static const uint32_t kPrefix[12] = {
    0x20000, 0x20001, 0x30004, 0x30005, 0x30006, 0x4000e,
    0x5001e, 0x6003e, 0x7007e, 0x800fe, 0x901fe, 0x901ff,
};

// Codec::Codec (0x00231e10) fills 768 bytes: 256 zeros, the identity, 256
// copies of 255. Clamp points at the identity and OffsetClamp 128 past it.
static uint8_t kClampTab[768];
#define CLAMP (kClampTab + 256)

// DecodeTab (0x00334be8): the top 9 bits of the accumulator -> { bits, value }.
static uint8_t kDecode[512 * 2];
static int     gTablesBuilt;

static void build_texel_tables(void);

void mv3_build_tables(void)
{
    int k, j, i;

    if (gTablesBuilt) return;
    for (i = 0; i < 256; i++) {
        kClampTab[i]       = 0;
        kClampTab[256 + i] = (uint8_t)i;
        kClampTab[512 + i] = 255;
    }

    // BuildDecodeTab: class k has a prefix, then k bits whose top one is
    // the sign. A class too long for 9 bits becomes an escape entry.
    memset(kDecode, 0, sizeof(kDecode));
    for (k = 0; k < 12; k++) {
        int half = 1 << k;
        int mask = (half - 1) >> 1;
        int len  = (int)(kPrefix[k] >> 16);
        int code = (int)(kPrefix[k] & 0xffff);
        for (j = 0; j < half; j++) {
            int bits, pattern, value;
            if (k + len >= 10) {
                bits    = len;
                pattern = code;
                value   = -128;
            } else {
                bits    = k + len;
                pattern = (code << k) | j;
                if (k == 0)
                    value = 0;
                else if (j < half / 2)
                    value = (j & mask) + (1 << (k - 1));
                else
                    value = -((j & mask) + (1 << (k - 1)));
            }
            for (i = 0; i < 512; i++) {
                if ((i >> (9 - bits)) != pattern) continue;
                kDecode[i * 2 + 0] = (uint8_t)(value == -128 ? k - 1 : bits);
                kDecode[i * 2 + 1] = (uint8_t)(int8_t)value;
            }
        }
    }
    build_texel_tables();
    gTablesBuilt = 1;
}

const uint8_t* mv3_decode_table(void)
{
    mv3_build_tables();
    return kDecode;
}

// OffsetClamp[v]: the table is v + 384 from its start.
static inline uint8_t offset_clamp(uint32_t v)
{
    int32_t i = (int32_t)v + 384;
    if ((uint32_t)i < 768u) return kClampTab[i];
    mv3_clamp_misses++;
    return i < 0 ? 0 : 255;
}

// Clamp[d + v], which the IDCTAdds write through: d + v + 256 from the
// table's start.
static inline uint8_t add_clamp(uint8_t d, uint32_t v)
{
    int32_t i = (int32_t)(d + v) + 256;
    if ((uint32_t)i < 768u) return kClampTab[i];
    mv3_clamp_misses++;
    return i < 0 ? 0 : 255;
}

// -- the dequant tables ------------------------------------------------------

// DCTTable::ConvertQualityToScale (0x00236df8), IJG's curve.
static int quality_to_scale(int q)
{
    if (q < 1) q = 1;
    if (q > 100) q = 100;
    return q < 50 ? 5000 / q : 200 - 2 * q;
}

// GenerateLuma / GenerateChroma (0x00236e48, 0x00236e98) into ScaleTable
// (0x00236d90).
static void generate(int q, const int16_t* base, int16_t* t)
{
    int scale = quality_to_scale(q), i;
    for (i = 0; i < 64; i++) {
        int32_t v = (int32_t)((uint32_t)base[i] * (uint32_t)scale) + 50;
        v /= 100;
        if (v <= 0) v = 1;
        else if (v > 32767) v = 32767;
        t[i] = (int16_t)v;
    }
}

void mv3_init_idct_tables(Mv3Codec* m, int quality, int delta)
{
    int q = (int8_t)quality, qd = q + (int8_t)delta, i, t;

    generate(q,  kLumaQuant,   m->quant[0]);
    generate(qd, kLumaQuant,   m->quant[1]);
    generate(q,  kChromaQuant, m->quant[2]);
    generate(qd, kChromaQuant, m->quant[3]);
    for (t = 0; t < 4; t++)
        for (i = 0; i < 64; i++)
            m->quant[t][i] = (int16_t)SRA((uint32_t)m->quant[t][i]
                                          * (uint32_t)kAan[i] + 2048, 12);
}

// -- the entropy layer -----------------------------------------------------

void mv3_bits_init(Mv3Bits* b, const uint8_t* p, const uint8_t* end)
{
    b->p = p;
    b->end = end;
    b->count = 0;
    b->accum = 0;
}

static inline void refill(Mv3Bits* b)
{
    while (b->count < 25) {
        uint32_t byte = b->p < b->end ? *b->p : 0;
        b->p++;
        b->accum |= byte << ((24 - b->count) & 31);
        b->count += 8;
    }
}

// GETBITS (0x00237660): GetBits without the refill. The shifts are MIPS's,
// by the low five bits.
static inline uint32_t take(Mv3Bits* b, unsigned n)
{
    uint32_t v = b->accum >> ((0u - n) & 31);
    b->accum <<= n & 31;
    b->count -= n;
    return v;
}

uint32_t mv3_get_bits(Mv3Bits* b, unsigned n)
{
    refill(b);
    return take(b, n);
}

void mv3_decompress(Mv3Bits* bits, int16_t* out, uint32_t count)
{
    // The reader in a local, so that it lives in registers: through `bits`
    // any byte of the table read or coefficient written could be it, and
    // the compiler would store and reload it around each one.
    Mv3Bits  st = *bits;
    Mv3Bits* b = &st;
    int16_t* end = out + count;

    while (out < end) {
        const uint8_t* e;
        int8_t value;

        refill(b);
        e = &kDecode[(b->accum >> 23) * 2];
        value = (int8_t)e[1];
        if (value == -128) {
            // The escape: class kk + 1's prefix, a sign, then kk bits of a
            // magnitude whose top bit is implied.
            unsigned kk = e[0];
            unsigned len = kPrefix[kk + 1] >> 16;
            uint32_t sign, mag;
            b->accum <<= len & 31;
            b->count -= len;
            sign = take(b, 1);
            mag = (b->accum >> ((0u - kk) & 31)) + (1u << (kk & 31));
            b->accum <<= kk & 31;
            b->count -= kk;
            *out++ = (int16_t)(sign ? 0u - mag : mag);
        } else if (value != 0) {
            b->accum <<= e[0] & 31;
            b->count -= e[0];
            *out++ = value;
        } else {
            // A run of zeros: after the 2-bit prefix, a flag picks a 6-bit
            // run + 9 or a 3-bit run + 1. The run is written whole, so it
            // can land past `end`; mv3_decode leaves room.
            uint32_t run;
            b->accum <<= 2;
            b->count -= 2;
            if (take(b, 1))
                run = take(b, 6) + 9;
            else
                run = take(b, 3) + 1;
            memset(out, 0, run * sizeof(*out));
            out += run;
        }
    }
    *bits = st;
}

// -- the IDCTs -------------------------------------------------------------

// The AAN odd and even halves, as both passes spell them.
#define AAN_PASS(x0, x1, x2, x3, x4, x5, x6, x7, o0, o1, o2, o3, o4, o5, o6, o7) \
    do {                                                                      \
        uint32_t t10 = x0 + x4, t11 = x0 - x4;                                \
        uint32_t t13 = x2 + x6;                                               \
        uint32_t t12 = SRA((x2 - x6) * 362u, 8) - t13;                        \
        uint32_t e0 = t10 + t13, e3 = t10 - t13;                              \
        uint32_t e1 = t11 + t12, e2 = t11 - t12;                              \
        uint32_t z13 = x5 + x3, z10 = x5 - x3;                                \
        uint32_t z11 = x1 + x7, z12 = x1 - x7;                                \
        uint32_t d7 = z11 + z13;                                              \
        uint32_t d11 = SRA((z11 - z13) * 362u, 8);                            \
        uint32_t z5 = SRA((z10 + z12) * 473u, 8);                             \
        uint32_t d10 = SRA(z12 * 277u, 8) - z5;                               \
        uint32_t d12 = SRA(z10 * (uint32_t)-669, 8) + z5;                     \
        uint32_t d6 = d12 - d7;                                               \
        uint32_t d5 = d11 - d6;                                               \
        uint32_t d4 = d10 + d5;                                               \
        o0 = e0 + d7; o7 = e0 - d7;                                           \
        o1 = e1 + d6; o6 = e1 - d6;                                           \
        o2 = e2 + d5; o5 = e2 - d5;                                           \
        o4 = e3 + d4; o3 = e3 - d4;                                           \
    } while (0)

// Columns first, each coefficient dequantised as it is read. IDCT and
// IDCTAdd share it. With x1..x7 at 0 the AAN pass gives x0 in all eight
// places, wrapping arithmetic and all, so a column whose AC terms are all
// 0 is copied instead -- retail's scalar IDCT computes it, to the same
// values. Most columns of the movies' blocks are like that. `zig`, when
// set, is the scan: the block is read through it, as the unscan into a
// scratch block would leave it, without the copy.
static inline void idct_columns(const int16_t* coef, const uint8_t* zig,
                                const int16_t* q, uint32_t* ws)
{
#define AT(k) (zig ? coef[zig[k]] : coef[k])
    int i;
    for (i = 0; i < 8; i++) {
        uint32_t x[8];
        int r;
        if ((AT(8 + i) | AT(16 + i) | AT(24 + i) | AT(32 + i)
             | AT(40 + i) | AT(48 + i) | AT(56 + i)) == 0) {
            uint32_t x0 = (uint32_t)AT(i) * (uint32_t)q[i];
            for (r = 0; r < 8; r++) ws[r * 8 + i] = x0;
            continue;
        }
        for (r = 0; r < 8; r++)
            x[r] = (uint32_t)AT(r * 8 + i) * (uint32_t)q[r * 8 + i];
        AAN_PASS(x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7],
                 ws[i], ws[8 + i], ws[16 + i], ws[24 + i],
                 ws[32 + i], ws[40 + i], ws[48 + i], ws[56 + i]);
    }
#undef AT
}

// Then rows, descaled by 5 bits into OffsetClamp; a row with nothing past
// its first term is that term throughout, as a column is.
static inline void idct_rows(const uint32_t* ws, uint8_t* dst, int stride)
{
    int i;
    for (i = 0; i < 8; i++) {
        const uint32_t* w = ws + i * 8;
        uint32_t o[8];
        int c;
        if ((w[1] | w[2] | w[3] | w[4] | w[5] | w[6] | w[7]) == 0) {
            memset(dst, offset_clamp(SRA(w[0], 5)), 8);
            dst += stride;
            continue;
        }
        AAN_PASS(w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7],
                 o[0], o[1], o[2], o[3], o[4], o[5], o[6], o[7]);
        for (c = 0; c < 8; c++) dst[c] = offset_clamp(SRA(o[c], 5));
        dst += stride;
    }
}

// The rows, descaled by 5 bits and added to what is there, via Clamp.
static inline void idct_add_rows(const uint32_t* ws, uint8_t* dst, int stride)
{
    int i;
    for (i = 0; i < 8; i++) {
        const uint32_t* w = ws + i * 8;
        uint32_t o[8];
        int c;
        if ((w[1] | w[2] | w[3] | w[4] | w[5] | w[6] | w[7]) == 0) {
            uint32_t v = SRA(w[0], 5);
            for (c = 0; c < 8; c++) dst[c] = add_clamp(dst[c], v);
            dst += stride;
            continue;
        }
        AAN_PASS(w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7],
                 o[0], o[1], o[2], o[3], o[4], o[5], o[6], o[7]);
        for (c = 0; c < 8; c++) dst[c] = add_clamp(dst[c], SRA(o[c], 5));
        dst += stride;
    }
}

void mv3_idct(const int16_t* coef, const int16_t* q, uint8_t* dst, int stride)
{
    uint32_t ws[64];
    idct_columns(coef, NULL, q, ws);
    idct_rows(ws, dst, stride);
}

void mv3_idct_add(const int16_t* coef, const int16_t* q, uint8_t* dst,
                  int stride)
{
    uint32_t ws[64];
    idct_columns(coef, NULL, q, ws);
    idct_add_rows(ws, dst, stride);
}

// IDCTImageData unscans into a scratch block as IDCTAddImageData does,
// then runs IDCT on it.
void mv3_idct_zigzag(const int16_t* coef, const int16_t* q, uint8_t* dst,
                     int stride)
{
    uint32_t ws[64];
    idct_columns(coef, kZig, q, ws);
    idct_rows(ws, dst, stride);
}

// IDCTAddImageData unscans into a scratch block (0x00334b68) through the
// inverse scan, then jumps to IDCTAdd.
void mv3_idct_add_zigzag(const int16_t* coef, const int16_t* q, uint8_t* dst,
                         int stride)
{
    uint32_t ws[64];
    idct_columns(coef, kZig, q, ws);
    idct_add_rows(ws, dst, stride);
}

void mv3_idct1(const int16_t* coef, const int16_t* q, uint8_t* dst, int stride)
{
    uint8_t v = offset_clamp(SRA((uint32_t)coef[0] * (uint32_t)q[0], 5));
    int r;
    for (r = 0; r < 8; r++, dst += stride) memset(dst, v, 8);
}

void mv3_idct1_add(const int16_t* coef, const int16_t* q, uint8_t* dst,
                   int stride)
{
    uint32_t v = SRA((uint32_t)coef[0] * (uint32_t)q[0], 5);
    int r, c;
    for (r = 0; r < 8; r++, dst += stride)
        for (c = 0; c < 8; c++) dst[c] = add_clamp(dst[c], v);
}

// Four coefficients, the top-left 2x2 row by row: only columns 0 and 1 of
// rows 0 and 1 are live, so each pass is the AAN pass with x2..x7 or x1's
// partners at zero, and a lone DC skips the arithmetic. IDCT4 and IDCTAdd4
// share the columns.
static inline void idct4_columns(const int16_t* coef, const int16_t* q,
                                 uint32_t* ws)
{
    int i;

    for (i = 0; i < 2; i++) {
        uint32_t x0, x1;
        int r;
        if (coef[i + 2] == 0) {
            x0 = (uint32_t)coef[i] * (uint32_t)q[i];
            for (r = 0; r < 8; r++) ws[r * 8 + i] = x0;
            continue;
        }
        x1 = (uint32_t)coef[i + 2] * (uint32_t)q[i + 8];
        x0 = (uint32_t)coef[i] * (uint32_t)q[i];
        {
            uint32_t z5  = SRA(x1 * 473u, 8);
            uint32_t d6  = z5 - x1;
            uint32_t d5  = SRA(x1 * 362u, 8) - d6;
            uint32_t d4  = SRA(x1 * 277u, 8) - z5 + d5;
            ws[0 * 8 + i] = x0 + x1;  ws[7 * 8 + i] = x0 - x1;
            ws[1 * 8 + i] = x0 + d6;  ws[6 * 8 + i] = x0 - d6;
            ws[2 * 8 + i] = x0 + d5;  ws[5 * 8 + i] = x0 - d5;
            ws[4 * 8 + i] = x0 + d4;  ws[3 * 8 + i] = x0 - d4;
        }
    }
}

void mv3_idct4(const int16_t* coef, const int16_t* q, uint8_t* dst, int stride)
{
    uint32_t ws[64];
    int i;

    idct4_columns(coef, q, ws);
    for (i = 0; i < 8; i++, dst += stride) {
        uint32_t x0 = ws[i * 8], x1 = ws[i * 8 + 1];
        if (x1 == 0) {
            memset(dst, offset_clamp(SRA(x0, 5)), 8);
            continue;
        }
        {
            uint32_t z5 = SRA(x1 * 473u, 8);
            uint32_t d6 = z5 - x1;
            uint32_t d5 = SRA(x1 * 362u, 8) - d6;
            uint32_t d4 = SRA(x1 * 277u, 8) - z5 + d5;
            dst[0] = offset_clamp(SRA(x0 + x1, 5));
            dst[1] = offset_clamp(SRA(x0 + d6, 5));
            dst[2] = offset_clamp(SRA(x0 + d5, 5));
            dst[3] = offset_clamp(SRA(x0 - d4, 5));
            dst[4] = offset_clamp(SRA(x0 + d4, 5));
            dst[5] = offset_clamp(SRA(x0 - d5, 5));
            dst[6] = offset_clamp(SRA(x0 - d6, 5));
            dst[7] = offset_clamp(SRA(x0 - x1, 5));
        }
    }
}

void mv3_idct4_add(const int16_t* coef, const int16_t* q, uint8_t* dst,
                   int stride)
{
    uint32_t ws[64];
    int i, c;

    idct4_columns(coef, q, ws);
    for (i = 0; i < 8; i++, dst += stride) {
        uint32_t x0 = ws[i * 8], x1 = ws[i * 8 + 1];
        if (x1 == 0) {
            uint32_t v = SRA(x0, 5);
            for (c = 0; c < 8; c++) dst[c] = add_clamp(dst[c], v);
            continue;
        }
        {
            uint32_t z5 = SRA(x1 * 473u, 8);
            uint32_t d6 = z5 - x1;
            uint32_t d5 = SRA(x1 * 362u, 8) - d6;
            uint32_t d4 = SRA(x1 * 277u, 8) - z5 + d5;
            dst[0] = add_clamp(dst[0], SRA(x0 + x1, 5));
            dst[1] = add_clamp(dst[1], SRA(x0 + d6, 5));
            dst[2] = add_clamp(dst[2], SRA(x0 + d5, 5));
            dst[3] = add_clamp(dst[3], SRA(x0 - d4, 5));
            dst[4] = add_clamp(dst[4], SRA(x0 + d4, 5));
            dst[5] = add_clamp(dst[5], SRA(x0 - d5, 5));
            dst[6] = add_clamp(dst[6], SRA(x0 - d6, 5));
            dst[7] = add_clamp(dst[7], SRA(x0 - x1, 5));
        }
    }
}

// IDCTZero (0x00234a68): mid grey.
void mv3_idct_zero(uint8_t* dst, int stride)
{
    int r;
    for (r = 0; r < 8; r++, dst += stride) memset(dst, 0x80, 8);
}

// -- the frame ---------------------------------------------------------------

// y, u, v and the vectors inside one allocation, as Init lays them out.
static void point(uint8_t* base, uint32_t area, uint8_t** y, uint8_t** u,
                  uint8_t** v, int16_t** vects)
{
    *y = base;
    *u = base + area;
    *v = base + 2 * (size_t)area;
    *vects = (int16_t*)(base + 3 * (size_t)area);
}

int mv3_init(Mv3Codec* m, int width, int height)
{
    size_t ysize;

    memset(m, 0, sizeof(*m));
    if (width <= 0 || height <= 0 || (width % MV3_MB) || (height % MV3_MB))
        return MV3_ERR_SIZE;
    mv3_build_tables();
    m->width  = width;
    m->height = height;
    m->mbw    = width / MV3_MB;
    m->numVects = m->mbw * (height / MV3_MB);
    ysize = (size_t)width * (size_t)height;
    m->area = (uint32_t)((ysize + 127) & ~(size_t)127);
    m->allocSize = 3 * m->area + (uint32_t)m->numVects * 4u;
    // Both zeroed, as Init's memsets leave them. A zero run can write 72
    // values past the vectors' count, so each has that much more.
    m->planes = (uint8_t*)calloc(1, m->allocSize + 72 * 2);
    m->prevPlanes = (uint8_t*)calloc(1, m->allocSize + 72 * 2);
    m->transp = (uint8_t*)calloc(1, ((size_t)m->numVects + 3) / 4);
    // Init (0x00234560) sizes pDCTData at a row of full blocks; a zero run
    // can write 72 past the count, so the port adds that.
    m->coefCap = (uint32_t)m->mbw * 384u;
    m->coef = (int16_t*)calloc(m->coefCap + 72, sizeof(int16_t));
    if (!m->planes || !m->prevPlanes || !m->transp || !m->coef) {
        mv3_free(m);
        return MV3_ERR_ALLOC;
    }
    point(m->planes, m->area, &m->y, &m->u, &m->v, &m->vects);
    point(m->prevPlanes, m->area, &m->prevY, &m->prevU, &m->prevV,
          &m->prevVects);
    return MV3_OK;
}

void mv3_free(Mv3Codec* m)
{
    free(m->planes);
    free(m->prevPlanes);
    free(m->transp);
    free(m->coef);
    m->planes = m->prevPlanes = m->transp = NULL;
    m->coef = NULL;
    m->y = m->u = m->v = NULL;
    m->prevY = m->prevU = m->prevV = NULL;
    m->vects = m->prevVects = NULL;
}

// SwapPrevBuffer (0x00236638): PtrSwap on pData, pY, pU, pV and pVects with
// their pPrev twins, so all five trade places together.
static void swap_prev(Mv3Codec* m)
{
    uint8_t* p = m->planes;
    m->planes = m->prevPlanes;
    m->prevPlanes = p;
    point(m->planes, m->area, &m->y, &m->u, &m->v, &m->vects);
    point(m->prevPlanes, m->area, &m->prevY, &m->prevU, &m->prevV,
          &m->prevVects);
}

// `n` rows of `n` bytes, `stride` apart, from the previous frame's
// allocation at byte `off`. Retail reads a luma row with lq and qfsrv and a
// chroma one with ldl/ldr: 16 or 8 bytes from wherever they start.
static void copy_rows(const Mv3Codec* m, ptrdiff_t off, int stride,
                      uint8_t* dst, int n)
{
    ptrdiff_t size = (ptrdiff_t)m->allocSize;
    int r, i;

    for (r = 0; r < n; r++, off += stride, dst += stride) {
        if (off >= 0 && off + n <= size) {
            memcpy(dst, m->prevPlanes + off, (size_t)n);
            continue;
        }
        for (i = 0; i < n; i++) {
            ptrdiff_t o = off + i;
            if (o >= 0 && o < size) {
                dst[i] = m->prevPlanes[o];
            } else {
                dst[i] = 0;
                mv3_copy_misses++;
            }
        }
    }
}

void mv3_copy_prev(Mv3Codec* m, int x, int y, uint8_t* dy, uint8_t* du,
                   uint8_t* dv, int idx)
{
    int w = m->width, cw = m->width / 2;
    int sx = x + m->vects[idx * 2], sy = y + m->vects[idx * 2 + 1];
    // Chroma at half the vector, C's division, toward zero.
    ptrdiff_t c = (ptrdiff_t)(sy / 2) * cw + sx / 2;

    copy_rows(m, (ptrdiff_t)sy * w + sx, w, dy, 16);
    copy_rows(m, (ptrdiff_t)m->area + c, cw, du, 8);
    copy_rows(m, 2 * (ptrdiff_t)m->area + c, cw, dv, 8);
}

// One block, by its type: ToImage's dispatch to IDCTZero, IDCTImageData1,
// IDCTImageData4 and IDCTImageData.
static inline const int16_t* block(const int16_t* c, unsigned type,
                                   const int16_t* q, uint8_t* dst, int stride)
{
    switch (type) {
    case 0: mv3_idct_zero(dst, stride); break;
    case 1: mv3_idct1(c, q, dst, stride); break;
    case 2: mv3_idct4(c, q, dst, stride); break;
    default: mv3_idct_zigzag(c, q, dst, stride); break;
    }
    return c + kAdvance[type];
}

// A copied macroblock's residual: nothing for type 0, then
// IDCTAddImageData1, IDCTAddImageData4 and IDCTAddImageData.
static inline const int16_t* block_add(const int16_t* c, unsigned type,
                                       const int16_t* q, uint8_t* dst,
                                       int stride)
{
    switch (type) {
    case 0: break;
    case 1: mv3_idct1_add(c, q, dst, stride); break;
    case 2: mv3_idct4_add(c, q, dst, stride); break;
    default: mv3_idct_add_zigzag(c, q, dst, stride); break;
    }
    return c + kAdvance[type];
}

// Block type i. In retail's buffer the types run on into the bitstream; a
// read past the frame's end is 0.
static inline unsigned type_of(const uint8_t* types, size_t cap, uint32_t i)
{
    if ((i >> 2) >= cap) return 0;
    return (types[i >> 2] >> ((i & 3) * 2)) & 3;
}

int mv3_decode(Mv3Codec* m, const uint8_t* frame, size_t len)
{
    const uint8_t* comp;
    const uint8_t* types;
    const uint8_t* end = frame + len;
    int w = m->width, cw = m->width / 2, row, mb, n, intra, vects = 0;
    uint32_t blk = 0, mbi = 0, vec = 0;
    size_t head, tcap, transp = ((size_t)m->numVects + 3) / 4;
    uint8_t *py, *pu, *pv;
    uint32_t typeSize;

    if (len < 6) return MV3_ERR_SHORT;
    // DecompressFrameShared: the two quality bytes, then the layout word.
    // 0 asks ToImage for the intra layout (flags bit 1); anything else is
    // the inter one.
    intra = frame[2] == 0 && frame[3] == 0;
    mv3_init_idct_tables(m, frame[0], frame[1]);

    // pCompData: the s16 size of the block types; an inter frame's then has
    // the s16 count of its motion vectors and pTransp's bytes. Then the
    // types, then the bits.
    comp = frame + 4;
    head = intra ? 2 : 4 + transp;
    if ((size_t)(end - comp) < head) return MV3_ERR_SHORT;
    typeSize = (uint32_t)(int16_t)(comp[0] | comp[1] << 8);
    types = comp + head;
    tcap = (size_t)(end - types);
    if (tcap < typeSize) return MV3_ERR_SHORT;
    if (intra) {
        if (typeSize < (uint32_t)(m->numVects * 6 + 3) / 4)
            return MV3_ERR_SHORT;
    } else {
        vects = (int16_t)(comp[2] | comp[3] << 8);
        if (vects < 0 || vects > m->numVects) return MV3_ERR_VECTS;
    }

    // What the frame before this left in y, u and v is now the previous
    // frame, and this one decodes over the one before that.
    swap_prev(m);
    if (!intra) memcpy(m->transp, comp + 4, transp);
    mv3_bits_init(&m->bits, types + typeSize, end);
    if (!intra) mv3_decompress(&m->bits, m->vects, (uint32_t)vects * 2);

    py = m->y;
    pu = m->u;
    pv = m->v;
    for (row = 0; row < m->height; row += MV3_MB) {
        uint32_t count = mv3_get_bits(&m->bits, 16);
        // An inter row says how many of its macroblocks carry coefficients.
        uint32_t coded = intra ? (uint32_t)m->mbw : mv3_get_bits(&m->bits, 8);
        int16_t* c;
        int16_t dcY = 0, dcU = 0, dcV = 0;
        uint32_t b;

        if (count > m->coefCap || coded > (uint32_t)m->mbw) return MV3_ERR_ROW;
        mv3_decompress(&m->bits, m->coef, count);

        // The DC predictors, one each for Y, U and V, start at 0 each row.
        c = m->coef;
        b = blk;
        for (mb = 0; mb < (int)coded; mb++) {
            for (n = 0; n < 6; n++, b++) {
                unsigned t = type_of(types, tcap, b);
                int16_t* dc = n < 4 ? &dcY : n == 4 ? &dcU : &dcV;
                if (!kAdvance[t]) continue;
                c[0] = (int16_t)(c[0] + *dc);
                *dc = c[0];
                c += kAdvance[t];
            }
        }

        // The macroblocks: four luma, U, V. A copied one's residual, if it
        // has one, is at the inter tables; a coded one is at the intra ones.
        {
            const int16_t* k = m->coef;
            for (mb = 0; mb < m->mbw; mb++, mbi++) {
                unsigned bits = intra ? 0 : m->transp[mbi >> 2] >> (mbi & 3);
                if (bits & 1) {
                    const int16_t* ql = m->quant[1];
                    const int16_t* qc = m->quant[3];
                    mv3_copy_prev(m, mb * MV3_MB, row, py, pu, pv, (int)vec++);
                    if (!(bits & 16)) {
                        k = block_add(k, type_of(types, tcap, blk++), ql, py, w);
                        k = block_add(k, type_of(types, tcap, blk++), ql, py + 8, w);
                        k = block_add(k, type_of(types, tcap, blk++), ql, py + 8 * w, w);
                        k = block_add(k, type_of(types, tcap, blk++), ql, py + 8 * w + 8, w);
                        k = block_add(k, type_of(types, tcap, blk++), qc, pu, cw);
                        k = block_add(k, type_of(types, tcap, blk++), qc, pv, cw);
                    }
                } else {
                    const int16_t* ql = m->quant[0];
                    const int16_t* qc = m->quant[2];
                    k = block(k, type_of(types, tcap, blk++), ql, py, w);
                    k = block(k, type_of(types, tcap, blk++), ql, py + 8, w);
                    k = block(k, type_of(types, tcap, blk++), ql, py + 8 * w, w);
                    k = block(k, type_of(types, tcap, blk++), ql, py + 8 * w + 8, w);
                    k = block(k, type_of(types, tcap, blk++), qc, pu, cw);
                    k = block(k, type_of(types, tcap, blk++), qc, pv, cw);
                }
                py += 16;
                pu += 8;
                pv += 8;
            }
        }
        py += 15 * w;
        pu += 7 * cw;
        pv += 7 * cw;
    }
    return MV3_OK;
}

// -- YUV -> RGB --------------------------------------------------------------

// ToImage32's division by 256: toward zero, a +255 bias below zero.
static inline int32_t div256(int32_t x)
{
    return (x > -1 ? x : x + 255) >> 8;
}

typedef struct { int32_t r, g, b; } Chroma;

static inline Chroma chroma(uint8_t u, uint8_t v)
{
    int32_t cr = (int32_t)v - 128, cb = (int32_t)u - 128;
    Chroma c;
    c.r = div256(cr * 359);
    c.g = div256(cb * -88 - cr * 183);
    c.b = div256(cb * 454);
    return c;
}

void mv3_to_rgba(const Mv3Codec* m, uint8_t* dst, int flip)
{
    int w = m->width, h = m->height, x, y;
    int stride = flip ? -4 * w : 4 * w;
    uint8_t* row = flip ? dst + (size_t)4 * w * (h - 1) : dst;
    const uint8_t* py = m->y;
    const uint8_t* pu = m->u;
    const uint8_t* pv = m->v;

    for (y = 0; y < h; y += 2) {
        uint8_t* d = row;
        for (x = 0; x < w; x += 2) {
            Chroma c = chroma(*pu++, *pv++);
            const uint8_t* ys[4] = { py + x, py + x + 1, py + w + x, py + w + x + 1 };
            uint8_t* ds[4] = { d, d + 4, d + stride, d + stride + 4 };
            int i;
            for (i = 0; i < 4; i++) {
                ds[i][0] = CLAMP[*ys[i] + c.r];
                ds[i][1] = CLAMP[*ys[i] + c.g];
                ds[i][2] = CLAMP[*ys[i] + c.b];
                ds[i][3] = 255;
            }
            d += 8;
        }
        py += 2 * w;
        row += 2 * stride;
    }
}

// Clamp a byte at a time, as ARMv6's UQADD8 and UQSUB8 do: each byte of a
// and b summed, or differenced, and held to 0..255.
#if defined(__ARM_FEATURE_SIMD32)
#include <arm_acle.h>
static inline uint32_t sat_add8(uint32_t a, uint32_t b) { return __uqadd8(a, b); }
static inline uint32_t sat_sub8(uint32_t a, uint32_t b) { return __uqsub8(a, b); }
#else
static inline uint32_t sat_add8(uint32_t a, uint32_t b)
{
    uint32_t r = 0;
    int i;
    for (i = 0; i < 32; i += 8) {
        uint32_t x = (a >> i & 0xff) + (b >> i & 0xff);
        r |= (x > 255 ? 255 : x) << i;
    }
    return r;
}
static inline uint32_t sat_sub8(uint32_t a, uint32_t b)
{
    uint32_t r = 0;
    int i;
    for (i = 0; i < 32; i += 8) {
        uint32_t x = a >> i & 0xff, y = b >> i & 0xff;
        r |= (x > y ? x - y : 0) << i;
    }
    return r;
}
#endif

// A texel's R, G and B are Clamp[y + c.r], [y + c.g] and [y + c.b]. Each c
// is under 256 either way (359, 454, and 88 + 183, times at most 128, over
// 256), and y is 0..255, so adding c's part at or above 0 and taking its
// part below 0 away, a byte at a time and each held to 0..255, is that
// clamp: one part is 0, and neither can carry y past the other end. The
// parts are kept as the bytes of a texel, R at the top, alpha at the
// bottom: `up` to add and `down` to take away.
typedef struct { uint32_t up, down; } ChromaBytes;

// y in R, G and B; c.r's parts, which only v sets; c.b's, which only u
// sets, with the alpha's 255 in `up`.
static uint32_t    kLumaBytes[256];
static ChromaBytes kRedBytes[256];
static ChromaBytes kBlueBytes[256];

static inline uint32_t pos_part(int32_t x) { return x > 0 ? (uint32_t)x : 0; }

static void build_texel_tables(void)
{
    int i;
    for (i = 0; i < 256; i++) {
        Chroma c = chroma((uint8_t)i, (uint8_t)i);
        kLumaBytes[i]      = (uint32_t)i * 0x01010100u;
        kRedBytes[i].up    = pos_part(c.r) << 24;
        kRedBytes[i].down  = pos_part(-c.r) << 24;
        kBlueBytes[i].up   = pos_part(c.b) << 8 | 0xffu;
        kBlueBytes[i].down = pos_part(-c.b) << 8;
    }
}

// A quad's parts. c.g takes both u and v, so it is worked out here; the
// compiler drops chroma's c.r and c.b, which the tables have.
static inline ChromaBytes chroma_bytes(uint8_t u, uint8_t v)
{
    Chroma c = chroma(u, v);
    ChromaBytes k;
    k.up   = kRedBytes[v].up | pos_part(c.g) << 16 | kBlueBytes[u].up;
    k.down = kRedBytes[v].down | pos_part(-c.g) << 16 | kBlueBytes[u].down;
    return k;
}

static inline uint32_t texel(uint8_t y, ChromaBytes k)
{
    return sat_sub8(sat_add8(kLumaBytes[y], k.up), k.down);
}

// Inside an 8x8 tile the texels run in Morton order, x's bits at 0, 2 and 4
// and y's at 1, 3 and 5, so a 2x2 quad is four texels in a row, and where
// it starts is x's bits 1 and 2 at 2 and 4, plus y's at 3 and 5.
static const uint8_t kQuadX[4] = { 0, 4, 16, 20 };
static const uint8_t kQuadY[4] = { 0, 8, 32, 40 };

void mv3_to_tiled_rgba8(const Mv3Codec* m, uint32_t* dst, int texWidth)
{
    int w = m->width, h = m->height, cw = w / 2, x, y, i;
    uint32_t tilesX = (uint32_t)texWidth / 8;

    // Image row y (top-down) is plane row h - 1 - y, so the image's quad at
    // rows y, y + 1 is plane rows h - 1 - y and h - 2 - y, sharing chroma
    // row (h - 2 - y) / 2. A tile's width at a time: the width is a whole
    // number of macroblocks.
    for (y = 0; y < h; y += 2) {
        const uint8_t* top = m->y + (size_t)w * (h - 1 - y);
        const uint8_t* bot = top - w;
        size_t crow = (size_t)cw * ((h - 2 - y) / 2);
        const uint8_t* pu = m->u + crow;
        const uint8_t* pv = m->v + crow;
        uint32_t* tile = dst + (size_t)(y >> 3) * tilesX * 64
                       + kQuadY[(y >> 1) & 3];
        for (x = 0; x < w; x += 8, tile += 64) {
            for (i = 0; i < 4; i++) {
                int qx = x + 2 * i;
                ChromaBytes k = chroma_bytes(pu[qx >> 1], pv[qx >> 1]);
                uint32_t* t = tile + kQuadX[i];
                t[0] = texel(top[qx], k);
                t[1] = texel(top[qx + 1], k);
                t[2] = texel(bot[qx], k);
                t[3] = texel(bot[qx + 1], k);
            }
        }
    }
}
