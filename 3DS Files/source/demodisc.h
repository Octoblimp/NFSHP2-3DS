// demodisc -- DemoDiscManager, the kiosk-mode controller, 48 bytes at
// 0x002e8120 (TheDemoDiscManager).
//
// Only the record, for now. bActive is 0 on the retail disc and nothing
// sets it (see docs/formats/boot-flow.md, "Demo disc"), so none of the
// class's behaviour is reachable; but GenerateJoyEvents inlines its
// RegisterActivity, which stamps LastActivityTime with RealTimer on any
// frame that queued an event, active or not.

#ifndef DEMODISC_H
#define DEMODISC_H

#include <stddef.h>
#include <stdint.h>

typedef struct DemoDiscManager {
    int32_t  bActive;               // 0
    int32_t  Dummy;                 // 4
    int32_t  StartTime;             // 8, a Timer
    int32_t  LastActivityTime;      // 12, a Timer
    int32_t  nDemoDiscEndReason;    // 16
    int32_t  NumDemoLoops;          // 20
    uint16_t Language;              // 24
    uint16_t Aspect;                // 26
    uint16_t PlayMode;              // 28
    uint16_t InactiveTimeout;       // 30
    uint16_t TotalTimeout;          // 32
    uint16_t MediaType;             // 34
    uint16_t MasterVolumeScale;     // 36
    uint16_t DirectorySectorNum;    // 38
    int32_t  bCalledSCEADemoStart;  // 40
    int32_t  bCalledSCEEDemoStart;  // 44
} DemoDiscManager;

typedef char demodisc_layout_check[
    (sizeof(DemoDiscManager) == 48
     && offsetof(DemoDiscManager, LastActivityTime) == 12
     && offsetof(DemoDiscManager, bCalledSCEEDemoStart) == 44) ? 1 : -1];

extern DemoDiscManager TheDemoDiscManager;   // 0x002e8120

#endif
