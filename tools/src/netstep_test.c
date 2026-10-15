// Host harness for a local wireless race in lockstep (netstep.c, TASKS 37d,
// and its end, 37f).
//
// Builds "3DS Files/source/netstep.c" and runs up to eight consoles of it
// in one process, each with its own NetStep (netstep_bind), on one clock
// in milliseconds. Console 0 hosts; console p is place p. Between them is
// a fake of the link's unreliable messages: each takes the scenario's
// latency and jitter (so they overtake each other), and some are lost or
// come twice, and those that find WL_INBOX waiting are dropped, as the
// link's inbox drops them; in one scenario junk of netstep's own types
// goes with them. The host's peers are numbered the other way round from
// the places, and the peers past the consoles are junk. A link is lost
// once the console at its other end has not pumped it for the link's
// timeout: the patience the race set, or its own 3 s once netstep gave it
// back, or main.c's after the stop; or at once, both ways, where a
// scenario has a console vanish at its stop or before the start. A link
// lost stays lost, both ways, as wireless.c's does (the host sends the
// client off), and has no inbox, until a scenario re-peers it (37g-2):
// main.c's rejoin, tried each second while the client holds for its host
// and the host for that place, the link new with nothing of the old on
// it. A scenario can cut a client's link to the host: nothing goes over
// it from then, so each end finds it lost by its timeout, as a console
// out of range does. A console pumps every millisecond but when it is
// gone, in its first frame's drawing, in a stall after its stop (its
// save, its unload), or while its loop is frozen (it comes back after to
// its link lost).
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
// The end, as main.c has it: after the scenario's last frame for it a
// console stops (netstep_stop), gives the link netrace's patience
// (netrace_end), and drains (netstep_drain) each millisecond while
// netstep_ending says so. Its lobby then reads the link, everything on it,
// and says it is back (LOBBY_MSG_BACK, a reliable message here never
// lost) when the scenario has it so.
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
//   - the places racing: never one that is not, one gone or stopped
//     dropped once and never back, none dropped that is on;
//   - the hold (37g): a console whose link is lost said lost, and said
//     gone no sooner than the hold after, nor more than a few ms past it;
//     one gone before the start said so and never held for; a client that
//     loses its host alone no sooner than the hold after; netstep_held's
//     places on the host those it said lost and not yet gone, on a client
//     what the host said or its host lost, the time left never more than
//     the hold, and every console still on held for each place lost,
//     and alone for none;
//   - a link re-peered while both ends held (37g-2): back said once on
//     each end, by the host no later than the hold, by the client no
//     later than NETSTEP_BACK_MS past it; neither end gone nor alone, and
//     no record without the place; one re-peered too late never back;
//   - every message no longer than WL_MSG_MAX, to a peer there is and
//     over a link not lost, a
//     client's PADS and the host's FRAMES only; from a client alone only
//     its stop, and after a console's stop only its stop (a client's with
//     no pads), and nothing once it has ended; no link with more than
//     MAX_RATE a second;
//   - netstep never reads the lobby's message, and each one sent reaches
//     its console's lobby;
//   - the link's patience kept until frames flow, and then its own given
//     back once;
//   - the log: a checksum every NETSTEP_LOG_EVERY frames, "differs" only
//     where the scenario makes a console's checksum differ, once for each
//     place, and the gone, alone, stopped, left, gone-on, drained and
//     given-up lines as the scenario has them;
//   - every console still on reaching the scenario's last frame, or its
//     stop, and on a clean link, a fast one or a slow, no frame waited on
//     long;
//   - after netstep_stop nothing is in, and every drain ends.
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
#define HEADER    21      // netstep.c's
#define HOLD_SLACK 3u     // ms a hold may run past its end: polls a ms
#define MSG_BACK  0x18    // lobby.h's LOBBY_MSG_BACK
#define TAIL_MS   3000u   // run on once all is done, for what is in flight

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
    int         stopAt[MAXC];       // frames it runs before its stop, 0:
                                    // none (it runs `frames` and waits on)
    int         stallAfterStop[MAXC];   // ms its loop stops for after it
    int         backAfter[MAXC];    // its lobby's back this many ms, less
                                    // one, after its stop; 0: never
    int         deafAfterStop;      // consoles that hear no message of
                                    // netstep's once stopped, a bit each
    int         vanishAtStop;       // consoles gone at their stop, their
                                    // link lost at once, a bit each
    int         outageAtStop;       // ms every message is lost from the
                                    // first stop on
    int         giveUp;             // the host's drain gives up
    int         goneOn;             // clients that see the host's lobby
                                    // before its stop, a bit each
    int         maxWait;            // ms a frame may wait on, 0: no check
    int         maxRun;             // ms all its frames may take, 0: any
    int         junk;               // ms between junk messages, 0: none
    int         hold;               // ms a lost console is held for, 0:
                                    // netstep's own
    int         vanishAtStart;      // consoles racing but gone before the
                                    // first poll, a bit each
    int         freezeAt[MAXC];     // ms its loop stops, 0: never
    int         freezeFor[MAXC];    // ms it stays stopped
    int         dropAt[MAXC];       // ms a client's link to the host is
                                    // cut, 0: never (37g-2)
    int         repeerAt[MAXC];     // ms from which its rejoin is tried,
                                    // each second, 0: never
    int         dropAgain[MAXC];    // ms its link is cut again, once
                                    // back, 0: never
    int         repeerLate;         // clients whose rejoin is tried each
                                    // ms, taken only 2 ms or less before
                                    // its hold ends, a bit each
    int         repeerHalf;         // clients whose rejoin brings up its
                                    // own end alone: it sees the host,
                                    // which never sees it, a bit each
    int         repeerMute;         // clients whose rejoin brings up the
                                    // host's end alone: the host sees it,
                                    // and it hears nothing and sends no
                                    // pads (one restarted), a bit each
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
      .latency = 5, .goneAt = { 0, 0, 3000 }, .hold = 5000 },
    // Held for netstep's own 1:30 (37g).
    { .name = "two, the client gone", .consoles = 2, .frames = 500,
      .latency = 5, .goneAt = { 0, 4000 } },
    { .name = "two, the host gone", .consoles = 2, .frames = 500,
      .latency = 5, .goneAt = { 4000, 0 } },
    { .name = "three, the host gone", .consoles = 3, .frames = 500,
      .latency = 5, .jitter = 10, .lossPct = 10, .goneAt = { 5000, 0, 0 },
      .hold = 7000 },
    { .name = "three, place 1 gone, a lossy link", .consoles = 3,
      .frames = 500, .latency = 4, .jitter = 20, .lossPct = 20,
      .dupPct = 5, .goneAt = { 0, 4000 }, .hold = 6000 },
    // Place 2's link lost to the host at 6 s, the host gone at 7 s while
    // it holds: place 1 holds for place 2 on the host's word, then for
    // the host, then races alone, the host's word gone with it.
    { .name = "three, place 2 gone, then the host while it holds",
      .consoles = 3, .frames = 500, .latency = 5,
      .goneAt = { 7000, 0, 3000 }, .hold = 8000 },
    // Gone before the first poll: not held for.
    { .name = "three, place 2 gone at the start", .consoles = 3,
      .frames = 300, .latency = 5, .vanishAtStart = 0x04 },
    { .name = "two, the host gone at the start", .consoles = 2,
      .frames = 300, .latency = 5, .vanishAtStart = 0x01 },
    // A loop stopped past the link's timeout: its link lost for good.
    // Each side holds for the other, then goes on without it.
    { .name = "two, the client's loop frozen 6 s", .consoles = 2,
      .frames = 400, .latency = 5, .freezeAt = { 0, 4000 },
      .freezeFor = { 0, 6000 }, .hold = 20000 },
    { .name = "two, the host's loop frozen 5 s", .consoles = 2,
      .frames = 400, .latency = 5, .freezeAt = { 3000, 0 },
      .freezeFor = { 5000, 0 }, .hold = 6000 },
    { .name = "three, place 2's loop frozen 5 s, a lossy link",
      .consoles = 3, .frames = 400, .latency = 4, .jitter = 15,
      .lossPct = 15, .freezeAt = { 0, 0, 3000 },
      .freezeFor = { 0, 0, 5000 }, .hold = 8000 },
    // Stopped for less than the link's timeout: nothing lost.
    { .name = "two, the client's loop frozen 2 s", .consoles = 2,
      .frames = 400, .latency = 5, .freezeAt = { 0, 4000 },
      .freezeFor = { 0, 2000 }, .hold = 8000 },
    // A link cut, each end on (37g-2): lost to both at 7 s, re-peered at
    // 9 s, and on from the frame it held on.
    { .name = "two, the client's link cut, back in the hold", .consoles = 2,
      .frames = 500, .latency = 5, .dropAt = { 0, 4000 },
      .repeerAt = { 0, 9000 }, .hold = 20000 },
    // Back on the host's word as the client's hold ends: it waits on.
    { .name = "two, the client's link cut, back as its hold ends",
      .consoles = 2, .frames = 400, .latency = 5, .dropAt = { 0, 4000 },
      .repeerAt = { 0, 5000 }, .repeerLate = 0x02, .hold = 6000 },
    // The client on the link again, the host never: no word comes, and
    // it goes on alone once it has waited for it.
    { .name = "two, the client's link cut, its rejoin half up",
      .consoles = 2, .frames = 400, .latency = 5, .dropAt = { 0, 4000 },
      .repeerAt = { 0, 9000 }, .repeerHalf = 0x02, .hold = 8000 },
    // Lost, back, lost again and back again: nothing of the first time
    // left over.
    { .name = "two, the client's link cut twice, back each time",
      .consoles = 2, .frames = 700, .latency = 5, .dropAt = { 0, 4000 },
      .repeerAt = { 0, 9000 }, .dropAgain = { 0, 14000 }, .hold = 20000 },
    // The host's end on the link again, no pad ever from it (as a
    // console restarted and joined, 37g-3's): the host waits past the
    // hold for its pads, then it is gone.
    { .name = "two, the client's link cut, back with no pads",
      .consoles = 2, .frames = 400, .latency = 5, .dropAt = { 0, 4000 },
      .repeerAt = { 0, 9000 }, .repeerMute = 0x02, .hold = 8000 },
    { .name = "two, the client's link cut, its rejoin too late",
      .consoles = 2, .frames = 400, .latency = 5, .dropAt = { 0, 4000 },
      .repeerAt = { 0, 14000 }, .hold = 5000 },
    // Place 1 held for place 2, back first, then on the host's word.
    { .name = "three, both links cut, back one after the other",
      .consoles = 3, .frames = 500, .latency = 5, .dropAt = { 0, 4000, 4000 },
      .repeerAt = { 0, 8000, 10000 }, .hold = 15000 },
    { .name = "three, place 2's link cut, back, a lossy link",
      .consoles = 3, .frames = 500, .latency = 4, .jitter = 15,
      .lossPct = 15, .dupPct = 5, .dropAt = { 0, 0, 3000 },
      .repeerAt = { 0, 0, 7000 }, .hold = 10000 },
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
    { .name = "four, all gone but the host", .consoles = 4, .frames = 400,
      .latency = 5, .goneAt = { 0, 2000, 3000, 2500 }, .hold = 4000 },
    { .name = "three, junk on the race's link", .consoles = 3,
      .frames = 300, .latency = 5, .jitter = 10, .junk = 7 },

    // -- the end (37f). Every console of a race stops on the same frame,
    // as main.c stops each where the end's save is asked for.
    { .name = "two, both stop", .consoles = 2, .frames = 300,
      .latency = 5, .stopAt = { 300, 300 } },
    { .name = "two, both stop, a lossy link", .consoles = 2, .frames = 300,
      .latency = 4, .jitter = 20, .lossPct = 20, .dupPct = 5,
      .stopAt = { 300, 300 } },
    { .name = "two, both stop, the host slow", .consoles = 2,
      .frames = 300, .latency = 5, .period = { 50, 20 },
      .stopAt = { 300, 300 } },
    { .name = "two, both stop, the client slow", .consoles = 2,
      .frames = 300, .latency = 5, .period = { 20, 55 },
      .stopAt = { 300, 300 } },
    { .name = "eight, all stop, a lossy link", .consoles = 8, .frames = 300,
      .latency = 3, .jitter = 15, .lossPct = 15, .dupPct = 5,
      .period = { 33, 30, 36, 33, 40, 28, 33, 35 },
      .stopAt = { 300, 300, 300, 300, 300, 300, 300, 300 } },
    { .name = "two, both stop, the host's loop held after", .consoles = 2,
      .frames = 300, .latency = 5, .period = { 20, 30 },
      .stopAt = { 300, 300 }, .stallAfterStop = { 2000, 0 } },
    { .name = "two, both stop, the client's loop held after",
      .consoles = 2, .frames = 300, .latency = 5, .period = { 30, 20 },
      .stopAt = { 300, 300 }, .stallAfterStop = { 0, 5000 } },
    { .name = "three, both stop, place 2 gone", .consoles = 3,
      .frames = 300, .latency = 5, .goneAt = { 0, 0, 3000 },
      .stopAt = { 300, 300 }, .hold = 5000 },
    { .name = "two, both stop, both back", .consoles = 2, .frames = 300,
      .latency = 5, .jitter = 10, .stopAt = { 300, 300 },
      .backAfter = { 1000, 1500 } },
    // The client's stop and then its lobby's, all in at once.
    { .name = "two, both stop, the host held, the client back soon",
      .consoles = 2, .frames = 300, .latency = 5, .period = { 20, 30 },
      .stopAt = { 300, 300 }, .stallAfterStop = { 2000, 0 },
      .backAfter = { 0, 50 } },
    { .name = "two, both stop, the link out at the stop", .consoles = 2,
      .frames = 300, .latency = 5, .stopAt = { 300, 300 },
      .outageAtStop = 300 },
    { .name = "three, all stop, place 2's link lost at its stop",
      .consoles = 3, .frames = 300, .latency = 5, .period = { 20, 55, 55 },
      .stopAt = { 300, 300, 300 }, .vanishAtStop = 0x04 },
    // The client's stop said while the host stops: cut short.
    { .name = "two, both stop, the host's link lost at its stop",
      .consoles = 2, .frames = 300, .latency = 5, .period = { 50, 20 },
      .stopAt = { 300, 300 }, .vanishAtStop = 0x01 },
    // The parted ends: never main.c's, but each must still end. The
    // client slow, the host stops with no record of its last frame.
    { .name = "two, the host stops", .consoles = 2, .frames = 200,
      .latency = 5, .period = { 20, 40 }, .stopAt = { 150 } },
    { .name = "two, the client stops", .consoles = 2, .frames = 300,
      .latency = 5, .stopAt = { 0, 150 } },
    // Past the host's stop, alone, and its own stop while it still says
    // the first.
    { .name = "two, the client stops just past the host's", .consoles = 2,
      .frames = 300, .latency = 5, .stopAt = { 150, 153 } },
    { .name = "two, the client stops, then the host", .consoles = 2,
      .frames = 300, .latency = 5, .stopAt = { 300, 150 },
      .backAfter = { 500, 500 } },
    // The host ahead, back in its lobby before the client has its stop.
    { .name = "two, the host back before the client stops",
      .consoles = 2, .frames = 300, .latency = 5, .period = { 20, 60 },
      .stopAt = { 150, 250 }, .backAfter = { 1, 0 }, .goneOn = 0x02 },
    // The client's stop lost every time: the host gives up, or hears its
    // lobby.
    { .name = "two, the client's stop unheard", .consoles = 2,
      .frames = 300, .latency = 5, .period = { 20, 55 },
      .stopAt = { 300, 300 }, .deafAfterStop = 0x01, .giveUp = 1 },
    { .name = "two, the client's stop unheard, its lobby heard",
      .consoles = 2, .frames = 300, .latency = 5, .period = { 20, 55 },
      .stopAt = { 300, 300 }, .deafAfterStop = 0x01,
      .backAfter = { 0, 2000 } },
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
    int          vanished;       // gone, its link lost at once
    int          stopped;
    uint32_t     stoppedAt;      // ms
    uint32_t     stallTo;        // ms its loop is held until, after it
    int          waiting;        // put, and polling for the frame
    uint32_t     startAt;        // when the next frame starts
    uint32_t     lastStart;
    uint32_t     waitFrom;
    uint32_t     maxWaited;
    uint32_t     ran;            // frames run
    uint32_t     doneAt;         // ms it ran its last
    uint32_t     acc;            // the running hash
    uint32_t     patience;       // as last set, 0 the link's own
    int          patienceSets;   // netstep's
    int          aloneFrom;      // the first record made alone, or -1
    uint8_t      liveSeen;       // the places live in its last record
    int          wasLive[MAXC];
    int          sent;           // messages this tick
    uint32_t     sends;          // and all of them
    uint32_t     pumped;         // ms its loop last pumped the link
    int          backSent;       // its lobby said it is back
    int          backTo;         // the lobby's messages sent to it
    int          backGot;        // and read by its lobby
    int          stopSends;      // its messages that said a stop
    uint32_t     saidStop;       // the first of them's
    char         lines[LINES][160];
    int          numLines;
    int          lineCount;      // all of them, kept or not
    int          differs, goneLines, aloneLines, flowLines, hashLines;
    int          stopLines, drainDone, gaveUp, hostStopSaid, pastLines;
    int          goneOnHost, toldStop;
    int          told;           // NetStepDifferFn calls
    int          saidPlace;      // the last "differs" line's, -1 none yet
    unsigned long saidFrame;
    int          goneSaid[MAXC];
    int          stoppedSaid[MAXC], leftSaid[MAXC], goneOnSaid[MAXC];
    // The hold: lost as said, by place (the host lost a client's place
    // 0's), and when; held for now, and ever, as netstep_held said.
    int          lostSaid[MAXC], startGoneSaid[MAXC];
    uint32_t     lostAt[MAXC];
    uint8_t      lostNow;
    uint8_t      heldSeen;
    int          backSaid[MAXC]; // back as said, by place (37g-2)
    int          repeered;       // its link to the host, a client's
    int          halfUp;         // and that only at its own end
    int          hostUp;         // or only at the host's
    int          frozen;         // its loop stopped, a scenario's freeze
    uint8_t      q[MAXFRAMES + NETSTEP_DELAY + 2];   // its steps put
} Console;

typedef struct {
    int          in;
    NetStepFrame r;
} Truth;

static Console         C[MAXC];
static Pipe            g_pipe[MAXC][MAXC];   // [from][to]
static int             g_lost[MAXC][MAXC];   // a link lost, until re-peered
static uint32_t        g_cutAt[MAXC];        // ms a client's link was cut
static Truth           g_truth[MAXFRAMES + 8];
static const Scenario* S;
static int             g_cur = -1;
static int             g_lobby;              // the lobby reads, not netstep
static uint32_t        g_now;
static uint32_t        g_firstStop;          // ms, 0: none yet
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

static uint32_t get32(const uint8_t* b)
{
    return (uint32_t)b[0] | (uint32_t)b[1] << 8 | (uint32_t)b[2] << 16
         | (uint32_t)b[3] << 24;
}

static int bitsOf(uint8_t v)
{
    int n = 0;
    for (; v; v >>= 1) n += v & 1;
    return n;
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

// Its loop held, after its stop, or frozen: it pumps and reads nothing.
static int held(int c)
{
    if (C[c].frozen) return 1;
    return C[c].stopped && (int32_t)(g_now - C[c].stallTo) < 0;
}

static uint32_t holdOf(void)
{
    return S->hold ? (uint32_t)S->hold : NETSTEP_HOLD_MS;
}

// The cut of the link between a and b, one of them the host; 0: none.
static uint32_t cutOf(int a, int b)
{
    return g_cutAt[a != 0 ? a : b];
}

static int fPeerAlive(int i)
{
    int      t = target(g_cur, i);
    uint32_t timeout, last;

    if (t < 0) return 0;
    if (C[g_cur].vanished || C[t].vanished) return 0;
    if (g_lost[g_cur][t]) return 0;
    timeout = C[g_cur].patience ? C[g_cur].patience : LINK_MS;
    // Cut, nothing of its heard since.
    last = C[t].pumped;
    if (cutOf(g_cur, t) && (int32_t)(last - cutOf(g_cur, t)) > 0)
        last = cutOf(g_cur, t);
    if (g_now - last < timeout) return 1;
    g_lost[g_cur][t] = g_lost[t][g_cur] = 1;
    return 0;
}

static int used(const Pipe* p)
{
    int k, n = 0;
    for (k = 0; k < PIPE; k++) n += p->q[k].used;
    return n;
}

// Into the pipe from `from` to `to`, due after the latency and jitter.
static void put(int from, int to, uint8_t type, const void* data, size_t n)
{
    Pipe* p = &g_pipe[from][to];
    int   k;

    for (k = 0; k < PIPE && p->q[k].used; k++) {
    }
    if (k == PIPE) {
        fault("the pipe %d to %d is full", from, to);
        return;
    }
    p->q[k].used   = 1;
    p->q[k].due    = g_now + (uint32_t)S->latency
                   + (S->jitter ? lcg() % (uint32_t)S->jitter : 0);
    p->q[k].m.seq  = WL_UNRELIABLE;
    p->q[k].m.type = type;
    p->q[k].m.len  = (uint8_t)n;
    memcpy(p->q[k].m.data, data, n);
}

// What netstep may send: its own type; alone, only its stop; once
// stopped, only its stop again (a client's with no pads), and that only
// while it is ending.
static void checkSend(uint8_t type, const uint8_t* d, size_t n)
{
    Console* k    = &C[g_cur];
    uint32_t stop = n >= HEADER ? get32(d + 15) : NETSTEP_NONE;

    if (g_cur == 0 ? type != NETSTEP_MSG_FRAMES : type != NETSTEP_MSG_PADS)
        fault("sent message type %02x", type);
    if (n < HEADER) fault("a message of %u bytes", (unsigned)n);
    if (k->aloneFrom >= 0 && stop == NETSTEP_NONE) fault("sent alone");
    // A stop once said stays what it was; a client says it NETSTEP_TELLS
    // times at most.
    if (stop != NETSTEP_NONE) {
        if (k->stopSends++ == 0) k->saidStop = stop;
        else if (stop != k->saidStop)
            fault("said its stop at %lu, then at %lu",
                  (unsigned long)k->saidStop, (unsigned long)stop);
        if (g_cur != 0 && k->stopSends == NETSTEP_TELLS + 1)
            fault("said its stop more than %d times", NETSTEP_TELLS);
    }
    if (!k->stopped) return;
    if (!k->ns.ending) fault("sent after its end");
    if (stop != k->ns.stopAt)
        fault("sent after its stop at %lu, saying %lu",
              (unsigned long)k->ns.stopAt, (unsigned long)stop);
    if (g_cur != 0 && n > 8 && d[8] != 0) fault("pads sent after its stop");
}

static int fSend(int i, uint8_t type, const void* data, size_t n)
{
    int t = target(g_cur, i);
    int copies;

    if (t < 0) {
        fault("sent to peer %d, which is not there", i);
        return 0;
    }
    // A link lost is never asked again: the host holds for that place,
    // and a client for its host, with nothing sent over it.
    if (g_lost[g_cur][t]) fault("sent to console %d, its link lost", t);
    if (n > WL_MSG_MAX) {
        fault("a message of %u bytes", (unsigned)n);
        return 0;
    }
    checkSend(type, (const uint8_t*)data, n);
    if (C[g_cur].sent >= WL_UNREL_MAX) return 0;   // the packet is full
    C[g_cur].sent++;
    C[g_cur].sends++;
    if (C[t].gone) return 1;
    if (cutOf(g_cur, t)) return 1;
    if (((S->deafAfterStop >> t) & 1) && C[t].stopped) return 1;
    if (S->outageFrom && g_now >= (uint32_t)S->outageFrom
        && g_now < (uint32_t)S->outageTo)
        return 1;
    if (S->outageAtStop && g_firstStop
        && g_now - g_firstStop < (uint32_t)S->outageAtStop)
        return 1;
    if ((int)(lcg() % 100) < S->lossPct) return 1;
    copies = (int)(lcg() % 100) < S->dupPct ? 2 : 1;
    while (copies--) {
        // The inbox full: an unreliable message is dropped.
        if (used(&g_pipe[g_cur][t]) >= WL_INBOX) return 1;
        put(g_cur, t, type, data, n);
    }
    return 1;
}

// The first due message from peer i, the earliest first; -1 for none.
static int next(int i, int* from)
{
    int   t = target(g_cur, i);
    Pipe* p;
    int   k, best = -1;

    *from = t;
    if (t < 0) {
        fault("read from peer %d, which is not there", i);
        return -1;
    }
    // A link lost has no inbox (wireless_peer_link).
    if (g_lost[g_cur][t]) return -1;
    p = &g_pipe[t][g_cur];
    for (k = 0; k < PIPE; k++) {
        if (!p->q[k].used || (int32_t)(g_now - p->q[k].due) < 0) continue;
        if (best < 0 || (int32_t)(p->q[k].due - p->q[best].due) < 0)
            best = k;
    }
    return best;
}

static int fRecv(int i, WlMsg* out)
{
    int from, k = next(i, &from);

    if (k < 0) return 0;
    *out = g_pipe[from][g_cur].q[k].m;
    g_pipe[from][g_cur].q[k].used = 0;
    if (out->type == MSG_BACK && !g_lobby)
        fault("netstep read the lobby's message from peer %d", i);
    return 1;
}

static int fPeek(int i, WlMsg* out)
{
    int from, k = next(i, &from);

    if (k < 0) return 0;
    *out = g_pipe[from][g_cur].q[k].m;
    return 1;
}

// Junk of netstep's own types on the race's link, its length not what
// its count says, which netstep drops whole: to the host a client's pads,
// to a client the host's records.
static void junk(int from, int to)
{
    uint8_t d[WL_MSG_MAX];
    size_t  len = HEADER;
    int     i, n;

    if (C[from].gone || C[from].stopped) return;
    if (used(&g_pipe[from][to]) >= WL_INBOX) return;
    for (i = 0; i < WL_MSG_MAX; i++) d[i] = (uint8_t)lcg();
    n    = to == 0 ? (int)(lcg() % 4) : 1 + (int)(lcg() % 3);
    d[8] = (uint8_t)n;
    for (i = 0; i < n; i++) {
        if (to == 0) {
            len += 8;
            continue;
        }
        d[len + 1] = (uint8_t)(1 + lcg() % 255);   // live
        len += 2 + (size_t)bitsOf(d[len + 1]) * 8;
    }
    len += 1 + lcg() % 7;
    put(from, to, to == 0 ? NETSTEP_MSG_PADS : NETSTEP_MSG_FRAMES, d, len);
}

static void fSetPatience(uint32_t ms)
{
    C[g_cur].patience = ms;
    C[g_cur].patienceSets++;
}

// A place back, as the log said (37g-2): one lost, after as long as it
// was, within NETSTEP_BACK_MS past the hold.
static void backOf(Console* k, int p, unsigned long ms)
{
    uint32_t most = holdOf() + HOLD_SLACK + NETSTEP_BACK_MS;

    k->backSaid[p]++;
    if (!(k->lostNow & (1u << p))) {
        fault("place %d back, not lost", p);
        return;
    }
    if (ms != g_now - k->lostAt[p])
        fault("place %d back after %lu ms, lost %lu ms ago", p, ms,
              (unsigned long)(g_now - k->lostAt[p]));
    if (ms > most) fault("place %d back %lu ms after it was lost", p, ms);
    k->lostNow &= (uint8_t)~(1u << p);
}

static void fLog(const char* line)
{
    Console*      k = &C[g_cur];
    int           p;
    unsigned long n, ms;
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
            // On the link again, its pads waited for.
            uint32_t from = holdOf() + (C[p].hostUp ? NETSTEP_BACK_MS : 0);

            if (!k->lostSaid[p]) fault("place %d gone, never lost", p);
            else if (g_now - k->lostAt[p] < from
                     || g_now - k->lostAt[p] > from + HOLD_SLACK)
                fault("place %d gone %lu ms after it was lost", p,
                      (unsigned long)(g_now - k->lostAt[p]));
            k->lostNow &= (uint8_t)~(1u << p);
        }
    }
    if (sscanf(line, "netstep: place %d lost at frame %lu; held for", &p, &n)
            == 2 && p >= 0 && p < MAXC) {
        if (k->lostNow & (1u << p)) fault("place %d said lost twice", p);
        k->lostSaid[p]++;
        k->lostAt[p] = g_now;
        k->lostNow |= (uint8_t)(1u << p);
    }
    if (strstr(line, " was gone at the start")
        && sscanf(line, "netstep: place %d", &p) == 1 && p >= 0 && p < MAXC) {
        if (k->startGoneSaid[p]) fault("place %d said gone at the start "
                                       "twice", p);
        k->startGoneSaid[p] = 1;
    }
    if (sscanf(line, "netstep: place %d back at frame %lu, after %lu ms", &p,
               &n, &ms) == 3 && p > 0 && p < MAXC)
        backOf(k, p, ms);
    if (sscanf(line, "netstep: the host back at frame %lu, after %lu ms", &n,
               &ms) == 2)
        backOf(k, 0, ms);
    if (sscanf(line, "netstep: the host lost at frame %lu; held for", &n)
        == 1) {
        if (k->lostNow & 1u) fault("the host said lost twice");
        k->lostSaid[0]++;
        k->lostAt[0] = g_now;
        k->lostNow |= 1u;
    }
    if (sscanf(line, "netstep: place %d stopped after %lu frames", &p, &n)
            == 2 && p >= 0 && p < MAXC) {
        if (k->stoppedSaid[p]) fault("place %d said stopped twice", p);
        k->stoppedSaid[p] = 1;
    }
    if (sscanf(line, "netstep: place %d left, from frame %lu", &p, &n) == 2
        && p >= 0 && p < MAXC) {
        if (k->leftSaid[p]) fault("place %d said left twice", p);
        k->leftSaid[p] = 1;
    }
    if (strstr(line, " has gone on, its stop unheard")
        && sscanf(line, "netstep: place %d", &p) == 1 && p >= 0 && p < MAXC) {
        if (k->goneOnSaid[p]) fault("place %d said gone on twice", p);
        k->goneOnSaid[p] = 1;
    }
    if (sscanf(line, "netstep: the host is gone, from frame %lu", &n) == 1) {
        // On the link again, the host's word waited for.
        uint32_t from = holdOf() + (k->halfUp ? NETSTEP_BACK_MS : 0);

        k->aloneLines++;
        k->aloneFrom = (int)n;
        if (k->lostNow & 1u) {
            if (g_now - k->lostAt[0] < from
                || g_now - k->lostAt[0] > from + HOLD_SLACK)
                fault("alone %lu ms after the host was lost",
                      (unsigned long)(g_now - k->lostAt[0]));
            k->lostNow &= (uint8_t)~1u;
        } else if (!(S->vanishAtStart & 1)) {
            fault("alone, the host never lost");
        }
    }
    if (sscanf(line, "netstep: past the host's stop, from frame %lu", &n)
        == 1) {
        k->pastLines++;
        k->aloneFrom = (int)n;
    }
    if (sscanf(line, "netstep: the host has gone on, from frame %lu", &n)
        == 1) {
        k->goneOnHost++;
        k->aloneFrom = (int)n;
    }
    if (sscanf(line, "netstep: the host stopped after %lu frames", &n) == 1)
        k->hostStopSaid++;
    if (!strncmp(line, "netstep: stop at frame ", 23)) k->stopLines++;
    if (!strncmp(line, "netstep: every client stopped, ", 31)) k->drainDone++;
    if (strstr(line, " never said it stopped; given up after ")) k->gaveUp++;
    if (!strcmp(line, "netstep: the stop said")) k->toldStop++;
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
    .peek        = fPeek,
    .setPatience = fSetPatience,
};

// ------------------------------------------------------------ the lobby

// Its lobby up: back this long after its stop (0: once it has ended).
static int lobbyUp(int c)
{
    const Console* k = &C[c];

    if (!k->stopped) return 0;
    if (S->backAfter[c])
        return g_now - k->stoppedAt + 1u >= (uint32_t)S->backAfter[c];
    return !k->ns.ending;
}

// The lobby's message, reliable: never lost, but to a console gone.
static void sayBack(int c)
{
    static const uint8_t none = 0;
    int                  t;

    C[c].backSent = 1;
    for (t = 0; t < S->consoles; t++) {
        if (t == c || (c != 0 && t != 0) || C[t].gone || g_lost[c][t])
            continue;
        if ((S->notRacing >> t) & 1) continue;
        put(c, t, MSG_BACK, &none, 1);
        C[t].backTo++;
    }
}

// Everything on the link, as the lobby reads it once up: what it says is
// back, and the race's last.
static void lobbyRead(int c)
{
    WlMsg m;
    int   i, peers = c == 0 ? S->consoles - 1 : 1;

    g_lobby = 1;
    for (i = 0; i < peers; i++)
        while (fRecv(i, &m))
            if (m.type == MSG_BACK) C[c].backGot++;
    g_lobby = 0;
}

static void lobbyTick(int c)
{
    if (!lobbyUp(c)) return;
    if (S->backAfter[c] && !C[c].backSent) sayBack(c);
    lobbyRead(c);
}

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
                if (!C[p].gone && !C[p].stopped && !alone && !g_lost[0][p]
                    && !g_lost[p][0])
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

// main.c's end: lockstep stopped, netrace's patience, and a first drain.
static void stop(int c)
{
    Console* k = &C[c];

    netstep_stop(g_now);
    k->stopped   = 1;
    k->stoppedAt = g_now;
    k->stallTo   = g_now + 1u + (uint32_t)S->stallAfterStop[c];
    k->patience  = PATIENCE;
    if (!g_firstStop) g_firstStop = g_now;
    if (netstep_on()) fault("on after netstep_stop");
    if (netstep_current() != NULL) fault("a frame after netstep_stop");
    if (netstep_poll(g_now)) fault("polled in after netstep_stop");
    // Its link lost at once: turned off at its save, say. Nothing more of
    // its goes out, and nothing more comes in.
    if ((S->vanishAtStop >> c) & 1) k->gone = k->vanished = 1;
    // A lobby back at once says so before the first drain.
    if (S->backAfter[c] == 1) sayBack(c);
    netstep_drain(g_now);
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
    if (S->stopAt[c] && k->ran == (uint32_t)S->stopAt[c]) stop(c);
}

// Its first frame's drawing, which stops its loop for seconds.
static int drawingFirst(int c)
{
    const Console* k = &C[c];

    return k->ran == 1 && S->firstStall[c] && !k->waiting
        && (int32_t)(g_now - k->startAt) < 0;
}

// The ms left of a hold whose places `lost` were lost at `at` (by place,
// as the log said): the least of each one's.
static uint32_t leftOf(uint8_t lost, const uint32_t* at)
{
    uint32_t left = 0, most = holdOf();
    int      p, any = 0;

    for (p = 0; p < MAXC; p++) {
        uint32_t since, l;

        if (!((lost >> p) & 1)) continue;
        since = g_now - at[p];
        l = since < most ? most - since : 0;
        if (!any || l < left) left = l;
        any = 1;
    }
    return left;
}

// What netstep_held says against what the log said: the host's places
// lost and not yet gone or back, and the least time left of them, to the
// ms; a client's host lost, and its own time left; or the places the
// host's last message held for, its seconds rounded up, so never less
// than the host's own time left now.
static void checkHeld(int c)
{
    Console* k = &C[c];
    uint32_t left, most = holdOf();
    uint8_t  m = netstep_held(g_now, &left);

    if (c != 0) most = (most + 999u) / 1000u * 1000u;
    k->heldSeen |= m;
    if (!m && left) fault("held for none, %lu ms left", (unsigned long)left);
    if (left > most) fault("held, %lu ms left", (unsigned long)left);
    if (m & (1u << c)) fault("held for itself");
    // Alone, the host's last word is no more: its places are the CPU's.
    if (k->aloneFrom >= 0 && m) fault("held for %02x, alone", m);
    if (c == 0 && m != k->lostNow)
        fault("held for %02x, lost %02x", m, k->lostNow);
    if (c == 0 && m && left != leftOf(m, k->lostAt))
        fault("held, %lu ms left, not %lu", (unsigned long)left,
              (unsigned long)leftOf(m, k->lostAt));
    if (c != 0 && (k->lostNow & 1u) && m != 1u)
        fault("held for %02x, the host lost", m);
    if (c != 0 && (k->lostNow & 1u) && left != leftOf(1u, k->lostAt))
        fault("held for the host, %lu ms left, not %lu",
              (unsigned long)left, (unsigned long)leftOf(1u, k->lostAt));
    if (c != 0 && !(k->lostNow & 1u) && (m & (uint8_t)~C[0].heldSeen))
        fault("held for %02x, which the host never held for", m);
    if (c != 0 && !(k->lostNow & 1u) && m && C[0].lostNow
        && left < leftOf(C[0].lostNow, C[0].lostAt))
        fault("held, %lu ms left, the host %lu", (unsigned long)left,
              (unsigned long)leftOf(C[0].lostNow, C[0].lostAt));
}

static void tick(int c)
{
    Console* k = &C[c];

    if (k->gone || held(c)) return;
    if (!k->stopped) checkHeld(c);
    // Drained each millisecond, ended or not: once it has, a drain does
    // nothing (main.c drains once at the stop, whatever is left to say).
    if (k->stopped) {
        netstep_drain(g_now);
        lobbyTick(c);
        return;
    }
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

// A client's cut link re-peered while both ends hold for it: its rejoin
// tried from well within the hold (37g-2).
static int repeers(int p)
{
    return S->dropAt[p] && S->repeerAt[p]
        && !(((S->repeerHalf | S->repeerMute) >> p) & 1)
        && S->repeerAt[p] < S->dropAt[p] + (int)holdOf();
}

// A console lost for good: gone, its loop stopped past the link's
// timeout, or its link cut and never re-peered.
static int goesAt(int p)
{
    return S->goneAt[p]
        || (S->freezeAt[p] && (uint32_t)S->freezeFor[p] > LINK_MS)
        || (S->dropAt[p] && !repeers(p));
}

static int expectGone(int c, int p)
{
    // The host says each racing client gone; a client says none.
    return c == 0 && p != 0 && p < S->consoles && (goesAt(p) || goesAt(0))
        && !(S->notRacing >> p & 1) && !(S->vanishAtStart >> p & 1);
}

// The host held for place p and said so: on to the end, or gone well
// after p's link was lost to it (LINK_MS after p went).
static int hostSaw(int p)
{
    if (!goesAt(0) && !(S->vanishAtStart & 1)) return 1;
    return S->goneAt[0] && S->goneAt[p]
        && S->goneAt[p] + (int)LINK_MS + 500 < S->goneAt[0];
}

// Client c with its host at some time while the host holds for place p:
// not when both links were cut and p was back first, c's still lost.
static int heardHold(int c, int p)
{
    if (!S->dropAt[c] || !S->dropAt[p]) return 1;
    return !repeers(p) || S->repeerAt[c] < S->repeerAt[p];
}

// The lines of the hold, and each console's netstep_held.
static void checkHold(int c, const Console* k)
{
    int p;

    for (p = 0; p < S->consoles; p++) {
        int racing = !((S->notRacing >> p) & 1) && p != c;
        int start  = racing && ((S->vanishAtStart >> p) & 1);
        // The host holds for each client lost, a client for its host:
        // the other gone, or lost to it while its own loop stopped, or
        // the link between them cut.
        int lost   = racing && !start && (c == 0 || p == 0)
                  && (goesAt(p) || goesAt(c) || (c == 0 && S->dropAt[p])
                      || (p == 0 && S->dropAt[c]));
        // Back, the link re-peered in the hold.
        int back   = lost && ((c == 0 && repeers(p))
                              || (p == 0 && repeers(c)));
        // As often as the link was cut.
        int cuts   = 1 + !!((c == 0 && S->dropAgain[p])
                            || (p == 0 && S->dropAgain[c]));
        // A client still with its host is held for each place the host
        // holds for.
        int seen   = lost || (c != 0 && p != 0 && racing && !start
                              && (goesAt(p) || S->dropAt[p]) && hostSaw(p)
                              && !goesAt(c) && heardHold(c, p));

        if (k->lostSaid[p] != lost * cuts)
            fault("place %d said lost %d times", p, k->lostSaid[p]);
        if (k->backSaid[p] != back * cuts)
            fault("place %d said back %d times", p, k->backSaid[p]);
        if (k->startGoneSaid[p] != (start && c == 0))
            fault("place %d said gone at the start %d times", p,
                  k->startGoneSaid[p]);
        if (!!(k->heldSeen & (1u << p)) != seen)
            fault("held for place %d: %d", p, !!(k->heldSeen & (1u << p)));
    }
    if (k->lostNow) fault("still held for %02x", k->lostNow);
}

// The host's end: each racing client's stop heard, and its drain ended
// once.
static void hostEnd(const Console* k)
{
    int p;

    for (p = 1; p < S->consoles; p++) {
        int first, after;

        if (((S->notRacing >> p) & 1) || goesAt(p)
            || ((S->vanishAtStart >> p) & 1)) {
            if (k->stoppedSaid[p] || k->leftSaid[p] || k->goneOnSaid[p])
                fault("said place %d stopped, which was not racing", p);
            continue;
        }
        // Its link lost at its stop, before a word of it went out.
        if ((S->vanishAtStop >> p) & 1) {
            if (k->stoppedSaid[p] || k->goneOnSaid[p])
                fault("heard place %d stop, which said nothing", p);
            continue;
        }
        first = S->stopAt[p] && (!S->stopAt[0] || S->stopAt[p] < S->stopAt[0]);
        after = S->stopAt[0] && !first;
        if (first && !(k->stoppedSaid[p] && k->leftSaid[p]))
            fault("place %d stopped first: said stopped %d, left %d", p,
                  k->stoppedSaid[p], k->leftSaid[p]);
        if (after && !S->giveUp && !k->stoppedSaid[p] && !k->goneOnSaid[p])
            fault("never heard place %d stop", p);
        if (!S->stopAt[0] && !S->stopAt[p]
            && (k->stoppedSaid[p] || k->leftSaid[p] || k->goneOnSaid[p]))
            fault("said place %d stopped", p);
        if (k->goneOnSaid[p] && !S->backAfter[p])
            fault("said place %d went on, with no lobby of its own", p);
    }
    if (S->stopAt[0] && k->drainDone + k->gaveUp != 1)
        fault("its drain ended %d times", k->drainDone + k->gaveUp);
    if (!S->stopAt[0] && (k->drainDone || k->gaveUp))
        fault("a drain with no stop");
    if (k->gaveUp != (S->giveUp != 0)) fault("gave up %d times", k->gaveUp);
}

// A client's: past the host's stop, or its lobby seen, alone; its own
// stop said.
static void clientEnd(int c, const Console* k)
{
    int hostOn = !goesAt(0) && !goesAt(c) && !(S->vanishAtStart & 1);
    int past   = hostOn && S->stopAt[0]
              && (!S->stopAt[c] || S->stopAt[c] > S->stopAt[0]);
    int on     = (S->goneOn >> c) & 1;
    // The host's link lost at its stop, while this one says its own: cut
    // short.
    int cut    = S->vanishAtStop & 1;
    int tells  = hostOn && !cut && (S->stopAt[c] || past);

    if (k->goneOnHost != on)
        fault("said the host went on %d times", k->goneOnHost);
    if (k->pastLines != (past && !on))
        fault("said past the host's stop %d times", k->pastLines);
    if (past && !on && k->hostStopSaid != 1)
        fault("said the host stopped %d times", k->hostStopSaid);
    if (k->hostStopSaid > 1)
        fault("said the host stopped %d times", k->hostStopSaid);
    if (k->toldStop != tells) fault("said its stop %d times", k->toldStop);
}

static void finish(void)
{
    int c, p, diverge = 0;

    for (p = 0; p < S->consoles; p++)
        if (S->divergeAt[p]) diverge = 1;
    for (c = 0; c < S->consoles; c++) {
        Console* k = &C[c];
        int      wantAlone = c != 0 && !S->goneAt[c]
                          && (goesAt(0) || goesAt(c)
                              || (S->vanishAtStart & 1));

        g_cur = c;
        if (k->gone) continue;
        if (S->stopAt[c] && !k->stopped) fault("never stopped");
        if (k->stopped && k->ran != (uint32_t)S->stopAt[c])
            fault("stopped after %lu frames", (unsigned long)k->ran);
        if (!k->stopped && k->ran < (uint32_t)S->frames)
            fault("ran %lu of %d frames", (unsigned long)k->ran, S->frames);
        if (k->stopLines != k->stopped)
            fault("said its stop %d times", k->stopLines);
        if (k->stopped && k->ns.ending) fault("still ending");
        if (k->flowLines != 1)
            fault("said frames flow %d times", k->flowLines);
        if (k->patienceSets != 1 || (!k->stopped && k->patience != 0))
            fault("patience %lu after %d sets", (unsigned long)k->patience,
                  k->patienceSets);
        if (k->stopped && k->backGot != k->backTo)
            fault("its lobby read %d of the %d it was sent", k->backGot,
                  k->backTo);
        for (p = 0; p < MAXC; p++)
            if (k->goneSaid[p] != expectGone(c, p))
                fault("place %d gone said %d", p, k->goneSaid[p]);
        if (k->aloneLines != wantAlone)
            fault("said alone %d times", k->aloneLines);
        checkHold(c, k);
        if (c == 0) hostEnd(k);
        else clientEnd(c, k);
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

// main.c's rejoin (37g-2): a client holding for its host finds it again,
// and the host lets it back into its place while it holds for it; late,
// only in the hold's last 2 ms. The link is new: nothing of the old one's
// is on it. Half up, only the client's end comes up; mute, only the
// host's.
static void repeer(int c)
{
    uint32_t left;
    uint8_t  host, client;

    if (!g_lost[0][c] || C[0].gone || C[c].gone || held(0) || held(c)
        || C[0].stopped || C[c].stopped)
        return;
    enter(0);
    host = netstep_held(g_now, NULL);
    enter(c);
    client = netstep_held(g_now, &left);
    if (!((host >> c) & 1) || !(client & 1)) return;
    if (((S->repeerLate >> c) & 1) && left > 2) return;
    if ((S->repeerMute >> c) & 1) {
        g_lost[0][c] = 0;
        C[c].hostUp  = 1;
    } else {
        g_lost[c][0] = 0;
        if (!((S->repeerHalf >> c) & 1)) g_lost[0][c] = 0;
        else C[c].halfUp = 1;
    }
    g_cutAt[c] = 0;
    memset(&g_pipe[0][c], 0, sizeof g_pipe[0][c]);
    memset(&g_pipe[c][0], 0, sizeof g_pipe[c][0]);
    C[c].repeered = 1;
}

// Still to come: a frame to run, a drain, a lobby to come back.
static int busy(int c)
{
    const Console* k = &C[c];

    if (k->gone) return 0;
    if (!k->stopped) return k->ran < (uint32_t)S->frames;
    return k->ns.ending || held(c) || (S->backAfter[c] && !k->backSent);
}

static void runScenario(const Scenario* s)
{
    int      peers[MAXC];
    int      c, p, stops = 0;
    uint32_t tail = 0;

    S = s;
    memset(C, 0, sizeof C);
    memset(g_pipe, 0, sizeof g_pipe);
    memset(g_lost, 0, sizeof g_lost);
    memset(g_cutAt, 0, sizeof g_cutAt);
    memset(g_truth, 0, sizeof g_truth);
    g_lcg       = 12345u;
    g_now       = 1000;
    g_firstStop = 0;
    printf("scenario %s\n", s->name);
    for (c = 0; c < s->consoles; c++) {
        enter(c);
        netstep_init(&kNet, fLog);
        // Before GO, as main.c: netstep_start keeps them.
        netstep_on_differ(fDiffer);
        netstep_set_hold((uint32_t)s->hold);
        C[c].saidPlace = -1;
        if (s->stopAt[c]) stops = 1;
        if ((s->notRacing >> c) & 1) {
            C[c].gone = 1;
            continue;
        }
        if ((s->vanishAtStart >> c) & 1) {
            C[c].gone = C[c].vanished = 1;
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
        int more = 0;

        for (c = 0; c < s->consoles; c++) {
            if (s->goneAt[c] && g_now == (uint32_t)s->goneAt[c])
                C[c].gone = 1;
            if (c > 0 && s->dropAt[c] && g_now == (uint32_t)s->dropAt[c])
                g_cutAt[c] = g_now;
            if (c > 0 && s->dropAgain[c]
                && g_now == (uint32_t)s->dropAgain[c]) {
                if (!C[c].repeered) fault("cut again, never back");
                g_cutAt[c]    = g_now;
                C[c].repeered = 0;
            }
            if (s->freezeAt[c])
                C[c].frozen = g_now >= (uint32_t)s->freezeAt[c]
                           && g_now < (uint32_t)(s->freezeAt[c]
                                                 + s->freezeFor[c]);
            C[c].sent = 0;
            if (!C[c].gone && !drawingFirst(c) && !held(c))
                C[c].pumped = g_now;
            if (c > 0 && s->junk && g_now % (uint32_t)s->junk == 0) {
                junk(0, c);
                junk(c, 0);
            }
        }
        for (c = 1; c < s->consoles; c++) {
            uint32_t from = (uint32_t)s->repeerAt[c];

            if (!from || C[c].repeered || g_now < from) continue;
            if (((s->repeerLate >> c) & 1) || (g_now - from) % 1000u == 0)
                repeer(c);
        }
        for (c = 0; c < s->consoles; c++) {
            enter(c);
            tick(c);
            more |= busy(c);
        }
        // With a stop, on a little for what is still in flight.
        if (more) {
            tail = 0;
            continue;
        }
        if (!stops) break;
        if (!tail) tail = g_now + TAIL_MS;
        if (g_now >= tail) break;
    }
    finish();
    for (c = 0; c < s->consoles; c++)
        printf("  console %d: %lu frames in %lu ms, %d lines, waited %lu ms "
               "most%s%s\n", c, (unsigned long)C[c].ran,
               (unsigned long)(C[c].doneAt ? C[c].doneAt - 1000u : 0),
               C[c].lineCount, (unsigned long)C[c].maxWaited,
               C[c].gone ? ", gone" : "",
               C[c].stopped ? ", stopped" : "");
    for (c = 0; c < s->consoles; c++)
        for (p = 0; p < C[c].numLines && p < 6; p++)
            printf("  %d: %s\n", c, C[c].lines[p]);
    // The end's lines, wherever they fell.
    for (c = 0; c < s->consoles; c++)
        for (p = 6; p < C[c].numLines; p++)
            if (strstr(C[c].lines[p], "stop") || strstr(C[c].lines[p], "left")
                || strstr(C[c].lines[p], "gone on")
                || strstr(C[c].lines[p], "given up"))
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
