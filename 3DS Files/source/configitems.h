// configitems -- the words LoadConfigItems (0x0012faf0) fills, at their
// disc values.
//
// Retail keeps the race a SkipFE boot starts, and the cars a new frontend
// database starts with, in a run of words at gp-23256 .. gp-23124
// (0x0032fe18 .. 0x0032fe9c). LoadConfigItems reads them back from a
// joylog's channel 32 and SaveConfigItems writes them there, so a recorded
// session plays back with the setup it was recorded with; nothing else
// writes them, and on a retail boot they keep the image's values. They
// are words, and the readers that want a byte read the low one (`lbu`),
// which the port's `(uint8_t)` casts take.
//
// SkipFE itself (gp-23220) is gameflow's skipFE, which playercam.c's
// gPlayerCamSkipFE points at, and the POV index (gp-23172) is playerinit.c's
// PlayerSkipFEPOVIndex; both were ported before this file.
//
// The names are the demo's where the demo has the word. Retail added the
// one at gp-23180, which StartSkipFEGame copies to RaceParameters' New624;
// the retail map gives it the demo's SkipFEHelicopter, but the image's
// SkipFE start (0x00184bd8) puts gp-23188 into bHelicopter (+620) and
// gp-23184 into bSpikeStrips (+616), so the port names the three for where
// they go.
//
// SetupCarsForRace and StartRace read two more, past the default cars:
// ForceAllAICarsToBeThisType, the AI's car type unless it is -1, and
// MaximumNumAICars, the AI count StartRace allows (the demo's names, at the
// demo's places after DefaultPlayer2SkinIndex less the one gp-23120 holds,
// AllCarsAvailableInCarSelectScreen).
//
// The next word, TunePreRaceSequence, keeps PreRaceCameraCoordinator
// cycling its cameras when it is set, for tuning them; at 0 the pre-race
// ends once each car has had its camera.

#ifndef CONFIGITEMS_H
#define CONFIGITEMS_H

#include <stdint.h>

extern int32_t TrackSelectedInConfigFile;   // gp-23256, -1
extern int32_t bVersionE3;                  // gp-23224, 0
extern int32_t SkipFENumPlayerCars;         // gp-23216, 1
extern int32_t SkipFENumAICars;             // gp-23212, 0
extern int32_t SkipFENumLaps;               // gp-23208, 8
extern int32_t SkipFEMaxCops;               // gp-23204, 0
extern float   SkipFETimeUntilCopsAppear;   // gp-23200, 1.0
extern int32_t SkipFETickets;               // gp-23196, 1
extern int32_t SkipFERoadBlocks;            // gp-23192, 1
extern int32_t SkipFEHelicopter;            // gp-23188, 1
extern int32_t SkipFESpikeStrips;           // gp-23184, 1
extern int32_t SkipFENew624;                // gp-23180, 1
extern int32_t SkipFEBeACop;                // gp-23176, 0
extern int32_t SkipFERearView;              // gp-23168, 1
extern float   SkipFETrafficDensity;        // gp-23164, 0.0
extern float   SkipFETrafficOncoming;       // gp-23160, 0.5
extern int32_t SkipFERaceType;              // gp-23156, 1
extern int32_t SkipFESpeedoMode;            // gp-23152, 1
extern int32_t SkipFEDifficulty;            // gp-23148, 0
extern int32_t SkipFEEnableJumpCam;         // gp-23144, 1
extern int32_t SkipFEEnableZoneCam;         // gp-23140, 1
extern int32_t DefaultPlayer1CarType;       // gp-23136, 37
extern int32_t DefaultPlayer2CarType;       // gp-23132, 37
extern int32_t DefaultPlayer1SkinIndex;     // gp-23128, 1
extern int32_t DefaultPlayer2SkinIndex;     // gp-23124, 1
extern int32_t ForceAllAICarsToBeThisType;  // gp-23116, -1
extern int32_t MaximumNumAICars;            // gp-23112, 7
extern int32_t TunePreRaceSequence;         // gp-23108, 0

// The port's own word, not retail's: "DebugLog 1" has main.c write
// sdmc:/nfshp2_debug.txt. Off by default: on 2026-10-11 the console's
// SD driver (Process9) crashed twice as the log went to the card in a
// race (logwriter.h).
extern int32_t ConfigDebugLog;              // 0

// The port's own too: a race's frame goes to the GPU in parts as it is
// drawn (hangwatch_gpu_sends_begin) rather than whole at C3D_FrameEnd.
// Opt-in from 2026-10-12, on by default since 2026-10-13 (TASKS 57):
// the GPU-bound fire on track 11 waited for the CPU's whole draw first.
// "GpuSends 0" sends the frame whole again, should the device's GPU
// ever stop with it.
extern int32_t ConfigGpuSends;              // 1

// The port's own: each of those sends flushes the linear heap by the
// kernel's svcFlushProcessDataCache, not by a request to GSP that makes
// the same call (hangwatch.c, flush_heap; TASKS 65, 2026-10-14). A 3DSX
// from a homebrew launcher always asks GSP. "KernelFlush 0" asks GSP in
// the CIA too.
extern int32_t ConfigKernelFlush;           // 1

// The port's own: "ClusterCull 0" draws every batch whole, as before the
// clusters (geocull.h), for a timing run to compare (2026-10-12).
extern int32_t ConfigClusterCull;           // 1

// The port's own: "ForceChopper N" sends the helicopter after the player
// in an R-held (SkipFE) race and has it bomb every few seconds, for
// testing its munitions (12k-6) with no chase: 1 rockets, 2 and 3 the
// smoke bombs, 4 the spike belt, 5 each in turn (main.c,
// forceChopperTick). Off by default (2026-10-12).
extern int32_t ConfigForceChopper;          // 0

// The port's own: "DebugMenu 1" shows the main menu's Debug Menu item
// from boot, as the L + R + D-Pad Up chord does there (debugmenu.h,
// TASKS 53). Off by default (2026-10-13).
extern int32_t ConfigDebugMenu;             // 0

// The port's own: "WirelessTest 1" hosts a local wireless network and
// "WirelessTest 2" joins one, and the two soak the link for
// WirelessTestSeconds in place of the game (wirelesstest.h, TASKS 37a).
// The host waits for WirelessTestConsoles consoles, itself among them.
// Off by default (2026-10-14).
extern int32_t ConfigWirelessTest;          // 0
extern int32_t ConfigWirelessTestSeconds;   // 120
extern int32_t ConfigWirelessTestConsoles;  // 2

// The port's own: "WirelessOff 1" has the Local Wireless lobby take the
// console's wireless communication as turned off (TASKS 62), as the
// HOME Menu's setting does; Azahar's is never off. Off by default
// (2026-10-14).
extern int32_t ConfigWirelessOff;           // 0

// The port's own: "WirelessTestFinish n" finishes a wireless race on its
// lockstep frame n, or the first one after it that is racing, on every
// console, as if each car had crossed the line where it was
// (racecoordinator_the_race_has_finished): the Azahar runs' way to the
// results and Next Race (TASKS 37f-2). Off by default (2026-10-15).
extern int32_t ConfigWirelessTestFinish;    // 0

// The port's own: a console lost mid-race is waited for this long, the
// race held on every console, before its car is the CPU's (netstep's hold,
// TASKS 37g). 0 is netstep's own, 90 s. Azahar runs set it short.
extern int32_t ConfigWirelessHoldSeconds;   // 90

// The port's own: "WirelessTestDropFrame n" has this console's wireless
// hear and send nothing for WirelessTestDropMs from its lockstep frame n
// (wireless_test_deaf), as one out of range: each end loses the link, the
// race holds, and the console finds the host again and is taken back
// (TASKS 37g-2). The Azahar runs' way to a dropped link. Off by default
// (2026-10-15).
extern int32_t ConfigWirelessTestDropFrame; // 0
extern int32_t ConfigWirelessTestDropMs;    // 5000

// The port's own: "WirelessTestBlindFrame n" has this console draw none of
// a wireless race's frames for WirelessTestBlindFrames from its lockstep
// frame n, still in step and at the race's pace, as a console catching up
// runs them (37g-3): the Azahar runs' way to what an undrawn frame changes
// in the world (TASKS 37f-2). Off by default (2026-10-15).
extern int32_t ConfigWirelessTestBlindFrame;  // 0
extern int32_t ConfigWirelessTestBlindFrames; // 300

// SkipFE as the image reads it, `lw -23220(gp)`: gameflow's skipFE
// through gPlayerCamSkipFE, 0 while that is unset.
int32_t config_skip_fe(void);

// ------------------------------------------------- the port's config file
//
// The port's own, in the joylog's place: retail reads these words from a
// joylog's channel 32, which only a development kit records (joylog.h), so
// on a retail console they keep the image's values. The port reads a text
// file instead, CONFIG_ITEMS_FILE, when the card has one. Each line is a
// name above and its value, "SkipFENumAICars 3"; `#` starts a comment.
// "SkipFE 1" turns SkipFE on as holding R does. A name it does not know,
// or a value it cannot read, is reported and skipped. main.c reads it at
// boot, before InitFred; with no file nothing changes.
#define CONFIG_ITEMS_FILE "sdmc:/nfshp2_config.txt"

// The port's own: "TestFinish n" finishes a race on this console alone
// (not a wireless one) n seconds after its GO: the player's car
// crosses in place TestFinishPlace, the cars ahead of it first, and the
// rest as SimulateRaceFinish has them (racecoordinator_the_race_has_
// finished). The Azahar runs' way to an event's end screens and back to
// the event tree (TASKS 69f). Off by default (2026-10-16).
// "TestFinishTime s" gives the player's car a lap of s seconds instead of
// the time projected from how far it got, so a time trial's goal can be
// met (2026-10-17). In Be A Cop each racer is arrested instead, and the
// last arrest wins the race for the cop.
extern int32_t ConfigTestFinish;            // 0
extern int32_t ConfigTestFinishPlace;       // 1
extern int32_t ConfigTestFinishTime;        // 0

// The port's own: "ReplayCheck 1" plays parts of each race back as it
// goes and logs what does not come out as it was captured (main.c,
// replayCheckTick; TASKS 72f-2). The race jumps back twice: some 20
// seconds after GO to the last lap snapshot, then to the older instant
// replay, each played on to where the capture had got to. Needs
// "DebugLog 1" for the log. Off by default (2026-10-17).
extern int32_t ConfigReplayCheck;           // 0

// The port's own: "DemoReplays 1" lets attract mode play the disc's six
// replays (sdmc:/NFSHP2/REPLAY) as retail does. Off by default
// (2026-10-17): the port's car physics is the demo's (TASKS 73), so a PS2
// replay drifts from its first frame -- every frame's checksum misses,
// which ends the demo at once, and the car leaves the road some 40
// seconds in. Off, ConsiderLaunching answers "none" and attract mode is
// retail's other demo, the AI race (demomode.c).
extern int32_t ConfigDemoReplays;           // 0

typedef void (*ConfigItemsLogFn)(const char *line);

// Applies `text` (NUL-terminated), each word as it is read; SkipFE goes
// to *skipFE. `log` (may be NULL) gets a line for each word set and each
// line skipped. Answers the number of words set.
int config_items_apply_text(const char *text, int *skipFE,
                            ConfigItemsLogFn log);

#endif
