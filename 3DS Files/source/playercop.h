// playercop -- Be A Cop's player cop (12m-1): tPlayerCop's Think
// (0x0022d5c8), ChangeChaseTarget (0x0022d700) and SelectCarToChase
// (0x0022d898), from retail's cop.obj, and the horn's
// tCopManager::BeACopToggleSirenAndLights (0x002289b8), copmgr.obj's.
//
// The player's car is the cop's. The horn picks the speeder to chase: the
// nearest car ahead within 175 m (or any within 20 m), the last two picks
// held back for five seconds, so pressing again moves on to the next car.
// The first pick asks for a pursuit; a new pick turns the pursuit on it;
// the same pick again plays "BeACopRequestFailed". With nothing to chase
// and no pursuit the horn turns the lights on and off. Think keeps the
// lights and siren with the chase, and lets a helicopter go that has fired
// four salvos.
//
// They sit apart from cop.c, whose harness does not link the speech and
// the samples. main.c binds them to cop.c's and realdriver.c's seams.
//
// Cross-check: tools/playercop_check.py. Write-up: docs/formats/cops.md,
// "Be A Cop's player cop".

#ifndef PLAYERCOP_H
#define PLAYERCOP_H

#include "cop.h"
#include "copmanager.h"

struct Car;

// Think, 0x0022d5c8. With the car's player and no NIS playing, both
// held-back picks' timers count down by WorldTimeElapsed; one at 0 or
// under lets its pick go (-1). Then with a pursuit the car's siren is
// mode 1 and its lights 2 (fast); with no pursuit but a car pulled over
// (any of the manager's CarPullovers, up to the World's CopCarPos, active)
// the siren is off and the lights 2; else they stay. A pursuit's
// helicopter that has fired four salvos or more is let go.
void tplayercop_think(tPlayerCop *c);

// ChangeChaseTarget, 0x0022d700: the horn's, in a race that is racing.
// Nothing with no player or with a NIS playing. Else the pick
// (SelectCarToChase): with no pursuit RequestPursuit asks for one on it;
// a pursuit of another car turns to it (tPursuit's change of target,
// pursuitspeech.h); a pursuit of the same car plays BeACopRequestFailed
// (1.0, 0, 0). No pick and no pursuit turns the lights from off to 1 and
// from anything else to off, as a word.
void tplayercop_change_chase_target(tPlayerCop *c);

// SelectCarToChase, 0x0022d898. Each car before the World's CopCarPos
// that is not the cop's own, not blinking and not finished scores
// 185 - d, d its distance in x and y, when it is within 20 m in z, closer
// than 175 m and ahead (Car::IsCarInFront within 10000 BAM), or else
// closer than 20 m; the rest -1. The last pick's score, if it has one,
// becomes 0 and the one before's 5. The best score above -1 (the first
// of equals) is the pick: the last pick moves back with its timer, and
// the new one is held for 5 s. NULL when no car scores.
struct Car *tplayercop_select_car_to_chase(tPlayerCop *c);

// tCopManager::BeACopToggleSirenAndLights, 0x002289b8: the player cop's
// ChangeChaseTarget while pCurrentRace is RACE_STAGE_RACING. Retail
// passes NULL when there is no player cop, and the port does nothing.
void copmanager_be_a_cop_toggle_siren_and_lights(tCopManager *m);

#endif
