// raceevent -- RaceEvent, the event being raced: TheRaceEvent (0x0031b600).
//
// When the player starts an event of a tree (or a challenge knockout), the
// event's details are copied into TheRaceEvent (EventTree::SetRace, RE-6c),
// and its state, a few bytes of Fred (eventtree.h), is pointed at. The race
// then reads the event's type and counts, records each racer's finish into
// aResults, and the end of the race posts the results into the state,
// judges the state against the event's objective, and says whether a
// knockout or a tournament has another race.
//
// Retail has this in RaceEvent.obj: 0x00200ac8 .. 0x00200c38, 0x00200e30,
// 0x00201478 and 0x002014e8 .. 0x002026f0. TheRaceEvent is zeroed BSS with
// no constructor. docs/formats/race-event.md has the decode.

#ifndef RACEEVENT_H
#define RACEEVENT_H

#include <stddef.h>
#include <stdint.h>

#include "eventtree.h"
#include "race.h"

// --------------------------------------------------------- the records

// EventResult, 12 bytes: a racer's place, time and finish reason, by its
// racer index (RacerIndexFromDriverNumber).
typedef struct EventResult {
    int32_t nPosition;                 //  0  1 .. 8, 0 none
    Timer   Time;                      //  4
    int32_t nFinishReason;             //  8  the RacingCar's FinishReason
} EventResult;                         // 12

// EventTrack, 4 bytes: one of the event's tracks, which EventTrack::SetRace
// (0x001fec20, RE-6c) puts into TheRaceParameters.
typedef struct EventTrack {
    uint8_t b[4];
} EventTrack;

// RaceEvent, 432 bytes in retail (the demo's was 376: retail added
// aSavedState and the word at 120). pTree and pState are native pointers
// here; the layout check holds on the 3DS only.
typedef struct RaceEvent {
    EventTree   *pTree;                //   0
    uint8_t     *pState;               //   4  the event's state in Fred
    uint8_t      aOldState[16];        //   8  the state before the race
    uint8_t      aSavedState[16];      //  24  the state at the race's start
    char         sName[32];            //  40
    char         sRewardName[32];      //  72
    int16_t      nNumber;              // 104  the event's number, 1 .. 32
    int16_t      nType;                // 106  eEventType
    int16_t      nClass;               // 108
    int16_t      nCars;                // 110
    int16_t      nTracks;              // 112
    int16_t      nRewards;             // 114
    int16_t      nOpponents;           // 116
    int16_t      nInitialPlayers;      // 118  the players at its start
    int32_t      bIsLastOpen;          // 120  StartRace's, the one event left
    EventGoal    Objective;            // 124
    uint8_t      aCars[20][4];         // 132
    EventTrack   aTracks[8];           // 212
    EventReward  aRewards[8];          // 244
    uint8_t      aOpponents[7][4];     // 308
    EventResult  aResults[8];          // 336
} RaceEvent;                           // 432

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char raceevent_layout_check[
    (offsetof(RaceEvent, aOldState) == 8
     && offsetof(RaceEvent, sName) == 40
     && offsetof(RaceEvent, nNumber) == 104
     && offsetof(RaceEvent, nInitialPlayers) == 118
     && offsetof(RaceEvent, bIsLastOpen) == 120
     && offsetof(RaceEvent, Objective) == 124
     && offsetof(RaceEvent, aTracks) == 212
     && offsetof(RaceEvent, aRewards) == 244
     && offsetof(RaceEvent, aResults) == 336
     && sizeof(RaceEvent) == 432) ? 1 : -1];
#endif

extern RaceEvent TheRaceEvent;

// --------------------------------------------------------- the calls

// The event types fall into four groups in every one of retail's jump
// tables: rank (race 0, lap knockout 2), time (time trial 1, point to
// point 5, Be A Cop 6), knockout (race knockout 3) and tournament (4).
// Types 7 and up take each table's default.

// 0x00200e30: the state's size, 1, 4 or 16; 1 past the table.
int32_t raceevent_get_state_size(const RaceEvent *ev);

// 0x00201478: a knockout or a tournament, the events of several races.
int32_t raceevent_is_multi_track(const RaceEvent *ev);

// 0x002014f8: FrontendDatabase::RaceWasAborted on Fred.
int32_t raceevent_race_was_aborted(const RaceEvent *ev);

// 0x00201518: every result zeroed (EventResult::Reset, 0x002014e8).
void raceevent_reset_results(RaceEvent *ev);

// 0x00201558 and 0x00201578. The players are driver numbers 0 and 1 and the
// AI 100 on; the racer indexes put the AI after the event's first players.
int32_t raceevent_racer_index_from_driver_number(const RaceEvent *ev,
                                                 int32_t n);
int32_t raceevent_driver_number_from_racer_index(const RaceEvent *ev,
                                                 int32_t i);

// 0x00201598, Race::FinishCar's and NotifyTheRaceIsOver's. The racer's
// place, time (its best lap in a lap race, the cop's time in Be A Cop) and
// finish reason go into its result. The race is unused.
void raceevent_record_results(RaceEvent *ev, Race *race,
                              struct RacingCar *rc, int32_t pos);

// 0x00201668 and 0x00201698: the driver is in TheRaceParameters and not
// put out by a knockout.
int32_t raceevent_racer_in_the_race(const RaceEvent *ev, int32_t i);
int32_t raceevent_driver_in_the_race(const RaceEvent *ev, int32_t n);

// 0x002016d0 and 0x00201708: in a race knockout race (RaceType 4), the
// knockout state gives the racer a rank.
int32_t raceevent_racer_eliminated(const RaceEvent *ev, int32_t i);
int32_t raceevent_driver_eliminated(const RaceEvent *ev, int32_t n);

// 0x00201738 and 0x002017c8: the racer still in with the highest, or the
// lowest, place; 0 when none.
int32_t raceevent_get_last_place(const RaceEvent *ev);
int32_t raceevent_get_first_place(const RaceEvent *ev);

// 0x00201858, 0x00201880, 0x002018a0, 0x002018c0: pState when the type is
// of that group, else NULL.
uint8_t *raceevent_get_rank_state(const RaceEvent *ev);
uint8_t *raceevent_get_tournament_state(const RaceEvent *ev);
uint8_t *raceevent_get_ko_state(const RaceEvent *ev);
uint8_t *raceevent_get_time_state(const RaceEvent *ev);

// 0x002018f8, TheRaceIsOver's and TheRaceWasQuit's: the results into the
// state, unless the race was aborted.
void raceevent_post_results(RaceEvent *ev);

// 0x00201a80, TheRaceIsLeaving's: the state into aSavedState.
void raceevent_save_state(RaceEvent *ev);

// 0x00201ac0, TheRaceWasRestarted's: the state into aOldState, unless a
// knockout or tournament has another race, then aSavedState back.
void raceevent_cycle_results(RaceEvent *ev);

// 0x00201b38, the end game's: the event back to its first race.
void raceevent_restart(RaceEvent *ev);

// 0x00201bd8 and 0x00201db8: whether the race left the event's status
// worse, or better, than aOldState's.
int32_t raceevent_status_fell(const RaceEvent *ev);
int32_t raceevent_status_advanced(const RaceEvent *ev);

// 0x00201fb0: aOldState back into the state when the status fell.
void raceevent_keep_state(RaceEvent *ev);

// 0x00202010 and 0x00202088: a knockout's or a tournament's race so far
// and races in all; 0 and 1 for the rest.
int32_t raceevent_get_race_index(const RaceEvent *ev);
int32_t raceevent_get_race_count(const RaceEvent *ev);

// 0x002020b8, FrontendDatabase::SetupNextRace's: the next race of a
// knockout or a tournament set up, or 0 when there is none.
int32_t raceevent_setup_next_race(RaceEvent *ev);

// 0x002022c0: the grid by the last race's places (a knockout) or the
// points (a tournament); 0 on the first race and for other types.
int32_t raceevent_calc_starting_positions(RaceEvent *ev);

// 0x00202420.
int32_t raceevent_is_there_another_race(const RaceEvent *ev);

// 0x00202528: `state` judged against the objective. 0x002025c8: the state
// judged against `goal`. 0x00202658 and 0x00202678: the state, and
// aOldState, against the objective. A NULL state reads as zeros.
int32_t raceevent_get_status_of(const RaceEvent *ev, const uint8_t *state);
int32_t raceevent_get_status_goal(const RaceEvent *ev,
                                  const EventGoal *goal);
int32_t raceevent_get_status(const RaceEvent *ev);
int32_t raceevent_get_old_status(const RaceEvent *ev);

// 0x00202698.
void raceevent_reset_state(RaceEvent *ev);

// 0x00200b30: reward `i` earned by `state` (NULL: the event's state).
// 0x00200ac8: any reward earned by the event's state.
int32_t raceevent_reward_earned(const RaceEvent *ev, int32_t i,
                                const uint8_t *state);
int32_t raceevent_any_reward_earned(const RaceEvent *ev);

// 0x00200c38: the player won the event outright.
int32_t raceevent_user_won(const RaceEvent *ev);

// --------------------------------------------------------- the seams

// EventTrack::SetRace (0x001fec20), RE-6c's. NULL does nothing.
extern void (*gEventTrackSetRaceOnFn)(const EventTrack *t,
                                      RaceParameters *rp);

#endif
