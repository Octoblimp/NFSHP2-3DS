// netstep -- a local wireless race run in lockstep, the port's (TASKS 37d).
//
// Retail's two players share one PS2, so one game reads both pads. The
// port's are on consoles of their own (TASKS 37, "The design"): each runs
// the whole race, and they stay the same race by running the same frames
// on the same input. From GO on (netrace.h), frame by frame:
//
//   - Each console reads its own pad and sends it for the frame
//     NETSTEP_DELAY ahead: a DualShock's buttons and sticks as joyhid
//     builds them (bytes 2 to 7; the pressures follow from the buttons)
//     and the presses the flow's screens take (the pause menu, the
//     results).
//   - The host puts its own pad and the step it measured, its frame's
//     time, into the record of that frame once every place racing has
//     sent its pad for it, and sends the records on to the clients.
//   - Every console runs frame n on record n alone: its step for the
//     world's, place 0's pad on port 0 and place 1's on port 1, and every
//     place's presses for the flow, each on its port. A console waits for
//     the record it needs, the host for the pads it needs.
//
// Frames 0 to NETSTEP_DELAY - 1 need no wait: no pad is in for them, and
// each console makes them as the host would, every pad at rest, each
// step NETSTEP_Q_FIRST.
//
// All of it goes unreliably (wlproto.h): each message says what its
// sender still needs, and repeats everything the other side has not said
// it got, so a lost one is made good by the next. The race's link keeps
// netrace's patience until frames have flowed for NETSTEP_SETTLE, past
// the first frame's long drawing, and then has its own timeout back.
//
// A console lost (37g): the host builds no record without a client
// whose link is lost, so the race holds on every console, for the hold
// (NETSTEP_HOLD_MS, netstep_set_hold). Each message of the host's says
// which places are waited for and the seconds left (netstep_held), for
// the screen. Past the hold the host builds without the place, its pad at
// rest, and every console hands its car to the CPU on the first record
// without its bit. A client that loses the host holds the same way, then
// goes on alone: its own pad on its place, the rest at rest, every other
// car the CPU's. A console already gone at the first poll is not waited
// for. A link that comes back in the hold (37g-2: main.c re-peers it, the
// host letting the console back only while it holds for its place) is
// taken back. The host sends the place its records again, and the client,
// once they come, goes on from the frame it held on and sends its pads;
// once those come, the host says the place is back and builds with it
// again from the record it held on. Either end back on the link as its
// hold ends waits up to NETSTEP_BACK_MS more for the other's word, and a
// console on the link that sends no pads (one restarted, not in the race)
// is gone once that is over.
//
// The end (37f). Each console stops where its race leaves lockstep
// (netstep_stop: the race gone, or the end's save, main.c), all of them
// on the same frame, as they run the same flow; every message then says
// how many frames its sender ran. A client still behind may need records
// the host ran, so the host serves them on (netstep_drain) until each
// client has said it stopped, is gone, or NETSTEP_DRAIN_MS have passed. A
// stopped client says so NETSTEP_TELLS times, NETSTEP_RESEND_MS apart,
// and reads nothing more: what comes next on the link is the lobby's.
// Should the two ever part, a client that stops first has left (the host
// goes on without it, as without one gone), and a client still on past
// the host's last frame goes on alone, and says it stopped. Neither reads
// past a message not the race's (NetStepNet's peek): it is the lobby's,
// left for it, and says its sender has gone on, as a stop would.
//
// Each console also says, in every message, its checksum of the world
// after the last frame it ran. A console that has run that frame itself
// and has another says so in the log, once for each place, and tells its
// NetStepDifferFn (37e: lockhash.h logs the world's parts then).
//
// Host-buildable: the link is the NetStepNet's and the time is given, so
// tools/src/netstep_test.c can run eight consoles in one process
// (netstep_bind).

#ifndef NETSTEP_H
#define NETSTEP_H

#include <stddef.h>
#include <stdint.h>

#include "wireless.h"

#define NETSTEP_MAX        WIRELESS_MAX_CONSOLES
#define NETSTEP_DELAY      3      // frames from a pad's read to its use
#define NETSTEP_RING       64     // frames kept, a power of two
#define NETSTEP_PAD_BYTES  6      // a DualShock buffer's bytes 2 to 7
#define NETSTEP_Q_FIRST    120    // the first frames' step: 1/30 s
#define NETSTEP_RESEND_MS  16     // what is still wanted goes again
#define NETSTEP_SETTLE     30     // frames before the link's own timeout
#define NETSTEP_LOG_EVERY  150    // frames between the log's checksums
#define NETSTEP_TELLS      30     // a client's stop said this many times
#define NETSTEP_DRAIN_MS   10000  // the host's last frames served at most
#define NETSTEP_HOLD_MS    90000  // a lost console waited for (37g)
#define NETSTEP_BACK_MS    3000   // a console back, its word waited for past
                                  // the hold (37g-2)
#define NETSTEP_NONE       0xffffffffu

// The race's unreliable messages, after netrace's.
enum {
    NETSTEP_MSG_PADS = 0x16,  // a client's: its pads from the host's need
    NETSTEP_MSG_FRAMES,       // the host's: the records from a client's
};

typedef struct NetStepPad {
    uint8_t  ds2[NETSTEP_PAD_BYTES];  // buttons (active low), then sticks
    uint16_t menu;                    // the 3DS keys pressed, for the flow
} NetStepPad;

typedef struct NetStepFrame {
    uint32_t   n;                     // the frame
    uint8_t    q;                     // its step, in 1/3600 s
    uint8_t    live;                  // the places racing, a bit each
    NetStepPad pad[NETSTEP_MAX];      // at rest for a place not live
} NetStepFrame;

typedef struct NetStepNet {
    int  (*peerAlive)(int i);
    int  (*send)(int i, uint8_t type, const void* data, size_t n);
    int  (*recv)(int i, WlMsg* out);
    int  (*peek)(int i, WlMsg* out);      // recv's next, left to be read
    void (*setPatience)(uint32_t ms);
} NetStepNet;

typedef void (*NetStepLogFn)(const char* line);

// Told after the log's line that place `place`'s checksum of frame
// `frame` differs from this console's: once for each place (37e,
// lockhash_differs).
typedef void (*NetStepDifferFn)(int place, uint32_t frame);

typedef struct NetStep {
    NetStepNet   net;
    NetStepLogFn log;
    NetStepDifferFn differ;
    int          on;
    int          host;
    int          place;
    int          peer[NETSTEP_MAX];          // by place, as the lobby's
    uint8_t      live;                       // the host's; a client's own
    int          alone;                      // a client without its host
    uint32_t     frame;                      // the next to run
    uint32_t     put;                        // the next of this console's
    uint32_t     built;                      // the next record not in
    int          settled;                    // the link's timeout back
    // Each place's pads by frame (padFor: the frame, or NETSTEP_NONE),
    // and the step that came with this console's own.
    NetStepPad   pads[NETSTEP_MAX][NETSTEP_RING];
    uint32_t     padFor[NETSTEP_MAX][NETSTEP_RING];
    uint8_t      q[NETSTEP_RING];
    NetStepFrame recs[NETSTEP_RING];         // recs[i].n: NETSTEP_NONE
    // The host's, by place: the next record the client has yet to get,
    // and whether one was built since the last send to it.
    uint32_t     need[NETSTEP_MAX];
    int          fresh[NETSTEP_MAX];
    // A client's: the first of its pads the host still needs.
    uint32_t     padNeed;
    uint32_t     lastSend[NETSTEP_MAX];      // ms, by place
    // Checksums by frame (hashFor, theirFor: the frame, or NETSTEP_NONE):
    // this console's, and each place's as it said them.
    uint16_t     hash[NETSTEP_RING];
    uint32_t     hashFor[NETSTEP_RING];
    uint16_t     theirHash[NETSTEP_MAX][NETSTEP_RING];
    uint32_t     theirFor[NETSTEP_MAX][NETSTEP_RING];
    int          differs[NETSTEP_MAX];       // said once
    uint32_t     sendFails;
    // The hold (37g). By place, a link lost and when (ms): the host's of
    // each client, a client's of the host (place 0). The host's, by place:
    // pads come from one lost, its link re-peered (37g-2). A client's: what
    // the host's last message said it holds for, and the seconds left.
    uint32_t     holdMs;
    int          polled;                     // the first poll made
    int          lost[NETSTEP_MAX];
    uint32_t     lostAt[NETSTEP_MAX];
    int          back[NETSTEP_MAX];
    uint8_t      held;
    uint8_t      heldLeft;
    // The end. stopAt: the frames run when this console left lockstep,
    // by its stop or a client's going alone past the host's, which every
    // message says; NETSTEP_NONE before. The host's, by place: each that
    // said it stopped. A client's: the host's stopAt as it said it, and
    // its own stop still to say (tells, the sends left).
    uint32_t     stopAt;
    int          ending;                     // stopped, and not done
    uint32_t     endFrom;                    // ms, the stop
    int          left[NETSTEP_MAX];
    uint32_t     hostStop;
    int          tells;
} NetStep;

// The one running: netstep's own unless bound to another (NULL: its own).
void netstep_bind(NetStep* s);

void netstep_init(const NetStepNet* net, NetStepLogFn log);

// Who is told of a checksum that differs (NULL: no one). Kept from GO to
// GO, as the link and the log are.
void netstep_on_differ(NetStepDifferFn fn);

// How long a lost console is waited for, in ms (0: NETSTEP_HOLD_MS). Kept
// from GO to GO.
void netstep_set_hold(uint32_t ms);

// GO: this console's place, the link's peer of each place (-1 for none;
// past `consoles` not read), and the places racing, this one among them.
void netstep_start(int place, int consoles, const int peer[NETSTEP_MAX],
                   uint8_t racing);
int  netstep_on(void);

// After the last frame this console runs in lockstep, at `now` in ms:
// no frame is current from then on. netstep_drain, once a loop from then
// until netstep_ending says 0, serves the host's last frames, or says a
// client's stop.
void netstep_stop(uint32_t now);
void netstep_drain(uint32_t now);
int  netstep_ending(void);

// This console's pad for the frame NETSTEP_DELAY past the one to run,
// and the step it measured (the host's goes into that frame's record).
// Once a frame, before netstep_poll.
void netstep_put(const NetStepPad* pad, uint8_t q);

// What came in, the host's records built, and what is due sent: 1 once
// the frame to run is in.
int  netstep_poll(uint32_t now);

// The frame to run, once netstep_poll has said so; else NULL.
const NetStepFrame* netstep_current(void);

// The frame ran, the world's checksum after it: on to the next.
void netstep_done(uint16_t hash);

uint32_t netstep_frame(void);

// The pad of a place at rest.
void netstep_rest(NetStepPad* pad);

// The places the race holds for, their links lost, a bit each (0: none),
// and the ms left before it goes on without them.
uint8_t netstep_held(uint32_t now, uint32_t* msLeft);

#endif
