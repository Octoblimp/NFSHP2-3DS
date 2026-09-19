/*
 * ea_demux.c -- see ea_demux.h. Ported from FFmpeg's real
 * libavformat/electronicarts.c (process_ea_header, process_video_header_vp6,
 * ea_read_packet), video-only (audio/other chunks are skipped since NFSU2/NFSHP2-
 * 3DS only needs to display the boot-movie picture, and audio is already
 * played from a separately-extracted .wav asset -- see main.c).
 *
 * Chunk layout confirmed byte-for-byte against a hex dump of the real
 * PC Files/MOVIES/ealogo.vp6: MVhd (size 0x20) at offset 0, nb_frames=94,
 * tb_den=1000000, tb_num=33333 (~30fps); SCHl (audio header, size 0x2C)
 * immediately follows and ends exactly at offset 0x4C, where the first
 * MV0K keyframe chunk begins (size 0x60 -> 88 bytes of VP6 payload).
 */
#include "ea_demux.h"
#include "vp6compat.h" /* AV_INPUT_BUFFER_PADDING_SIZE, av_malloc/av_free */
#include <string.h>

#define MKTAG(a,b,c,d) ((uint32_t)(a) | ((uint32_t)(b)<<8) | ((uint32_t)(c)<<16) | ((uint32_t)(d)<<24))

#define MVhd_TAG MKTAG('M','V','h','d')
#define SCHl_TAG MKTAG('S','C','H','l')
#define SHEN_TAG MKTAG('S','H','E','N')
#define MV0K_TAG MKTAG('M','V','0','K')
#define MV0F_TAG MKTAG('M','V','0','F')
#define SCDl_TAG MKTAG('S','C','D','l')
#define SCEl_TAG MKTAG('S','C','E','l')
#define SEND_TAG MKTAG('S','E','N','D')

static uint32_t rl32(const uint8_t b[4]) {
    return (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
}
static uint32_t rb32(const uint8_t b[4]) {
    return ((uint32_t)b[0] << 24) | ((uint32_t)b[1] << 16) | ((uint32_t)b[2] << 8) | (uint32_t)b[3];
}
static uint32_t bswap32(uint32_t v) {
    return ((v & 0xFF) << 24) | ((v & 0xFF00) << 8) | ((v >> 8) & 0xFF00) | ((v >> 24) & 0xFF);
}

/* Reads an 8-byte chunk header (tag + size, tag always little-endian per
 * the real demuxer). On the very first call, auto-detects whether the size
 * field itself is big-endian (rare EA variant) the same way ea_read_header
 * does: if the raw LE-decoded size looks implausible relative to its
 * byte-swapped value, prefer big-endian. Returns false on short read/EOF. */
static bool read_chunk_header(EaDemuxer *demux, uint32_t *tag, uint32_t *size, bool detect_endian) {
    uint8_t hdr[8];
    if (fread(hdr, 1, 8, demux->f) != 8)
        return false;
    *tag = rl32(hdr);
    uint32_t size_le = rl32(hdr + 4);
    if (detect_endian) {
        uint32_t size_be = rb32(hdr + 4);
        demux->big_endian = size_le > bswap32(size_le) && size_be < size_le;
    }
    *size = demux->big_endian ? rb32(hdr + 4) : size_le;
    return true;
}

bool ea_demux_open(EaDemuxer *demux, const char *path) {
    memset(demux, 0, sizeof(*demux));
    demux->f = fopen(path, "rb");
    if (!demux->f)
        return false;

    bool first = true;
    for (;;) {
        long chunk_start = ftell(demux->f);
        uint32_t tag, size;
        if (!read_chunk_header(demux, &tag, &size, first))
            goto fail;
        first = false;

        if (size < 8)
            goto fail;

        if (tag == MVhd_TAG) {
            uint8_t body[8 + 4 + 4 + 4 + 4];
            /* skip(8) + nb_frames(4) + skip(4) + tb_den(4) + tb_num(4) */
            if (fread(body, 1, sizeof(body), demux->f) != sizeof(body))
                goto fail;
            demux->nb_frames = demux->big_endian ? rb32(body + 8) : rl32(body + 8);
            demux->tb_den    = demux->big_endian ? rb32(body + 16) : rl32(body + 16);
            demux->tb_num    = demux->big_endian ? rb32(body + 20) : rl32(body + 20);
            if ((int32_t)demux->tb_den <= 0 || (int32_t)demux->tb_num <= 0)
                goto fail;
            demux->fps = (double)demux->tb_den / (double)demux->tb_num;
            /* Skip to the end of this chunk (size includes the 8-byte header). */
            if (fseek(demux->f, chunk_start + (long)size, SEEK_SET) != 0)
                goto fail;
            continue;
        }

        if (tag == SCHl_TAG || tag == SHEN_TAG) {
            /* Audio header -- not needed for video-only playback, skip it. */
            if (fseek(demux->f, chunk_start + (long)size, SEEK_SET) != 0)
                goto fail;
            continue;
        }

        /* Not a recognized header chunk -- this is the first data chunk.
         * Rewind to its start so ea_demux_read_video_packet can consume it. */
        if (fseek(demux->f, chunk_start, SEEK_SET) != 0)
            goto fail;
        break;
    }

    if (demux->nb_frames == 0)
        goto fail;

    return true;

fail:
    fclose(demux->f);
    memset(demux, 0, sizeof(*demux));
    return false;
}

void ea_demux_close(EaDemuxer *demux) {
    if (demux->f)
        fclose(demux->f);
    memset(demux, 0, sizeof(*demux));
}

bool ea_demux_read_video_packet(EaDemuxer *demux, uint8_t **out_data,
                                 int *out_size, bool *out_key) {
    for (;;) {
        uint32_t tag, size;
        if (!read_chunk_header(demux, &tag, &size, false))
            return false;

        if (size < 8 || tag == 0 || tag == SCEl_TAG || tag == SEND_TAG)
            return false;

        uint32_t payload_size = size - 8;

        if (tag == MV0K_TAG || tag == MV0F_TAG) {
            if (payload_size == 0) {
                /* Empty video chunk (duplicate frame): treat as a zero-byte
                 * packet the caller can skip decoding for. */
                *out_data = NULL;
                *out_size = 0;
                *out_key = (tag == MV0K_TAG);
                return true;
            }
            uint8_t *buf = (uint8_t *)av_malloc(payload_size + AV_INPUT_BUFFER_PADDING_SIZE);
            if (!buf)
                return false;
            if (fread(buf, 1, payload_size, demux->f) != payload_size) {
                av_free(buf);
                return false;
            }
            memset(buf + payload_size, 0, AV_INPUT_BUFFER_PADDING_SIZE);
            *out_data = buf;
            *out_size = (int)payload_size;
            *out_key = (tag == MV0K_TAG);
            return true;
        }

        /* Audio or other non-video chunk: skip it and keep scanning. */
        if (fseek(demux->f, (long)payload_size, SEEK_CUR) != 0)
            return false;
    }
}
