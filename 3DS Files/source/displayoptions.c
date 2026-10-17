// tDisplayOptionsScreen and tCustomizeHUDScreen (displayoptions.h),
// retail's in its order: tDisplayOptionsScreen's constructor (0x001f33b8),
// ToggleScoring and its twin (0x001f35e8, 0x001f3608), the Redraws
// (0x001f3628 .. 0x001f3990), CycleLeaderboard (0x001f3678), CycleTrackMap
// (0x001f3730), ToggleRearview (0x001f3878), ToggleUnits (0x001f38f8),
// DoHighlight (0x001f3990), HandleEvent (0x001f3a28) and Callback
// (0x001f3ec0); then tCustomizeHUDScreen's constructor (0x001f3f20),
// destructor (0x001f4178), toggles and Redraws (0x001f42a0 .. 0x001f46d4),
// HandleEvent (0x001f46d8) and CallbackP1 (0x001f4960). Where retail's B
// saves with autosave on, Display Options asks (the save prompt, below).

#include "displayoptions.h"

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

// tScrollingMenuList's arrows and clip, and the value arrows.
#define OBJ_SCROLL_UP   0xedf2e4eeu
#define OBJ_SCROLL_DOWN 0x20d73d01u
#define OBJ_SCROLL_CLIP 0xc67cfb4au
#define OBJ_LEFT_ARROW  0xd1cda594u
#define OBJ_RIGHT_ARROW 0x9345e4a7u

// "On" and "Off".
#define LANG_ON  140114
#define LANG_OFF 140115

// The save prompt: memcard.c's popup, titled "Save" (150000), with its Yes
// and No (150103, 150104), as Audio Options'.
#define LANG_SAVE 0x249f0
#define LANG_YES  0x24a57
#define LANG_NO   0x24a58

#define AUTOSAVE_SCREEN "Autosave"
#define CUSTOMHUD_NAME  "Customize P1 HUD"

enum { ANSWER_STAY, ANSWER_DISCARD, ANSWER_SAVE };

// The menus' noises (BSND_*): what HandleEvent writes into data->noise.
#define NOISE_NONE  0
#define NOISE_LEFT  1
#define NOISE_RIGHT 2

static DisplayOptionsHooks sHooks;

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

static void showScreen(BGameFlow* gf, uint32_t screen, int visible)
{
    if (screen && gf->hooks.setScreenVisible)
        gf->hooks.setScreenVisible(gf->hooks.user, screen, visible);
}

// MENUITEM_n's n, or 0.
static int rowOf(uint32_t item, int rows)
{
    uint32_t n = item - BSCR_ITEM_MENUITEM(1);
    return n < (uint32_t)rows ? (int)n + 1 : 0;
}

// Left is the one way, anything else the other: the cycles' direction and
// the noise, as every retail toggle here works it out.
static int dirOf(BScreenMessage msg)
{
    return msg == BMSG_MENUITEM_PAD_LEFT ? -1 : 1;
}

static int noiseOf(BScreenMessage msg)
{
    return msg == BMSG_MENUITEM_PAD_LEFT ? NOISE_LEFT : NOISE_RIGHT;
}

// ---------------------------------------- tDisplayOptionsChangeManager
//
// 112 bytes at 0x0031ad00: Start copies, Different (0x001ee878) compares,
// in this order, Fred's DisplayCalibrationData, DisplayOptionsData and the
// two FrontendPlayers' cPlayerSettings.

typedef struct {
    int32_t                calibration[2];   // +0
    tGlobalDisplaySettings display;          // +8
    cPlayerSettings        players[2];       // +16, +64
} DisplaySnapshot;

static DisplaySnapshot sEntry;
static int             sEntryHeld;

static void snapshotFred(DisplaySnapshot* s)
{
    memcpy(s->calibration, Fred.DisplayCalibrationData,
           sizeof s->calibration);
    s->display = Fred.DisplayOptionsData;
    for (int i = 0; i < 2; i++)
        s->players[i] = Fred.FrontendPlayers[i].mPlayerSettings;
}

static int differentFromFred(const DisplaySnapshot* s)
{
    DisplaySnapshot now;

    memset(&now, 0, sizeof now);
    snapshotFred(&now);
    return memcmp(now.calibration, s->calibration, sizeof now.calibration)
        || memcmp(&now.display, &s->display, sizeof now.display)
        || memcmp(now.players, s->players, sizeof now.players);
}

static void restoreFred(const DisplaySnapshot* s)
{
    memcpy(Fred.DisplayCalibrationData, s->calibration,
           sizeof s->calibration);
    Fred.DisplayOptionsData = s->display;
    for (int i = 0; i < 2; i++)
        Fred.FrontendPlayers[i].mPlayerSettings = s->players[i];
}

void displayopts_init(const DisplayOptionsHooks* hooks)
{
    memset(&sHooks, 0, sizeof sHooks);
    if (hooks) sHooks = *hooks;
    sEntryHeld = 0;
}

void displayopts_start(void)
{
    memset(&sEntry, 0, sizeof sEntry);
    snapshotFred(&sEntry);
    sEntryHeld = 1;
    say("display options snapshot");
}

// ------------------------------------------------- tDisplayOptionsScreen

#define DISPLAY_ROWS 9

// The value text beside rows 1..6, which the arrows and the second bloom
// follow: the track map, the mirror, the units, the leaderboard, the jump
// cams and the Zone cams.
#define OBJ_TRACK_MAP   0x55cb09f2u
#define OBJ_REARVIEW    0x2e931f1bu
#define OBJ_UNITS       0x03d90172u
#define OBJ_LEADERBOARD 0x5610f2f4u
#define OBJ_JUMP_CAMS   0x422313cbu
#define OBJ_ZONE_CAMS   0x8fe4086bu

static const uint32_t kDisplayValues[6] = {
    OBJ_TRACK_MAP, OBJ_REARVIEW, OBJ_UNITS, OBJ_LEADERBOARD,
    OBJ_JUMP_CAMS, OBJ_ZONE_CAMS,
};

// "Set the map's display style." .. "Calibrate the display offset.", by
// row; 150704, the score's, is Customize HUD's.
static const int kDisplayBlurbs[DISPLAY_ROWS] = {
    150700, 150701, 150702, 150703, 150705, 150706, 150707, 150708, 150709,
};

// 0x002ba178: what scrolls, the nine rows and six values.
static const uint32_t kScrollObjects[15] = {
    0x52e039f3u, 0x52e039f4u, 0x52e039f5u, 0x52e039f6u, 0x52e039f7u,
    0x52e039f8u, 0x52e039f9u, 0x52e039fau, 0x52e039fbu,
    OBJ_TRACK_MAP, OBJ_REARVIEW, OBJ_UNITS, OBJ_LEADERBOARD, OBJ_ZONE_CAMS,
    OBJ_JUMP_CAMS,
};

// The track map's modes, eTrackMapMode, as 0x001f37d0 names them: 3D
// Rotation, 3D Standard, 2D Rotation, 2D Standard, Fixed, Full size, Off,
// then the two-player and Be A Cop maps' own (7 has none).
static const int kTrackMapIds[10] = {
    140101, 140102, 140103, 140200, 140104, 140105, LANG_OFF, 0,
    140201, 140202,
};

// The modes a race with one player allows (0x003140a0, six of them; the
// HUD's OnePlayerModes), and the first of the two-player and Be A Cop
// lists (0x00331090, 0x00331098), which a map that is on sets.
static const int8_t kOnePlayerModes[6] = { 0, 1, 2, 3, 4, 6 };
#define TRACKMAP_OFF       6
#define TWO_PLAYER_FIRST   7
#define BE_THE_COP_FIRST   8

// The leaderboard's text by mode (0x002ba1b8): Off, "Top 3", On.
static const int kLeaderboardIds[3] = { LANG_OFF, 102001, LANG_ON };

// 616 bytes in retail (bMalloc'd on SCREEN_ACTIVATE, its pointer at
// gp-16888, which every OptionsScreenBase page shares).
typedef struct {
    BScreenInstance        inst;     // OptionsScreenBase, +0 .. +100
    tGlobalDisplaySettings data;     // +100
    BScrollList            list;     // +108
    BArrows                arrows;   // +164
    int                    asking;   // the save prompt is up
} DisplayScreen;

static DisplayScreen sDisplay;

static void setOnOff(uint32_t screen, uint32_t object, int on)
{
    flailer_set_language_id(screen, object, on ? LANG_ON : LANG_OFF);
}

// RedrawTrackMap (0x001f37d0): the one-player map's mode, the frontend's.
static void redrawTrackMap(DisplayScreen* d)
{
    int mode = d->data.OnePlayerTrackMapMode;
    flailer_set_language_id(d->inst.screen, OBJ_TRACK_MAP,
                            mode >= 0 && mode < 10 ? kTrackMapIds[mode] : 0);
}

static void redrawRearView(DisplayScreen* d)        // 0x001f38d0
{
    setOnOff(d->inst.screen, OBJ_REARVIEW, d->data.RearViewMirror != 0);
}

// RedrawUnits (0x001f3950): mph, km/h, or nothing.
static void redrawUnits(DisplayScreen* d)
{
    int u = d->data.Units;
    flailer_set_language_id(d->inst.screen, OBJ_UNITS,
                            u == 0 ? 140106 : u == 1 ? 140107 : 0);
}

static void redrawLeaderboard(DisplayScreen* d)     // 0x001f36d8
{
    int m = d->data.LeaderboardMode;
    flailer_set_language_id(d->inst.screen, OBJ_LEADERBOARD,
                            m >= 0 && m < 3 ? kLeaderboardIds[m] : 0);
}

// RedrawScoring (0x001f3628), retail's name for the jump cams' byte, and
// its twin for the Zone cams' (0x001f3650).
static void redrawJumpCams(DisplayScreen* d)
{
    setOnOff(d->inst.screen, OBJ_JUMP_CAMS, d->data.JumpCams != 0);
}

static void redrawZoneCams(DisplayScreen* d)
{
    setOnOff(d->inst.screen, OBJ_ZONE_CAMS, d->data.ZoneCams != 0);
}

// tGlobalDisplaySettings::CycleTrackMap (0x001ee148) as the frontend runs
// it: with the flow IN_FRONTEND it is always the one-player map, stepped
// through its list by `dir` and wrapping; a mode off the list starts at
// the list's first. Then the screen's own rule (0x001f3730): Off turns the
// two-player and Be A Cop maps off too, anything else puts them back to
// their first.
static void cycleTrackMap(DisplayScreen* d, int dir)
{
    int8_t* m = &d->data.OnePlayerTrackMapMode;
    int     n = 6, i;

    for (i = 0; i < n && kOnePlayerModes[i] != *m; i++) {}
    if (i == n) {
        *m = kOnePlayerModes[0];
    } else {
        i += dir;
        if (i >= n) i = 0;
        else if (i < 0) i = n - 1;
        *m = kOnePlayerModes[i];
    }
    if (*m == TRACKMAP_OFF) {
        d->data.TwoPlayerTrackMapMode = TRACKMAP_OFF;
        d->data.BeTheCopTrackMapMode  = TRACKMAP_OFF;
    } else {
        d->data.TwoPlayerTrackMapMode = TWO_PLAYER_FIRST;
        d->data.BeTheCopTrackMapMode  = BE_THE_COP_FIRST;
    }
    redrawTrackMap(d);
    say("display: track map %d", (int)*m);
}

// CycleLeaderboardMode (0x001ee120): anything but 2 becomes 2 (On), and 2
// becomes 0 (Off), whichever way the pad went; answers whether it changed.
// Top 3 (1) only ever comes from a save.
static int cycleLeaderboard(DisplayScreen* d)
{
    int8_t old = d->data.LeaderboardMode;
    d->data.LeaderboardMode = old != 2 ? 2 : 0;
    redrawLeaderboard(d);
    say("display: leaderboard %d", (int)d->data.LeaderboardMode);
    return d->data.LeaderboardMode != old;
}

// The constructor (0x001f33b8). Retail scrolls nine rows in a window of
// seven; with Customize P2 HUD and Calibrate display offset hidden, the
// seven left all fit and the list never scrolls.
static void displayConstruct(BGameFlow* gf, DisplayScreen* d, uint32_t screen)
{
    BSetup* s = bsetup_instance();

    memset(d, 0, sizeof *d);
    bscr_optbase_construct(&d->inst, screen);
    if (s) {
        bscroll_init(s, &d->list, screen, BSCR_ITEM_MENUITEM(1),
                     BSCR_ITEM_MENUITEM(7), OBJ_SCROLL_UP, OBJ_SCROLL_DOWN,
                     OBJ_SCROLL_CLIP);
        barrows_init(s, &d->arrows, screen, OBJ_LEFT_ARROW, OBJ_RIGHT_ARROW);
    }
    d->data = Fred.DisplayOptionsData;
    redrawTrackMap(d);
    redrawRearView(d);
    redrawUnits(d);
    redrawLeaderboard(d);
    redrawJumpCams(d);
    redrawZoneCams(d);
    if (s) {
        bscroll_add_objects(s, &d->list, kScrollObjects, 15);
        d->list.numMenuItemsToScroll = 7;
    }
    flailer_set_clip_to_poly(screen, OBJ_LEFT_ARROW, OBJ_SCROLL_CLIP);
    flailer_set_clip_to_poly(screen, OBJ_RIGHT_ARROW, OBJ_SCROLL_CLIP);
    // The port's: GrayMenuItem's mode 2 disables and hides both rows, so
    // the menu passes over them.
    if (gf->hooks.grayMenuItem) {
        gf->hooks.grayMenuItem(gf->hooks.user, screen, BSCR_ITEM_MENUITEM(8),
                               BSCR_GRAY_HIDE);
        gf->hooks.grayMenuItem(gf->hooks.user, screen, BSCR_ITEM_MENUITEM(9),
                               BSCR_GRAY_HIDE);
    }
    // Options' Start took the snapshot; this is for a way in without it.
    if (!sEntryHeld) displayopts_start();
    say("display options: in, map %d mirror %d units %d board %d jump %d "
        "zone %d", d->data.OnePlayerTrackMapMode, d->data.RearViewMirror,
        d->data.Units, d->data.LeaderboardMode, d->data.JumpCams,
        d->data.ZoneCams);
}

static void displayDestruct(DisplayScreen* d)
{
    BSetup* s = bsetup_instance();

    if (!d->inst.live) return;
    if (s) bscroll_release(s, &d->list);
    bscr_optbase_destruct(&d->inst);
    memset(d, 0, sizeof *d);
}

// ---------------------------------------------------------- the prompt
//
// The port's (the user's word, 2026-10-13): B with Fred not as it was when
// Options opened the page asks "Save your changes to the SD Card?" in the
// page's place, as Audio Options does. Yes saves on the Autosave screen, in
// this page's place, so its end moves back to Options; No puts all four
// back as they were, then moves back; B on the popup stays.

static void askToSave(BGameFlow* gf, DisplayScreen* d)
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
    say("display back: changed, asking to save");
    if (bpopup_summon(gf, &cfg) < 0) {
        say("no popup free");
        return;
    }
    d->asking = 1;
    showScreen(gf, d->inst.screen, 0);
}

static void answered(BGameFlow* gf, DisplayScreen* d, int answer)
{
    if (!d->asking) return;
    d->asking = 0;
    showScreen(gf, d->inst.screen, 1);
    if (answer == ANSWER_STAY) {
        say("display save: stay");
        return;
    }
    sEntryHeld = 0;
    if (answer == ANSWER_SAVE) {
        say("display save: yes");
        bgf_change_to_screen(gf, AUTOSAVE_SCREEN, 0);
        return;
    }
    restoreFred(&sEntry);
    say("display save: no, settings put back");
    bgf_move_back_screen(gf, 1);
}

// B: retail's, the page's copy into Fred, then the port's question in
// place of the autosave when Different says so.
static void displayBack(BGameFlow* gf, DisplayScreen* d,
                        BScreenCallbackData* data)
{
    Fred.DisplayOptionsData = d->data;
    if (!sEntryHeld || !differentFromFred(&sEntry)) {
        say("display back: unchanged");
        sEntryHeld = 0;
        return;
    }
    // The pop waits for the answer.
    data->param = 0;
    askToSave(gf, d);
}

// HandleEvent (0x001f3a28): the scrolling list and the arrows see every
// message first.
static void displayEvent(BGameFlow* gf, DisplayScreen* d, BScreenMessage msg,
                         BScreenCallbackData* data)
{
    BSetup*  s    = bsetup_instance();
    uint32_t item = data ? data->itemHash : 0;
    int      row  = rowOf(item, DISPLAY_ROWS);

    if (s) {
        bscroll_event(s, &d->list, msg, data);
        barrows_event(s, &d->arrows, msg);
    }
    switch (msg) {
    case BMSG_MENUITEM_SELECT:
        if (row == 7) {
            Fred.DisplayOptionsData = d->data;
            say("display: to %s", CUSTOMHUD_NAME);
            bscr_optbase_exit(&d->inst, CUSTOMHUD_NAME);
            if (s) barrows_set(s, &d->arrows, 0);
        } else if (data) {
            data->noise = NOISE_NONE;
        }
        return;
    case BMSG_MENUITEM_HIGHLIGHT: {
        // DoHighlight(0) on rows 7..9 is the arrows hidden, as Set(0) is.
        uint32_t value = row >= 1 && row <= 6 ? kDisplayValues[row - 1] : 0;
        banim_blurb_new_text_id(bscr_anim(), &d->inst.blurbAnim,
                                row ? kDisplayBlurbs[row - 1] : 0);
        bscr_optbase_highlight(&d->inst, data, bscroll_current_mask(&d->list));
        // The second bloom on the value, after the base's highlight, which
        // the port's puts on the row.
        banim_highlight_set_item(bscr_anim(), &d->inst.bloom2, value);
        if (s) barrows_set(s, &d->arrows, value);
        return;
    }
    case BMSG_MENUITEM_PAD_LEFT:
    case BMSG_MENUITEM_PAD_RIGHT:
        switch (row) {
        case 1:
            cycleTrackMap(d, dirOf(msg));
            if (data) data->noise = noiseOf(msg);
            break;
        case 2:
            d->data.RearViewMirror = d->data.RearViewMirror == 0;
            redrawRearView(d);
            say("display: mirror %d", d->data.RearViewMirror);
            if (data) data->noise = noiseOf(msg);
            break;
        case 3:
            d->data.Units = d->data.Units == 0;
            redrawUnits(d);
            say("display: units %d", d->data.Units);
            if (data) data->noise = noiseOf(msg);
            break;
        case 4: {
            int changed = cycleLeaderboard(d);
            if (data) data->noise = changed ? NOISE_LEFT : NOISE_NONE;
            break;
        }
        case 5:
            d->data.JumpCams = d->data.JumpCams == 0;
            redrawJumpCams(d);
            say("display: jump cams %d", d->data.JumpCams);
            if (data) data->noise = NOISE_LEFT;
            break;
        case 6:
            d->data.ZoneCams = d->data.ZoneCams == 0;
            redrawZoneCams(d);
            say("display: zone cams %d", d->data.ZoneCams);
            if (data) data->noise = NOISE_LEFT;
            break;
        default:
            break;
        }
        banim_highlight_force_start(bscr_anim(), &d->inst.bloom2);
        return;
    case BMSG_MENUITEM_PAD_UP:
        // The list stops at its ends: retail's last is MENUITEM_9, the
        // port's MENUITEM_7.
        if (row == 1 && data) data->param = 1;
        return;
    case BMSG_MENUITEM_PAD_DOWN:
        if (row == 7 && data) data->param = 1;
        return;
    case BMSG_SCREEN_BACK_BUTTON:
        if (data) displayBack(gf, d, data);
        return;
    case BMSG_POPUP_DISMISS:
        answered(gf, d, data ? data->param : ANSWER_STAY);
        return;
    default:
        // TICK: the blurb is the base's, which its tick animates.
        return;
    }
}

void displayopts_callback(BGameFlow* gf, BScreenMessage msg,
                          BScreenCallbackData* data)
{
    DisplayScreen* d = &sDisplay;

    if (msg == BMSG_SCREEN_ACTIVATE) {
        displayConstruct(gf, d, data ? data->itemHash : DISPLAYOPTS_SCREEN);
        return;
    }
    if (!d->inst.live) return;
    if (msg == BMSG_SCREEN_UNACTIVATE) {
        displayDestruct(d);
        return;
    }
    if (bscr_optbase_first_crack(&d->inst, msg, data)) return;
    displayEvent(gf, d, msg, data);
}

// --------------------------------------------------- tCustomizeHUDScreen

#define HUD_ROWS 7

// The value text by row: the lookback, the acceleration camera, the
// gauges, the position, the lap info, the split time and the score.
#define OBJ_LOOKBACK      0x2e018745u
#define OBJ_CAMERA_SPRING 0xffc3dcd2u
#define OBJ_GAUGES        0x4ceb3ed2u
#define OBJ_POSITION      0x1054482bu
#define OBJ_LAP_INFO      0xc7e2117eu
#define OBJ_SPLIT_TIME    0x6caf6d10u
#define OBJ_SCORE         0x6bd89c11u

static const uint32_t kHudValues[HUD_ROWS] = {
    OBJ_LOOKBACK, OBJ_CAMERA_SPRING, OBJ_GAUGES, OBJ_POSITION, OBJ_LAP_INFO,
    OBJ_SPLIT_TIME, OBJ_SCORE,
};

// What the arrows follow (DoHighlight's argument): the first two rows'
// labels, the others' values. One line, so the same height either way.
static const uint32_t kHudArrows[HUD_ROWS] = {
    0x52e039f3u, 0x52e039f4u, OBJ_GAUGES, OBJ_POSITION, OBJ_LAP_INFO,
    OBJ_SPLIT_TIME, OBJ_SCORE,
};

// "Set the lookback mode." .. "Set the split time mode.", then Display
// Options' "Show or hide the current score.".
static const int kHudBlurbs[HUD_ROWS] = {
    150900, 150901, 150902, 150903, 150904, 150905, 150704,
};

// PreferredHudFeatures' bits the rows toggle (cPlayerSettings 0x001ee1f8,
// 0x001ee2b0, 0x001ee230), and the split's (0x001ee258).
#define HUD_GAUGES   0x040u
#define HUD_POSITION 0x010u
#define HUD_LAP_INFO 0x100u
#define HUD_SPLIT    0x004u

// The split time's modes (0x002ba300): Race Leader, Lap Record, Best Lap,
// Last Lap, Off.
static const int kSplitIds[5] = { 140108, 140109, 140110, 140111, LANG_OFF };
#define SPLIT_OFF 4

// 580 bytes in retail.
typedef struct {
    BScreenInstance inst;       // OptionsScreenBase, +0 .. +100
    cPlayerSettings data;       // +100
    int32_t         player;     // +148
    BArrows         arrows;     // +152, +156: the arrows' bitmaps
} HudScreen;

static HudScreen sHud;

// RedrawLookback (0x001f43f0): Bird's Eye, Lookback, or nothing.
static void redrawLookback(HudScreen* h)
{
    int v = h->data.Lookback;
    flailer_set_language_id(h->inst.screen, OBJ_LOOKBACK,
                            v == 0 ? 140118 : v == 1 ? 140113 : 0);
}

// RedrawCameraSpring (0x001f4360): 1 is off.
static void redrawCameraSpring(HudScreen* h)
{
    setOnOff(h->inst.screen, OBJ_CAMERA_SPRING, h->data.CameraSpring != 1);
}

static void redrawFeature(HudScreen* h, uint32_t object, uint32_t bit)
{
    setOnOff(h->inst.screen, object,
             (h->data.PreferredHudFeatures & bit) != 0);
}

static void redrawSplitTime(HudScreen* h)           // 0x001f45d8
{
    int v = h->data.SplitTimeType;
    flailer_set_language_id(h->inst.screen, OBJ_SPLIT_TIME,
                            v >= 0 && v < 5 ? kSplitIds[v] : 0);
}

static void redrawScore(HudScreen* h)               // 0x001f46b0
{
    setOnOff(h->inst.screen, OBJ_SCORE, h->data.New44 != 0);
}

static void redrawHud(HudScreen* h)
{
    redrawFeature(h, OBJ_GAUGES, HUD_GAUGES);
    redrawFeature(h, OBJ_POSITION, HUD_POSITION);
    redrawFeature(h, OBJ_LAP_INFO, HUD_LAP_INFO);
    redrawSplitTime(h);
    redrawLookback(h);
    redrawCameraSpring(h);
    redrawScore(h);
}

// The constructor (0x001f3f20): the player's settings copied in.
static void hudConstruct(HudScreen* h, uint32_t screen, int player)
{
    BSetup* s = bsetup_instance();

    memset(h, 0, sizeof *h);
    bscr_optbase_construct(&h->inst, screen);
    h->player = player;
    h->data   = Fred.FrontendPlayers[player].mPlayerSettings;
    redrawHud(h);
    if (s) barrows_init(s, &h->arrows, screen, OBJ_LEFT_ARROW,
                        OBJ_RIGHT_ARROW);
    say("customize hud: in, player %d, features 0x%03x split %d lookback %d "
        "spring %d score %d", player,
        (unsigned)h->data.PreferredHudFeatures, h->data.SplitTimeType,
        (int)h->data.Lookback, (int)h->data.CameraSpring,
        (int)h->data.New44);
}

// The destructor (0x001f4178): the settings copied back out.
static void hudDestruct(HudScreen* h)
{
    if (!h->inst.live) return;
    Fred.FrontendPlayers[h->player].mPlayerSettings = h->data;
    say("customize hud: out, features 0x%03x split %d lookback %d spring %d "
        "score %d", (unsigned)h->data.PreferredHudFeatures,
        h->data.SplitTimeType, (int)h->data.Lookback,
        (int)h->data.CameraSpring, (int)h->data.New44);
    bscr_optbase_destruct(&h->inst);
    memset(h, 0, sizeof *h);
}

// CycleSplitTime (0x001ee258): 0..4 wrapping, and the split shown unless
// it is Off.
static void cycleSplitTime(HudScreen* h, int dir)
{
    int v = h->data.SplitTimeType + dir;

    if (v < 0) v = SPLIT_OFF;
    if (v > SPLIT_OFF) v = 0;
    h->data.SplitTimeType = (int8_t)v;
    if (v == SPLIT_OFF) h->data.PreferredHudFeatures &= ~HUD_SPLIT;
    else h->data.PreferredHudFeatures |= HUD_SPLIT;
    redrawSplitTime(h);
}

// HandleEvent (0x001f46d8). Up and Down wrap; B is the base's, back to
// Display Options.
static void hudEvent(HudScreen* h, BScreenMessage msg,
                     BScreenCallbackData* data)
{
    BSetup*  s    = bsetup_instance();
    uint32_t item = data ? data->itemHash : 0;
    int      row  = rowOf(item, HUD_ROWS);

    switch (msg) {
    case BMSG_MENUITEM_SELECT:
    case BMSG_SCREEN_START_BUTTON:
        if (data) data->noise = NOISE_NONE;
        return;
    case BMSG_MENUITEM_HIGHLIGHT:
        // DoHighlight (0x001f40e0) is ArrowAligner and the pair shown.
        if (s) barrows_set(s, &h->arrows, row ? kHudArrows[row - 1] : 0);
        banim_blurb_new_text_id(bscr_anim(), &h->inst.blurbAnim,
                                row ? kHudBlurbs[row - 1] : 0);
        banim_highlight_set_item(bscr_anim(), &h->inst.bloom2,
                                 row ? kHudValues[row - 1] : 0);
        return;
    case BMSG_MENUITEM_PAD_LEFT:
    case BMSG_MENUITEM_PAD_RIGHT:
        switch (row) {
        case 1:   // ToggleLookback (0x001ee2d8): 0 and 1 into each other
            if (h->data.Lookback == 0) h->data.Lookback = 1;
            else if (h->data.Lookback == 1) h->data.Lookback = 0;
            redrawLookback(h);
            break;
        case 2:   // ToggleCameraSpring (0x001ee328)
            h->data.CameraSpring = h->data.CameraSpring == 0;
            redrawCameraSpring(h);
            break;
        case 3:
            h->data.PreferredHudFeatures ^= HUD_GAUGES;
            redrawFeature(h, OBJ_GAUGES, HUD_GAUGES);
            break;
        case 4:
            h->data.PreferredHudFeatures ^= HUD_POSITION;
            redrawFeature(h, OBJ_POSITION, HUD_POSITION);
            break;
        case 5:
            h->data.PreferredHudFeatures ^= HUD_LAP_INFO;
            redrawFeature(h, OBJ_LAP_INFO, HUD_LAP_INFO);
            break;
        case 6:
            cycleSplitTime(h, dirOf(msg));
            break;
        case 7:   // 0x001ee020
            h->data.New44 = h->data.New44 == 0;
            redrawScore(h);
            break;
        default:
            break;
        }
        if (row && data) data->noise = noiseOf(msg);
        if (row) say("customize hud: row %d, features 0x%03x split %d "
                     "lookback %d spring %d score %d", row,
                     (unsigned)h->data.PreferredHudFeatures,
                     h->data.SplitTimeType, (int)h->data.Lookback,
                     (int)h->data.CameraSpring, (int)h->data.New44);
        banim_highlight_force_start(bscr_anim(), &h->inst.bloom2);
        return;
    case BMSG_SCREEN_TICK:
        // The blurb is the base's; AnimateCursor is the arrows' pulse.
        if (s) barrows_event(s, &h->arrows, msg);
        return;
    default:
        return;
    }
}

void customhud_callback(BGameFlow* gf, BScreenMessage msg,
                        BScreenCallbackData* data)
{
    HudScreen* h = &sHud;

    (void)gf;
    if (msg == BMSG_SCREEN_ACTIVATE) {
        hudConstruct(h, data ? data->itemHash : CUSTOMHUD_SCREEN, 0);
        return;
    }
    if (!h->inst.live) return;
    if (msg == BMSG_SCREEN_UNACTIVATE) {
        hudDestruct(h);
        return;
    }
    if (bscr_optbase_first_crack(&h->inst, msg, data)) return;
    hudEvent(h, msg, data);
}
