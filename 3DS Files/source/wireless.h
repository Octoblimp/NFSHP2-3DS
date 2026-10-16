// wireless -- the local wireless link over UDS, the port's (TASKS 37a).
//
// Up to eight consoles, each with its own card, race each other over the
// 3DS's local wireless (TASKS 37, "The design"): a race has eight cars,
// and the user asked for the grid's worth (2026-10-14). One console hosts
// a UDS network of up to WIRELESS_MAX_CONSOLES nodes; the others scan for
// it and join. The network is a star: each client talks to the host
// alone, over one wlproto link (wlproto.h), and the host keeps one link
// for each client, so what the race reads is already in order, once,
// and checked. This file is only the glue: UDS up and down, the network
// made, found, joined and left, each packet pulled into its sender's
// link and each link's packets sent to its console's node.
//
// The host's network takes clients until wireless_set_open(0) closes it
// (the lobby's start), or until it is full. A client that leaves, or
// goes quiet, keeps its place in the host's list with `alive` 0, so the
// race can tell who went; wireless_forget_lost clears those places.
// While a race holds for one (37g-2, wireless_set_rejoin), it may come
// back into its place: a client that lost its host finds it again by its
// address (wireless_rejoin) and joins it anew.
//
// The host's beacon carries a few bytes of its own (WIRELESS_APPDATA_MAX)
// after the port's tag and wlproto's version, so a scan lists only hosts
// of this port that speak the same protocol, and the lobby can say what
// each one is hosting.
//
// Everything runs on the caller's thread: wireless_pump once a frame
// pulls what came, ticks the links (which send) and reads the network's
// status. wireless_scan blocks while the radio listens for beacons.
//
// docs/formats/wireless.md has the beacon's and the packet's layout.

#ifndef WIRELESS_H
#define WIRELESS_H

#include <stddef.h>
#include <stdint.h>

#include "wlproto.h"

#define WIRELESS_COMM_ID      0x4e485032u   // "NHP2": the port's networks
#define WIRELESS_ID8          0x01u
#define WIRELESS_CHANNEL      1             // UDS's data channel
#define WIRELESS_MAX_CONSOLES 8             // a race's eight cars
#define WIRELESS_MAX_PEERS    (WIRELESS_MAX_CONSOLES - 1)
#define WIRELESS_MAX_HOSTS    8
#define WIRELESS_APPDATA_MAX  64
#define WIRELESS_NAME_MAX     32            // a console's name, UTF-8

typedef enum WirelessState {
    WIRELESS_OFF,          // UDS not up
    WIRELESS_IDLE,         // up, on no network
    WIRELESS_HOSTING,      // a network made; its clients are the peers
    WIRELESS_CONNECTED,    // on a host's network, the host the one peer
    WIRELESS_LOST          // a client whose host left or went quiet
} WirelessState;

typedef struct WirelessHost {
    char     name[WIRELESS_NAME_MAX];       // the host console's user name
    uint8_t  appdata[WIRELESS_APPDATA_MAX]; // what the host said it hosts
    size_t   appdataSize;
    int      consoles;                      // on its network now
    int      maxConsoles;
    int      scanIndex;                     // for wireless_join
} WirelessHost;

typedef void (*WirelessLogFn)(const char *fmt, ...);

// UDS up: 1, or 0 when there is no local wireless (the switch off, or no
// nwm::UDS), which `log` is told.
int  wireless_start(WirelessLogFn log, uint32_t nowMs);
void wireless_stop(void);

// Whether the console's wireless communication is turned off (the HOME
// Menu's setting, or an Old 3DS's switch): the shared page's
// NETWORK_STATE, 7 then (3dbrew, "Configuration Memory"). Read at any
// time, UDS up or not. Azahar's is always 2, Internet.
int  wireless_radio_off(void);

// A network for up to `consoles` consoles (this one among them, 2 to
// WIRELESS_MAX_CONSOLES), its beacon carrying `appdata`. It is open.
int  wireless_host(int consoles, const void *appdata, size_t n);

// The host lets more clients in (1) or no more (0).
void wireless_set_open(int open);

// The host's, in a race (37g-2): while on, a console whose link was lost
// may come back into its old place, its user name the same (and its
// friend code seed, when both have one), with a new link, if `ok` says
// the race still holds for that peer; any other that comes is sent away,
// as once closed. Off, no one comes in.
typedef int (*WirelessRejoinFn)(int peer);
void wireless_set_rejoin(int on, WirelessRejoinFn ok);

// A client's whose host was lost (WIRELESS_LOST), in a race (37g-2): off
// the old network, the host found again by its address and joined anew,
// the one peer as before: 1 when joined. Blocks while it scans.
int  wireless_rejoin(void);

// For the Azahar runs (WirelessTestDropFrame, 37g-2): from now for `ms`,
// this console hears nothing and sends nothing, as one out of range,
// so each end of each link finds it lost; and no rejoin until then.
void wireless_test_deaf(uint32_t ms);

// The hosts in range, up to `max`: how many, or -1 when the scan failed.
// Full ones are left out. The list stays good until the next scan.
int  wireless_scan(WirelessHost *out, int max);

// Joins the host the last scan listed as out[i] (its scanIndex).
int  wireless_join(int scanIndex);

// Off the network, as host or as client.
void wireless_leave(void);

// Once a frame: the packets that came into the links, the links' ticks
// at `nowMs`, and the network's status.
void wireless_pump(uint32_t nowMs);

WirelessState wireless_state(void);
int           wireless_is_host(void);

// The peers: a client's one is the host; the host's are its clients, in
// the order they came. A place stays when its console goes (alive 0).
int           wireless_peer_count(void);
int           wireless_peer_alive(int i);
uint16_t      wireless_peer_node(int i);
const char   *wireless_peer_name(int i);

// The link to peer i, for wl_link_send and wl_link_recv; NULL once it
// has gone, or with no such peer.
WlLink       *wireless_peer_link(int i);

// The host's: client i sent off the network, its place kept as one
// lost's: a console the race gave up on as it loaded again (37g-3).
void          wireless_drop(int i);

// The host's: the places of the consoles that went, cleared.
void          wireless_forget_lost(void);

// How long a peer may be silent before its link is lost, for every link
// now and to come, until wireless_start: 0 is wlproto's WL_TIMEOUT_MS.
// The race's setup asks for longer while the consoles load (netrace.c).
void          wireless_set_patience(uint32_t ms);
// Peer i's link's alone (37g-3), until the next wireless_set_patience or
// the link's take-back; 0 the link's own.
void          wireless_set_peer_patience(int i, uint32_t ms);

// This console's user name as the network has it (UTF-8), or "" when on
// no network.
const char   *wireless_self_name(void);

// What went wrong at the UDS level, for the log.
typedef struct WirelessStats {
    uint32_t sendErrors;     // udsSendTo failed (not the ignorable one)
    uint32_t pullErrors;
    uint32_t strays;         // packets from a node that is not a peer
    uint32_t statusChanges;
    uint16_t self;           // this console's node
    uint16_t nodes;          // on the network, this one among them
} WirelessStats;

void wireless_stats(WirelessStats *out);

#endif
