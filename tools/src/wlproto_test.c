// wlproto_test -- the host half of tools/wlproto_check.py: two wlproto
// links, A and B, over a channel that drops, repeats, delays (and so
// reorders) and cuts packets, and damages some. Each side sends numbered
// messages whose bytes say what they are, and what the other side reads
// is checked as it comes:
//
//   - reliable messages come in order, each once, intact, and every one
//     sent has come by the end, once the channel has been clean a while;
//   - an unreliable one is one that was sent, intact, and comes twice
//     only on a channel that repeats;
//   - on a clean channel each message comes in the tick its packet lands,
//     nothing is resent while the round trip is under WL_RESEND_MS, and
//     every unreliable one comes;
//   - on a lossy one, a reliable message's mean wait stays within a
//     bound that a slow resend breaks;
//   - a cut longer than the timeout loses the link on both sides, and the
//     link comes back once it ends; no shorter gap loses it;
//   - a quiet link sends a keepalive each WL_KEEPALIVE_MS, and one that
//     only receives sends little more than an ack each tick a reliable
//     message came;
//   - a send is refused exactly when the window or the unreliable queue
//     is full, or the message is too long;
//   - a peek (wl_link_peek, TASKS 37f) is the message the next read
//     takes, and leaves it there;
//   - a damaged packet changes nothing but the malformed count: one made
//     from a real packet with each framing rule broken in turn and its
//     CRC made right again, one with a bit flipped, and noise.
//
// Each scenario prints a line of what happened, and the last line is
// "faults N".

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "wlproto.h"

#define MAX_FLIGHT 8192
#define KINDS      11      // the crafted packets' kinds

static int g_faults;

static void fault(const char *what, int sc, uint32_t now, long a, long b)
{
    if (g_faults < 40)
        printf("  FAULT %s (scenario %d, t %u: %ld %ld)\n", what, sc,
               (unsigned)now, a, b);
    g_faults++;
}

// ------------------------------------------------------------ the dice

static uint32_t g_rng;

static uint32_t rnd(void)
{
    g_rng ^= g_rng << 13;
    g_rng ^= g_rng >> 17;
    g_rng ^= g_rng << 5;
    return g_rng;
}

static int chance(int per_mille)
{
    return (int)(rnd() % 1000) < per_mille;
}

static uint32_t hash3(uint32_t a, uint32_t b, uint32_t c)
{
    uint32_t h = a * 0x9e3779b1u ^ b * 0x85ebca77u ^ c * 0xc2b2ae3du;

    h ^= h >> 15;
    h *= 0x2c1b3c6du;
    h ^= h >> 12;
    h *= 0x297a2d39u;
    h ^= h >> 15;
    return h;
}

// The harness's own CRC-16/CCITT-FALSE, so a change to wlproto.c's is
// not copied here.
static uint16_t crc16(const uint8_t *p, size_t n, uint16_t c)
{
    size_t i;
    int    b;

    for (i = 0; i < n; i++) {
        c ^= (uint16_t)(p[i] << 8);
        for (b = 0; b < 8; b++)
            c = (uint16_t)((c & 0x8000u) ? (unsigned)c << 1 ^ 0x1021u
                                         : (unsigned)c << 1);
    }
    return c;
}

static void fix_crc(uint8_t *buf, size_t n)
{
    uint16_t c = crc16(buf + WL_HEADER, n - WL_HEADER,
                       crc16(buf, 5, 0xffffu));

    buf[5] = (uint8_t)c;
    buf[6] = (uint8_t)(c >> 8);
}

// --------------------------------------------------------- the scenario

typedef struct Scenario {
    int      drop, dup, garbage;    // per mille
    uint32_t delayMin, delayMax;    // ms
    uint32_t cutFrom, cutTo;        // ms; packets sent within are lost
    uint32_t tick;                  // ms between ticks
    uint32_t length;                // ms of traffic, then a clean drain
    int      relPerTick, unrelPerTick;   // most a side sends a tick
    int      maxLen;
    uint32_t stallFrom, stallTo;    // B reads nothing within
    uint32_t seed;
    int      senders;               // 1 A, 2 B, 3 both, 0 neither
} Scenario;

#define DRAIN 4000u

static const Scenario *g_sc;
static int      g_scIndex;
static uint32_t g_now;
static int      g_clean;            // the drain: nothing lost or late

static int clean_channel(const Scenario *s)
{
    return s->drop == 0 && s->dup == 0 && s->garbage == 0 && s->cutTo == 0
           && s->stallTo == 0 && s->delayMin == s->delayMax;
}

// The time from a packet's going to its being taken: it lands at the
// first tick at or past its delay, and the next tick at the soonest.
static uint32_t hop_ms(const Scenario *s)
{
    uint32_t hops = (s->delayMax + s->tick - 1) / s->tick;

    return (hops ? hops : 1) * s->tick;
}

// --------------------------------------------------------- the channel

typedef struct Flight {
    uint32_t at;          // when it lands
    int      to;          // 0 for A, 1 for B
    size_t   n;
    uint8_t  buf[WL_PACKET_MAX];
} Flight;

static Flight g_flight[MAX_FLIGHT];
static int    g_numFlight;

static void launch(int to, const uint8_t *buf, size_t n, uint32_t delay)
{
    Flight *f;

    if (g_numFlight >= MAX_FLIGHT) {
        fault("the channel overflowed", g_scIndex, g_now, g_numFlight, 0);
        return;
    }
    f = &g_flight[g_numFlight++];
    f->at = g_now + delay;
    f->to = to;
    f->n  = n;
    memcpy(f->buf, buf, n);
}

// ----------------------------------------------------------- the sides

typedef struct Side {
    WlLink   link;
    int      id;
    int      sends;
    uint32_t relSent, unrelSent;      // numbered from 0
    uint32_t relGot, unrelGot, unrelRepeats;
    uint32_t relAt[1 << 16];          // reliable i's send, ms
    uint32_t unrelAt[1 << 16];
    uint8_t  unrelSeen[1 << 16];
    int      queued;                  // unreliable since the last tick
    double   waitSum;                 // the reliable messages' waits
    uint32_t waitMax;
    int      alive;                   // as last seen
    uint32_t lostAt, backAt;
    uint32_t ackTicks;                // ticks a reliable message came
    int      ackThisTick;
    uint32_t crafted[KINDS];
} Side;

static Side g_side[2];

static int rel_len(int id, uint32_t i)
{
    return (int)(hash3((uint32_t)id, i, 0x11u) % (uint32_t)(g_sc->maxLen + 1));
}

static void rel_bytes(int id, uint32_t i, uint8_t *out, int len)
{
    int j;

    for (j = 0; j < len; j++)
        out[j] = (uint8_t)hash3((uint32_t)id, i, 0x100u + (uint32_t)j);
}

static int unrel_len(int id, uint32_t k)
{
    int most = g_sc->maxLen < 4 ? 4 : g_sc->maxLen;

    return 4 + (int)(hash3((uint32_t)id | 0x80u, k, 0x22u)
                     % (uint32_t)(most - 3));
}

static void unrel_bytes(int id, uint32_t k, uint8_t *out, int len)
{
    int j;

    memcpy(out, &k, 4);
    for (j = 4; j < len; j++)
        out[j] = (uint8_t)hash3((uint32_t)id | 0x80u, k, 0x100u + (uint32_t)j);
}

// What a link holds that a packet could change.
typedef struct Seen {
    uint32_t packetsIn, lastHeard, malformed, repeats, dropped;
    int      heard, inCount, ackDue;
    uint16_t base, expect;
    uint8_t  isHeld[WL_WINDOW];
} Seen;

static void seen(const WlLink *l, Seen *s)
{
    memset(s, 0, sizeof *s);
    s->packetsIn = l->packetsIn;
    s->lastHeard = l->lastHeard;
    s->malformed = l->malformed;
    s->repeats   = l->repeats;
    s->dropped   = l->dropped;
    s->heard     = l->heard;
    s->inCount   = l->inCount;
    s->ackDue    = l->ackDue;
    s->base      = l->base;
    s->expect    = l->expect;
    memcpy(s->isHeld, l->isHeld, sizeof s->isHeld);
}

// A real packet `buf` made wrong in one way, the CRC made right again
// for all but the kinds that test it; taken by side `to` at once, which
// must change nothing but its malformed count.
static void craft(int to, const uint8_t *buf, size_t n, int sc)
{
    uint8_t  junk[WL_PACKET_MAX + 300];
    size_t   m = n, at;
    int      kind = (int)(rnd() % KINDS), count = buf[4], i, fix = 1;
    Side    *d = &g_side[to];
    Seen     before, after;

    memcpy(junk, buf, n);
    if (kind == 3 && count == 255)
        kind = 4;
    if ((kind == 6 || kind == 7) && count == 0)
        kind = 3;
    if (kind == 8 && n == WL_HEADER)
        kind = 10;
    switch (kind) {
    case 0:                                     // not the magic
        junk[0] ^= (uint8_t)(1 + rnd() % 255);
        break;
    case 1:                                     // another version
        junk[1] = (uint8_t)(WL_VERSION + 1 + rnd() % 255);
        break;
    case 2:                                     // an ack with the top bit
        junk[3] |= 0x80u;
        break;
    case 3:                                     // a message more than held
        junk[4] = (uint8_t)(count + 1);
        break;
    case 4:                                     // bytes past the last
        if (count > 0)
            junk[4] = (uint8_t)(count - 1);
        else
            junk[m++] = (uint8_t)rnd();
        break;
    case 5:                                     // a message too long
        junk[4] = 1;
        junk[WL_HEADER] = 0;
        junk[WL_HEADER + 1] = (uint8_t)(rnd() & 0x7f);
        junk[WL_HEADER + 2] = 1;
        junk[WL_HEADER + 3] = (uint8_t)(WL_MSG_MAX + 1
                                        + rnd() % (255 - WL_MSG_MAX));
        m = WL_HEADER + WL_MSG_HEADER + junk[WL_HEADER + 3];
        for (at = WL_HEADER + WL_MSG_HEADER; at < m; at++)
            junk[at] = (uint8_t)rnd();
        break;
    case 6:                                     // a length past the end
        at = WL_HEADER;
        for (i = 0; i + 1 < count; i++)
            at += WL_MSG_HEADER + junk[at + 3];
        if (junk[at + 3] == 255)
            junk[4] = (uint8_t)(count + 1 < 256 ? count + 1 : count - 1);
        else
            junk[at + 3] = (uint8_t)(junk[at + 3] + 1
                                     + rnd() % (255u - junk[at + 3]));
        break;
    case 7:                                     // unreliable, but numbered
        at = WL_HEADER;
        for (i = (int)(rnd() % (uint32_t)count); i > 0; i--)
            at += WL_MSG_HEADER + junk[at + 3];
        junk[at + 1] = (uint8_t)(0x80u | (rnd() & 0x7f));
        if (junk[at] == 0 && junk[at + 1] == 0x80u)
            junk[at] = 1;
        break;
    case 8:                                     // cut short
        m = WL_HEADER + rnd() % (n - WL_HEADER);
        break;
    case 9:                                     // a bit flipped
        junk[rnd() % n] ^= (uint8_t)(1u << (rnd() % 8));
        fix = 0;
        break;
    default:                                    // shorter than a header
        m = rnd() % WL_HEADER;
        fix = 0;
        break;
    }
    if (fix)
        fix_crc(junk, m);
    d->crafted[kind]++;
    seen(&d->link, &before);
    wl_link_packet_in(&d->link, junk, m);
    seen(&d->link, &after);
    before.malformed++;
    if (memcmp(&before, &after, sizeof before) != 0)
        fault("a crafted packet was taken", sc, g_now, kind, (long)m);
}

// A link's send: `ctx` is the side the packet goes to.
static void chan_send(void *ctx, const uint8_t *buf, size_t n)
{
    int      to = (int)(intptr_t)ctx;
    uint32_t span, delay;

    if (n > WL_PACKET_MAX || n < WL_HEADER) {
        fault("packet of a wrong size", g_scIndex, g_now, (long)n, 0);
        return;
    }
    if (g_clean) {
        launch(to, buf, n, 0);
        return;
    }
    if (chance(g_sc->garbage))
        craft(to, buf, n, g_scIndex);
    if (g_now >= g_sc->cutFrom && g_now < g_sc->cutTo)
        return;
    if (chance(g_sc->drop))
        return;
    span  = g_sc->delayMax - g_sc->delayMin;
    delay = g_sc->delayMin + (span ? rnd() % (span + 1) : 0);
    launch(to, buf, n, delay);
    if (chance(g_sc->dup))
        launch(to, buf, n, g_sc->delayMin + (span ? rnd() % (span + 1) : 0));
    if (chance(g_sc->garbage)) {
        // On the air: a bit flipped, which the CRC must catch.
        uint8_t junk[WL_PACKET_MAX];

        memcpy(junk, buf, n);
        junk[rnd() % n] ^= (uint8_t)(1u << (rnd() % 8));
        launch(to, junk, n, delay);
    }
}

// The reliable messages in flight, by the harness's own arithmetic.
static int unacked(const WlLink *l)
{
    return (int)((uint32_t)(l->next - l->base) & WL_SEQ_MASK);
}

static void side_send(Side *s, int sc, int traffic)
{
    uint8_t buf[WL_MSG_MAX + 1];
    int     i, n;

    if (!traffic || !s->sends)
        return;
    n = (int)(rnd() % (uint32_t)(g_sc->relPerTick + 1));
    for (i = 0; i < n && s->relSent < 65536u; i++) {
        int len = rel_len(s->id, s->relSent);
        int full = unacked(&s->link) >= WL_WINDOW;

        rel_bytes(s->id, s->relSent, buf, len);
        if (wl_link_unacked(&s->link) != unacked(&s->link))
            fault("unacked miscounted", sc, g_now,
                  wl_link_unacked(&s->link), unacked(&s->link));
        if (!wl_link_send(&s->link, 1, buf, (size_t)len, 1)) {
            if (!full)
                fault("reliable send refused with room", sc, g_now,
                      unacked(&s->link), len);
            break;
        }
        if (full)
            fault("reliable send past the window", sc, g_now, 0, 0);
        s->relAt[s->relSent] = g_now;
        s->relSent++;
    }
    n = (int)(rnd() % (uint32_t)(g_sc->unrelPerTick + 1));
    for (i = 0; i < n && s->unrelSent < 65536u; i++) {
        int len = unrel_len(s->id, s->unrelSent);
        int ok;

        unrel_bytes(s->id, s->unrelSent, buf, len);
        ok = wl_link_send(&s->link, 2, buf, (size_t)len, 0);
        if (ok && s->queued >= WL_UNREL_MAX)
            fault("unreliable send past the queue", sc, g_now, s->queued, 0);
        if (!ok && s->queued < WL_UNREL_MAX)
            fault("unreliable send refused with room", sc, g_now, s->queued,
                  len);
        if (!ok)
            break;
        s->queued++;
        s->unrelAt[s->unrelSent] = g_now;
        s->unrelSent++;
    }
    // Now and then one a byte too long, which must be refused.
    if ((rnd() & 63) == 0) {
        memset(buf, 0xa5, sizeof buf);
        if (wl_link_send(&s->link, 1, buf, WL_MSG_MAX + 1, (int)(rnd() & 1)))
            fault("a message too long was taken", sc, g_now, 0, 0);
    }
}

static int same_msg(const WlMsg *a, const WlMsg *b)
{
    return a->type == b->type && a->seq == b->seq && a->len == b->len
        && memcmp(a->data, b->data, a->len) == 0;
}

// What `s` reads, from the other side `o`.
static void side_read(Side *s, Side *o, int sc)
{
    WlMsg   m;
    uint8_t want[WL_MSG_MAX];
    int     clean = clean_channel(g_sc);

    if (s->id == 1 && g_now >= g_sc->stallFrom && g_now < g_sc->stallTo)
        return;
    for (;;) {
        WlMsg p, p2;
        int   peeked = wl_link_peek(&s->link, &p), got;

        // A peek is the next read, and leaves it to be read.
        if (wl_link_peek(&s->link, &p2) != peeked
            || (peeked && !same_msg(&p, &p2)))
            fault("a second peek saw another", sc, g_now, peeked, 0);
        got = wl_link_recv(&s->link, &m);
        if (got != peeked || (got && !same_msg(&p, &m)))
            fault("a peek was not the next read", sc, g_now, peeked, got);
        if (!got)
            break;
        if (m.type == 1) {
            uint32_t i = s->relGot, wait;
            int      len;

            if (m.seq == WL_UNRELIABLE)
                fault("reliable type came unreliable", sc, g_now, 0, 0);
            if (i >= o->relSent) {
                fault("reliable message never sent", sc, g_now, (long)i,
                      (long)o->relSent);
                continue;
            }
            len = rel_len(o->id, i);
            rel_bytes(o->id, i, want, len);
            if (m.len != len || memcmp(m.data, want, (size_t)len) != 0)
                fault("reliable message out of order or changed", sc, g_now,
                      (long)i, m.len);
            wait = g_now - o->relAt[i];
            if (clean && wait > hop_ms(g_sc))
                fault("reliable message late on a clean channel", sc, g_now,
                      (long)i, (long)wait);
            s->waitSum += wait;
            if (wait > s->waitMax)
                s->waitMax = wait;
            s->relGot++;
        } else if (m.type == 2) {
            uint32_t k;
            int      len;

            if (m.seq != WL_UNRELIABLE)
                fault("unreliable type came reliable", sc, g_now, m.seq, 0);
            if (m.len < 4) {
                fault("unreliable message too short", sc, g_now, m.len, 0);
                continue;
            }
            memcpy(&k, m.data, 4);
            if (k >= o->unrelSent) {
                fault("unreliable message never sent", sc, g_now, (long)k,
                      (long)o->unrelSent);
                continue;
            }
            len = unrel_len(o->id, k);
            unrel_bytes(o->id, k, want, len);
            if (m.len != len || memcmp(m.data, want, (size_t)len) != 0)
                fault("unreliable message changed", sc, g_now, (long)k, m.len);
            if (clean && g_now - o->unrelAt[k] > hop_ms(g_sc))
                fault("unreliable message late on a clean channel", sc, g_now,
                      (long)k, (long)(g_now - o->unrelAt[k]));
            if (s->unrelSeen[k])
                s->unrelRepeats++;
            s->unrelSeen[k] = 1;
            s->unrelGot++;
        } else {
            fault("message of no type sent", sc, g_now, m.type, 0);
        }
    }
    // Read to the end: nothing it could have read is left held.
    {
        int h = s->link.expect % WL_WINDOW;

        if (s->link.isHeld[h] && s->link.held[h].seq == s->link.expect)
            fault("a message to read left held", sc, g_now, s->link.expect,
                  s->link.inCount);
    }
}

// ------------------------------------------------------------ the run

// Whether a packet holds a reliable message (only asked of one its
// link took, so well formed).
static int has_reliable(const uint8_t *buf)
{
    size_t at = WL_HEADER;
    int    i;

    for (i = 0; i < buf[4]; i++) {
        if ((buf[at] | buf[at + 1] << 8) != WL_UNRELIABLE)
            return 1;
        at += WL_MSG_HEADER + buf[at + 3];
    }
    return 0;
}

static void deliver_due(void)
{
    int i = 0;

    while (i < g_numFlight) {
        Flight *f = &g_flight[i];

        if ((int32_t)(g_now - f->at) >= 0) {
            static Flight copy;
            Side    *d;
            uint32_t was;

            copy = *f;
            d = &g_side[copy.to];
            was = d->link.packetsIn;
            g_flight[i] = g_flight[--g_numFlight];
            wl_link_packet_in(&d->link, copy.buf, copy.n);
            if (d->link.packetsIn != was && has_reliable(copy.buf))
                d->ackThisTick = 1;
        } else {
            i++;
        }
    }
}

static void noise(void)
{
    uint8_t  junk[64];
    size_t   n = rnd() % sizeof junk, j;
    int      to = (int)(rnd() & 1);
    Side    *d = &g_side[to];
    Seen     before, after;

    for (j = 0; j < n; j++)
        junk[j] = (uint8_t)rnd();
    if (n > 0 && (rnd() & 1))
        junk[0] = WL_MAGIC;
    if (n > 1 && (rnd() & 1))
        junk[1] = WL_VERSION;
    seen(&d->link, &before);
    wl_link_packet_in(&d->link, junk, n);
    seen(&d->link, &after);
    before.malformed++;
    if (memcmp(&before, &after, sizeof before) != 0)
        fault("noise was taken", g_scIndex, g_now, (long)n, 0);
}

static void run(int sc, const Scenario *s)
{
    uint32_t start = 1000, end, t, total;
    uint32_t cut = s->cutTo - s->cutFrom;
    int      k;

    g_sc = s;
    g_scIndex = sc;
    g_rng = s->seed ? s->seed : 1u;
    g_numFlight = 0;
    g_clean = 0;
    g_now = start;
    for (k = 0; k < 2; k++) {
        Side *d = &g_side[k];

        memset(d, 0, sizeof *d);
        d->id = k;
        d->sends = (s->senders >> k) & 1;
        wl_link_init(&d->link, chan_send, (void *)(intptr_t)(1 - k), g_now);
        if (wl_link_alive(&d->link))
            fault("alive before hearing anything", sc, g_now, k, 0);
    }
    end = start + s->length;
    // Traffic, then a clean drain long enough for every resend.
    for (t = start; t < end + DRAIN; t += s->tick) {
        int traffic = t < end;

        g_now = t;
        g_clean = !traffic;
        if (traffic && s->garbage && chance(s->garbage / 4 + 1))
            noise();
        deliver_due();
        for (k = 0; k < 2; k++)
            side_read(&g_side[k], &g_side[1 - k], sc);
        for (k = 0; k < 2; k++)
            side_send(&g_side[k], sc, traffic);
        for (k = 0; k < 2; k++) {
            Side *d = &g_side[k];
            int   alive;

            wl_link_tick(&d->link, g_now);
            d->queued = 0;
            d->ackTicks += (uint32_t)d->ackThisTick;
            d->ackThisTick = 0;
            alive = wl_link_alive(&d->link);
            if (d->alive && !alive && !d->lostAt)
                d->lostAt = g_now;
            if (!d->alive && alive && d->lostAt && !d->backAt)
                d->backAt = g_now;
            d->alive = alive;
        }
    }
    total = g_now + s->tick - start;

    for (k = 0; k < 2; k++) {
        Side    *d = &g_side[k], *o = &g_side[1 - k];
        uint32_t lostBy, backBy, most, least;

        if (d->relGot != o->relSent)
            fault("reliable messages missing at the end", sc, g_now,
                  (long)d->relGot, (long)o->relSent);
        if (unacked(&o->link) != 0)
            fault("messages still unacked at the end", sc, g_now,
                  unacked(&o->link), 0);
        if (!d->alive)
            fault("link not alive at the end", sc, g_now, 0, 0);
        if (clean_channel(s) && d->unrelGot != o->unrelSent)
            fault("unreliable messages lost on a clean channel", sc, g_now,
                  (long)d->unrelGot, (long)o->unrelSent);
        if (s->dup == 0 && d->unrelRepeats)
            fault("unreliable message came twice with no repeats", sc, g_now,
                  (long)d->unrelRepeats, 0);
        if (s->garbage == 0 && d->link.malformed)
            fault("malformed packets with none sent", sc, g_now,
                  (long)d->link.malformed, 0);
        if (clean_channel(s) && 2 * hop_ms(s) <= WL_RESEND_MS
            && d->link.resends)
            fault("resends on a clean channel", sc, g_now,
                  (long)d->link.resends, 0);
        // A lossy channel's mean wait: a round trip and a resend for each
        // loss, with room for the losses' runs and the messages held
        // behind a lost one.
        if (!clean_channel(s) && s->cutTo == 0 && s->stallTo == 0
            && d->relGot > 100) {
            double mean = d->waitSum / d->relGot;
            double lossy = (double)s->drop / (1000 - s->drop);
            double bound = hop_ms(s) + s->delayMax
                           + 3.0 * lossy * (WL_RESEND_MS + s->tick);

            if (mean > bound)
                fault("reliable messages slow on a lossy channel", sc, g_now,
                      (long)mean, (long)bound);
        }
        // A cut longer than the timeout and what it takes to notice:
        // lost within it, and back after it. A gap a second short of the
        // timeout never loses it.
        if (cut > WL_TIMEOUT_MS + s->delayMax + WL_KEEPALIVE_MS
                  + 2 * s->tick) {
            lostBy = s->cutFrom + s->delayMax + WL_TIMEOUT_MS + 2 * s->tick;
            backBy = s->cutTo + WL_KEEPALIVE_MS + 2 * s->tick + s->delayMax;
            if (s->drop)
                backBy += 2000;
            if (!d->lostAt || d->lostAt > lostBy || d->lostAt < s->cutFrom)
                fault("link not lost in a long cut", sc, g_now,
                      (long)d->lostAt, (long)lostBy);
            if (!d->backAt || d->backAt > backBy || d->backAt < s->cutTo)
                fault("link not back after the cut", sc, g_now,
                      (long)d->backAt, (long)backBy);
        } else if (cut + 1000 + s->delayMax + WL_KEEPALIVE_MS + 2 * s->tick
                   < WL_TIMEOUT_MS && d->lostAt) {
            fault("link lost with no long cut", sc, g_now, (long)d->lostAt, 0);
        }
        // A quiet link: a keepalive each WL_KEEPALIVE_MS (to the tick).
        most = total / WL_KEEPALIVE_MS + 2;
        least = total / (WL_KEEPALIVE_MS + s->tick);
        least = least > 2 ? least - 2 : 0;
        if (s->senders == 0 && !s->garbage
            && (d->link.packetsOut > most || d->link.packetsOut < least))
            fault("quiet link's keepalives off", sc, g_now,
                  (long)d->link.packetsOut, (long)most);
        // One that only receives: its acks, and keepalives between.
        if (s->senders && !d->sends
            && d->link.packetsOut > d->ackTicks + most)
            fault("receiver sends too much", sc, g_now,
                  (long)d->link.packetsOut, (long)(d->ackTicks + most));
    }
    printf("R %d: A %u/%u B %u/%u; got A %u/%u (%u twice) B %u/%u (%u twice);"
           " packets %u %u; resends %u %u; repeats %u %u; malformed %u %u;"
           " dropped %u %u; wait %.1f/%u %.1f/%u; lost %u %u back %u %u;"
           " crafted",
           sc, (unsigned)g_side[0].relSent, (unsigned)g_side[0].unrelSent,
           (unsigned)g_side[1].relSent, (unsigned)g_side[1].unrelSent,
           (unsigned)g_side[0].relGot, (unsigned)g_side[0].unrelGot,
           (unsigned)g_side[0].unrelRepeats,
           (unsigned)g_side[1].relGot, (unsigned)g_side[1].unrelGot,
           (unsigned)g_side[1].unrelRepeats,
           (unsigned)g_side[0].link.packetsOut,
           (unsigned)g_side[1].link.packetsOut,
           (unsigned)g_side[0].link.resends, (unsigned)g_side[1].link.resends,
           (unsigned)g_side[0].link.repeats, (unsigned)g_side[1].link.repeats,
           (unsigned)g_side[0].link.malformed,
           (unsigned)g_side[1].link.malformed,
           (unsigned)g_side[0].link.dropped, (unsigned)g_side[1].link.dropped,
           g_side[0].relGot ? g_side[0].waitSum / g_side[0].relGot : 0.0,
           (unsigned)g_side[0].waitMax,
           g_side[1].relGot ? g_side[1].waitSum / g_side[1].relGot : 0.0,
           (unsigned)g_side[1].waitMax,
           (unsigned)(g_side[0].lostAt ? g_side[0].lostAt - start : 0),
           (unsigned)(g_side[1].lostAt ? g_side[1].lostAt - start : 0),
           (unsigned)(g_side[0].backAt ? g_side[0].backAt - start : 0),
           (unsigned)(g_side[1].backAt ? g_side[1].backAt - start : 0));
    for (k = 0; k < KINDS; k++)
        printf(" %u", (unsigned)(g_side[0].crafted[k] + g_side[1].crafted[k]));
    printf("\n");
}

// One scenario a line: drop dup garbage delayMin delayMax cutFrom cutTo
// tick length relPerTick unrelPerTick maxLen stallFrom stallTo seed
// senders, the times from the start (1000 is added).
int main(int argc, char **argv)
{
    static char line[512];
    FILE *fp;
    int   n = 0;

    if (argc != 2) {
        fprintf(stderr, "usage: wlproto_test scenarios.txt\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    while (fgets(line, sizeof line, fp) != NULL) {
        Scenario s;
        unsigned v[16];

        if (sscanf(line, "%u %u %u %u %u %u %u %u %u %u %u %u %u %u %u %u",
                   &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6], &v[7],
                   &v[8], &v[9], &v[10], &v[11], &v[12], &v[13], &v[14],
                   &v[15]) != 16)
            continue;
        s.drop = (int)v[0];
        s.dup = (int)v[1];
        s.garbage = (int)v[2];
        s.delayMin = v[3];
        s.delayMax = v[4];
        s.cutFrom = v[6] ? v[5] + 1000 : 0;
        s.cutTo = v[6] ? v[6] + 1000 : 0;
        s.tick = v[7];
        s.length = v[8];
        s.relPerTick = (int)v[9];
        s.unrelPerTick = (int)v[10];
        s.maxLen = (int)v[11];
        s.stallFrom = v[13] ? v[12] + 1000 : 0;
        s.stallTo = v[13] ? v[13] + 1000 : 0;
        s.seed = v[14];
        s.senders = (int)v[15];
        run(n++, &s);
    }
    fclose(fp);
    printf("faults %d\n", g_faults);
    return 0;
}
