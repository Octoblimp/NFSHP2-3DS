// wlproto -- the local wireless link's protocol, the port's (TASKS 37a).
//
// Retail's two players share one PS2. The port's share the air: two
// consoles, each with its own card, run the same race and send each other
// only small messages (TASKS 37, "The design"). UDS, the 3DS's local
// wireless, carries frames of up to 1478 bytes and loses some, repeats
// some and swaps some round. This is the layer over it that does not:
//
//   - A reliable message reaches the other console once, intact, in the
//     order it was sent, or the link is lost. Each one carries a 15-bit
//     sequence number. Every packet carries an ack, the next number its
//     sender has yet to deliver, so the other side can forget all below
//     it. One not acked within WL_RESEND_MS goes again, up to WL_WINDOW of
//     them at a time.
//   - An unreliable message goes in the next packet only. It may be lost,
//     arrive twice, or overtake another. The race's per-frame messages
//     are of this kind, and each repeats the last few frames, so a frame
//     lost on the air comes in the next packet.
//
// Each packet carries a CRC-16 of itself. UDS's own checks make a
// damaged frame rare, but a packet the CRC or the framing rejects is
// counted and dropped whole, so nothing in it is believed.
//
// It knows nothing of UDS: wireless.c hands it each packet that comes in
// and the time, and it hands back the packets to send through `send`.
// tools/wlproto_check.py runs two links over a channel that drops,
// repeats, delays and cuts packets. docs/formats/wireless.md has the
// packet's layout.

#ifndef WLPROTO_H
#define WLPROTO_H

#include <stddef.h>
#include <stdint.h>

#define WL_MAGIC        0x48u    // 'H'
#define WL_VERSION      1u
#define WL_PACKET_MAX   1024     // under UDS's 1478
#define WL_HEADER       7        // magic, version, ack (2), count, crc (2)
#define WL_MSG_HEADER   4        // seq (2), type, len
#define WL_MSG_MAX      240      // a message's payload
#define WL_WINDOW       32       // reliable messages in flight
#define WL_UNREL_MAX    8        // unreliable messages for the next packet
#define WL_INBOX        64       // messages waiting to be read
#define WL_RESEND_MS    100
#define WL_KEEPALIVE_MS 100
#define WL_TIMEOUT_MS   3000

#define WL_SEQ_MASK     0x7fffu
#define WL_UNRELIABLE   0x8000u  // in a message's seq

typedef struct WlMsg {
    uint16_t seq;                // the sequence number, or WL_UNRELIABLE
    uint8_t  type;
    uint8_t  len;
    uint8_t  data[WL_MSG_MAX];
} WlMsg;

typedef void (*WlSendFn)(void *ctx, const uint8_t *buf, size_t n);

typedef struct WlLink {
    WlSendFn send;
    void    *ctx;
    uint32_t now;                // ms, as wl_link_tick last had it
    uint32_t lastHeard;          // a well-formed packet came
    uint32_t lastSent;
    int      heard;              // anything at all yet
    uint32_t timeout;            // ms of silence that lose it

    // Out: the reliable messages from base up to next, not yet acked,
    // each in out[seq % WL_WINDOW] with when it is due to go (again) and
    // how often it has gone.
    uint16_t base, next;
    WlMsg    out[WL_WINDOW];
    uint32_t dueAt[WL_WINDOW];
    uint8_t  tries[WL_WINDOW];
    WlMsg    unrel[WL_UNREL_MAX];
    int      numUnrel;

    // In: the next number to deliver; the reliable messages taken and
    // not yet in the inbox, each in held[seq % WL_WINDOW] (those come
    // early, and the next when the inbox is full); and what is waiting to
    // be read.
    uint16_t expect;
    WlMsg    held[WL_WINDOW];
    uint8_t  isHeld[WL_WINDOW];
    WlMsg    inbox[WL_INBOX];
    int      inHead, inCount;
    int      ackDue;             // a reliable message came: ack it

    // What happened, for the log; `dropped` counts the unreliable
    // messages that found the inbox full.
    uint32_t packetsIn, packetsOut, malformed, repeats, resends, dropped;
} WlLink;

void wl_link_init(WlLink *l, WlSendFn send, void *ctx, uint32_t now);

// Queues a message: 1, or 0 when it cannot go (the window or the
// unreliable queue is full, or it is too long).
int wl_link_send(WlLink *l, uint8_t type, const void *data, size_t n,
                 int reliable);

// A packet off the air. One that is not well formed is counted and
// dropped whole.
void wl_link_packet_in(WlLink *l, const uint8_t *buf, size_t n);

// The time moves on to `now` (ms); sends what is due: the new messages,
// those to go again, and an ack or a keepalive.
void wl_link_tick(WlLink *l, uint32_t now);

// The next message to read into *out: 1, or 0 for none.
int wl_link_recv(WlLink *l, WlMsg *out);

// The same, left to be read: a reader that takes only its own messages
// leaves another's for its reader (netstep.c, the lobby's after a race).
int wl_link_peek(const WlLink *l, WlMsg *out);

// Heard from within the link's timeout, WL_TIMEOUT_MS until set.
int wl_link_alive(const WlLink *l);

// The silence that loses the link from now on: longer while a console
// loads a track and its loop stops for seconds (netrace.c). 0 is
// WL_TIMEOUT_MS.
void wl_link_set_timeout(WlLink *l, uint32_t ms);

// Reliable messages sent and not yet acked.
int wl_link_unacked(const WlLink *l);

#endif
