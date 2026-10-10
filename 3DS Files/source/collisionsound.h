// collisionsound -- CollisionSounds.obj: CollisionSounds, collision_sound
// and CollisionSample (retail 0x001e4658 .. 0x001e5e58).
//
// The crashes and scrapes. A Collision near a player asks for a sample when
// it begins (CreateSample): a crash from one of five libraries of three --
// metal small, medium and hard by how hard the knock was, wood on a wood or
// cactus wall -- played once at a random pitch. Each scrape a collision
// reports (PlayScrape) starts a looping scrape on a wood, cactus or solid
// wall, which Update keeps at the contact's volume and azimuth. When the
// collision ends (ReleaseSample) a sample still playing goes on the free
// list to finish, the scrape faded out over 50 ms; Update deletes each
// once it stops or is almost silent. The one-shots -- a smokeable knocked
// over, a car's glass, a busted roadblock, an explosion -- go through
// sound3d_oneshot.
//
// CollisionSample is a bSample from a pool of 40, with a table whose one
// slot is the destructor; every delete is through it. The samples come from
// the "InGame" region, loaded once Update finds the regions in.
//
// docs/formats/collisionsound.md has the rest; tools/collisionsound_check.py
// runs retail's code against this.

#ifndef COLLISIONSOUND_H
#define COLLISIONSOUND_H

#include <stdint.h>

#include "blist.h"
#include "bslotpool.h"
#include "bsound.h"
#include "bvector.h"

struct Collision;
struct SmokeableInfo;

// ------------------------------------------------------------ the records

// 196 bytes in retail: the bSample (188, its vptr slot at 184 holding this
// class's table), then FreeSampleList's node. The port's bSample is 184
// bytes with no vptr, so the table's word lands at 184 on the 3DS as well.
typedef struct CollisionSample {
    BSample  Sample;                    //   0
    uint32_t _vtable;                   // 184
    bNode    Node;                      // 188  FreeSampleList's
} CollisionSample;                      // 196

// SampleLibrary<3>, 16 bytes: three samples, played in turn.
typedef struct SampleLibrary {
    BSample *Samples[3];                //  0
    int32_t  CurrSampleIndex;           // 12
} SampleLibrary;

// _vt$15CollisionSample: two entries, the destructor at 8.
#define COLLISIONSAMPLE_VTABLE     0x002b9410u
#define COLLISIONSAMPLE_VT_DESTROY 8    // (this, flags): flags & 1 deletes
#define COLLISIONSAMPLE_VT_ENTRIES 2

// Registers the table. Once at boot.
void collisionsound_install_vtables(void);

// ------------------------------------------------------------ the globals

// The libraries, in the bss: foliage 0x0031a778, wood 0x0031a788, metal
// small, medium and hard 0x0031a798 on.
extern SampleLibrary CollisionFoilageSamples;
extern SampleLibrary CollisionWoodSamples;
extern SampleLibrary CollisionMetalSamples[3];

extern BSample   *CollisionMetalScraping;       // gp-17240
extern BSample   *CollisionWoodScraping;        // gp-17244
extern BSample   *CollisionGlassBreaking;       // gp-17248
extern int32_t    CollisionSoundRegionsLoaded;  // gp-17236
// gp-17264, 1 in the image: LoadSampleTable sets it, and nothing reads it.
extern int32_t    CollisionSampleTableLoaded;
extern uint32_t   CollisionPetrolPumpNameHash;  // gp-17272
extern uint32_t   CollisionGasPumpNameHash;     // gp-17268
extern bNode      CollisionFreeSampleList;      // gp-17280
// "CollisionSampleSounds", gp-17288: 40 slots.
extern BSlotPool *CollisionSamplePool;

// ------------------------------------------------------- CollisionSounds

// 0x001e4658. Wood (terrain 15 or 16) or the metal library by the impulse,
// and its next sample; NULL when that is missing.
BSample *collisionsounds_get_collision_sound_type(struct Collision *c);

void collisionsounds_register(void);            // 0x001e4740
void collisionsounds_load_sample_table(void);   // 0x001e47a8
void collisionsounds_unregister(void);          // 0x001e4a78

// 0x001e4b58. The distance to view 1's camera, or the nearer of the two
// players' with two.
float collisionsounds_get_distance_to_camera(const bVector3 *pos);
float collisionsounds_calc_collision_volume(struct Collision *c);
float collisionsounds_calc_collision_scrape_volume(struct Collision *c);
int32_t collisionsounds_calc_collision_azimuth(struct Collision *c);

void collisionsounds_start_scraping(struct Collision *c);   // 0x001e4cc8
void collisionsounds_update_sample(struct Collision *c);    // 0x001e4e00
void collisionsounds_update(void);                          // 0x001e4ea8
void collisionsounds_mute(int32_t on);                      // 0x001e5018

// ------------------------------------------------------- collision_sound

// 0x001e51a8 .. 0x001e51c0 jump to the four above.
void collision_sound_register(void);
void collision_sound_unregister(void);
void collision_sound_update(void);
void collision_sound_mute(int32_t on);

// 0x001e51c8. Every sample on the free list deleted. racecoord.c's
// gCollisionSoundResetFn.
void collision_sound_reset(void);

// 0x001e5278 and 0x001e53b0, collision.h's seams.
CollisionSample *collision_sound_create_sample(struct Collision *c);
void collision_sound_release_sample(struct Collision *c);

// 0x001e5470 and 0x001e5508, the smokeables' two.
void collision_sound_play_foilage(const bVector3 *pos);
void collision_sound_play_generic_smokable(const bVector3 *pos);

// 0x001e55a8. Smokeable::ConsiderImpulse and SmokeBomb::Move's: a plant's
// foliage or the generic crash, and for a pump the explosion and more.
void collision_sound_play_smokeable(const bVector3 *pos,
                                    struct SmokeableInfo *info);
void collision_sound_play_glass(const bVector3 *pos);           // 0x001e5660
// 0x001e5688, pursuit.c's and playernis.c's seam.
void collision_sound_play_bust_road_block(const bVector3 *pos);
void collision_sound_play_explosion(const bVector3 *pos);       // 0x001e56f0
// 0x001e57d0, collision.h's seam.
void collision_sound_play_scrape(struct Collision *c);

// ------------------------------------------------------- CollisionSample

void collisionsample_initialize(CollisionSample *s, const BSample *src);
void collisionsample_destroy(CollisionSample *s, int32_t flags);

#endif
