#pragma once
#include <stdint.h>

#include "banim.h"
#include "bmenu.h"

// The memory card: BootAutoLoader, the Options screen's LoadSaveWrapper and
// the end of a race's Autosaver, and the five classes under them --
// MemcardLoader, MemcardSaver, MemcardTester, MemcardPrompter and
// SavegameData -- over cDBFileSys, the card's file system. Retail's,
// SLES_507.31, and every address here is retail's.
//
// BootAutoload is the first screen of every boot. It checks the card, loads
// "settings.db" from it if there is one, and says what it found in a popup
// (bpopup.h) that stays up for four seconds; then it moves back to the
// language screen or the title. "Phils Load Save", Options' Load/Save,
// loads and saves on request and turns autosave on and off; "Autosave" is
// the save the end of a race goes through. Every card state of all three
// is here. What the loader hands the host once the settings are in is the
// host's (fredLoaded).
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
// Fred.Autosave (0x002fc054), which the Load/Save screen toggles and a
// failed autosave clears. Fred+0 is the size, which SetupForSave writes.
#define BMC_FRED_AUTOSAVE   4

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
    // +1460: what the last CHECK_EXISTENCE found, 1 if the file opened.
    // The saver reads it; the loader goes by lastError.
    int                        fileExists;
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

// MemcardSaver's states, as the code numbers them. The .mdebug's enum
// (IDLE to READY_TO_LEAVE, 0-11) is an older class's, like the loader's.
// PROMPT_TO_CREATE is set by nothing in retail -- the demo's saver asked
// before it made the file, and retail's dismiss handler still answers it
// -- and is the port's again (BMemcardSaver.askCreate).
enum {
    BMC_SAVER_IDLE = 0,
    BMC_SAVER_CHECK_FOR_CARD = 1,       // Verify, a second of "Checking"
    BMC_SAVER_CHECK_IF_CARD_OK = 2,     // CheckForSavegameFile
    BMC_SAVER_PROMPT_SKIP = 3,          // 151028: go on without saving?
    BMC_SAVER_PROMPT_RETRY = 4,
    BMC_SAVER_PROMPT_TO_CREATE = 5,     // 151023
    BMC_SAVER_WRITING_FILE = 6,
    BMC_SAVER_PROMPT_TO_OVERWRITE = 7,  // 151020
    BMC_SAVER_SHOWING_STATUS = 8,       // "saved successfully"
    BMC_SAVER_SHOWING_ERROR = 9,
    BMC_SAVER_FORMAT_PROMPT = 10,       // 151007
    BMC_SAVER_CHECK_BEFORE_FORMAT = 11,
    BMC_SAVER_DOING_FORMAT = 12,
    BMC_SAVER_PROMPT_RETRY_FORMAT = 13, // 151010
    BMC_SAVER_DONE = 14,
    BMC_SAVER_CHECK_BEFORE_OVERWRITE = 15,
    BMC_SAVER_CHECK_BEFORE_CREATE = 16,
};

// MemcardSaver (0x002460f8), 24 bytes.
typedef struct {
    uint32_t          screenHash;  // +0
    BMemcardTester*   tester;      // +4
    BMemcardPrompter* prompter;    // +8
    uint32_t          timer;       // +12
    int               state;       // +16
    // +20, StartSaveSequence's third argument: 1 for a save the player
    // asked for -- Load/Save's Save, the end of a race's -- and 0 for the
    // one that turning autosave on starts. A save that does not happen
    // turns autosave back off when it is 0, and asks "continue without
    // saving?" when it is 1 and autosave is on.
    int               keepAutosave;
    // Port-only: ask before making the file (PROMPT_TO_CREATE) rather
    // than writing it at once, so the end of a race always asks.
    int               askCreate;
    BGameFlow*        gf;
} BMemcardSaver;

// MemcardSaver::HandleEvent (0x00246138). Returns 1 on the tick it
// finishes.
int memcard_saver_event(BMemcardSaver* s, BScreenMessage msg,
                        BScreenCallbackData* data);

// "Phils Load Save"'s items, and the Autosave line's two strings.
#define BMC_ITEM_SAVE            0x52e039f3u
#define BMC_ITEM_LOAD            0x52e039f4u
#define BMC_ITEM_AUTOSAVE        0x52e039f5u
#define BMC_LANG_AUTOSAVE_OFF    0x249f2   // 150002, "Autosave off"
#define BMC_LANG_AUTOSAVE_ON     0x249f3   // 150003, "Autosave on"

// LoadSaveWrapper (0x002473d0), 192 bytes: 0 on the menu, 1 saving, 2
// loading. 3 and 4 are set by nothing.
typedef struct {
    BSavegameData    savegame;   // +0, a local copy for the loader
    BMemcardSaver    saver;      // +4
    BMemcardLoader   loader;     // +28, MANUAL
    BMemcardTester   tester;     // +56
    BMemcardPrompter prompter;   // +76
    uint32_t         screenHash; // +80
    int              state;      // +84, which the constructor leaves be
    // +88, tSlideOnScreen: not the port's yet, so only traced.
    BHighlightAnim   highlight;  // +160
    BGameFlow*       gf;
    int              tracedAnimate;  // "bloom animate" said since the item
} BLoadSaveWrapper;

void memcard_load_save_init(BLoadSaveWrapper* w, BGameFlow* gf,
                            uint32_t screenHash);
void memcard_load_save_destroy(BLoadSaveWrapper* w);
// HandleEvent, 0x00247530.
void memcard_load_save_event(BLoadSaveWrapper* w, BScreenMessage msg,
                             BScreenCallbackData* data);

// Autosaver (0x00247b48), 64 bytes: the save started by the constructor,
// with no local copy -- the saver writes Fred itself -- and on its end the
// completion callback, or a move back with none.
typedef struct {
    void (*done)(void);          // +0
    BSavegameData    savegame;   // +4
    BMemcardSaver    saver;      // +8
    BMemcardTester   tester;     // +32
    BMemcardPrompter prompter;   // +52
    uint32_t         screenHash; // +56
    int              state;      // +60: 1 saving, 0 done
} BAutosaver;

void memcard_autosaver_init(BAutosaver* a, BGameFlow* gf,
                            uint32_t screenHash);
void memcard_autosaver_destroy(BAutosaver* a);
// HandleEvent, 0x00247c68. Nothing after the callback may touch `a`: the
// callback moves on to another screen, which destroys it.
void memcard_autosaver_event(BAutosaver* a, BScreenMessage msg,
                             BScreenCallbackData* data);

// CalculateChecksum (0x001878b0).
uint32_t memcard_checksum(const uint8_t* fred);
