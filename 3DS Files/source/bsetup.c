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

static int findObject(BSetup* s, uint32_t screen, uint32_t object, int type)
{
    return s->hooks.findObject
               ? s->hooks.findObject(s->hooks.user, screen, object, type)
               : 0;
}

static float topLeftY(BSetup* s, uint32_t screen, uint32_t object)
{
    return s->hooks.getTopLeftY
               ? s->hooks.getTopLeftY(s->hooks.user, screen, object)
               : 0.0f;
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

void bsetup_btc_defaults(BBeTheCopData* d)
{
    d->opponentGrid = 2;
    d->opponentType = 0;
    d->catchup      = 1;
    d->traffic      = 0;
    d->damage       = 1;
}

static void btcLoad(BBeTheCopData* d, const uint8_t* fred)
{
    const uint8_t* p = fred + FRED_BE_THE_COP_SETUP;
    d->opponentGrid = get32(p + 0);
    d->opponentType = get32(p + 4);
    d->catchup      = get32(p + 8);
    d->traffic      = get32(p + 12);
    d->damage       = get32(p + 16);
}

static void btcSave(const BBeTheCopData* d, uint8_t* fred)
{
    uint8_t* p = fred + FRED_BE_THE_COP_SETUP;
    put32(p + 0, d->opponentGrid);
    put32(p + 4, d->opponentType);
    put32(p + 8, d->catchup);
    put32(p + 12, d->traffic);
    put32(p + 16, d->damage);
}

void bsetup_fred_defaults(uint8_t* fred)
{
    BChallengeData c;
    BBeTheCopData  b;
    bsetup_challenge_defaults(&c);
    bsetup_challenge_save(&c, fred);
    bsetup_btc_defaults(&b);
    btcSave(&b, fred);
}

static int32_t fredGet(BSetup* s, uint32_t off)
{
    return s->gf->fred ? get32(s->gf->fred + off) : 0;
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

// ------------------------------------------------------ tScrollingMenuList

// 0x0031cfa0, MI_1_MASK .. MI_7_MASK, which the static initialiser at
// 0x0024a888 hashes. The word before it is 0 and nothing writes it, and
// CurrentMask is -1 until the first highlight: the port reads 0 for any
// index off the seven.
static const uint32_t kScrollMasks[7] = {
    BSCR_MI_MASK(1), BSCR_MI_MASK(2), BSCR_MI_MASK(3), BSCR_MI_MASK(4),
    BSCR_MI_MASK(5), BSCR_MI_MASK(6), BSCR_MI_MASK(7),
};

// tMenuAnimElement's constructor (0x00249c78): the spline at rest on the
// object's Y. It zeroes Val, both derivatives and ValDesired, then sets
// ValDesired and SavedY to the Y, flags a seek if the Y is not 0, and
// clears the state again: whatever the Y, the element starts idle, there.
// Retail leaves the coefficients and Time as the heap had them; a seek
// rebuilds both before it reads either.
static void elementInit(BSetup* s, BScrollList* l, BMenuAnimElement* el,
                        uint32_t object)
{
    memset(el, 0, sizeof(*el));
    el->object                 = object;
    el->yAnim.arrivalThreshold = 1.0f;
    el->yAnim.duration         = 0.5f;
    el->savedY                 = topLeftY(s, l->screen, object);
    el->yAnim.valDesired       = el->savedY;
    el->yAnim.state            = 0;
    el->yAnim.val              = el->yAnim.valDesired;
    el->yAnim.dval             = el->yAnim.dvalDesired;
}

// The constructor (0x00249de0): the arrows' pulse, tfeSineWave(0, 128, 10),
// the visible area from the first item's Y to the last's (SetVisibleArea,
// 0x00249f28), and both arrows at the pulse's alpha.
static void scrollInit(BSetup* s, BScrollList* l, uint32_t screen,
                       uint32_t first, uint32_t last, uint32_t up,
                       uint32_t down, uint32_t clip)
{
    memset(l, 0, sizeof(*l));
    l->screen = screen;
    bsine_init(&l->arrowAnimator, 0.0f, 128.0f, 10.0f);
    l->top         = topLeftY(s, screen, first);
    l->bottom      = topLeftY(s, screen, last);
    l->upArrow     = up;
    l->downArrow   = down;
    l->clipPoly    = clip;
    l->currentMask = -1;
    HOOK(s, setAlpha, screen, up, bsine_val_int(&l->arrowAnimator));
    HOOK(s, setAlpha, screen, down, bsine_val_int(&l->arrowAnimator));
    l->numMenuItemsToScroll = 0;
}

// AddObject (0x00249f70): an object the screen has is clipped to the poly
// and appended. The port's list holds 16, BuildMenu's most.
static void scrollAddObject(BSetup* s, BScrollList* l, uint32_t object)
{
    if (!findObject(s, l->screen, object, 0)) return;
    HOOK(s, setClipToPoly, l->screen, object, l->clipPoly);
    if (l->numElements == BSCROLL_MAX_ELEMENTS) return;
    elementInit(s, l, &l->elements[l->numElements++], object);
}

// AddObjects (0x00249ff8).
static void scrollAddObjects(BSetup* s, BScrollList* l,
                             const uint32_t* objects, int n)
{
    for (int i = 0; i < n; i++) scrollAddObject(s, l, objects[i]);
}

// The destructor (0x00249ed0): each element's (0x00249d30) puts its object
// back at SavedY, in the list's order.
static void scrollRelease(BSetup* s, BScrollList* l)
{
    for (int i = 0; i < l->numElements; i++) {
        BMenuAnimElement* el = &l->elements[i];
        HOOK(s, setObjectTopLeftY, l->screen, el->object, el->savedY);
    }
    l->numElements = 0;
}

// FindMenuElement (0x0024a050): the first element on that object.
static BMenuAnimElement* scrollFind(BScrollList* l, uint32_t object)
{
    for (int i = 0; i < l->numElements; i++)
        if (l->elements[i].object == object) return &l->elements[i];
    return NULL;
}

// tMenuAnimElement::ApplyDeltaY (0x00249d70): the destination moves, and
// the spline seeks if that is not where it is.
static void elementApplyDeltaY(BMenuAnimElement* el, float d)
{
    el->yAnim.valDesired = el->yAnim.valDesired + d;
    if (el->yAnim.valDesired != el->yAnim.val) el->yAnim.state = 2;
}

// SetDesiredTopLeftY (0x0024a090): move every element by what puts this
// object's destination at `y`. Retail reads the element unchecked, so an
// object on the screen and not in the list is a read of address 20 there;
// here it moves nothing.
static void scrollSetDesiredTopLeftY(BSetup* s, BScrollList* l,
                                     uint32_t object, float y)
{
    int               found = findObject(s, l->screen, object, 0);
    BMenuAnimElement* el    = scrollFind(l, object);
    float             d;

    if (!found || !el) return;
    d = y - el->yAnim.valDesired;
    for (int i = 0; i < l->numElements; i++)
        elementApplyDeltaY(&l->elements[i], d);
}

// SetCurrentObject (0x0024a120): an object above the area comes down to
// its top, one below it up to its bottom.
static void scrollSetCurrentObject(BSetup* s, BScrollList* l,
                                   uint32_t object)
{
    float y = topLeftY(s, l->screen, object);
    if (y < l->top) scrollSetDesiredTopLeftY(s, l, object, l->top);
    else if (l->bottom < y) scrollSetDesiredTopLeftY(s, l, object, l->bottom);
}

// Tick (0x0024a1a8): each element's (0x00249da0) seeks its spline by
// RealTimeElapsed, with the limits 0, and puts its object at the value;
// then the pulse steps and both arrows take it.
static void scrollTick(BSetup* s, BScrollList* l)
{
    for (int i = 0; i < l->numElements; i++) {
        BMenuAnimElement* el = &l->elements[i];
        bspline_seek(&el->yAnim, s->gf->realElapsed);
        HOOK(s, setObjectTopLeftY, l->screen, el->object, el->yAnim.val);
    }
    bsine_step(&l->arrowAnimator, s->gf->realElapsed);
    HOOK(s, setAlpha, l->screen, l->upArrow,
         bsine_val_int(&l->arrowAnimator));
    HOOK(s, setAlpha, l->screen, l->downArrow,
         bsine_val_int(&l->arrowAnimator));
}

// Highlight (0x0024a248), retail's: only the first highlight places the
// mask, from the item's number -- MENUITEM_7 and past it, and two hashes
// more, all at the seventh. After that only the pad moves it.
static void scrollHighlight(BScrollList* l, uint32_t item)
{
    if (l->currentMask != -1) return;
    switch (item) {
        case BSCR_ITEM_MENUITEM(1): l->currentMask = 0; break;
        case BSCR_ITEM_MENUITEM(2): l->currentMask = 1; break;
        case BSCR_ITEM_MENUITEM(3): l->currentMask = 2; break;
        case BSCR_ITEM_MENUITEM(4): l->currentMask = 3; break;
        case BSCR_ITEM_MENUITEM(5): l->currentMask = 4; break;
        case BSCR_ITEM_MENUITEM(6): l->currentMask = 5; break;
        case BSCR_ITEM_MENUITEM(7):
        case BSCR_ITEM_MENUITEM(8):
        case BSCR_ITEM_MENUITEM(9):
        case 0xaee77883u:
        case 0xaee77884u: l->currentMask = 6; break;
        default: break;
    }
}

// GetCurrentMenuMask (0x0024a368).
static uint32_t scrollCurrentMask(const BScrollList* l)
{
    return (uint32_t)l->currentMask < 7 ? kScrollMasks[l->currentMask] : 0;
}

// MoveMaskDown (0x0024a388) stops at the last of the items to scroll, or
// the seventh; MoveMaskUp (0x0024a3c0) at the first.
static void scrollMoveMaskDown(BScrollList* l)
{
    int32_t n = l->numMenuItemsToScroll < 7 ? l->numMenuItemsToScroll : 7;
    l->currentMask = l->currentMask + 1;
    if (!(l->currentMask < n)) l->currentMask = n - 1;
}

static void scrollMoveMaskUp(BScrollList* l)
{
    l->currentMask = l->currentMask - 1;
    if (l->currentMask < 0) l->currentMask = 0;
}

// ShowUpArrow / ShowDownArrow (0x0024a3e0, 0x0024a430): with 8 items or
// more, whether any element is headed above the area, or below it.
static int scrollShowUpArrow(const BScrollList* l)
{
    if (l->numMenuItemsToScroll < 8) return 0;
    for (int i = 0; i < l->numElements; i++)
        if (l->elements[i].yAnim.valDesired < l->top) return 1;
    return 0;
}

static int scrollShowDownArrow(const BScrollList* l)
{
    if (l->numMenuItemsToScroll < 8) return 0;
    for (int i = 0; i < l->numElements; i++)
        if (l->bottom < l->elements[i].yAnim.valDesired) return 1;
    return 0;
}

// HandleEvent (0x0024a480): the pad moves the mask, a highlight places it
// and follows the item, and a tick animates.
static void scrollEvent(BSetup* s, BScrollList* l, BScreenMessage msg,
                        const BScreenCallbackData* data)
{
    switch (msg) {
        case BMSG_MENUITEM_PAD_UP: scrollMoveMaskUp(l); break;
        case BMSG_MENUITEM_PAD_DOWN: scrollMoveMaskDown(l); break;
        case BMSG_MENUITEM_HIGHLIGHT:
            scrollHighlight(l, data->itemHash);
            scrollSetCurrentObject(s, l, data->itemHash);
            HOOK(s, setVisible, l->screen, l->upArrow, scrollShowUpArrow(l));
            HOOK(s, setVisible, l->screen, l->downArrow,
                 scrollShowDownArrow(l));
            break;
        case BMSG_SCREEN_TICK: scrollTick(s, l); break;
        default: break;
    }
}

// ------------------------------------------------------ RaceSetupBaseClass

// The three tables BuildMenu reads, eight each: the items (0x00313e38),
// their masks (0x00313e58) and the value text beside each (0x00313e78).
static const uint32_t kRowItems[BRACESETUP_MAX_ROWS] = {
    BSCR_ITEM_MENUITEM(1), BSCR_ITEM_MENUITEM(2), BSCR_ITEM_MENUITEM(3),
    BSCR_ITEM_MENUITEM(4), BSCR_ITEM_MENUITEM(5), BSCR_ITEM_MENUITEM(6),
    BSCR_ITEM_MENUITEM(7), BSCR_ITEM_MENUITEM(8),
};
static const uint32_t kRowMasks[BRACESETUP_MAX_ROWS] = {
    BSCR_MI_MASK(1), BSCR_MI_MASK(2), BSCR_MI_MASK(3), BSCR_MI_MASK(4),
    BSCR_MI_MASK(5), BSCR_MI_MASK(6), BSCR_MI_MASK(7), BSCR_MI_MASK(8),
};
static const uint32_t kRowTexts[BRACESETUP_MAX_ROWS] = {
    0x69a2c757u, 0x69a2c758u, 0x69a2c759u, 0x69a2c75au,
    0x69a2c75bu, 0x69a2c75cu, 0x69a2c75du, 0x69a2c75eu,
};

// The two tables the three rows below read, "Off" and "On" (gp-18760, and
// gp-18744 the same), and Minimum, Moderate, Maximum and Off (0x00313e28).
// Retail indexes them unchecked; the value is its changer's unless a save
// says otherwise, and the port reads 0 for anything off the table.
static const int32_t kOffOn[2]      = {30008, 30009};
static const int32_t kTraffic[4]    = {30018, 30019, 30020, 30008};

static void refreshFrom(BSetup* s, BRaceSetup* r, const int32_t* table,
                        int n, int32_t value, uint32_t text)
{
    int id = (uint32_t)value < (uint32_t)n ? table[value] : 0;
    HOOK(s, setLanguageID, r->screen, text, id);
}

// MaybeChangeCatchup (0x001b7970) and MaybeChangeDamage (0x001b7a78): a
// toggle whichever way the pad went -- anything not 0 comes back 0 -- and
// always a change.
static int maybeChangeCatchup(BSetup* s, BRaceSetup* r, int32_t dir,
                              int32_t* value)
{
    (void)s;
    (void)r;
    (void)dir;
    *value = *value == 0;
    return 1;
}

static int maybeChangeDamage(BSetup* s, BRaceSetup* r, int32_t dir,
                             int32_t* value)
{
    (void)s;
    (void)r;
    (void)dir;
    *value = *value == 0;
    return 1;
}

// MaybeChangeTraffic (0x001b79a8): 0..3, wrapping.
static int maybeChangeTraffic(BSetup* s, BRaceSetup* r, int32_t dir,
                              int32_t* value)
{
    int32_t old = *value;
    (void)s;
    (void)r;
    *value = valueChanger(old, dir, 0, 3);
    return *value != old;
}

// RefreshCatchup (0x001b7988), RefreshTraffic (0x001b79f0), RefreshDamage
// (0x001b7a90).
static void refreshCatchup(BSetup* s, BRaceSetup* r, int32_t value,
                           uint32_t text)
{
    refreshFrom(s, r, kOffOn, 2, value, text);
}

static void refreshTraffic(BSetup* s, BRaceSetup* r, int32_t value,
                           uint32_t text)
{
    refreshFrom(s, r, kTraffic, 4, value, text);
}

static void refreshDamage(BSetup* s, BRaceSetup* r, int32_t value,
                          uint32_t text)
{
    refreshFrom(s, r, kOffOn, 2, value, text);
}

// FindChangeable (0x001b7ab0): the row on that item, or none.
static BChangeable* findRow(BRaceSetup* r, uint32_t item)
{
    for (int i = 0; i < r->numRows; i++)
        if (r->rows[i].menuItem == item) return &r->rows[i];
    return NULL;
}

// GetIndexForMenuItem (0x001b8358): the item's place in the eight, 0 for
// one that is not there.
static int rowIndex(uint32_t item)
{
    for (int i = 0; i < BRACESETUP_MAX_ROWS; i++)
        if (kRowItems[i] == item) return i;
    return 0;
}

// Attach (0x001b7dd8): a row on the end, not yet on an item. Retail's list
// has no end; its BuildMenu reads its tables past eight rows, and the port
// takes eight.
static void raceSetupAttach(BRaceSetup* r, int32_t languageID,
                            int32_t blurbID, BSetupChangeFn change,
                            BSetupRefreshFn refresh, int32_t* value)
{
    BChangeable* c;
    if (r->numRows == BRACESETUP_MAX_ROWS) return;
    c             = &r->rows[r->numRows++];
    c->menuItem   = 0;
    c->changeText = 0;
    c->languageID = languageID;
    c->value      = value;
    c->change     = change;
    c->refresh    = refresh;
    c->blurbID    = blurbID;
}

// ResyncChangeables (0x001b7ca0): every row's value text, from its value.
static void raceSetupResync(BSetup* s, BRaceSetup* r)
{
    for (int i = 0; i < r->numRows; i++) {
        BChangeable* c = &r->rows[i];
        c->refresh(s, r, *c->value, c->changeText);
    }
}

// BuildMenu (0x001b85b8). The masks all go in, with indicator mode 1. Each
// row takes the next item and value text: the text shown, the item shown
// and enabled on the screen called `name` and given the row's label, and
// the text shown again. The items past the rows are hidden with their
// text. The scroller gets the rows' texts, then their items.
static void raceSetupBuildMenu(BSetup* s, BRaceSetup* r, const char* name)
{
    BAnim* a = clock(s);
    int    i;

    bsel_set_indicator_mode(&r->sel, 1);
    bsel_add_items(a, &r->sel, kRowMasks, BRACESETUP_MAX_ROWS);
    for (i = 0; i < r->numRows; i++) {
        BChangeable* c = &r->rows[i];
        c->menuItem    = kRowItems[i];
        c->changeText  = kRowTexts[i];
        HOOK(s, setVisible, r->screen, c->changeText, 1);
        HOOK(s, grayMenuItemNamed, name, r->screen, c->menuItem, 1);
        HOOK(s, setLanguageID, r->screen, c->menuItem, c->languageID);
        HOOK(s, setVisible, r->screen, c->changeText, 1);
    }
    for (; i < BRACESETUP_MAX_ROWS; i++) {
        HOOK(s, grayMenuItemNamed, name, r->screen, kRowItems[i], 2);
        HOOK(s, setVisible, r->screen, kRowTexts[i], 0);
    }
    r->scroller.numMenuItemsToScroll = r->numRows;
    scrollAddObjects(s, &r->scroller, kRowTexts, r->numRows);
    scrollAddObjects(s, &r->scroller, kRowItems, r->numRows);
}

// SetupHighlight (0x001b7d50): the brackets to the mask's box, as
// OnHighlight puts You're The Cop's round the item's. Retail's box is the
// stack's until GetBoundingBox finds the mask.
static void raceSetupHighlightBox(BSetup* s, BRaceSetup* r, uint32_t mask)
{
    int32_t box[4] = {0, 0, 0, 0};   // left, top, right, bottom

    if (s->hooks.getBoundingBox)
        s->hooks.getBoundingBox(s->hooks.user, r->screen, mask, box);
    HOOK(s, setTopLeftY, r->screen, BSCR_OBJ_MI_UNDERSCORE,
         (int32_t)((float)box[3] + -3.0f));
    HOOK(s, setTopLeftY, r->screen, BSCR_OBJ_MI_OVERSCORE,
         (int32_t)((float)box[1] - 6.0f));
}

// The constructor (0x001b8390), in its order: the SelectionSet, the slide
// in to MI_1_MASK's X, the two blooms (the item's in BloomTargetColor, the
// value's in its own), the scroller on MENUITEM_1 .. MENUITEM_7, the
// arrows, the blurb, the movie, and both arrows clipped to the poly.
static void raceSetupCtor(BSetup* s, BRaceSetup* r, uint32_t screen)
{
    BAnim* a = clock(s);

    memset(r, 0, sizeof(*r));
    bsel_init(a, &r->sel, screen);
    banim_slide_in_init(a, &r->slideIn, screen,
                        topLeftX(s, screen, BSCR_MI_MASK(1)));
    banim_highlight_init(a, &r->highlight, screen, 0xab671c9au,
                         (int32_t)BANIM_BLOOM_COLOR);
    banim_highlight_init(a, &r->change, screen, 0x1042eac3u, -1);
    scrollInit(s, &r->scroller, screen, BSCR_ITEM_MENUITEM(1),
               BSCR_ITEM_MENUITEM(7), BSETUP_OBJ_UP_ARROW,
               BSETUP_OBJ_DOWN_ARROW, BSETUP_OBJ_CLIP_POLY);
    barrows_init(s, &r->arrows, screen, BSETUP_OBJ_LEFT_ARROW,
                 BSETUP_OBJ_RIGHT_ARROW);
    banim_blurb_init(a, &r->blurb, screen, BSCR_OBJ_SCROLLING_TEXT,
                     BSCR_OBJ_SCROLLING_TEXT, BSCR_OBJ_WHITEOUT_BAR);
    r->screen = screen;
    startTheRightMovie(s);
    r->exitActive = 0;
    HOOK(s, setClipToPoly, screen, BSETUP_OBJ_LEFT_ARROW,
         BSETUP_OBJ_CLIP_POLY);
    HOOK(s, setClipToPoly, screen, BSETUP_OBJ_RIGHT_ARROW,
         BSETUP_OBJ_CLIP_POLY);
    r->current = 0;
}

// The destructor (0x001b84f0): the help override off, the exit animation
// if one ran, then the members in reverse. The blooms', the
// SelectionSet's and the rows' only free.
static void raceSetupDtor(BSetup* s, BRaceSetup* r)
{
    BAnim* a = clock(s);

    HOOK(s, setHelpOverride, NULL);
    if (r->exitActive) banim_slide_release(a, &r->exit.slide);
    banim_blurb_release(a, &r->blurb);
    scrollRelease(s, &r->scroller);
    banim_slide_release(a, &r->slideIn);
    memset(r, 0, sizeof(*r));
}

// HandleMenuEvent (0x001b7ea8). A tick animates both blooms first; the
// arrows see every message; a running exit takes every message and nothing
// else does; then the scroller, then the message itself.
static void raceSetupEvent(BSetup* s, BRaceSetup* r, BScreenMessage msg,
                           BScreenCallbackData* data)
{
    BAnim*       a = clock(s);
    BChangeable* c;
    int          idx;

    if (msg == BMSG_SCREEN_TICK) {
        banim_highlight_animate(a, &r->highlight);
        banim_highlight_animate(a, &r->change);
    }
    barrows_event(s, &r->arrows, msg);
    if (r->exitActive) {
        int32_t param = data ? data->param : 0;
        int32_t noise = data ? data->noise : 0;
        // A finished exit changes screen, which unactivates this one and
        // clears `r`. Nothing after this may touch it.
        banim_exit_message(a, &r->exit, (int)msg, &param, &noise);
        if (data) {
            data->param = param;
            data->noise = noise;
        }
        return;
    }
    if (!data) return;
    scrollEvent(s, &r->scroller, msg, data);

    switch (msg) {
        // SELECT: car select, the two-player screen if Fred says two cars.
        // The brackets leave with the items, and the arrows go.
        case BMSG_MENUITEM_SELECT: {
            const char* target =
                fredGet(s, FRED_NUM_PLAYER_CARS) == 2 ? "Select Car2P"
                                                      : "Select Car";
            banim_exit_init(a, &r->exit, r->screen, target);
            r->exitActive = 1;
            banim_slide_add_group(a, &r->exit.slide, BSCR_GROUP_UNDERSCORE,
                                  BSCR_OBJ_MI_UNDERSCORE,
                                  topLeftX(s, r->screen,
                                           BSCR_OBJ_MI_UNDERSCORE),
                                  BANIM_OFFSCREEN_X,
                                  r->exit.slide.totalTime);
            barrows_set(s, &r->arrows, 0);
            break;
        }
        // HIGHLIGHT: the row's line (retail reads the row unchecked), the
        // arrows on the item's value, the mask and brackets where the
        // scroller has the mask, and the two blooms.
        case BMSG_MENUITEM_HIGHLIGHT:
            c = findRow(r, data->itemHash);
            if (c) banim_blurb_new_text_id(a, &r->blurb, c->blurbID);
            r->current = data->itemHash;
            idx        = rowIndex(data->itemHash);
            barrows_set(s, &r->arrows, kRowTexts[idx]);
            bsel_set_current(a, &r->sel, scrollCurrentMask(&r->scroller));
            raceSetupHighlightBox(s, r, scrollCurrentMask(&r->scroller));
            banim_highlight_set_item(a, &r->highlight, kRowItems[idx]);
            banim_highlight_set_item(a, &r->change, kRowTexts[idx]);
            break;
        // LEFT and RIGHT: the row changes by one and its text follows, with
        // the menu's sound and the value's bloom; no change is silent.
        case BMSG_MENUITEM_PAD_LEFT:
        case BMSG_MENUITEM_PAD_RIGHT: {
            int32_t dir = msg == BMSG_MENUITEM_PAD_LEFT ? -1 : 1;
            c           = findRow(r, data->itemHash);
            if (!c) break;
            if (!c->change(s, r, dir, c->value)) {
                data->noise = 0;
                break;
            }
            c->refresh(s, r, *c->value, c->changeText);
            data->noise = msg == BMSG_MENUITEM_PAD_LEFT ? BSND_MENU_LEFT
                                                        : BSND_MENU_RIGHT;
            banim_highlight_force_start(a, &r->change);
            break;
        }
        // UP on the first row and DOWN on the last are taken: the menu does
        // not wrap.
        case BMSG_MENUITEM_PAD_UP:
            if (data->itemHash == BSCR_ITEM_MENUITEM(1)) data->param = 1;
            break;
        case BMSG_MENUITEM_PAD_DOWN:
            if (!(rowIndex(data->itemHash) < r->numRows - 1)) data->param = 1;
            break;
        case BMSG_SCREEN_TICK:
            banim_blurb_animate(a, &r->blurb);
            if (!banim_slide_finished(&r->slideIn))
                banim_slide_animate(a, &r->slideIn);
            break;
        default:
            break;
    }
}

// ----------------------------------------------------------- BeTheCopSetup

// The constructor (0x001b9248): the base, Fred's five words, the three
// rows -- Catch-up, Traffic, Damage -- then the menu and their values.
static void btcCtor(BSetup* s, uint32_t screen)
{
    BRaceSetup* r = &s->race;

    raceSetupCtor(s, r, screen);
    if (s->gf->fred) btcLoad(&r->btc, s->gf->fred);
    else bsetup_btc_defaults(&r->btc);
    raceSetupAttach(r, 30005, 30502, maybeChangeCatchup, refreshCatchup,
                    &r->btc.catchup);
    raceSetupAttach(r, 30006, 30503, maybeChangeTraffic, refreshTraffic,
                    &r->btc.traffic);
    raceSetupAttach(r, 30101, 30504, maybeChangeDamage, refreshDamage,
                    &r->btc.damage);
    raceSetupBuildMenu(s, r, "Be The Cop Setup");
    raceSetupResync(s, r);
    r->live = 1;
}

// The destructor (0x001b9348): Fred gets the five words back, and the race
// its parameters and the challenge its cars, whether or not SELECT went.
static void btcDtor(BSetup* s)
{
    BRaceSetup* r = &s->race;

    if (s->gf->fred) btcSave(&r->btc, s->gf->fred);
    HOOK0(s, setupRaceParametersAfterRaceSetup);
    HOOK0(s, makeChallengeCarsAvailable);
    raceSetupDtor(s, r);
}

// BaseCallback (0x001b7b20), which ACTIVATE news the screen on for (104 is
// BeTheCopSetup), UNACTIVATE deletes, and everything else goes to
// HandleMenuEvent -- in retail with pInstance unchecked.
void bsetup_btc_callback(BGameFlow* gf, BScreenMessage msg,
                         BScreenCallbackData* data)
{
    BSetup* s = g_setup;

    if (!s || !gf->anim) return;
    s->gf = gf;
    switch (msg) {
        case BMSG_SCREEN_ACTIVATE:
            btcCtor(s, data ? data->itemHash : BSETUP_SCREEN_BE_THE_COP_SETUP);
            break;
        case BMSG_SCREEN_UNACTIVATE:
            if (s->race.live) btcDtor(s);
            break;
        default:
            if (s->race.live) raceSetupEvent(s, &s->race, msg, data);
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

BSetup* bsetup_instance(void)
{
    return g_setup;
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
