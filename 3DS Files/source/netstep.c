// netstep -- a local wireless race run in lockstep: see netstep.h.

#include "netstep.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#define MASK     (NETSTEP_RING - 1)
#define HEADER   15   // need (4), first (4), count, checksum's frame (4), it
#define PAD_WIRE 8    // the DualShock's six bytes, the presses (2)

static NetStep  s_own;
static NetStep* S = &s_own;

static void say(const char* fmt, ...)
{
    char    line[256];
    va_list ap;

    if (!S->log) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    S->log(line);
}

static void put32(uint8_t* b, uint32_t v)
{
    b[0] = (uint8_t)v;
    b[1] = (uint8_t)(v >> 8);
    b[2] = (uint8_t)(v >> 16);
    b[3] = (uint8_t)(v >> 24);
}

static uint32_t get32(const uint8_t* b)
{
    return (uint32_t)b[0] | (uint32_t)b[1] << 8 | (uint32_t)b[2] << 16
         | (uint32_t)b[3] << 24;
}

static int bits(uint8_t v)
{
    int n = 0;
    for (; v; v &= (uint8_t)(v - 1)) n++;
    return n;
}

void netstep_rest(NetStepPad* pad)
{
    pad->ds2[0] = 0xff;   // no button down
    pad->ds2[1] = 0xff;
    pad->ds2[2] = 0x80;   // the sticks centred
    pad->ds2[3] = 0x80;
    pad->ds2[4] = 0x80;
    pad->ds2[5] = 0x80;
    pad->menu   = 0;
}

static int padIn(int p, uint32_t n)
{
    return S->padFor[p][n & MASK] == n;
}

static int recIn(uint32_t n)
{
    return S->recs[n & MASK].n == n;
}

// Another place's console still there, by its link (a client asks only of
// the host's).
static int alive(int p)
{
    return S->net.peerAlive(S->peer[p]);
}

static void encodePad(uint8_t* b, const NetStepPad* pad)
{
    memcpy(b, pad->ds2, NETSTEP_PAD_BYTES);
    b[6] = (uint8_t)pad->menu;
    b[7] = (uint8_t)(pad->menu >> 8);
}

static void decodePad(NetStepPad* pad, const uint8_t* b)
{
    memcpy(pad->ds2, b, NETSTEP_PAD_BYTES);
    pad->menu = (uint16_t)(b[6] | b[7] << 8);
}

// ------------------------------------------------------------ the records

// Record `n`: the step, the places racing, the pad of each that is in.
static void buildRecord(uint32_t n, uint8_t live, uint8_t q)
{
    NetStepFrame* r = &S->recs[n & MASK];
    int           p;

    r->q    = q;
    r->live = live;
    for (p = 0; p < NETSTEP_MAX; p++) {
        if (((live >> p) & 1) && padIn(p, n))
            r->pad[p] = S->pads[p][n & MASK];
        else
            netstep_rest(&r->pad[p]);
    }
    r->n = n;
}

// The host's: each record whose pads are all in, in order.
static void hostBuild(void)
{
    while (S->built < S->put) {
        uint32_t n = S->built;
        int      p;

        for (p = 0; p < NETSTEP_MAX; p++)
            if (((S->live >> p) & 1) && !padIn(p, n)) return;
        buildRecord(n, S->live, S->q[n & MASK]);
        S->built++;
        for (p = 0; p < NETSTEP_MAX; p++) S->fresh[p] = 1;
    }
}

// A client's alone: its own pad on its place, the rest at rest.
static void aloneBuild(void)
{
    while (S->built < S->put) {
        buildRecord(S->built, S->live, S->q[S->built & MASK]);
        S->built++;
    }
}

// ------------------------------------------------------------ checksums

// The checksum after the last frame run: before the first, frame
// NETSTEP_NONE's, which no one checks.
static void putHash(uint8_t* b)
{
    uint32_t last = S->frame - 1;

    put32(b, last);
    b[4] = (uint8_t)S->hash[last & MASK];
    b[5] = (uint8_t)(S->hash[last & MASK] >> 8);
}

// Place `p`'s checksum of frame `n` against this console's, once both
// are in: whichever of the two runs it last.
static void checkHash(int p, uint32_t n)
{
    uint32_t i = n & MASK;

    if (S->theirFor[p][i] != n || S->hashFor[i] != n || S->differs[p])
        return;
    if (S->theirHash[p][i] == S->hash[i]) return;
    S->differs[p] = 1;
    say("netstep: frame %lu differs from place %d's: %04x here, %04x there",
        (unsigned long)n, p, S->hash[i], S->theirHash[p][i]);
    if (S->differ) S->differ(p, n);
}

static void takeHash(int p, const uint8_t* b)
{
    uint32_t n = get32(b);

    if (n == NETSTEP_NONE) return;   // none run yet
    S->theirHash[p][n & MASK] = (uint16_t)(b[4] | b[5] << 8);
    S->theirFor[p][n & MASK]  = n;
    checkHash(p, n);
}

// ------------------------------------------------------------ the host's

static void takePads(int p, const WlMsg* m)
{
    const uint8_t* d = m->data;
    uint32_t       need, first;
    int            count, i;

    // One its pads do not fill is dropped.
    count = d[8];
    if (m->len != HEADER + (size_t)count * PAD_WIRE) return;
    need  = get32(d);
    first = get32(d + 4);
    if (need > S->need[p]) S->need[p] = need;
    takeHash(p, d + 9);
    for (i = 0; i < count; i++) {
        uint32_t n = first + (uint32_t)i;

        // Past ones too, by the wrap: only the ring's from the next record.
        if (n - S->built >= NETSTEP_RING) continue;
        decodePad(&S->pads[p][n & MASK], d + HEADER + (size_t)i * PAD_WIRE);
        S->padFor[p][n & MASK] = n;
    }
}

// To client `p`: its pads from the next record on, and the records from
// the first it has yet to get, as many as fit. It has said it has no more
// than the host built, and the host can build no further than its pads.
static void sendFrames(int p, uint32_t now)
{
    uint8_t  b[WL_MSG_MAX];
    uint32_t first = S->need[p], n;
    size_t   o = HEADER;
    int      count = 0;

    put32(b, S->built);
    put32(b + 4, first);
    for (n = first; n < S->built; n++) {
        const NetStepFrame* r = &S->recs[n & MASK];
        size_t size = 2 + (size_t)bits(r->live) * PAD_WIRE;
        int    q;

        if (o + size > WL_MSG_MAX) break;
        b[o++] = r->q;
        b[o++] = r->live;
        for (q = 0; q < NETSTEP_MAX; q++) {
            if (!((r->live >> q) & 1)) continue;
            encodePad(b + o, &r->pad[q]);
            o += PAD_WIRE;
        }
        count++;
    }
    b[8] = (uint8_t)count;
    putHash(b + 9);
    if (!S->net.send(S->peer[p], NETSTEP_MSG_FRAMES, b, o)) S->sendFails++;
    S->lastSend[p] = now;
    S->fresh[p]    = 0;
}

static void hostPoll(uint32_t now)
{
    WlMsg m;
    int   p;

    for (p = 0; p < NETSTEP_MAX; p++) {
        if (p == S->place || S->peer[p] < 0) continue;
        while (S->net.recv(S->peer[p], &m))
            if (m.type == NETSTEP_MSG_PADS) takePads(p, &m);
    }
    for (p = 0; p < NETSTEP_MAX; p++) {
        if (p == S->place || !((S->live >> p) & 1) || alive(p)) continue;
        S->live &= (uint8_t)~(1u << p);
        say("netstep: place %d is gone, from frame %lu", p,
            (unsigned long)S->built);
    }
    hostBuild();
    for (p = 0; p < NETSTEP_MAX; p++) {
        if (p == S->place || !((S->live >> p) & 1)) continue;
        if (S->fresh[p] || now - S->lastSend[p] >= NETSTEP_RESEND_MS)
            sendFrames(p, now);
    }
}

// ------------------------------------------------------------ a client's

static void takeFrames(const WlMsg* m)
{
    const uint8_t* d = m->data;
    uint32_t       need, first;
    size_t         o;
    int            count, i;

    // The records' lengths first: one they do not add up to is dropped.
    count = d[8];
    for (i = 0, o = HEADER; i < count && o + 2 <= m->len; i++)
        o += 2 + (size_t)bits(d[o + 1]) * PAD_WIRE;
    if (i < count || o != m->len) return;
    need  = get32(d);
    first = get32(d + 4);
    if (need > S->padNeed) S->padNeed = need;
    takeHash(0, d + 9);
    for (i = 0, o = HEADER; i < count; i++) {
        uint32_t     n = first + (uint32_t)i;
        NetStepFrame r;
        int          p;

        r.q    = d[o];
        r.live = d[o + 1];
        o += 2;
        for (p = 0; p < NETSTEP_MAX; p++) {
            if ((r.live >> p) & 1) {
                decodePad(&r.pad[p], d + o);
                o += PAD_WIRE;
            } else {
                netstep_rest(&r.pad[p]);
            }
        }
        r.n = n;
        // Past ones too, by the wrap: only the ring's from the frame to run.
        if (n - S->frame >= NETSTEP_RING) continue;
        S->recs[n & MASK] = r;
    }
    while (recIn(S->built)) S->built++;
}

// To the host: the records still wanted, and this console's pads from the
// first it still needs, as many as fit. The host built no further than
// them, and they run no further than NETSTEP_DELAY past its records.
static void sendPads(uint32_t now)
{
    uint8_t  b[WL_MSG_MAX];
    uint32_t first = S->padNeed, n;
    size_t   o = HEADER;
    int      count = 0;

    put32(b, S->built);
    put32(b + 4, first);
    for (n = first; n < S->put && o + PAD_WIRE <= WL_MSG_MAX; n++) {
        encodePad(b + o, &S->pads[S->place][n & MASK]);
        o += PAD_WIRE;
        count++;
    }
    b[8] = (uint8_t)count;
    putHash(b + 9);
    if (!S->net.send(S->peer[0], NETSTEP_MSG_PADS, b, o)) S->sendFails++;
    S->lastSend[S->place] = now;
}

static void clientPoll(uint32_t now)
{
    WlMsg m;

    if (!S->alone) {
        while (S->net.recv(S->peer[0], &m))
            if (m.type == NETSTEP_MSG_FRAMES) takeFrames(&m);
        if (!alive(0)) {
            S->alone = 1;
            S->live  = (uint8_t)(1u << S->place);
            say("netstep: the host is gone, from frame %lu; racing alone",
                (unsigned long)S->built);
        }
    }
    if (S->alone) {
        aloneBuild();
        return;
    }
    // A new pad goes at once with no more: it is put at the frame's
    // start, a frame past the last poll's send.
    if (now - S->lastSend[S->place] >= NETSTEP_RESEND_MS) sendPads(now);
}

// ------------------------------------------------------------ the race's

void netstep_bind(NetStep* s)
{
    S = s ? s : &s_own;
}

void netstep_init(const NetStepNet* net, NetStepLogFn log)
{
    memset(S, 0, sizeof *S);
    if (net) S->net = *net;
    S->log = log;
}

void netstep_on_differ(NetStepDifferFn fn)
{
    S->differ = fn;
}

void netstep_start(int place, int consoles, const int peer[NETSTEP_MAX],
                   uint8_t racing)
{
    NetStepNet      net    = S->net;
    NetStepLogFn    log    = S->log;
    NetStepDifferFn differ = S->differ;
    uint32_t     n;
    int          p, i;

    memset(S, 0, sizeof *S);
    S->net    = net;
    S->log    = log;
    S->differ = differ;
    S->on     = 1;
    S->host   = place == 0;
    S->place  = place;
    for (p = 0; p < NETSTEP_MAX; p++) {
        S->peer[p] = p < consoles ? peer[p] : -1;
        for (i = 0; i < NETSTEP_RING; i++) {
            S->padFor[p][i]   = NETSTEP_NONE;
            S->theirFor[p][i] = NETSTEP_NONE;
        }
    }
    // Every record's frame is 0 from the clear, and record 0 is built
    // below, so no other is in; no checksum is.
    for (i = 0; i < NETSTEP_RING; i++) S->hashFor[i] = NETSTEP_NONE;
    // A place already gone is dropped at the host's first poll.
    S->live = racing;
    // The first frames, every console's own: no pad is in for them.
    for (n = 0; n < NETSTEP_DELAY; n++)
        buildRecord(n, S->live, NETSTEP_Q_FIRST);
    S->built = NETSTEP_DELAY;
    S->put   = NETSTEP_DELAY;
    say("netstep: start, place %d, racing %02x, delay %d", place,
        (unsigned)S->live, NETSTEP_DELAY);
}

void netstep_stop(void)
{
    if (!S->on) return;
    say("netstep: stop at frame %lu, %lu sends refused",
        (unsigned long)S->frame, (unsigned long)S->sendFails);
    S->on = 0;
}

int netstep_on(void)
{
    return S->on;
}

void netstep_put(const NetStepPad* pad, uint8_t q)
{
    uint32_t i = S->put & MASK;

    if (!S->on) return;
    S->pads[S->place][i]   = *pad;
    S->padFor[S->place][i] = S->put;
    S->q[i]                = q;
    S->put++;
}

int netstep_poll(uint32_t now)
{
    if (!S->on) return 0;
    if (S->host) hostPoll(now);
    else clientPoll(now);
    if (!S->settled && S->built >= NETSTEP_DELAY + NETSTEP_SETTLE) {
        S->settled = 1;
        S->net.setPatience(0);
        say("netstep: frames flow, the link's own timeout back at frame %lu",
            (unsigned long)S->frame);
    }
    return recIn(S->frame);
}

const NetStepFrame* netstep_current(void)
{
    return S->on && recIn(S->frame) ? &S->recs[S->frame & MASK] : NULL;
}

void netstep_done(uint16_t hash)
{
    uint32_t n = S->frame;
    int      p;

    S->hash[n & MASK]    = hash;
    S->hashFor[n & MASK] = n;
    if (n % NETSTEP_LOG_EVERY == 0)
        say("netstep: frame %lu hash %04x", (unsigned long)n, hash);
    for (p = 0; p < NETSTEP_MAX; p++) checkHash(p, n);
    S->frame++;
}

uint32_t netstep_frame(void)
{
    return S->frame;
}
