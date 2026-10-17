// Harness for tools/enginesound_check.py: runs the checker's script on
// enginesound.c and prints what the model prints for the retail image.
// bSample, bSound's regions, Update and GetCategoryVolume, the region and
// in-game samples, sound's random float and audio mode, bMalloc, the ticker,
// bGetFile (which serves the disc's engine.ctb and engine.ltb from the
// directory given), eGetView, IsReplayDemoMode, the race's stage, the car
// type table, DriveTrain's GetState and Sound3d's
// UpdateCamRelativeDistAndVelocity are logging fakes, the same fakes the
// checker gives retail's code. Sound3d's constructor, destructor and
// Activate are copies of sound3d.c's, which sound3d_check.py holds to the
// image; Average is average.c's own, which average_check.py does. See the
// checker's docstring.
//
//     enginesound_test script.txt sound-dir > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "average.h"
#include "bfile.h"
#include "bmem.h"
#include "bsound.h"
#include "bticker.h"
#include "camera.h"
#include "car.h"
#include "carinit.h"
#include "carsound.h"
#include "cartypeinfo.h"
#include "drivetrain.h"
#include "engine.h"
#include "enginesound.h"
#include "eview.h"
#include "physicscar.h"
#include "player.h"
#include "race.h"
#include "racecoord.h"
#include "realtime.h"
#include "sound.h"
#include "sound3d.h"
#include "vtable.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

int32_t          SoundEnabled = 1;
int32_t          CarSoundEnabled = 1;
float            TestRPM = 100.0f;
int32_t          PlayerNumPlayers = 1;
float            WorldTimeSeconds;
float            WorldTimeElapsed;
RaceCoordinator *pRaceCoordinator;
Race            *pCurrentRace;

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

static void *pattern(size_t n)
{
    void *p = malloc(n);

    memset(p, 0xa5, n);
    return p;
}

// ------------------------------------------------------------- the objects

#define MAXCAR   8
#define MAXALLOC 64
#define MAXSRC   64
#define MAXFILE  16
#define MAXVIEW  4

static const char *soundDir;

static Car             *cars[MAXCAR];
static CarTypeInfo      types[MAXCAR];
static CarTypeInfo      rideTypes[MAXCAR];  // cartypeinfo_get's, by ride type
static RideInfo         rides[MAXCAR];
static struct Player    players[MAXCAR];
static PhysicsCar      *movers[MAXCAR];
static DriveTrain      *dts[MAXCAR];
static Engine           engines[MAXCAR];
static EngineInfo       infos[MAXCAR];
static DriveTrainState  dtStates[MAXCAR];
static Sound3d         *snds[MAXCAR];
static eView            views[MAXVIEW];
static Camera           cams[MAXVIEW];
static RaceCoordinator  rc;
static int              raceStore;
static int32_t          raceStage;
static int32_t          replayDemo;
static int32_t          audioMode;
static float            catVolume;

static struct {
    void       *p;
    const char *tag;
} allocs[MAXALLOC];
static int nallocs;

// The samples bRegion::Sample and GetInGameSample hand out, one a name;
// `missing` and `nosrc` names get none.
static struct {
    char    nm[32];
    int     ingame;
    BSample s;
} srcs[MAXSRC];
static int nsrcs;
static char missing[8][32];
static int  nmissing;
static char nosrc[8][32];
static int  nnosrc;

static struct {
    char nm[32];
    int  r;
} regions[8];
static int nregions;
static int fakebsound;
static SoundModule fakemod;

static void *files[MAXFILE];
static int   nfiles;

static uint32_t randF[64];
static int      nRandF, atRandF;

static uint32_t tick, tickStep = 7;

// bSample's playing flag, by sample.
static const BSample *playing[128];
static int            nplaying;

static int is_playing(const BSample *s)
{
    int i;

    for (i = 0; i < nplaying; i++)
        if (playing[i] == s)
            return 1;
    return 0;
}

static void set_playing(const BSample *s, int on)
{
    int i;

    for (i = 0; i < nplaying; i++) {
        if (playing[i] == s) {
            if (!on)
                playing[i] = playing[--nplaying];
            return;
        }
    }
    if (on && nplaying < 128)
        playing[nplaying++] = s;
}

static const char *name(const void *p)
{
    static char buf[8][48];
    static int k;
    char *b = buf[k++ & 7];
    int i, j;

    if (p == NULL)
        return "0";
    for (i = 0; i < nallocs; i++) {
        const char *t = allocs[i].tag;

        if (p == allocs[i].p) {
            sprintf(b, "m%d", i);
            return b;
        }
        if (!strcmp(t, "PlayerEngineSound")) {
            PlayerEngineSound *s = allocs[i].p;

            if (p == &s->NitroStartSample) {
                sprintf(b, "m%d.ns", i);
                return b;
            }
            if (p == &s->NitroLoopSample) {
                sprintf(b, "m%d.nl", i);
                return b;
            }
            for (j = 0; j < ENGINESOUND_VOICES; j++) {
                if (p == &s->left[j].sample) {
                    sprintf(b, "m%d.l%d", i, j);
                    return b;
                }
                if (p == &s->right[j].sample) {
                    sprintf(b, "m%d.r%d", i, j);
                    return b;
                }
            }
        }
        if (!strcmp(t, "AIEngineSound")) {
            AIEngineSound *s = allocs[i].p;

            if (p == &s->EngineSample) {
                sprintf(b, "m%d.s", i);
                return b;
            }
            if (p == &s->RPMAverage) {
                sprintf(b, "m%d.avg", i);
                return b;
            }
        }
    }
    for (i = 0; i < nsrcs; i++) {
        if (p == &srcs[i].s) {
            sprintf(b, "%s:%s", srcs[i].ingame ? "src" : "rs", srcs[i].nm);
            return b;
        }
    }
    for (i = 0; i < nregions; i++) {
        if (p == &regions[i].r) {
            sprintf(b, "reg:%s", regions[i].nm);
            return b;
        }
    }
    for (i = 0; i < nfiles; i++) {
        if (p == files[i]) {
            sprintf(b, "f%d", i);
            return b;
        }
    }
    for (i = 0; i < MAXCAR; i++) {
        if (cars[i] == NULL)
            continue;
        if (p == cars[i]) {
            sprintf(b, "car%d", i);
            return b;
        }
        if (p == &cars[i]->State.Position) {
            sprintf(b, "car%d.pos", i);
            return b;
        }
    }
    return "?";
}

static const char *vtname(uint32_t v)
{
    switch (v) {
    case PLAYERENGINESOUND_VTABLE: return "player";
    case AIENGINESOUND_VTABLE:     return "ai";
    case SOUND3D_VTABLE:           return "s3d";
    }
    return "?";
}

// ------------------------------------------------------------- Sound3d

// sound3d.c's three, as they are there.
void sound3d_construct(Sound3d *s)
{
    s->_vtable = SOUND3D_VTABLE;
    s->DopplerIsActive = 1;
    s->Pitch = 1.0f;
    s->Activated = 0;
    s->Volume = 1.0f;
    s->Azimuth = 0;
    s->SndToCameraVelocity = 0.0f;
    s->SndToCameraDistance = 0.0f;
}

void sound3d_destroy(Sound3d *s, int32_t flags)
{
    s->_vtable = SOUND3D_VTABLE;
    if (flags & 1)
        bFree(s);
}

typedef void (*VtVoidFn)(void *self);

void sound3d_activate(Sound3d *s, int32_t on)
{
    const VtEntry *e;

    if (!on) {
        e = vt_slot(s->_vtable, SOUND3D_VT_DEACTIVATE);
        ((VtVoidFn)e->fn)(vt_this(s, e));
    } else if (!s->Activated) {
        e = vt_slot(s->_vtable, SOUND3D_VT_ACTIVATESOUND);
        ((VtVoidFn)e->fn)(vt_this(s, e));
    }
    s->Activated = on;
}

void sound3d_update_cam_relative_dist_and_velocity(Sound3d *s,
                                                   const bVector3 *pos)
{
    printf("  camrel %s pos=%s\n", name(s), name(pos));
}

// --------------------------------------------------------------- bSample

// Retail's bSample() takes no type; the port's 0 is not printed.
void bsample_construct(BSample *s, int8_t type)
{
    (void)type;
    printf("  bctor %s\n", name(s));
}

void bsample_destruct(BSample *s)
{
    printf("  bdtor %s\n", name(s));
}

void bsample_initialize_copy(BSample *s, const BSample *other)
{
    printf("  binit %s from %s\n", name(s), name(other));
}

void bsample_set_category(BSample *s, uint32_t category)
{
    printf("  bcat %s %u\n", name(s), category);
}

BVoice *bsample_play(BSample *s, float volume, float pan, float pitch)
{
    printf("  bplay %s %08x %08x %08x\n", name(s), bits(volume), bits(pan),
           bits(pitch));
    set_playing(s, 1);
    return NULL;
}

void bsample_stop(BSample *s)
{
    printf("  bstop %s\n", name(s));
    set_playing(s, 0);
}

void bsample_pause(BSample *s, bool pause)
{
    printf("  bpause %s %d\n", name(s), pause ? 1 : 0);
}

void bsample_set_azimuth(BSample *s, uint16_t azimuth)
{
    printf("  baz %s %d\n", name(s), azimuth);
}

void bsample_set_volume(BSample *s, float volume)
{
    printf("  bvol %s %08x\n", name(s), bits(volume));
}

int32_t bsample_set_pitch(BSample *s, float pitch)
{
    printf("  bpitch %s %08x\n", name(s), bits(pitch));
    return 0;
}

bool bsample_is_playing(const BSample *s)
{
    int v = is_playing(s);

    printf("  bisplaying %s %d\n", name(s), v);
    return v != 0;
}

void bsample_lock_voice(BSample *s)
{
    printf("  block %s\n", name(s));
}

// ---------------------------------------------------------------- bSound

BSound *bsound_get(void)
{
    return (BSound *)(void *)&fakebsound;
}

static void check_bsound(const BSound *s, const char *what)
{
    if (s != (const BSound *)(void *)&fakebsound)
        printf("  %s: not bSound's\n", what);
}

BRegion *bsound_region(const BSound *s, const char *nm)
{
    int i;

    printf("  region %s\n", nm);
    check_bsound(s, "region");
    for (i = 0; i < nregions; i++)
        if (!strcmp(regions[i].nm, nm))
            return (BRegion *)(void *)&regions[i].r;
    strcpy(regions[nregions].nm, nm);
    return (BRegion *)(void *)&regions[nregions++].r;
}

void bsound_update(BSound *s)
{
    printf("  bsupdate\n");
    check_bsound(s, "update");
}

float bsound_get_category_volume(const BSound *s, uint32_t category)
{
    printf("  catvol %u -> %08x\n", category, bits(catVolume));
    check_bsound(s, "catvol");
    return catVolume;
}

static int listed(char (*list)[32], int n, const char *nm)
{
    int i;

    for (i = 0; i < n; i++)
        if (!strcmp(list[i], nm))
            return 1;
    return 0;
}

static BSample *src(const char *nm, int ingame)
{
    int i;

    for (i = 0; i < nsrcs; i++)
        if (srcs[i].ingame == ingame && !strcmp(srcs[i].nm, nm))
            return &srcs[i].s;
    strcpy(srcs[nsrcs].nm, nm);
    srcs[nsrcs].ingame = ingame;
    return &srcs[nsrcs++].s;
}

BSample *bregion_sample(const BRegion *r, const char *nm)
{
    printf("  rsample %s %s\n", name(r), nm);
    if (listed(missing, nmissing, nm))
        return NULL;
    return src(nm, 0);
}

// ---------------------------------------------------------------- sound

SoundModule *sound_get(void)
{
    return &fakemod;
}

BSample *sound_get_in_game_sample(SoundModule *m, const char *nm)
{
    printf("  ingame %s\n", nm);
    if (m != &fakemod)
        printf("  ingame: not the module\n");
    if (listed(nosrc, nnosrc, nm))
        return NULL;
    return src(nm, 1);
}

float sound_random_float(SoundModule *m, float range)
{
    uint32_t v = atRandF < nRandF ? randF[atRandF++] : 0;

    (void)m;
    printf("  randf %08x -> %08x\n", bits(range), v);
    return unbits(v);
}

// Not printed: the port's mono build never asks.
int32_t sound_get_audio_mode(const SoundModule *m)
{
    (void)m;
    return audioMode;
}

// ------------------------------------------------------------ the heap

static const char *alloc_ok(const char *tag, int size)
{
    int want = -1;

    if (!strcmp(tag, "PlayerEngineSound"))
        want = (int)sizeof(PlayerEngineSound);
    else if (!strcmp(tag, "AIEngineSound"))
        want = (int)sizeof(AIEngineSound);
    else if (!strcmp(tag, "..\\indep\\src\\table.cpp"))
        want = 20 * (int)sizeof(float);
    return size == want ? "ok" : "BAD";
}

void *bMalloc(int size, const char *tag, int flags, int pool)
{
    void *p = pattern((size_t)size);

    allocs[nallocs].p = p;
    allocs[nallocs].tag = tag;
    nallocs++;
    printf("  malloc %s %d %d size-%s -> m%d\n", tag, flags, pool,
           alloc_ok(tag, size), nallocs - 1);
    return p;
}

void bFree(void *p)
{
    printf("  delete %s\n", name(p));
}

// ------------------------------------------------------------ the rest

uint32_t bGetTicker(void)
{
    uint32_t v = tick;

    tick += tickStep;
    printf("  ticker -> %u\n", v);
    return v;
}

float bGetTickerDifference(uint32_t from, uint32_t to)
{
    float d = (float)(uint32_t)(to - from);

    printf("  tickdiff %u %u -> %08x\n", from, to, bits(d));
    return d;
}

// The disc's file, by the name's last part in upper case.
void *bGetFile(const char *nm, int32_t *size, int32_t pool)
{
    char path[512], base[64];
    const char *slash = strrchr(nm, '\\');
    FILE *fh;
    long n;
    void *p;
    int i;

    strcpy(base, slash ? slash + 1 : nm);
    for (i = 0; base[i]; i++)
        if (base[i] >= 'a' && base[i] <= 'z')
            base[i] = (char)(base[i] - 32);
    sprintf(path, "%s/%s", soundDir, base);
    fh = fopen(path, "rb");
    if (fh == NULL) {
        printf("  getfile %s: no %s\n", nm, path);
        exit(3);
    }
    fseek(fh, 0, SEEK_END);
    n = ftell(fh);
    fseek(fh, 0, SEEK_SET);
    p = malloc((size_t)n);
    if (fread(p, 1, (size_t)n, fh) != (size_t)n)
        exit(3);
    fclose(fh);
    files[nfiles] = p;
    printf("  getfile %s %s %d -> f%d\n", nm, size ? "size" : "0", pool,
           nfiles);
    nfiles++;
    return p;
}

eView *eGetView(int32_t id)
{
    printf("  view %d\n", id);
    return &views[id];
}

int32_t racecoordinator_is_replay_demo_mode(const RaceCoordinator *r)
{
    printf("  rdm %s -> %d\n", r == &rc ? "rc" : "?", replayDemo);
    return replayDemo;
}

// Retail reads the stage inline: not printed.
eRaceStage race_get_race_stage(const Race *r)
{
    (void)r;
    return (eRaceStage)raceStage;
}

const CarTypeInfo *cartypeinfo_get(int32_t carType)
{
    return &rideTypes[carType];
}

DriveTrainState *drivetrain_get_state(DriveTrain *d)
{
    int k;

    for (k = 0; k < MAXCAR; k++) {
        if (d == dts[k]) {
            printf("  dtstate dt%d\n", k);
            return &dtStates[k];
        }
    }
    printf("  dtstate ?\n");
    return &dtStates[0];
}

// ------------------------------------------------------------ the dumps

typedef struct Field {
    const char *nm;
    size_t      off;
    char        t;
} Field;

#define PF(n, f, t) { n, offsetof(PlayerEngineSound, f), t }
#define AF(n, f, t) { n, offsetof(AIEngineSound, f), t }

static const Field pfields[] = {
    PF("act", Sound.Activated, 'i'),
    PF("dop", Sound.DopplerIsActive, 'i'),
    PF("svol", Sound.Volume, 'f'),
    PF("spitch", Sound.Pitch, 'f'),
    PF("saz", Sound.Azimuth, 'H'),
    PF("thr", CurrThrottle, 'i'),
    PF("redoff", RedLineRPMOffset, 'f'),
    PF("topoff", TopGearRPMOffset, 'f'),
    PF("gsvs", GearShiftVolumeScale, 'f'),
    PF("gsup", GearShiftingUp, 'i'),
    PF("brt", UpdateBlownRodTime, 'f'),
    PF("bh", bHandle, 'B'),
    PF("vol", Volume, 'i'),
    PF("ratio", Ratio, 'i'),
    PF("dopp", Doppler, 'H'),
    PF("azim", Azim, 'H'),
    PF("sep", Seperation, 'H'),
    PF("timbre", Timbre, 'b'),
    PF("hp", HighestPatch, 'b'),
    PF("cl", ControllerLevel, 'h'),
    PF("clt", ControllerLevelTarget, 'h'),
    PF("cur", CurrentLevel, 'h'),
    PF("bend", BendRange, 'i'),
    PF("bass", BassAdd, 'i'),
    PF("pov0", POVTimbre[0], 'h'),
    PF("pov1", POVTimbre[1], 'h'),
    PF("pov2", POVTimbre[2], 'h'),
    PF("pov3", POVTimbre[3], 'h'),
    PF("stereo", IsStereo, 'i'),
    PF("bfb", EngineBackfireBuildup, 'i'),
    PF("rpm", CurrentRPM, 'f'),
    PF("dtime", fEngineDuckerThrottleTime, 'f'),
    PF("dscale", fEngineDuckerVolumeScale, 'f'),
    PF("mode", CurrAudioMode, 'i'),
};

static const Field afields[] = {
    AF("act", Sound.Activated, 'i'),
    AF("dop", Sound.DopplerIsActive, 'i'),
    AF("svol", Sound.Volume, 'f'),
    AF("spitch", Sound.Pitch, 'f'),
    AF("saz", Sound.Azimuth, 'H'),
    AF("base", EnginePitchBase, 'f'),
    AF("tgt", StartLineTargetPitch, 'f'),
    AF("curp", StartLineCurrPitch, 'f'),
    AF("slots", RPMAverage.nSlots, 'B'),
    AF("slot", RPMAverage.nCurrentSlot, 'B'),
    AF("n", RPMAverage.nSamples, 'B'),
    AF("total", RPMAverage.fTotal, 'f'),
    AF("mean", RPMAverage.fAverage, 'f'),
    AF("gear", CurrGear, 'i'),
    AF("frames", GearFrames, 'i'),
    AF("srpm", SmoothRPM, 'f'),
    AF("gvs", GearVolumeScale, 'f'),
};

#define NFIELDS(t) ((int)(sizeof(t) / sizeof((t)[0])))

static void print_field(const void *base, const Field *f)
{
    const char *p = (const char *)base + f->off;

    switch (f->t) {
    case 'i': printf(" %s=%d", f->nm, *(const int32_t *)p); break;
    case 'h': printf(" %s=%d", f->nm, *(const int16_t *)p); break;
    case 'H': printf(" %s=%d", f->nm, *(const uint16_t *)p); break;
    case 'b': printf(" %s=%d", f->nm, *(const int8_t *)p); break;
    case 'B': printf(" %s=%d", f->nm, *(const uint8_t *)p); break;
    case 'f': printf(" %s=%08x", f->nm, bits(*(const float *)p)); break;
    }
}

static void set_field(void *base, const Field *fs, int n, const char *nm,
                      const char *v)
{
    int i;

    for (i = 0; i < n; i++) {
        char *p = (char *)base + fs[i].off;
        long x = strtol(v, NULL, 0);

        if (strcmp(fs[i].nm, nm))
            continue;
        switch (fs[i].t) {
        case 'i': *(int32_t *)p = (int32_t)x; break;
        case 'h': *(int16_t *)p = (int16_t)x; break;
        case 'H': *(uint16_t *)p = (uint16_t)x; break;
        case 'b': *(int8_t *)p = (int8_t)x; break;
        case 'B': *(uint8_t *)p = (uint8_t)x; break;
        case 'f': *(float *)p = unbits((uint32_t)strtoul(v, NULL, 16));
            break;
        }
        return;
    }
    printf("  no field %s\n", nm);
}

static void dump_player(int k)
{
    PlayerEngineSound *s = (PlayerEngineSound *)snds[k];
    int i;

    printf("  pd %s vt=%s car=%s", name(s), vtname(s->Sound._vtable),
           name(s->pCar));
    for (i = 0; i < NFIELDS(pfields); i++)
        print_field(s, &pfields[i]);
    printf(" sync=%08x\n", bits(cars[k]->State.RedLineSyncRPM));
    printf("  left");
    for (i = 0; i < ENGINESOUND_VOICES; i++)
        printf(" %d/%d/%08x/%d", s->left[i].vol, s->left[i].bend,
               bits(s->left[i].pitch), s->left[i].azim);
    printf("\n  right");
    for (i = 0; i < ENGINESOUND_VOICES; i++)
        printf(" %d/%d/%08x/%d", s->right[i].vol, s->right[i].bend,
               bits(s->right[i].pitch), s->right[i].azim);
    printf("\n  delay");
    for (i = 0; i < ENGINESOUND_VOICES; i++)
        printf(" %d", s->delay[i]);
    printf("\n  es");
    for (i = 0; i < ENGINESOUND_PATCHES; i++) {
        const EngineSample *e = &s->engineSample[i];

        printf(" %d/%d/%d/%s/%d/%08x", e->bnkID, e->patchtype, e->isEnabled,
               name(e->sample), e->detune, bits(e->volume));
    }
    printf("\n  defs %s %s\n", name(s->definitions[0]),
           name(s->definitions[1]));
}

static void dump_ai(int k)
{
    AIEngineSound *s = (AIEngineSound *)snds[k];
    int i;

    printf("  ad %s vt=%s car=%s", name(s), vtname(s->Sound._vtable),
           name(s->pCar));
    for (i = 0; i < NFIELDS(afields); i++)
        print_field(s, &afields[i]);
    printf(" data=%s\n  avg", name(s->RPMAverage.pData));
    for (i = 0; i < 20; i++)
        printf(" %08x", bits(s->RPMAverage.pData[i]));
    printf("\n");
}

static const struct {
    VtFn fn;
    const char *nm;
} fnames[] = {
    { (VtFn)playerenginesound_destroy, "player-dtor" },
    { (VtFn)sound3d_activate, "activate" },
    { (VtFn)playerenginesound_update, "player-update" },
    { (VtFn)playerenginesound_mute, "player-mute" },
    { (VtFn)playerenginesound_deactivate_sound, "player-deact" },
    { (VtFn)playerenginesound_activate_sound, "player-act" },
    { (VtFn)sound3d_update_cam_relative_dist_and_velocity, "camrel" },
    { (VtFn)aienginesound_destroy, "ai-dtor" },
    { (VtFn)aienginesound_update, "ai-update" },
    { (VtFn)aienginesound_mute, "ai-mute" },
    { (VtFn)aienginesound_deactivate_sound, "ai-deact" },
    { (VtFn)aienginesound_activate_sound, "ai-act" },
};

static void dump_tables(void)
{
    static const struct {
        const char *label;
        uint32_t vt;
    } t[] = {
        { "player", PLAYERENGINESOUND_VTABLE },
        { "ai", AIENGINESOUND_VTABLE },
    };
    size_t i, j;
    int k, n;

    for (i = 0; i < sizeof(t) / sizeof(t[0]); i++) {
        const VtEntry *e = vt_table(t[i].vt, &n);

        if (e == NULL) {
            printf("  vt %s missing\n", t[i].label);
            continue;
        }
        printf("  vt %s %d entries\n", t[i].label, n);
        for (k = 1; k < n; k++) {
            const char *nm = "?";

            for (j = 0; j < sizeof(fnames) / sizeof(fnames[0]); j++)
                if (fnames[j].fn == e[k].fn)
                    nm = fnames[j].nm;
            printf("  vt %s %d %d %s\n", t[i].label, 8 * k, e[k].delta, nm);
        }
    }
}

// ------------------------------------------------------------- the ops

typedef void (*VtDestroyFn)(void *self, int32_t flags);
typedef void (*VtActivateFn)(void *self, int32_t on);
typedef void (*VtUpdateFn)(void *self, float volume, uint16_t azimuth,
                           float pitch);
typedef void (*VtMuteFn)(void *self, int32_t on);
typedef void (*VtCamRelativeFn)(void *self, const bVector3 *pos);

static PlayerEngineSound *pes(int k)
{
    return (PlayerEngineSound *)snds[k];
}

static EngineVoiceAttr *voice(int k, const char *side, int i)
{
    return side[0] == 'r' ? &pes(k)->right[i] : &pes(k)->left[i];
}

static BSample *sample_ref(int k, const char *w)
{
    if (!strcmp(w, "ns"))
        return &pes(k)->NitroStartSample;
    if (!strcmp(w, "nl"))
        return &pes(k)->NitroLoopSample;
    if (!strcmp(w, "s"))
        return &((AIEngineSound *)snds[k])->EngineSample;
    return &voice(k, w, atoi(w + 1))->sample;
}

static void new_car(int k, int usage, int aieng, int view, int pov)
{
    Car *c = cars[k] = pattern(sizeof(Car));
    PhysicsCar *m = movers[k] = pattern(sizeof(PhysicsCar));
    DriveTrain *d = dts[k] = pattern(sizeof(DriveTrain));
    CarTypeInfo *t = &types[k];

    memset(t, 0, sizeof(*t));
    sprintf(t->Sound.BaseName, "Car%d", k);
    sprintf(t->Sound.Prefix, "P%d", k);
    t->Sound.AIEngineNumber = (int16_t)aieng;
    rides[k].Type = k;
    memset(&rideTypes[k], 0, sizeof(rideTypes[k]));
    rideTypes[k].UsageType = usage;
    memset(&players[k], 0, sizeof(players[k]));
    players[k].ViewID = view;
    players[k].PlayerSettings.DriveCameraPOVIndex = (int8_t)pov;
    memset(&engines[k], 0, sizeof(engines[k]));
    memset(&infos[k], 0, sizeof(infos[k]));
    memset(&dtStates[k], 0, sizeof(dtStates[k]));
    engines[k].EI = &infos[k];
    m->pDriveTrain = d;
    d->pEngine = &engines[k];
    d->CurrentGear = d->DesiredGear = (Gear)2;
    d->CurrentClutchState = CLUTCH_ENGAGED;
    c->pCarTypeInfo = t;
    c->pRideInfo = &rides[k];
    c->pPlayer = &players[k];
    c->TheMovementMode = PHYSICS_MOVEMENT;
    c->pCarMover = (CarMover *)(void *)m;
    c->State.Position.x = c->State.Position.y = 0.0f;
    c->State.Position.z = c->State.Position.pad = 0.0f;
    c->State.BodyMatrix.v0.x = 1.0f;
    c->State.BodyMatrix.v0.y = c->State.BodyMatrix.v0.z = 0.0f;
    c->State.BodyMatrix.v0.w = 0.0f;
    c->State.VelocityMagnitude = 0.0f;
    c->State.CurrentGear = (Gear)2;
    c->State.Throttle = 0.0f;
    c->State.RPM = 1000.0f;
    c->State.RedLineSyncRPM = 0.0f;
}

static void op(char **f, int nf)
{
    const char *o = f[0];
    int k;

#define I(n) ((n) < nf ? (int)strtol(f[n], NULL, 0) : 0)
#define FB(n) ((n) < nf ? unbits((uint32_t)strtoul(f[n], NULL, 16)) : 0.0f)

    if (!strcmp(o, "tables")) {
        dump_tables();
    } else if (!strcmp(o, "se")) {
        SoundEnabled = I(1);
    } else if (!strcmp(o, "cse")) {
        CarSoundEnabled = I(1);
    } else if (!strcmp(o, "npp")) {
        PlayerNumPlayers = I(1);
    } else if (!strcmp(o, "trpm")) {
        TestRPM = FB(1);
    } else if (!strcmp(o, "wts")) {
        WorldTimeSeconds = FB(1);
    } else if (!strcmp(o, "wte")) {
        WorldTimeElapsed = FB(1);
    } else if (!strcmp(o, "am")) {
        audioMode = I(1);
    } else if (!strcmp(o, "rcs")) {
        rc.CurrentRCState = (RCState)I(1);
    } else if (!strcmp(o, "rdm")) {
        replayDemo = I(1);
    } else if (!strcmp(o, "race")) {
        raceStage = I(1);
        pCurrentRace = raceStage < 0 ? NULL : (Race *)(void *)&raceStore;
    } else if (!strcmp(o, "catvol")) {
        catVolume = FB(1);
    } else if (!strcmp(o, "rf")) {
        randF[nRandF++] = (uint32_t)strtoul(f[1], NULL, 16);
    } else if (!strcmp(o, "tick")) {
        tickStep = (uint32_t)I(1);
    } else if (!strcmp(o, "missing")) {
        strcpy(missing[nmissing++], f[1]);
    } else if (!strcmp(o, "nosrc")) {
        strcpy(nosrc[nnosrc++], f[1]);
    } else if (!strcmp(o, "car")) {
        new_car(I(1), I(2), I(3), I(4), I(5));
    } else if (!strcmp(o, "snd")) {
        SoundInfo *si = &types[I(1)].Sound;
        int i;

        si->IdleOffset = (int16_t)I(2);
        for (i = 0; i < 4; i++)
            si->Timbre[i] = (char)I(3 + i);
        si->BendRange = (int16_t)I(7);
        si->BaseAdd = (int16_t)I(8);
        si->RedLineOffset = (int16_t)I(9);
        si->TopGearOffset = (int16_t)I(10);
    } else if (!strcmp(o, "det")) {
        int i;

        for (i = 0; i < 12; i++)
            types[I(1)].Sound.Detune[i] = (int16_t)I(2 + i);
    } else if (!strcmp(o, "vols")) {
        int i;

        for (i = 0; i < 12; i++)
            types[I(1)].Sound.Volume[i] = FB(2 + i);
    } else if (!strcmp(o, "tinfo")) {
        types[I(1)].Engine.MaxRPM = FB(2);
        types[I(1)].DriveTrain.NumGears = I(3);
    } else if (!strcmp(o, "mode")) {
        cars[I(1)]->TheMovementMode = (MovementMode)I(2);
    } else if (!strcmp(o, "st")) {
        Car *c = cars[I(1)];

        c->State.VelocityMagnitude = FB(2);
        c->State.CurrentGear = (Gear)I(3);
        c->State.Throttle = FB(4);
        c->State.RPM = FB(5);
    } else if (!strcmp(o, "pos")) {
        Car *c = cars[I(1)];

        c->State.Position.x = FB(2);
        c->State.Position.y = FB(3);
        c->State.Position.z = FB(4);
    } else if (!strcmp(o, "bm")) {
        Car *c = cars[I(1)];

        c->State.BodyMatrix.v0.x = FB(2);
        c->State.BodyMatrix.v0.y = FB(3);
        c->State.BodyMatrix.v0.z = FB(4);
    } else if (!strcmp(o, "dt")) {
        DriveTrain *d = dts[I(1)];

        d->CurrentGear = (Gear)I(2);
        d->DesiredGear = (Gear)I(3);
        d->CurrentClutchState = (ClutchState)I(4);
        dtStates[I(1)].clutch = FB(5);
    } else if (!strcmp(o, "shift")) {
        dts[I(1)]->ShiftUpRPM[I(2)] = FB(3);
    } else if (!strcmp(o, "einfo")) {
        infos[I(1)].RedLineRPM = FB(2);
        infos[I(1)].MaxRPM = FB(3);
    } else if (!strcmp(o, "nitro")) {
        engines[I(1)].NitroFlag = I(2);
        engines[I(1)].NitroBoostTimer = FB(3);
    } else if (!strcmp(o, "cam")) {
        Camera *c = &cams[I(1)];

        views[I(1)].pCamera = c;
        c->CurrentKey.Position.x = FB(2);
        c->CurrentKey.Position.y = FB(3);
        c->CurrentKey.Position.z = FB(4);
        c->CurrentKey.Direction.x = FB(5);
        c->CurrentKey.Direction.y = FB(6);
        c->CurrentKey.Direction.z = FB(7);
    } else if (!strcmp(o, "view")) {
        players[I(1)].ViewID = I(2);
    } else if (!strcmp(o, "pov")) {
        players[I(1)].PlayerSettings.DriveCameraPOVIndex = (int8_t)I(2);
    } else if (!strcmp(o, "mk")) {
        k = I(1);
        if (!strcmp(f[2], "player"))
            snds[k] = enginesound_create_player(cars[k]);
        else
            snds[k] = enginesound_create_ai(cars[k]);
        printf("  -> %s\n", name(snds[k]));
    } else if (!strcmp(o, "lpes")) {
        printf("  last %s\n", name(LastPlayerEngineSound));
    } else if (!strcmp(o, "vc")) {
        Sound3d *t = snds[I(1)];
        int slot = I(2);
        const VtEntry *e = vt_slot(t->_vtable, slot);
        void *self = vt_this(t, e);

        switch (slot) {
        case 8:
            ((VtDestroyFn)e->fn)(self, I(3));
            break;
        case 16:
            ((VtActivateFn)e->fn)(self, I(3));
            break;
        case 24:
            ((VtUpdateFn)e->fn)(self, FB(3), (uint16_t)I(4), FB(5));
            break;
        case 32:
            ((VtMuteFn)e->fn)(self, I(3));
            break;
        case 40:
        case 48:
            ((VtVoidFn)e->fn)(self);
            break;
        case 56:
            ((VtCamRelativeFn)e->fn)(self, &cars[I(3)]->State.Position);
            break;
        }
    } else if (!strcmp(o, "ramp")) {
        playerenginesound_ramp_throttle(pes(I(1)));
    } else if (!strcmp(o, "gear")) {
        playerenginesound_update_gear_shift_effect(pes(I(1)));
    } else if (!strcmp(o, "redline")) {
        float r = FB(2);

        playerenginesound_update_to_red_line_rpm(pes(I(1)), &r);
        printf("  = %08x\n", bits(r));
    } else if (!strcmp(o, "nitroe")) {
        playerenginesound_update_nitro_effect(pes(I(1)), FB(2),
                                              (uint16_t)I(3), FB(4));
    } else if (!strcmp(o, "ducker")) {
        playerenginesound_update_engine_ducker(pes(I(1)));
    } else if (!strcmp(o, "ueng")) {
        playerenginesound_update_engine(pes(I(1)));
    } else if (!strcmp(o, "setc")) {
        playerenginesound_set(pes(I(1)), I(2), I(3), I(4), I(5), I(6), I(7),
                              FB(8), I(9));
    } else if (!strcmp(o, "resolve")) {
        playerenginesound_resolve_tables(pes(I(1)));
    } else if (!strcmp(o, "init")) {
        playerenginesound_init(pes(I(1)));
    } else if (!strcmp(o, "vplay")) {
        EnginePlayOptions po;

        po.vol = (int16_t)I(4);
        po.bend = (int16_t)I(5);
        po.pitch = FB(6);
        po.azimuth = (uint16_t)I(7);
        po.elevation = (uint16_t)I(8);
        enginevoice_play(voice(I(1), f[2], I(3)), &po);
    } else if (!strcmp(o, "vstop")) {
        enginevoice_stop(voice(I(1), f[2], I(3)));
    } else if (!strcmp(o, "vvol")) {
        enginevoice_set_volume(voice(I(1), f[2], I(3)), (int16_t)I(4));
    } else if (!strcmp(o, "vpitch")) {
        enginevoice_set_pitch(voice(I(1), f[2], I(3)), FB(4));
    } else if (!strcmp(o, "vaz")) {
        enginevoice_set_azimuth(voice(I(1), f[2], I(3)), (uint16_t)I(4));
    } else if (!strcmp(o, "vset")) {
        EngineVoiceAttr *v = voice(I(1), f[2], I(3));

        v->vol = (int16_t)I(4);
        v->bend = (int16_t)I(5);
        v->pitch = FB(6);
        v->azim = (uint16_t)I(7);
    } else if (!strcmp(o, "pset")) {
        set_field(snds[I(1)], pfields, NFIELDS(pfields), f[2], f[3]);
    } else if (!strcmp(o, "aset")) {
        set_field(snds[I(1)], afields, NFIELDS(afields), f[2], f[3]);
    } else if (!strcmp(o, "delay")) {
        pes(I(1))->delay[I(2)] = (int8_t)I(3);
    } else if (!strcmp(o, "es")) {
        EngineSample *e = &pes(I(1))->engineSample[I(2)];

        e->bnkID = I(3);
        e->patchtype = (int16_t)I(4);
        e->isEnabled = (int16_t)I(5);
        e->detune = I(6);
        e->volume = FB(7);
    } else if (!strcmp(o, "pcar")) {
        pes(I(1))->pCar = I(2) ? cars[I(1)] : NULL;
    } else if (!strcmp(o, "tpatch")) {
        pes(I(1))->definitions[I(2)]->patchnum[I(3)] = (int8_t)I(4);
    } else if (!strcmp(o, "tres")) {
        pes(I(1))->definitions[I(2)]->resolved = (int8_t)I(3);
    } else if (!strcmp(o, "tvol")) {
        EngineDef *d = pes(I(1))->definitions[I(2)];
        int a = I(3);

        ((int8_t *)&d->pvoltable[a] + d->pvoltable[a])[I(4)] = (int8_t)I(5);
    } else if (!strcmp(o, "tdump")) {
        EngineDef *d = pes(I(1))->definitions[I(2)];
        int a, l;

        printf("  def id=%08x ver=%d res=%d pn=", (uint32_t)d->id, d->ver,
               d->resolved);
        for (a = 0; a < 8; a++)
            printf("%d%s", d->patchnum[a], a < 7 ? "," : "");
        printf("\n");
        // A slot with no patch has no table: retail's ResolveTables points
        // it at its own field.
        for (a = 0; a < 8; a++) {
            const int8_t *t = (const int8_t *)&d->pvoltable[a]
                              + d->pvoltable[a];

            if (d->patchnum[a] < 0) {
                printf("  vt%d -\n", a);
                continue;
            }
            printf("  vt%d", a);
            for (l = 0; l < 441; l += 20)
                printf(" %d", t[l]);
            printf("\n");
        }
    } else if (!strcmp(o, "bplaying")) {
        set_playing(sample_ref(I(1), f[2]), I(3));
    } else if (!strcmp(o, "cv")) {
        ((AIEngineSound *)snds[I(1)])->EngineSample.currentVolume = FB(2);
    } else if (!strcmp(o, "aname")) {
        printf("  -> %s\n", aienginesound_get_engine_sample_name(
                                (AIEngineSound *)snds[I(1)]));
    } else if (!strcmp(o, "arpm")) {
        printf("  = %08x\n", bits(aienginesound_compute_rpm_pitch_shift(
                                (AIEngineSound *)snds[I(1)])));
    } else if (!strcmp(o, "astart")) {
        printf("  = %08x\n", bits(
                   aienginesound_compute_start_line_rpm_pitch_shift(
                       (AIEngineSound *)snds[I(1)])));
    } else if (!strcmp(o, "acar")) {
        ((AIEngineSound *)snds[I(1)])->pCar = cars[I(2)];
    } else if (!strcmp(o, "pd")) {
        dump_player(I(1));
    } else if (!strcmp(o, "ad")) {
        dump_ai(I(1));
    } else {
        printf("  unknown op %s\n", o);
    }
#undef I
#undef FB
}

int main(int argc, char **argv)
{
    char line[512];
    FILE *fh;

    if (argc < 3) {
        fprintf(stderr, "usage: enginesound_test script.txt sound-dir\n");
        return 2;
    }
    fh = fopen(argv[1], "r");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
    soundDir = argv[2];
    pRaceCoordinator = &rc;

    enginesound_install_vtables();
    vt_install(SOUND3D_VTABLE, NULL, 0);

    while (fgets(line, sizeof(line), fh)) {
        char *f[32];
        int nf = 0;
        char *p;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        printf("> %s\n", line);
        p = line;
        f[nf++] = p;
        while ((p = strchr(p, '|')) != NULL && nf < 32) {
            *p++ = 0;
            f[nf++] = p;
        }
        op(f, nf);
        fflush(stdout);
    }
    fclose(fh);
    return 0;
}
