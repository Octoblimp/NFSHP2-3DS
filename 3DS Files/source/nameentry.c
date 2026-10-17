// NameEntry (nameentry.h), retail's in its order: the constructor
// (0x0024d408), HandleEvent (0x0024d870) under Callback (0x0024dbd8),
// MaybeActivateKeyboard (0x0024d5c0), ChangeGender (0x0024d660),
// RedrawGenders (0x0024d7b0) and tNameEntryData (0x0024d2f0, 0x0024d370).
// Where retail opens tKeyboard, this opens the 3DS's, and does at once
// what tKeyboard's done key does when the player confirms. Where retail's
// BACK saves only with autosave on, this asks (the save prompt, below).

#include "nameentry.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "banim.h"
#include "bpopup.h"
#include "bscreens.h"
#include "bsetup.h"
#include "flailer.h"
#include "fred.h"
#include "portlang.h"

// The rows, MENUITEM_1..4: Player 1's name and gender, Player 2's.
#define ITEM_P1_NAME   BSCR_ITEM_MENUITEM(1)
#define ITEM_P1_GENDER BSCR_ITEM_MENUITEM(2)
#define ITEM_P2_NAME   BSCR_ITEM_MENUITEM(3)
#define ITEM_P2_GENDER BSCR_ITEM_MENUITEM(4)

// The values: each name's text, and the genders' ("P1_GENDER",
// "P2_GENDER").
#define OBJ_P1_NAME    0x71450a81u
#define OBJ_P2_NAME    0x71572302u
#define OBJ_P1_GENDER  0xd6f9d954u
#define OBJ_P2_GENDER  0xc33bae35u

// tKeyboard's, hidden by tKeyboard::SetVisible (0x0024c5d0) with 0: the
// grid's group, each player's seven character boxes, and the cursor.
#define GROUP_KEYBOARD 0x670b6fddu
#define GROUP_P1_CHARS 0x7b95e55cu
#define GROUP_P2_CHARS 0x7deb0dfdu
#define OBJ_CURSOR     0xc01086b5u

// Player 2's half, which the port hides: its rows' bars (MI_3_MASK,
// MI_4_MASK) and the "Player 2" label, a text named like the title's and
// "Player 1"'s, in the screen's common group, found by its string.
#define OBJ_MI_3_MASK  0x72df3492u
#define OBJ_MI_4_MASK  0x75345d33u
#define GROUP_SCREEN   0x457755c9u
#define LANG_PLAYER_2  160206

// The two blooms' spare texts and the arrows, as the setup screens have.
#define OBJ_BLOOM      0xab671c9au
#define OBJ_BLOOM_VAL  0x1042eac3u

#define LANG_MALE      160004
#define LANG_FEMALE    160005
// "Enter name for Player 1." .. "Set the gender for Player 2.", by row.
#define LANG_BLURB     150800

// FrontendSoundEvent 29, NameFinalSelect: tKeyboard's done key.
#define SOUND_NAME_DONE 29

// cPlayerSettings::SetName (0x00187de8): bStrNCpy of 11.
#define SETNAME_COPY   11

// The screen the end of a race saves on (main.c's kScreens).
#define AUTOSAVE_SCREEN "Autosave"

// The save prompt: memcard.c's popup, titled "Save" (150000), with its Yes
// and No (150103, 150104), as the debug menu's.
#define LANG_SAVE 0x249f0
#define LANG_YES  0x24a57
#define LANG_NO   0x24a58

enum { ANSWER_STAY, ANSWER_DISCARD, ANSWER_SAVE };

// tNameEntryData, 32 bytes: the names and genders as the screen found
// them, so BACK can tell whether anything changed.
typedef struct {
    char    p1Name[12];   // +0
    char    p2Name[12];   // +12
    int32_t gender1;      // +24
    int32_t gender2;      // +28
} NameEntryData;

// NameEntry, 776 bytes in retail (bMalloc'd on SCREEN_ACTIVATE, its
// pointer at 0x00331ed4). tKeyboard and State are the 3DS keyboard's now,
// which is never open across a callback.
typedef struct {
    int            live;
    int            asking;      // the save prompt is up
    uint32_t       screen;      // +4
    NameEntryData  data;        // +228
    BHighlightAnim highlight;   // +260
    BHighlightAnim change;      // +292
    BArrows        arrows;      // +324
    BBlurb         blurb;       // +356
} NameEntry;

static NameEntryHooks sHooks;
static NameEntry      sEntry;

void nameentry_init(const NameEntryHooks* hooks)
{
    memset(&sHooks, 0, sizeof sHooks);
    if (hooks) sHooks = *hooks;
    memset(&sEntry, 0, sizeof sEntry);
}

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

int nameentry_char_ok(int c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
        || (c >= '0' && c <= '9') || c == '!' || c == '.' || c == '#'
        || c == ' ';
}

static BAnim* clock(BGameFlow* gf)
{
    banim_set_clock(gf->anim, (int32_t)gf->realTimer, gf->realElapsed);
    return gf->anim;
}

static cPlayerSettings* settings(int player)
{
    return &Fred.FrontendPlayers[player].mPlayerSettings;
}

// bStrNCpy (0x002535a0): up to n bytes, stopping after the terminator.
static void b_strncpy(char* dst, const char* src, int n)
{
    int i;

    for (i = 0; i < n; i++) {
        dst[i] = src[i];
        if (src[i] == '\0') break;
    }
}

static const char* translate(int id)
{
    const char* s = gFredTranslateFn ? gFredTranslateFn(id) : NULL;
    return s ? s : "";
}

// tNameEntryData::Init (0x0024d2f0).
static void dataInit(NameEntryData* d)
{
    b_strncpy(d->p1Name, settings(0)->PlayerName, 12);
    b_strncpy(d->p2Name, settings(1)->PlayerName, 12);
    d->gender1 = settings(0)->PreferredGender;
    d->gender2 = settings(1)->PreferredGender;
}

// tNameEntryData::Different (0x0024d370).
static int dataDifferent(const NameEntryData* d)
{
    return strcmp(d->p1Name, settings(0)->PlayerName) != 0
        || strcmp(d->p2Name, settings(1)->PlayerName) != 0
        || d->gender1 != settings(0)->PreferredGender
        || d->gender2 != settings(1)->PreferredGender;
}

// RedrawGenders (0x0024d7b0). A gender that is neither gives Player 1's
// text no string, and Player 2's the string Player 1's got (s0 kept).
static void redrawGenders(NameEntry* e)
{
    int      g1 = settings(0)->PreferredGender;
    int      g2 = settings(1)->PreferredGender;
    uint32_t id = g1 == 0 ? LANG_MALE : g1 == 1 ? LANG_FEMALE : 0;

    flailer_set_language_id(e->screen, OBJ_P1_GENDER, id);
    if (g2 == 0) id = LANG_MALE;
    else if (g2 == 1) id = LANG_FEMALE;
    flailer_set_language_id(e->screen, OBJ_P2_GENDER, id);
}

// tKeyboard::SetVisible (0x0024c5d0) with 0, for `player`: the grid, the
// player's character boxes and the cursor hidden, the name shown.
static void hideKeyboard(NameEntry* e, int player)
{
    flailer_set_group_visibility(e->screen, GROUP_KEYBOARD, 0);
    flailer_set_group_visibility(e->screen,
                                 player ? GROUP_P2_CHARS : GROUP_P1_CHARS, 0);
    flailer_set_visibility(e->screen, OBJ_CURSOR, 0);
    flailer_set_visibility(e->screen, player ? OBJ_P2_NAME : OBJ_P1_NAME, 1);
}

// The port's: Player 2's rows hidden, as the 3DS has no second player
// (the user's word, 2026-10-13). GrayMenuItem's mode 2 disables and hides
// each row's label, so the menu passes over them; their values, bars and
// the "Player 2" label go too. Retail shows all four rows.
static void hidePlayer2(BGameFlow* gf, uint32_t screen)
{
    struct FlailerObjectChunk* o = NULL;

    if (gf->hooks.grayMenuItem) {
        gf->hooks.grayMenuItem(gf->hooks.user, screen, ITEM_P2_NAME,
                               BSCR_GRAY_HIDE);
        gf->hooks.grayMenuItem(gf->hooks.user, screen, ITEM_P2_GENDER,
                               BSCR_GRAY_HIDE);
    }
    flailer_set_visibility(screen, OBJ_P2_NAME, FLAILER_OBJECT_INVISIBLE);
    flailer_set_visibility(screen, OBJ_P2_GENDER, FLAILER_OBJECT_INVISIBLE);
    flailer_set_visibility(screen, OBJ_MI_3_MASK, FLAILER_OBJECT_INVISIBLE);
    flailer_set_visibility(screen, OBJ_MI_4_MASK, FLAILER_OBJECT_INVISIBLE);
    while ((o = flailer_find_object_by_group(screen, GROUP_SCREEN,
                                             FLAILER_TYPE_TEXT, o)) != NULL)
        if (((struct FlailerTextChunk*)o)->LanguageID == LANG_PLAYER_2)
            flailerobject_set_visibility(o, FLAILER_OBJECT_INVISIBLE);
}

// The constructor, 0x0024d408.
static void construct(BGameFlow* gf, NameEntry* e, uint32_t screen)
{
    BAnim*  a = clock(gf);
    BSetup* s = bsetup_instance();

    memset(e, 0, sizeof *e);
    e->live   = 1;
    e->screen = screen;
    banim_highlight_init(a, &e->highlight, screen, OBJ_BLOOM,
                         (int32_t)BANIM_BLOOM_COLOR);
    banim_highlight_init(a, &e->change, screen, OBJ_BLOOM_VAL, -1);
    if (s)
        barrows_init(s, &e->arrows, screen, BSETUP_OBJ_LEFT_ARROW,
                     BSETUP_OBJ_RIGHT_ARROW);
    banim_blurb_init(a, &e->blurb, screen, BSCR_OBJ_SCROLLING_TEXT,
                     BSCR_OBJ_SCROLLING_TEXT, BSCR_OBJ_WHITEOUT_BAR);
    hideKeyboard(e, 0);
    hideKeyboard(e, 1);
    flailer_printf(screen, OBJ_P1_NAME, "%s", settings(0)->PlayerName);
    flailer_printf(screen, OBJ_P2_NAME, "%s", settings(1)->PlayerName);
    redrawGenders(e);
    dataInit(&e->data);
    hidePlayer2(gf, screen);
    say("in: \"%s\" %d, \"%s\" %d", settings(0)->PlayerName,
        settings(0)->PreferredGender, settings(1)->PlayerName,
        settings(1)->PreferredGender);
}

// The destructor, 0x0024d548: the blurb's, and the two blooms', which
// leave nothing behind.
static void destroy(BGameFlow* gf, NameEntry* e)
{
    if (!e->live) return;
    banim_blurb_release(clock(gf), &e->blurb);
    e->live = 0;
}

// MaybeActivateKeyboard (0x0024d5c0): a name's row opens the keyboard
// for its own player's pad only. Then tKeyboard::Activate (0x0024c708)
// copies the name into its eight-byte buffer, seven at most, and on the
// done key, or BACK, SetName (0x0024d288) takes the buffer with
// NameFinalSelect's noise. The 3DS keyboard's Cancel keeps the old name
// instead, silently: the applet has made its own noise.
static int maybeKeyboard(BGameFlow* gf, NameEntry* e,
                         BScreenCallbackData* data)
{
    int  player = data->itemHash == ITEM_P2_NAME;
    char name[NAMEENTRY_MAX_CHARS + 1];

    (void)gf;
    if (data->port != player) return 0;
    memset(name, 0, sizeof name);
    b_strncpy(name, settings(player)->PlayerName, NAMEENTRY_MAX_CHARS);
    say("keyboard: player %d, \"%s\"", player + 1, name);
    if (!sHooks.keyboard
        || !sHooks.keyboard(sHooks.user,
                            translate(LANG_BLURB + 2 * player), name,
                            (int)sizeof name)) {
        say("keyboard: cancelled, \"%s\" kept",
            settings(player)->PlayerName);
        data->noise = 0;
        return 1;
    }
    name[NAMEENTRY_MAX_CHARS] = '\0';
    b_strncpy(settings(player)->PlayerName, name, SETNAME_COPY);
    flailer_printf(e->screen, player ? OBJ_P2_NAME : OBJ_P1_NAME, "%s",
                   settings(player)->PlayerName);
    data->noise = SOUND_NAME_DONE;
    say("keyboard: player %d is \"%s\"", player + 1,
        settings(player)->PlayerName);
    return 1;
}

// ChangeGender (0x0024d660): a gender's row, for its own player's pad,
// turns 0 into 1 and anything else into 0.
static void changeGender(BGameFlow* gf, NameEntry* e, BScreenMessage msg,
                         BScreenCallbackData* data)
{
    int player = data->itemHash == ITEM_P2_GENDER;
    int mine   = data->port == player;

    if (mine) {
        cPlayerSettings* p = settings(player);
        p->PreferredGender = p->PreferredGender == 0;
        say("gender: player %d is %d", player + 1, p->PreferredGender);
    }
    redrawGenders(e);
    if (!mine) {
        data->noise = 0;
        return;
    }
    if (msg == BMSG_MENUITEM_PAD_LEFT) data->noise = BSND_MENU_LEFT;
    else if (msg == BMSG_MENUITEM_PAD_RIGHT) data->noise = BSND_MENU_RIGHT;
    banim_highlight_set_item(clock(gf), &e->change,
                             player ? OBJ_P2_GENDER : OBJ_P1_GENDER);
}

// tNameEntryData's names and genders back in the settings: No's.
static void dataPutBack(const NameEntryData* d)
{
    b_strncpy(settings(0)->PlayerName, d->p1Name, 12);
    b_strncpy(settings(1)->PlayerName, d->p2Name, 12);
    settings(0)->PreferredGender = d->gender1;
    settings(1)->PreferredGender = d->gender2;
}

// ---------------------------------------------------------- the prompt
//
// The port's (the user's word, 2026-10-13): BACK with anything changed
// asks "Save your changes to the SD Card?" in the screen's place, as the
// debug menu does. Yes saves on the Autosave screen, in NameEntry's place,
// so its end moves back to Options; No puts the names and genders back as
// the screen found them and moves back; B on the popup stays. Retail's
// BACK saves only with autosave on, and with it off leaves the changes
// unsaved.

static void showScreen(BGameFlow* gf, uint32_t screen, int visible)
{
    if (screen && gf->hooks.setScreenVisible)
        gf->hooks.setScreenVisible(gf->hooks.user, screen, visible);
}

static void askToSave(BGameFlow* gf, NameEntry* e)
{
    BPopupConfig cfg;

    memset(&cfg, 0, sizeof cfg);
    cfg.numButtons     = 2;
    cfg.flags          = BPOPUP_HORIZONTAL | BPOPUP_CANCELABLE
                       | BPOPUP_BUTTONS_BELOW;
    cfg.parent         = gf->screen;
    cfg.screen         = BPOPUP_SCREEN_MEMCARD;
    cfg.message        = portlang_get(gf->currLanguage,
                                      PORTLANG_SAVE_CHANGES, NULL);
    cfg.button[0]      = LANG_YES;
    cfg.button[1]      = LANG_NO;
    cfg.buttonParam[0] = ANSWER_SAVE;
    cfg.buttonParam[1] = ANSWER_DISCARD;
    cfg.cancelParam    = ANSWER_STAY;
    cfg.dismissParam   = ANSWER_STAY;
    cfg.startButton    = 0;
    cfg.joyPort        = -1;
    cfg.title          = LANG_SAVE;
    say("back: changed, asking to save");
    if (bpopup_summon(gf, &cfg) < 0) {
        say("no popup free");
        return;
    }
    e->asking = 1;
    showScreen(gf, e->screen, 0);
}

static void answered(BGameFlow* gf, NameEntry* e, int answer)
{
    if (!e->asking) return;
    e->asking = 0;
    showScreen(gf, e->screen, 1);
    if (answer == ANSWER_STAY) {
        say("save: stay");
        return;
    }
    if (answer == ANSWER_SAVE) {
        say("save: yes");
        bgf_change_to_screen(gf, AUTOSAVE_SCREEN, 0);
        return;
    }
    dataPutBack(&e->data);
    say("save: no, back to \"%s\" %d", settings(0)->PlayerName,
        settings(0)->PreferredGender);
    bgf_move_back_screen(gf, 1);
}

// HandleEvent's HIGHLIGHT: the item's bloom, then by row the value's bloom,
// the arrows and the blurb.
static void highlight(BGameFlow* gf, NameEntry* e, uint32_t item)
{
    BAnim*   a      = clock(gf);
    BSetup*  s      = bsetup_instance();
    uint32_t follow = 0;
    int      row;

    banim_highlight_set_item(a, &e->highlight, item);
    if (item == ITEM_P1_NAME) row = 0;
    else if (item == ITEM_P1_GENDER) row = 1, follow = OBJ_P1_GENDER;
    else if (item == ITEM_P2_NAME) row = 2;
    else if (item == ITEM_P2_GENDER) row = 3, follow = OBJ_P2_GENDER;
    else return;
    banim_highlight_set_item(a, &e->change, follow);
    if (s) barrows_set(s, &e->arrows, follow);
    banim_blurb_new_text_id(a, &e->blurb, LANG_BLURB + row);
}

void nameentry_callback(BGameFlow* gf, BScreenMessage msg,
                        BScreenCallbackData* data)
{
    NameEntry* e = &sEntry;
    BSetup*    s;
    uint32_t   item;

    if (msg == BMSG_SCREEN_ACTIVATE) {
        construct(gf, e, data->itemHash);
        return;
    }
    if (msg == BMSG_SCREEN_UNACTIVATE) {
        destroy(gf, e);
        return;
    }
    if (!e->live) return;
    if (msg == BMSG_SCREEN_TICK) {
        BAnim* a = clock(gf);
        banim_highlight_animate(a, &e->highlight);
        banim_highlight_animate(a, &e->change);
        banim_blurb_animate(a, &e->blurb);
    }
    s = bsetup_instance();
    if (s) barrows_event(s, &e->arrows, msg);
    item = data ? data->itemHash : 0;
    switch (msg) {
    case BMSG_MENUITEM_SELECT:
        if (item == ITEM_P1_NAME || item == ITEM_P2_NAME) {
            if (maybeKeyboard(gf, e, data)) return;
            data->noise = 0;
        } else if (item == ITEM_P1_GENDER || item == ITEM_P2_GENDER) {
            data->noise = 0;
        }
        return;
    case BMSG_MENUITEM_HIGHLIGHT:
        highlight(gf, e, item);
        return;
    case BMSG_MENUITEM_PAD_LEFT:
    case BMSG_MENUITEM_PAD_RIGHT:
        if (item == ITEM_P1_GENDER || item == ITEM_P2_GENDER)
            changeGender(gf, e, msg, data);
        return;
    case BMSG_SCREEN_BACK_BUTTON:
        if (!data) return;
        if (!dataDifferent(&e->data)) {
            say("back: unchanged");
            return;
        }
        // The pop waits for the answer.
        data->param = 0;
        askToSave(gf, e);
        return;
    case BMSG_POPUP_DISMISS:
        answered(gf, e, data ? data->param : ANSWER_STAY);
        return;
    default:
        return;
    }
}
