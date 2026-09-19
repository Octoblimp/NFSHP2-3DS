/*
 * vp6compat.c -- implementation of the minimal AVFrame/AVCodecContext
 * compatibility shim declared in vp6compat.h. See that header for context.
 */
#include "vp6compat.h"
#include <stdarg.h>
#include <stdio.h>

#define VP6_BORDER 32

/* Standard JPEG/MPEG zig-zag scan order (real ffmpeg ff_zigzag_direct table). */
const uint8_t ff_zigzag_direct[64] = {
    0,   1,  8, 16,  9,  2,  3, 10,
    17, 24, 32, 25, 18, 11,  4,  5,
    12, 19, 26, 33, 40, 48, 41, 34,
    27, 20, 13,  6,  7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36,
    29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46,
    53, 60, 61, 54, 47, 55, 62, 63,
};

/* Bit-reversal-per-byte table (real ffmpeg ff_reverse table). Generated
 * mechanically (reverse bits of index i) rather than typed by hand, so it is
 * exactly the standard table ffmpeg itself builds from the same formula. */
const uint8_t ff_reverse[256] = {
    0x00, 0x80, 0x40, 0xC0, 0x20, 0xA0, 0x60, 0xE0, 0x10, 0x90, 0x50, 0xD0, 0x30, 0xB0, 0x70, 0xF0,
    0x08, 0x88, 0x48, 0xC8, 0x28, 0xA8, 0x68, 0xE8, 0x18, 0x98, 0x58, 0xD8, 0x38, 0xB8, 0x78, 0xF8,
    0x04, 0x84, 0x44, 0xC4, 0x24, 0xA4, 0x64, 0xE4, 0x14, 0x94, 0x54, 0xD4, 0x34, 0xB4, 0x74, 0xF4,
    0x0C, 0x8C, 0x4C, 0xCC, 0x2C, 0xAC, 0x6C, 0xEC, 0x1C, 0x9C, 0x5C, 0xDC, 0x3C, 0xBC, 0x7C, 0xFC,
    0x02, 0x82, 0x42, 0xC2, 0x22, 0xA2, 0x62, 0xE2, 0x12, 0x92, 0x52, 0xD2, 0x32, 0xB2, 0x72, 0xF2,
    0x0A, 0x8A, 0x4A, 0xCA, 0x2A, 0xAA, 0x6A, 0xEA, 0x1A, 0x9A, 0x5A, 0xDA, 0x3A, 0xBA, 0x7A, 0xFA,
    0x06, 0x86, 0x46, 0xC6, 0x26, 0xA6, 0x66, 0xE6, 0x16, 0x96, 0x56, 0xD6, 0x36, 0xB6, 0x76, 0xF6,
    0x0E, 0x8E, 0x4E, 0xCE, 0x2E, 0xAE, 0x6E, 0xEE, 0x1E, 0x9E, 0x5E, 0xDE, 0x3E, 0xBE, 0x7E, 0xFE,
    0x01, 0x81, 0x41, 0xC1, 0x21, 0xA1, 0x61, 0xE1, 0x11, 0x91, 0x51, 0xD1, 0x31, 0xB1, 0x71, 0xF1,
    0x09, 0x89, 0x49, 0xC9, 0x29, 0xA9, 0x69, 0xE9, 0x19, 0x99, 0x59, 0xD9, 0x39, 0xB9, 0x79, 0xF9,
    0x05, 0x85, 0x45, 0xC5, 0x25, 0xA5, 0x65, 0xE5, 0x15, 0x95, 0x55, 0xD5, 0x35, 0xB5, 0x75, 0xF5,
    0x0D, 0x8D, 0x4D, 0xCD, 0x2D, 0xAD, 0x6D, 0xED, 0x1D, 0x9D, 0x5D, 0xDD, 0x3D, 0xBD, 0x7D, 0xFD,
    0x03, 0x83, 0x43, 0xC3, 0x23, 0xA3, 0x63, 0xE3, 0x13, 0x93, 0x53, 0xD3, 0x33, 0xB3, 0x73, 0xF3,
    0x0B, 0x8B, 0x4B, 0xCB, 0x2B, 0xAB, 0x6B, 0xEB, 0x1B, 0x9B, 0x5B, 0xDB, 0x3B, 0xBB, 0x7B, 0xFB,
    0x07, 0x87, 0x47, 0xC7, 0x27, 0xA7, 0x67, 0xE7, 0x17, 0x97, 0x57, 0xD7, 0x37, 0xB7, 0x77, 0xF7,
    0x0F, 0x8F, 0x4F, 0xCF, 0x2F, 0xAF, 0x6F, 0xEF, 0x1F, 0x9F, 0x5F, 0xDF, 0x3F, 0xBF, 0x7F, 0xFF,
};

void vp6_shim_log(int level, const char *fmt, ...)
{
    if (level > AV_LOG_WARNING)
        return; /* skip INFO/DEBUG chatter, keep the errors/warnings that matter */

    FILE *f = fopen("sdmc:/nfshp2_debug.txt", "a");
    if (!f)
        return;
    va_list ap;
    va_start(ap, fmt);
    fprintf(f, "[vp6] ");
    vfprintf(f, fmt, ap);
    va_end(ap);
    fclose(f);
}

AVFrame *av_frame_alloc(void)
{
    return (AVFrame *)calloc(1, sizeof(AVFrame));
}

static void free_planes(AVFrame *f)
{
    int i;
    for (i = 0; i < 4; i++) {
        free(f->base_alloc[i]);
        f->base_alloc[i] = NULL;
        f->data[i] = NULL;
        f->linesize[i] = 0;
        f->plane_h[i] = 0;
    }
}

void av_frame_unref(AVFrame *frame)
{
    if (!frame)
        return;
    free_planes(frame);
    frame->width = frame->height = 0;
    frame->flags = 0;
    frame->pict_type = AV_PICTURE_TYPE_NONE;
    frame->border = 0;
}

void av_frame_free(AVFrame **frame)
{
    if (!frame || !*frame)
        return;
    av_frame_unref(*frame);
    free(*frame);
    *frame = NULL;
}

static int deep_copy(AVFrame *dst, const AVFrame *src)
{
    int i;
    av_frame_unref(dst);
    if (!src->data[0]) {
        dst->width = src->width;
        dst->height = src->height;
        dst->flags = src->flags;
        dst->pict_type = src->pict_type;
        return 0;
    }
    for (i = 0; i < 4; i++) {
        size_t total;
        if (!src->base_alloc[i])
            continue;
        total = (size_t)src->linesize[i] * (size_t)src->plane_h[i];
        dst->base_alloc[i] = (uint8_t *)malloc(total);
        if (!dst->base_alloc[i]) {
            free_planes(dst);
            return AVERROR(ENOMEM);
        }
        memcpy(dst->base_alloc[i], src->base_alloc[i], total);
        dst->linesize[i] = src->linesize[i];
        dst->plane_h[i] = src->plane_h[i];
        dst->data[i] = dst->base_alloc[i] +
                       (src->data[i] - src->base_alloc[i]);
    }
    dst->border = src->border;
    dst->width = src->width;
    dst->height = src->height;
    dst->flags = src->flags;
    dst->pict_type = src->pict_type;
    return 0;
}

int av_frame_ref(AVFrame *dst, const AVFrame *src)
{
    return deep_copy(dst, (AVFrame *)src);
}

int av_frame_replace(AVFrame *dst, const AVFrame *src)
{
    return deep_copy(dst, (AVFrame *)src);
}

int ff_set_dimensions(AVCodecContext *avctx, int width, int height)
{
    avctx->width = avctx->coded_width = width;
    avctx->height = avctx->coded_height = height;
    return 0;
}

int ff_get_buffer(AVCodecContext *avctx, AVFrame *frame, int flags)
{
    int i;
    int border = VP6_BORDER;
    int plane_w[4], plane_h_unpadded[4];
    (void)flags;

    /* vp56.c sets AV_FRAME_FLAG_KEY on this same frame object in
     * parse_header (and again for VP56_SIZE_CHANGE) before calling us --
     * av_frame_unref() must not wipe that back out, or every "no explicit
     * update" probability-model entry in vp6_parse_coeff_models() silently
     * falls through to neither branch and is left at its zeroed default
     * instead of the real 128 fallback, corrupting the coefficient models
     * for the whole frame. */
    int saved_flags = frame->flags;
    av_frame_unref(frame);
    frame->flags = saved_flags;

    plane_w[0] = plane_w[3] = avctx->coded_width;
    plane_h_unpadded[0] = plane_h_unpadded[3] = avctx->coded_height;
    plane_w[1] = plane_w[2] = avctx->coded_width / 2;
    plane_h_unpadded[1] = plane_h_unpadded[2] = avctx->coded_height / 2;

    int nplanes = (avctx->pix_fmt == AV_PIX_FMT_YUVA420P) ? 4 : 3;

    for (i = 0; i < nplanes; i++) {
        int stride = plane_w[i] + 2 * border;
        int padded_h = plane_h_unpadded[i] + 2 * border;
        size_t total = (size_t)stride * (size_t)padded_h;

        frame->base_alloc[i] = (uint8_t *)calloc(1, total);
        if (!frame->base_alloc[i]) {
            free_planes(frame);
            return AVERROR(ENOMEM);
        }
        frame->linesize[i] = stride;
        frame->plane_h[i] = padded_h;
        frame->data[i] = frame->base_alloc[i] + (size_t)border * stride + border;
    }

    frame->border = border;
    frame->width = avctx->width;
    frame->height = avctx->height;
    return 0;
}
