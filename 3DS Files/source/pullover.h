// pullover -- a car pulled over by the cops: tCopManager's CreatePullover
// (0x00226f30), EndPullover (0x00225878) and the NIS's callback to it
// (0x00225868), GetArrestingOfficer (0x00225c40) and
// RemoveSpeedTrapsForCar (0x00228538), with the two Player methods
// retail put among them, StartBustedDisplay (0x00228f08) and
// StopBustedDisplay (0x00228f00). They are copmgr.obj's, here with the
// pullover they make and end.
//
// A pursuit that stops its car (tPursuit::Update) calls CreatePullover with
// `b` 1, and a spike strip's blown tires (spikestrip.c) with no pursuit and
// `b` 0. The car's CarPullovers entry goes active. A player caught by a
// pursuit plays the ticket's or the arrest's NIS (Player::PlayNextNis),
// whose end calls EndPullover; everyone else is held for 7 s, or 2 s
// behind Be A Cop's BUSTED!, and MonitorPullovers (copmgr.c) ends it.
// The tickets count up with each `b`, and at TheRaceParameters'
// nNumTicketsBeforeArrest the pullover is an arrest: EndPullover then
// finishes the car's race (Race::FinishCar, RACING_CAR_ARRESTED). A ticket
// puts a player back on the road at the next route point and lets an AI
// racer drive on.
//
// docs/formats/pullover.md has the write-up; tools/pullover_check.py runs
// retail's code against this file.

#ifndef PULLOVER_H
#define PULLOVER_H

#include <stdint.h>

#include "copmanager.h"

struct Car;
struct Player;

// tCopManager::CreatePullover(tPursuit *, Car *, bool), 0x00226f30. The
// entry of the car's CarIndex goes active, with no NIS and no BUSTED!;
// bArrest is left as it was. An AI racer is told to pull over within 3 s,
// or with no timeout (-1) when a pursuit caught it. Then, with `b`:
//   - In Be A Cop the cop is the player's. The last racer to catch (the
//     arrests made one short of NumRacingCars - 1) or a two-player race
//     plays the NIS; any other shows BUSTED! on the cop's player.
//   - Otherwise a car with a player plays the NIS with the arresting
//     officer (GetArrestingOfficer).
//   - The tickets so far (pCopManager's entry), at
//     nNumTicketsBeforeArrest or more, make it an arrest: in Be A Cop,
//     with the cop player's SCORING_SPEED_BUSTED; elsewhere unless the
//     race is a free run.
// With the NIS: the speech queue flushed, then the racer-caught speech
// (with the pursuit's cop, 4, and 1 at pursuit level 4 else 2) for an
// arrest, or the pull-over event. An AI cop leaves the pursuit, goes to
// LS_CAUGHT_SPEEDER and is the entry's cop. Then Player::PlayNextNis with
// the cop's car, EndPullover's callback and the index; the radar traps the
// car is near are let go; and in Be A Cop a car with a player loses its
// camera movers. Without the NIS: a pursuit's caught car (`b`) gets the
// ticket speech, the hold is 7 s (2 s with BUSTED!) and there is no cop.
// Last, `b` counts a ticket (the manager's own entry, a byte).
void copmanager_create_pullover(tCopManager *m, tPursuit *p,
                                struct Car *car, int32_t b);

// tCopManager::EndPullover(int), 0x00225878, for CarTable[i]. The entry
// goes inactive, the car is not to be chased for 8 s, its radar traps wait
// 0.75 of GetBaseSpeedTrapSpawnTime, its tires are fixed (retail's
// FixBlownTires, 0x00135120: the rumble and both counts, nothing else) and
// a RealDriver's e-brake stop is cleared. An AI cop on the entry is done
// writing its ticket. Then:
//   - An arrest: one more arrest made; an AI racer told to pull over with
//     no timeout; the car finished with RACING_CAR_ARRESTED, unblinked.
//     In Be A Cop a racer blinks out, unless it was the last to catch
//     (the arrests made reach NumRacingCars - 1); a car with a player
//     finishes as RACING_CAR_BE_THE_COP_LOST instead. Either of those two
//     ends the race: the cop's car finishes too (RACING_CAR_BE_THE_COP_WON)
//     with the arrests' speech and SCORING_QUOTA_FILLED. The car leaves the
//     map and its driver is no longer drawn.
//   - A ticket: an AI racer back to AIACTION_JUST_DRIVE and its boost
//     released; a player's car reset 15 m/s on at the next route point,
//     blinking.
// In Be A Cop BUSTED! goes off the cop's player. Unless the car is the
// cop's own, the cop car's lights and siren go off, and unless the race
// ended, the time limit starts again (when BeACopResetTimerAfterArrest is
// set) and a car with a player has its and the cop car's damage reset.
void copmanager_end_pullover(tCopManager *m, int32_t i);

// EndPullover(int), 0x00225868: the NIS's callback, EndPullover on
// pCopManager.
void copmanager_end_pullover_callback(int32_t i);

// tCopManager::GetArrestingOfficer(tPursuit *), 0x00225c40: the pursuit's
// first cop, else its roadblock's first; else the first of the AI cops
// (nNumAICops of them) heading for a radar trap or a patrol; else Cops[0].
tCop *copmanager_get_arresting_officer(tCopManager *m, tPursuit *p);

// tCopManager::RemoveSpeedTrapsForCar(Car *), 0x00228538. Each AI cop
// heading for a radar trap goes back to limbo unless a player's car not
// in a NIS is within 250 m of it. `car` only names the timer:
// pCopManager's fSpeedTrapSpawnTimer for it starts again.
void copmanager_remove_speed_traps_for_car(tCopManager *m, struct Car *car);

// tAICop::DoneWritingTicket, 0x00230c58, cop.obj's but EndPullover's
// alone: unless disabled, to LS_CAUGHT_SPEEDER (asked for only when it is
// not already), LogicSubState LSS_CAUGHTSPEEDER_WAITING (the current
// sub-state, not the desired one) and fSubStateTimer 10 s.
struct tAICop;
void taicop_done_writing_ticket(struct tAICop *c);

// Player::StartBustedDisplay (0x00228f08) and StopBustedDisplay
// (0x00228f00): the flailer NIS overlay's StartBusted and Finish.
void player_start_busted_display(struct Player *p);
void player_stop_busted_display(struct Player *p);

// What these reach elsewhere. NULL does nothing.
//   - Player::PlayNextNis (0x00176308), playernis.h: the NIS for the
//     caught car, which calls `done` with `param` when it ends. Its 1 is
//     not read.
//   - The speech manager's raiseRacerCaught (0x0020ae00, the speaker, 4
//     and the arrest type), 0x002075d8 (SPCH event 206 outside the
//     replays), 0x00207648 (Be A Cop's arrests: NumPlayerCars, 0, 1 and
//     the count) and tPursuit::AITicketSpeech (0x0022b840), step 14.
extern int32_t (*gPlayerPlayNextNisFn)(struct Player *pl, struct Car *car,
                                       struct Car *cop,
                                       void (*done)(int32_t), int32_t param);
extern void (*gSpeechRaiseRacerCaughtFn)(uint32_t speaker, uint32_t n,
                                         int32_t arrestType);
extern void (*gSpeechPulloverEventFn)(void);
extern void (*gSpeechBeACopArrestFn)(int32_t players, int32_t a,
                                     int32_t b, int32_t arrests);
extern void (*gPursuitAITicketSpeechFn)(tPursuit *p);

#endif
