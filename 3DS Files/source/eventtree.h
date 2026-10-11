// eventtree -- the career's two event trees, Championship and Hot Pursuit:
// their events, what each event needs and gives, and the player's progress
// through them. EventTree.obj (0x001fd130 .. 0x00202cfc) without the 3D
// tree the frontend draws (BuildTree, the leaves, Update and Render, the
// view's neighbours), which goes with the tree's screen. The decode is
// docs/formats/event-tree.md; tools/eventtree_check.py runs retail's code
// against this.
//
// FRONTB.BUN holds one EventTree chunk (0x80034a00) per tree. Its children
// are the name (type 1), the cars (0x34a01, 4 bytes each), the tracks
// (0x34a02, 4), the goals (0x34a03, 8), the rewards (0x34a04, 8), the
// events (0x34a05, 188) and the opponents (0x34a06, 4). The tree points
// into the chunk; nothing is copied.
//
// An event's progress is a few bytes of Fred: ChampionshipState and
// HotPursuitState, 256 bytes each, which CalcStatePointers deals out. The
// 32nd event, the Ultimate, is shared: both trees point at the first
// tree's bytes, through Fred.pUltimateState.
//
// Where the port differs, none of it visible to the game:
// - An EventInfo's first two words are retail's pTree and pState
//   pointers. The record is the chunk's own, 188 bytes, so on a 64-bit
//   host the words cannot hold pointers. The port keeps a handle for the
//   tree (its slot in a small table, plus 1) and the state's offset from
//   &Fred; 0 is NULL in both. Fred.pUltimateState holds the same offset.
// - Retail's constructor stores a vector whose fourth word is whatever was
//   on its stack into vCenter. The port's is 0.
// - A tree whose name is neither tree's is deleted by the loader, which
//   then carries on writing the chunk's later children into the freed
//   tree. The port stops filling it. The disc's two names are both known.

#ifndef EVENTTREE_H
#define EVENTTREE_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"

// eEventType, an event's (and RaceEvent's) nType.
enum {
    EVENT_RACE = 0,
    EVENT_TIME_TRIAL = 1,
    EVENT_LAP_KNOCKOUT = 2,
    EVENT_RACE_KNOCKOUT = 3,
    EVENT_TOURNAMENT = 4,
    EVENT_POINT2POINT = 5,
    EVENT_BE_A_COP = 6
};

// eEventStatus.
enum {
    EVENT_LOCKED = 0,
    EVENT_UNTRIED = 1,
    EVENT_INPROGRESS = 2,
    EVENT_FAILED = 3,
    EVENT_PASSED = 4
};

// eRewardType, an EventReward's nType.
enum {
    REWARD_CAR = 0,
    REWARD_TRACK = 1
};

// EventTree's nType, which SetName sets from the name.
enum {
    EVENT_TREE_CHAMPIONSHIP = 0,
    EVENT_TREE_HOT_PURSUIT = 1
};

// The Ultimate event's number, the same in both trees.
#define EVENT_ULTIMATE 32

// The size of EventInfo in the chunk, and of each tree's state in Fred.
#define EVENT_INFO_SIZE 188
#define EVENT_TREE_STATE_SIZE 256

// An event's goal, 8 bytes: of type nType (eGoalType: 1 rank, 2 time, 3
// points), passed when event nEvent's status says so with nData.
typedef struct EventGoal {
    uint16_t nType;                //  0
    uint16_t nEvent;               //  2
    uint32_t nData;                //  4
} EventGoal;                       //  8

// An event's reward, 8 bytes in retail (the demo's 4 had no nData). A car
// (nType 0): nValue1 is the car type. A track (1): nValue1 the track,
// nValue2 its direction. nData is the result that earns it: the place, or
// the time, or the points rank.
typedef struct EventReward {
    uint8_t nType;                 //  0
    uint8_t nValue1;               //  1
    uint8_t nValue2;               //  2
    uint8_t nValue3;               //  3
    int32_t nData;                 //  4
} EventReward;                     //  8

// An event, 188 bytes, the chunk's record. The arrays index the tree's
// tables; only the first n of each are set, the rest is the tool's garbage.
// Bytes 45 .. 58 are SetRace's, which this slice does not reach.
typedef struct EventInfo {
    uint32_t TreeHandle;           //   0  retail's pTree (see above)
    uint32_t StateOffset;          //   4  retail's pState (see above)
    char     sName[32];            //   8
    int8_t   nNumber;              //  40  1 .. 32
    int8_t   nType;                //  41  eEventType
    int8_t   nClass;               //  42
    int8_t   nOpponentSelect;      //  43
    int8_t   nCops;                //  44
    uint8_t  pad45[3];             //  45
    int32_t  eCopStrength;         //  48
    uint8_t  Race52[7];            //  52  the cops' options, SetRace's
    int8_t   nCars;                //  59
    int8_t   nTracks;              //  60
    int8_t   nGoals;               //  61
    int8_t   nRewards;             //  62
    int8_t   nOpponents;           //  63
    int8_t   bZoneEnabled;         //  64
    uint8_t  pad65;                //  65
    int16_t  nObjective;           //  66  a goal of the tree
    int16_t  aCars[20];            //  68
    int16_t  aTracks[8];           // 108
    int16_t  aGoals[8];            // 124
    int16_t  aRewards[8];          // 140
    int16_t  aOpponents[7];        // 156
    uint8_t  pad170[2];            // 170
    float    fOpponentBoostScale;  // 172
    int32_t  mTitleString;         // 176  70000 + n
    int32_t  mDescriptionString;   // 180  70064 + n
    int32_t  New184;               // 184
} EventInfo;                       // 188

typedef char eventinfo_layout_check[
    (sizeof(EventInfo) == EVENT_INFO_SIZE
     && offsetof(EventInfo, nNumber) == 40
     && offsetof(EventInfo, nCars) == 59
     && offsetof(EventInfo, nObjective) == 66
     && offsetof(EventInfo, aCars) == 68
     && offsetof(EventInfo, aTracks) == 108
     && offsetof(EventInfo, aGoals) == 124
     && offsetof(EventInfo, aRewards) == 140
     && offsetof(EventInfo, aOpponents) == 156
     && offsetof(EventInfo, fOpponentBoostScale) == 172
     && offsetof(EventInfo, New184) == 184) ? 1 : -1];

// The view's leaf, of which this slice reads only the event (+4).
typedef struct EventLeaf {
    struct EventTree *pTree;       //  0
    EventInfo        *pInfo;       //  4
} EventLeaf;

// EventTree, 288 bytes in retail: a bTList node, the tables in the chunk,
// the events' state and the view's fields, which the constructor clears.
typedef struct EventTree {
    bNode        Node;                     //   0
    int32_t      nType;                    //   8
    char        *pName;                    //  12  bMalloc'd
    void        *pCameraMover;             //  16
    const uint8_t *pCars;                  //  20  EventCar, 4 bytes
    int32_t      nCars;                    //  24
    const uint8_t *pTracks;                //  28  EventTrack, 4 bytes
    int32_t      nTracks;                  //  32
    const EventGoal *pGoals;               //  36
    int32_t      nGoals;                   //  40
    const EventReward *pRewards;           //  44
    int32_t      nRewards;                 //  48
    const uint8_t *pOpponents;             //  52  EventOpponent, 4 bytes
    int32_t      nOpponents;               //  56
    EventInfo   *pEvents;                  //  60
    void        *pLeaves;                  //  64  BuildTree's
    int32_t      nEvents;                  //  68
    int32_t      nStateSize;               //  72
    void        *pPolys;                   //  76
    int32_t      nPolys;                   //  80
    void        *pLineTexture;             //  84
    EventLeaf   *pCurrentLeaf;             //  88
    EventInfo   *pCurrentEvent;            //  92
    float        vCenter[4];               //  96
    int32_t      bShowLines;               // 112
    int32_t      pad116[3];                // 116
    float        mNumberMatrix[16];        // 128
    float        mClassMatrix[16];         // 192
    void        *RaceTypeToTextureTable[8]; // 256
} EventTree;                               // 288

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char eventtree_layout_check[
    (offsetof(EventTree, pEvents) == 60
     && offsetof(EventTree, pCurrentLeaf) == 88
     && offsetof(EventTree, vCenter) == 96
     && offsetof(EventTree, mNumberMatrix) == 128
     && offsetof(EventTree, RaceTypeToTextureTable) == 256
     && sizeof(EventTree) == 288) ? 1 : -1];
#endif

// The trees, retail's bTList at gp-16712, in the loader's order.
extern bNode gEventTrees;

// gp-16700 and gp-16696: the Championship and Hot Pursuit trees, set by
// SetName, cleared by the unloader. gp-16704 is the unloader's too, and
// nothing reads it.
extern EventTree *gChampionshipTree;
extern EventTree *gHotPursuitTree;
extern EventTree *gEventTreeWord16704;

// UnlockAllEvents, gp-16720: every event passed. Nothing sets it.
extern int32_t gUnlockAllEvents;

// The seams are other modules': esolid.h's gGetTextureInfoFn (the
// constructor's race-type icons, NULL leaving them NULL), fred.h's
// gFredTranslateFn (GetTranslatedString, for GetFinishString; NULL gives
// ""), cartypeinfo.h's gCurrLanguageFn (the language Timer's printing
// takes; NULL is 0) and raceinit.h's gEggIsOnFn (egg 6 opens the
// Championship's 31st event, egg 7 Hot Pursuit's; NULL reads every egg
// off).

// The race-type icons' names, hashed by the module's static constructor
// into 0x0031b8f0: RACEICON, TIMETRIALICON, LAPKNOCKOUTICON,
// RACEKNOCKOUTICON, TOURNEYICON and POINT2POINTICON.
extern const char *const gEventTreeRaceTypeTextureNames[6];

// ------------------------------------------------------- the handles

// The tree of an event (NULL for none) and its state (NULL before
// CalcStatePointers), through the record's handle and offset.
EventTree *event_info_tree(const EventInfo *e);
uint8_t *event_info_state(const EventInfo *e);

// Fred.pUltimateState as a pointer, NULL while unset.
uint8_t *event_tree_ultimate_state(void);

// --------------------------------------------------------- the states

// EventRankState, 1 byte: the place, 0 untried. Reset 0x00200000, Unlock
// 0x00200008 (first), GetStatus 0x00200018 (untried, else passed when the
// place is at most the goal's nData, unsigned, else failed).
void rank_state_reset(uint8_t *s);
void rank_state_unlock(uint8_t *s, const EventGoal *goal);
int32_t rank_state_get_status(const uint8_t *s, const EventGoal *goal);

// EventTimeState, 4 bytes: the time, 0 or 0x7fffffff untried. Reset
// 0x00200048, Unlock 0x00200050 ((int)4000.5f, from gp-27800), GetStatus
// 0x00200068 (passed at or under the goal's nData, signed).
void time_state_reset(uint8_t *s);
void time_state_unlock(uint8_t *s, const EventGoal *goal);
int32_t time_state_get_status(const uint8_t *s, const EventGoal *goal);

// EventKoState, 16 bytes in retail (the demo's 8): +0 eight 4-bit ranks,
// each driver's place once out, 0 still in; +4 eight 4-bit start
// positions; +8 the car (int16), +10 its skin and +11 the dash (int8);
// +12 a seed.
void ko_state_reset(uint8_t *s);                            // 0x002000a8
void ko_state_unlock(uint8_t *s, const EventGoal *goal, int32_t n); // 0x002000b8
int32_t ko_state_get_race_index(const uint8_t *s);          // 0x002001a8
int32_t ko_state_get_rank(const uint8_t *s, int32_t i);     // 0x00200220
void ko_state_set_rank(uint8_t *s, int32_t i, int32_t rank); // 0x002002f8
int32_t ko_state_get_status(const uint8_t *s, const EventGoal *goal); // 0x002003f8
void ko_state_set_selected_car(uint8_t *s, int32_t car, int32_t skin,
                               int32_t dash);              // 0x00200468
void ko_state_get_selected_car(const uint8_t *s, int32_t *car,
                               int32_t *skin, int32_t *dash); // 0x00200478
void ko_state_set_start_position(uint8_t *s, int32_t i, int32_t pos); // 0x00200498
int32_t ko_state_get_start_position(const uint8_t *s, int32_t i);    // 0x00200598
uint32_t ko_state_get_seed(const uint8_t *s);               // 0x002002c0
void ko_state_new_seed(uint8_t *s);                         // 0x002002c8

// EventTournamentState, 16 bytes in retail (the demo's 12): +0 eight
// drivers' points, bytes; +8 the car, +10 skin, +11 dash; +12 a seed.
void tournament_state_reset(uint8_t *s);                    // 0x00200638
void tournament_state_unlock(uint8_t *s, const EventGoal *goal,
                             int32_t races);                // 0x00200668
int32_t tournament_state_get_race_index(const uint8_t *s,
                                        int32_t opponents); // 0x002006a0
int32_t tournament_state_racer_rank(const uint8_t *s, int32_t i); // 0x00200710
int32_t tournament_state_user_rank(const uint8_t *s);       // 0x00200768
int32_t tournament_state_points_for_finish_pos(int32_t pos); // 0x00200788
int32_t tournament_state_get_status(const uint8_t *s, const EventGoal *goal,
                                    int32_t races, int32_t opponents); // 0x002007d0
void tournament_state_set_selected_car(uint8_t *s, int32_t car,
                                       int32_t skin, int32_t dash); // 0x00200848
void tournament_state_get_selected_car(const uint8_t *s, int32_t *car,
                                       int32_t *skin, int32_t *dash); // 0x00200858
uint32_t tournament_state_get_seed(const uint8_t *s);       // 0x00200798
void tournament_state_new_seed(uint8_t *s);                 // 0x002007a0

// ---------------------------------------------------------- EventInfo

// The tables by the event's index, NULL outside 0 .. n-1: GetCar
// 0x00200878, GetGoal 0x002008b8, GetTrack 0x002008f8, GetReward
// 0x00200938, GetOpponent 0x00200978. GetObjective (0x002009b8) is the
// tree's goal nObjective, unchecked.
const uint8_t *event_info_get_car(const EventInfo *e, int32_t i);
const EventGoal *event_info_get_goal(const EventInfo *e, int32_t i);
const uint8_t *event_info_get_track(const EventInfo *e, int32_t i);
const EventReward *event_info_get_reward(const EventInfo *e, int32_t i);
const uint8_t *event_info_get_opponent(const EventInfo *e, int32_t i);
const EventGoal *event_info_get_objective(const EventInfo *e);

// The state by its kind, NULL for another type: the rank's (race, lap
// knockout; 0x00200d48), the tournament's (0x00200d70), the knockout's
// (0x00200d90) and the time's (time trial, point to point, Be A Cop;
// 0x00200db0).
uint8_t *event_info_rank_state(const EventInfo *e);
uint8_t *event_info_tournament_state(const EventInfo *e);
uint8_t *event_info_ko_state(const EventInfo *e);
uint8_t *event_info_time_state(const EventInfo *e);

// 0x002009d0: reward i is earned. 0 without the reward or with the event
// below failed; otherwise the result against the reward's nData.
int32_t event_info_reward_earned(const EventInfo *e, int32_t i);

// GetStateSize, 0x00200de8: 1, 4 or 16 by the type; 1 past 6.
int32_t event_info_get_state_size(const EventInfo *e);

// GetFinishString, 0x00200e78: the result in words into a static buffer,
// "" while below failed: the place's string (61000 + place, through a
// table of 16) or the time, Timer's way.
const char *event_info_get_finish_string(const EventInfo *e);

// 0x00200f98: the event is the last one left. Every event 1 .. 31 of both
// trees is passed but this one, Hot Pursuit's Ultimate is still locked,
// and this one is not passed. StartRace asks it.
int32_t event_info_is_last_open(const EventInfo *e);

// GetStatus, 0x002010b8, against `goal` (NULL: the event's own state).
// With goal NULL the event is locked until one of its goals is passed (the
// Ultimate: until every other event is), then the state against the
// objective. UnlockAllEvents makes everything passed; eggs 6 and 7 open
// the 31st events.
int32_t event_info_get_status(const EventInfo *e, const EventGoal *goal);

// GetRaceIndex 0x002012d8 (the knockout's or the tournament's, else 0),
// GetRaceCount 0x00201350 (opponents for a knockout, tracks for a
// tournament, else 1).
int32_t event_info_get_race_index(const EventInfo *e);
int32_t event_info_get_race_count(const EventInfo *e);

// ResetState 0x00201380 (untried), UnlockState 0x002013e0 (passed).
void event_info_reset_state(EventInfo *e);
void event_info_unlock_state(EventInfo *e);

// IsMultiTrack 0x00201468 (a race knockout or a tournament), and the
// selected car of those two (0x00201488, 0x002014b8).
int32_t event_info_is_multi_track(const EventInfo *e);
void event_info_set_selected_car(EventInfo *e, int32_t car, int32_t skin,
                                 int32_t dash);
void event_info_get_selected_car(const EventInfo *e, int32_t *car,
                                 int32_t *skin, int32_t *dash);

// EventGoal::Passed, 0x001fffb0: the goal's event, in the same tree,
// passes against the goal.
int32_t event_goal_passed(const EventGoal *g, const EventTree *tree);

// ---------------------------------------------------------- EventTree

// The constructor (0x001fd130) on a zeroed record, and the destructor
// (0x001fd250) with its flags (bit 0 frees it).
void event_tree_construct(EventTree *t, const char *name);
void event_tree_destruct(EventTree *t, int32_t flags);

// SetName, 0x001fdef8: copies the name. "Hot Pursuit" makes the tree
// type 1 and gHotPursuitTree; "Championship" type 0 and
// gChampionshipTree (each "... E3" under bVersionE3). 1 for either, 0
// for any other name or NULL.
int32_t event_tree_set_name(EventTree *t, const char *name);

// GetEventNumber 0x001fdfe8 (the event numbered n, or NULL), and
// GetEventIndex 0x001fe030 (its index, -1 for none).
EventInfo *event_tree_get_event_number(const EventTree *t, int32_t n);
int32_t event_tree_get_event_index(const EventTree *t, int32_t n);

// SetEvents, 0x001fff60: the chunk's events, size / 188 of them, each
// pointed back at the tree.
void event_tree_set_events(EventTree *t, void *events, int32_t size);

// CalcStatePointers, 0x001fe988: deals `state` out to the events, first
// those whose state is at least `align` bytes, each rounded up to it, then
// the rest packed. The Ultimate takes Fred.pUltimateState when it is set,
// and sets it otherwise.
void event_tree_calc_state_pointers(EventTree *t, uint8_t *state,
                                    int32_t size, int32_t align);

// ResetState 0x001feb50, UnlockState 0x001febb0 (every event's), and
// UnlockCurrentNode 0x001fec10 (the current leaf's event).
void event_tree_reset_state(EventTree *t);
void event_tree_unlock_state(EventTree *t);
void event_tree_unlock_current_node(EventTree *t);

// A car (reward type 0) or a track and direction (type 1) among the
// events' rewards. IsCarUnlocked (0x001ff360): the first such reward
// earned, 0 when none. CarIsAReward (0x001ff438). FindEventCarIsARewardFor
// (0x001ff500): its event. IsTrackUnlocked (0x001ff5c8): as the car's,
// but 1 when none. TrackIsAReward (0x001ff6c8), FindEventTrackIsARewardFor
// (0x001ff7c0).
int32_t event_tree_is_car_unlocked(const EventTree *t, int32_t car);
int32_t event_tree_car_is_a_reward(const EventTree *t, int32_t car);
EventInfo *event_tree_find_event_car_is_a_reward_for(const EventTree *t,
                                                     int32_t car);
int32_t event_tree_is_track_unlocked(const EventTree *t, int32_t track,
                                     int32_t direction);
int32_t event_tree_track_is_a_reward(const EventTree *t, int32_t track,
                                     int32_t direction);
EventInfo *event_tree_find_event_track_is_a_reward_for(const EventTree *t,
                                                       int32_t track,
                                                       int32_t direction);

// ------------------------------------------------------- over the trees

// IsCarAnEventReward 0x001ff8b8, EventTreeIsCarUnlocked 0x001ff918,
// FindEventThatCarIsARewardFor 0x001ff9d8, FindEventThatTrackIsARewardFor
// 0x001ffa38, IsTrackAnEventReward 0x001ffaa8 and EventTreeIsTrackUnlocked
// 0x001ffb18 (the first tree that has the track as a reward decides; 1
// when none has).
int32_t is_car_an_event_reward(int32_t car);
int32_t event_tree_is_car_unlocked_any(int32_t car);
EventInfo *find_event_that_car_is_a_reward_for(int32_t car);
EventInfo *find_event_that_track_is_a_reward_for(int32_t track,
                                                 int32_t direction);
int32_t is_track_an_event_reward(int32_t track, int32_t direction);
int32_t event_tree_is_track_unlocked_any(int32_t track, int32_t direction);

// 0x001ff978: how many of cars 0 .. 63 are an event's reward and earned.
int32_t event_trees_num_cars_unlocked(void);

// LockEvents 0x001ffbb0 and UnlockEvents 0x001ffbf8: every tree's state
// reset, or passed.
void lock_events(void);
void unlock_events(void);

// 0x002026f8: both trees' Ultimates are passed.
int32_t event_trees_both_ultimates_passed(void);

// GetEventTree(const char *), 0x001ffef8: the tree whose name bStrICmp
// matches, or NULL.
EventTree *get_event_tree(const char *name);

// LoaderEventTree 0x001ffc40 and UnloaderEventTree 0x001ffe80, on an
// EventTree chunk's header (0 for any other chunk, else 1). The loader
// links a new tree at the end of gEventTrees and points it into the chunk;
// the events' state comes from Fred by the tree's type. The unloader
// clears the three words and deletes every tree.
int loader_event_tree(uint8_t *chunk);
int unloader_event_tree(uint8_t *chunk);

#endif
