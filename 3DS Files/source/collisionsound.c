#include "collisionsound.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#include "bchunk.h"
#include "camera.h"
#include "carinit.h"
#include "collision.h"
#include "eefpu.h"
#include "eview.h"
#include "race.h"
#include "realtime.h"
#include "smokeable.h"
#include "sound.h"
#include "sound3d.h"
#include "terraintype.h"
#include "vtable.h"
#include "world.h"

SampleLibrary CollisionFoilageSamples;          // 0x0031a778
SampleLibrary CollisionWoodSamples;             // 0x0031a788
SampleLibrary CollisionMetalSamples[3];         // 0x0031a798

BSample   *CollisionMetalScraping;              // gp-17240
BSample   *CollisionWoodScraping;               // gp-17244
BSample   *CollisionGlassBreaking;              // gp-17248
int32_t    CollisionSoundRegionsLoaded;         // gp-17236
int32_t    CollisionSampleTableLoaded = 1;      // gp-17264
uint32_t   CollisionPetrolPumpNameHash;         // gp-17272
uint32_t   CollisionGasPumpNameHash;            // gp-17268
// The static constructor (0x001e5d98) points the sentinel at itself.
bNode      CollisionFreeSampleList = {
    &CollisionFreeSampleList, &CollisionFreeSampleList
};
BSlotPool *CollisionSamplePool;                 // gp-17288

typedef void (*VtDestroyFn)(void *self, int32_t flags);

// ---------------------------------------------------------------- helpers

#define NODE_SAMPLE(n) \
    ((CollisionSample *)((char *)(n) - offsetof(CollisionSample, Node)))

// bTList's Remove: the neighbours joined, the node's own links left.
static void unlink_node(bNode *n)
{
    bNode *next = n->next;
    bNode *prev = n->prev;

    prev->next = next;
    next->prev = prev;
}

// AddHead.
static void push_free(CollisionSample *s)
{
    bNode *old = CollisionFreeSampleList.next;

    CollisionFreeSampleList.next = &s->Node;
    old->prev = &s->Node;
    s->Node.prev = &CollisionFreeSampleList;
    s->Node.next = old;
}

// `delete s`, through slot 8.
static void delete_sample(CollisionSample *s)
{
    const VtEntry *e = vt_slot(s->_vtable, COLLISIONSAMPLE_VT_DESTROY);

    ((VtDestroyFn)e->fn)(vt_this(s, e), 3);
}

// Every sample on the free list off it and deleted.
static void delete_free_samples(void)
{
    bNode *n = CollisionFreeSampleList.next;

    while (n != &CollisionFreeSampleList) {
        bNode *next = n->next;

        unlink_node(n);
        delete_sample(NODE_SAMPLE(n));
        n = next;
    }
}

// SampleLibrary<3>::GetSample: the next of the three, in turn.
static BSample *library_next(SampleLibrary *l)
{
    l->CurrSampleIndex = (l->CurrSampleIndex + 1) % 3;
    return l->Samples[l->CurrSampleIndex];
}

// SampleLibrary<3>::LoadSamples, inline in LoadSampleTable: `name` and
// "01", its last character 1, 2 and 3 in turn.
static void library_load(SampleLibrary *l, const char *name)
{
    char buf[32];
    size_t last;
    int32_t i;

    strcpy(buf, name);
    strcat(buf, "01");
    last = strlen(buf) - 1;
    for (i = 0; i < 3; i++) {
        buf[last] = (char)('1' + i);
        l->Samples[i] = sound_get_in_game_sample(sound_get(), buf);
        bsample_set_category(l->Samples[i], 0);
    }
    l->CurrSampleIndex = 0;
}

// How long the collision has been going, in seconds.
static float collision_age(const Collision *c)
{
    return (float)(int32_t)((uint32_t)WorldTimer - c->CollisionTime.PackedTime)
           * 0.00025f;                          // gp-28200
}

// A new sample from the pool, a copy of `src`.
static CollisionSample *new_sample(const BSample *src)
{
    CollisionSample *s = (CollisionSample *)bSlotOMalloc(CollisionSamplePool);

    bsample_construct(&s->Sample, 0);
    s->_vtable = COLLISIONSAMPLE_VTABLE;
    collisionsample_initialize(s, src);
    return s;
}

// The VU0's (x*x + y*y) + z*z.
static float dist_to(const bVector3 *pos, const struct Camera *cam)
{
    float x = cam->CurrentKey.Position.x - pos->x;
    float y = cam->CurrentKey.Position.y - pos->y;
    float z = cam->CurrentKey.Position.z - pos->z;

    return ee_sqrt((x * x + y * y) + z * z);
}

// ------------------------------------------------------- CollisionSample

void collisionsample_initialize(CollisionSample *s, const BSample *src)
{
    bsample_initialize_copy(&s->Sample, src);
}

void collisionsample_destroy(CollisionSample *s, int32_t flags)
{
    s->_vtable = COLLISIONSAMPLE_VTABLE;
    bsample_stop(&s->Sample);
    bsample_destruct(&s->Sample);
    if (flags & 1)
        bSlotFree(CollisionSamplePool, s);
}

// ------------------------------------------------------- CollisionSounds

BSample *collisionsounds_get_collision_sound_type(Collision *c)
{
    int32_t terrain = collision_get_terrain_type(c);
    int32_t idx;

    if (terrain < TERRAIN_TYPE_SOLID_WALL
        && terrain >= TERRAIN_TYPE_WOOD_WALL)
        return library_next(&CollisionWoodSamples);
    idx = ee_trunc_w(c->TotalImpulseMagnitude * (1.0f / 30.0f)   // gp-28216
                     * 3.0f);
    if (idx >= 3)
        idx = 2;
    else if (idx < 0)
        idx = 0;
    return library_next(&CollisionMetalSamples[idx]);
}

void collisionsounds_register(void)
{
    CollisionSoundRegionsLoaded = 0;
    if (CollisionSamplePool == NULL)
        CollisionSamplePool = bNewSlotPool((int)sizeof(CollisionSample), 40,
                                           "CollisionSampleSounds", 16);
    if (CollisionPetrolPumpNameHash == 0) {
        CollisionPetrolPumpNameHash = bchunk_hash("CS_PetrolPump");
        CollisionGasPumpNameHash = bchunk_hash("CS_GasPump");
    }
}

void collisionsounds_load_sample_table(void)
{
    CollisionSampleTableLoaded = 1;
    library_load(&CollisionMetalSamples[0], "CrashMetalSmall");
    library_load(&CollisionMetalSamples[1], "CrashMetalMedium");
    library_load(&CollisionMetalSamples[2], "CrashMetalHard");
    library_load(&CollisionWoodSamples, "CrashWood");
    library_load(&CollisionFoilageSamples, "CrashFoilage");
    CollisionMetalScraping = sound_get_in_game_sample(sound_get(),
                                                      "CrashMetalScrape");
    bsample_set_category(CollisionMetalScraping, 0);
    CollisionWoodScraping = sound_get_in_game_sample(sound_get(),
                                                     "CrashWoodScrape");
    bsample_set_category(CollisionWoodScraping, 0);
    CollisionGlassBreaking = sound_get_in_game_sample(sound_get(),
                                                      "CrashGlass01");
    bsample_set_category(CollisionGlassBreaking, 0);
}

void collisionsounds_unregister(void)
{
    CollisionSoundRegionsLoaded = 0;
    delete_free_samples();
    if (CollisionSamplePool != NULL) {
        bDeleteSlotPool(CollisionSamplePool);
        CollisionSamplePool = NULL;
    }
}

float collisionsounds_get_distance_to_camera(const bVector3 *pos)
{
    float d = dist_to(pos, eGetView(1)->pCamera);

    if (TheRaceParameters.NumPlayerCars >= 2) {
        float d2 = dist_to(pos, eGetView(2)->pCamera);

        if (d2 < d)
            d = d2;
    }
    return d;
}

// Out to 35 from the camera: as loud as the impulse, at most 1, and all of
// it within 35.
float collisionsounds_calc_collision_volume(Collision *c)
{
    float d = collisionsounds_get_distance_to_camera(&c->InitialContactPoint);
    float v, near;

    if (!(d < 35.0f))
        return 0.0f;
    v = c->TotalImpulseMagnitude * (1.0f / 30.0f)  // gp-28208
        * 0.65f;                                    // gp-28204
    if (1.0f < v)
        v = 1.0f;
    near = ee_div(35.0f, d);
    if (1.0f < near)
        near = 1.0f;
    return near * v;
}

float collisionsounds_calc_collision_scrape_volume(Collision *c)
{
    float v = collisionsounds_calc_collision_volume(c)
              * (c->CurrentScrapeSpeed * (1.0f / 6.0f));   // gp-28212

    if (1.0f < v)
        v = 1.0f;
    return v;
}

int32_t collisionsounds_calc_collision_azimuth(Collision *c)
{
    (void)c;
    return 0;
}

// A wood or cactus wall's scrape or a solid wall's, once the collision is
// a tenth of a second old.
void collisionsounds_start_scraping(Collision *c)
{
    int32_t terrain;
    const BSample *src;
    CollisionSample *s;
    float vol;

    if (collision_age(c) < 0.1f)                // gp-28196
        return;
    terrain = collision_get_terrain_type(c);
    if (terrain < TERRAIN_TYPE_WOOD_WALL)
        src = NULL;
    else if (terrain < TERRAIN_TYPE_SOLID_WALL)
        src = CollisionWoodScraping;
    else if (terrain == TERRAIN_TYPE_SOLID_WALL)
        src = CollisionMetalScraping;
    else
        src = NULL;
    if (src == NULL)
        return;
    s = new_sample(src);
    c->Scrape = s;
    vol = collisionsounds_calc_collision_scrape_volume(c);
    if (SoundEnabled) {
        bsample_set_azimuth(&s->Sample,
                            sound3d_compute_azimuth(&c->CurrentContactPoint));
        bsample_play(&s->Sample, vol * 1.9f, 0.0f, 0.0f);   // gp-28192
        bsample_set_pitch(&s->Sample,
                          sound_random_float(sound_get(), 0.36f)  // gp-28188
                          + -0.18f);                              // gp-28184
    }
}

void collisionsounds_update_sample(Collision *c)
{
    CollisionSample *s = c->Scrape;
    float vol;
    uint16_t az;

    if (s == NULL)
        return;
    vol = sound3d_compute_volume(&c->CurrentContactPoint, 200.0f);
    vol = vol * collisionsounds_calc_collision_scrape_volume(c);
    vol = vol * 1.9f;                           // gp-28180
    az = sound3d_compute_azimuth(&c->CurrentContactPoint);
    bsample_set_volume(&s->Sample, vol);
    bsample_set_azimuth(&s->Sample, az);
}

// The table once the regions are in; the free list's samples that have
// stopped, or are down to 0.05, deleted; and each collision's scrape kept
// up, and a sample asked for where it has none.
void collisionsounds_update(void)
{
    bNode *n;
    Collision *c;

    if (pCurrentWorld == NULL)
        return;
    if (!CollisionSoundRegionsLoaded
        && sound_is_region_loading_complete(sound_get())) {
        CollisionSoundRegionsLoaded = 1;
        collisionsounds_load_sample_table();
    }
    n = CollisionFreeSampleList.next;
    while (n != &CollisionFreeSampleList) {
        CollisionSample *s = NODE_SAMPLE(n);
        bNode *next = n->next;

        if (!bsample_is_playing(&s->Sample)
            || bsample_get_volume(&s->Sample) <= 0.05f) {  // gp-28176
            unlink_node(n);
            delete_sample(s);
        }
        n = next;
    }
    for (c = (Collision *)pCurrentWorld->CollisionList.next;
         c != (Collision *)&pCurrentWorld->CollisionList;
         c = c->Link.next) {
        if (c->Scrape != NULL)
            collisionsounds_update_sample(c);
        if (c->Sample == NULL)
            c->Sample = collision_sound_create_sample(c);
    }
}

// The scrapes, every collision's samples, the free list's, and the wood
// and foliage crashes that are playing; not the metal ones. Retail reads
// pCurrentWorld without a test.
void collisionsounds_mute(int32_t on)
{
    bNode *n;
    int32_t i;

    bsample_pause(CollisionMetalScraping, on != 0);
    bsample_pause(CollisionWoodScraping, on != 0);
    if (pCurrentWorld != NULL) {
        Collision *c;

        for (c = (Collision *)pCurrentWorld->CollisionList.next;
             c != (Collision *)&pCurrentWorld->CollisionList;
             c = c->Link.next) {
            if (c->Sample != NULL)
                bsample_pause(&c->Sample->Sample, on != 0);
            if (c->Scrape != NULL)
                bsample_pause(&c->Scrape->Sample, on != 0);
        }
    }
    for (n = CollisionFreeSampleList.next; n != &CollisionFreeSampleList;
         n = n->next)
        bsample_pause(&NODE_SAMPLE(n)->Sample, on != 0);
    for (i = 0; i < 3; i++) {
        BSample *s = CollisionWoodSamples.Samples[i];

        if (s != NULL && bsample_is_playing(s))
            bsample_pause(s, on != 0);
    }
    for (i = 0; i < 3; i++) {
        BSample *s = CollisionFoilageSamples.Samples[i];

        if (s != NULL && bsample_is_playing(s))
            bsample_pause(s, on != 0);
    }
}

// ------------------------------------------------------- collision_sound

void collision_sound_register(void)
{
    collisionsounds_register();
}

void collision_sound_unregister(void)
{
    collisionsounds_unregister();
}

void collision_sound_update(void)
{
    collisionsounds_update();
}

void collision_sound_mute(int32_t on)
{
    collisionsounds_mute(on);
}

void collision_sound_reset(void)
{
    delete_free_samples();
}

// A crash for a collision a tenth of a second old, louder than 0.2, at a
// random pitch; NULL otherwise. With sound off it is made and not played.
CollisionSample *collision_sound_create_sample(Collision *c)
{
    const BSample *src;
    CollisionSample *s;
    float vol;

    if (collision_age(c) < 0.1f)                // gp-28168
        return NULL;
    src = collisionsounds_get_collision_sound_type(c);
    if (src == NULL)
        return NULL;
    vol = collisionsounds_calc_collision_volume(c);
    if (!(0.2f < vol))                          // gp-28164
        return NULL;
    s = new_sample(src);
    if (SoundEnabled) {
        float pitch = sound_random_float(sound_get(), 0.6f)  // gp-28160
                      + 0.5f;

        bsample_play(&s->Sample, vol * 1.9f, 0.0f,   // gp-28156
                     pitch - 1.0f);
        bsample_set_azimuth(&s->Sample,
                            sound3d_compute_azimuth(&c->CurrentContactPoint));
    }
    return s;
}

// A sample still playing goes on the free list to finish, and one that
// has stopped is deleted. A scrape still playing fades out over 50 ms on
// the free list; one that has stopped is left, its slot not given back
// until UnRegister deletes the pool.
void collision_sound_release_sample(Collision *c)
{
    CollisionSample *s = c->Sample;

    if (s != NULL) {
        if (bsample_is_playing(&s->Sample))
            push_free(s);
        else
            delete_sample(s);
    }
    s = c->Scrape;
    if (s != NULL && bsample_is_playing(&s->Sample)) {
        bsample_fade(&s->Sample, 0.0f, 50);
        push_free(s);
    }
}

void collision_sound_play_foilage(const bVector3 *pos)
{
    BSample *s;

    if (!SoundEnabled)
        return;
    s = library_next(&CollisionFoilageSamples);
    sound3d_oneshot_play(s, pos, 1.9f,                          // gp-28148
                         sound_random_float(sound_get(), 0.6f)  // gp-28152
                         + 0.5f);
}

void collision_sound_play_generic_smokable(const bVector3 *pos)
{
    BSample *s;

    if (!SoundEnabled)
        return;
    s = library_next(&CollisionWoodSamples);
    sound3d_oneshot_play(s, pos, 2.5f,
                         sound_random_float(sound_get(), 0.6f)  // gp-28144
                         + 0.5f);
}

// A plant's foliage or the generic crash; then for either pump the
// explosion and "PreviewZone".
void collision_sound_play_smokeable(const bVector3 *pos, SmokeableInfo *info)
{
    if (!SoundEnabled)
        return;
    if (info != NULL && info->TheTerrainType == TERRAIN_TYPE_PLANT)
        collision_sound_play_foilage(pos);
    else
        collision_sound_play_generic_smokable(pos);
    if (info == NULL)
        return;
    if (info->NameHash == CollisionPetrolPumpNameHash
        || info->NameHash == CollisionGasPumpNameHash) {
        collision_sound_play_explosion(pos);
        sound3d_oneshot_play_named(sound_get(), "PreviewZone", pos,
                                   1.9f, 1.0f);             // gp-28140
    }
}

void collision_sound_play_glass(const bVector3 *pos)
{
    if (!SoundEnabled)
        return;
    sound3d_oneshot_play(CollisionGlassBreaking, pos, 1.9f,   // gp-28136
                         1.0f);
}

// "FinishLine" at half pitch, in no category. Retail asks for category 0's
// volume first and drops it.
void collision_sound_play_bust_road_block(const bVector3 *pos)
{
    Sound3dSample *s;

    bsound_get_category_volume(bsound_get(), 0);
    s = sound3d_oneshot_play_named(sound_get(), "FinishLine", pos, 1.0f,
                                   0.5f);
    if (s != NULL)
        bsample_set_category(&s->Sample, 0xffffffffu);
}

// "Bomb" twice, each heard out to 300 at up to 6. Retail does not test
// Play's answer before writing the envelope.
void collision_sound_play_explosion(const bVector3 *pos)
{
    Sound3dSample *s;

    if (!SoundEnabled)
        return;
    s = sound3d_oneshot_play_named(sound_get(), "Bomb", pos, 1.0f,
                                   sound_random_float(sound_get(), 0.6f)
                                   + 0.5f);                 // gp-28132
    s->Envelope.MaxVolAtSource = 6.0f;
    s->Envelope.Coeff = 1.0f / 300.0f;                      // gp-28128
    s->Envelope.CutOffDistance = 300.0f;
    s = sound3d_oneshot_play_named(sound_get(), "Bomb", pos, 1.0f,
                                   sound_random_float(sound_get(), 0.6f)
                                   + 0.5f);                 // gp-28124
    s->Envelope.MaxVolAtSource = 6.0f;
    s->Envelope.Coeff = 1.0f / 300.0f;
    s->Envelope.CutOffDistance = 300.0f;
}

void collision_sound_play_scrape(Collision *c)
{
    if (SoundEnabled && c->Scrape == NULL)
        collisionsounds_start_scraping(c);
}

// ------------------------------------------------------------- the table

static const VtEntry collisionsample_vt[COLLISIONSAMPLE_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)collisionsample_destroy },    //  8  0x001e5db0
};

void collisionsound_install_vtables(void)
{
    vt_install(COLLISIONSAMPLE_VTABLE, collisionsample_vt,
               COLLISIONSAMPLE_VT_ENTRIES);
}
