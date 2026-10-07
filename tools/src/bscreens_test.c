// Host harness for the three frontend screens.
//
// Builds "3DS Files/source/bscreens.c" and "gameflow.c" for the host and
// drives Cops On Mode Select, Cops Off Mode Select and the Options screen
// through a fixed set of scenarios, printing everything observable: the
// flow's own trace, the screen-list transitions, and every BScreensHooks
// call the screens make.
//
//     scenario <name>
//     <the flow trace: change, enter, leave, msg, stack, want, ...>
//     <the screens' trace: ctor, dtor, bracket, blurb, select, exit, ...>
//     hook <what> ...
//     frame <n> <realTime> <realTimer>
//     final screen <name> cops <n> beacop <n> ...
//
// tools/bscreens_check.py prints the same from an independent Python model
// and diffs the two, the way bootflow_check.py does for the boot sequence.
// Nothing here reads a bundle: these screens are behaviour, and the point of
// the diff is to catch a misread of the behaviour. The layout half -- that
// MI_3_MASK really is where the third label sits -- is checked against
// FRONTB.BUN by tools/flailer_dump.py instead.
//
// Usage: bscreens_test [scenario]...      (no argument runs them all)

#include <stdio.h>
#include <string.h>

#include "bscreens.h"

// --------------------------------------------------------------- the world

static void wTrace(void* user, const char* line)
{
    (void)user;
    printf("%s\n", line);
}

// The menu is built before SCREEN_ACTIVATE and activated after it.
static void wOpenScreen(void* user, const BScreenConfig* cfg)
{
    (void)user;
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

// gameflow.c traces all three of these itself, immediately before it calls
// the hook, so a hook that printed would double every line. They are here to
// show the port is calling them, not to say anything.
static void wSetScreenVisible(void* u, uint32_t s, int v)
{ (void)u; (void)s; (void)v; }

static void wSetObjectVisible(void* u, uint32_t s, uint32_t o, int v)
{ (void)u; (void)s; (void)o; (void)v; }

static void wSound(void* user, int ev) { (void)user; (void)ev; }

// ------------------------------------------------------------ the hooks

static void hGray(void* user, uint32_t screen, uint32_t item,
                  BScrGrayMode mode)
{
    (void)user;
    printf("hook gray %08x %08x %d\n", (unsigned)screen, (unsigned)item,
           (int)mode);
}

static void hBlurb(void* user, uint32_t screen, int blurbId)
{
    (void)user;
    printf("hook blurb %08x %d\n", (unsigned)screen, blurbId);
}

static void hBrackets(void* user, uint32_t screen, uint32_t mask,
                      float under, float over)
{
    (void)user;
    printf("hook brackets %08x %08x %.1f %.1f\n", (unsigned)screen,
           (unsigned)mask, under, over);
}

static void hStartMovie(void* user, const char* path)
{
    (void)user;
    printf("hook movie %s\n", path);
}

static void hStopMovie(void* user) { (void)user; printf("hook movie stop\n"); }

static void hJukebox(void* user, int start)
{
    (void)user;
    printf("hook jukebox %d\n", start);
}

static void hDisplayStart(void* user)
{
    (void)user;
    printf("hook display start\n");
}

static void hQuickRace(void* user, int transmission)
{
    (void)user;
    printf("hook quickrace transmission %d\n", transmission);
}

// -------------------------------------------------- the Flailer bundle

// What FRONTB.BUN gives the animation kit, cut down to the objects it asks
// about. Nothing here prints: banim's own traffic is tools/banim_check.py's
// business, and what this file is for is what the SCREENS do -- which is
// why the world exists at all. The exit-animation durations that used to be
// three hand-computed constants in bscreens.h now come out of this table,
// because tSlideOutAnimation takes the longest duration of the
// MENUITEM_i_GROUPs it finds.
//
// The counts are from the bundle: MENUITEM_i_GROUP for i = 1..4 on Cops On,
// 1..3 on Cops Off and 1..7 on Options. Group i runs for 0.05 + 0.05i
// seconds, so the longest is the last one and the three screens take
// 0.25s, 0.20s and 0.40s -- the three constants bscreens.h used to spell
// out by hand. UNDERSCORE_GROUP is then added at that same duration, which
// is why the numbers do not move when the brackets join in.
typedef struct WObject {
    uint32_t screen;
    uint32_t name;
    uint32_t group;
    int      type;
    float    x, y;
} WObject;

#define W_GROUP(i) (0x59c1995eu + (unsigned)(i) * 1291467969u)

static WObject g_world[64];
static int     g_numWorld;

static void addObject(uint32_t screen, uint32_t name, uint32_t group,
                      int type, float x, float y)
{
    WObject* o;
    if (g_numWorld >= (int)(sizeof(g_world) / sizeof(g_world[0]))) return;
    o = &g_world[g_numWorld++];
    o->screen = screen;
    o->name   = name;
    o->group  = group;
    o->type   = type;
    o->x      = x;
    o->y      = y;
}

static void addScreenObjects(uint32_t screen, int numItems)
{
    for (int i = 1; i <= numItems; i++) {
        addObject(screen, BSCR_MI_MASK(i), W_GROUP(i), BANIM_TYPE_BITMAP,
                  100.0f, 50.0f + (float)(i - 1) * 20.0f);
        addObject(screen, BSCR_ITEM_MENUITEM(i), W_GROUP(i),
                  BANIM_TYPE_TEXT, 120.0f, 50.0f + (float)(i - 1) * 20.0f);
    }
    addObject(screen, BSCR_OBJ_MI_UNDERSCORE, BSCR_GROUP_UNDERSCORE,
              BANIM_TYPE_BITMAP, 95.0f, 50.0f);
    addObject(screen, BSCR_OBJ_MI_OVERSCORE, BSCR_GROUP_UNDERSCORE,
              BANIM_TYPE_BITMAP, 95.0f, 44.0f);
    addObject(screen, BSCR_OBJ_SCROLLING_TEXT, 0, BANIM_TYPE_TEXT,
              40.0f, 200.0f);
    addObject(screen, BSCR_OBJ_WHITEOUT_BAR, 0, BANIM_TYPE_BITMAP,
              40.0f, 198.0f);
    addObject(screen, BSCR_OBJ_BLOOM_TEXT, 0, BANIM_TYPE_TEXT, 0.0f, 0.0f);
    addObject(screen, BSCR_OBJ_BLOOM_TEXT_2, 0, BANIM_TYPE_TEXT, 0.0f, 0.0f);
}

static void buildWorld(void)
{
    g_numWorld = 0;
    addScreenObjects(BSCR_SCREEN_COPS_ON_MODE_SELECT, 4);
    addScreenObjects(BSCR_SCREEN_COPS_OFF_MODE_SELECT, 3);
    addScreenObjects(BSCR_SCREEN_OPTIONS, 7);
}

static WObject* wFind(uint32_t screen, uint32_t name, int type)
{
    for (int i = 0; i < g_numWorld; i++) {
        if (g_world[i].screen != screen || g_world[i].name != name) continue;
        if (type != BANIM_TYPE_ANY && g_world[i].type != type) continue;
        return &g_world[i];
    }
    return NULL;
}

static int aObjectExists(void* u, uint32_t s, uint32_t o, int t)
{ (void)u; return wFind(s, o, t) != NULL; }

static int aGroupExists(void* u, uint32_t s, uint32_t g, int t)
{
    (void)u;
    if (!g) return 0;
    for (int i = 0; i < g_numWorld; i++) {
        if (g_world[i].screen != s || g_world[i].group != g) continue;
        if (t != BANIM_TYPE_ANY && g_world[i].type != t) continue;
        return 1;
    }
    return 0;
}

static int aObjectType(void* u, uint32_t s, uint32_t o)
{ WObject* p = wFind(s, o, BANIM_TYPE_ANY); (void)u; return p ? p->type : 0; }

static void aGetTopLeft(void* u, uint32_t s, uint32_t o, float* x, float* y)
{
    WObject* p = wFind(s, o, BANIM_TYPE_ANY);
    (void)u;
    if (!p) return;
    *x = p->x;
    *y = p->y;
}

static void aSetTopLeft(void* u, uint32_t s, uint32_t o, float x, float y)
{
    WObject* p = wFind(s, o, BANIM_TYPE_ANY);
    (void)u;
    if (!p) return;
    p->x = x;
    p->y = y;
}

static void aSetGroupPos(void* u, uint32_t s, uint32_t g, uint32_t m,
                         float x, float y)
{
    WObject* master = wFind(s, m, BANIM_TYPE_ANY);
    float    dx, dy;
    (void)u;
    if (!master) return;
    dx = x - master->x;
    dy = y - master->y;
    for (int i = 0; i < g_numWorld; i++) {
        if (g_world[i].screen != s || g_world[i].group != g) continue;
        g_world[i].x += dx;
        g_world[i].y += dy;
    }
    if (master->group != g) {
        master->x = x;
        master->y = y;
    }
}

// The rest of the kit's world is write-only as far as these scenarios are
// concerned -- alphas, colours, scales and strings change nothing the
// screens can see -- so the hooks that only set are left unimplemented and
// the ones that read answer with the authored value.
static int aGetAlpha(void* u, uint32_t s, uint32_t o, int corner)
{ (void)u; (void)s; (void)o; (void)corner; return 128; }

static void aGetScale(void* u, uint32_t s, uint32_t o, float* sx, float* sy)
{ (void)u; (void)s; (void)o; *sx = 1.0f; *sy = 1.0f; }

static const char* aTranslate(void* u, int id)
{
    static char buf[32];
    (void)u;
    snprintf(buf, sizeof(buf), "<string %d>", id);
    return buf;
}

static void setupAnimHooks(BAnimHooks* h)
{
    memset(h, 0, sizeof(*h));
    h->objectExists = aObjectExists;
    h->groupExists  = aGroupExists;
    h->objectType   = aObjectType;
    h->getTopLeft   = aGetTopLeft;
    h->setTopLeft   = aSetTopLeft;
    h->setGroupPos  = aSetGroupPos;
    h->getAlpha     = aGetAlpha;
    h->getScale     = aGetScale;
    h->translate    = aTranslate;
    // changeToScreen and trace are bscreens.c's; it installs its own over
    // whatever is passed here, because both are free functions on a global
    // in the original and neither belongs to the bundle.
}

// ------------------------------------------------------------ the registry

// Only the three. The boot screens are bootflow_check.py's business, and
// leaving them out keeps every destination these three name -- Challenge,
// View Event Tree, Audio Options and the rest -- unregistered, which is
// exactly what the port can honestly claim today. "Options" is the one
// exception: both Mode Selects have a row that goes there, and it is here.
static const BScreenConfig kScreens[] = {
    { "Cops On Mode Select",  BSCR_SCREEN_COPS_ON_MODE_SELECT,
      bscr_cops_on_callback },
    { "Cops Off Mode Select", BSCR_SCREEN_COPS_OFF_MODE_SELECT,
      bscr_cops_off_callback },
    { "Options",              BSCR_SCREEN_OPTIONS,
      bscr_options_callback },
};

static const BGameFlowStateInfo kStates[BGF_NUM_STATES] = {
    { "NONE",                     NULL, NULL, NULL },
    { "LOADING_FRONTEND",         NULL, NULL, NULL },
    { "UNLOADING_FRONTEND",       NULL, NULL, NULL },
    { "IN_FRONTEND",              NULL, NULL, NULL },
    { "LOADING_TRACK_COMMON",     NULL, NULL, NULL },
    { "LOADING_TRACK_SPECIFIC",   NULL, NULL, NULL },
    { "RACING",                   NULL, NULL, NULL },
    { "UNLOADING_TRACK_SPECIFIC", NULL, NULL, NULL },
    { "UNLOADING_TRACK_COMMON",   NULL, NULL, NULL },
};

// ------------------------------------------------------------- scenarios

#define SIXTIETH (1.0f / 60.0f)

typedef struct {
    const char* name;
    const char* screen;     // where the scenario starts
    int         videoMode;  // MODE_PAL = 0, MODE_NTSC = 1
    int         copsOn;     // Fred.MainMenuOpts.mPolice
    int         frames;
    struct { int frame; const char* what; } input[8];
} Scenario;

static const Scenario kScenarios[] = {
    // Every item highlighted in turn: four brackets, four blurbs, and a
    // fifth MENUITEM the switch has a case for but the bundle never draws.
    { "copson_highlight", "Cops On Mode Select", 1, 1, 8,
      {{1,"h1"},{2,"h2"},{3,"h3"},{4,"h4"},{5,"h5"},{6,"hx"},{0,0}} },
    // Challenge: Boost and BeACop are written now, the screen changes when
    // the slide-out finishes 0.25s later -- 16 frames at 1/60, because
    // RealTimer gains 66 a frame and the animation wants 1000.
    { "copson_challenge", "Cops On Mode Select", 1, 1, 24,
      {{2,"h3"},{3,"s3"},{0,0}} },
    // Quick Race has no exit animation at all: it stops the panel movie and
    // hands the race its parameters on the spot.
    { "copson_quick", "Cops On Mode Select", 1, 1, 8,
      {{2,"h1"},{3,"s1"},{0,0}} },
    // The same with the transmission button held. Pressed before the
    // select and still down at it, which is the only thing that matters.
    { "copson_gearbox", "Cops On Mode Select", 1, 1, 8,
      {{1,"xon"},{2,"h1"},{3,"s1"},{0,0}} },
    // Held and then released before the select: automatic again.
    { "copson_gearbox_off", "Cops On Mode Select", 1, 1, 8,
      {{1,"xon"},{2,"xoff"},{3,"s1"},{0,0}} },
    // Quick Race and Ultimate Road Racer on a second pad do nothing and
    // eat the click; Challenge on a second pad works.
    { "copson_port1", "Cops On Mode Select", 1, 1, 10,
      {{2,"P1"},{4,"P4"},{6,"P3"},{0,0}} },
    // BACK and the pad during the slide-out. The animation vetoes BACK and
    // consumes PAD_UP, so neither reaches the menu; the change still lands
    // on the frame the stopwatch runs out.
    { "copson_locked", "Cops On Mode Select", 1, 1, 24,
      {{2,"s4"},{4,"back"},{6,"up"},{8,"down"},{0,0}} },
    // The dead row: MENUITEM_5 is a case in both switches with no object in
    // FRONTB.BUN. Driven by hash anyway, it is the one destination of the
    // five that is registered.
    { "copson_options", "Cops On Mode Select", 1, 1, 24,
      {{2,"s5"},{0,0}} },
    // Cops Off: three authored items, a 0.20s slide-out (13 frames), and
    // World Championship writing the other GameType.
    { "copsoff_highlight", "Cops Off Mode Select", 1, 0, 8,
      {{1,"h1"},{2,"h2"},{3,"h3"},{4,"h4"},{0,0}} },
    { "copsoff_worldchamp", "Cops Off Mode Select", 1, 0, 20,
      {{2,"h3"},{3,"s3"},{0,0}} },
    // Quick Race off the cops-off screen: seven AI cars instead of three,
    // no cops, and a different grid slot.
    { "copsoff_quick", "Cops Off Mode Select", 1, 0, 8,
      {{2,"h1"},{3,"s1"},{0,0}} },
    // PAL Options: seven items, seven blurbs, and the brackets on the
    // other pair of offsets.
    { "options_pal", "Options", 0, 0, 10,
      {{1,"h1"},{2,"h3"},{3,"h5"},{4,"h7"},{5,"hx"},{0,0}} },
    // NTSC: no language to pick, so MENUITEM_7 is disabled AND hidden at
    // construction.
    { "options_ntsc", "Options", 1, 0, 6, {{1,"h7"},{0,0}} },
    // Audio slides out over 0.40s (25 frames); Display does the same and
    // takes the display manager's snapshot first.
    { "options_audio", "Options", 0, 0, 32, {{2,"h1"},{3,"s1"},{0,0}} },
    { "options_display", "Options", 0, 0, 32, {{2,"h3"},{3,"s3"},{0,0}} },
    // Credits changes screen on the spot, with no animation at all.
    { "options_credits", "Options", 0, 0, 8, {{2,"h6"},{3,"s6"},{0,0}} },
    // An item hash that is not a MENUITEM_n: the highlight leaves the mask
    // at 0 and runs anyway, and the select builds an exit animation to an
    // empty screen name, which after 0.40s resolves to nothing at all.
    { "options_unknown", "Options", 0, 0, 32, {{2,"hx"},{3,"sx"},{0,0}} },
};
#define NUM_SCENARIOS ((int)(sizeof(kScenarios) / sizeof(kScenarios[0])))

static BScreens g_screens;

static void doInput(BGameFlow* gf, const char* what)
{
    printf("input %s\n", what);
    if (!strcmp(what, "back")) {
        // The pad's BACK, which the screen hears first.
        bgf_back_button(gf, 0);
    } else if (!strcmp(what, "up")) {
        bgf_menu_item_event(gf, BMSG_MENUITEM_PAD_UP,
                            BSCR_ITEM_MENUITEM(1), 0);
    } else if (!strcmp(what, "down")) {
        bgf_menu_item_event(gf, BMSG_MENUITEM_PAD_DOWN,
                            BSCR_ITEM_MENUITEM(1), 0);
    } else if (!strcmp(what, "xon")) {
        bscr_joy(&g_screens, 0, BSCR_JOY_SELECT_TRANSMISSION, 1);
    } else if (!strcmp(what, "xoff")) {
        bscr_joy(&g_screens, 0, BSCR_JOY_SELECT_TRANSMISSION, 0);
    } else if (!strcmp(what, "hx")) {
        bgf_menu_item_event(gf, BMSG_MENUITEM_HIGHLIGHT, 0xdeadbeefu, 0);
    } else if (!strcmp(what, "sx")) {
        bgf_menu_item_event(gf, BMSG_MENUITEM_SELECT, 0xdeadbeefu, 0);
    } else if (what[0] == 'h') {
        bgf_menu_item_event(gf, BMSG_MENUITEM_HIGHLIGHT,
                            BSCR_ITEM_MENUITEM(what[1] - '0'), 0);
    } else if (what[0] == 's') {
        bgf_menu_item_event(gf, BMSG_MENUITEM_SELECT,
                            BSCR_ITEM_MENUITEM(what[1] - '0'), 0);
    } else if (what[0] == 'P') {
        // The same select, on the second pad.
        bgf_menu_item_event(gf, BMSG_MENUITEM_SELECT,
                            BSCR_ITEM_MENUITEM(what[1] - '0'), 1);
    }
}

static void runScenario(const Scenario* sc)
{
    BGameFlow      gf;
    BGameFlowHooks hooks;
    BScreensHooks  sh;
    BAnimHooks     ah;

    printf("scenario %s\n", sc->name);

    memset(&hooks, 0, sizeof(hooks));
    hooks.trace            = wTrace;
    hooks.openScreen       = wOpenScreen;
    hooks.enterScreen      = wEnterScreen;
    hooks.leaveScreen      = wLeaveScreen;
    hooks.setScreenVisible = wSetScreenVisible;
    hooks.setObjectVisible = wSetObjectVisible;
    hooks.sound            = wSound;

    bgf_init(&gf, kStates, BGF_NUM_STATES,
             kScreens, (int)(sizeof(kScreens) / sizeof(kScreens[0])),
             NULL, 0, &hooks);
    gf.videoMode = sc->videoMode;
    gf.copsOn    = sc->copsOn;

    memset(&sh, 0, sizeof(sh));
    sh.grayMenuItem        = hGray;
    sh.setBlurb            = hBlurb;
    sh.moveBrackets        = hBrackets;
    sh.startMovie          = hStartMovie;
    sh.stopMovie           = hStopMovie;
    sh.jukebox             = hJukebox;
    sh.displayOptionsStart = hDisplayStart;
    sh.startQuickRace      = hQuickRace;
    // After the two gf fields: bscr_init takes its copy of VIDEO_MODE here.
    bscr_init(&g_screens, &gf, &sh);

    buildWorld();
    setupAnimHooks(&ah);
    bscr_set_anim_hooks(&g_screens, &ah);

    // No boot sequence. The flow is parked in NONE with nothing to service,
    // and the scenario drops straight onto the screen under test -- which
    // is also why the stack starts empty, so BACK has nowhere to go.
    bgf_change_to_screen(&gf, sc->screen, 0);

    for (int f = 0; f < sc->frames; f++) {
        for (int i = 0; i < 8; i++) {
            if (!sc->input[i].what || sc->input[i].frame != f) continue;
            doInput(&gf, sc->input[i].what);
        }
        bgf_frame(&gf, SIXTIETH);
        printf("frame %d %u %u\n", f, (unsigned)gf.realTime,
               (unsigned)gf.realTimer);
    }

    printf("final screen %s cops %d beacop %d gametype %d cars %d tree %d "
           "boost %d ticks %d %d %d\n",
           gf.screen ? gf.screen->name : "-", gf.copsOn, g_screens.beACop,
           g_screens.gameType, g_screens.numPlayerCars,
           g_screens.eventTreeType, g_screens.boost,
           g_screens.copsOn.tickCount, g_screens.copsOff.tickCount,
           g_screens.options.tickCount);
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
