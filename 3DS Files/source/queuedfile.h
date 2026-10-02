// queuedfile -- retail's QueuedFile (0x001ad6d8 .. 0x001add40), the queue
// of file reads under ResourceFile and the streaming texture packs. The
// code is the demo's (0x001a2f80 .. 0x001a35e8), unchanged.
//
// AddQueuedFile puts a read on the list: so many bytes of a named file,
// from an offset, into a buffer, with a callback for when it is done.
// Each ServiceQueuedFiles services the file system, then looks at the read
// in progress, which is the first file on the list:
//   * done, with every byte read: the file leaves the list and its
//     callback is called with 0;
//   * done, after one block of a larger file: the file stays, WAITING;
//   * done, after AbortQueuedFile asked while it read: it leaves the list
//     with no call;
//   * failed: it leaves the list and its callback is called with 1;
//   * still reading: nothing more this time.
// With no read in progress, the list is sorted by priority, lowest first,
// and its first file starts its next block: BeginRead opens the file,
// checks it is long enough, seeks, and starts one asynchronous read of at
// most BlockSize bytes. A file that will not open, or is too short, is
// failed at once.
//
// Joylog: while it replays, the status comes from the recording rather
// than the read, and a read the recording says is over is waited for;
// otherwise the status is recorded. On a retail console neither happens
// (joylog.h), and the port keeps both calls.
//
// Cross-checked with resource.c by tools/resource_check.py against the
// retail image; written up in docs/formats/resource-file.md.

#ifndef QUEUEDFILE_H
#define QUEUEDFILE_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bslotpool.h"

// QueuedFileStatus.
enum {
    QF_WAITING = 0,
    QF_READING = 1,
    QF_DONE    = 2,
    QF_ERROR   = 3,
};

// A read's completion: the parameter and 1 for a failed read, else 0.
typedef void (*QueuedFileCallback)(intptr_t param, int32_t error);

// QueuedFile, 100 bytes.
typedef struct QueuedFile {
    bNode    Node;                  //  0
    void    *pBuf;                  //  8
    char     Filename[48];          // 12
    int32_t  FilePos;               // 60
    int32_t  NumBytes;              // 64
    int32_t  NumRead;               // 68
    int32_t  BlockSize;             // 72
    int32_t  Priority;              // 76
    QueuedFileCallback Callback;    // 80
    intptr_t CallbackParam;         // 84
    int32_t  Handle;                // 88
    int32_t  Status;                // 92
    int32_t  AbortFlag;             // 96
} QueuedFile;                       // 100

#if UINTPTR_MAX == 0xffffffffu
typedef char queuedfile_layout_check[
    (sizeof(QueuedFile) == 100 && offsetof(QueuedFile, Filename) == 12
     && offsetof(QueuedFile, FilePos) == 60
     && offsetof(QueuedFile, Callback) == 80
     && offsetof(QueuedFile, AbortFlag) == 96) ? 1 : -1];
#endif

// gp-19120, "QueuedFileSlotPool": 16 slots of 100 bytes.
extern BSlotPool *QueuedFileSlotPool;
// gp-19116, QueuedFile::CurrentHandle: the next file's handle, from 1 to
// 100000 and round to 1 again.
extern int32_t QueuedFile_CurrentHandle;
// gp-19112: a read is in progress, on the list's first file.
extern int32_t QueuedFileReadInProgress;
// gp-19104.
extern bNode QueuedFileList;

// _GLOBAL_$I$QueuedFileSlotPool (0x001adc78, the demo's 0x001a3520):
// the list made empty.
void queuedfile_static_init(void);
// _GLOBAL_$D$QueuedFileSlotPool (0x001adc68): every file left on the list
// unlinked and freed, with no callback, as bTList<QueuedFile>'s
// destructor (0x001adbf8) does.
void queuedfile_static_destruct(void);

// InitQueuedFiles (0x001ada10) and CloseQueuedFiles (0x001ada40): the
// pool. InitializeEverything runs the first; nothing runs the second.
void init_queued_files(void);
void close_queued_files(void);

// AddQueuedFile (0x001ada60): the file's handle. Priority 5, and blocks of
// 1 MB, until ChangeQueuedFileParams.
int32_t add_queued_file(void *buf, const char *name, int32_t pos,
                        int32_t num_bytes, QueuedFileCallback cb,
                        intptr_t param);
// ChangeQueuedFileParams (0x001adb08). Nothing for a handle not queued.
void change_queued_file_params(int32_t handle, int32_t priority,
                               int32_t block_size);
// AbortQueuedFile (0x001adb48): 1 when the file is gone (it was waiting,
// or was not queued), 0 when it is reading and will be dropped once the
// read is over.
int32_t abort_queued_file(int32_t handle);
// FindQueuedFile (0x001ad9d8).
QueuedFile *find_queued_file(int32_t handle);
// ServiceQueuedFiles (0x001ad850).
void service_queued_files(void);

#endif
