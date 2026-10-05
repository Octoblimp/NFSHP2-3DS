// frontres -- FRONTB.BUN's engine half: the ResourceFile load that
// BeginGameFlowLoadingFrontend asks for, and its unload.
//
// The device reads FRONTB once, at boot, for the UI (main.c's addBundle),
// and holds it resident. Retail's frontend load puts the whole file
// through LoadChunks and PostLoadFixup before its callback runs, and its
// BeginGameFlowUnloadingFrontEnd hands it back through UnloadChunks,
// newest chunk first, and PostLoadFixup again. These are those two, over
// the UI's copy:
//
//   * the solid list, 0x80034000 at offset 0 -- PLATFORM, the fifteen
//     TRACK*_MINI and CARCOVER. loader_solid_list fixes its tables up in
//     place, which cannot be done twice, so each load takes a fresh copy
//     of the chunk, at the same offset mod 128, and the unload frees it;
//   * the texture pack and the anim pack, loaded in place, as INGAMEB's
//     are for the race: loader_texture_pack only points the records at
//     their pixels;
//   * the Flailer chunk, the two event trees and the four fonts, whose
//     slots are not ported and do nothing: the UI already has them.
//
// Written up in docs/formats/car-select.md, "The draw on the device".

#ifndef FRONTRES_H
#define FRONTRES_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// LoadChunks over FRONTB's `len` bytes at `data`, which stay the
// caller's and must outlive frontres_unload, then PostLoadFixup. False,
// and nothing loaded, when there is no room for the solid list's copy.
// A second call before frontres_unload does nothing.
bool frontres_load(uint8_t *data, size_t len);

// UnloadChunks over the same chunks, newest first, then PostLoadFixup;
// the solid list's copy is freed. Nothing when nothing is loaded.
void frontres_unload(void);

// Whether FRONTB's chunks are loaded.
bool frontres_loaded(void);

#endif
