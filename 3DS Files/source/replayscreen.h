// replayscreen -- ReplayScreen from retail: the screen over an instant
// replay, with its timeline, its markers, its cameras and its buttons.
//
//   ReplayScreen::ReplayScreen(int)              0x001ebda8
//   ReplayScreen::~ReplayScreen()                0x001ebf98
//   (no symbol: the markers, the port's name)    0x001ec0c0
//   ReplayScreen::ShouldWeBeWatchingNis          0x001ec490
//   ReplayScreen::StopWatchingNis                0x001ec4c0
//   ReplayScreen::HasCameraMover                 0x001ec510
//   ReplayScreen::ChangeCameraMover              0x001ec540
//   ReplayScreen::Tick                           0x001ec768
//   ReplayScreen::Update                         0x001ec858
//   ReplayScreen::AddJoyHandlers(JoystickPort)   0x001ecd80
//   ReplayScreen::RemoveJoyHandlers(JoystickPort) 0x001ecea8
//   ReplayScreen::JoyHandler                     0x001ecf58
//   ReplayScreen::GetTimelinePositionX(float)    0x001ed410
//   ReplayScreen::SetFlailerBitmapPosition       0x001ed448
//   ReplayScreen::Pause(int)                     0x001ed498
//   ReplayScreen::JoyHandlerBridge               0x001ed4c0
//
// Retail's symbol table names 0x001ec0c0 the constructor; its callers say
// otherwise. TASKS 72g-2. RCStateInstantReplayCallback makes one and ticks
// it (72g-3), and MainLoop updates it. docs/formats/replay.md has the
// decode.

#ifndef REPLAYSCREEN_H
#define REPLAYSCREEN_H

#include <stddef.h>
#include <stdint.h>

#include "joyevent.h"
#include "replay.h"

struct CameraMover;
struct FlailerBitmapChunk;
struct FlailerObjectChunk;
struct NisCameraCoordinator;

// The screen and the one shown when the timeline is hidden.
#define REPLAY_SCREEN_HASH          0x60befaedu
#define REPLAY_SCREEN_HIDDEN_HASH   0xddce04a3u

// Each of retail's two marker lists holds 16.
#define REPLAY_SCREEN_MAX_MARKERS   16

// A marker on the timeline: a snapshot's beginning and end in seconds, the
// flailer object that marks it and the snapshot.
typedef struct ReplayScreenMarker {
    float    BeginTime;                          //   0
    float    EndTime;                            //   4
    struct FlailerObjectChunk *pObject;          //   8
    ReplaySnapshot *pSnapshot;                   //  12
} ReplayScreenMarker;                            //  16

// 584 bytes in retail. The demo's 248 had one list of markers; retail has
// one for the laps and the instant replay and one for the demo snapshots,
// and the word at 28.
typedef struct ReplayScreen {
    float    BeginningOfTime;                    //   0  seconds
    float    EndOfTime;                          //   4
    int32_t  TimelinePositionX;                  //   8
    int32_t  TimelineWidthX;                     //  12
    int32_t  HideTimeline;                       //  16
    int32_t  PlayerNumber;                       //  20
    int32_t  CameraMode;                         //  24  0..3
    int32_t  LastJoyLoop;                        //  28  new: RealLoopCounter
    int32_t  ReplayEndedTime;                    //  32  a Timer, RealTimer's
    int32_t  NumLapMarkers;                      //  36
    ReplayScreenMarker LapMarkers[REPLAY_SCREEN_MAX_MARKERS];       //  40
    int32_t  NumHighlightMarkers;                // 296
    ReplayScreenMarker HighlightMarkers[REPLAY_SCREEN_MAX_MARKERS]; // 300
    struct FlailerBitmapChunk *pTimeMarkerBitmap;                   // 556
    // Blinking while TheDemoModeReplay plays a snapshot, records one, or
    // wants to record one.
    struct FlailerObjectChunk *pDemoModeIndicator[3];               // 560
    struct CameraMover *pDriveCameraMover;                          // 572
    void     *pDemoCameraCoordinator;                               // 576
    struct NisCameraCoordinator *pNisCameraCoordinator;             // 580
} ReplayScreen;

#define REPLAY_SCREEN_SIZE          584

typedef char replayscreen_marker_check[
    (offsetof(ReplayScreen, LapMarkers) == 40
     && offsetof(ReplayScreen, NumLapMarkers) == 36
     && offsetof(ReplayScreen, LastJoyLoop) == 28) ? 1 : -1];
#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char replayscreen_size_check[
    (sizeof(ReplayScreenMarker) == 16
     && offsetof(ReplayScreen, NumHighlightMarkers) == 296
     && offsetof(ReplayScreen, HighlightMarkers) == 300
     && offsetof(ReplayScreen, pTimeMarkerBitmap) == 556
     && offsetof(ReplayScreen, pDemoModeIndicator) == 560
     && offsetof(ReplayScreen, pDriveCameraMover) == 572
     && offsetof(ReplayScreen, pNisCameraCoordinator) == 580
     && sizeof(ReplayScreen) == REPLAY_SCREEN_SIZE) ? 1 : -1];
#endif

// ReplayCameraTypes (0x0031a888): CameraMode to the camera it makes. 0 the
// demo camera, 1 the chase, 2 the chase looking back, 3 the bumper.
extern const int32_t ReplayCameraTypes[4];

// 0x0031a758: the help's lines, 0 at the end.
extern const int32_t ReplayScreenHelpIDs[9];

// ---------------------------------------------------- TheDemoModeReplay
//
// The three words of TheDemoModeReplay (0x002f0960) the screen reads, and
// TheDemoDiscManager's two timeouts (0x002effe0) that MARK_DEMO writes.
// TASKS 72h ports the classes around them; until then nothing else sets
// them, and the screen's demo branches stay asleep.
extern int32_t DemoModeReplay_WantToBeRecordingSnapshot;           // +20
extern ReplaySnapshot *DemoModeReplay_pCurrentRecordingSnapshot;   // +24
extern ReplaySnapshot *DemoModeReplay_pCurrentPlayingSnapshot;     // +32
extern int16_t DemoDiscManager_InactiveTimeout;                    // +30
extern int16_t DemoDiscManager_TotalTimeout;                       // +32

// ---------------------------------------------------------------- the seams
//
// What the screen calls that the port binds in main.c. Each does nothing
// when NULL, or answers as said.

// sound::PlayCommonRegionSample (0x001af760) and MakeFrontendSound
// (0x0016e038).
extern void (*gReplayScreenPlaySampleFn)(const char *name, float volume);
extern void (*gReplayScreenFrontendSoundFn)(int32_t event);

// The flow's tHelpMenu (+452): IsActive (0x001e4170), and 0x0016ca40, which
// on a press (1) dismisses it if it is up and summons these lines if not,
// then answers IsActive. NULL answers 0.
extern int32_t (*gReplayScreenHelpActiveFn)(void);
extern int32_t (*gReplayScreenToggleHelpFn)(const int32_t *lines,
                                            int32_t value);

// bIsThereACDInTheDrive (0x00255670). NULL answers 1, as the retail disc
// always does, which keeps MARK_DEMO a tweaker's button.
extern int32_t (*gReplayScreenIsThereACDFn)(void);

// RadialBlurOnOff (0x0010f1e0) on eGetView(1). NULL does nothing.
extern void (*gReplayScreenRadialBlurFn)(int32_t on);

// DemoModeReplay's CanTestDemoMode (0x0013f2d0), BeginDemoModeTest
// (0x0013f300), ServiceDemoMode (0x0013f430, 1 forward), EndDemoMode
// (0x0013f4f0), BeginRecordingSnapshot (0x0013f660) and
// EndRecordingSnapshot (0x0013f670), and 0x0013f310, which has no symbol:
// whether the snapshot played in a demo test goes on; Tick pauses the
// replay unless it answers 1. NULL CanTest answers 0 and NULL goes-on 1.
extern int32_t (*gDemoModeReplayCanTestFn)(void);
extern void (*gDemoModeReplayBeginTestFn)(void);
extern int32_t (*gDemoModeReplayTestGoesOnFn)(void);
extern void (*gDemoModeReplayServiceDemoModeFn)(int32_t forward);
extern void (*gDemoModeReplayEndDemoModeFn)(void);
extern void (*gDemoModeReplayBeginRecordingFn)(void);
extern void (*gDemoModeReplayEndRecordingFn)(int32_t keep);

// ---------------------------------------------------------------- the class

// 0x001ebda8, on REPLAY_SCREEN_SIZE bytes. The screen shown, the timeline
// from the replay's beginning to its end (a second at least) across the
// TIMELINE bitmap, the markers, the demo indicators, the joystick
// handlers on both ports, the camera, and the replay's sound on.
ReplayScreen *replayscreen_construct(void *mem, int32_t playerNumber);

// 0x001ebf98. Whichever screen was up hidden, the markers, the handlers,
// the pause off, the slow motion off, the camera deleted, and the demo's
// recording and test ended. Flag 1 frees the screen.
void replayscreen_destroy(ReplayScreen *s, int32_t flags);

// 0x001ec0c0. Every marker hidden; then, with `build`, the lists made
// again from the manager's snapshots, shown and placed on the timeline.
void replayscreen_setup_markers(ReplayScreen *s, int32_t build);

int32_t replayscreen_should_watch_nis(ReplayScreen *s);    // 0x001ec490
void replayscreen_stop_watching_nis(ReplayScreen *s);      // 0x001ec4c0
int32_t replayscreen_has_camera_mover(ReplayScreen *s);    // 0x001ec510

// 0x001ec540. The blur as the player's car has it, the old camera deleted,
// and the NIS's camera if one plays, else CameraMode's.
void replayscreen_change_camera_mover(ReplayScreen *s);

// 0x001ec768. At the capture's end the replay pauses; four seconds of it
// paused with the end screens up skip the replay.
void replayscreen_tick(ReplayScreen *s);

// 0x001ec858. The markers and the time marker; the player's number, lap,
// place and time, or why the race ended; the demo indicators; and the
// camera made again when it is missing or the NIS started or stopped.
void replayscreen_update(ReplayScreen *s);

void replayscreen_add_joy_handlers(ReplayScreen *s, JoystickPort port);
void replayscreen_remove_joy_handlers(ReplayScreen *s, JoystickPort port);

// 0x001ecf58. Events 99 to 110, JOY_EVENT_REPLAY_SKIP to _ERASE_DEMO, one
// a RealLoopCounter loop, none but HELP while the help is up.
void replayscreen_joy_handler(ReplayScreen *s, JoystickPort port,
                              JoyEvent ev, uint8_t value);

int32_t replayscreen_timeline_position_x(const ReplayScreen *s, float t);
void replayscreen_set_bitmap_position(ReplayScreen *s,
                                      struct FlailerBitmapChunk *b,
                                      float t);
void replayscreen_pause(ReplayScreen *s, int32_t on);

// 0x001ed4c0, the JoyHandler AddJoyHandler is given, with the screen.
void replayscreen_joy_handler_bridge(JoystickPort port, JoyEvent ev,
                                     uint8_t value, void *obj);

#endif
