// Options' Controller (joyconfig.h): JoystickPreConfig, then
// JoystickConfigScreen made the page where the keys are picked.

#include "joyconfig.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "banim.h"
#include "bpopup.h"
#include "bscreens.h"
#include "bsetup.h"
#include "flailer.h"
#include "helpglyph.h"
#include "joyhid.h"
#include "portlang.h"

#define GROUP_SCREEN 0x457755c9u

// The save prompt, as Display Options': memcard.c's popup, titled "Save"
// (150000), with its Yes and No (150103, 150104).
#define LANG_SAVE 0x249f0
#define LANG_YES  0x24a57
#define LANG_NO   0x24a58

#define AUTOSAVE_SCREEN "Autosave"
#define CONFIG_NAME     "Joystick Config Port1"

enum { ANSWER_STAY, ANSWER_DISCARD, ANSWER_SAVE };

static JoyConfigHooks sHooks;

static void say(const char* fmt, ...)
{
    char    line[160];
    va_list ap;

    if (!sHooks.log) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    sHooks.log(sHooks.user, line);
}

static void noise(int n)
{
    if (sHooks.noise && n) sHooks.noise(n, sHooks.user);
}

static void showScreen(BGameFlow* gf, uint32_t screen, int visible)
{
    if (screen && gf->hooks.setScreenVisible)
        gf->hooks.setScreenVisible(gf->hooks.user, screen, visible);
}

static void hide(uint32_t screen, uint32_t object)
{
    flailer_set_visibility(screen, object, FLAILER_OBJECT_INVISIBLE);
}

static void show(uint32_t screen, uint32_t object, int visible)
{
    flailer_set_visibility(screen, object, visible ? FLAILER_OBJECT_VISIBLE
                                                   : FLAILER_OBJECT_INVISIBLE);
}

void joyconfig_init(const JoyConfigHooks* hooks)
{
    memset(&sHooks, 0, sizeof sHooks);
    if (hooks) sHooks = *hooks;
}

// ----------------------------------------------------- JoystickPreConfig
//
// Retail's rows: Player 1's Configuration, Calibration and Vibration, then
// Player 2's. The port's is the first alone; the rest go, their values,
// arrows and masks, and the "Player 2" heading.

#define PRE_OFF_P1      0x3fabc377u
#define PRE_OFF_P2      0xe2f33138u
#define PRE_ARROW_L_P1  0x7bcd6704u
#define PRE_ARROW_R_P1  0x7c51b6d7u
#define PRE_ARROW_L_P2  0x7bcd6705u
#define PRE_ARROW_R_P2  0x7c51b6d8u
#define LANG_PLAYER_2   160206
// "Change controls on controller 1."
#define PRE_BLURB       150600

static BScreenInstance sPre;

static void preConstruct(BGameFlow* gf, uint32_t screen)
{
    struct FlailerObjectChunk* o = NULL;
    int                        n;

    bscr_optbase_construct(&sPre, screen);
    for (n = 2; n <= 6; n++) {
        if (gf->hooks.grayMenuItem)
            gf->hooks.grayMenuItem(gf->hooks.user, screen,
                                   BSCR_ITEM_MENUITEM(n), BSCR_GRAY_HIDE);
        hide(screen, BSCR_MI_MASK(n));
    }
    hide(screen, PRE_OFF_P1);
    hide(screen, PRE_OFF_P2);
    hide(screen, PRE_ARROW_L_P1);
    hide(screen, PRE_ARROW_R_P1);
    hide(screen, PRE_ARROW_L_P2);
    hide(screen, PRE_ARROW_R_P2);
    while ((o = flailer_find_object_by_group(screen, GROUP_SCREEN,
                                             FLAILER_TYPE_TEXT, o)) != NULL)
        if (((struct FlailerTextChunk*)o)->LanguageID == LANG_PLAYER_2)
            flailerobject_set_visibility(o, FLAILER_OBJECT_INVISIBLE);
    say("controller: in");
}

void joypreconfig_callback(BGameFlow* gf, BScreenMessage msg,
                           BScreenCallbackData* data)
{
    uint32_t item;

    if (msg == BMSG_SCREEN_ACTIVATE) {
        preConstruct(gf, data ? data->itemHash : JOYPRECONFIG_SCREEN);
        return;
    }
    if (!sPre.live) return;
    if (msg == BMSG_SCREEN_UNACTIVATE) {
        bscr_optbase_destruct(&sPre);
        return;
    }
    if (bscr_optbase_first_crack(&sPre, msg, data)) return;
    item = data ? data->itemHash : 0;
    switch (msg) {
    case BMSG_MENUITEM_HIGHLIGHT:
        banim_blurb_new_text_id(bscr_anim(), &sPre.blurbAnim,
                                item == BSCR_ITEM_MENUITEM(1) ? PRE_BLURB : 0);
        return;
    case BMSG_MENUITEM_SELECT:
        if (item == BSCR_ITEM_MENUITEM(1)) {
            say("controller: to %s", CONFIG_NAME);
            bscr_optbase_exit(&sPre, CONFIG_NAME);
        } else if (data) {
            data->noise = BSND_NONE;
        }
        return;
    case BMSG_MENUITEM_PAD_UP:
    case BMSG_MENUITEM_PAD_DOWN:
        // One row: nothing to move to, and no noise.
        if (data) data->param = 1;
        return;
    default:
        return;
    }
}

// --------------------------------------------------- JoystickConfigScreen

// The table's name (MENUITEM_1, retail's configuration letter) between its
// arrows, and retail's picture of the pad, which the port has none of.
#define OBJ_TABLE     BSCR_ITEM_MENUITEM(1)
#define OBJ_ARROW_L   0xd1cda594u
#define OBJ_ARROW_R   0x9345e4a7u
#define OBJ_PICTURE   0x0b2ad6dfu

// The left panel the name and its arrows sit in: x 0 .. 133, and the
// name's authored scale.
#define PANEL_RIGHT   133.0f
#define PANEL_MARGIN  6.0f
#define TABLE_SCALE   1.25f
#define TABLE_Y       80.0f

// The labels' colour as authored (the GS's, alpha on top), and the current
// one's: white.
#define COLOR_LABEL   0x80505050u
#define COLOR_CURRENT 0x80808080u

// The fixed rows: Steering (the Circle Pad, or the D-pad's Left and
// Right), Pause (START), and the C-Stick's throttle and brake.
#define OBJ_STEER_LABEL   0x7cc1f1ffu
#define OBJ_STEER_GLYPH   0xff20a4fbu
#define OBJ_STEER_ALT     0xcdf8d89au
#define OBJ_THROTTLE_ALT  0x967b758fu
#define OBJ_BRAKE_ALT     0xe5fa6ddeu
#define OBJ_BOOST_ALT     0x380e492bu
#define OBJ_BOOST_PLUS    0x5f73d02fu
#define OBJ_PAUSE_LABEL   0x6bee2b3cu
#define OBJ_PAUSE_GLYPH   0xd3d405d8u

// The Zone rows' second half, the racer's: the camera's key and its '+'
// before each shift key in the Manual half.
#define OBJ_FREEZE_CAMERA 0x05a3ec91u
#define OBJ_FREEZE_PLUS   0xe98f9ed5u
#define OBJ_ZOOM_CAMERA   0xede8c395u
#define OBJ_ZOOM_PLUS     0xd953a559u

// Retail's labels' LanguageIDs.
#define LANG_STEERING    120013
#define LANG_THROTTLE    120001
#define LANG_BRAKE       120002
#define LANG_EBRAKE      120003
#define LANG_CAMERA      120005
#define LANG_LOOKBACK    120006
#define LANG_SHIFTDOWN   120007
#define LANG_SHIFTUP     120008
#define LANG_ZONEFREEZE  120010
#define LANG_ZONEZOOM    120011
#define LANG_BOOST       120014
#define LANG_HORN        121001
#define LANG_PAUSE       121004
#define LANG_HUD         121005

// Each label and its glyph, where it is (the column, and the line: retail's
// MI_n_MASK lights lines 1 .. 7), and the action it shows in each table:
// -1 for none, the row hidden; JOYCFG_SHOWS for a key it shows but is not
// picked here (the racer's Zone rows show the shift keys they use).
#define JOYCFG_SHOWS 0x40

typedef struct {
    uint32_t label, glyph;
    uint8_t  column, line;     // 0 left, 1 right; 1 .. 8
    int8_t   racer, cop;       // JOYHID_ACT_*, | JOYCFG_SHOWS, or -1
    int32_t  langRacer, langCop;
} Slot;

#define SHOWS(a) ((int8_t)((a) | JOYCFG_SHOWS))

static const Slot kSlots[] = {
    { 0x487e6614u, 0x426b9bb0u, 0, 2, JOYHID_ACT_THROTTLE,
      JOYHID_ACT_THROTTLE, LANG_THROTTLE, LANG_THROTTLE },
    { 0xe9c869c3u, 0x0cf6153fu, 0, 3, JOYHID_ACT_BRAKE, JOYHID_ACT_BRAKE,
      LANG_BRAKE, LANG_BRAKE },
    { 0x336aa372u, 0x8adf84ceu, 0, 4, -1, JOYHID_ACT_BOOST,
      LANG_BOOST, LANG_BOOST },
    { 0x866729bfu, 0x3d6cd4bbu, 0, 6, JOYHID_ACT_HUD, JOYHID_ACT_HUD,
      LANG_HUD, LANG_HUD },
    { 0x42d77800u, 0x87e6eb1cu, 0, 7, JOYHID_ACT_SHIFTUP,
      JOYHID_ACT_SHIFTUP, LANG_SHIFTUP, LANG_SHIFTUP },
    { 0x1bf89b53u, 0x852c78cfu, 0, 8, JOYHID_ACT_SHIFTDOWN,
      JOYHID_ACT_SHIFTDOWN, LANG_SHIFTDOWN, LANG_SHIFTDOWN },
    { 0xfcf4e8c8u, 0x85b274e4u, 1, 1, JOYHID_ACT_EBRAKE, JOYHID_ACT_EBRAKE,
      LANG_EBRAKE, LANG_EBRAKE },
    { 0x4c040295u, 0xb6a4c851u, 1, 2, JOYHID_ACT_HORN, JOYHID_ACT_HORN,
      LANG_HORN, LANG_HORN },
    { 0x15524647u, 0xa9bb8243u, 1, 3, JOYHID_ACT_CAMERA, JOYHID_ACT_CAMERA,
      LANG_CAMERA, LANG_CAMERA },
    { 0xecd38543u, 0x7164a0bfu, 1, 4, JOYHID_ACT_LOOKBACK,
      JOYHID_ACT_LOOKBACK, LANG_LOOKBACK, LANG_LOOKBACK },
    // The automatic box's Zone rows: the shift keys alone; the cop's calls.
    { 0xd565eebbu, 0x6c443937u, 1, 5, SHOWS(JOYHID_ACT_SHIFTDOWN),
      JOYHID_ACT_ROADBLOCK, LANG_ZONEFREEZE, PORTLANG_ROADBLOCK },
    { 0xdc950ebfu, 0x595759bbu, 1, 6, SHOWS(JOYHID_ACT_SHIFTUP),
      JOYHID_ACT_HELICOPTER, LANG_ZONEZOOM, PORTLANG_HELICOPTER },
    // The Manual half's, the camera's key with the shift key: the racer's.
    { 0x3991ed98u, 0x55f013b4u, 1, 7, SHOWS(JOYHID_ACT_SHIFTDOWN), -1,
      LANG_ZONEFREEZE, LANG_ZONEFREEZE },
    { 0x6184611cu, 0x7c30f7b8u, 1, 8, SHOWS(JOYHID_ACT_SHIFTUP), -1,
      LANG_ZONEZOOM, LANG_ZONEZOOM },
};

#define NUM_SLOTS ((int)(sizeof kSlots / sizeof kSlots[0]))
#define ROW_TABLE (-1)
// A mask no screen has: the SelectionSet lights no line. Line 8 has none
// of its own (its band is always the lighter one).
#define MASK_NONE 1u

typedef struct {
    BScreenInstance inst;
    BArrows         arrows;
    int             cop;        // the table shown
    int             cursor;     // a kSlots index, or ROW_TABLE
    int             waiting;    // for the cursor's new key
    int             asking;     // the save prompt is up
    float           blink;
    JoyHidBindings  entry;      // as the page found them
    BGameFlow*      gf;
} ConfigScreen;

static ConfigScreen sConfig;
static char         sBody[320];

static uint8_t* shownTable(ConfigScreen* c)
{
    return c->cop ? gJoyHidBindings.cop : gJoyHidBindings.racer;
}

static int slotAction(const ConfigScreen* c, int i)
{
    return c->cop ? kSlots[i].cop : kSlots[i].racer;
}

// A slot the cursor can be on: one whose action is picked here.
static int pickable(const ConfigScreen* c, int i)
{
    int a = slotAction(c, i);
    return a >= 0 && !(a & JOYCFG_SHOWS);
}

static void printGlyph(uint32_t screen, uint32_t object, unsigned char ch)
{
    if (!ch) {
        hide(screen, object);
        return;
    }
    flailer_printf(screen, object, "%c", ch);
    show(screen, object, 1);
}

// The table's name between its arrows, at its own scale or less: the
// arrows to the panel's edges, the name centred between them.
static void layoutTable(ConfigScreen* c)
{
    uint32_t screen = c->inst.screen;
    float    aw     = (float)flailer_get_width(screen, OBJ_ARROW_L);
    float    left, right, w, h, k = 1.0f;

    if (aw <= 0.0f) aw = 16.0f;
    flailer_set_top_left_x(screen, OBJ_ARROW_L, (int32_t)PANEL_MARGIN);
    flailer_set_top_left_x(screen, OBJ_ARROW_R,
                           (int32_t)(PANEL_RIGHT - PANEL_MARGIN - aw));
    left  = PANEL_MARGIN + aw + 4.0f;
    right = PANEL_RIGHT - PANEL_MARGIN - aw - 4.0f;

    flailer_set_language_id(screen, OBJ_TABLE,
                            c->cop ? PORTLANG_COP : PORTLANG_RACER);
    flailer_set_scale_x(screen, OBJ_TABLE, TABLE_SCALE);
    flailer_set_scale_y(screen, OBJ_TABLE, TABLE_SCALE);
    w = (float)flailer_get_width(screen, OBJ_TABLE);
    h = (float)flailer_get_height(screen, OBJ_TABLE);
    if (w > right - left && w > 0.0f) {
        k = (right - left) / w;
        flailer_set_scale_x(screen, OBJ_TABLE, TABLE_SCALE * k);
        flailer_set_scale_y(screen, OBJ_TABLE, TABLE_SCALE * k);
        w *= k;
    }
    flailer_set_top_left_x(screen, OBJ_TABLE,
                           (int32_t)(left + (right - left - w) / 2));
    flailer_set_top_left_y(screen, OBJ_TABLE,
                           (int32_t)(TABLE_Y + h * (1.0f - k) / 2));
}

// Everything the shown table says: the name, the rows it has and each
// one's key.
static void redraw(ConfigScreen* c)
{
    uint32_t       screen = c->inst.screen;
    const uint8_t* t      = shownTable(c);
    int            i;

    layoutTable(c);
    for (i = 0; i < NUM_SLOTS; i++) {
        const Slot* s = &kSlots[i];
        int         a = slotAction(c, i);
        int         on = a >= 0;

        show(screen, s->label, on);
        if (on) flailer_set_language_id(screen, s->label,
                                        c->cop ? s->langCop : s->langRacer);
        printGlyph(screen, s->glyph,
                   on ? helpglyph_key_char(t[a & ~JOYCFG_SHOWS]) : 0);
    }
    // The racer's Manual Zone rows have the camera's key too.
    printGlyph(screen, OBJ_FREEZE_CAMERA,
               c->cop ? 0 : helpglyph_key_char(t[JOYHID_ACT_CAMERA]));
    printGlyph(screen, OBJ_ZOOM_CAMERA,
               c->cop ? 0 : helpglyph_key_char(t[JOYHID_ACT_CAMERA]));
    show(screen, OBJ_FREEZE_PLUS,
         !c->cop && t[JOYHID_ACT_CAMERA] != JOYHID_BIND_NONE
             && t[JOYHID_ACT_SHIFTDOWN] != JOYHID_BIND_NONE);
    show(screen, OBJ_ZOOM_PLUS,
         !c->cop && t[JOYHID_ACT_CAMERA] != JOYHID_BIND_NONE
             && t[JOYHID_ACT_SHIFTUP] != JOYHID_BIND_NONE);
}

// The fixed rows, once.
static void drawFixed(uint32_t screen)
{
    flailer_set_language_id(screen, OBJ_STEER_LABEL, LANG_STEERING);
    flailer_set_language_id(screen, OBJ_PAUSE_LABEL, LANG_PAUSE);
    printGlyph(screen, OBJ_STEER_GLYPH, 0x90);    // the Circle Pad
    printGlyph(screen, OBJ_STEER_ALT, 0x9a);      // the D-pad
    printGlyph(screen, OBJ_THROTTLE_ALT, 0x95);   // the C-Stick
    printGlyph(screen, OBJ_BRAKE_ALT, 0x95);
    printGlyph(screen, OBJ_PAUSE_GLYPH, 0x80);    // START
    hide(screen, OBJ_BOOST_ALT);
    hide(screen, OBJ_BOOST_PLUS);
    hide(screen, OBJ_PICTURE);
}

// The cursor shown: its line lit and its label white, or the arrows on the
// table's name.
static void applyCursor(ConfigScreen* c)
{
    BSetup*             s = bsetup_instance();
    BScreenCallbackData d;
    uint32_t            screen = c->inst.screen;
    int                 i;

    memset(&d, 0, sizeof d);
    for (i = 0; i < NUM_SLOTS; i++)
        flailer_set_text_color(screen, kSlots[i].label,
                               i == c->cursor ? COLOR_CURRENT : COLOR_LABEL);
    flailer_set_text_color(screen, OBJ_TABLE, c->cursor == ROW_TABLE
                                                  ? COLOR_CURRENT
                                                  : COLOR_LABEL);
    if (c->cursor == ROW_TABLE) {
        d.itemHash = OBJ_TABLE;
        bscr_optbase_highlight(&c->inst, &d, MASK_NONE);
        if (s) barrows_set(s, &c->arrows, OBJ_TABLE);
    } else {
        const Slot* sl = &kSlots[c->cursor];
        d.itemHash = sl->label;
        bscr_optbase_highlight(&c->inst, &d, sl->line <= 7
                                                 ? BSCR_MI_MASK(sl->line)
                                                 : MASK_NONE);
        if (s) barrows_set(s, &c->arrows, 0);
    }
}

static void configConstruct(BGameFlow* gf, ConfigScreen* c, uint32_t screen)
{
    BSetup* s = bsetup_instance();

    memset(c, 0, sizeof *c);
    bscr_optbase_construct(&c->inst, screen);
    c->gf     = gf;
    c->cursor = ROW_TABLE;
    c->entry  = gJoyHidBindings;
    if (s) barrows_init(s, &c->arrows, screen, OBJ_ARROW_L, OBJ_ARROW_R);
    drawFixed(screen);
    redraw(c);
    applyCursor(c);
    {
        char racer[2 * JOYHID_ACT_COUNT + 1], cop[2 * JOYHID_ACT_COUNT + 1];
        int  i;

        for (i = 0; i < JOYHID_ACT_COUNT; i++) {
            snprintf(racer + 2 * i, 3, "%02x", gJoyHidBindings.racer[i]);
            snprintf(cop + 2 * i, 3, "%02x", gJoyHidBindings.cop[i]);
        }
        say("controller config: in, racer %s cop %s", racer, cop);
    }
}

static void configDestruct(ConfigScreen* c)
{
    if (!c->inst.live) return;
    bscr_optbase_destruct(&c->inst);
    memset(c, 0, sizeof *c);
}

// The next pickable slot down (dir 1) or up (-1) the cursor's column, or
// -1 past its end.
static int stepInColumn(const ConfigScreen* c, int from, int dir)
{
    int best = -1, i;
    int col  = kSlots[from].column, line = kSlots[from].line;

    for (i = 0; i < NUM_SLOTS; i++) {
        int l = kSlots[i].line;
        if (!pickable(c, i) || kSlots[i].column != col) continue;
        if (dir > 0 ? l <= line : l >= line) continue;
        if (best < 0 || (dir > 0 ? l < kSlots[best].line
                                 : l > kSlots[best].line))
            best = i;
    }
    return best;
}

// The first pickable slot of a column from the top, or the nearest line to
// `line` in it.
static int nearestInColumn(const ConfigScreen* c, int col, int line)
{
    int best = -1, bestD = 99, i;

    for (i = 0; i < NUM_SLOTS; i++) {
        int dl;
        if (!pickable(c, i) || kSlots[i].column != col) continue;
        dl = kSlots[i].line - line;
        if (dl < 0) dl = -dl;
        if (dl < bestD) {
            best  = i;
            bestD = dl;
        }
    }
    return best;
}

static void moveTo(ConfigScreen* c, int cursor, int sound)
{
    if (cursor == c->cursor) return;
    c->cursor = cursor;
    applyCursor(c);
    noise(sound);
}

static void flipTable(ConfigScreen* c, int sound)
{
    c->cop = !c->cop;
    redraw(c);
    applyCursor(c);
    noise(sound);
    say("controller config: %s's keys", c->cop ? "cop" : "racer");
}

// The wait's end with key `k` pressed (a JOYHID_BIND_*).
static void bindKey(ConfigScreen* c, int k)
{
    uint8_t* t = shownTable(c);
    int      a = slotAction(c, c->cursor);

    c->waiting = 0;
    if (t[a] == k) {
        noise(BSND_MENU_SELECT);
    } else if (!joyhid_bind_keeps_drive(t, a, k)) {
        // The throttle or the brake would be left on no key.
        noise(BSND_MENU_CANCEL);
        say("controller config: %s action %d to key %d refused",
            c->cop ? "cop" : "racer", a, k);
    } else {
        joyhid_bind(t, a, k);
        noise(BSND_MENU_SELECT);
        say("controller config: %s action %d to key %d",
            c->cop ? "cop" : "racer", a, k);
    }
    redraw(c);
}

// --------------------------------------------------------- the prompt
//
// B with the keys not as the page found them asks "Save your changes to
// the card?", as Display Options does: Yes saves on the Autosave screen in
// this page's place, No puts the keys back and moves back, B stays.

static void askToSave(BGameFlow* gf, ConfigScreen* c)
{
    static const char kMessage[] = "Save your changes to the card?";
    BPopupConfig cfg;

    memset(&cfg, 0, sizeof cfg);
    cfg.numButtons     = 2;
    cfg.flags          = BPOPUP_HORIZONTAL | BPOPUP_CANCELABLE
                       | BPOPUP_BUTTONS_BELOW;
    cfg.parent         = gf->screen;
    cfg.screen         = BPOPUP_SCREEN_MEMCARD;
    cfg.message        = kMessage;
    cfg.button[0]      = LANG_YES;
    cfg.button[1]      = LANG_NO;
    cfg.buttonParam[0] = ANSWER_SAVE;
    cfg.buttonParam[1] = ANSWER_DISCARD;
    cfg.cancelParam    = ANSWER_STAY;
    cfg.dismissParam   = ANSWER_STAY;
    cfg.startButton    = 0;
    cfg.joyPort        = -1;
    cfg.title          = LANG_SAVE;
    say("controller back: changed, asking to save");
    if (bpopup_summon(gf, &cfg) < 0) {
        say("no popup free");
        return;
    }
    c->asking = 1;
    showScreen(gf, c->inst.screen, 0);
}

static void answered(BGameFlow* gf, ConfigScreen* c, int answer)
{
    if (!c->asking) return;
    c->asking = 0;
    showScreen(gf, c->inst.screen, 1);
    if (answer == ANSWER_STAY) {
        say("controller save: stay");
        return;
    }
    if (answer == ANSWER_SAVE) {
        say("controller save: yes");
        bgf_change_to_screen(gf, AUTOSAVE_SCREEN, 0);
        return;
    }
    gJoyHidBindings = c->entry;
    say("controller save: no, keys put back");
    bgf_move_back_screen(gf, 1);
}

static void configBack(BGameFlow* gf, ConfigScreen* c,
                       BScreenCallbackData* data)
{
    if (c->waiting) {
        data->param = 0;
        return;
    }
    if (!memcmp(&c->entry, &gJoyHidBindings, sizeof c->entry)) {
        say("controller back: unchanged");
        return;
    }
    data->param = 0;
    askToSave(gf, c);
}

static void configEvent(BGameFlow* gf, ConfigScreen* c, BScreenMessage msg,
                        BScreenCallbackData* data)
{
    BSetup* s = bsetup_instance();
    int     next;

    switch (msg) {
    case BMSG_MENUITEM_HIGHLIGHT:
        // The base lit MENUITEM_1's line; the cursor's own instead.
        applyCursor(c);
        return;
    case BMSG_MENUITEM_SELECT:
        if (data) data->noise = BSND_NONE;
        // START's select does nothing here; its wait-ending is the input's.
        if (data && data->param == BJOY_START) return;
        if (c->cursor == ROW_TABLE) {
            flipTable(c, BSND_MENU_SELECT);
        } else {
            c->waiting = 1;
            c->blink   = 0.0f;
            noise(BSND_MENU_SELECT);
            say("controller config: waiting for %s action %d's key",
                c->cop ? "cop" : "racer", slotAction(c, c->cursor));
        }
        return;
    case BMSG_MENUITEM_PAD_LEFT:
    case BMSG_MENUITEM_PAD_RIGHT:
        if (data) data->noise = BSND_NONE;
        if (c->cursor == ROW_TABLE) {
            flipTable(c, msg == BMSG_MENUITEM_PAD_LEFT ? BSND_MENU_LEFT
                                                       : BSND_MENU_RIGHT);
            return;
        }
        next = nearestInColumn(c, !kSlots[c->cursor].column,
                               kSlots[c->cursor].line);
        if (next >= 0)
            moveTo(c, next, msg == BMSG_MENUITEM_PAD_LEFT ? BSND_MENU_LEFT
                                                          : BSND_MENU_RIGHT);
        return;
    case BMSG_MENUITEM_PAD_UP:
        if (data) data->param = 1;
        if (c->cursor == ROW_TABLE) return;
        next = stepInColumn(c, c->cursor, -1);
        moveTo(c, next >= 0 ? next : ROW_TABLE, BSND_MENU_UP);
        return;
    case BMSG_MENUITEM_PAD_DOWN:
        if (data) data->param = 1;
        next = c->cursor == ROW_TABLE ? nearestInColumn(c, 0, 1)
                                      : stepInColumn(c, c->cursor, 1);
        if (next >= 0) moveTo(c, next, BSND_MENU_DOWN);
        return;
    case BMSG_SCREEN_START_BUTTON:
        if (data) data->param = 1;
        return;
    case BMSG_SCREEN_BACK_BUTTON:
        if (data) configBack(gf, c, data);
        return;
    case BMSG_POPUP_DISMISS:
        answered(gf, c, data ? data->param : ANSWER_STAY);
        return;
    case BMSG_SCREEN_TICK:
        if (s) barrows_event(s, &c->arrows, msg);
        if (c->waiting && c->cursor != ROW_TABLE) {
            const Slot* sl = &kSlots[c->cursor];
            c->blink += gf->realElapsed;
            if (c->blink >= 0.6f) c->blink -= 0.6f;
            show(c->inst.screen, sl->glyph, c->blink < 0.35f
                 && shownTable(c)[slotAction(c, c->cursor)]
                        != JOYHID_BIND_NONE);
        }
        return;
    default:
        return;
    }
}

void joyconfig_callback(BGameFlow* gf, BScreenMessage msg,
                        BScreenCallbackData* data)
{
    ConfigScreen* c = &sConfig;

    if (msg == BMSG_SCREEN_ACTIVATE) {
        configConstruct(gf, c, data ? data->itemHash : JOYCONFIG_SCREEN);
        return;
    }
    if (!c->inst.live) return;
    if (msg == BMSG_SCREEN_UNACTIVATE) {
        configDestruct(c);
        return;
    }
    if (bscr_optbase_first_crack(&c->inst, msg, data)) return;
    configEvent(gf, c, msg, data);
}

// ------------------------------------------------------ main.c's half

static int pageUp(void)
{
    return sConfig.inst.live && !sConfig.asking && !sConfig.inst.exitActive;
}

uint32_t joyconfig_input(uint32_t down)
{
    ConfigScreen* c = &sConfig;
    int           k;

    if (!pageUp()) return 0;
    if (c->waiting) {
        if (down & JOYHID_START) {
            c->waiting = 0;
            noise(BSND_MENU_CANCEL);
            redraw(c);
            say("controller config: wait stopped");
            return ~0u;
        }
        for (k = 0; k < JOYHID_BIND_KEYS; k++)
            if (down & joyhid_bind_key(k)) {
                bindKey(c, k);
                break;
            }
        return ~0u;
    }
    if (down & JOYHID_X) {
        JoyHidBindings d;

        joyhid_default_bindings(&d);
        memcpy(shownTable(c), c->cop ? d.cop : d.racer, JOYHID_ACT_COUNT);
        redraw(c);
        noise(BSND_MENU_SELECT);
        say("controller config: %s's keys to the defaults",
            c->cop ? "cop" : "racer");
        return JOYHID_X;
    }
    return 0;
}

int32_t joyconfig_help_layout(void)
{
    return pageUp() ? HELPGLYPH_LAYOUT_KEYS : -1;
}

// The label's text with the help line's: the action's name, for the wait.
const char* joyconfig_bottom_body(void)
{
    ConfigScreen* c = &sConfig;
    char          tmpl[256], name[64];
    const char*   at;
    const Slot*   sl;

    if (!pageUp()) return NULL;
    if (!sHooks.text) return "";
    if (!c->waiting || c->cursor == ROW_TABLE) {
        sHooks.text(sHooks.user, PORTLANG_CONTROLS_BLURB, sBody, sizeof sBody);
        return sBody;
    }
    sl = &kSlots[c->cursor];
    sHooks.text(sHooks.user, PORTLANG_CONTROLS_PRESS, tmpl, sizeof tmpl);
    sHooks.text(sHooks.user, c->cop ? sl->langCop : sl->langRacer, name,
                sizeof name);
    at = strstr(tmpl, "$NAME");
    if (!at) {
        snprintf(sBody, sizeof sBody, "%s", tmpl);
    } else {
        snprintf(sBody, sizeof sBody, "%.*s%s%s", (int)(at - tmpl), tmpl,
                 name, at + 5);
    }
    return sBody;
}

// In HELPGLYPH_LAYOUT_KEYS's characters: Cross is A, Circle B, Triangle X.
const char* joyconfig_bottom_hint(void)
{
    ConfigScreen* c = &sConfig;

    if (!pageUp()) return NULL;
    if (c->waiting) return "\x80 Cancel";
    // Two lines, A's (or the arrows') and B's on top, X's under them: one
    // line of three did not fit beside the logo.
    if (c->cursor == ROW_TABLE)
        return "\x84\x85 Racer/Cop  \x89 Back\n\x87 Defaults";
    return "\x86 Change  \x89 Back\n\x87 Defaults";
}
