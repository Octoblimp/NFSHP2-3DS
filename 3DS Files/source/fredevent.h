// fredevent -- FrontendDatabase's event calls: the tree of the game type,
// the event select screen's choice, the cars an event offers, the car of a
// knockout or a tournament, the challenge knockout's fake event, StartRace's
// event word and SetupCarsForRace's event opponent; and the events a race
// opened, the list after TheRaceEvent.
//
// The career's two trees (eventtree.h) are game types 8 (the World
// Championship, the Championship tree) and 9 (Ultimate Road Racer, Hot
// Pursuit's). A challenge knockout (game type 4) has no tree: StartRace
// makes TheRaceEvent a knockout of its own, with the tracks picked at
// random or the setup's track for every race.
//
// Retail has this in FrontendDatabase.obj (0x00183d80 .. 0x00184bd0,
// 0x00185568 and FrontendPlayerInfo's 0x00187928), DataEventSelectScreen's
// three (0x001f5d00 .. 0x001f5d50) and the list's (0x001f72a8 ..
// 0x001f7458). docs/formats/fred-event.md has the decode.

#ifndef FREDEVENT_H
#define FREDEVENT_H

#include <stddef.h>
#include <stdint.h>

#include "eventtree.h"
#include "fred.h"
#include "raceevent.h"

// ------------------------------------------------------------- the tree

// GetEventTree, 0x00185568: game type 8's tree is "Championship", 9's "Hot
// Pursuit", each "... E3" under bVersionE3 (get_event_tree's lookup); any
// other game has none.
EventTree *fred_get_event_tree(const FrontendDatabase *f);

// DataEventSelectScreen, Fred's SelectedEventData: [0] the tree's type the
// mode select set (SetTreeType, 0x001f5d50: the Cops Off screen's 0, the
// Cops On screen's 1), [2] the event chosen in a tree of type 0 and [1] in
// one of type 1. GetSelectedEvent (0x001f5d00) answers by `type`, 1 for
// any other. SetSelectedEvent (0x001f5d28) goes by [0] and not by its
// `type`, which tEventTreeView passes as the tree's.
int32_t data_event_select_get_selected_event(const int32_t *d,
                                             int32_t type);
void data_event_select_set_selected_event(int32_t *d, int32_t type,
                                          int32_t n);
void data_event_select_set_tree_type(int32_t *d, int32_t type);

// ------------------------------------------------------------- the cars

// FrontendPlayerInfo::FlushAvailableCars, 0x00187928: every car hidden.
// The skins and the dash stay as they were.
void fpi_flush_available_cars(FrontendPlayerInfo *p);

// MakeEventCarsAvailable, 0x00183d80, tTreeDetails': both players' cars
// flushed, then each of the event's cars offered to both. A car's record in
// the tree's table is the type in byte 2, the skin in the low four bits of
// byte 3 (0 offers every skin) and the dash in bit 6 of byte 3.
void fred_make_event_cars_available(FrontendDatabase *f,
                                    const EventTree *tree,
                                    const EventInfo *e);

// MaybeSetSelectedCarForMultiTrackEvent, 0x00184318, StartRace's: in an
// event tree's race, the first player's ride is kept as the selected
// event's car (EventInfo::SetSelectedCar, for a knockout or a tournament).
void fred_maybe_set_selected_car_for_multi_track_event(FrontendDatabase *f);

// ContinueMultiTrackEvent, 0x001843e8, tTreeDetails': in an event tree's
// game, the first player gets the selected event's car back and the race
// starts.
void fred_continue_multi_track_event(FrontendDatabase *f);

// ------------------------------------------------- the challenge knockout

// PickRandomTracksForChallengeKnockout, 0x001846a0. Every track and
// direction that is unlocked (IsTrackUnlocked on the track's twin) goes on
// a list, which RandomizeList (0x00184578) shuffles with bRandom; the
// race's own track and direction go first (added when missing), and the
// knockout's races take the list in order: the track, its time of day and
// laps (1 point to point, else 2), the race's weather, direction and
// traffic.
void fred_pick_random_tracks_for_challenge_knockout(FrontendDatabase *f);

// SetupFakeRaceEventForChallengeKnockout, 0x001849f0, StartRace's for game
// type 4: TheRaceEvent a "Challenge Race Knockout" of the players and the
// AI less one races, its state its own aOldState, the objective a place of
// 3 or better. The race knockout setup's [5] picks the tracks: 0 at
// random, 1 the race's track for every race, any other leaves them.
void fred_setup_fake_race_event_for_challenge_knockout(FrontendDatabase *f);

// --------------------------------------------------------- the race's

// StartRace's event word (0x001850e0): IsLastOpen (0x00200f98) on the
// tree's current event, Fred's nCurrentEvent. 0 without a tree or event.
int32_t fred_event_word(FrontendDatabase *f);

// SetupCarsForRace's opponent `i` (0x00185a1c): the record in the tree's
// opponent table the current event's index points at. NULL without a tree,
// an event or a table.
const uint8_t *fred_event_opponent(FrontendDatabase *f, int32_t i);

// --------------------------------------------------- the events opened

// The events a race opened: up to four goals of the tree's events with the
// number of the event each opens (32 the Ultimate), filled by
// tTreeDetails::StartEvent (0x001f7480) and judged after the race.
typedef struct EventOpened {
    EventGoal Goal;                    //  0
    int32_t   nEvent;                  //  8
} EventOpened;                         // 12

typedef struct EventsOpened {
    EventOpened aEvents[4];            //  0
    int32_t     nCount;                // 48
} EventsOpened;                        // 52

typedef char eventsopened_layout_check[
    (sizeof(EventOpened) == 12 && offsetof(EventsOpened, nCount) == 48
     && sizeof(EventsOpened) == 52) ? 1 : -1];

// The list at 0x0031b7b0, the object after TheRaceEvent.
extern EventsOpened TheEventsOpened;

// 0x001f72a8: none. 0x001f72b0: the goal and the event's number added
// while there are fewer than four.
void events_opened_clear(EventsOpened *l);
void events_opened_add(EventsOpened *l, const EventGoal *g, int32_t n);

// 0x001f7398: the numbers of the events whose goal the event's state now
// passes (RaceEvent's GetStatus against the goal, 0x002025c8) into `out`,
// and how many. Retail does not read `max`; there are at most four.
// 0x001f7458: how many, ShouldSeeRewardScreen's (endgame.h's
// gRaceEventNumOpenedFn).
int32_t events_opened_passed(const EventsOpened *l, int32_t *out,
                             int32_t max, const RaceEvent *ev);
int32_t events_opened_num_passed(const EventsOpened *l,
                                 const RaceEvent *ev);

#endif
