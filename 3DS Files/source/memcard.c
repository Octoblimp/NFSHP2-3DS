// The memory card: BootAutoLoader and the classes under it. See memcard.h,
// and docs/formats/boot-flow.md, "The memory card", for the decompilation --
// every rule below names a retail address.

#include "memcard.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bpopup.h"
#include "gameflow.h"

// ---------------------------------------------------------------- tracing

static void trace(BGameFlow* gf, const char* fmt, ...)
{
    char    line[192];
    va_list ap;
    if (!gf->hooks.trace) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    gf->hooks.trace(gf->hooks.user, line);
}

// The loader's timers: (float)(int)(RealTimer - start) * 0.00025f against
// a literal -- 2.0f for every state but READY_TO_LEAVE's 4.0f. Signed: a
// start in the future is not a long wait.
static int waited(const BGameFlow* gf, uint32_t start, float seconds)
{
    return seconds < (float)(int32_t)(gf->realTimer - start) * 0.00025f;
}

static uint32_t get32(const uint8_t* p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16
           | (uint32_t)p[3] << 24;
}

static void put32(uint8_t* p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

// --------------------------------------------------------- the blank card
//
// What the flow gets with no file system from the host: a card that is
// there, formatted and empty, and forgets what it is given. Every job
// finishes on the first Service after it starts.

typedef struct {
    BMemcardFileSys base;
    int             pending;    // the job, or BMC_FS_IDLE
    BMemcardDone    done;
    void*           param;
} BlankCard;

static void blankDestroy(BMemcardFileSys* fs) { free(fs); }

static void blankService(BMemcardFileSys* fs, int port, int slot)
{
    BlankCard*   c = (BlankCard*)fs;
    BMemcardDone done;
    (void)port;
    (void)slot;
    if (c->pending == BMC_FS_IDLE) return;
    switch (c->pending) {
        case BMC_FS_LOAD:
        case BMC_FS_CHECK_EXISTENCE: fs->lastError = BMC_FILE_NOT_FOUND; break;
        default:                     fs->lastError = BMC_OK;             break;
    }
    if (c->pending == BMC_FS_CHECK_EXISTENCE) fs->fileExists = 0;
    c->pending = BMC_FS_IDLE;
    done       = c->done;
    c->done    = NULL;
    if (done) done(c->param);
}

static void blankSetFileData(BMemcardFileSys* fs, const char* name,
                             void* data, int size)
{
    (void)fs;
    (void)name;
    (void)data;
    (void)size;
}

// CalculateFreeSpaceRequired (0x0012d1a0), with no icon: the file rounded
// up to KB, and five for the directory.
static int blankCalcFree(BMemcardFileSys* fs, int size)
{
    (void)fs;
    return (size + 1023) / 1024 + 5;
}

// An empty 8 MB card.
static int blankFreeSpace(BMemcardFileSys* fs)
{
    (void)fs;
    return 8192;
}

static int blankSetState(BMemcardFileSys* fs, int state, BMemcardDone done,
                         void* param)
{
    BlankCard* c = (BlankCard*)fs;
    if (c->pending != BMC_FS_IDLE || state <= BMC_FS_IDLE
        || state >= BMC_FS_WAITING)
        return 0;
    c->pending = state;
    c->done    = done;
    c->param   = param;
    return 1;
}

static const BMemcardFileSysVtbl kBlankCard = {
    blankDestroy, blankService, blankSetFileData, blankCalcFree,
    blankFreeSpace, blankSetState,
};

static BMemcardFileSys* blankCardNew(void)
{
    BlankCard* c = (BlankCard*)calloc(1, sizeof(*c));
    if (!c) return NULL;
    c->base.vt        = &kBlankCard;
    c->base.lastError = BMC_OK;
    return &c->base;
}

// ----------------------------------------------------------- SavegameData

uint32_t memcard_checksum(const uint8_t* fred)
{
    uint32_t sum = 0;
    for (int i = 0; i < BMC_CHECKSUM_OFFSET / 4; i++)
        sum += get32(fred + 4 * i);
    return sum;
}

// The constructor, 0x00245640: a local Fred for n == 1, none for 0. The
// original news a Fred and runs its constructor; the copy is cleared before
// every load, so zeroes do as well.
static void savegameInit(BSavegameData* s, int n)
{
    s->local = n == 1 ? (uint8_t*)calloc(1, BMC_SAVE_SIZE) : NULL;
}

static void savegameDestroy(BSavegameData* s)
{
    free(s->local);
    s->local = NULL;
}

// SetupForLoad, 0x00245700.
static uint8_t* savegameSetupForLoad(BSavegameData* s)
{
    if (s->local) memset(s->local, 0, BMC_SAVE_SIZE);
    return s->local;
}

// VerifyChecksumAfterLoad, 0x00245780.
static int savegameVerify(const BSavegameData* s)
{
    if (!s->local) return 0;
    return memcard_checksum(s->local) == get32(s->local + BMC_CHECKSUM_OFFSET);
}

// SetupForSave, 0x00245738: Fred itself, whatever the SavegameData, with
// its size in its first word and its checksum in its last.
static uint8_t* savegameSetupForSave(BGameFlow* gf)
{
    uint8_t* fred = gf->fred;
    if (!fred) return NULL;
    put32(fred, BMC_SAVE_SIZE);
    put32(fred + BMC_CHECKSUM_OFFSET, memcard_checksum(fred));
    return fred;
}

// ---------------------------------------------------------- MemcardTester

// GetPort and GetSlot (0x00245600, 0x00245608) of the tester's device:
// both 0, whatever the device.
static int devicePort(int device) { (void)device; return 0; }
static int deviceSlot(int device) { (void)device; return 0; }

// The constructor, 0x002457c0: the file system made, then serviced until
// it has stopped saying "error", "busy" or "new card" -- with no bound,
// as in the original.
static void testerInit(BMemcardTester* t, BGameFlow* gf, uint32_t screenHash,
                       int device, BSavegameData* savegame)
{
    int p, s;
    t->screenHash = screenHash;
    t->device     = device;
    t->savegame   = savegame;
    t->active     = 0;
    t->gf         = gf;
    t->fs         = gf->hooks.newFileSys ? gf->hooks.newFileSys(gf->hooks.user)
                                         : NULL;
    if (!t->fs) t->fs = blankCardNew();
    if (!t->fs) return;
    p = devicePort(device);
    s = deviceSlot(device);
    while (t->fs->lastError == BMC_ERROR || t->fs->lastError == BMC_IN_PROGRESS
           || t->fs->lastError == BMC_NEW_CARD)
        t->fs->vt->service(t->fs, p, s);
}

// The destructor, 0x00245898.
static void testerDestroy(BMemcardTester* t)
{
    if (t->fs) t->fs->vt->destroy(t->fs);
    t->fs = NULL;
}

// HandleEvent, 0x00245900: a tick services the card.
static void testerEvent(BMemcardTester* t, BScreenMessage msg)
{
    if (msg != BMSG_SCREEN_TICK || !t->fs) return;
    t->fs->vt->service(t->fs, devicePort(t->device), deviceSlot(t->device));
}

// Every job's callback (0x00245c38, 0x00245b98, 0x00245ca0, ...).
static void testerDone(void* param)
{
    ((BMemcardTester*)param)->active = 0;
}

// The jobs' shared tail: Active until the callback, or at once if the job
// was refused.
static int testerStart(BMemcardTester* t, int state)
{
    if (!t->fs) {
        t->active = 0;
        return 0;
    }
    if (!t->fs->vt->setState(t->fs, state, testerDone, t)) t->active = 0;
    return t->active != 0;
}

// Verify, 0x00245c40.
static int testerVerify(BMemcardTester* t)
{
    t->active = 1;
    return testerStart(t, BMC_FS_VERIFY);
}

// Load, 0x00245ba0: into the cleared local copy.
static int testerLoad(BMemcardTester* t)
{
    uint8_t* buf;
    t->active = 1;
    buf       = savegameSetupForLoad(t->savegame);
    if (t->fs)
        t->fs->vt->setFileData(t->fs, BMC_SAVE_NAME, buf, BMC_SAVE_SIZE);
    return testerStart(t, BMC_FS_LOAD);
}

// CheckForSavegameFile, 0x00245ca8.
static int testerCheckForSavegameFile(BMemcardTester* t)
{
    t->active = 1;
    if (t->fs) t->fs->vt->setFileData(t->fs, BMC_SAVE_NAME, NULL, 0);
    return testerStart(t, BMC_FS_CHECK_EXISTENCE);
}

// Save, 0x00245b00: Fred, checksummed, written whole.
static int testerSave(BMemcardTester* t)
{
    uint8_t* buf;
    t->active = 1;
    buf       = savegameSetupForSave(t->gf);
    if (t->fs)
        t->fs->vt->setFileData(t->fs, BMC_SAVE_NAME, buf, BMC_SAVE_SIZE);
    return testerStart(t, BMC_FS_SAVE);
}

// FormatCallback, 0x00245a40: the format done, the card verified, with
// Active up again until that is done too. Its lastError is the one the
// saver reads.
static void testerFormatDone(void* param)
{
    BMemcardTester* t = (BMemcardTester*)param;
    t->active = 1;
    if (!t->fs->vt->setState(t->fs, BMC_FS_VERIFY, testerDone, t))
        t->active = 0;
}

// Format, 0x00245a98. Unformat (0x002459d8) and ShowDirectoryTree
// (0x00245970), the class's other two jobs, are called by nothing.
static int testerFormat(BMemcardTester* t)
{
    t->active = 1;
    if (!t->fs) {
        t->active = 0;
        return 0;
    }
    if (!t->fs->vt->setState(t->fs, BMC_FS_FORMAT, testerFormatDone, t))
        t->active = 0;
    return t->active != 0;
}

// OverwriteFred, 0x00245d30: the loaded copy over Fred, DemoModeStatus's
// neighbour at +904 cleared, and the language the boot chose kept over the
// file's. Then six calls this port owes, which take the loaded settings
// into the frontend: 0x001fe988 twice (Fred+392 and Fred+648, 256 bytes
// each, into gp-16700 and gp-16696), 0x001ef120(Fred+148), 0x00154308 and
// 0x00155000 for each pad with Fred+376[pad], and 0x001f4b10(Fred+324).
// Those are the host's, through fredLoaded: the audio options' (jukebox.h)
// is the one it has so far.
static void testerOverwriteFred(BMemcardTester* t)
{
    BGameFlow* gf   = t->gf;
    uint8_t*   fred = gf->fred;
    if (!fred || !t->savegame->local) {
        trace(gf, "fred none");
        return;
    }
    memcpy(fred, t->savegame->local, BMC_SAVE_SIZE);
    put32(fred + BMC_FRED_CLEARED, 0);
    put32(fred + BMC_FRED_LANGUAGE, (uint32_t)gf->currLanguage);
    trace(gf, "fred loaded %08x %08x %u %d", (unsigned)get32(fred),
          (unsigned)get32(fred + BMC_CHECKSUM_OFFSET),
          (unsigned)get32(fred + BMC_FRED_CLEARED),
          (int)get32(fred + BMC_FRED_LANGUAGE));
    if (gf->hooks.fredLoaded) gf->hooks.fredLoaded(gf->hooks.user, fred);
}

// -------------------------------------------------------- MemcardPrompter

#define PROMPT_TITLE     0x249f4   // 150004, "Memory Card (PS2)"
#define PROMPT_YES       0x24a57
#define PROMPT_NO        0x24a58

// The messages the loader and the saver show: 151001 and on.
#define MSG_LOADING      0x24dd9   // 151001
#define MSG_LOADED       0x24dda   // 151002
#define MSG_NO_FILE      0x24ddb   // 151003
#define MSG_SAVING       0x24ddc   // 151004: the slot, twice
#define MSG_SAVED        0x24ddd   // 151005
#define MSG_NO_CARD_RETRY 0x24dde  // 151006
#define MSG_FORMAT_ASK   0x24ddf   // 151007
#define MSG_FORMATTING   0x24de0   // 151008
#define MSG_FORMAT_RETRY 0x24de2   // 151010
#define MSG_NO_SPACE     0x24de3   // 151011: slot, then KB
#define MSG_SAVE_RETRY   0x24de4   // 151012
#define MSG_CHECKING     0x24de5   // 151013
#define MSG_NEW_CARD     0x24de6   // 151014
#define MSG_NO_CARD_SLOT1 0x24de9  // 151017, "slot 1" in the string
#define MSG_LOAD_RETRY   0x24dea   // 151018
#define MSG_SAVE_OVERWRITE 0x24dec // 151020
#define MSG_OVERWRITE    0x24dee   // 151022
#define MSG_CREATE       0x24def   // 151023, the demo's
#define MSG_LOAD_FAILED  0x24df0   // 151024
#define MSG_NO_CARD      0x24df1   // 151025
#define MSG_NO_CARD_KB   0x24df3   // 151027: slot, then KB
#define MSG_NO_SAVE      0x24df4   // 151028: no arguments
#define MSG_UNFORMATTED  0x24e3d   // 151101

// GetTranslatedString (0x0021e560), through the animation kit's hook.
static const char* translate(BGameFlow* gf, int id)
{
    const char* s = NULL;
    if (gf->anim && gf->anim->hooks.translate)
        s = gf->anim->hooks.translate(gf->anim->hooks.user, id);
    return s ? s : "";
}

// sprintf (0x00251398) as the prompts use it: %d from the arguments in
// order, and %% -- the only conversions the strings carry. Anything else is
// copied as it stands rather than read off a stack that is not there, and
// a %d past the arguments prints 0.
static void formatPrompt(char* out, size_t cap, const char* fmt,
                         const int* args, int nargs)
{
    size_t n = 0;
    int    used = 0;
    if (cap == 0) return;
    while (*fmt && n + 1 < cap) {
        if (fmt[0] == '%' && fmt[1] == 'd') {
            char num[16];
            int  v = used < nargs ? args[used] : 0;
            used++;
            snprintf(num, sizeof(num), "%d", v);
            for (const char* q = num; *q && n + 1 < cap; q++) out[n++] = *q;
            fmt += 2;
        } else if (fmt[0] == '%' && fmt[1] == '%') {
            out[n++] = '%';
            fmt += 2;
        } else {
            out[n++] = *fmt++;
        }
    }
    out[n] = '\0';
}

static void prompterInit(BMemcardPrompter* p, BGameFlow* gf,
                         uint32_t screenHash)
{
    memset(p, 0, sizeof(*p));
    p->screenHash = screenHash;
    p->gf   = gf;
}

// DisplayMessage, 0x00245e30: whatever the card said last taken down, and
// the message up in its place, with no buttons -- SELECT does nothing to
// it. The slot is shown counting from 1.
static void prompterDisplayMessage(BMemcardPrompter* p, int id, int slot,
                                   int unused)
{
    BGameFlow*   gf = p->gf;
    BPopupConfig cfg;
    int          args[2];
    (void)unused;

    bpopup_dismiss(gf, 0);
    // Every id gets the slot; some get it twice (0x002bebf0), which no
    // string reads.
    args[0] = slot + 1;
    args[1] = slot + 1;
    formatPrompt(p->message, sizeof(p->message), translate(gf, id), args, 2);

    memset(&cfg, 0, sizeof(cfg));
    cfg.numButtons     = 0;
    cfg.flags          = BPOPUP_HORIZONTAL | BPOPUP_NO_SELECT;
    cfg.parent         = gf->screen;
    cfg.screen         = BPOPUP_SCREEN_MEMCARD;
    cfg.message        = p->message;
    cfg.button[0]      = 0;
    cfg.button[1]      = 0;
    cfg.button[2]      = 0;
    cfg.buttonParam[0] = -1;
    cfg.buttonParam[1] = -1;
    cfg.buttonParam[2] = -1;
    cfg.startButton    = 1;
    cfg.joyPort        = -1;
    cfg.timeout        = 0;
    cfg.title          = PROMPT_TITLE;
    bpopup_summon(gf, &cfg);
}

// DisplayYesNoMessage, 0x00245f60: Yes and No, left and right, starting on
// No, with the two params the loader reads back on BMSG_POPUP_DISMISS. BACK
// does nothing to it.
static void prompterYesNo(BMemcardPrompter* p, int id, int yesParam,
                          int noParam, int slot, int kb)
{
    BGameFlow*   gf = p->gf;
    BPopupConfig cfg;
    int          args[2];
    int          nargs;

    bpopup_dismiss(gf, 0);
    // 0x002bed90: the two "requires %d KB" strings take the size too, and
    // 151028 takes nothing.
    args[0] = slot + 1;
    args[1] = kb;
    nargs   = (id == MSG_NO_SPACE || id == MSG_NO_CARD_KB) ? 2
            : id == MSG_NO_SAVE                          ? 0
                                                         : 1;
    formatPrompt(p->message, sizeof(p->message), translate(gf, id),
                 nargs ? args : NULL, nargs);

    memset(&cfg, 0, sizeof(cfg));
    cfg.numButtons     = 2;
    cfg.flags          = BPOPUP_HORIZONTAL | BPOPUP_BUTTONS_BELOW;
    cfg.parent         = gf->screen;
    cfg.screen         = BPOPUP_SCREEN_MEMCARD;
    cfg.message        = p->message;
    cfg.button[0]      = PROMPT_YES;
    cfg.button[1]      = PROMPT_NO;
    cfg.button[2]      = 0;
    cfg.buttonParam[0] = yesParam;
    cfg.buttonParam[1] = noParam;
    cfg.buttonParam[2] = 0;
    cfg.startButton    = 1;
    cfg.joyPort        = -1;
    cfg.timeout        = 0;
    cfg.title          = PROMPT_TITLE;
    bpopup_summon(gf, &cfg);
}

// Clear, 0x002460e8.
static void prompterClear(BMemcardPrompter* p)
{
    bpopup_dismiss(p->gf, 0);
}

// ---------------------------------------------------------- MemcardLoader

static void loaderInit(BMemcardLoader* l, BGameFlow* gf, uint32_t screenHash,
                       int mode)
{
    memset(l, 0, sizeof(*l));
    l->screenHash = screenHash;
    l->loadMode = mode;
    l->gf       = gf;
}

static int loaderSlot(const BMemcardLoader* l)
{
    return deviceSlot(l->tester->device);
}

// StartLoadSequence(), 0x00247320: "Checking for Memory Card", and the
// card verified.
static void loaderStartLoadSequence(BMemcardLoader* l)
{
    l->state = BMC_LOADER_CHECK_FOR_CARD;
    l->timer = l->gf->realTimer;
    prompterDisplayMessage(l->prompter, MSG_CHECKING, loaderSlot(l), 0);
    testerVerify(l->tester);
}

// StartLoadSequence(tester, prompter), 0x00247310.
static void loaderStart(BMemcardLoader* l, BMemcardTester* t,
                        BMemcardPrompter* p)
{
    l->tester   = t;
    l->prompter = p;
    loaderStartLoadSequence(l);
}

// StartRead, 0x00247378: "Loading", and the file read.
static void loaderStartRead(BMemcardLoader* l)
{
    l->state = BMC_LOADER_READING_FILE;
    l->timer = l->gf->realTimer;
    prompterDisplayMessage(l->prompter, MSG_LOADING, loaderSlot(l), 0);
    testerLoad(l->tester);
}

// READY_TO_LEAVE, with a message, in the two orders the original has: the
// state set first, so the old message's dismissal is silenced (msg 21 in
// state 7 clears Noise) ...
static void loaderLeaveQuietly(BMemcardLoader* l, int id)
{
    l->state = BMC_LOADER_READY_TO_LEAVE;
    l->timer = l->gf->realTimer;
    prompterDisplayMessage(l->prompter, id, loaderSlot(l), 0);
}

// ... or the message first, which the old one's dismissal clicks through.
static void loaderLeave(BMemcardLoader* l, int id)
{
    prompterDisplayMessage(l->prompter, id, loaderSlot(l), 0);
    l->state = BMC_LOADER_READY_TO_LEAVE;
    l->timer = l->gf->realTimer;
}

static void loaderAsk(BMemcardLoader* l, int id, int yes, int no, int kb,
                      int state)
{
    prompterYesNo(l->prompter, id, yes, no, loaderSlot(l), kb);
    l->state = state;
}

// No card, or a card the loader cannot use: the boot says so and goes on;
// a manual load asks to retry.
static void loaderNoCard(BMemcardLoader* l)
{
    if (l->loadMode == BMC_LOAD_BOOT)
        loaderLeave(l, MSG_NO_CARD);
    else
        loaderAsk(l, MSG_NO_CARD_RETRY, 0, 1, 0, BMC_LOADER_PROMPT_RETRY);
}

// CHECK_FOR_CARD: two seconds of "Checking", then what Verify found.
static void loaderCheckForCard(BMemcardLoader* l)
{
    BMemcardTester* t = l->tester;
    int             err;

    if (t->active || !waited(l->gf, l->timer, 2.0f)) return;
    err = t->fs ? t->fs->lastError : BMC_NO_CARD;
    if (err == BMC_NOT_FORMATTED) {
        l->endState = 1;
        loaderLeaveQuietly(l, MSG_UNFORMATTED);
    } else if (err == BMC_OK || err == BMC_NEW_CARD) {
        l->state = BMC_LOADER_CHECK_IF_CARD_OK;
        if (!testerCheckForSavegameFile(t)) l->state = BMC_LOADER_DONE;
    } else {
        loaderNoCard(l);
    }
}

// CHECK_IF_CARD_OK: is settings.db there? The boot reads it; a manual load
// asks first, because it is about to replace the settings in use.
static void loaderCheckIfCardOK(BMemcardLoader* l)
{
    BMemcardTester*  t  = l->tester;
    BMemcardFileSys* fs = t->fs;
    int              err;

    if (t->active) return;
    err = fs ? fs->lastError : BMC_NO_CARD;
    if (err == BMC_OK) {
        if (l->loadMode == BMC_LOAD_BOOT)
            loaderStartRead(l);
        else
            loaderAsk(l, MSG_OVERWRITE, 2, 3, 0, BMC_LOADER_PROMPT_OVERWRITE);
    } else if (err == BMC_FILE_NOT_FOUND) {
        if (l->loadMode == BMC_LOAD_BOOT) {
            // Room to save later, or the boot asks now. Free space first.
            int freeKB = fs->vt->getFreeSpace(fs);
            int need   = fs->vt->calcFreeSpaceRequired(fs, BMC_SAVE_SIZE);
            if (freeKB < need) {
                loaderAsk(l, MSG_NO_SPACE, 0, 1, need,
                          BMC_LOADER_PROMPT_RETRY);
                return;
            }
        }
        l->endState = 2;
        loaderLeaveQuietly(l, MSG_NO_FILE);
    } else if (l->loadMode == BMC_LOAD_BOOT) {
        int need = fs ? fs->vt->calcFreeSpaceRequired(fs, BMC_SAVE_SIZE) : 0;
        loaderAsk(l, MSG_NO_CARD_KB, 0, 1, need, BMC_LOADER_PROMPT_RETRY);
    } else {
        loaderAsk(l, MSG_NO_CARD_RETRY, 0, 1, 0, BMC_LOADER_PROMPT_RETRY);
    }
}

// READING_FILE: two seconds of "Loading", then the checksum.
static void loaderReadingFile(BMemcardLoader* l)
{
    BMemcardTester* t = l->tester;
    int             err;

    if (t->active || !waited(l->gf, l->timer, 2.0f)) return;
    err = t->fs ? t->fs->lastError : BMC_NO_CARD;
    if (err == BMC_OK && savegameVerify(t->savegame)) {
        prompterDisplayMessage(l->prompter, MSG_LOADED, loaderSlot(l), 0);
        testerOverwriteFred(t);
        l->state = BMC_LOADER_READY_TO_LEAVE;
        l->timer = l->gf->realTimer;
    } else if (l->loadMode == BMC_LOAD_BOOT) {
        loaderLeave(l, MSG_LOAD_FAILED);
    } else {
        loaderAsk(l, MSG_LOAD_RETRY, 0, 1, 0, BMC_LOADER_PROMPT_RETRY);
    }
}

// SHOW_STATUS, a manual load's second look at the card after the
// overwrite prompt (table 0x002beea0 on the error, 3 past its end).
static void loaderShowStatus(BMemcardLoader* l)
{
    BMemcardTester* t = l->tester;
    int             err;

    if (t->active || !waited(l->gf, l->timer, 2.0f)) return;
    err = t->fs ? t->fs->lastError : BMC_NO_CARD;
    switch ((unsigned)err < 6u ? err : BMC_NO_CARD) {
        case BMC_OK:
            loaderStartRead(l);
            break;
        case BMC_NOT_FORMATTED:
            l->endState = 1;
            loaderLeaveQuietly(l, MSG_UNFORMATTED);
            break;
        case BMC_NEW_CARD:
            l->endState = 2;
            loaderLeave(l, MSG_NEW_CARD);
            break;
        case BMC_FILE_NOT_FOUND:
            l->endState = 2;
            loaderLeaveQuietly(l, MSG_NO_FILE);
            break;
        default:
            loaderNoCard(l);
            break;
    }
}

int memcard_loader_event(BMemcardLoader* l, BScreenMessage msg,
                         BScreenCallbackData* data)
{
    if (msg == BMSG_SCREEN_TICK) {
        if (l->tester->active) testerEvent(l->tester, BMSG_SCREEN_TICK);
        switch (l->state) {       // 0x002bee80 on State - 1
            case BMC_LOADER_CHECK_FOR_CARD:   loaderCheckForCard(l);  break;
            case BMC_LOADER_CHECK_IF_CARD_OK: loaderCheckIfCardOK(l); break;
            case BMC_LOADER_READING_FILE:     loaderReadingFile(l);   break;
            case BMC_LOADER_SHOW_STATUS:      loaderShowStatus(l);    break;
            case BMC_LOADER_READY_TO_LEAVE:
                if (waited(l->gf, l->timer, 4.0f)) l->state = BMC_LOADER_DONE;
                break;
            default:              // IDLE, the two prompts, DONE
                break;
        }
        if (l->state == BMC_LOADER_DONE) {
            prompterClear(l->prompter);
            return 1;
        }
        return 0;
    }

    if (msg == BMSG_POPUP_DISMISS && data) {
        switch (l->state) {       // 0x002beec0 on State - 3
            case BMC_LOADER_READING_FILE:
            case BMC_LOADER_READY_TO_LEAVE:
            case BMC_LOADER_DONE:
                // A message taken down to put the next one up: no click.
                data->noise = 0;
                break;
            case BMC_LOADER_PROMPT_RETRY:
                if (data->param == 0)
                    loaderStartLoadSequence(l);
                else if (data->param == 1)
                    l->state = BMC_LOADER_DONE;
                break;
            case BMC_LOADER_PROMPT_OVERWRITE:
                if (data->param == 2) {
                    prompterDisplayMessage(l->prompter, MSG_CHECKING,
                                           loaderSlot(l), 0);
                    l->state = BMC_LOADER_SHOW_STATUS;
                    l->timer = l->gf->realTimer;
                    testerCheckForSavegameFile(l->tester);
                } else if (data->param == 3) {
                    l->state = BMC_LOADER_DONE;
                }
                break;
            default:
                break;
        }
    }
    return 0;
}

// ----------------------------------------------------------- MemcardSaver

static int autosaveOn(const BGameFlow* gf)
{
    return gf->fred && get32(gf->fred + BMC_FRED_AUTOSAVE) != 0;
}

static void setAutosave(BGameFlow* gf, int on)
{
    if (gf->fred) put32(gf->fred + BMC_FRED_AUTOSAVE, (uint32_t)on);
}

// The constructor, 0x002460f8.
static void saverInit(BMemcardSaver* s, BGameFlow* gf, uint32_t screenHash)
{
    memset(s, 0, sizeof(*s));
    s->screenHash = screenHash;
    s->gf         = gf;
}

static int saverSlot(const BMemcardSaver* s)
{
    return deviceSlot(s->tester->device);
}

static int saverError(const BMemcardSaver* s)
{
    return s->tester->fs ? s->tester->fs->lastError : BMC_NO_CARD;
}

// 0x00246110, with 1 when the save did not happen: turning autosave on
// takes it back off again.
static void saverFinish(BMemcardSaver* s, int notSaved)
{
    if (notSaved == 1 && !s->keepAutosave) setAutosave(s->gf, 0);
}

// 0x002469e0, every "no" and every error's end: with autosave on, a save
// the player asked for asks whether to go on without one.
static void saverCancel(BMemcardSaver* s)
{
    if (autosaveOn(s->gf) && s->keepAutosave == 1) {
        prompterYesNo(s->prompter, MSG_NO_SAVE, 2, 3, saverSlot(s), 0);
        s->state = BMC_SAVER_PROMPT_SKIP;
    } else {
        s->state = BMC_SAVER_DONE;
        saverFinish(s, 1);
    }
}

// ShowErrorAndLeave, 0x00246a78: two seconds of it, then the cancel.
static void saverShowError(BMemcardSaver* s, int id)
{
    prompterDisplayMessage(s->prompter, id, saverSlot(s), 0);
    s->state = BMC_SAVER_SHOWING_ERROR;
    s->timer = s->gf->realTimer;
}

static void saverAsk(BMemcardSaver* s, int id, int yes, int no, int kb,
                     int state)
{
    prompterYesNo(s->prompter, id, yes, no, saverSlot(s), kb);
    s->state = state;
}

// The retry prompt, which most errors end in: "try again?", 3 yes, 2 no.
static void saverAskRetry(BMemcardSaver* s, int id, int kb)
{
    saverAsk(s, id, 3, 2, kb, BMC_SAVER_PROMPT_RETRY);
}

// StartFormat, 0x00246ab8.
static void saverStartFormat(BMemcardSaver* s)
{
    s->state = BMC_SAVER_DOING_FORMAT;
    s->timer = s->gf->realTimer;
    prompterDisplayMessage(s->prompter, MSG_FORMATTING, saverSlot(s), 0);
    testerFormat(s->tester);
}

// StartWrite, 0x00246b10.
static void saverStartWrite(BMemcardSaver* s)
{
    s->state = BMC_SAVER_WRITING_FILE;
    s->timer = s->gf->realTimer;
    prompterDisplayMessage(s->prompter, MSG_SAVING, saverSlot(s), 0);
    testerSave(s->tester);
}

// StartSaveSequence(), 0x00246b80.
static void saverStartSaveSequence(BMemcardSaver* s)
{
    s->state = BMC_SAVER_CHECK_FOR_CARD;
    s->timer = s->gf->realTimer;
    prompterDisplayMessage(s->prompter, MSG_CHECKING, saverSlot(s), 0);
    testerVerify(s->tester);
}

// StartSaveSequence(tester, prompter, keepAutosave), 0x00246b68.
static void saverStart(BMemcardSaver* s, BMemcardTester* t,
                       BMemcardPrompter* p, int keepAutosave)
{
    s->tester       = t;
    s->prompter     = p;
    s->keepAutosave = keepAutosave;
    saverStartSaveSequence(s);
}

// A second look at the card after a prompt (Verify, or the file check):
// "Checking" up, and the state that reads it.
static void saverRecheck(BMemcardSaver* s, int state, int checkFile)
{
    prompterDisplayMessage(s->prompter, MSG_CHECKING, saverSlot(s), 0);
    s->state = state;
    s->timer = s->gf->realTimer;
    if (checkFile)
        testerCheckForSavegameFile(s->tester);
    else
        testerVerify(s->tester);
}

// CHECK_FOR_CARD: a second of "Checking", then what Verify found.
static void saverCheckForCard(BMemcardSaver* s)
{
    int err;
    if (s->tester->active || !waited(s->gf, s->timer, 1.0f)) return;
    err = saverError(s);
    if (err == BMC_NOT_FORMATTED) {
        saverAsk(s, MSG_FORMAT_ASK, 7, 6, 0, BMC_SAVER_FORMAT_PROMPT);
    } else if (err == BMC_OK || err == BMC_NEW_CARD) {
        s->state = BMC_SAVER_CHECK_IF_CARD_OK;
        if (!testerCheckForSavegameFile(s->tester))
            saverShowError(s, MSG_NO_CARD_SLOT1);
    } else {
        saverAskRetry(s, MSG_NO_CARD_RETRY, 0);
    }
}

// CHECK_IF_CARD_OK: the file there is overwritten if the player says so;
// with none, the card needs the room for one.
static void saverCheckIfCardOK(BMemcardSaver* s)
{
    BMemcardFileSys* fs = s->tester->fs;
    int              err;
    if (s->tester->active) return;
    err = saverError(s);
    if (err != BMC_OK && err != BMC_FILE_NOT_FOUND) {
        saverShowError(s, MSG_NO_CARD_SLOT1);
    } else if (fs->fileExists) {
        saverAsk(s, MSG_SAVE_OVERWRITE, 5, 4, 0,
                 BMC_SAVER_PROMPT_TO_OVERWRITE);
    } else {
        int freeKB = fs->vt->getFreeSpace(fs);
        int need   = fs->vt->calcFreeSpaceRequired(fs, BMC_SAVE_SIZE);
        if (freeKB < need)
            saverAskRetry(s, MSG_NO_SPACE, need);
        else if (s->askCreate)
            // The port's: the demo's question (0x002304a0), where retail
            // makes the file without one.
            saverAsk(s, MSG_CREATE, 1, 0, 0, BMC_SAVER_PROMPT_TO_CREATE);
        else
            saverStartWrite(s);
    }
}

// WRITING_FILE: two seconds of "Saving", then how it went.
static void saverWritingFile(BMemcardSaver* s)
{
    BMemcardFileSys* fs = s->tester->fs;
    int              err;
    if (s->tester->active || !waited(s->gf, s->timer, 2.0f)) return;
    err = saverError(s);
    if (err == BMC_OK) {
        prompterDisplayMessage(s->prompter, MSG_SAVED, saverSlot(s), 0);
        s->state = BMC_SAVER_SHOWING_STATUS;
        s->timer = s->gf->realTimer;
    } else if (err == BMC_INSUFFICIENT_FREE_SPACE) {
        saverAskRetry(s, MSG_NO_SPACE,
                      fs->vt->calcFreeSpaceRequired(fs, BMC_SAVE_SIZE));
    } else {
        saverAskRetry(s, MSG_SAVE_RETRY, 0);
    }
}

// CHECK_BEFORE_FORMAT: the card looked at again once the player has said
// to format it, in case it changed under the prompt.
static void saverCheckBeforeFormat(BMemcardSaver* s)
{
    int err;
    if (s->tester->active || !waited(s->gf, s->timer, 2.0f)) return;
    err = saverError(s);
    if (err == BMC_NOT_FORMATTED)
        saverStartFormat(s);
    else if (err == BMC_OK || err == BMC_NEW_CARD)
        saverShowError(s, MSG_NEW_CARD);
    else if (err == BMC_NO_CARD)
        saverAskRetry(s, MSG_NO_CARD_RETRY, 0);
    else
        saverShowError(s, MSG_NO_CARD_SLOT1);
}

// DOING_FORMAT: what the Verify after the format found.
static void saverDoingFormat(BMemcardSaver* s)
{
    if (s->tester->active || !waited(s->gf, s->timer, 2.0f)) return;
    if (saverError(s) == BMC_OK)
        saverStartSaveSequence(s);
    else
        saverAsk(s, MSG_FORMAT_RETRY, 9, 8, 0,
                 BMC_SAVER_PROMPT_RETRY_FORMAT);
}

// CHECK_BEFORE_OVERWRITE: the file looked for again once the player has
// said to overwrite it.
static void saverCheckBeforeOverwrite(BMemcardSaver* s)
{
    int err;
    if (s->tester->active || !waited(s->gf, s->timer, 2.0f)) return;
    err = saverError(s);
    if (err == BMC_NOT_FORMATTED)
        saverAsk(s, MSG_FORMAT_ASK, 7, 6, 0, BMC_SAVER_FORMAT_PROMPT);
    else if (err == BMC_OK)
        saverStartWrite(s);
    else if (err == BMC_NEW_CARD)
        saverShowError(s, MSG_NEW_CARD);
    else if (err == BMC_NO_CARD)
        saverAskRetry(s, MSG_NO_CARD_RETRY, 0);
    else
        saverShowError(s, MSG_NO_CARD_SLOT1);
}

// CHECK_BEFORE_CREATE: the card verified again once the player has said
// to make the file.
static void saverCheckBeforeCreate(BMemcardSaver* s)
{
    int err;
    if (s->tester->active || !waited(s->gf, s->timer, 2.0f)) return;
    err = saverError(s);
    if (err == BMC_NEW_CARD)
        saverShowError(s, MSG_NEW_CARD);
    else if (err == BMC_OK || err == BMC_FILE_NOT_FOUND)
        saverStartWrite(s);
    else if (err == BMC_NO_CARD)
        saverAskRetry(s, MSG_NO_CARD_RETRY, 0);
    else
        saverShowError(s, MSG_NO_CARD_SLOT1);
}

int memcard_saver_event(BMemcardSaver* s, BScreenMessage msg,
                        BScreenCallbackData* data)
{
    if (msg == BMSG_SCREEN_TICK) {
        if (s->tester->active) testerEvent(s->tester, BMSG_SCREEN_TICK);
        switch (s->state) {       // 0x002bee00 on State - 1
            case BMC_SAVER_CHECK_FOR_CARD:   saverCheckForCard(s);  break;
            case BMC_SAVER_CHECK_IF_CARD_OK: saverCheckIfCardOK(s); break;
            case BMC_SAVER_WRITING_FILE:     saverWritingFile(s);   break;
            case BMC_SAVER_SHOWING_STATUS:
                if (waited(s->gf, s->timer, 2.0f)) s->state = BMC_SAVER_DONE;
                break;
            case BMC_SAVER_SHOWING_ERROR:
                if (waited(s->gf, s->timer, 2.0f)) saverCancel(s);
                break;
            case BMC_SAVER_CHECK_BEFORE_FORMAT: saverCheckBeforeFormat(s); break;
            case BMC_SAVER_DOING_FORMAT:        saverDoingFormat(s);       break;
            case BMC_SAVER_CHECK_BEFORE_OVERWRITE:
                saverCheckBeforeOverwrite(s);
                break;
            case BMC_SAVER_CHECK_BEFORE_CREATE:
                saverCheckBeforeCreate(s);
                break;
            default:              // IDLE, the prompts, DONE
                break;
        }
        if (s->state == BMC_SAVER_DONE) {
            prompterClear(s->prompter);
            return 1;
        }
        return 0;
    }

    // The original reads Param and writes Noise with no check on `data`.
    if (msg != BMSG_POPUP_DISMISS || !data) return 0;
    switch (s->state) {           // 0x002bee40 on State - 1
        case BMC_SAVER_CHECK_FOR_CARD:
        case BMC_SAVER_WRITING_FILE:
        case BMC_SAVER_SHOWING_STATUS:
        case BMC_SAVER_DOING_FORMAT:
        case BMC_SAVER_DONE:
            // A message taken down to put the next one up: no click.
            data->noise = 0;
            break;
        case BMC_SAVER_PROMPT_SKIP:
        case BMC_SAVER_PROMPT_RETRY:
            if (data->param == 2) {
                if (s->state == BMC_SAVER_PROMPT_RETRY) {
                    saverCancel(s);
                } else {
                    s->state = BMC_SAVER_DONE;
                    saverFinish(s, 1);
                }
            } else if (data->param == 3) {
                saverStartSaveSequence(s);
            }
            break;
        case BMC_SAVER_PROMPT_TO_CREATE:
            if (data->param == 0)
                saverCancel(s);
            else if (data->param == 1)
                saverRecheck(s, BMC_SAVER_CHECK_BEFORE_CREATE, 0);
            break;
        case BMC_SAVER_PROMPT_TO_OVERWRITE:
            if (data->param == 5)
                saverRecheck(s, BMC_SAVER_CHECK_BEFORE_OVERWRITE, 1);
            else if (data->param == 4)
                saverCancel(s);
            break;
        case BMC_SAVER_FORMAT_PROMPT:
            if (data->param == 7)
                saverRecheck(s, BMC_SAVER_CHECK_BEFORE_FORMAT, 0);
            else if (data->param == 6)
                saverCancel(s);
            break;
        case BMC_SAVER_PROMPT_RETRY_FORMAT:
            if (data->param == 9)
                saverRecheck(s, BMC_SAVER_CHECK_BEFORE_FORMAT, 0);
            else if (data->param == 8)
                saverCancel(s);
            break;
        default:                  // the two checks after a prompt, and 9
            break;
    }
    return 0;
}

// --------------------------------------------------------- LoadSaveWrapper

// FlailerSetScreenVisibility (0x0016eb68), as a bool.
static void screenVisible(BGameFlow* gf, uint32_t screen, int visible)
{
    trace(gf, "vis screen %08x %d", (unsigned)screen, visible);
    if (gf->hooks.setScreenVisible)
        gf->hooks.setScreenVisible(gf->hooks.user, screen, visible);
}

// FlailerSetLanguageID (0x001449a8).
static void setLanguageId(BGameFlow* gf, uint32_t screen, uint32_t object,
                          int id)
{
    trace(gf, "language id %08x %08x %d", (unsigned)screen, (unsigned)object,
          id);
    if (gf->hooks.setLanguageId)
        gf->hooks.setLanguageId(gf->hooks.user, screen, object, id);
}

// The Autosave line says which it is.
static void lswAutosaveLine(BLoadSaveWrapper* w)
{
    setLanguageId(w->gf, w->screenHash, BMC_ITEM_AUTOSAVE,
                  autosaveOn(w->gf) ? BMC_LANG_AUTOSAVE_ON
                                    : BMC_LANG_AUTOSAVE_OFF);
}

// The tSlideOnScreen at +88 (0x001ee918): the menu slides off while the
// card works and back on after. The port has no slide yet; the menu
// screen's own visibility, which the wrapper sets around it, is what the
// player sees.
static void lswSlide(BLoadSaveWrapper* w, const char* what)
{
    trace(w->gf, "slide %s", what);
}

// tHighlightAnimation::HandleMessage (0x00248ae0) on the bloom at +160:
// TICK animates it, MENUITEM_HIGHLIGHT moves it to the item.
static void lswHighlight(BLoadSaveWrapper* w, BScreenMessage msg,
                         BScreenCallbackData* data)
{
    BAnim* a = w->gf->anim;
    if (msg == BMSG_SCREEN_TICK) {
        if (!w->tracedAnimate) trace(w->gf, "bloom animate");
        w->tracedAnimate = 1;
        if (a) banim_highlight_animate(a, &w->highlight);
    } else if (msg == BMSG_MENUITEM_HIGHLIGHT && data) {
        trace(w->gf, "bloom item %08x", (unsigned)data->itemHash);
        w->tracedAnimate = 0;
        if (a) banim_highlight_set_item(a, &w->highlight, data->itemHash);
    }
}

// The card's job done: the menu back, sliding on, with its Autosave line.
static void lswBackToMenu(BLoadSaveWrapper* w)
{
    screenVisible(w->gf, w->screenHash, 1);
    lswSlide(w, "appear");
    w->state = 0;
    lswAutosaveLine(w);
}

// ... and off while it works.
static void lswStartSave(BLoadSaveWrapper* w, int keepAutosave)
{
    w->state = 1;
    screenVisible(w->gf, w->screenHash, 0);
    saverStart(&w->saver, &w->tester, &w->prompter, keepAutosave);
    lswSlide(w, "disappear");
}

void memcard_load_save_init(BLoadSaveWrapper* w, BGameFlow* gf,
                            uint32_t screenHash)
{
    BAnim* a = gf->anim;
    memset(w, 0, sizeof(*w));
    w->gf = gf;
    savegameInit(&w->savegame, 1);
    saverInit(&w->saver, gf, screenHash);
    loaderInit(&w->loader, gf, screenHash, BMC_LOAD_MANUAL);
    testerInit(&w->tester, gf, screenHash, 0, &w->savegame);
    prompterInit(&w->prompter, gf, screenHash);
    trace(gf, "slide init %08x %08x %08x %08x", (unsigned)screenHash,
          0x03c790bbu, 0x718cd8c3u, 0x95ad096bu);
    trace(gf, "bloom init %08x %08x %08x", (unsigned)screenHash,
          0xab671c9au, BANIM_BLOOM_COLOR);
    if (a)
        banim_highlight_init(a, &w->highlight, screenHash, 0xab671c9au,
                             (int32_t)BANIM_BLOOM_COLOR);
    bgf_stop_movie(gf);                // 0x00247468
    w->screenHash = screenHash;
    lswAutosaveLine(w);
}

// The destructor, 0x002474b8. Like the boot's, it leaves the popup be.
void memcard_load_save_destroy(BLoadSaveWrapper* w)
{
    testerDestroy(&w->tester);
    savegameDestroy(&w->savegame);
}

void memcard_load_save_event(BLoadSaveWrapper* w, BScreenMessage msg,
                             BScreenCallbackData* data)
{
    BGameFlow* gf = w->gf;

    switch (w->state) {
        case 1:
            if (memcard_saver_event(&w->saver, msg, data) == 1)
                lswBackToMenu(w);
            return;
        case 2:
            if (memcard_loader_event(&w->loader, msg, data) == 1)
                lswBackToMenu(w);
            return;
        case 3:
        case 4:
            if (w->tester.active) {
                testerEvent(&w->tester, msg);
                return;
            }
            screenVisible(gf, w->screenHash, 1);
            lswSlide(w, "appear");
            w->state = 0;
            break;
        default:
            break;
    }

    lswHighlight(w, msg, data);
    switch (msg) {
        case BMSG_MENUITEM_SELECT:
            if (!data) break;
            if (data->itemHash == BMC_ITEM_SAVE) {
                lswStartSave(w, 1);
            } else if (data->itemHash == BMC_ITEM_LOAD) {
                w->state = 2;
                screenVisible(gf, w->screenHash, 0);
                loaderStart(&w->loader, &w->tester, &w->prompter);
                lswSlide(w, "disappear");
            }
            break;
        case BMSG_MENUITEM_PAD_LEFT:
        case BMSG_MENUITEM_PAD_RIGHT:
            // Either way flips it; turned on, it saves at once, and a save
            // that does not happen turns it back off.
            if (!data || data->itemHash != BMC_ITEM_AUTOSAVE) break;
            setAutosave(gf, !autosaveOn(gf));
            lswAutosaveLine(w);
            data->noise = 2;
            if (autosaveOn(gf)) lswStartSave(w, 0);
            break;
        default:                  // TICK's slide, which the port has not
            break;
    }
}

// -------------------------------------------------------------- Autosaver

void memcard_autosaver_init(BAutosaver* a, BGameFlow* gf, uint32_t screenHash)
{
    memset(a, 0, sizeof(*a));
    savegameInit(&a->savegame, 0);
    saverInit(&a->saver, gf, screenHash);
    testerInit(&a->tester, gf, screenHash, 0, &a->savegame);
    prompterInit(&a->prompter, gf, screenHash);
    a->screenHash = screenHash;
    a->state      = 1;
    // The port's: ask before making the file, so the end of a race always
    // asks before it saves (gf->saveAskCreate).
    a->saver.askCreate = gf->saveAskCreate;
    saverStart(&a->saver, &a->tester, &a->prompter, 1);
    a->done = NULL;
}

// The destructor, 0x00247c08.
void memcard_autosaver_destroy(BAutosaver* a)
{
    testerDestroy(&a->tester);
    savegameDestroy(&a->savegame);
}

void memcard_autosaver_event(BAutosaver* a, BScreenMessage msg,
                             BScreenCallbackData* data)
{
    BGameFlow* gf = a->saver.gf;
    if (a->state != 1) return;
    if (memcard_saver_event(&a->saver, msg, data) == 1) a->state = 0;
    if (msg != BMSG_SCREEN_TICK || a->state != 0) return;
    if (a->done) {
        trace(gf, "autosave done");
        a->done();
    } else {
        bgf_move_back_screen(gf, 1);
    }
}

// --------------------------------------------------------- BootAutoLoader

void memcard_boot_autoloader_init(BBootAutoLoader* b, BGameFlow* gf,
                                  uint32_t screenHash, int manual)
{
    memset(b, 0, sizeof(*b));
    loaderInit(&b->loader, gf, screenHash,
               manual ? BMC_LOAD_MANUAL : BMC_LOAD_BOOT);
    savegameInit(&b->savegame, 1);
    testerInit(&b->tester, gf, screenHash, 0, &b->savegame);
    prompterInit(&b->prompter, gf, screenHash);
    b->screenHash = screenHash;
    bgf_stop_movie(gf);                // 0x00247934
    b->state = 1;
    loaderStart(&b->loader, &b->tester, &b->prompter);
}

// The destructor, 0x00247978. The popup is not taken down here: the loader
// clears it on the tick it finishes.
void memcard_boot_autoloader_destroy(BBootAutoLoader* b)
{
    testerDestroy(&b->tester);
    savegameDestroy(&b->savegame);
}

void memcard_boot_autoloader_event(BBootAutoLoader* b, BScreenMessage msg,
                                   BScreenCallbackData* data)
{
    BGameFlow* gf = b->loader.gf;
    if (b->state != 1) return;
    if (memcard_loader_event(&b->loader, msg, data) == 1) b->state = 0;
    // The move back unactivates the screen, which destroys this: nothing
    // after it may touch `b`.
    if (msg == BMSG_SCREEN_TICK && b->state == 0) bgf_move_back_screen(gf, 1);
}
