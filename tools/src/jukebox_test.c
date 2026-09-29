// Harness for tools/jukebox_check.py: runs the checker's script on
// jukebox.c and prints what the model prints for the retail image. The
// sample and the file are logging stubs; an assert prints its line and
// ends the op, as retail's bBreak ends the game. See the checker's
// docstring.
//
//     jukebox_test script.txt cart1.bin cart2.bin ... > out.txt

#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "jukebox.h"

static JBSound   snd;
static uint8_t   ao[JB_AO_SIZE];
static jmp_buf   abort_op;

static uint8_t*  cart[8];
static long      cart_size[8];
static int       cart_now = 0;
static long      cart_pos;
static int       sound_up = 1;
static int       audio_mode;
static int       g_state, g_cops, g_paused;
static uint32_t  g_vblank;
static float     g_dt;

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

// ------------------------------------------------------------- the host

static void h_create(void* c, uint32_t rate) { (void)c; printf("  create %u\n", rate); }
static void h_destroy(void* c) { (void)c; printf("  destroy\n"); }
static void h_load(void* c, const char* path, uint32_t off, uint32_t size)
{
    (void)c;
    printf("  load %s %u %u\n", path, off, size);
}
static void h_play(void* c, float v, float a, float b)
{
    (void)c;
    printf("  play %08x %08x %08x\n", bits(v), bits(a), bits(b));
}
static void h_stop(void* c) { (void)c; printf("  stop\n"); }
static void h_pause(void* c, bool on) { (void)c; printf("  pause %d\n", on ? 1 : 0); }
static void h_fade(void* c, float to, uint32_t ms)
{
    (void)c;
    printf("  fade %08x %u\n", bits(to), ms);
}
static void h_cleanup(void* c) { (void)c; printf("  cleanup\n"); }
static void h_category(void* c, uint32_t cat) { (void)c; printf("  category %u\n", cat); }
static void h_scale(void* c, float v) { (void)c; printf("  scale %08x\n", bits(v)); }

static void* h_open(void* c, const char* path)
{
    (void)c;
    printf("  open %s\n", path);
    if (!cart_now) {
        return NULL;
    }
    cart_pos = 0;
    return &cart_pos;
}

static int h_read(void* c, void* file, void* buf, uint32_t n)
{
    (void)c;
    (void)file;
    printf("  read %u\n", n);
    uint8_t* b = cart[cart_now];
    for (uint32_t i = 0; i < n; i++) {
        ((uint8_t*)buf)[i] = cart_pos < cart_size[cart_now] ? b[cart_pos] : 0;
        cart_pos++;
    }
    return (int)n;
}

static void h_close(void* c, void* file) { (void)c; (void)file; printf("  close\n"); }
static int  h_sound_up(void* c) { (void)c; return sound_up; }

static void h_assert(void* c, int line)
{
    (void)c;
    printf("  assert %d\n", line);
    longjmp(abort_op, 1);
}

static const JBHost host = {
    NULL, h_create, h_destroy, h_load, h_play, h_stop, h_pause, h_fade,
    h_cleanup, h_category, h_scale, h_open, h_read, h_close, h_sound_up,
    h_assert,
};

static int      w_state(void* c) { (void)c; return g_state; }
static int      w_cops(void* c) { (void)c; return g_cops; }
static uint32_t w_vblank(void* c) { (void)c; return g_vblank; }
static int      w_paused(void* c) { (void)c; return g_paused; }

static const JBWorld world = { NULL, w_state, w_cops, w_vblank, w_paused };

// ------------------------------------------------------------- the dump

static void dump(void)
{
    JBPlayer* p = &snd.jukebox;
    printf("  player cats=%u tunes=%u file=%d sample=%d state=%u keep=%u "
           "cur=%u,%u on=%u cat=%u vol=%08x trig=%u pbp=%u last=%u\n",
           p->numCategories, p->numTunes, p->fileOpen ? 1 : 0,
           p->sample ? 1 : 0, p->statePlay, p->keepPlaying, p->curCatNum,
           p->curTuneNum, p->on, p->soundCategory, bits(p->volume), p->trigger,
           p->pauseBeforePlay, p->lastCategory);
    printf("  hdr");
    for (int i = 0; i < 8; i++) {
        printf(" %u", p->header[i]);
    }
    printf("\n");
    for (uint32_t c = 0; c < p->numCategories && c < JB_MAX_CATEGORIES; c++) {
        JBCategory* k = &p->category[c];
        printf("  cat %u %s n=%u use=%u last=%u idx=", c, k->name,
               k->numTunes, k->use, k->lastTunePlayed);
        for (uint32_t t = 0; t < k->numTunes && t < JB_MAX_TUNES; t++) {
            printf(t ? ",%u" : "%u", k->tuneIndex[t]);
        }
        printf("\n");
    }
    for (uint32_t t = 0; t < p->numTunes && t < JB_MAX_TUNES; t++) {
        JBTune* u = &p->tune[t];
        printf("  tune %u %s use=%u size=%u off=%u sync=%u id=%u\n", t,
               u->name, u->use, u->size, u->offset, u->syncSize, u->id);
    }
    printf("  sound se=%d me=%d first=%d,%d,%d,%d delay=%08x muted=%d "
           "saved=%08x,%08x,%08x,%08x,%08x speech=%08x key=%d\n",
           snd.soundEnabled, snd.musicEnabled, snd.firstMenuTune,
           snd.firstPursuitTune, snd.firstRaceTune, snd.firstAdvance,
           bits(snd.delayedStart), snd.muted, bits(snd.savedVolume[0]),
           bits(snd.savedVolume[1]), bits(snd.savedVolume[2]),
           bits(snd.savedVolume[3]), bits(snd.savedVolume[4]),
           bits(snd.savedSpeechVolume), snd.trackKey);
    printf("  vol");
    for (int i = 0; i < 16; i++) {
        printf(" %08x", bits(snd.categoryVolume[i]));
    }
    printf("\n");
    printf("  ao ");
    for (int i = 0; i < JB_AO_SIZE; i++) {
        printf("%02x", ao[i]);
    }
    printf("\n");
}

// ------------------------------------------------------------- the script

static char* arg[12];
static int   nargs;

static long  num(int i) { return i < nargs ? strtol(arg[i], NULL, 0) : 0; }
static uint32_t unum(int i) { return (uint32_t)num(i); }
static float fnum(int i) { return unbits((uint32_t)strtoul(arg[i], NULL, 16)); }

static void run(void)
{
    JBPlayer* p = &snd.jukebox;
    const char* op = arg[0];
    if (!strcmp(op, "load")) {
        jb_load_cartridge(p, "SOUND\\JukeboxM.JBC", false);
    } else if (!strcmp(op, "close")) {
        jb_close(p);
    } else if (!strcmp(op, "defaults")) {
        jb_audio_init_with_defaults(&snd, ao, audio_mode);
    } else if (!strcmp(op, "fromsound")) {
        jb_audio_from_sound(&snd, ao, (int)num(1), audio_mode);
    } else if (!strcmp(op, "apply")) {
        printf("  audiomode %d\n", jb_audio_apply(&snd, ao));
    } else if (!strcmp(op, "select")) {
        jb_music_set_selection(&snd, ao, (int)num(1));
    } else if (!strcmp(op, "mstart")) {
        jb_music_start(&snd, ao, 0);
    } else if (!strcmp(op, "mstop")) {
        jb_music_stop(&snd);
    } else if (!strcmp(op, "delayed")) {
        jb_music_delayed_start(&snd, fnum(1));
    } else if (!strcmp(op, "misplaying")) {
        printf("  = %d\n", jb_music_is_playing(&snd) ? 1 : 0);
    } else if (!strcmp(op, "update")) {
        jb_update(p);
    } else if (!strcmp(op, "event")) {
        jb_sample_callback(p, unum(1));
    } else if (!strcmp(op, "start")) {
        jb_start(p, unum(1));
    } else if (!strcmp(op, "starttune")) {
        jb_start_tune(p, unum(1), unum(2), unum(3));
    } else if (!strcmp(op, "stopj")) {
        jb_stop(p);
    } else if (!strcmp(op, "fade")) {
        jb_fade_out(p, unum(1));
    } else if (!strcmp(op, "fadeadv")) {
        jb_fade_out_advance(p, unum(1));
    } else if (!strcmp(op, "advance")) {
        jb_advance(p);
    } else if (!strcmp(op, "seton")) {
        jb_set_on(p, unum(1));
    } else if (!strcmp(op, "setvol")) {
        jb_set_volume(p, fnum(1));
    } else if (!strcmp(op, "tuneon")) {
        jb_set_tune_on(p, unum(1), unum(2));
    } else if (!strcmp(op, "tuneoff")) {
        jb_set_tune_off(p, unum(1), unum(2));
    } else if (!strcmp(op, "gettuneon")) {
        printf("  = %d\n", jb_get_tune_on(p, unum(1), unum(2)) ? 1 : 0);
    } else if (!strcmp(op, "caton")) {
        jb_set_category_on(p, unum(1));
    } else if (!strcmp(op, "catoff")) {
        jb_set_category_off(p, unum(1));
    } else if (!strcmp(op, "pick")) {
        uint32_t c = 0, t = 0;
        bool r = jb_pick_next_tune(p, &c, &t);
        if (r) {
            printf("  = 1 %u %u\n", c, t);
        } else {
            printf("  = 0\n");
        }
    } else if (!strcmp(op, "jpause")) {
        jb_pause(p, unum(1));
    } else if (!strcmp(op, "isplaying")) {
        printf("  = %d\n", jb_is_playing(p) ? 1 : 0);
    } else if (!strcmp(op, "isfading")) {
        printf("  = %d\n", jb_is_fading(p) ? 1 : 0);
    } else if (!strcmp(op, "stopplaying")) {
        jb_stop_playing(p);
    } else if (!strcmp(op, "startfading")) {
        jb_start_fading(p, unum(1));
    } else if (!strcmp(op, "startplaying")) {
        jb_start_playing(p);
    } else if (!strcmp(op, "startplayingtune")) {
        jb_start_playing_tune(p, unum(1), unum(2));
    } else if (!strcmp(op, "name")) {
        printf("  = %s\n", jb_tune_name(p, unum(1), unum(2)));
    } else if (!strcmp(op, "offset")) {
        printf("  = %u\n", jb_tune_offset(p, unum(1), unum(2)));
    } else if (!strcmp(op, "size")) {
        printf("  = %u\n", jb_tune_size(p, unum(1), unum(2)));
    } else if (!strcmp(op, "id")) {
        printf("  = %u\n", jb_tune_id(p, unum(1), unum(2)));
    } else if (!strcmp(op, "addcat")) {
        printf("  = %d\n", jb_add_category(p, arg[1]));
    } else if (!strcmp(op, "addtune")) {
        printf("  = %d\n", jb_add_tune(p, arg[1], arg[2], unum(3), unum(4),
                                       unum(5), unum(6)));
    } else if (!strcmp(op, "track")) {
        const char* s = jb_track_string(&snd, (int)num(1), (int)num(2),
                                        (int)num(3));
        printf("  = %s\n", s ? s : "(null)");
    } else if (!strcmp(op, "status")) {
        printf("  = %d\n", jb_track_status(&snd, (int)num(1), (int)num(2)));
    } else if (!strcmp(op, "current")) {
        printf("  = %u\n", jb_current_track(&snd));
    } else if (!strcmp(op, "savedvol")) {
        printf("  = %08x\n", bits(jb_saved_volume(&snd, unum(1))));
    } else if (!strcmp(op, "saved")) {
        jb_save_volumes_for_speech(&snd);
    } else if (!strcmp(op, "setcatvol")) {
        jb_set_category_volume(&snd, unum(1), fnum(2));
    } else if (!strcmp(op, "soundupdate")) {
        jb_music_update(&snd, ao, g_dt);
    } else if (!strcmp(op, "state")) {
        g_state = (int)num(1);
    } else if (!strcmp(op, "cops")) {
        g_cops = (int)num(1);
    } else if (!strcmp(op, "vblank")) {
        g_vblank = unum(1);
    } else if (!strcmp(op, "paused")) {
        g_paused = (int)num(1);
    } else if (!strcmp(op, "muted")) {
        snd.muted = (int)num(1);
    } else if (!strcmp(op, "dt")) {
        g_dt = fnum(1);
    } else if (!strcmp(op, "enable")) {
        snd.soundEnabled = (int)num(1);
        snd.musicEnabled = (int)num(2);
    } else if (!strcmp(op, "aob")) {
        ao[num(1)] = (uint8_t)num(2);
    } else if (!strcmp(op, "aow")) {
        uint32_t v = unum(2);
        memcpy(ao + num(1), &v, 4);
    } else if (!strcmp(op, "mode")) {
        audio_mode = (int)num(1);
    } else if (!strcmp(op, "soundup")) {
        sound_up = (int)num(1);
    } else if (!strcmp(op, "cart")) {
        cart_now = (int)num(1);
    } else if (!strcmp(op, "defvol")) {
        jb_default_category_volumes(&snd);
    } else if (!strcmp(op, "oneshots")) {
        snd.firstMenuTune = (int)num(1);
        snd.firstPursuitTune = (int)num(2);
        snd.firstRaceTune = (int)num(3);
        snd.firstAdvance = (int)num(4);
    } else if (!strcmp(op, "dump")) {
        dump();
    } else {
        printf("  unknown op %s\n", op);
    }
}

int main(int argc, char** argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: jukebox_test script cart...\n");
        return 2;
    }
    for (int i = 2; i < argc && i - 1 < 8; i++) {
        FILE* f = fopen(argv[i], "rb");
        if (!f) {
            fprintf(stderr, "no %s\n", argv[i]);
            return 2;
        }
        fseek(f, 0, SEEK_END);
        cart_size[i - 1] = ftell(f);
        fseek(f, 0, SEEK_SET);
        cart[i - 1] = (uint8_t*)malloc((size_t)cart_size[i - 1] + 1);
        if (fread(cart[i - 1], 1, (size_t)cart_size[i - 1], f) !=
            (size_t)cart_size[i - 1]) {
            return 2;
        }
        fclose(f);
    }
    FILE* sc = fopen(argv[1], "r");
    if (!sc) {
        return 2;
    }
    jb_sound_init(&snd, &host, &world);
    static char line[512];
    while (fgets(line, sizeof line, sc)) {
        line[strcspn(line, "\r\n")] = 0;
        if (!line[0]) {
            continue;
        }
        printf("> %s\n", line);
        nargs = 0;
        for (char* t = strtok(line, "|"); t && nargs < 12;
             t = strtok(NULL, "|")) {
            arg[nargs++] = t;
        }
        if (!setjmp(abort_op)) {
            run();
        }
        fflush(stdout);
    }
    fclose(sc);
    return 0;
}
