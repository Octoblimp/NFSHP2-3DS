// copmgrsnap -- tCopManager::DoSnapshot, retail's 0x00223b70 (TASKS 72e-3):
// the cop manager's part of a replay snapshot, which World's reaches
// through SnapshotCops and gCopManagerDoSnapshotFn.
//
// A file of its own, as copsnap.c is: it deletes and makes the pursuits
// and the spike strips a restore needs, and reaches the pursuits', the
// cops' and the strips' snapshots (copsnap.c), which a checker records
// rather than runs. Retail's VerifyMoveDataInSync calls between the parts
// ("After tPursuits" and the rest) reach an empty function and are left
// out.
//
// Prototype: copmgr.h. Cross-check: tools/copmgrsnap_check.py. Write-up:
// docs/formats/replay.md.

#include <stdint.h>

#include "bslotpool.h"
#include "copmanager.h"
#include "copmgr.h"
#include "pursuit.h"
#include "race.h"
#include "replay.h"
#include "spikestrip.h"
#include "vtable.h"
#include "world.h"

typedef void (*DtorFn)(void *self, int32_t flags);
typedef void (*CopSnapshotFn)(void *self, ReplaySnapshot *s);

// TraversebList(list, NULL), 0x00250428: the nodes after the head.
static int32_t list_count(const tPursuitNode *list)
{
    const tPursuitNode *n;
    int32_t             k = 0;

    for (n = list->Next; n != list; n = n->Next)
        k++;
    return k;
}

// The speakers' Deque<unsigned int,4>, inlined as copmgr.c's are.
static int deque_empty(const CopSpeakerDeque *d)
{
    return d->Full == 0 && d->Tail == d->Head;
}

static void push_head(CopSpeakerDeque *d, uint32_t v)
{
    if (d->Full != 0)
        return;
    d->Head = d->Head == 0 ? 3 : d->Head - 1;
    d->Data[d->Head] = v;
    d->Full = d->Tail == d->Head;
}

// The speakers' voice ids, back to front, then 6. Taking (and either
// checksum) turns the ring a whole time round, each id from the tail back
// to the head, until the id that was at the head comes round again; a
// restore pushes each id at the head of an emptied ring.
static void speakers_do_snapshot(CopSpeakerDeque *d, ReplaySnapshot *s)
{
    uint32_t v = 0, front = 0;

    if (s->RestoringSnapshotFlag) {
        d->Full = 0;
        d->Tail = d->Head;
        ReplaySnapshot_MoveUInt(s, &v, 4);
        while (v != 6) {
            push_head(d, v);
            ReplaySnapshot_MoveUInt(s, &v, 4);
        }
        return;
    }
    if (!deque_empty(d)) {
        front = d->Data[d->Head];
        do {
            if (!deque_empty(d)) {
                d->Tail = d->Tail == 0 ? 3 : d->Tail - 1;
                d->Full = 0;
                v = d->Data[d->Tail];
            }
            push_head(d, v);
            ReplaySnapshot_MoveUInt(s, &v, 4);
        } while (v != front);
    }
    v = 6;
    ReplaySnapshot_MoveUInt(s, &v, 4);
}

// The counts are verified; a restore empties the roadblocks' and the
// radar traps' cops, which the cops' own snapshots give back. The
// pursuits go as a count and their ids, a restore deleting every pursuit
// and making one for each id, then each pursuit's own; each cop's, through
// its table; the strips as a count, a restore destroying every strip and
// making each again at the head of the list, then each strip's own. Then
// the pullovers, the speakers, the timers, Be A Cop's damage and time, and
// Be A Cop's counts.
void copmanager_do_snapshot(tCopManager *m, ReplaySnapshot *s)
{
    tPursuitNode *pl = &m->PursuitList;
    tPursuitNode *sl = &m->SpikeStripList;
    tPursuitNode *n;
    uint8_t       npursuits;
    int32_t       nstrips, i;

    ReplaySnapshot_BeginSection(s, m, "tCopManager");
    ReplaySnapshot_VerifyInt(s, &m->nNumAICops, 4);                //    4
    ReplaySnapshot_VerifyInt(s, &m->nNumRoadBlocks, 4);            //  316
    ReplaySnapshot_VerifyInt(s, &m->nNumSpeedTraps, 4);            // 8256
    if (s->RestoringSnapshotFlag) {
        for (i = 0; i < m->nNumRoadBlocks; i++) {
            m->RoadBlocks[i].cops[0] = NULL;
            m->RoadBlocks[i].cops[1] = NULL;
        }
        for (i = 0; i < m->nNumSpeedTraps; i++)
            m->SpeedTraps[i].cop = NULL;
    }

    // The pursuits.
    npursuits = (uint8_t)list_count(pl);
    ReplaySnapshot_MoveUChar(s, &npursuits, 1);
    if (s->RestoringSnapshotFlag) {
        while (pl->Next != pl)
            copmanager_delete_pursuit(m, (tPursuit *)(void *)pl->Next);
        for (i = 0; i < npursuits; i++) {
            int8_t id;

            ReplaySnapshot_MoveChar(s, &id, 1);
            copmanager_new_pursuit(m, id, NULL);
        }
    } else {
        for (n = pl->Next; n != pl; n = n->Next) {
            int8_t id = ((tPursuit *)(void *)n)->nPursuitId;       // 1480

            ReplaySnapshot_MoveChar(s, &id, 1);
        }
    }
    for (n = pl->Next; n != pl; n = n->Next)
        tpursuit_do_snapshot((tPursuit *)(void *)n, s);

    // The cops.
    for (i = 0; i < m->nNumCops; i++) {
        tCop          *c = m->Cops[i];
        const VtEntry *e = vt_slot(c->vptr, TCOP_VT_SNAPSHOT);

        ((CopSnapshotFn)e->fn)(vt_this(c, e), s);
    }

    // The spike strips.
    nstrips = list_count(sl);
    ReplaySnapshot_MoveInt(s, &nstrips, 4);
    if (s->RestoringSnapshotFlag) {
        while (sl->Next != sl) {
            tSpikeStrip   *t = (tSpikeStrip *)(void *)sl->Next;
            tPursuitNode  *nx = t->Node.Next, *pv = t->Node.Prev;
            const VtEntry *e = vt_slot(t->vptr, TSPIKESTRIP_VT_DTOR);

            pv->Next = nx;
            nx->Prev = pv;
            ((DtorFn)e->fn)(vt_this(t, e), 3);
        }
        for (i = 0; i < nstrips; i++) {
            tSpikeStrip  *t = tspikestrip_construct_default(
                (tSpikeStrip *)bSlotOMalloc(SpikeStripSlotPool));
            tPursuitNode *old = sl->Next;

            sl->Next = &t->Node;
            old->Prev = &t->Node;
            t->Node.Next = old;
            t->Node.Prev = sl;
        }
    }
    for (n = sl->Next; n != sl; n = n->Next)
        tspikestrip_do_snapshot((tSpikeStrip *)(void *)n, s);

    // The pullovers and the chopper.
    for (i = 0; i < COPMANAGER_NUM_PULLOVERS; i++) {
        tCarPulloverInfo *p = &m->CarPullovers[i];

        ReplaySnapshot_MoveBool(s, &p->bActive, 1);                //   12
        ReplaySnapshot_MoveBool(s, &p->bPlayNIS, 1);               //   16
        ReplaySnapshot_MoveBool(s, &p->bArrest, 1);                //   20
        ReplaySnapshot_MoveFloat(s, &p->fHoldTimer);               //    4
        ReplaySnapshot_MoveChar(s, &p->nNumTickets, 1);            //    8
        ReplaySnapshot_MoveInt(s, &p->nCopIndex, 4);               //    0
    }
    ReplaySnapshot_MoveBool(s, &m->bChopperBusy, 1);               //  312

    speakers_do_snapshot(&m->CopSpeakers, s);                      // 10308

    // The timers, one of each for each car up to the cops.
    for (i = 0; i < pCurrentWorld->CopCarPos; i++) {
        ReplaySnapshot_MoveFloat(s, &m->fPursuableTimer[i]);       // 10356
        ReplaySnapshot_MoveFloat(s, &m->fSpeedTrapSpawnTimer[i]);  // 10388
    }

    if (TheRaceParameters.BeACop) {
        for (i = 0; i < COPMANAGER_NUM_CARS; i++)
            ReplaySnapshot_MoveFloat(s, &m->fCarDamage[i]);        // 10420
        ReplaySnapshot_MoveFloat(s, &m->fBeACopTime);              // 10480
    }

    ReplaySnapshot_MoveBool(s, &m->bBeACopAlreadySaidLookOutForSpeeders,
                            1);                                    // 10484
    ReplaySnapshot_MoveBool(s, &m->New10488, 1);                   // 10488
    ReplaySnapshot_MoveInt(s, &m->nBeACopNumRoadBlocks, 4);        //    0
    ReplaySnapshot_MoveInt(s, &m->nBeACopNumChopperAttacks, 4);    // 10492
    ReplaySnapshot_MoveInt(s, &m->nBeACopNumArrestsMade, 4);       // 10496
    ReplaySnapshot_EndSection(s);
}
