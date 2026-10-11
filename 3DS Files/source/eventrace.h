// eventrace -- the races an event sets: EventTrack::SetRace and
// SetFromRace, EventTree::SetRace and the event's description with its
// $ tokens.
//
// When the player starts an event of a tree (tTreeDetails::StartEvent,
// 0x001f6a84), EventTree::SetRace copies the event into TheRaceEvent
// (raceevent.h) and sets TheRaceParameters for its type: the race type,
// the time to beat, the cops, the opponents and the objective's text.
// StartRace then puts the event's track for the race index into the race
// parameters through EventTrack::SetRace (fredrace.h's gEventTrackSetRaceFn).
//
// Retail has this in EventTree.obj: 0x001f5d58 .. 0x001f60e8 (the
// description) and 0x001fec20 .. 0x001ff360. docs/formats/event-race.md
// has the decode.

#ifndef EVENTRACE_H
#define EVENTRACE_H

#include <stdint.h>

#include "eventtree.h"
#include "race.h"
#include "raceevent.h"

// ---------------------------------------------------------- EventTrack

// An EventTrack's word: the track in the low byte, then the direction
// (bit 9), the weather (10..11), the time of day (12..13), the laps
// (14..17), the traffic's density (18..24, in hundredths) and its oncoming
// share (25..31, in hundredths).

// 0x001fec20: the track into the race parameters, and Point2Point from
// the track's TrackInfo when it has one.
void event_track_set_race(const EventTrack *t, RaceParameters *rp);

// 0x001fed30, which nothing in retail calls: the race parameters back
// into the word.
void event_track_set_from_race(EventTrack *t, const RaceParameters *rp);

// ---------------------------------------------------------- EventTree

// 0x001fee20: event `e` of `tree` into TheRaceEvent and `rp`. The tree's
// current event and Fred's nCurrentEvent become it; the state goes into
// aOldState; the reward's name and the objective's text are made; a race
// knockout or a tournament on its first race gets a new seed.
void event_tree_set_race(EventTree *tree, RaceParameters *rp,
                         EventInfo *e);

// ---------------------------------------------------- the description

// MapStringToEventToEventDescriptionToken, 8 bytes in retail: a token's
// id and its text. The table is 0x0031b200.
typedef struct EventDescriptionToken {
    int32_t     nId;
    const char *sName;
} EventDescriptionToken;

enum {
    EVENT_TOKEN_TARGET_TIME,           // $TARGET_TIME
    EVENT_TOKEN_NUM_LAPS,              // $NUM_LAPS
    EVENT_TOKEN_NUM_OPPONENTS,         // $NUM_OPPONENTS
    EVENT_TOKEN_NUM_RACES,             // $NUM_RACES
    EVENT_TOKEN_EVENTS_UNLOCKED,       // $EVENTS_UNLOCKED
    EVENT_TOKEN_COMPLETION_TIME,       // $COMPLETION_TIME
    EVENT_TOKEN_EVENT_UNLOCKED,        // $EVENT_UNLOCKED
    EVENT_TOKEN_TRACK_NAME,            // $TRACK_NAME
    EVENT_TOKEN_COUNT
};

extern const EventDescriptionToken gEventDescriptionTokens[EVENT_TOKEN_COUNT];

// 0x001f5d58: the first token whose text starts `src`, or NULL.
const EventDescriptionToken *get_event_description_token(const char *src);

// The longest text a token makes, with its NUL: retail's buffer is the 64
// bytes at the bottom of FormatEventDescription's frame.
#define EVENT_TOKEN_TEXT 64

// 0x001f5dd0: the token's text for event `e` of `tree` into `out`. An id
// past the table leaves `out` as it was.
void format_event_description_token(const EventTree *tree,
                                    const EventInfo *e,
                                    const EventDescriptionToken *tok,
                                    char *out);

// 0x001f5f88: `src` into `dst`, each token replaced by its text; at most
// n - 1 characters and the NUL. n <= 0 writes nothing.
void format_event_description(const EventTree *tree, const EventInfo *e,
                              const char *src, char *dst, int32_t n);

// --------------------------------------------------------- the seams

// GetTranslatedString(int) (0x0021e560); NULL, or a NULL answer, is the
// image's "NOT TRANSLATED PROPERLY".
extern const char *(*gEventRaceTranslateFn)(int32_t id);
// GetTranslatedString(const char *) (0x0021e508); NULL, or a NULL answer,
// is the text itself.
extern const char *(*gEventRaceTranslateStringFn)(const char *s);

#endif
