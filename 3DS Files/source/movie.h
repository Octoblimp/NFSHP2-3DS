#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

// Plays the `.M3V` sequences `tools/movie_bake.py` writes.
//
// This is not an MV3 decoder. MV3 is about 5,000 instructions of fixed-point
// IDCT, motion compensation and a prefix-coded entropy layer -- all of it read
// off `NFSHP2.ELF` and written up in `docs/formats/mv3-video.md` -- and there
// is exactly one movie on the disc that uses it: `MOVIES\INTRO\EALOGO_EN.AVI`,
// 512x256, 30 fps, 90 frames, three seconds of EA logo. Porting the codec to
// the 3DS to replay three seconds is the wrong trade, so the port decodes the
// movie once on the host (`tools/video_extract.py`, which runs the PS2's own
// decoder under an emulator) and bakes the result into a format the console
// can stream with no per-pixel work:
//
//   * RGB565 already in the PICA200's 8x8 Morton tile order, so a frame lands
//     in `C3D_Tex::data` by memcpy rather than by a swizzling loop;
//   * a changed-tile bitmap per frame, because the logo sits on a black field
//     and most tiles do not move;
//   * RLE16 over the changed tiles, runs allowed to cross tile boundaries.
//
// The consequence, and the reason the title sequence is the only caller: a
// delta frame is meaningless without every frame before it, so an `.M3V` plays
// forwards from the start and does not seek. `TitleScreen` never asks for
// anything else.
//
// Nothing here includes <3ds.h> except the clearly-marked block at the end, so
// the decoder builds and is tested on the host -- see `tools/src/movie_test.c`
// and `tools/movie_check.py`.

#define M3V_MAGIC       0x3156334DU   // "M3V1", little-endian
#define M3V_HEADER_SIZE 0x30
#define M3V_TILE        8
#define M3V_TILE_PIXELS (M3V_TILE * M3V_TILE)

// The only format the baker emits. Anything else is a file from the future.
#define M3V_FMT_RGB565_TILED 0

typedef struct {
    uint16_t width, height;
    uint16_t frames, fps;
    uint16_t format, tileBytes;
    uint32_t maxFrameLen;
    uint32_t frameTableOff;
    uint32_t audioOff, audioLen, audioRate;
    uint16_t audioChannels, audioBits;
} M3VInfo;

typedef struct {
    FILE*     file;
    M3VInfo   info;
    uint32_t* table;       // frames x { offset, length }
    uint8_t*  frameBuf;    // maxFrameLen bytes
    uint16_t* surface;     // width * height u16, in tile order
    bool      ownSurface;
    uint32_t  numTiles;
    uint32_t  nextFrame;   // the frame m3v_next() will decode
    float     clock;       // seconds of playback consumed
} M3VMovie;

// Reads `path`'s header and frame table. `surface` is where frames are
// decoded to; pass the texture's data pointer to decode straight into VRAM,
// or NULL to have the movie allocate width*height*2 bytes of its own.
// It must hold width*height u16 whichever way.
bool m3v_open(M3VMovie* m, const char* path, uint16_t* surface);
void m3v_close(M3VMovie* m);

// Decodes the next frame into the surface. False at the end of the movie, or
// on a malformed payload -- which is also the end, since deltas chain.
bool m3v_next(M3VMovie* m);

// Advances the movie by `dt` seconds, decoding however many frames that is
// (dropping none: a slow frame catches up). Returns true once the last frame
// has been shown and the movie's running time has elapsed, which is what
// `DriveMovie` (0x0016a060) returns 1 for.
bool m3v_drive(M3VMovie* m, float dt);

bool m3v_finished(const M3VMovie* m);

// Total running time in seconds, frames / fps.
float m3v_duration(const M3VMovie* m);

// Reads the header out of a M3V_HEADER_SIZE-byte buffer. Exposed for the
// host test; m3v_open() uses it.
bool m3v_parse_header(const uint8_t* buf, size_t len, M3VInfo* out);

// Applies one frame payload to `surface` in place. `numTiles` is
// (width/8) * (height/8). Exposed for the host test.
bool m3v_apply(const uint8_t* body, size_t len, uint16_t* surface,
               uint32_t numTiles);

// Turns a PS2 movie path from TitleMoviesToPlay -- backslashes, `.AVI` -- into
// the baked file's path inside the data directory: forward slashes, `.M3V`.
// Returns false if it would not fit.
bool m3v_baked_path(const char* ps2Path, char* out, size_t cap);

#ifdef __3DS__
#include <citro3d.h>

// Opens `path` into a freshly created RGB565 texture and decodes frame 0 into
// it. The texture is owned by the player until m3v_tex_close().
bool m3v_tex_open(M3VMovie* m, C3D_Tex* tex, const char* path);
void m3v_tex_close(M3VMovie* m, C3D_Tex* tex);

// m3v_drive() plus the C3D_TexFlush() the GPU needs afterwards.
bool m3v_tex_drive(M3VMovie* m, C3D_Tex* tex, float dt);
#endif
