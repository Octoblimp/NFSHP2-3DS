// AudioOptionsScreen and JukeBoxMusicScreen (audiooptions.h), retail's in
// its order: FlailerSlider (0x0016dc20 .. 0x0016dec8), then
// AudioOptionsScreen's constructor (0x001ef3c8), FindSlider (0x001efa68),
// ChangeAudioMode (0x001efaa0), RedrawAudioMode (0x001efb38), HandleEvent
// (0x001efb80) and Callback (0x001f0278), then JukeBoxMusicScreen's
// constructor (0x001f02d8), ShowPlaylist (0x001f0478),
// PlayCurrentSelectedSong (0x001f0cc8), HandleEvent (0x001f0d10) and
// Callback (0x001f1220). Where retail's B saves with autosave on, Audio
// Options asks (the save prompt, below).

#include "audiooptions.h"

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

// Audio Options' rows: the seven sliders, the mode, JukeBox, and the two
// Defaults (named DEFAULT_VOLUMES and DEFAULT_JUKEBOX in FRONTB.BUN).
#define ITEM_MODE            BSCR_ITEM_MENUITEM(8)
#define ITEM_JUKEBOX         BSCR_ITEM_MENUITEM(9)
#define ITEM_DEFAULT_VOLUMES 0xaee77883u
#define ITEM_DEFAULT_JUKEBOX 0xaee77884u

// The mode's value text, which the arrows follow.
#define OBJ_MODE_VALUE 0x2932dfcau

// tScrollingMenuList's arrows and clip.
#define OBJ_SCROLL_UP   0xedf2e4eeu
#define OBJ_SCROLL_DOWN 0x20d73d01u
#define OBJ_SCROLL_CLIP 0xc67cfb4au

#define OBJ_LEFT_ARROW  0xd1cda594u
#define OBJ_RIGHT_ARROW 0x9345e4a7u

// "Mono", "Stereo", "Dolby Pro Logic II", by sound::GetAudioMode. The 3DS
// has no Pro Logic decoder on the other end; mode 2 plays as the console's
// own Surround (bsnd_set_mode), and says so, in the port's string.
#define LANG_MONO     110009
#define LANG_STEREO   110008
#define LANG_PROLOGIC PORTLANG_SURROUND
// "Set volume from mute to maximum." .. "Restore factory Jukebox
// settings.", by row.
#define LANG_BLURB    150500

// The save prompt: memcard.c's popup, titled "Save" (150000), with its Yes
// and No (150103, 150104), as Player Names'.
#define LANG_SAVE 0x249f0
#define LANG_YES  0x24a57
#define LANG_NO   0x24a58

#define AUTOSAVE_SCREEN "Autosave"
#define JUKEBOX_NAME    "JukeBox Music"

enum { ANSWER_STAY, ANSWER_DISCARD, ANSWER_SAVE };

// The menus' noises (BSND_*): what HandleEvent writes into data->noise.
#define NOISE_NONE   0
#define NOISE_LEFT   1
#define NOISE_RIGHT  2
#define NOISE_UP     3
#define NOISE_DOWN   4
#define NOISE_SELECT 5
#define NOISE_CANCEL 6

// RealTimer's units a second.
#define TICKS_PER_SECOND 4000.0f

typedef union {
    uint8_t b[JB_AO_SIZE];
    float   f[JB_AO_SIZE / 4];
} AudioData;

static AudioOptionsHooks sHooks;

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

static int32_t rd32(const uint8_t* p)
{
    int32_t v;
    memcpy(&v, p, 4);
    return v;
}

static void wr32(uint8_t* p, int32_t v) { memcpy(p, &v, 4); }

static int8_t* tune(AudioData* d, int i)
{
    return (int8_t*)&d->b[JB_AO_TUNE_LIST + 4 * i];
}

// 0x001ef120 and SetAudioMode after it: the options into bSound.
static void applyAudio(const uint8_t* ao)
{
    int mode;

    if (!sHooks.jukebox) return;
    mode = jb_audio_apply(sHooks.jukebox, ao);
    if (sHooks.sound) sound_set_audio_mode(sHooks.sound, mode);
}

static void showScreen(BGameFlow* gf, uint32_t screen, int visible)
{
    if (screen && gf->hooks.setScreenVisible)
        gf->hooks.setScreenVisible(gf->hooks.user, screen, visible);
}

// ---------------------------------------------------------- FlailerSlider
//
// 92 bytes in retail, in a bTList the screen owns. The knob's place along
// the track is the volume scaled so the game's own volume sits at 0.7 of
// the way (sound 0x001afa18's 0.7 over 0x001afa28's default for the
// category), and eases there over a quarter second.

typedef struct {
    uint32_t screen;   // +8
    uint32_t track;    // +12
    uint32_t knob;     // +16
    uint32_t item;     // +20
    uint32_t cat;      // +24
    float    min;      // +28
    float    max;      // +32
    float*   value;    // +36, into the screen's copy of the options
    float    scale;    // +40
    BSpline  pos;      // +44
} Slider;

// 0x001afa28's table, each category's volume as the game ships it.
static const float kDefaultVolume[7] = {
    0.38f, 0.55f, 0.33f, 0.31f, 0.85f, 0.45f, 0.75f,
};

// FlailerSlider::FlailerSlider (0x0016dc20).
static void sliderInit(Slider* sl, uint32_t screen, uint32_t item,
                       uint32_t track, uint32_t knob, uint32_t cat,
                       float* value, float min, float max)
{
    memset(sl, 0, sizeof *sl);
    sl->screen = screen;
    sl->item   = item;
    sl->track  = track;
    sl->knob   = knob;
    sl->cat    = cat;
    sl->value  = value;
    sl->min    = min;
    sl->max    = max;
    sl->scale  = 0.7f / kDefaultVolume[cat < 7 ? cat : 0];
    sl->pos.duration         = 0.25f;
    sl->pos.arrivalThreshold = 1.0f;
    // SetValDesired then SetVal: the knob starts where it belongs.
    sl->pos.valDesired = *value * sl->scale;
    sl->pos.val        = sl->pos.valDesired;
    sl->pos.state      = 0;
    sl->pos.dval       = sl->pos.dvalDesired;
}

// StepValue (0x0016dd38): the value moved by `delta` within the track,
// bSound's category set to it if `setVolume`, and the menu's adjust sound
// at the knob's new place when it moved.
static void sliderStep(Slider* sl, float delta, int setVolume)
{
    float pos = (*sl->value + delta) * sl->scale;
    float v;
    int   changed;

    if (sl->max < pos) pos = sl->max;
    if (pos < sl->min) pos = sl->min;
    v       = pos / sl->scale;
    changed = v != *sl->value;
    *sl->value = v;
    if (sHooks.jukebox) {
        if (setVolume) jb_set_category_volume(sHooks.jukebox, sl->cat, v);
        jb_save_volumes_for_speech(sHooks.jukebox);
    }
    if (changed) {
        if (sHooks.sound)
            sound_play_common_region_sample(sHooks.sound, "MenuAdjustVolume",
                                            pos);
        say("slider %u: %.3f", (unsigned)sl->cat, (double)v);
    }
    sl->pos.valDesired = pos;
    if (pos != sl->pos.val) sl->pos.state = 2;
}

// Animate (0x0016de30): the ease stepped, and the knob put that far along
// the track.
static void sliderAnimate(BGameFlow* gf, Slider* sl)
{
    int32_t l = 0, t = 0, r = 0, b = 0;

    bspline_seek(&sl->pos, gf->realElapsed);
    flailer_get_bounding_box(sl->screen, sl->track, &l, &t, &r, &b);
    flailer_set_top_left_x(sl->screen, sl->knob,
                           (int32_t)((float)l + sl->pos.val * (float)(r - l)));
}

// ------------------------------------------------------ AudioOptionsScreen

#define NUM_SLIDERS 7

// 792 bytes in retail (bMalloc'd on SCREEN_ACTIVATE, its pointer at
// gp-16888, which every OptionsScreenBase page shares).
typedef struct {
    BScreenInstance inst;              // OptionsScreenBase, +0 .. +100
    AudioData       data;              // +100, DataAudioOptionsScreen
    Slider          slider[NUM_SLIDERS];   // +276, the bTList
    BScrollList     list;              // +284
    BArrows         arrows;            // +340
    int             asking;            // the save prompt is up
} AudioScreen;

static AudioScreen sAudio;

// The port's: Fred's options as Options left them, kept across JukeBox
// and back, so B can ask whether to keep what changed.
static uint8_t sEntry[JB_AO_SIZE];
static int     sEntryHeld;

// The sliders, by row: the track, the knob, the bSound category and where
// the value is.
static const struct {
    uint32_t track, knob, cat, offset;
} kSliders[NUM_SLIDERS] = {
    { 0xa29f7a16u, 0xc866642bu, 5, JB_AO_MENU_MUSIC   },
    { 0xa29f7a17u, 0xc866686cu, 4, JB_AO_RACING_MUSIC },
    { 0xa29f7a18u, 0xc8666cadu, 0, JB_AO_SFX          },
    { 0xa29f7a19u, 0xc86670eeu, 1, JB_AO_SFX_TIRES    },
    { 0xa29f7a1au, 0xc866752fu, 2, JB_AO_SFX_ENGINE   },
    { 0xa29f7a1bu, 0xc8667970u, 3, JB_AO_SFX_MENU     },
    { 0xa29f7a1cu, 0xc8667db1u, 6, JB_AO_SPEECH       },
};

// 0x002b9c30: what scrolls, every row and every slider's two parts.
static const uint32_t kScrollObjects[26] = {
    0x52e039f3u, 0x52e039f4u, 0x52e039f5u, 0x52e039f6u, 0x52e039f7u,
    0x52e039f8u, 0x52e039f9u, 0x52e039fau, 0x52e039fbu,
    ITEM_DEFAULT_VOLUMES, ITEM_DEFAULT_JUKEBOX,
    0xa29f7a16u, 0xc866642bu, 0xa29f7a17u, 0xc866686cu,
    0xa29f7a18u, 0xc8666cadu, 0xa29f7a19u, 0xc86670eeu,
    0xa29f7a1au, 0xc866752fu, 0xa29f7a1bu, 0xc8667970u,
    0xa29f7a1cu, 0xc8667db1u,
    OBJ_MODE_VALUE,
};

void audioopts_init(const AudioOptionsHooks* hooks)
{
    memset(&sHooks, 0, sizeof sHooks);
    if (hooks) sHooks = *hooks;
    memset(&sAudio, 0, sizeof sAudio);
    sEntryHeld = 0;
}

// The seven volumes from bSound, in the constructor's order.
static void readVolumes(AudioData* d)
{
    for (int i = 0; i < NUM_SLIDERS; i++)
        d->f[kSliders[i].offset / 4] = sHooks.jukebox
            ? jb_get_category_volume(sHooks.jukebox, kSliders[i].cat) : 0.0f;
}

static int audioMode(void)
{
    return sHooks.sound ? sound_get_audio_mode(sHooks.sound) : 1;
}

// RedrawAudioMode (0x001efb38).
static void redrawAudioMode(AudioScreen* a, int mode)
{
    uint32_t id = mode == 0 ? LANG_MONO
                : mode == 1 ? LANG_STEREO
                : mode == 2 ? LANG_PROLOGIC : 0;
    flailer_set_language_id(a->inst.screen, OBJ_MODE_VALUE, id);
}

// The constructor (0x001ef3c8).
static void audioConstruct(AudioScreen* a, uint32_t screen)
{
    BSetup* s = bsetup_instance();

    memset(a, 0, sizeof *a);
    bscr_optbase_construct(&a->inst, screen);
    if (s) {
        bscroll_init(s, &a->list, screen, BSCR_ITEM_MENUITEM(1),
                     BSCR_ITEM_MENUITEM(7), OBJ_SCROLL_UP, OBJ_SCROLL_DOWN,
                     OBJ_SCROLL_CLIP);
        barrows_init(s, &a->arrows, screen, OBJ_LEFT_ARROW, OBJ_RIGHT_ARROW);
    }
    memcpy(a->data.b, Fred.AudioOptionsScreenData, JB_AO_SIZE);
    readVolumes(&a->data);
    for (int i = 0; i < NUM_SLIDERS; i++)
        sliderInit(&a->slider[i], screen, BSCR_ITEM_MENUITEM(1 + i),
                   kSliders[i].track, kSliders[i].knob, kSliders[i].cat,
                   &a->data.f[kSliders[i].offset / 4], 0.0f, 1.0f);
    redrawAudioMode(a, audioMode());
    if (s) {
        bscroll_add_objects(s, &a->list, kScrollObjects, 26);
        a->list.numMenuItemsToScroll = 11;
    }
    if (!sEntryHeld) {
        memcpy(sEntry, Fred.AudioOptionsScreenData, JB_AO_SIZE);
        sEntryHeld = 1;
    }
    say("audio options: in, mode %d", audioMode());
}

static void audioDestruct(AudioScreen* a)
{
    BSetup* s = bsetup_instance();

    if (!a->inst.live) return;
    if (s) bscroll_release(s, &a->list);
    bscr_optbase_destruct(&a->inst);
    memset(a, 0, sizeof *a);
}

// FindSlider (0x001efa68).
static Slider* findSlider(AudioScreen* a, uint32_t item)
{
    for (int i = 0; i < NUM_SLIDERS; i++)
        if (a->slider[i].item == item) return &a->slider[i];
    return NULL;
}

// ChangeAudioMode (0x001efaa0): Mono, Stereo, Dolby Pro Logic II round.
static void changeAudioMode(AudioScreen* a, BScreenMessage msg)
{
    int mode = (audioMode() + (msg == BMSG_MENUITEM_PAD_LEFT ? -1 : 1)) % 3;
    int16_t m16;

    if (mode < 0) mode = 2;
    if (sHooks.sound) sound_set_audio_mode(sHooks.sound, mode);
    redrawAudioMode(a, mode);
    m16 = (int16_t)audioMode();
    memcpy(&a->data.b[JB_AO_AUDIO_MODE], &m16, 2);
    say("audio mode %d", (int)m16);
}

// ---------------------------------------------------------- the prompt
//
// The port's (the user's word, 2026-10-13): B with Fred's options not as
// they were when the player came in from Options asks "Save your changes
// to the SD Card?" in the page's place, as Player Names does. Yes saves on
// the Autosave screen, in this page's place, so its end moves back to
// Options; No puts the options back as they were and applies them, then
// moves back; B on the popup stays.

static void releaseEntry(void) { sEntryHeld = 0; }

static void askToSave(BGameFlow* gf, AudioScreen* a)
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
    say("audio back: changed, asking to save");
    if (bpopup_summon(gf, &cfg) < 0) {
        say("no popup free");
        return;
    }
    a->asking = 1;
    showScreen(gf, a->inst.screen, 0);
}

static void answered(BGameFlow* gf, AudioScreen* a, int answer)
{
    if (!a->asking) return;
    a->asking = 0;
    showScreen(gf, a->inst.screen, 1);
    if (answer == ANSWER_STAY) {
        say("audio save: stay");
        return;
    }
    releaseEntry();
    if (answer == ANSWER_SAVE) {
        say("audio save: yes");
        bgf_change_to_screen(gf, AUTOSAVE_SCREEN, 0);
        return;
    }
    memcpy(Fred.AudioOptionsScreenData, sEntry, JB_AO_SIZE);
    applyAudio(Fred.AudioOptionsScreenData);
    say("audio save: no, options put back");
    bgf_move_back_screen(gf, 1);
}

// B: retail's, the page's copy into Fred and applied when it differs, then
// the port's question in place of the autosave.
static void audioBack(BGameFlow* gf, AudioScreen* a, BScreenCallbackData* data)
{
    if (memcmp(a->data.b, Fred.AudioOptionsScreenData, JB_AO_SIZE) != 0) {
        memcpy(Fred.AudioOptionsScreenData, a->data.b, JB_AO_SIZE);
        applyAudio(Fred.AudioOptionsScreenData);
    }
    if (!sEntryHeld
        || memcmp(Fred.AudioOptionsScreenData, sEntry, JB_AO_SIZE) == 0) {
        say("audio back: unchanged");
        releaseEntry();
        return;
    }
    // The pop waits for the answer.
    data->param = 0;
    askToSave(gf, a);
}

// HandleEvent (0x001efb80): the scrolling list and the arrows see every
// message first.
static void audioEvent(BGameFlow* gf, AudioScreen* a, BScreenMessage msg,
                       BScreenCallbackData* data)
{
    BSetup*  s    = bsetup_instance();
    uint32_t item = data ? data->itemHash : 0;
    Slider*  sl;

    if (s) {
        bscroll_event(s, &a->list, msg, data);
        barrows_event(s, &a->arrows, msg);
    }
    switch (msg) {
    case BMSG_MENUITEM_SELECT:
        if (item == ITEM_JUKEBOX) {
            memcpy(Fred.AudioOptionsScreenData, a->data.b, JB_AO_SIZE);
            applyAudio(Fred.AudioOptionsScreenData);
            say("audio: to the jukebox");
            bscr_optbase_exit(&a->inst, JUKEBOX_NAME);
        } else if (item == ITEM_DEFAULT_VOLUMES) {
            if (sHooks.jukebox) jb_default_category_volumes(sHooks.jukebox);
            readVolumes(&a->data);
            for (int i = 0; i < NUM_SLIDERS; i++)
                sliderStep(&a->slider[i], 0.0f, 0);
            say("audio: default volumes");
        } else if (item == ITEM_DEFAULT_JUKEBOX) {
            if (sHooks.jukebox)
                jb_audio_default_jukebox(sHooks.jukebox, a->data.b);
            say("audio: default jukebox");
        } else if (data) {
            data->noise = NOISE_NONE;
        }
        return;
    case BMSG_MENUITEM_HIGHLIGHT: {
        int id = 0;
        if (item >= BSCR_ITEM_MENUITEM(1) && item <= BSCR_ITEM_MENUITEM(9))
            id = LANG_BLURB + (int)(item - BSCR_ITEM_MENUITEM(1));
        else if (item == ITEM_DEFAULT_VOLUMES) id = LANG_BLURB + 9;
        else if (item == ITEM_DEFAULT_JUKEBOX) id = LANG_BLURB + 10;
        banim_blurb_new_text_id(bscr_anim(), &a->inst.blurbAnim, id);
        bscr_optbase_highlight(&a->inst, data, bscroll_current_mask(&a->list));
        if (s) barrows_set(s, &a->arrows,
                           item == ITEM_MODE ? OBJ_MODE_VALUE : 0);
        return;
    }
    case BMSG_MENUITEM_PAD_LEFT:
    case BMSG_MENUITEM_PAD_RIGHT:
        if (item == ITEM_MODE) {
            changeAudioMode(a, msg);
            if (data) data->noise = msg == BMSG_MENUITEM_PAD_LEFT
                                  ? NOISE_LEFT : NOISE_RIGHT;
        } else if (item != ITEM_JUKEBOX && (sl = findSlider(a, item))) {
            sliderStep(sl, msg == BMSG_MENUITEM_PAD_LEFT ? -0.05f : 0.05f,
                       1);
        }
        return;
    case BMSG_MENUITEM_PAD_UP:
        // The list stops at its ends.
        if (item == BSCR_ITEM_MENUITEM(1) && data) data->param = 1;
        return;
    case BMSG_MENUITEM_PAD_DOWN:
        if (item == ITEM_DEFAULT_JUKEBOX && data) data->param = 1;
        return;
    case BMSG_SCREEN_START_BUTTON:
        if (data) data->noise = NOISE_NONE;
        return;
    case BMSG_SCREEN_BACK_BUTTON:
        if (data) audioBack(gf, a, data);
        return;
    case BMSG_POPUP_DISMISS:
        answered(gf, a, data ? data->param : ANSWER_STAY);
        return;
    case BMSG_SCREEN_TICK:
        // The blurb is the base's, which its tick animates.
        for (int i = 0; i < NUM_SLIDERS; i++)
            sliderAnimate(gf, &a->slider[i]);
        return;
    default:
        return;
    }
}

void audioopts_callback(BGameFlow* gf, BScreenMessage msg,
                        BScreenCallbackData* data)
{
    AudioScreen* a = &sAudio;

    if (msg == BMSG_SCREEN_ACTIVATE) {
        audioConstruct(a, data ? data->itemHash : AUDIOOPTS_SCREEN);
        return;
    }
    if (!a->inst.live) return;
    if (msg == BMSG_SCREEN_UNACTIVATE) {
        audioDestruct(a);
        return;
    }
    if (bscr_optbase_first_crack(&a->inst, msg, data)) return;
    audioEvent(gf, a, msg, data);
}

// ------------------------------------------------------ JukeBoxMusicScreen

#define ROWS 5

// The list's five rows: each tune's name, artist and when it plays, and
// the selected row's two bars (0x0031ae00 .. 0x0031ae60).
static const uint32_t kRowName[ROWS] = {
    0x64a819c7u, 0x64a819c8u, 0x64a819c9u, 0x64a819cau, 0x64a819cbu,
};
static const uint32_t kRowArtist[ROWS] = {
    0x03b57047u, 0x03b57048u, 0x03b57049u, 0x03b5704au, 0x03b5704bu,
};
static const uint32_t kRowStatus[ROWS] = {
    0x89fb635fu, 0x8c508c00u, 0x8ea5b4a1u, 0x90fadd42u, 0x935005e3u,
};
static const uint32_t kRowBarA[ROWS] = {
    0x0b825845u, 0x0b825846u, 0x0b825847u, 0x0b825848u, 0x0b825849u,
};
static const uint32_t kRowBarB[ROWS] = {
    0xfc0279b8u, 0xfc0279b9u, 0xfc0279bau, 0xfc0279bbu, 0xfc0279bcu,
};

// The favourite's line, "name (artist)".
#define OBJ_FAVOURITE 0x0b41999au

// 0x002b9d30, by AudioPlaylistOnOff's Status: "Off", "World Racing",
// "Hot Pursuit", "Menu", "Menu/Racing", "Always".
static const uint32_t kStatusIds[6] = {
    110041, 110042, 110045, 110043, 110052, 110044,
};

// The text colours: the frontend's own (gp-21296), the highlight's
// (gp-21296 .. gp-21288 with alpha) and the gray of a genre turned off
// (gp-21284 ..).
#define COLOR_NORMAL    0x00808080u
#define COLOR_HIGHLIGHT 0x80004080u
#define COLOR_OFF       0x80181818u

// 576 bytes in retail.
typedef struct {
    BScreenInstance inst;          // OptionsScreenBase
    uint32_t        timer;         // +100, RealTimer at the last move
    int             pending;       // +104, play the selection soon
    int             inPlaylist;    // +108
    AudioData       data;          // +112
    int32_t         top;           // +288, the first row's place
    JBGenreMgr      genres;        // +292
} JukeBoxScreen;

static JukeBoxScreen sJuke;

static int32_t jsel(JukeBoxScreen* j) { return rd32(&j->data.b[JB_AO_SELECTED_SONG]); }
static void    setJsel(JukeBoxScreen* j, int32_t v) { wr32(&j->data.b[JB_AO_SELECTED_SONG], v); }
static int     jcur(JukeBoxScreen* j) { return (int8_t)j->data.b[JB_AO_CURR_GENRE]; }
static uint8_t jmask(JukeBoxScreen* j) { return j->data.b[JB_AO_GENRE_MASK]; }

static JBGenre* curGenre(JukeBoxScreen* j)
{
    int cur = jcur(j);
    if (cur < 0 || cur >= j->genres.numGenres) return NULL;
    return &j->genres.genre[cur];
}

static int genreOn(JukeBoxScreen* j, int genre)
{
    return genre >= 0 && genre < 8 && (jmask(j) & (1u << genre)) != 0;
}

static const char* trackText(int cat, int t, int field)
{
    const char* s = sHooks.jukebox
        ? jb_track_string(sHooks.jukebox, cat, t, field) : NULL;
    return s ? s : "";
}

// ShowPlaylist (0x001f0478).
static void showPlaylist(JukeBoxScreen* j)
{
    uint32_t screen = j->inst.screen;
    JBGenre* g      = curGenre(j);
    int      count  = g ? g->numTracks : 0;
    int32_t  sel    = jsel(j);
    int      rows, r;
    int8_t*  fav;
    int32_t  favIdx;

    // The window follows the selection.
    while (sel >= j->top + ROWS && j->top + ROWS < count) j->top++;
    while (sel < j->top && j->top > 0) j->top--;
    rows = count < ROWS + 1 ? count : ROWS;
    for (r = 0; r < rows; r++) {
        int32_t  s   = j->top + r;
        int      idx = g->tracks[s];
        int8_t*  e   = tune(&j->data, idx);
        uint32_t color = COLOR_NORMAL;
        int      status;

        flailer_printf(screen, kRowArtist[r], "%s",
                       trackText(e[0], e[1], JB_TRACK_ARTIST));
        flailer_printf(screen, kRowName[r], "%s",
                       trackText(e[0], e[1], JB_TRACK_NAME));
        status = genreOn(j, jcur(j)) ? e[2] : 0;
        flailer_set_language_id(screen, kRowStatus[r],
                                status >= 0 && status < 6
                                ? kStatusIds[status] : 0);
        if (j->inPlaylist && sel == s) {
            color = COLOR_HIGHLIGHT;
            flailer_set_visibility(screen, kRowBarA[r], 1);
            flailer_set_visibility(screen, kRowBarB[r], 1);
        } else {
            flailer_set_visibility(screen, kRowBarA[r], 0);
            flailer_set_visibility(screen, kRowBarB[r], 0);
            if (!genreOn(j, jcur(j))) color = COLOR_OFF;
        }
        flailer_set_text_color(screen, kRowName[r], color);
        flailer_set_text_color(screen, kRowArtist[r], color);
        flailer_set_text_color(screen, kRowStatus[r], color);
        flailer_set_visibility(screen, kRowName[r], 1);
        flailer_set_visibility(screen, kRowArtist[r], 1);
        flailer_set_visibility(screen, kRowStatus[r], 1);
    }
    for (; r < ROWS; r++) {
        flailer_set_visibility(screen, kRowName[r], 0);
        flailer_set_visibility(screen, kRowArtist[r], 0);
        flailer_set_visibility(screen, kRowStatus[r], 0);
        flailer_set_visibility(screen, kRowBarA[r], 0);
        flailer_set_visibility(screen, kRowBarB[r], 0);
    }
    flailer_set_visibility(screen, OBJ_SCROLL_UP,
                           j->inPlaylist && j->top != 0);
    flailer_set_visibility(screen, OBJ_SCROLL_DOWN,
                           j->inPlaylist && count >= ROWS
                           && j->top != count - ROWS);
    favIdx = rd32(&j->data.b[JB_AO_FE_FAVOURITE]);
    if (favIdx >= 0 && favIdx < JB_AO_MAX_TUNES) {
        fav = tune(&j->data, favIdx);
        flailer_printf(screen, OBJ_FAVOURITE, "%s (%s)",
                       trackText(fav[0], fav[1], JB_TRACK_NAME),
                       trackText(fav[0], fav[1], JB_TRACK_ARTIST));
    }
    flailer_printf(screen, BSCR_ITEM_MENUITEM(1), "%s", g ? g->name : "");
    flailer_set_text_color(screen, BSCR_ITEM_MENUITEM(1),
                           j->inPlaylist ? COLOR_NORMAL : COLOR_HIGHLIGHT);
    flailer_set_visibility(screen, OBJ_LEFT_ARROW, !j->inPlaylist);
    flailer_set_visibility(screen, OBJ_RIGHT_ARROW, !j->inPlaylist);
}

// PlayCurrentSelectedSong (0x001f0cc8).
static void playSelected(JukeBoxScreen* j)
{
    JBGenre* g   = curGenre(j);
    int32_t  sel = jsel(j);
    int8_t*  e;

    if (!g || sel < 0 || sel >= g->numTracks || !sHooks.jukebox) return;
    e = tune(&j->data, g->tracks[sel]);
    jb_start_tune(&sHooks.jukebox->jukebox, (uint32_t)e[0], (uint32_t)e[1], 0);
    say("jukebox: playing %d/%d \"%s\"", e[0], e[1],
        trackText(e[0], e[1], JB_TRACK_NAME));
}

// The constructor (0x001f02d8).
static void jukeConstruct(BGameFlow* gf, JukeBoxScreen* j, uint32_t screen)
{
    (void)gf;
    memset(j, 0, sizeof *j);
    bscr_optbase_construct(&j->inst, screen);
    memcpy(j->data.b, Fred.AudioOptionsScreenData, JB_AO_SIZE);
    j->inPlaylist = 0;
    j->top        = 0;
    setJsel(j, 0);
    if (sHooks.jukebox) jb_genre_populate(sHooks.jukebox, &j->genres, j->data.b);
    if (jcur(j) >= j->genres.numGenres) j->data.b[JB_AO_CURR_GENRE] = 0;
    showPlaylist(j);
    say("jukebox: in, %d genres, genre %d, mask 0x%02x",
        (int)j->genres.numGenres, jcur(j), jmask(j));
}

static void jukeDestruct(JukeBoxScreen* j)
{
    if (!j->inst.live) return;
    bscr_optbase_destruct(&j->inst);
    memset(j, 0, sizeof *j);
}

// B: retail's, the page's copy into Fred, the selection rebuilt, and the
// favourite (or the list) started. The question waits for Audio Options.
static void jukeBack(JukeBoxScreen* j)
{
    int32_t favIdx = rd32(&j->data.b[JB_AO_FE_FAVOURITE]);
    JBPlayer* p;

    memcpy(Fred.AudioOptionsScreenData, j->data.b, JB_AO_SIZE);
    if (!sHooks.jukebox) return;
    p = &sHooks.jukebox->jukebox;
    jb_music_set_selection(sHooks.jukebox, Fred.AudioOptionsScreenData, 5);
    if (favIdx >= 0 && favIdx < JB_AO_MAX_TUNES) {
        int8_t* e = tune(&j->data, favIdx);
        if (genreOn(j, e[3]) && e[2] != 0) {
            jb_start_tune(p, (uint32_t)e[0], (uint32_t)e[1], 1);
            say("jukebox back: favourite %d/%d", e[0], e[1]);
            return;
        }
    }
    jb_start(p, 1);
    say("jukebox back: the list");
}

// HandleEvent (0x001f0d10).
static void jukeEvent(BGameFlow* gf, JukeBoxScreen* j, BScreenMessage msg,
                      BScreenCallbackData* data)
{
    JBGenre* g = curGenre(j);

    switch (msg) {
    case BMSG_MENUITEM_SELECT:
    case BMSG_MENUITEM_SQUARE:
    case BMSG_SCREEN_START_BUTTON:
        if (data) data->noise = NOISE_NONE;
        return;
    case BMSG_MENUITEM_PAD_LEFT:
    case BMSG_MENUITEM_PAD_RIGHT: {
        int d = msg == BMSG_MENUITEM_PAD_LEFT ? -1 : 1;
        if (j->inPlaylist) {
            int32_t sel = jsel(j);
            int8_t* e;
            int     status;
            if (!g || sel < 0 || sel >= g->numTracks) return;
            e      = tune(&j->data, g->tracks[sel]);
            status = e[2] + d;
            if (status < 0) status = 5;
            if (status > 5) status = 0;
            e[2] = (int8_t)status;
            say("jukebox: tune %d status %d", g->tracks[sel], status);
        } else {
            int n   = j->genres.numGenres;
            int cur = jcur(j) + d;
            if (n <= 0) cur = 0;
            else if (cur < 0) cur = n - 1;
            else if (cur >= n) cur = 0;
            j->data.b[JB_AO_CURR_GENRE] = (uint8_t)(int8_t)cur;
            setJsel(j, 0);
            say("jukebox: genre %d", cur);
        }
        if (data) data->noise = d < 0 ? NOISE_LEFT : NOISE_RIGHT;
        showPlaylist(j);
        return;
    }
    case BMSG_MENUITEM_PAD_UP:
    case BMSG_MENUITEM_PAD_DOWN:
        if (j->inPlaylist) {
            int32_t sel   = jsel(j);
            int     d     = msg == BMSG_MENUITEM_PAD_UP ? -1 : 1;
            int     count = g ? g->numTracks : 0;
            int32_t n;
            if (msg == BMSG_MENUITEM_PAD_UP && sel == 0 && j->top == 0) {
                j->inPlaylist = 0;
                if (sHooks.jukebox) jb_stop(&sHooks.jukebox->jukebox);
                showPlaylist(j);
                return;
            }
            n = sel + d;
            if (n < 0 || n >= count) n -= d;
            if (n == sel) {
                if (data) data->noise = NOISE_NONE;
                return;
            }
            setJsel(j, n);
            if (data) data->noise = d < 0 ? NOISE_UP : NOISE_DOWN;
            j->timer   = gf->realTimer;
            j->pending = 1;
            showPlaylist(j);
            return;
        }
        if (msg != BMSG_MENUITEM_PAD_DOWN) {
            if (data) data->noise = NOISE_NONE;
            return;
        }
        if (genreOn(j, jcur(j)) && g && g->numTracks > 0) {
            j->inPlaylist = 1;
            showPlaylist(j);
            j->pending = 1;
            j->timer   = gf->realTimer;
            return;
        }
        if (data) data->noise = NOISE_CANCEL;
        return;
    case BMSG_SCREEN_L1: {
        int     cur = jcur(j);
        uint8_t bit = cur >= 0 && cur < 8 ? (uint8_t)(1u << cur) : 0;
        j->data.b[JB_AO_GENRE_MASK] ^= bit;
        if (!genreOn(j, cur)) {
            j->inPlaylist = 0;
            j->top        = 0;
            setJsel(j, 0);
        }
        say("jukebox: genre %d %s", cur, genreOn(j, cur) ? "on" : "off");
        if (data) data->noise = NOISE_SELECT;
        showPlaylist(j);
        return;
    }
    case BMSG_SCREEN_BACK_BUTTON:
        jukeBack(j);
        return;
    case BMSG_SCREEN_TICK: {
        float since = (float)(int32_t)(gf->realTimer - j->timer)
                    / TICKS_PER_SECOND;
        if (since > 0.5f && j->pending) {
            j->pending = 0;
            playSelected(j);
        }
        since = (float)(int32_t)(gf->realTimer - j->timer) / TICKS_PER_SECOND;
        // Half a minute after the last move, the selection plays again
        // whenever nothing is.
        if (since > 30.0f && sHooks.jukebox) {
            JBPlayer* p = &sHooks.jukebox->jukebox;
            jb_update(p);
            if (p->statePlay != JB_PLAYING && !jb_is_fading(p))
                playSelected(j);
        }
        return;
    }
    default:
        return;
    }
}

void jukeboxscreen_callback(BGameFlow* gf, BScreenMessage msg,
                            BScreenCallbackData* data)
{
    JukeBoxScreen* j = &sJuke;

    if (msg == BMSG_SCREEN_ACTIVATE) {
        jukeConstruct(gf, j, data ? data->itemHash : JUKEBOX_SCREEN);
        return;
    }
    if (!j->inst.live) return;
    if (msg == BMSG_SCREEN_UNACTIVATE) {
        jukeDestruct(j);
        return;
    }
    if (bscr_optbase_first_crack(&j->inst, msg, data)) return;
    jukeEvent(gf, j, msg, data);
}
