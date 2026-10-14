// wlproto -- the local wireless link's protocol: see wlproto.h.

#include "wlproto.h"

#include <string.h>

// How far b is behind a, going forward round the 15 bits.
static uint16_t seq_diff(uint16_t a, uint16_t b)
{
    return (uint16_t)((a - b) & WL_SEQ_MASK);
}

static uint16_t seq_next(uint16_t s)
{
    return (uint16_t)((s + 1u) & WL_SEQ_MASK);
}

static uint16_t rd16(const uint8_t *p)
{
    return (uint16_t)(p[0] | p[1] << 8);
}

static void wr16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}

// CRC-16/CCITT-FALSE, a bit at a time: packets are small and few.
static uint16_t crc16(const uint8_t *p, size_t n, uint16_t c)
{
    while (n--) {
        int b;

        c ^= (uint16_t)(*p++ << 8);
        for (b = 0; b < 8; b++)
            c = (uint16_t)((c & 0x8000u) ? (unsigned)c << 1 ^ 0x1021u
                                         : (unsigned)c << 1);
    }
    return c;
}

// A packet's CRC: of all of it but the CRC's own two bytes (5 and 6).
static uint16_t packet_crc(const uint8_t *buf, size_t n)
{
    return crc16(buf + WL_HEADER, n - WL_HEADER, crc16(buf, 5, 0xffffu));
}

void wl_link_init(WlLink *l, WlSendFn send, void *ctx, uint32_t now)
{
    memset(l, 0, sizeof *l);
    l->send      = send;
    l->ctx       = ctx;
    l->now       = now;
    l->lastHeard = now;
    l->lastSent  = now;
}

int wl_link_send(WlLink *l, uint8_t type, const void *data, size_t n,
                 int reliable)
{
    WlMsg *m;

    if (n > WL_MSG_MAX)
        return 0;
    if (reliable) {
        int k;

        if (seq_diff(l->next, l->base) >= WL_WINDOW)
            return 0;
        k = l->next % WL_WINDOW;
        m = &l->out[k];
        m->seq      = l->next;
        l->dueAt[k] = l->now;
        l->tries[k] = 0;
        l->next     = seq_next(l->next);
    } else {
        if (l->numUnrel >= WL_UNREL_MAX)
            return 0;
        m = &l->unrel[l->numUnrel++];
        m->seq = WL_UNRELIABLE;
    }
    m->type = type;
    m->len  = (uint8_t)n;
    if (n)
        memcpy(m->data, data, n);
    return 1;
}

// ------------------------------------------------------------------ out

typedef struct Packet {
    uint8_t buf[WL_PACKET_MAX];
    size_t  n;
    int     count;
} Packet;

static void packet_begin(WlLink *l, Packet *p)
{
    p->buf[0] = WL_MAGIC;
    p->buf[1] = WL_VERSION;
    wr16(p->buf + 2, l->expect);
    p->n     = WL_HEADER;
    p->count = 0;
}

static void packet_send(WlLink *l, Packet *p)
{
    p->buf[4] = (uint8_t)p->count;
    wr16(p->buf + 5, packet_crc(p->buf, p->n));
    l->send(l->ctx, p->buf, p->n);
    l->packetsOut++;
    l->lastSent = l->now;
    p->n     = WL_HEADER;
    p->count = 0;
}

static void packet_put(WlLink *l, Packet *p, const WlMsg *m)
{
    size_t need = WL_MSG_HEADER + m->len;

    if (p->n + need > WL_PACKET_MAX || p->count == 255)
        packet_send(l, p);
    wr16(p->buf + p->n, m->seq);
    p->buf[p->n + 2] = m->type;
    p->buf[p->n + 3] = m->len;
    memcpy(p->buf + p->n + WL_MSG_HEADER, m->data, m->len);
    p->n += need;
    p->count++;
}

void wl_link_tick(WlLink *l, uint32_t now)
{
    Packet   p;
    uint32_t before = l->packetsOut;
    uint16_t s;
    int      i;

    l->now = now;
    packet_begin(l, &p);
    for (s = l->base; s != l->next; s = seq_next(s)) {
        int k = s % WL_WINDOW;

        if ((int32_t)(now - l->dueAt[k]) < 0)
            continue;
        if (l->tries[k])
            l->resends++;
        if (l->tries[k] < 255)
            l->tries[k]++;
        l->dueAt[k] = now + WL_RESEND_MS;
        packet_put(l, &p, &l->out[k]);
    }
    for (i = 0; i < l->numUnrel; i++)
        packet_put(l, &p, &l->unrel[i]);
    l->numUnrel = 0;
    // Whatever is left, or an ack or a keepalive when nothing went.
    if (p.count > 0
        || (l->packetsOut == before
            && (l->ackDue || (int32_t)(now - l->lastSent) >= WL_KEEPALIVE_MS)))
        packet_send(l, &p);
    l->ackDue = 0;
}

// ------------------------------------------------------------------- in

static int inbox_put(WlLink *l, const WlMsg *m)
{
    if (l->inCount >= WL_INBOX)
        return 0;
    l->inbox[(l->inHead + l->inCount) % WL_INBOX] = *m;
    l->inCount++;
    return 1;
}

// The messages held for the next numbers, while there is room.
static void drain_held(WlLink *l)
{
    for (;;) {
        int k = l->expect % WL_WINDOW;

        if (!l->isHeld[k] || l->held[k].seq != l->expect)
            return;
        if (!inbox_put(l, &l->held[k]))
            return;
        l->isHeld[k] = 0;
        l->expect    = seq_next(l->expect);
    }
}

static void take(WlLink *l, const WlMsg *m)
{
    uint16_t d;
    int      k;

    if (m->seq == WL_UNRELIABLE) {
        if (!inbox_put(l, m))
            l->dropped++;
        return;
    }
    l->ackDue = 1;
    d = seq_diff(m->seq, l->expect);
    k = m->seq % WL_WINDOW;
    // Delivered already (or from beyond the window, which a sender keeping
    // to it never sends), or held already.
    if (d >= WL_WINDOW || l->isHeld[k]) {
        l->repeats++;
        return;
    }
    // Held until those before it have come and the inbox has room. Until
    // then it is not acked, so the other side sends it again.
    l->held[k]   = *m;
    l->isHeld[k] = 1;
    drain_held(l);
}

void wl_link_packet_in(WlLink *l, const uint8_t *buf, size_t n)
{
    size_t   at;
    uint16_t ack;
    int      count, i;

    if (n < WL_HEADER || buf[0] != WL_MAGIC || buf[1] != WL_VERSION)
        goto bad;
    if (rd16(buf + 5) != packet_crc(buf, n))
        goto bad;
    ack   = rd16(buf + 2);
    count = buf[4];
    if (ack & WL_UNRELIABLE)
        goto bad;
    at = WL_HEADER;
    for (i = 0; i < count; i++) {
        uint16_t seq;
        size_t   len;

        if (at + WL_MSG_HEADER > n)
            goto bad;
        seq = rd16(buf + at);
        len = buf[at + 3];
        if ((seq & WL_UNRELIABLE) && seq != WL_UNRELIABLE)
            goto bad;
        if (len > WL_MSG_MAX)
            goto bad;
        at += WL_MSG_HEADER + len;
    }
    // One that runs past the end leaves `at` past it too.
    if (at != n)
        goto bad;

    l->packetsIn++;
    l->heard     = 1;
    l->lastHeard = l->now;
    // Every number below the ack is delivered: forget them. An ack from
    // before the last (a packet overtaken) or past what was sent says
    // nothing new.
    if (seq_diff(ack, l->base) <= seq_diff(l->next, l->base))
        l->base = ack;
    at = WL_HEADER;
    for (i = 0; i < count; i++) {
        WlMsg m;

        m.seq  = rd16(buf + at);
        m.type = buf[at + 2];
        m.len  = buf[at + 3];
        memcpy(m.data, buf + at + WL_MSG_HEADER, m.len);
        at += WL_MSG_HEADER + m.len;
        take(l, &m);
    }
    return;
bad:
    l->malformed++;
}

int wl_link_recv(WlLink *l, WlMsg *out)
{
    if (l->inCount == 0)
        return 0;
    *out = l->inbox[l->inHead];
    l->inHead = (l->inHead + 1) % WL_INBOX;
    l->inCount--;
    // Room again: the next message held for it.
    drain_held(l);
    return 1;
}

int wl_link_alive(const WlLink *l)
{
    return l->heard && (int32_t)(l->now - l->lastHeard) < WL_TIMEOUT_MS;
}

int wl_link_unacked(const WlLink *l)
{
    return seq_diff(l->next, l->base);
}
