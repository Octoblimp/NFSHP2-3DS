#include "jdlz.h"
#include <stdlib.h>
#include <string.h>

#define JDLZ_HEADER_SIZE 16

bool jdlz_read_header(const u8* data, size_t dataLen, size_t offset,
                       u32* uncompressedLen, u32* compressedLen) {
	if (dataLen < JDLZ_HEADER_SIZE || offset > dataLen - JDLZ_HEADER_SIZE)
		return false;
	if (memcmp(data + offset, "JDLZ", 4) != 0)
		return false;
	if (data[offset + 4] != 0x02)
		return false;

	u32 uLen, cLen;
	memcpy(&uLen, data + offset + 8, 4);
	memcpy(&cLen, data + offset + 12, 4);
	*uncompressedLen = uLen;
	*compressedLen = cLen;
	return true;
}

bool jdlz_decompress(const u8* data, size_t dataLen, size_t offset,
                      u8** outBuf, u32* outLen, u32* consumed) {
	u32 uncompressedLen, compressedLen;
	if (!jdlz_read_header(data, dataLen, offset, &uncompressedLen, &compressedLen))
		return false;
	if (compressedLen < JDLZ_HEADER_SIZE || offset + compressedLen > dataLen)
		return false;

	u8* out = (u8*)malloc(uncompressedLen ? uncompressedLen : 1);
	if (!out)
		return false;

	size_t inPos = offset + JDLZ_HEADER_SIZE;
	size_t inEnd = offset + compressedLen;
	u32 outPos = 0;
	int flags1 = 1, flags2 = 1;

	while (inPos < inEnd && outPos < uncompressedLen) {
		if (flags1 == 1) {
			if (inPos >= inEnd) break;
			flags1 = data[inPos++] | 0x100;
		}
		if (flags2 == 1) {
			if (inPos >= inEnd) break;
			flags2 = data[inPos++] | 0x100;
		}

		if (flags1 & 1) {
			if (inPos + 2 > inEnd) break;
			u8 b0 = data[inPos];
			u8 b1 = data[inPos + 1];
			u32 length, t;
			if (flags2 & 1) {
				// short match: 1-16 byte backtrack, 3-4098 byte length
				length = (u32)(b1 | ((b0 & 0xF0) << 4)) + 3;
				t = (u32)(b0 & 0x0F) + 1;
			} else {
				// long match: 17-2064 byte backtrack, 3-34 byte length
				t = (u32)(b1 | ((b0 & 0xE0) << 3)) + 17;
				length = (u32)(b0 & 0x1F) + 3;
			}
			inPos += 2;

			if (t > outPos || outPos + length > uncompressedLen) {
				// Malformed/truncated input (shouldn't happen against real
				// game data) -- bail rather than read/write out of bounds.
				free(out);
				return false;
			}
			for (u32 i = 0; i < length; i++)
				out[outPos + i] = out[outPos + i - t];
			outPos += length;
			flags2 >>= 1;
		} else {
			if (inPos >= inEnd || outPos >= uncompressedLen) break;
			out[outPos++] = data[inPos++];
		}
		flags1 >>= 1;
	}

	*outBuf = out;
	*outLen = uncompressedLen;
	*consumed = compressedLen;
	return true;
}

u32 jdlz_decompress_prefix(const u8* data, size_t dataLen, size_t offset,
                            u8* out, u32 outCap) {
	u32 uncompressedLen, compressedLen;
	if (!out || outCap == 0)
		return 0;
	if (!jdlz_read_header(data, dataLen, offset, &uncompressedLen, &compressedLen))
		return 0;
	if (compressedLen < JDLZ_HEADER_SIZE || offset + compressedLen > dataLen)
		return 0;

	// The cap is the only difference from jdlz_decompress(): a back-reference
	// always points into output this pass has already produced (the format has
	// no window that predates offset 0), so a truncated prefix decodes exactly
	// the same bytes the full pass would -- it just stops early. A match that
	// would straddle the cap is copied up to the cap and then ends the pass.
	const u32 limit = (uncompressedLen < outCap) ? uncompressedLen : outCap;

	size_t inPos = offset + JDLZ_HEADER_SIZE;
	size_t inEnd = offset + compressedLen;
	u32 outPos = 0;
	int flags1 = 1, flags2 = 1;

	while (inPos < inEnd && outPos < limit) {
		if (flags1 == 1) {
			if (inPos >= inEnd) break;
			flags1 = data[inPos++] | 0x100;
		}
		if (flags2 == 1) {
			if (inPos >= inEnd) break;
			flags2 = data[inPos++] | 0x100;
		}

		if (flags1 & 1) {
			if (inPos + 2 > inEnd) break;
			u8 b0 = data[inPos];
			u8 b1 = data[inPos + 1];
			u32 length, t;
			if (flags2 & 1) {
				length = (u32)(b1 | ((b0 & 0xF0) << 4)) + 3;
				t = (u32)(b0 & 0x0F) + 1;
			} else {
				t = (u32)(b1 | ((b0 & 0xE0) << 3)) + 17;
				length = (u32)(b0 & 0x1F) + 3;
			}
			inPos += 2;

			if (t > outPos)
				return outPos;   // malformed; keep what decoded cleanly
			for (u32 i = 0; i < length && outPos < limit; i++, outPos++)
				out[outPos] = out[outPos - t];
			flags2 >>= 1;
		} else {
			if (inPos >= inEnd) break;
			out[outPos++] = data[inPos++];
		}
		flags1 >>= 1;
	}

	return outPos;
}
