// playercop -- Be A Cop's player cop (12m-1): tPlayerCop's Think
// (0x0022d5c8), ChangeChaseTarget (0x0022d700) and SelectCarToChase
// (0x0022d898), from retail's cop.obj, and the horn's
// tCopManager::BeACopToggleSirenAndLights (0x002289b8), copmgr.obj's.
// With them the manager's BeACopThink (0x00227f30, 12m-2): Be A Cop's
// clock and its end, the dispatch's call, and the wrecked cars.
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
// the samples. main.c binds them to cop.c's, copmgr.c's and realdriver.c's
// seams.
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

// tCopManager::BeACopThink, 0x00227f30, the manager Think's last step in
// Be A Cop (copmgr.h's gCopManagerBeACopThinkFn). The player cop is
// Cops[nPlayerCopIndex]; the port returns without one.
//
// 1. In the fly-by of a race of two players, once (New10488),
//    PlayBustedSpeech.
// 2. In the pre-race, once (bBeACopAlreadySaidLookOutForSpeeders), the
//    dispatch's Be On Lookout at the landmark the cop's car is in (0 for
//    none). With two players the clock is set: the track's
//    TotalTimeAroundTrack, by 1 for a point to point or the laps, by 1.5.
// 3. Nothing more until the race clock (RaceTime) is above 0.
// 4. While the cop's car races (a racing car, not finished), with its
//    player, and no pullover active but its own car's slot: the clock
//    counts down by WorldTimeElapsed. At 0 or under it is 0, the car
//    finishes BE_THE_COP_LOST, the speech is the time-out's (players, 1,
//    2, arrests), the cop's chase is deleted and let go, and with two
//    players the speeder (CarTable[1]), unfinished, finishes the same.
// 5. Each car before CopCarPos whose fCarDamage is 1 or more: its
//    CarDamage wrecked (aborts while that is not ported); an AI racer
//    ForceBoosts 0.3, 0.4 or 0.5 by nDifficultyLevel; another player's car
//    (not the cop's) gets a damage boost of 0.75 and a traction boost of
//    1 - damage / 80.
// 6. With two players, the speeder (CarTable[1]) finished and the cop
//    (CarTable[0]) not: the cop finishes BE_THE_COP_LOST, the speech
//    (2, 0, 2, arrests).
void copmanager_be_a_cop_think(tCopManager *m);

#endif
