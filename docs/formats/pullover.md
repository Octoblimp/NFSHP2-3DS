# Pullovers (step 12l-1)

A pullover is a car the cops have stopped. A chase makes one when it
catches its car ([pursuit](pursuit.md), tPursuit::Update and
IsChasedCarStoppable), and so does a spike strip that blows a car's
tires ([cops](cops.md)). A player caught by a chase gets a ticket or,
past the race's limit, an arrest, and watches its NIS
([nis](nis.md)). Everyone else is held a few seconds and let go. An
arrest ends the car's race.

This page covers tCopManager's CreatePullover and EndPullover, the NIS's
callback, GetArrestingOfficer and RemoveSpeedTrapsForCar, with the two
Player methods retail put among them. They are copmgr.obj's. The port
has them in `pullover.{c,h}`, and `tools/pullover_check.py` runs
retail's code against them. MonitorPullovers, which ends the pullovers
without a NIS, came with the cop manager's think
([cop-manager](cop-manager.md)).

| function | retail | port |
|---|---|---|
| tCopManager::CreatePullover(tPursuit *, Car *, bool) | `0x00226f30` | `copmanager_create_pullover` |
| tCopManager::EndPullover(int) | `0x00225878` | `copmanager_end_pullover` |
| EndPullover(int), the NIS's callback | `0x00225868` | `copmanager_end_pullover_callback` |
| tCopManager::GetArrestingOfficer(tPursuit *) | `0x00225c40` | `copmanager_get_arresting_officer` |
| tCopManager::RemoveSpeedTrapsForCar(Car *) | `0x00228538` | `copmanager_remove_speed_traps_for_car` |
| tAICop::DoneWritingTicket | `0x00230c58` | `taicop_done_writing_ticket` |
| Player::StopBustedDisplay | `0x00228f00` | `player_stop_busted_display` |
| Player::StartBustedDisplay | `0x00228f08` | `player_start_busted_display` |

## The record

The cop manager has one record per car, `CarPullovers[8]` at 88, indexed
by the car's CarIndex. Each record is 28 bytes (tCarPulloverInfo):

| offset | field | |
|---:|---|---|
| 0 | `nCopIndex` | the cop writing the ticket, or -1 |
| 4 | `fHoldTimer` | seconds left without a NIS |
| 8 | `nNumTickets` | a byte |
| 12 | `bActive` | |
| 16 | `bPlayNIS` | |
| 20 | `bArrest` | |
| 24 | `bShouldDisplayBustedText` | Be A Cop's BUSTED! |

A chase does not stop a car whose record is active
(IsChasedCarStoppable), and a car being pulled over is not chased.

## CreatePullover(pursuit, car, b)

A chase calls it with `b` 1. A spike strip calls it with no pursuit and
`b` 0. The car's record goes active, with no NIS and no BUSTED!.
`bArrest` keeps its old value. An AI racer is told to pull over within
3 s, or with no timeout (-1) when a pursuit caught it. Then, with `b`:

- **In Be A Cop** the cop is the player's. The racer plays the NIS if it
  is the last to be caught (the arrests made are one short of
  NumRacingCars - 1) or the race has two players. Any other racer shows
  BUSTED! on the cop's player instead.
- **Otherwise** a car with a player plays the NIS, with the arresting
  officer (GetArrestingOfficer).
- **An arrest:** when the tickets so far (pCopManager's record) are at
  nNumTicketsBeforeArrest or more, the pullover is an arrest. In Be A
  Cop that also scores the cop player's SCORING_SPEED_BUSTED. Elsewhere
  it applies unless the race is a free run.

With the NIS:

1. The speech queue is flushed. Then an arrest gets the racer-caught
   speech (the pursuit's cop, 4, and 1 at pursuit level 4, else 2), and
   a ticket gets the pull-over event.
2. An AI cop leaves the pursuit, goes to LS_CAUGHT_SPEEDER and becomes
   the record's cop.
3. Player::PlayNextNis runs with the cop's car, EndPullover's callback
   and the car's index.
4. The radar traps near the car are let go.
5. In Be A Cop, a car with a player loses its camera movers.

Without the NIS, a car a pursuit caught (`b`) gets the ticket speech.
The hold is 7 s, or 2 s with BUSTED!, and there is no cop.

Last, `b` counts a ticket in the manager's own record.

## EndPullover(i)

The NIS's end calls this for CarTable[i] through the callback, and so
does MonitorPullovers once a hold runs out. First:

1. The record goes inactive, and the car is not chased for 8 s.
2. Its radar traps wait 0.75 of GetBaseSpeedTrapSpawnTime.
3. Its tires are fixed. Retail's FixBlownTires (`0x00135120`) clears the
   rumble and both counts, nothing else.
4. A RealDriver's e-brake stop is cleared.
5. An AI cop on the record is done writing its ticket
   (DoneWritingTicket: LS_CAUGHT_SPEEDER, the waiting sub-state, and 10
   s on its timer).

Then:

- **An arrest.** One more arrest is made. An AI racer is told to pull
  over with no timeout, and the car finishes with RACING_CAR_ARRESTED,
  no longer blinking. In Be A Cop, a racer blinks out unless it was the
  last to be caught. A car with a player finishes as
  RACING_CAR_BE_THE_COP_LOST instead. Either of those two ends the race:
  the cop's car finishes too (RACING_CAR_BE_THE_COP_WON), with the
  arrests' speech and SCORING_QUOTA_FILLED. The arrested car leaves the
  map and its driver is no longer drawn.
- **A ticket.** An AI racer goes back to AIACTION_JUST_DRIVE and its
  boost is let go. A player's car is reset at the next route point,
  15 m/s on and blinking.

In Be A Cop, BUSTED! goes off the cop's player. Unless the car is the
cop's own, the cop car's lights and siren go off. Unless the race ended:

- the time limit starts again, when BeACopResetTimerAfterArrest is set;
- a car with a player has its damage and the cop car's reset.

## The others

- **GetArrestingOfficer(pursuit)** is the pursuit's first cop, or else
  its roadblock's first. Failing both, it is the first of the AI cops
  heading for a radar trap or a patrol; failing that, Cops[0].
- **RemoveSpeedTrapsForCar(car)** sends each AI cop heading for a radar
  trap back to limbo, unless a player's car not in a NIS is within 250 m
  of it. `car` only picks the timer: pCopManager's
  fSpeedTrapSpawnTimer for it starts again.
- **StartBustedDisplay** and **StopBustedDisplay** are the NIS
  overlay's StartBusted and Finish ([hud-nis](hud-nis.md)).

## Seams

`main.c` binds `gCopManagerCreatePulloverFn` (tPursuit::Update's, and
the spike strip's) and `gCopManagerEndPulloverFn` (MonitorPullovers').
CreatePullover reaches `gPlayerPlayNextNisFn`, bound since 12l-2. The
speech calls are step 14's and do nothing while NULL:

- `gSpeechRaiseRacerCaughtFn`, the speech manager's raiseRacerCaught
  (`0x0020ae00`);
- `gSpeechPulloverEventFn`, SPCH event 206 outside the replays
  (`0x002075d8`);
- `gSpeechBeACopArrestFn`, Be A Cop's arrests (`0x00207648`);
- `gPursuitAITicketSpeechFn`, tPursuit::AITicketSpeech (`0x0022b840`).

## The checks

`tools/pullover_check.py` runs the eight functions against retail's code
in mipsemu. It covers:

- GetArrestingOfficer's every source;
- RemoveSpeedTrapsForCar's range, cops and timer;
- the callback and the Busted display;
- CreatePullover's Be A Cop matrix, Hot Pursuit with and without a
  player, the tickets, the free run, the arresting officer, the managers
  told apart, and the timeouts;
- EndPullover's arrest matrix, the tickets, the record's cop, the cop
  car's own pullover, the lights and the time limit.

It runs 212,448 ops and 161,773 lines, 0 differ, and all 145 of its
mutations are caught.

On Azahar (2026-10-09), a chase that caught the stopped player made a
ticket. Its NIS played under the overlay, EndPullover put the car back
on the road blinking with one ticket, and the race went on.
