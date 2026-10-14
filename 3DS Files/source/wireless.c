// wireless -- the local wireless link over UDS: see wireless.h.

#include "wireless.h"

#include <3ds.h>
#include <stdlib.h>
#include <string.h>

#define SHAREDMEM      0x3000     // udsInit's, 0x1000-aligned
#define SCAN_BUF       0x4000
#define STATUS_POLL_MS 250        // the status read even with no event
#define JOIN_QUIET_MS  (2 * WL_TIMEOUT_MS)   // joined, and nothing heard

// The beacon's appdata: the tag, wlproto's version, the length of the
// caller's bytes, then those.
static const uint8_t kTag[4] = { 'N', 'H', 'P', '2' };
#define APPDATA_HEAD 6

// Every network of the port's has this one: the beacon's comm ID and the
// tag already keep other games out.
static const char kPassphrase[] = "NFSHP2-3DS local race";

static struct {
    WirelessLogFn       log;
    int                 up;
    int                 network;      // made or joined
    int                 host;
    udsBindContext      bind;
    WirelessState       state;
    uint16_t            peer;
    uint16_t            self;
    WlLink              link;
    uint32_t            now;
    uint32_t            joinedAt;
    uint32_t            statusAt;
    udsNetworkScanInfo *scan;
    size_t              numScan;
    WirelessStats       stats;
} W;

static uint8_t s_in[UDS_DATAFRAME_MAXSIZE];

#define LOG(...) do { if (W.log) W.log(__VA_ARGS__); } while (0)

static void send_packet(void *ctx, const uint8_t *buf, size_t n)
{
    Result r;

    (void)ctx;
    if (!W.peer)
        return;
    r = udsSendTo(W.peer, WIRELESS_CHANNEL, UDS_SENDFLAG_Default, buf, n);
    if (UDS_CHECK_SENDTO_FATALERROR(r)) {
        W.stats.sendErrors++;
        if (W.stats.sendErrors == 1 || W.stats.sendErrors % 300 == 0)
            LOG("wireless: udsSendTo %08lx (%lu so far)", (unsigned long)r,
                (unsigned long)W.stats.sendErrors);
    }
}

static void free_scan(void)
{
    free(W.scan);
    W.scan    = NULL;
    W.numScan = 0;
}

static void connect_link(uint16_t peer)
{
    W.peer     = peer;
    W.joinedAt = W.now;
    W.state    = WIRELESS_CONNECTED;
    wl_link_init(&W.link, send_packet, NULL, W.now);
}

int wireless_start(WirelessLogFn log, uint32_t nowMs)
{
    Result r;

    if (W.up)
        return 1;
    memset(&W, 0, sizeof W);
    W.log = log;
    W.now = nowMs;
    r = udsInit(SHAREDMEM, NULL);
    if (R_FAILED(r)) {
        LOG("wireless: udsInit %08lx -- no local wireless", (unsigned long)r);
        W.state = WIRELESS_OFF;
        return 0;
    }
    W.up    = 1;
    W.state = WIRELESS_IDLE;
    LOG("wireless: up");
    return 1;
}

void wireless_stop(void)
{
    if (!W.up)
        return;
    wireless_leave();
    free_scan();
    udsExit();
    W.up    = 0;
    W.state = WIRELESS_OFF;
    LOG("wireless: down");
}

int wireless_host(const void *appdata, size_t n)
{
    udsNetworkStruct net;
    uint8_t          beacon[APPDATA_HEAD + WIRELESS_APPDATA_MAX];
    Result           r;

    if (!W.up || W.network || n > WIRELESS_APPDATA_MAX)
        return 0;
    udsGenerateDefaultNetworkStruct(&net, WIRELESS_COMM_ID, WIRELESS_ID8, 2);
    r = udsCreateNetwork(&net, kPassphrase, sizeof kPassphrase, &W.bind,
                         WIRELESS_CHANNEL, UDS_DEFAULT_RECVBUFSIZE);
    if (R_FAILED(r)) {
        LOG("wireless: udsCreateNetwork %08lx", (unsigned long)r);
        return 0;
    }
    W.network = 1;
    W.host    = 1;
    W.peer    = 0;
    W.self    = UDS_HOST_NETWORKNODEID;
    W.state   = WIRELESS_HOSTING;
    W.statusAt = W.now - STATUS_POLL_MS;
    memcpy(beacon, kTag, sizeof kTag);
    beacon[4] = WL_VERSION;
    beacon[5] = (uint8_t)n;
    if (n)
        memcpy(beacon + APPDATA_HEAD, appdata, n);
    r = udsSetApplicationData(beacon, APPDATA_HEAD + n);
    if (R_FAILED(r))
        LOG("wireless: udsSetApplicationData %08lx", (unsigned long)r);
    // No spectators: the race is two consoles' alone.
    udsEjectSpectator();
    LOG("wireless: hosting");
    return 1;
}

int wireless_scan(WirelessHost *out, int max)
{
    static uint8_t buf[SCAN_BUF];
    size_t         i;
    int            count = 0;
    Result         r;

    if (!W.up)
        return -1;
    free_scan();
    r = udsScanBeacons(buf, sizeof buf, &W.scan, &W.numScan,
                       WIRELESS_COMM_ID, WIRELESS_ID8, NULL,
                       W.network ? true : false);
    if (R_FAILED(r)) {
        LOG("wireless: udsScanBeacons %08lx", (unsigned long)r);
        free_scan();
        return -1;
    }
    for (i = 0; i < W.numScan && count < max; i++) {
        const udsNetworkStruct *net = &W.scan[i].network;
        uint8_t       beacon[APPDATA_HEAD + WIRELESS_APPDATA_MAX];
        size_t        got = 0;
        WirelessHost *h = &out[count];
        char          name[WIRELESS_NAME_MAX];

        r = udsGetNetworkStructApplicationData(net, beacon, sizeof beacon,
                                               &got);
        if (R_FAILED(r) || got < APPDATA_HEAD
            || memcmp(beacon, kTag, sizeof kTag) != 0
            || beacon[4] != WL_VERSION || beacon[5] > got - APPDATA_HEAD)
            continue;
        if (net->total_nodes >= net->max_nodes)
            continue;
        memset(h, 0, sizeof *h);
        memset(name, 0, sizeof name);
        if (R_SUCCEEDED(udsGetNodeInfoUsername(&W.scan[i].nodes[0], name)))
            memcpy(h->name, name, sizeof h->name - 1);
        h->appdataSize = beacon[5];
        memcpy(h->appdata, beacon + APPDATA_HEAD, h->appdataSize);
        h->scanIndex = (int)i;
        count++;
    }
    return count;
}

int wireless_join(int scanIndex)
{
    Result r;

    if (!W.up || W.network || scanIndex < 0
        || (size_t)scanIndex >= W.numScan)
        return 0;
    r = udsConnectNetwork(&W.scan[scanIndex].network, kPassphrase,
                          sizeof kPassphrase, &W.bind,
                          UDS_BROADCAST_NETWORKNODEID, UDSCONTYPE_Client,
                          WIRELESS_CHANNEL, UDS_DEFAULT_RECVBUFSIZE);
    if (R_FAILED(r)) {
        LOG("wireless: udsConnectNetwork %08lx", (unsigned long)r);
        return 0;
    }
    W.network  = 1;
    W.host     = 0;
    W.statusAt = W.now - STATUS_POLL_MS;
    connect_link(UDS_HOST_NETWORKNODEID);
    free_scan();
    LOG("wireless: joined");
    return 1;
}

void wireless_leave(void)
{
    if (!W.network)
        return;
    if (W.host)
        udsDestroyNetwork();
    else
        udsDisconnectNetwork();
    udsUnbind(&W.bind);
    W.network = 0;
    W.host    = 0;
    W.peer    = 0;
    W.self    = 0;
    W.state   = W.up ? WIRELESS_IDLE : WIRELESS_OFF;
    LOG("wireless: left");
}

// Who is on the network: the host takes the first client as its peer and
// then lets no one else in; either side marks the link lost when the
// other's node goes.
static void read_status(void)
{
    udsConnectionStatus st;
    int                 event = udsWaitConnectionStatusEvent(false, false);
    Result              r;

    if (!event && (int32_t)(W.now - W.statusAt) < STATUS_POLL_MS)
        return;
    W.statusAt = W.now;
    r = udsGetConnectionStatus(&st);
    if (R_FAILED(r))
        return;
    if (event) {
        W.stats.statusChanges++;
        LOG("wireless: status %lx, node %u, %u of %u nodes, mask %04x",
            (unsigned long)st.status, st.cur_NetworkNodeID, st.total_nodes,
            st.max_nodes, st.node_bitmask);
    }
    W.self = st.cur_NetworkNodeID;
    if (W.host) {
        uint16_t others = (uint16_t)(st.node_bitmask & ~1u);

        if (W.state == WIRELESS_HOSTING && others) {
            uint16_t node = 2;

            while (!(others & (1u << (node - 1))))
                node++;
            udsSetNewConnectionsBlocked(true, true, false);
            connect_link(node);
            LOG("wireless: node %u joined", node);
        } else if (W.state == WIRELESS_CONNECTED
                   && !(st.node_bitmask & (1u << (W.peer - 1)))) {
            W.state = WIRELESS_LOST;
            LOG("wireless: node %u left", W.peer);
        }
    } else if (W.state == WIRELESS_CONNECTED && !(st.node_bitmask & 1u)) {
        W.state = WIRELESS_LOST;
        LOG("wireless: the host left");
    }
}

void wireless_pump(uint32_t nowMs)
{
    int i;

    W.now = nowMs;
    if (!W.network)
        return;
    read_status();
    // What came, from the peer alone; anything before there is one, or
    // after it is lost, is let go.
    for (i = 0; i < 64; i++) {
        size_t   got = 0;
        uint16_t src = 0;
        Result   r = udsPullPacket(&W.bind, s_in, sizeof s_in, &got, &src);

        if (R_FAILED(r)) {
            if (W.stats.pullErrors++ == 0)
                LOG("wireless: udsPullPacket %08lx", (unsigned long)r);
            break;
        }
        if (got == 0)
            break;
        if (W.state != WIRELESS_CONNECTED || src != W.peer) {
            W.stats.strays++;
            continue;
        }
        wl_link_packet_in(&W.link, s_in, got);
    }
    if (W.state != WIRELESS_CONNECTED)
        return;
    wl_link_tick(&W.link, nowMs);
    if (W.link.heard ? !wl_link_alive(&W.link)
                     : (int32_t)(nowMs - W.joinedAt) >= JOIN_QUIET_MS) {
        W.state = WIRELESS_LOST;
        LOG("wireless: the link went quiet (%s)",
            W.link.heard ? "timed out" : "never heard");
    }
}

WirelessState wireless_state(void)
{
    return W.state;
}

int wireless_is_host(void)
{
    return W.host;
}

WlLink *wireless_link(void)
{
    return W.state == WIRELESS_CONNECTED ? &W.link : NULL;
}

void wireless_stats(WirelessStats *out)
{
    *out = W.stats;
    out->peer = W.peer;
    out->self = W.self;
}
