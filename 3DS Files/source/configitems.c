// configitems -- see configitems.h.

#include "configitems.h"

#include <stddef.h>

#include "playercam.h"

int32_t TrackSelectedInConfigFile = -1;     // gp-23256
int32_t bVersionE3;                         // gp-23224
int32_t SkipFENumPlayerCars = 1;            // gp-23216
int32_t SkipFENumAICars;                    // gp-23212
int32_t SkipFENumLaps = 8;                  // gp-23208
int32_t SkipFEMaxCops;                      // gp-23204
float   SkipFETimeUntilCopsAppear = 1.0f;   // gp-23200
int32_t SkipFETickets = 1;                  // gp-23196
int32_t SkipFERoadBlocks = 1;               // gp-23192
int32_t SkipFEHelicopter = 1;               // gp-23188
int32_t SkipFESpikeStrips = 1;              // gp-23184
int32_t SkipFENew624 = 1;                   // gp-23180
int32_t SkipFEBeACop;                       // gp-23176
int32_t SkipFERearView = 1;                 // gp-23168
float   SkipFETrafficDensity;               // gp-23164
float   SkipFETrafficOncoming = 0.5f;       // gp-23160
int32_t SkipFERaceType = 1;                 // gp-23156
int32_t SkipFESpeedoMode = 1;               // gp-23152
int32_t SkipFEDifficulty;                   // gp-23148
int32_t SkipFEEnableJumpCam = 1;            // gp-23144
int32_t SkipFEEnableZoneCam = 1;            // gp-23140
int32_t DefaultPlayer1CarType = 37;         // gp-23136
int32_t DefaultPlayer2CarType = 37;         // gp-23132
int32_t DefaultPlayer1SkinIndex = 1;        // gp-23128
int32_t DefaultPlayer2SkinIndex = 1;        // gp-23124

int32_t config_skip_fe(void)
{
    return gPlayerCamSkipFE != NULL ? *gPlayerCamSkipFE : 0;
}
