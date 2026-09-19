/*
 * ea_demux.h -- minimal demuxer for EA's proprietary MVhd/SCHl/MV0K/MV0F/
 * SCEl multimedia container (as used by NFSU2's ealogo.vp6 and NFSHP2's equivalent
 * boot-movie assets), video-only. Chunk layout and field offsets ported
 * directly from FFmpeg's real libavformat/electronicarts.c demuxer
 * (process_ea_header / process_video_header_vp6 / ea_read_packet), cross
 * -validated byte-for-byte against a hex dump of the real ealogo.vp6 file.
 */
#ifndef EA_DEMUX_H
#define EA_DEMUX_H

#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>

typedef struct EaDemuxer {
    FILE *f;

    /* From the MVhd header. */
    uint32_t nb_frames;
    uint32_t tb_den;   /* time_base.den */
    uint32_t tb_num;   /* time_base.num */
    double   fps;      /* tb_den / tb_num, precomputed */

    bool big_endian;   /* chunk size fields are big-endian (rare EA variant) */
} EaDemuxer;

/* Opens 'path', scans the MVhd (+ skips SCHl/audio headers) so nb_frames/
 * fps are populated. Returns true on success; on failure the file is
 * closed and *demux is left zeroed. */
bool ea_demux_open(EaDemuxer *demux, const char *path);

void ea_demux_close(EaDemuxer *demux);

/* Reads forward from the current file position to the next MV0K/MV0F video
 * chunk, and returns its raw VP6 payload in a freshly av_malloc'd buffer
 * (caller must free()) sized (chunk payload size + AV_INPUT_BUFFER_PADDING_
 * SIZE), with the padding tail zeroed as vp6's bitstream reader requires.
 * *out_size receives the real payload size (without padding). *out_key is
 * set true for MV0K (keyframe) chunks. Returns false at end-of-clip / EOF
 * or on any read error. */
bool ea_demux_read_video_packet(EaDemuxer *demux, uint8_t **out_data,
                                 int *out_size, bool *out_key);

#endif /* EA_DEMUX_H */
