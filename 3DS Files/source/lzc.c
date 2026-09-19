// bWare "COMP" (.LZC) decompressor -- see lzc.h.
//
// Ported from LZDecompress() at 0x001aa460 in NFSHP2.ELF via
// tools/lzdecompress.py. The token encoding is documented in
// docs/formats/zdir-archive.md; the short version is 16-bit control words
// read LSB-first, a clear bit meaning one literal byte and a set bit meaning
// a two-byte back-reference of 3..18 bytes from up to 4095 back.
//
// The EE original unrolls 16 tokens at a time and only drops to one at a time
// inside the last 32 bytes of the payload, which is what keeps a short final
// group from overrunning. That structure is kept here so the two stay
// comparable, with explicit bounds checks added on top: assets come off an SD
// card the user can edit, so a corrupt block has to fail rather than walk off
// the end of the heap.

#include <stdlib.h>
#include <string.h>

#include "lzc.h"

#define LZC_MAGIC   0x504d4f43u   /* 'COMP', little-endian */
#define LZC_STORED  1             /* method 1 = payload is already raw */

static u32 rd32(const u8* p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((u32)p[3] << 24); }
static u16 rd16(const u8* p) { return (u16)(p[0] | (p[1] << 8)); }

bool lzc_read_header(const u8* data, size_t dataLen, size_t offset,
                     u32* uncompressedLen, u32* compressedLen)
{
    if (!data || offset > dataLen || dataLen - offset < LZC_HEADER_SIZE)
        return false;

    const u8* h = data + offset;
    if (rd32(h) != LZC_MAGIC)
        return false;

    u32 outLen = rd32(h + 8);
    u32 blkLen = rd32(h + 12);          /* header + payload */
    if (blkLen < LZC_HEADER_SIZE || blkLen > dataLen - offset)
        return false;

    if (uncompressedLen) *uncompressedLen = outLen;
    if (compressedLen)   *compressedLen = blkLen;
    return true;
}

// Expands the block at blk[0 .. blkLen) into out, writing at most outCap
// bytes, and returns how many it produced. Stops cleanly at the first sign of
// a malformed stream; the caller decides whether a short result is an error.
static u32 lzc_expand(const u8* blk, u32 blkLen, u8* out, size_t outCap)
{
    u32 sp = LZC_HEADER_SIZE;
    size_t dp = 0;
    u32 ctrl = 1;

    while (sp != blkLen) {
        if (ctrl == 1) {                       /* sentinel reached bit 0 */
            if (sp + 2 > blkLen) break;
            ctrl = (u32)blk[sp] | 0x10000u | ((u32)blk[sp + 1] << 8);
            sp += 2;
        }

        int n = (sp + 0x20 <= blkLen) ? 16 : 1;
        for (int i = 0; i < n; i++) {
            if (ctrl & 1) {
                if (sp + 2 > blkLen) return (u32)dp;
                u32 b0 = blk[sp], b1 = blk[sp + 1];
                sp += 2;

                u32 dist = ((b0 & 0xf0u) << 4) | b1;
                u32 len  = 3u + (b0 & 0x0fu);
                if (dist == 0 || dist > dp) return (u32)dp;
                if (outCap - dp < len) len = (u32)(outCap - dp);

                /* Matches may overlap the write cursor, so copy byte by byte
                   -- memcpy/memmove would produce the wrong bytes here. */
                for (u32 k = 0; k < len; k++, dp++)
                    out[dp] = out[dp - dist];
                if (dp >= outCap) return (u32)dp;
            } else {
                if (sp >= blkLen) return (u32)dp;
                if (dp >= outCap) return (u32)dp;
                out[dp++] = blk[sp++];
            }
            ctrl >>= 1;
        }
    }
    return (u32)dp;
}

bool lzc_decompress_into(const u8* data, size_t dataLen, size_t offset,
                         u8* out, size_t outCap, u32* outLen)
{
    u32 declared, blkLen;
    if (!out || !lzc_read_header(data, dataLen, offset, &declared, &blkLen))
        return false;
    if (outCap < declared)
        return false;

    const u8* blk = data + offset;
    u32 produced;

    if (rd16(blk + 6) == LZC_STORED) {
        produced = blkLen - LZC_HEADER_SIZE;
        if (produced > declared) produced = declared;
        memcpy(out, blk + LZC_HEADER_SIZE, produced);
    } else {
        produced = lzc_expand(blk, blkLen, out, outCap);
    }

    if (outLen) *outLen = produced;
    return produced == declared;
}

bool lzc_decompress(const u8* data, size_t dataLen, size_t offset,
                    u8** outBuf, u32* outLen, u32* consumed)
{
    u32 declared, blkLen;
    if (!outBuf || !lzc_read_header(data, dataLen, offset, &declared, &blkLen))
        return false;

    u8* buf = (u8*)malloc(declared ? declared : 1);
    if (!buf)
        return false;

    u32 produced = 0;
    if (!lzc_decompress_into(data, dataLen, offset, buf, declared, &produced)) {
        free(buf);
        return false;
    }

    *outBuf = buf;
    if (outLen)   *outLen = produced;
    if (consumed) *consumed = blkLen;
    return true;
}

u32 lzc_decompress_prefix(const u8* data, size_t dataLen, size_t offset,
                          u8* out, u32 outCap)
{
    u32 declared, blkLen;
    if (!out || !outCap || !lzc_read_header(data, dataLen, offset, &declared, &blkLen))
        return 0;

    const u8* blk = data + offset;
    u32 cap = (outCap < declared) ? outCap : declared;

    if (rd16(blk + 6) == LZC_STORED) {
        u32 avail = blkLen - LZC_HEADER_SIZE;
        if (cap > avail) cap = avail;
        memcpy(out, blk + LZC_HEADER_SIZE, cap);
        return cap;
    }
    return lzc_expand(blk, blkLen, out, cap);
}
