// bodysnap -- the collision bodies' part of a replay snapshot (TASKS
// 72d-2): the three SnapshotEverything methods World's calls after the
// smokeables', retail's 0x001d8980 (TrackPolygonCollisionBody), 0x001d6e70
// (CollisionBody) and 0x001d6208 (CollisionBodyWitness).
//
// A file of its own, as carsnap.c is the car's: a restore makes track
// polygons' bodies and witnesses from the pools and their constructors,
// which a checker records rather than runs. Every body's and witness's own
// snapshot is collisionbody.c's (TASKS 72b).
//
// Prototypes: collisionbody.h. Cross-check: tools/worldsnap_check.py.
// Write-up: docs/formats/replay.md.

#include <stdint.h>

#include "bslotpool.h"
#include "collisionbody.h"
#include "replay.h"
#include "topology.h"
#include "vtable.h"

#define BODY_END    ((CollisionBody *)(void *)&CollisionBodyList)
#define WITNESS_END ((CollisionBodyWitness *)(void *)&CollisionBodyWitnessList)

typedef void (*BodySnapshotFn)(void *self, ReplaySnapshot *s);

// The body's own DoSnapshot, slot 16 of its table.
static void body_do_snapshot(CollisionBody *b, ReplaySnapshot *s)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_DO_SNAPSHOT);

    ((BodySnapshotFn)e->fn)(vt_this(b, e), s);
}

// Each track polygon's body as its polygon's index in the tree's table and
// its ID, then its own snapshot; 0xffff ends the list. A restore makes each
// again on the same polygon.
void trackpolygoncollisionbody_snapshot_everything(ReplaySnapshot *s)
{
    CollisionBody *b;

    ReplaySnapshot_BeginNamedSection(s, "AllTrackPolygonCollisionBodies");
    ReplaySnapshot_VerifyInt(
        s, &TheCollisionStats.NumTrackPolygonCollisionBodies, 4);
    if (s->RestoringSnapshotFlag) {
        uint16_t index = 0, id = 0;

        for (;;) {
            TopologyTreePolygon *p;
            TrackPolygonCollisionBody *t;

            ReplaySnapshot_MoveUShort(s, &index, 2);
            if (index == 0xffff)
                break;
            p = &TheTopologyTree.pPolygonTable[index];
            ReplaySnapshot_MoveUShort(s, &id, 2);
            t = trackpolygoncollisionbody_init(
                (TrackPolygonCollisionBody *)bSlotOMalloc(
                    TrackPolygonCollisionBodySlotPool), id, p);
            body_do_snapshot(&t->Static.Body, s);
        }
    } else {
        uint16_t end = 0xffff;

        for (b = CollisionBodyList.next; b != BODY_END; b = b->Link.next) {
            TrackPolygonCollisionBody *t =
                (TrackPolygonCollisionBody *)(void *)b;
            uint16_t index, id;

            if (b->Type != TRACK_POLYGON_COLLISION_BODY)
                continue;
            index = (uint16_t)(t->pTP->pPolygon
                               - TheTopologyTree.pPolygonTable);
            ReplaySnapshot_MoveUShort(s, &index, 2);
            id = (uint16_t)b->ID;
            ReplaySnapshot_MoveUShort(s, &id, 2);
            body_do_snapshot(b, s);
        }
        ReplaySnapshot_MoveUShort(s, &end, 2);
    }
    ReplaySnapshot_EndSection(s);
}

// Checksumming only: every body's ID, in list order.
void collisionbody_snapshot_everything(ReplaySnapshot *s)
{
    CollisionBody *b;

    ReplaySnapshot_BeginNamedSection(s, "AllCollisionBodies");
    for (b = CollisionBodyList.next; b != BODY_END; b = b->Link.next) {
        uint16_t id = (uint16_t)b->ID;

        ReplaySnapshot_VerifyUShort(s, &id, 2);
    }
    ReplaySnapshot_EndSection(s);
}

// The witness count, then each witness as its two bodies' IDs and its own
// snapshot. A restore finds the bodies by ID and makes the witness again;
// World's has eliminated the old ones first.
void cbwitness_snapshot_everything(ReplaySnapshot *s)
{
    ReplaySnapshot_BeginNamedSection(s, "AllCollisionBodyWitnesses");
    if (s->RestoringSnapshotFlag) {
        int32_t n = 0, i, id1 = 0, id2 = 0;

        ReplaySnapshot_MoveInt(s, &n, 2);
        for (i = 0; i < n; i++) {
            CollisionBody *b1, *b2;
            CollisionBodyWitness *w;

            ReplaySnapshot_MoveInt(s, &id1, 2);
            ReplaySnapshot_MoveInt(s, &id2, 2);
            b1 = collisionbody_find(id1);
            b2 = collisionbody_find(id2);
            w = cbwitness_init((CollisionBodyWitness *)bSlotOMalloc(
                                   CollisionBodyWitnessSlotPool), b1, b2);
            cbwitness_do_snapshot(w, s);
        }
    } else {
        CollisionBodyWitness *w;

        ReplaySnapshot_MoveInt(s, &TheCollisionStats.NumCollisionBodyWitnesses,
                               2);
        for (w = CollisionBodyWitnessList.next; w != WITNESS_END;
             w = w->Link.next) {
            int32_t id1 = w->pBody1->ID, id2 = w->pBody2->ID;

            ReplaySnapshot_MoveInt(s, &id1, 2);
            ReplaySnapshot_MoveInt(s, &id2, 2);
            cbwitness_do_snapshot(w, s);
        }
    }
    ReplaySnapshot_EndSection(s);
}
