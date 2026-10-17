// copsnap -- the cops' part of a replay snapshot (TASKS 72e): the
// munitions' own DoSnapshots, DroppedSpikes' (retail's 0x001bef90) and
// Rocket's (0x001bf910), slot 16 of their tables; tSpikeStrip's
// (0x00241898); and the chopper's (0x001e7d08), which World's calls through
// gChopperDoSnapshotFn.
//
// A file of its own, as worldsnap.c is: each reaches its class's own
// functions (the strip's Init, the chopper's RemoveChopperFromWorld and
// ClearVariables) and the other classes' snapshots, which a checker records
// rather than runs.
//
// Prototypes: munition.h, spikestrip.h, chopper.h. Cross-check:
// tools/copsnap_check.py. Write-up: docs/formats/replay.md.

#include <stdint.h>

#include "chopper.h"
#include "collisionbody.h"
#include "munition.h"
#include "replay.h"
#include "smokeable.h"
#include "spikestrip.h"
#include "trackpath.h"
#include "trackroute.h"
#include "world.h"

// ---------------------------------------------------------- the munitions

// Struck spikes not yet gone off, then the smokeable.
void droppedspikes_do_snapshot(CollisionBody *b, ReplaySnapshot *s)
{
    DroppedSpikes *d = (DroppedSpikes *)(void *)b;

    ReplaySnapshot_BeginSection(s, d, "DroppedSpikes");
    ReplaySnapshot_MoveBool(s, &d->DeploySpikes, 1);               // 1152
    smokeable_do_snapshot(b, s);
    ReplaySnapshot_EndSection(s);
}

// The yaw and the target, then the smokeable.
void rocket_do_snapshot(CollisionBody *b, ReplaySnapshot *s)
{
    Rocket *r = (Rocket *)(void *)b;

    ReplaySnapshot_BeginSection(s, r, "Rocket");
    ReplaySnapshot_MoveFloat(s, &r->Yaw);                          // 1156
    world_do_car_pointer_snapshot(pCurrentWorld, &r->Target, s);   // 1152
    smokeable_do_snapshot(b, s);
    ReplaySnapshot_EndSection(s);
}

// ------------------------------------------------------- the spike strip

// The ends, the roadblock and the lifetime; a restore lays the pieces
// again (Init), which leaves the blink alone. Then the blink.
void tspikestrip_do_snapshot(tSpikeStrip *t, ReplaySnapshot *s)
{
    ReplaySnapshot_BeginNamedSection(s, "tSpikeStrip");
    ReplaySnapshot_MoveVector2(s, &t->v2Start);                    //    8
    ReplaySnapshot_MoveVector2(s, &t->v2End);                      //   16
    ReplaySnapshot_MoveInt(s, &t->nRoadBlockID, 4);                //   24
    ReplaySnapshot_MoveFloat(s, &t->fLifetime);                    //   36
    if (s->RestoringSnapshotFlag)
        tspikestrip_init(t, &t->v2Start, &t->v2End, t->nRoadBlockID,
                         t->fLifetime);
    ReplaySnapshot_MoveBool(s, &t->bIsBlinking, 1);                //   28
    ReplaySnapshot_MoveFloat(s, &t->fBlinkTimer);                  //   32
    ReplaySnapshot_EndNamedSection(s);
}

// ------------------------------------------------------------ the chopper

// A restore takes the chopper out of the world first. Eating donuts it
// moves nothing more, and taking or restoring clears it; otherwise the
// rest, the routes and the points as numbers.
void chopper_do_snapshot(struct Chopper *h, ReplaySnapshot *s)
{
    TrackRouteManager *m = &TheTrackRouteManager;

    ReplaySnapshot_BeginNamedSection(s, "Chopper");
    if (s->RestoringSnapshotFlag)
        chopper_remove_from_world(h);
    ReplaySnapshot_MoveData(s, &h->Plan, 1, -1, 0);                //  728
    if (h->Plan == CHOPPLAN_EATING_DONUTS) {
        if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag)
            chopper_clear_variables(h);
        ReplaySnapshot_EndNamedSection(s);
        return;
    }
    ReplaySnapshot_MoveFloat(s, &h->TimeUntilThink);               //  720
    world_do_car_pointer_snapshot(pCurrentWorld, &h->CurrentCar, s); // 724
    ReplaySnapshot_MoveData(s, &h->MoveMode, 1, -1, 0);            //  732
    trmgr_do_route_pointer_snapshot(m, s, &h->ChopperRoute);       //  736
    trmgr_do_point_pointer_snapshot_in_route(m, s, &h->ChopperPoint,
                                             h->ChopperRoute);     //  740
    trmgr_do_route_pointer_snapshot(m, s, &h->TargetRoute);        //  744
    trmgr_do_point_pointer_snapshot_in_route(m, s, &h->TargetPoint,
                                             h->TargetRoute);      //  748
    trmgr_do_route_pointer_snapshot(m, s, &h->OldCarRoute);        //  796
    trmgr_do_point_pointer_snapshot_in_route(m, s, &h->OldCarPoint,
                                             h->OldCarRoute);      //  800
    trackpath_coord_do_snapshot(&h->TP, s);                        //  752
    ReplaySnapshot_MoveVector3(s, &h->CurrentPos);                 //  832
    ReplaySnapshot_MoveMatrix(s, &h->Matrix);                      //  848
    ReplaySnapshot_MoveFloat(s, &h->Speed);                        //  912
    ReplaySnapshot_MoveVector2(s, &h->Acceleration);               //  916
    ReplaySnapshot_MoveFloat(s, &h->Roll);                         //  924
    ReplaySnapshot_MoveFloat(s, &h->DesiredRoll);                  //  928
    ReplaySnapshot_MoveFloat(s, &h->Yaw);                          //  932
    ReplaySnapshot_MoveFloat(s, &h->Pitch);                        //  936
    ReplaySnapshot_MoveFloat(s, &h->DesiredPitch);                 //  940
    ReplaySnapshot_MoveFloat(s, &h->RotRate);                      //  944
    ReplaySnapshot_MoveFloat(s, &h->ZVelocity);                    //  948
    ReplaySnapshot_MoveFloat(s, &h->GroundZ);                      //  952
    ReplaySnapshot_MoveBool(s, &h->EmitDust, 1);                   //  956
    ReplaySnapshot_MoveFloat(s, &h->TargetDistance);               //  792
    ReplaySnapshot_MoveData(s, &h->BombRunType, 1, -1, 0);         //  804
    ReplaySnapshot_MoveInt(s, &h->NumSalvosReleased, 4);           //  808
    ReplaySnapshot_MoveFloat(s, &h->TimeUntilNextSalvo);           //  812
    ReplaySnapshot_MoveInt(s, &h->NextLauncher, 4);                //  816
    ReplaySnapshot_MoveFloat(s, &h->Timeout);                      //  820
    ReplaySnapshot_MoveFloat(s, &h->StuckTime);                    //  824
    ReplaySnapshot_MoveInt(s, &h->TotalSalvos, 4);                 //  828
    ReplaySnapshot_EndNamedSection(s);
}
