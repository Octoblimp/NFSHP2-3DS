// joyevent -- Joystick.obj, the part that turns pad bytes into JoyEvents
// (0x00150a50 .. 0x00152860 in NFSHP2.ELF). joystick.{c,h} keep the two
// type queries the physics already needed; everything else in the object
// is here.
//
// The shape of it. Every consumer of input -- the menus, RealDriver, the
// replay, the cameras -- registers a handler for one JoyEvent on one port.
// Each registration is an EventNode on that port's Joystick. Once a frame,
// GenerateJoyEvents walks every node, finds the ScannerConfig that says
// which bits of the pad buffer mean that event for the controller in the
// port, runs the config's scanner over the buffer, and queues whatever
// the scanner returns. Then it calls the handlers, in queue order.
//
// Nothing here knows what a button is. The meaning of every bit is in
// ScannerConfigTable (231 entries, scannertab.c, generated from the image),
// and the pad buffer is the DualShock 2's 32 bytes whatever the hardware:
// joypad.c builds one from the 3DS's buttons and sticks.
//
// Names. Free functions keep the original's names, like joystick.c's.
// Members are Class_Method. The two overloads are split:
//
//     FindScannerConfig(JoyEvent, int, int)  -> FindScannerConfig
//     FindScannerConfig(char*, int, int)     -> FindScannerConfigByName
//     AddJoyHandler(int, JoyEvent, ...)      -> (0x00151230, a bare `j` to
//                                                the other; not ported)
//
// Not ported: JoystickDoSnapshot (0x001514b0), which needs ReplaySnapshot,
// and PrintAllRegisteredJoyHandlers (0x00151538), which walks both lists
// and prints nothing on the retail build.
//
// See docs/formats/joystick.md. Cross-checked by tools/joystick_check.py.

#ifndef JOYEVENT_H
#define JOYEVENT_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "graph.h"
#include "joyeventid.h"
#include "joystick.h"

// ---------------------------------------------------------------- records

struct EventNode;
struct Joystick;
struct ScannerConfig;

// The handler every registration names: port, event, the value the
// scanner packed into bits 8..15, and the object it was registered with.
typedef void (*JoyHandler)(JoystickPort port, JoyEvent ev, uint8_t value,
                           void *obj);

// A scanner reads the pad buffer through a node's config and answers the
// event to queue, `Event + (value << 8)`, or 0 for nothing. `data` is this
// frame's buffer and `data2` the one before it.
typedef uint16_t (*JoyScanner)(struct EventNode *node, const uint32_t *data,
                               const uint32_t *data2,
                               const struct ScannerConfig *cfg,
                               struct Joystick *joy);

// bTNode<EventNode> and the bTList head in Joystick have the same two
// words, and the list is circular through the head.
typedef struct JoyLink {
    struct JoyLink *Next;          // 0
    struct JoyLink *Prev;          // 4
} JoyLink;

// 36 bytes, out of EventNodeSlotPool.
typedef struct EventNode {
    JoyLink              Link;          // 0
    JoyEvent             Event;         // 8
    const struct ScannerConfig *Config; // 12
    JoyHandler           Handler;       // 16
    void                *HandlerObject; // 20
    uint32_t             PreviousValue; // 24
    int32_t              FirstTime;     // 28
    int32_t              UserParam;     // 32
} EventNode;

// 32 bytes, one row of ScannerConfigTable. ConfigurationNumbers lists the
// configurations the row belongs to: -1 is all of them, 0 is an unused
// slot. Shift is a bit number in the 32-byte buffer and Xor is 1 for the
// DualShock's active-low buttons.
typedef struct ScannerConfig {
    int8_t      ConfigurationNumbers[8]; // 0
    JoyEvent    Event;                   // 8
    JoyScanner  Scanner;                 // 12
    uint8_t     Xor1;                    // 16
    uint8_t     Xor2;                    // 17
    uint8_t     Shift1;                  // 18
    uint8_t     Shift2;                  // 19
    uint8_t     Param;                   // 20
    uint8_t     AnalogDeviceNumber;      // 21
    uint8_t     ValidDuringReplay;       // 22
    int32_t     ButtonChar;              // 24, an eButtonChars glyph
    const char *ButtonName;              // 28
} ScannerConfig;

// 20 bytes, one row of ValidJoystickConfigurationTable: a controller type
// code, the configurations it can use, and the dead zone and hysteresis
// for its three analog devices.
typedef struct ValidJoystickConfiguration {
    int32_t JoystickType;              // 0
    int8_t  ConfigurationNumbers[10];  // 4
    uint8_t SteerHysterysis;           // 14
    uint8_t SteerDeadZoneSize;         // 15
    uint8_t ThrottleHysterysis;        // 16
    uint8_t ThrottleDeadZoneSize;      // 17
    uint8_t BrakeHysterysis;           // 18
    uint8_t BrakeDeadZoneSize;         // 19
} ValidJoystickConfiguration;

// 8 bytes, one row of EventNameTable.
typedef struct EventName {
    JoyEvent    Event;
    const char *Name;
} EventName;

// 44 bytes. A four-knee response curve for one analog device, and how far
// the value has to move before a new event is sent. Device 0 is unused;
// the configs name 1 steer, 2 brake and 3 throttle.
typedef struct AnalogJoystickCalibration {
    bVector2 vData[4];            // 0
    Graph    gCalibration;        // 32, over vData
    uint8_t  HysterysisAmount;    // 40
} AnalogJoystickCalibration;

#define JOY_CALIBRATIONS 4

// 204 bytes, JoystickArray[2] at 0x002f1558.
typedef struct Joystick {
    JoyLink  EventNodeList;                                     // 0
    AnalogJoystickCalibration
             AnalogJoystickCalibrationTable[JOY_CALIBRATIONS];  // 8
    int32_t  PortNumber;                                        // 184
    int32_t  CurrentType;                                       // 188
    int32_t  PreviousType;                                      // 192
    int32_t  NumValidTypeDetections;                            // 196
    int32_t  UserConfigurationNumber;                           // 200
} Joystick;

// 12 bytes.
typedef struct QueuedJoystickEvent {
    uint16_t   EventData;      // 0, the scanner's answer
    uint8_t    Port;           // 2
    uint8_t    Event;          // 3
    JoyHandler Handler;        // 4
    void      *HandlerObject;  // 8
} QueuedJoystickEvent;

#define JOY_MAX_QUEUED_EVENTS 256

// 3076 bytes, TheQueuedJoystickEvents at 0x002f16f0.
typedef struct QueuedJoystickEvents {
    int32_t             NumEvents;                      // 0
    QueuedJoystickEvent Events[JOY_MAX_QUEUED_EVENTS];  // 4
} QueuedJoystickEvents;

// The offsets above are the image's on a 32-bit target, which the 3DS is.
// A 64-bit host widens every pointer, and nothing reads these records as
// bytes, so there the check is skipped rather than bent to fit.
#if UINTPTR_MAX == 0xffffffffu
typedef char joyevent_layout_check[
    (sizeof(EventNode) == 36 && offsetof(EventNode, UserParam) == 32
     && sizeof(ScannerConfig) == 32 && offsetof(ScannerConfig, ButtonName) == 28
     && sizeof(ValidJoystickConfiguration) == 20
     && sizeof(AnalogJoystickCalibration) == 44
     && offsetof(AnalogJoystickCalibration, HysterysisAmount) == 40
     && sizeof(Joystick) == 204 && offsetof(Joystick, PortNumber) == 184
     && sizeof(QueuedJoystickEvent) == 12
     && sizeof(QueuedJoystickEvents) == 3076) ? 1 : -1];
#endif

// ----------------------------------------------------------------- tables

// Generated into scannertab.c by tools/gen_scanner_tables.py.
extern const ScannerConfig ScannerConfigTable[];               // 0x002dc6c0
extern const int32_t NumScannerConfigs;                        // gp-24344, 231
extern const ValidJoystickConfiguration
    ValidJoystickConfigurationTable[];                         // 0x002de3a0
extern const int32_t NumValidJoystickConfigurations;           // gp-24340, 7
extern const EventName EventNameTable[];                       // 0x002f22f8
#define JOY_EVENT_NAMES 127

// ---------------------------------------------------------------- globals

extern Joystick JoystickArray[JOYSTICK_PORTS];                 // 0x002f1558
extern QueuedJoystickEvents TheQueuedJoystickEvents;           // 0x002f16f0
extern struct BSlotPool *EventNodeSlotPool;                    // gp-22456

// ---------------------------------------------------- QueuedJoystickEvents

// 0x00150a50. Appends one entry, or drops it if 256 are queued.
void QueuedJoystickEvents_AddEvent(QueuedJoystickEvents *q, int32_t port,
                                   uint16_t value, const EventNode *node);

// 0x00150aa0. Clears the handler of every queued entry for (port, event),
// so a handler removed from inside another handler is not called later in
// the same frame.
void QueuedJoystickEvents_RemoveEvent(QueuedJoystickEvents *q, int32_t port,
                                      JoyEvent ev);

// --------------------------------------------------------------- Joystick

// 0x00150ae8. Ten frames of the same new type before it is believed; then
// every node is reconnected to the new type's configs. Answers how many
// events it queued.
int32_t Joystick_GenerateEventsFromScanners(Joystick *joy, int32_t type,
                                            const uint32_t *data,
                                            const uint32_t *data2,
                                            QueuedJoystickEvents *q);

// 0x00150c70. The first node for the event, or NULL.
EventNode *Joystick_FindEventNode(Joystick *joy, JoyEvent ev);

// 0x00150ca0. Looks the node's config up again and resets its state.
void Joystick_ConnectEventNodeConfig(Joystick *joy, EventNode *node);

// 0x001524e0. Frees every node, then bit 0 of flags is delete. The static
// destructor runs it on both joysticks with 0; nothing in the port does.
void Joystick_Destroy(Joystick *joy, int32_t flags);

// 0x00152770. The node's slot back to EventNodeSlotPool if bit 0.
void EventNode_Destroy(EventNode *node, int32_t flags);

// 0x00152588, _GLOBAL_$I$EventNodeSlotPool. The two joysticks' lists and
// calibration curves, and an empty queue.
void joyevent_static_init(void);

// ------------------------------------------------------------ calibration

// 0x00150ce8 / 0x00150d38 / 0x00150d90. The curve's two end knees, and
// the dead zone as the distance from 128 to the third knee.
void    SetJoystickCalibration(JoystickPort port, int32_t dev, uint8_t lo,
                               uint8_t hi);
void    GetJoystickCalibration(JoystickPort port, int32_t dev, uint8_t *lo,
                               uint8_t *hi);
uint8_t GetJoystickDeadzone(JoystickPort port, int32_t dev);

// 0x00152428. The dead zone and hysteresis for one device, from the last
// ValidJoystickConfigurationTable row for the type.
void ChooseDeadZoneAndHysterysis(AnalogJoystickCalibration *cal,
                                 int32_t type, int32_t dev);

// ---------------------------------------------------------- logged events

// 0x00150dd8 / 0x00150df0 / 0x00150e70. One queued event as 24 bits,
// `event | value << 8 | port << 16`, the form the replay and the joylog
// store; and back.
uint32_t MakeLoggedJoystickEvent(JoyEvent ev, uint8_t value,
                                 JoystickPort port);
void     AddLoggedJoystickEvent(uint32_t logged, QueuedJoystickEvents *q,
                                int32_t unused);
uint32_t GetLoggedJoystickEvent(int32_t i, QueuedJoystickEvents *q);

// ------------------------------------------------------------- the frame

// 0x00150e98. Once a frame: read the pads (or the joylog, or the replay),
// queue, then dispatch.
void GenerateJoyEvents(void);

// ---------------------------------------------------------- registration

// 0x00151190. Appends a node for (port, event) and connects it. A port may
// register the same event more than once; each gets its own node.
void AddJoyHandler(JoystickPort port, JoyEvent ev, JoyHandler fn, void *obj);

// 0x00151238. Removes the first node for (port, event) and cancels its
// queued entries.
void RemoveJoyHandler(JoystickPort port, JoyEvent ev);

// 0x001512c8.
int32_t IsJoyHandlerAdded(JoystickPort port, JoyEvent ev);

// 0x001512f8. Writes the new type into CurrentJoystickTypes.
void TypeChangedHandler(JoystickPort port, JoyEvent ev, uint8_t value,
                        void *obj);

// 0x00151308. CurrentJoystickTypes[port] != 255.
int32_t IsJoystickPluggedIn(JoystickPort port);

// 0x00151330 / 0x001513a8.
void InitJoystickTypeMonitoring(void);
void CloseJoystickTypeMonitoring(void);

// 0x00151408 / 0x00151410, both `jr ra`.
void TestJoyHandler(JoystickPort port, JoyEvent ev, uint8_t value, void *obj);
void TestJoystick(void);

// 0x00151418 / 0x00151480.
void InitJoystick(void);
void CloseJoystick(void);

// 0x001514f8. "JOY_EVENT_MISSING_NAME!" for the five events the table
// does not name.
const char *GetJoyEventName(JoyEvent ev);

// ----------------------------------------------------------- the scanners

uint16_t Scanner_TypeChanged(EventNode *, const uint32_t *, const uint32_t *,
                             const ScannerConfig *, Joystick *);  // 0x001515a0
uint16_t Scanner_DigitalAnyButton(EventNode *, const uint32_t *,
                                  const uint32_t *, const ScannerConfig *,
                                  Joystick *);                    // 0x001515e0
uint16_t Scanner_DigitalDown(EventNode *, const uint32_t *, const uint32_t *,
                             const ScannerConfig *, Joystick *);  // 0x00151668
uint16_t Scanner_DigitalDownPlus(EventNode *, const uint32_t *,
                                 const uint32_t *, const ScannerConfig *,
                                 Joystick *);                     // 0x00151780
uint16_t Scanner_DigitalUpOrDown(EventNode *, const uint32_t *,
                                 const uint32_t *, const ScannerConfig *,
                                 Joystick *);                     // 0x001517a0
uint16_t Scanner_DigitalUpOrDownPlus(EventNode *, const uint32_t *,
                                     const uint32_t *, const ScannerConfig *,
                                     Joystick *);                 // 0x001518b0
uint16_t Scanner_DigitalDoublePress(EventNode *, const uint32_t *,
                                    const uint32_t *, const ScannerConfig *,
                                    Joystick *);                  // 0x001518d0
uint16_t Scanner_DigitalRepeat(EventNode *, const uint32_t *, const uint32_t *,
                               const ScannerConfig *, Joystick *); // 0x00151a48
uint16_t Scanner_DigitalSteer(EventNode *, const uint32_t *, const uint32_t *,
                              const ScannerConfig *, Joystick *); // 0x00151ba0
uint16_t Scanner_DigitalAnalog(EventNode *, const uint32_t *, const uint32_t *,
                               const ScannerConfig *, Joystick *); // 0x00151c48
uint16_t Scanner_Analog(EventNode *, const uint32_t *, const uint32_t *,
                        const ScannerConfig *, Joystick *);       // 0x00151e00

// ------------------------------------------------------- configurations

// 0x00151fb8 / 0x00151fd8. Only stores the number: nodes already
// connected keep their configs until the type next changes.
void    SetJoystickUserConfiguration(JoystickPort port, int32_t n);
int32_t GetJoystickUserConfiguration(JoystickPort port);

// 0x00151ff8. The type's nonzero configuration numbers, at most `max`.
int32_t DetermineAvailableJoystickConfigurations(int32_t *out, int32_t max,
                                                 int32_t type);

// 0x00152088. The user's choice if the type offers it, else the type's
// first; 0 for a type the table does not know.
int32_t ChooseJoystickConfigurationNumber(int32_t type, int32_t user);

// 0x001520f0 / 0x00152280.
const ScannerConfig *FindScannerConfig(JoyEvent ev, int32_t type,
                                       int32_t user);
const ScannerConfig *FindScannerConfigByName(const char *name, int32_t type,
                                             int32_t user);

// 0x001521b0 / 0x00152220 / 0x001523a8. What the options screen shows.
const char *GetJoystickButtonName(JoystickPort port, JoyEvent ev);
int32_t     GetJoystickButtonChar(JoystickPort port, JoyEvent ev);
JoyEvent    GetJoystickButtonEvent(JoystickPort port, const char *name);

// 0x00152370. The events the options screen lets a player rebind.
int32_t IsConfigurableRacingEvent(JoyEvent ev);

#endif
