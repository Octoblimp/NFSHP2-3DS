// smokesnap -- the smokeables' part of a replay snapshot (TASKS 72d-2):
// VirginSmokeable::DoSnapshot (retail's 0x00220128) and Smokeable's
// (0x002208a0), slot 16 of their tables, and SnapshotAllSmokeables
// (0x0021fb30), which World's calls.
//
// A file of its own, as carsnap.c is the car's: the snapshots reach the
// pools, the constructors and the bodies' own snapshots, which a checker
// records rather than runs. A restore throws every smokeable away and makes
// each again from what was taken: the virgins from their spawners' indices,
// the others from their ID, their info's and their model's name hashes and
// their type; each new body's own snapshot then restores the rest.
//
// Prototypes: smokeable.h. Cross-check: tools/worldsnap_check.py.
// Write-up: docs/formats/replay.md.

#include <stdint.h>

#include "bslotpool.h"
#include "collisionbody.h"
#include "replay.h"
#include "rigidbody.h"
#include "smokeable.h"
#include "vtable.h"
#include "worldobject.h"

#define BODY_END ((CollisionBody *)(void *)&CollisionBodyList)

typedef void (*BodySnapshotFn)(void *self, ReplaySnapshot *s);
typedef int32_t (*SmokeTypeFn)(void *self);

// The body's own DoSnapshot, slot 16 of its table.
static void body_do_snapshot(CollisionBody *b, ReplaySnapshot *s)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_DO_SNAPSHOT);

    ((BodySnapshotFn)e->fn)(vt_this(b, e), s);
}

// GetSmokeType, slot 208: a munition's own, 0 for a plain smokeable.
static int32_t body_get_smoke_type(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, SMOKEABLE_VT_GET_SMOKE_TYPE);

    return ((SmokeTypeFn)e->fn)(vt_this(b, e));
}

void virginsmokeable_do_snapshot(CollisionBody *b, ReplaySnapshot *s)
{
    ReplaySnapshot_BeginNamedSection(s, "VirginSmokeable");
    staticcollisionbody_do_snapshot(b, s);
    ReplaySnapshot_EndSection(s);
}

// The spawner goes as its index, which a restore turns back into the
// spawner. Retail reads the restored index from a stack short that a
// snapshot moving nothing leaves as it was; the port's is 0.
void smokeable_do_snapshot(CollisionBody *b, ReplaySnapshot *s)
{
    Smokeable *sm = (Smokeable *)(void *)b;

    ReplaySnapshot_BeginSection(s, sm, "Smokeable");
    dynamiccollisionbody_do_snapshot(b, s);
    ReplaySnapshot_MoveChar(s, &sm->Awake, 1);                     // 1122
    ReplaySnapshot_MoveChar(s, &sm->Blinking, 1);                  // 1123
    ReplaySnapshot_VerifyUInt(s, &sm->SI->NameHash, 4);            //  272
    ReplaySnapshot_MoveFloat(s, &sm->AnchorStrength);              //  276
    ReplaySnapshot_MoveFloat(s, &sm->BreakingStrength);            //  280
    ReplaySnapshot_MoveTimer(s, (int32_t *)&sm->TimeAwoken);       //  288
    ReplaySnapshot_MoveTimer(s, (int32_t *)&sm->TimeCreated);      //  284
    ReplaySnapshot_MoveTimer(s, (int32_t *)&sm->TimeLastCarContact); // 292
    ReplaySnapshot_MoveFloat(s, &sm->GroundRaise);                 //  300
    if (s->RestoringSnapshotFlag) {
        int16_t index = 0;

        ReplaySnapshot_MoveShort(s, &index, 2);
        sm->pSmokeableSpawner = smokeable_get_spawner(index);      //  296
    } else {
        int16_t index =
            (int16_t)smokeable_get_spawner_index(sm->pSmokeableSpawner);

        ReplaySnapshot_MoveShort(s, &index, 2);
    }
    rigidbody_do_snapshot((RigidBody *)sm->Dynamic.pBody, s);      //   96
    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag)
        dynamiccollisionbody_update_position(&sm->Dynamic);
    ReplaySnapshot_VerifyVector2(s, &b->BBoxMin);                  //   20
    ReplaySnapshot_VerifyVector2(s, &b->BBoxMax);                  //   28
    ReplaySnapshot_EndSection(s);
}

// Two lists, each ended by -1: the virgins as their spawners' indices, then
// the other smokeables as ID, info hash, model name hash and a byte of the
// type, each followed by the body's own snapshot. The image moves the type
// into the low byte of a stack word whose upper three bytes it never sets,
// and creates from the whole word; the port's word starts at 0.
void snapshot_all_smokeables(ReplaySnapshot *s)
{
    CollisionBody *b;

    ReplaySnapshot_BeginNamedSection(s, "AllSmokeables");
    ReplaySnapshot_MoveInt(s, &AwakeSmokeablesCount, 4);
    if (s->RestoringSnapshotFlag) {
        uint16_t index = 0, id = 0;
        uint32_t info_hash = 0, name_hash = 0;
        int32_t type = 0;

        delete_smokeable_collision_bodies();
        for (;;) {
            VirginSmokeable *v;

            ReplaySnapshot_MoveUShort(s, &index, 2);
            if (index == 0xffff)
                break;
            v = virginsmokeable_init(
                (VirginSmokeable *)bSlotOMalloc(VirginSmokeableSlotPool),
                &pSmokeableSpawners[index]);
            body_do_snapshot(&v->Static.Body, s);
        }
        for (;;) {
            Smokeable *sm;

            ReplaySnapshot_MoveUShort(s, &id, 2);
            if (id == 0xffff)
                break;
            ReplaySnapshot_MoveUInt(s, &info_hash, 4);
            ReplaySnapshot_MoveUInt(s, &name_hash, 4);
            ReplaySnapshot_MoveData(s, &type, 1, -1, 0);
            sm = smokeable_create(type, id, find_smokeable_info(info_hash),
                                  name_hash);
            body_do_snapshot(&sm->Dynamic.Body, s);
        }
    } else {
        int16_t end = -1;

        for (b = CollisionBodyList.next; b != BODY_END; b = b->Link.next) {
            VirginSmokeable *v = (VirginSmokeable *)(void *)b;
            int16_t index;

            if (b->Type != VIRGIN_SMOKEABLE_COLLISION_BODY)
                continue;
            index = (int16_t)(v->pSmokeableSpawner - pSmokeableSpawners);
            ReplaySnapshot_MoveShort(s, &index, 2);
            body_do_snapshot(b, s);
        }
        ReplaySnapshot_MoveShort(s, &end, 2);
        for (b = CollisionBodyList.next; b != BODY_END; b = b->Link.next) {
            Smokeable *sm = (Smokeable *)(void *)b;
            uint16_t id;
            uint32_t name_hash;
            int32_t type;

            if (b->Type != SMOKEABLE_COLLISION_BODY)
                continue;
            id = (uint16_t)b->ID;
            name_hash = worldobject_get_name_hash(&sm->TheWorldObject);
            type = body_get_smoke_type(b);
            ReplaySnapshot_MoveUShort(s, &id, 2);
            ReplaySnapshot_MoveUInt(s, &sm->SI->NameHash, 4);
            ReplaySnapshot_MoveUInt(s, &name_hash, 4);
            ReplaySnapshot_MoveData(s, &type, 1, -1, 0);
            body_do_snapshot(b, s);
        }
        ReplaySnapshot_MoveShort(s, &end, 2);
    }
    ReplaySnapshot_EndSection(s);
}
