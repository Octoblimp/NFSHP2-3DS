// Harness for tools/sound_check.py: runs the checker's script on sound.c
// and prints what the model prints for the retail image. bSound, the
// jukebox and every module sound.c reaches through SoundHooks are logging
// fakes, the same fakes the checker gives retail's code. See the checker's
// docstring.
//
//     sound_test script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "bsound.h"
#include "bticker.h"
#include "jukebox.h"
#include "sound.h"

int32_t SoundEnabled = 1;

static SoundModule mod;
static BSound      bs;
static JBSound     jb;
static uint8_t     ao[JB_AO_SIZE];

static uint32_t bits(float f)
{
    uint32_t v;
    memcpy(&v, &f, 4);
    return v;
}

static float unbits(uint32_t v)
{
    float f;
    memcpy(&f, &v, 4);
    return f;
}

// ------------------------------------------------------------- the world

static int      g_state, g_paused, g_replay, g_jget, g_sedplay;
static int      g_vevery = 1, g_vcount;
static uint32_t g_vblank, g_tick;
static float    g_dt;
static int      g_race = -1;
static int      g_nplayers;
static struct { int muffle, zone; float vol; } g_player[2];
static char     g_track[40];
static int      g_hastrack;
static struct { int exists, rank, type; } g_driver[2];
static char     g_cartype[64][40];
static int      g_world, g_chopper, g_ncars, g_carmask;
static int      g_carsound[32];

static char     g_missing[16][64];
static int      g_nmissing;
static char     g_fail[16][40];
static int      g_nfail;

// ------------------------------------------------------------- the ticker

uint32_t bGetTicker(void)
{
    return g_tick;
}

float bGetTickerDifference(uint32_t from, uint32_t to)
{
    return (float)(uint32_t)(to - from);
}

// ------------------------------------------------------------- bSound

static int  g_up = 1, g_auto = 1, g_ucount;
static float g_vol[16];

static char g_pend[8][40];
static int  g_npend;

typedef struct {
    BRegion r;
    int     registered;
} FakeRegion;
static FakeRegion g_reg[32];
static int        g_nreg;

typedef struct {
    BSample s;
    char    id[80];
} FakeSample;
static FakeSample g_smp[64];
static int        g_nsmp;

static FakeRegion* region_of(const char* name, int create)
{
    for (int i = 0; i < g_nreg; i++)
        if (strcmp(g_reg[i].r.name, name) == 0)
            return &g_reg[i];
    if (!create || g_nreg == 32)
        return NULL;
    FakeRegion* r = &g_reg[g_nreg++];
    snprintf(r->r.name, sizeof r->r.name, "%s", name);
    return r;
}

static const char* sid(const BSample* s)
{
    for (int i = 0; i < g_nsmp; i++)
        if (&g_smp[i].s == s)
            return g_smp[i].id;
    return "(null)";
}

static int failing(const char* name)
{
    for (int i = 0; i < g_nfail; i++)
        if (strcmp(g_fail[i], name) == 0)
            return 1;
    return 0;
}

static void deliver(BSound* s)
{
    char name[40];
    FakeRegion* r;

    snprintf(name, sizeof name, "%s", g_pend[0]);
    memmove(g_pend[0], g_pend[1], sizeof g_pend[0] * (size_t)(g_npend - 1));
    g_npend--;
    s->pendingCount = g_npend;
    r = region_of(name, 1);
    r->registered = 1;
    if (strcmp(name, "common") == 0)
        s->common = &r->r;
    printf("  arrive %s\n", name);
    if (s->client)
        s->client(BSOUND_REGION_LOADED, &r->r, s->clientData);
}

void bsound_init(BSound* s, BsndDriver* d, BSoundCallback client,
                 void* clientData)
{
    (void)d;
    printf("  binit\n");
    s->client = client;
    s->clientData = clientData;
    s->status = g_up ? 1 : 0;
}

void bsound_set_path(BSound* s, const char* path)
{
    (void)s;
    printf("  bpath %s\n", path);
}

int32_t bsound_load_region(BSound* s, const char* name)
{
    printf("  bload %s\n", name);
    if (s->status != 1 || failing(name) || g_npend == 8)
        return 0;
    snprintf(g_pend[g_npend++], sizeof g_pend[0], "%s", name);
    s->pendingCount = g_npend;
    return 1;
}

int32_t bsound_get_status(const BSound* s)
{
    return s->status;
}

// With `auto` k, a pending region comes in on the kth update.
void bsound_update(BSound* s)
{
    printf("  bupdate\n");
    if (s->status == 1 && g_auto && g_npend > 0 && ++g_ucount >= g_auto) {
        g_ucount = 0;
        deliver(s);
    }
}

void bsound_unload_region(BSound* s, const char* name)
{
    FakeRegion* r = region_of(name, 0);

    printf("  bunload %s\n", name);
    if (r != NULL && r->registered) {
        r->registered = 0;
        if (s->common == &r->r)
            s->common = NULL;
    }
}

BRegion* bsound_common_region(const BSound* s)
{
    return s->common;
}

BRegion* bsound_region(const BSound* s, const char* name)
{
    FakeRegion* r = region_of(name, 0);

    (void)s;
    printf("  bregion %s\n", name);
    return r != NULL && r->registered ? &r->r : NULL;
}

const char* bregion_name(const BRegion* r)
{
    return r->name;
}

BSample* bregion_sample(const BRegion* r, const char* name)
{
    char id[80];

    printf("  bsample %s %s\n", r ? r->name : "(null)", name);
    if (r == NULL || name[0] == 'X')
        return NULL;
    snprintf(id, sizeof id, "%s/%s", r->name, name);
    for (int i = 0; i < g_nsmp; i++)
        if (strcmp(g_smp[i].id, id) == 0)
            return &g_smp[i].s;
    if (g_nsmp == 64)
        return NULL;
    snprintf(g_smp[g_nsmp].id, sizeof g_smp[0].id, "%s", id);
    return &g_smp[g_nsmp++].s;
}

void bsample_set_category(BSample* s, uint32_t category)
{
    printf("  bcat %s %u\n", sid(s), category);
}

BVoice* bsample_play(BSample* s, float volume, float pan, float pitch)
{
    printf("  bplay %s %08x %08x %08x\n", sid(s), bits(volume), bits(pan),
           bits(pitch));
    return NULL;
}

float bsound_get_category_volume(const BSound* s, uint32_t category)
{
    (void)s;
    return category < 16 ? g_vol[category] : 1.0f;
}

void bsound_set_category_volume(BSound* s, uint32_t category, float v)
{
    (void)s;
    printf("  bvol %u %08x\n", category, bits(v));
    if (category < 16)
        g_vol[category] = v;
}

void bsound_set_mode(BSound* s, int32_t mode)
{
    (void)s;
    printf("  bmode %d\n", mode);
}

// ------------------------------------------------------------- the jukebox

void jb_load_cartridge(JBPlayer* p, const char* path, bool arg)
{
    (void)p;
    printf("  jbload %s %d\n", path, arg ? 1 : 0);
}

void jb_update(JBPlayer* p)
{
    (void)p;
    printf("  jbupdate\n");
}

void jb_pause(JBPlayer* p, uint32_t on)
{
    (void)p;
    printf("  jbpause %d\n", (int32_t)on);
}

void jb_default_category_volumes(JBSound* s)
{
    (void)s;
    printf("  jbdefvol\n");
}

void jb_music_start(JBSound* s, const uint8_t* fredAudio, int arg)
{
    (void)s;
    (void)fredAudio;
    printf("  jbstart %d\n", arg);
}

void jb_music_set_selection(JBSound* s, const uint8_t* fredAudio, int cat)
{
    (void)s;
    (void)fredAudio;
    printf("  jbselect %d\n", cat);
}

// ------------------------------------------------------------- the hooks

static int h_game_state(void* c) { (void)c; return g_state; }
static int h_paused(void* c) { (void)c; return g_paused; }
static float h_dt(void* c) { (void)c; return g_dt; }
static uint32_t h_vblank(void* c) { (void)c; return g_vblank; }

static void h_service(void* c)
{
    (void)c;
    printf("  service\n");
    if (++g_vcount >= g_vevery) {
        g_vcount = 0;
        g_vblank++;
    }
}

static int h_file_exists(void* c, const char* path)
{
    (void)c;
    printf("  exists %s\n", path);
    for (int i = 0; i < g_nmissing; i++)
        if (strcmp(g_missing[i], path) == 0)
            return 0;
    return 1;
}

static void h_flash(void* c, int r, int g, int b, const char* why,
                    float seconds)
{
    (void)c;
    printf("  flash %d %d %d %s %08x\n", r, g, b, why, bits(seconds));
}

static int h_race_state(void* c) { (void)c; return g_race; }
static int h_num_players(void* c) { (void)c; return g_nplayers; }

static void h_player_zone(void* c, int i, int* muffle, int* zone,
                          float* volume)
{
    (void)c;
    *muffle = g_player[i].muffle;
    *zone = g_player[i].zone;
    *volume = g_player[i].vol;
}

static const char* h_track_region(void* c)
{
    (void)c;
    return g_hastrack ? g_track : NULL;
}

static const char* h_driver_region(void* c, int i)
{
    (void)c;
    printf("  driver %d\n", i);
    if (!g_driver[i].exists)
        return NULL;
    if ((int8_t)g_driver[i].rank > 0)
        return NULL;
    return g_cartype[g_driver[i].type & 63];
}

static int h_num_cars(void* c) { (void)c; return g_world ? g_ncars : 0; }

static void* h_car_sound(void* c, int i)
{
    (void)c;
    return (g_carmask >> i) & 1 ? &g_carsound[i] : NULL;
}

static void h_car_sound_mute(void* c, void* s, int on)
{
    (void)c;
    printf("  carmute %d %d\n", (int)((int*)s - g_carsound), on);
}

static int h_helicopter(void* c) { (void)c; return g_world && g_chopper; }
static int h_joylog_replaying(void* c) { (void)c; return g_replay; }

static int32_t h_joylog_get(void* c, int nbits, int channel)
{
    (void)c;
    printf("  jget %d %d\n", nbits, channel);
    return g_jget;
}

static void h_joylog_add(void* c, int32_t value, int nbits, int channel)
{
    (void)c;
    printf("  jadd %d %d %d\n", value, nbits, channel);
}

static int h_sed_playing(void* c) { (void)c; return g_sedplay; }

#define SAY(fn, text) static void fn(void* c) { (void)c; printf("  " text "\n"); }
#define SAY1(fn, text) static void fn(void* c, int on) { (void)c; printf("  " text " %d\n", on); }
SAY(h_speech_update, "speech update")
SAY1(h_speech_mute, "speech mute")
SAY(h_speech_flush, "speech flush")
SAY(h_sed_create, "sed create")
SAY(h_sed_update, "sed update")
SAY(h_noise_request, "noise request")
SAY(h_noise_unload, "noise unload")
SAY(h_noise_update, "noise update")
SAY1(h_noise_mute, "noise mute")
SAY(h_collision_register, "collision register")
SAY(h_collision_unregister, "collision unregister")
SAY(h_collision_update, "collision update")
SAY1(h_collision_mute, "collision mute")
SAY(h_scape_update, "scape update")
SAY1(h_scape_mute, "scape mute")
SAY(h_car_sounds_update, "carsounds")
SAY(h_chopper_update, "chopper update")
SAY1(h_chopper_mute, "chopper mute")
SAY(h_oneshot_init, "oneshot init")
SAY(h_oneshot_close, "oneshot close")
SAY(h_oneshot_update, "oneshot update")
SAY1(h_oneshot_mute, "oneshot mute")

static const SoundHooks hooks = {
    .game_state = h_game_state,
    .paused = h_paused,
    .dt = h_dt,
    .vblank = h_vblank,
    .service_files = h_service,
    .file_exists = h_file_exists,
    .flash = h_flash,
    .race_state = h_race_state,
    .num_players = h_num_players,
    .player_zone = h_player_zone,
    .track_region = h_track_region,
    .driver_region = h_driver_region,
    .num_cars = h_num_cars,
    .car_sound = h_car_sound,
    .helicopter = h_helicopter,
    .joylog_replaying = h_joylog_replaying,
    .joylog_get = h_joylog_get,
    .joylog_add = h_joylog_add,
    .sound_path = NULL,
    .skip_missing = 0,
    .speech_update = h_speech_update,
    .speech_mute = h_speech_mute,
    .speech_flush = h_speech_flush,
    .speech_sed_playing = h_sed_playing,
    .sed_create = h_sed_create,
    .sed_update = h_sed_update,
    .noise_request = h_noise_request,
    .noise_unload = h_noise_unload,
    .noise_update = h_noise_update,
    .noise_mute = h_noise_mute,
    .collision_register = h_collision_register,
    .collision_unregister = h_collision_unregister,
    .collision_update = h_collision_update,
    .collision_mute = h_collision_mute,
    .scape_update = h_scape_update,
    .scape_mute = h_scape_mute,
    .car_sounds_update = h_car_sounds_update,
    .car_sound_mute = h_car_sound_mute,
    .chopper_update = h_chopper_update,
    .chopper_mute = h_chopper_mute,
    .oneshot_init = h_oneshot_init,
    .oneshot_close = h_oneshot_close,
    .oneshot_update = h_oneshot_update,
    .oneshot_mute = h_oneshot_mute,
};

static void done(intptr_t param)
{
    printf("  done %d\n", (int)param);
}

// ------------------------------------------------------------- the dump

static const char* rname(const BRegion* r)
{
    return r ? r->name : "(null)";
}

static void dump(void)
{
    printf("  mod loading=%d start=%u last=%u muffle=%08x,%08x scale=%08x "
           "seed=%08x dseed=%08x mode=%d common=%d ingame=%s fe=%s done=%d "
           "param=%d speech=%d pvu=%d\n",
           mod.loading, mod.loadStart, mod.lastUpdate,
           bits(mod.muffleCurrent), bits(mod.muffleTarget),
           bits(mod.lastScale), mod.seed, bDefaultSeed, mod.audioMode,
           mod.commonLoaded, rname(mod.inGameRegion),
           rname(mod.frontEndRegion), mod.done != NULL ? 1 : 0,
           (int)mod.doneParam, mod.speechEnabled, mod.printVoiceUsage);
    for (int i = 0; i < SOUND_REGIONS; i++)
        printf("  slot %d '%s' %d\n", i, mod.region[i].name,
               mod.region[i].loaded);
    printf("  jb delay=%08x muted=%d me=%d se=%d\n", bits(jb.delayedStart),
           jb.muted, jb.musicEnabled, SoundEnabled);
    printf("  bs status=%d pending=%d", bs.status, g_npend);
    for (int i = 0; i < g_npend; i++)
        printf(" %s", g_pend[i]);
    printf(" common=%s regions=", rname(bs.common));
    for (int i = 0; i < g_nreg; i++)
        if (g_reg[i].registered)
            printf("%s,", g_reg[i].r.name);
    printf("\n  vol");
    for (int i = 0; i < 16; i++)
        printf(" %08x", bits(g_vol[i]));
    printf("\n");
}

// ------------------------------------------------------------- the ops

static char* arg[12];
static int   nargs;

static int ai(int i)
{
    return i < nargs ? (int)strtol(arg[i], NULL, 0) : 0;
}

static uint32_t ah(int i)
{
    return i < nargs ? (uint32_t)strtoul(arg[i], NULL, 16) : 0;
}

static const char* as(int i)
{
    if (i >= nargs || strcmp(arg[i], "~") == 0)
        return "";
    return arg[i];
}

static void run(void)
{
    const char* o = arg[0];

    if (!strcmp(o, "init")) {
        sound_initialize_driver(&mod);
    } else if (!strcmp(o, "event")) {
        FakeRegion* r = region_of(as(2), 1);
        sound_driver_callback((uint32_t)ai(1), &r->r, &mod);
    } else if (!strcmp(o, "arrive")) {
        if (g_npend > 0)
            deliver(&bs);
    } else if (!strcmp(o, "ingame")) {
        sound_load_regions_in_game(&mod, ai(2) ? NULL : done, ai(1));
    } else if (!strcmp(o, "frontend")) {
        sound_load_regions_front_end(&mod, ai(2) ? NULL : done, ai(1));
    } else if (!strcmp(o, "real")) {
        printf("  = %d\n", sound_real_is_region_loading_complete(&mod));
    } else if (!strcmp(o, "iscomplete")) {
        printf("  = %d\n", sound_is_region_loading_complete(&mod));
    } else if (!strcmp(o, "unload")) {
        sound_unload_regions(&mod);
    } else if (!strcmp(o, "update")) {
        sound_update(&mod);
    } else if (!strcmp(o, "muffler")) {
        sound_update_volume_muffler(&mod);
    } else if (!strcmp(o, "scale")) {
        sound_scale_category_volumes(&mod, unbits(ah(1)), ai(2));
    } else if (!strcmp(o, "mute")) {
        sound_mute(&mod, ai(1));
    } else if (!strcmp(o, "mutereplay")) {
        sound_mute_replay(&mod, ai(1));
    } else if (!strcmp(o, "mutecars")) {
        sound_mute_car_sounds(&mod, ai(1));
    } else if (!strcmp(o, "getsample")) {
        printf("  = %s\n", sid(sound_get_in_game_sample(&mod, as(1))));
    } else if (!strcmp(o, "playcommon")) {
        sound_play_common_region_sample(&mod, as(1), unbits(ah(2)));
    } else if (!strcmp(o, "finish")) {
        sound_trigger_finish_line_sound(&mod);
    } else if (!strcmp(o, "randi")) {
        printf("  = %d\n", sound_random_int(&mod, ai(1)));
    } else if (!strcmp(o, "randf")) {
        printf("  = %08x\n", bits(sound_random_float(&mod, unbits(ah(1)))));
    } else if (!strcmp(o, "setmode")) {
        sound_set_audio_mode(&mod, ai(1));
    } else if (!strcmp(o, "getmode")) {
        printf("  = %d\n", sound_get_audio_mode(&mod));
    } else if (!strcmp(o, "dump")) {
        dump();
    // ---- the world
    } else if (!strcmp(o, "se")) {
        SoundEnabled = ai(1);
    } else if (!strcmp(o, "me")) {
        jb.musicEnabled = ai(1);
    } else if (!strcmp(o, "speechen")) {
        mod.speechEnabled = ai(1);
    } else if (!strcmp(o, "pvu")) {
        mod.printVoiceUsage = ai(1);
    } else if (!strcmp(o, "up")) {
        g_up = ai(1);
    } else if (!strcmp(o, "auto")) {
        g_auto = ai(1);
        g_ucount = 0;
    } else if (!strcmp(o, "flush")) {
        g_npend = 0;
        bs.pendingCount = 0;
        g_ucount = 0;
    } else if (!strcmp(o, "uncommon")) {
        mod.commonLoaded = 0;
    } else if (!strcmp(o, "vblank")) {
        g_vblank = (uint32_t)strtoul(arg[1], NULL, 0);
    } else if (!strcmp(o, "missing")) {
        char path[64];
        snprintf(path, sizeof path, "sound\\%s.msh", as(1));
        if (ai(2) && g_nmissing < 16) {
            snprintf(g_missing[g_nmissing++], sizeof g_missing[0], "%s", path);
        } else if (!ai(2)) {
            for (int i = 0; i < g_nmissing; i++)
                if (!strcmp(g_missing[i], path))
                    g_missing[i][0] = '\0';
        }
    } else if (!strcmp(o, "fail")) {
        if (ai(2) && g_nfail < 16) {
            snprintf(g_fail[g_nfail++], sizeof g_fail[0], "%s", as(1));
        } else if (!ai(2)) {
            for (int i = 0; i < g_nfail; i++)
                if (!strcmp(g_fail[i], as(1)))
                    g_fail[i][0] = '\0';
        }
    } else if (!strcmp(o, "state")) {
        g_state = ai(1);
    } else if (!strcmp(o, "paused")) {
        g_paused = ai(1);
    } else if (!strcmp(o, "dt")) {
        g_dt = unbits(ah(1));
    } else if (!strcmp(o, "tick")) {
        g_tick = (uint32_t)strtoul(arg[1], NULL, 0);
    } else if (!strcmp(o, "vevery")) {
        g_vevery = ai(1);
        g_vcount = 0;
    } else if (!strcmp(o, "replay")) {
        g_replay = ai(1);
        g_jget = ai(2);
    } else if (!strcmp(o, "race")) {
        g_race = ai(1);
    } else if (!strcmp(o, "players")) {
        g_nplayers = ai(1);
    } else if (!strcmp(o, "player")) {
        g_player[ai(1)].muffle = ai(2);
        g_player[ai(1)].zone = ai(3);
        g_player[ai(1)].vol = unbits(ah(4));
    } else if (!strcmp(o, "track")) {
        g_hastrack = strcmp(arg[1], "@") != 0;
        snprintf(g_track, sizeof g_track, "%s", g_hastrack ? as(1) : "");
    } else if (!strcmp(o, "driver")) {
        g_driver[ai(1)].exists = ai(2);
        g_driver[ai(1)].rank = ai(3);
        g_driver[ai(1)].type = ai(4);
    } else if (!strcmp(o, "cartype")) {
        snprintf(g_cartype[ai(1) & 63], sizeof g_cartype[0], "%s", as(2));
    } else if (!strcmp(o, "world")) {
        g_world = ai(1);
    } else if (!strcmp(o, "chopper")) {
        g_chopper = ai(1);
    } else if (!strcmp(o, "cars")) {
        g_ncars = ai(1);
        g_carmask = (int)strtol(arg[2], NULL, 0);
    } else if (!strcmp(o, "sedplay")) {
        g_sedplay = ai(1);
    } else if (!strcmp(o, "catvol")) {
        if (ai(1) < 16)
            g_vol[ai(1)] = unbits(ah(2));
    } else if (!strcmp(o, "saved")) {
        jb.savedVolume[ai(1)] = unbits(ah(2));
    } else if (!strcmp(o, "savedsp")) {
        jb.savedSpeechVolume = unbits(ah(1));
    } else if (!strcmp(o, "jbcat")) {
        jb.jukebox.soundCategory = (uint32_t)ai(1);
    } else if (!strcmp(o, "delay")) {
        jb.delayedStart = unbits(ah(1));
    } else if (!strcmp(o, "muted")) {
        jb.muted = ai(1);
    } else if (!strcmp(o, "seed")) {
        mod.seed = (uint32_t)strtoul(arg[1], NULL, 0);
    } else if (!strcmp(o, "dseed")) {
        bDefaultSeed = (uint32_t)strtoul(arg[1], NULL, 0);
    } else {
        printf("  unknown op %s\n", o);
    }
}

int main(int argc, char** argv)
{
    static char line[512];
    FILE* sc;

    if (argc < 2) {
        fprintf(stderr, "usage: sound_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (!sc)
        return 2;
    for (int i = 0; i < 16; i++)
        g_vol[i] = 1.0f;
    jb.savedSpeechVolume = -1.0f;
    sound_init(&mod, &bs, NULL, &jb, ao, &hooks);
    while (fgets(line, sizeof line, sc)) {
        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        printf("> %s\n", line);
        nargs = 0;
        for (char* t = strtok(line, "|"); t && nargs < 12;
             t = strtok(NULL, "|"))
            arg[nargs++] = t;
        run();
        fflush(stdout);
    }
    fclose(sc);
    return 0;
}
