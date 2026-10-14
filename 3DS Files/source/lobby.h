// lobby -- the Local Wireless lobby, the port's (TASKS 37b).
//
// Retail's second player has a pad on the same PS2. The port's has a 3DS
// of their own (TASKS 37), so where a mode screen's two players go to the
// two-pad car select, the port's go here first. The lobby is a screen of
// popups, tPopupMenu's (bpopup.h) on the memory card's popup screen, over
// whatever the frontend shows behind it:
//
//   - "Host a race, or join one?" Host or Join; BACK leaves the lobby.
//   - The host: UDS up and a network made, then the names of the consoles
//     on it, this one first. Start shows once one has joined, and closes
//     the network; BACK takes it down.
//   - A joiner: a scan each LOBBY_SCAN_MS until a race is found, then
//     that race, its host's name and how many are on it: Join, or Next
//     for the next one found (a new scan once the list has been seen).
//     Once joined, the host's name until the host starts; BACK leaves.
//   - The link lost, local wireless off or a join refused: the line, OK,
//     and back to the question.
//
// Start goes to every client as LOBBY_MSG_START, and every console then
// goes on to "Select Car", the lobby pushed under it. Coming back to the
// lobby takes the network down. What the race needs over the link (the
// cars, the race's parameters, a barrier) is netrace.c's (37c), which the
// lobby tells what Start settled.
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

// The lobby's place in the screen table, and where a select of two
// players goes on the 3DS (bsetup.c).
#define LOBBY_SCREEN_NAME "Local Wireless"
#define LOBBY_NEXT_SCREEN "Select Car"

#define LOBBY_SCAN_MS 1000

// The lobby's reliable messages. 37c's come after.
enum {
    LOBBY_MSG_START = 0x10,     // the host's: the race is on
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
} LobbyNet;

// What the lobby says it did, for the log and the check.
typedef void (*LobbyLogFn)(const char* line);

void lobby_init(const LobbyNet* net, LobbyLogFn log);

// What Start settled. Each console still on has a place, the host's 0
// and the clients' 1 on in the order they came; `peer` is each place's
// peer for the link (the host's own -1, and on a client only the host's,
// 0, is known) and -1 past `consoles`.
typedef struct LobbyRace {
    int  consoles;
    int  place;
    int  peer[WIRELESS_MAX_CONSOLES];
    char hostName[WIRELESS_NAME_MAX];    // Latin-1; on the host its own
} LobbyRace;

// Told on Start, on every console, before it goes on to car select.
typedef void (*LobbyStartFn)(const LobbyRace* race);
void lobby_on_start(LobbyStartFn fn);

// When the lobby is next come back to, the line `id` with `name` for
// $NAME (Latin-1, as lobby_latin1 makes it) and OK, before the question:
// the race lost a console on the way to it.
void lobby_notice_next(int32_t id, const char* name);

// The ScreenCallback, for kScreens[]: LOBBY_SCREEN_NAME's.
void lobby_callback(BGameFlow* gf, BScreenMessage msg,
                    BScreenCallbackData* data);

// A console's UTF-8 name as the frontend's fonts take it: Latin-1, with
// '?' for what Latin-1 has not and for '@', the popups' line break.
void lobby_latin1(char* out, size_t cap, const char* utf8);

#endif
