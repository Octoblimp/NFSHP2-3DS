// endevent -- the career's screens in the end-game list: the Tourney
// Standings after a tournament's race, the events a race opened, the
// event's result and its reward, and the two You're The Cop results.
//
// Tourney Standings lists every racing car by its rank in the
// tournament's points: its place, its driver, its car, the points this
// race gave and its total, in the player's colour for a player. The first
// player's row says the tournament speech once per list.
//
// Events Unlocked says which events of an event tree the race opened, by
// number. The Reward menu (retail's EventRewardScreen) says whether the
// event was passed or failed, with a blurb for how and the reward it
// earned, and the speech for both once per list.
//
// Be The Cop Results 1P has the pursuit's points: the time left over and
// its bonus when the cop won, what the race gave and the total. Be The Cop
// Results 2P says who won the split-screen pursuit and each side's points.
//
// Every class is 8 bytes, an EndGameMenusBase whose vtable has the base's
// HandleEvent and nothing else of its own but the destructor.
//
// What is ported, retail's addresses (SLES_507.31):
//
//   TourneyStandingsScreen::TourneyStandingsScreen   0x001dd5d0
//   the tourney points' order                        0x001dd5c0
//   the reward screen's blurb id                     0x001de788
//   the player's place in the event                  0x001dea88
//   the reward screen's blurb                        0x001dead8
//   EventRewardScreen::EventRewardScreen             0x001def38
//   EventsUnlockedScreen::EventsUnlockedScreen       0x001df180
//   BeTheCopResults1P::BeTheCopResults1P             0x001e0898
//   BeTheCopResults2P::BeTheCopResults2P             0x001e0a10
//   BeTheCopResults2P::Render                        0x001e0bc8 (empty)
//   the destructors                                  0x001e2340,
//                                                    0x001e2358,
//                                                    0x001e23a0,
//                                                    0x001e24f8,
//                                                    0x001e2510
//
// Slice RE-6d. docs/formats/end-event.md has the decode.

#ifndef ENDEVENT_H
#define ENDEVENT_H

#include <stdint.h>

#include "blist.h"
#include "bmenu.h"
#include "car.h"
#include "endgame.h"

// TOURNEY_STANDINGS' rows: each row n (1 to 8) has POS_n, NAME_n, TYPE_n,
// RACE_n and TOTAL_n, by SprintfAndHash. The track's name and the race's
// number are Race Results' (endresults.h's).
#define TOURNEY_ROWS                 8

// The reward screens' title (endresults.h's END_REWARD_OBJ_TITLE) for an
// event passed and failed, "EVENT %d PASSED" and "EVENT %d FAILED", and
// Events Unlocked's, "EVENTS UNLOCKED".
#define END_EVENT_LANG_PASSED        0xde4a4
#define END_EVENT_LANG_FAILED        0xde4a5
#define END_EVENT_LANG_UNLOCKED      0xde2b6

// The You're The Cop screens' objects. 1P: the group with the time left
// and its bonus, the time left, the bonus, the race's points, the race's
// points with the bonus, and the career's.
#define BTC_GROUP_TIME_BONUS         0x8564c282u
#define BTC_OBJ_TIME_LEFT            0x761c6807u
#define BTC_OBJ_TIME_BONUS           0xc8f86ae5u
#define BTC_OBJ_POINTS               0xd49e65d2u
#define BTC_OBJ_POINTS_EARNED        0x98fcdd99u
#define BTC_OBJ_POINTS_TOTAL         0xb8b4361bu
// 2P: the two players' blurbs and points.
#define BTC_GROUP_P1_BLURB           0xfe6b3c76u
#define BTC_GROUP_P2_BLURB           0x4b657937u
#define BTC_OBJ_P1_POINTS            0x89e0e2dbu
#define BTC_OBJ_P2_POINTS            0x89e0e2dcu

// The time left is worth 100 points a second.
#define BTC_TIME_BONUS_PER_SECOND    100

// TourneyPoints, 20 bytes, bMalloc(20, "TourneyPoints", 0, 16): a racing
// car, its points in the tournament and its rank in them.
typedef struct TourneyPoints {
    bNode             Node;    //  0
    struct RacingCar *Car;     //  8
    int32_t           Points;  // 12
    int32_t           Rank;    // 16
} TourneyPoints;               // 20

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char tourneypoints_layout_check[
    (sizeof(TourneyPoints) == 20) ? 1 : -1];
#endif

extern const EndGameMenusVTable kTourneyStandingsVTable;  // 0x002b9028
extern const EndGameMenusVTable kEventRewardVTable;       // 0x002b9088
extern const EndGameMenusVTable kEventsUnlockedVTable;    // 0x002b90b8
extern const EndGameMenusVTable kBTCResults1PVTable;      // 0x002b8f98
extern const EndGameMenusVTable kBTCResults2PVTable;      // 0x002b8f68

// The constructors, gEndGameScreenCtorFns' shape; `data` is not read.
EndGameMenusBase *tourney_standings_construct(void *mem, uint32_t hash,
                                              BScreenCallbackData *data);
EndGameMenusBase *event_reward_construct(void *mem, uint32_t hash,
                                         BScreenCallbackData *data);
EndGameMenusBase *events_unlocked_construct(void *mem, uint32_t hash,
                                            BScreenCallbackData *data);
EndGameMenusBase *btc_results_1p_construct(void *mem, uint32_t hash,
                                           BScreenCallbackData *data);
EndGameMenusBase *btc_results_2p_construct(void *mem, uint32_t hash,
                                           BScreenCallbackData *data);
void tourney_standings_destroy(EndGameMenusBase *m, int32_t flags);
void event_reward_destroy(EndGameMenusBase *m, int32_t flags);
void events_unlocked_destroy(EndGameMenusBase *m, int32_t flags);
void btc_results_1p_destroy(EndGameMenusBase *m, int32_t flags);
void btc_results_2p_destroy(EndGameMenusBase *m, int32_t flags);

// The Reward menu's blurb: the LanguageID for the event's result
// (0x001de788) and the blurb made from it into `out`, 256 bytes
// (0x001dead8). The player's place: the tournament's rank in points, or
// where `driver` finished (0x001dea88); every call asks for driver 0.
int32_t event_reward_lang_id(void);
void event_reward_format(char *out, int32_t id);
int32_t event_reward_user_rank(int32_t driver);

#endif
