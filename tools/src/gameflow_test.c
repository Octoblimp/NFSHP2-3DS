// Host harness for the 3DS boot flow.
//
// Builds "3DS Files/source/gameflow.c" -- with bpopup.c and memcard.c under
// it -- for the host and runs a fixed set of boot scenarios against a
// simulated world -- a loader that finishes at the end of the frame that
// asked, a movie that runs five frames, a scripted memory card, the popup
// screen's text objects -- printing every observable step:
//
//     scenario <name>
//     frame <n> <realTime> <realTimer>
//     <whatever the flow traced: state, begin, end, change, enter, leave,
//      msg, stack, vis, movie, tex, sound, load, language, speech, gray,
//      popup, color, text, pos, fs, fred, replay, demo mode>
//     final <state> <screen> <stackDepth>
//
// tools/bootflow_check.py prints the same from retail's own code, run on
// SLES_507.31 in mipsemu where it can be, and diffs the two. Nothing here
// reads a bundle: the boot flow is behaviour, and the point of the diff is
// to catch a misread of the behaviour.
//
// Usage: gameflow_test [scenario]...      (no argument runs them all)

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gameflow.h"

// ------------------------------------------------------------- the world

#define MOVIE_FRAMES   5
#define PANEL_FRAMES   90
#define LOADER_FRAMES  1
#define TEXTURE_POLLS  2
#define REPLAY_FRAMES  3
#define MAX_PENDING    4
#define MAX_INPUTS     8

// The memory card, scripted. Every job finishes on its `busy`-th Service,
// leaving lastError at the job's answer; the constructor's pump takes
// `pump` Services to settle at `settle`. Same rules as the fake cDBFileSys
// in tools/bootflow_check.py.
typedef struct {
    const char* name;
    int pump;      // Services until the constructor's pump settles
    int settle;    // lastError it settles at (never 2: the pump would spin)
    int verify;    // lastError a VERIFY leaves
    int check;     // ... the first CHECK_EXISTENCE
    int check2;    // ... every later one, -1 for the same as the first
    int load;      // ... a LOAD
    int goodSum;   // the file's checksum holds
    int freeKB;    // GetFreeSpace
    int busy;      // Services a job takes
    int refuse;    // SetState takes no job
    int verify2;   // ... every VERIFY after the first, -1 for the same
    int save;      // ... a SAVE
    int format;    // ... a FORMAT
} Card;

// A card a FORMAT has left formatted verifies clean, has no file and has
// room; one a SAVE has written has the file. That is the card's, not the
// file system object's: it outlasts the tester that did it.
static const Card kCards[] = {
    // name          pump set  ver chk chk2 load sum  free busy ref ver2 save fmt
    { "blank",        1,  0,   0,  5,  -1,  0,   1, 8192,  1,  0,  -1,  0,  0 },
    { "good",         1,  0,   0,  0,  -1,  0,   1, 8192,  1,  0,  -1,  0,  0 },
    { "badsum",       1,  0,   0,  0,  -1,  0,   0, 8192,  1,  0,  -1,  0,  0 },
    { "loaderr",      1,  0,   0,  0,  -1,  3,   1, 8192,  1,  0,  -1,  0,  0 },
    { "nocard",       1,  3,   3,  3,  -1,  3,   1,    0,  1,  0,  -1,  0,  0 },
    { "unformatted",  1,  1,   1,  1,  -1,  1,   1,    0,  1,  0,  -1,  0,  0 },
    { "newcard",      1,  0,   2,  5,  -1,  0,   1, 8192,  1,  0,  -1,  0,  0 },
    { "full",         1,  0,   0,  5,  -1,  0,   1,   10,  1,  0,  -1,  0,  0 },
    { "tight",        1,  0,   0,  5,  -1,  0,   1,   75,  1,  0,  -1,  0,  0 },
    { "checkerr",     1,  0,   0,  3,  -1,  0,   1, 8192,  1,  0,  -1,  0,  0 },
    { "busy",         3,  0,   0,  5,  -1,  0,   1, 8192,  3,  0,  -1,  0,  0 },
    { "slow",         1,  0,   0,  5,  -1,  0,   1, 8192,  6,  0,  -1,  0,  0 },
    { "refuse",       1,  0,   0,  5,  -1,  0,   1, 8192,  1,  1,  -1,  0,  0 },
    { "gone",         1,  0,   0,  0,   5,  0,   1, 8192,  1,  0,  -1,  0,  0 },
    { "swapped",      1,  0,   0,  0,   2,  0,   1, 8192,  1,  0,  -1,  0,  0 },
    { "pulled",       1,  0,   0,  0,   3,  0,   1, 8192,  1,  0,  -1,  0,  0 },
    // The saver's: a write that fails, or finds no room; a format that
    // fails; a card formatted under the prompt; one pulled after the first
    // look, and one that cannot be read for the file once it was there.
    { "savefail",     1,  0,   0,  5,  -1,  0,   1, 8192,  1,  0,  -1,  3,  0 },
    { "savefull",     1,  0,   0,  5,  -1,  0,   1, 8192,  1,  0,  -1,  4,  0 },
    { "badformat",    1,  1,   1,  1,  -1,  1,   1,    0,  1,  0,  -1,  0,  3 },
    { "fixed",        1,  1,   1,  1,  -1,  1,   1,    0,  1,  0,   0,  0,  0 },
    { "yanked",       1,  0,   0,  5,  -1,  0,   1, 8192,  1,  0,   3,  0,  0 },
    { "goneafter",    1,  0,   0,  0,   3,  0,   1, 8192,  1,  0,  -1,  0,  0 },
};

typedef struct {
    const char* name;
    int videoMode;
    int currLanguage;
    int skipMovies;
    int frontendLaunchType;
    int demoModeStatus;
    int haveIntroMovie;   // pretend NFSINTRO_EN.AVI is on the disc
    int forceLegal;       // turn the dead MumboJumbo panels back on
    int frames;
    float dt;
    // up to eight scripted inputs: frame number and what to do
    struct { int frame; const char* what; } input[MAX_INPUTS];
    const char* card;     // a kCards row; NULL is "blank"
    int manual;           // the loader in MANUAL mode
    int replays;          // demo replays ConsiderLaunching will start
    // What UnlaunchFrontendMenus reads: Fred.GameType, and the race's demo
    // mode -- 1 AIDemoMode, 2 ReplayDemoMode, which the hook answers alike.
    int gameType;
    int raceDemo;
    int askCreate;        // gf.saveAskCreate: the Autosaver asks to make the file
} Scenario;

// A load in flight: what to print when it lands, and its callback.
typedef struct {
    const char*   label;
    BGameFlowDone done;
} Pending;

typedef struct World World;

// The scripted cDBFileSys.
typedef struct {
    BMemcardFileSys base;
    World*          w;
    int             pumpLeft;
    int             job;
    int             left;
    int             checks;
    int             verifies;
    BMemcardDone    done;
    void*           param;
    uint8_t*        data;
    int             size;
} WCard;

// The popup screen's text objects, in the file's order (FRONTB.BUN's
// 0x0ce3f7ce). The bitmaps are left out: nothing the popup does asks. The
// first two lines' MaxChars are 29 and 30, not the file's 40: at 40 no line
// of the scenarios' messages breaks where RenderTextIntoGroup's "MaxChars
// less two" matters, and every line would answer the same.
typedef struct {
    uint32_t hash;
    uint32_t group;
    float    y;
    float    sy;
    int      maxChars;
    uint32_t color;
} WObj;

#define FONT_HEIGHT 43.0f   // a2d444f6's

static const WObj kPopupObjs[] = {
    { 0xe0105664u, 0x457755c9u, 324.0f, 0.75f, 16, 0x80505050u },
    { 0xe0105663u, 0x457755c9u, 324.0f, 0.75f, 16, 0x80505050u },
    { 0x0783bebfu, 0x5d6dd123u,  98.0f, 0.6f,  29, 0x80505050u },
    { 0x0783bec0u, 0x5d6dd123u, 123.0f, 0.6f,  30, 0x80505050u },
    { 0x0783bec1u, 0x5d6dd123u, 148.0f, 0.6f,  40, 0x80505050u },
    { 0x0783bec2u, 0x5d6dd123u, 173.0f, 0.6f,  40, 0x80505050u },
    { 0x0783bec3u, 0x5d6dd123u, 198.0f, 0.6f,  40, 0x80505050u },
    { 0x0783bec4u, 0x5d6dd123u, 223.0f, 0.6f,  40, 0x80505050u },
    { 0x0783bec5u, 0x5d6dd123u, 248.0f, 0.6f,  40, 0x80505050u },
    { 0x0783bec6u, 0x5d6dd123u, 273.0f, 0.6f,  40, 0x80505050u },
    { 0x0783bec7u, 0x5d6dd123u, 298.0f, 0.6f,  40, 0x80505050u },
    { 0x85eda094u, 0x457755c9u,  41.0f, 0.85f, 19, 0x80646464u },
    { 0xab671c9au, 0x457755c9u, 602.0f, 0.75f, 21, 0x80808080u },
};
#define NUM_POPUP_OBJS ((int)(sizeof(kPopupObjs) / sizeof(kPopupObjs[0])))

struct World {
    const Scenario* sc;
    const Card*     card;
    BGameFlow*      gf;
    int             movieOpen;
    int             movieLeft;
    int             texPolls;
    int             loaderDue;    // nothing lands before this frame count
    uint32_t        activeItem;   // the highlighted item, for GetActiveMenuItem
    Pending         pending[MAX_PENDING];
    int             numPending;
    WCard           fs;
    int             fsOpen;
    int             formatted;    // the card, since a FORMAT
    int             saved;        // ... since a SAVE
    WObj            objs[NUM_POPUP_OBJS];
    int             replaysLeft;
    uint32_t        replayDue;
    int             inGame;       // InGameFlag
    char            text[192];
};

static void wTrace(void* user, const char* line)
{
    (void)user;
    printf("%s\n", line);
}

static int wMovieOpen(void* user, const char* path)
{
    World* w = (World*)user;
    // Only MOVIES\INTRO\EALOGO_EN.AVI is really in ZDIR.BIN. The scenario
    // can pretend the NFS intro is there too, which is the only way to
    // exercise the second movie at all.
    int present = strcmp(path, "MOVIES\\INTRO\\EALOGO_EN.AVI") == 0
                  || (w->sc->haveIntroMovie
                      && strcmp(path, "MOVIES\\INTRO\\NFSINTRO_EN.AVI") == 0);
    if (!present) return 0;
    w->movieOpen = 1;
    w->movieLeft = MOVIE_FRAMES;
    return 1;
}

static int wMovieDrive(void* user)
{
    World* w = (World*)user;
    if (w->movieLeft > 0) w->movieLeft--;
    return w->movieLeft == 0;
}

// Closing a movie that is open is traced; closing nothing is not, since
// retail's destructor closes whether or not anything is playing.
static void wMovieClose(void* user)
{
    World* w = (World*)user;
    if (w->movieOpen) printf("movie close\n");
    w->movieOpen = 0;
    w->movieLeft = 0;
}

// The menus' movie, TheMoviePlayer as StartMovie and UpdateMovie drive it --
// the same player as the title's. Every movie a menu names is on the disc,
// and Update answers 0 on its PANEL_FRAMES-th call, or with nothing open.
static int wPanelOpen(void* user, const char* path)
{
    World* w = (World*)user;
    printf("panel open %s\n", path);
    w->movieOpen = 1;
    w->movieLeft = PANEL_FRAMES;
    return 1;
}

static int wPanelUpdate(void* user)
{
    World* w = (World*)user;
    if (!w->movieOpen) return 0;
    if (w->movieLeft > 0) w->movieLeft--;
    if (w->movieLeft > 0) return 1;
    printf("panel end\n");
    return 0;
}

static int wInGame(void* user)
{
    return ((World*)user)->inGame;
}

static void wQueue(World* w, const char* label, BGameFlowDone done)
{
    if (!done) return;
    if (w->numPending >= MAX_PENDING) {
        printf("loader full %s\n", label);
        return;
    }
    w->pending[w->numPending].label = label;
    w->pending[w->numPending].done  = done;
    w->numPending++;
}

static void wLoadResource(void* user, const char* path, BGameFlowDone done)
{
    wQueue((World*)user, path, done);
}

static void wLoadSoundRegions(void* user, BGameFlowDone done)
{
    wQueue((World*)user, "sound regions", done);
}

// ServiceResourceLoading, at the frame's end: MainLoop calls it after
// eDisplayFrame (0x0012f60c). A load asked for during a frame has landed by
// the end of it and its callback runs then; a load that callback asks for
// lands at the next frame's end.
static void wServiceLoads(World* w)
{
    Pending run[MAX_PENDING];
    int     n = w->numPending;
    if ((int)w->gf->frameCounter < w->loaderDue) return;
    memcpy(run, w->pending, sizeof(run[0]) * (size_t)n);
    w->numPending = 0;
    for (int i = 0; i < n; i++) {
        printf("loaded %s\n", run[i].label);
        run[i].done(w->gf);
    }
}

static void wLoadTexture(void* user, uint32_t tex)
{
    (void)tex;
    ((World*)user)->texPolls = 0;
}

static int wTextureReady(void* user, uint32_t tex)
{
    World* w = (World*)user;
    (void)tex;
    return ++w->texPolls >= TEXTURE_POLLS;
}

static void wUnloadTexture(void* user, uint32_t tex) { (void)user; (void)tex; }

// A new menu starts on its first item.
static void wOpenScreen(void* user, const BScreenConfig* cfg)
{
    ((World*)user)->activeItem = BGF_ITEM_MENUITEM_1;
    printf("ui open %08x\n", (unsigned)cfg->hash);
}

static void wEnterScreen(void* user, const BScreenConfig* cfg)
{
    (void)user;
    printf("ui enter %08x\n", (unsigned)cfg->hash);
}

static void wLeaveScreen(void* user, const BScreenConfig* cfg)
{
    (void)user;
    printf("ui leave %08x\n", (unsigned)cfg->hash);
}

static uint32_t wActiveMenuItem(void* user)
{
    return ((World*)user)->activeItem;
}

static void wSound(void* user, int ev) { (void)user; (void)ev; }
static void wJukebox(void* user, int start)
{
    (void)user;
    printf("jukebox %d\n", start);
}
static int wGameType(void* user)
{
    return ((World*)user)->sc->gameType;
}
static int wRaceDemo(void* user)
{
    return ((World*)user)->sc->raceDemo != 0;
}
static void wSongMonitorReset(void* user)
{
    (void)user;
    printf("song monitor reset\n");
}
static void wEasterEggs(void* user, int start)
{
    (void)user;
    printf("eggs %d\n", start);
}
static void wMoveBrackets(void* user, uint32_t screen, uint32_t mask,
                          float under, float over)
{
    (void)user;
    printf("brackets %08x %08x %.1f %.1f\n", (unsigned)screen,
           (unsigned)mask, under, over);
}
static void wSetBlurb(void* user, uint32_t screen, int blurb)
{
    (void)user;
    printf("blurb %08x %d\n", (unsigned)screen, blurb);
}
static void wStartDemoMode(void* user) { (void)user; printf("attract\n"); }
static void wSetScreenVisible(void* u, uint32_t s, int v)
{ (void)u; (void)s; (void)v; }
static void wSetObjectVisible(void* u, uint32_t s, uint32_t o, int v)
{ (void)u; (void)s; (void)o; (void)v; }
static void wSetGroupVisible(void* u, uint32_t s, uint32_t g, int v)
{ (void)u; (void)s; (void)g; (void)v; }
static void wChangeTexture(void* u, uint32_t s, uint32_t o, uint32_t t)
{ (void)u; (void)s; (void)o; (void)t; }

// ------------------------------------------------------------- the card

// The save file a LOAD hands back: Fred's size in word 0, a pattern, a
// language (Italian) at +372 and a nonzero +904 for OverwriteFred to
// replace, and the checksum -- one off when the card says it is bad.
static void wWriteSave(const WCard* c)
{
    uint32_t sum = 0;
    uint8_t* d   = c->data;
    if (!d || c->size < BMC_SAVE_SIZE) return;
    for (int i = 0; i < BMC_CHECKSUM_OFFSET / 4; i++) {
        uint32_t v = i == 0 ? (uint32_t)BMC_SAVE_SIZE : (uint32_t)i * 2654435761u;
        if (i == BMC_FRED_LANGUAGE / 4) v = 3;
        if (i == BMC_FRED_CLEARED / 4) v = 7;
        memcpy(d + 4 * i, &v, 4);
        sum += v;
    }
    if (!c->w->card->goodSum) sum += 1;
    memcpy(d + BMC_CHECKSUM_OFFSET, &sum, 4);
}

static void cDestroy(BMemcardFileSys* fs)
{
    WCard* c = (WCard*)fs;
    printf("fs delete\n");
    c->w->fsOpen = 0;
}

static void cService(BMemcardFileSys* fs, int port, int slot)
{
    WCard*       c    = (WCard*)fs;
    const Card*  card = c->w->card;
    BMemcardDone done;
    printf("fs service %d %d\n", port, slot);
    if (!c->job) {
        if (c->pumpLeft > 0) {
            c->pumpLeft--;
            fs->lastError = c->pumpLeft > 0 ? BMC_IN_PROGRESS : card->settle;
        }
        return;
    }
    if (--c->left > 0) return;
    switch (c->job) {
        case BMC_FS_VERIFY:
            fs->lastError = c->w->formatted ? BMC_OK
                          : c->verifies > 0 && card->verify2 >= 0
                                ? card->verify2 : card->verify;
            c->verifies++;
            break;
        case BMC_FS_CHECK_EXISTENCE:
            fs->lastError = c->w->saved ? BMC_OK
                          : c->w->formatted ? BMC_FILE_NOT_FOUND
                          : c->checks > 0 && card->check2 >= 0 ? card->check2
                                                               : card->check;
            c->checks++;
            fs->fileExists = fs->lastError == BMC_OK;
            break;
        case BMC_FS_LOAD:
            fs->lastError = card->load;
            if (card->load == BMC_OK) wWriteSave(c);
            break;
        case BMC_FS_SAVE:
            // What went to the card: Fred's size, its Autosave word and its
            // checksum.
            fs->lastError = card->save;
            if (card->save == BMC_OK && c->data && c->size >= BMC_SAVE_SIZE) {
                uint32_t w0, as, sum;
                memcpy(&w0, c->data, 4);
                memcpy(&as, c->data + BMC_FRED_AUTOSAVE, 4);
                memcpy(&sum, c->data + BMC_CHECKSUM_OFFSET, 4);
                printf("fs saved %08x %08x %08x\n", (unsigned)w0,
                       (unsigned)as, (unsigned)sum);
                c->w->saved = 1;
            }
            break;
        case BMC_FS_FORMAT:
            fs->lastError = card->format;
            if (card->format == BMC_OK) c->w->formatted = 1;
            break;
        default: fs->lastError = BMC_OK; break;
    }
    c->job = 0;
    printf("fs done %d\n", fs->lastError);
    done    = c->done;
    c->done = NULL;
    if (done) done(c->param);
}

static void cSetFileData(BMemcardFileSys* fs, const char* name, void* data,
                         int size)
{
    WCard* c = (WCard*)fs;
    printf("fs file %s %d\n", name ? name : "(null)", size);
    c->data = (uint8_t*)data;
    c->size = size;
}

static int cCalcFree(BMemcardFileSys* fs, int size)
{
    (void)fs;
    printf("fs calc %d\n", size);
    return (size + 1023) / 1024 + 5;
}

static int cFreeSpace(BMemcardFileSys* fs)
{
    WCard* c    = (WCard*)fs;
    int    free = c->w->formatted ? 8192 : c->w->card->freeKB;
    printf("fs free %d\n", free);
    return free;
}

static int cSetState(BMemcardFileSys* fs, int state, BMemcardDone done,
                     void* param)
{
    WCard* c = (WCard*)fs;
    printf("fs state %d\n", state);
    if (c->w->card->refuse || c->job) return 0;
    c->job        = state;
    c->left       = c->w->card->busy;
    c->done       = done;
    c->param      = param;
    fs->lastError = BMC_IN_PROGRESS;
    return 1;
}

static const BMemcardFileSysVtbl kCardVtbl = {
    cDestroy, cService, cSetFileData, cCalcFree, cFreeSpace, cSetState,
};

static BMemcardFileSys* wNewFileSys(void* user)
{
    World* w = (World*)user;
    printf("fs new\n");
    memset(&w->fs, 0, sizeof(w->fs));
    w->fs.base.vt        = &kCardVtbl;
    w->fs.base.lastError = BMC_ERROR;
    w->fs.w              = w;
    w->fs.pumpLeft       = w->card->pump;
    w->fsOpen            = 1;
    return &w->fs.base;
}

// ----------------------------------------------------------- the replay

// TheDemoModeReplay: ConsiderLaunching starts one loading while the
// scenario has any left, and it lands REPLAY_FRAMES frames later.
static int wReplayConsider(void* user)
{
    World* w = (World*)user;
    if (w->replaysLeft <= 0) return 0;
    w->replaysLeft--;
    w->gf->replayLoading = 1;
    w->replayDue         = w->gf->frameCounter + REPLAY_FRAMES;
    return 1;
}

static void wReplayLaunch(void* user)
{
    ((World*)user)->gf->replayLoaded = 0;
}

static void wServiceReplay(World* w)
{
    if (!w->gf->replayLoading || w->gf->frameCounter < w->replayDue) return;
    w->gf->replayLoading = 0;
    w->gf->replayLoaded  = 1;
    printf("replay loaded\n");
}

// ------------------------------------------------- the popup screen's world

static int wFind(World* w, uint32_t screen, uint32_t obj)
{
    if (screen != BPOPUP_SCREEN_MEMCARD) return -1;
    for (int i = 0; i < NUM_POPUP_OBJS; i++)
        if (w->objs[i].hash == obj) return i;
    return -1;
}

static int aObjectExists(void* u, uint32_t screen, uint32_t obj, int type)
{
    return wFind((World*)u, screen, obj) >= 0
           && (type == BANIM_TYPE_ANY || type == BANIM_TYPE_TEXT);
}

static int32_t aNextInGroup(void* u, uint32_t screen, uint32_t group,
                            int type, int32_t after, uint32_t* hash)
{
    World* w = (World*)u;
    if (screen != BPOPUP_SCREEN_MEMCARD
        || (type != BANIM_TYPE_ANY && type != BANIM_TYPE_TEXT))
        return -1;
    for (int i = after + 1; i < NUM_POPUP_OBJS; i++) {
        if (w->objs[i].group != group) continue;
        *hash = w->objs[i].hash;
        return i;
    }
    return -1;
}

static int aMaxChars(void* u, uint32_t screen, uint32_t obj)
{
    World* w = (World*)u;
    int    i = wFind(w, screen, obj);
    return i < 0 ? 0 : w->objs[i].maxChars;
}

// GetScaledHeight (0x00140cd8): ScaleY times the font's height, the height
// truncated to an int first.
static float aScaledHeight(void* u, uint32_t screen, uint32_t obj)
{
    World* w = (World*)u;
    int    i = wFind(w, screen, obj);
    return i < 0 ? 0.0f : w->objs[i].sy * (float)(int)FONT_HEIGHT;
}

static uint32_t aGetColor(void* u, uint32_t screen, uint32_t obj)
{
    World* w = (World*)u;
    int    i = wFind(w, screen, obj);
    return i < 0 ? 0 : w->objs[i].color;
}

static void aSetColor(void* u, uint32_t screen, uint32_t obj, uint32_t color)
{
    World* w = (World*)u;
    int    i = wFind(w, screen, obj);
    if (i >= 0) w->objs[i].color = color;
}

static void aGetTopLeft(void* u, uint32_t screen, uint32_t obj, float* x,
                        float* y)
{
    World* w = (World*)u;
    int    i = wFind(w, screen, obj);
    *x = 0.0f;
    *y = i < 0 ? 0.0f : w->objs[i].y;
}

static void aSetTopLeft(void* u, uint32_t screen, uint32_t obj, float x,
                        float y)
{
    World* w = (World*)u;
    int    i = wFind(w, screen, obj);
    (void)x;
    if (i >= 0) w->objs[i].y = y;
}

// Stand-in strings, the same in bootflow_check.py: long enough to wrap, a
// forced break and a blank line, and the arguments each prompt passes.
static const char* aTranslate(void* u, int id)
{
    World* w = (World*)u;
    if (id == 0x24de3 || id == 0x24df3)
        snprintf(w->text, sizeof(w->text),
                 "<string %d> slot %%d needs %%d KB free, more than the"
                 " card has left.@Try again?", id);
    else if (id == 0x24df4)
        // 151028 is passed nothing: retail's sprintf would read a stale
        // register for a %d.
        snprintf(w->text, sizeof(w->text),
                 "<string %d> with nothing to fill in: a message long enough"
                 " that it has to wrap onto another line.@ @And one more.",
                 id);
    else
        snprintf(w->text, sizeof(w->text),
                 "<string %d> in slot %%d: a message long enough that it"
                 " has to wrap onto another line.@ @And one more.", id);
    return w->text;
}

static void setupAnimHooks(BAnimHooks* h, World* w)
{
    memset(h, 0, sizeof(*h));
    h->user             = w;
    h->objectExists     = aObjectExists;
    h->nextInGroup      = aNextInGroup;
    h->textMaxChars     = aMaxChars;
    h->textScaledHeight = aScaledHeight;
    h->getColor         = aGetColor;
    h->setColor         = aSetColor;
    h->getTopLeft       = aGetTopLeft;
    h->setTopLeft       = aSetTopLeft;
    h->translate        = aTranslate;
}

// ---------------------------------------------------------- the two tables

// The screen registry, the subset the boot flow names. Recovered by
// tools/screen_registry.py: `name` is the C++ literal, `hash` is
// bStringHash of the authored name, and they are different strings.
static const BScreenConfig kScreens[] = {
    { "BootAutoload",            BGF_SCREEN_BOOT_AUTOLOAD,
      bgf_boot_autoload_callback },
    { "Language Options Pre FE", BGF_SCREEN_LANGUAGE,
      bgf_language_screen_callback },
    { "Title Screen",            BGF_SCREEN_TITLE,
      bgf_title_screen_callback },
    { "New Main Menu",           BGF_SCREEN_NEW_MAIN_MENU,
      bgf_new_main_menu_callback },
    // Unreachable on the retail build -- ShouldSeeLegalMumboJumbo returns 0
    // -- but registered so a scenario can force it.
    { "Legal MumboJumbo",        BGF_SCREEN_MUMBO_JUMBO,
      bgf_mumbo_jumbo_callback },
    // Options' Load/Save, and the race's end's save, which shares
    // BootAutoload's empty Flailer screen.
    { "Phils Load Save",         0x9829bfabu,
      bgf_load_save_callback },
    { "Autosave",                BGF_SCREEN_BOOT_AUTOLOAD,
      bgf_autosave_callback },
};

// LaunchFrontendMenus' push list. The last row that passes is the first
// screen seen: retail's (0x0016f950), the language screen first.
static const BBootStage kBootStages[] = {
    { "Title Screen",            bgf_should_see_title_sequence },
    { "Legal MumboJumbo",        bgf_should_see_legal_mumbo_jumbo },
    { "BootAutoload",            bgf_should_see_autoload },
    { "Language Options Pre FE", bgf_should_see_language_select },
};

static const BGameFlowStateInfo kGameFlowStates[BGF_NUM_STATES] = {
    { "NONE",                     NULL, NULL, NULL },
    { "LOADING_FRONTEND",         bgf_begin_loading_frontend,
                                  bgf_end_loading_frontend, NULL },
    { "UNLOADING_FRONTEND",       bgf_begin_unloading_frontend, NULL, NULL },
    { "IN_FRONTEND",              NULL, NULL, NULL },
    { "LOADING_TRACK_COMMON",     NULL, NULL, NULL },
    { "LOADING_TRACK_SPECIFIC",   NULL, NULL, NULL },
    { "RACING",                   NULL, NULL, NULL },
    { "UNLOADING_TRACK_SPECIFIC", NULL, NULL, NULL },
    { "UNLOADING_TRACK_COMMON",   NULL, NULL, NULL },
};

// ------------------------------------------------------------- scenarios

#define SIXTIETH (1.0f / 60.0f)

// Every boot but the relaunch starts on BootAutoload,
// which takes two seconds checking the blank card and four more saying so.
// The scenarios that were written before it ran add these many frames, so
// that their frame numbers still count from where they did. It activates in
// frame 2 and used to move back in frame 3; at 1/60 it now takes 122 frames
// checking, 1 looking for the file and 243 saying there is none, and moves
// back in frame 368. At a second a frame, in frame 11.
#define BOOT60 365
#define BOOT1  8

// `currLanguage` is what the language is once LoadGlobalChunks has set
// English: 0 leaves it, another language is set through SetCurrLanguage,
// and -1 is written straight over it -- a state the disc never reaches,
// kept for the predicate's first test and the screen's -1 paths.
// The rows before the card's leave its four fields out: blank, BOOT, no
// replay, no attract mode.
// The saver's rows: back from a race with a demo waiting, so straight to
// the main menu with no BootAutoload, at a second a frame. SAVE_ASK asks
// before making the file.
#define SAVE_ROW(n, c, f, ...)                                              \
    { .name = n, .videoMode = 1, .skipMovies = 1, .frontendLaunchType = 2, \
      .demoModeStatus = 2, .frames = f, .dt = 1.0f, .card = c,            \
      .input = __VA_ARGS__ }
#define SAVE_ASK(n, c, f, ...)                                              \
    { .name = n, .videoMode = 1, .skipMovies = 1, .frontendLaunchType = 2, \
      .demoModeStatus = 2, .frames = f, .dt = 1.0f, .card = c,            \
      .askCreate = 1, .input = __VA_ARGS__ }

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wmissing-field-initializers"
static const Scenario kScenarios[] = {
    // An NTSC console: no language screen.
    { "ntsc", 1, 0, 0, 1, 0, 0, 0, BOOT60 + 40, SIXTIETH, {{0,0}} },
    // The shipped boot, PAL: Language Options Pre FE, which waits for a
    // choice, and BootAutoload after it.
    { "pal", 0, 0, 0, 1, 0, 0, 0, BOOT60 + 40, SIXTIETH, {{0,0}} },
    // No language at all: the first test in the predicate fires whatever
    // the video mode is. BACK there is vetoed and does nothing else, since
    // there is nothing to keep; Spanish is then chosen and the screen moves
    // back to BootAutoload, and then the title, whose movies are Spanish.
    { "nolang", 1, -1, 0, 1, 0, 0, 0, BOOT60 + 40, SIXTIETH,
      {{10, "back"}, {14, "item5"}} },
    // SkipMovies: the title screen starts at rest, with no movie.
    { "skipmovies", 1, 0, 1, 1, 0, 0, 0, BOOT60 + 30, SIXTIETH, {{0,0}} },
    // A second visit to the frontend with a demo waiting: straight to the
    // main menu, stack reset. BACK there is the main menu's, which vetoes it
    // without a sound.
    { "relaunch", 1, 0, 0, 2, 2, 0, 0, 20, SIXTIETH, {{10, "back"}} },
    // At rest on the title for over thirty seconds at one second a frame:
    // PRESS START comes up after four, attract mode after thirty. There is
    // no replay to show, so the race starts at once.
    { "attract", 1, 0, 1, 1, 0, 0, 0, BOOT1 + 40, 1.0f, {{0,0}} },
    // The title comes to rest 9 frames after the autoload, and PRESS
    // START is up 243 frames later -- the first multiple of 66 ticks over
    // 16000. Select at 14 is too early and does nothing; BACK at 20, in the
    // EA logo, and at 260, at rest, is vetoed by the title; select at 270
    // goes to the main menu; select again there does nothing; BACK there,
    // twice, is vetoed by retail's main menu, which clears Param and Noise.
    // The demo's went back to the title.
    { "select", 1, 0, 0, 1, 0, 0, 0, BOOT60 + 300, SIXTIETH,
      {{BOOT60 + 14, "select"}, {BOOT60 + 20, "back"},
       {BOOT60 + 260, "back"}, {BOOT60 + 270, "select"},
       {BOOT60 + 282, "select"}, {BOOT60 + 288, "back"},
       {BOOT60 + 292, "back"}} },
    // With the NFS intro present. Movie 0 runs over frames 3-7 and movie 1
    // over 8-12, so select at 5 lands inside the EA logo and is ignored --
    // movieIndex is still 0 -- and select at 10 lands inside the NFS intro
    // and stops it: the title comes to rest, still on Title Screen. Select
    // at 20 is before PRESS START and does nothing; select at 262 is after
    // it and goes to the main menu.
    // START at 21, which the title swallows without a sound.
    { "skipintro", 1, 0, 0, 1, 0, 1, 0, BOOT60 + 300, SIXTIETH,
      {{BOOT60 + 5, "select"}, {BOOT60 + 10, "select"},
       {BOOT60 + 20, "select"}, {BOOT60 + 21, "start"},
       {BOOT60 + 262, "select"}} },
    // The intro stopped at frame 10, then left alone at one second a frame:
    // attract mode comes thirty seconds after the skip, not after the
    // screen's arrival, because the skip restarts the Timer at +16.
    { "skipidle", 1, 0, 0, 1, 0, 1, 0, BOOT1 + 50, 1.0f,
      {{BOOT1 + 10, "select"}} },
    // The same with the movies left to finish: thirty seconds from the
    // moment the title comes to rest, which restarts the Timer too.
    { "restidle", 1, 0, 0, 1, 0, 0, 0, BOOT1 + 50, 1.0f, {{0,0}} },
    // The three main-menu items, each of which asks for a screen the port
    // has not registered: the flow is left with no current screen, and BACK
    // pops New Main Menu back. Hot Pursuit and World Racing differ only in
    // CopsOn, which "final" prints. PRESS START is up 243 frames after the
    // title comes to rest, as in "select"; with the movies skipped the main
    // menu starts none of its own.
    { "mainmenu", 1, 0, 1, 1, 0, 0, 0, BOOT60 + 280, SIXTIETH,
      {{BOOT60 + 250, "select"}, {BOOT60 + 254, "item3"},
       {BOOT60 + 258, "back"}, {BOOT60 + 262, "item1"}} },
    // Hot Pursuit, then a race: StartRace's ask for UNLOADING_FRONTEND,
    // whose Begin leaves the screens and asks for LOADING_TRACK_COMMON.
    { "leavefe", 1, 0, 1, 1, 0, 0, 0, BOOT60 + 270, SIXTIETH,
      {{BOOT60 + 250, "select"}, {BOOT60 + 254, "item1"},
       {BOOT60 + 260, "race"}} },
    // UnlaunchFrontendMenus over each kind of game: with View Event Tree
    // and a Quick Race screen pushed over New Main Menu, game types 2 to 7
    // pop back to the main menu, 8 and 9 to the event tree, and the rest
    // pop nothing. A demo race comes back with launch type 2, any other 3.
    { .name = "leavegtm1", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = BOOT60 + 270, .dt = SIXTIETH,
      .gameType = -1, .raceDemo = 0,
      .input = {{BOOT60 + 250, "select"}, {BOOT60 + 254, "item1"},
                {BOOT60 + 256, "pushvet"}, {BOOT60 + 257, "pushqr"},
                {BOOT60 + 260, "race"}} },
    { .name = "leavegt1", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = BOOT60 + 270, .dt = SIXTIETH,
      .gameType = 1, .raceDemo = 0,
      .input = {{BOOT60 + 250, "select"}, {BOOT60 + 254, "item1"},
                {BOOT60 + 256, "pushvet"}, {BOOT60 + 257, "pushqr"},
                {BOOT60 + 260, "race"}} },
    { .name = "leavegt2", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = BOOT60 + 270, .dt = SIXTIETH,
      .gameType = 2, .raceDemo = 0,
      .input = {{BOOT60 + 250, "select"}, {BOOT60 + 254, "item1"},
                {BOOT60 + 256, "pushvet"}, {BOOT60 + 257, "pushqr"},
                {BOOT60 + 260, "race"}} },
    { .name = "leavegt5", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = BOOT60 + 270, .dt = SIXTIETH,
      .gameType = 5, .raceDemo = 0,
      .input = {{BOOT60 + 250, "select"}, {BOOT60 + 254, "item1"},
                {BOOT60 + 256, "pushvet"}, {BOOT60 + 257, "pushqr"},
                {BOOT60 + 260, "race"}} },
    { .name = "leavegt7", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = BOOT60 + 270, .dt = SIXTIETH,
      .gameType = 7, .raceDemo = 0,
      .input = {{BOOT60 + 250, "select"}, {BOOT60 + 254, "item1"},
                {BOOT60 + 256, "pushvet"}, {BOOT60 + 257, "pushqr"},
                {BOOT60 + 260, "race"}} },
    { .name = "leavegt8", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = BOOT60 + 270, .dt = SIXTIETH,
      .gameType = 8, .raceDemo = 0,
      .input = {{BOOT60 + 250, "select"}, {BOOT60 + 254, "item1"},
                {BOOT60 + 256, "pushvet"}, {BOOT60 + 257, "pushqr"},
                {BOOT60 + 260, "race"}} },
    { .name = "leavegt9", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = BOOT60 + 270, .dt = SIXTIETH,
      .gameType = 9, .raceDemo = 0,
      .input = {{BOOT60 + 250, "select"}, {BOOT60 + 254, "item1"},
                {BOOT60 + 256, "pushvet"}, {BOOT60 + 257, "pushqr"},
                {BOOT60 + 260, "race"}} },
    { .name = "leavegt10", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = BOOT60 + 270, .dt = SIXTIETH,
      .gameType = 10, .raceDemo = 0,
      .input = {{BOOT60 + 250, "select"}, {BOOT60 + 254, "item1"},
                {BOOT60 + 256, "pushvet"}, {BOOT60 + 257, "pushqr"},
                {BOOT60 + 260, "race"}} },
    { .name = "leavegt2d1", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = BOOT60 + 270, .dt = SIXTIETH,
      .gameType = 2, .raceDemo = 1,
      .input = {{BOOT60 + 250, "select"}, {BOOT60 + 254, "item1"},
                {BOOT60 + 256, "pushvet"}, {BOOT60 + 257, "pushqr"},
                {BOOT60 + 260, "race"}} },
    { .name = "leavegt8d2", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = BOOT60 + 270, .dt = SIXTIETH,
      .gameType = 8, .raceDemo = 2,
      .input = {{BOOT60 + 250, "select"}, {BOOT60 + 254, "item1"},
                {BOOT60 + 256, "pushvet"}, {BOOT60 + 257, "pushqr"},
                {BOOT60 + 260, "race"}} },
    { .name = "leavegt0d1", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = BOOT60 + 270, .dt = SIXTIETH,
      .gameType = 0, .raceDemo = 1,
      .input = {{BOOT60 + 250, "select"}, {BOOT60 + 254, "item1"},
                {BOOT60 + 256, "pushvet"}, {BOOT60 + 257, "pushqr"},
                {BOOT60 + 260, "race"}} },
    // Force the legal screen, which the retail predicate never allows.
    { "mumbo", 1, 0, 0, 1, 0, 0, 0, BOOT60 + 30, SIXTIETH,
      {{BOOT60 + 12, "mumbo"}} },
    // The same with the two dead predicates turned on, so the legal and
    // anti-piracy panels and their 7-second timers actually run. One second
    // a frame, because 14 seconds at 1/60 is 840 frames of nothing.
    { "legal", 1, 0, 0, 1, 0, 0, 1, BOOT1 + 40, 1.0f,
      {{BOOT1 + 5, "mumbo"}} },
    // French from the start: the second movie is retail's own French
    // intro, and the LOADING art is the French one.
    { "french", 1, 1, 0, 1, 0, 0, 0, BOOT60 + 30, SIXTIETH, {{0,0}} },
    // PAL, French chosen on the language screen: the table, the speech and
    // the LOADING art all change, the frontend takes its defaults, and the
    // screen moves back to BootAutoload and then the title -- whose EA logo
    // is EALOGO_FR.
    { "palselect", 0, 0, 0, 1, 0, 0, 0, BOOT60 + 30, SIXTIETH,
      {{8, "item2"}} },
    // PAL, BACK on the language screen with Italian highlighted: BACK
    // chooses the highlighted language, as SELECT would.
    { "palback", 0, 0, 0, 1, 0, 0, 0, BOOT60 + 30, SIXTIETH,
      {{7, "hl4"}, {8, "back"}} },
    // PAL, Load All Languages. Hidden on this disc, and selected anyway:
    // the flag is set and the screen moves back with English kept.
    { "palall", 0, 0, 0, 1, 0, 0, 0, BOOT60 + 30, SIXTIETH,
      {{8, "item7"}} },
    // PAL, English chosen when English is in: SetLanguage returns at once,
    // and the frontend still takes its defaults.
    { "palsame", 0, 0, 0, 1, 0, 0, 0, BOOT60 + 30, SIXTIETH,
      {{8, "item1"}} },
    // PAL, French from the start and English chosen: the French LOADING art
    // is swapped back.
    { "palrevert", 0, 1, 0, 1, 0, 0, 0, BOOT60 + 30, SIXTIETH,
      {{8, "item1"}} },

    // ------------------------------------------------ BootAutoload's card
    //
    // NTSC with the movies skipped, at a second a frame: the autoload and
    // the title coming to rest behind it. The loader is BOOT unless the
    // row says MANUAL. Inputs go to the popup first, as the pad's do.

    // A save on the card, loaded: Fred takes it, with the boot's language
    // (French) kept over the file's (Italian).
    { .name = "good", .videoMode = 1, .currLanguage = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 20, .dt = 1.0f, .card = "good" },
    // PAL with that save (TASKS 56): French is chosen first, and the
    // frontend's defaults it takes are then loaded over, so the save's
    // points and the rest are kept, with the language just chosen.
    { .name = "palcard", .videoMode = 0, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 24, .dt = 1.0f, .card = "good",
      .input = {{4, "item2"}} },
    // A checksum that does not hold, and a load the card fails: "Load
    // failed", the old message's dismissal clicking through, and on.
    { .name = "badsum", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 20, .dt = 1.0f, .card = "badsum" },
    { .name = "loaderr", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 20, .dt = 1.0f, .card = "loaderr" },
    // No card, an unformatted one and a new one. SELECT on a message with
    // no buttons does nothing.
    { .name = "nocard", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 16, .dt = 1.0f, .card = "nocard",
      .input = {{4, "select"}} },
    { .name = "unformatted", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 16, .dt = 1.0f,
      .card = "unformatted" },
    { .name = "newcard", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 16, .dt = 1.0f, .card = "newcard" },
    // A card with no room to save later: the boot asks. No first, which
    // leaves; up, down and BACK do nothing to a horizontal popup that
    // cannot be cancelled.
    { .name = "fullno", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 16, .dt = 1.0f, .card = "full",
      .input = {{7, "up"}, {7, "down"}, {7, "back"}, {8, "select"}} },
    // Yes, to look again, which asks again; then left twice, which wraps
    // round to No, and START, which chooses as SELECT does.
    { .name = "fullyes", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 24, .dt = 1.0f, .card = "full",
      .input = {{7, "left"}, {8, "select"}, {13, "left"}, {13, "left"}, {14, "start"}} },
    // Exactly the 75 KB a save takes: room enough, so no question.
    { .name = "tight", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 16, .dt = 1.0f, .card = "tight" },
    // The card cannot be read for the file: the boot asks, with the size.
    { .name = "checkerr", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 16, .dt = 1.0f, .card = "checkerr",
      .input = {{7, "right"}, {8, "select"}} },
    // A card slow to answer: the pump, and jobs that take three services.
    { .name = "busy", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 20, .dt = 1.0f, .card = "busy" },
    // Jobs that take six Services: the Verify outlasts the two seconds of
    // "Checking", which wait for it.
    { .name = "slow", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 24, .dt = 1.0f, .card = "slow" },
    // A card that takes no job: Verify comes straight back, and the check
    // for the file ends the load there and then.
    { .name = "refuse", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 12, .dt = 1.0f, .card = "refuse" },
    // At 1/60, where the timers' last frames are: the load's two seconds
    // and the message's four.
    { .name = "goodslow", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 400, .dt = SIXTIETH, .card = "good" },

    // MANUAL, the Options screen's load. The file is there: overwrite the
    // settings? No leaves; Yes checks again and loads.
    { .name = "manualno", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 14, .dt = 1.0f, .card = "good",
      .manual = 1, .input = {{7, "select"}} },
    { .name = "manualyes", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 24, .dt = 1.0f, .card = "good",
      .manual = 1, .input = {{7, "left"}, {8, "select"}} },
    // Yes at half-second frames: a whole second's worth of 0.00025 rounds
    // up (12000 of them come to 3.0000002), so at one-second frames a
    // two-second wait and a three-second one end on the same tick.
    { .name = "manualhalf", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 40, .dt = 0.5f, .card = "good",
      .manual = 1, .input = {{9, "left"}, {10, "select"}} },
    // Yes, and the second look finds the file gone, the card swapped or
    // the card pulled.
    { .name = "manualgone", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 20, .dt = 1.0f, .card = "gone",
      .manual = 1, .input = {{7, "left"}, {8, "select"}} },
    { .name = "manualswap", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 20, .dt = 1.0f, .card = "swapped",
      .manual = 1, .input = {{7, "left"}, {8, "select"}} },
    { .name = "manualpull", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 20, .dt = 1.0f, .card = "pulled",
      .manual = 1, .input = {{7, "left"}, {8, "select"}, {12, "select"}} },
    // A bad file loaded by hand asks to try again; no card asks to retry,
    // and Yes starts the whole sequence over.
    { .name = "manualbad", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 24, .dt = 1.0f, .card = "badsum",
      .manual = 1, .input = {{7, "left"}, {8, "select"}, {16, "select"}} },
    { .name = "manualnocard", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 20, .dt = 1.0f, .card = "nocard",
      .manual = 1, .input = {{6, "left"}, {7, "select"}, {11, "select"}} },
    // The file is not there: a manual load says so and leaves.
    { .name = "manualnone", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = 14, .dt = 1.0f, .manual = 1 },

    // ------------------------------------------- ConsiderStartDemoMode
    //
    // A replay to show: attract mode starts it loading and waits, then
    // plays it and starts the race behind it.
    { .name = "replay", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 1, .frames = BOOT1 + 44, .dt = 1.0f,
      .replays = 1 },
    // The main menu's movie starts with the screen and plays on, one loop
    // after another -- UpdateMovie opens it again whenever Update answers
    // 0 -- until InGameFlag stops it. StopMovie takes the gate down, so
    // when the flag drops again UpdateMovie does nothing; kept up, it would
    // find nothing open and open the movie again.
    { .name = "menumovie", .videoMode = 1, .frontendLaunchType = 1,
      .frames = BOOT60 + 500, .dt = SIXTIETH,
      .input = {{BOOT60 + 270, "select"}, {BOOT60 + 480, "ingame"},
                {BOOT60 + 490, "outgame"}} },
    // Back on the main menu with its movie still playing: StartMovie finds
    // the same name and leaves it be. Then another movie in its place, as
    // the Options screen's constructor starts one: the first is stopped and
    // the second opened, and loops under its own name. The same name again
    // does nothing.
    { .name = "menuagain", .videoMode = 1, .frontendLaunchType = 1,
      .frames = BOOT60 + 400, .dt = SIXTIETH,
      .input = {{BOOT60 + 270, "select"}, {BOOT60 + 274, "item3"},
                {BOOT60 + 278, "back"}, {BOOT60 + 290, "optionsmovie"},
                {BOOT60 + 300, "optionsmovie"}} },
    // BACK on the main menu while its movie plays: vetoed, silently, and
    // the movie plays on, loop after loop, for forty seconds. Retail's
    // OnTick would start attract mode at thirty; the port owes that until
    // StartDemoMode has a race, and the checker's run of OnTick stubs
    // ConsiderStartDemoMode (bootflow_check.py, RetailMainMenu).
    { .name = "menuidle", .videoMode = 1, .frontendLaunchType = 1,
      .frames = BOOT1 + 60, .dt = 1.0f,
      .input = {{BOOT1 + 16, "select"}, {BOOT1 + 18, "back"}} },
    // StartDemoMode's StopMovie with a movie open. Retail gets there from
    // a screen that plays one and calls ConsiderStartDemoMode, as the main
    // menu's OnTick does; the port has none yet, so the options movie is
    // opened under the title at rest, which then goes to attract at thirty
    // seconds and stops it first. The movies are on: with SkipMovies set,
    // StartMovie opens nothing.
    { .name = "attractmovie", .videoMode = 1, .frontendLaunchType = 1,
      .frames = BOOT1 + 40, .dt = 1.0f,
      .input = {{BOOT1 + 12, "optionsmovie"}} },
    // The main menu's highlight: OnHighlight moves the brackets to each
    // item's mask and sets its blurb, and an item it does not know (hi9,
    // MENUITEM_9) moves nothing. Then into Options and back, and the
    // highlight still moves them -- which, before OnHighlight was ported,
    // it did not: the brackets stayed where NEW_MAIN_MENU authors them.
    { .name = "menuhighlight", .videoMode = 1, .frontendLaunchType = 1,
      .frames = BOOT60 + 300, .dt = SIXTIETH,
      .input = {{BOOT60 + 270, "select"}, {BOOT60 + 272, "hi2"},
                {BOOT60 + 273, "hi3"}, {BOOT60 + 274, "hi9"},
                {BOOT60 + 275, "item3"}, {BOOT60 + 278, "back"},
                {BOOT60 + 280, "hi1"}, {BOOT60 + 282, "hi2"}} },
    // The race asked for from the main menu with its movie playing:
    // UnlaunchFrontendMenus stops it after the launch type.
    { .name = "leavemovie", .videoMode = 1, .frontendLaunchType = 1,
      .frames = BOOT60 + 320, .dt = SIXTIETH, .gameType = 2,
      .input = {{BOOT60 + 270, "select"}, {BOOT60 + 300, "race"}} },

    // ------------------------------------------------------- MemcardSaver
    //
    // Back from a race with a demo waiting, so straight to the main menu
    // with no BootAutoload, at a second a frame; then Options' Load/Save
    // over it, or the race's end's Autosave.
    { .name = "lssave", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 2, .demoModeStatus = 2, .frames = 24, .dt = 1.0f,
      .input = {{3, "loadsave"}, {5, "picksave"}, {20, "back"}} },
    SAVE_ROW("lsoverwriteyes", "good", 24, {{3, "loadsave"}, {5, "picksave"},
             {9, "left"}, {10, "select"}}),
    SAVE_ROW("lsoverwriteno", "good", 16, {{3, "loadsave"}, {5, "picksave"},
             {9, "select"}}),
    SAVE_ROW("lsnocardno", "nocard", 16, {{3, "loadsave"}, {5, "picksave"},
             {9, "select"}}),
    SAVE_ROW("lsnocardyes", "nocard", 24, {{3, "loadsave"}, {5, "picksave"},
             {9, "left"}, {10, "select"}, {16, "select"}}),
    SAVE_ROW("lsformatyes", "unformatted", 36, {{3, "loadsave"},
             {5, "picksave"}, {9, "left"}, {10, "select"}}),
    SAVE_ROW("lsformatno", "unformatted", 16, {{3, "loadsave"},
             {5, "picksave"}, {9, "select"}}),
    SAVE_ROW("lsbadformat", "badformat", 40, {{3, "loadsave"},
             {5, "picksave"}, {9, "left"}, {10, "select"}, {18, "left"},
             {19, "select"}, {28, "select"}}),
    SAVE_ROW("lsfixed", "fixed", 24, {{3, "loadsave"}, {5, "picksave"},
             {9, "left"}, {10, "select"}}),
    SAVE_ROW("lsfull", "full", 16, {{3, "loadsave"}, {5, "picksave"},
             {9, "select"}}),
    SAVE_ROW("lssavefail", "savefail", 36, {{3, "loadsave"},
             {5, "picksave"}, {12, "left"}, {13, "select"}, {24, "select"}}),
    SAVE_ROW("lssavefull", "savefull", 20, {{3, "loadsave"},
             {5, "picksave"}, {12, "select"}}),
    SAVE_ROW("lsnewcard", "newcard", 20, {{3, "loadsave"},
             {5, "picksave"}}),
    SAVE_ROW("lsgone", "goneafter", 24, {{3, "loadsave"}, {5, "picksave"},
             {9, "left"}, {10, "select"}, {16, "select"}}),
    // The look for the file fails; the file there at the first look is
    // gone at the second, after Yes to overwriting it.
    SAVE_ROW("lscheckerr", "checkerr", 16, {{3, "loadsave"},
             {5, "picksave"}}),
    SAVE_ROW("lsfilegone", "gone", 24, {{3, "loadsave"}, {5, "picksave"},
             {9, "left"}, {10, "select"}}),
    // Autosave turned on saves at once, and stays on; off again does not
    // save. On with no card: the save that does not happen turns it back
    // off.
    SAVE_ROW("lsautoon", "blank", 20, {{3, "loadsave"}, {5, "asright"}}),
    SAVE_ROW("lsautooff", "blank", 24, {{3, "loadsave"}, {5, "asleft"},
             {16, "asright"}, {18, "picksave"}}),
    SAVE_ROW("lsautonocard", "nocard", 16, {{3, "loadsave"},
             {5, "asright"}, {9, "select"}}),
    // Autosave on and Save with no card: No to trying again asks whether
    // to go on without saving; No to that tries again, Yes leaves.
    SAVE_ROW("lsskip", "nocard", 32, {{2, "fredautosave"}, {3, "loadsave"},
             {5, "picksave"}, {9, "select"}, {11, "select"}, {15, "select"},
             {17, "left"}, {18, "select"}}),
    // Load, the loader's MANUAL sequence under the menu.
    SAVE_ROW("lsload", "good", 24, {{3, "loadsave"}, {5, "pickload"},
             {9, "left"}, {10, "select"}}),
    // The bloom on the menu's lines, and BACK out of the menu.
    SAVE_ROW("lslite", "blank", 12, {{3, "loadsave"}, {5, "litesave"},
             {7, "liteauto"}, {9, "back"}}),
    // The Options screen's movie, which the wrapper's constructor stops.
    // Movies on, or StartMovie opens nothing.
    { .name = "lsmovie", .videoMode = 1, .frontendLaunchType = 2,
      .demoModeStatus = 2, .frames = 8, .dt = 1.0f, .card = "blank",
      .input = {{3, "optionsmovie"}, {4, "loadsave"}} },
    // At 1/60, where the saver's timers end: a second of "Checking", two
    // of "Saving" and two of "Saved".
    { .name = "lssaveslow", .videoMode = 1, .skipMovies = 1,
      .frontendLaunchType = 2, .demoModeStatus = 2, .frames = 400,
      .dt = SIXTIETH, .card = "blank",
      .input = {{3, "loadsave"}, {5, "picksave"}} },

    // The race's end's Autosave: with no callback it moves back; with one
    // it hands over. The port asks before making the file.
    SAVE_ROW("asblank", "blank", 16, {{3, "autosave"}}),
    SAVE_ROW("ascb", "blank", 16, {{3, "autosave"}, {4, "autosavecb"}}),
    // A callback that leaves the screen up is called once.
    SAVE_ROW("asstay", "blank", 16, {{3, "autosave"}, {4, "autosavestay"}}),
    SAVE_ASK("ascreateyes", "blank", 20, {{3, "autosave"}, {4, "autosavecb"},
             {7, "left"}, {8, "select"}}),
    SAVE_ASK("ascreateno", "blank", 16, {{3, "autosave"}, {4, "autosavecb"},
             {7, "select"}}),
    SAVE_ASK("ascreateskip", "blank", 20, {{2, "fredautosave"},
             {3, "autosave"}, {4, "autosavecb"}, {7, "select"},
             {9, "left"}, {10, "select"}}),
    SAVE_ASK("ascreatenew", "newcard", 20, {{3, "autosave"},
             {4, "autosavecb"}, {7, "left"}, {8, "select"}}),
    SAVE_ASK("ascreateyank", "yanked", 20, {{3, "autosave"},
             {4, "autosavecb"}, {7, "left"}, {8, "select"}, {12, "select"}}),
    SAVE_ASK("asoverwrite", "good", 20, {{3, "autosave"}, {4, "autosavecb"},
             {7, "left"}, {8, "select"}}),
    SAVE_ASK("asunformatted", "unformatted", 16, {{3, "autosave"},
             {4, "autosavecb"}, {7, "select"}}),
};
#pragma GCC diagnostic pop
#define NUM_SCENARIOS ((int)(sizeof(kScenarios) / sizeof(kScenarios[0])))

static const Card* findCard(const char* name)
{
    if (!name) name = "blank";
    for (size_t i = 0; i < sizeof(kCards) / sizeof(kCards[0]); i++)
        if (!strcmp(kCards[i].name, name)) return &kCards[i];
    fprintf(stderr, "unknown card: %s\n", name);
    exit(2);
}

// FlailerScreenList::JoyHandler's first stop: a popup that is up takes the
// pad's event before the screen hears of it.
static int popupJoy(BGameFlow* gf, int ev)
{
    return bpopup_joy(gf, 0, ev, 1);
}

static uint8_t sFred[BMC_SAVE_SIZE];

// The Autosave screen's completion callback, as the end of a race hands it
// one: on to the next screen, here the main menu. memcard.c says
// "autosave done" before it calls this.
static BGameFlow* sAutosaveFlow;

static void wAutosaveDone(void)
{
    bgf_change_to_screen(sAutosaveFlow, "New Main Menu", 0);
}

// Quit's: a message posted to the race, with the Autosave screen still up.
static void wAutosaveStay(void)
{
}

static void runScenario(const Scenario* sc)
{
    BGameFlow      gf;
    BGameFlowHooks hooks;
    BAnimHooks     animHooks;
    World          w;
    BAnim          anim;

    printf("scenario %s\n", sc->name);

    memset(&w, 0, sizeof(w));
    w.sc          = sc;
    w.card        = findCard(sc->card);
    w.gf          = &gf;
    w.loaderDue   = LOADER_FRAMES;
    w.replaysLeft = sc->replays;
    memcpy(w.objs, kPopupObjs, sizeof(w.objs));

    memset(&hooks, 0, sizeof(hooks));
    hooks.user                    = &w;
    hooks.trace                   = wTrace;
    hooks.setScreenVisible        = wSetScreenVisible;
    hooks.setObjectVisible        = wSetObjectVisible;
    hooks.setGroupVisible         = wSetGroupVisible;
    hooks.changeTexture           = wChangeTexture;
    hooks.openScreen              = wOpenScreen;
    hooks.enterScreen             = wEnterScreen;
    hooks.leaveScreen             = wLeaveScreen;
    hooks.activeMenuItem          = wActiveMenuItem;
    hooks.movieOpen               = wMovieOpen;
    hooks.movieDrive              = wMovieDrive;
    hooks.movieClose              = wMovieClose;
    hooks.loadResource            = wLoadResource;
    hooks.loadSoundRegions        = wLoadSoundRegions;
    hooks.loadTexture             = wLoadTexture;
    hooks.textureReady            = wTextureReady;
    hooks.unloadTexture           = wUnloadTexture;
    hooks.newFileSys              = wNewFileSys;
    hooks.sound                   = wSound;
    hooks.jukebox                 = wJukebox;
    hooks.songMonitorReset        = wSongMonitorReset;
    hooks.gameType                = wGameType;
    hooks.raceDemo                = wRaceDemo;
    hooks.easterEggs              = wEasterEggs;
    hooks.moveBrackets            = wMoveBrackets;
    hooks.setBlurb                = wSetBlurb;
    hooks.startDemoMode           = wStartDemoMode;
    hooks.replayConsiderLaunching = wReplayConsider;
    hooks.replayLaunch            = wReplayLaunch;
    hooks.panelMovieOpen          = wPanelOpen;
    hooks.panelMovieUpdate        = wPanelUpdate;
    hooks.inGame                  = wInGame;

    bgf_init(&gf, kGameFlowStates, BGF_NUM_STATES,
             kScreens, (int)(sizeof(kScreens) / sizeof(kScreens[0])),
             kBootStages, (int)(sizeof(kBootStages) / sizeof(kBootStages[0])),
             &hooks);

    gf.videoMode          = sc->videoMode;
    gf.skipMovies         = sc->skipMovies;
    gf.frontendLaunchType = sc->frontendLaunchType;
    gf.demoModeStatus     = sc->demoModeStatus;
    gf.forceLegalScreens  = sc->forceLegal;
    gf.autoloadManual     = sc->manual;
    gf.saveAskCreate      = sc->askCreate;
    memset(sFred, 0, sizeof(sFred));
    gf.fred       = sFred;
    sAutosaveFlow = &gf;

    // The animation kit: the title's bloom, which finds nothing on its
    // screen and only keeps its timers, and the popup's screen, which is
    // the world above.
    setupAnimHooks(&animHooks, &w);
    banim_init(&anim, &animHooks);
    gf.anim = &anim;

    // InitializeEverything's LoadGlobalChunks, then the scenario's language.
    bgf_load_global_chunks(&gf);
    if (sc->currLanguage == -1) {
        printf("input no language\n");
        gf.currLanguage = -1;
    } else if (sc->currLanguage != 0) {
        printf("input language %d\n", sc->currLanguage);
        bgf_set_curr_language(&gf, sc->currLanguage);
    }

    // main (0x0012da88): ask for LOADING_FRONTEND, then hand over to
    // MainLoop. SkipFE would call StartSkipFEGame instead; it ships as 0.
    bgf_change_state(&gf, BGF_LOADING_FRONTEND, BGF_NONE);

    for (int f = 0; f < sc->frames; f++) {
        for (int i = 0; i < MAX_INPUTS; i++) {
            const char* what = sc->input[i].what;
            if (!what || sc->input[i].frame != f) continue;
            if (!strcmp(what, "loadsave") || !strcmp(what, "autosave")) {
                // Options' Load/Save, or the race's end's save, over the
                // main menu.
                printf("input %s\n", what);
                bgf_push_screen(&gf, "New Main Menu");
                bgf_change_to_screen(&gf, what[0] == 'l' ? "Phils Load Save"
                                                         : "Autosave", 0);
            } else if (!strcmp(what, "picksave") || !strcmp(what, "pickload")) {
                // SELECT on the Save or the Load line.
                printf("input %s\n", what);
                bgf_menu_item_event(&gf, BMSG_MENUITEM_SELECT,
                                    what[4] == 's' ? BMC_ITEM_SAVE
                                                   : BMC_ITEM_LOAD, 0);
            } else if (!strcmp(what, "asleft") || !strcmp(what, "asright")) {
                // The d-pad on the Autosave line.
                printf("input %s\n", what);
                bgf_menu_item_event(&gf, what[2] == 'l' ? BMSG_MENUITEM_PAD_LEFT
                                                        : BMSG_MENUITEM_PAD_RIGHT,
                                    BMC_ITEM_AUTOSAVE, 0);
            } else if (!strcmp(what, "litesave") || !strcmp(what, "liteauto")) {
                // MENUITEM_HIGHLIGHT on the Save or the Autosave line.
                printf("input %s\n", what);
                bgf_menu_item_event(&gf, BMSG_MENUITEM_HIGHLIGHT,
                                    what[4] == 's' ? BMC_ITEM_SAVE
                                                   : BMC_ITEM_AUTOSAVE, 0);
            } else if (!strcmp(what, "fredautosave")) {
                // Autosave on, as a loaded profile can have it.
                printf("input fredautosave\n");
                memset(sFred + BMC_FRED_AUTOSAVE, 0, 4);
                sFred[BMC_FRED_AUTOSAVE] = 1;
            } else if (!strcmp(what, "autosavecb")) {
                // The race's end's SetAutosaveCompletionCallback.
                printf("input autosavecb\n");
                bgf_set_autosave_completion_callback(&gf, wAutosaveDone);
            } else if (!strcmp(what, "autosavestay")) {
                printf("input autosavestay\n");
                bgf_set_autosave_completion_callback(&gf, wAutosaveStay);
            } else if (!strcmp(what, "select")) {
                printf("input select\n");
                if (!popupJoy(&gf, BJOY_MENU_SELECT))
                    bgf_screen_event(&gf, BMSG_MENUITEM_SELECT, 0);
            } else if (!strcmp(what, "start")) {
                // START with no menu, as main.c sends it.
                printf("input start\n");
                if (!popupJoy(&gf, BJOY_START))
                    bgf_screen_event(&gf, BMSG_SCREEN_START_BUTTON, 0);
            } else if (!strcmp(what, "back")) {
                // The pad's BACK, from port 0.
                printf("input back\n");
                if (!popupJoy(&gf, BJOY_MENU_BACK)) bgf_back_button(&gf, 0);
            } else if (!strcmp(what, "left") || !strcmp(what, "right")
                       || !strcmp(what, "up") || !strcmp(what, "down")) {
                // The d-pad, which only a popup hears here.
                int ev = what[0] == 'l' ? BJOY_SCROLL_LEFT
                       : what[0] == 'r' ? BJOY_SCROLL_RIGHT
                       : what[0] == 'u' ? BJOY_SCROLL_UP
                                        : BJOY_SCROLL_DOWN;
                printf("input %s\n", what);
                popupJoy(&gf, ev);
            } else if (!strncmp(what, "item", 4)) {
                // A menu item selected by hash, the way FlailerMenu sends
                // it: "item<n>" is MENUITEM_n.
                unsigned n = (unsigned)(what[4] - '1');
                printf("input %s\n", what);
                bgf_menu_item_event(&gf, BMSG_MENUITEM_SELECT,
                                    BGF_ITEM_MENUITEM_1 + n, 0);
            } else if (!strncmp(what, "hl", 2)) {
                // The highlight moved to MENUITEM_n.
                printf("input %s\n", what);
                w.activeItem = BGF_ITEM_MENUITEM_1 + (unsigned)(what[2] - '1');
            } else if (!strncmp(what, "hi", 2)) {
                // ... and FlailerMenu said so: MENUITEM_HIGHLIGHT for
                // MENUITEM_n, as bmenu sends it on entry and on a move.
                unsigned n = (unsigned)(what[2] - '1');
                printf("input %s\n", what);
                w.activeItem = BGF_ITEM_MENUITEM_1 + n;
                bgf_menu_item_event(&gf, BMSG_MENUITEM_HIGHLIGHT,
                                    BGF_ITEM_MENUITEM_1 + n, 0);
            } else if (!strncmp(what, "slow", 4)) {
                // A slow loader: nothing lands before frame n.
                printf("input %s\n", what);
                w.loaderDue = atoi(what + 4);
            } else if (!strcmp(what, "optionsmovie")) {
                // OptionsScreenBase's constructor's StartMovie (0x001f4da4),
                // the screen itself not being ported.
                printf("input optionsmovie\n");
                bgf_start_movie(&gf, "MOVIES\\options_movie_new.AVI");
            } else if (!strcmp(what, "ingame")) {
                // InGameFlag up, as the race's loading sets it.
                printf("input ingame\n");
                w.inGame = 1;
            } else if (!strcmp(what, "outgame")) {
                // ... and down again, as the race's end clears it.
                printf("input outgame\n");
                w.inGame = 0;
            } else if (!strcmp(what, "race")) {
                // StartRace from the frontend: ChangeGameFlow(
                // UNLOADING_FRONTEND, NONE).
                printf("input race\n");
                bgf_change_state(&gf, BGF_UNLOADING_FRONTEND, BGF_NONE);
            } else if (!strcmp(what, "mumbo")) {
                printf("input mumbo\n");
                bgf_push_screen(&gf, "New Main Menu");
                bgf_change_to_screen(&gf, "Legal MumboJumbo", 0);
            } else if (!strcmp(what, "pushvet")) {
                printf("input pushvet\n");
                bgf_push_screen(&gf, "View Event Tree");
            } else if (!strcmp(what, "pushqr")) {
                printf("input pushqr\n");
                bgf_push_screen(&gf, "Quick Race");
            }
        }
        bgf_frame(&gf, sc->dt);
        wServiceLoads(&w);
        wServiceReplay(&w);
        printf("frame %d %u %u\n", f, (unsigned)gf.realTime,
               (unsigned)gf.realTimer);
    }

    {
        uint32_t autosave;
        memcpy(&autosave, sFred + BMC_FRED_AUTOSAVE, 4);
        printf("final %s %s %d cops %d language %d autosave %08x\n",
               bgf_state_name(&gf, gf.current),
               gf.screen ? gf.screen->name : "-", gf.stack.index, gf.copsOn,
               gf.currLanguage, (unsigned)autosave);
    }
    // Whatever is still open, as the next boot would find it.
    if (gf.autoloadActive) memcard_boot_autoloader_destroy(&gf.autoload);
    if (gf.loadSaveActive) memcard_load_save_destroy(&gf.loadSave);
    if (gf.autosaverActive) memcard_autosaver_destroy(&gf.autosaver);
}

int main(int argc, char** argv)
{
    if (argc < 2) {
        for (int i = 0; i < NUM_SCENARIOS; i++) runScenario(&kScenarios[i]);
        return 0;
    }
    for (int a = 1; a < argc; a++) {
        int found = 0;
        for (int i = 0; i < NUM_SCENARIOS; i++) {
            if (strcmp(kScenarios[i].name, argv[a])) continue;
            runScenario(&kScenarios[i]);
            found = 1;
        }
        if (!found) {
            fprintf(stderr, "unknown scenario: %s\n", argv[a]);
            return 2;
        }
    }
    return 0;
}
