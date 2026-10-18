// dmreplay -- retail's DemoModeReplay (0x0013ee08 .. 0x0013fa70): the
// attract mode's replays, TheDemoModeReplay (0x002f0960).
//
// The disc has five, REPLAY\JUL23\*.bin. Each is a resource file of three
// chunk types, which slot 29 of the loader tables hands here:
//
//   0x39100  DemoModeReplayInfo, 80 bytes: version 8, the track, 1, 0 and
//            the author's computer name
//   0x39101  a ReplaySnapshot, its 344-byte head and its data: one or more
//            DEMO_MODE_SNAPSHOT and one REPLAY_MANAGER_STATE
//   0x39102  the bRepeat the race was captured into, cut at its end
//
// The title's ConsiderStartDemoMode asks ConsiderLaunching for one, which
// picks the next file (the first at random) and starts it loading. Once it
// is in, Launch sets ActiveFlag, and FrontendDatabase::StartRace takes the
// race's parameters from the first snapshot (RestoreRaceParametersSnapshot)
// and unloads the file. The track's loading loads it again, and the
// ReplayManager takes its log and snapshots (replaymgr.c). The race
// coordinator's ReplayDemoMode state then plays each DEMO_MODE_SNAPSHOT from
// its BeginLoopTime to its EndLoopTime (BeginDemoMode, TestGoesOn,
// ServiceDemoMode). After the last, the demo ends.
//
// The rest is the replay screen's editing, which retail reaches only with
// its debug keys: recording a snapshot, erasing part of one, testing them,
// and the tweakers that pick a file, save it and erase the snapshots.
// Save and SaveSnapshots write the file through the PS2 dev kit's host
// link, and are not ported; the tweaker that asks for them is kept.
//
// The object is split. The words other modules read are theirs:
//
//   +0   ActiveFlag                   trackflow.c   DemoModeReplayActiveFlag
//   +20  (retail's own)               replayscreen.c
//                                     DemoModeReplay_WantToBeErasingSnapshot
//   +24  pCurrentRecordingSnapshot    replayscreen.c
//   +32  pCurrentPlayingSnapshot      replayscreen.c
//   +52  pRepeat                      replaymgr.c   DemoModeReplay_pRepeat
//   +56  ReplaySnapshotList           replaymgr.c   DemoModeReplay_SnapshotList
//
// and the rest are TheDemoModeReplay's below. The names are the demo's
// (its stabs); retail put the word at +20 in. docs/formats/replay.md, 72h-2,
// has the decode, and tools/dmreplay_check.py runs this against retail.

#ifndef DMREPLAY_H
#define DMREPLAY_H

#include <stdint.h>

#include "replay.h"

// DemoModeReplayInfo, the 0x39100 chunk.
typedef struct DemoModeReplayInfo {
    int32_t VersionNumber;               //  0   8
    int32_t TrackNumber;                 //  4   TheRaceParameters' first word
    int32_t New8;                        //  8   1; Launch wants 1
    int32_t New12;                       // 12   0
    char    AuthorName[64];              // 16   bGetComputerName's
} DemoModeReplayInfo;                    // 80

// TheDemoModeReplay's own words.
typedef struct DemoModeReplay {
    int32_t LoadingFlag;                     //  +4
    int32_t LoadedFlag;                      //  +8
    int32_t CurrentSnapshotFileNumber;       // +12  1..5 once one is picked
    int32_t WantToBeRecordingSnapshot;       // +16
    int32_t PlayingSnapshotNumber;           // +28
    int32_t TweakerSnapshotFileNumber;       // +36  -1, or the file to pick
    int32_t TweakerSaveSnapshotFile;         // +40
    int32_t TweakerEraseRecordedSnapshots;   // +44
    const DemoModeReplayInfo *pInfo;         // +48  in the loaded file
} DemoModeReplay;

extern DemoModeReplay TheDemoModeReplay;

// The snapshots' names (0x002af118 and 0x002af100).
#define DEMO_MODE_SNAPSHOT_NAME    "DEMO_MODE_SNAPSHOT"
#define REPLAY_MANAGER_STATE_NAME  "REPLAY_MANAGER_STATE"
// GetNumSnapshots' answer, the size of DemoModeReplayFilenames.
#define DEMO_MODE_REPLAY_NUM_FILES 6
// GenerateFilename's buffer, as retail's callers have it.
#define DEMO_MODE_REPLAY_FILENAME_SIZE 64

// __14DemoModeReplay (0x0013ee08), TheDemoModeReplay's static
// constructor: the tweaker's file -1, the list empty and the rest 0. Its
// split words too.
void dmreplay_construct(void);

// Loader and Unloader (0x0013ee58 and 0x0013eed8), slot 29's. The info
// and the log are taken where they lie. A snapshot is marked loaded from
// memory (MemoryImageLoadedFlag) and goes on the list's end; its unload
// takes it off only when it is on it. Each answers 1 for the three types
// and 0 for any other.
int dmreplay_loader(uint8_t *chunk);
int dmreplay_unloader(uint8_t *chunk);

// GetBaseFilename (0x0013efc0): DemoModeReplayFilenames (0x002f0948) at
// `i`, or at 0 when `i` is not 0..5. 0 is the dev kit's REPLAY0.BIN.
const char *dmreplay_get_base_filename(int32_t i);
// GenerateFilename (0x0013efe0): "REPLAY\" and the base name, or "" when
// the base name is.
void dmreplay_generate_filename(char *out, int32_t i);

// LoadResourceFile (0x0013f070): LoadingFlag, then the current file as a
// RESOURCE_FILE_REPLAY with ResourceFileLoadedCallback (0x0013f110), which
// clears LoadingFlag and sets LoadedFlag.
void dmreplay_load_resource_file(void);
// UnloadResourceFile (0x0013f0c0): with LoadedFlag, every replay resource
// file unloaded, newest first, and LoadedFlag cleared.
void dmreplay_unload_resource_file(void);
void dmreplay_resource_file_loaded_callback(intptr_t param);

// ConsiderLaunching (0x0013f120): the next file, the first drawn with
// bRandom(5) + 1, the tweaker's when it is set, and 1 after 5; then 1 and
// the file loading, or 0 when its name is empty or it is not there.
int32_t dmreplay_consider_launching(void);
// Launch (0x0013f1c0): ActiveFlag from an info of version 8 whose New8 is
// 1, or else the file unloaded.
void dmreplay_launch(void);
// RestoreRaceParametersSnapshot (0x0013f220): TheRaceParameters from the
// first snapshot on the list -- InitWithDefaults, then its DoSnapshot read
// from the snapshot's start -- with ReplayDemoMode set.
void dmreplay_restore_race_parameters_snapshot(void);

// BeginDemoMode (0x0013f288): the manager restored from
// REPLAY_MANAGER_STATE, and the first DEMO_MODE_SNAPSHOT played.
void dmreplay_begin_demo_mode(void);
// GetNumSnapshots (0x0013f2c8): 6.
int32_t dmreplay_get_num_snapshots(void);
// CanTestDemoMode (0x0013f2d0): whether the manager has a
// DEMO_MODE_SNAPSHOT.
int32_t dmreplay_can_test_demo_mode(void);
// BeginDemoModeTest (0x0013f300): the first DEMO_MODE_SNAPSHOT played.
void dmreplay_begin_demo_mode_test(void);
// 0x0013f310, no symbol: whether the demo goes on. Once the world reaches
// the playing snapshot's EndLoopTime, the next is played, and with none 0
// is the answer. While the erase is held (+20) the playing snapshot is
// cut: deleted when under 2 s long, or ended here in its second half,
// and the next played.
int32_t dmreplay_test_goes_on(void);
// ServiceDemoMode (0x0013f430): the next DEMO_MODE_SNAPSHOT when
// `forward`, else the one before (the first from the first), made the
// playing one and posted to the race coordinator as RC_MOVE_REPLAY.
void dmreplay_service_demo_mode(int32_t forward);
// EndDemoMode (0x0013f4f0): nothing playing, ActiveFlag clear, the
// snapshot number 0.
void dmreplay_end_demo_mode(void);

// Service (0x0013f500), each ReplayManager::BeginFrame, told whether the
// manager takes a snapshot this loop. Then a recording starts (a
// REPLAY_MANAGER_STATE and a DEMO_MODE_SNAPSHOT taken), and an erase held
// in the playing snapshot's first 3 s takes it again here, so that it
// starts later and keeps its end. The snapshot being recorded ends at the
// world's loop and time. Then the two tweakers: save (not ported) and
// erase.
void dmreplay_service(int32_t snapshot_this_loop);
// BeginRecordingSnapshot (0x0013f660) and EndRecordingSnapshot
// (0x0013f670), the replay screen's MARK_DEMO: a recording of 30 loops or
// fewer is deleted. `keep` is not read.
void dmreplay_begin_recording_snapshot(void);
void dmreplay_end_recording_snapshot(int32_t keep);
// EraseRecordedSnapshots (0x0013f6c0): every DEMO_MODE_SNAPSHOT and one
// REPLAY_MANAGER_STATE deleted, and nothing playing or recording.
void dmreplay_erase_recorded_snapshots(void);

// ---------------------------------------------------------------- seams

// Save (0x0013f7e8), which writes the snapshots to the file through the
// dev kit's host link, and bRefreshTweaker (0x0025d2c8) after each
// tweaker. NULL does nothing.
extern void (*gDemoModeReplaySaveFn)(void);
extern void (*gDemoModeReplayRefreshTweakerFn)(void);

#endif
