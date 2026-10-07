// quickrace -- the Mode Selects' Quick Race: StartQuickRace, the express
// game's track pick, and the track locks it reads.
//
// Quick Race is the first item on both Mode Selects. Retail's
// CopsOnModeSelect::HandleEvent (0x002170b0) and the cops-off one call
// StartQuickRace (0x00216c18) on a select from the first pad, with the
// transmission button's state the screen keeps at +628. StartQuickRace
// fills TheRaceParameters for one player against the AI on a random
// unlocked track, gives the player a random available car and calls
// FrontendDatabase::StartRace, which asks the game flow to leave the
// frontend for the track. There is no setup screen in between.
//
// Retail's is not the demo's (0x00203ae0, which bscreens.c carried until
// 11g-2): it starts from RaceParameters::InitWithDefaults, puts the player
// last on the grid (start position NumAICars + 1, the demo's 2 or 8),
// takes the time of day and the direction from the track pick, assigns the
// car, and starts the race.
//
// docs/formats/quick-race.md has the decode.

#ifndef QUICKRACE_H
#define QUICKRACE_H

#include <stdint.h>

// --------------------------------------------------------- the track locks

// The event trees, retail's bList at gp-16712, which LoaderEventTree
// (0x001ffc40) fills from FRONTB.BUN's chunk 0x80034a00, one tree a chunk.
// EventTree (0x001fd130 on) is not ported, so the list is the host's:
// gNumEventTrees trees, each asked by its place in the list through
// EventTree::TrackIsAReward (0x001ff6c8) and EventTree::IsTrackUnlocked
// (0x001ff5c8). NULL answers 0. The game has no trees until they are
// ported, so every track is unlocked; retail's FRONTB holds some back as
// the event trees' rewards.
extern int32_t gNumEventTrees;
extern int32_t (*gEventTreeTrackIsARewardFn)(int32_t tree, int32_t track,
                                             int32_t direction);
extern int32_t (*gEventTreeIsTrackUnlockedFn)(int32_t tree, int32_t track,
                                              int32_t direction);

// IsTrackAnEventReward, 0x001ffaa8: whether any tree has the track, run
// that way (eTrackDirection, 0 forwards and 1 backwards), as a reward.
int32_t is_track_an_event_reward(int32_t track, int32_t direction);

// EventTreeIsTrackUnlocked, 0x001ffb18: the first tree that has it as a
// reward answers whether it is unlocked there, 1 or 0; with none, 1.
int32_t event_tree_is_track_unlocked(int32_t track, int32_t direction);

// IsTrackUnlocked, 0x0024b760: an event reward is unlocked when its tree
// says so, and every other track is.
int32_t is_track_unlocked(int32_t track, int32_t direction);

// --------------------------------------------------------- the race

// The track PickTrackNumberForExpressGame answers: a node of its list,
// whose two links are dropped here.
typedef struct ExpressTrack {
    int32_t Track;                               //  8 in the node
    int32_t Direction;                           // 12  eTrackDirection
} ExpressTrack;

// 0x00216aa8. With TrackSelectedInConfigFile set (0 or more), that track
// forwards. Otherwise each track from 0 to HighestTrackNumber that
// GetTrackInfo has goes on a list once for each direction that
// IsTrackUnlocked allows, asked by its SameAsTrackNumber and listed by its
// TrackNumber, forwards before backwards; one is drawn with bRandom(int)
// on bDefaultSeed. With nothing unlocked the image's bRandom traps on its
// divide by 0; the port answers track 0 forwards.
void pick_track_number_for_express_game(ExpressTrack *out);

// FlailerScreenList::StopMovie (0x0016d0a0) on TheFlailerScreenList, the
// Mode Select's panel movie. NULL does nothing.
extern void (*gQuickRaceStopMovieFn)(void);

// StartQuickRace, 0x00216c18. `transmission` is the Mode Select's +628,
// whether the transmission button was down.
//
// RaceParameters::InitWithDefaults on TheRaceParameters, StopMovie, then
// with `cops` Fred.MainMenuOpts[1] (mPolice, read after the movie stops):
// Fred.GameType 2 (the express game) and one player car; the picked track,
// its direction, and its TimeOfDay and Point2Point from GetTrackInfo;
// cops ? 3 : 7 AI cars and the player one place behind them; traffic 0.33
// and 0.5; a single race of two laps for one player; MaxCops cops ? 4 : 0
// and two tickets before an arrest with cops; the tickets, road blocks,
// spike strips, helicopter and the word at 624 `cops` as read; no Be A Cop
// road blocks or choppers; cop strength, opponent strength and the boost 1
// with both scales 1.0; no event tree race, objective or training lines.
// Then MakeChallengeCarsAvailable and the player's car for GameType 2:
// with TrackSelectedInConfigFile set, DefaultPlayer1CarType made available
// with every skin and its dash and assigned with DefaultPlayer1SkinIndex;
// otherwise GenerateRandomRideInfo (racing, any class) until a car is
// CAR_STATUS_AVAILABLE, assigned with its skin. The transmission goes into
// the first player's settings, and StartRace runs on Fred.
void start_quick_race(int32_t transmission);

#endif
