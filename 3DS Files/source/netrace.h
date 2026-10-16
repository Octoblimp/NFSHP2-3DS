// netrace -- a local wireless race's setup, the port's (TASKS 37c).
//
// The lobby (lobby.c) ends with every console on its way to car select,
// the link up and each with a place: the host's 0, the clients' 1 on.
// From there:
//
//   - Each console picks its own car. A client then sends it to the host
//     (NETRACE_MSG_CAR: the ride and the player's settings) and waits on
//     the screen "Wireless Race" instead of going on to Select Track.
//     BACK there takes it back to car select and the car back
//     (NETRACE_MSG_UNCAR).
//   - The host picks the track. Its start waits on the same screen, the
//     line naming whoever has not sent a car, until all still on have.
//   - The host builds the race: retail's StartRace (fred_start_race), with
//     the first client's car and settings as the second player's and the
//     rest of the clients' cars in AI racers' places (gFredNetRideFn), as
//     many CPU racers as the host chose in the lobby (TASKS 37c-2) on top.
//     The CPU racers take the front of the grid by performance, as
//     retail's AI racers do; the players start behind them in the order
//     of their places.
//     What it made -- the race's parameters, the driver table, the race
//     event, Fred's game type and player count, the random seed, and the
//     driver each place drives -- goes to every client (NETRACE_MSG_SETUP,
//     in pieces). A client takes it all in place of its own and loads.
//   - Each console holds at the end of its load (gTrackFlowHoldRaceFn),
//     the loading screen up; a client says so (NETRACE_MSG_LOADED). Once
//     all still on have, the host sends NETRACE_MSG_GO with the seed as
//     it is then, and every console starts the race on that seed.
//
// From the lobby's start on, a silent console is waited for
// NETRACE_PATIENCE_MS, since the load and then the race's first frame
// (its drawing's preparation) stop a console's loop for seconds. The race
// (37d) gives the link its own timeout back once every console's frames
// come in; going back to the lobby does too.
//
// A console lost on the way: before the build the host races without it,
// or goes back to the lobby with a notice when none is left; a client
// that loses the host goes back to the lobby with the notice. Once the
// race is built nobody gone is waited for: the host goes on when the rest
// have loaded, and a client that loses the host at the hold starts alone.
// What a race does with a console gone is 37f's.
//
// A console back after a restart (37g-3): its lobby joined the racing
// host into the place of one the race holds for (37g-2's rejoin, by its
// name) and said so (LOBBY_MSG_REJOIN), which netstep leaves on the link
// for the host's netrace. In the event's first race, the race lets it
// back in (netstep_rejoin) and answers (LOBBY_MSG_RESUME: the place and
// Start's mode) with the setup it built, again. The console takes it
// from its lobby and loads (LobbyRace.resume); once it says it loaded,
// the host sends it GO with the race's seed, and it runs the race from
// its first frame on the host's records until it has caught up
// (netstep.h). In a later race, the setup kept is the first's, so the
// answer is empty: refused. Given up on as it loads (the hold over), it
// is sent off the network.
//
// The race's end (37f): lockstep stops on every console after the same
// frame (netstep.h) and netrace_end leaves the race NR_ENDED. From there
// the frontend (each console back to the lobby, and netrace off once it
// loads), or the event's next race or its restart: every console loads
// the next race on what lockstep left it, the same on each, and holds
// again; the host sends GO with a new seed once the rest have loaded. A
// client says it loaded only once its stop has been said, and the host
// sends GO only once its last frames have been served (NetRaceNet.busy),
// so the last race's messages are read and dropped before the next GO.
//
// Host-buildable: the link is the NetRaceNet's, and what of the game it
// does not reach through globals the NetRaceGame's, which main.c fills
// and tools/src/netrace_test.c fakes. The state is a NetRace, so that the
// harness can run several consoles in one process (netrace_bind).

#ifndef NETRACE_H
#define NETRACE_H

#include <stddef.h>
#include <stdint.h>

#include "bmenu.h"
#include "car.h"
#include "lobby.h"
#include "playersettings.h"
#include "wireless.h"

typedef struct BGameFlow BGameFlow;

#define NETRACE_SCREEN_NAME "Wireless Race"
#define NETRACE_PATIENCE_MS 30000u
#define NETRACE_PIECE       (WL_MSG_MAX - 4)   // a SETUP piece's bytes
#define NETRACE_SETUP_MAX   4096
#define NETRACE_MAX_HUMAN_AI 6                 // AI racers' places taken

// The race's reliable messages, after the lobby's.
enum {
    NETRACE_MSG_CAR = 0x11,   // a client's: place, ride (8), settings (48)
    NETRACE_MSG_UNCAR,        // a client's: place; its car taken back
    NETRACE_MSG_SETUP,        // the host's: offset (2), total (2), bytes
    NETRACE_MSG_LOADED,       // a client's: place; loaded and held
    NETRACE_MSG_GO,           // the host's: the seed (4)
};

// The link, as wireless.h has it.
typedef struct NetRaceNet {
    WirelessState (*state)(void);
    int           (*peerAlive)(int i);
    const char*   (*peerName)(int i);      // UTF-8
    int           (*send)(int i, uint8_t type, const void* data, size_t n);
    int           (*recv)(int i, WlMsg* out);
    void          (*setPatience)(uint32_t ms);
    // The last race's end still on the link (netstep_ending): nothing of
    // netrace's read or sent until it is through. NULL: never.
    int           (*busy)(void);
    // The next message from peer i, left on the link (37g-3).
    int           (*peek)(int i, WlMsg* out);
    // A console back in place `p` after a restart (37g-3): netstep_rejoin,
    // 1 when let in; the places still loading or catching up
    // (netstep_rejoining); and peer i sent off the network
    // (wireless_drop). NULL: no console comes back.
    int           (*rejoin)(int p);
    uint8_t       (*rejoining)(void);
    void          (*drop)(int i);
    // Peer i's link's own patience (37g-3), as setPatience's: a console
    // back after a restart has netrace's from its RESUME until it has
    // caught up, over its load and its first frame's long preparation; 0
    // the link's own. NULL: none.
    void          (*setPeerPatience)(int i, uint32_t ms);
} NetRaceNet;

// The game's, where a global will not do.
typedef struct NetRaceGame {
    // StartRace on the global Fred: the race built, the load asked for.
    void           (*startRace)(void);
    // Fred's player `p`'s ride for Fred.GameType.
    RideInfo*      (*selectedRide)(int p);
    // GetCharacterInfo, for each driver a client takes.
    CharacterInfo* (*characterInfo)(int32_t character);
    // The flow on to loading, as StartRace asks for it.
    void           (*startLoading)(void);
    // trackflow_go_racing.
    void           (*goRacing)(void);
} NetRaceGame;

typedef void (*NetRaceLogFn)(const char* line);

typedef enum {
    NR_OFF,       // no wireless race
    NR_CARS,      // on from the lobby: car select, and the host's track
    NR_WAIT,      // "Wireless Race": the host's for cars, a client's for
                  // the setup
    NR_LOADING,   // built, or taken, and loading
    NR_HOLD,      // loaded, and held for the rest (host) or GO (client)
    NR_RACING,    // GO: the race is on
    NR_ENDED      // lockstep stopped (37f): the frontend next, or the
                  // event's next race, which holds again
} NetRaceStage;

typedef struct NetRaceCar {
    int             in;          // sent and not taken back
    RideInfo        ride;
    cPlayerSettings settings;
} NetRaceCar;

typedef struct NetRace {
    NetRaceNet   net;
    NetRaceGame  game;
    NetRaceLogFn log;
    NetRaceStage stage;
    LobbyRace    race;
    int          host;
    int          gone[WIRELESS_MAX_CONSOLES];      // lost, by place
    // By place: the host's, the clients' cars as sent; once the race is
    // built, on every console, the settings of each place racing.
    NetRaceCar   cars[WIRELESS_MAX_CONSOLES];
    int          loaded[WIRELESS_MAX_CONSOLES];    // the host's, by place
    int          saidLoaded;                       // a client's LOADED sent
    int          round;                            // races run, from 0
    int8_t       driver[WIRELESS_MAX_CONSOLES];    // by place, or -1
    int          humanAI;                          // the host's build
    int          aiPlace[NETRACE_MAX_HUMAN_AI];    // AI racer k's place
    uint8_t      setup[NETRACE_SETUP_MAX];         // sent, or coming
    size_t       setupLen, setupGot;
    uint32_t     seed;                             // GO's
    int          lastGone;                         // the place, or -1
    // Back after a restart (37g-3): a client's, its race taken from its
    // lobby; the host's, by place, the setup sent again and GO not yet,
    // and its link on netrace's patience until it has caught up.
    int          resumed;
    int          resuming[WIRELESS_MAX_CONSOLES];
    int          patient[WIRELESS_MAX_CONSOLES];
    // Each place's console, Latin-1: the host's own, and every client's
    // from the setup (37g).
    char         names[WIRELESS_MAX_CONSOLES][WIRELESS_NAME_MAX];
    // "Wireless Race"
    int          popup;
    int          quiet;
    char         message[512];
} NetRace;

// The one running: netrace's own unless bound to another (NULL: its own).
void netrace_bind(NetRace* r);

void netrace_init(const NetRaceNet* net, const NetRaceGame* game,
                  NetRaceLogFn log);

// The lobby's Start (LobbyStartFn), or its answer from a racing host to
// a console back after a restart (race->resume): the setup next.
void netrace_begin(const LobbyRace* race);

// A wireless race set up or run: from the lobby's Start until the link
// goes down.
int netrace_active(void);
NetRaceStage netrace_stage(void);

// This console's place, and the driver (UniqueDriverNumber) place `p`
// drives once the race is built, or -1.
int netrace_place(void);
int netrace_driver(int p);

// The race as the lobby's Start handed it on: the consoles, their peers
// and this console's place.
const LobbyRace* netrace_race(void);

// 1 on a console back after a restart (37g-3), in the race it came back
// into: from its GO it runs the race's past, undrawn, until it is in step.
int netrace_back_in(void);

// Place `p`'s console name, Latin-1, once the race is built; else "".
const char* netrace_place_name(int p);

// The lines over a race held for consoles lost (37g, netstep_held): the
// link to those of `places` lost, and the time left, m:ss. '@' breaks a
// line, as in retail's text.
void netrace_held_text(const BGameFlow* gf, uint8_t places, uint32_t msLeft,
                       char* out, size_t cap);

// Past the hold: that the CPU drives each of `places`' cars now.
void netrace_cpu_text(const BGameFlow* gf, uint8_t places, char* out,
                      size_t cap);

// Over a race held for consoles back after a restart (37g-3,
// netstep_rejoining): that each of `places` is coming back, and how far
// the furthest behind has got, `pct`; on the end of `out`, after a '@'
// when it has a line already.
void netrace_back_text(const BGameFlow* gf, uint8_t places, int pct,
                       char* out, size_t cap);

// On the console itself as it catches up: how far, `pct`.
void netrace_catch_up_text(const BGameFlow* gf, int pct, char* out,
                           size_t cap);

// Each frame, after the link's pump, wherever the flow is: what came in,
// the setup moved on, and "Wireless Race"'s popup kept up.
void netrace_frame(BGameFlow* gf);

// Car select's continue: a client's car to the host and the client on to
// "Wireless Race". 1 when it took over from Select Track.
int netrace_car_chosen(BGameFlow* gf);

// Track select's start on the host: the race built, or waited for on
// "Wireless Race". 1 when it took over from StartRace.
int netrace_host_start(BGameFlow* gf);

// gTrackFlowHoldRaceFn: the race built or taken, or the event's next one
// after the last race's end, loaded. A client says so on its next frame.
int netrace_hold(void);

// The race has left lockstep (netstep_stop, 37f): NR_ENDED. The link waits
// NETRACE_PATIENCE_MS for a silent console again, through each one's save
// and load. Should the frontend come next, it comes back to the lobby with
// the link up (lobby_back_next; gameflow's raceReturn named it at the
// race's start), and netrace is off once it loads; the event's next race
// holds and starts again in step (netrace_hold).
void netrace_end(void);

// The ScreenCallback, for kScreens[]: NETRACE_SCREEN_NAME's.
void netrace_callback(BGameFlow* gf, BScreenMessage msg,
                      BScreenCallbackData* data);

#endif
