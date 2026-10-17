// copsnap -- the cops' part of a replay snapshot (TASKS 72e). 72e-1: the
// munitions' own DoSnapshots, DroppedSpikes' (retail's 0x001bef90) and
// Rocket's (0x001bf910), slot 16 of their tables; tSpikeStrip's
// (0x00241898); and the chopper's (0x001e7d08), which World's calls through
// gChopperDoSnapshotFn. 72e-2: the cop manager's pursuit, cop and radar
// trap pointers (0x002245b8, 0x00224648, 0x002243f8); tPursuit's
// (0x0022a548) with its history's (0x0022d180), its roadblock state
// machine's (0x0022ce60) and its barrels' (0x0024f358); and the cops',
// tCop's (0x0022d440), tPlayerCop's (0x0022d7e8) and tAICop's (0x0022dd20),
// slot 32 of the cops' tables.
//
// A file of its own, as worldsnap.c is: each reaches its class's own
// functions (the strip's Init, the chopper's RemoveChopperFromWorld and
// ClearVariables, the pursuit's IsCopInPursuit) and the other classes'
// snapshots, which a checker records rather than runs.
//
// Prototypes: munition.h, spikestrip.h, chopper.h, copmanager.h, pursuit.h,
// barricade.h, cop.h. Cross-check: tools/copsnap_check.py. Write-up:
// docs/formats/replay.md.

#include <stdint.h>

#include "barricade.h"
#include "car.h"
#include "chopper.h"
#include "collisionbody.h"
#include "cop.h"
#include "copmanager.h"
#include "drivetarget.h"
#include "munition.h"
#include "pursuit.h"
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

// ------------------------------------------- the cop manager's pointers

// A pursuit as its id, a signed byte: a restore reads it into -1 and looks
// it up; the other modes move the pursuit's own id, or -1 for none.
void copmanager_do_pursuit_pointer_snapshot(tCopManager *m, ReplaySnapshot *s,
                                            tPursuit **pp)
{
    int8_t c = -1;

    if (s->RestoringSnapshotFlag) {
        ReplaySnapshot_MoveChar(s, &c, 1);
        *pp = NULL;
        if (c >= 0)
            *pp = m->PursuitsById[c];
        return;
    }
    if (*pp != NULL)
        c = (*pp)->nPursuitId;
    ReplaySnapshot_MoveChar(s, &c, 1);
}

// A cop as its number, an int stored in one byte.
void copmanager_do_cop_pointer_snapshot(tCopManager *m, ReplaySnapshot *s,
                                        tCop **pp)
{
    int32_t n = -1;

    if (*pp != NULL)
        n = (*pp)->nCopNumber;
    ReplaySnapshot_MoveInt(s, &n, 1);
    if (s->RestoringSnapshotFlag) {
        *pp = NULL;
        if (n >= 0)
            *pp = m->Cops[n];
    }
}

// A radar trap as its index in SpeedTraps, the same way.
void copmanager_do_speed_trap_pointer_snapshot(tCopManager *m,
                                               ReplaySnapshot *s,
                                               tSpeedTrap **pp)
{
    int32_t n = -1;

    if (*pp != NULL)
        n = (int32_t)(*pp - m->SpeedTraps);
    ReplaySnapshot_MoveInt(s, &n, 1);
    if (s->RestoringSnapshotFlag) {
        *pp = NULL;
        if (n >= 0)
            *pp = &m->SpeedTraps[n];
    }
}

// ------------------------------------------------------------ the pursuit

// The chased car's last 30 velocities: the count, then each velocity
// before its time, all 30.
void tpursuithistory_do_snapshot(tPursuitHistory *h, ReplaySnapshot *s)
{
    int32_t i;

    ReplaySnapshot_MoveInt(s, &h->nCount, 1);                      //    0
    for (i = 0; i < 30; i++) {
        ReplaySnapshot_MoveVector2(s, &h->v2Velocity[i]);          //    4
        ReplaySnapshot_MoveFloat(s, &h->fTime[i]);                 //  244
    }
}

// No section; the pursuit is set back in every mode.
void troadblockstatemachine_do_snapshot(tRoadBlockStateMachine *sm,
                                        ReplaySnapshot *s, tPursuit *p)
{
    ReplaySnapshot_MoveData(s, &sm->State, 1, -1, 0);              //    0
    ReplaySnapshot_MoveFloat(s, &sm->fStateTimer);                 //    4
    ReplaySnapshot_MoveInt(s, (int32_t *)&sm->SpeechFlags, 4);     //    8
    ReplaySnapshot_MoveInt(s, &sm->nRoadBlockCount, 4);            //   12
    sm->pPursuit = p;                                              //   16
}

// Each barrel's fade timer, then its id.
void barricademanager_do_snapshot(BarricadeManager *b, ReplaySnapshot *s)
{
    int32_t i;

    ReplaySnapshot_BeginNamedSection(s, "BarricadeManager");
    for (i = 0; i < BARRICADE_MAX_BARRELS; i++) {
        ReplaySnapshot_MoveFloat(s, &b->fFadeTimer[i]);            //   20
        ReplaySnapshot_MoveShort(s, &b->nBarrel[i], 2);            //    0
    }
    ReplaySnapshot_EndNamedSection(s);
}

// The id checked; the car, the roadblock with its speaker and cops, the
// chopper as a flag (World's on a restore); then the rest in retail's
// order, the drive targets, the history while a player is chased, the
// roadblock's state machine and the barrels.
void tpursuit_do_snapshot(tPursuit *p, ReplaySnapshot *s)
{
    int32_t chopper, i;

    ReplaySnapshot_BeginSection(s, p, "tPursuit");
    ReplaySnapshot_VerifyChar(s, &p->nPursuitId, 1);               // 1480
    world_do_pointer_snapshot(pCurrentWorld, s, &p->pChasedCar);   //   16
    copmanager_do_road_block_pointer_snapshot(pCopManager, s,
                                              &p->pRoadBlock);     //   20
    if (p->pRoadBlock != NULL) {
        ReplaySnapshot_MoveUInt(s, &p->pRoadBlock->CopSpeaker, 4); // rb 116
        for (i = 0; i < 2; i++)
            copmanager_do_cop_pointer_snapshot(
                pCopManager, s, (tCop **)&p->pRoadBlock->cops[i]); // rb 0
    }
    ReplaySnapshot_MoveUInt(s, &p->PrimaryCopSpeaker, 4);          // 1496
    ReplaySnapshot_MoveUInt(s, &p->SecondaryCopSpeaker, 4);        // 1500
    ReplaySnapshot_MoveInt(s, &p->nMaxChaseCops, 4);               //    8
    ReplaySnapshot_MoveInt(s, &p->nMaxRoadBlockCops, 4);           //   12
    ReplaySnapshot_MoveInt(s, &p->nRoadblockCount, 4);             // 1584
    chopper = p->pChopper != NULL;
    ReplaySnapshot_MoveInt(s, &chopper, 4);                        //   24
    if (s->RestoringSnapshotFlag) {
        p->pChopper = NULL;
        if (chopper)
            p->pChopper = pCurrentWorld->Helicopter;
    }
    ReplaySnapshot_MoveFloat(s, &p->fChopperAttackTimer);          // 1536
    ReplaySnapshot_MoveFloat(s, &p->fChopperNextAttackTime);       // 1540
    ReplaySnapshot_MoveData(s, &p->ChopperState, 1, -1, 0);        // 1580
    ReplaySnapshot_MoveInt(s, &p->nNumCops, 4);                    // 1476
    for (i = 0; i < p->nNumCops; i++)
        copmanager_do_cop_pointer_snapshot(pCopManager, s,
                                           &p->Cops[i]);           //   28
    ReplaySnapshot_MoveData(s, &p->PursuitState, 1, -1, 0);        // 1484
    ReplaySnapshot_MoveData(s, &p->PursuitSubState, 1, -1, 0);     // 1488
    ReplaySnapshot_MoveData(s, &p->CurrentLandmark, 1, -1, 0);     // 1504
    ReplaySnapshot_MoveFloat(s, &p->fPursuitStateTimer);           // 1524
    ReplaySnapshot_MoveFloat(s, &p->fRoadBlockSpawnTimer);         // 1532
    ReplaySnapshot_MoveFloat(s, &p->fRoadBlockDisbandTimer);       // 1528
    ReplaySnapshot_MoveFloat(s, &p->fCatchCarTimer);               // 1520
    ReplaySnapshot_MoveFloat(s, &p->fChaseDirection);              // 1548
    ReplaySnapshot_MoveFloat(s, &p->fChaseDirectionTimer);         // 1552
    ReplaySnapshot_MoveFloat(s, &p->New1556);                      // 1556
    ReplaySnapshot_MoveBool(s, &p->bAlreadyJoined, 1);             // 1508
    ReplaySnapshot_MoveBool(s, &p->bAlreadyBeenHit, 1);            // 1512
    ReplaySnapshot_MoveBool(s, &p->bAlreadyCalledForBackup, 1);    // 1516
    ReplaySnapshot_MoveFloat(s, &p->fChasedCarTopSpeed);           // 1544
    ReplaySnapshot_MoveUInt(s, &p->BehaviourFlags, 4);             // 1588
    ReplaySnapshot_MoveInt(s, &p->nHUDPursuitLevel, 1);            // 1492
    drivetarget_do_snapshot(&p->FarDriveTarget, s);                //   48
    drivetarget_do_snapshot(&p->NearDriveTarget, s);               //  576
    if (p->pChasedCar->pPlayer != NULL)
        tpursuithistory_do_snapshot(&p->History, s);               // 1104
    troadblockstatemachine_do_snapshot(&p->RoadBlockStateMachine, s,
                                       p);                         // 1560
    barricademanager_do_snapshot(p->pBarricades, s);               // 1472
    ReplaySnapshot_EndSection(s);
}

// --------------------------------------------------------------- the cops

// The base's, which both cops' call first: the car and the pursuit; a
// pursuit that no longer holds the cop, or has gone (its id below 0), is
// dropped in every mode. Then the four logic states' bytes.
void tcop_do_snapshot(tCop *c, ReplaySnapshot *s)
{
    ReplaySnapshot_BeginNamedSection(s, "tCop");
    world_do_pointer_snapshot(pCurrentWorld, s, &c->pMyCar);       //    4
    copmanager_do_pursuit_pointer_snapshot(pCopManager, s,
                                           &c->pMyPursuit);        //    0
    if (c->pMyPursuit != NULL) {
        if (!tpursuit_is_cop_in_pursuit(c->pMyPursuit, c))
            c->pMyPursuit = NULL;
        else if (c->pMyPursuit->nPursuitId < 0)
            c->pMyPursuit = NULL;
    }
    ReplaySnapshot_MoveData(s, &c->LogicState, 1, -1, 0);          //   12
    ReplaySnapshot_MoveData(s, &c->LogicSubState, 1, -1, 0);       //   20
    ReplaySnapshot_MoveData(s, &c->DesiredLogicState, 1, -1, 0);   //   16
    ReplaySnapshot_MoveData(s, &c->DesiredLogicSubState, 1, -1, 0);//   24
    ReplaySnapshot_EndNamedSection(s);
}

// Slot 32 of tPlayerCop's table: the base, the two selections each with
// its timer, and the light.
void tplayercop_do_snapshot(tPlayerCop *c, ReplaySnapshot *s)
{
    int32_t i;

    ReplaySnapshot_BeginSection(s, c, "tPlayerCop");
    tcop_do_snapshot(&c->Base, s);
    for (i = 0; i < 2; i++) {
        ReplaySnapshot_MoveInt(s, &c->nPrevSelection[i], 1);       //   32
        ReplaySnapshot_MoveFloat(s, &c->fPrevSelectionTimer[i]);   //   40
    }
    ReplaySnapshot_MoveBool(s, &c->bPrevCopLightState, 1);         //   48
    ReplaySnapshot_EndSection(s);
}

// Slot 32 of tAICop's table, in a section named "tCop" as the base's is:
// the base, the radar trap, the roadblock, the physics timers and the
// driving line, the offsets, RouteInfo through the route manager; a
// restore gives the radar trap its cop back. The hit grace timer last.
void taicop_do_snapshot(tAICop *c, ReplaySnapshot *s)
{
    TrackRouteManager *m = &TheTrackRouteManager;

    ReplaySnapshot_BeginSection(s, c, "tCop");
    tcop_do_snapshot(&c->Base, s);
    copmanager_do_speed_trap_pointer_snapshot(pCopManager, s,
                                              &c->pMySpeedTrap);   //   36
    ReplaySnapshot_MoveInt(s, &c->nMyRoadBlockIndex, 1);           //   40
    ReplaySnapshot_MoveFloat(s, &c->fSecondsInPhysicsMode);        //   84
    ReplaySnapshot_MoveFloat(s, &c->fMovementModeSwitchDelay);     //   88
    ReplaySnapshot_MoveInt(s, &c->nDrivingLineIndex, 4);           //   92
    ReplaySnapshot_MoveFloat(s, &c->fSubStateTimer);               //   44
    ReplaySnapshot_MoveFloat(s, &c->New48.x);                      //   48
    ReplaySnapshot_MoveFloat(s, &c->New48.y);                      //   52
    ReplaySnapshot_MoveFloat(s, &c->MyDLOffset.x);                 //   56
    ReplaySnapshot_MoveFloat(s, &c->MyDLOffset.y);                 //   60
    ReplaySnapshot_MoveFloat(s, &c->New64);                        //   64
    ReplaySnapshot_MoveFloat(s, &c->New68);                        //   68
    ReplaySnapshot_MoveFloat(s, &c->fFlankSide);                   //   72
    trmgr_do_route_pointer_snapshot(m, s, &c->RouteInfo.Route);    //   76
    trmgr_do_point_pointer_snapshot_in_route(m, s, &c->RouteInfo.Point,
                                             c->RouteInfo.Route);  //   80
    if (s->RestoringSnapshotFlag && c->pMySpeedTrap != NULL)
        c->pMySpeedTrap->cop = &c->Base;
    ReplaySnapshot_MoveFloat(s, &c->New32);                        //   32
    ReplaySnapshot_EndSection(s);
}
