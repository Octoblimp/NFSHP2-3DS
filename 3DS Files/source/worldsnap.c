// worldsnap -- the top of a replay snapshot (TASKS 72d-2): World::DoSnapshot
// (retail's 0x0014d148), RaceCoordinator::DoSnapshot (0x001498f0), which
// takes the World's, the Race's and every Player's, and SnapshotCops
// (0x00227cd8).
//
// World's takes its own state, then the clock's, the teleporter's, the
// track graph's, every car's, the cops' and the chopper's, then the
// smokeables' and the collision bodies'. A restore first throws away what
// a snapshot cannot carry -- the clans, the effects, the fern shakers, the
// glare and the camera shakers -- and, before the bodies, every witness,
// which the snapshot makes again.
//
// Prototypes: world.h and racecoord.h. Cross-check:
// tools/worldsnap_check.py. Write-up: docs/formats/replay.md.

#include <stddef.h>
#include <stdint.h>

#include "acidsys.h"
#include "car.h"
#include "collisionbody.h"
#include "copmanager.h"
#include "player.h"
#include "race.h"
#include "racecoord.h"
#include "racecore.h"
#include "realtime.h"
#include "replay.h"
#include "shake.h"
#include "smokeable.h"
#include "sundraw.h"
#include "trackgraph.h"
#include "traffictele.h"
#include "world.h"

// The calls the port has nothing for yet; a NULL one is skipped.
void (*gFlushClansFn)(void);
void (*gFlushFernShakersFn)(void);
void (*gCopManagerDoSnapshotFn)(struct tCopManager *m,
                                struct ReplaySnapshot *s);
void (*gChopperDoSnapshotFn)(struct Chopper *h, struct ReplaySnapshot *s);

void snapshot_cops(ReplaySnapshot *s)
{
    if (pCopManager != NULL && gCopManagerDoSnapshotFn != NULL)
        gCopManagerDoSnapshotFn(pCopManager, s);
}

// The callback goes as its four bytes, as retail moves it: a replay plays
// back in the run that took it.
void world_do_snapshot(World *w, ReplaySnapshot *s)
{
    int32_t i;

    ReplaySnapshot_BeginNamedSection(s, "World");
    ReplaySnapshot_MoveUInt(s, &w->WorldRandomSeed, 4);            // 376
    ReplaySnapshot_MoveFloat(s, &w->fTimeToRemainPaused);          // 380
    ReplaySnapshot_MoveFloat(s, &w->fTimeScale);                   // 388
    ReplaySnapshot_MoveFloat(s, &w->fTimeScaleTimer);              // 392
    ReplaySnapshot_MoveData(s, (void *)&w->TimeScaleCallback, 4, -1, 0);
    ReplaySnapshot_MoveInt(s, &w->TimeScaleCallbackParam, 4);      // 400
    ReplaySnapshot_MoveVector3(s, &w->PlayerPositions[0]);         // 336
    ReplaySnapshot_MoveVector3(s, &w->PlayerPositions[1]);         // 352
    ReplaySnapshot_MoveFloat(s, &w->PlayerDATs[0]);                // 368
    ReplaySnapshot_MoveFloat(s, &w->PlayerDATs[1]);                // 372
    ReplaySnapshot_MoveUInt(s, &w->CollisionPredictionID, 4);      // 408
    ReplaySnapshot_MoveUInt(s, &w->PotentialDriveTargetID, 4);     // 412
    if (s->RestoringSnapshotFlag) {
        if (gFlushClansFn != NULL)
            gFlushClansFn();
        acid_system_kill_all_active_effects(&WorldEffects);
        if (gFlushFernShakersFn != NULL)
            gFlushFernShakersFn();
        bResetGlare = 1;
        reset_camera_shakers();
    }
    WorldTimeDoSnapshot(s);
    if (w->Teleporter != NULL)
        traffic_teleporter_do_snapshot(w->Teleporter, s);
    if (TheTrackGraph != NULL)
        trackgraph_do_snapshot(TheTrackGraph, s);
    for (i = 0; i < w->TotalNumCars; i++)
        car_do_snapshot(w->CarTable[i], s);
    snapshot_cops(s);
    if (w->Helicopter != NULL && gChopperDoSnapshotFn != NULL)
        gChopperDoSnapshotFn(w->Helicopter, s);
    if (s->RestoringSnapshotFlag)
        cbwitness_eliminate_all();
    snapshot_all_smokeables(s);
    trackpolygoncollisionbody_snapshot_everything(s);
    collisionbody_snapshot_everything(s);
    cbwitness_snapshot_everything(s);
    ReplaySnapshot_EndSection(s);
}

// The coordinator itself has nothing in the snapshot.
void racecoordinator_do_snapshot(RaceCoordinator *rc, ReplaySnapshot *s)
{
    int32_t i;

    (void)rc;
    ReplaySnapshot_BeginNamedSection(s, "RaceCoordinator");
    world_do_snapshot(pCurrentWorld, s);
    race_do_snapshot(pCurrentRace, s);
    for (i = 0; i < PlayerNumPlayers; i++)
        player_do_snapshot(PlayerPlayersByIndex[i], s);
    ReplaySnapshot_EndSection(s);
}
