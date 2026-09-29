#pragma once
#include <stddef.h>
#include <stdint.h>

// EA's MV3 video codec, fourcc MV30, transcribed from the retail ELF's
// DCTImage, Huffman and MV3Codec (SLES_507.31, addresses below).
// `docs/formats/mv3-video.md` has the format; this is the code.
//
// A frame whose layout word is 0 is intra: every macroblock is coded. The
// boot movies in MOVIES\INTRO are all intra. Any other layout word is an
// inter frame, which the menu movies in MOVIES are nearly all made of: a
// macroblock may be copied from the previous frame, displaced by a motion
// vector, with a residual added on top or not. So an inter movie has to be
// decoded frame by frame, none skipped.
//
// Held to retail's own decoder, run in mipsemu, by `tools/mv3_check.py`: the
// tables, the entropy layer, each IDCT and IDCTAdd, the motion copy and the
// colour conversion function by function; whole frames of the boot movies
// byte for byte; and inter sequences, synthetic ones and a menu movie's.
//
// Nothing here includes <3ds.h>, so the host builds and tests the same file.

#define MV3_MB 16

enum {
    MV3_OK          = 0,
    MV3_ERR_SHORT   = -1,     // a frame too short for its own header
    MV3_ERR_VECTS   = -2,     // more motion vectors than macroblocks
    MV3_ERR_ROW     = -3,     // a row asks for more coefficients, or more
                              // coded macroblocks, than it has
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

// DCTImage. The planes hold the picture the way the encoder fed it in,
// bottom row first.
//
// Init (0x00234560) makes two allocations of the same layout, the frame
// being decoded and the one before it: Y, U and V each in `area` bytes (the
// Y plane's size rounded up to 128, so U and V are four times their size),
// then the motion vectors. A vector that reaches past its plane reads what
// retail's does, so the port keeps the layout; one that leaves the
// allocation reads 0 (mv3_copy_misses).
typedef struct {
    int      width, height;       // DCTImage +68, +72
    int      mbw;                 // (width + 15) / 16
    int      numVects;            // +80, NumVects: one per macroblock
    uint32_t area;                // a plane's bytes in the allocation
    uint32_t allocSize;           // 3 * area + numVects * 4, as retail's
    uint8_t* planes;              // +0, pData
    uint8_t* y;                   // +4, width x height
    uint8_t* u;                   // +8, width/2 x height/2
    uint8_t* v;                   // +12
    int16_t* vects;               // +28, pVects: dx, dy for each copied
                                  // macroblock, in order
    uint8_t* prevPlanes;          // +40, pPrevData
    uint8_t* prevY;               // +44
    uint8_t* prevU;               // +48
    uint8_t* prevV;               // +52
    int16_t* prevVects;           // +56
    uint8_t* transp;              // +20, pTransp: a byte per four
                                  // macroblocks, copy bits low, no-residual
                                  // bits high
    int16_t* coef;                // +60, pDCTData: one macroblock row
    uint32_t coefCap;             // +64, mbw * 384
    int16_t  quant[4][64];        // +92 luma, +220 luma at q+d,
                                  // +348 chroma, +476 chroma at q+d
    Mv3Bits  bits;
} Mv3Codec;

int  mv3_init(Mv3Codec* m, int width, int height);
void mv3_free(Mv3Codec* m);

// DecompressFrameShared (0x00239148) and ToImage (0x00234b38): one frame,
// its four-byte header included, into the planes. The frame before it is
// what an inter frame copies from, so an inter movie's frames go through
// here in order.
//
// Retail's ToImage ends with SwapPrevBuffer (0x00236638); the port swaps as
// it starts instead, so that between frames y, u and v are the frame just
// decoded, which is what mv3_to_rgba and mv3_to_tiled_rgba8 read. The
// buffers alternate the same way.
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

// IDCTAdd (0x00233c20), IDCTAdd1 (0x00233fa0) and IDCTAdd4 (0x00234090): the
// same transforms, each output added to the byte already in `dst` through
// `Codec::Clamp` rather than written through OffsetClamp. An inter frame's
// residual goes through these, onto the copied macroblock.
// mv3_idct_add_zigzag unscans first, as IDCTAddImageData (0x00234aa0) does.
void mv3_idct_add(const int16_t* coef, const int16_t* q, uint8_t* dst,
                  int stride);
void mv3_idct_add_zigzag(const int16_t* coef, const int16_t* q, uint8_t* dst,
                         int stride);
void mv3_idct1_add(const int16_t* coef, const int16_t* q, uint8_t* dst,
                   int stride);
void mv3_idct4_add(const int16_t* coef, const int16_t* q, uint8_t* dst,
                   int stride);

// CopyPreviousFrameBlock (0x00236950): macroblock (x, y) of the previous
// frame, displaced by vector `idx`, into the three destinations.
void mv3_copy_prev(Mv3Codec* m, int x, int y, uint8_t* dy, uint8_t* du,
                   uint8_t* dv, int idx);

// How many IDCT outputs fell outside the clamp tables since the last reset.
// The PS2 indexes `Codec::OffsetClamp` and `Codec::Clamp` without a bound,
// so such a value reads whatever memory surrounds the table; the port
// saturates instead. Retail's data never gets there (tools/mv3_check.py
// counts it).
extern uint32_t mv3_clamp_misses;

// How many bytes a motion copy read from outside its allocation, which the
// PS2 reads from whatever is there and the port reads as 0. Retail's data
// never gets there either.
extern uint32_t mv3_copy_misses;
