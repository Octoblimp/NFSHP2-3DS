#pragma once
#include <stddef.h>
#include <stdint.h>

// EA's MV3 video codec, fourcc MV30: the intra half, transcribed from the
// retail ELF's DCTImage, Huffman and MV3Codec (SLES_507.31, addresses below).
// `docs/formats/mv3-video.md` has the format; this is the code.
//
// Every retail movie is intra: each frame's layout word is 0, so no frame
// needs the one before it, and motion compensation never runs. A frame
// whose layout word is not 0 is refused (MV3_ERR_INTER) rather than guessed
// at. The demo disc's EALOGO_EN.AVI is the only MV3 file with deltas, and the
// port does not play the demo's data.
//
// Held to retail's own decoder, run in mipsemu, by `tools/mv3_check.py`: the
// tables, the entropy layer, each IDCT and the colour conversion function by
// function, and whole frames of the boot movies byte for byte.
//
// Nothing here includes <3ds.h>, so the host builds and tests the same file.

#define MV3_MB 16

enum {
    MV3_OK          = 0,
    MV3_ERR_SHORT   = -1,     // a frame too short for its own header
    MV3_ERR_INTER   = -2,     // the motion layout, which retail never uses
    MV3_ERR_ROW     = -3,     // a row asks for more coefficients than fit
    MV3_ERR_ALLOC   = -4,
    MV3_ERR_SIZE    = -5,     // not a whole number of macroblocks
};

// Huffman (24 bytes on the PS2): accum at +0, the live bit count at +4, the
// byte pointer at +20. `end` is the port's own: a refill past it reads 0,
// where the PS2 reads whatever memory follows the frame.
typedef struct {
    uint32_t       accum;
    uint32_t       count;
    const uint8_t* p;
    const uint8_t* end;
} Mv3Bits;

// DCTImage, what of it the intra path uses. The planes hold the picture the
// way the encoder fed it in, bottom row first.
typedef struct {
    int      width, height;       // DCTImage +68, +72
    int      mbw;                 // (width + 15) / 16
    uint8_t* planes;              // one allocation for all three
    uint8_t* y;                   // +4, width x height
    uint8_t* u;                   // +8, width/2 x height/2
    uint8_t* v;                   // +12
    int16_t* coef;                // +60, pDCTData: one macroblock row
    uint32_t coefCap;             // +64, mbw * 384
    int16_t  quant[4][64];        // +92 luma, +220 luma at q+d,
                                  // +348 chroma, +476 chroma at q+d
    Mv3Bits  bits;
} Mv3Codec;

int  mv3_init(Mv3Codec* m, int width, int height);
void mv3_free(Mv3Codec* m);

// DecompressFrameShared (0x00239148) and ToImage (0x00234b38): one frame,
// its four-byte header included, into the planes.
int  mv3_decode(Mv3Codec* m, const uint8_t* frame, size_t len);

// ToImage32 (0x002363a8): the planes as R, G, B, A bytes, width*4 a row.
// `flip` is ToImage's flags bit 0, which a negative biHeight sets; it turns
// the planes' bottom-up rows into a top-down image.
void mv3_to_rgba(const Mv3Codec* m, uint8_t* dst, int flip);

// The same pixels as mv3_to_rgba(m, dst, 1), written as the PICA200's RGBA8
// texels (R << 24 | G << 16 | B << 8 | A) in 8x8 Morton tiles, top row
// first -- `texpack_upload`'s layout. `texWidth` is the texture's width,
// which may be wider than the movie. A 2x2 quad shares one chroma sample and
// is four consecutive texels in Morton order, so each quad is one store run.
void mv3_to_tiled_rgba8(const Mv3Codec* m, uint32_t* dst, int texWidth);

// -- the pieces, exposed for the checker --------------------------------------

// Codec::Codec's clamp table and Huffman::BuildDecodeTab (0x002372a8).
// mv3_init() calls it; it only builds once.
void mv3_build_tables(void);
const uint8_t* mv3_decode_table(void);              // 512 x { bits, value }

// InitIDCTTables (0x00234718): the four dequant tables for a frame's two
// quality bytes.
void mv3_init_idct_tables(Mv3Codec* m, int quality, int delta);

void     mv3_bits_init(Mv3Bits* b, const uint8_t* p, const uint8_t* end);
uint32_t mv3_get_bits(Mv3Bits* b, unsigned n);      // GetBits (0x00237228)
void     mv3_decompress(Mv3Bits* b, int16_t* out, uint32_t count);
                                                    // Decompress (0x00237428)

// IDCT (0x00232d60, the path retail's mode word 2 selects), IDCT1
// (0x00233950) and IDCT4 (0x002339a8): dequantise and transform one 8x8
// block into `dst`. IDCT takes its 64 coefficients in natural order;
// mv3_idct_zigzag first undoes the stream's scan, as IDCTImageData does.
void mv3_idct(const int16_t* coef, const int16_t* q, uint8_t* dst, int stride);
void mv3_idct_zigzag(const int16_t* coef, const int16_t* q, uint8_t* dst,
                     int stride);
void mv3_idct1(const int16_t* coef, const int16_t* q, uint8_t* dst, int stride);
void mv3_idct4(const int16_t* coef, const int16_t* q, uint8_t* dst, int stride);
void mv3_idct_zero(uint8_t* dst, int stride);

// How many IDCT outputs fell outside the clamp table since the last reset.
// The PS2 indexes `Codec::OffsetClamp` without a bound, so such a value
// reads whatever memory surrounds the table; the port saturates instead.
// Retail's data never gets there (tools/mv3_check.py counts it).
extern uint32_t mv3_clamp_misses;
