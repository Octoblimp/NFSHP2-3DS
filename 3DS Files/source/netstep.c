// netstep -- a local wireless race run in lockstep: see netstep.h.

#include "netstep.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#define MASK     (NETSTEP_RING - 1)
#define HEADER   21   // need (4), first (4), count, checksum's frame (4), it
                      // (2), the stop (4), the hold: its places, its
                      // seconds left (the host's; a client's 0)
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

// The host's: a client still racing with it, which has not said it
// stopped.
static int serving(int p)
{
    return p != S->place && ((S->live >> p) & 1) && !S->left[p] && alive(p);
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

// The places the host holds for, and the ms left of the one lost first.
static uint8_t hostHeld(uint32_t now, uint32_t* msLeft)
{
    uint8_t  mask = 0;
    uint32_t left = 0;
    int      p;

    for (p = 0; p < NETSTEP_MAX; p++) {
        uint32_t since;

        if (!S->lost[p] || !((S->live >> p) & 1)) continue;
        since = now - S->lostAt[p];
        since = since < S->holdMs ? S->holdMs - since : 0;
        if (!mask || since < left) left = since;
        mask |= (uint8_t)(1u << p);
    }
    if (msLeft) *msLeft = left;
    return mask;
}

static void takePads(int p, const WlMsg* m)
{
    const uint8_t* d = m->data;
    uint32_t       need, first, stop;
    int            count, i;

    // One its pads do not fill is dropped.
    count = d[8];
    if (m->len != HEADER + (size_t)count * PAD_WIRE) return;
    need  = get32(d);
    first = get32(d + 4);
    stop  = get32(d + 15);
    if (need > S->need[p]) S->need[p] = need;
    takeHash(p, d + 9);
    if (stop != NETSTEP_NONE && !S->left[p]) {
        S->left[p] = 1;
        say("netstep: place %d stopped after %lu frames", p,
            (unsigned long)stop);
    }
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
    uint32_t first = S->need[p], n, left;
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
    put32(b + 15, S->stopAt);
    b[19] = hostHeld(now, &left);
    b[20] = (uint8_t)((left + 999) / 1000);
    if (!S->net.send(S->peer[p], NETSTEP_MSG_FRAMES, b, o)) S->sendFails++;
    S->lastSend[p] = now;
    S->fresh[p]    = 0;
}

// Each racing client's pads. Not those of one gone or stopped, nor any
// past a message not the race's: what it sends from its stop on is the
// lobby's, left on the link for it. One that came before its stop was
// heard says the client has gone on all the same.
static void hostRead(void)
{
    WlMsg m;
    int   p;

    for (p = 0; p < NETSTEP_MAX; p++) {
        if (!serving(p)) continue;
        while (!S->left[p] && S->net.peek(S->peer[p], &m)) {
            if (m.type != NETSTEP_MSG_PADS) {
                S->left[p] = 1;
                say("netstep: place %d has gone on, its stop unheard", p);
                break;
            }
            S->net.recv(S->peer[p], &m);
            takePads(p, &m);
        }
    }
}

static void hostPoll(uint32_t now)
{
    int p;

    hostRead();
    // A client that stopped has left the race: from the next record on it
    // is built without. One whose link is lost is held for (37g): no
    // record is built without its pad until the hold is over, and then
    // the records are built without it, as without one left. One gone
    // already at the first poll is not held for.
    for (p = 0; p < NETSTEP_MAX; p++) {
        if (p == S->place || !((S->live >> p) & 1)) continue;
        if (S->left[p]) {
            say("netstep: place %d left, from frame %lu", p,
                (unsigned long)S->built);
        } else if (alive(p)) {
            continue;
        } else if (!S->polled) {
            say("netstep: place %d was gone at the start", p);
        } else if (!S->lost[p]) {
            S->lost[p]   = 1;
            S->lostAt[p] = now;
            say("netstep: place %d lost at frame %lu; held for %lu ms", p,
                (unsigned long)S->built, (unsigned long)S->holdMs);
            continue;
        } else if (now - S->lostAt[p] < S->holdMs) {
            continue;
        } else {
            say("netstep: place %d is gone, from frame %lu; its car to the "
                "CPU", p, (unsigned long)S->built);
        }
        S->lost[p] = 0;
        S->live &= (uint8_t)~(1u << p);
    }
    hostBuild();
    for (p = 0; p < NETSTEP_MAX; p++) {
        if (p == S->place || !((S->live >> p) & 1) || S->lost[p]) continue;
        if (S->fresh[p] || now - S->lastSend[p] >= NETSTEP_RESEND_MS)
            sendFrames(p, now);
    }
}

// Stopped: each client still racing has the records it needs to reach
// the host's stop, as the race did, until it says it stopped too.
static void hostDrain(uint32_t now)
{
    int p, waiting = -1;

    hostRead();
    for (p = 0; p < NETSTEP_MAX; p++) {
        if (!serving(p)) continue;
        waiting = p;
        if (S->fresh[p] || now - S->lastSend[p] >= NETSTEP_RESEND_MS)
            sendFrames(p, now);
    }
    if (waiting < 0) {
        S->ending = 0;
        say("netstep: every client stopped, %lu ms after the host",
            (unsigned long)(now - S->endFrom));
    } else if (now - S->endFrom >= NETSTEP_DRAIN_MS) {
        S->ending = 0;
        say("netstep: place %d never said it stopped; given up after %lu ms",
            waiting, (unsigned long)(now - S->endFrom));
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
    S->held     = d[19];
    S->heldLeft = d[20];
    if (get32(d + 15) != NETSTEP_NONE && S->hostStop == NETSTEP_NONE) {
        S->hostStop = get32(d + 15);
        say("netstep: the host stopped after %lu frames",
            (unsigned long)S->hostStop);
    }
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
// Stopped, none: the host builds no more with them.
static void sendPads(uint32_t now)
{
    uint8_t  b[WL_MSG_MAX];
    uint32_t first = S->padNeed, n;
    uint32_t end = S->stopAt == NETSTEP_NONE ? S->put : first;
    size_t   o = HEADER;
    int      count = 0;

    put32(b, S->built);
    put32(b + 4, first);
    for (n = first; n < end && o + PAD_WIRE <= WL_MSG_MAX; n++) {
        encodePad(b + o, &S->pads[S->place][n & MASK]);
        o += PAD_WIRE;
        count++;
    }
    b[8] = (uint8_t)count;
    putHash(b + 9);
    put32(b + 15, S->stopAt);
    b[19] = 0;
    b[20] = 0;
    if (!S->net.send(S->peer[0], NETSTEP_MSG_PADS, b, o)) S->sendFails++;
    S->lastSend[S->place] = now;
}

// A client's stop said, each NETSTEP_RESEND_MS, until it has been said
// NETSTEP_TELLS times or the host is gone. Nothing is read: the host
// sends nothing more after it reads one.
static void tell(uint32_t now)
{
    if (S->tells <= 0) return;
    if (!alive(0)) {
        S->tells = 0;
        return;
    }
    if (now - S->lastSend[S->place] < NETSTEP_RESEND_MS) return;
    sendPads(now);
    if (--S->tells == 0) say("netstep: the stop said");
}

static void clientPoll(uint32_t now)
{
    WlMsg m;

    if (!S->alone) {
        int on = 0;   // the host's lobby, left for it: the host went on

        while (S->net.peek(S->peer[0], &m)) {
            if (m.type != NETSTEP_MSG_FRAMES) {
                on = 1;
                break;
            }
            S->net.recv(S->peer[0], &m);
            takeFrames(&m);
        }
        if (!alive(0)) {
            // Held for (37g), as the host holds for a client, unless gone
            // already at the first poll; then alone, the rest the CPU's.
            if (S->polled && !S->lost[0]) {
                S->lost[0]   = 1;
                S->lostAt[0] = now;
                say("netstep: the host lost at frame %lu; held for %lu ms",
                    (unsigned long)S->built, (unsigned long)S->holdMs);
            } else if (!S->polled || now - S->lostAt[0] >= S->holdMs) {
                S->alone   = 1;
                S->live    = (uint8_t)(1u << S->place);
                S->lost[0] = 0;
                say("netstep: the host is gone, from frame %lu; racing "
                    "alone, the other cars the CPU's",
                    (unsigned long)S->built);
            }
        } else if (on || (S->hostStop != NETSTEP_NONE
                          && S->frame >= S->hostStop)) {
            // Past the host's last frame, on its own: it has left the
            // host's race, which it says as a stop.
            S->alone  = 1;
            S->live   = (uint8_t)(1u << S->place);
            S->stopAt = S->frame;
            S->tells  = NETSTEP_TELLS;
            say(on ? "netstep: the host has gone on, from frame %lu; racing "
                     "alone"
                   : "netstep: past the host's stop, from frame %lu; racing "
                     "alone", (unsigned long)S->built);
        }
    }
    if (S->alone) {
        tell(now);
        aloneBuild();
        return;
    }
    if (S->lost[0]) return;
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

// 0 is netstep_start's NETSTEP_HOLD_MS.
void netstep_set_hold(uint32_t ms)
{
    S->holdMs = ms;
}

void netstep_start(int place, int consoles, const int peer[NETSTEP_MAX],
                   uint8_t racing)
{
    NetStepNet      net    = S->net;
    NetStepLogFn    log    = S->log;
    NetStepDifferFn differ = S->differ;
    uint32_t        holdMs = S->holdMs ? S->holdMs : NETSTEP_HOLD_MS;
    uint32_t     n;
    int          p, i;

    memset(S, 0, sizeof *S);
    S->net    = net;
    S->log    = log;
    S->differ = differ;
    S->holdMs = holdMs;
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
    S->stopAt   = NETSTEP_NONE;
    S->hostStop = NETSTEP_NONE;
    say("netstep: start, place %d, racing %02x, delay %d", place,
        (unsigned)S->live, NETSTEP_DELAY);
}

int netstep_on(void)
{
    return S->on;
}

void netstep_stop(uint32_t now)
{
    if (!S->on) return;
    say("netstep: stop at frame %lu, %lu sends refused",
        (unsigned long)S->frame, (unsigned long)S->sendFails);
    S->on = 0;
    // A client alone past the host's stop said its own then.
    if (S->stopAt == NETSTEP_NONE) S->stopAt = S->frame;
    S->endFrom = now;
    if (S->host) {
        S->ending = 1;
    } else {
        if (!S->alone) S->tells = NETSTEP_TELLS;
        S->ending = S->tells > 0;
    }
}

void netstep_drain(uint32_t now)
{
    if (!S->ending) return;
    if (S->host) {
        hostDrain(now);
        return;
    }
    tell(now);
    if (S->tells <= 0) S->ending = 0;
}

int netstep_ending(void)
{
    return S->ending;
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
    S->polled = 1;
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

uint8_t netstep_held(uint32_t now, uint32_t* msLeft)
{
    uint32_t since;

    if (msLeft) *msLeft = 0;
    if (!S->on || S->alone) return 0;
    if (S->host) return hostHeld(now, msLeft);
    if (!S->lost[0]) {
        if (msLeft) *msLeft = (uint32_t)S->heldLeft * 1000u;
        return S->held;
    }
    since = now - S->lostAt[0];
    if (msLeft) *msLeft = since < S->holdMs ? S->holdMs - since : 0;
    return 1;
}
