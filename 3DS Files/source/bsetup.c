// The race setup screens. See bsetup.h, and docs/formats/frontend-setup.md
// for the decompilation this is a port of -- every rule below names a
// retail address (SLES_507.31).

#include "bsetup.h"

#include <string.h>

#include "bmath.h"
#include "bscreens.h"

// ---------------------------------------------------------------- hooks

#define HOOK(s, fn, ...)                                                 \
    do {                                                                 \
        if ((s)->hooks.fn) (s)->hooks.fn((s)->hooks.user, __VA_ARGS__); \
    } while (0)
#define HOOK0(s, fn)                                                     \
    do {                                                                 \
        if ((s)->hooks.fn) (s)->hooks.fn((s)->hooks.user);               \
    } while (0)

static BSetup* g_setup;

// The kit runs on the flow's clock, as the main menu's does (flowAnim in
// gameflow.c): RealTimer and RealTimeElapsed are one global each.
static BAnim* clock(BSetup* s)
{
    BAnim* a = s->gf->anim;
    banim_set_clock(a, (int32_t)s->gf->realTimer, s->gf->realElapsed);
    return a;
}

static float topLeftX(BSetup* s, uint32_t screen, uint32_t object)
{
    return s->hooks.getTopLeftX
               ? s->hooks.getTopLeftX(s->hooks.user, screen, object)
               : 0.0f;
}

static int joystickPluggedIn(BSetup* s, int port)
{
    return s->hooks.isJoystickPluggedIn
               ? s->hooks.isJoystickPluggedIn(s->hooks.user, port)
               : 0;
}

// ------------------------------------------------------------ Fred's bytes

static int32_t get32(const uint8_t* p)
{
    return (int32_t)((uint32_t)p[0] | (uint32_t)p[1] << 8
                     | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24);
}

static void put32(uint8_t* p, int32_t v)
{
    uint32_t u = (uint32_t)v;
    p[0] = (uint8_t)u;
    p[1] = (uint8_t)(u >> 8);
    p[2] = (uint8_t)(u >> 16);
    p[3] = (uint8_t)(u >> 24);
}

void bsetup_challenge_defaults(BChallengeData* d)
{
    d->numPlayers    = 1;
    d->challengeMode = 3;
    d->raceMode      = 1;
    d->skillLevel    = 1;
    d->beACopSkill   = 0;
}

void bsetup_challenge_load(BChallengeData* d, const uint8_t* fred)
{
    const uint8_t* p = fred + FRED_CHALLENGE_SCREEN;
    d->numPlayers    = get32(p + 0);
    d->challengeMode = get32(p + 4);
    d->raceMode      = get32(p + 8);
    d->skillLevel    = get32(p + 12);
    d->beACopSkill   = get32(p + 16);
}

void bsetup_challenge_save(const BChallengeData* d, uint8_t* fred)
{
    uint8_t* p = fred + FRED_CHALLENGE_SCREEN;
    put32(p + 0, d->numPlayers);
    put32(p + 4, d->challengeMode);
    put32(p + 8, d->raceMode);
    put32(p + 12, d->skillLevel);
    put32(p + 16, d->beACopSkill);
}

// Fred.GameType and Fred.NumPlayerCars, which every setup screen writes on
// the way in and out.
static void fredSetGame(BSetup* s, int32_t gameType, int32_t numPlayerCars)
{
    uint8_t* fred = s->gf->fred;
    if (!fred) return;
    put32(fred + FRED_GAME_TYPE, gameType);
    put32(fred + FRED_NUM_PLAYER_CARS, numPlayerCars);
}

// ------------------------------------------------------------ tfeSineWave

void bsine_init(BSineWave* w, float lo, float hi, float rate)
{
    w->lo    = lo;
    w->hi    = hi;
    w->rate  = rate;
    w->phase = 0.0f;
}

// Step (0x0024a5d8): the phase is stored, then tested, and 6.283 comes off
// once -- a step of more than a whole turn leaves it past the wrap.
void bsine_step(BSineWave* w, float dt)
{
    w->phase = w->phase + w->rate * dt;
    if (BSINE_WRAP < w->phase) w->phase = w->phase - BSINE_WRAP;
}

// GetValFloat (0x0024a610), in its own order: (sin + 1) * 0.5 first, then
// (hi - lo) times that, then lo plus it.
float bsine_val(const BSineWave* w)
{
    float t = (bSinF(w->phase) + 1.0f) * 0.5f;
    return w->lo + (w->hi - w->lo) * t;
}

// GetValInt (0x0024a668): cvt.w.s, which truncates.
int32_t bsine_val_int(const BSineWave* w)
{
    return (int32_t)bsine_val(w);
}

// ----------------------------------------------------------------- arrows

// UpdateVisibility (0x0024a800): each bitmap the constructor found is shown
// while the pair follows something, hidden otherwise.
static void arrowsUpdateVisibility(BSetup* s, BArrows* r)
{
    int visible = r->follow != 0;
    if (r->hasLeft) HOOK(s, setBitmapVisible, r->screen, r->left, visible);
    if (r->hasRight) HOOK(s, setBitmapVisible, r->screen, r->right, visible);
}

void barrows_init(BSetup* s, BArrows* r, uint32_t screen, uint32_t left,
                  uint32_t right)
{
    memset(r, 0, sizeof(*r));
    bsine_init(&r->pulse, 0.0f, 128.0f, 10.0f);
    r->screen = screen;
    r->left   = left;
    r->right  = right;
    // FindFlailerObject(screen, name, 2): bitmaps only.
    r->hasLeft = s->hooks.findObject
                     ? s->hooks.findObject(s->hooks.user, screen, left, 2)
                     : 0;
    r->hasRight = s->hooks.findObject
                      ? s->hooks.findObject(s->hooks.user, screen, right, 2)
                      : 0;
    barrows_set(s, r, 0);
}

void barrows_set(BSetup* s, BArrows* r, uint32_t object)
{
    r->follow = object;
    arrowsUpdateVisibility(s, r);
}

// Tick (0x0024a730). The centre is asked for once, before either arrow;
// the alpha is asked of the wave once per arrow.
static void arrowsTick(BSetup* s, BArrows* r)
{
    bsine_step(&r->pulse, s->gf->realElapsed);
    if (r->follow) {
        int32_t y = s->hooks.getCenterY
                        ? s->hooks.getCenterY(s->hooks.user, r->screen,
                                              r->follow)
                        : 0;
        if (r->hasLeft) {
            HOOK(s, setBitmapAlpha, r->screen, r->left,
                 bsine_val_int(&r->pulse));
            HOOK(s, setBitmapCenterY, r->screen, r->left, (float)y);
        }
        if (r->hasRight) {
            HOOK(s, setBitmapAlpha, r->screen, r->right,
                 bsine_val_int(&r->pulse));
            HOOK(s, setBitmapCenterY, r->screen, r->right, (float)y);
        }
    }
    arrowsUpdateVisibility(s, r);
}

void barrows_event(BSetup* s, BArrows* r, BScreenMessage msg)
{
    if (msg == BMSG_SCREEN_TICK) arrowsTick(s, r);
}

// ------------------------------------------------ the challenge helpers

// ValueChanger (0x001b5c78): add, then wrap past either end to the other.
static int32_t valueChanger(int32_t cur, int32_t d, int32_t lo, int32_t hi)
{
    int32_t v = cur + d;
    if (hi < v) v = lo;
    if (v < lo) v = hi;
    return v;
}

// MaybeChangeNumPlayers (0x001b5c90): 1 or 2, wrapping, and 1 whenever the
// second pad is not plugged in -- which on a 3DS is always. Answers whether
// it changed.
static int maybeChangeNumPlayers(BSetup* s, BChallengeData* d, int32_t n)
{
    int32_t v = n > 0 ? n : 2;
    if (v >= 3) v = 1;
    if (!joystickPluggedIn(s, 1)) v = 1;
    if (d->numPlayers == v) return 0;
    d->numPlayers = v;
    return 1;
}

// MaybeChangeOpponentSkillLevel (0x001b5d70): 0..2, wrapping.
static int maybeChangeOpponentSkillLevel(int32_t d, int32_t* skill)
{
    int32_t old = *skill;
    *skill = valueChanger(old, d, 0, 2);
    return *skill != old;
}

// MakeJoystickArrowsRight (0x001b5d00): without both pads, no arrows on
// Players and back to one player. Its result is dropped.
static void makeJoystickArrowsRight(BSetup* s, BChallengeData* d, BArrows* r)
{
    if (joystickPluggedIn(s, 0) && joystickPluggedIn(s, 1)) return;
    barrows_set(s, r, 0);
    maybeChangeNumPlayers(s, d, 1);
}

// StartTheRightMovie (0x001b5de0): the movie of whichever mode the main
// menu picked, Fred.MainMenuOpts.mPolice. The port keeps that in
// gf->copsOn.
static void startTheRightMovie(BSetup* s)
{
    HOOK(s, startMovie, s->gf->copsOn ? "MOVIES\\hotpursuit_movie.AVI"
                                      : "MOVIES\\worldracing_ movie.AVI");
}

// 0x00313d98: "Beginner", "Advanced", "Expert", then a 0.
static const int32_t kSkillLabels[4] = {30015, 30016, 30017, 0};

// RefreshOpponentSkillLevel (0x001b5dc0) indexes that table unchecked. The
// skill is ValueChanger's, 0..2, unless a save says otherwise; the port
// reads the terminator's 0 for anything outside the four words.
static void refreshOpponentSkillLevel(BSetup* s, uint32_t screen,
                                      int32_t skill, uint32_t object)
{
    int id = (uint32_t)skill < 4 ? kSkillLabels[skill] : 0;
    HOOK(s, setLanguageID, screen, object, id);
}

// 0x0031a490, the four help lines, 0-terminated.
static const int32_t kBeACopHelp[5] = {805000, 805001, 805002, 805003, 0};

// --------------------------------------------------- BeACopChallengeSetup

#define ITEM_PLAYERS BSCR_ITEM_MENUITEM(1)
#define ITEM_SKILL   BSCR_ITEM_MENUITEM(2)
#define ITEM_SETUP   BSCR_ITEM_MENUITEM(3)

static const uint32_t kBeACopMasks[3] = {
    BSCR_MI_MASK(1), BSCR_MI_MASK(2), BSCR_MI_MASK(3),
};

// ResyncChangeables (0x001b7680). Two players gray Skill Level and hide its
// value; the opponents are the other player. Any other count touches
// neither, and the skill's label is set either way.
static void beACopResync(BSetup* s, BBeACopSetup* b)
{
    if (b->data.numPlayers == 1) {
        HOOK(s, setLanguageID, b->screen, BSETUP_OBJ_PLAYERS_VALUE, 20003);
        HOOK(s, grayMenuItem, b->screen, ITEM_SKILL, BSCR_GRAY_ENABLE);
        HOOK(s, setVisible, b->screen, BSETUP_OBJ_SKILL_VALUE, 1);
    } else if (b->data.numPlayers == 2) {
        HOOK(s, setLanguageID, b->screen, BSETUP_OBJ_PLAYERS_VALUE, 20004);
        HOOK(s, grayMenuItem, b->screen, ITEM_SKILL, BSCR_GRAY_DISABLE);
        HOOK(s, setVisible, b->screen, BSETUP_OBJ_SKILL_VALUE, 0);
    }
    refreshOpponentSkillLevel(s, b->screen, b->data.beACopSkill,
                              BSETUP_OBJ_SKILL_VALUE);
}

// 0x001b70d8: the item's line for the blurb. Players says solo or
// head-to-head, Skill Level how fast the opponents are, Setup the one line.
static void beACopBlurb(BSetup* s, BBeACopSetup* b, uint32_t item)
{
    int id = 0;
    switch (item) {
        case ITEM_PLAYERS:
            if (b->data.numPlayers == 1) id = 19000;
            else if (b->data.numPlayers == 2) id = 19001;
            break;
        case ITEM_SKILL:
            if (b->data.beACopSkill == 0) id = 19002;
            else if (b->data.beACopSkill == 1) id = 19003;
            else if (b->data.beACopSkill == 2) id = 19004;
            break;
        case ITEM_SETUP:
            id = 19005;
            break;
        default:
            break;
    }
    banim_blurb_new_text_id(clock(s), &b->blurb, id);
}

// The constructor (0x001b6c68), in its order. The Fred calls come after the
// arrows and before the SelectionSet's items; see bsetup.h for what the
// three car calls are.
static void beACopCtor(BSetup* s, uint32_t screen)
{
    BBeACopSetup* b = &s->beACop;
    BAnim*        a = clock(s);

    memset(b, 0, sizeof(*b));
    b->screen = screen;
    bsel_init(a, &b->sel, screen);
    banim_blurb_init(a, &b->blurb, screen, BSCR_OBJ_SCROLLING_TEXT,
                     BSCR_OBJ_SCROLLING_TEXT, BSCR_OBJ_WHITEOUT_BAR);
    banim_slide_in_init(a, &b->slideIn, screen,
                        topLeftX(s, screen, BSCR_MI_MASK(1)));
    // Two blooms: the item's, in BloomTargetColor, and the value's, in its
    // own colour (gp-18792, -1).
    banim_highlight_init(a, &b->highlight, screen, 0xab671c9au,
                         (int32_t)BANIM_BLOOM_COLOR);
    banim_highlight_init(a, &b->change, screen, 0x1042eac3u, -1);
    barrows_init(s, &b->arrows, screen, BSETUP_OBJ_LEFT_ARROW,
                 BSETUP_OBJ_RIGHT_ARROW);
    if (s->gf->fred) bsetup_challenge_load(&b->data, s->gf->fred);
    else bsetup_challenge_defaults(&b->data);
    fredSetGame(s, FRED_CHALLENGE_GAME_BE_A_COP, b->data.numPlayers);
    HOOK0(s, makeChallengeCarsAvailable);
    HOOK0(s, preloadCars);
    bsel_set_indicator_mode(&b->sel, 1);
    bsel_add_items(a, &b->sel, kBeACopMasks, 3);
    makeJoystickArrowsRight(s, &b->data, &b->arrows);
    beACopResync(s, b);
    startTheRightMovie(s);
    b->exitActive = 0;
    HOOK(s, setHelpOverride, kBeACopHelp);
    b->live = 1;
}

// The destructor (0x001b6e30): the exit animation first, which puts the
// items back; Fred gets the count, the game type and the settings back;
// then the help override comes off and the members go in reverse. The
// arrows have no destructor and the SelectionSet's only frees.
static void beACopDtor(BSetup* s)
{
    BBeACopSetup* b = &s->beACop;
    BAnim*        a = clock(s);

    if (b->exitActive) banim_slide_release(a, &b->exit.slide);
    fredSetGame(s, FRED_CHALLENGE_GAME_BE_A_COP, b->data.numPlayers);
    if (s->gf->fred) bsetup_challenge_save(&b->data, s->gf->fred);
    HOOK(s, setHelpOverride, NULL);
    banim_slide_release(a, &b->slideIn);
    banim_blurb_release(a, &b->blurb);
    memset(b, 0, sizeof(*b));
}

// OnTick (0x001b6fb0): the arrows, the four animations, then the pads. On
// Players the arrows show only with two pads in; without them the count
// falls back to one, and the line with it. On the other items only the
// count is checked, and the labels resynced whether it changed or not.
static void beACopTick(BSetup* s, BBeACopSetup* b)
{
    BAnim* a = clock(s);

    barrows_event(s, &b->arrows, BMSG_SCREEN_TICK);
    banim_slide_animate(a, &b->slideIn);
    banim_highlight_animate(a, &b->highlight);
    banim_highlight_animate(a, &b->change);
    banim_blurb_animate(a, &b->blurb);

    if (b->current == ITEM_PLAYERS) {
        if (joystickPluggedIn(s, 0) && joystickPluggedIn(s, 1)) {
            barrows_set(s, &b->arrows, BSETUP_OBJ_PLAYERS_VALUE);
            return;
        }
        barrows_set(s, &b->arrows, 0);
        if (maybeChangeNumPlayers(s, &b->data, 1)) {
            beACopResync(s, b);
            beACopBlurb(s, b, b->current);
        }
    } else {
        if (joystickPluggedIn(s, 0) && joystickPluggedIn(s, 1)) return;
        maybeChangeNumPlayers(s, &b->data, 1);
        beACopResync(s, b);
    }
}

// OnHighlight (0x001b7188). The brackets go to the item's own box -- not
// its mask's, as on the Mode Selects -- by retail's two constants, gp-16112
// (-3.0) under the bottom and gp-16116 (6.0) over the top, each summed in
// float and cut to an int by FlailerSetTopLeftY(int, int, float)
// (0x001b9ae8). Then the line, the item's bloom and the current item,
// whatever the item is; then the arrows, mask and value bloom by item.
static void beACopHighlight(BSetup* s, BBeACopSetup* b, uint32_t item)
{
    BAnim*  a      = clock(s);
    int32_t box[4] = {0, 0, 0, 0};   // left, top, right, bottom

    if (s->hooks.getBoundingBox)
        s->hooks.getBoundingBox(s->hooks.user, b->screen, item, box);
    HOOK(s, setTopLeftY, b->screen, BSCR_OBJ_MI_UNDERSCORE,
         (int32_t)((float)box[3] + -3.0f));
    HOOK(s, setTopLeftY, b->screen, BSCR_OBJ_MI_OVERSCORE,
         (int32_t)((float)box[1] - 6.0f));
    beACopBlurb(s, b, item);
    banim_highlight_set_item(a, &b->highlight, item);
    b->current = item;

    switch (item) {
        case ITEM_PLAYERS:
            barrows_set(s, &b->arrows, BSETUP_OBJ_PLAYERS_VALUE);
            makeJoystickArrowsRight(s, &b->data, &b->arrows);
            bsel_set_current(a, &b->sel, BSCR_MI_MASK(1));
            banim_highlight_set_item(a, &b->change, BSETUP_OBJ_PLAYERS_VALUE);
            break;
        case ITEM_SKILL:
            barrows_set(s, &b->arrows, BSETUP_OBJ_SKILL_VALUE);
            bsel_set_current(a, &b->sel, BSCR_MI_MASK(2));
            banim_highlight_set_item(a, &b->change, BSETUP_OBJ_SKILL_VALUE);
            break;
        case ITEM_SETUP:
            barrows_set(s, &b->arrows, 0);
            bsel_set_current(a, &b->sel, BSCR_MI_MASK(3));
            banim_highlight_set_item(a, &b->change, 0);
            break;
        default:
            break;
    }
}

// OnScroll (0x001b7330): left is -1 and right +1. A change blooms the value,
// resyncs and rewrites the line, with the menu's left or right sound; no
// change is silent. The count goes through MaybeChangeNumPlayers, so with
// one pad it never leaves 1.
static void beACopScroll(BSetup* s, BBeACopSetup* b, BScreenMessage msg,
                         BScreenCallbackData* data)
{
    int32_t  dir     = msg == BMSG_MENUITEM_PAD_LEFT ? -1 : 1;
    int      changed = 0;
    uint32_t object  = 0;

    if (data->itemHash == ITEM_PLAYERS) {
        changed = maybeChangeNumPlayers(s, &b->data, b->data.numPlayers + dir);
        object  = BSETUP_OBJ_PLAYERS_VALUE;
    } else if (data->itemHash == ITEM_SKILL) {
        changed = maybeChangeOpponentSkillLevel(dir, &b->data.beACopSkill);
        object  = BSETUP_OBJ_SKILL_VALUE;
    }
    if (!changed) {
        data->noise = 0;
        return;
    }
    if (msg == BMSG_MENUITEM_PAD_LEFT) data->noise = BSND_MENU_LEFT;
    else if (msg == BMSG_MENUITEM_PAD_RIGHT) data->noise = BSND_MENU_RIGHT;
    banim_highlight_set_item(clock(s), &b->change, object);
    beACopResync(s, b);
    beACopBlurb(s, b, data->itemHash);
}

// SELECT (0x001b74f8). One player takes only the first pad's; two take
// either. Fred gets the settings, the count and the game type, and
// TheRaceParameters the count and the race mode. Players and Skill Level
// go to car select, the one- or two-player screen, making the challenge
// cars available and setting the race up first; Setup goes to Be The Cop
// Setup. The exit animation takes the brackets with it.
static void beACopSelect(BSetup* s, BBeACopSetup* b,
                         BScreenCallbackData* data)
{
    const char* target = "";
    BAnim*      a;
    int32_t     numPlayers;

    if (!((b->data.numPlayers == 1 && data->port == 0)
          || b->data.numPlayers == 2))
        return;
    if (s->gf->fred) bsetup_challenge_save(&b->data, s->gf->fred);
    numPlayers = b->data.numPlayers;
    fredSetGame(s, FRED_CHALLENGE_GAME_BE_A_COP, numPlayers);
    HOOK(s, setRaceParameters, numPlayers, b->data.raceMode);

    if (data->itemHash >= ITEM_PLAYERS && data->itemHash <= ITEM_SKILL) {
        target = numPlayers == 2 ? "Select Car2P" : "Select Car";
        HOOK0(s, makeChallengeCarsAvailable);
        HOOK0(s, setupRaceParametersAfterRaceSetup);
    } else if (data->itemHash == ITEM_SETUP) {
        target = "Be The Cop Setup";
    }

    a = clock(s);
    banim_exit_init(a, &b->exit, b->screen, target);
    b->exitActive = 1;
    banim_slide_add_group(a, &b->exit.slide, BSCR_GROUP_UNDERSCORE,
                          BSCR_OBJ_MI_UNDERSCORE,
                          topLeftX(s, b->screen, BSCR_OBJ_MI_UNDERSCORE),
                          BANIM_OFFSCREEN_X, b->exit.slide.totalTime);
}

// HandleEvent (0x001b7438). TICK runs OnTick before anything else, the exit
// animation or not; while one runs it gets every message, and nothing
// else does.
static void beACopEvent(BSetup* s, BScreenMessage msg,
                        BScreenCallbackData* data)
{
    BBeACopSetup* b = &s->beACop;

    if (msg == BMSG_SCREEN_TICK) beACopTick(s, b);
    if (b->exitActive) {
        int32_t param = data ? data->param : 0;
        int32_t noise = data ? data->noise : 0;
        // A finished exit changes screen, which unactivates this one and
        // clears `b`. Nothing after this may touch it.
        banim_exit_message(clock(s), &b->exit, (int)msg, &param, &noise);
        if (data) {
            data->param = param;
            data->noise = noise;
        }
        return;
    }
    if (!data) return;
    switch (msg) {
        case BMSG_MENUITEM_HIGHLIGHT:
            beACopHighlight(s, b, data->itemHash);
            break;
        case BMSG_MENUITEM_SELECT:
            beACopSelect(s, b, data);
            break;
        case BMSG_MENUITEM_PAD_LEFT:
        case BMSG_MENUITEM_PAD_RIGHT:
            beACopScroll(s, b, msg, data);
            break;
        default:
            break;
    }
}

void bsetup_init(BSetup* s, BGameFlow* gf, const BSetupHooks* hooks)
{
    memset(s, 0, sizeof(*s));
    s->gf = gf;
    if (hooks) s->hooks = *hooks;
    g_setup = s;
}

// Callback (0x001b6f18): ACTIVATE news the instance on the screen the
// callback data names, UNACTIVATE deletes it if there is one, and every
// other message goes to HandleEvent -- in retail with the instance
// unchecked, here only while there is one.
void bsetup_beacop_callback(BGameFlow* gf, BScreenMessage msg,
                            BScreenCallbackData* data)
{
    BSetup* s = g_setup;

    if (!s || !gf->anim) return;
    s->gf = gf;
    switch (msg) {
        case BMSG_SCREEN_ACTIVATE:
            beACopCtor(s, data ? data->itemHash : BSETUP_SCREEN_BEACOP);
            break;
        case BMSG_SCREEN_UNACTIVATE:
            if (s->beACop.live) beACopDtor(s);
            break;
        default:
            if (s->beACop.live) beACopEvent(s, msg, data);
            break;
    }
}
