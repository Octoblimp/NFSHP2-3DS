// fredrace -- FrontendDatabase's race start: StartSkipFEGame, StartRace,
// SetupCarsForRace and what they call.
//
// StartRace (0x00184f68) is where every race begins. The frontend's track
// select calls it, and so does a SkipFE boot through StartSkipFEGame
// (0x00184bd8), which fills TheRaceParameters from the SkipFE words first.
// It sets the boost scales and the AI count, builds the race's drivers
// (SetupCarsForRace: the players, the AI, the traffic and the cops, then
// the starting grid), copies the players' settings into TheRaceParameters
// and asks the game flow for the track.
//
// What StartRace and SetupCarsForRace do with TheRaceEvent (0x0031b600,
// raceevent.h) and the event trees goes through the seams at the bottom.
// Only GameTypes 4, 8 and 9 use the race event (UseTheRaceEvent), and only
// an event game's opponents (OpponentSelect 2) read a tree; the other game
// types touch none of it but four fields of TheRaceEvent.
//
// docs/formats/race-start.md has the decode.

#ifndef FREDRACE_H
#define FREDRACE_H

#include <stddef.h>
#include <stdint.h>

#include "car.h"
#include "fred.h"
#include "race.h"
#include "raceevent.h"

// --------------------------------------------------------- the game types

// 0x001841a8: GameTypes 4, 8 and 9 run off TheRaceEvent.
int32_t fred_use_the_race_event(const FrontendDatabase *f);

// 0x001855f0: GameTypes 3 to 7, the challenges.
int32_t fred_is_challenge_game(const FrontendDatabase *f);

// 0x00185618: GameTypes 8 and 9, the event trees.
int32_t fred_is_event_game(const FrontendDatabase *f);

// IsMultiTrack, 0x00184248: TheRaceParameters.RaceType 4 or 5, signed
// (`slti`). It reads nothing of the database.
static inline int32_t fred_is_multi_track(const FrontendDatabase *f)
{
    int32_t t = TheRaceParameters.RaceType;

    (void)f;
    return t < 6 && t >= 4;
}

// UseTreeEvent, 0x001841e8: GameTypes 8 and 9, an event tree's race. The
// image has it twice over, IsEventGame being the other.
static inline int32_t fred_use_tree_event(const FrontendDatabase *f)
{
    int32_t t = f->GameType;

    return t == 8 || t == 9;
}

// IsThereAnotherRace, 0x00184210: a race event's, and another race of it
// to come. fred_use_the_race_event is fredrace.c's, the second answer the
// seam's (gRaceEventIsThereAnotherRaceFn, below).
static inline int32_t fred_is_there_another_race(const FrontendDatabase *f);

// FrontendPlayerInfo::GetSelectedRideInfo, 0x00187af8: the ride the
// player picked for game type `gameType`, unchecked.
RideInfo *fpi_get_selected_ride_info(FrontendPlayerInfo *p, int32_t gameType);

// FrontendPlayerInfo::GetSelectedCarClass, 0x00187970: the class of the
// ride the player picked for the current game type (5 for a ride with no
// car, where the image reads before the table). Select Track's records
// ask it.
int32_t fpi_get_selected_car_class(FrontendPlayerInfo *p);

// --------------------------------------------------------- the drivers

// RideInfo::Init, 0x00187dd0.
void ride_info_init(RideInfo *r, int32_t type, int32_t skin, int32_t dash,
                    int32_t vertexDamage);

// DriverInfo's constructor, 0x00188610: the number, the type, a copy of
// the ride, the character and its CharacterInfo (GetCharacterInfo, NULL
// out of range), the skill and the starting position; not eliminated.
void driver_info_init(DriverInfo *d, int32_t unique, DriverType type,
                      const RideInfo *ride, int32_t character, int32_t skill,
                      int32_t startPos);

// CarTypeInfo::GetRandomSkin, retail 0x00188460. A cop's is GetSkinNumber's
// first; a car with no skins answers 0; the rest draw one of their skins
// with bRandom on bDefaultSeed. The demo's (cartypeinfo.h) drew on a seed
// of its own.
int32_t car_type_info_get_random_skin(const CarTypeInfo *ct);

// GenerateRandomRideInfo, 0x00188218. Among the cars of `usage` that have
// geometry and a skin, of class `carClass` unless it is -1, a draw weighted
// by each car's LocationProb for the race's location (GetLocationIndex):
// the ride's type, a random skin and its three flags 0. Answers 0, and
// leaves the ride, when the weights add up to 0.001 or less.
int32_t generate_random_ride_info(RideInfo *r, int32_t usage,
                                  int32_t carClass);

// 0x001840a0. The first number in list[0 .. n) that is not -1 and whose
// character fits `gender`: any for -1; else a body named "MALE" for 0 and
// any other body for 1. It is taken (set to -1) and answered; 0 when none
// fits.
int32_t pick_character_number_that_isnt_racing(int32_t *list, int32_t n,
                                               int32_t gender);

// 0x00185640. The number of the track's cop character, by the name hash in
// its TrackInfo, or "Cop" when that is 0; -1 when no character has it. The
// argument is not read: the track is TheRaceParameters'.
int32_t pick_cop_character_number(int32_t track);

// 0x00183ed0 and 0x00183f68: whether a driver still in the race has a car
// of this type, or one of this skin's PaintType (GetSkinInfo's, with the
// table's first skin standing in for one not found).
int32_t are_there_any_cars_of_type(int32_t type);
int32_t are_there_any_cars_of_colour(int32_t type, int32_t skin);

// 0x00184018. Up to a hundred random skins of `type`, until one's colour
// is not racing; the last one drawn either way.
int32_t pick_unused_skin(int32_t type);

// --------------------------------------------------------- the records

// HighScoreTable's indexes. GetUniqueTrackIndex (0x001868a0) is the
// track's HighScoreIndex, 0 for a track that is missing or not valid.
// GetUniqueLapIndex (0x001868d8) is the lap count's place in 1, 2, 3, 4, 5,
// 6, 7, 8 and 10, and 0 for any other. GetTotalTimesIndex (0x00186938)
// and GetLapTimesIndex (0x001869d0) put them together with the car class
// and whether the track is run backwards.
int32_t high_score_table_get_unique_track_index(int32_t track);
int32_t high_score_table_get_unique_lap_index(int32_t laps);
int32_t high_score_table_get_total_times_index(int32_t track,
                                               int32_t carClass,
                                               int32_t direction,
                                               int32_t laps);
int32_t high_score_table_get_lap_times_index(int32_t track, int32_t carClass,
                                             int32_t direction);

// FrontendDatabase::SetRecordTimesToBeat, 0x00184490: the player's
// settings in TheRaceParameters take the challenge table's best total time
// (only for a race with laps) and best lap for the track, the class of the
// player's car and the direction. 0x001842a8 does it for each player.
void fred_set_record_times_to_beat(FrontendDatabase *f, int32_t player);
void fred_set_all_record_times_to_beat(FrontendDatabase *f);

// --------------------------------------------------------- the race start

// 0x00185fe8. The players and AI racers with no starting position yet, by
// how quickly their cars pull away (the torque curve's peak over the mass,
// times first gear and the final drive, over the rear wheel's radius),
// each take the lowest position from 1 that no driver holds; 9 when 1 to
// 8 are all taken.
void fred_calculate_starting_positions(FrontendDatabase *f);

// 0x00185690. TheRaceParameters' drivers, rebuilt.
void fred_setup_cars_for_race(FrontendDatabase *f);

// 0x00184f68.
void fred_start_race(FrontendDatabase *f);

// 0x00184bd8. TheRaceParameters from the SkipFE words (configitems.h),
// then StartRace. retail's main (0x0012f000) calls it in place of
// ChangeGameFlow(LOADING_FRONTEND) when SkipFE is set.
void fred_start_skip_fe_game(FrontendDatabase *f);

// FrontendDatabase::SetupRaceParametersAfterRaceSetup, 0x001862b0: a
// challenge game's setup screen (GameTypes 3 to 7) into TheRaceParameters
// -- the AI count and the grid, the traffic, the catch-up, the opponents,
// the damage, the cops, the jump and zone cams, and Be A Cop's objective,
// clock and help. The game type, the two difficulties
// (ChallengeScreenData[3] and [4]) and the cams are the global Fred's; the
// players, the police switch and the setup data are `f`'s. Any other game
// type takes the defaults: no AI, minimum traffic, damage on. A traffic
// setting outside 0..3, which the image reads off its stack, is none.
void fred_setup_race_parameters_after_race_setup(FrontendDatabase *f);

// --------------------------------------------------------- the seams

// StartRace reads TheRaceEvent's type (nType) and its track count
// (nTracks) and writes the player count (nInitialPlayers) and bIsLastOpen;
// the end of the race (endgame.c) reads the event's number, its reward
// count and bIsLastOpen.

// The race event's calls, on TheRaceEvent. NULL answers 0 and does
// nothing.
//   SetupFakeRaceEventForChallengeKnockout  0x001849f0  (a FrontendDatabase
//                                                       method)
//   RaceEvent::GetStatus                    0x00202658
//   RaceEvent::ResetState                   0x00202698
//   RaceEvent::GetRaceIndex                 0x00202010
//   EventTrack::SetRace                     0x001fec20, on the event's
//                                           track `index`
//   0x00200598 on GetKoState (0x002018a0)   a player's starting position
//   UserRank on GetTournamentState          0x00200768, 0x00201880
//   0x00200f98 on the tree's current event  StartRace's event word; the
//                                           tree is GetEventTree's
//                                           (0x00185568), and a NULL tree
//                                           leaves the word 0
//   RaceEvent::DriverEliminated             0x00201708
//   GetRank on GetKoState, by               0x00200220, 0x00201558
//   RacerIndexFromDriverNumber
//   0x002022c0                              CalculateStartingPositions'
extern void (*gSetupFakeRaceEventForChallengeKnockoutFn)(FrontendDatabase *f);
extern int32_t (*gRaceEventGetStatusFn)(void);
extern void (*gRaceEventResetStateFn)(void);
extern int32_t (*gRaceEventGetRaceIndexFn)(void);
extern void (*gEventTrackSetRaceFn)(int32_t index, RaceParameters *rp);
extern int32_t (*gRaceEventKoStartPositionFn)(int32_t player);
extern int32_t (*gRaceEventTournamentUserRankFn)(void);
extern int32_t (*gFredEventWordFn)(FrontendDatabase *f);
extern int32_t (*gRaceEventDriverEliminatedFn)(int32_t number);
extern int32_t (*gRaceEventEliminatedRankFn)(int32_t number);
extern void (*gRaceEventStartingPositionsFn)(void);

// RaceEvent::IsThereAnotherRace (0x00202420) on TheRaceEvent: another race
// of the event to come.
extern int32_t (*gRaceEventIsThereAnotherRaceFn)(void);

static inline int32_t fred_is_there_another_race(const FrontendDatabase *f)
{
    return fred_use_the_race_event(f) && gRaceEventIsThereAnotherRaceFn != NULL
           && gRaceEventIsThereAnotherRaceFn() != 0;
}

// An event game's opponent `i` (OpponentSelect 2): the record GetEventTree,
// EventTree::GetEventNumber and the event's opponent table point at, four
// bytes -- the car type, the skin (below 0 for any unused one) and the
// skill. NULL, or a NULL answer, reads four zero bytes.
extern const uint8_t *(*gFredEventOpponentFn)(FrontendDatabase *f, int32_t i);

// MaybeSetSelectedCarForMultiTrackEvent (0x00184318), which runs only for
// an event tree's race (UseTreeEvent) and sets its EventInfo's car.
extern void (*gFredMaybeSetSelectedCarForMultiTrackEventFn)(FrontendDatabase *f);

// TheDemoModeReplay (0x002f0960): when its first word is set, StartRace
// restores the replay's RaceParameters snapshot and unloads its file.
extern void (*gDemoModeReplayStartRaceFn)(void);

// 0x001ff978, the count of the event trees' reward cars that are unlocked,
// for RaceParameters' New784. NULL answers 0.
extern int32_t (*gEventRewardCarsUnlockedFn)(void);

// CurrentGameFlowState (gp-21420) and ChangeGameFlow (0x001680d8), which
// StartRace asks for UNLOADING_FRONTEND from the frontend (state 3) and
// LOADING_TRACK_COMMON from anywhere else. NULL reads state 0 and changes
// nothing.
extern int32_t (*gFredGameFlowStateFn)(void);
extern void (*gFredChangeGameFlowFn)(int32_t state);

// The port's: a local wireless race's third to eighth players drive AI
// racers' cars (netrace.c, TASKS 37c). SetupCarsForRace asks it for AI
// racer `ai`'s ride first; nonzero means it wrote one into `ride`, which
// then takes the place of the one the AI would choose. NULL asks nothing,
// as retail.
extern int32_t (*gFredNetRideFn)(int32_t ai, RideInfo *ride);

#endif
