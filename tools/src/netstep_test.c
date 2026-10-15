// Host harness for a local wireless race in lockstep (netstep.c, TASKS 37d).
//
// Builds "3DS Files/source/netstep.c" and runs up to eight consoles of it
// in one process, each with its own NetStep (netstep_bind), on one clock
// in milliseconds. Console 0 hosts; console p is place p. Between them is
// a fake of the link's unreliable messages: each takes the scenario's
// latency and jitter (so they overtake each other), and some are lost or
// come twice; in one scenario netrace's own messages go with them. The
// host's peers are numbered the other way round from the places, and the
// peers past the consoles are junk. A link is lost once the console at
// its other end has not pumped it for the link's timeout: the patience
// the race set, or its own 3 s once netstep gave it back. A console pumps
// every millisecond but when it is gone, or in its first frame's drawing.
//
// Each console does what main.c's frame does: at the frame's start it
// puts its pad for the frame NETSTEP_DELAY ahead with the step it
// measured (the time since its last frame began, in 1/3600 s, clamped as
// PrepareRealTimestep clamps it), then polls each millisecond until the
// frame's record is in, runs it, and says its checksum: a running hash of
// every record it ran. A frame takes the scenario's time, and the first
// can stall for seconds, as the race's first drawing does. Each pad is a
// function of its place and frame, so any console's record can be
// checked against what was put.
//
// Checked, with a FAULT for each found:
//
//   - each console runs frames 0, 1, 2... in order;
//   - frames 0 to NETSTEP_DELAY - 1: the first step, every pad at rest;
//   - every later record: the step the host put for it, each live place's
//     pad as that place put it, every other at rest; a client alone, its
//     own step and pad, the rest at rest;
//   - every console's record of a frame the same as every other's, but a
//     client's alone;
//   - the places racing: never one that is not, one gone dropped once and
//     never back, none dropped that is on;
//   - every message no longer than WL_MSG_MAX, to a peer there is, a
//     client's PADS and the host's FRAMES only, none from a client alone,
//     and no link with more than MAX_RATE a second;
//   - the link's patience kept until frames flow, and then its own given
//     back once;
//   - the log: a checksum every NETSTEP_LOG_EVERY frames, "differs" only
//     where the scenario makes a console's checksum differ, once for each
//     place, and the gone and alone lines as the scenario has them;
//   - every console still on reaching the scenario's last frame, and on a
//     clean link, a fast one or a slow, no frame waited on long;
//   - after netstep_stop nothing is in.
//
// The last line is "total faults N".

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "netstep.h"

#define MAXC      NETSTEP_MAX
#define MAXFRAMES 1200
#define PIPE      512
#define LINES     64
#define LINK_MS   3000u
#define PATIENCE  30000u
#define MAX_RATE  120     // messages a second on a link

typedef struct {
    const char* name;
    int         consoles;
    int         frames;       // each console still on runs these
    int         latency;      // ms
    int         jitter;       // ms, more at random
    int         lossPct;      // messages lost
    int         dupPct;       // messages twice
    int         period[MAXC]; // ms a frame; 0: 33
    int         firstStall[MAXC];   // ms the first frame takes, 0: none
    int         startLate[MAXC];    // ms its GO came after the first's
    int         goneAt[MAXC];       // ms a console goes, 0: never
    int         notRacing;          // places that do not race, a bit each:
                                    // consoles gone before the build
    int         outageFrom, outageTo;   // ms every message is lost
    int         divergeAt[MAXC];    // frame its checksum is made to differ
    int         stopAt;             // frame console 0 stops at, 0: never
    int         maxWait;            // ms a frame may wait on, 0: no check
    int         maxRun;             // ms all its frames may take, 0: any
    int         stray;              // ms between netrace's messages, 0: none
} Scenario;

static const Scenario kScenarios[] = {
    { .name = "two, a clean link", .consoles = 2, .frames = 600,
      .latency = 5, .maxWait = 120 },
    // Records and pads go as soon as they are in: 48 ms each way leaves
    // the delay's 99 ms 3.
    { .name = "two, a slow link", .consoles = 2, .frames = 400,
      .latency = 48, .maxWait = 6 },
    // 60 ms each way is more than the delay's 99 ms: every frame waits on
    // the link, and a record or pad held back makes the race slower:
    // 11.4 s as it is.
    { .name = "two, a link slower than the delay", .consoles = 2,
      .frames = 300, .latency = 60, .maxRun = 12000 },
    { .name = "two, the client starts late", .consoles = 2, .frames = 300,
      .latency = 5, .startLate = { 0, 600 } },
    { .name = "two, a lossy link", .consoles = 2, .frames = 600,
      .latency = 4, .jitter = 20, .lossPct = 20, .dupPct = 5 },
    { .name = "two, the host slow", .consoles = 2, .frames = 400,
      .latency = 5, .period = { 50, 20 }, .maxWait = 150 },
    { .name = "two, the client slow", .consoles = 2, .frames = 400,
      .latency = 5, .period = { 20, 55 }, .maxWait = 150 },
    { .name = "two, the first frame's drawing", .consoles = 2,
      .frames = 300, .latency = 5, .firstStall = { 4000, 9000 } },
    { .name = "eight, a lossy link", .consoles = 8, .frames = 400,
      .latency = 3, .jitter = 15, .lossPct = 15, .dupPct = 5,
      .period = { 33, 30, 36, 33, 40, 28, 33, 35 } },
    { .name = "three, place 2 gone", .consoles = 3, .frames = 500,
      .latency = 5, .goneAt = { 0, 0, 3000 } },
    { .name = "two, the client gone", .consoles = 2, .frames = 500,
      .latency = 5, .goneAt = { 0, 4000 } },
    { .name = "two, the host gone", .consoles = 2, .frames = 500,
      .latency = 5, .goneAt = { 4000, 0 } },
    { .name = "three, the host gone", .consoles = 3, .frames = 500,
      .latency = 5, .jitter = 10, .lossPct = 10, .goneAt = { 5000, 0, 0 } },
    { .name = "two, a checksum differs", .consoles = 2, .frames = 400,
      .latency = 5, .divergeAt = { 0, 200 } },
    // The client runs ahead, so each checksum comes to the host before
    // the host has run its frame, and to the client after.
    { .name = "two, the host slow, a checksum differs", .consoles = 2,
      .frames = 400, .latency = 5, .period = { 50, 20 },
      .divergeAt = { 0, 200 } },
    { .name = "two, a second of nothing", .consoles = 2, .frames = 400,
      .latency = 5, .outageFrom = 3000, .outageTo = 4000 },
    { .name = "three, place 1 not racing", .consoles = 3, .frames = 300,
      .latency = 5, .notRacing = 0x02 },
    { .name = "two, the host stops", .consoles = 2, .frames = 200,
      .latency = 5, .stopAt = 150 },
    { .name = "four, all gone but the host", .consoles = 4, .frames = 400,
      .latency = 5, .goneAt = { 0, 2000, 3000, 2500 } },
    { .name = "three, netrace's messages too", .consoles = 3, .frames = 300,
      .latency = 5, .jitter = 10, .stray = 7 },
};

typedef struct {
    int      used;
    uint32_t due;
    WlMsg    m;
} InFlight;

typedef struct {
    InFlight q[PIPE];
} Pipe;

typedef struct {
    NetStep      ns;
    int          gone;
    int          stopped;
    int          waiting;        // put, and polling for the frame
    uint32_t     startAt;        // when the next frame starts
    uint32_t     lastStart;
    uint32_t     waitFrom;
    uint32_t     maxWaited;
    uint32_t     ran;            // frames run
    uint32_t     doneAt;         // ms it ran its last
    uint32_t     acc;            // the running hash
    uint32_t     patience;       // as last set, 0 the link's own
    int          patienceSets;
    int          aloneFrom;      // the first record made alone, or -1
    uint8_t      liveSeen;       // the places live in its last record
    int          wasLive[MAXC];
    int          sent;           // messages this tick
    uint32_t     sends;          // and all of them
    uint32_t     pumped;         // ms its loop last pumped the link
    char         lines[LINES][160];
    int          numLines;
    int          lineCount;      // all of them, kept or not
    int          differs, goneLines, aloneLines, flowLines, hashLines;
    int          told;           // NetStepDifferFn calls
    int          saidPlace;      // the last "differs" line's, -1 none yet
    unsigned long saidFrame;
    int          goneSaid[MAXC];
    uint8_t      q[MAXFRAMES + NETSTEP_DELAY + 2];   // its steps put
} Console;

typedef struct {
    int          in;
    NetStepFrame r;
} Truth;

static Console         C[MAXC];
static Pipe            g_pipe[MAXC][MAXC];   // [from][to]
static Truth           g_truth[MAXFRAMES + 8];
static const Scenario* S;
static int             g_cur = -1;
static uint32_t        g_now;
static int             g_faults;
static uint32_t        g_lcg;

static void fault(const char* fmt, ...)
{
    va_list ap;

    printf("  FAULT [%s, console %d, %lu ms] ", S ? S->name : "-", g_cur,
           (unsigned long)g_now);
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    printf("\n");
    g_faults++;
}

static uint32_t lcg(void)
{
    g_lcg = g_lcg * 1664525u + 1013904223u;
    return g_lcg >> 8;
}

static void enter(int c)
{
    g_cur = c;
    netstep_bind(&C[c].ns);
}

// ------------------------------------------------------------ the pads

static void padOf(int place, uint32_t n, NetStepPad* pad)
{
    uint32_t h = (uint32_t)place * 2654435761u ^ n * 40503u ^ 0x5bd1e995u;
    int      i;

    for (i = 0; i < NETSTEP_PAD_BYTES; i++) {
        h = h * 1103515245u + 12345u;
        pad->ds2[i] = (uint8_t)(h >> 16);
    }
    h = h * 1103515245u + 12345u;
    pad->menu = (uint16_t)(h >> 12);
}

static int samePad(const NetStepPad* a, const NetStepPad* b)
{
    return !memcmp(a->ds2, b->ds2, NETSTEP_PAD_BYTES) && a->menu == b->menu;
}

// A DualShock let go: no button down (they are active low), the sticks
// centred; no presses for the flow.
static int atRest(const NetStepPad* p)
{
    static const NetStepPad kRest = {
        { 0xff, 0xff, 0x80, 0x80, 0x80, 0x80 }, 0 };

    return samePad(p, &kRest);
}

static int sameFrame(const NetStepFrame* a, const NetStepFrame* b)
{
    int p;

    if (a->n != b->n || a->q != b->q || a->live != b->live) return 0;
    for (p = 0; p < MAXC; p++)
        if (!samePad(&a->pad[p], &b->pad[p])) return 0;
    return 1;
}

// ------------------------------------------------------------ the link

// The host's peer i is place consoles - 1 - i; a client's one, the host.
static int peerOf(int place)
{
    return S->consoles - 1 - place;
}

static int target(int c, int i)
{
    if (c != 0) return i == 0 ? 0 : -1;
    if (i < 0 || i >= S->consoles - 1) return -1;
    return S->consoles - 1 - i;
}

static int fPeerAlive(int i)
{
    int      t = target(g_cur, i);
    uint32_t timeout;

    if (t < 0) return 0;
    timeout = C[g_cur].patience ? C[g_cur].patience : LINK_MS;
    return g_now - C[t].pumped < timeout;
}

static int fSend(int i, uint8_t type, const void* data, size_t n)
{
    int  t = target(g_cur, i);
    int  k, copies;
    Pipe* p;

    if (t < 0) {
        fault("sent to peer %d, which is not there", i);
        return 0;
    }
    if (n > WL_MSG_MAX) {
        fault("a message of %u bytes", (unsigned)n);
        return 0;
    }
    if (g_cur == 0 ? type != NETSTEP_MSG_FRAMES : type != NETSTEP_MSG_PADS)
        fault("sent message type %02x", type);
    if (C[g_cur].aloneFrom >= 0) fault("sent alone");
    if (C[g_cur].sent >= WL_UNREL_MAX) return 0;   // the packet is full
    C[g_cur].sent++;
    C[g_cur].sends++;
    if (C[t].gone || C[t].stopped) return 1;
    if (S->outageFrom && g_now >= (uint32_t)S->outageFrom
        && g_now < (uint32_t)S->outageTo)
        return 1;
    if ((int)(lcg() % 100) < S->lossPct) return 1;
    copies = (int)(lcg() % 100) < S->dupPct ? 2 : 1;
    p = &g_pipe[g_cur][t];
    while (copies--) {
        for (k = 0; k < PIPE && p->q[k].used; k++) {
        }
        if (k == PIPE) {
            fault("the pipe %d to %d is full", g_cur, t);
            return 0;
        }
        p->q[k].used   = 1;
        p->q[k].due    = g_now + (uint32_t)S->latency
                       + (S->jitter ? lcg() % (uint32_t)S->jitter : 0);
        p->q[k].m.seq  = WL_UNRELIABLE;
        p->q[k].m.type = type;
        p->q[k].m.len  = (uint8_t)n;
        memcpy(p->q[k].m.data, data, n);
    }
    return 1;
}

// The first due message from peer i, the earliest first.
static int fRecv(int i, WlMsg* out)
{
    int   t = target(g_cur, i);
    Pipe* p;
    int   k, best = -1;

    if (t < 0) {
        fault("read from peer %d, which is not there", i);
        return 0;
    }
    p = &g_pipe[t][g_cur];
    for (k = 0; k < PIPE; k++) {
        if (!p->q[k].used || (int32_t)(g_now - p->q[k].due) < 0) continue;
        if (best < 0 || (int32_t)(p->q[k].due - p->q[best].due) < 0)
            best = k;
    }
    if (best < 0) return 0;
    *out = p->q[best].m;
    p->q[best].used = 0;
    return 1;
}

// One of netrace's own messages on the race's link, which netstep leaves
// alone: anything in it, and every other one shaped as the netstep
// message its receiver takes (to the host a client's pads, to a client the
// host's records), so only the type tells them apart.
static void stray(int from, int to)
{
    static int shaped;
    Pipe*      p = &g_pipe[from][to];
    WlMsg*     m;
    int        k, i, n;
    size_t     len;

    if (C[from].gone || C[from].stopped) return;
    for (k = 0; k < PIPE && p->q[k].used; k++) {
    }
    if (k == PIPE) return;
    p->q[k].used = 1;
    p->q[k].due  = g_now + (uint32_t)S->latency;
    m            = &p->q[k].m;
    m->seq       = WL_UNRELIABLE;
    m->type      = (uint8_t)(0x10 + lcg() % 6);
    for (i = 0; i < WL_MSG_MAX; i++) m->data[i] = (uint8_t)lcg();
    shaped = !shaped;
    if (!shaped) {
        m->len = (uint8_t)(15 + lcg() % 60);
        return;
    }
    n = to == 0 ? (int)(lcg() % 4) : 1 + (int)(lcg() % 3);
    m->data[8] = (uint8_t)n;
    len = 15;
    for (i = 0; i < n; i++) {
        if (to == 0) {
            len += 8;
            continue;
        }
        m->data[len + 1] = (uint8_t)(1 + lcg() % 255);   // live
        len += 2;
        for (k = 0; k < NETSTEP_MAX; k++)
            if ((m->data[len - 1] >> k) & 1) len += 8;
    }
    m->len = (uint8_t)len;
}

static void fSetPatience(uint32_t ms)
{
    C[g_cur].patience = ms;
    C[g_cur].patienceSets++;
}

static void fLog(const char* line)
{
    Console*      k = &C[g_cur];
    int           p;
    unsigned long n;
    unsigned      h;

    if (k->numLines < LINES)
        snprintf(k->lines[k->numLines++], sizeof k->lines[0], "%s", line);
    k->lineCount++;
    if (strstr(line, " differs from place ")) {
        k->differs++;
        if (sscanf(line, "netstep: frame %lu differs from place %d's", &n, &p)
            == 2) {
            k->saidPlace = p;
            k->saidFrame = n;
        }
    }
    if (sscanf(line, "netstep: place %d is gone, from frame %lu", &p, &n)
        == 2) {
        k->goneLines++;
        if (p >= 0 && p < MAXC) {
            if (k->goneSaid[p]) fault("place %d said gone twice", p);
            k->goneSaid[p] = 1;
        }
    }
    if (sscanf(line, "netstep: the host is gone, from frame %lu", &n) == 1) {
        k->aloneLines++;
        k->aloneFrom = (int)n;
    }
    if (strstr(line, "frames flow")) k->flowLines++;
    if (sscanf(line, "netstep: frame %lu hash %x", &n, &h) == 2) {
        k->hashLines++;
        if (n % NETSTEP_LOG_EVERY) fault("a checksum logged at frame %lu", n);
    }
}

// Told just after the log's line, of its place and frame, and of a frame
// this console made differ, or the place did.
static void fDiffer(int place, uint32_t frame)
{
    Console* k = &C[g_cur];

    k->told++;
    if (k->saidPlace != place || k->saidFrame != frame)
        fault("told of place %d, frame %lu; the line said %d, %lu", place,
              (unsigned long)frame, k->saidPlace, k->saidFrame);
    k->saidPlace = -1;
    if (place < 0 || place >= S->consoles || place == g_cur)
        fault("told of place %d", place);
    else if (!(S->divergeAt[g_cur] && frame >= (uint32_t)S->divergeAt[g_cur])
             && !(S->divergeAt[place]
                  && frame >= (uint32_t)S->divergeAt[place]))
        fault("told of frame %lu, before either diverged",
              (unsigned long)frame);
}

static const NetStepNet kNet = {
    .peerAlive   = fPeerAlive,
    .send        = fSend,
    .recv        = fRecv,
    .setPatience = fSetPatience,
};

// ------------------------------------------------------------ a frame

static int periodOf(int c)
{
    return S->period[c] ? S->period[c] : 33;
}

static uint8_t measure(int c)
{
    uint32_t ms = g_now - C[c].lastStart;
    uint32_t q  = (ms * 36 + 5) / 10;

    if (C[c].ran == 0) q = 0;   // no last frame: the clamp's least
    return (uint8_t)(q < 60 ? 60 : q > 180 ? 180 : q);
}

static void beginFrame(int c)
{
    Console*   k = &C[c];
    NetStepPad pad;
    uint32_t   n = netstep_frame() + NETSTEP_DELAY;
    uint8_t    q = measure(c);

    padOf(c, n, &pad);
    if (n < sizeof k->q) k->q[n] = q;
    netstep_put(&pad, q);
    k->lastStart = g_now;
    k->waiting   = 1;
    k->waitFrom  = g_now;
}

static void checkRecord(int c, const NetStepFrame* r)
{
    Console*   k = &C[c];
    NetStepPad want;
    int        alone = k->aloneFrom >= 0 && r->n >= (uint32_t)k->aloneFrom;
    int        p;

    if (r->n != k->ran) fault("ran frame %lu, not %lu", (unsigned long)r->n,
                              (unsigned long)k->ran);
    if (r->live & (uint8_t)~((1u << S->consoles) - 1u))
        fault("frame %lu: live %02x past the consoles", (unsigned long)r->n,
              r->live);
    if (r->live & S->notRacing)
        fault("frame %lu: live %02x with a place not racing",
              (unsigned long)r->n, r->live);
    if (!(r->live & (1u << c)))
        fault("frame %lu: this console's place not live", (unsigned long)r->n);
    if (r->n < NETSTEP_DELAY) {
        if (r->q != NETSTEP_Q_FIRST)
            fault("frame %lu: step %d", (unsigned long)r->n, r->q);
        for (p = 0; p < MAXC; p++)
            if (!atRest(&r->pad[p]))
                fault("frame %lu: place %d's pad not at rest",
                      (unsigned long)r->n, p);
        return;
    }
    if (alone) {
        if (r->live != (1u << c))
            fault("frame %lu alone: live %02x", (unsigned long)r->n, r->live);
        if (r->n < sizeof k->q && r->q != k->q[r->n])
            fault("frame %lu alone: step %d, put %d", (unsigned long)r->n,
                  r->q, k->q[r->n]);
    } else if (r->n < sizeof C[0].q && r->q != C[0].q[r->n]) {
        fault("frame %lu: step %d, the host put %d", (unsigned long)r->n,
              r->q, C[0].q[r->n]);
    }
    for (p = 0; p < MAXC; p++) {
        if ((r->live >> p) & 1) {
            padOf(p, r->n, &want);
            if (!samePad(&r->pad[p], &want))
                fault("frame %lu: place %d's pad not as put",
                      (unsigned long)r->n, p);
            if (k->wasLive[p] < 0)
                fault("frame %lu: place %d live again", (unsigned long)r->n,
                      p);
        } else {
            if (!atRest(&r->pad[p]))
                fault("frame %lu: place %d not live, its pad not at rest",
                      (unsigned long)r->n, p);
            if (k->wasLive[p] > 0) {
                k->wasLive[p] = -1;
                if (!C[p].gone && !alone)
                    fault("frame %lu: place %d dropped, still on",
                          (unsigned long)r->n, p);
            }
        }
        if (((r->live >> p) & 1) && k->wasLive[p] == 0) k->wasLive[p] = 1;
    }
    if (alone || r->n >= MAXFRAMES) return;
    if (!g_truth[r->n].in) {
        g_truth[r->n].in = 1;
        g_truth[r->n].r  = *r;
    } else if (!sameFrame(&g_truth[r->n].r, r)) {
        fault("frame %lu: not the record another console ran",
              (unsigned long)r->n);
    }
}

static void runFrame(int c)
{
    Console*            k = &C[c];
    const NetStepFrame* r = netstep_current();
    uint32_t            waited = g_now - k->waitFrom;
    uint16_t            h;
    int                 p;

    if (r == NULL) {
        fault("polled in, nothing current");
        return;
    }
    checkRecord(c, r);
    if (k->ran > 10 && waited > k->maxWaited) k->maxWaited = waited;
    k->acc = k->acc * 31u + r->n * 7u + r->q;
    for (p = 0; p < MAXC; p++) {
        k->acc = k->acc * 131u + (uint32_t)r->pad[p].ds2[0] * 3u
               + r->pad[p].ds2[4] + r->pad[p].menu;
    }
    h = (uint16_t)(k->acc ^ (k->acc >> 16));
    if (S->divergeAt[c] && r->n >= (uint32_t)S->divergeAt[c]) h ^= 0x5a5a;
    netstep_done(h);
    k->ran++;
    if (k->ran == (uint32_t)S->frames) k->doneAt = g_now;
    k->waiting = 0;
    k->startAt = g_now + (uint32_t)(k->ran == 1 && S->firstStall[c]
                                        ? S->firstStall[c] : periodOf(c));
    if (S->stopAt && c == 0 && k->ran == (uint32_t)S->stopAt) {
        netstep_stop();
        k->stopped = 1;
        if (netstep_on()) fault("on after netstep_stop");
        if (netstep_current() != NULL) fault("a frame after netstep_stop");
        if (netstep_poll(g_now)) fault("polled in after netstep_stop");
    }
}

// Its first frame's drawing, which stops its loop for seconds.
static int drawingFirst(int c)
{
    const Console* k = &C[c];

    return k->ran == 1 && S->firstStall[c] && !k->waiting
        && (int32_t)(g_now - k->startAt) < 0;
}

static void tick(int c)
{
    Console* k = &C[c];

    if (k->gone || k->stopped) return;
    // Done with its frames, a console still reads and answers, as it
    // would waiting on its next.
    if (k->ran >= (uint32_t)S->frames) {
        (void)netstep_poll(g_now);
        return;
    }
    if (!k->waiting && (int32_t)(g_now - k->startAt) >= 0) beginFrame(c);
    if (k->waiting && netstep_poll(g_now)) runFrame(c);
}

// ------------------------------------------------------------ a scenario

static int expectGone(int c, int p)
{
    // The host says each racing client gone; a client says none.
    return c == 0 && p != 0 && S->goneAt[p] && !(S->notRacing >> p & 1);
}

static void finish(void)
{
    int c, p, diverge = 0;

    for (p = 0; p < S->consoles; p++)
        if (S->divergeAt[p]) diverge = 1;
    for (c = 0; c < S->consoles; c++) {
        Console* k = &C[c];
        int      wantAlone = c != 0 && S->goneAt[0] && !S->goneAt[c];

        g_cur = c;
        if (k->gone) continue;
        if (!k->stopped && k->ran < (uint32_t)S->frames)
            fault("ran %lu of %d frames", (unsigned long)k->ran, S->frames);
        // A client whose host stopped waits on; main.c stops each
        // console's own at the same frame.
        if (!S->stopAt || c == 0) {
            if (k->flowLines != 1)
                fault("said frames flow %d times", k->flowLines);
            if (k->patience != 0 || k->patienceSets != 1)
                fault("patience %lu after %d sets", (unsigned long)k->patience,
                      k->patienceSets);
        }
        for (p = 0; p < MAXC; p++)
            if (k->goneSaid[p] != expectGone(c, p))
                fault("place %d gone said %d", p, k->goneSaid[p]);
        if (k->aloneLines != wantAlone)
            fault("said alone %d times", k->aloneLines);
        if (!diverge && k->differs)
            fault("said differs %d times", k->differs);
        if (diverge && !k->differs)
            fault("said nothing of the checksum that differs");
        if (k->differs > (c == 0 ? S->consoles - 1 : 1))
            fault("said differs %d times", k->differs);
        if (k->told != k->differs)
            fault("told %d times of %d differences", k->told, k->differs);
        if (k->hashLines < 1) fault("no checksum logged");
        if (S->maxWait && k->maxWaited > (uint32_t)S->maxWait)
            fault("waited %lu ms on a frame", (unsigned long)k->maxWaited);
        if (S->maxRun && k->doneAt - 1000u > (uint32_t)S->maxRun)
            fault("its frames took %lu ms",
                  (unsigned long)(k->doneAt - 1000u));
        {
            uint32_t ms    = g_now - 1000u;
            uint32_t links = c == 0 ? (uint32_t)S->consoles - 1u : 1u;
            uint32_t rate  = ms ? k->sends * 1000u / ms / links : 0;

            if (rate > MAX_RATE) fault("%lu messages a second on a link",
                                       (unsigned long)rate);
        }
    }
}

static void runScenario(const Scenario* s)
{
    int peers[MAXC];
    int c, p;

    S = s;
    memset(C, 0, sizeof C);
    memset(g_pipe, 0, sizeof g_pipe);
    memset(g_truth, 0, sizeof g_truth);
    g_lcg = 12345u;
    g_now = 1000;
    printf("scenario %s\n", s->name);
    for (c = 0; c < s->consoles; c++) {
        enter(c);
        netstep_init(&kNet, fLog);
        // Before GO, as main.c: netstep_start keeps it.
        netstep_on_differ(fDiffer);
        C[c].saidPlace = -1;
        if ((s->notRacing >> c) & 1) {
            C[c].gone = 1;
            continue;
        }
        C[c].patience  = PATIENCE;   // netrace's, from the lobby's start
        C[c].aloneFrom = -1;
        // Past the consoles, anything: netstep reads none of them.
        for (p = 0; p < MAXC; p++)
            peers[p] = p >= s->consoles ? 77
                     : c == 0 ? (p > 0 ? peerOf(p) : -1)
                              : (p == 0 ? 0 : -1);
        netstep_start(c, s->consoles, peers,
                      (uint8_t)(((1u << s->consoles) - 1u) & ~s->notRacing));
        if (!netstep_on()) fault("not on after netstep_start");
        C[c].startAt = g_now + (uint32_t)(lcg() % 40)
                     + (uint32_t)s->startLate[c];
    }
    for (; g_now < 1000u + 200000u; g_now++) {
        int busy = 0;

        for (c = 0; c < s->consoles; c++) {
            if (s->goneAt[c] && g_now == (uint32_t)s->goneAt[c])
                C[c].gone = 1;
            C[c].sent = 0;
            if (!C[c].gone && !drawingFirst(c)) C[c].pumped = g_now;
            if (c > 0 && s->stray && g_now % (uint32_t)s->stray == 0) {
                stray(0, c);
                stray(c, 0);
            }
        }
        for (c = 0; c < s->consoles; c++) {
            enter(c);
            tick(c);
            if (!C[c].gone && !C[c].stopped && C[c].ran < (uint32_t)s->frames)
                busy = 1;
        }
        if (!busy) break;
        if (s->stopAt && C[0].stopped && g_now > 60000u) break;
    }
    if (s->stopAt) {
        // The client waits for frames the stopped host will never send.
        C[1].stopped = 1;
    }
    finish();
    for (c = 0; c < s->consoles; c++)
        printf("  console %d: %lu frames in %lu ms, %d lines, waited %lu ms "
               "most%s\n", c, (unsigned long)C[c].ran,
               (unsigned long)(C[c].doneAt ? C[c].doneAt - 1000u : 0),
               C[c].lineCount, (unsigned long)C[c].maxWaited,
               C[c].gone ? ", gone" : "");
    for (c = 0; c < s->consoles; c++)
        for (p = 0; p < C[c].numLines && p < 6; p++)
            printf("  %d: %s\n", c, C[c].lines[p]);
}

int main(void)
{
    size_t i;
    int    before;

    for (i = 0; i < sizeof kScenarios / sizeof kScenarios[0]; i++) {
        before = g_faults;
        runScenario(&kScenarios[i]);
        printf("faults %d\n", g_faults - before);
    }
    printf("total faults %d\n", g_faults);
    return 0;
}
