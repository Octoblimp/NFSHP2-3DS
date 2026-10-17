// playersnap -- Player::DoSnapshot, retail's 0x00175db0: the player's part
// of a replay snapshot (TASKS 72d).
//
// A file of its own, as carsnap.c is the car's: it reaches the NIS
// manager, the speed average and SetInputMode, which player.c's checkers
// do not link. Each move names its field; the comments give retail's
// offset, which the port's Player keeps.
//
// Prototype: player.h. Cross-check: tools/racesnap_check.py. Write-up:
// docs/formats/replay.md.

#include "average.h"
#include "nismanager.h"
#include "player.h"
#include "playerinput.h"
#include "replay.h"

void player_do_snapshot(struct Player *p, ReplaySnapshot *s)
{
    ReplaySnapshot_BeginNamedSection(s, "Player");
    ReplaySnapshot_MoveInt(s, (int32_t *)&p->TimeFinishedRacing, 4);    //  80
    ReplaySnapshot_MoveInt(s, (int32_t *)&p->FinishAnimationLength, 2); //  84
    ReplaySnapshot_MoveInt(s, &p->nZoneCurrent, 1);                     //  88
    ReplaySnapshot_MoveData(s, p->nZoneCredits, 8, 8, 0);               //  96
    ReplaySnapshot_MoveData(s, p->tAutoZoneTimers, 32, -1, 0);          // 104
    ReplaySnapshot_MoveInt(s, &p->nGlueCount, 1);                       // 192
    average_do_snapshot(p->pAverageSpeedRatio, s);                      // 160
    ReplaySnapshot_MoveTimer(s, (int32_t *)&p->tAverageSpeedTimer);     // 164
    ReplaySnapshot_MoveFloat(s, &p->fMaxSpeedRatio);                    // 168
    ReplaySnapshot_MoveTimer(s, (int32_t *)&p->LastTimeCarInTrouble);   // 172
    ReplaySnapshot_MoveTimer(s, (int32_t *)&p->TimeToDisplayResetPrompt); // 176
    ReplaySnapshot_MoveFloat(s, &p->fTroubleSpeed);                     // 180
    ReplaySnapshot_MoveTimer(s, (int32_t *)&p->tTroubleSpeedTimer);     // 184
    ReplaySnapshot_MoveData(s, &p->DrivingControls, 4, -1, 0);          // 188
    ReplaySnapshot_MoveInt(s, &p->ArrestNisIndex, 4);                   // 232
    ReplaySnapshot_MoveInt(s, &p->TicketNisIndex, 4);                   // 236
    // The callback's address as four bytes, as the image has it: a replay
    // is only played back by the build that took it.
    ReplaySnapshot_MoveData(s, (void *)&p->NisFinishedCallback, 4, -1, 0); // 0
    ReplaySnapshot_MoveInt(s, (int32_t *)&p->NisFinishedCallbackParam, 4); // 240
    nismanager_do_snapshot(p->pNisManager, s);                          // 244
    ReplaySnapshot_MoveBool(s, &p->bWrongWay, 1);                       // 760
    ReplaySnapshot_MoveBool(s, &p->bLookBack, 1);                       // 764
    ReplaySnapshot_MoveBool(s, &p->bZoneMuffleSound, 1);                // 144
    if (s->RestoringSnapshotFlag)
        player_set_input_mode(p, 0);
    ReplaySnapshot_MoveFloat(s, &p->fFreezeZoneDelayTimer);             // 156
    ReplaySnapshot_EndNamedSection(s);
}
