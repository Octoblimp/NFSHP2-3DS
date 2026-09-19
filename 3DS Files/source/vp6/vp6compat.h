/*
 * vp6compat.h -- minimal, purpose-built compatibility shim standing in for
 * FFmpeg's libavutil/libavcodec framework headers (avcodec.h, decode.h,
 * codec_internal.h, bytestream.h, libavutil headers, config.h) so that the
 * vendored FFmpeg VP5/VP6 decoder source files (vp56.c, vp6.c, vlc.c,
 * huffman.c, vp3dsp.c, hpeldsp.c, h264chroma.c, videodsp.c, vp6dsp.c,
 * vpx_rac.c and their headers) can be compiled standalone for the 3DS
 * (devkitARM / armv6k, no threads, single VP6 stream, no hwaccel).
 *
 * Only the exact symbol surface actually referenced by those files is
 * provided here -- this is NOT a general libavutil/libavcodec replacement.
 *
 * AVFrame/AVPacket refcounting is intentionally simplified to plain deep
 * copies (no atomic refcounts, no buffer pools) since we only ever decode
 * one VP6 stream at a time, single-threaded. This changes performance
 * characteristics but not decoded pixel output.
 */
#ifndef VP6COMPAT_H
#define VP6COMPAT_H

#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <errno.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---------------------------------------------------------------------
 * Attributes / inline helpers
 * --------------------------------------------------------------------- */
#define av_always_inline __attribute__((always_inline)) inline
#define av_unused        __attribute__((unused))
#define av_cold
#define av_const
#define av_noinline      __attribute__((noinline))
#define DECLARE_ALIGNED(n, t, v) t __attribute__((aligned(n))) v

#define av_builtin_constant_p(x) __builtin_constant_p(x)

#define ARCH_ARM 0
#define ARCH_X86 0
#define HAVE_FAST_64BIT 0
#define CONFIG_SAFE_BITSTREAM_READER 0

/* ---------------------------------------------------------------------
 * Basic min/max/clip/array macros (libavutil/common.h subset)
 * --------------------------------------------------------------------- */
#define FFMIN(a,b) ((a) > (b) ? (b) : (a))
#define FFMIN3(a,b,c) FFMIN(FFMIN(a,b),c)
#define FFMAX(a,b) ((a) > (b) ? (a) : (b))
#define FFMAX3(a,b,c) FFMAX(FFMAX(a,b),c)
#define FFABS(a) ((a) >= 0 ? (a) : (-(a)))
#define FFSIGN(a) ((a) > 0 ? 1 : -1)
#define FFSWAP(type,a,b) do{type SWAP_tmp= b; b= a; a= SWAP_tmp;}while(0)
#define FFALIGN(x, a) (((x)+(a)-1)&~((a)-1))
#define FF_ARRAY_ELEMS(a) (sizeof(a) / sizeof((a)[0]))

static av_always_inline int av_clip(int a, int amin, int amax)
{
    if (a < amin) return amin;
    if (a > amax) return amax;
    return a;
}
static av_always_inline int av_clip_uint8(int a)
{
    if (a & (~0xFF)) return (-a) >> 31 & 0xFF;
    return a;
}
static av_always_inline int av_clip_int8(int a)
{
    if ((a + 0x80) & ~0xFF) return (a >> 31) ^ 0x7F;
    return a;
}
static av_always_inline unsigned av_clip_uintp2(int a, int p)
{
    if (a & ~((1 << p) - 1)) return (~a) >> 31 & ((1 << p) - 1);
    return a;
}

static av_always_inline int sign_extend(int val, int bits)
{
    int shift = (int)(sizeof(int) * 8 - bits);
    union { unsigned u; int s; } v = { (unsigned) val << shift };
    return v.s >> shift;
}
static av_always_inline int64_t sign_extend64(int64_t val, int bits)
{
    int shift = (int)(sizeof(int64_t) * 8 - bits);
    union { uint64_t u; int64_t s; } v = { (uint64_t) val << shift };
    return v.s >> shift;
}
/* libavutil/common.h: rounding right-shift-by-1 (used for MV rounding). */
#define RSHIFT(a,b) ((a) > 0 ? ((a) + ((1<<(b))>>1))>>(b) : ((a) + ((1<<(b))>>1)-1)>>(b))
static av_always_inline unsigned zero_extend(unsigned val, unsigned bits)
{
    return (val << (32 - bits)) >> (32 - bits);
}
#define NEG_USR32(a,s) (((uint32_t)(a))>>(32-(s)))
#define NEG_SSR32(a,s) (((int32_t) (a))>>(32-(s)))

/* libavcodec/mathops.h's overflow-safe-multiply helper type: plain unsigned
 * int is the generic (non-arch-specific) definition ffmpeg itself falls
 * back to when no CPU-specific mathops.h overrides it. */
#define SUINT unsigned

/* ---------------------------------------------------------------------
 * Unaligned memory access helpers (libavutil/intreadwrite.h subset)
 * --------------------------------------------------------------------- */
static av_always_inline uint16_t AV_RB16(const void *p)
{
    const uint8_t *a = (const uint8_t *)p;
    return (uint16_t)((a[0] << 8) | a[1]);
}
static av_always_inline uint32_t AV_RB24(const void *p)
{
    const uint8_t *a = (const uint8_t *)p;
    return ((uint32_t)a[0] << 16) | (a[1] << 8) | a[2];
}
static av_always_inline uint32_t AV_RB32(const void *p)
{
    const uint8_t *a = (const uint8_t *)p;
    return ((uint32_t)a[0] << 24) | ((uint32_t)a[1] << 16) | (a[2] << 8) | a[3];
}
static av_always_inline uint16_t AV_RL16(const void *p)
{
    const uint8_t *a = (const uint8_t *)p;
    return (uint16_t)(a[0] | (a[1] << 8));
}
static av_always_inline uint32_t AV_RL32(const void *p)
{
    const uint8_t *a = (const uint8_t *)p;
    return (uint32_t)a[0] | ((uint32_t)a[1] << 8) | ((uint32_t)a[2] << 16) | ((uint32_t)a[3] << 24);
}
static av_always_inline uint32_t AV_RN16(const void *p) { uint16_t v; memcpy(&v, p, 2); return v; }
static av_always_inline uint32_t AV_RN32(const void *p) { uint32_t v; memcpy(&v, p, 4); return v; }
static av_always_inline uint64_t AV_RN64(const void *p) { uint64_t v; memcpy(&v, p, 8); return v; }
#define AV_RN32A AV_RN32
#define AV_RN64A AV_RN64
static av_always_inline void AV_WN16(void *p, uint16_t v) { memcpy(p, &v, 2); }
static av_always_inline void AV_WN32(void *p, uint32_t v) { memcpy(p, &v, 4); }
static av_always_inline void AV_WN64(void *p, uint64_t v) { memcpy(p, &v, 8); }
#define AV_WN32A AV_WN32
#define AV_WN64A AV_WN64
#define AV_COPY64(d,s) memcpy(d,s,8)

static av_always_inline unsigned bytestream_get_be16(const uint8_t **b)
{
    unsigned v = AV_RB16(*b); *b += 2; return v;
}
static av_always_inline unsigned bytestream_get_be24(const uint8_t **b)
{
    unsigned v = AV_RB24(*b); *b += 3; return v;
}

/* ---------------------------------------------------------------------
 * Error codes / logging (libavutil/error.h, libavutil/log.h subset)
 * --------------------------------------------------------------------- */
#define AVERROR(e) (-(e))
#define AVERROR_INVALIDDATA (-1000001)
#define AVERROR_PATCHWELCOME (-1000002)

#define AV_LOG_ERROR   16
#define AV_LOG_WARNING 24
#define AV_LOG_INFO    32
#define AV_LOG_DEBUG   48

void vp6_shim_log(int level, const char *fmt, ...);
#define av_log(avctx, level, ...) vp6_shim_log(level, __VA_ARGS__)

#define av_assert0(cond) do { if (!(cond)) { vp6_shim_log(AV_LOG_ERROR, "assert failed: %s\n", #cond); } } while (0)
#define av_assert1(cond) ((void)0)
#define av_assert2(cond) ((void)0)

/* ---------------------------------------------------------------------
 * Memory allocation (libavutil/mem.h subset)
 * --------------------------------------------------------------------- */
static av_always_inline void *av_malloc(size_t size) { return malloc(size ? size : 1); }
static av_always_inline void *av_mallocz(size_t size) { return calloc(1, size ? size : 1); }
static av_always_inline void *av_malloc_array(size_t n, size_t s) { size_t t = n * s; return malloc(t ? t : 1); }
static av_always_inline void *av_mallocz_array(size_t n, size_t s) { return calloc(n ? n : 1, s ? s : 1); }
static av_always_inline void  av_free(void *p) { free(p); }
static av_always_inline void  av_freep(void *p)
{
    void **pp = (void **)p;
    free(*pp);
    *pp = NULL;
}
static av_always_inline void *av_realloc(void *p, size_t size) { return realloc(p, size ? size : 1); }
static av_always_inline int av_reallocp_array(void *pptr, size_t nmemb, size_t size)
{
    void **p = (void **)pptr;
    void *r;
    if (nmemb == 0 || size == 0) { free(*p); *p = NULL; return 0; }
    r = realloc(*p, nmemb * size);
    if (!r) return AVERROR(ENOMEM);
    *p = r;
    return 0;
}

/* av_realloc_f: grows *ptr geometrically (like real ffmpeg's av_fast_realloc
 * family) until it holds at least min_size elements of elem_size bytes;
 * returns the (possibly reallocated) pointer, or NULL on failure (leaving
 * the original block untouched, matching ffmpeg's av_realloc_f contract). */
static av_always_inline void *av_realloc_f(void *ptr, size_t nelem, size_t elsize)
{
    size_t size = nelem * elsize;
    void *r;
    if (elsize == 0 || nelem == 0)
        size = 0;
    r = realloc(ptr, size ? size : 1);
    if (!r && size)
        free(ptr);
    return r;
}

#define AV_QSORT(p, num, type, cmp) qsort((p), (num), sizeof(type), (int(*)(const void*,const void*))(cmp))

/* Bit-reversal table (real ffmpeg's ff_reverse, libavcodec/mathtables.c) --
 * ff_reverse[x] reverses the bit order of byte x. Defined in vp6compat.c. */
extern const uint8_t ff_reverse[256];

/* Debug-only tracing macros (no-ops here; vlc.c calls these purely for
 * diagnostic logging that has no effect on decoded output). */
#define ff_dlog(ctx, ...) do { } while (0)
#define ff_tlog(ctx, ...) do { } while (0)

static av_always_inline void avpriv_request_sample(void *avc, const char *fmt, ...) { (void)avc; (void)fmt; }

#define av_unreachable(msg) do { } while (0)

/* ---------------------------------------------------------------------
 * AVCodecContext / AVFrame / AVPacket (minimal subset actually used)
 * --------------------------------------------------------------------- */
enum AVPixelFormat {
    AV_PIX_FMT_NONE = -1,
    AV_PIX_FMT_YUV420P,
    AV_PIX_FMT_YUVA420P,
};

enum AVCodecID {
    AV_CODEC_ID_NONE = 0,
    AV_CODEC_ID_VP5,
    AV_CODEC_ID_VP6,
    AV_CODEC_ID_VP6F,
    AV_CODEC_ID_VP6A,
};

enum AVPictureType {
    AV_PICTURE_TYPE_NONE = 0,
    AV_PICTURE_TYPE_I,
    AV_PICTURE_TYPE_P,
};

#define AV_FRAME_FLAG_KEY         (1 << 0)
#define AV_FRAME_FLAG_INTERLACED  (1 << 1)

#define AV_GET_BUFFER_FLAG_REF 1

#define AVDISCARD_NONE    -16
#define AVDISCARD_DEFAULT   0
#define AVDISCARD_NONREF     8
#define AVDISCARD_BIONLY    16
#define AVDISCARD_NONKEY     32
#define AVDISCARD_ALL        48

typedef struct AVCodecDesc { enum AVCodecID id; } AVCodecDesc;

typedef struct AVCodecContext {
    void *priv_data;

    int width, height;
    int coded_width, coded_height;
    enum AVPixelFormat pix_fmt;

    int flags;
    int skip_alpha;
    int skip_loop_filter;
    int error_concealment;

    const uint8_t *extradata;
    int extradata_size;

    const AVCodecDesc *codec;
    enum AVCodecID codec_id;

    int (*execute2)(struct AVCodecContext *c,
                     int (*func)(struct AVCodecContext *c2, void *arg, int jobnr, int threadnr),
                     void *arg, int *ret, int count);
} AVCodecContext;

typedef struct AVFrame {
    uint8_t *data[4];
    int      linesize[4];
    uint8_t *base_alloc[4]; /* real malloc'd base pointer for each plane (data[] is offset into it by border) */
    int      plane_h[4];    /* allocated (padded) height of each plane's base_alloc buffer */
    int      border;        /* pixels of padding on every side of each plane, for edge-safe MC */
    int width, height;
    int flags;
    enum AVPictureType pict_type;
} AVFrame;

typedef struct AVPacket {
    const uint8_t *data;
    int size;
} AVPacket;

AVFrame *av_frame_alloc(void);
void     av_frame_free(AVFrame **frame);
void     av_frame_unref(AVFrame *frame);
int      av_frame_ref(AVFrame *dst, const AVFrame *src);
int      av_frame_replace(AVFrame *dst, const AVFrame *src);

int  ff_get_buffer(AVCodecContext *avctx, AVFrame *frame, int flags);
int  ff_set_dimensions(AVCodecContext *avctx, int width, int height);

/* ---------------------------------------------------------------------
 * defs.h subset
 * --------------------------------------------------------------------- */
#define AV_INPUT_BUFFER_PADDING_SIZE 64

/* Standard JPEG/MPEG zig-zag scan order, referenced by vp56.c to build its
 * IDCT scan table (transposed). Defined in vp6compat.c. */
extern const uint8_t ff_zigzag_direct[64];

#ifdef __cplusplus
}
#endif

#endif /* VP6COMPAT_H */
