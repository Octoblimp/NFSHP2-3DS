#pragma once
#include <3ds.h>

// Runtime decoder for EA Blackbox's "JDLZ" compression format. C port of
// tools/jdlz.py (see that file's docstring for the header layout and the
// reference implementations this was ported from) -- used at boot-menu load
// time to decompress PC Files/FRONTEND/FrontB.lzc (one big outer JDLZ block
// containing every real .fng screen as its own individually JDLZ-compressed
// sub-block, back to back -- see tools/fng_extract.py / docs/formats/
// frontend-menu-re.md).

// Reads/validates the 16-byte JDLZ header at data[offset]. *compressedLen
// includes the header itself (matches the on-disk field); *uncompressedLen
// is the decompressed payload size. Returns false if there isn't room for a
// header at offset, or the magic/version byte don't match.
bool jdlz_read_header(const u8* data, size_t dataLen, size_t offset,
                       u32* uncompressedLen, u32* compressedLen);

// Decompresses one JDLZ block at data[offset]. On success, *outBuf is a
// malloc'd buffer of *outLen bytes (caller owns it, must free()), and
// *consumed is the block's compressed length -- so a caller walking a
// concatenated stream of blocks can advance to the next one. Returns false
// on a bad header or if the declared compressed length runs past dataLen.
bool jdlz_decompress(const u8* data, size_t dataLen, size_t offset,
                      u8** outBuf, u32* outLen, u32* consumed);

// Decompresses only the FRONT of the JDLZ block at data[offset] -- at most
// `outCap` bytes into the caller's buffer -- and returns how many it produced.
//
// This exists so a container scan can identify a compressed sub-block without
// paying for it. Every .fng package in a .bun carries its on-disk Name string
// at payload offset 40, so 128 bytes of output is enough to read both the
// FEn magic and the name; deciding "is this the screen I want?" that way costs
// a few hundred bytes of decode per candidate instead of the whole package
// (UI_PC_Customize_Options.fng alone is 377,952 bytes, and InGameCommon.bun
// holds 24 of these back to back). Returns 0 on a bad header.
u32 jdlz_decompress_prefix(const u8* data, size_t dataLen, size_t offset,
                            u8* out, u32 outCap);
