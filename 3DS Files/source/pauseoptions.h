// pauseoptions -- the screens the pause menu leads to: retail's PAUSE_MAIN
// module from 0x001710f8 to 0x00173e30, and the three Player and pause
// calls they make.
//
//   Pause Options        PAUSE_OPTIONS (0x2b5a03a8): Audio and Display
//                        lead on; Damage, Handling, Transmission, Jump
//                        Cams and Zone Cams change with Left and Right, at
//                        once, for the race being driven
//   Pause audio          PAUSE_AUDIO (0x6b321e4e): five sliders (racing
//                        music, ambient effects, engines, tires, speech)
//                        and the audio mode; the volumes go to bSound
//                        when the page closes, the mode at once
//   Pause display        PAUSE_DISPLAY (0xcc36fab2): the HUD, the mirror,
//                        the track map, the leaderboard, lap info,
//                        position, gauges, the split, the score, camera
//                        spring, lookback and the HUD hotkey
//   Race Objective       PRERACE_BLURB (0x887b4d37): the race's objective,
//                        as the pre-race blurb shows it
//   Pause BAC controls   PRERACE_BLURB again: You're The Cop's controls,
//                        two pages
//
// Each page's B goes back a page, START resumes the race if the player
// who paused pressed it. None of them writes the save: the pause changes
// TheRaceParameters, the players' settings and bSound, as retail does.
//
// The Options page gives each change to the race's ReplayManager as a
// special event (AddSpecialEvent), which makes it at once with
// HandlePauseMenuReplaySpecialEvents (pausereplay.c) and keeps it for the
// replay, as retail does.
//
// The 3DS has no rumble, so Vibration (MENUITEM_3) is hidden and the five
// rows under it move up a row. "Race Objective 2PBAC" (the two-player
// cop's) is not registered: the port races one player a console.
//
// docs/formats/pause-options.md has the decode.

#ifndef PAUSEOPTIONS_H
#define PAUSEOPTIONS_H

#include <stdint.h>

#include "bmenu.h"
#include "jukebox.h"
#include "sound.h"

struct BGameFlow;
struct Player;

// INGAMEB's screens, as FlailerScreenConfig registers them (the module's
// static constructors, 0x00174bf0 among them).
#define PAUSE_OPTIONS_SCREEN 0x2b5a03a8u   // PAUSE_OPTIONS
#define PAUSE_AUDIO_SCREEN   0x6b321e4eu   // PAUSE_AUDIO
#define PAUSE_DISPLAY_SCREEN 0xcc36fab2u   // PAUSE_DISPLAY
// Race Objective and Pause BAC controls are on startrace.h's
// STARTRACE_SCREEN_BLURB.

// What the pages need of main.c.
typedef struct {
    void*        user;
    void       (*log)(void* user, const char* line);   // the port's log
    JBSound*     jukebox;   // bSound's category volumes
    SoundModule* sound;     // the audio mode and the menu's samples
} PauseOptionsHooks;

void pause_options_init(const PauseOptionsHooks* hooks);

// The five FlailerScreenConfig callbacks, for kScreens[]:
// PauseOptionsCallback (0x001729f0), PauseAudioCallback (0x00171898),
// PauseDisplayCallback (0x00173d88), PauseRaceObjective::Callback
// (0x00171bb8) and PauseViewControls' (0x00171fd0).
void pause_options_callback(struct BGameFlow* gf, BScreenMessage msg,
                            BScreenCallbackData* data);
void pause_audio_callback(struct BGameFlow* gf, BScreenMessage msg,
                          BScreenCallbackData* data);
void pause_display_callback(struct BGameFlow* gf, BScreenMessage msg,
                            BScreenCallbackData* data);
void pause_race_objective_callback(struct BGameFlow* gf, BScreenMessage msg,
                                   BScreenCallbackData* data);
void pause_view_controls_callback(struct BGameFlow* gf, BScreenMessage msg,
                                  BScreenCallbackData* data);

// Player::CycleHud (0x00178ba8): PlayersHudState stepped by `dir` through
// {0, 1, 3, 2}, or {0, 3, 2} with two players shown, wrapping; a state
// off the list counts as the first. Also the HUD hotkey's
// (playerinput.h's gPlayerCycleHudFn).
void player_cycle_hud(struct Player* p, int32_t dir);
// Player::SetCameraSpring (0x00181e50): the setting, and the drive
// camera's DisableLag if the player's camera is one.
void player_set_camera_spring(struct Player* p, int32_t v);

#endif
