// Harness for tools/tiresound_check.py: runs the checker's script on
// tiresound.c and prints what the model prints for the retail image.
// bSample, bSound's regions, GetCategoryVolume and Flush, the region and
// in-game samples, sound's random float, the jukebox's saved volume,
// bMalloc and Sound3d's UpdateCamRelativeDistAndVelocity are logging fakes,
// the same fakes the checker gives retail's code. Sound3d's constructor,
// destructor and Activate are copies of sound3d.c's, which
// sound3d_check.py holds to the image; TerrainTypeInfoTable is
// terraintypetab.c's own, which gen_terrain_table.py --check does. See the
// checker's docstring.
//
//     tiresound_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bsound.h"
#include "car.h"
#include "carsound.h"
#include "jukebox.h"
#include "realtime.h"
#include "sound.h"
#include "sound3d.h"
#include "terraintype.h"
#include "tiresound.h"
#include "track.h"
#include "vtable.h"

int32_t    SoundEnabled = 1;
int32_t    CarSoundEnabled = 1;
int32_t    CarDamageSoundEnabled = 1;
int32_t    RoadNoiseEnabled = 1;
float      WorldTimeElapsed;
TrackInfo *CurrentTrackInfo;

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

static Car       *cars[MAXCAR];
static Sound3d   *snds[MAXCAR];
static TrackInfo  track;
static float      catVolume;
static float      jbVolume = 1.0f;
static int        noRegion;

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

static uint32_t randF[64];
static int      nRandF, atRandF;

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

// A tyre's samples, by the script's names.
static const char *const pnames[] = {
    "tf", "bo", "mb", "ph", "lv", "rn", "dn", "rk", "dk", "sq", "ds", "bp",
    "bu", "bs",
};
static const char *const anames[] = { "tf", "bo", "rk", "dk" };

#define NNAMES(t) ((int)(sizeof(t) / sizeof((t)[0])))

static BSample *player_sample(PlayerTireSound *s, int i)
{
    BSample *t[] = {
        &s->Base.TireFlop, &s->Base.BottomOut, &s->MetalBump.TerrainSample,
        &s->PotHole.TerrainSample, &s->LeavesNoise, &s->RoadNoise,
        &s->DirtNoise, &s->RoadSkid, &s->DirtSkid, &s->Squall,
        &s->DirtSquall, &s->BurnOutPeel, &s->Busted, &s->BustedScrape,
    };

    return t[i];
}

static BSample *ai_sample(OpponentTireSound *s, int i)
{
    BSample *t[] = {
        &s->Base.TireFlop, &s->Base.BottomOut, &s->RoadSkid, &s->DirtSkid,
    };

    return t[i];
}

static const char *name(const void *p)
{
    static char buf[8][48];
    static int k;
    char *b = buf[k++ & 7];
    int i, j;

    if (p == NULL)
        return "0";
    if (p == &PlayerTireSoundOneShotTimeDelay)
        return "delay";
    for (i = 0; i < nallocs; i++) {
        const char *t = allocs[i].tag;

        if (p == allocs[i].p) {
            sprintf(b, "m%d", i);
            return b;
        }
        if (!strcmp(t, "PlayerTireSound")) {
            for (j = 0; j < NNAMES(pnames); j++) {
                if (p == player_sample(allocs[i].p, j)) {
                    sprintf(b, "m%d.%s", i, pnames[j]);
                    return b;
                }
            }
        }
        if (!strcmp(t, "kAITireSound")) {
            for (j = 0; j < NNAMES(anames); j++) {
                if (p == ai_sample(allocs[i].p, j)) {
                    sprintf(b, "m%d.%s", i, anames[j]);
                    return b;
                }
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

// Kept, as retail's is: UpdateTireImpact reads it back.
void bsample_set_category(BSample *s, uint32_t category)
{
    printf("  bcat %s %u\n", name(s), category);
    s->category = category;
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
    if (noRegion)
        return NULL;
    for (i = 0; i < nregions; i++)
        if (!strcmp(regions[i].nm, nm))
            return (BRegion *)(void *)&regions[i].r;
    strcpy(regions[nregions].nm, nm);
    return (BRegion *)(void *)&regions[nregions++].r;
}

float bsound_get_category_volume(const BSound *s, uint32_t category)
{
    printf("  catvol %u -> %08x\n", category, bits(catVolume));
    check_bsound(s, "catvol");
    return catVolume;
}

void bsound_flush(BSound *s, int32_t wait)
{
    printf("  flush %d\n", wait);
    check_bsound(s, "flush");
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

// Retail's is static and takes only the category.
float jb_saved_volume(const JBSound *s, uint32_t cat)
{
    (void)s;
    printf("  jbvol %u -> %08x\n", cat, bits(jbVolume));
    return jbVolume;
}

// ------------------------------------------------------------ the heap

static const char *alloc_ok(const char *tag, int size)
{
    int want = -1;

    if (!strcmp(tag, "PlayerTireSound"))
        want = (int)sizeof(PlayerTireSound);
    else if (!strcmp(tag, "kAITireSound"))
        want = (int)sizeof(OpponentTireSound);
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

// ------------------------------------------------------------ the dumps

typedef struct Field {
    const char *nm;
    size_t      off;
    char        t;
} Field;

#define PF(n, f, t) { n, offsetof(PlayerTireSound, f), t }
#define AF(n, f, t) { n, offsetof(OpponentTireSound, f), t }

// 'p' is a pointer, printed by name.
static const Field pfields[] = {
    PF("act", Base.Sound.Activated, 'i'),
    PF("dop", Base.Sound.DopplerIsActive, 'i'),
    PF("svol", Base.Sound.Volume, 'f'),
    PF("spitch", Base.Sound.Pitch, 'f'),
    PF("saz", Base.Sound.Azimuth, 'H'),
    PF("ft", Base.FrontTireTouching, 'H'),
    PF("rt", Base.RearTireTouching, 'H'),
    PF("bocat", Base.BottomOut.category, 'i'),
    PF("car", pCar, 'p'),
    PF("lrp", LockedRearPitch, 'f'),
    PF("csp", CurrSquallPitch, 'f'),
    PF("csv", CurrSquallVolume, 'f'),
    PF("mode", Mode, 'i'),
    PF("side", Side, 'i'),
    PF("rns", RoadNoiseScale, 'f'),
    PF("pts", PlayThumperSounds, 'i'),
    PF("utt", UpdateThumperTime, 'f'),
    PF("prev", PrevShouldMakeRoadNoise, 'i'),
    PF("mbf", MetalBump.bFoundSample, 'i'),
    PF("mbon", MetalBump.bOnTerrainType, 'i'),
    PF("mbd", MetalBump.pTimeDelay, 'p'),
    PF("mbside", MetalBump.Side, 'i'),
    PF("phf", PotHole.bFoundSample, 'i'),
    PF("phon", PotHole.bOnTerrainType, 'i'),
    PF("phd", PotHole.pTimeDelay, 'p'),
    PF("phside", PotHole.Side, 'i'),
    PF("fls", FoundLeavesSample, 'i'),
};

static const Field afields[] = {
    AF("act", Base.Sound.Activated, 'i'),
    AF("dop", Base.Sound.DopplerIsActive, 'i'),
    AF("svol", Base.Sound.Volume, 'f'),
    AF("spitch", Base.Sound.Pitch, 'f'),
    AF("saz", Base.Sound.Azimuth, 'H'),
    AF("ft", Base.FrontTireTouching, 'H'),
    AF("rt", Base.RearTireTouching, 'H'),
    AF("bocat", Base.BottomOut.category, 'i'),
    AF("car", pCar, 'p'),
    AF("prev", PrevSkid, 'p'),
    AF("csv", CurrSkidVolume, 'f'),
    AF("tsv", TargetSkidVolume, 'f'),
};

#define NFIELDS(t) ((int)(sizeof(t) / sizeof((t)[0])))

static void print_field(const void *base, const Field *f)
{
    const char *p = (const char *)base + f->off;

    switch (f->t) {
    case 'i': printf(" %s=%d", f->nm, *(const int32_t *)p); break;
    case 'H': printf(" %s=%d", f->nm, *(const uint16_t *)p); break;
    case 'f': printf(" %s=%08x", f->nm, bits(*(const float *)p)); break;
    case 'p': printf(" %s=%s", f->nm, name(*(void *const *)p)); break;
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
        case 'H': *(uint16_t *)p = (uint16_t)x; break;
        case 'f': *(float *)p = unbits((uint32_t)strtoul(v, NULL, 16));
            break;
        case 'p': printf("  pointer field %s\n", nm); break;
        }
        return;
    }
    printf("  no field %s\n", nm);
}

static void dump_player(int k)
{
    PlayerTireSound *s = (PlayerTireSound *)snds[k];
    int i;

    printf("  pd %s vt=%08x", name(s), s->Base.Sound._vtable);
    for (i = 0; i < NFIELDS(pfields); i++)
        print_field(s, &pfields[i]);
    printf(" delay=%08x\n", bits(PlayerTireSoundOneShotTimeDelay));
}

static void dump_ai(int k)
{
    OpponentTireSound *s = (OpponentTireSound *)snds[k];
    int i;

    printf("  ad %s vt=%08x", name(s), s->Base.Sound._vtable);
    for (i = 0; i < NFIELDS(afields); i++)
        print_field(s, &afields[i]);
    printf("\n");
}

static const struct {
    VtFn fn;
    const char *nm;
} fnames[] = {
    { (VtFn)basetiresound_destroy, "base-dtor" },
    { (VtFn)sound3d_activate, "activate" },
    { (VtFn)basetiresound_mute, "base-mute" },
    { (VtFn)sound3d_update_cam_relative_dist_and_velocity, "camrel" },
    { (VtFn)basetiresound_trigger_tire_blow_out, "base-tbo" },
    { (VtFn)basetiresound_scale_road_noise, "base-srn" },
    { (VtFn)playertiresound_destroy, "player-dtor" },
    { (VtFn)playertiresound_update, "player-update" },
    { (VtFn)playertiresound_mute, "player-mute" },
    { (VtFn)playertiresound_deactivate_sound, "player-deact" },
    { (VtFn)playertiresound_activate_sound, "player-act" },
    { (VtFn)playertiresound_trigger_tire_blow_out, "player-tbo" },
    { (VtFn)playertiresound_scale_road_noise, "player-srn" },
    { (VtFn)opponenttiresound_destroy, "ai-dtor" },
    { (VtFn)opponenttiresound_update, "ai-update" },
    { (VtFn)opponenttiresound_mute, "ai-mute" },
    { (VtFn)opponenttiresound_deactivate_sound, "ai-deact" },
    { (VtFn)opponenttiresound_activate_sound, "ai-act" },
};

static void dump_tables(void)
{
    static const struct {
        const char *label;
        uint32_t vt;
    } t[] = {
        { "base", BASETIRESOUND_VTABLE },
        { "player", PLAYERTIRESOUND_VTABLE },
        { "ai", OPPONENTTIRESOUND_VTABLE },
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
            const char *nm = e[k].fn == NULL ? "pure" : "?";

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
typedef void (*VtScaleFn)(void *self, float f);

static PlayerTireSound *pts(int k)
{
    return (PlayerTireSound *)snds[k];
}

static OpponentTireSound *ots(int k)
{
    return (OpponentTireSound *)snds[k];
}

static TerrainOneShot *one_shot(int k, const char *w)
{
    return !strcmp(w, "mb") ? &pts(k)->MetalBump : &pts(k)->PotHole;
}

// A tyre's sample by name: the player's or, with `ai`, the AI's.
static BSample *sample_ref(int k, const char *w)
{
    int j;

    for (j = 0; j < NNAMES(anames); j++)
        if (!strcmp(w + 1, anames[j]) && w[0] == 'a')
            return ai_sample(ots(k), j);
    for (j = 0; j < NNAMES(pnames); j++)
        if (!strcmp(w, pnames[j]))
            return player_sample(pts(k), j);
    printf("  no sample %s\n", w);
    return &srcs[0].s;
}

static void new_car(int k)
{
    Car *c = cars[k] = pattern(sizeof(Car));
    int i;

    c->State.Position.x = c->State.Position.y = 0.0f;
    c->State.Position.z = c->State.Position.pad = 0.0f;
    c->State.Velocity.z = 0.0f;
    c->State.AngularVelocity.x = c->State.AngularVelocity.y = 0.0f;
    for (i = 0; i < 4; i++) {
        c->State.WheelTouchingGround[i] = 1;
        c->State.WheelTerrain[i] = (TerrainType)0;
        c->State.CrossedWheelTerrain[i] = (TerrainType)0;
        c->State.WheelSlip[i].x = c->State.WheelSlip[i].y = 0.0f;
        c->State.WheelAngularVelocity[i] = 0.0f;
        c->State.WheelTractionUsage[i] = 0.0f;
    }
    c->State.VelocityMagnitude = 0.0f;
    c->State.Throttle = 0.0f;
    c->NumBlownTires = 0;
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
    } else if (!strcmp(o, "cdse")) {
        CarDamageSoundEnabled = I(1);
    } else if (!strcmp(o, "rne")) {
        RoadNoiseEnabled = I(1);
    } else if (!strcmp(o, "wte")) {
        WorldTimeElapsed = FB(1);
    } else if (!strcmp(o, "delay")) {
        PlayerTireSoundOneShotTimeDelay = FB(1);
    } else if (!strcmp(o, "thoff")) {
        ThumperAzimuthOffset = (uint16_t)I(1);
    } else if (!strcmp(o, "catvol")) {
        catVolume = FB(1);
    } else if (!strcmp(o, "jbvol")) {
        jbVolume = FB(1);
    } else if (!strcmp(o, "rf")) {
        randF[nRandF++] = (uint32_t)strtoul(f[1], NULL, 16);
    } else if (!strcmp(o, "missing")) {
        strcpy(missing[nmissing++], f[1]);
    } else if (!strcmp(o, "nosrc")) {
        strcpy(nosrc[nnosrc++], f[1]);
    } else if (!strcmp(o, "unsrc")) {
        nnosrc = 0;
        nmissing = 0;
    } else if (!strcmp(o, "noregion")) {
        noRegion = I(1);
    } else if (!strcmp(o, "track")) {
        strcpy(track.SoundRegion, f[1]);
    } else if (!strcmp(o, "car")) {
        new_car(I(1));
    } else if (!strcmp(o, "wheel")) {
        Car *c = cars[I(1)];
        int i = I(2);

        c->State.WheelTouchingGround[i] = (int8_t)I(3);
        c->State.WheelTerrain[i] = (TerrainType)I(4);
        c->State.CrossedWheelTerrain[i] = (TerrainType)I(5);
        c->State.WheelSlip[i].x = FB(6);
        c->State.WheelSlip[i].y = FB(7);
        c->State.WheelAngularVelocity[i] = FB(8);
        c->State.WheelTractionUsage[i] = FB(9);
    } else if (!strcmp(o, "cv")) {
        Car *c = cars[I(1)];

        c->State.Velocity.z = FB(2);
        c->State.AngularVelocity.x = FB(3);
        c->State.AngularVelocity.y = FB(4);
        c->State.VelocityMagnitude = FB(5);
        c->State.Throttle = FB(6);
    } else if (!strcmp(o, "blown")) {
        cars[I(1)]->NumBlownTires = (uint8_t)I(2);
    } else if (!strcmp(o, "mk")) {
        k = I(1);
        if (!strcmp(f[2], "player"))
            snds[k] = tiresound_create_player(cars[k], I(3));
        else
            snds[k] = tiresound_create_ai(cars[k]);
        printf("  -> %s\n", name(snds[k]));
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
        case 64:
            ((VtVoidFn)e->fn)(self);
            break;
        case 56:
            ((VtCamRelativeFn)e->fn)(self, &cars[I(3)]->State.Position);
            break;
        case 72:
            ((VtScaleFn)e->fn)(self, FB(3));
            break;
        }
    } else if (!strcmp(o, "tbo")) {
        tiresound_trigger_blow_out(snds[I(1)]);
    } else if (!strcmp(o, "srn")) {
        tiresound_scale_road_noise(snds[I(1)], FB(2));
    } else if (!strcmp(o, "impact")) {
        basetiresound_update_tire_impact((BaseTireSound *)snds[I(1)],
                                         cars[I(2)], I(3));
    } else if (!strcmp(o, "tos")) {
        terrainoneshot_update(one_shot(I(1), f[2]), cars[I(1)], I(3), FB(4),
                              (uint16_t)I(5), FB(6));
    } else if (!strcmp(o, "tosmute")) {
        terrainoneshot_mute(one_shot(I(1), f[2]), I(3));
    } else if (!strcmp(o, "tosinit")) {
        terrainoneshot_init(one_shot(I(1), f[2]),
                            strcmp(f[3], "0") ? src(f[3], 1) : NULL,
                            I(5) ? &PlayerTireSoundOneShotTimeDelay : NULL,
                            I(4));
    } else if (!strcmp(o, "setpitch")) {
        playertiresound_set_sample_pitch(pts(I(1)), sample_ref(I(1), f[2]),
                                         FB(3));
    } else if (!strcmp(o, "squallvp") || !strcmp(o, "skidvp")) {
        float v = FB(2), p = FB(3);

        if (o[1] == 'q')
            playertiresound_calc_tire_squall_volume_and_pitch(pts(I(1)), &v,
                                                              &p);
        else
            playertiresound_calc_tire_skid_volume_and_pitch(pts(I(1)), &v,
                                                            &p);
        printf("  = %08x %08x\n", bits(v), bits(p));
    } else if (!strcmp(o, "nvol")) {
        printf("  = %08x\n",
               bits(playertiresound_calc_tire_noise_volume(pts(I(1)))));
    } else if (!strcmp(o, "npitch")) {
        printf("  = %08x\n",
               bits(playertiresound_calc_tire_noise_pitch(pts(I(1)))));
    } else if (!strcmp(o, "svol")) {
        printf("  = %08x\n",
               bits(playertiresound_calc_tire_squall_volume(pts(I(1)))));
    } else if (!strcmp(o, "spitch")) {
        printf("  = %08x\n",
               bits(playertiresound_calc_tire_squall_pitch(pts(I(1)))));
    } else if (!strcmp(o, "usq")) {
        playertiresound_update_squall(pts(I(1)), I(2), FB(3), (uint16_t)I(4),
                                      FB(5));
    } else if (!strcmp(o, "leaves")) {
        playertiresound_update_leaves(pts(I(1)), FB(2), (uint16_t)I(3),
                                      FB(4));
    } else if (!strcmp(o, "rtt")) {
        playertiresound_reset_thumper_time(pts(I(1)));
    } else if (!strcmp(o, "thump")) {
        playertiresound_update_thumper_tires(pts(I(1)));
    } else if (!strcmp(o, "skids")) {
        opponenttiresound_update_skids(ots(I(1)), FB(2), (uint16_t)I(3),
                                       FB(4));
    } else if (!strcmp(o, "bplaying")) {
        set_playing(sample_ref(I(1), f[2]), I(3));
    } else if (!strcmp(o, "bcv")) {
        sample_ref(I(1), f[2])->currentVolume = FB(3);
    } else if (!strcmp(o, "pset")) {
        set_field(snds[I(1)], pfields, NFIELDS(pfields), f[2], f[3]);
    } else if (!strcmp(o, "aset")) {
        set_field(snds[I(1)], afields, NFIELDS(afields), f[2], f[3]);
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

    if (argc < 2) {
        fprintf(stderr, "usage: tiresound_test script.txt\n");
        return 2;
    }
    fh = fopen(argv[1], "r");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
    memset(&track, 0, sizeof(track));
    strcpy(track.SoundRegion, "T0");
    CurrentTrackInfo = &track;

    tiresound_install_vtables();
    vt_install(SOUND3D_VTABLE, NULL, 0);

    while (fgets(line, sizeof(line), fh)) {
        char *f[32];
        int nf = 0;
        char *p;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0] || line[0] == '#')
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
