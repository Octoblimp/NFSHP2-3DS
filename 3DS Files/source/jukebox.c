// The jukebox: cJukeboxPlayer, cJukeboxCartridge, sound::jukebox and the
// playlist half of DataAudioOptionsScreen, from the retail image. See
// jukebox.h; tools/jukebox_check.py holds it to retail.
//
// Retail's asserts end the game (bAssertFail breaks). Here the host hears of
// one and the function stops where retail would have: the checker's
// harness never comes back from it, the 3DS logs it and carries on.
#include "jukebox.h"

#include <stdlib.h>
#include <string.h>

#include "bmath.h"

static void jb_fail(const JBPlayer* p, int line)
{
    if (p->host && p->host->assert_fail) {
        p->host->assert_fail(p->host->ctx, line);
    }
}

#define H (p->host)

// ------------------------------------------------------------- cartridge

// GetTuneName (0x0027c8e0) and the three like it: the category's nth tune.
static JBTune* jb_tune_at(JBPlayer* p, uint32_t cat, uint32_t tune,
                          int line)
{
    if (cat >= p->numCategories) {
        jb_fail(p, line);
        return NULL;
    }
    if (tune >= p->category[cat].numTunes) {
        jb_fail(p, line + 1);
        return NULL;
    }
    uint32_t id = p->category[cat].tuneIndex[tune];
    return id < JB_MAX_TUNES ? &p->tune[id] : NULL;
}

const char* jb_tune_name(JBPlayer* p, uint32_t cat, uint32_t tune)
{
    JBTune* t = jb_tune_at(p, cat, tune, 45);
    return t ? t->name : "";
}

// Past the tune's sync data, if it has any, rounded up to the next 2 KB
// sector the way the disc laid it out.
uint32_t jb_tune_offset(JBPlayer* p, uint32_t cat, uint32_t tune)
{
    JBTune* t = jb_tune_at(p, cat, tune, 55);
    if (!t) {
        return 0;
    }
    uint32_t sync = t->syncSize ? ((t->syncSize >> 11) << 11) + 2048 : 0;
    return t->offset + sync;
}

uint32_t jb_tune_size(JBPlayer* p, uint32_t cat, uint32_t tune)
{
    JBTune* t = jb_tune_at(p, cat, tune, 78);
    return t ? t->size : 0;
}

uint32_t jb_tune_id(JBPlayer* p, uint32_t cat, uint32_t tune)
{
    JBTune* t = jb_tune_at(p, cat, tune, 98);
    return t ? t->id : 0;
}

static void jb_copy_name(char* dst, const char* src)
{
    size_t n = strlen(src);
    if (n >= JB_NAME_MAX) {
        n = JB_NAME_MAX - 1;
    }
    memcpy(dst, src, n);
    dst[n] = 0;
}

// 0x0027d008. No bound on the count: the cartridge never has 16.
int32_t jb_add_category(JBPlayer* p, const char* name)
{
    uint32_t i;
    for (i = 0; i < p->numCategories; i++) {
        if (strcmp(name, p->category[i].name) == 0) {
            return (int32_t)i;
        }
    }
    if (i >= JB_MAX_CATEGORIES) {
        return (int32_t)JB_MAX_CATEGORIES - 1;
    }
    JBCategory* c = &p->category[i];
    jb_copy_name(c->name, name);
    c->numTunes = 0;
    c->use = 1;
    p->numCategories++;
    return (int32_t)i;
}

// 0x0027d220. A name already on the cartridge is the same tune again, its
// numbers rewritten and itself listed a second time in the category.
int32_t jb_add_tune(JBPlayer* p, const char* cat, const char* name,
                    uint32_t offset, uint32_t size, uint32_t sync,
                    uint32_t id)
{
    uint32_t i;
    for (i = 0; i < p->numTunes; i++) {
        if (strcmp(name, p->tune[i].name) == 0) {
            break;
        }
    }
    if (i == p->numTunes) {
        if (i >= JB_MAX_TUNES) {
            return -1;
        }
        jb_copy_name(p->tune[i].name, name);
        p->numTunes++;
    }
    JBTune* t = &p->tune[i];
    t->offset = offset;
    t->size = size;
    t->syncSize = sync;
    t->id = id;
    t->use = 1;
    JBCategory* c = &p->category[jb_add_category(p, cat)];
    if (c->numTunes < JB_MAX_TUNES) {
        c->tuneIndex[c->numTunes++] = i;
    }
    c->lastTunePlayed = 0;
    return (int32_t)i;
}

// ---------------------------------------------------------------- player

void jb_player_init(JBPlayer* p, const JBHost* host)
{
    memset(p, 0, sizeof *p);
    p->on = 1;
    p->soundCategory = 0xFFFFFFFFu;
    p->volume = 1.0f;
    p->host = host;
}

bool jb_is_cartridge_loaded(const JBPlayer* p)
{
    return p->fileOpen;
}

static uint32_t rd32(const uint8_t* b)
{
    return (uint32_t)b[0] | (uint32_t)b[1] << 8 | (uint32_t)b[2] << 16 |
           (uint32_t)b[3] << 24;
}

void jb_load_cartridge(JBPlayer* p, const char* path, bool arg)
{
    (void)arg;
    if (!H->sound_up(H->ctx)) {           // bSound::GetStatus() != 1
        return;
    }
    if (jb_is_cartridge_loaded(p)) {
        jb_fail(p, 301);
        return;
    }
    p->file = H->open(H->ctx, path);
    if (!p->file) {
        jb_fail(p, 306);
        return;
    }
    p->fileOpen = true;
    size_t n = strlen(path);
    if (n >= JB_PATH_MAX) {
        n = JB_PATH_MAX - 1;
    }
    memcpy(p->path, path, n);
    p->path[n] = 0;

    uint8_t head[JB_HEADER_SIZE];
    memset(head, 0, sizeof head);
    H->read(H->ctx, p->file, head, JB_HEADER_SIZE);
    for (unsigned i = 0; i < JB_HEADER_SIZE / 4; i++) {
        p->header[i] = rd32(head + 4 * i);
    }

    uint32_t size = p->header[4];
    uint8_t* index = size ? (uint8_t*)calloc(1, size) : NULL;
    if (size && !index) {
        jb_fail(p, 319);
        return;
    }
    if (size) {
        H->read(H->ctx, p->file, index, size);
    }
    // Each category: its tune count and name in 64 bytes, then the tunes'
    // 96 each -- offset, size, sync size, name. Nothing past the index is
    // looked at; a short one reads as zeros.
    uint32_t at = 0;
    for (uint32_t c = 0; c < p->header[3]; c++) {
        if (at + 64 > size) {
            break;
        }
        const uint8_t* cat = index + at;
        at += 64;
        char cname[61];
        memcpy(cname, cat + 4, 60);
        cname[60] = 0;
        uint32_t tunes = rd32(cat);
        for (uint32_t t = 0; t < tunes; t++) {
            if (at + 96 > size) {
                break;
            }
            const uint8_t* tu = index + at;
            at += 96;
            char tname[85];
            memcpy(tname, tu + 12, 84);
            tname[84] = 0;
            jb_add_tune(p, cname, tname, rd32(tu), rd32(tu + 4),
                        rd32(tu + 8), 0);
        }
    }
    free(index);

    if (!p->sample) {
        H->create(H->ctx, p->header[2]);   // GetSampleRate: header+8
        p->sample = true;
    }
}

// 0x0027de40. Each loop zeroes its count on the first pass, so only the
// first category and tune are deleted -- the rest leak, and the counts end
// at 0 either way.
void jb_close(JBPlayer* p)
{
    if (p->fileOpen) {
        H->close(H->ctx, p->file);
        p->file = NULL;
        p->fileOpen = false;
    }
    if (p->sample) {
        H->destroy(H->ctx);
        p->sample = false;
    }
    p->numCategories = 0;
    p->numTunes = 0;
}

void jb_start(JBPlayer* p, uint32_t keep)
{
    p->keepPlaying = keep;
    if (jb_is_cartridge_loaded(p)) {
        jb_advance(p);
    }
}

void jb_start_tune(JBPlayer* p, uint32_t cat, uint32_t tune, uint32_t keep)
{
    p->keepPlaying = keep;
    if (jb_is_cartridge_loaded(p)) {
        if (jb_is_playing(p) || jb_is_fading(p)) {
            jb_stop_playing(p);
        }
        jb_start_playing_tune(p, cat, tune);
    }
}

void jb_stop(JBPlayer* p)
{
    if (jb_is_cartridge_loaded(p)) {
        if (jb_is_playing(p) || jb_is_fading(p)) {
            jb_stop_playing(p);
        }
        p->keepPlaying = 0;
    }
}

void jb_fade_out(JBPlayer* p, uint32_t ms)
{
    if (jb_is_cartridge_loaded(p)) {
        if (jb_is_playing(p) && !jb_is_fading(p)) {
            jb_start_fading(p, ms);
        }
        p->keepPlaying = 0;
    }
}

void jb_fade_out_advance(JBPlayer* p, uint32_t ms)
{
    if (jb_is_cartridge_loaded(p) && jb_is_playing(p) && !jb_is_fading(p)) {
        jb_start_fading(p, ms);
    }
}

void jb_advance(JBPlayer* p)
{
    if (jb_is_cartridge_loaded(p)) {
        if (jb_is_playing(p) || jb_is_fading(p)) {
            jb_stop_playing(p);
        }
        jb_start_playing(p);
    }
}

bool jb_is_done_playing(const JBPlayer* p)
{
    return p->sample && p->statePlay == JB_DONE_PLAYING;
}

bool jb_is_done_fading(const JBPlayer* p)
{
    return p->sample && p->statePlay == JB_DONE_FADING;
}

// 0x0027dff8: what the sample's callback flagged, acted on here.
void jb_update(JBPlayer* p)
{
    if (p->trigger) {
        if (p->statePlay == JB_FADING) {
            H->cleanup(H->ctx);
            p->statePlay = JB_NOTINUSE;
        } else if (!p->pauseBeforePlay) {
            H->play(H->ctx, 1.0f, 0.0f, 0.0f);
        }
        p->trigger = 0;
    }
    if (jb_is_done_fading(p)) {
        H->cleanup(H->ctx);
        p->statePlay = JB_NOTINUSE;
    }
    if (jb_is_done_playing(p)) {
        H->cleanup(H->ctx);
        p->statePlay = JB_NOTINUSE;
        if (p->keepPlaying == 1) {
            jb_start_playing(p);
        }
    }
}

void jb_set_on(JBPlayer* p, uint32_t on)
{
    if (!on && p->on) {
        jb_stop(p);
    }
    p->on = on;
}

void jb_sample_callback(JBPlayer* p, uint32_t event)
{
    switch (event) {
    case JB_EVENT_BUFFERED:
    case JB_EVENT_BUFFERED2:
        p->trigger = 1;
        break;
    case JB_EVENT_FADE_END:
        p->statePlay = JB_DONE_FADING;
        break;
    case JB_EVENT_PLAY_END:
        p->statePlay = JB_DONE_PLAYING;
        break;
    default:
        break;
    }
}

void jb_stop_playing(JBPlayer* p)
{
    if (!p->sample) {
        jb_fail(p, 574);
        return;
    }
    if (p->statePlay == JB_PLAYING || p->statePlay == JB_FADING) {
        H->stop(H->ctx);
        p->statePlay = JB_NOTINUSE;
    }
}

void jb_pause(JBPlayer* p, uint32_t on)
{
    if (!p->sample) {
        jb_fail(p, 592);
        return;
    }
    if (p->statePlay == JB_PLAYING || p->statePlay == JB_FADING) {
        H->pause(H->ctx, on != 0);
    }
}

void jb_start_fading(JBPlayer* p, uint32_t ms)
{
    if (!p->sample) {
        jb_fail(p, 645);
        return;
    }
    if (p->statePlay == JB_PLAYING) {
        H->fade(H->ctx, 0.0f, ms);
        p->statePlay = JB_FADING;
    }
}

// 0x0027e530. The sample reads the tune straight out of the cartridge: 48
// bytes in, past its VAG header, for the index's size.
void jb_start_playing_tune(JBPlayer* p, uint32_t cat, uint32_t tune)
{
    if (!p->sample) {
        jb_fail(p, 662);
        return;
    }
    if (!p->on) {
        return;
    }
    p->curCatNum = cat;
    p->curTuneNum = tune;
    if (!jb_tune_at(p, cat, tune, 45)) {       // the Printf's GetTuneName
        return;
    }
    uint32_t offset = jb_tune_offset(p, cat, tune) + 48;
    uint32_t size = jb_tune_size(p, cat, tune);
    H->load(H->ctx, p->path, offset, size);
    H->set_category(H->ctx, p->soundCategory);
    H->set_scale_volume(H->ctx, p->volume);
    p->statePlay = JB_PLAYING;
}

void jb_start_playing(JBPlayer* p)
{
    if (!p->sample) {
        jb_fail(p, 736);
        return;
    }
    uint32_t cat, tune;
    if (jb_pick_next_tune(p, &cat, &tune)) {
        jb_start_playing_tune(p, cat, tune);
    }
}

void jb_set_volume(JBPlayer* p, float v)
{
    p->volume = v;
    if (p->sample) {
        H->set_scale_volume(H->ctx, v);
    }
}

static JBTune* jb_tune_checked(JBPlayer* p, uint32_t cat, uint32_t tune,
                               int line)
{
    if (cat >= p->numCategories) {
        jb_fail(p, line);
        return NULL;
    }
    if (tune >= p->category[cat].numTunes) {
        jb_fail(p, line + 1);
        return NULL;
    }
    uint32_t id = p->category[cat].tuneIndex[tune];
    return id < JB_MAX_TUNES ? &p->tune[id] : NULL;
}

void jb_set_tune_on(JBPlayer* p, uint32_t cat, uint32_t tune)
{
    JBTune* t = jb_tune_checked(p, cat, tune, 757);
    if (t) {
        t->use = 1;
    }
}

void jb_set_tune_off(JBPlayer* p, uint32_t cat, uint32_t tune)
{
    JBTune* t = jb_tune_checked(p, cat, tune, 767);
    if (t) {
        t->use = 0;
    }
}

bool jb_get_tune_on(JBPlayer* p, uint32_t cat, uint32_t tune)
{
    JBTune* t = jb_tune_checked(p, cat, tune, 777);
    return t && t->use;
}

void jb_set_category_on(JBPlayer* p, uint32_t cat)
{
    if (cat >= p->numCategories) {
        jb_fail(p, 790);
        return;
    }
    p->category[cat].use = 1;
}

void jb_set_category_off(JBPlayer* p, uint32_t cat)
{
    if (cat >= p->numCategories) {
        jb_fail(p, 797);
        return;
    }
    p->category[cat].use = 0;
}

// 0x0027eca8: round the categories from the one after the last played,
// and in each round its tunes from the one after its last, for one that is
// on.
bool jb_pick_next_tune(JBPlayer* p, uint32_t* cat, uint32_t* tune)
{
    uint32_t n = p->numCategories;
    for (uint32_t i = 1; i <= n; i++) {
        uint32_t c = (p->lastCategory + i) % n;
        JBCategory* k = &p->category[c];
        if (!k->use) {
            continue;
        }
        for (uint32_t j = 1; j <= k->numTunes; j++) {
            uint32_t t = (k->lastTunePlayed + j) % k->numTunes;
            uint32_t id = k->tuneIndex[t];
            if (id < JB_MAX_TUNES && p->tune[id].use) {
                *cat = c;
                p->lastCategory = c;
                *tune = t;
                k->lastTunePlayed = t;
                return true;
            }
        }
    }
    return false;
}

bool jb_is_fading(JBPlayer* p)
{
    jb_update(p);
    return p->statePlay == JB_FADING;
}

bool jb_is_playing(JBPlayer* p)
{
    jb_update(p);
    return p->statePlay == JB_PLAYING || jb_is_fading(p);
}

void jb_set_category(JBPlayer* p, uint32_t cat)
{
    p->soundCategory = cat;
    if (p->sample) {
        H->set_category(H->ctx, cat);
    }
}

#undef H

// -------------------------------------------------------- sound::jukebox

// SaveVolumesForSpeech's list, 0x00313890.
static const uint32_t kSavedCategory[5] = {0, 1, 2, 5, 4};

void jb_sound_init(JBSound* s, const JBHost* host, const JBWorld* world)
{
    memset(s, 0, sizeof *s);
    jb_player_init(&s->jukebox, host);
    s->soundEnabled = 1;
    s->musicEnabled = 1;
    s->firstMenuTune = 1;
    s->firstPursuitTune = 1;
    s->firstRaceTune = 1;
    s->firstAdvance = 1;
    for (int i = 0; i < 5; i++) {
        s->savedVolume[i] = -1.0f;
    }
    s->savedSpeechVolume = -1.0f;
    for (int i = 0; i < 16; i++) {
        s->categoryVolume[i] = 1.0f;
    }
    s->trackKey = -1;
    s->world = world;
}

float jb_get_category_volume(const JBSound* s, uint32_t cat)
{
    return cat < 16 ? s->categoryVolume[cat] : 1.0f;
}

void jb_set_category_volume(JBSound* s, uint32_t cat, float v)
{
    if (cat < 16) {
        s->categoryVolume[cat] = v;
    }
}

float jb_saved_volume(const JBSound* s, uint32_t cat)
{
    switch (cat) {
    case 0: return s->savedVolume[0];
    case 1: return s->savedVolume[1];
    case 2: return s->savedVolume[2];
    case 4: return s->savedVolume[4];
    case 5: return s->savedVolume[3];
    default: return 0.0f;
    }
}

void jb_save_volumes_for_speech(JBSound* s)
{
    for (int i = 0; i < 5; i++) {
        s->savedVolume[i] = jb_get_category_volume(s, kSavedCategory[i]);
    }
    s->savedSpeechVolume = jb_get_category_volume(s, 6);
}

// 0x001afa28's table: each category's volume as the game ships it -- the
// effects, tires, engines, menu effects, racing music, menu music, speech.
static const float kDefaultVolume[7] = {
    0.38f, 0.55f, 0.33f, 0.31f, 0.85f, 0.45f, 0.75f,
};

// 0x001afab8, the end of InitializeSoundDriver and the audio options'
// Default. A demo disc's launcher scaled these by the volume it passed
// (TheDemoDiscManager, 0x002effe0 +36, in tenths); the retail disc runs
// with it off, so the scale is 1.
void jb_default_category_volumes(JBSound* s)
{
    for (uint32_t i = 0; i < 7; i++) {
        jb_set_category_volume(s, i, kDefaultVolume[i]);
    }
    jb_save_volumes_for_speech(s);
}

static int jb_state(const JBSound* s)
{
    return s->world && s->world->game_state
        ? s->world->game_state(s->world->ctx) : 0;
}

static int jb_max_cops(const JBSound* s)
{
    return s->world && s->world->max_cops
        ? s->world->max_cops(s->world->ctx) : 0;
}

// 0x001aea40: the first tune a list plays, once each -- the menu's is the
// playlist's entry 5, a pursuit's 14, a race's 7.
static int jb_first_pick(JBSound* s)
{
    uint32_t cat = s->jukebox.soundCategory;
    if (cat == 5) {
        if (s->firstMenuTune) {
            s->firstMenuTune = 0;
            return 5;
        }
        return -1;
    }
    if (cat == 4) {
        if (jb_max_cops(s) > 0) {
            if (s->firstPursuitTune) {
                s->firstPursuitTune = 0;
                return 14;
            }
            return -1;
        }
        if (s->firstRaceTune) {
            s->firstRaceTune = 0;
            return 7;
        }
        return -1;
    }
    return -1;
}

static uint32_t jb_genre_bit(int8_t genre)
{
    return 1u << ((uint32_t)genre & 31);
}

void jb_music_start(JBSound* s, const uint8_t* ao, int arg)
{
    (void)arg;
    JBPlayer* p = &s->jukebox;
    if (!s->soundEnabled || !s->musicEnabled) {
        return;
    }
    jb_update(p);
    if (p->statePlay == JB_PLAYING || jb_is_fading(p)) {
        return;
    }
    int idx = jb_first_pick(s);
    // A change from retail, at the user's request: retail opens the first
    // race of every boot with the same tune ("Going Down On It", or "One
    // Little Victory (Inst)" with cops). With randomRaceOpener the racing
    // list starts through the random skip below instead.
    if (s->randomRaceOpener && s->jukebox.soundCategory == 4) {
        idx = -1;
    }
    const uint8_t* e = idx >= 0 ? ao + JB_AO_TUNE_LIST + 4 * idx : NULL;
    if (e && (jb_genre_bit((int8_t)e[3]) & ao[JB_AO_GENRE_MASK]) && e[2]) {
        jb_start_tune(p, (uint32_t)(int32_t)(int8_t)e[0],
                      (uint32_t)(int32_t)(int8_t)e[1], 1);
    } else {
        // Anything else starts where the jukebox left off -- but the first
        // time, a random number of tunes on, seeded from the VBlank count.
        if (s->firstAdvance) {
            uint32_t seed = s->world && s->world->vblank
                ? s->world->vblank(s->world->ctx) : 0;
            uint32_t tunes = p->curCatNum < p->numCategories
                ? p->category[p->curCatNum].numTunes : 0;
            int32_t n = bRandomI((int32_t)tunes, &seed);
            if (s->quietSkip) {
                // Each Advance would stop the tune, pick the next and load
                // it; only the pick outlives the next one. Advance does
                // nothing without a cartridge, and StartPlaying picks
                // nothing without a sample.
                uint32_t c, t;
                while (n-- > 0 && jb_is_cartridge_loaded(p) && p->sample) {
                    (void)jb_pick_next_tune(p, &c, &t);
                }
            } else {
                while (n-- > 0) {
                    jb_advance(p);
                }
            }
            s->firstAdvance = 0;
        }
        jb_start(p, 1);
    }
    // Racing music off holds it paused outside the frontend, menu music
    // off inside it. The second call is the one that sticks.
    int fe = jb_state(s) == JB_STATE_IN_FRONTEND;
    jb_pause(p, jb_saved_volume(s, 4) == 0.0f && !fe);
    jb_pause(p, jb_saved_volume(s, 5) == 0.0f && fe);
}

void jb_music_stop(JBSound* s)
{
    if (s->musicEnabled) {
        jb_stop(&s->jukebox);
    }
}

void jb_music_delayed_start(JBSound* s, float seconds)
{
    s->delayedStart = seconds;
    jb_music_stop(s);
}

bool jb_music_is_playing(JBSound* s)
{
    JBPlayer* p = &s->jukebox;
    if (jb_state(s) == JB_STATE_IN_FRONTEND) {
        jb_update(p);
        return p->statePlay == JB_PLAYING || jb_is_fading(p);
    }
    jb_update(p);
    bool playing = p->statePlay == JB_PLAYING || jb_is_fading(p);
    return playing && 0.0f < jb_saved_volume(s, 4);
}

// 0x002b6300: whether a tune plays, by its status (the rows) and the list
// (the columns: the menu, a race, a pursuit). Status 0 never plays, 1 only
// in a pursuit, 2 in a race, 3 in the menu, 4 in the menu and races, 5
// everywhere.
static const int8_t kPlaysOn[18] = {
    0, 0, 0,
    0, 1, 0,
    0, 0, 1,
    1, 0, 0,
    1, 1, 0,
    1, 1, 1,
};

void jb_music_set_selection(JBSound* s, const uint8_t* ao, int cat)
{
    JBPlayer* p = &s->jukebox;
    if (!s->musicEnabled) {
        return;
    }
    jb_set_category(p, (uint32_t)cat);
    int col = cat == 4 ? (jb_max_cops(s) > 0 ? 2 : 1) : cat == 5 ? 0 : -1;
    int32_t n = (int32_t)rd32(ao + JB_AO_NUM_TUNES);
    for (int32_t i = 0; i < n; i++) {
        const uint8_t* e = ao + JB_AO_TUNE_LIST + 4 * i;
        int k = (int8_t)e[2] * 3 + col;
        // Retail reads its stack for a row past the table; nothing in the
        // game's lists reaches one.
        int on = k >= 0 && k < 18 && kPlaysOn[k] &&
                 (ao[JB_AO_GENRE_MASK] & jb_genre_bit((int8_t)e[3]));
        uint32_t c = (uint32_t)(int32_t)(int8_t)e[0];
        uint32_t t = (uint32_t)(int32_t)(int8_t)e[1];
        if (on) {
            jb_set_tune_on(p, c, t);
        } else {
            jb_set_tune_off(p, c, t);
        }
    }
}

// 0x001aed90: the name copied and cut at every '-' into its fields; a
// field is only listed if something follows its '-', so "--" gives an
// empty one.
static const char** jb_extract(JBSound* s, int cat, int tune)
{
    int32_t key = (int32_t)((uint32_t)cat << 16) + tune;
    if (key == s->trackKey) {
        return s->track;
    }
    s->trackKey = key;
    jb_copy_name(s->trackName,
                 jb_tune_name(&s->jukebox, (uint32_t)cat, (uint32_t)tune));
    memset(s->track, 0, sizeof s->track);
    s->track[0] = s->trackName;
    int n = 1;
    for (char* c = s->trackName; *c; c++) {
        if (*c == '-') {
            *c = 0;
            if (c[1] != 0 && n < 16) {
                s->track[n++] = c + 1;
            }
        }
    }
    return s->track;
}

const char* jb_track_string(JBSound* s, int cat, int tune, int field)
{
    if (!s->musicEnabled) {
        return NULL;
    }
    if (cat == -1) {
        cat = (int)s->jukebox.curCatNum;
    }
    if (tune == -1) {
        tune = (int)s->jukebox.curTuneNum;
    }
    return jb_extract(s, cat, tune)[field & 15];
}

// bStrToLong (0x002537d0): the leading decimal digits, no sign.
static int32_t jb_str_to_long(const char* p)
{
    uint32_t v = 0;
    while (*p >= '0' && *p <= '9') {
        v = v * 10 + (uint32_t)(*p++ - '0');
    }
    return (int32_t)v;
}

int jb_track_status(JBSound* s, int cat, int tune)
{
    const char* st = jb_track_string(s, cat, tune, 4);
    if (!st || !*st) {
        return 0;
    }
    return (int)jb_str_to_long(st);
}

uint32_t jb_current_track(const JBSound* s)
{
    return s->jukebox.curTuneNum;
}

void jb_music_update(JBSound* s, const uint8_t* ao, float dt)
{
    if (!s->soundEnabled) {
        return;
    }
    jb_update(&s->jukebox);
    int paused = s->world && s->world->paused
        ? s->world->paused(s->world->ctx) : 0;
    if (paused || jb_state(s) == JB_STATE_IN_FRONTEND || s->muted) {
        return;
    }
    if (0.0f < s->delayedStart) {
        s->delayedStart -= dt;
    }
    if (s->delayedStart < 0.0f) {
        jb_music_start(s, ao, 0);
        s->delayedStart = 0.0f;
    }
}

// ---------------------------------------------- DataAudioOptionsScreen

static void wr32(uint8_t* b, uint32_t v)
{
    b[0] = (uint8_t)v;
    b[1] = (uint8_t)(v >> 8);
    b[2] = (uint8_t)(v >> 16);
    b[3] = (uint8_t)(v >> 24);
}

static void wrf(uint8_t* b, float f)
{
    uint32_t v;
    memcpy(&v, &f, 4);
    wr32(b, v);
}

static float rdf(const uint8_t* b)
{
    uint32_t v = rd32(b);
    float f;
    memcpy(&f, &v, 4);
    return f;
}

void jb_audio_from_sound(JBSound* s, uint8_t* ao, int tunes, int audioMode)
{
    JBPlayer* p = &s->jukebox;
    wrf(ao + JB_AO_MENU_MUSIC, jb_get_category_volume(s, 5));
    wrf(ao + JB_AO_RACING_MUSIC, jb_get_category_volume(s, 4));
    wrf(ao + JB_AO_SFX, jb_get_category_volume(s, 0));
    wrf(ao + JB_AO_SPEECH, jb_get_category_volume(s, 6));
    wrf(ao + JB_AO_SFX_ENGINE, jb_get_category_volume(s, 2));
    wrf(ao + JB_AO_SFX_MENU, jb_get_category_volume(s, 3));
    wrf(ao + JB_AO_SFX_TIRES, jb_get_category_volume(s, 1));
    if (tunes) {
        wr32(ao + JB_AO_NUM_TUNES, 0);
        for (uint32_t c = 0; c < p->numCategories; c++) {
            for (uint32_t t = 0; t < p->category[c].numTunes; t++) {
                int32_t n = (int32_t)rd32(ao + JB_AO_NUM_TUNES);
                if (n < JB_AO_MAX_TUNES) {
                    uint8_t* e = ao + JB_AO_TUNE_LIST + 4 * n;
                    e[0] = (uint8_t)c;
                    e[1] = (uint8_t)t;
                    e[2] = (uint8_t)jb_track_status(s, (int)c, (int)t);
                    wr32(ao + JB_AO_NUM_TUNES, (uint32_t)n + 1);
                }
            }
        }
    }
    ao[JB_AO_AUDIO_MODE] = (uint8_t)audioMode;
    ao[JB_AO_AUDIO_MODE + 1] = (uint8_t)(audioMode >> 8);
}

// GenreMgr, on InitWithDefaults' stack: six genres, each a name and the
// tunes that have it.
typedef struct {
    char    name[JB_NAME_MAX];
    int32_t numTracks;
    int8_t  tracks[JB_AO_MAX_TUNES];
} JBGenre;

void jb_audio_init_with_defaults(JBSound* s, uint8_t* ao, int audioMode)
{
    jb_audio_from_sound(s, ao, 1, audioMode);
    wr32(ao + JB_AO_FE_FAVOURITE, 5);
    ao[JB_AO_GENRE_MASK] = 0xff;
    wr32(ao + JB_AO_SELECTED_SONG, 0);
    wr32(ao + JB_AO_INGAME_FAVOURITE, 0);
    ao[JB_AO_CURR_GENRE] = 0;

    // GenreMgr::Populate: each tune's genre numbered in the order they
    // first turn up -- Rock 0, Techno 1 on the retail cartridge.
    JBGenre genre[6];
    int32_t genres = 0;
    memset(genre, 0, sizeof genre);
    int32_t n = (int32_t)rd32(ao + JB_AO_NUM_TUNES);
    for (int32_t i = 0; i < n; i++) {
        uint8_t* e = ao + JB_AO_TUNE_LIST + 4 * i;
        const char* g = jb_track_string(s, (int8_t)e[0], (int8_t)e[1], 3);
        if (!g || !*g) {
            continue;
        }
        int32_t k;
        for (k = 0; k < genres; k++) {
            if (strcmp(g, genre[k].name) == 0) {
                break;
            }
        }
        if (k == genres) {
            if (genres >= 6) {
                continue;               // past retail's six: its stack
            }
            jb_copy_name(genre[k].name, g);
            genres++;
        }
        e[3] = (uint8_t)k;
        if (genre[k].numTracks < JB_AO_MAX_TUNES) {
            genre[k].tracks[genre[k].numTracks++] = (int8_t)i;
        }
    }
}

int jb_audio_apply(JBSound* s, const uint8_t* ao)
{
    jb_set_category_volume(s, 5, rdf(ao + JB_AO_MENU_MUSIC));
    jb_set_category_volume(s, 4, rdf(ao + JB_AO_RACING_MUSIC));
    jb_set_category_volume(s, 0, rdf(ao + JB_AO_SFX));
    jb_set_category_volume(s, 6, rdf(ao + JB_AO_SPEECH));
    jb_set_category_volume(s, 2, rdf(ao + JB_AO_SFX_ENGINE));
    jb_set_category_volume(s, 3, rdf(ao + JB_AO_SFX_MENU));
    jb_set_category_volume(s, 1, rdf(ao + JB_AO_SFX_TIRES));
    jb_save_volumes_for_speech(s);
    jb_music_set_selection(s, ao, 5);
    return (int16_t)(ao[JB_AO_AUDIO_MODE] | ao[JB_AO_AUDIO_MODE + 1] << 8);
}
