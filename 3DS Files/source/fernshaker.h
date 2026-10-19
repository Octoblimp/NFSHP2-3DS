// fernshaker -- the FernShaker half of FernShaker.obj, retail 0x001d9b58 ..
// 0x001da5d8: the bushes a car drives through.
//
// A track's fern triggers (eventmgr.h, TRIGGER_EVENT_CAR_ON_FERN) name a
// scenery instance by its section and number. When a car is inside one,
// Car::TriggerEvents calls FlattenFern, which is empty in retail, and
// ShakeFern with the car's velocity. ShakeFern finds the bush's shaker or
// makes one: the instance is hidden (ExcludeFlags bit 0x10, as Smokeable
// hides its virgins) and drawn instead as a WorldObject of the same model,
// whose rigid animation the shake starts; the leaves are the emitters of
// the animation's FernShakerInfo, BUSHSHAKE_A or BUSHSHAKE_B. A shaker
// lasts 240 frames from its last start (4 s) and goes at the next
// ShakeFern after that, the instance shown again.
//
// The port draws a WorldObject without its rigid animation, so a shaken
// bush stands still in its place; the leaves fly. InitFernFlatteners,
// ServiceFernFlatteners and FlattenFern are empty in retail and are not
// ported.
//
// Prototypes and globals here; the write-up is docs/formats/event-manager.md.
// Cross-check: tools/eventmgr_check.py.

#ifndef FERNSHAKER_H
#define FERNSHAKER_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bslotpool.h"
#include "bvector.h"
#include "scenery.h"
#include "worldobject.h"

// FernShakerInfo, 16 bytes (type#941): which emitters a rigid animation's
// shake fires.
typedef struct FernShakerInfo {
    uint32_t RigidAnimationNameHash;    //  0
    uint32_t EmitterGroupNameHash;      //  4
    bNode    EmitterList;               //  8  bTList<AcidEmitter>
} FernShakerInfo;

// FernShaker, 28 bytes (type#958). SceneryCode is the trigger's
// parameter: the section in the high half, the instance in the low.
// StartTime is a WorldTimeFrames.
typedef struct FernShaker {
    bNode            Node;              //  0  bTNode<FernShaker>
    uint32_t         SceneryCode;       //  8
    int32_t          StartTime;         // 12
    SceneryInstance *pSceneryInstance;  // 16
    WorldObject     *pWorldObject;      // 20
    FernShakerInfo  *pFernShakerInfo;   // 24
} FernShaker;

#if UINTPTR_MAX == 0xffffffffu
typedef char fernshaker_layout_check[
    (sizeof(FernShakerInfo) == 16 && sizeof(FernShaker) == 28
     && offsetof(FernShaker, pFernShakerInfo) == 24) ? 1 : -1];
#endif

// How long a shaker lives, in frames: ShakeFern drops one whose age is
// not under this.
#define FERN_SHAKER_LIFETIME 241

// The image's globals, gp-17664 .. gp-17644. The table is a new[] of
// NumFernShakerInfos: bMalloc's block holds the count at its start and the
// table 16 bytes on. The list starts empty.
extern FernShakerInfo *pFernShakerInfoTable;
extern int32_t         NumFernShakerInfos;
extern BSlotPool      *FernShakerSlotPool;     // 32 of 28 bytes
extern bNode           FernShakerList;

// InitFernShakers, 0x001da0f8: the pool, in pool 16, and two infos, each
// Init with BUSHSHAKE_A and BUSHSHAKE_B for both its animation and its
// emitter group. The World's constructor calls it (worldinit.c).
void init_fern_shakers(void);

// FlushFernShakers, 0x001da1b0: every shaker off the list from its head
// and deleted. World::DoSnapshot calls it on a restore (worldsnap.c).
void flush_fern_shakers(void);

// CloseFernShakers, 0x001da200: the infos destroyed, the last first, the
// table freed (with no test of the block), the table and the count
// cleared, the shakers flushed and the pool deleted and cleared.
void close_fern_shakers(void);

// FernShakerInfo::Init(const char *, const char *), 0x001da538: the two
// names' hashes, then afxGetEmitters onto its list for the group's.
void fern_shaker_info_init(FernShakerInfo *info, const char *animation,
                           const char *group);

// _$_14FernShakerInfo, 0x001da588: its list's emitters off from the head
// and deleted with 3, and with bit 0 of `flags` the info freed.
void fern_shaker_info_destroy(FernShakerInfo *info, int32_t flags);

// FernShaker::FernShaker(unsigned int), 0x001d9b68. The code and
// WorldTimeFrames as the start, the rest NULL. Then, for a section that is
// loaded and whose instance's info has an LOD 0 model with a rigid
// animation: the instance, a WorldObject of that model's name at the
// instance's place (from WorldObjectSlotPool, without lighting), the
// instance hidden, and the first info whose animation is the model's.
// The image reads ScenerySectionHeaderTable unbounded, and an instance of
// a NULL instance table unless it is the first; the port takes a section
// past the table, or a NULL table, as no section.
FernShaker *fern_shaker_construct(FernShaker *s, uint32_t code);

// _$_10FernShaker, 0x001d9d90. With an instance: shown again, and its
// WorldObject, if any, deleted with 3. With bit 0 of `flags` the shaker
// back to its pool.
void fern_shaker_destroy(FernShaker *s, int32_t flags);

// FernShaker::Shake(const bVector3 *), 0x001d9e08. Nothing without an
// instance, or when the object's model has no rigid animation. The speed
// is |vel| * 2.23 (mph): nothing at 5 or under. An animation not playing
// (GetRigidAnimationTime below 0) starts again now, from its middle frame
// over 30 mph and from frame 0 else, and the shaker's start with it.
// Then (speed - 5) * 0.04, held to 0..1, is the shake: over 0, each of
// the info's emitters is put at the instance with the velocity (w 0) and
// fired on WorldEffects with minus the shake and no car.
void fern_shaker_shake(FernShaker *s, const bVector3 *vel);

// ShakeFern(unsigned int, const bVector3 *), 0x001da270. Every shaker
// FERN_SHAKER_LIFETIME frames old or more goes. Then the code's shaker
// shakes; with none, a new one goes on the list's tail first, unless the
// pool is full, which shakes nothing.
void shake_fern(uint32_t code, const bVector3 *vel);

// FlattenFern(unsigned int), 0x001d9b58: empty.
void flatten_fern(uint32_t code);

#endif
