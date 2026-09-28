#pragma once
#include <stdint.h>

#include "bmenu.h"

// The memory card, as the boot uses it: BootAutoLoader and the four classes
// under it -- MemcardLoader, MemcardTester, MemcardPrompter and SavegameData
// -- over cDBFileSys, the card's file system. Retail's, SLES_507.31, and
// every address here is retail's.
//
// BootAutoload is the first screen of every boot. It checks the card, loads
// "settings.db" from it if there is one, and says what it found in a popup
// (bpopup.h) that stays up for four seconds; then it moves back to the
// language screen or the title. The whole of it, every card state included,
// is here. What it does NOT do yet is what the loaded settings are for:
// OverwriteFred's six calls into the frontend database, the sound mixer and
// the controller setup (memcard_overwrite_fred).
//
// cDBFileSys is the one part that is not ported. It is the PS2's memory
// card library behind a vtable, and the 3DS has no memory card: the host
// supplies a file system through BMemcardFileSys -- main.c's keeps
// settings.db in sdmc:/NFSHP2/SAVES -- and tools/bootflow_check.py drives
// retail's classes over a scripted one.
//
// Written up in docs/formats/boot-flow.md, "The memory card". Free of
// <3ds.h> like the rest of the flow.

typedef struct BGameFlow BGameFlow;

// eFILE_SYS_STATES: what SetState asks the file system to do.
enum {
    BMC_FS_IDLE = 0,
    BMC_FS_SAVE = 1,
    BMC_FS_LOAD = 2,
    BMC_FS_CHECK_EXISTENCE = 3,
    BMC_FS_GET_DIR = 4,
    BMC_FS_FORMAT = 5,
    BMC_FS_UNFORMAT = 6,
    BMC_FS_VERIFY = 7,
    BMC_FS_WAITING = 8,
};

// cDBFilesBase::mLastError. SetLastError (0x0012ddc0) maps the card
// library's eMC codes onto these: 0-5 and 7-12 as they are, 13 (in
// progress) to 15, and anything else -- 6, FILE_EXISTS, among them -- to 16.
// The constructor starts it at 16.
enum {
    BMC_OK = 0,
    BMC_NOT_FORMATTED = 1,
    BMC_NEW_CARD = 2,
    BMC_NO_CARD = 3,
    BMC_INSUFFICIENT_FREE_SPACE = 4,
    BMC_FILE_NOT_FOUND = 5,
    BMC_IN_PROGRESS = 15,
    BMC_ERROR = 16,
};

// The save file: 0x114e0 bytes, Fred whole. Its last word is a checksum
// (CalculateChecksum, 0x001878b0): the sum of the 17719 words before it.
#define BMC_SAVE_NAME       "settings.db"   // 0x002bebe0
#define BMC_SAVE_SIZE       0x114e0
#define BMC_CHECKSUM_OFFSET 0x114dc
// The Fred fields OverwriteFred writes after the copy.
#define BMC_FRED_LANGUAGE   372
#define BMC_FRED_CLEARED    904

typedef struct BMemcardFileSys BMemcardFileSys;

// SetState's callback: run by Service when the job is done, with `param`.
typedef void (*BMemcardDone)(void* param);

// cDBFilesBase's vtable, the six slots the memory card classes call. The
// +offsets are the original's (8-byte GCC 2 entries at vtable +376).
typedef struct {
    void (*destroy)(BMemcardFileSys* fs);                               // +8
    // Advance the job. The job's callback runs from in here.
    void (*service)(BMemcardFileSys* fs, int port, int slot);           // +16
    // The file the next job is about: NULL data and 0 size for a job that
    // only asks whether the file is there.
    void (*setFileData)(BMemcardFileSys* fs, const char* name, void* data,
                        int size);                                      // +40
    // In KB, like getFreeSpace.
    int  (*calcFreeSpaceRequired)(BMemcardFileSys* fs, int size);       // +64
    int  (*getFreeSpace)(BMemcardFileSys* fs);                          // +168
    // Start a job. 0 if it was not taken, in which case no callback comes.
    int  (*setState)(BMemcardFileSys* fs, int state, BMemcardDone done,
                     void* param);                                      // +176
} BMemcardFileSysVtbl;

struct BMemcardFileSys {
    const BMemcardFileSysVtbl* vt;
    int                        lastError;   // +292
};

// SavegameData (0x00245640), 4 bytes: the local copy a load reads into,
// allocated by the constructor when asked for one (n == 1).
typedef struct {
    uint8_t* local;
} BSavegameData;

// MemcardTester (0x002457c0), 20 bytes.
typedef struct {
    BMemcardFileSys* fs;         // +0
    uint32_t         screenHash; // +4, see BBootAutoLoader
    int              active;     // +8: a job is out
    int              device;     // +12
    BSavegameData*   savegame;   // +16
    BGameFlow*       gf;         // the port's, for the trace
} BMemcardTester;

// MemcardPrompter, 4 bytes, and the port's copy of the message: the
// original sprintfs onto its own stack and hands the popup the pointer,
// which is good for as long as Summon runs.
typedef struct {
    uint32_t   screenHash;
    BGameFlow* gf;
    char       message[256];
} BMemcardPrompter;

// MemcardLoader::LoaderState, which is not the type info's: the .mdebug
// enum has 0-7 and the code has 1-8, with DONE last.
enum {
    BMC_LOADER_IDLE = 0,
    BMC_LOADER_CHECK_FOR_CARD = 1,
    BMC_LOADER_CHECK_IF_CARD_OK = 2,
    BMC_LOADER_READING_FILE = 3,
    BMC_LOADER_PROMPT_RETRY = 4,
    BMC_LOADER_PROMPT_OVERWRITE = 5,
    BMC_LOADER_SHOW_STATUS = 6,
    BMC_LOADER_READY_TO_LEAVE = 7,
    BMC_LOADER_DONE = 8,
};

// LoadMode: the boot's is BOOT, and the Options screen's load MANUAL.
enum { BMC_LOAD_MANUAL = 0, BMC_LOAD_BOOT = 1 };

// MemcardLoader (0x00246bd8), 28 bytes.
typedef struct {
    uint32_t          screenHash;  // +0
    BMemcardTester*   tester;      // +4
    BMemcardPrompter* prompter;    // +8
    uint32_t          timer;       // +12: RealTimer at the state's start
    int               loadMode;    // +16
    int               state;       // +20
    int               endState;    // +24: 0 OK, 1 unformatted, 2 no file
    BGameFlow*        gf;
} BMemcardLoader;

// BootAutoLoader (0x002478c0), 88 bytes: 1 loading, 2 saving, 0 done. The
// saver at +28 is never started -- nothing sets state 2 -- and is not here.
typedef struct {
    BMemcardLoader   loader;     // +0
    BSavegameData    savegame;   // +52
    BMemcardTester   tester;     // +56
    BMemcardPrompter prompter;   // +76
    // +80. Every class here keeps one, as the .mdebug's ScreenHash, and
    // nothing reads it. The boot's is the ItemHash of SCREEN_ACTIVATE -- the
    // BootAutoload screen's own hash -- which the callback hands over where
    // a port might be expected: the card is always device 0.
    uint32_t         screenHash;
    int              state;      // +84
} BBootAutoLoader;

// The constructor: the card opened, StopMovie, and the load sequence
// started. `manual` is the port's, like forceLegalScreens: the boot's
// loader is always BOOT, and MANUAL is how a scenario reaches the loader's
// other half before the Options screen that owns it is ported.
void memcard_boot_autoloader_init(BBootAutoLoader* b, BGameFlow* gf,
                                  uint32_t screenHash, int manual);
void memcard_boot_autoloader_destroy(BBootAutoLoader* b);

// BootAutoLoader::HandleEvent (0x002479d8): the loader's, and a move back
// once it is done.
void memcard_boot_autoloader_event(BBootAutoLoader* b, BScreenMessage msg,
                                   BScreenCallbackData* data);

// MemcardLoader::HandleEvent (0x00246c00). Returns 1 on the tick it
// finishes.
int memcard_loader_event(BMemcardLoader* l, BScreenMessage msg,
                         BScreenCallbackData* data);

// CalculateChecksum (0x001878b0).
uint32_t memcard_checksum(const uint8_t* fred);
