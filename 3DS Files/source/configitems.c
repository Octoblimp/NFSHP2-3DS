// configitems -- see configitems.h.

#include "configitems.h"

#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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
int32_t ForceAllAICarsToBeThisType = -1;    // gp-23116
int32_t MaximumNumAICars = 7;               // gp-23112
int32_t TunePreRaceSequence;                // gp-23108
int32_t ConfigDebugLog;                     // the port's own
int32_t ConfigGpuSends = 1;                 // the port's own
int32_t ConfigKernelFlush = 1;              // the port's own
int32_t ConfigClusterCull = 1;              // the port's own
int32_t ConfigForceChopper;                 // the port's own
int32_t ConfigDebugMenu;                    // the port's own
int32_t ConfigWirelessTest;                 // the port's own
int32_t ConfigWirelessTestSeconds = 120;    // the port's own
int32_t ConfigWirelessTestConsoles = 2;     // the port's own
int32_t ConfigWirelessOff;                  // the port's own
int32_t ConfigWirelessTestFinish;           // the port's own
int32_t ConfigWirelessHoldSeconds = 90;     // the port's own

int32_t config_skip_fe(void)
{
    return gPlayerCamSkipFE != NULL ? *gPlayerCamSkipFE : 0;
}

// ------------------------------------------------- the port's config file

typedef struct ConfigItem {
    const char *Name;
    void       *Word;
    int         IsFloat;
} ConfigItem;

static const ConfigItem kConfigItems[] = {
    { "TrackSelectedInConfigFile",  &TrackSelectedInConfigFile,  0 },
    { "bVersionE3",                 &bVersionE3,                 0 },
    { "SkipFENumPlayerCars",        &SkipFENumPlayerCars,        0 },
    { "SkipFENumAICars",            &SkipFENumAICars,            0 },
    { "SkipFENumLaps",              &SkipFENumLaps,              0 },
    { "SkipFEMaxCops",              &SkipFEMaxCops,              0 },
    { "SkipFETimeUntilCopsAppear",  &SkipFETimeUntilCopsAppear,  1 },
    { "SkipFETickets",              &SkipFETickets,              0 },
    { "SkipFERoadBlocks",           &SkipFERoadBlocks,           0 },
    { "SkipFEHelicopter",           &SkipFEHelicopter,           0 },
    { "SkipFESpikeStrips",          &SkipFESpikeStrips,          0 },
    { "SkipFENew624",               &SkipFENew624,               0 },
    { "SkipFEBeACop",               &SkipFEBeACop,               0 },
    { "SkipFERearView",             &SkipFERearView,             0 },
    { "SkipFETrafficDensity",       &SkipFETrafficDensity,       1 },
    { "SkipFETrafficOncoming",      &SkipFETrafficOncoming,      1 },
    { "SkipFERaceType",             &SkipFERaceType,             0 },
    { "SkipFESpeedoMode",           &SkipFESpeedoMode,           0 },
    { "SkipFEDifficulty",           &SkipFEDifficulty,           0 },
    { "SkipFEEnableJumpCam",        &SkipFEEnableJumpCam,        0 },
    { "SkipFEEnableZoneCam",        &SkipFEEnableZoneCam,        0 },
    { "DefaultPlayer1CarType",      &DefaultPlayer1CarType,      0 },
    { "DefaultPlayer2CarType",      &DefaultPlayer2CarType,      0 },
    { "DefaultPlayer1SkinIndex",    &DefaultPlayer1SkinIndex,    0 },
    { "DefaultPlayer2SkinIndex",    &DefaultPlayer2SkinIndex,    0 },
    { "ForceAllAICarsToBeThisType", &ForceAllAICarsToBeThisType, 0 },
    { "MaximumNumAICars",           &MaximumNumAICars,           0 },
    { "TunePreRaceSequence",        &TunePreRaceSequence,        0 },
    { "DebugLog",                   &ConfigDebugLog,             0 },
    { "GpuSends",                   &ConfigGpuSends,             0 },
    { "KernelFlush",                &ConfigKernelFlush,          0 },
    { "ClusterCull",                &ConfigClusterCull,          0 },
    { "ForceChopper",               &ConfigForceChopper,         0 },
    { "DebugMenu",                  &ConfigDebugMenu,            0 },
    { "WirelessTest",               &ConfigWirelessTest,         0 },
    { "WirelessTestSeconds",        &ConfigWirelessTestSeconds,  0 },
    { "WirelessTestConsoles",       &ConfigWirelessTestConsoles, 0 },
    { "WirelessOff",                &ConfigWirelessOff,          0 },
    { "WirelessTestFinish",         &ConfigWirelessTestFinish,   0 },
    { "WirelessHoldSeconds",        &ConfigWirelessHoldSeconds,  0 },
};

static void config_log(ConfigItemsLogFn log, const char *fmt,
                       const char *a, const char *b)
{
    char line[320];

    if (log == NULL)
        return;
    snprintf(line, sizeof line, fmt, a, b);
    log(line);
}

// One line, NUL-terminated and stripped of its comment.
static int config_apply_line(char *line, int *skipFE, ConfigItemsLogFn log)
{
    char name[64], value[64], extra[2];
    const ConfigItem *it = NULL;
    char *end;
    size_t i;
    long n;
    float f;
    int got = sscanf(line, "%63s %63s %1s", name, value, extra);

    if (got <= 0)
        return 0;
    if (got != 2) {
        config_log(log, "config: skipped \"%s\"%s", line, "");
        return 0;
    }
    if (strcmp(name, "SkipFE") != 0) {
        for (i = 0; i < sizeof kConfigItems / sizeof kConfigItems[0]; i++)
            if (strcmp(name, kConfigItems[i].Name) == 0)
                it = &kConfigItems[i];
        if (it == NULL) {
            config_log(log, "config: no item %s%s", name, "");
            return 0;
        }
    }
    if (it != NULL && it->IsFloat) {
        f = strtof(value, &end);
        if (end == value || *end != '\0') {
            config_log(log, "config: %s: bad value %s", name, value);
            return 0;
        }
        *(float *)it->Word = f;
    } else {
        n = strtol(value, &end, 0);
        if (end == value || *end != '\0') {
            config_log(log, "config: %s: bad value %s", name, value);
            return 0;
        }
        if (it != NULL)
            *(int32_t *)it->Word = (int32_t)n;
        else
            *skipFE = (int)n;
    }
    config_log(log, "config: %s = %s", name, value);
    return 1;
}

int config_items_apply_text(const char *text, int *skipFE,
                            ConfigItemsLogFn log)
{
    char line[256];
    int set = 0;

    while (*text != '\0') {
        size_t len = strcspn(text, "\r\n");
        size_t keep = len < sizeof line - 1 ? len : sizeof line - 1;
        char *hash;

        memcpy(line, text, keep);
        line[keep] = '\0';
        hash = strchr(line, '#');
        if (hash != NULL)
            *hash = '\0';
        set += config_apply_line(line, skipFE, log);
        text += len;
        while (*text == '\r' || *text == '\n')
            text++;
    }
    return set;
}
