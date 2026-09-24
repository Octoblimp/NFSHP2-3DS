// Harness for tools/joystick_check.py: runs the checker's op script on the
// port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out. See the checker's docstring for what each stand-in
// below is standing in for.
//
//     joystick_test ops.bin > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bslotpool.h"
#include "demodisc.h"
#include "joyevent.h"
#include "joylog.h"
#include "joypad.h"
#include "joystick.h"
#include "realtime.h"
#include "replay.h"

enum {
    OP_TAG, OP_INIT, OP_CLOSE, OP_ADD, OP_REMOVE, OP_ISADDED, OP_PAD, OP_READ,
    OP_CLOCK, OP_FRAME, OP_DUMP, OP_SETUSER, OP_CALSET, OP_CALGET,
    OP_CHOOSEDZ, OP_FIND, OP_FINDNAME, OP_AVAIL, OP_CHOOSECFG, OP_BUTTON,
    OP_BUTTONEV, OP_CONFIGURABLE, OP_EVNAME, OP_MAKELOG, OP_ADDLOG,
    OP_GETLOG, OP_REPLAY, OP_FEED, OP_JOYLOG, OP_NODE, OP_SCAN, OP_SETJOY,
    OP_QRESET, OP_QREMOVE, OP_CURTYPE, OP_TYPEQ, OP_RING, OP_DESTROY
};

#define N_HANDLERS 8
#define H_TC 8
#define H_NULL 9

// ------------------------------------------------------------ the script

static int32_t *words_in;
static size_t   nwords_in;
static size_t   rd;

static int32_t next(void)
{
    if (rd >= nwords_in) {
        fprintf(stderr, "ops: ran off the end\n");
        exit(2);
    }
    return words_in[rd++];
}

static char **read_strings(int32_t *count)
{
    int32_t n = next();
    char  **out = calloc((size_t)n + 1, sizeof(char *));
    int32_t i;

    for (i = 0; i < n; i++) {
        int32_t len = next();
        int32_t k;

        out[i] = malloc((size_t)len + 1);
        for (k = 0; k < len; k++)
            out[i][k] = (char)next();
        out[i][len] = 0;
    }
    *count = n;
    return out;
}

// ---------------------------------------------------- the slot pool stand-in

static BSlotPool fake_pool;
static void    **blocks;
static int32_t   nblocks;

static const char *pool_name(const BSlotPool *p)
{
    return p == &fake_pool ? "ok" : (p == NULL ? "null" : "?");
}

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *name,
                        int memoryPool)
{
    // The image's EventNode is 36 bytes; this host's is wider.
    printf("pool new slot %d n %d name %s mp %d\n",
           slotSize == (int)sizeof(EventNode) ? 36 : slotSize, numSlots,
           name ? name : "(null)", memoryPool);
    return &fake_pool;
}

void *bSlotOMalloc(BSlotPool *pool)
{
    void *p = malloc(sizeof(EventNode));

    memset(p, 0xa5, sizeof(EventNode));
    blocks = realloc(blocks, sizeof(void *) * (size_t)(nblocks + 1));
    blocks[nblocks] = p;
    printf("  alloc #%d pool %s\n", nblocks, pool_name(pool));
    nblocks++;
    return p;
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    int32_t i;

    for (i = 0; i < nblocks; i++)
        if (blocks[i] == slot)
            break;
    if (i < nblocks) {
        printf("  free #%d pool %s\n", i, pool_name(pool));
        // Never reused: a read after the free reads 0xdd, as on the image.
        memset(slot, 0xdd, sizeof(EventNode));
    } else {
        printf("  free #? pool %s\n", pool_name(pool));
    }
}

void bDeleteSlotPool(BSlotPool *pool)
{
    printf("pool delete %s\n", pool_name(pool));
}

// ------------------------------------------------------- the platform read

static uint32_t pads[2][8];

static void pad_read(int32_t port, uint8_t *buf)
{
    int32_t i;

    for (i = 0; i < 32; i++)
        buf[i] = (uint8_t)(pads[port][i >> 2] >> (8 * (i & 3)));
}

// ------------------------------------------------------ the scripted feeds

static int32_t feed[2][4096];
static int32_t feed_len[2];
static int32_t feed_pos[2];

static int32_t pop(int32_t which)
{
    if (feed_pos[which] >= feed_len[which])
        return 0;
    return feed[which][feed_pos[which]++];
}

static ReplayManager the_rm;
static int32_t       the_repeat;

static int32_t rm_get(ReplayManager *rm, int32_t bits, int32_t ch)
{
    int32_t v = pop(0);

    printf("  rm get bits %d ch %d%s -> %d\n", bits, ch,
           rm == &the_rm ? "" : " rm?", v);
    return v;
}

static void rm_add(ReplayManager *rm, int32_t value, int32_t bits,
                   int32_t ch)
{
    printf("  rm add %d bits %d ch %d%s\n", value, bits, ch,
           rm == &the_rm ? "" : " rm?");
}

static int32_t jl_get(int32_t bits, int32_t ch)
{
    int32_t v = pop(1);

    printf("  jl get bits %d ch %d -> %d\n", bits, ch, v);
    return v;
}

static void jl_add(int32_t value, int32_t bits, int32_t ch)
{
    printf("  jl add %d bits %d ch %d\n", value, bits, ch);
}

// ------------------------------------------------------------ the handlers

static void handler(int32_t k, JoystickPort port, JoyEvent ev, uint8_t val,
                    void *obj)
{
    uint32_t o = (uint32_t)(uintptr_t)obj;

    printf("  call h%d port %d ev %d val %d obj %u\n", k, port, ev, val, o);
    if (k == 6)
        RemoveJoyHandler((JoystickPort)((o >> 8) & 0xff),
                         (JoyEvent)(o & 0xff));
}

static void h0(JoystickPort p, JoyEvent e, uint8_t v, void *o) { handler(0, p, e, v, o); }
static void h1(JoystickPort p, JoyEvent e, uint8_t v, void *o) { handler(1, p, e, v, o); }
static void h2(JoystickPort p, JoyEvent e, uint8_t v, void *o) { handler(2, p, e, v, o); }
static void h3(JoystickPort p, JoyEvent e, uint8_t v, void *o) { handler(3, p, e, v, o); }
static void h4(JoystickPort p, JoyEvent e, uint8_t v, void *o) { handler(4, p, e, v, o); }
static void h5(JoystickPort p, JoyEvent e, uint8_t v, void *o) { handler(5, p, e, v, o); }
static void h6(JoystickPort p, JoyEvent e, uint8_t v, void *o) { handler(6, p, e, v, o); }

static void h7(JoystickPort p, JoyEvent e, uint8_t v, void *o)
{
    uint32_t x = (uint32_t)(uintptr_t)o;

    handler(7, p, e, v, o);
    AddJoyHandler((JoystickPort)((x >> 8) & 0xff), (JoyEvent)(x & 0xff), h0,
                  (void *)(uintptr_t)0x77);
}

static const JoyHandler HANDLERS[N_HANDLERS] = {h0, h1, h2, h3, h4, h5, h6,
                                                h7};

static JoyHandler hid_fn(int32_t hid)
{
    if (hid == H_TC)
        return TypeChangedHandler;
    if (hid == H_NULL)
        return NULL;
    return HANDLERS[hid];
}

static const char *hname(JoyHandler h)
{
    static char buf[8];
    int32_t     k;

    if (h == NULL)
        return "null";
    if (h == TypeChangedHandler)
        return "tc";
    for (k = 0; k < N_HANDLERS; k++)
        if (h == HANDLERS[k]) {
            snprintf(buf, sizeof(buf), "h%d", k);
            return buf;
        }
    return "?";
}

static int32_t cfg_row(const ScannerConfig *c)
{
    if (c == NULL)
        return -1;
    if (c >= ScannerConfigTable && c < ScannerConfigTable + NumScannerConfigs)
        return (int32_t)(c - ScannerConfigTable);
    return -2;
}

static uint32_t fbits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static const JoyScanner SCANNERS[] = {
    Scanner_TypeChanged, Scanner_DigitalAnyButton, Scanner_DigitalDown,
    Scanner_DigitalDownPlus, Scanner_DigitalUpOrDown,
    Scanner_DigitalUpOrDownPlus, Scanner_DigitalDoublePress,
    Scanner_DigitalRepeat, Scanner_DigitalSteer, Scanner_DigitalAnalog,
    Scanner_Analog,
};

// --------------------------------------------------------------- the prints

static void dump(int32_t port)
{
    Joystick *j = &JoystickArray[port];
    JoyLink  *l;
    int32_t   i;
    int32_t   n = 0;
    int32_t   m = 0;

    printf("joy %d port %d cur %d prev %d det %d user %d\n", port,
           j->PortNumber, j->CurrentType, j->PreviousType,
           j->NumValidTypeDetections, j->UserConfigurationNumber);
    for (i = 0; i < JOY_CALIBRATIONS; i++) {
        AnalogJoystickCalibration *c = &j->AnalogJoystickCalibrationTable[i];
        int32_t                    k;

        printf("  cal %d hyst %d n %d %s", i, c->HysterysisAmount,
               c->gCalibration.NumPoints,
               c->gCalibration.pPoints == c->vData ? "self" : "other");
        for (k = 0; k < 4; k++)
            printf(" %08x %08x", fbits(c->vData[k].x), fbits(c->vData[k].y));
        printf("\n");
    }
    for (l = j->EventNodeList.Next; l != &j->EventNodeList && n < 400;
         l = l->Next, n++) {
        const EventNode *e = (const EventNode *)l;

        printf("  node ev %d cfg %d pv %u ft %d up %d h %s obj %u\n",
               e->Event, cfg_row(e->Config), e->PreviousValue, e->FirstTime,
               e->UserParam, hname(e->Handler),
               (uint32_t)(uintptr_t)e->HandlerObject);
    }
    for (l = j->EventNodeList.Prev; l != &j->EventNodeList && m < 400;
         l = l->Prev)
        m++;
    printf("  nodes %d back %d\n", n, m);
}

static void queue(void)
{
    const QueuedJoystickEvents *q = &TheQueuedJoystickEvents;
    int32_t                     i;

    printf("queue %d\n", q->NumEvents);
    for (i = 0; i < q->NumEvents && i < JOY_MAX_QUEUED_EVENTS; i++) {
        const QueuedJoystickEvent *e = &q->Events[i];

        printf("  q port %d ev %d data %04x h %s obj %u\n", e->Port, e->Event,
               e->EventData, hname(e->Handler),
               (uint32_t)(uintptr_t)e->HandlerObject);
    }
}

static void ring(void)
{
    int32_t port;
    int32_t i;

    printf("ring top %d bot %d prep %d init %d\n", JoystickRingBufferTop,
           JoystickRingBufferBottom, JoystickRingBufferPreparedTop,
           JoypadInitialised);
    for (port = 0; port < 2; port++) {
        printf("  types %d", port);
        for (i = 0; i < JOYPAD_RING; i++)
            printf(" %d/%d", PadRingData[port][i].RegularControllerType,
                   PadRingData[port][i].LogitechDeviceID);
        printf("\n");
    }
}

static void after_frame(void)
{
    queue();
    printf("ring top %d bot %d prep %d\n", JoystickRingBufferTop,
           JoystickRingBufferBottom, JoystickRingBufferPreparedTop);
    printf("demo %d types %d %d jl %d %d\n",
           TheDemoDiscManager.LastActivityTime, CurrentJoystickTypes[0],
           CurrentJoystickTypes[1], Joylog_ReplayingFlag,
           Joylog_CapturingFlag);
    if (pReplayManager != NULL)
        printf("rm fnum %d\n", pReplayManager->FancyJoyEventNumber);
}

// ---------------------------------------------------------------- the loop

int main(int argc, char **argv)
{
    FILE         *fh;
    long          size;
    char        **tags;
    char        **names;
    int32_t       ntags;
    int32_t       nnames;
    size_t        end;
    EventNode     nodes[4];
    ScannerConfig cfg;
    uint32_t      data2[8] = {0};

    if (argc < 2) {
        fprintf(stderr, "usage: joystick_test ops.bin\n");
        return 2;
    }
    fh = fopen(argv[1], "rb");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
    fseek(fh, 0, SEEK_END);
    size = ftell(fh);
    fseek(fh, 0, SEEK_SET);
    words_in = malloc((size_t)size);
    nwords_in = (size_t)size / 4;
    if (fread(words_in, 4, nwords_in, fh) != nwords_in) {
        fprintf(stderr, "short read\n");
        return 2;
    }
    fclose(fh);

    tags = read_strings(&ntags);
    names = read_strings(&nnames);
    end = (size_t)next();
    end += rd;

    gJoypadRead = pad_read;
    gReplayManagerGetData = rm_get;
    gReplayManagerAddData = rm_add;
    gJoylogRepeatGetData = jl_get;
    gJoylogRepeatAddData = jl_add;
    memset(nodes, 0, sizeof(nodes));

    joyevent_static_init();

    while (rd < end) {
        int32_t op = next();

        switch (op) {
        case OP_TAG:
            printf("[%s]\n", tags[next()]);
            break;
        case OP_INIT:
            printf("init\n");
            InitJoystick();
            break;
        case OP_CLOSE:
            printf("close\n");
            CloseJoystick();
            break;
        case OP_ADD: {
            int32_t port = next(), ev = next(), hid = next(), obj = next();

            printf("add port %d ev %d h%d obj %d\n", port, ev, hid, obj);
            AddJoyHandler(port, ev, hid_fn(hid), (void *)(uintptr_t)(uint32_t)obj);
            break;
        }
        case OP_REMOVE: {
            int32_t port = next(), ev = next();

            printf("remove port %d ev %d\n", port, ev);
            RemoveJoyHandler(port, ev);
            break;
        }
        case OP_ISADDED: {
            int32_t port = next(), ev = next();

            printf("added port %d ev %d -> %d\n", port, ev,
                   IsJoyHandlerAdded(port, ev));
            break;
        }
        case OP_PAD: {
            int32_t port = next();
            int32_t i;

            for (i = 0; i < 8; i++)
                pads[port][i] = (uint32_t)next();
            break;
        }
        case OP_READ: {
            int32_t n = next();

            while (n-- > 0)
                ReadJoystickData();
            break;
        }
        case OP_CLOCK:
            FrameCounter = next();
            RealTimer = next();
            break;
        case OP_FRAME:
            printf("frame %d\n", FrameCounter);
            GenerateJoyEvents();
            after_frame();
            break;
        case OP_DUMP:
            dump(next());
            break;
        case OP_SETUSER: {
            int32_t port = next(), n = next();

            SetJoystickUserConfiguration(port, n);
            printf("user %d -> %d\n", port, GetJoystickUserConfiguration(port));
            break;
        }
        case OP_CALSET: {
            int32_t port = next(), dev = next(), lo = next(), hi = next();

            SetJoystickCalibration(port, dev, (uint8_t)lo, (uint8_t)hi);
            break;
        }
        case OP_CALGET: {
            int32_t port = next(), dev = next();
            uint8_t lo, hi;

            GetJoystickCalibration(port, dev, &lo, &hi);
            printf("cal get %d %d lo %d hi %d dz %d\n", port, dev, lo, hi,
                   GetJoystickDeadzone(port, dev));
            break;
        }
        case OP_CHOOSEDZ: {
            int32_t port = next(), cal = next(), type = next(), dev = next();
            AnalogJoystickCalibration *c =
                &JoystickArray[port].AnalogJoystickCalibrationTable[cal];

            ChooseDeadZoneAndHysterysis(c, type, dev);
            printf("dz %d %d type %d dev %d hyst %d k1 %08x k2 %08x\n", port,
                   cal, type, dev, c->HysterysisAmount, fbits(c->vData[1].x),
                   fbits(c->vData[2].x));
            break;
        }
        case OP_FIND: {
            int32_t ev = next(), type = next(), user = next();

            printf("find %d %d %d -> %d\n", ev, type, user,
                   cfg_row(FindScannerConfig(ev, type, user)));
            break;
        }
        case OP_FINDNAME: {
            int32_t     ni = next(), type = next(), user = next();
            const char *nm = ni < 0 ? NULL : names[ni];

            printf("findname %d %d %d -> %d\n", ni, type, user,
                   cfg_row(FindScannerConfigByName(nm, type, user)));
            break;
        }
        case OP_AVAIL: {
            int32_t type = next(), max = next();
            int32_t out[16];
            int32_t n;
            int32_t i;

            memset(out, 0xee, sizeof(out));
            n = DetermineAvailableJoystickConfigurations(out, max, type);
            printf("avail %d %d -> %d", type, max, n);
            for (i = 0; i < 12; i++)
                printf(" %d", out[i]);
            printf("\n");
            break;
        }
        case OP_CHOOSECFG: {
            int32_t type = next(), user = next();

            printf("choose %d %d -> %d\n", type, user,
                   ChooseJoystickConfigurationNumber(type, user));
            break;
        }
        case OP_BUTTON: {
            int32_t port = next(), ev = next();
            const char *nm = GetJoystickButtonName(port, ev);

            printf("button %d %d -> \"%s\" %d\n", port, ev, nm ? nm : "(null)",
                   GetJoystickButtonChar(port, ev));
            break;
        }
        case OP_BUTTONEV: {
            int32_t     port = next(), ni = next();
            const char *nm = ni < 0 ? NULL : names[ni];

            printf("bevent %d %d -> %d\n", port, ni,
                   GetJoystickButtonEvent(port, nm));
            break;
        }
        case OP_CONFIGURABLE: {
            int32_t ev = next();

            printf("configurable %d -> %d\n", ev, IsConfigurableRacingEvent(ev));
            break;
        }
        case OP_EVNAME: {
            int32_t ev = next();

            printf("evname %d -> %s\n", ev, GetJoyEventName(ev));
            break;
        }
        case OP_MAKELOG: {
            int32_t ev = next(), v = next(), port = next();

            printf("makelog %d %d %d -> %08x\n", ev, v, port,
                   MakeLoggedJoystickEvent(ev, (uint8_t)v, port));
            break;
        }
        case OP_ADDLOG: {
            uint32_t logged = (uint32_t)next();

            AddLoggedJoystickEvent(logged, &TheQueuedJoystickEvents, 1);
            printf("addlog %08x -> %d\n", logged,
                   TheQueuedJoystickEvents.NumEvents);
            break;
        }
        case OP_GETLOG: {
            int32_t i = next();

            printf("getlog %d -> %08x\n", i,
                   GetLoggedJoystickEvent(i, &TheQueuedJoystickEvents));
            break;
        }
        case OP_REPLAY: {
            int32_t present = next();
            int32_t i;

            the_rm.ReplayingFlag = next();
            the_rm.ReplayPausedThisFrame = next();
            the_rm.FancyReplayInProgress = next();
            the_rm.FancyJoyEventNumber = next();
            the_rm.NumFancyJoyEvents = next();
            for (i = 0; i < 8; i++) {
                uint32_t w = (uint32_t)next();

                the_rm.FancyJoyEventTable[4 * i + 0] = (uint8_t)w;
                the_rm.FancyJoyEventTable[4 * i + 1] = (uint8_t)(w >> 8);
                the_rm.FancyJoyEventTable[4 * i + 2] = (uint8_t)(w >> 16);
                the_rm.FancyJoyEventTable[4 * i + 3] = (uint8_t)(w >> 24);
            }
            pReplayManager = present ? &the_rm : NULL;
            break;
        }
        case OP_FEED: {
            int32_t which = next(), v = next();

            feed[which][feed_len[which]++] = v;
            break;
        }
        case OP_JOYLOG:
            Joylog_ReplayingFlag = next();
            Joylog_CapturingFlag = next();
            Joylog_pRepeat = next() ? (void *)&the_repeat : NULL;
            break;
        case OP_NODE: {
            int32_t    slot = next();
            EventNode *n = &nodes[slot];

            memset(n, 0, sizeof(*n));
            n->Event = next();
            n->Config = &cfg;
            n->PreviousValue = (uint32_t)next();
            n->FirstTime = next();
            n->UserParam = next();
            break;
        }
        case OP_SCAN: {
            int32_t    kind = next(), slot = next();
            EventNode *n = &nodes[slot];
            uint32_t   data[8];
            int32_t    port;
            int32_t    i;
            uint16_t   r;

            memset(&cfg, 0, sizeof(cfg));
            cfg.Event = n->Event;
            cfg.Scanner = SCANNERS[kind];
            cfg.Xor1 = (uint8_t)next();
            cfg.Xor2 = (uint8_t)next();
            cfg.Shift1 = (uint8_t)next();
            cfg.Shift2 = (uint8_t)next();
            cfg.Param = (uint8_t)next();
            cfg.AnalogDeviceNumber = (uint8_t)next();
            FrameCounter = next();
            port = next();
            for (i = 0; i < 8; i++)
                data[i] = (uint32_t)next();
            if (next())
                for (i = 0; i < 8; i++)
                    data2[i] = (uint32_t)next();
            r = SCANNERS[kind](n, data, data2, &cfg, &JoystickArray[port]);
            printf("scan %d -> %04x pv %u ft %d up %d\n", FrameCounter, r,
                   n->PreviousValue, n->FirstTime, n->UserParam);
            memcpy(data2, data, sizeof(data2));
            break;
        }
        case OP_SETJOY: {
            Joystick *j = &JoystickArray[next()];

            j->CurrentType = next();
            j->PreviousType = next();
            j->NumValidTypeDetections = next();
            break;
        }
        case OP_QRESET:
            TheQueuedJoystickEvents.NumEvents = 0;
            break;
        case OP_QREMOVE: {
            int32_t port = next(), ev = next();

            QueuedJoystickEvents_RemoveEvent(&TheQueuedJoystickEvents, port, ev);
            printf("qremove %d %d\n", port, ev);
            queue();
            break;
        }
        case OP_CURTYPE: {
            int32_t port = next(), type = next();

            CurrentJoystickTypes[port] = (uint8_t)type;
            break;
        }
        case OP_TYPEQ: {
            int32_t port = next();

            printf("typeq %d type %d plugged %d user %d wheel %d stiff %d\n",
                   port, GetJoystickType(port), IsJoystickPluggedIn(port),
                   GetJoystickUserConfiguration(port),
                   IsJoystickTypeWheel(port),
                   DoesJoystickHaveStiffThrottle(port));
            break;
        }
        case OP_RING:
            ring();
            break;
        case OP_DESTROY: {
            int32_t port = next();

            printf("destroy %d\n", port);
            Joystick_Destroy(&JoystickArray[port], 2);
            break;
        }
        default:
            fprintf(stderr, "unknown op %d at word %zu\n", op, rd - 1);
            return 2;
        }
    }
    (void)nnames;
    return 0;
}
