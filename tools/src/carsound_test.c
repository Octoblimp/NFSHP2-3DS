// Harness for tools/carsound_check.py: runs the checker's script on
// carsound.c and prints what the model prints for the retail image. bSample,
// the regions, GetInGameSample, the random helpers, bMalloc, the
// TopologyCoordinate, the engine and tyre sounds, the collision bodies,
// WorldToCar and ClearZoneSound are logging fakes, the same fakes the
// checker gives retail's code; so are Sound3d's Update and
// UpdateCamRelativeDistAndVelocity. Sound3d's constructor, destructor and
// Activate are copies of sound3d.c's, which sound3d_check.py holds to the
// image, and Car::UpdateSound is car.c's. See the checker's docstring.
//
//     carsound_test script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bsound.h"
#include "bvector.h"
#include "car.h"
#include "carsound.h"
#include "cartypeinfo.h"
#include "collisionbody.h"
#include "player.h"
#include "playerzone.h"
#include "race.h"
#include "realtime.h"
#include "sound.h"
#include "sound3d.h"
#include "topology.h"
#include "vtable.h"
#include "world.h"

int32_t           SoundEnabled = 1;
RaceParameters    TheRaceParameters;
World            *pCurrentWorld;
float             WorldTimeElapsed;
uint16_t          CarSoundMultiPlayerAzimuth;
CollisionBodyNode CollisionBodyList;

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

#define MAXCAR   16
#define MAXALLOC 96
#define MAXPROBE 32
#define MAXBODY  12
#define NSRC     14
#define NREG     4

static const char *const srcNames[NSRC] = {
    "Splash1", "Splash2", "Splash3", "TirePop1", "Wind", "Reflection01",
    "Reflection02", "Horn01", "Horn02", "CopSiren01", "CopSiren02",
    "CopSiren03", "P0Horn", "Zone",
};
// The in-game region has all but the car's own horn and the zone's; the
// car regions only "P0Horn", in "Car0".
static const char *const regNames[NREG] = { "InGame", "Car0", "Car1", "Car2" };

static BSample      srcs[NSRC];
static int          regs[NREG];
static int          fakebsound;
static SoundModule  fakemod;

static Car         *cars[MAXCAR];
static BaseCarSound *snds[MAXCAR];
static CarTypeInfo  types[MAXCAR];
static DriverInfo   drivers[MAXCAR];
static struct Player players[MAXCAR];
static World        world;

static struct {
    void       *p;
    const char *tag;
} allocs[MAXALLOC];
static int nallocs;

static Sound3d *probes[MAXPROBE];
static int      probeKind[MAXPROBE];    // 0 engine, 1 tyre
static int      nprobes;

static CarCollisionBody bodies[MAXBODY];
static bVector3 bodyPos[MAXBODY], bodyVel[MAXBODY];
static int32_t  bodyTerrain[MAXBODY];

static int notires;

// What the fake Sound3d::Update and UpdateCamRelativeDistAndVelocity
// leave in the record.
static float    nuVol = 1.0f, nuPitch = 1.0f, nuDist;
static uint16_t nuAz;
// A car sound's own distance, over nuDist, from `nd`.
static float    ndDist[MAXCAR];
static int      ndSet[MAXCAR];

static float dist_for(const Sound3d *s)
{
    int k;

    for (k = 0; k < MAXCAR; k++)
        if (ndSet[k] && (const void *)snds[k] == (const void *)s)
            return ndDist[k];
    return nuDist;
}

static int32_t  randI[64];
static int      nRandI, atRandI;
static uint32_t randF[64];
static int      nRandF, atRandF;

static CollisionBody *locFirst, *locLast;

// bSample's playing flag, by sample.
static const BSample *playing[64];
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
    if (on && nplaying < 64)
        playing[nplaying++] = s;
}

static const char *name(const void *p)
{
    static char buf[8][32];
    static int k;
    char *b = buf[k++ & 7];
    int i, j;

    if (p == NULL)
        return "0";
    if (p == &CollisionBodyList)
        return "L";
    if (p == &BasePlayerCarSoundEnvelope)
        return "penv";
    if (p == &BaseAICarSoundEnvelope)
        return "aienv";
    for (i = 0; i < nallocs; i++) {
        const char *t = allocs[i].tag;

        if (p == allocs[i].p) {
            sprintf(b, "m%d", i);
            return b;
        }
        if (!strcmp(t, "PlayerCarSound")
            && p == &((BasePlayerCarSound *)allocs[i].p)->WindSample) {
            sprintf(b, "m%d.wind", i);
            return b;
        }
        if (!strcmp(t, "HornSound3d")
            && p == &((HornSound3d *)allocs[i].p)->HornSample) {
            sprintf(b, "m%d.b", i);
            return b;
        }
        if (!strcmp(t, "SirenSound")) {
            for (j = 0; j < 3; j++) {
                if (p == &((SirenSound3d *)allocs[i].p)->SirenSampleTable[j]) {
                    sprintf(b, "m%d.b%d", i, j);
                    return b;
                }
            }
        }
    }
    for (i = 0; i < nprobes; i++) {
        if (p == probes[i]) {
            sprintf(b, "%s%d", probeKind[i] ? "tire" : "eng", i);
            return b;
        }
    }
    for (i = 0; i < NSRC; i++) {
        if (p == &srcs[i]) {
            sprintf(b, "src:%s", srcNames[i]);
            return b;
        }
    }
    for (i = 0; i < NREG; i++) {
        if (p == &regs[i]) {
            sprintf(b, "reg:%s", regNames[i]);
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
        if (p == &players[i]) {
            sprintf(b, "p%d", i);
            return b;
        }
    }
    for (i = 0; i < MAXBODY; i++) {
        if (p == &bodies[i]) {
            sprintf(b, "b%d", i);
            return b;
        }
    }
    return "?";
}

#define PROBE_VT 0x00500000u
#define BODY_VT  0x00500100u

static const char *vtname(uint32_t v)
{
    switch (v) {
    case BASECARSOUND_VTABLE:       return "base";
    case BASEPLAYERCARSOUND_VTABLE: return "player";
    case BASEAICARSOUND_VTABLE:     return "ai";
    case HORNSOUND3D_VTABLE:        return "horn";
    case SIRENSOUND3D_VTABLE:       return "siren";
    case SOUND3D_VTABLE:            return "s3d";
    case PROBE_VT:                  return "probe";
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

void sound3d_update(Sound3d *s, const bVector3 *pos,
                    const Sound3dEnvelope *env)
{
    printf("  s3dupd %s pos=%s env=%s\n", name(s), name(pos), name(env));
    s->Volume = nuVol;
    s->Pitch = nuPitch;
    s->Azimuth = nuAz;
    s->SndToCameraDistance = dist_for(s);
}

void sound3d_update_cam_relative_dist_and_velocity(Sound3d *s,
                                                   const bVector3 *pos)
{
    printf("  camrel %s pos=%s\n", name(s), name(pos));
    s->SndToCameraDistance = dist_for(s);
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

BSound *bsound_get(void)
{
    return (BSound *)(void *)&fakebsound;
}

BRegion *bsound_region(const BSound *s, const char *nm)
{
    int i;

    printf("  region %s\n", nm);
    if (s != (const BSound *)(void *)&fakebsound)
        printf("  region: not bSound's\n");
    for (i = 0; i < NREG; i++)
        if (!strcmp(nm, regNames[i]))
            return (BRegion *)(void *)&regs[i];
    return NULL;
}

static BSample *src(const char *nm)
{
    int i;

    for (i = 0; i < NSRC; i++)
        if (!strcmp(nm, srcNames[i]))
            return &srcs[i];
    return NULL;
}

BSample *bregion_sample(const BRegion *r, const char *nm)
{
    printf("  rsample %s %s\n", name(r), nm);
    if (r == (const BRegion *)(void *)&regs[0]) {
        if (!strncmp(nm, "CopSiren", 8))
            return src(nm);
        return NULL;
    }
    if (r == (const BRegion *)(void *)&regs[1] && !strcmp(nm, "P0Horn"))
        return src(nm);
    return NULL;
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
    if (!strcmp(nm, "P0Horn") || !strcmp(nm, "Zone")
        || !strncmp(nm, "CopSiren", 8))
        return NULL;
    return src(nm);
}

int32_t sound_random_int(SoundModule *m, int32_t range)
{
    int32_t v = atRandI < nRandI ? randI[atRandI++] : 0;

    (void)m;
    printf("  randi %d -> %d\n", range, v);
    return v;
}

float sound_random_float(SoundModule *m, float range)
{
    uint32_t v = atRandF < nRandF ? randF[atRandF++] : 0;

    (void)m;
    printf("  randf %08x -> %08x\n", bits(range), v);
    return unbits(v);
}

// ------------------------------------------------------------ the heap

static const char *alloc_ok(const char *tag, int size)
{
    int want = -1;

    if (!strcmp(tag, "PlayerCarSound"))
        want = (int)sizeof(BasePlayerCarSound);
    else if (!strcmp(tag, "AICarSound"))
        want = (int)sizeof(BaseAICarSound);
    else if (!strcmp(tag, "HornSound3d"))
        want = (int)sizeof(HornSound3d);
    else if (!strcmp(tag, "SirenSound"))
        want = (int)sizeof(SirenSound3d);
    else if (!strcmp(tag, "..\\indep\\src\\carsounds.cpp"))
        want = (int)sizeof(TopologyCoordinate);
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

void topology_init(TopologyCoordinate *tc)
{
    printf("  tcctor %s\n", name(tc));
}

void topology_destroy(TopologyCoordinate *tc)
{
    printf("  tcdtor %s\n", name(tc));
}

// ------------------------------------------------------------ the car

typedef void (*VtSoundUpdateFn)(void *self, float volume, uint16_t azimuth,
                                float pitch);

// car.c's car_update_sound, as it is there.
void car_update_sound(Car *c)
{
    BaseCarSound *snd = c->pBaseCarSound;
    const VtEntry *e;

    if (!snd)
        return;
    e = vt_slot(((Sound3d *)snd)->_vtable, SOUND3D_VT_UPDATE);
    ((VtSoundUpdateFn)e->fn)(vt_this(snd, e), 1.0f, 0, 1.0f);
}

void car_world_to_car(Car *c, bVector2 *out, const bVector2 *in)
{
    printf("  w2c %s %08x %08x\n", name(c), bits(in->x), bits(in->y));
    out->x = in->x - c->State.Position.x;
    out->y = in->y - c->State.Position.y;
}

void player_clear_zone_sound(struct Player *p)
{
    printf("  clearzone %s\n", name(p));
}

// ------------------------------------------------------ the probes

static void p_destroy(void *s, int32_t flags)
{
    printf("  pdestroy %s %d\n", name(s), flags);
}

static void p_activate(void *s, int32_t on)
{
    printf("  pact %s %d\n", name(s), on);
    ((Sound3d *)s)->Activated = on;
}

static void p_update(void *s, float v, uint16_t az, float pitch)
{
    printf("  pupd %s %08x %d %08x\n", name(s), bits(v), az, bits(pitch));
}

static void p_mute(void *s, int32_t on)
{
    printf("  pmute %s %d\n", name(s), on);
}

static void p_deact(void *s)
{
    printf("  pdeact %s\n", name(s));
}

static void p_actsound(void *s)
{
    printf("  pactsound %s\n", name(s));
}

static void p_camrel(void *s, const bVector3 *pos)
{
    printf("  pcamrel %s %s\n", name(s), name(pos));
}

#define E(f) { 0, 0, (VtFn)(f) }

// Sound3d's own, for a record its destructor has run on: the horn the
// script deletes before its car's sound.
static const VtEntry s3d_vt[SOUND3D_VT_ENTRIES] = {
    { 0, 0, NULL }, E(sound3d_destroy), E(sound3d_activate),
};

static const VtEntry probe_vt[8] = {
    { 0, 0, NULL }, E(p_destroy), E(p_activate), E(p_update), E(p_mute),
    E(p_deact), E(p_actsound), E(p_camrel),
};

static Sound3d *new_probe(int kind)
{
    Sound3d *p = pattern(sizeof(Sound3d));

    p->Activated = 0;
    p->_vtable = PROBE_VT;
    probes[nprobes] = p;
    probeKind[nprobes] = kind;
    nprobes++;
    return p;
}

static Sound3d *mk_player_engine(Car *c)
{
    Sound3d *p = new_probe(0);

    printf("  mkeng player %s -> %s\n", name(c), name(p));
    return p;
}

static Sound3d *mk_ai_engine(Car *c)
{
    Sound3d *p = new_probe(0);

    printf("  mkeng ai %s -> %s\n", name(c), name(p));
    return p;
}

static Sound3d *mk_player_tire(Car *c, int32_t side)
{
    Sound3d *p = notires ? NULL : new_probe(1);

    printf("  mktire player %s %d -> %s\n", name(c), side, name(p));
    return p;
}

static Sound3d *mk_ai_tire(Car *c)
{
    Sound3d *p = notires ? NULL : new_probe(1);

    printf("  mktire ai %s -> %s\n", name(c), name(p));
    return p;
}

static void tire_blow(Sound3d *t)
{
    printf("  tblow %s\n", name(t));
}

static void tire_road(Sound3d *t, float f)
{
    printf("  troad %s %08x\n", name(t), bits(f));
}

// ------------------------------------------------------ the bodies

static bVector3 *b_position(void *b)
{
    int j = (int)((CarCollisionBody *)b - bodies);

    printf("  bpos %s\n", name(b));
    return &bodyPos[j];
}

static bVector3 *b_velocity(void *b)
{
    int j = (int)((CarCollisionBody *)b - bodies);

    printf("  bvel %s\n", name(b));
    return &bodyVel[j];
}

static int32_t b_terrain(void *b)
{
    int j = (int)((CarCollisionBody *)b - bodies);

    printf("  bterrain %s\n", name(b));
    return bodyTerrain[j];
}

static VtEntry body_vt[COLLISIONBODY_VT_ENTRIES];

void dynamiccollisionbody_get_local_collision_bodies(DynamicCollisionBody *d,
                                                     float margin,
                                                     CollisionBody **first,
                                                     CollisionBody **last)
{
    printf("  local %s %08x\n", name(d), bits(margin));
    *first = locFirst;
    *last = locLast;
}

static CollisionBody *body_ref(const char *f)
{
    if (f[0] == 'L')
        return (CollisionBody *)(void *)&CollisionBodyList;
    return &bodies[atoi(f)].Dynamic.Body;
}

// ------------------------------------------------------------ the dumps

static void dump3d(const char *label, const Sound3d *s)
{
    printf("  %s %s vt=%s act=%d dop=%d vol=%08x pitch=%08x az=%d vel=%08x "
           "dist=%08x\n", label, name(s), vtname(s->_vtable), s->Activated,
           s->DopplerIsActive, bits(s->Volume), bits(s->Pitch), s->Azimuth,
           bits(s->SndToCameraVelocity), bits(s->SndToCameraDistance));
}

static void dump(int k)
{
    BaseCarSound *s = snds[k];

    dump3d("snd", &s->Sound);
    printf("  base car=%s sl=%d sr=%d slt=%d srt=%d horn=%s siren=%s eng=%s "
           "pop=%s t0=%s t1=%s env=%s\n", name(s->pCar), s->SplashLeft,
           s->SplashRight, s->SplashLeftTimer, s->SplashRightTimer,
           name(s->HornSound), name(s->SirenSound), name(s->EngineSound),
           name(s->TireSoundBlowOut), name(s->TireSound[0]),
           name(s->TireSound[1]), name(s->pSoundEnvelope));
    if (s->Sound._vtable == BASEPLAYERCARSOUND_VTABLE) {
        BasePlayerCarSound *p = (BasePlayerCarSound *)s;

        printf("  player rev=%s rl=%d rr=%d chk=%d paz=%d\n",
               name(p->ReverbTopologyCoordinate), p->EngineReflectionLeft,
               p->EngineReflectionRight, p->CheckForReflected,
               p->PlayerAzimuth);
    }
    if (s->HornSound != NULL) {
        dump3d("horn", &s->HornSound->Sound);
        printf("  detune=%08x\n", bits(s->HornSound->DetunePitch));
    }
    if (s->SirenSound != NULL) {
        SirenSound3d *r = s->SirenSound;

        dump3d("siren", &r->Sound);
        printf("  cur=%d switch=%08x broken=%d target=%08x curr=%08x\n",
               r->CurrentSiren, bits(r->SwitchSirenTime), r->IsSirenBroken,
               bits(r->BrokenSirenPitchTarget),
               bits(r->CurrBrokenSirenPitch));
    }
}

static const struct {
    VtFn fn;
    const char *nm;
} fnames[] = {
    { (VtFn)basecarsound_destroy, "base-dtor" },
    { (VtFn)sound3d_activate, "activate" },
    { (VtFn)basecarsound_update, "base-update" },
    { (VtFn)basecarsound_mute, "base-mute" },
    { (VtFn)basecarsound_deactivate_sound, "base-deact" },
    { (VtFn)basecarsound_activate_sound, "base-act" },
    { (VtFn)sound3d_update_cam_relative_dist_and_velocity, "camrel" },
    { (VtFn)basecarsound_get_horn_sample, "base-horn" },
    { (VtFn)baseplayercarsound_destroy, "player-dtor" },
    { (VtFn)baseplayercarsound_update, "player-update" },
    { (VtFn)baseplayercarsound_mute, "player-mute" },
    { (VtFn)baseplayercarsound_get_horn_sample, "player-horn" },
    { (VtFn)baseaicarsound_destroy, "ai-dtor" },
    { (VtFn)baseaicarsound_update, "ai-update" },
    { (VtFn)hornsound3d_destroy, "horn-dtor" },
    { (VtFn)hornsound3d_update, "horn-update" },
    { (VtFn)hornsound3d_mute, "horn-mute" },
    { (VtFn)hornsound3d_deactivate_sound, "horn-deact" },
    { (VtFn)hornsound3d_activate_sound, "horn-act" },
    { (VtFn)sirensound3d_destroy, "siren-dtor" },
    { (VtFn)sirensound3d_update, "siren-update" },
    { (VtFn)sirensound3d_mute, "siren-mute" },
    { (VtFn)sirensound3d_deactivate_sound, "siren-deact" },
    { (VtFn)sirensound3d_activate_sound, "siren-act" },
};

static void dump_tables(void)
{
    static const struct {
        const char *label;
        uint32_t vt;
    } t[] = {
        { "base", BASECARSOUND_VTABLE },
        { "player", BASEPLAYERCARSOUND_VTABLE },
        { "ai", BASEAICARSOUND_VTABLE },
        { "horn", HORNSOUND3D_VTABLE },
        { "siren", SIRENSOUND3D_VTABLE },
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

static void *target(const char *f)
{
    BaseCarSound *s;

    if (f[0] == 'h')
        return snds[atoi(f + 1)]->HornSound;
    if (f[0] == 's')
        return snds[atoi(f + 1)]->SirenSound;
    if (f[0] == 'e')
        return probes[atoi(f + 1)];
    s = snds[atoi(f)];
    return s;
}

typedef void (*VtDestroyFn)(void *self, int32_t flags);
typedef void (*VtActivateFn)(void *self, int32_t on);
typedef void (*VtMuteFn)(void *self, int32_t on);
typedef void (*VtCamRelativeFn)(void *self, const bVector3 *pos);
typedef BSample *(*VtHornFn)(void *self);

static void link_world(char **f, int nf)
{
    CarNode *prev = (CarNode *)&world.CarList;
    int i;

    pCurrentWorld = &world;
    for (i = 1; i < nf; i++) {
        Car *c = cars[atoi(f[i])];

        prev->next = &c->Link;
        c->Link.prev = prev;
        prev = &c->Link;
    }
    prev->next = (CarNode *)&world.CarList;
    world.CarList.prev = prev;
}

static void op(char **f, int nf)
{
    const char *o = f[0];
    int k;

#define I(n) ((n) < nf ? (int)strtol(f[n], NULL, 0) : 0)
#define FB(n) ((n) < nf ? unbits((uint32_t)strtoul(f[n], NULL, 16)) : 0.0f)

    if (!strcmp(o, "tables")) {
        dump_tables();
    } else if (!strcmp(o, "statics")) {
        printf("  statics mpaz=%d penv=%08x,%08x,%08x aienv=%08x,%08x,%08x "
               "max=%d num=%d cse=%d cdse=%d rne=%d\n",
               CarSoundMultiPlayerAzimuth,
               bits(BasePlayerCarSoundEnvelope.MaxVolAtSource),
               bits(BasePlayerCarSoundEnvelope.CutOffDistance),
               bits(BasePlayerCarSoundEnvelope.Coeff),
               bits(BaseAICarSoundEnvelope.MaxVolAtSource),
               bits(BaseAICarSoundEnvelope.CutOffDistance),
               bits(BaseAICarSoundEnvelope.Coeff), MaxActiveCarSounds,
               NumClosestCarSounds, CarSoundEnabled, CarDamageSoundEnabled,
               RoadNoiseEnabled);
    } else if (!strcmp(o, "se")) {
        SoundEnabled = I(1);
    } else if (!strcmp(o, "cse")) {
        CarSoundEnabled = I(1);
    } else if (!strcmp(o, "cdse")) {
        CarDamageSoundEnabled = I(1);
    } else if (!strcmp(o, "rne")) {
        RoadNoiseEnabled = I(1);
    } else if (!strcmp(o, "npc")) {
        TheRaceParameters.NumPlayerCars = I(1);
    } else if (!strcmp(o, "dt")) {
        WorldTimeElapsed = FB(1);
    } else if (!strcmp(o, "mpaz")) {
        CarSoundMultiPlayerAzimuth = (uint16_t)I(1);
    } else if (!strcmp(o, "ri")) {
        randI[nRandI++] = I(1);
    } else if (!strcmp(o, "rf")) {
        randF[nRandF++] = (uint32_t)strtoul(f[1], NULL, 16);
    } else if (!strcmp(o, "nu")) {
        nuVol = FB(1);
        nuPitch = FB(2);
        nuAz = (uint16_t)I(3);
        nuDist = FB(4);
    } else if (!strcmp(o, "nd")) {
        k = I(1);
        ndSet[k] = 1;
        ndDist[k] = FB(2);
    } else if (!strcmp(o, "setpov")) {
        players[I(1)].PlayerSettings.DriveCameraPOVIndex = (int8_t)I(2);
    } else if (!strcmp(o, "notires")) {
        notires = I(1);
    } else if (!strcmp(o, "car")) {
        Car *c;

        k = I(1);
        c = cars[k] = pattern(sizeof(Car));
        c->DriverNumber = (int16_t)I(2);
        c->pCarTypeInfo = &types[k];
        types[k].UsageType = I(3);
        sprintf(types[k].Sound.BaseName, "Car%d", k);
        sprintf(types[k].Sound.Prefix, "P%d", k);
        c->MyDriver = &drivers[k];
        drivers[k].TheDriverType = (DriverType)I(4);
        if (I(5) >= 0) {
            c->pPlayer = &players[k];
            players[k].PlayerSettings.DriveCameraPOVIndex = (int8_t)I(5);
            players[k].pZoneSample = NULL;
            players[k].nZoneCurrent = 0;
        } else {
            c->pPlayer = NULL;
        }
        c->pBaseCarSound = NULL;
        c->TheSirenMode = SIREN_MODE_NONE;
        c->State.Position.x = c->State.Position.y = 0.0f;
        c->State.Position.z = c->State.Position.pad = 0.0f;
        c->State.VelocityMagnitude = 0.0f;
        c->pDynamicCollisionBody = NULL;
    } else if (!strcmp(o, "cpos")) {
        Car *c = cars[I(1)];

        c->State.Position.x = FB(2);
        c->State.Position.y = FB(3);
        c->State.Position.z = FB(4);
    } else if (!strcmp(o, "cvel")) {
        cars[I(1)]->State.VelocityMagnitude = FB(2);
    } else if (!strcmp(o, "csiren")) {
        cars[I(1)]->TheSirenMode = (SirenMode)I(2);
    } else if (!strcmp(o, "zone")) {
        k = I(1);
        players[k].pZoneSample = I(2) ? (struct bSample *)src("Zone") : NULL;
        players[k].nZoneCurrent = I(3);
    } else if (!strcmp(o, "world")) {
        link_world(f, nf);
    } else if (!strcmp(o, "noworld")) {
        pCurrentWorld = NULL;
    } else if (!strcmp(o, "mk")) {
        Car *c;

        k = I(1);
        c = cars[k];
        if (!strcmp(f[2], "player"))
            snds[k] = carsound_create_player(c);
        else if (!strcmp(f[2], "ai"))
            snds[k] = carsound_create_ai(c);
        else
            snds[k] = carsound_create_ai_cop(c);
        c->pBaseCarSound = snds[k];
        printf("  -> %s\n", name(snds[k]));
    } else if (!strcmp(o, "vc")) {
        void *t = target(f[1]);
        int slot = I(2);
        const VtEntry *e = vt_slot(((Sound3d *)t)->_vtable, slot);
        void *self = vt_this(t, e);

        switch (slot) {
        case 8:
            if (f[1][0] >= '0' && f[1][0] <= '9' && I(3) == 3)
                carsound_delete((BaseCarSound *)t, 3);
            else
                ((VtDestroyFn)e->fn)(self, I(3));
            break;
        case 16:
            ((VtActivateFn)e->fn)(self, I(3));
            break;
        case 24:
            ((VtSoundUpdateFn)e->fn)(self, FB(3), (uint16_t)I(4), FB(5));
            break;
        case 32:
            ((VtMuteFn)e->fn)(self, I(3));
            break;
        case 40:
        case 48:
            ((VtVoidFn)e->fn)(self);
            break;
        case 56:
            ((VtCamRelativeFn)e->fn)(self,
                                     &cars[I(3)]->State.Position);
            break;
        case 64:
            printf("  -> %s\n", name(((VtHornFn)e->fn)(self)));
            break;
        }
    } else if (!strcmp(o, "s3")) {
        Sound3d *s = target(f[1]);

        s->Activated = I(2);
        s->Volume = FB(3);
        s->Pitch = FB(4);
        s->Azimuth = (uint16_t)I(5);
        s->SndToCameraDistance = FB(6);
    } else if (!strcmp(o, "pov")) {
        printf("  = %08x\n", bits(carsound_get_pov_volume(cars[I(1)],
                                                          I(2))));
    } else if (!strcmp(o, "splash")) {
        basecarsound_trigger_splash(snds[I(1)], I(2), I(3));
    } else if (!strcmp(o, "usplash")) {
        BaseCarSound *s = snds[I(1)];

        if (I(2))
            basecarsound_update_splash(s, FB(3), &s->SplashRight,
                                       &s->SplashRightTimer);
        else
            basecarsound_update_splash(s, FB(3), &s->SplashLeft,
                                       &s->SplashLeftTimer);
    } else if (!strcmp(o, "settimer")) {
        BaseCarSound *s = snds[I(1)];

        s->SplashLeftTimer = I(2);
        s->SplashRightTimer = I(3);
    } else if (!strcmp(o, "uss")) {
        basecarsound_update_siren_sound(snds[I(1)]);
    } else if (!strcmp(o, "blow")) {
        basecarsound_trigger_tire_blow_out(snds[I(1)]);
    } else if (!strcmp(o, "road")) {
        basecarsound_scale_road_noise(snds[I(1)], FB(2));
    } else if (!strcmp(o, "sphere")) {
        printf("  = %d\n", basecarsound_in_sound_sphere(snds[I(1)]));
    } else if (!strcmp(o, "honk")) {
        basecarsound_start_honk_horn(snds[I(1)]);
    } else if (!strcmp(o, "stophonk")) {
        basecarsound_stop_honk_horn(snds[I(1)]);
    } else if (!strcmp(o, "ishonk")) {
        printf("  = %d\n", basecarsound_is_honking(snds[I(1)]));
    } else if (!strcmp(o, "splashs")) {
        printf("  -> %s\n", name(basecarsound_get_splash_sample(I(1))));
    } else if (!strcmp(o, "refls")) {
        printf("  -> %s\n", name(baseplayercarsound_get_engine_reflection_sample(
                                (BasePlayerCarSound *)snds[I(1)], I(2))));
    } else if (!strcmp(o, "windv")) {
        printf("  = %08x\n", bits(baseplayercarsound_calc_wind_volume(
                                (BasePlayerCarSound *)snds[I(1)], FB(2))));
    } else if (!strcmp(o, "windp")) {
        printf("  = %08x\n", bits(baseplayercarsound_calc_wind_pitch(
                                (BasePlayerCarSound *)snds[I(1)], FB(2))));
    } else if (!strcmp(o, "uer")) {
        baseplayercarsound_update_engine_reflection(
            (BasePlayerCarSound *)snds[I(1)], FB(2), (uint16_t)I(3), FB(4));
    } else if (!strcmp(o, "udbr")) {
        baseplayercarsound_update_dynamic_body_reflections(
            (BasePlayerCarSound *)snds[I(1)]);
    } else if (!strcmp(o, "refl")) {
        BasePlayerCarSound *p = (BasePlayerCarSound *)snds[I(1)];

        p->EngineReflectionLeft = I(2);
        p->EngineReflectionRight = I(3);
        p->CheckForReflected = I(4);
    } else if (!strcmp(o, "trt")) {
        printf("  -> %s\n", name(carsound_get_reverb_topology_coordinate(
                                snds[I(1)])));
    } else if (!strcmp(o, "ins")) {
        carsound_maybe_insert(snds[I(1)]);
    } else if (!strcmp(o, "actv")) {
        carsound_maybe_activate(snds[I(1)]);
    } else if (!strcmp(o, "ucs")) {
        carsound_update_car_sounds();
    } else if (!strcmp(o, "max")) {
        MaxActiveCarSounds = I(1);
    } else if (!strcmp(o, "closest")) {
        int i;

        printf("  closest max=%d num=%d", MaxActiveCarSounds,
               NumClosestCarSounds);
        for (i = 0; i < CARSOUND_MAX_CLOSEST; i++)
            printf(" %s", name(ClosestCarSounds[i]));
        printf("\n");
    } else if (!strcmp(o, "clearclosest")) {
        int i;

        for (i = 0; i < CARSOUND_MAX_CLOSEST; i++)
            ClosestCarSounds[i] = NULL;
        NumClosestCarSounds = 0;
    } else if (!strcmp(o, "choose")) {
        printf("  -> %s\n", name(hornsound3d_choose_horn_sample(
                                snds[I(1)]->HornSound)));
    } else if (!strcmp(o, "detune")) {
        snds[I(1)]->HornSound->DetunePitch = FB(2);
    } else if (!strcmp(o, "smode")) {
        sirensound3d_update_mode(snds[I(1)]->SirenSound, I(2));
    } else if (!strcmp(o, "sbroken")) {
        sirensound3d_set_siren_broken(snds[I(1)]->SirenSound, I(2));
    } else if (!strcmp(o, "sbp")) {
        printf("  = %08x\n", bits(sirensound3d_get_broken_siren_pitch(
                                snds[I(1)]->SirenSound)));
    } else if (!strcmp(o, "sset")) {
        SirenSound3d *r = snds[I(1)]->SirenSound;

        r->CurrentSiren = I(2);
        r->SwitchSirenTime = FB(3);
        r->BrokenSirenPitchTarget = FB(4);
        r->CurrBrokenSirenPitch = FB(5);
    } else if (!strcmp(o, "bplaying")) {
        BSample *b = &snds[I(1)]->SirenSound->SirenSampleTable[I(2)];

        set_playing(b, I(3));
    } else if (!strcmp(o, "body")) {
        int j = I(1);

        bodies[j].Dynamic.Body._vtable = BODY_VT;
        bodyPos[j].x = FB(2);
        bodyPos[j].y = FB(3);
        bodyPos[j].z = FB(4);
        bodyPos[j].pad = 0.0f;
        bodyVel[j].x = FB(5);
        bodyVel[j].y = FB(6);
        bodyVel[j].z = FB(7);
        bodyVel[j].pad = 0.0f;
        bodyTerrain[j] = I(8);
    } else if (!strcmp(o, "cbody")) {
        cars[I(1)]->pDynamicCollisionBody = &bodies[I(2)];
    } else if (!strcmp(o, "link")) {
        CollisionBody *prev = (CollisionBody *)(void *)&CollisionBodyList;
        int i;

        for (i = 1; i < nf; i++) {
            CollisionBody *b = &bodies[atoi(f[i])].Dynamic.Body;

            prev->Link.next = b;
            b->Link.prev = prev;
            prev = b;
        }
        prev->Link.next = (CollisionBody *)(void *)&CollisionBodyList;
        CollisionBodyList.prev = prev;
    } else if (!strcmp(o, "loc")) {
        locFirst = body_ref(f[1]);
        locLast = body_ref(f[2]);
    } else if (!strcmp(o, "d")) {
        dump(I(1));
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
        fprintf(stderr, "usage: carsound_test script.txt\n");
        return 2;
    }
    fh = fopen(argv[1], "r");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }

    carsound_install_vtables();
    vt_install(PROBE_VT, probe_vt, 8);
    vt_install(SOUND3D_VTABLE, s3d_vt, SOUND3D_VT_ENTRIES);
    body_vt[VT_SLOT(COLLISIONBODY_VT_GET_POSITION)].fn = (VtFn)b_position;
    body_vt[VT_SLOT(COLLISIONBODY_VT_GET_VELOCITY)].fn = (VtFn)b_velocity;
    body_vt[VT_SLOT(COLLISIONBODY_VT_GET_TERRAIN_TYPE)].fn = (VtFn)b_terrain;
    vt_install(BODY_VT, body_vt, COLLISIONBODY_VT_ENTRIES);
    CarSoundMultiPlayerAzimuth = 10922;
    gCreatePlayerEngineFn = mk_player_engine;
    gCreateAIEngineFn = mk_ai_engine;
    gCreatePlayerTireFn = mk_player_tire;
    gCreateAITireFn = mk_ai_tire;
    gTireSoundTriggerBlowOutFn = tire_blow;
    gTireSoundScaleRoadNoiseFn = tire_road;
    CollisionBodyList.next = (CollisionBody *)(void *)&CollisionBodyList;
    CollisionBodyList.prev = (CollisionBody *)(void *)&CollisionBodyList;
    world.CarList.next = world.CarList.prev = &world.CarList;

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
