// racespeech -- the race's own speech, retail's RaceSpeech.obj (0x00206900
// .. 0x00207870): the announcer at the finish, after each lap, over the
// records, the rewards and an event's result, and Be A Cop's arrests.
//
// Each function adds one speech event (spch.h's spch_add_event_v) with its
// parameters as the speech library's bits; the sentences' rules pick on
// them. None is said in a replay: the coordinator's states 4, 5 and 7, or
// the replay demo. The race's own speech, at the finish and after a lap,
// is also kept out of time trials, the AI demo and a race of one car.
//
// What is ported, retail's addresses (SLES_507.31):
//
//   FlipCoinNoReplay                    0x00206900
//   WeDontWantToSayAnything             0x00206920
//   BustedByCops(TransientStatsElement*) 0x002069f0
//   BustedByCops(Car*)                  0x00206a00
//   SpecialLastPlaceSpeech              0x00206a30
//   RaceFinishedSpeech                  0x00206ab8
//   an event's result (no name)         0x00206bc8
//   OnePlayerLapSpeech                  0x00206d98
//   TwoPlayerLapSpeech                  0x00206eb8
//   LapKnockoutSpeech                   0x00207010
//   MaybeDoKnockoutRaceOverSpeech       0x00207018
//   LapRecordSpeech                     0x002070e8
//   LapFinishedSpeech                   0x00207198
//   GetTopTimeFlag                      0x00207270
//   PostGameLapRecord                   0x00207298
//   PostGameTimeRecord                  0x00207330
//   TournamentRaceSpeech                0x002073f0
//   an event's reward (no name)         0x00207450
//   RewardCarSpeech (no name)           0x00207488
//   a track's reward (no name)          0x00207550
//   PointsScreenSpeech                  0x002075b0
//   a pullover (no name)                0x002075d8
//   Be A Cop's arrests (no name)        0x00207648
//   PlayBustedSpeech                    0x002077b8
//   SingleP1OrP2, both                  0x002077e0, 0x00207810
//   PlayerSingleP1OrP2                  0x00207840
//
// SplitTimeSpeech (0x00207268) is empty and Race::Update's call to it is
// not ported. The conversions are speechconv.h's. RE-5 (14-10c);
// docs/formats/race-speech.md has the decode, and
// tools/racespeech_check.py runs retail's code against this.

#ifndef RACESPEECH_H
#define RACESPEECH_H

#include <stdint.h>

#include "fred.h"

struct Car;
struct Player;

// DuringRaceSpeech, type#3764, 16 bytes: the lap speech's four
// parameters, SPCH1Type_duringRaceTypeA to D. LapFinishedSpeech passes
// only TypeA.
typedef struct DuringRaceSpeech {
    uint32_t TypeA;                     //  0  the lap: start lap n
    uint32_t TypeB;                     //  4  two players' places
    uint32_t TypeC;                     //  8  two players' gap
    uint32_t TypeD;                     // 12  one player's place, last lap
} DuringRaceSpeech;

// 0x00206ab8, from Player::SetHudFeatures as the player's car finishes.
// Once per player: HasHeardRaceOverSpeech. Be A Cop says nothing. Busted
// is event 168; otherwise event 165 with the place (one player, player
// one or player two), or the last place's own. Knockouts say theirs
// elsewhere. `reason` is not read.
void race_finished_speech(struct Car *car, int32_t reason);

// 0x00207198, from Race::Update as a car completes lap `laps`: a lap
// record (event 164), or event 160 with DuringRaceSpeech's TypeA.
void lap_finished_speech(struct Car *car, int32_t laps);

// OnePlayerLapSpeech (0x00206d98) and TwoPlayerLapSpeech (0x00206eb8),
// lap_finished_speech's: `d`'s fields for the car's lap. One player: the
// last lap (TypeD), else on a coin's toss, or after lap 19, the place
// (TypeD) when the race has AI cars, else the lap (TypeA). Two players:
// the car's lead over the other in laps (TypeC) with no AI cars, its
// place (TypeB) with them. Only TypeA is ever said.
void one_player_lap_speech(DuringRaceSpeech *d, struct Car *car,
                           int32_t laps);
void two_player_lap_speech(DuringRaceSpeech *d, struct Car *car,
                           int32_t laps);

// 0x00207018, from Player::FillInRaceOverMessages: a knockout's out or
// through (event 169), once per player.
void maybe_do_knockout_race_over_speech(struct Player *p, int32_t advances);

// 0x00207298 and 0x00207330, from the Best Lap Times and Best Total
// Times screens: a record the player set (event 166), `place` 0 for the
// top. Not for a busted car, nor in an event tree's race the player did
// not win.
void post_game_lap_record(int32_t player, int32_t place,
                          TransientStatsElement *row);
void post_game_time_record(int32_t player, int32_t place,
                           TransientStatsElement *row);

// 0x002073f0, from the Tourney Standings: the place `n` from 0 after a
// race (event 165), or at the end, for the winner (event 167).
void tournament_race_speech(int32_t b, int32_t n);

// 0x00206bc8, from the event results screen: an event game's result for
// player `p`, with `row` its TransientStats row. Failed, event 168;
// won, event 216 or 217 with the event's number, once said first.
void race_event_speech(struct Player *p, TransientStatsElement *row);

// 0x00207450, from the event results screen: the event's reward, three
// bytes: 0 and a car type, or nonzero, a track and its direction. `p` is
// not read; nothing without `won` or a reward.
void race_event_reward_speech(struct Player *p, int32_t won,
                              const uint8_t *reward);

// 0x00207488: the car type a reward unlocked: event 150 for a cop car,
// 149 for a high-performance one (204 for types 21 and 22, whose bits are
// 128), else 147. 1 if said.
int32_t reward_car_speech(int32_t carType);

// 0x00207550: a track a reward unlocked (event 151). 1 if said.
int32_t reward_track_speech(int32_t track, int32_t direction);

// 0x002075b0, from ShowPointsResults: event 210 for a finish bonus.
void points_screen_speech(int32_t bonus);

// 0x002075d8, from tCopManager::CreatePullover: event 206.
void pullover_speech(void);

// 0x00207648, from Be A Cop's arrests and BeACopThink: event 213 with
// SPCH1Type_beCopFinishType. Two players: lost if `missed`, else player
// two or player one beat the speeder, by `winner`. One: the quota met,
// or missed with 0, 1 or 2 arrests, or lost.
void be_a_cop_arrest_speech(int32_t players, int32_t missed, int32_t winner,
                            int32_t arrests);

// 0x002077b8, from BeACopThink: event 214.
void play_busted_speech(void);

// RaceEvent's test at 0x00200c38 (no name) on TheRaceEvent: the player
// has won the event, by its type. NULL answers 0. RaceEvent::GetStatus is
// fredrace.h's gRaceEventGetStatusFn.
extern int32_t (*gRaceEventUserWonFn)(void);

#endif
