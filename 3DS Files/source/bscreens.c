#include "bscreens.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

// The three screens NewMainMenu leads to. See bscreens.h for the shape and
// docs/formats/frontend-screens.md for the decompilation.

// FlailerScreenConfig::Callback is a free function with no user pointer, so
// the screen it belongs to has to be found some other way. The original
// keeps one file-static pointer per class -- gp[-16848] for CopsOnModeSelect,
// gp[-17632] for OptionsScreenBase -- and news/deletes the object around it
// on SCREEN_ACTIVATE / SCREEN_UNACTIVATE. This is the same thing with the
// three instances living inside one BScreens the caller owns.
static BScreens* g_screens;

static void trace(BScreens* s, const char* fmt, ...)
{
    char    line[192];
    va_list ap;
    if (!s || !s->gf || !s->gf->hooks.trace) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    s->gf->hooks.trace(s->gf->hooks.user, line);
}

#define HOOK(s, fn, ...) \
    do { if ((s)->hooks.fn) (s)->hooks.fn((s)->hooks.user, __VA_ARGS__); } while (0)

// The same, for the hooks whose only argument is the user pointer. A
// variadic macro with an empty __VA_ARGS__ is not c11, so the
// no-argument case needs its own spelling rather than a dummy 0.
#define HOOK0(s, fn) \
    do { if ((s)->hooks.fn) (s)->hooks.fn((s)->hooks.user); } while (0)

// banim's ChangeToScreen and trace hooks. Both are free functions on a
// global in the original -- ChangeToScreen (0x0014a438) walks the one
// FlailerScreenList and bPrintf writes to the one console -- so neither
// needs the user pointer, and taking the instance from g_screens is what
// lets BAnimHooks keep a single `user` for the Flailer side.
static void animChangeToScreen(void* user, const char* name, int push)
{
    BScreens* s = g_screens;
    (void)user;
    if (s) bgf_change_to_screen(s->gf, name, push);
}

static void animTrace(void* user, const char* line)
{
    BScreens* s = g_screens;
    (void)user;
    if (s && s->gf && s->gf->hooks.trace)
        s->gf->hooks.trace(s->gf->hooks.user, line);
}

static void installAnimHooks(BScreens* s, const BAnimHooks* hooks)
{
    banim_init(&s->anim, hooks);
    s->anim.hooks.changeToScreen = animChangeToScreen;
    s->anim.hooks.trace          = animTrace;
}

void bscr_init(BScreens* s, BGameFlow* gf, const BScreensHooks* hooks)
{
    memset(s, 0, sizeof(*s));
    s->gf = gf;
    if (hooks) s->hooks = *hooks;
    // GetVideoMode (0x001992a0) reads the same VIDEO_MODE the boot flow
    // does, so the two cannot disagree.
    s->videoMode = gf ? gf->videoMode : 0;
    g_screens = s;
    installAnimHooks(s, NULL);
}

void bscr_set_anim_hooks(BScreens* s, const BAnimHooks* hooks)
{
    g_screens = s;
    installAnimHooks(s, hooks);
}

// RealTimer and RealTimeElapsed are one global each in the original, so the
// animation layer is slaved to the flow's copy rather than counting its own.
// Every entry point does this first; it is two stores.
static BAnim* clock(BScreens* s)
{
    if (s->gf) banim_set_clock(&s->anim, (int32_t)s->gf->realTimer,
                               s->gf->realElapsed);
    return &s->anim;
}

// FlailerGetTopLeftPosition's X, for the two places a screen needs to know
// where something was authored: the slide-in target and the underscore's
// start. The kit's hooks are the screens' only window onto the bundle.
static float topLeftX(BScreens* s, uint32_t screen, uint32_t object)
{
    float x = 0.0f, y = 0.0f;
    if (s->anim.hooks.getTopLeft)
        s->anim.hooks.getTopLeft(s->anim.hooks.user, screen, object, &x, &y);
    return x;
}

// ------------------------------------------------------ item hash <-> index

// MENUITEM_n -> n, or 0 for anything else. Both Mode Selects and the Options
// screen do this with `itemHash + 0xad1fc60d` and an unsigned range check --
// 0xad1fc60d is -bhash("MENUITEM_1") -- so a hash that is not one of the
// consecutive MENUITEM_n values falls off the end and the message is simply
// dropped, sound and all.
static int itemIndex(uint32_t itemHash, int numCases)
{
    uint32_t i = itemHash - BSCR_ITEM_MENUITEM(1);
    if (i >= (uint32_t)numCases) return 0;
    return (int)i + 1;
}

// --------------------------------------------------- tExitScreenAnimation

// StartChangeToScreen (0x00203ec8 / 0x00204570 / the Options equivalent):
// a tExitScreenAnimation over the screen's MENUITEM_i_GROUPs, plus one more
// group for UNDERSCORE_GROUP so the two brackets leave with the items. The
// destination name is not copied -- both here and in the original it is a
// pointer into a static table -- which matters because the screen is torn
// down while the animation still holds it.
static void exitStart(BScreens* s, BScreenInstance* inst, const char* name)
{
    BAnim* a = clock(s);
    banim_exit_init(a, &inst->exit, inst->screen, name ? name : "");
    banim_slide_add_group(a, &inst->exit.slide, BSCR_GROUP_UNDERSCORE,
                          BSCR_OBJ_MI_UNDERSCORE,
                          topLeftX(s, inst->screen, BSCR_OBJ_MI_UNDERSCORE),
                          BANIM_OFFSCREEN_X, inst->exit.slide.totalTime);
    inst->exitActive = true;
}

// tExitScreenAnimation::HandleMessages (0x00232b90). Returns true if the
// screen it belongs to has been torn down -- which happens when the
// animation finishes and changes screen -- so the caller stops touching it.
static bool exitHandleMessages(BScreens* s, BScreenInstance* inst,
                               BScreenMessage msg, BScreenCallbackData* data)
{
    int32_t param = data ? data->param : 0;
    int32_t noise = data ? data->noise : 0;
    int     done;

    done = banim_exit_message(clock(s), &inst->exit, (int)msg, &param,
                              &noise);
    if (data) {
        data->param = param;
        data->noise = noise;
    }
    // banim called ChangeToScreen through the hook, which unactivated this
    // screen and cleared `inst`. Nothing here may touch it again.
    return done != 0;
}

// ---------------------------------------------------------- shared helpers

// The half of SetupHighlight (0x00204160 / inside 0x001e55a0) that anything
// outside the animation kit can see: the two brackets move to the current
// item's bounding box and SelectionSet remembers it.
static void setCurrentItem(BScreens* s, BScreenInstance* inst, uint32_t mask,
                           float under, float over)
{
    inst->currentMask = mask;
    HOOK(s, moveBrackets, inst->screen, mask, under, over);
    // SelectionSet::SetCurrentItem (0x001694a8) last, after the brackets.
    bsel_set_current(clock(s), &inst->sel, mask);
    trace(s, "bracket %08x", (unsigned)mask);
}

static void setBlurb(BScreens* s, BScreenInstance* inst, int blurbId)
{
    inst->blurb = blurbId;
    // tAnimatedBlurb::NewText(int) (0x00232f20) looks the id up in LANGTAB
    // and starts the wipe. The hook stays because the game's own idea of a
    // blurb -- which sentence goes with which item -- is not the animation.
    banim_blurb_new_text_id(clock(s), &inst->blurbAnim, blurbId);
    HOOK(s, setBlurb, inst->screen, blurbId);
    trace(s, "blurb %d", blurbId);
}

// The half of every constructor that is the animation kit. `masks` is the
// MI_n_MASK table the screen's SelectionSet is built over: five entries on
// the Mode Selects (0x00313948) and eight on the Options base (0x0029d160),
// in both cases however many the screen actually authors.
static void kitConstruct(BScreens* s, BScreenInstance* inst,
                         const uint32_t* masks, int numMasks)
{
    BAnim* a = clock(s);

    bsel_init(a, &inst->sel, inst->screen);
    // IndicatorMode 1 on every screen that has one, which inverts the
    // sense: the mask over the CURRENT item is the one turned off.
    bsel_set_indicator_mode(&inst->sel, 1);
    bsel_add_items(a, &inst->sel, masks, numMasks);

    banim_blurb_init(a, &inst->blurbAnim, inst->screen,
                     BSCR_OBJ_SCROLLING_TEXT, BSCR_OBJ_SCROLLING_TEXT,
                     BSCR_OBJ_WHITEOUT_BAR);
    banim_highlight_init(a, &inst->bloom, inst->screen, BSCR_OBJ_BLOOM_TEXT,
                         (int32_t)BANIM_BLOOM_COLOR);
    // The target is wherever MI_1_MASK was authored: every group slides to
    // the same X, and the stagger is in the durations, not the distances.
    banim_slide_in_init(a, &inst->slideIn, inst->screen,
                        topLeftX(s, inst->screen, BSCR_MI_MASK(1)));
}

static void kitDestruct(BScreens* s, BScreenInstance* inst)
{
    BAnim* a = clock(s);
    // Reverse order, because that is the order the destructors run in and
    // because each one puts its objects back where it found them.
    if (inst->exitActive) banim_slide_release(a, &inst->exit.slide);
    banim_slide_release(a, &inst->slideIn);
    banim_blurb_release(a, &inst->blurbAnim);
}

// OnTick (0x00204120): SelectionSet::Update, then the three Animate calls.
static void kitTick(BScreens* s, BScreenInstance* inst)
{
    BAnim* a = clock(s);
    bsel_update(&inst->sel);
    banim_blurb_animate(a, &inst->blurbAnim);
    banim_highlight_animate(a, &inst->bloom);
    if (inst->hasBloom2) banim_highlight_animate(a, &inst->bloom2);
    banim_slide_animate(a, &inst->slideIn);
}

void bscr_quick_race_params(const BScreens* s, int transmission,
                            int trackNumber, int point2Point,
                            BQuickRace* out)
{
    // Fred.MainMenuOpts.mPolice, the same flag that picked the Mode Select.
    int cops = (s && s->gf) ? (s->gf->copsOn != 0) : 0;

    memset(out, 0, sizeof(*out));
    out->trackNumber          = trackNumber;
    out->trafficDensity       = 0.33f;
    out->trafficOncoming      = 0.5f;
    out->raceType             = 1;
    out->point2Point          = point2Point;
    out->numLapsInRace        = 2;
    out->numPlayerCars        = 1;
    out->numAICars            = cops ? 3 : 7;
    out->playerStartPosition  = cops ? 2 : 8;
    out->trainingLinesEnabled = 0;
    out->hasObjective         = 0;
    out->objectiveCleared     = 1;
    out->eventTreeRace        = 0;
    out->maxCops              = cops ? 4 : 0;
    out->tickets              = cops;
    out->roadBlocks           = cops;
    out->spikeStrips          = cops;
    out->helicopter           = cops;
    out->ticketsBeforeArrest  = cops ? 2 : 0;
    out->numBeACopRoadBlocks  = 0;
    out->numBeACopChoppers    = 0;
    out->copStrength          = 1;
    out->opponentStrength     = 1;
    out->boost                = 1;
    out->boostScale[0]        = 1.0f;
    out->boostScale[1]        = 1.0f;
    out->gameType             = BSCR_FRED_EXPRESS_GAME;
    out->fredNumPlayerCars    = 1;
    out->transmissionType     = transmission ? 1 : 0;
}

// StartQuickRace (0x00203ae0). The track pick (PickTrackNumberForExpressGame,
// 0x00203530) and Point2Point (GetTrackInfo(track)[67]) come out of the
// track database, which Phase 4 owns, so they arrive as 0 here and the
// parameter block is handed over as-is.
static void startQuickRace(BScreens* s, BScreenInstance* inst)
{
    BQuickRace p;
    bscr_quick_race_params(s, inst->transmission, 0, 0, &p);
    HOOK0(s, stopMovie);
    trace(s, "quickrace cops=%d transmission=%d aicars=%d maxcops=%d start=%d",
          s->gf ? (s->gf->copsOn != 0) : 0, p.transmissionType,
          p.numAICars, p.maxCops, p.playerStartPosition);
    if (s->hooks.startQuickRace) s->hooks.startQuickRace(s->hooks.user, &p);
}

// ------------------------------------------------------- the two Mode Selects

typedef enum {
    BMODE_QUICK_RACE,   // port 0 only -> StartQuickRace
    BMODE_BE_A_COP,     // BeACop = 1
    BMODE_CHALLENGE,    // Boost = 1, BeACop = 0
    BMODE_EVENT_TREE,   // port 0 only -> GameType / NumPlayerCars / tree type
    BMODE_PLAIN,        // straight to the named screen
} BModeAction;

typedef struct {
    int         blurb;      // LanguageID handed to tAnimatedBlurb::NewText
    BModeAction action;
    int         gameType;   // BMODE_EVENT_TREE only
    int         treeType;   // BMODE_EVENT_TREE only
    const char* screen;     // where the exit animation goes
} BModeItem;

typedef struct {
    const char*      name;
    uint32_t         hash;
    const char*      movie;
    bool             doubleTick;   // CopsOnModeSelect ticks twice; see below
    int              numCases;     // cases in the item switch, authored or not
    int              authored;     // MENUITEM_n objects FRONTB.BUN defines
    const BModeItem* items;
} BModeConfig;

// The SelectionSet tables, as they sit in .data. 0x00313948 is five
// entries and both Mode Selects pass it; 0x0029d160 is eight and belongs to
// OptionsScreenBase. Neither is trimmed to the items the screen authors --
// AddItem counts a mask that is not there, and the indices after it would
// shift if the table were shortened.
static const uint32_t kModeMasks[5] = {
    BSCR_MI_MASK(1), BSCR_MI_MASK(2), BSCR_MI_MASK(3), BSCR_MI_MASK(4),
    BSCR_MI_MASK(5),
};

static const uint32_t kOptionMasks[8] = {
    BSCR_MI_MASK(1), BSCR_MI_MASK(2), BSCR_MI_MASK(3), BSCR_MI_MASK(4),
    BSCR_MI_MASK(5), BSCR_MI_MASK(6), BSCR_MI_MASK(7), BSCR_MI_MASK(8),
};

// CopsOnModeSelect::OnHighlight (0x00204218) and ::HandleEvent (0x00203f50).
// The screen's four authored labels are Quick Race / You're The Cop /
// Challenge / Ultimate Road Racer. MENUITEM_5 has a case in both switches
// but no object in FRONTB.BUN, so it is dead on this disc -- kept because
// it is what the code says and because it is the same "-> Options" row the
// other Mode Select carries.
static const BModeItem kCopsOnItems[] = {
    { 10017, BMODE_QUICK_RACE, 0, 0, NULL                },
    { 10014, BMODE_BE_A_COP,   0, 0, "ChallengeBeACop"   },
    { 10012, BMODE_CHALLENGE,  0, 0, "Challenge"         },
    { 10013, BMODE_EVENT_TREE, BSCR_FRED_HOTPURSUIT_GAME, 1,
                                     "View Event Tree"   },
    { 10009, BMODE_PLAIN,      0, 0, "Options"           },
};

// CopsOffModeSelect::OnHighlight (0x00204880) and ::HandleEvent (0x002045f8):
// Quick Race / Challenge / World Championship, and the same dead "Options"
// row -- here it is MENUITEM_4 that FRONTB.BUN never defines.
static const BModeItem kCopsOffItems[] = {
    { 10006, BMODE_QUICK_RACE, 0, 0, NULL              },
    { 10007, BMODE_CHALLENGE,  0, 0, "Challenge"       },
    { 10008, BMODE_EVENT_TREE, BSCR_FRED_ULTIMATE_GAME, 0,
                                     "View Event Tree" },
    { 10009, BMODE_PLAIN,      0, 0, "Options"         },
};

static const BModeConfig kCopsOn = {
    "Cops On Mode Select", BSCR_SCREEN_COPS_ON_MODE_SELECT,
    "MOVIES\\hotpursuit_movie.AVI",
    true, 5, 4, kCopsOnItems,
};

// The space in "worldracing_ movie.AVI" is not a typo here; it is the
// filename the shipped code asks for. Neither movie is on the disc -- the
// MOVIES directory has no hotpursuit_movie.AVI either -- so both Mode
// Selects open a file that is not there and carry on, the same way the
// title screen's second movie does.
static const BModeConfig kCopsOff = {
    "Cops Off Mode Select", BSCR_SCREEN_COPS_OFF_MODE_SELECT,
    "MOVIES\\worldracing_ movie.AVI",
    false, 4, 3, kCopsOffItems,
};

static void modeOnTick(BScreens* s, BScreenInstance* inst)
{
    kitTick(s, inst);
    inst->tickCount++;
}

// The constructor (0x00203d28 / 0x002043d0).
static void modeConstruct(BScreens* s, BScreenInstance* inst,
                          const BModeConfig* cfg, uint32_t screen)
{
    memset(inst, 0, sizeof(*inst));
    inst->live   = true;
    inst->screen = screen;
    HOOK(s, startMovie, cfg->movie);
    // Both Mode Selects pass the same five-entry table (0x00313948) however
    // many items they actually have.
    kitConstruct(s, inst, kModeMasks, 5);
    // AddJoyHandler(port 0, JOY_EVENT_MAIN_MENU_SELECT_TRANSMISSION).
    HOOK(s, jukebox, 1);
    trace(s, "%s ctor %08x", cfg->name, (unsigned)screen);
}

static void modeDestruct(BScreens* s, BScreenInstance* inst,
                         const BModeConfig* cfg)
{
    // RemoveJoyHandler(0, 23), then the animation kit's destructors.
    trace(s, "%s dtor", cfg->name);
    kitDestruct(s, inst);
    memset(inst, 0, sizeof(*inst));
}

static void modeOnHighlight(BScreens* s, BScreenInstance* inst,
                            const BModeConfig* cfg, BScreenCallbackData* data)
{
    int n = itemIndex(data ? data->itemHash : 0, cfg->numCases);
    // SetCurrentMenuItem runs BEFORE the range check and takes the raw
    // hash, so an item the switch does not know about still blooms -- and
    // an unknown hash sets the bloom to an object that is not there, which
    // hides the copy rather than leaving the last one scaled up.
    banim_highlight_set_item(clock(s), &inst->bloom,
                             data ? data->itemHash : 0);
    if (!n) return;
    // SetupHighlight(this, MI_n_MASK, blurb): the brackets first, then the
    // blurb, then SelectionSet::SetCurrentItem.
    setCurrentItem(s, inst, BSCR_MI_MASK(n),
                   BSCR_UNDER_MODE_SELECT, BSCR_OVER_MODE_SELECT);
    setBlurb(s, inst, cfg->items[n - 1].blurb);
}

// Returns true if the screen was torn down.
static bool modeOnSelect(BScreens* s, BScreenInstance* inst,
                         const BModeConfig* cfg, BScreenCallbackData* data)
{
    const BModeItem* item;
    int              n = itemIndex(data ? data->itemHash : 0, cfg->numCases);

    if (!n) return false;
    item = &cfg->items[n - 1];
    trace(s, "select MENUITEM_%d", n);

    switch (item->action) {
        case BMODE_QUICK_RACE:
            // Split screen has its own path; on a second pad this item
            // does nothing and eats the click.
            if (data && data->port != 0) { data->noise = 0; return false; }
            startQuickRace(s, inst);
            return false;

        case BMODE_BE_A_COP:
            s->beACop = 1;
            break;

        case BMODE_CHALLENGE:
            s->boost  = 1;
            s->beACop = 0;
            break;

        case BMODE_EVENT_TREE:
            if (data && data->port != 0) { data->noise = 0; return false; }
            s->gameType      = item->gameType;
            s->numPlayerCars = 1;
            s->eventTreeType = item->treeType;
            break;

        case BMODE_PLAIN:
            break;
    }

    // StartChangeToScreen (0x00203ec8): new tExitScreenAnimation, then one
    // more slide group for the two brackets. The screen change happens when
    // the animation finishes, not now.
    exitStart(s, inst, item->screen);
    return false;
}

static void modeHandleEvent(BScreens* s, BScreenInstance* inst,
                            const BModeConfig* cfg, BScreenMessage msg,
                            BScreenCallbackData* data)
{
    if (msg == BMSG_SCREEN_TICK) modeOnTick(s, inst);

    if (inst->exitActive) {
        exitHandleMessages(s, inst, msg, data);
        return;
    }

    if (msg == BMSG_MENUITEM_HIGHLIGHT) {
        modeOnHighlight(s, inst, cfg, data);
        return;
    }
    if (msg < BMSG_MENUITEM_UNHIGHLIGHT) {           // the `msg < 5` arm
        if (msg == BMSG_MENUITEM_SELECT) modeOnSelect(s, inst, cfg, data);
        return;
    }
    // ...and the `msg >= 5` arm, which tests for SCREEN_TICK again.
    // CopsOnModeSelect therefore runs OnTick twice per tick and
    // CopsOffModeSelect once. Nothing observable depends on it -- OnTick is
    // four animation calls -- but it is a real difference between two
    // screens that are otherwise the same file twice, so the port keeps it.
    if (msg == BMSG_SCREEN_TICK && cfg->doubleTick) modeOnTick(s, inst);
}

// Callback (0x00204338 / 0x00204988).
static void modeCallback(BScreens* s, BScreenInstance* inst,
                         const BModeConfig* cfg, BScreenMessage msg,
                         BScreenCallbackData* data)
{
    if (msg == BMSG_SCREEN_ACTIVATE) {
        modeConstruct(s, inst, cfg, data ? data->itemHash : cfg->hash);
        return;
    }
    if (msg == BMSG_SCREEN_UNACTIVATE) {
        if (inst->live) modeDestruct(s, inst, cfg);
        return;
    }
    // The original tail-calls HandleEvent with whatever pInstance holds,
    // NULL included; it only ever sees NULL if a message arrives outside an
    // activate/unactivate pair, which the screen list does not do.
    if (!inst->live) { trace(s, "%s message with no instance", cfg->name); return; }
    modeHandleEvent(s, inst, cfg, msg, data);
}

void bscr_cops_on_callback(BGameFlow* gf, BScreenMessage msg,
                           BScreenCallbackData* data)
{
    BScreens* s = g_screens;
    (void)gf;
    if (!s) return;
    modeCallback(s, &s->copsOn, &kCopsOn, msg, data);
}

void bscr_cops_off_callback(BGameFlow* gf, BScreenMessage msg,
                            BScreenCallbackData* data)
{
    BScreens* s = g_screens;
    (void)gf;
    if (!s) return;
    modeCallback(s, &s->copsOff, &kCopsOff, msg, data);
}

void bscr_joy(BScreens* s, int port, int joyEvent, int pressed)
{
    if (!s) return;
    if (joyEvent != BSCR_JOY_SELECT_TRANSMISSION) return;
    // AddJoyHandler registers on port 0 only, and only while the screen is
    // up, so no other pad and no other screen can reach this.
    if (port != 0) return;
    if (s->copsOn.live)  s->copsOn.transmission  = pressed;
    if (s->copsOff.live) s->copsOff.transmission = pressed;
}

// ------------------------------------------------------------- the Options

// tOptionsScreen::HandleEvent's SELECT arm (0x001e0b0c). Four of the seven
// items slide the screen out first and three change immediately; the mix is
// not a pattern, it is what each destination needed.
typedef struct {
    int         blurb;       // LanguageID, from the HIGHLIGHT table
    const char* screen;
    bool        immediate;   // true: ChangeToScreen now, no exit animation
    bool        displayStart;// MENUITEM_3 also kicks the display manager
} BOptionItem;

static const BOptionItem kOptionItems[7] = {
    { 100020, "Audio Options",      false, false },  // 1 Audio
    { 100021, "Joystick PreConfig", false, false },  // 2 Controller
    { 100022, "Display Options",    false, true  },  // 3 Display
    { 100023, "Phils Load Save",    true,  false },  // 4 Save/Load
    { 100024, "NameEntry",          false, false },  // 5 Player Names
    { 100025, "Credits",            true,  false },  // 6 Credits
    { 100026, "Language Options",   true,  false },  // 7 Languages
};

// OptionsScreenBase (0x001e53d0) then tOptionsScreen (0x001e09d0).
static void optionsConstruct(BScreens* s, BScreenInstance* inst,
                             uint32_t screen)
{
    memset(inst, 0, sizeof(*inst));
    inst->live   = true;
    inst->screen = screen;
    // The base builds a slide-in animation, two highlight animations and a
    // SelectionSet over MI_1_MASK .. MI_8_MASK (eight, though the screen
    // authors seven), then starts the background movie. Unlike the Mode
    // Selects it does not touch the jukebox and registers no joy handler.
    kitConstruct(s, inst, kOptionMasks, 8);
    // The second bloom, with colour -1: the copy keeps whatever colour the
    // object it came from had.
    banim_highlight_init(clock(s), &inst->bloom2, screen,
                         BSCR_OBJ_BLOOM_TEXT_2, -1);
    inst->hasBloom2 = true;
    HOOK(s, startMovie, "MOVIES\\options_movie_new.AVI");
    trace(s, "Options ctor %08x", (unsigned)screen);

    // The one rule in the derived constructor: on NTSC there is no language
    // to pick, so MENUITEM_7 is disabled AND hidden. GrayMenuItem's mode 2
    // does both; mode 0 would have left it on screen, grayed.
    if (s->videoMode == 1) {
        HOOK(s, grayMenuItem, screen, BSCR_ITEM_MENUITEM(7), BSCR_GRAY_HIDE);
        trace(s, "gray MENUITEM_7 hide (NTSC)");
    }
}

static void optionsDestruct(BScreens* s, BScreenInstance* inst)
{
    trace(s, "Options dtor");
    kitDestruct(s, inst);
    memset(inst, 0, sizeof(*inst));
}

// OptionsScreenBase::HandleHighlight (0x001e55a0), reached through the
// vtable at +96. `overrideMask` is 0 from FirstCrackAtMessage; the screens
// that pass a mask of their own are the other Options pages.
static void optionsHandleHighlight(BScreens* s, BScreenInstance* inst,
                                   BScreenCallbackData* data,
                                   uint32_t overrideMask)
{
    uint32_t mask = overrideMask;
    BAnim*   a    = clock(s);

    // Both highlight animations, on the raw hash, before anything else.
    banim_highlight_set_item(a, &inst->bloom, data ? data->itemHash : 0);
    banim_highlight_set_item(a, &inst->bloom2, data ? data->itemHash : 0);

    if (!mask) {
        int n = itemIndex(data ? data->itemHash : 0, 7);
        // Out of range leaves the mask at 0, and the rest of the function
        // runs anyway: SetCurrentItem(0) and a bounding box for nothing.
        mask = n ? BSCR_MI_MASK(n) : 0u;
    }
    setCurrentItem(s, inst, mask, BSCR_UNDER_OPTIONS, BSCR_OVER_OPTIONS);
}

// Returns true if the screen was torn down.
static bool optionsOnSelect(BScreens* s, BScreenInstance* inst,
                            BScreenCallbackData* data)
{
    const char* dest      = "";      // the out-of-range default, an empty
    bool        immediate = false;   // literal, which resolves to no screen
    int         n         = itemIndex(data ? data->itemHash : 0, 7);

    if (n) {
        const BOptionItem* item = &kOptionItems[n - 1];
        dest      = item->screen;
        immediate = item->immediate;
        trace(s, "select MENUITEM_%d", n);
        if (item->displayStart) {
            // tDisplayOptionsChangeManager::Start (0x001e0508) takes a
            // snapshot so the Display page can offer to revert.
            HOOK0(s, displayOptionsStart);
            trace(s, "display options start");
        }
    } else {
        trace(s, "select unknown %08x", data ? (unsigned)data->itemHash : 0u);
    }

    if (immediate) {
        bgf_change_to_screen(s->gf, dest, 1);
        return true;
    }
    exitStart(s, inst, dest);
    return false;
}

// tOptionsScreen::HandleEvent (0x001e0ac0), the derived half.
static bool optionsHandleEvent(BScreens* s, BScreenInstance* inst,
                               BScreenMessage msg, BScreenCallbackData* data)
{
    if (msg == BMSG_MENUITEM_HIGHLIGHT) {
        int n = itemIndex(data ? data->itemHash : 0, 7);
        if (n) setBlurb(s, inst, kOptionItems[n - 1].blurb);
        // then tAnimatedBlurb::Animate and Rumbleator::Tick
        return false;
    }
    if (msg < BMSG_MENUITEM_UNHIGHLIGHT) {
        if (msg == BMSG_MENUITEM_SELECT) return optionsOnSelect(s, inst, data);
        return false;
    }
    if (msg == BMSG_SCREEN_TICK) {
        // tAnimatedBlurb::Animate and Rumbleator::Tick again. The blurb is
        // animated twice per tick on this screen -- once here and once in
        // FirstCrackAtMessage -- which is not a slip in the port: both call
        // sites are in the disassembly, and the second Animate does nothing
        // new because RealTimer has not moved between them.
        banim_blurb_animate(clock(s), &inst->blurbAnim);
        inst->tickCount++;
    }
    return false;
}

// OptionsScreenBase::FirstCrackAtMessage (0x001e56c0). The base gets every
// message before the derived class does, runs the highlight and the
// animations itself, and hands the message to the exit animation instead of
// the derived HandleEvent once one exists.
static void optionsFirstCrack(BScreens* s, BScreenInstance* inst,
                              BScreenMessage msg, BScreenCallbackData* data)
{
    if (msg == BMSG_MENUITEM_HIGHLIGHT) {
        optionsHandleHighlight(s, inst, data, 0);
    } else if (msg == BMSG_SCREEN_TICK) {
        kitTick(s, inst);
    }

    if (inst->exitActive) {
        exitHandleMessages(s, inst, msg, data);
        return;
    }
    optionsHandleEvent(s, inst, msg, data);
}

// tOptionsScreen::Callback (0x001e0d18) into OptionsScreenBase::BaseCallback
// (0x001e5798).
void bscr_options_callback(BGameFlow* gf, BScreenMessage msg,
                           BScreenCallbackData* data)
{
    BScreens* s = g_screens;
    (void)gf;
    if (!s) return;

    if (msg == BMSG_SCREEN_ACTIVATE) {
        optionsConstruct(s, &s->options, data ? data->itemHash
                                              : BSCR_SCREEN_OPTIONS);
        return;
    }
    if (msg == BMSG_SCREEN_UNACTIVATE) {
        if (s->options.live) optionsDestruct(s, &s->options);
        return;
    }
    if (!s->options.live) { trace(s, "Options message with no instance"); return; }
    optionsFirstCrack(s, &s->options, msg, data);
}
