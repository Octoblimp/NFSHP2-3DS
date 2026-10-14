// wireless -- the local wireless link over UDS, the port's (TASKS 37a).
//
// Two consoles, each with its own card, race each other over the 3DS's
// local wireless (TASKS 37, "The design"). One hosts a UDS network of two
// nodes; the other scans for it and joins. Every packet then goes through
// one wlproto link (wlproto.h) between the two, so what the race reads is
// already in order, once, and checked. This file is only the glue: UDS up
// and down, the network made, found, joined and left, each packet pulled
// into the link and the link's packets sent to the other console's node.
//
// The host's beacon carries a few bytes of its own (WIRELESS_APPDATA_MAX)
// after the port's tag and wlproto's version, so a scan lists only hosts
// of this port that speak the same protocol, and the lobby can say what
// each one is hosting.
//
// Everything runs on the caller's thread: wireless_pump once a frame
// pulls what came, ticks the link (which sends) and reads the network's
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
#define WIRELESS_MAX_HOSTS    8
#define WIRELESS_APPDATA_MAX  64
#define WIRELESS_NAME_MAX     32            // a console's name, UTF-8

typedef enum WirelessState {
    WIRELESS_OFF,          // UDS not up
    WIRELESS_IDLE,         // up, on no network
    WIRELESS_HOSTING,      // a network made, no one joined yet
    WIRELESS_CONNECTED,    // the other console is on the network
    WIRELESS_LOST          // it was, and has left or gone quiet
} WirelessState;

typedef struct WirelessHost {
    char     name[WIRELESS_NAME_MAX];       // the host console's user name
    uint8_t  appdata[WIRELESS_APPDATA_MAX]; // what the host said it hosts
    size_t   appdataSize;
    int      scanIndex;                     // for wireless_join
} WirelessHost;

typedef void (*WirelessLogFn)(const char *fmt, ...);

// UDS up: 1, or 0 when there is no local wireless (the switch off, or no
// nwm::UDS), which `log` is told.
int  wireless_start(WirelessLogFn log, uint32_t nowMs);
void wireless_stop(void);

// A network for one other console, its beacon carrying `appdata`.
int  wireless_host(const void *appdata, size_t n);

// The hosts in range, up to `max`: how many, or -1 when the scan failed.
// The list stays good until the next scan.
int  wireless_scan(WirelessHost *out, int max);

// Joins the host the last scan listed as out[i] (its scanIndex).
int  wireless_join(int scanIndex);

// Off the network, as host or as client.
void wireless_leave(void);

// Once a frame: the packets that came into the link, the link's tick at
// `nowMs`, and the network's status.
void wireless_pump(uint32_t nowMs);

WirelessState wireless_state(void);
int           wireless_is_host(void);

// The link to the other console, for wl_link_send and wl_link_recv while
// CONNECTED; NULL with no one to talk to.
WlLink       *wireless_link(void);

// What went wrong at the UDS level, for the log.
typedef struct WirelessStats {
    uint32_t sendErrors;     // udsSendTo failed (not the ignorable one)
    uint32_t pullErrors;
    uint32_t strays;         // packets from a node that is not the peer
    uint32_t statusChanges;
    uint16_t peer;           // the other console's node, 0 for none
    uint16_t self;           // this console's
} WirelessStats;

void wireless_stats(WirelessStats *out);

#endif
