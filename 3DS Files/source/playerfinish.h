// playerfinish -- Player.obj from retail: the player's car crossing the
// finish.
//
//   Player::SetFinishedRacing   0x00176650   344 bytes (the demo's
//                                            0x001700d0, 276)
//
// Step 11g-2b, with raceupdate.c, whose Race::FinishCar calls it for a
// player's car. docs/formats/race-update.md has the decode.

#ifndef PLAYERFINISH_H
#define PLAYERFINISH_H

#include <stdint.h>

struct Player;

// Once per race: TimeFinishedRacing is WorldTimeFrames, and the finish
// animation 360 frames. When the car has done the race's laps:
//   - outside You're The Cop, a CrossFinishLine replay event worth 10, and
//     7.5 more for each other racing car within 30 m;
//   - with every player finished, the speech queue cleared;
//   - the finish line sound.
// A second call changes nothing.
void player_set_finished_racing(struct Player *p);

// --------------------------------------------------------------- the seams

// cSEDWedge::ClearEventQueue (0x00206190) on the wedge at gp-19016, when
// there is one. Task 26's speech. NULL clears nothing.
extern void (*gSpeechClearEventQueueFn)(void);

// TriggerFinishLineSound(Player *) (0x001afb38). NULL plays nothing.
extern void (*gTriggerFinishLineSoundFn)(struct Player *p);

#endif
