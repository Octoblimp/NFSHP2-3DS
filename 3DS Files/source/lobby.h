// lobby -- the Local Wireless lobby, the port's (TASKS 37b).
//
// Retail's second player has a pad on the same PS2. The port's has a 3DS
// of their own (TASKS 37), so the port's multiplayer is a row of the main
// menu's own, Local Wireless (TASKS 63), which comes here. The lobby is a
// screen of popups, tPopupMenu's (bpopup.h) on the memory card's popup
// screen, over whatever the frontend shows behind it:
//
//   - "Host a race, or join one?" Host or Join; BACK leaves the lobby.
//   - Host: "Which mode will you host?" Hot Pursuit or World Racing, as
//     the main menu sets them, then retail's Challenge (LOBBY_SETUP_SCREEN)
//     for the race type, the skill and, under Setup, the track, its
//     Players reading Local Wireless (lobby_on_setup). Its select comes
//     back here; BACK from it, to the mode again.
//   - The host, set up: UDS up and a network made, then the names of the
//     consoles on it, this one first. Start shows once one has joined,
//     and closes the network; BACK takes it down, to Host or Join. Where
//     the race setup has CPU racers to choose (lobby_cpu_wish, TASKS
//     37c-2), a last line says how many and CPU Racers counts one more,
//     none again past as many as fit beside the consoles on the network;
//     the highlight stays on it as consoles come and go, so A there never
//     starts the race.
//   - A joiner: a scan each LOBBY_SCAN_MS until a race is found, then
//     that race, its host's name and how many are on it: Join, or Next
//     for the next one found (a new scan once the list has been seen).
//     Once joined, the host's name until the host starts; BACK leaves.
//   - The link lost, local wireless off or a join refused: the line, OK,
//     and back to the question.
//   - The console's wireless communication turned off (TASKS 62), on Host
//     or Join or under the lobby with the link up: the line that says so
//     and that it is turned on from the HOME Menu, OK, the question. UDS
//     is never started with it off.
//
// Start goes to every client as LOBBY_MSG_START, with the host's game
// type and cops, and every console then goes on to "Select Car", the
// lobby pushed under it. Coming back to the
// lobby before the race takes the network down. What the race needs over the link (the
// cars, the race's parameters, a barrier) is netrace.c's (37c), which the
// lobby tells what Start settled.
//
// After the race (TASKS 37f, lobby_back_next) the frontend comes back to
// the lobby with the link up: the host's list again, open to joiners, and
// a client's wait for the host's next Start. Each says it is back
// (LOBBY_MSG_BACK). The host lists a client once it is, and has Start
// again once every client still on is; each console, once every other
// still on is back, gives the link its own timeout again (the race's end
// left it long for the loads). With the link gone on the way, the line
// that says so, as before.
//
// A joiner says so to the host it joins (LOBBY_MSG_REJOIN), which a host
// in its lobby lets be. A host racing has let it on only into the place
// of a console the race holds for, by its name (37g-2): one that
// restarted mid-race and came back through Join (37g-3). Its race then
// answers (LOBBY_MSG_RESUME) with the place and Start's mode, and the
// race's setup after; the joiner waits on as it did for Start, and goes
// to the race's load from here, no car select (LobbyRace.resume). An
// answer with nothing in it is a race that will not take it back: the
// line that it could not join, OK, the question.
//
// Host-buildable: the link is the LobbyNet's, wireless.h's on the 3DS and
// a script in tools/src/lobby_test.c.

#ifndef LOBBY_H
#define LOBBY_H

#include <stddef.h>
#include <stdint.h>

#include "bmenu.h"
#include "wireless.h"

typedef struct BGameFlow BGameFlow;

// The lobby's place in the screen table (gameflow.h's
// BGF_LOCAL_WIRELESS_NAME, the main menu's way here), where a select of
// two players goes on the 3DS (bsetup.c), and where the host sets the
// race up.
#define LOBBY_SCREEN_NAME  "Local Wireless"
#define LOBBY_SETUP_SCREEN "Challenge"
#define LOBBY_NEXT_SCREEN "Select Car"

#define LOBBY_SCAN_MS 1000

// The lobby's reliable messages. 37c's come after.
enum {
    LOBBY_MSG_START  = 0x10,    // the host's: the race is on
    LOBBY_MSG_BACK   = 0x18,    // either's: back from the race (37f)
    LOBBY_MSG_REJOIN = 0x19,    // a joiner's, on joining (37g-3)
    LOBBY_MSG_RESUME = 0x1a,    // the racing host's answer: consoles,
                                // place, game type, cops; none: refused
};

// The link, as wireless.h has it. The lobby calls nothing else.
typedef struct LobbyNet {
    int           (*start)(void);
    void          (*stop)(void);
    int           (*host)(int consoles, const void* appdata, size_t n);
    void          (*setOpen)(int open);
    int           (*scan)(WirelessHost* out, int max);
    int           (*join)(int scanIndex);
    void          (*leave)(void);
    WirelessState (*state)(void);
    int           (*peerCount)(void);
    int           (*peerAlive)(int i);
    const char*   (*peerName)(int i);
    void          (*forgetLost)(void);
    // This console's name, UTF-8.
    const char*   (*selfName)(void);
    // A reliable message to peer i, and the next one from it.
    int           (*send)(int i, uint8_t type, const void* data, size_t n);
    int           (*recv)(int i, WlMsg* out);
    // Whether the console's wireless communication is turned off (TASKS
    // 62, wireless_radio_off): asked before start, and each frame with
    // the link up. NULL: never.
    int           (*radioOff)(void);
    // The silence that loses a console from now on, 0 for the link's own
    // (wireless_set_patience). NULL: never set.
    void          (*setPatience)(uint32_t ms);
} LobbyNet;

// What the lobby says it did, for the log and the check.
typedef void (*LobbyLogFn)(const char* line);

void lobby_init(const LobbyNet* net, LobbyLogFn log);

// The host's CPU racers. Retail's grid has 8 cars, so there is room for 8
// less the consoles. The wish is asked as hosting begins: how many the
// race setup the lobby came from has (LOBBY_CPU_FULL for its Full Grid,
// as many as fit), or LOBBY_CPU_NONE (any count below 0) where the mode
// has none to choose. With no wish function there is no choice.
#define LOBBY_GRID     8
#define LOBBY_CPU_NONE (-1)
#define LOBBY_CPU_FULL LOBBY_GRID
typedef int (*LobbyCpuFn)(void);
void lobby_cpu_wish(LobbyCpuFn fn);

// What Start settled. Each console still on has a place, the host's 0
// and the clients' 1 on in the order they came; `peer` is each place's
// peer for the link (the host's own -1, and on a client only the host's,
// 0, is known) and -1 past `consoles`. `cpu` is the host's CPU racers, 0
// with no choice and on a client (the host's setup says). `gameType` and
// `copsOn` are the host's Fred.GameType (the gameflow's gameType hook)
// and cops, on every console, for a client's car select: a client comes
// from the main menu, not from a setup of its own. -1 and 0 from a host
// that did not send them. `resume` is 1 on a console back in a race it
// was in before a restart (37g-3): the race is on, and its setup comes
// at once.
typedef struct LobbyRace {
    int  consoles;
    int  place;
    int  peer[WIRELESS_MAX_CONSOLES];
    char hostName[WIRELESS_NAME_MAX];    // Latin-1; on the host its own
    int  cpu;
    int  gameType;
    int  copsOn;
    int  resume;
} LobbyRace;

// Told on Start, on every console, before it goes on to car select; and
// on a console back in a race (`resume`), the lobby still up.
typedef void (*LobbyStartFn)(const LobbyRace* race);
void lobby_on_start(LobbyStartFn fn);

// Told 1 as the host goes to set the race up, after Host and the mode,
// and 0 when the lobby is back, set up or not: while it is 1, the setup
// screens are for Local Wireless (bsetup.h's wirelessPlayers).
typedef void (*LobbySetupFn)(int on);
void lobby_on_setup(LobbySetupFn fn);

// When the lobby is next come back to, the line `id` with `name` for
// $NAME (Latin-1, as lobby_latin1 makes it) and OK, before the question:
// the race lost a console on the way to it.
void lobby_notice_next(int32_t id, const char* name);

// When the lobby is next come back to, it is from the race with the link
// up (netrace_end): the host's list or a client's wait, as before Start.
void lobby_back_next(void);

// A console back in a race (37g-3) that could not take its setup: the
// line `id` with `name` (Latin-1), OK, the question, the link down. Only
// while the lobby waits on that race.
void lobby_resume_failed(BGameFlow* gf, int32_t id, const char* name);

// The ScreenCallback, for kScreens[]: LOBBY_SCREEN_NAME's.
void lobby_callback(BGameFlow* gf, BScreenMessage msg,
                    BScreenCallbackData* data);

// A console's UTF-8 name as the frontend's fonts take it: Latin-1, with
// '?' for what Latin-1 has not and for '@', the popups' line break.
void lobby_latin1(char* out, size_t cap, const char* utf8);

#endif
