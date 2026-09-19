/*
 * vp6_api.h -- entry points into the vendored FFmpeg VP6 decoder
 * (vp6.c/vp56.c) exposed for direct use outside FFmpeg's own codec
 * registry/dispatch machinery (which this standalone port doesn't carry).
 */
#ifndef VP6_API_H
#define VP6_API_H

#include "vp6compat.h"
#include "vp56.h" /* VP56Context -- caller must av_mallocz(sizeof(VP56Context))
                    * into AVCodecContext.priv_data before vp6_decode_init(). */

/* Defined in vp6.c (with FFCodec registration stripped, see the comment
 * at the bottom of that file). */
int vp6_decode_init(AVCodecContext *avctx);
int vp6_decode_free(AVCodecContext *avctx);

/* Defined in vp56.c; shared entry point for VP5/VP6 frame decoding. */
int ff_vp56_decode_frame(AVCodecContext *avctx, AVFrame *frame,
                          int *got_frame, AVPacket *avpkt);

#endif /* VP6_API_H */
