// joyevent -- see joyevent.h.

#include "joyevent.h"

#include <string.h>

#include "bslotpool.h"
#include "joylog.h"
#include "joypad.h"
#include "realtime.h"
#include "replay.h"

Joystick             JoystickArray[JOYSTICK_PORTS];
QueuedJoystickEvents TheQueuedJoystickEvents;
BSlotPool           *EventNodeSlotPool;

// The joylog's and the replay's channel for a queued event count (8 bits)
// and for one event (19 bits: the event, its value, the port).
#define LOG_COUNT_BITS 8
#define LOG_EVENT_BITS 19

// One bit, or one byte, of the pad buffer: `data[s >> 5] >> (s & 31)`.
static uint32_t pad_word(const uint32_t *data, uint32_t shift)
{
    return data[shift >> 5] >> (shift & 31);
}

// ---------------------------------------------------- QueuedJoystickEvents

void QueuedJoystickEvents_AddEvent(QueuedJoystickEvents *q, int32_t port,
                                   uint16_t value, const EventNode *node)
{
    QueuedJoystickEvent *e;

    if (q->NumEvents >= JOY_MAX_QUEUED_EVENTS)
        return;
    e = &q->Events[q->NumEvents++];
    e->Port = (uint8_t)port;
    e->EventData = value;
    e->Event = (uint8_t)node->Event;
    e->HandlerObject = node->HandlerObject;
    e->Handler = node->Handler;
}

void QueuedJoystickEvents_RemoveEvent(QueuedJoystickEvents *q, int32_t port,
                                      JoyEvent ev)
{
    int32_t i;

    for (i = 0; i < q->NumEvents; i++) {
        QueuedJoystickEvent *e = &q->Events[i];

        if ((int32_t)e->Port == port && e->Event == (uint8_t)ev)
            e->Handler = NULL;
    }
}

// --------------------------------------------------------------- Joystick

int32_t Joystick_GenerateEventsFromScanners(Joystick *joy, int32_t type,
                                            const uint32_t *data,
                                            const uint32_t *data2,
                                            QueuedJoystickEvents *q)
{
    JoyLink *l;
    int32_t replaying;
    int32_t count = 0;
    int32_t i;

    if (type != joy->CurrentType) {
        if (type != joy->PreviousType) {
            joy->PreviousType = type;
            joy->NumValidTypeDetections = 0;
            return 0;
        }
        if (++joy->NumValidTypeDetections < 10)
            return 0;
        joy->CurrentType = type;
        for (i = 0; i < JOY_CALIBRATIONS; i++)
            ChooseDeadZoneAndHysterysis(
                &joy->AnalogJoystickCalibrationTable[i], type, i);
        for (l = joy->EventNodeList.Next; l != &joy->EventNodeList;
             l = l->Next)
            Joystick_ConnectEventNodeConfig(joy, (EventNode *)l);
    }

    replaying = pReplayManager != NULL && pReplayManager->ReplayingFlag != 0;
    for (l = joy->EventNodeList.Next; l != &joy->EventNodeList; l = l->Next) {
        EventNode *node = (EventNode *)l;
        const ScannerConfig *cfg = node->Config;
        uint16_t v;

        if (cfg == NULL || cfg->Scanner == NULL)
            continue;
        if (replaying && !cfg->ValidDuringReplay)
            continue;
        v = cfg->Scanner(node, data, data2, cfg, joy);
        if (v != 0) {
            QueuedJoystickEvents_AddEvent(q, joy->PortNumber, v, node);
            count++;
        }
    }
    return count;
}

EventNode *Joystick_FindEventNode(Joystick *joy, JoyEvent ev)
{
    JoyLink *l;

    for (l = joy->EventNodeList.Next; l != &joy->EventNodeList; l = l->Next)
        if (((EventNode *)l)->Event == ev)
            return (EventNode *)l;
    return NULL;
}

void Joystick_ConnectEventNodeConfig(Joystick *joy, EventNode *node)
{
    node->Config = FindScannerConfig(node->Event, joy->CurrentType,
                                     joy->UserConfigurationNumber);
    node->FirstTime = 1;
    node->PreviousValue = 0;
}

// bTList<EventNode>'s destructor (0x00152700), inline: unlink and free
// from the front until the list is empty. bList's own with 2 does nothing.
void Joystick_Destroy(Joystick *joy, int32_t flags)
{
    JoyLink *head = &joy->EventNodeList;

    while (head->Next != head) {
        JoyLink *l = head->Next;

        l->Prev->Next = l->Next;
        l->Next->Prev = l->Prev;
        EventNode_Destroy((EventNode *)l, 3);
    }
    // Bit 0 would be __builtin_delete; JoystickArray is static.
    (void)flags;
}

void EventNode_Destroy(EventNode *node, int32_t flags)
{
    // bTNode's destructor with 0 does nothing.
    if (flags & 1)
        bSlotFree(EventNodeSlotPool, node);
}

void joyevent_static_init(void)
{
    int32_t p;
    int32_t i;

    for (p = 0; p < JOYSTICK_PORTS; p++) {
        Joystick *joy = &JoystickArray[p];

        joy->EventNodeList.Next = &joy->EventNodeList;
        joy->EventNodeList.Prev = &joy->EventNodeList;
        for (i = 0; i < JOY_CALIBRATIONS; i++) {
            AnalogJoystickCalibration *cal =
                &joy->AnalogJoystickCalibrationTable[i];

            graph_init(&cal->gCalibration, cal->vData, 4);
            cal->vData[0].x = 0.0f;
            cal->vData[0].y = 0.0f;
            cal->vData[1].x = 128.0f;
            cal->vData[1].y = 128.0f;
            cal->vData[2].x = 128.0f;
            cal->vData[2].y = 128.0f;
            cal->vData[3].x = 255.0f;
            cal->vData[3].y = 255.0f;
            cal->HysterysisAmount = 0;
        }
        joy->UserConfigurationNumber = 0;
        joy->CurrentType = -1;
        joy->PreviousType = -1;
        joy->NumValidTypeDetections = 0;
    }
    TheQueuedJoystickEvents.NumEvents = 0;
}

// ------------------------------------------------------------ calibration

static AnalogJoystickCalibration *calibration(JoystickPort port, int32_t dev)
{
    return &JoystickArray[port].AnalogJoystickCalibrationTable[dev];
}

void SetJoystickCalibration(JoystickPort port, int32_t dev, uint8_t lo,
                            uint8_t hi)
{
    AnalogJoystickCalibration *cal = calibration(port, dev);

    cal->vData[3].x = (float)hi;
    cal->vData[0].x = (float)lo;
}

void GetJoystickCalibration(JoystickPort port, int32_t dev, uint8_t *lo,
                            uint8_t *hi)
{
    AnalogJoystickCalibration *cal = calibration(port, dev);

    *lo = (uint8_t)(int32_t)cal->vData[0].x;
    *hi = (uint8_t)(int32_t)cal->vData[3].x;
}

uint8_t GetJoystickDeadzone(JoystickPort port, int32_t dev)
{
    return (uint8_t)(int32_t)(calibration(port, dev)->vData[2].x - 128.0f);
}

void ChooseDeadZoneAndHysterysis(AnalogJoystickCalibration *cal,
                                 int32_t type, int32_t dev)
{
    uint32_t hyst = 12;
    uint32_t dz = 20;
    int32_t i;

    // No break: the last row for the type wins.
    for (i = 0; i < NumValidJoystickConfigurations; i++) {
        const ValidJoystickConfiguration *v =
            &ValidJoystickConfigurationTable[i];

        if (v->JoystickType != type)
            continue;
        if (dev == 1) {
            dz = v->SteerDeadZoneSize;
            hyst = v->SteerHysterysis;
        } else if (dev == 2) {
            dz = v->ThrottleDeadZoneSize;
            hyst = v->ThrottleHysterysis;
        } else if (dev == 3) {
            dz = v->BrakeDeadZoneSize;
            hyst = v->BrakeHysterysis;
        } else {
            hyst = v->SteerHysterysis;
        }
    }
    cal->HysterysisAmount = (uint8_t)hyst;
    cal->vData[2].x = (float)(int32_t)dz + 128.0f;
    cal->vData[1].x = 128.0f - (float)(int32_t)dz;
}

// ---------------------------------------------------------- logged events

uint32_t MakeLoggedJoystickEvent(JoyEvent ev, uint8_t value,
                                 JoystickPort port)
{
    return (uint32_t)ev + ((uint32_t)value << 8) + ((uint32_t)port << 16);
}

void AddLoggedJoystickEvent(uint32_t logged, QueuedJoystickEvents *q,
                            int32_t unused)
{
    int32_t port = (int32_t)(logged >> 16);
    EventNode *node = Joystick_FindEventNode(&JoystickArray[port],
                                             (JoyEvent)(logged & 0xff));

    (void)unused;
    if (node != NULL)
        QueuedJoystickEvents_AddEvent(q, port, (uint16_t)logged, node);
}

uint32_t GetLoggedJoystickEvent(int32_t i, QueuedJoystickEvents *q)
{
    const QueuedJoystickEvent *e = &q->Events[i];

    return ((uint32_t)e->Port << 16) | e->EventData;
}

// ------------------------------------------------------------- the frame

void GenerateJoyEvents(void)
{
    QueuedJoystickEvents *q = &TheQueuedJoystickEvents;
    int32_t n;
    int32_t i;

    q->NumEvents = 0;
    if (Joylog_ReplayingFlag) {
        n = Joylog_GetData(LOG_COUNT_BITS, 1);
        for (i = 0; i < n; i++)
            AddLoggedJoystickEvent(
                (uint32_t)Joylog_GetData(LOG_EVENT_BITS, 1), q, 1);
    } else if (pReplayManager == NULL
               || !pReplayManager->FancyReplayInProgress) {
        PrepareToGetJoystickData();
        while (IsThereJoystickData()) {
            int32_t port;

            for (port = 0; port < JOYSTICK_PORTS; port++) {
                int32_t type;
                const uint32_t *data2;
                const uint32_t *data =
                    GetJoystickTypeAndData(port, &type, &data2);

                // Retail inlines DemoDiscManager::RegisterActivity on the
                // answer, a stamp only the demo disc's timeout reads.
                Joystick_GenerateEventsFromScanners(&JoystickArray[port],
                                                    type, data, data2, q);
            }
            AdvanceJoystickData();
        }
        n = q->NumEvents;
        Joylog_AddData(n, LOG_COUNT_BITS, 1);
        for (i = 0; i < n; i++)
            Joylog_AddData((int32_t)GetLoggedJoystickEvent(i, q),
                           LOG_EVENT_BITS, 1);
    }

    if (pReplayManager != NULL) {
        ReplayManager *rm = pReplayManager;

        if (rm->FancyJoyEventNumber < rm->NumFancyJoyEvents) {
            uint8_t ev = rm->FancyJoyEventTable[rm->FancyJoyEventNumber++];

            if (ev != 0)
                AddLoggedJoystickEvent(MakeLoggedJoystickEvent(ev, 1, 0),
                                       q, 1);
            rm = pReplayManager;
        }
        if (!rm->ReplayingFlag || rm->ReplayPausedThisFrame) {
            n = q->NumEvents;
            ReplayManager_AddData(pReplayManager, n, LOG_COUNT_BITS, 0);
            for (i = 0; i < n; i++)
                ReplayManager_AddData(pReplayManager,
                                      (int32_t)GetLoggedJoystickEvent(i, q),
                                      LOG_EVENT_BITS, 0);
        } else {
            n = ReplayManager_GetData(rm, LOG_COUNT_BITS, 0);
            for (i = 0; i < n; i++)
                AddLoggedJoystickEvent(
                    (uint32_t)ReplayManager_GetData(pReplayManager,
                                                    LOG_EVENT_BITS, 0),
                    q, 0);
        }
    }

    // A handler may queue nothing but may remove handlers, which clears
    // their entries; NumEvents and each Handler are read fresh.
    for (i = 0; i < q->NumEvents; i++) {
        const QueuedJoystickEvent *e = &q->Events[i];

        if (e->Handler != NULL)
            e->Handler(e->Port, e->EventData & 0xff,
                       (uint8_t)(e->EventData >> 8), e->HandlerObject);
    }
}

// ---------------------------------------------------------- registration

void AddJoyHandler(JoystickPort port, JoyEvent ev, JoyHandler fn, void *obj)
{
    Joystick *joy = &JoystickArray[port];
    EventNode *node;
    JoyLink *tail;

    // The image looks the event up first and never reads the answer.
    (void)Joystick_FindEventNode(joy, ev);
    node = (EventNode *)bSlotOMalloc(EventNodeSlotPool);
    tail = joy->EventNodeList.Prev;
    node->Event = ev;
    tail->Next = &node->Link;
    joy->EventNodeList.Prev = &node->Link;
    node->Handler = fn;
    node->HandlerObject = obj;
    node->Link.Next = &joy->EventNodeList;
    node->Link.Prev = tail;
    node->Config = NULL;
    node->FirstTime = 0;
    node->PreviousValue = 0;
    node->UserParam = 0;
    Joystick_ConnectEventNodeConfig(joy, node);
}

void RemoveJoyHandler(JoystickPort port, JoyEvent ev)
{
    Joystick *joy = &JoystickArray[port];
    EventNode *node;

    QueuedJoystickEvents_RemoveEvent(&TheQueuedJoystickEvents, port, ev);
    node = Joystick_FindEventNode(joy, ev);
    if (node == NULL)
        return;
    node->Link.Prev->Next = node->Link.Next;
    node->Link.Next->Prev = node->Link.Prev;
    EventNode_Destroy(node, 3);
}

int32_t IsJoyHandlerAdded(JoystickPort port, JoyEvent ev)
{
    return Joystick_FindEventNode(&JoystickArray[port], ev) != NULL;
}

void TypeChangedHandler(JoystickPort port, JoyEvent ev, uint8_t value,
                        void *obj)
{
    (void)ev;
    (void)obj;
    CurrentJoystickTypes[port] = value;
}

int32_t IsJoystickPluggedIn(JoystickPort port)
{
    return CurrentJoystickTypes[port] != 0xff;
}

void InitJoystickTypeMonitoring(void)
{
    int32_t p;

    for (p = 0; p < JOYSTICK_PORTS; p++) {
        CurrentJoystickTypes[p] = 0xff;
        AddJoyHandler(p, JOY_EVENT_TYPE_CHANGED, TypeChangedHandler, NULL);
    }
}

void CloseJoystickTypeMonitoring(void)
{
    int32_t p;

    for (p = 0; p < JOYSTICK_PORTS; p++) {
        CurrentJoystickTypes[p] = 0xff;
        RemoveJoyHandler(p, JOY_EVENT_TYPE_CHANGED);
    }
}

void TestJoyHandler(JoystickPort port, JoyEvent ev, uint8_t value, void *obj)
{
    (void)port;
    (void)ev;
    (void)value;
    (void)obj;
}

void TestJoystick(void)
{
}

void InitJoystick(void)
{
    int32_t p;

    for (p = 0; p < JOYSTICK_PORTS; p++)
        JoystickArray[p].PortNumber = p;
    EventNodeSlotPool = bNewSlotPool(sizeof(EventNode), 96,
                                     "EventNodeSlotPool", 16);
    PlatformInitJoystick();
    InitJoystickTypeMonitoring();
    TestJoystick();
}

void CloseJoystick(void)
{
    CloseJoystickTypeMonitoring();
    PlatformCloseJoystick();
    bDeleteSlotPool(EventNodeSlotPool);
    EventNodeSlotPool = NULL;
}

const char *GetJoyEventName(JoyEvent ev)
{
    int32_t i;

    for (i = 0; i < JOY_EVENT_NAMES; i++)
        if (EventNameTable[i].Event == ev)
            return EventNameTable[i].Name;
    return "JOY_EVENT_MISSING_NAME!";
}

// ----------------------------------------------------------- the scanners

uint16_t Scanner_TypeChanged(EventNode *node, const uint32_t *data,
                             const uint32_t *data2, const ScannerConfig *cfg,
                             Joystick *joy)
{
    uint32_t t = (uint8_t)joy->CurrentType;

    (void)data;
    (void)data2;
    (void)cfg;
    if (t != node->PreviousValue || node->FirstTime) {
        node->FirstTime = 0;
        node->PreviousValue = t;
        return (uint16_t)(node->Event + (t << 8));
    }
    return 0;
}

uint16_t Scanner_DigitalAnyButton(EventNode *node, const uint32_t *data,
                                  const uint32_t *data2,
                                  const ScannerConfig *cfg, Joystick *joy)
{
    uint32_t flip = cfg->Xor1 ? 0xffffffffu : 0;
    uint32_t mask = (1u << (cfg->Param & 31)) - 1;
    uint32_t v = ((pad_word(data, cfg->Shift1) ^ flip) & mask) != 0;

    (void)data2;
    (void)joy;
    if (node->FirstTime) {
        node->FirstTime = 0;
        node->PreviousValue = v;
    }
    if (v == node->PreviousValue)
        return 0;
    node->PreviousValue = v;
    if (v == 0)
        return 0;
    return (uint16_t)(node->Event + (v << 8));
}

// The prologue Down, UpOrDown, DoublePress and Repeat all inline. Shift 0
// means "no button", which reads as held. A second button with Xor2 set is
// a combo: it has to be held this frame and last, and the first has to be
// newly pressed this frame.
static uint32_t digital_pressed(const uint32_t *data, const uint32_t *data2,
                                const ScannerConfig *cfg)
{
    uint32_t b1 = 1;
    uint32_t b2 = 1;

    if (cfg->Shift1)
        b1 = (pad_word(data, cfg->Shift1) ^ cfg->Xor1) & 1;
    if (cfg->Shift2) {
        b2 = (pad_word(data, cfg->Shift2) ^ cfg->Xor2) & 1;
        if (cfg->Xor2) {
            uint32_t p2 = (pad_word(data2, cfg->Shift2) ^ cfg->Xor2) & 1;
            uint32_t p1 = (pad_word(data2, cfg->Shift1) ^ cfg->Xor1) & 1;

            if (b2 ^ p2)
                b2 = 0;
            b1 = b1 & (b1 ^ p1);
        }
    }
    return b1 & b2;
}

// Pressed is `Param`, or 1 if Param is 0.
static uint32_t digital_value(const uint32_t *data, const uint32_t *data2,
                              const ScannerConfig *cfg)
{
    if (!digital_pressed(data, data2, cfg))
        return 0;
    return cfg->Param ? cfg->Param : 1;
}

uint16_t Scanner_DigitalDown(EventNode *node, const uint32_t *data,
                             const uint32_t *data2, const ScannerConfig *cfg,
                             Joystick *joy)
{
    uint32_t v = digital_value(data, data2, cfg);

    (void)joy;
    if (node->FirstTime) {
        node->FirstTime = 0;
        node->PreviousValue = v;
    }
    if (v == node->PreviousValue)
        return 0;
    node->PreviousValue = v;
    if (v == 0)
        return 0;
    return (uint16_t)(node->Event + (v << 8));
}

uint16_t Scanner_DigitalDownPlus(EventNode *node, const uint32_t *data,
                                 const uint32_t *data2,
                                 const ScannerConfig *cfg, Joystick *joy)
{
    return Scanner_DigitalDown(node, data, data2, cfg, joy);
}

uint16_t Scanner_DigitalUpOrDown(EventNode *node, const uint32_t *data,
                                 const uint32_t *data2,
                                 const ScannerConfig *cfg, Joystick *joy)
{
    uint32_t v = digital_value(data, data2, cfg);

    (void)joy;
    if (v != node->PreviousValue || node->FirstTime) {
        node->FirstTime = 0;
        node->PreviousValue = v;
        return (uint16_t)(node->Event + (v << 8));
    }
    return 0;
}

uint16_t Scanner_DigitalUpOrDownPlus(EventNode *node, const uint32_t *data,
                                     const uint32_t *data2,
                                     const ScannerConfig *cfg, Joystick *joy)
{
    return Scanner_DigitalUpOrDown(node, data, data2, cfg, joy);
}

// A counter in UserParam: 0..49 the first press, 50..99 the gap, 100..149
// the second press. A second press released 2..11 frames after it began
// fires once, with value 0.
uint16_t Scanner_DigitalDoublePress(EventNode *node, const uint32_t *data,
                                    const uint32_t *data2,
                                    const ScannerConfig *cfg, Joystick *joy)
{
    uint32_t p = digital_pressed(data, data2, cfg);
    int32_t c = node->UserParam;
    int32_t limit;
    int32_t fire = 0;

    (void)joy;
    if (c < 50) {
        if (!p)
            c = ((uint32_t)(c - 2) < 10) ? 50 : 0;
        limit = 48;
        c = (limit < c) ? c : c + 1;
    } else if (c < 100) {
        if (p)
            c = ((uint32_t)(c - 52) < 10) ? 100 : 0;
        if (c < 99)
            c++;
        else if (c == 99)
            c = 0;
    } else if (c < 150) {
        if (!p) {
            if ((uint32_t)(c - 102) < 10)
                fire = 1;
            c = 0;
        }
        limit = 148;
        c = (limit < c) ? c : c + 1;
    }
    node->UserParam = c;
    return fire ? (uint16_t)node->Event : 0;
}

// Value 1 on the press, 2 every 6 frames once it has been held 25, and 0
// on the release.
uint16_t Scanner_DigitalRepeat(EventNode *node, const uint32_t *data,
                               const uint32_t *data2,
                               const ScannerConfig *cfg, Joystick *joy)
{
    uint32_t p = digital_pressed(data, data2, cfg);

    (void)joy;
    if (node->FirstTime) {
        node->FirstTime = 0;
        node->PreviousValue = 0;
    }
    if (!p) {
        if (node->PreviousValue == 0)
            return 0;
        node->PreviousValue = 0;
        return (uint16_t)node->Event;
    }
    if (node->PreviousValue - 1 < 2) {
        if (node->UserParam < FrameCounter) {
            node->PreviousValue = 2;
            node->UserParam = FrameCounter + 6;
            return (uint16_t)(node->Event + 512);
        }
        return 0;
    }
    node->PreviousValue = 1;
    node->UserParam = FrameCounter + 25;
    return (uint16_t)(node->Event + 256);
}

// Two buttons as a stick: 0 for the first alone, 255 for the second alone,
// 128 for neither or both.
uint16_t Scanner_DigitalSteer(EventNode *node, const uint32_t *data,
                              const uint32_t *data2, const ScannerConfig *cfg,
                              Joystick *joy)
{
    uint32_t b1 = (pad_word(data, cfg->Shift1) ^ cfg->Xor1) & 1;
    uint32_t b2 = (pad_word(data, cfg->Shift2) ^ cfg->Xor2) & 1;
    uint32_t t;

    (void)data2;
    (void)joy;
    if (b1)
        t = b2 ? 128 : 0;
    else
        t = b2 ? 255 : 128;
    if (t != node->PreviousValue || node->FirstTime) {
        node->FirstTime = 0;
        node->PreviousValue = t;
        return (uint16_t)(node->Event + (t << 8));
    }
    return 0;
}

// A stick as a button, for the menus: Param 1 is the low end (below 8),
// Param 2 the high end (248 and up). Pushing out fires, holding repeats on
// the same timing as DigitalRepeat, coming back releases. Two axes, and the
// first that says anything wins.
uint16_t Scanner_DigitalAnalog(EventNode *node, const uint32_t *data,
                               const uint32_t *data2,
                               const ScannerConfig *cfg, Joystick *joy)
{
    uint32_t t2 = (pad_word(data, cfg->Shift1) ^ cfg->Xor1) & 0xff;
    uint32_t t4 = 128;
    uint32_t old;
    int32_t i;

    (void)data2;
    (void)joy;
    if (cfg->Shift2)
        t4 = (pad_word(data, cfg->Shift2) ^ cfg->Xor2) & 0xff;
    if (node->FirstTime) {
        node->FirstTime = 0;
        node->PreviousValue = (t4 << 8) | t2;
        return 0;
    }
    old = node->PreviousValue;
    node->PreviousValue = (t4 << 8) | t2;
    for (i = 0; i < 2; i++) {
        int32_t o = (int32_t)(i ? (old >> 8) & 0xff : old & 0xff);
        int32_t n = (int32_t)(i ? t4 : t2);

        if (cfg->Param == 1) {
            if (o >= 9) {
                if (n < 8)
                    goto fire;
            } else if (o < 8) {
                if (n >= 9)
                    return (uint16_t)node->Event;
                if (n < 8 && node->UserParam < FrameCounter)
                    goto repeat;
            }
        } else if (cfg->Param == 2) {
            if (o < 247) {
                if (n >= 248)
                    goto fire;
            } else if (o >= 248) {
                if (n < 247)
                    return (uint16_t)node->Event;
                if (n >= 248 && node->UserParam < FrameCounter)
                    goto repeat;
            }
        }
    }
    return 0;

fire:
    node->UserParam = FrameCounter + 25;
    return (uint16_t)(node->Event + 256);
repeat:
    node->UserParam = FrameCounter + 6;
    return (uint16_t)(node->Event + 256);
}

// A stick, trigger or pressure through the device's calibration curve.
// Param 1 folds the low half onto 0..255 and Param 2 the high half; 0
// passes the curve's answer through. An event goes out when the value has
// moved by more than the hysteresis, or has reached 0, 128 or 255.
uint16_t Scanner_Analog(EventNode *node, const uint32_t *data,
                        const uint32_t *data2, const ScannerConfig *cfg,
                        Joystick *joy)
{
    uint32_t raw = (pad_word(data, cfg->Shift1) ^ cfg->Xor1) & 0xff;
    AnalogJoystickCalibration *cal =
        &joy->AnalogJoystickCalibrationTable[cfg->AnalogDeviceNumber];
    uint32_t h = cal->HysterysisAmount;
    uint32_t v;
    uint32_t enable = 1;

    (void)data2;
    v = (uint8_t)(int32_t)graph_get_value(&cal->gCalibration, (float)raw);
    if (cfg->Param == 1) {
        v = (v < 127 ? 127 - v : 0) << 1;
        if (v == 254)
            v = 255;
    } else if (cfg->Param == 2) {
        v = (v > 128 ? v - 128 : 0) << 1;
        if (v == 254)
            v = 255;
    }
    if (node->FirstTime) {
        node->FirstTime = 0;
        node->PreviousValue = v;
        return (uint16_t)(node->Event + (v << 8));
    }
    if (cfg->Shift2)
        enable = (pad_word(data, cfg->Shift2) ^ cfg->Xor2) & 1;
    if (!enable)
        return 0;
    if (v == 0 || v == 128 || v == 255)
        h = 0;
    if (v + h < node->PreviousValue || node->PreviousValue + h < v) {
        node->PreviousValue = v;
        return (uint16_t)(node->Event + (v << 8));
    }
    return 0;
}

// ------------------------------------------------------- configurations

void SetJoystickUserConfiguration(JoystickPort port, int32_t n)
{
    JoystickArray[port].UserConfigurationNumber = n;
}

int32_t GetJoystickUserConfiguration(JoystickPort port)
{
    return JoystickArray[port].UserConfigurationNumber;
}

int32_t DetermineAvailableJoystickConfigurations(int32_t *out, int32_t max,
                                                 int32_t type)
{
    int32_t i;
    int32_t j;

    for (i = 0; i < NumValidJoystickConfigurations; i++) {
        const ValidJoystickConfiguration *v =
            &ValidJoystickConfigurationTable[i];
        int32_t n = 0;

        if (v->JoystickType != type)
            continue;
        for (j = 0; j < 10; j++) {
            int32_t c = v->ConfigurationNumbers[j];

            if (c != 0 && n < max)
                out[n++] = c;
        }
        return n;
    }
    return 0;
}

int32_t ChooseJoystickConfigurationNumber(int32_t type, int32_t user)
{
    int32_t buf[10];
    int32_t n = DetermineAvailableJoystickConfigurations(buf, 10, type);
    int32_t i;

    if (n == 0)
        return 0;
    for (i = 0; i < n; i++)
        if (buf[i] == user)
            return user;
    return buf[0];
}

// Configuration 0 -- no type believed yet -- matches only the type-change
// row, so a node registered before the pad is recognised is idle until
// the type monitor reconnects it.
const ScannerConfig *FindScannerConfig(JoyEvent ev, int32_t type,
                                       int32_t user)
{
    int32_t cfg = ChooseJoystickConfigurationNumber(type, user);
    int32_t i;
    int32_t j;

    for (i = 0; i < NumScannerConfigs; i++) {
        const ScannerConfig *s = &ScannerConfigTable[i];

        if (s->Event != ev)
            continue;
        for (j = 0; j < 8; j++) {
            int32_t c;

            if (cfg == 0) {
                if (ev == JOY_EVENT_TYPE_CHANGED)
                    return s;
                continue;
            }
            c = s->ConfigurationNumbers[j];
            if (c == 0)
                continue;
            if (c == -1 || c == cfg)
                return s;
        }
    }
    return NULL;
}

const ScannerConfig *FindScannerConfigByName(const char *name, int32_t type,
                                             int32_t user)
{
    int32_t cfg = ChooseJoystickConfigurationNumber(type, user);
    int32_t i;
    int32_t j;

    for (i = 0; i < NumScannerConfigs; i++) {
        const ScannerConfig *s = &ScannerConfigTable[i];

        if (s->ButtonName == NULL || name == NULL
            || strcmp(s->ButtonName, name) != 0)
            continue;
        for (j = 0; j < 8; j++) {
            int32_t c = s->ConfigurationNumbers[j];

            if (c == 0)
                continue;
            if (c == -1 || c == cfg)
                return s;
        }
    }
    return NULL;
}

const char *GetJoystickButtonName(JoystickPort port, JoyEvent ev)
{
    const ScannerConfig *s = FindScannerConfig(
        ev, GetJoystickType(port), GetJoystickUserConfiguration(port));

    if (s == NULL || s->ButtonName == NULL)
        return "";
    return s->ButtonName;
}

int32_t GetJoystickButtonChar(JoystickPort port, JoyEvent ev)
{
    const ScannerConfig *s = FindScannerConfig(
        ev, GetJoystickType(port), GetJoystickUserConfiguration(port));

    return s ? s->ButtonChar : 0;
}

JoyEvent GetJoystickButtonEvent(JoystickPort port, const char *name)
{
    const ScannerConfig *s = FindScannerConfigByName(
        name, GetJoystickType(port), GetJoystickUserConfiguration(port));

    if (s == NULL || s->ButtonName == NULL
        || !IsConfigurableRacingEvent(s->Event))
        return JOY_EVENT_NULL;
    return s->Event;
}

int32_t IsConfigurableRacingEvent(JoyEvent ev)
{
    switch (ev) {
    case JOY_EVENT_CAMERA_POV_CHANGE:
    case JOY_EVENT_CAMERA_LOOKBACK:
    case JOY_EVENT_ZONE_FREEZE:
    case JOY_EVENT_ZONE_PREVIEW:
    case JOY_EVENT_ZONE_SLOMO:
    case JOY_EVENT_STEER:
    case JOY_EVENT_STEER_ANALOG:
    case JOY_EVENT_THROTTLE:
    case JOY_EVENT_THROTTLE_ANALOG:
    case JOY_EVENT_THROTTLE_ANALOG_ALTERNATE:
    case JOY_EVENT_BRAKE:
    case JOY_EVENT_BRAKE_ANALOG:
    case JOY_EVENT_BRAKE_ANALOG_ALTERNATE:
    case JOY_EVENT_REVERSE:
    case JOY_EVENT_REVERSE_ANALOG:
    case JOY_EVENT_EBRAKE:
    case JOY_EVENT_EBRAKE_ANALOG:
    case JOY_EVENT_SHIFTUP:
    case JOY_EVENT_SHIFTDOWN:
    case JOY_EVENT_HONK_HORN:
    case JOY_EVENT_CYCLE_HUD:
        return 1;
    default:
        return 0;
    }
}
