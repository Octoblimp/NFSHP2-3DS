#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "texpack.h"

// A texture pack read from the SD card a texture at a time, rather than held
// in memory whole.
//
// texpack.c takes a buffer and expects the entire pack to be in it. That is
// right for the UI bundles -- FRONTB.BUN is one file the frontend needs all
// of -- and wrong for CARS\TEXTURES.BIN, which is 15,300,536 bytes of which
// a single car uses about 400 KB. The port already holds FRONTB.BUN,
// GLOBALB.BUN and INGAMEB.BUN resident, which is 17.6 MB before any geometry
// exists at all, so a second 15 MB is not available on an Old3DS.
//
// What is actually needed to find a texture is the 0x30300003 info table:
// 772 records of 164 bytes, 126,608 bytes for the whole car set. That is
// resident here. The 0x30300004 pixel blob stays on the card and the two
// ranges one texture needs -- its mip level and its CLUT -- are read into a
// staging buffer at upload time and freed again.
//
// The decode itself is still texpack.c's, unchanged: texsrc_upload() stages
// the bytes, rewrites the offsets in a *copy* of the TexInfo to point into
// the staging buffer, and calls texpack_upload(). Nothing about the format
// is re-implemented here, so tools/src/texpack_test.c still covers it.

#define TEXSRC_MAX_PACKS 4
#define TEXSRC_MAX_PATH  256

typedef struct {
    uint8_t* info;        // the 0x30300003 payload, resident
    uint32_t infoSize;
    uint32_t count;       // infoSize / TEXPACK_RECORD_SIZE
    long     dataOff;     // file offset of the 0x30300004 payload, 128-aligned
    uint32_t dataSize;    // bytes left after that alignment
    char     name[20];    // from 0x30300002: "CARTEXTURES", "GLOBAL", ...
} TexSrcPack;

typedef struct {
    FILE*      fp;
    TexSrcPack pack[TEXSRC_MAX_PACKS];
    int        numPacks;
    char       path[TEXSRC_MAX_PATH];
} TexSource;

// One texture, found. `info.record` points into the source's resident info
// table, so it is valid until texsrc_close().
typedef struct {
    int     pack;
    TexInfo info;
} TexSrcEntry;

// Opens `path` and indexes every 0xb0300001 in it, reading each one's info
// table into memory. False if the file will not open or holds no pack.
bool texsrc_open(TexSource* ts, const char* path);
void texsrc_close(TexSource* ts);

// First pack, in file order, whose table holds `hash`. False if none does --
// which is not an error: 13 of the 142 texture hashes the car geometry
// refers to are in no pack on the disc at all. See docs/formats/
// solid-geometry.md.
bool texsrc_find(const TexSource* ts, uint32_t hash, TexSrcEntry* out);

// How many textures the source can reach, across all its packs.
uint32_t texsrc_count(const TexSource* ts);

// Walks every pack's table in order, so a caller can enumerate without
// knowing a hash. False past the end.
bool texsrc_at(const TexSource* ts, uint32_t index, TexSrcEntry* out);

// Reads the two ranges mip level `level` of `e` needs -- levels 0..level of
// its pixels, and its CLUT -- into one freshly allocated buffer, and hands
// back a TexPack and a TexInfo that address that buffer instead of the file.
// The pair can then be passed straight to texpack_decode() or
// texpack_upload(); the caller frees *outStage afterwards.
//
// This is the whole of what streaming adds, and it is deliberately free of
// <3ds.h> so that tools/src/texsrc_test.c can decode a pack both ways on the
// host -- through this and through a whole-file texpack_open() -- and compare
// the pixels. The seek arithmetic and the 128-byte data alignment are the
// parts that can silently roll a texture sideways, and that test is what
// stops them.
bool texsrc_stage(TexSource* ts, const TexSrcEntry* e, int level,
                  uint8_t** outStage, TexPack* outPack, TexInfo* outInfo);

#ifdef __3DS__
#include <citro3d.h>

// texsrc_stage() followed by texpack_upload(), which pads to a power of two.
// The texture belongs to the caller (C3D_TexDelete).
bool texsrc_upload(TexSource* ts, const TexSrcEntry* e, int level,
                   C3D_Tex* out);
#endif
