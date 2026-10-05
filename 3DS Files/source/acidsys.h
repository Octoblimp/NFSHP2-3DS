// acidsys -- the effect system of AcidFXE.obj (retail 0x00126d70 ..
// 0x001276fc and 0x0012a1e0 .. 0x0012a5e8; the demo's 0x001258d0 ..
// 0x00126258), its data half: the three slot pools, the emitter datas and
// emitters a file brings, slot 6 of the LoaderTable, the lookups, the
// copies the cars and the munitions take, and an AcidEffectSystem's
// auto emitters and active groups.
//
// An emitter data (AcidEmitterData, 544 bytes) is what an effect looks
// like: its texture, its cycle, how many particles and how they move. An
// emitter (AcidEmitter, 192 bytes) is one place that emits, with a data
// and a cycle state. Both come in chunks, 0x35021 and 0x35020, which the
// loader leaves where they are: every data goes on EmitterDataList, and
// every emitter on WorldEffects' auto emitters. GLOBALB has 111 datas and
// 112 emitters, every one LIBRARY, a template that afxGetEmitters copies
// for a car, a smoke bomb or the car select's nebula; each track has 10 to
// 40 emitters, every one ON.
//
// TriggerEmitter (0x00127700), DoTimeStep (0x00128718) and
// UpdateInterestPoints (0x001286a0) make the particles and move them: an
// emitter near one of the three interest points emits into an active
// group, one group per emitter and car, and each step ages, slows and
// moves every particle and frees the dead ones. RenderEffects, which draws
// them, comes next (SC-3c).
//
// FrameEffects (retail 0x002ef5e0) is the frontend's system, which the car
// select's nebula goes on; WorldEffects (0x002ef640) is the race's.
//
// Not ported: the system's destructor (0x0012a398) and the object's
// static destructor (0x0012a1e0), which run only at exit. They would hand
// the chunks' emitters to the emitter pool and the chunks' datas to bFree.
//
// Cross-check: tools/afx_check.py. Write-up: docs/formats/acidfx.md.

#ifndef ACIDSYS_H
#define ACIDSYS_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bmatrix.h"
#include "bslotpool.h"
#include "bvector.h"

// AcidCycleStateNames (the demo's 0x002e7710): "OFF", "ON", "DISABLED",
// "LIBRARY".
enum {
    ACID_OFF      = 0,
    ACID_ON       = 1,
    ACID_DISABLED = 2,
    ACID_LIBRARY  = 3
};

// The chunks: two containers the loader takes and passes over, the
// emitters (AcidEmitterPackHeader, version 5) and the datas
// (AcidEmitterDataPackHeader, version 4). No file on the disc has the
// containers; every one has the two packs at the top level.
#define ACID_CHUNK_A          0x80035000u
#define ACID_CHUNK_B          0x80035010u
#define ACID_CHUNK_EMITTERS   0x00035020u
#define ACID_CHUNK_DATAS      0x00035021u
#define ACID_EMITTERS_VERSION 5
#define ACID_DATAS_VERSION    4

// AcidEmitterData, 544 bytes (type#1490).
typedef struct AcidEmitterData {
    bNode     Node;                         //   0
    uint32_t  NameHash;                     //   8
    uint32_t  TextureNameHash;              //  12
    uint32_t  GroupNameHash;                //  16
    void     *Texture;                      //  20  TextureInfo *
    uint8_t   SpreadAsDisc;                 //  24
    uint8_t   ContactSheetW;                //  25
    uint8_t   ContactSheetH;                //  26
    uint8_t   AnimFPS;                      //  27
    uint8_t   RandomStartFrame;             //  28
    uint8_t   RandomRotationDirection;      //  29
    uint8_t   MotionLive;                   //  30
    uint8_t   pad1;                         //  31
    float     OnCycle;                      //  32
    float     OnCycleVariance;              //  36
    float     OffCycle;                     //  40
    float     OffCycleVariance;             //  44
    float     NumParticles;                 //  48
    float     NumParticlesVariance;         //  52
    float     Life;                         //  56
    float     LifeVariance;                 //  60
    float     Speed;                        //  64
    float     SpeedVariance;                //  68
    float     InitialAngleRange;            //  72
    float     SpreadAngle;                  //  76
    float     MotionInherit;                //  80
    float     MotionInheritVariance;        //  84
    int32_t   CarPosition;                  //  88  CarEffectPosition
    int32_t   pad2;                         //  92
    bVector4  VolumeCenter;                 //  96
    bVector4  VolumeExtent;                 // 112
    float     FarClip;                      // 128
    float     Gravity;                      // 132
    float     Drag;                         // 136
    float     MaxPixelSize;                 // 140
    bVector4  KeyPositions;                 // 144
    bMatrix4  ColourMatrix;                 // 160
    bVector4  Size;                         // 224
    bVector4  RelativeAngle;                // 240
    bMatrix4  ColourBasis;                  // 256
    bMatrix4  ExtraBasis;                   // 320
    char      Name[64];                     // 384
    char      TextureName[48];              // 448
    char      GroupName[48];                // 496
} AcidEmitterData;                          // 544

struct AcidActiveGroup;

// AcidEmitter, 192 bytes (type#1514).
typedef struct AcidEmitter {
    bNode     Node;                         //   0
    uint32_t  NameHash;                     //   8
    uint32_t  EmitterDataNameHash;          //  12
    int32_t   State;                        //  16  ACID_*
    float     RemainingCycleTime;           //  20
    float     EmissionCountdown;            //  24
    AcidEmitterData *EmitterData;           //  28
    struct AcidActiveGroup *LastActiveGroup; // 32
    uint32_t  RandomSeed;                   //  36
    uint32_t  DontEmit;                     //  40
    uint32_t  pad2;                         //  44
    bMatrix4  LocalWorld;                   //  48
    bVector4  InheritVelocity;              // 112
    char      Name[64];                     // 128
} AcidEmitter;                              // 192

// AcidParticle, 32 bytes (type#2708). Life is seconds times 1024, which
// DoTimeStep reads signed (lh): a life past 32 s, 60 s at most, is
// negative there and the particle dies on its first step. Speed is
// world units a second times 128, read unsigned (lhu); the .mdebug has it
// signed. VX, VY and VZ are the direction times 127, Inherit the share of
// the car's motion times 255, and Frame the contact sheet's cell.
typedef struct AcidParticle {
    bNode     Node;                         //   0
    uint16_t  Life;                         //   8
    int16_t   Angle;                        //  10
    uint16_t  Speed;                        //  12
    uint8_t   Inherit;                      //  14
    uint8_t   Pad;                          //  15
    float     X;                            //  16
    float     Y;                            //  20
    float     Z;                            //  24
    int8_t    VX;                           //  28
    int8_t    VY;                           //  29
    int8_t    VZ;                           //  30
    uint8_t   Frame;                        //  31
} AcidParticle;                             //  32

// AcidActiveGroup, 28 bytes (type#2179): one emission's particles.
typedef struct AcidActiveGroup {
    bNode     Node;                         //   0
    AcidEmitterData *EmitterData;           //   8
    AcidEmitter *Emitter;                   //  12
    void     *pCar;                         //  16  Car *
    bNode     ParticleList;                 //  20  bTList<AcidParticle>
} AcidActiveGroup;                          //  28

// AcidEffectSystem, 96 bytes (type#1570).
typedef struct AcidEffectSystem {
    bNode     ActiveGroupList;              //   0  bTList<AcidActiveGroup>
    bNode     AutoEmitterList;              //   8  bTList<AcidEmitter>
    bVector4  InterestPoints[3];            //  16
    AcidEmitter *CurrentEmitter;            //  64
    int32_t   SelectEmitterIndex;           //  68
    uint8_t   DebugStats;                   //  72
    uint8_t   CreateEmitterMaxScript;       //  73
    uint8_t   pad;                          //  74
    uint8_t   PrintEmitterList;             //  75
    uint8_t   PrintNearbyEmitters;          //  76
    uint8_t   OnlyShowCurrentEmitter;       //  77
    uint8_t   pad78[2];                     //  78
    int32_t   NumAutoEmitters;              //  80
    int32_t   NumVisibleParticles;          //  84
    float     RenderTime;                   //  88
    float     UpdateTime;                   //  92
} AcidEffectSystem;                         //  96

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char acid_data_size_check[sizeof(AcidEmitterData) == 544 ? 1 : -1];
typedef char acid_data_name_check[
    offsetof(AcidEmitterData, Name) == 384 ? 1 : -1];
typedef char acid_emitter_size_check[sizeof(AcidEmitter) == 192 ? 1 : -1];
typedef char acid_emitter_world_check[
    offsetof(AcidEmitter, LocalWorld) == 48 ? 1 : -1];
typedef char acid_particle_size_check[sizeof(AcidParticle) == 32 ? 1 : -1];
typedef char acid_group_size_check[sizeof(AcidActiveGroup) == 28 ? 1 : -1];
typedef char acid_system_size_check[sizeof(AcidEffectSystem) == 96 ? 1 : -1];
typedef char acid_system_count_check[
    offsetof(AcidEffectSystem, NumAutoEmitters) == 80 ? 1 : -1];
#endif

// ------------------------------------------------------------ the globals

extern BSlotPool *AcidParticleSlotPool;     // gp-23528
extern BSlotPool *AcidActiveGroupSlotPool;  // gp-23524
extern BSlotPool *AcidEmitterSlotPool;      // gp-23520
// The emitters made from the pool and not yet deleted. The copies count,
// and so do the deletes of an emitter that was never counted.
extern int32_t    NumAcidEmitters;          // gp-23516
extern bNode      EmitterDataList;          // gp-23512, bTList
// The auto emitters' first seeds come from here: 0x23985727 at boot.
extern uint32_t   AcidRandomSeed;           // gp-23504
extern AcidEffectSystem FrameEffects;       // 0x002ef5e0
extern AcidEffectSystem WorldEffects;       // 0x002ef640

// ------------------------------------------------------------ the object

// _GLOBAL_$I$AcidCycleStateNames (0x0012a220; the demo's, entry 9 of its
// __CTOR_LIST__, is at 0x00128cd0): EmitterDataList empty, then
// FrameEffects and WorldEffects constructed. Once, at boot, from
// sinit_run.
void acid_static_init(void);

// afxInit (0x00126d70), from InitializeEverything after
// InitDisplaySystem: 1000 particles of 32 bytes, 400 groups of 28 and 600
// emitters of 192, all with memory pool 16. The particles' and the groups'
// pools lose OVERFLOW_IF_FULL and ZERO_ALLOCATED_MEMORY; the emitters'
// keep all four flags.
void afx_init(void);

// afxClose (0x00126e08): every active group of FrameEffects and then of
// WorldEffects freed, and the particles' and the groups' pools deleted.
// The emitters' pool is left. Nothing in the image calls it.
void afx_close(void);

// LoaderAcidFX (0x00126e50) and UnloaderAcidFX (0x00126f60), slot 6.
// Both take the two containers and do nothing with them. A pack of the
// wrong version is taken and left alone. The loader puts each data on
// EmitterDataList's tail and gives each emitter the data its
// EmitterDataNameHash names, then makes it one of WorldEffects' auto
// emitters; the unloader takes each data off the list, and each emitter
// off WorldEffects, in the pack's order.
int loader_acid_fx(uint8_t *chunk);
int unloader_acid_fx(uint8_t *chunk);

// afxTrackLoader (0x00127068) and afxTrackUnloader (0x00127070). Empty.
void afx_track_loader(void);
void afx_track_unloader(void);

// afxUpdateTextures (0x00127078), from PostLoadFixup: each data whose
// Texture is NULL, or a texture of another name, looks its texture up
// again, GetTextureInfo(TextureNameHash, 0, 0), which may be NULL.
void afx_update_textures(void);

// afxAddEmitterData (0x001270e8): onto EmitterDataList's tail.
// afxRemoveEmitterData (0x00127108): off it. Its own links are left.
void afx_add_emitter_data(AcidEmitterData *d);
void afx_remove_emitter_data(AcidEmitterData *d);

// afxGetEmitterData (0x00127120): the first data after `after` (NULL, the
// list's head) with that name and that group, either of which 0 leaves
// out. Both 0 is NULL.
AcidEmitterData *afx_get_emitter_data(uint32_t name_hash, uint32_t group_hash,
                                      AcidEmitterData *after);

// afxGetEmitter (0x00127198): the same over WorldEffects' auto emitters,
// the name being the emitter's and the group its data's. With a name
// and no group, the listing compares the name with its data's NameHash
// instead, and reads an emitter with no data at address 8: the port
// passes over that emitter.
AcidEmitter *afx_get_emitter(uint32_t name_hash, uint32_t group_hash,
                             AcidEmitter *after);

// afxCopyEmitter (0x00127228): a new emitter from the pool, zero from its
// eighth byte, counted, with the original's name (and its hash), its data
// and its LocalWorld. NULL when the pool gives none, still counted; the
// listing clears 184 bytes at address 8 then, which the port does not.
AcidEmitter *afx_copy_emitter(const AcidEmitter *src);

// afxGetEmitters (0x001272e0): a copy of each of WorldEffects' auto
// emitters whose data is of that group, onto the list's tail in turn. A
// copy the pool cannot give is left out.
void afx_get_emitters(bNode *list, uint32_t group_hash);

// afxDeleteEmitters (0x00127368): each emitter off the list from its head
// and deleted.
void afx_delete_emitters(bNode *list);

// AcidEmitter::SetEmitterData(AcidEmitterData *) (0x001273c0): set and 1,
// or for NULL, left and 0. SetEmitterData(unsigned int) (0x001273d8): the
// data of that name, afxGetEmitterData(hash, 0, NULL), the same way.
int32_t acid_emitter_set_emitter_data(AcidEmitter *e, AcidEmitterData *d);
int32_t acid_emitter_set_emitter_data_hash(AcidEmitter *e, uint32_t hash);

// AcidEmitter's deleting destructor (0x00124e20, and its twin 0x0012a3f8):
// uncounted, then with bit 0 of `flags` the slot back to the pool.
void acid_emitter_delete(AcidEmitter *e, int32_t flags);

// AcidActiveGroup's deleting destructor (0x0012a258): Emitter and
// EmitterData NULL, every particle off its list from the head and back to
// the particles' pool, then with bit 0 of `flags` the group to its own.
void acid_active_group_delete(AcidActiveGroup *g, int32_t flags);

// AcidEffectSystem::AcidEffectSystem (0x00127418): both lists empty, and
// zero from CurrentEmitter on. The interest points are left.
void acid_system_construct(AcidEffectSystem *s);

// AcidEffectSystem::TweakerCheck (0x00127490) and RenderDebug
// (0x00127498). Empty.
void acid_system_tweaker_check(AcidEffectSystem *s);

// AcidEffectSystem::AddAutoEmitter (0x001274a0). An emitter with no seed
// takes the next of AcidRandomSeed's. One with no data, or DISABLED,
// becomes DISABLED and goes on the list's tail; LIBRARY goes on the tail;
// OFF and ON go on the head, with the cycle their state names drawn from
// its variance on the emitter's own seed, and nothing left to emit; any
// other state becomes DISABLED on the tail. The count goes up each time.
void acid_system_add_auto_emitter(AcidEffectSystem *s, AcidEmitter *e);

// RemoveAutoEmitter (0x00127688): off the list and uncounted. Its links
// are left.
void acid_system_remove_auto_emitter(AcidEffectSystem *s, AcidEmitter *e);

// KillAllActiveEffects (0x001276a8): each active group off the list from
// its head and deleted.
void acid_system_kill_all_active_effects(AcidEffectSystem *s);

// UpdateInterestPoints (0x001286a0): the eyes of views 1, 2 and 0, into
// InterestPoints[0], [1] and [2], each only while its view has a camera.
void acid_system_update_interest_points(AcidEffectSystem *s);

// TriggerEmitter (0x00127700): time_step's particles from one emitter.
//
// Nothing happens unless the emitter's position is within its data's
// FarClip of an interest point. An emitter with no seed takes one first,
// as AddAutoEmitter gives it. It emits while ON, or always for a negative
// time_step, a burst of -time_step seconds; a positive step stops at the
// end of the emitter's cycle.
//
// The particles go into the emitter's last group if that group is still
// the emitter's and the car's, or else a new one on the system's tail. A
// full group pool keeps the last group, whatever it is, and none emits
// nothing. A particle is drawn from the emitter's seed: its direction
// across the spread (a disc about the emitter's y, or angles about x, y
// and z), its place in the volume, its first frame, its life, angle and
// speed, and its share of the emitter's InheritVelocity, which a data with
// MotionLive leaves to DoTimeStep. DontEmit, or a full particle pool,
// draws one and keeps none. A group left with no particles is freed, and
// LastActiveGroup still names it.
void acid_system_trigger_emitter(AcidEffectSystem *s, AcidEmitter *e,
                                 float time_step, void *car);

// DoTimeStep (0x00128718), from World's step for WorldEffects
// (0x0014e110, after TweakerCheck), the frontend's frame for FrameEffects
// (0x00113fd0), and 0x0012a0f4 for a system of its own.
//
// Each auto emitter from the head, up to and including the first that is
// neither ON nor OFF: an ON one emits, and an ON or OFF one's cycle runs
// down and flips, the next cycle drawn from its variance and less the
// overrun. In the frontend (CurrentGameFlowState 3) each data's ColourBasis
// and ExtraBasis are made again from its keys. Then every particle of
// every group ages; one whose life is gone is freed, and the rest turn
// their frames, slow by their data's drag, fall by its gravity and move,
// with their share of the car's own motion when the data has MotionLive.
// A group left with no particles is freed. UpdateTime is the step's
// milliseconds.
void acid_system_do_time_step(AcidEffectSystem *s, float dt);

// CurrentGameFlowState (gp-21420), which DoTimeStep reads for the
// frontend's 3. NULL reads 0.
extern int32_t (*gAcidGameFlowStateFn)(void);

#endif
