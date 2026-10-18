// pauseoptions -- the pause menu's pages; pauseoptions.h has the map.

#include "pauseoptions.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "banim.h"
#include "bsetup.h"
#include "cammover.h"
#include "drivecam.h"
#include "flailer.h"
#include "flailerwrap.h"
#include "gameflow.h"
#include "joyevent.h"
#include "joystick.h"
#include "pausemenu.h"
#include "pausereplay.h"
#include "player.h"
#include "portlang.h"
#include "race.h"
#include "racecoord.h"
#include "raceevent.h"
#include "raceparams.h"
#include "rcpost.h"
#include "realtime.h"
#include "replaymgr.h"
#include "startrace.h"

// GrayMenuItem's modes.
#define GRAY_DISABLE 0
#define GRAY_ENABLE  1
#define GRAY_HIDE    2

// The menus' noises (BSND_*).
#define NOISE_NONE   0
#define NOISE_LEFT   BSND_MENU_LEFT
#define NOISE_RIGHT  BSND_MENU_RIGHT
#define NOISE_CANCEL BSND_MENU_CANCEL
#define NOISE_START  BSND_MENU_START

#define ITEM(n) (0x52e039f2u + (uint32_t)(n))   // bhash("MENUITEM_n")
// MENUITEM_10 to MENUITEM_12, which hash apart from the first nine.
#define ITEM_10 0xaee77883u
#define ITEM_11 0xaee77884u
#define ITEM_12 0xaee77885u

// Every page's: the bloom on the item, the second bloom on its value, and
// the arrows either side of the value.
#define OBJ_VALUE_BLOOM 0x1042eac3u
#define OBJ_LEFT_ARROW  0xd1cda594u
#define OBJ_RIGHT_ARROW 0x9345e4a7u
// "PLAYER N" on Options and Display.
#define OBJ_PLAYER_TITLE 0x18b2dbc8u
#define LANG_PLAYER_1    210101
#define LANG_PLAYER_2    210102

#define LANG_ON  140114
#define LANG_OFF 140115

static PauseOptionsHooks sHooks;

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

// ------------------------------------------------------------- the seams

static BAnim* anim(void)
{
    return gPauseMenuAnimFn != NULL ? gPauseMenuAnimFn() : NULL;
}

static void gray_menu_item(uint32_t item, int32_t mode, uint32_t screen)
{
    if (gGrayMenuItemFn != NULL)
        gGrayMenuItemFn(item, mode, screen);
}

static void change_to_screen(const char* name, int32_t push)
{
    if (gChangeToScreenFn != NULL)
        gChangeToScreenFn(name, push);
}

static const char* translate(int32_t id)
{
    const char* s = gPauseTranslateFn != NULL ? gPauseTranslateFn(id) : NULL;

    return s != NULL ? s : "";
}

// GrayMenuItem and the value beside it shown or hidden to match, as the
// pages do it row by row.
static void gray_row(uint32_t screen, uint32_t item, uint32_t value, int on)
{
    gray_menu_item(item, on ? GRAY_ENABLE : GRAY_DISABLE, screen);
    flailer_set_visibility(screen, value,
                           on ? FLAILER_OBJECT_VISIBLE
                              : FLAILER_OBJECT_INVISIBLE);
}

static void set_on_off(uint32_t screen, uint32_t object, int on)
{
    flailer_set_language_id(screen, object, on ? LANG_ON : LANG_OFF);
}

// The player on `port` and the title over the page: PLAYER 1 for player
// 0, PLAYER 2 for player 1. Retail leaves the player NULL for a port
// neither is on, which no pause comes from; the port takes the player it
// shows.
static struct Player* player_on_port(uint32_t screen, int32_t port)
{
    struct Player* p0 = PlayerPlayersByNumber[0];
    struct Player* p1 = PlayerPlayersByNumber[1];
    struct Player* p;

    if (p0 != NULL && p0->JoyPort == port)
        p = p0;
    else if (p1 != NULL && p1->JoyPort == port)
        p = p1;
    else
        p = player_shown(0);
    if (p != NULL)
        flailer_set_language_id(screen, OBJ_PLAYER_TITLE,
                                p->PlayerNumber == 1 ? LANG_PLAYER_2
                                                     : LANG_PLAYER_1);
    return p;
}

// ------------------------------------------------- the pages' shared base
//
// 0x001710f8: the bloom (ANIMATING_MENUITEM in BloomTargetColor), the
// value's bloom (its own colour) and the arrows. 0x00171180, every
// message but ACTIVATE and UNACTIVATE: the bloom's, then the arrows'.

typedef struct {
    uint32_t       screen;    // +96
    BHighlightAnim bloom;     // +0
    BHighlightAnim value;     // +32
    BArrows        arrows;    // +64
} PauseBase;

static void base_construct(PauseBase* b, uint32_t screen)
{
    BAnim*  a = anim();
    BSetup* s = bsetup_instance();

    memset(b, 0, sizeof *b);
    b->screen = screen;
    if (a != NULL) {
        banim_highlight_init(a, &b->bloom, screen, PAUSE_MENU_OBJ_BLOOM,
                             (int32_t)BANIM_BLOOM_COLOR);
        banim_highlight_init(a, &b->value, screen, OBJ_VALUE_BLOOM, -1);
    }
    if (s != NULL)
        barrows_init(s, &b->arrows, screen, OBJ_LEFT_ARROW, OBJ_RIGHT_ARROW);
}

static void base_handle(PauseBase* b, BScreenMessage msg,
                        const BScreenCallbackData* data)
{
    BSetup* s = bsetup_instance();

    pause_highlight_handle_message(&b->bloom, msg, data);
    if (s != NULL)
        barrows_event(s, &b->arrows, msg);
}

// The arrows on `object` (0 hides them), and the value's bloom there.
static void base_follow(PauseBase* b, uint32_t object, int bloom)
{
    BSetup* s = bsetup_instance();
    BAnim*  a = anim();

    if (s != NULL)
        barrows_set(s, &b->arrows, object);
    if (bloom && a != NULL)
        banim_highlight_set_item(a, &b->value, object);
}

static void base_force_start(PauseBase* b)
{
    BAnim* a = anim();

    if (a != NULL)
        banim_highlight_force_start(a, &b->value);
}

static void base_animate(PauseBase* b)
{
    BAnim* a = anim();

    if (a != NULL)
        banim_highlight_animate(a, &b->value);
}

// START on every page but the cop's controls: back to the race if the
// player who paused pressed it.
static int base_resume(BScreenCallbackData* data)
{
    if (ThePauseMenu == NULL
        || !pause_menu_maybe_resume(ThePauseMenu, data->port))
        return 0;
    data->noise = NOISE_START;
    return 1;
}

// ------------------------------------------------- the special events

// AddSpecialEvent on the race's ReplayManager (0x0013e3f8): the change is
// made at once (pausereplay.c, through main.c's gReplayHandleSpecialEventFn)
// and kept for the replay. Retail calls it on pReplayManager with no test;
// with no manager the port makes the change alone.
static void special_event(int32_t ev, int32_t a, int32_t b)
{
    if (pReplayManager != NULL) {
        replaymgr_add_special_event(pReplayManager, ev, a, b);
    } else {
        ReplaySpecialEventInfo e;

        e.Type = ev;
        e.LoopCount = WorldLoopCounter;
        e.A = a;
        e.B = b;
        pause_menu_replay_special_event(&e);
    }
    say("pause: event %d (%d, %d)", (int)ev, (int)a, (int)b);
}

// ---------------------------------------------------------- the Player's

void player_cycle_hud(struct Player* p, int32_t dir)
{
    static const int8_t kOne[4] = { 0, 1, 3, 2 };
    static const int8_t kTwo[3] = { 0, 3, 2 };
    const int8_t*       list = kOne;
    int32_t             n = 4, i, at = 0;

    if (p == NULL)
        return;
    if (PLAYER_NUM_SHOWN() == 2) {
        list = kTwo;
        n = 3;
    }
    for (i = 0; i < n; i++)
        if (list[i] == p->PlayerSettings.PlayersHudState)
            at = i;
    at += dir;
    if (at < 0)
        at = n - 1;
    if (at >= n)
        at = 0;
    p->PlayerSettings.PlayersHudState = list[at];
}

void player_set_camera_spring(struct Player* p, int32_t v)
{
    CameraMover* m = p->pCameraMover;

    p->PlayerSettings.CameraSpring = v;
    if (m != NULL && m->Type == CM_DRIVE)
        ((DriveCameraMover*)m)->DisableLag = v;
}

// 0x00181e78, after Display's lookback: the drive camera's LookbackSpeed
// put back to retail's 300.9 (0x0032e1d4).
static void player_reset_lookback_speed(struct Player* p)
{
    CameraMover* m = p->pCameraMover;

    if (m != NULL && m->Type == CM_DRIVE)
        ((DriveCameraMover*)m)->LookbackSpeed = 300.9f;
}

// ------------------------------------------------------------ PauseOptions
//
// 0x00172068 .. 0x001729f0, 144 bytes in retail.

#define OPT_ITEM_AUDIO     ITEM(1)
#define OPT_ITEM_DISPLAY   ITEM(2)
#define OPT_ITEM_VIBRATION ITEM(3)
#define OPT_ITEM_DAMAGE    ITEM(4)
#define OPT_ITEM_HANDLING  ITEM(5)
#define OPT_ITEM_TRANS     ITEM(6)
#define OPT_ITEM_JUMP      ITEM(7)
#define OPT_ITEM_ZONE      ITEM(8)
#define OPT_ITEM_ALT_CAM   ITEM(9)    // off the screen in PAUSE_OPTIONS

#define OPT_OBJ_VIBRATION  0x5deb55a3u
#define OPT_OBJ_DAMAGE     0xb6791614u
#define OPT_OBJ_HANDLING   0xa2450f0fu
#define OPT_OBJ_TRANS      0x6db88809u
#define OPT_OBJ_JUMP       0x1f1b628bu
#define OPT_OBJ_ZONE       0x16e95f2bu
#define OPT_OBJ_ALT_CAM    0xcb3bdd8fu

// Damage On/Off, Handling Classic/Extreme, Transmission by type.
#define LANG_DAMAGE_ON   210009
#define LANG_DAMAGE_OFF  210010
#define LANG_CLASSIC     49050
#define LANG_EXTREME     49060
#define LANG_AUTOMATIC   49020
#define LANG_MANUAL      49030
#define LANG_SEMI_AUTO   49010

typedef struct {
    PauseBase      base;
    struct Player* player;   // +136
    int32_t        port;     // +140
    int            live;
} PauseOptions;

static PauseOptions sOptions;

// The port Display was chosen from (gp-21000, 0x003306f8).
static int32_t sDisplayPort = -1;

// Vibration's row hidden, and the rows under it moved up one: each
// label and value to where the one above it was. The places are read
// once, before the first move, so a second visit moves nothing further.
static const uint32_t kOptLabels[6] = {
    OPT_ITEM_VIBRATION, OPT_ITEM_DAMAGE, OPT_ITEM_HANDLING, OPT_ITEM_TRANS,
    OPT_ITEM_JUMP, OPT_ITEM_ZONE,
};
static const uint32_t kOptValues[6] = {
    OPT_OBJ_VIBRATION, OPT_OBJ_DAMAGE, OPT_OBJ_HANDLING, OPT_OBJ_TRANS,
    OPT_OBJ_JUMP, OPT_OBJ_ZONE,
};

static void hide_vibration(uint32_t screen)
{
    static int     held;
    static int32_t labelY[6], valueY[6];
    int            i;

    if (!held) {
        for (i = 0; i < 6; i++) {
            labelY[i] = (int32_t)flailer_get_top_left_y(screen, kOptLabels[i]);
            valueY[i] = (int32_t)flailer_get_top_left_y(screen, kOptValues[i]);
        }
        held = 1;
    }
    gray_menu_item(OPT_ITEM_VIBRATION, GRAY_HIDE, screen);
    flailer_set_visibility(screen, OPT_OBJ_VIBRATION,
                           FLAILER_OBJECT_INVISIBLE);
    for (i = 1; i < 6; i++) {
        flailer_set_top_left_y(screen, kOptLabels[i], labelY[i - 1]);
        flailer_set_top_left_y(screen, kOptValues[i], valueY[i - 1]);
    }
}

static void opt_display_damage(PauseOptions* o)
{
    flailer_set_language_id(o->base.screen, OPT_OBJ_DAMAGE,
                            TheRaceParameters.DamageEnabled
                                ? LANG_DAMAGE_ON : LANG_DAMAGE_OFF);
}

// 0x00172688.
static void opt_display_handling(PauseOptions* o)
{
    flailer_set_language_id(o->base.screen, OPT_OBJ_HANDLING,
                            o->player->PlayerSettings.DrivingStyle == 0
                                ? LANG_CLASSIC : LANG_EXTREME);
}

static void opt_display_transmission(PauseOptions* o)
{
    int8_t t = o->player->PlayerSettings.TransmissionType;

    if (t == 0)
        flailer_set_language_id(o->base.screen, OPT_OBJ_TRANS,
                                LANG_AUTOMATIC);
    else if (t == 1)
        flailer_set_language_id(o->base.screen, OPT_OBJ_TRANS, LANG_MANUAL);
    else if (t == 2)
        flailer_set_language_id(o->base.screen, OPT_OBJ_TRANS,
                                LANG_SEMI_AUTO);
}

static void opt_display_jump_cam(PauseOptions* o)
{
    set_on_off(o->base.screen, OPT_OBJ_JUMP,
               TheRaceParameters.GlobalDisplaySettings.JumpCams != 0);
}

static void opt_display_zone_cam(PauseOptions* o)
{
    set_on_off(o->base.screen, OPT_OBJ_ZONE,
               TheRaceParameters.GlobalDisplaySettings.ZoneCams != 0);
}

// 0x00172260: the two cameras' rows only with one player.
static void opt_gray_cams(PauseOptions* o)
{
    int one = PLAYER_NUM_SHOWN() == 1;
    int mode = one ? GRAY_ENABLE : GRAY_HIDE;
    int vis = one ? FLAILER_OBJECT_VISIBLE : FLAILER_OBJECT_INVISIBLE;

    gray_menu_item(OPT_ITEM_JUMP, mode, o->base.screen);
    flailer_set_visibility(o->base.screen, OPT_OBJ_JUMP, vis);
    gray_menu_item(OPT_ITEM_ZONE, mode, o->base.screen);
    flailer_set_visibility(o->base.screen, OPT_OBJ_ZONE, vis);
}

// The constructor. Vibration and Alternate Cam (whose value is the
// lookback's) are left out: the one hidden here, the other off the screen.
// Retail grays Damage only for an active demo disc.
static void opt_construct(PauseOptions* o, uint32_t screen, int32_t port)
{
    memset(o, 0, sizeof *o);
    base_construct(&o->base, screen);
    o->port = port;
    o->player = player_on_port(screen, port);
    o->live = 1;
    if (o->player == NULL)
        return;
    hide_vibration(screen);
    opt_display_damage(o);
    opt_display_handling(o);
    opt_display_transmission(o);
    opt_display_jump_cam(o);
    opt_display_zone_cam(o);
    opt_gray_cams(o);
    flailer_set_visibility(screen, OPT_OBJ_DAMAGE, FLAILER_OBJECT_VISIBLE);
    say("pause options: in, player %d", (int)o->player->PlayerNumber);
}

static uint32_t opt_value_of(uint32_t item)
{
    switch (item) {
    case OPT_ITEM_VIBRATION: return OPT_OBJ_VIBRATION;
    case OPT_ITEM_DAMAGE:    return OPT_OBJ_DAMAGE;
    case OPT_ITEM_HANDLING:  return OPT_OBJ_HANDLING;
    case OPT_ITEM_TRANS:     return OPT_OBJ_TRANS;
    case OPT_ITEM_JUMP:      return OPT_OBJ_JUMP;
    case OPT_ITEM_ZONE:      return OPT_OBJ_ZONE;
    case OPT_ITEM_ALT_CAM:   return OPT_OBJ_ALT_CAM;
    default:                 return 0;
    }
}

// Left or Right on a row: the change, as a special event, and its value
// shown again. Each answers whether it changed anything; every one does.
static int opt_change(PauseOptions* o, uint32_t item, BScreenMessage msg)
{
    const cPlayerSettings* s = &o->player->PlayerSettings;
    int32_t                t;

    switch (item) {
    case OPT_ITEM_DAMAGE:      // SetDrivingStyle, so named in retail
        special_event(PAUSE_EVENT_DAMAGE,
                      TheRaceParameters.DamageEnabled ^ 1, 0);
        opt_display_damage(o);
        return 1;
    case OPT_ITEM_HANDLING:    // 0x00172420
        special_event(PAUSE_EVENT_HANDLING, o->player->PlayerNumber,
                      s->DrivingStyle == 0);
        opt_display_handling(o);
        opt_gray_cams(o);
        return 1;
    case OPT_ITEM_TRANS:
        t = s->TransmissionType + (msg == BMSG_MENUITEM_PAD_LEFT ? -1 : 1);
        special_event(PAUSE_EVENT_TRANSMISSION, o->player->PlayerNumber,
                      (t % 3 + 3) % 3);
        opt_display_transmission(o);
        return 1;
    case OPT_ITEM_JUMP:
        special_event(PAUSE_EVENT_JUMP_CAMS,
                      TheRaceParameters.GlobalDisplaySettings.JumpCams == 0,
                      0);
        opt_display_jump_cam(o);
        return 1;
    case OPT_ITEM_ZONE:
        special_event(PAUSE_EVENT_ZONE_CAMS,
                      TheRaceParameters.GlobalDisplaySettings.ZoneCams == 0,
                      0);
        opt_display_zone_cam(o);
        return 1;
    default:
        return 0;
    }
}

static void opt_handle(PauseOptions* o, BScreenMessage msg,
                       BScreenCallbackData* data)
{
    uint32_t v;

    base_handle(&o->base, msg, data);
    switch (msg) {
    case BMSG_MENUITEM_SELECT:
        if (data->itemHash == OPT_ITEM_AUDIO) {
            change_to_screen(kPauseAudioScreen, 0);
        } else if (data->itemHash == OPT_ITEM_DISPLAY) {
            sDisplayPort = data->port;
            change_to_screen(kPauseDisplayScreen, 0);
        } else {
            data->noise = NOISE_NONE;
        }
        break;
    case BMSG_MENUITEM_HIGHLIGHT:
        v = opt_value_of(data->itemHash);
        base_follow(&o->base, v, 1);
        break;
    case BMSG_MENUITEM_PAD_LEFT:
    case BMSG_MENUITEM_PAD_RIGHT:
        if (o->player != NULL && opt_change(o, data->itemHash, msg)) {
            data->noise = msg == BMSG_MENUITEM_PAD_LEFT ? NOISE_LEFT
                                                         : NOISE_RIGHT;
            base_force_start(&o->base);
        }
        break;
    case BMSG_SCREEN_START_BUTTON:
        base_resume(data);
        break;
    case BMSG_SCREEN_BACK_BUTTON:
        change_to_screen(kPauseMenuScreen, 0);
        data->param = 0;
        break;
    case BMSG_SCREEN_TICK:
        base_animate(&o->base);
        break;
    default:
        break;
    }
}

void pause_options_callback(struct BGameFlow* gf, BScreenMessage msg,
                            BScreenCallbackData* data)
{
    (void)gf;
    if (msg == BMSG_SCREEN_ACTIVATE) {
        opt_construct(&sOptions, data->itemHash,
                      ThePauseMenu != NULL ? ThePauseMenu->OptionsChooser
                                           : -1);
    } else if (msg == BMSG_SCREEN_UNACTIVATE) {
        memset(&sOptions, 0, sizeof sOptions);
    } else if (sOptions.live) {
        opt_handle(&sOptions, msg, data);
    }
}

// ---------------------------------------------------------- PauseAudioOpts
//
// 0x001711c8 .. 0x00171898, 288 bytes in retail: five FlailerSliders in a
// bTList and the seven volumes, read from bSound when the page opens and
// set there when it closes. A slider's step changes only the copy.

#define AUD_ITEM_MODE      ITEM(6)
#define AUD_OBJ_MODE_VALUE 0x2932dfcau

#define LANG_MONO      110009
#define LANG_STEREO    110008
#define LANG_PROLOGIC  PORTLANG_SURROUND   // retail's 110011, Pro Logic II

#define NUM_CATEGORIES 7
#define NUM_SLIDERS    5

// 0x001afa28's table: each category's volume as the game ships it. A
// slider's knob sits at 0.7 of the track for it.
static const float kDefaultVolume[NUM_CATEGORIES] = {
    0.38f, 0.55f, 0.33f, 0.31f, 0.85f, 0.45f, 0.75f,
};

// The sliders by row: the track, the knob and bSound's category. Racing
// music, ambient effects, engines, tires, speech.
static const struct {
    uint32_t track, knob, cat;
} kPauseSliders[NUM_SLIDERS] = {
    { 0xa29f7a16u, 0xc866642bu, 4 },
    { 0xa29f7a17u, 0xc866686cu, 0 },
    { 0xa29f7a18u, 0xc8666cadu, 2 },
    { 0xa29f7a19u, 0xc86670eeu, 1 },
    { 0xa29f7a1au, 0xc866752fu, 6 },
};

// FlailerSlider, 92 bytes in retail (audiooptions.c has its decode).
typedef struct {
    uint32_t item, track, knob, cat;
    float    min, max;
    float*   value;
    float    scale;
    BSpline  pos;
} PauseSlider;

typedef struct {
    PauseBase   base;
    float       volume[NUM_CATEGORIES];   // +112, by category
    PauseSlider slider[NUM_SLIDERS];
    int         live;
} PauseAudio;

static PauseAudio sAudio;

static int audio_mode(void)
{
    return sHooks.sound != NULL ? sound_get_audio_mode(sHooks.sound) : 1;
}

// RedrawAudioMode (0x00171680).
static void aud_redraw_mode(PauseAudio* p, int mode)
{
    uint32_t id = mode == 0 ? LANG_MONO
                : mode == 1 ? LANG_STEREO
                : mode == 2 ? LANG_PROLOGIC : 0;

    flailer_set_language_id(p->base.screen, AUD_OBJ_MODE_VALUE, id);
}

static void aud_construct(PauseAudio* p, uint32_t screen)
{
    int i;

    memset(p, 0, sizeof *p);
    base_construct(&p->base, screen);
    for (i = 0; i < NUM_CATEGORIES; i++)
        p->volume[i] = sHooks.jukebox != NULL
                           ? jb_get_category_volume(sHooks.jukebox,
                                                    (uint32_t)i)
                           : 0.0f;
    for (i = 0; i < NUM_SLIDERS; i++) {
        PauseSlider* sl = &p->slider[i];

        sl->item = ITEM(1 + i);
        sl->track = kPauseSliders[i].track;
        sl->knob = kPauseSliders[i].knob;
        sl->cat = kPauseSliders[i].cat;
        sl->value = &p->volume[sl->cat];
        sl->min = 0.0f;
        sl->max = 1.0f;
        sl->scale = 0.7f / kDefaultVolume[sl->cat];
        sl->pos.duration = 0.25f;
        sl->pos.arrivalThreshold = 1.0f;
        sl->pos.valDesired = *sl->value * sl->scale;
        sl->pos.val = sl->pos.valDesired;
        sl->pos.state = 0;
        sl->pos.dval = sl->pos.dvalDesired;
    }
    aud_redraw_mode(p, audio_mode());
    p->live = 1;
    say("pause audio: in, mode %d", audio_mode());
}

// The destructor (0x001714f8): the seven volumes into bSound, and speech's
// ducking told.
static void aud_destruct(PauseAudio* p)
{
    int i;

    if (!p->live)
        return;
    if (sHooks.jukebox != NULL) {
        for (i = 0; i < NUM_CATEGORIES; i++)
            jb_set_category_volume(sHooks.jukebox, (uint32_t)i,
                                   p->volume[i]);
        jb_save_volumes_for_speech(sHooks.jukebox);
    }
    say("pause audio: out, racing %.3f sfx %.3f engine %.3f tires %.3f "
        "speech %.3f", (double)p->volume[4], (double)p->volume[0],
        (double)p->volume[2], (double)p->volume[1], (double)p->volume[6]);
    memset(p, 0, sizeof *p);
}

// ChangeAudioMode (0x001715f8): one along, wrapping, at once.
static void aud_change_mode(PauseAudio* p, BScreenMessage msg)
{
    int mode = (audio_mode() + (msg == BMSG_MENUITEM_PAD_LEFT ? -1 : 1)) % 3;

    if (mode < 0)
        mode = 2;
    if (sHooks.sound != NULL)
        sound_set_audio_mode(sHooks.sound, mode);
    aud_redraw_mode(p, mode);
    say("pause audio: mode %d", mode);
}

// The slider's step, as MenuCallback does it: 0.05 of the volume, held to
// the track, and the adjust sound at the knob's new place if it moved.
static void aud_step(PauseSlider* sl, BScreenMessage msg)
{
    float d = msg == BMSG_MENUITEM_PAD_LEFT ? -0.05f : 0.05f;
    float pos = (*sl->value + d) * sl->scale;
    float v, was;

    if (sl->max < pos)
        pos = sl->max;
    if (pos < sl->min)
        pos = sl->min;
    v = pos / sl->scale;
    was = *sl->value;
    *sl->value = v;
    if (sHooks.jukebox != NULL)
        jb_save_volumes_for_speech(sHooks.jukebox);
    if (v != was && sHooks.sound != NULL)
        sound_play_common_region_sample(sHooks.sound, "MenuAdjustVolume",
                                        pos);
    sl->pos.valDesired = pos;
    if (pos != sl->pos.val)
        sl->pos.state = 2;
}

// FlailerSlider::Animate (0x0016de30).
static void aud_animate(BGameFlow* gf, uint32_t screen, PauseSlider* sl)
{
    int32_t l = 0, t = 0, r = 0, b = 0;

    bspline_seek(&sl->pos, gf != NULL ? gf->realElapsed : 0.0f);
    flailer_get_bounding_box(screen, sl->track, &l, &t, &r, &b);
    flailer_set_top_left_x(screen, sl->knob,
                           (int32_t)((float)l + sl->pos.val * (float)(r - l)));
}

static void aud_handle(BGameFlow* gf, PauseAudio* p, BScreenMessage msg,
                       BScreenCallbackData* data)
{
    int i;

    base_handle(&p->base, msg, data);
    switch (msg) {
    case BMSG_MENUITEM_SELECT:
        data->noise = NOISE_NONE;
        break;
    case BMSG_MENUITEM_HIGHLIGHT:
        if (data->itemHash == AUD_ITEM_MODE)
            base_follow(&p->base, AUD_OBJ_MODE_VALUE, 1);
        else
            base_follow(&p->base, 0, 0);
        break;
    case BMSG_MENUITEM_PAD_LEFT:
    case BMSG_MENUITEM_PAD_RIGHT:
        if (data->itemHash == AUD_ITEM_MODE) {
            aud_change_mode(p, msg);
            data->noise = msg == BMSG_MENUITEM_PAD_LEFT ? NOISE_LEFT
                                                         : NOISE_RIGHT;
            base_force_start(&p->base);
            break;
        }
        for (i = 0; i < NUM_SLIDERS; i++)
            if (p->slider[i].item == data->itemHash)
                aud_step(&p->slider[i], msg);
        break;
    case BMSG_SCREEN_START_BUTTON:
        base_resume(data);
        break;
    case BMSG_SCREEN_BACK_BUTTON:
        change_to_screen(kPauseOptionsScreen, 0);
        data->param = 0;
        break;
    case BMSG_SCREEN_TICK:
        for (i = 0; i < NUM_SLIDERS; i++)
            aud_animate(gf, p->base.screen, &p->slider[i]);
        base_animate(&p->base);
        break;
    default:
        break;
    }
}

void pause_audio_callback(struct BGameFlow* gf, BScreenMessage msg,
                          BScreenCallbackData* data)
{
    if (msg == BMSG_SCREEN_ACTIVATE) {
        aud_construct(&sAudio, data->itemHash);
    } else if (msg == BMSG_SCREEN_UNACTIVATE) {
        data->noise = NOISE_CANCEL;
        aud_destruct(&sAudio);
    } else if (sAudio.live) {
        aud_handle(gf, &sAudio, msg, data);
    }
}

// -------------------------------------------------------- PauseDisplayOpts
//
// 0x00172aa0 .. 0x00173d88, 108 bytes in retail: the player's own HUD
// settings and the race's display settings, changed where they live.

#define DIS_ITEM_HUD        ITEM(1)
#define DIS_ITEM_MIRROR     ITEM(2)
#define DIS_ITEM_TRACK_MAP  ITEM(3)
#define DIS_ITEM_LEADERS    ITEM(4)
#define DIS_ITEM_LAP_INFO   ITEM(5)
#define DIS_ITEM_POSITION   ITEM(6)
#define DIS_ITEM_GAUGES     ITEM(7)
#define DIS_ITEM_SPLIT      ITEM(8)
#define DIS_ITEM_SCORE      ITEM(9)
#define DIS_ITEM_SPRING     ITEM_10
#define DIS_ITEM_LOOKBACK   ITEM_11
#define DIS_ITEM_HOTKEY     ITEM_12

#define DIS_OBJ_HUD         0x5b472b16u
#define DIS_OBJ_MIRROR      0x2e931f1bu
#define DIS_OBJ_TRACK_MAP   0x55cb09f2u   // TRACKMAP
#define DIS_OBJ_LEADERS     0x71a78ef4u
#define DIS_OBJ_LAP_INFO    0x8b788a68u
#define DIS_OBJ_POSITION    0xe8434eb4u
#define DIS_OBJ_GAUGES      0x5d6c141bu
#define DIS_OBJ_SPLIT       0x12b1ebd9u
#define DIS_OBJ_SCORE       0x5d2a9432u
#define DIS_OBJ_SPRING      0xffc3dcd2u
#define DIS_OBJ_LOOKBACK    0x2e018745u
#define DIS_OBJ_HOTKEY      0x4aff0df3u

// PreferredHudFeatures' bits the page turns on and off.
#define HUD_SPLIT     0x004u
#define HUD_POSITION  0x010u
#define HUD_GAUGES    0x040u
#define HUD_LAP_INFO  0x100u

// "Lap Info", which AdjustLapInfo puts on MENUITEM_5 whoever is driving.
#define LANG_LAP_INFO 140016
// The lookback's two: Lookback, and Bird's Eye for 0.
#define LANG_LOOKBACK   140113
#define LANG_BIRDS_EYE  140118

typedef struct {
    PauseBase      base;
    struct Player* player;   // +104
    int            live;
} PauseDisplay;

static PauseDisplay sDisplay;

// The HUD's four states: On, Off, Map Only, Gauges Only.
static const int kHudIds[4] = { 210004, 210006, 210005, 210025 };
// DisplayTrackmap's, by mode: 3D Rotation .. Off and the cop's two.
static const int kTrackMapIds[10] = {
    140101, 140102, 140103, 140200, 140104, 140105, LANG_OFF, 140104,
    140201, 140202,
};
// 0x002b3358: Off, Top 3, On.
static const int kLeaderboardIds[3] = { LANG_OFF, 102001, LANG_ON };
static const int kSplitIds[5] = { 140108, 140109, 140110, 140111, LANG_OFF };

// The track map lists tGlobalDisplaySettings::CycleTrackMap steps
// through in a race: one player's, two players' and the cop's.
static const int8_t kOnePlayerMaps[6] = { 0, 1, 2, 3, 4, 6 };
static const int8_t kTwoPlayerMaps[2] = { 7, 6 };
static const int8_t kBeTheCopMaps[2] = { 8, 6 };

static const cPlayerSettings* dis_settings(const PauseDisplay* d)
{
    return &d->player->PlayerSettings;
}

static int8_t* dis_track_map_mode(void)
{
    tGlobalDisplaySettings* g = &TheRaceParameters.GlobalDisplaySettings;

    if (TheRaceParameters.BeACop)
        return &g->BeTheCopTrackMapMode;
    if (PLAYER_NUM_SHOWN() == 1)
        return &g->OnePlayerTrackMapMode;
    return &g->TwoPlayerTrackMapMode;
}

// The time trial against a set time (the leaderboard and position rows'
// test, 0x00172f58 and ShouldSeePosition).
static int time_trial_time_set(void)
{
    uint32_t t = TheRaceParameters.TimeTrialTime.PackedTime;

    return t != 0 && t != 0x7fffffffu;
}

static void dis_display_hud(PauseDisplay* d)
{
    int8_t s = dis_settings(d)->PlayersHudState;

    flailer_set_language_id(d->base.screen, DIS_OBJ_HUD,
                            s >= 0 && s < 4 ? (uint32_t)kHudIds[s] : 0);
}

static void dis_display_mirror(PauseDisplay* d)
{
    set_on_off(d->base.screen, DIS_OBJ_MIRROR,
               TheRaceParameters.GlobalDisplaySettings.RearViewMirror != 0);
}

static void dis_display_track_map(PauseDisplay* d)
{
    int8_t m = *dis_track_map_mode();

    flailer_set_language_id(d->base.screen, DIS_OBJ_TRACK_MAP,
                            m >= 0 && m < 10 ? (uint32_t)kTrackMapIds[m]
                                             : 0);
}

static void dis_display_leaders(PauseDisplay* d)
{
    int8_t m = TheRaceParameters.GlobalDisplaySettings.LeaderboardMode;

    flailer_set_language_id(d->base.screen, DIS_OBJ_LEADERS,
                            m >= 0 && m < 3 ? (uint32_t)kLeaderboardIds[m]
                                            : 0);
}

static void dis_display_feature(PauseDisplay* d, uint32_t object,
                                uint32_t bit)
{
    set_on_off(d->base.screen, object,
               (dis_settings(d)->PreferredHudFeatures & bit) != 0);
}

static void dis_display_split(PauseDisplay* d)
{
    int8_t s = dis_settings(d)->SplitTimeType;

    flailer_set_language_id(d->base.screen, DIS_OBJ_SPLIT,
                            s >= 0 && s < 5 ? (uint32_t)kSplitIds[s] : 0);
}

static void dis_display_score(PauseDisplay* d)
{
    set_on_off(d->base.screen, DIS_OBJ_SCORE, dis_settings(d)->New44 != 0);
}

// Camera spring reads On unless it is 1: 1 is the lag turned off.
static void dis_display_spring(PauseDisplay* d)
{
    set_on_off(d->base.screen, DIS_OBJ_SPRING,
               dis_settings(d)->CameraSpring != 1);
}

static void dis_display_lookback(PauseDisplay* d)
{
    int32_t l = dis_settings(d)->Lookback;

    flailer_set_language_id(d->base.screen, DIS_OBJ_LOOKBACK,
                            l == 0 ? LANG_BIRDS_EYE
                            : l == 1 ? LANG_LOOKBACK : 0);
}

static void dis_display_hotkey(PauseDisplay* d)
{
    set_on_off(d->base.screen, DIS_OBJ_HOTKEY, dis_settings(d)->New40 != 0);
}

// 0x00172bd0: with the HUD anything but On, every row under it is grayed
// and its value hidden. Then each row's own test.
static void dis_gray(PauseDisplay* d)
{
    const RaceParameters* rp = &TheRaceParameters;
    uint32_t              sc = d->base.screen;
    int                   hud = dis_settings(d)->PlayersHudState == 0;
    int                   cop = rp->BeACop != 0;
    int                   free_run = race_parameters_is_free_run(rp) != 0;
    int                   tt = time_trial_time_set();
    // A time trial against a set time, as a lap race or point to point.
    int                   timed = !cop && tt
                                  && (rp->RaceType == 2 || rp->Point2Point);

    gray_row(sc, DIS_ITEM_MIRROR, DIS_OBJ_MIRROR,
             PLAYER_NUM_SHOWN() == 1 && hud);
    gray_row(sc, DIS_ITEM_TRACK_MAP, DIS_OBJ_TRACK_MAP, hud);
    gray_row(sc, DIS_ITEM_LEADERS, DIS_OBJ_LEADERS,
             !timed && !free_run && !cop && hud);
    gray_row(sc, DIS_ITEM_LAP_INFO, DIS_OBJ_LAP_INFO,
             hud && (!cop || d->player->PlayerNumber != 0));
    gray_row(sc, DIS_ITEM_POSITION, DIS_OBJ_POSITION,
             !timed && !cop && !free_run && hud);
    gray_row(sc, DIS_ITEM_GAUGES, DIS_OBJ_GAUGES, !cop && hud);
    gray_row(sc, DIS_ITEM_SPLIT, DIS_OBJ_SPLIT, !cop && hud);
    gray_row(sc, DIS_ITEM_SCORE, DIS_OBJ_SCORE, !free_run && hud);
}

static void dis_construct(PauseDisplay* d, uint32_t screen, int32_t port)
{
    memset(d, 0, sizeof *d);
    base_construct(&d->base, screen);
    d->player = player_on_port(screen, port);
    d->live = 1;
    if (d->player == NULL)
        return;
    dis_display_mirror(d);
    dis_display_spring(d);
    dis_display_lookback(d);
    dis_display_feature(d, DIS_OBJ_POSITION, HUD_POSITION);
    dis_display_split(d);
    dis_display_feature(d, DIS_OBJ_LAP_INFO, HUD_LAP_INFO);
    dis_display_feature(d, DIS_OBJ_GAUGES, HUD_GAUGES);
    dis_display_track_map(d);
    dis_display_leaders(d);
    dis_display_score(d);
    dis_display_hud(d);
    dis_display_hotkey(d);
    dis_gray(d);
    // AdjustLapInfo (0x001731c0): the cop's test picks nothing; the row
    // is "Lap Info" either way.
    flailer_set_language_id(screen, DIS_ITEM_LAP_INFO, LANG_LAP_INFO);
    say("pause display: in, player %d, hud %d",
        (int)d->player->PlayerNumber,
        (int)d->player->PlayerSettings.PlayersHudState);
}

static uint32_t dis_value_of(uint32_t item)
{
    switch (item) {
    case DIS_ITEM_HUD:       return DIS_OBJ_HUD;
    case DIS_ITEM_MIRROR:    return DIS_OBJ_MIRROR;
    case DIS_ITEM_TRACK_MAP: return DIS_OBJ_TRACK_MAP;
    case DIS_ITEM_LEADERS:   return DIS_OBJ_LEADERS;
    case DIS_ITEM_LAP_INFO:  return DIS_OBJ_LAP_INFO;
    case DIS_ITEM_POSITION:  return DIS_OBJ_POSITION;
    case DIS_ITEM_GAUGES:    return DIS_OBJ_GAUGES;
    case DIS_ITEM_SPLIT:     return DIS_OBJ_SPLIT;
    case DIS_ITEM_SCORE:     return DIS_OBJ_SCORE;
    case DIS_ITEM_SPRING:    return DIS_OBJ_SPRING;
    case DIS_ITEM_LOOKBACK:  return DIS_OBJ_LOOKBACK;
    case DIS_ITEM_HOTKEY:    return DIS_OBJ_HOTKEY;
    default:                 return 0;
    }
}

// tGlobalDisplaySettings::CycleTrackMap (0x001ee148) in a race: the
// shown mode stepped through its list by `dir`, wrapping; a mode off the
// list goes to the list's first. Answers whether it changed.
static int dis_cycle_track_map(int dir)
{
    int8_t*       m = dis_track_map_mode();
    const int8_t* list = kOnePlayerMaps;
    int           n = 6, i, was = *m;

    if (m == &TheRaceParameters.GlobalDisplaySettings.BeTheCopTrackMapMode) {
        list = kBeTheCopMaps;
        n = 2;
    } else if (m
               == &TheRaceParameters.GlobalDisplaySettings
                       .TwoPlayerTrackMapMode) {
        list = kTwoPlayerMaps;
        n = 2;
    }
    for (i = 0; i < n && list[i] != *m; i++) {}
    if (i == n) {
        *m = list[0];
    } else {
        i += dir;
        if (i >= n)
            i = 0;
        else if (i < 0)
            i = n - 1;
        *m = list[i];
    }
    return *m != was;
}

// A PreferredHudFeatures bit turned over; always a change.
static int dis_toggle_feature(PauseDisplay* d, uint32_t object, uint32_t bit)
{
    d->player->PlayerSettings.PreferredHudFeatures ^= bit;
    dis_display_feature(d, object, bit);
    return 1;
}

static int dis_change(PauseDisplay* d, uint32_t item, int dir)
{
    cPlayerSettings*        s = &d->player->PlayerSettings;
    tGlobalDisplaySettings* g = &TheRaceParameters.GlobalDisplaySettings;
    int                     v, was;

    switch (item) {
    case DIS_ITEM_HUD:
        player_cycle_hud(d->player, dir);
        dis_display_hud(d);
        dis_gray(d);
        return 1;
    case DIS_ITEM_MIRROR:
        g->RearViewMirror = g->RearViewMirror == 0;
        dis_display_mirror(d);
        return 1;
    case DIS_ITEM_TRACK_MAP:
        v = dis_cycle_track_map(dir);
        dis_display_track_map(d);
        return v;
    case DIS_ITEM_LEADERS:    // CycleLeaderboardMode: Off and On only
        was = g->LeaderboardMode;
        g->LeaderboardMode = was != 2 ? 2 : 0;
        dis_display_leaders(d);
        return g->LeaderboardMode != was;
    case DIS_ITEM_LAP_INFO:
        return dis_toggle_feature(d, DIS_OBJ_LAP_INFO, HUD_LAP_INFO);
    case DIS_ITEM_POSITION:
        return dis_toggle_feature(d, DIS_OBJ_POSITION, HUD_POSITION);
    case DIS_ITEM_GAUGES:
        return dis_toggle_feature(d, DIS_OBJ_GAUGES, HUD_GAUGES);
    case DIS_ITEM_SPLIT:      // CycleSplitTime (0x001ee258)
        v = s->SplitTimeType + dir;
        if (v < 0)
            v = 4;
        if (v > 4)
            v = 0;
        was = s->SplitTimeType;
        s->SplitTimeType = (int8_t)v;
        if (v == 4)
            s->PreferredHudFeatures &= ~HUD_SPLIT;
        else
            s->PreferredHudFeatures |= HUD_SPLIT;
        dis_display_split(d);
        return v != was;
    case DIS_ITEM_SCORE:      // 0x001ee020
        s->New44 = s->New44 == 0;
        dis_display_score(d);
        return 1;
    case DIS_ITEM_SPRING:     // ToggleCameraSpring (0x001ee328)
        s->CameraSpring = s->CameraSpring == 0;
        player_set_camera_spring(d->player, s->CameraSpring);
        dis_display_spring(d);
        return 1;
    case DIS_ITEM_LOOKBACK:   // ToggleLookback (0x001ee2d8)
        if (s->Lookback == 0)
            s->Lookback = 1;
        else if (s->Lookback == 1)
            s->Lookback = 0;
        player_reset_lookback_speed(d->player);
        dis_display_lookback(d);
        return 1;
    case DIS_ITEM_HOTKEY:     // 0x001ee220
        s->New40 = s->New40 == 0;
        dis_display_hotkey(d);
        return 1;
    default:
        return 0;
    }
}

static void dis_handle(PauseDisplay* d, BScreenMessage msg,
                       BScreenCallbackData* data)
{
    base_handle(&d->base, msg, data);
    switch (msg) {
    case BMSG_MENUITEM_SELECT:
        data->noise = NOISE_NONE;
        break;
    case BMSG_MENUITEM_HIGHLIGHT:
        base_follow(&d->base, dis_value_of(data->itemHash), 1);
        break;
    case BMSG_MENUITEM_PAD_LEFT:
    case BMSG_MENUITEM_PAD_RIGHT:
        if (d->player != NULL
            && dis_change(d, data->itemHash,
                          msg == BMSG_MENUITEM_PAD_LEFT ? -1 : 1)) {
            data->noise = msg == BMSG_MENUITEM_PAD_LEFT ? NOISE_LEFT
                                                         : NOISE_RIGHT;
            base_force_start(&d->base);
            say("pause display: %08x hud %d features 0x%03x",
                (unsigned)data->itemHash,
                (int)d->player->PlayerSettings.PlayersHudState,
                (unsigned)d->player->PlayerSettings.PreferredHudFeatures);
        } else {
            data->noise = NOISE_NONE;
        }
        break;
    case BMSG_SCREEN_START_BUTTON:
        base_resume(data);
        break;
    case BMSG_SCREEN_BACK_BUTTON:
        change_to_screen(kPauseOptionsScreen, 0);
        data->param = 0;
        break;
    case BMSG_SCREEN_TICK:
        base_animate(&d->base);
        break;
    default:
        break;
    }
}

void pause_display_callback(struct BGameFlow* gf, BScreenMessage msg,
                            BScreenCallbackData* data)
{
    (void)gf;
    if (msg == BMSG_SCREEN_ACTIVATE) {
        dis_construct(&sDisplay, data->itemHash, sDisplayPort);
    } else if (msg == BMSG_SCREEN_UNACTIVATE) {
        memset(&sDisplay, 0, sizeof sDisplay);
    } else if (sDisplay.live) {
        dis_handle(&sDisplay, msg, data);
    }
}

// ------------------------------------------------------ PauseRaceObjective
//
// 0x00171948 .. 0x00171bb8, 8 bytes in retail: the screen and whether it
// is the one-player blurb (the 2PBAC screen, 0xb5ecd7a0, is the other).

// gp-21068 (0x003306b4) and gp-21060 (0x003306bc): the horn's character,
// kept from the last frame a pad was in.
static int32_t sObjectiveChar;
static int32_t sControlsChar;

typedef struct {
    uint32_t screen;
    int32_t  page;   // the cop's controls: 1 or 2
    int      live;
} PauseBlurb;

static PauseBlurb sObjective;
static PauseBlurb sControls;

static void blurb_show_paging(uint32_t screen, int32_t v)
{
    flailer_set_visibility(screen, STARTRACE_OBJ_PREVIOUS, v);
    flailer_set_visibility(screen, STARTRACE_OBJ_NEXT, v);
}

static void objective_construct(PauseBlurb* b, uint32_t screen)
{
    memset(b, 0, sizeof *b);
    b->screen = screen;
    b->live = 1;
    if (TheRaceParameters.EventTreeRace)
        flailer_printf(screen, STARTRACE_OBJ_HEADING,
                       translate(STARTRACE_LANG_EVENT_OBJECTIVE),
                       (int)TheRaceEvent.nNumber);
    else if (TheRaceParameters.BeACop)
        flailer_set_language_id(screen, STARTRACE_OBJ_HEADING,
                                STARTRACE_LANG_YOURE_THE_COP);
    else
        flailer_set_language_id(screen, STARTRACE_OBJ_HEADING,
                                STARTRACE_LANG_OBJECTIVE);
    blurb_show_paging(screen, FLAILER_OBJECT_VISIBLE);
    say("pause objective: in");
}

// RENDER: pre_race_blurb_text's, its %c the horn's button.
static void objective_render(PauseBlurb* b)
{
    char        buf[512];
    const char* fmt;

    if (IsJoystickPluggedIn(0))
        sObjectiveChar = GetJoystickButtonChar(0, JOY_EVENT_HONK_HORN);
    fmt = pre_race_blurb_text(0);
    snprintf(buf, sizeof buf, fmt != NULL ? fmt : "", (int)sObjectiveChar);
    flailer_render_text_into_rectangle(b->screen, STARTRACE_OBJ_BLURB_TEXT,
                                       STARTRACE_OBJ_BLURB_BOX, buf, 1.0f);
}

// Retail leaves the paging shown, on the screen the next race's blurb
// shares; the port hides it as it goes.
void pause_race_objective_callback(struct BGameFlow* gf, BScreenMessage msg,
                                   BScreenCallbackData* data)
{
    (void)gf;
    switch (msg) {
    case BMSG_SCREEN_ACTIVATE:
        objective_construct(&sObjective, data->itemHash);
        break;
    case BMSG_SCREEN_UNACTIVATE:
        if (sObjective.live)
            blurb_show_paging(sObjective.screen, FLAILER_OBJECT_INVISIBLE);
        memset(&sObjective, 0, sizeof sObjective);
        break;
    case BMSG_SCREEN_START_BUTTON:
        if (base_resume(data))
            data->param = 1;
        break;
    case BMSG_MENUITEM_SELECT:
    case BMSG_SCREEN_BACK_BUTTON:
        change_to_screen(kPauseMenuScreen, 0);
        data->param = 0;
        break;
    case BMSG_SCREEN_RENDER:
        if (sObjective.live)
            objective_render(&sObjective);
        break;
    default:
        break;
    }
}

// -------------------------------------------------------- PauseViewControls
//
// 0x00171c50 .. 0x00171fd0: You're The Cop's controls over two pages,
// for the pad on port 0 and player 0's gears.

#define LANG_COP_CONTROLS 200021   // the heading
#define JOYSTICK_TYPE_WHEEL_22 22
#define JOYSTICK_TYPE_PAD_41   0x41

// 0x00171c50: the page's text, or NULL.
static const char* controls_text(int32_t page)
{
    const struct Player* p0 = PlayerPlayersByNumber[0];
    int32_t              pad, t, id;

    if (page != 1 && page != 2)
        return NULL;
    if (!IsJoystickPluggedIn(0))
        return translate(STARTRACE_LANG_INSERT_CONTROLLER);
    if (IsJoystickTypeWheel(0)) {
        if (GetJoystickType(0) == JOYSTICK_TYPE_WHEEL_22)
            id = page == 1 ? 200060 : 200061;
        else
            id = page == 1 ? 200054 : 200055;
        return translate(id);
    }
    pad = GetJoystickType(0) != JOYSTICK_TYPE_PAD_41;
    t = p0 != NULL ? p0->PlayerSettings.TransmissionType : 0;
    if (t < 0 || t >= 3)
        return NULL;
    if (t == 0)
        id = pad ? (page == 1 ? 200052 : 200053)
                 : (page == 1 ? 200058 : 200059);
    else
        id = pad ? (page == 1 ? 200050 : 200051)
                 : (page == 1 ? 200056 : 200057);
    return translate(id);
}

static void controls_render(PauseBlurb* b)
{
    char        buf[512];
    const char* fmt;

    if (IsJoystickPluggedIn(0))
        sControlsChar = GetJoystickButtonChar(0, JOY_EVENT_HONK_HORN);
    fmt = controls_text(b->page);
    snprintf(buf, sizeof buf, fmt != NULL ? fmt : "", (int)sControlsChar);
    flailer_render_text_into_rectangle(b->screen, STARTRACE_OBJ_BLURB_TEXT,
                                       STARTRACE_OBJ_BLURB_BOX, buf, 1.0f);
    blurb_show_paging(b->screen, FLAILER_OBJECT_VISIBLE);
}

// A selects the next page, B the one before; past either end is the
// Pause Menu. START does nothing here.
void pause_view_controls_callback(struct BGameFlow* gf, BScreenMessage msg,
                                  BScreenCallbackData* data)
{
    (void)gf;
    switch (msg) {
    case BMSG_SCREEN_ACTIVATE:
        memset(&sControls, 0, sizeof sControls);
        sControls.screen = data->itemHash;
        sControls.page = 1;
        sControls.live = 1;
        flailer_set_language_id(sControls.screen, STARTRACE_OBJ_HEADING,
                                LANG_COP_CONTROLS);
        say("pause cop controls: in");
        break;
    case BMSG_SCREEN_UNACTIVATE:
        if (sControls.live)
            blurb_show_paging(sControls.screen, FLAILER_OBJECT_INVISIBLE);
        memset(&sControls, 0, sizeof sControls);
        break;
    case BMSG_MENUITEM_SELECT:
        if (!sControls.live)
            break;
        if (++sControls.page > 2) {
            change_to_screen(kPauseMenuScreen, 0);
            data->param = 0;
        }
        break;
    case BMSG_SCREEN_BACK_BUTTON:
        if (!sControls.live)
            break;
        if (--sControls.page < 1)
            change_to_screen(kPauseMenuScreen, 0);
        data->param = 0;
        break;
    case BMSG_SCREEN_RENDER:
        if (sControls.live)
            controls_render(&sControls);
        break;
    default:
        break;
    }
}

// ---------------------------------------------------------------- the init

void pause_options_init(const PauseOptionsHooks* hooks)
{
    memset(&sHooks, 0, sizeof sHooks);
    if (hooks != NULL)
        sHooks = *hooks;
    memset(&sOptions, 0, sizeof sOptions);
    memset(&sAudio, 0, sizeof sAudio);
    memset(&sDisplay, 0, sizeof sDisplay);
    memset(&sObjective, 0, sizeof sObjective);
    memset(&sControls, 0, sizeof sControls);
    sDisplayPort = -1;
}
