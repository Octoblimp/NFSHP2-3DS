// Harness for tools/soundscape_check.py: runs the checker's script on
// soundscape.c and choppersound.c and prints what the model prints for the
// retail image. bSample, bsample_new and bsample_delete, bSound's region
// and the region's samples, the three effect seams, the sound's randoms
// and in-game samples, get_active_cameras, topology_get_elevation,
// ScaleRoadNoise, Sound3d's constructor, Update and destructor, and bMalloc
// are logging fakes, the same fakes the checker gives retail's code. See
// the checker's docstring.
//
//     soundscape_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bsound.h"
#include "camera.h"
#include "car.h"
#include "carinit.h"
#include "carsound.h"
#include "chopper.h"
#include "choppersound.h"
#include "player.h"
#include "race.h"
#include "realtime.h"
#include "sound.h"
#include "sound3d.h"
#include "soundscape.h"
#include "topology.h"
#include "track.h"
#include "vtable.h"

int32_t          SoundEnabled = 1;
float            WorldTimeElapsed;
TrackInfo       *CurrentTrackInfo;
RaceParameters   TheRaceParameters;
struct Player   *PlayerPlayersByIndex[2];
RaceCoordinator *pRaceCoordinator;

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

#define MAXSLOT  64
#define MAXNAMED 128
#define MAXQ     512
#define MAXCHUNK 64
#define MAXHELI  4
#define MAXHS    8

static int          fakebsound, fakedriver, fakepool, fakerc;
static SoundModule  fakemod;
static TrackInfo    track;
static Camera       cams[3];
static Camera      *acams[2];
static Car         *cars[2];
static struct Player players[2];
static int          bcss[2];

static BSample *slots[MAXSLOT];
static int      nslots;

// The regions, their samples and the in-game samples, one a name; the
// script's names get none.
static struct {
    char nm[32];
    int  r;
} regions[MAXNAMED];
static int nregions;
static struct {
    char    nm[32];
    BSample s;
} rsamples[MAXNAMED], srcs[MAXNAMED];
static int  nrsamples, nsrcs;
static char noreg[8][32], nosmp[8][32], nosrc[8][32];
static int  nnoreg, nnosmp, nnosrc;

static uint32_t randF[MAXQ], elevQ[MAXQ];
static int32_t  randI[MAXQ];
static int      nRandF, atRandF, nRandI, atRandI, nElev, atElev;
static struct {
    uint32_t vol, pitch;
    int      az;
} s3dQ[MAXQ];
static int nS3d, atS3d;

static uint8_t *chunks[MAXCHUNK];
static size_t   chunkLen[MAXCHUNK];

static struct Chopper *helis[MAXHELI];
static int             nhelis;
static ChopperSound   *hss[MAXHS];
static int             nhss;

static const BSample *playing[MAXSLOT * 4];
static int            nplaying;
static struct {
    const BSample *s;
    uint32_t       v;
} vols[MAXSLOT];
static int nvols;

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
    if (on)
        playing[nplaying++] = s;
}

static uint32_t get_vol(const BSample *s)
{
    int i;

    for (i = 0; i < nvols; i++)
        if (vols[i].s == s)
            return vols[i].v;
    return 0x3f800000u;
}

static void set_vol(const BSample *s, uint32_t v)
{
    int i;

    for (i = 0; i < nvols; i++) {
        if (vols[i].s == s) {
            vols[i].v = v;
            return;
        }
    }
    vols[nvols].s = s;
    vols[nvols++].v = v;
}

static int listed(char (*list)[32], int n, const char *nm)
{
    int i;

    for (i = 0; i < n; i++)
        if (!strcmp(list[i], nm))
            return 1;
    return 0;
}

static const char *name(const void *p)
{
    static char buf[8][64];
    static int k;
    char *b = buf[k++ & 7];
    const uint8_t *q = p;
    int i;

    if (p == NULL)
        return "0";
    if (p == (const void *)&fakebsound)
        return "bsound";
    if (p == (const void *)&fakedriver)
        return "drv";
    if (p == (const void *)&fakepool)
        return "pool";
    for (i = 0; i < nslots; i++) {
        if (p == slots[i]) {
            sprintf(b, "s%d", i);
            return b;
        }
    }
    for (i = 0; i < nregions; i++) {
        if (p == &regions[i].r) {
            sprintf(b, "reg:%s", regions[i].nm);
            return b;
        }
    }
    for (i = 0; i < nrsamples; i++) {
        if (p == &rsamples[i].s) {
            sprintf(b, "r:%s", rsamples[i].nm);
            return b;
        }
    }
    for (i = 0; i < nsrcs; i++) {
        if (p == &srcs[i].s) {
            sprintf(b, "src:%s", srcs[i].nm);
            return b;
        }
    }
    for (i = 0; i < SOUNDSCAPE_ONESHOT_AMBIENT; i++) {
        if (p == &SoundScapeOneShotAmbientArray[i].Sample360Azimuth) {
            sprintf(b, "x%d.360", i);
            return b;
        }
    }
    for (i = 0; i < 3; i++) {
        if (p == &cams[i]) {
            sprintf(b, "cam%d", i);
            return b;
        }
    }
    for (i = 0; i < 2; i++) {
        if (p == cars[i]) {
            sprintf(b, "car%d", i);
            return b;
        }
        if (p == &cars[i]->TheTopologyCoordinate) {
            sprintf(b, "car%d.tc", i);
            return b;
        }
        if (p == &bcss[i]) {
            sprintf(b, "bcs%d", i);
            return b;
        }
    }
    for (i = 0; i < nhelis; i++) {
        if (p == helis[i]) {
            sprintf(b, "h%d", i);
            return b;
        }
        if (p == &helis[i]->CurrentPos) {
            sprintf(b, "h%d.pos", i);
            return b;
        }
    }
    for (i = 0; i < nhss; i++) {
        if (p == hss[i]) {
            sprintf(b, "hs%d", i);
            return b;
        }
    }
    for (i = 0; i < MAXCHUNK; i++) {
        if (chunks[i] != NULL && q >= chunks[i]
            && q < chunks[i] + chunkLen[i]) {
            sprintf(b, "ch%d+%d", i, (int)(q - chunks[i]));
            return b;
        }
    }
    return "?";
}

// A sample by the script's name: a region's (r:Wind), an in-game sample
// (src:ChopperEngine), a pool slot (s3) or a one-shot's second (x1.360).
static BSample *sample_ref(const char *w)
{
    int i;

    if (!strcmp(w, "0"))
        return NULL;
    if (!strncmp(w, "r:", 2)) {
        for (i = 0; i < nrsamples; i++)
            if (!strcmp(rsamples[i].nm, w + 2))
                return &rsamples[i].s;
    } else if (!strncmp(w, "src:", 4)) {
        for (i = 0; i < nsrcs; i++)
            if (!strcmp(srcs[i].nm, w + 4))
                return &srcs[i].s;
    } else if (w[0] == 's' && w[1] >= '0' && w[1] <= '9') {
        i = atoi(w + 1);
        if (i < nslots)
            return slots[i];
    } else if (w[0] == 'x' && strstr(w, ".360") != NULL) {
        return &SoundScapeOneShotAmbientArray[atoi(w + 1)].Sample360Azimuth;
    }
    printf("  no sample %s\n", w);
    return NULL;
}

// --------------------------------------------------------------- bSample

// Retail's bSample() takes no type; the port's 0 is not printed.
void bsample_construct(BSample *s, int8_t type)
{
    (void)type;
    printf("  bctor %s\n", name(s));
}

void bsample_initialize_copy(BSample *s, const BSample *other)
{
    printf("  binit %s from %s\n", name(s), name(other));
}

void bsample_set_category(BSample *s, uint32_t category)
{
    printf("  bcat %s %u\n", name(s), category);
    if (s != NULL)
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

void bsample_mute(BSample *s, bool mute)
{
    printf("  bmute %s %d\n", name(s), mute ? 1 : 0);
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

// Asked of no sample, silent and no: the port asks it of none.
bool bsample_is_playing(const BSample *s)
{
    int v;

    if (s == NULL)
        return false;
    v = is_playing(s);
    printf("  bisplaying %s %d\n", name(s), v);
    return v != 0;
}

float bsample_get_volume(const BSample *s)
{
    uint32_t v = get_vol(s);

    printf("  bgetvol %s -> %08x\n", name(s), v);
    return unbits(v);
}

void bsample_fade(BSample *s, float volume, uint32_t ms)
{
    printf("  bfade %s %08x %u\n", name(s), bits(volume), ms);
}

// bOMalloc on the slot pool and the constructor, as retail's are.
BSample *bsample_new(int8_t type)
{
    BSample *s = pattern(sizeof(BSample));

    slots[nslots++] = s;
    printf("  omalloc %s -> %s\n", name(&fakepool), name(s));
    bsample_construct(s, type);
    return s;
}

void bsample_delete(BSample *s)
{
    printf("  bdelete %s\n", name(s));
}

// ---------------------------------------------------------------- bSound

BSound *bsound_get(void)
{
    return (BSound *)(void *)&fakebsound;
}

BRegion *bsound_region(const BSound *s, const char *nm)
{
    int i;

    printf("  region %s %s\n", name(s), nm);
    if (listed(noreg, nnoreg, nm))
        return NULL;
    for (i = 0; i < nregions; i++)
        if (!strcmp(regions[i].nm, nm))
            return (BRegion *)(void *)&regions[i].r;
    strcpy(regions[nregions].nm, nm);
    return (BRegion *)(void *)&regions[nregions++].r;
}

BSample *bregion_sample(const BRegion *r, const char *nm)
{
    int i;

    printf("  rsample %s %s\n", name(r), nm);
    if (listed(nosmp, nnosmp, nm))
        return NULL;
    for (i = 0; i < nrsamples; i++)
        if (!strcmp(rsamples[i].nm, nm))
            return &rsamples[i].s;
    strcpy(rsamples[nrsamples].nm, nm);
    return &rsamples[nrsamples++].s;
}

static void effect_volume(uint32_t voices, uint32_t on, float volume,
                          float pan)
{
    printf("  effvol %08x %u %08x %08x\n", voices, on, bits(volume),
           bits(pan));
}

static void effect_mode(uint32_t mode)
{
    printf("  effmode %u\n", mode);
}

static void effect_parameter(uint32_t which, uint32_t core, float value)
{
    printf("  effparam %u %u %08x\n", which, core, bits(value));
}

// ---------------------------------------------------------------- sound

SoundModule *sound_get(void)
{
    return &fakemod;
}

float sound_random_float(SoundModule *m, float range)
{
    uint32_t v = atRandF < nRandF ? randF[atRandF++] : 0;

    if (m != &fakemod)
        printf("  randf: not the module\n");
    printf("  randf %08x -> %08x\n", bits(range), v);
    return unbits(v);
}

int32_t sound_random_int(SoundModule *m, int32_t range)
{
    int32_t v = atRandI < nRandI ? randI[atRandI++] : 0;

    if (m != &fakemod)
        printf("  randi: not the module\n");
    printf("  randi %d -> %d\n", range, v);
    return v;
}

BSample *sound_get_in_game_sample(SoundModule *m, const char *nm)
{
    int i;

    printf("  ingame %s\n", nm);
    if (m != &fakemod)
        printf("  ingame: not the module\n");
    if (listed(nosrc, nnosrc, nm))
        return NULL;
    for (i = 0; i < nsrcs; i++)
        if (!strcmp(srcs[i].nm, nm))
            return &srcs[i].s;
    strcpy(srcs[nsrcs].nm, nm);
    return &srcs[nsrcs++].s;
}

// ------------------------------------------------------- the rest it calls

struct Camera **get_active_cameras(void)
{
    printf("  gac\n");
    return acams;
}

float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    uint32_t v = atElev < nElev ? elevQ[atElev++] : 0;

    printf("  elev %s %08x %08x %08x %s%s%s -> %08x\n", name(tc),
           bits(pt->x), bits(pt->y), bits(pt->z), terrain ? "t" : "-",
           normal ? "n" : "-", found ? "f" : "-", v);
    return unbits(v);
}

void basecarsound_scale_road_noise(BaseCarSound *s, float f)
{
    printf("  roadnoise %s %08x\n", name(s), bits(f));
}

void sound3d_construct(Sound3d *s)
{
    printf("  s3dctor %s\n", name(s));
    s->Activated = 0;
    s->DopplerIsActive = 1;
    s->Volume = 1.0f;
    s->Pitch = 1.0f;
    s->Azimuth = 0;
    s->SndToCameraVelocity = 0.0f;
    s->SndToCameraDistance = 0.0f;
    s->_vtable = SOUND3D_VTABLE;
}

void sound3d_update(Sound3d *s, const bVector3 *pos,
                    const Sound3dEnvelope *env)
{
    printf("  s3dupd %s %s %08x %08x %08x\n", name(s), name(pos),
           bits(env->MaxVolAtSource), bits(env->CutOffDistance),
           bits(env->Coeff));
    if (atS3d < nS3d) {
        s->Volume = unbits(s3dQ[atS3d].vol);
        s->Pitch = unbits(s3dQ[atS3d].pitch);
        s->Azimuth = (uint16_t)s3dQ[atS3d].az;
        atS3d++;
    }
}

void sound3d_destroy(Sound3d *s, int32_t flags)
{
    printf("  s3ddtor %s %d\n", name(s), flags);
}

void sound3d_activate(Sound3d *s, int32_t on)
{
    printf("  s3dactivate? %s %d\n", name(s), on);
}

void sound3d_update_cam_relative_dist_and_velocity(Sound3d *s,
                                                   const bVector3 *pos)
{
    printf("  camrel? %s %s\n", name(s), name(pos));
}

void *bMalloc(int size, const char *nm, int flags, int pool)
{
    ChopperSound *s = pattern(sizeof(ChopperSound));

    s->pChopperSample = NULL;
    hss[nhss++] = s;
    printf("  malloc size-%s %s %d %d -> %s\n",
           size == (int)sizeof(ChopperSound) ? "ok" : "BAD", nm, flags, pool,
           name(s));
    return s;
}

// ------------------------------------------------------------ the dumps

static void dump_globals(void)
{
    printf("  gd djl=%d nrev=%d cur=%d ron=%d rain=%s vol=%08x tgt=%08x"
           " pan=%08x nloop=%d nshot=%d\n",
           SoundScapeDataJustLoaded, SoundScapeNumReverbAreas,
           SoundScapeCurrentlyActiveReverbArea, SoundScapeReverbOn,
           name(SoundScapeRain), bits(SoundScapeReverbVolume),
           bits(SoundScapeTargetReverbVolume), bits(SoundScapeReverbPan),
           SoundScapeNumLoopingAmbient, SoundScapeNumOneShotAmbient);
    printf("  gd mode=%d/%d delay=%08x/%08x fb=%08x/%08x level=%08x/%08x"
           " depth=%08x/%08x\n",
           ReverbMode, DesiredReverbMode, bits(ReverbDelay),
           bits(DesiredReverbDelay), bits(ReverbFeedback),
           bits(DesiredReverbFeedback), bits(ReverbLevel),
           bits(DesiredReverbLevel), bits(ReverbDepth),
           bits(DesiredReverbDepth));
}

static const char *area_str(const SoundArea *a)
{
    static char buf[4][160];
    static int k;
    char *b = buf[k++ & 3];

    sprintf(b, "area %d %s %d %s", a->NumAreaVerts, name(a->AreaVerts),
            a->NumAreaFaces, name(a->AreaFaces));
    return b;
}

static void dump_reverb(int i)
{
    const ReverbArea *r = &SoundScapeReverbAreaArray[i];
    int k, n = r->NumSounds;

    printf("  rd %d %s reverb=%d %s sounds=%d", i, name(r->Name), r->Reverb,
           area_str(&r->Area), n);
    for (k = 0; k < n && k < 8; k++)
        printf(" (%s %08x %08x)", name(r->Sounds[k].SampleName),
               bits(r->Sounds[k].Period), bits(r->Sounds[k].PeriodError));
    printf("\n");
}

static void dump_looping(int i)
{
    const LoopingAmbient *l = &SoundScapeLoopingAmbientArray[i];

    printf("  ld %d %s %s fade=%d/%d active=%d src=%d sphere=%d sample=%s"
           " %s at=%08x,%08x coeff=%08x radius=%08x\n",
           i, name(l->Name), name(l->SampleName), l->FadeInDuration,
           l->FadeOutDuration, l->IsActive, l->HasSoundSource,
           l->UseSoundSphere, name(l->Sample), area_str(&l->Area),
           bits(l->SoundSource.x), bits(l->SoundSource.y),
           bits(l->SoundSourceDistanceCoeff), bits(l->SoundSphereRadius));
}

static void dump_oneshot(int i)
{
    const OneShotAmbient *o = &SoundScapeOneShotAmbientArray[i];

    printf("  od %d %s %s repeat=%08x/%08x pitch=%08x/%08x az=%08x"
           " active=%d time=%08x sample=%s %s cat360=%d\n",
           i, name(o->Name), name(o->SampleName), bits(o->Repeat),
           bits(o->RepeatDeviation), bits(o->Pitch),
           bits(o->PitchDeviation), bits(o->AzimuthDeviation), o->IsActive,
           bits(o->UpdateOneShotTime), name(o->Sample), area_str(&o->Area),
           (int32_t)o->Sample360Azimuth.category);
}

static void dump_modes(void)
{
    int k;

    printf("  mt");
    for (k = 0; k < 13; k++)
        printf(" %u", ReverbModeTable[k]);
    printf("\n");
}

static const char *fn_name(VtFn fn)
{
    if (fn == (VtFn)choppersound_destroy)
        return "dtor";
    if (fn == (VtFn)sound3d_activate)
        return "s3dactivate";
    if (fn == (VtFn)choppersound_update)
        return "update";
    if (fn == (VtFn)choppersound_mute)
        return "mute";
    if (fn == (VtFn)choppersound_deactivate_sound)
        return "deact";
    if (fn == (VtFn)choppersound_activate_sound)
        return "act";
    if (fn == (VtFn)sound3d_update_cam_relative_dist_and_velocity)
        return "camrel";
    return "?";
}

static void dump_tables(void)
{
    int n, k;
    const VtEntry *e = vt_table(CHOPPERSOUND_VTABLE, &n);

    if (e == NULL) {
        printf("  vt missing\n");
        return;
    }
    printf("  vt %d entries\n", n);
    for (k = 1; k < n; k++)
        printf("  vt %d %d %s\n", 8 * k, e[k].delta, fn_name(e[k].fn));
}

static void dump_hs(int i)
{
    const ChopperSound *s = hss[i];

    printf("  hd %s act=%d dop=%d vol=%08x pitch=%08x az=%d vel=%08x"
           " dist=%08x vt=%08x heli=%s sample=%s in=%d counter=%08x\n",
           name(s), s->Sound.Activated, s->Sound.DopplerIsActive,
           bits(s->Sound.Volume), bits(s->Sound.Pitch), s->Sound.Azimuth,
           bits(s->Sound.SndToCameraVelocity),
           bits(s->Sound.SndToCameraDistance), s->Sound._vtable,
           name(s->pChopper), name(s->pChopperSample), s->InSideTunnel,
           bits(s->TunnelFadeCounter));
}

// ------------------------------------------------------------- the ops

static const SoundArea *area_of(const char *kind, int i)
{
    if (kind[0] == 'r')
        return &SoundScapeReverbAreaArray[i].Area;
    if (kind[0] == 'l')
        return &SoundScapeLoopingAmbientArray[i].Area;
    return &SoundScapeOneShotAmbientArray[i].Area;
}

static Car *car_ref(int k)
{
    return k < 0 ? NULL : cars[k];
}

static void chunk_append(int k, const char *hex)
{
    size_t n = strlen(hex) / 2, i;

    chunks[k] = realloc(chunks[k], chunkLen[k] + n + 16);
    for (i = 0; i < n; i++) {
        unsigned v;

        sscanf(hex + 2 * i, "%2x", &v);
        chunks[k][chunkLen[k] + i] = (uint8_t)v;
    }
    chunkLen[k] += n;
}

static void op(char **f, int nf)
{
#define I(k) ((k) < nf ? (int)strtol(f[k], NULL, 0) : 0)
#define U(k) ((k) < nf ? (uint32_t)strtoul(f[k], NULL, 16) : 0u)
#define FB(k) unbits(U(k))
    const char *o = f[0];

    if (!strcmp(o, "tables")) {
        dump_tables();
    } else if (!strcmp(o, "mt")) {
        dump_modes();
    } else if (!strcmp(o, "se")) {
        SoundEnabled = I(1);
    } else if (!strcmp(o, "wte")) {
        WorldTimeElapsed = FB(1);
    } else if (!strcmp(o, "rc")) {
        pRaceCoordinator = I(1) ? (RaceCoordinator *)(void *)&fakerc : NULL;
    } else if (!strcmp(o, "npc")) {
        TheRaceParameters.NumPlayerCars = I(1);
    } else if (!strcmp(o, "track")) {
        memset(track.SoundRegion, 0, sizeof(track.SoundRegion));
        strncpy(track.SoundRegion, f[1], 31);
    } else if (!strcmp(o, "cam")) {
        Camera *c = &cams[I(1)];

        c->CurrentKey.Position.x = FB(2);
        c->CurrentKey.Position.y = FB(3);
        c->CurrentKey.Position.z = FB(4);
        c->CurrentKey.Direction.x = FB(5);
        c->CurrentKey.Direction.y = FB(6);
    } else if (!strcmp(o, "cams")) {
        acams[0] = I(1) < 0 ? NULL : &cams[I(1)];
        acams[1] = I(2) < 0 ? NULL : &cams[I(2)];
    } else if (!strcmp(o, "player")) {
        PlayerPlayersByIndex[I(1)] = I(2) ? &players[I(1)] : NULL;
    } else if (!strcmp(o, "carpos")) {
        Car *c = cars[I(1)];

        c->State.Position.x = FB(2);
        c->State.Position.y = FB(3);
        c->State.Position.z = FB(4);
    } else if (!strcmp(o, "carsnd")) {
        cars[I(1)]->pBaseCarSound =
            I(2) ? (BaseCarSound *)(void *)&bcss[I(1)] : NULL;
    } else if (!strcmp(o, "elev")) {
        elevQ[nElev++] = U(1);
    } else if (!strcmp(o, "rf")) {
        randF[nRandF++] = U(1);
    } else if (!strcmp(o, "ri")) {
        randI[nRandI++] = I(1);
    } else if (!strcmp(o, "noreg")) {
        strcpy(noreg[nnoreg++], f[1]);
    } else if (!strcmp(o, "unreg")) {
        nnoreg = 0;
    } else if (!strcmp(o, "nosmp")) {
        strcpy(nosmp[nnosmp++], f[1]);
    } else if (!strcmp(o, "unsmp")) {
        nnosmp = 0;
    } else if (!strcmp(o, "nosrc")) {
        strcpy(nosrc[nnosrc++], f[1]);
    } else if (!strcmp(o, "unsrc")) {
        nnosrc = 0;
    } else if (!strcmp(o, "bplaying")) {
        set_playing(sample_ref(f[1]), I(2));
    } else if (!strcmp(o, "bgv")) {
        set_vol(sample_ref(f[1]), U(2));
    } else if (!strcmp(o, "cnew")) {
        free(chunks[I(1)]);
        chunks[I(1)] = NULL;
        chunkLen[I(1)] = 0;
    } else if (!strcmp(o, "cb")) {
        chunk_append(I(1), f[2]);
    } else if (!strcmp(o, "load")) {
        printf("  = %d\n", loader_sound_scape(chunks[I(1)]));
    } else if (!strcmp(o, "unload")) {
        printf("  = %d\n", unloader_sound_scape(chunks[I(1)]));
    } else if (!strcmp(o, "cur")) {
        SoundScapeCurrentlyActiveReverbArea = I(1);
    } else if (!strcmp(o, "djl")) {
        SoundScapeDataJustLoaded = I(1);
    } else if (!strcmp(o, "ron")) {
        SoundScapeReverbOn = I(1);
    } else if (!strcmp(o, "rv")) {
        SoundScapeReverbVolume = FB(1);
        SoundScapeTargetReverbVolume = FB(2);
        SoundScapeReverbPan = FB(3);
    } else if (!strcmp(o, "rain")) {
        SoundScapeRain = sample_ref(f[1]);
    } else if (!strcmp(o, "desired")) {
        DesiredReverbMode = I(1);
        DesiredReverbDelay = FB(2);
        DesiredReverbFeedback = FB(3);
        DesiredReverbLevel = FB(4);
        DesiredReverbDepth = FB(5);
    } else if (!strcmp(o, "pia")) {
        bVector2 p;

        p.x = FB(3);
        p.y = FB(4);
        printf("  = %d\n", soundarea_is_point_in_area(area_of(f[1], I(2)),
                                                       &p));
    } else if (!strcmp(o, "aca")) {
        int32_t count = 0x5a5a5a5a;
        struct Camera **r = soundarea_are_cameras_in_area(
            area_of(f[1], I(2)), acams, &count);

        printf("  = %d %s %s\n", count, name(r[0]), name(r[1]));
    } else if (!strcmp(o, "lcaz")) {
        printf("  = %d\n", loopingambient_compute_azimuth(
                   &SoundScapeLoopingAmbientArray[I(1)], &cams[I(2)]));
    } else if (!strcmp(o, "lua")) {
        loopingambient_update_using_area(
            &SoundScapeLoopingAmbientArray[I(1)], acams);
    } else if (!strcmp(o, "lus")) {
        loopingambient_update_using_sound_sphere(
            &SoundScapeLoopingAmbientArray[I(1)], acams);
    } else if (!strcmp(o, "lupd")) {
        loopingambient_update(&SoundScapeLoopingAmbientArray[I(1)], acams);
    } else if (!strcmp(o, "lmute")) {
        loopingambient_mute(&SoundScapeLoopingAmbientArray[I(1)], I(2));
    } else if (!strcmp(o, "oplay")) {
        oneshotambient_play(&SoundScapeOneShotAmbientArray[I(1)]);
    } else if (!strcmp(o, "oupd")) {
        oneshotambient_update(&SoundScapeOneShotAmbientArray[I(1)], acams);
    } else if (!strcmp(o, "omute")) {
        oneshotambient_mute(&SoundScapeOneShotAmbientArray[I(1)], I(2));
    } else if (!strcmp(o, "wsr")) {
        printf("  = %d\n", soundscape_will_sound_right(I(1), car_ref(I(2))));
    } else if (!strcmp(o, "fgra")) {
        printf("  = %d\n", soundscape_find_good_reverb_area(car_ref(I(1))));
    } else if (!strcmp(o, "srv")) {
        soundscape_set_reverb_volume(FB(1), car_ref(I(2)));
    } else if (!strcmp(o, "iira")) {
        struct Car *c[2];
        int32_t r;

        c[0] = car_ref(I(1));
        c[1] = car_ref(I(2));
        r = soundscape_is_inside_reverb_area(c);
        printf("  = %d cur=%d djl=%d\n", r,
               SoundScapeCurrentlyActiveReverbArea,
               SoundScapeDataJustLoaded);
    } else if (!strcmp(o, "ura")) {
        soundscape_update_reverb_areas();
    } else if (!strcmp(o, "ula")) {
        soundscape_update_looping_ambient();
    } else if (!strcmp(o, "uoa")) {
        soundscape_update_one_shot_ambient();
    } else if (!strcmp(o, "update")) {
        sound_scape_update();
    } else if (!strcmp(o, "ssupdate")) {
        soundscape_update();
    } else if (!strcmp(o, "mute")) {
        sound_scape_mute(I(1));
    } else if (!strcmp(o, "ssmute")) {
        soundscape_mute(I(1));
    } else if (!strcmp(o, "tunnel")) {
        printf("  = %d\n", soundscape_is_inside_tunnel());
    } else if (!strcmp(o, "gd")) {
        dump_globals();
    } else if (!strcmp(o, "rd")) {
        dump_reverb(I(1));
    } else if (!strcmp(o, "ld")) {
        dump_looping(I(1));
    } else if (!strcmp(o, "od")) {
        dump_oneshot(I(1));
    // ---- the chopper
    } else if (!strcmp(o, "heli")) {
        helis[nhelis++] = calloc(1, sizeof(struct Chopper));
    } else if (!strcmp(o, "hcreate")) {
        printf("  -> %s\n", name(choppersound_create(helis[I(1)])));
    } else if (!strcmp(o, "hctor")) {
        ChopperSound *s = pattern(sizeof(ChopperSound));

        s->pChopperSample = NULL;
        hss[nhss++] = s;
        choppersound_construct(s, helis[I(1)]);
    } else if (!strcmp(o, "hdtor")) {
        choppersound_destroy(hss[I(1)], I(2));
    } else if (!strcmp(o, "hset")) {
        ChopperSound *s = hss[I(1)];

        s->Sound.Activated = I(2);
        s->Sound.Volume = FB(3);
        s->Sound.Pitch = FB(4);
        s->Sound.Azimuth = (uint16_t)I(5);
    } else if (!strcmp(o, "hsamp")) {
        hss[I(1)]->pChopperSample = sample_ref(f[2]);
    } else if (!strcmp(o, "hvt")) {
        hss[I(1)]->Sound._vtable = U(2);
    } else if (!strcmp(o, "htun")) {
        hss[I(1)]->InSideTunnel = I(2);
        hss[I(1)]->TunnelFadeCounter = FB(3);
    } else if (!strcmp(o, "hadj")) {
        float v = FB(2);

        choppersound_adjust_for_tunnel_volume(hss[I(1)], &v);
        printf("  = %08x\n", bits(v));
    } else if (!strcmp(o, "s3d")) {
        s3dQ[nS3d].vol = U(1);
        s3dQ[nS3d].pitch = U(2);
        s3dQ[nS3d++].az = I(3);
    } else if (!strcmp(o, "hupd")) {
        choppersound_update(hss[I(1)], unbits(0x12345678u), 0x4321,
                            unbits(0x9abcdef0u));
    } else if (!strcmp(o, "hmute")) {
        choppersound_mute(hss[I(1)], I(2));
    } else if (!strcmp(o, "hdeact")) {
        choppersound_deactivate_sound(hss[I(1)]);
    } else if (!strcmp(o, "hact")) {
        choppersound_activate_sound(hss[I(1)]);
    } else if (!strcmp(o, "hd")) {
        dump_hs(I(1));
    } else {
        printf("  unknown op %s\n", o);
    }
#undef I
#undef U
#undef FB
}

int main(int argc, char **argv)
{
    static char line[2048];
    FILE *fh;
    int i;

    if (argc < 2) {
        fprintf(stderr, "usage: soundscape_test script.txt\n");
        return 2;
    }
    fh = fopen(argv[1], "r");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
    CurrentTrackInfo = &track;
    TheRaceParameters.NumPlayerCars = 1;
    for (i = 0; i < 2; i++) {
        cars[i] = calloc(1, sizeof(Car));
        players[i].MyCar = cars[i];
    }
    gSoundScapeEffectVolumeFn = effect_volume;
    gSoundScapeEffectModeFn = effect_mode;
    gSoundScapeEffectParameterFn = effect_parameter;

    choppersound_install_vtables();
    soundscape_init();

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
