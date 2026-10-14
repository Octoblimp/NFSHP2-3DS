// Host harness for a local wireless race's setup (netrace.c, TASKS 37c).
//
// Builds "3DS Files/source/netrace.c" with the flow and its popups
// (gameflow.c, bpopup.c) and runs up to eight consoles of it in one
// process, each with its own flow, its own NetRace (netrace_bind) and its
// own copy of the game's globals netrace.c reaches -- TheRaceParameters,
// DriverInfoTable, TheRaceEvent, Fred, bDefaultSeed and the two selected
// rides -- swapped in for its turn each frame. Console 0 hosts; console p
// is place p. Between them is a fake of the link: reliable and in order,
// each message a few frames on the way, the host's peers numbered the
// other way round from the places.
//
// The game is a fake too: StartRace builds a driver table of the two
// players, then the AI racers, each asking gFredNetRideFn first and else
// drawing a ride from bDefaultSeed; Fred's settings go into the race's
// parameters, and a knockout points the event's state at its aOldState.
// A load takes the scenario's frames, the loop stalled for most of them,
// and draws a different count of randoms on each console; at its end it
// asks netrace_hold, as trackflow's Part6 does.
//
// Each scenario starts every console on "Select Car" with "Local
// Wireless" under it, as the lobby leaves them, calls netrace_begin, and
// then plays its events: a car chosen, the host's start on Select Track,
// A or B, a console gone (powered off), a link taken down. Checked each
// frame, with a FAULT for each found:
//
//   - one popup at most, and only on "Wireless Race", its parent that
//     screen, the memory card's look, the lobby's title, every port's, no
//     buttons, BACK the way out, and back at once after A;
//   - the host's line: "Waiting for a car from:" and each client still on
//     whose car it has not got (or got back), in place order; a client's:
//     the host's name in "Waiting for $NAME to start the race."; and the
//     host on that screen only while it waits;
//   - B on it the cancel sound, A none;
//   - the link's patience NETRACE_PATIENCE_MS from the start on, racing
//     too (the race's to give back), and its own back with the lobby;
//   - no message past WL_MSG_MAX, none to a peer that is not there;
//   - GO only once every console racing and still on has loaded and held,
//     once to each, and a console racing only after its load;
//
// and at the end:
//
//   - each console's screen, racing or not, its stage, and its log lines
//     in order; no place driving where nothing was built or taken; a
//     load after (a restart) not held; nothing said with no wireless race;
//   - the race's first messages, the host's and each client's, left
//     unread for the race (37d's);
//   - a client that lost the host racing on its own seed as it held;
//   - each racing client's race as the host's at GO: the parameters (but
//     for its own display settings, with the host's two cameras), the
//     driver table (each character its own console's), the event (its own
//     tree, and its own state unless the event's is in it), Fred's game
//     type and players, the driver of each place, and the seed;
//   - the host's table: its car, the first client's as the second
//     player's with that client's settings, the rest of the clients' in
//     AI racers' places, not damageable and instance 0; the drivers as
//     the scenario says; at least as many AI racers as players in their
//     places;
//   - the host's second player's ride and settings as they were.
//
//     scenario <name>
//     [<console>] <the flow's trace, netrace's log, the fake's calls>
//     faults <n>                   (after every scenario)
//     total faults <n>
//
// Usage: netrace_test [scenario]...      (no argument runs them all)

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "bpopup.h"
#include "fred.h"
#include "fredrace.h"
#include "gameflow.h"
#include "langtab.h"
#include "lobby.h"
#include "netrace.h"
#include "portlang.h"
#include "race.h"
#include "raceevent.h"
#include "raceparams.h"

#define SIXTIETH   (1.0f / 60.0f)
#define MAXC       WIRELESS_MAX_CONSOLES
#define MAX_EVENTS 24
#define MAX_EXPECT 24
#define LOG_MAX    160
#define PIPE_MAX   64
#define NUM_CHARS  16
#define STALL      20    // a loading console's loop runs one frame in this

// ------------------------------------------- the game's, netrace.c's view

RaceParameters   TheRaceParameters;
DriverInfo       DriverInfoTable[RACE_PARAMETERS_MAX_DRIVERS];
RaceEvent        TheRaceEvent;
FrontendDatabase Fred;
int32_t (*gFredNetRideFn)(int32_t ai, RideInfo* ride);

static RideInfo g_rides[2];   // Fred's players' selected rides

// ------------------------------------------------------------ scenarios

typedef struct {
    int         frame;
    int         console;
    const char* what;   // "car", "start", "A", "B", "gone", "off"
} Event;

typedef struct {
    const char* name;
    int         frames;
    int         consoles;
    int         language;
    int32_t     gameType;          // the host's Fred.GameType
    int32_t     numAI;             // the host's NumAICars, before
    int         delay;             // a message's most frames on the way
    int         load[MAXC];        // each console's load, in frames
    const char* names[MAXC];       // UTF-8
    Event       ev[MAX_EVENTS];
    int         corrupt;           // the setup's version broken on the way
    const char* endScreen[MAXC];   // NULL: a console gone, not checked
    int         racing[MAXC];
    const char* drivers;           // each place's, "0 1 100"; NULL none
    const char* expect[MAX_EXPECT];   // "<console>|<line's start>"
} Scenario;

// One console: no lobby's Start, a race of its own.
#define OFFLINE (S->consoles < 2)

#define TWO   { "hp2host", "hp2join1" }
#define THREE { "hp2host", "hp2join1", "hp2join2" }
#define EIGHT { "hp2host", "hp2join1", "hp2join2", "hp2join3", "hp2join4", \
                "hp2join5", "hp2join6", "hp2join7" }

static const Scenario kScenarios[] = {
    // Two: the client's car in before the host's start, which builds at
    // once; the client takes it, both load, the host waits for the
    // client's, and GO.
    { "two", 700, 2, LANG_EN, 1, 3, 3, {120, 260}, TWO,
      {{30, 1, "car"}, {40, 0, "car"}, {80, 0, "start"}}, 0,
      {"Racing", "Racing"}, {1, 1}, "0 1",
      {"0|netrace: begin, place 0 of 2", "1|netrace: begin, place 1 of 2",
       "1|netrace: car sent, type 8 skin 1",
       "0|netrace: place 1's car, type 8 skin 1",
       "0|netrace: the host's start",
       "0|netrace: built, track 7, 5 drivers, 0 players in AI places",
       "1|netrace: setup taken, track 7, 5 drivers, driver 1",
       "0|netrace: loaded, holding for the rest",
       "1|netrace: loaded, holding for the host",
       "0|netrace: place 1 loaded", "0|netrace: go, seed",
       "1|netrace: go, seed"} },

    // The host's start first: it waits for both, the line shrinking as
    // the cars come; A on it only puts it back.
    { "host_waits", 900, 3, LANG_EN, 1, 1, 4, {100, 150, 90}, THREE,
      {{20, 0, "car"}, {40, 0, "start"}, {60, 0, "A"}, {100, 1, "car"},
       {300, 2, "car"}}, 0,
      {"Racing", "Racing", "Racing"}, {1, 1, 1}, "0 1 100",
      {"0|netrace: wait Waiting for a car from:@hp2join1@hp2join2",
       "0|netrace: place 1's car",
       "0|netrace: wait Waiting for a car from:@hp2join2",
       "0|netrace: place 2's car",
       "0|netrace: built, track 7, 3 drivers, 1 players in AI places",
       "2|netrace: setup taken, track 7, 3 drivers, driver 100",
       "0|netrace: go, seed"} },

    // A client's car taken back with B, and sent again after the host's
    // start.
    { "client_back", 900, 2, LANG_EN, 1, 2, 3, {80, 80}, TWO,
      {{30, 1, "car"}, {100, 1, "B"}, {110, 0, "car"}, {150, 0, "start"},
       {250, 1, "car"}}, 0,
      {"Racing", "Racing"}, {1, 1}, "0 1",
      {"1|netrace: car sent", "1|netrace: wait Waiting for hp2host to "
       "start the race.", "1|netrace: back to car select",
       "0|netrace: place 1 took its car back",
       "0|netrace: wait Waiting for a car from:@hp2join1",
       "1|netrace: car sent", "1|netrace: wait Waiting for hp2host to "
       "start the race.", "0|netrace: built", "1|netrace: go, seed"} },

    // The host's B on its wait: back to Select Track, where a car coming
    // in builds nothing until the next start.
    { "host_back", 900, 2, LANG_EN, 1, 2, 3, {80, 80}, TWO,
      {{20, 0, "car"}, {40, 0, "start"}, {80, 0, "B"}, {120, 1, "car"},
       {200, 0, "start"}}, 0,
      {"Racing", "Racing"}, {1, 1}, "0 1",
      {"0|netrace: wait Waiting for a car from:@hp2join1",
       "0|netrace: back to track select", "0|netrace: place 1's car",
       "0|netrace: the host's start", "0|netrace: built"} },

    // Eight: six clients in AI racers' places, the AI count raised at the
    // start to the six; cars and loads all over the place.
    { "eight", 1500, 8, LANG_EN, 1, 2, 6,
      {200, 90, 400, 60, 300, 250, 120, 350}, EIGHT,
      {{50, 3, "car"}, {60, 0, "car"}, {70, 6, "car"}, {90, 0, "ai0"},
       {100, 0, "start"},
       {120, 1, "car"}, {130, 7, "car"}, {200, 2, "car"}, {210, 5, "car"},
       {400, 4, "car"}}, 0,
      {"Racing", "Racing", "Racing", "Racing", "Racing", "Racing",
       "Racing", "Racing"}, {1, 1, 1, 1, 1, 1, 1, 1},
      "0 1 100 101 102 103 104 105",
      {"0|netrace: 6 AI racers",
       "0|netrace: wait Waiting for a car from:@hp2join1@hp2join2@hp2join4"
       "@hp2join5@hp2join7",
       "0|netrace: built, track 7, 8 drivers, 6 players in AI places",
       "5|netrace: setup taken, track 7, 8 drivers, driver 103",
       "0|netrace: go, seed", "4|netrace: go, seed"} },

    // A client gone before its car: the race goes on without it, the next
    // the second player.
    { "client_gone_before", 800, 3, LANG_EN, 1, 3, 3, {80, 80, 80}, THREE,
      {{50, 1, "gone"}, {60, 2, "car"}, {70, 0, "car"}, {100, 0, "start"}},
      0, {"Racing", NULL, "Racing"}, {1, 0, 1}, "0 -1 1",
      {"0|netrace: place 1 (hp2join1) is gone",
       "0|netrace: built, track 7, 5 drivers, 0 players in AI places",
       "2|netrace: setup taken, track 7, 5 drivers, driver 1"} },

    // One gone after its car, before the start: not in the race.
    { "gone_with_car", 800, 3, LANG_EN, 1, 3, 3, {80, 80, 80}, THREE,
      {{30, 1, "car"}, {40, 2, "car"}, {100, 1, "gone"}, {110, 0, "car"},
       {150, 0, "start"}}, 0,
      {"Racing", NULL, "Racing"}, {1, 0, 1}, "0 -1 1",
      {"0|netrace: place 1's car", "0|netrace: place 2's car",
       "0|netrace: place 1 (hp2join1) is gone",
       "0|netrace: built, track 7, 5 drivers, 0 players in AI places"} },

    // One of two the host waits for gone: the line loses it, and the
    // other's car builds the race.
    { "gone_of_two_waited", 900, 4, LANG_EN, 1, 2, 3, {80, 80, 80, 80},
      { "hp2host", "hp2join1", "hp2join2", "hp2join3" },
      {{30, 1, "car"}, {35, 0, "car"}, {40, 0, "start"}, {100, 2, "gone"},
       {300, 3, "car"}}, 0,
      {"Racing", "Racing", NULL, "Racing"}, {1, 1, 0, 1}, "0 1 -1 100",
      {"0|netrace: wait Waiting for a car from:@hp2join2@hp2join3",
       "0|netrace: place 2 (hp2join2) is gone",
       "0|netrace: wait Waiting for a car from:@hp2join3",
       "0|netrace: built, track 7, 4 drivers, 1 players in AI places"} },

    // The last client gone on the frame of the host's start.
    { "all_gone_at_start", 300, 2, LANG_EN, 1, 3, 3, {80, 80}, TWO,
      {{20, 0, "car"}, {60, 1, "gone"}, {60, 0, "start"}}, 0,
      {"Local Wireless", NULL}, {0, 0}, NULL,
      {"0|netrace: the host's start",
       "0|netrace: place 1 (hp2join1) is gone",
       "0|netrace: every other console is gone",
       "0|lobby: notice The link to hp2join1 was lost."} },

    // One gone while the host waits for its car: built with the rest.
    { "client_gone_waiting", 800, 3, LANG_EN, 1, 1, 3, {80, 80, 80}, THREE,
      {{30, 1, "car"}, {50, 0, "car"}, {60, 0, "start"}, {150, 2, "gone"}},
      0, {"Racing", "Racing", NULL}, {1, 1, 0}, "0 1 -1",
      {"0|netrace: wait Waiting for a car from:@hp2join2",
       "0|netrace: place 2 (hp2join2) is gone",
       "0|netrace: built, track 7, 3 drivers, 0 players"} },

    // The only client gone while the host waits: back to the lobby, which
    // says so.
    { "all_gone", 400, 2, LANG_EN, 1, 3, 3, {80, 80}, TWO,
      {{20, 0, "car"}, {40, 0, "start"}, {100, 1, "gone"}}, 0,
      {"Local Wireless", NULL}, {0, 0}, NULL,
      {"0|netrace: place 1 (hp2join1) is gone",
       "0|netrace: every other console is gone",
       "0|netrace: back to the lobby",
       "0|lobby: notice The link to hp2join1 was lost."} },

    // And gone while the host is still on car select.
    { "all_gone_car_select", 300, 2, LANG_EN, 1, 3, 3, {80, 80}, TWO,
      {{50, 1, "gone"}}, 0,
      {"Local Wireless", NULL}, {0, 0}, NULL,
      {"0|netrace: every other console is gone",
       "0|netrace: back to the lobby",
       "0|lobby: notice The link to hp2join1 was lost."} },

    // The host gone while a client waits on "Wireless Race", or picks its
    // car: back to the lobby.
    { "host_gone_waiting", 400, 2, LANG_EN, 1, 3, 3, {80, 80}, TWO,
      {{30, 1, "car"}, {100, 0, "gone"}}, 0,
      {NULL, "Local Wireless"}, {0, 0}, NULL,
      {"1|netrace: wait Waiting for hp2host to start the race.",
       "1|netrace: place 0 (hp2host) is gone",
       "1|netrace: back to the lobby",
       "1|lobby: notice The link to hp2host was lost."} },
    { "host_gone_car_select", 400, 3, LANG_EN, 1, 3, 3, {80, 80, 80}, THREE,
      {{50, 0, "gone"}}, 0,
      {NULL, "Local Wireless", "Local Wireless"}, {0, 0, 0}, NULL,
      {"1|netrace: back to the lobby",
       "1|lobby: notice The link to hp2host was lost.",
       "2|netrace: back to the lobby",
       "2|lobby: notice The link to hp2host was lost."} },

    // The host gone while a client loads: it races alone at its hold.
    { "host_gone_loading", 900, 2, LANG_EN, 1, 3, 3, {100, 300}, TWO,
      {{30, 1, "car"}, {40, 0, "car"}, {80, 0, "start"}, {250, 0, "gone"}},
      0, {NULL, "Racing"}, {0, 1}, NULL,
      {"1|netrace: setup taken", "1|netrace: loaded, holding for the host",
       "1|netrace: the host is gone; racing alone",
       "1|netrace: go, seed"} },

    // A client gone while it loads: GO when the other has loaded.
    { "client_gone_loading", 900, 3, LANG_EN, 1, 0, 3, {100, 200, 400},
      THREE,
      {{30, 1, "car"}, {35, 2, "car"}, {40, 0, "car"}, {80, 0, "start"},
       {200, 2, "gone"}}, 0,
      {"Racing", "Racing", NULL}, {1, 1, 0}, "0 1 100",
      {"0|netrace: built, track 7, 3 drivers, 1 players in AI places",
       "0|netrace: place 2 (hp2join2) is gone", "0|netrace: place 1 loaded",
       "0|netrace: go, seed", "1|netrace: go, seed"} },

    // Lap Knockout: the fake event's state is its own aOldState.
    { "knockout", 700, 3, LANG_EN, 4, 0, 3, {120, 260, 200}, THREE,
      {{30, 1, "car"}, {32, 2, "car"}, {40, 0, "car"}, {80, 0, "start"}},
      0, {"Racing", "Racing", "Racing"}, {1, 1, 1}, "0 1 100",
      {"0|netrace: 1 AI racers",
       "0|netrace: built, track 7, 3 drivers, 1 players in AI places",
       "1|netrace: setup taken, track 7, 3 drivers, driver 1",
       "2|netrace: setup taken, track 7, 3 drivers, driver 100"} },

    // A setup that is not this build's: the client back to the lobby; the
    // host, its client gone, races alone.
    { "bad_setup", 700, 2, LANG_EN, 1, 3, 3, {120, 260}, TWO,
      {{30, 1, "car"}, {40, 0, "car"}, {80, 0, "start"}}, 1,
      {"Racing", "Local Wireless"}, {1, 0}, "0 1",
      {"1|netrace: the setup is not this build's",
       "1|netrace: back to the lobby",
       "1|lobby: notice The link to hp2host was lost.",
       "0|netrace: place 1 (hp2join1) is gone", "0|netrace: go, seed"} },

    // B on a client's car select: the lobby takes the link down, and the
    // host, alone, goes back to the lobby too.
    { "client_leaves", 300, 2, LANG_EN, 1, 3, 3, {80, 80}, TWO,
      {{20, 0, "car"}, {40, 1, "B"}}, 0,
      {"Local Wireless", "Local Wireless"}, {0, 0}, NULL,
      {"1|lobby: link down", "1|netrace: the link is down",
       "0|netrace: place 1 (hp2join1) is gone",
       "0|netrace: every other console is gone",
       "0|lobby: notice The link to hp2join1 was lost."} },

    // French, and names past ASCII.
    { "french", 800, 2, LANG_FR, 1, 3, 3, {80, 120},
      {"H\xc3\xb4te", "Zo\xc3\xab"},
      {{20, 0, "car"}, {40, 0, "start"}, {200, 1, "car"}}, 0,
      {"Racing", "Racing"}, {1, 1}, "0 1",
      {"0|netrace: wait En attente de la voiture de :@Zo\xeb",
       "1|netrace: wait En attente du lancement de la course par H\xf4te.",
       "1|netrace: setup taken", "1|netrace: go, seed"} },

    // No wireless race: car select and track select as ever, the load not
    // held, and netrace silent.
    { "offline", 300, 1, LANG_EN, 1, 3, 3, {80}, {"hp2host"},
      {{20, 0, "car"}, {40, 0, "start"}}, 0,
      {"Racing"}, {1}, NULL, {NULL} },
};
#define NUM_SCENARIOS ((int)(sizeof kScenarios / sizeof kScenarios[0]))

// -------------------------------------------------------------- consoles

typedef struct {
    WlMsg m;
    int   at;      // the frame it can be read
} Packet;

typedef struct {
    Packet q[PIPE_MAX];
    int    head, tail;
    int    lastAt;
} Pipe;

typedef struct {
    // Its turn's globals.
    RaceParameters   rp;
    DriverInfo       table[RACE_PARAMETERS_MAX_DRIVERS];
    RaceEvent        ev;
    FrontendDatabase fred;
    uint32_t         seed;
    RideInfo         rides[2];
    // Its own.
    NetRace          nr;
    BGameFlow        gf;
    LobbyRace        race;
    int              gone, off;
    uint32_t         patience;
    int              loadingAt, loadedAt, heldAt, racingAt;   // -1 not yet
    int32_t          notice;
    char             noticeName[WIRELESS_NAME_MAX];
    int              carIn[MAXC];      // the host's: the CARs read
    int              gos;              // GOs sent it
    int              goRecv;           // GOs it read
    int              starts;           // StartRaces
    int              sounds, sound0;
    int              pressed;          // this frame
    int              saidGone[MAXC];
    char             lastWait[600];    // since "Wireless Race" came up
    uint32_t         seedBuilt;        // the host's, StartRace's
    uint32_t         seedTaken;        // a client's, at its load
    uint32_t         seedHeld;         // at its hold
    // As it began.
    tGlobalDisplaySettings display;
    EventTree*       tree;
    uint8_t*         state;
    RideInfo         ride1;
    cPlayerSettings  set1;
    // At GO.
    RaceParameters   goRp;
    DriverInfo       goTable[RACE_PARAMETERS_MAX_DRIVERS];
    RaceEvent        goEv;
    uint32_t         goSeed;
    int8_t           goDriver[MAXC];
    int32_t          goGameType, goPlayers, goAborted;
    char             log[LOG_MAX][300];
    int              numLog;
} Console;

static Console         C[MAXC];
static Pipe            g_pipe[MAXC][MAXC];   // [from][to]
static EventTree       g_trees[MAXC];
static uint8_t         g_states[MAXC][16];
static CharacterInfo   g_chars[MAXC][NUM_CHARS];
static const Scenario* S;
static int             g_cur = -1;
static int             g_frame, g_faults;
static uint32_t        g_lcg;

static void fault(const char* fmt, ...)
{
    va_list ap;
    printf("  FAULT frame %d console %d: ", g_frame, g_cur);
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    printf("\n");
    g_faults++;
}

// The harness's own randoms, for the delays: not bDefaultSeed.
static uint32_t lcg(void)
{
    g_lcg = g_lcg * 1103515245u + 12345u;
    return g_lcg >> 16;
}

static int alive(int c)
{
    return c >= 0 && c < S->consoles && !C[c].gone && !C[c].off;
}

static void enter(int c)
{
    Console* k = &C[c];

    TheRaceParameters = k->rp;
    memcpy(DriverInfoTable, k->table, sizeof DriverInfoTable);
    TheRaceEvent = k->ev;
    Fred         = k->fred;
    bDefaultSeed = k->seed;
    memcpy(g_rides, k->rides, sizeof g_rides);
    netrace_bind(&k->nr);
    g_cur = c;
}

static void leave(void)
{
    Console* k = &C[g_cur];

    k->rp = TheRaceParameters;
    memcpy(k->table, DriverInfoTable, sizeof DriverInfoTable);
    k->ev   = TheRaceEvent;
    k->fred = Fred;
    k->seed = bDefaultSeed;
    memcpy(k->rides, g_rides, sizeof g_rides);
    netrace_bind(NULL);
    g_cur = -1;
}

static void wLog(const char* line)
{
    Console* k = &C[g_cur];
    int      p;

    printf("[%d] %s\n", g_cur, line);
    // A place said gone once, and only when it is, and a client says it
    // only of the host.
    if (sscanf(line, "netrace: place %d (", &p) == 1 && strstr(line, "is gone")) {
        if (p < 0 || p >= S->consoles || alive(p)) fault("place %d is not gone", p);
        else if (k->saidGone[p]++) fault("place %d said gone again", p);
        if (g_cur != 0 && p != 0) fault("a client on place %d", p);
    }
    // A wait line said once a change, from "Wireless Race" coming up.
    if (!strncmp(line, "netrace: wait ", 14)) {
        if (!strcmp(line + 14, k->lastWait)) fault("the same wait again");
        snprintf(k->lastWait, sizeof k->lastWait, "%s", line + 14);
    }
    if (k->numLog < LOG_MAX) {
        snprintf(k->log[k->numLog], sizeof k->log[0], "%s", line);
        k->numLog++;
    }
}

static const char* text(int32_t id)
{
    const char* s = portlang_get(S->language, id, NULL);
    return s ? s : "";
}

// --------------------------------------------------------- lobby.c's two

void lobby_latin1(char* out, size_t cap, const char* utf8)
{
    const unsigned char* s = (const unsigned char*)(utf8 ? utf8 : "");
    size_t               o = 0;

    while (*s && o + 1 < cap) {
        unsigned c = *s++;
        if (c >= 0xc0 && c < 0xe0 && (*s & 0xc0) == 0x80)
            c = ((c & 0x1f) << 6) | (*s++ & 0x3f);
        else if (c >= 0x80)
            c = '?';
        if (c == '@' || c > 0xff) c = '?';
        out[o++] = (char)c;
    }
    out[o] = 0;
}

void lobby_notice_next(int32_t id, const char* name)
{
    Console* k = &C[g_cur];

    printf("[%d] notice next %ld %s\n", g_cur, (long)id, name);
    if (k->notice) fault("a second notice");
    k->notice = id;
    snprintf(k->noticeName, sizeof k->noticeName, "%s", name ? name : "");
}

// `tmpl` with "$NAME" put in.
static void fillName(char* out, size_t cap, const char* tmpl,
                     const char* name)
{
    const char* at = strstr(tmpl, "$NAME");
    if (!at) snprintf(out, cap, "%s", tmpl);
    else snprintf(out, cap, "%.*s%s%s", (int)(at - tmpl), tmpl, name, at + 5);
}

// ---------------------------------------------------------------- the link

// The host's peer for place p: the places the other way round.
static int peerOf(int place)
{
    return S->consoles - 1 - place;
}

// The console the current one's peer `i` is, or -1.
static int target(int i)
{
    if (g_cur == 0) {
        int p = S->consoles - 1 - i;
        return i >= 0 && p >= 1 && p < S->consoles ? p : -1;
    }
    return i == 0 ? 0 : -1;
}

static WirelessState fState(void)
{
    if (C[g_cur].off) return WIRELESS_OFF;
    if (g_cur == 0) return WIRELESS_HOSTING;
    return alive(0) ? WIRELESS_CONNECTED : WIRELESS_LOST;
}

static int fPeerAlive(int i)
{
    int t = target(i);
    if (t < 0) fault("peerAlive(%d), no such peer", i);
    return !C[g_cur].off && alive(t);
}

static const char* fPeerName(int i)
{
    int t = target(i);
    if (t < 0) fault("peerName(%d), no such peer", i);
    return t >= 0 ? S->names[t] : "";
}

static void sentGo(int t)
{
    int p;

    if (g_cur != 0) fault("a GO from a client");
    if (C[0].heldAt < 0) fault("GO before the host's own load");
    for (p = 1; p < S->consoles; p++)
        if (C[0].nr.driver[p] >= 0 && alive(p) && C[p].heldAt < 0)
            fault("GO to %d before place %d loaded", t, p);
    if (++C[t].gos > 1) fault("GO %d to %d", C[t].gos, t);
}

static int fSend(int i, uint8_t type, const void* data, size_t n)
{
    int    t = target(i);
    Pipe*  p;
    Packet* k;

    printf("[%d] send %d %02x %u\n", g_cur, i, (unsigned)type, (unsigned)n);
    if (n > WL_MSG_MAX) {
        fault("a message of %u bytes", (unsigned)n);
        return 0;
    }
    if (t < 0) {
        fault("send to peer %d, no console", i);
        return 0;
    }
    if (C[g_cur].off) fault("send with the link down");
    if (type == NETRACE_MSG_GO) sentGo(t);
    if (type == NETRACE_MSG_SETUP && g_cur != 0) fault("a SETUP from a client");
    if ((type == NETRACE_MSG_CAR || type == NETRACE_MSG_UNCAR
         || type == NETRACE_MSG_LOADED) && g_cur == 0)
        fault("a client's message from the host");
    if (!alive(t)) return 1;   // lost on the way
    p = &g_pipe[g_cur][t];
    if (p->tail >= PIPE_MAX) {
        fault("pipe %d to %d full", g_cur, t);
        return 0;
    }
    k = &p->q[p->tail++];
    memset(k, 0, sizeof *k);
    k->m.type = type;
    k->m.len  = (uint8_t)n;
    memcpy(k->m.data, data, n);
    if (S->corrupt && type == NETRACE_MSG_SETUP && n > 6
        && k->m.data[0] == 0 && k->m.data[1] == 0)
        k->m.data[4 + 2] ^= 0x40;   // the header's version
    k->at = g_frame + 1 + (int)(lcg() % (uint32_t)S->delay);
    if (k->at < p->lastAt) k->at = p->lastAt;
    p->lastAt = k->at;
    return 1;
}

static int fRecv(int i, WlMsg* out)
{
    int   t = target(i);
    Pipe* p;

    if (t < 0) {
        fault("recv from peer %d, no console", i);
        return 0;
    }
    if (C[g_cur].off) return 0;
    p = &g_pipe[t][g_cur];
    if (p->head == p->tail || p->q[p->head].at > g_frame) return 0;
    *out = p->q[p->head++].m;
    printf("[%d] recv %d %02x %u\n", g_cur, i, (unsigned)out->type,
           (unsigned)out->len);
    if (g_cur == 0 && out->type == NETRACE_MSG_CAR) C[0].carIn[t] = 1;
    if (g_cur == 0 && out->type == NETRACE_MSG_UNCAR) C[0].carIn[t] = 0;
    if (out->type == NETRACE_MSG_GO) C[g_cur].goRecv++;
    return 1;
}

static void fSetPatience(uint32_t ms)
{
    printf("[%d] patience %lu\n", g_cur, (unsigned long)ms);
    C[g_cur].patience = ms;
}

static const NetRaceNet kNet = {
    fState, fPeerAlive, fPeerName, fSend, fRecv, fSetPatience,
};

// ---------------------------------------------------------------- the game

static uint32_t draw(void)
{
    bDefaultSeed = bDefaultSeed * 1664525u + 1013904223u;
    return bDefaultSeed >> 8;
}

static void gStartLoading(void)
{
    Console* k = &C[g_cur];

    printf("[%d] start loading\n", g_cur);
    if (k->loadingAt >= 0) fault("a second load");
    k->loadingAt = g_frame;
    k->seedTaken = bDefaultSeed;
    bgf_change_to_screen(&k->gf, "Loading", 0);
}

// FrontendDatabase::StartRace, as far as netrace.c cares.
static void gStartRace(void)
{
    RaceParameters* rp = &TheRaceParameters;
    int             i, n = 0;

    printf("[%d] start race\n", g_cur);
    C[g_cur].starts++;
    draw();
    for (i = 0; i < 2; i++, n++) {
        DriverInfo* d = &DriverInfoTable[n];
        memset(d, 0, sizeof *d);
        d->UniqueDriverNumber = (int8_t)i;
        d->CharacterNumber    = (int8_t)i;
        d->TheDriverType      = 1;
        d->CurrentRideInfo    = g_rides[i];
        d->CurrentRideInfo.CanBeVertexDamaged = 1;
        d->pCharacterInfo     = &g_chars[g_cur][i];
        rp->PlayerSettings[i] = Fred.FrontendPlayers[i].mPlayerSettings;
    }
    for (i = 0; i < rp->NumAICars && n < RACE_PARAMETERS_MAX_DRIVERS;
         i++, n++) {
        DriverInfo* d = &DriverInfoTable[n];
        RideInfo    ride;

        memset(d, 0, sizeof *d);
        if (!gFredNetRideFn || !gFredNetRideFn(i, &ride)) {
            memset(&ride, 0, sizeof ride);
            ride.Type          = (int32_t)(draw() % 40);
            ride.SkinNumber    = (int8_t)(draw() % 4);
            ride.InstanceIndex = 2;   // drawn: StartRace's own
        }
        d->UniqueDriverNumber = (int8_t)(100 + i);
        d->CharacterNumber    = (int8_t)(2 + i);
        d->SkillLevel         = (int8_t)(draw() % 3);
        d->StartingPosition   = (int8_t)n;
        d->TheDriverType      = 2;
        d->CurrentRideInfo    = ride;
        d->pCharacterInfo     = &g_chars[g_cur][2 + i];
    }
    rp->NumDriverInfo         = n;
    rp->pDriverInfoTable      = DriverInfoTable;
    rp->GlobalDisplaySettings = Fred.DisplayOptionsData;
    rp->New780                = (int32_t)draw();
    TheRaceEvent.nInitialPlayers = (int16_t)Fred.NumPlayerCars;
    if (Fred.GameType == 4) {
        TheRaceEvent.pState = TheRaceEvent.aOldState;
        memset(TheRaceEvent.aOldState, 0x11, sizeof TheRaceEvent.aOldState);
        TheRaceEvent.nOpponents = (int16_t)rp->NumAICars;
    }
    C[g_cur].seedBuilt = bDefaultSeed;
    gStartLoading();
    Fred.bRaceWasAborted = 0;
}

static RideInfo* gSelectedRide(int p)
{
    if (p < 0 || p > 1) fault("selectedRide(%d)", p);
    return &g_rides[p & 1];
}

static CharacterInfo* gCharacterInfo(int32_t c)
{
    return c >= 0 && c < NUM_CHARS ? &g_chars[g_cur][c] : NULL;
}

static void gGoRacing(void)
{
    Console* k = &C[g_cur];
    int      p;

    printf("[%d] racing\n", g_cur);
    if (k->racingAt >= 0) fault("racing twice");
    if (k->loadedAt < 0) fault("racing before the load");
    if (netrace_stage() != (OFFLINE ? NR_OFF : NR_RACING))
        fault("racing at stage %d", (int)netrace_stage());
    if (k->patience != (OFFLINE ? 0u : NETRACE_PATIENCE_MS))
        fault("racing with patience %lu", (unsigned long)k->patience);
    // The host's GO is on its seed as it is then, and a client that lost
    // the host races on its own as it held.
    if ((g_cur == 0 || !k->goRecv) && bDefaultSeed != k->seedHeld)
        fault("racing on %08lx, held on %08lx", (unsigned long)bDefaultSeed,
              (unsigned long)k->seedHeld);
    k->racingAt = g_frame;
    k->goRp     = TheRaceParameters;
    memcpy(k->goTable, DriverInfoTable, sizeof DriverInfoTable);
    k->goEv        = TheRaceEvent;
    k->goSeed      = bDefaultSeed;
    for (p = 0; p < MAXC; p++) k->goDriver[p] = (int8_t)netrace_driver(p);
    k->goGameType  = Fred.GameType;
    k->goPlayers   = Fred.NumPlayerCars;
    k->goAborted   = Fred.bRaceWasAborted;
    bgf_change_to_screen(&k->gf, "Racing", 0);
    // 37d's first message to each console racing, and each client's to the
    // host, which netrace must leave to the race.
    if (g_cur == 0) {
        for (p = 1; p < S->consoles; p++)
            if (k->goDriver[p] >= 0 && alive(p))
                fSend(peerOf(p), 0x20, "r", 1);
    } else if (alive(0)) {
        fSend(0, 0x21, "r", 1);
    }
}

static const NetRaceGame kGame = {
    gStartRace, gSelectedRide, gCharacterInfo, gStartLoading, gGoRacing,
};

// ---------------------------------------------------------------- the flow

static void wTrace(void* user, const char* line)
{
    (void)user;
    printf("[%d] %s\n", g_cur, line);
}

static void wSound(void* user, int ev)
{
    (void)user;
    printf("[%d] sound %d\n", g_cur, ev);
    if (C[g_cur].sounds++ == 0) C[g_cur].sound0 = ev;
}

static void otherScreen(BGameFlow* gf, BScreenMessage msg,
                        BScreenCallbackData* data)
{
    (void)gf;
    (void)msg;
    (void)data;
}

// The lobby, as far as the race sees it: coming back takes the link down,
// after the line it was left.
static void lobbyScreen(BGameFlow* gf, BScreenMessage msg,
                        BScreenCallbackData* data)
{
    Console* k = &C[g_cur];
    char     line[300];

    (void)gf;
    (void)data;
    if (msg != BMSG_SCREEN_ACTIVATE) return;
    k->off = 1;
    wLog("lobby: link down");
    if (k->notice) {
        if (k->patience != 0)
            fault("back to the lobby with patience %lu",
                  (unsigned long)k->patience);
        fillName(line + 14, sizeof line - 14, text(k->notice), k->noticeName);
        memcpy(line, "lobby: notice ", 14);
        wLog(line);
        k->notice = 0;
    }
}

// netrace's own, with the wait lines said from its coming up.
static void netraceScreen(BGameFlow* gf, BScreenMessage msg,
                          BScreenCallbackData* data)
{
    if (msg == BMSG_SCREEN_ACTIVATE) C[g_cur].lastWait[0] = 0;
    netrace_callback(gf, msg, data);
}

static const BScreenConfig kScreens[] = {
    { "Prev",              0x11111111u, otherScreen },
    { LOBBY_SCREEN_NAME,   0,           lobbyScreen },
    { "Select Car",        0x22222222u, otherScreen },
    { "Select Track",      0x33333333u, otherScreen },
    { NETRACE_SCREEN_NAME, 0,           netraceScreen },
    { "Loading",           0x44444444u, otherScreen },
    { "Racing",            0x55555555u, otherScreen },
};

static const BGameFlowStateInfo kStates[BGF_NUM_STATES] = {
    { "NONE",                     NULL, NULL, NULL },
    { "LOADING_FRONTEND",         NULL, NULL, NULL },
    { "UNLOADING_FRONTEND",       NULL, NULL, NULL },
    { "IN_FRONTEND",              NULL, NULL, NULL },
    { "LOADING_TRACK_COMMON",     NULL, NULL, NULL },
    { "LOADING_TRACK_SPECIFIC",   NULL, NULL, NULL },
    { "RACING",                   NULL, NULL, NULL },
    { "UNLOADING_TRACK_SPECIFIC", NULL, NULL, NULL },
    { "UNLOADING_TRACK_COMMON",   NULL, NULL, NULL },
};

static const char* screenName(const Console* k)
{
    return k->gf.screen ? k->gf.screen->name : "-";
}

// ------------------------------------------------------------- the checks

static const BPopup* upPopup(const Console* k, int* count)
{
    const BPopup* p = NULL;
    int           i;

    *count = 0;
    for (i = 0; i < BPOPUP_COUNT; i++) {
        if (!k->gf.popups[i].active) continue;
        (*count)++;
        p = &k->gf.popups[i];
    }
    return p;
}

static void wantLine(char* want, size_t cap)
{
    char name[WIRELESS_NAME_MAX];
    int  p;

    if (g_cur != 0) {
        lobby_latin1(name, sizeof name, S->names[0]);
        fillName(want, cap, text(PORTLANG_WAITING_FOR_HOST), name);
        return;
    }
    snprintf(want, cap, "%s", text(PORTLANG_WAITING_FOR_CARS));
    for (p = 1; p < S->consoles; p++) {
        if (!alive(p) || C[0].carIn[p]) continue;
        lobby_latin1(name, sizeof name, S->names[p]);
        strncat(want, "@", cap - strlen(want) - 1);
        strncat(want, name, cap - strlen(want) - 1);
    }
}

static void checkFrame(void)
{
    Console*      k = &C[g_cur];
    int           n;
    const BPopup* p  = upPopup(k, &n);
    NetRaceStage  st = netrace_stage();
    int           on = !strcmp(screenName(k), NETRACE_SCREEN_NAME);

    if (n > 1) fault("%d popups up", n);
    if (!on && n) fault("a popup up on %s", screenName(k));
    if (on) {
        char want[600];

        if (!p) {
            fault("\"Wireless Race\" with no popup");
        } else {
            const char* msg = p->cfg.message ? p->cfg.message : "";

            if (!p->parentName || strcmp(p->parentName, NETRACE_SCREEN_NAME))
                fault("the popup's parent is %s",
                      p->parentName ? p->parentName : "-");
            if (p->cfg.title != PORTLANG_LOCAL_WIRELESS)
                fault("the popup's title is %ld", (long)p->cfg.title);
            if (p->cfg.screen != BPOPUP_SCREEN_MEMCARD)
                fault("the popup's screen is %d", (int)p->cfg.screen);
            if (p->cfg.joyPort != -1)
                fault("the popup hears port %d alone", (int)p->cfg.joyPort);
            if (p->cfg.numButtons != 0)
                fault("%d buttons", (int)p->cfg.numButtons);
            if (!(p->cfg.flags & BPOPUP_CANCELABLE)) fault("BACK not taken");
            wantLine(want, sizeof want);
            if (strcmp(msg, want)) fault("the popup says \"%s\"", msg);
        }
        if (st != NR_WAIT) fault("\"Wireless Race\" at stage %d", (int)st);
    }
    if (st != NR_OFF && k->patience != NETRACE_PATIENCE_MS)
        fault("stage %d with patience %lu", (int)st,
              (unsigned long)k->patience);
    if (gFredNetRideFn) fault("gFredNetRideFn left set");
    if (k->sounds && !k->pressed) fault("sound %d with no press", k->sound0);
}

// The press's sounds: B on "Wireless Race" the cancel, A none.
static void press(const char* key)
{
    Console* k  = &C[g_cur];
    int      on = !strcmp(screenName(k), NETRACE_SCREEN_NAME);
    int      ev = !strcmp(key, "A") ? BJOY_MENU_SELECT : BJOY_MENU_BACK;

    k->sounds  = 0;
    k->pressed = 1;
    if (!bpopup_joy(&k->gf, 0, ev, 1) && ev == BJOY_MENU_BACK)
        bgf_back_button(&k->gf, 0);
    if (!on) return;
    if (ev == BJOY_MENU_SELECT && k->sounds)
        fault("A on the wait: sound %d", k->sound0);
    if (ev == BJOY_MENU_BACK && (k->sounds != 1 || k->sound0 != BSND_MENU_CANCEL))
        fault("B on the wait: %d sounds, the first %d", k->sounds,
              k->sounds ? k->sound0 : 0);
    // A puts it straight back, not a frame later.
    if (!strcmp(screenName(k), NETRACE_SCREEN_NAME)
        && netrace_stage() == NR_WAIT) {
        int n;
        upPopup(k, &n);
        if (!n) fault("no popup after %s", key);
    }
}

// A car chosen: this console's, and on, as car select's continue.
static void chooseCar(void)
{
    Console*         k = &C[g_cur];
    cPlayerSettings* s = &Fred.FrontendPlayers[0].mPlayerSettings;

    if (strcmp(screenName(k), "Select Car"))
        fault("a car chosen on %s", screenName(k));
    g_rides[0].Type          = 3 + 5 * g_cur;
    g_rides[0].SkinNumber    = (int8_t)(g_cur % 4);
    g_rides[0].InstanceIndex = 1;
    g_rides[0].HasDash       = 1;
    g_rides[0].CanBeVertexDamaged = 1;
    s->DriveCameraPOVIndex = (int8_t)g_cur;
    s->TransmissionType    = (int8_t)(g_cur & 1);
    if (!netrace_car_chosen(&k->gf))
        bgf_change_to_screen(&k->gf, "Select Track", 1);
}

// The host's start on Select Track, as track select's.
static void hostStart(void)
{
    Console* k = &C[g_cur];

    if (strcmp(screenName(k), "Select Track"))
        fault("a start on %s", screenName(k));
    TheRaceParameters.TrackNumber = 7;
    if (!(netrace_active()
          && (netrace_host_start(&k->gf) || netrace_car_chosen(&k->gf))))
        gStartRace();
}

// ------------------------------------------------------------- a scenario

static void initConsole(int c)
{
    Console*          k = &C[c];
    FrontendDatabase* f = &k->fred;
    int               i;

    memset(k, 0, sizeof *k);
    // What each console had, none of which a client's race may keep.
    memset(&k->rp, 0x20 + c, sizeof k->rp);
    k->rp.TrackNumber      = 1 + c;
    k->rp.NumPlayerCars    = 2;
    k->rp.NumAICars        = c == 0 ? S->numAI : 5;
    k->rp.NumDriverInfo    = 0;
    k->rp.pDriverInfoTable = DriverInfoTable;
    memset(k->table, 0x40 + c, sizeof k->table);
    memset(&k->ev, 0x60 + c, sizeof k->ev);
    k->ev.pTree  = &g_trees[c];
    k->ev.pState = g_states[c];
    f->GameType      = c == 0 ? S->gameType : 0;
    f->NumPlayerCars = c == 0 ? 2 : 1;
    f->bRaceWasAborted = 1;
    memset(&f->DisplayOptionsData, 0x70 + c, sizeof f->DisplayOptionsData);
    f->DisplayOptionsData.JumpCams = (int8_t)(c & 1);
    f->DisplayOptionsData.ZoneCams = (int8_t)((c >> 1) & 1);
    for (i = 0; i < 2; i++) {
        cPlayerSettings* s = &f->FrontendPlayers[i].mPlayerSettings;
        memset(s, 0x80 + 0x10 * i + c, sizeof *s);
        snprintf(s->PlayerName, sizeof s->PlayerName, "%c%d", "PQ"[i], c);
    }
    k->seed = 0x1000u + 0x111u * (uint32_t)c;
    k->rides[0].Type = 30 + c;
    k->rides[1].Type = 50 + c;
    k->rides[1].SkinNumber = 2;
    k->rides[1].CanBeVertexDamaged = 1;
    for (i = 0; i < NUM_CHARS; i++) g_chars[c][i].CharacterNumber = i;

    k->display = f->DisplayOptionsData;
    k->tree    = k->ev.pTree;
    k->state   = k->ev.pState;
    k->ride1   = k->rides[1];
    k->set1    = f->FrontendPlayers[1].mPlayerSettings;
    k->loadingAt = k->loadedAt = k->heldAt = k->racingAt = -1;

    // The lobby's Start: on to car select, the lobby under it.
    k->race.consoles = S->consoles;
    k->race.place    = c;
    for (i = 0; i < MAXC; i++) k->race.peer[i] = -1;
    if (c == 0) {
        for (i = 1; i < S->consoles; i++) k->race.peer[i] = peerOf(i);
    } else {
        k->race.peer[0] = 0;
    }
    lobby_latin1(k->race.hostName, sizeof k->race.hostName, S->names[0]);
}

static void startConsole(int c)
{
    Console*       k = &C[c];
    BGameFlowHooks hooks;

    enter(c);
    memset(&hooks, 0, sizeof hooks);
    hooks.trace = wTrace;
    hooks.sound = wSound;
    bgf_init(&k->gf, kStates, BGF_NUM_STATES, kScreens,
             (int)(sizeof kScreens / sizeof kScreens[0]), NULL, 0, &hooks);
    k->gf.currLanguage = S->language;
    netrace_init(&kNet, &kGame, wLog);
    bgf_change_to_screen(&k->gf, "Prev", 0);
    bgf_change_to_screen(&k->gf, LOBBY_SCREEN_NAME, 1);
    k->off = 0;   // the lobby's ACTIVATE, the first time: not yet down
    k->numLog = 0;
    bgf_change_to_screen(&k->gf, "Select Car", 1);
    if (!OFFLINE) netrace_begin(&k->race);
    leave();
}

static void consoleFrame(int c)
{
    Console* k = &C[c];
    int      e, stalled;

    enter(c);
    k->sounds  = 0;
    k->pressed = 0;
    for (e = 0; e < MAX_EVENTS && S->ev[e].what; e++) {
        const Event* v = &S->ev[e];
        if (v->frame != g_frame || v->console != c) continue;
        printf("[%d] event %s\n", c, v->what);
        if (!strcmp(v->what, "car")) chooseCar();
        else if (!strcmp(v->what, "start")) hostStart();
        else if (!strcmp(v->what, "A") || !strcmp(v->what, "B"))
            press(v->what);
        else if (!strcmp(v->what, "ai0"))
            TheRaceParameters.NumAICars = 0;   // track select's options
    }

    // A loading console's loop stalls but for a frame in STALL.
    stalled = k->loadingAt >= 0 && k->loadedAt < 0 && g_frame % STALL != 0;
    if (netrace_active() && !stalled) netrace_frame(&k->gf);

    if (k->loadingAt >= 0 && k->loadedAt < 0
        && g_frame - k->loadingAt >= S->load[c]) {
        int i;

        k->loadedAt = g_frame;
        // The load's own randoms, a different count on each console.
        for (i = 0; i <= c; i++) draw();
        k->seedHeld = bDefaultSeed;
        printf("[%d] loaded\n", c);
        if (netrace_hold()) {
            if (k->heldAt < 0 && netrace_stage() >= NR_HOLD)
                k->heldAt = g_frame;
        } else {
            gGoRacing();
        }
    }
    bgf_frame(&k->gf, SIXTIETH);
    checkFrame();
    leave();
}

static int parseDrivers(const char* s, int* out)
{
    int n = 0;
    while (s && *s && n < MAXC) {
        char* end;
        long  v = strtol(s, &end, 10);
        if (end == s) break;
        out[n++] = (int)v;
        s = end;
    }
    return n;
}

static int sameRide(const RideInfo* a, const RideInfo* b)
{
    return a->Type == b->Type && a->InstanceIndex == b->InstanceIndex
        && a->SkinNumber == b->SkinNumber && a->HasDash == b->HasDash
        && a->CanBeVertexDamaged == b->CanBeVertexDamaged;
}

// The car console c chose (chooseCar).
static RideInfo carOf(int c)
{
    RideInfo r;
    memset(&r, 0, sizeof r);
    r.Type          = 3 + 5 * c;
    r.SkinNumber    = (int8_t)(c % 4);
    r.InstanceIndex = 1;
    r.HasDash       = 1;
    r.CanBeVertexDamaged = 1;
    return r;
}

// Each racing place's settings, as console k has them: the ones its
// player had when the car was chosen.
static void checkSettings(const Console* k)
{
    int p;

    for (p = 0; p < S->consoles; p++) {
        if (k->goDriver[p] < 0) continue;
        if (memcmp(&k->nr.cars[p].settings,
                   &C[p].fred.FrontendPlayers[0].mPlayerSettings,
                   sizeof(cPlayerSettings)))
            fault("place %d's settings are not its player's", p);
    }
}

static void checkHost(void)
{
    const Console* h = &C[0];
    int            want[MAXC], n, p, ai = 0;

    g_cur = 0;
    if (memcmp(&h->rides[1], &h->ride1, sizeof h->ride1)
        || memcmp(&h->fred.FrontendPlayers[1].mPlayerSettings, &h->set1,
                  sizeof h->set1))
        fault("the host's second player not put back");
    if (h->racingAt < 0 || !S->drivers) return;
    checkSettings(h);
    n = parseDrivers(S->drivers, want);
    for (p = 0; p < S->consoles; p++) {
        int d = p < n ? want[p] : -1;
        RideInfo car = carOf(p);

        if (h->goDriver[p] != d)
            fault("place %d drives %d, not %d", p, h->goDriver[p], d);
        if (d == 0 && !sameRide(&h->goTable[0].CurrentRideInfo, &car))
            fault("the host's car is type %d", (int)h->goTable[0].CurrentRideInfo.Type);
        if (d == 1) {
            if (!sameRide(&h->goTable[1].CurrentRideInfo, &car))
                fault("the second player's car is type %d",
                      (int)h->goTable[1].CurrentRideInfo.Type);
            if (h->goRp.PlayerSettings[1].DriveCameraPOVIndex != p
                || strcmp(h->goRp.PlayerSettings[1].PlayerName, "P0") == 0)
                fault("the second player's settings are not place %d's", p);
        }
        if (d >= 100) {
            const DriverInfo* t = &h->goTable[2 + d - 100];
            car.InstanceIndex      = 0;
            car.CanBeVertexDamaged = 0;
            if (t->UniqueDriverNumber != d || !sameRide(&t->CurrentRideInfo, &car))
                fault("AI racer %d: driver %d, type %d instance %d damage %d",
                      d - 100, t->UniqueDriverNumber,
                      (int)t->CurrentRideInfo.Type,
                      t->CurrentRideInfo.InstanceIndex,
                      t->CurrentRideInfo.CanBeVertexDamaged);
            ai++;
        }
    }
    // The rest of the AI racers are StartRace's own, drawn.
    for (p = 2 + ai; p < h->goRp.NumDriverInfo; p++)
        if (h->goTable[p].CurrentRideInfo.HasDash
            || h->goTable[p].CurrentRideInfo.InstanceIndex != 2)
            fault("driver %d not in a car StartRace drew", p);
    if (h->goRp.NumAICars < ai)
        fault("%ld AI racers for %d players", (long)h->goRp.NumAICars, ai);
    if (h->goRp.NumAICars < S->consoles - 2)
        fault("%ld AI racers for %d consoles", (long)h->goRp.NumAICars,
              S->consoles);
    if (h->goTable[0].CurrentRideInfo.CanBeVertexDamaged != 1)
        fault("the host's car not damageable");
}

static void checkClient(int c)
{
    const Console* h = &C[0];
    const Console* k = &C[c];
    RaceParameters rp;
    RaceEvent      ev;
    int            i;

    g_cur = c;
    if (k->loadingAt >= 0 && k->seedTaken != h->seedBuilt)
        fault("loaded on seed %08lx, the race built on %08lx",
              (unsigned long)k->seedTaken, (unsigned long)h->seedBuilt);
    if (k->racingAt < 0) return;
    {
        const Pipe* p = &g_pipe[0][c];
        if (alive(0) && (p->head == p->tail || p->q[p->head].m.type != 0x20))
            fault("the race's message not left to the race");
        p = &g_pipe[c][0];
        if (alive(0) && h->racingAt >= 0
            && (p->head == p->tail || p->q[p->head].m.type != 0x21))
            fault("the race's message to the host not left to the race");
    }
    if (h->racingAt < 0) return;
    checkSettings(k);
    if (k->goSeed != h->goSeed)
        fault("seed %08lx at GO, the host's %08lx", (unsigned long)k->goSeed,
              (unsigned long)h->goSeed);
    rp = k->goRp;
    rp.GlobalDisplaySettings = h->goRp.GlobalDisplaySettings;
    if (memcmp(&rp, &h->goRp, sizeof rp)) fault("the parameters differ");
    {
        tGlobalDisplaySettings d = k->display;
        d.JumpCams = h->goRp.GlobalDisplaySettings.JumpCams;
        d.ZoneCams = h->goRp.GlobalDisplaySettings.ZoneCams;
        if (memcmp(&k->goRp.GlobalDisplaySettings, &d, sizeof d))
            fault("the display settings are not its own with the host's "
                  "cameras");
        if (memcmp(&k->fred.DisplayOptionsData, &k->display, sizeof d))
            fault("its own display settings changed");
    }
    for (i = 0; i < h->goRp.NumDriverInfo; i++) {
        DriverInfo a = k->goTable[i], b = h->goTable[i];
        if (a.pCharacterInfo != &g_chars[c][a.CharacterNumber])
            fault("driver %d's character not this console's", i);
        a.pCharacterInfo = b.pCharacterInfo = NULL;
        if (memcmp(&a, &b, sizeof a)) fault("driver %d differs", i);
    }
    ev = k->goEv;
    if (ev.pTree != k->tree) fault("the event's tree not its own");
    if (h->goEv.pState == TheRaceEvent.aOldState) {
        if (ev.pState != TheRaceEvent.aOldState)
            fault("the event's state not in the event");
    } else if (ev.pState != k->state) {
        fault("the event's state not its own");
    }
    ev.pTree  = h->goEv.pTree;
    ev.pState = h->goEv.pState;
    if (memcmp(&ev, &h->goEv, sizeof ev)) fault("the event differs");
    if (memcmp(k->goDriver, h->goDriver, sizeof k->goDriver))
        fault("the drivers differ");
    if (k->goGameType != h->goGameType || k->goPlayers != h->goPlayers)
        fault("game type %ld players %ld, the host's %ld %ld",
              (long)k->goGameType, (long)k->goPlayers, (long)h->goGameType,
              (long)h->goPlayers);
    if (k->goAborted) fault("the race was aborted");
    if (k->starts) fault("a client's own StartRace");
}

static void runScenario(const Scenario* sc)
{
    int c, f, e, at[MAXC];

    S        = sc;
    g_faults = 0;
    g_frame  = 0;
    g_lcg    = 1;
    memset(g_pipe, 0, sizeof g_pipe);
    printf("scenario %s\n", sc->name);
    for (c = 0; c < sc->consoles; c++) initConsole(c);
    for (c = 0; c < sc->consoles; c++) startConsole(c);

    for (f = 0; f < sc->frames; f++) {
        g_frame = f;
        for (e = 0; e < MAX_EVENTS && sc->ev[e].what; e++) {
            const Event* v = &sc->ev[e];
            if (v->frame != f) continue;
            if (!strcmp(v->what, "gone")) {
                int t;
                printf("[%d] gone\n", v->console);
                C[v->console].gone = 1;
                for (t = 0; t < MAXC; t++) {
                    g_pipe[v->console][t].head = g_pipe[v->console][t].tail;
                    g_pipe[t][v->console].head = g_pipe[t][v->console].tail;
                }
            } else if (!strcmp(v->what, "off")) {
                C[v->console].off = 1;
            }
        }
        for (c = 0; c < sc->consoles; c++)
            if (!C[c].gone) consoleFrame(c);
    }

    for (c = 0; c < sc->consoles; c++) {
        Console* k = &C[c];

        g_cur = c;
        if (sc->endScreen[c] && strcmp(screenName(k), sc->endScreen[c]))
            fault("ends on %s, not %s", screenName(k), sc->endScreen[c]);
        if (!k->gone && (k->racingAt >= 0) != sc->racing[c])
            fault("%s racing", k->racingAt >= 0 ? "ends" : "never");
        if (k->notice) fault("a notice left for the lobby");
        if (OFFLINE && k->numLog)
            fault("said \"%s\" with no wireless race", k->log[0]);
        if (!k->gone) {
            NetRaceStage want = k->racingAt >= 0 && !OFFLINE ? NR_RACING
                                                                 : NR_OFF;
            int          p;

            enter(c);
            if (netrace_stage() != want)
                fault("ends at stage %d, not %d", (int)netrace_stage(),
                      (int)want);
            // Nothing built or taken: no place drives.
            for (p = 0; p < MAXC && k->loadingAt < 0; p++)
                if (netrace_driver(p) != -1)
                    fault("place %d drives %d with no race", p,
                          netrace_driver(p));
            // A load after (a restart) is not held.
            if (netrace_hold()) fault("a second load held");
            leave();
        }
    }
    // Each console's lines in its own order.
    memset(at, 0, sizeof at);
    for (e = 0; e < MAX_EXPECT && sc->expect[e]; e++) {
        const char* want = sc->expect[e];
        int         c2   = want[0] - '0';
        size_t      n    = strlen(want + 2);

        g_cur = c2;
        while (at[c2] < C[c2].numLog && strncmp(C[c2].log[at[c2]], want + 2, n))
            at[c2]++;
        if (at[c2] == C[c2].numLog) {
            fault("never said \"%s\" (in order)", want + 2);
            break;
        }
        at[c2]++;
    }
    checkHost();
    for (c = 1; c < sc->consoles; c++) checkClient(c);
    g_cur = -1;
    printf("faults %d\n", g_faults);
}

int main(int argc, char** argv)
{
    int total = 0, a, i;

    if (argc < 2) {
        for (i = 0; i < NUM_SCENARIOS; i++) {
            runScenario(&kScenarios[i]);
            total += g_faults;
        }
    } else {
        for (a = 1; a < argc; a++) {
            int found = 0;
            for (i = 0; i < NUM_SCENARIOS; i++) {
                if (strcmp(kScenarios[i].name, argv[a])) continue;
                runScenario(&kScenarios[i]);
                total += g_faults;
                found = 1;
            }
            if (!found) {
                fprintf(stderr, "unknown scenario: %s\n", argv[a]);
                return 2;
            }
        }
    }
    printf("total faults %d\n", total);
    return 0;
}
