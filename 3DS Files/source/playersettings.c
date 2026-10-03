// playersettings -- see playersettings.h.

#include "playersettings.h"

#include <stddef.h>
#include <string.h>

#include "playercam.h"

uint8_t PlayerSkipFEPOVIndex = 1;                  // gp-23172

void player_settings_reset_to_defaults(cPlayerSettings *s)
{
    s->Rumble = 1;
    s->PlayersHudState = 0;
    s->DrivingStyle = 0;
    s->TransmissionType = 0;
    s->DriveCameraPOVIndex = gPlayerCamSkipFE != NULL && *gPlayerCamSkipFE
        ? (int8_t)PlayerSkipFEPOVIndex : 1;
    s->New5 = 0;
    s->Lookback = 1;
    s->SplitTimeType = 0;
    s->PreferredGender = 0;
    s->CameraSpring = 0;
    strcpy(s->PlayerName, "PLAYER");
    s->PreferredHudFeatures = 853;
    s->New44 = 1;
    s->New40 = 1;
    s->BestTotalTimeRecord.PackedTime = 0;
    s->BestLapTimeRecord.PackedTime = 0;
}
