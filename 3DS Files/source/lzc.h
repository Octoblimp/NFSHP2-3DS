#pragma once
#include <3ds.h>

// Runtime decoder for bWare's "COMP" compression -- the .LZC container used
// throughout ZZDATA.BIN. C port of tools/lzdecompress.py, which is itself a
// 1:1 port of LZDecompress() at 0x001aa460 in NFSHP2.ELF.
//
// This is NOT JDLZ. NFSU2 and the later EA Black Box titles use JDLZ; HP2
// predates it and ships its own LZSS in LZCompress.obj. There is no jdlz /
// JDLZ symbol anywhere in NFSHP2.ELF or its .MAP. See
// docs/formats/zdir-archive.md for the header layout and the token encoding.
//
// Most assets ship twice in the archive, once raw and once as a .LZC, so the
// loader can pick whichever is cheaper: on 3DS, reading 4 MB off the SD card
// and expanding it beats reading 15 MB of raw .BUN.

#define LZC_HEADER_SIZE 16

// Reads and validates the 16-byte COMP header at data[offset].
// *uncompressedLen is the size of the expanded payload; *compressedLen is the
// whole block including this header, so a caller walking a concatenated
// stream can advance by it. Returns false if there is no room for a header at
// offset, if the magic is not 'COMP', or if the declared block length runs
// past dataLen.
bool lzc_read_header(const u8* data, size_t dataLen, size_t offset,
                     u32* uncompressedLen, u32* compressedLen);

// Expands the COMP block at data[offset] into the caller's buffer. Writes at
// most outCap bytes and stores the produced length in *outLen. Returns false
// on a bad header, if outCap is smaller than the header's uncompressed size,
// or if the token stream tries to read or write out of bounds -- a truncated
// or corrupt block fails cleanly rather than running off the buffer.
bool lzc_decompress_into(const u8* data, size_t dataLen, size_t offset,
                         u8* out, size_t outCap, u32* outLen);

// Same, but allocates. On success *outBuf is a malloc'd buffer of *outLen
// bytes (caller owns it, must free()) and *consumed is the block's compressed
// length. Prefer lzc_decompress_into() when the destination is already
// allocated -- on 3DS that avoids a second copy of a multi-megabyte bundle.
bool lzc_decompress(const u8* data, size_t dataLen, size_t offset,
                    u8** outBuf, u32* outLen, u32* consumed);

// Expands only the front of the block at data[offset], at most outCap bytes,
// and returns how many it produced. Lets a container scan identify a block
// from its first few bytes -- the chunk type, or the ..\Psx2\CD\ build path
// most assets still carry -- without paying to expand a 9 MB track bundle.
// Returns 0 on a bad header.
u32 lzc_decompress_prefix(const u8* data, size_t dataLen, size_t offset,
                          u8* out, u32 outCap);
