#pragma once
#include <stdint.h>

#include "bmenu.h"
#include "gameflow.h"
#include "jukebox.h"
#include "sound.h"

// Options' Audio: retail's AudioOptionsScreen (0x001ef3c8 .. 0x001f02d4,
// "Audio Options" in kScreens) and the JukeBox Music page it opens
// (JukeBoxMusicScreen, 0x001f02d8 .. 0x001f127c). Both are
// OptionsScreenBase pages (bscreens.c's bscr_optbase_*).
//
// Audio Options is eleven rows in a window of seven that scrolls: the
// seven volume sliders (menu music, racing music, sound effects, tires,
// engines, menu effects, speech), the audio mode (Mono, Stereo, and retail's
// Dolby Pro Logic II shown as the 3DS's Surround), JukeBox, Default Volumes
// and Default JukeBox. Left and Right
// move a slider by 0.05 and set its volume at once; the mode changes at
// once too.
//
// JukeBox Music picks a genre with Left and Right and turns it on or off
// with L; Down enters the genre's list, where Up and Down pick a tune (it
// plays half a second later) and Left and Right set when it plays (Off,
// World Racing, Hot Pursuit, Menu, Menu/Racing, Always).
//
// Retail's B on either page writes the page's copy into Fred and, with
// autosave on and anything changed, saves on the Autosave screen. The
// port's Audio Options asks instead, with autosave on or off (the save
// prompt, the user's word of 2026-10-13), against Fred's options as they
// were when the player came in from Options, JukeBox's changes included:
// Yes saves there, No puts the options back and applies them, B stays.
// JukeBox's B goes back to Audio Options without asking.
// docs/formats/audio-options.md.

// FlailerScreenConfig's hashes.
#define AUDIOOPTS_SCREEN 0xe116761cu
#define JUKEBOX_SCREEN   0x95b2b627u

// What the pages need of main.c.
typedef struct {
    void*        user;
    void       (*log)(void* user, const char* line);   // the port's log
    JBSound*     jukebox;   // the game's jukebox, its player and volumes
    SoundModule* sound;     // the audio mode and the menus' samples
} AudioOptionsHooks;

void audioopts_init(const AudioOptionsHooks* hooks);

// AudioOptionsScreen::Callback (0x001f0278), for kScreens[].
void audioopts_callback(BGameFlow* gf, BScreenMessage msg,
                        BScreenCallbackData* data);
// JukeBoxMusicScreen::Callback (0x001f1220), for kScreens[].
void jukeboxscreen_callback(BGameFlow* gf, BScreenMessage msg,
                            BScreenCallbackData* data);
