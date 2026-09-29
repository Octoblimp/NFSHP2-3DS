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

// OverwriteFred, 0x00245d30: the loaded copy over Fred, DemoModeStatus's
// neighbour at +904 cleared, and the language the boot chose kept over the
// file's. Then six calls this port owes, which take the loaded settings
// into the frontend: 0x001fe988 twice (Fred+392 and Fred+648, 256 bytes
// each, into gp-16700 and gp-16696), 0x001ef120(Fred+148), 0x00154308 and
// 0x00155000 for each pad with Fred+376[pad], and 0x001f4b10(Fred+324).
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
}

// -------------------------------------------------------- MemcardPrompter

#define PROMPT_TITLE     0x249f4   // 150004, "Memory Card (PS2)"
#define PROMPT_YES       0x24a57
#define PROMPT_NO        0x24a58

// The messages the loader shows: 151001 and on.
#define MSG_LOADING      0x24dd9   // 151001
#define MSG_LOADED       0x24dda   // 151002
#define MSG_NO_FILE      0x24ddb   // 151003
#define MSG_NO_CARD_RETRY 0x24dde  // 151006
#define MSG_NO_SPACE     0x24de3   // 151011: slot, then KB
#define MSG_CHECKING     0x24de5   // 151013
#define MSG_NEW_CARD     0x24de6   // 151014
#define MSG_LOAD_RETRY   0x24dea   // 151018
#define MSG_OVERWRITE    0x24dee   // 151022
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
