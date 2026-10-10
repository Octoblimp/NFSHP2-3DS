// Harness for tools/collisionsound_check.py: runs the checker's script on
// collisionsound.c and prints what the model prints for the retail image.
// bSample, GetCategoryVolume, the in-game samples, sound's random float and
// IsSoundRegionLoadingComplete, Sound3d's ComputeVolume and ComputeAzimuth,
// sound3d_oneshot's two Plays, the slot pool, eGetView and Collision's
// GetTerrainType are logging fakes, the same fakes the checker gives
// retail's code. See the checker's docstring.
//
//     collisionsound_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bslotpool.h"
#include "bsound.h"
#include "camera.h"
#include "collision.h"
#include "collisionsound.h"
#include "eview.h"
#include "race.h"
#include "realtime.h"
#include "smokeable.h"
#include "sound.h"
#include "sound3d.h"
#include "vtable.h"
#include "world.h"

int32_t        SoundEnabled = 1;
int32_t        WorldTimer;
World         *pCurrentWorld;
RaceParameters TheRaceParameters;

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

#define MAXCOLL  32
#define MAXSLOT  128
#define MAXSRC   64
#define MAXSHOT  32
#define MAXSMK   8
#define MAXQ     128

static World          world;
static Collision     *colls[MAXCOLL];
static int32_t        terrain[MAXCOLL];
static SmokeableInfo *smks[MAXSMK];
static Camera         cams[3];
static eView          views[3];
static bVector3       posv;
static int            fakebsound;
static SoundModule    fakemod;
static float          catVolume;
static int            regionDone;
static int            noShot;

static void *slots[MAXSLOT];
static int   nslots;
static int   pools[4];
static int   npools;

static Sound3dSample *shots[MAXSHOT];
static int            nshots;

// The samples GetInGameSample hands out, one a name; `nosrc` names get
// none.
static struct {
    char    nm[32];
    BSample s;
} srcs[MAXSRC];
static int  nsrcs;
static char nosrc[8][32];
static int  nnosrc;

static uint32_t randF[MAXQ], cvolQ[MAXQ], azQ[MAXQ];
static int      nRandF, atRandF, nCvol, atCvol, nAz, atAz;

// bSample's playing flag and GetVolume's answer, by sample.
static const BSample *playing[MAXSLOT];
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
    if (on && nplaying < MAXSLOT)
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

static uint32_t pop(uint32_t *q, int n, int *at)
{
    return *at < n ? q[(*at)++] : 0;
}

static const char *name(const void *p)
{
    static char buf[8][48];
    static int k;
    char *b = buf[k++ & 7];
    int i;

    if (p == NULL)
        return "0";
    if (p == (const void *)&fakebsound)
        return "bsound";
    if (p == &posv)
        return "pos";
    for (i = 0; i < nslots; i++) {
        if (p == slots[i]) {
            sprintf(b, "c%d", i);
            return b;
        }
    }
    for (i = 0; i < nsrcs; i++) {
        if (p == &srcs[i].s) {
            sprintf(b, "src:%s", srcs[i].nm);
            return b;
        }
    }
    for (i = 0; i < MAXCOLL; i++) {
        if (colls[i] == NULL)
            continue;
        if (p == colls[i]) {
            sprintf(b, "k%d", i);
            return b;
        }
        if (p == &colls[i]->InitialContactPoint) {
            sprintf(b, "k%d.icp", i);
            return b;
        }
        if (p == &colls[i]->CurrentContactPoint) {
            sprintf(b, "k%d.ccp", i);
            return b;
        }
    }
    for (i = 0; i < nshots; i++) {
        if (p == shots[i]) {
            sprintf(b, "o%d", i);
            return b;
        }
        if (p == &shots[i]->Sample) {
            sprintf(b, "o%d.s", i);
            return b;
        }
    }
    for (i = 0; i < npools; i++) {
        if (p == &pools[i]) {
            sprintf(b, "pool%d", i);
            return b;
        }
    }
    return "?";
}

// A sample by the script's name: a pool slot (c3), a collision's Sample or
// Scrape (k4.sa, k4.sc), an in-game sample (src:CrashWood01) or a
// one-shot's (o1).
static BSample *sample_ref(const char *w)
{
    int i;

    if (w[0] == 'k') {
        Collision *c = colls[atoi(w + 1)];
        const char *dot = strchr(w, '.');
        CollisionSample *s = dot != NULL && dot[2] == 'a' ? c->Sample
                                                          : c->Scrape;

        if (s != NULL)
            return &s->Sample;
    } else if (w[0] == 'c' && w[1] >= '0' && w[1] <= '9') {
        i = atoi(w + 1);
        if (i < nslots)
            return (BSample *)slots[i];
    } else if (!strncmp(w, "src:", 4)) {
        for (i = 0; i < nsrcs; i++)
            if (!strcmp(srcs[i].nm, w + 4))
                return &srcs[i].s;
    } else if (w[0] == 'o') {
        i = atoi(w + 1);
        if (i < nshots)
            return &shots[i]->Sample;
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

void bsample_destruct(BSample *s)
{
    printf("  bdtor %s\n", name(s));
}

void bsample_initialize_copy(BSample *s, const BSample *other)
{
    printf("  binit %s from %s\n", name(s), name(other));
}

// Kept, as retail's is; a missing sample's is not.
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

// ---------------------------------------------------------------- bSound

BSound *bsound_get(void)
{
    return (BSound *)(void *)&fakebsound;
}

float bsound_get_category_volume(const BSound *s, uint32_t category)
{
    printf("  catvol %s %u -> %08x\n", name(s), category, bits(catVolume));
    return catVolume;
}

// ---------------------------------------------------------------- sound

SoundModule *sound_get(void)
{
    return &fakemod;
}

static int listed(char (*list)[32], int n, const char *nm)
{
    int i;

    for (i = 0; i < n; i++)
        if (!strcmp(list[i], nm))
            return 1;
    return 0;
}

static BSample *src(const char *nm)
{
    int i;

    for (i = 0; i < nsrcs; i++)
        if (!strcmp(srcs[i].nm, nm))
            return &srcs[i].s;
    strcpy(srcs[nsrcs].nm, nm);
    return &srcs[nsrcs++].s;
}

BSample *sound_get_in_game_sample(SoundModule *m, const char *nm)
{
    printf("  ingame %s\n", nm);
    if (m != &fakemod)
        printf("  ingame: not the module\n");
    if (listed(nosrc, nnosrc, nm))
        return NULL;
    return src(nm);
}

float sound_random_float(SoundModule *m, float range)
{
    uint32_t v = pop(randF, nRandF, &atRandF);

    if (m != &fakemod)
        printf("  randf: not the module\n");
    printf("  randf %08x -> %08x\n", bits(range), v);
    return unbits(v);
}

int sound_is_region_loading_complete(const SoundModule *m)
{
    (void)m;
    printf("  rlc -> %d\n", regionDone);
    return regionDone;
}

// --------------------------------------------------------------- Sound3d

uint16_t sound3d_compute_azimuth(const bVector3 *pos)
{
    uint32_t v = pop(azQ, nAz, &atAz) & 0xffff;

    printf("  caz %s -> %u\n", name(pos), v);
    return (uint16_t)v;
}

float sound3d_compute_volume(const bVector3 *pos, float cutOff)
{
    uint32_t v = pop(cvolQ, nCvol, &atCvol);

    printf("  cvol %s %08x -> %08x\n", name(pos), bits(cutOff), v);
    return unbits(v);
}

static Sound3dSample *new_shot(void)
{
    Sound3dSample *s;

    if (noShot)
        return NULL;
    s = pattern(sizeof(Sound3dSample));
    s->Envelope.MaxVolAtSource = 0.0f;
    s->Envelope.CutOffDistance = 0.0f;
    s->Envelope.Coeff = 0.0f;
    s->Sample.category = 7;
    shots[nshots++] = s;
    return s;
}

Sound3dSample *sound3d_oneshot_play(BSample *sample, const bVector3 *pos,
                                    float volume, float pitch)
{
    Sound3dSample *s = new_shot();

    printf("  oneshot %s %s %08x %08x -> %s\n", name(sample), name(pos),
           bits(volume), bits(pitch), name(s));
    return s;
}

Sound3dSample *sound3d_oneshot_play_named(struct SoundModule *m,
                                          const char *nm,
                                          const bVector3 *pos, float volume,
                                          float pitch)
{
    Sound3dSample *s = new_shot();

    if (m != &fakemod)
        printf("  oneshotn: not the module\n");
    printf("  oneshotn %s %s %08x %08x -> %s\n", nm, name(pos),
           bits(volume), bits(pitch), name(s));
    return s;
}

// ------------------------------------------------------------ the pool

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *nm,
                        int flags)
{
    BSlotPool *p = (BSlotPool *)(void *)&pools[npools++];

    printf("  newpool %s %d %d size-%s -> %s\n", nm, numSlots, flags,
           slotSize == (int)sizeof(CollisionSample) ? "ok" : "BAD",
           name(p));
    return p;
}

void bDeleteSlotPool(BSlotPool *pool)
{
    printf("  delpool %s\n", name(pool));
}

void *bSlotOMalloc(BSlotPool *pool)
{
    void *p = pattern(sizeof(CollisionSample));

    slots[nslots++] = p;
    printf("  omalloc %s -> %s\n", name(pool), name(p));
    return p;
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    printf("  pfree %s %s\n", name(pool), name(slot));
}

// ------------------------------------------------------- the rest it calls

eView *eGetView(int32_t id)
{
    printf("  view %d\n", id);
    return &views[id];
}

int32_t collision_get_terrain_type(Collision *c)
{
    int i;

    for (i = 0; i < MAXCOLL; i++) {
        if (colls[i] == c) {
            printf("  terrain %s -> %d\n", name(c), terrain[i]);
            return terrain[i];
        }
    }
    printf("  terrain %s -> ?\n", name(c));
    return 0;
}

// ------------------------------------------------------------ the dumps

static void dump_globals(void)
{
    static const struct {
        const char    *nm;
        SampleLibrary *l;
    } libs[] = {
        { "small", &CollisionMetalSamples[0] },
        { "medium", &CollisionMetalSamples[1] },
        { "hard", &CollisionMetalSamples[2] },
        { "wood", &CollisionWoodSamples },
        { "foil", &CollisionFoilageSamples },
    };
    size_t i;

    printf("  gd loaded=%d table=%d pool=%s petrol=%08x gas=%08x"
           " ms=%s ws=%s gb=%s\n",
           CollisionSoundRegionsLoaded, CollisionSampleTableLoaded,
           name(CollisionSamplePool), CollisionPetrolPumpNameHash,
           CollisionGasPumpNameHash, name(CollisionMetalScraping),
           name(CollisionWoodScraping), name(CollisionGlassBreaking));
    for (i = 0; i < sizeof(libs) / sizeof(libs[0]); i++)
        printf("  lib %s %s %s %s %d\n", libs[i].nm,
               name(libs[i].l->Samples[0]), name(libs[i].l->Samples[1]),
               name(libs[i].l->Samples[2]), libs[i].l->CurrSampleIndex);
}

static const char *node_name(const bNode *n)
{
    if (n == &CollisionFreeSampleList)
        return "head";
    return name((const char *)n - offsetof(CollisionSample, Node));
}

// The free list both ways, at most 64 a way.
static void dump_free(void)
{
    const bNode *n;
    int k;

    printf("  fl");
    for (n = CollisionFreeSampleList.next, k = 0;
         n != &CollisionFreeSampleList && k < 64; n = n->next, k++)
        printf(" %s", node_name(n));
    printf(" |");
    for (n = CollisionFreeSampleList.prev, k = 0;
         n != &CollisionFreeSampleList && k < 64; n = n->prev, k++)
        printf(" %s", node_name(n));
    printf("\n");
}

static void dump_coll(int k)
{
    Collision *c = colls[k];

    printf("  cd %s sample=%s scrape=%s\n", name(c), name(c->Sample),
           name(c->Scrape));
}

static void dump_sample(const char *w)
{
    CollisionSample *s = (CollisionSample *)sample_ref(w);

    if (s != NULL)
        printf("  sd %s vt=%08x\n", name(s), s->_vtable);
}

static void dump_shots(void)
{
    int i;

    for (i = 0; i < nshots; i++)
        printf("  od %s max=%08x cut=%08x coeff=%08x cat=%u\n",
               name(shots[i]), bits(shots[i]->Envelope.MaxVolAtSource),
               bits(shots[i]->Envelope.CutOffDistance),
               bits(shots[i]->Envelope.Coeff), shots[i]->Sample.category);
}

static void dump_tables(void)
{
    int n, k;
    const VtEntry *e = vt_table(COLLISIONSAMPLE_VTABLE, &n);

    if (e == NULL) {
        printf("  vt missing\n");
        return;
    }
    printf("  vt %d entries\n", n);
    for (k = 1; k < n; k++)
        printf("  vt %d %d %s\n", 8 * k, e[k].delta,
               e[k].fn == (VtFn)collisionsample_destroy ? "dtor"
               : e[k].fn == NULL ? "pure" : "?");
}

// ------------------------------------------------------------- the ops

static void new_coll(int k)
{
    Collision *c = colls[k] = pattern(sizeof(Collision));
    WorldList *l = &world.CollisionList;
    Collision *tail = (Collision *)l->prev;

    c->CollisionTime.PackedTime = 0;
    memset(&c->InitialContactPoint, 0, sizeof(c->InitialContactPoint));
    memset(&c->CurrentContactPoint, 0, sizeof(c->CurrentContactPoint));
    c->CurrentScrapeSpeed = 0.0f;
    c->TotalImpulseMagnitude = 0.0f;
    c->Sample = NULL;
    c->Scrape = NULL;
    terrain[k] = 0;
    // AddTail.
    c->Link.next = (Collision *)(void *)l;
    c->Link.prev = tail;
    if ((void *)tail == (void *)l)
        l->next = c;
    else
        tail->Link.next = c;
    l->prev = c;
}

static void unlink_coll(int k)
{
    Collision *c = colls[k];
    void *next = c->Link.next, *prev = c->Link.prev;
    WorldList *l = &world.CollisionList;

    if (prev == (void *)l)
        l->next = next;
    else
        ((Collision *)prev)->Link.next = next;
    if (next == (void *)l)
        l->prev = prev;
    else
        ((Collision *)next)->Link.prev = prev;
}

static void set_vec(bVector3 *v, char **f)
{
    v->x = unbits((uint32_t)strtoul(f[0], NULL, 16));
    v->y = unbits((uint32_t)strtoul(f[1], NULL, 16));
    v->z = unbits((uint32_t)strtoul(f[2], NULL, 16));
}

static void op(char **f, int nf)
{
#define I(k) ((k) < nf ? (int)strtol(f[k], NULL, 0) : 0)
#define U(k) ((k) < nf ? (uint32_t)strtoul(f[k], NULL, 16) : 0u)
#define FB(k) unbits(U(k))
#define POS(k) (&colls[I(k)]->InitialContactPoint)
    const char *o = f[0];

    if (!strcmp(o, "tables")) {
        dump_tables();
    } else if (!strcmp(o, "se")) {
        SoundEnabled = I(1);
    } else if (!strcmp(o, "wt")) {
        WorldTimer = I(1);
    } else if (!strcmp(o, "npc")) {
        TheRaceParameters.NumPlayerCars = I(1);
    } else if (!strcmp(o, "world")) {
        pCurrentWorld = I(1) ? &world : NULL;
    } else if (!strcmp(o, "cam")) {
        bVector3 *p = &cams[I(1)].CurrentKey.Position;

        set_vec(p, f + 2);
    } else if (!strcmp(o, "coll")) {
        new_coll(I(1));
    } else if (!strcmp(o, "unlink")) {
        unlink_coll(I(1));
    } else if (!strcmp(o, "cset")) {
        Collision *c = colls[I(1)];

        c->CollisionTime.PackedTime = (uint32_t)I(2);
        c->TotalImpulseMagnitude = FB(3);
        c->CurrentScrapeSpeed = FB(4);
        terrain[I(1)] = I(5);
    } else if (!strcmp(o, "cpos")) {
        Collision *c = colls[I(1)];

        set_vec(f[2][0] == 'i' ? &c->InitialContactPoint
                               : &c->CurrentContactPoint, f + 3);
    } else if (!strcmp(o, "csample")) {
        colls[I(1)]->Sample = !strcmp(f[2], "0") ? NULL
            : (CollisionSample *)sample_ref(f[2]);
    } else if (!strcmp(o, "cscrape")) {
        colls[I(1)]->Scrape = !strcmp(f[2], "0") ? NULL
            : (CollisionSample *)sample_ref(f[2]);
    } else if (!strcmp(o, "hash")) {
        CollisionPetrolPumpNameHash = U(1);
        CollisionGasPumpNameHash = U(2);
    } else if (!strcmp(o, "tbl")) {
        CollisionSampleTableLoaded = I(1);
    } else if (!strcmp(o, "rf")) {
        randF[nRandF++] = U(1);
    } else if (!strcmp(o, "cv")) {
        cvolQ[nCvol++] = U(1);
    } else if (!strcmp(o, "az")) {
        azQ[nAz++] = (uint32_t)I(1);
    } else if (!strcmp(o, "rlc")) {
        regionDone = I(1);
    } else if (!strcmp(o, "catvol")) {
        catVolume = FB(1);
    } else if (!strcmp(o, "noshot")) {
        noShot = I(1);
    } else if (!strcmp(o, "nosrc")) {
        strcpy(nosrc[nnosrc++], f[1]);
    } else if (!strcmp(o, "unsrc")) {
        nnosrc = 0;
    } else if (!strcmp(o, "bplaying")) {
        set_playing(sample_ref(f[1]), I(2));
    } else if (!strcmp(o, "bgv")) {
        set_vol(sample_ref(f[1]), U(2));
    } else if (!strcmp(o, "smk")) {
        SmokeableInfo *s = smks[I(1)] = pattern(sizeof(SmokeableInfo));

        s->NameHash = bchunk_hash(f[2]);
        s->TheTerrainType = I(3);
    } else if (!strcmp(o, "type")) {
        printf("  -> %s\n",
               name(collisionsounds_get_collision_sound_type(colls[I(1)])));
    } else if (!strcmp(o, "reg")) {
        collisionsounds_register();
    } else if (!strcmp(o, "load")) {
        collisionsounds_load_sample_table();
    } else if (!strcmp(o, "unreg")) {
        collisionsounds_unregister();
    } else if (!strcmp(o, "dist")) {
        set_vec(&posv, f + 1);
        printf("  = %08x\n", bits(collisionsounds_get_distance_to_camera(&posv)));
    } else if (!strcmp(o, "vol")) {
        printf("  = %08x\n",
               bits(collisionsounds_calc_collision_volume(colls[I(1)])));
    } else if (!strcmp(o, "svol")) {
        printf("  = %08x\n", bits(
            collisionsounds_calc_collision_scrape_volume(colls[I(1)])));
    } else if (!strcmp(o, "azc")) {
        printf("  = %d\n",
               collisionsounds_calc_collision_azimuth(colls[I(1)]));
    } else if (!strcmp(o, "start")) {
        collisionsounds_start_scraping(colls[I(1)]);
    } else if (!strcmp(o, "usample")) {
        collisionsounds_update_sample(colls[I(1)]);
    } else if (!strcmp(o, "update")) {
        collisionsounds_update();
    } else if (!strcmp(o, "mute")) {
        collisionsounds_mute(I(1));
    } else if (!strcmp(o, "csreg")) {
        collision_sound_register();
    } else if (!strcmp(o, "csunreg")) {
        collision_sound_unregister();
    } else if (!strcmp(o, "csupdate")) {
        collision_sound_update();
    } else if (!strcmp(o, "csmute")) {
        collision_sound_mute(I(1));
    } else if (!strcmp(o, "reset")) {
        collision_sound_reset();
    } else if (!strcmp(o, "create")) {
        printf("  -> %s\n", name(collision_sound_create_sample(colls[I(1)])));
    } else if (!strcmp(o, "screate")) {
        // As Update does: the answer kept as the collision's Sample.
        colls[I(1)]->Sample = collision_sound_create_sample(colls[I(1)]);
        printf("  -> %s\n", name(colls[I(1)]->Sample));
    } else if (!strcmp(o, "release")) {
        collision_sound_release_sample(colls[I(1)]);
    } else if (!strcmp(o, "foil")) {
        collision_sound_play_foilage(POS(1));
    } else if (!strcmp(o, "generic")) {
        collision_sound_play_generic_smokable(POS(1));
    } else if (!strcmp(o, "smoke")) {
        collision_sound_play_smokeable(POS(1),
                                       I(2) < 0 ? NULL : smks[I(2)]);
    } else if (!strcmp(o, "glass")) {
        collision_sound_play_glass(POS(1));
    } else if (!strcmp(o, "bust")) {
        collision_sound_play_bust_road_block(POS(1));
    } else if (!strcmp(o, "boom")) {
        collision_sound_play_explosion(POS(1));
    } else if (!strcmp(o, "scrape")) {
        collision_sound_play_scrape(colls[I(1)]);
    } else if (!strcmp(o, "gd")) {
        dump_globals();
    } else if (!strcmp(o, "cd")) {
        dump_coll(I(1));
    } else if (!strcmp(o, "fl")) {
        dump_free();
    } else if (!strcmp(o, "sd")) {
        dump_sample(f[1]);
    } else if (!strcmp(o, "od")) {
        dump_shots();
    } else {
        printf("  unknown op %s\n", o);
    }
#undef I
#undef U
#undef FB
#undef POS
}

int main(int argc, char **argv)
{
    char line[512];
    FILE *fh;
    int i;

    if (argc < 2) {
        fprintf(stderr, "usage: collisionsound_test script.txt\n");
        return 2;
    }
    fh = fopen(argv[1], "r");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
    world.CollisionList.next = world.CollisionList.prev =
        &world.CollisionList;
    for (i = 0; i < 3; i++)
        views[i].pCamera = &cams[i];

    collisionsound_install_vtables();

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
