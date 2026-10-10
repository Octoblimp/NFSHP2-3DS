// bfile -- bWare's file calls, the ones QueuedFile, ResourceFile and the
// streamed texture packs make.
//
//   bOpen(const char *)                                  0x002544c0
//   bClose(bFile *)                                      0x002544e8
//   bFileSize(bFile *)                                   0x00254550
//   bFileSize(const char *)                              0x00254568
//   bReadAsync(bFile *, void *, int, void (*)(bFile *, int), int)
//                                                        0x002546e8
//   bRead(bFile *, void *, int)                          0x002547f0
//   bSeek(bFile *, int, int)                             0x00254830
//   bServiceFileSystem()                                 0x002539b8
//
// Those are retail's addresses; the demo's are 0x0023c2a8, 0x0023c2d0,
// 0x0023c338, 0x0023c350, 0x0023c4b0, 0x0023c5b8, 0x0023c5f8 and
// 0x0023b790, all the same code. The image's are the PS2's: a name looked
// up in ZDIR.BIN and read out of ZZDATA.BIN by the IOP, and a read's
// callback run from bServiceFileSystem once the IOP says it is done. None
// of that is ported. The port's are port-only, over stdio and the
// extracted tree on the SD card (gamedata.h): a name is the disc's,
// `GLOBAL\INGAMEB.LZC`, with its backslashes turned to slashes.
//
// What the callers rely on is kept:
//   * a missing file is a NULL bOpen and a negative bFileSize(name);
//   * bReadAsync never calls back before it returns. The port reads at
//     once and keeps the callback for the next bServiceFileSystem, so a
//     queued read is in the frame after the one that started it, as the
//     earliest a read finishes on the console;
//   * bClose straight after bReadAsync, which BeginRead does, does not
//     lose the read.

#ifndef BFILE_H
#define BFILE_H

#include <stdint.h>

typedef struct bFile bFile;

// A read's completion: the file and the parameter bReadAsync was given.
// The file may already be closed, and only its address is passed.
typedef void (*bFileCallback)(bFile *f, intptr_t param);

bFile  *bOpen(const char *name);
void    bClose(bFile *f);
int32_t bFileSize(bFile *f);
// -1 for a file that is not there.
int32_t bFileSizeName(const char *name);
// SEEK_SET, SEEK_CUR or SEEK_END's numbers: 0, 1, 2.
void    bSeek(bFile *f, int32_t pos, int32_t whence);
void    bReadAsync(bFile *f, void *buf, int32_t n, bFileCallback cb,
                   intptr_t param);
// bRead(bFile *, void *, int), 0x002547f0 (the demo's 0x0023c5b8):
// bReadAsync with no callback, then a wait on bIsAsyncDone. The port's
// read is in when bReadAsync returns.
void    bRead(bFile *f, void *buf, int32_t n);
void    bServiceFileSystem(void);

// bGetFile(const char *, int *, int), 0x00254908: the whole file in a
// block of its own, bMalloc(size, name, 0, pool | 0x40), with the size to
// *size unless that is NULL. Retail asserts on a file that is not there
// (bfile.cpp, line 831) and the game stops; the port's says which file to
// stderr and aborts.
void   *bGetFile(const char *name, int32_t *size, int32_t pool);

#endif
