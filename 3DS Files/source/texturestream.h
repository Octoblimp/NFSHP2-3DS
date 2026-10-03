// texturestream -- TexturePack.obj's streaming half, retail's 0x001ac608
// .. 0x001ad048, with the read's bridge (0x001ad608) and
// ~LoadedTextureData (0x001ad610). The demo has the same code at
// 0x001a1f00 .. 0x001a28c0; the port follows retail, whose TexturePack
// fields sit 16 bytes on from the demo's (texturepack.h).
//
// A streamed pack is a TexturePack made with no file name, whose table
// comes from a file rather than from a bundle: LoadTextureTableFromFile
// reads the start of a texture-pack file -- the 0xb0300001 chunk's header
// and table -- copies the table out, and keeps where the blob's pixels
// start. Nothing is in memory until it is asked for. LoadGlobalChunks
// makes three: DynTextures over GLOBAL\DYNTEX.BIN, HudTextures over
// GLOBAL\HUDTEX.BIN and CarTextures over CARS\TEXTURES.BIN; retail's
// SelectTrackSlideshow makes a fourth.
//
// Asking for a texture asks for two ranges of the blob, its pixels and
// its palette. Each range lands in a LoadedTextureData: one that already
// holds it counts one more user; one not read yet that it ends within
// 1 KB before, or starts within 1 KB after, grows to take it, and then
// takes in a second such neighbour if it now reaches one; otherwise a new
// one goes on the list, which is sorted by where each starts. One range
// is read at a time, through QueuedFile, into a block of its own, and
// when it is in, every record of the pack whose pixels or palette lie in
// it is pointed there and eFixUpTables runs. LoadTexturesFromFile's
// callback rides the list as an empty range, after the ranges it asked
// for, and is called when the reads reach it. A range whose last user
// lets go is freed, its records cleared, once it is not being read.
//
// Retail's own oddities, kept:
//   * a callback's empty range leaves NumNotYetLoadedTextureDatas one
//     more than when the service started, not one less;
//   * the empty range is not exempt from the neighbour search, so a range
//     asked for at most 1 KB into the blob while a callback waits can grow
//     the empty range into a real one, and that callback is never called;
//     and the second neighbour a range takes in loses its callback;
//   * the sort leaves a callback's range where it is, and never compares
//     the ranges either side of it, so a callback still waits for exactly
//     the ranges asked for before it.
//
// Not here: PrintNameHashes (0x001acbd8) and PrintLoadedTextureData
// (0x001acc30), whose prints are compiled out and which nothing calls;
// and StreamingTexturePack (0x001ad048 .. 0x001ad450), whose Init nothing
// calls.
//
// Cross-check: tools/texturestream_check.py. Write-up:
// docs/formats/texture-streaming.md.

#ifndef TEXTURESTREAM_H
#define TEXTURESTREAM_H

#include <stdint.h>

#include "texturepack.h"

// gp-21432, gp-21428 and gp-21436: the three packs LoadGlobalChunks makes.
// pHudTexturePack is trackflow.h's, pCarTexturePack carloader.h's.
extern TexturePack *pDynamicTexturePack;

// LoadTextureTableFromFile(const char *), 0x001ac608. The file name into
// Filename, where every read of the pack's pixels goes; then, if the file
// opens, its first 128 KB at most. When the header and the table lie in
// that, the table is copied out and attached, TextureDataFilePos is where
// the blob's payload starts (rounded up to 128) and
// pTextureInfoNeedsToBeFreed is set. Either way the read is freed.
void texturepack_load_texture_table_from_file(TexturePack *p,
                                              const char *filename);

// FindLoadedTextureData(int, int), 0x001ac780: the first range that holds
// [pos, pos+size), read or not.
LoadedTextureData *texturepack_find_loaded_texture_data(TexturePack *p,
                                                        int32_t pos,
                                                        int32_t size);

// FindNotYetLoadedNeighbourTextureData(int, int, int), 0x001ac7d0: the
// first range with no block yet that [pos, pos+size) ends within 1 KB
// before or starts within 1 KB after. The third int is never read.
LoadedTextureData *texturepack_find_not_yet_loaded_neighbour_texture_data(
    TexturePack *p, int32_t pos, int32_t size);

// AddLoadedTextureData(int, int), 0x001ac880, and
// RemoveLoadedTextureData(int, int), 0x001aca30: a user more or less of
// [pos, pos+size). Remove answers 0 when no range holds it, else 1.
void texturepack_add_loaded_texture_data(TexturePack *p, int32_t pos,
                                         int32_t size);
int32_t texturepack_remove_loaded_texture_data(TexturePack *p, int32_t pos,
                                               int32_t size);

// DeleteLoadedTextureData(LoadedTextureData *), 0x001aca88: the range's
// records cleared if it was read, else one fewer waiting; then, once
// rendering is done, off the list and freed with its block.
void texturepack_delete_loaded_texture_data(TexturePack *p,
                                            LoadedTextureData *d);

// LoadTextureFromFile(TextureInfo *), 0x001acaf8, and
// UnloadTextureFromFile, 0x001acb68: a user more or less of the record's
// pixels and of its palette, each that has a size.
void texturepack_load_texture_from_file(TexturePack *p, TextureInfo *t);
void texturepack_unload_texture_from_file(TexturePack *p, TextureInfo *t);

// LoadTexturesFromFile(unsigned int *, int, void (*)(int), int),
// 0x001acc98: each named texture of the pack asked for (a 0 hash, or one
// the pack does not have, is passed over); with `cb`, an empty range that
// calls it with `param` once the ranges before it are in; then the
// service. UnloadTexturesFromFile(unsigned int *, int), 0x001acd90: each
// let go. The signatures are carloader.h's two seams'.
void texturepack_load_textures_from_file(TexturePack *p, uint32_t *hashes,
                                         int n, LoadedTextureDataCallback cb,
                                         intptr_t param);
void texturepack_unload_textures_from_file(TexturePack *p, uint32_t *hashes,
                                           int n);

// ServiceLoadingTextures(), 0x001ace00: with nothing being read and
// something waiting, the first range on the list with no block: an empty
// one is taken off and its callback called, and the service runs again; a
// real one gets its block and its read queued.
void texturepack_service_loading_textures(TexturePack *p);

// ReadCallback(int), 0x001acf28, which QueuedFile reaches through
// 0x001ad608 with the pack as its parameter: the range read is assigned,
// marked read, eFixUpTables runs, the range is deleted if no one wants it
// now, and the service runs again. A failed read is assigned the same.
void texturepack_read_callback(TexturePack *p, int32_t error);

// UnloadAllTexturesFromFile(), 0x001acf98: every range's users gone, every
// range not being read deleted, and nothing waiting.
void texturepack_unload_all_textures_from_file(TexturePack *p);

// GetLoadedSize(), 0x001ad008: the ranges' lengths, read or not.
int32_t texturepack_get_loaded_size(TexturePack *p);

#endif
