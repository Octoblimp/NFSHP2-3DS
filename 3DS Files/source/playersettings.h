// playersettings -- cPlayerSettings, on its own so that RaceParameters
// (race.h) and the frontend database (fred.h) can hold it without
// player.h's joystick, NIS and topology.

#ifndef PLAYERSETTINGS_H
#define PLAYERSETTINGS_H

#include <stddef.h>
#include <stdint.h>

#include "timer.h"

// cPlayerSettings, 48 bytes in retail: what the player chose in the
// frontend. The demo's (.mdebug type#3426) is 40. The seven one-byte
// fields are type 2, `char`, which the image loads with `lb`; type#31 is
// a 32-bit bit set and type#1884 twelve bytes, the name.
//
// Retail's word at 12 is an int, where the demo's was the float
// LookbackSpeed: ResetToDefaults (0x001edf90) makes it 1 and ToggleLookback
// (0x001ee2d8) turns 0 and 1 into each other and leaves anything else. The
// drive camera counts a look back only while it is 0. ResetToDefaults
// also writes the byte at 7, which the demo left as padding, and the two
// words retail added at 40 and 44; `0x001ee020` toggles the one at 44.
// There are no pointers, so the record is the image's on every host: the
// memory card saves the two in Fred's FrontendPlayers whole.
typedef struct cPlayerSettings {
    int8_t   PlayersHudState;                    //    0
    int8_t   Rumble;                             //    1
    int8_t   DrivingStyle;                       //    2  InitForRace gives it the car
    int8_t   TransmissionType;                   //    3
    int8_t   DriveCameraPOVIndex;                //    4  the drive camera's POV
    int8_t   SplitTimeType;                      //    5
    int8_t   PreferredGender;                    //    6
    int8_t   New7;                               //    7  retail's; 0 by default
    int32_t  CameraSpring;                       //    8
    int32_t  Lookback;                           //   12  retail's; see above
    uint32_t PreferredHudFeatures;               //   16
    char     PlayerName[12];                     //   20
    Timer    BestTotalTimeRecord;                //   32
    Timer    BestLapTimeRecord;                  //   36
    int32_t  New40;                              //   40  retail's; 1 by default
    int32_t  New44;                              //   44  retail's; 1 by default
} cPlayerSettings;                               //   48

typedef char cplayersettings_layout_check[
    (offsetof(cPlayerSettings, CameraSpring) == 8
     && offsetof(cPlayerSettings, PlayerName) == 20
     && offsetof(cPlayerSettings, BestTotalTimeRecord) == 32
     && offsetof(cPlayerSettings, New44) == 44
     && sizeof(cPlayerSettings) == 48)
    ? 1 : -1];

// cPlayerSettings::ResetToDefaults, 0x001edf90. Rumble 1 and the other
// three leading bytes 0; the POV 1, or with SkipFE PlayerSkipFEPOVIndex;
// bytes 5-7 0; CameraSpring 0, Lookback 1, PreferredHudFeatures 853, the
// name "PLAYER"; New44 and New40 1, then the two records 0.
void player_settings_reset_to_defaults(cPlayerSettings *s);

// The byte at gp-23172, 1 on the disc: ResetToDefaults' POV under SkipFE.
extern uint8_t PlayerSkipFEPOVIndex;

#endif
