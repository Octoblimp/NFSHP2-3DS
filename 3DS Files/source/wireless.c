// wireless -- the local wireless link over UDS: see wireless.h.

#include "wireless.h"

#include <3ds.h>
#include <stdlib.h>
#include <string.h>

#define SHAREDMEM      0x3000     // udsInit's, 0x1000-aligned
#define SCAN_BUF       0x4000
#define STATUS_POLL_MS 250        // the status read even with no event
#define JOIN_QUIET_MS  (2 * WL_TIMEOUT_MS)   // joined, and nothing heard
#define PULLS_A_PUMP   128        // seven clients' packets and more

// The beacon's appdata: the tag, wlproto's version, the length of the
// caller's bytes, then those.
static const uint8_t kTag[4] = { 'N', 'H', 'P', '2' };
#define APPDATA_HEAD 6

// Every network of the port's has this one: the beacon's comm ID and the
// tag already keep other games out.
static const char kPassphrase[] = "NFSHP2-3DS local race";

typedef struct Peer {
    uint16_t node;
    int      alive;
    char     name[WIRELESS_NAME_MAX];
    uint32_t joinedAt;
    WlLink   link;
} Peer;

static struct {
    WirelessLogFn       log;
    int                 up;
    int                 network;      // made or joined
    int                 host;
    int                 open;         // the host's: lets clients in
    udsBindContext      bind;
    WirelessState       state;
    uint16_t            self;
    uint16_t            goneMask;     // the host's: nodes let go, still on
    Peer                peers[WIRELESS_MAX_PEERS];
    int                 numPeers;     // places taken, in the order they came
    uint32_t            now;
    uint32_t            statusAt;
    udsNetworkScanInfo *scan;
    size_t              numScan;
    WirelessStats       stats;
} W;

static uint8_t s_in[UDS_DATAFRAME_MAXSIZE];

#define LOG(...) do { if (W.log) W.log(__VA_ARGS__); } while (0)

// Each link's ctx is its console's node.
static void send_packet(void *ctx, const uint8_t *buf, size_t n)
{
    uint16_t node = (uint16_t)(uintptr_t)ctx;
    Result   r;

    r = udsSendTo(node, WIRELESS_CHANNEL, UDS_SENDFLAG_Default, buf, n);
    if (UDS_CHECK_SENDTO_FATALERROR(r)) {
        W.stats.sendErrors++;
        if (W.stats.sendErrors == 1 || W.stats.sendErrors % 300 == 0)
            LOG("wireless: udsSendTo %u: %08lx (%lu so far)", node,
                (unsigned long)r, (unsigned long)W.stats.sendErrors);
    }
}

static void free_scan(void)
{
    free(W.scan);
    W.scan    = NULL;
    W.numScan = 0;
}

static void clear_peers(void)
{
    memset(W.peers, 0, sizeof W.peers);
    W.numPeers = 0;
}

static Peer *add_peer(uint16_t node, const char *name)
{
    Peer *p = NULL;
    int   i;

    if (W.numPeers < WIRELESS_MAX_PEERS) {
        p = &W.peers[W.numPeers++];
    } else {
        // Every place taken: the first of a console that went.
        for (i = 0; i < W.numPeers && p == NULL; i++)
            if (!W.peers[i].alive)
                p = &W.peers[i];
        if (p == NULL)
            return NULL;
    }
    memset(p, 0, sizeof *p);
    p->node     = node;
    p->alive    = 1;
    p->joinedAt = W.now;
    if (name)
        memcpy(p->name, name, sizeof p->name - 1);
    wl_link_init(&p->link, send_packet, (void *)(uintptr_t)node, W.now);
    return p;
}

static Peer *alive_peer(uint16_t node)
{
    int i;

    for (i = 0; i < W.numPeers; i++)
        if (W.peers[i].alive && W.peers[i].node == node)
            return &W.peers[i];
    return NULL;
}

// The host sends a client that went quiet off the network, and takes
// no node it has let go for a new one until the status has it gone.
static void peer_lost(Peer *p, const char *why, int eject)
{
    p->alive = 0;
    if (W.host) {
        W.goneMask |= (uint16_t)(1u << (p->node - 1));
        if (eject)
            udsEjectClient(p->node);
        LOG("wireless: node %u (%s) %s", p->node, p->name, why);
    } else {
        W.state = WIRELESS_LOST;
        LOG("wireless: the host %s", why);
    }
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

int wireless_host(int consoles, const void *appdata, size_t n)
{
    udsNetworkStruct net;
    uint8_t          beacon[APPDATA_HEAD + WIRELESS_APPDATA_MAX];
    Result           r;

    if (!W.up || W.network || n > WIRELESS_APPDATA_MAX || consoles < 2
        || consoles > WIRELESS_MAX_CONSOLES)
        return 0;
    udsGenerateDefaultNetworkStruct(&net, WIRELESS_COMM_ID, WIRELESS_ID8,
                                    (u8)consoles);
    r = udsCreateNetwork(&net, kPassphrase, sizeof kPassphrase, &W.bind,
                         WIRELESS_CHANNEL, UDS_DEFAULT_RECVBUFSIZE);
    if (R_FAILED(r)) {
        LOG("wireless: udsCreateNetwork %08lx", (unsigned long)r);
        return 0;
    }
    W.network  = 1;
    W.host     = 1;
    W.open     = 1;
    W.self     = UDS_HOST_NETWORKNODEID;
    W.state    = WIRELESS_HOSTING;
    W.statusAt = W.now - STATUS_POLL_MS;
    clear_peers();
    memcpy(beacon, kTag, sizeof kTag);
    beacon[4] = WL_VERSION;
    beacon[5] = (uint8_t)n;
    if (n)
        memcpy(beacon + APPDATA_HEAD, appdata, n);
    r = udsSetApplicationData(beacon, APPDATA_HEAD + n);
    if (R_FAILED(r))
        LOG("wireless: udsSetApplicationData %08lx", (unsigned long)r);
    // No spectators: the race is its consoles' alone.
    udsEjectSpectator();
    LOG("wireless: hosting for %d", consoles);
    return 1;
}

void wireless_set_open(int open)
{
    Result r;

    if (!W.host || W.open == !!open)
        return;
    W.open = !!open;
    r = udsSetNewConnectionsBlocked(!W.open, true, false);
    LOG("wireless: %s (%08lx)", W.open ? "open" : "closed", (unsigned long)r);
}

int wireless_scan(WirelessHost *out, int max)
{
    static uint8_t buf[SCAN_BUF];
    static int     lastSeen = -1, lastCount, lastForeign, lastFull;
    size_t         i;
    int            count = 0, foreign = 0, full = 0;
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
            || beacon[4] != WL_VERSION || beacon[5] > got - APPDATA_HEAD) {
            foreign++;
            continue;
        }
        if (net->total_nodes >= net->max_nodes) {
            full++;
            continue;
        }
        memset(h, 0, sizeof *h);
        memset(name, 0, sizeof name);
        if (R_SUCCEEDED(udsGetNodeInfoUsername(&W.scan[i].nodes[0], name)))
            memcpy(h->name, name, sizeof h->name - 1);
        h->appdataSize = beacon[5];
        memcpy(h->appdata, beacon + APPDATA_HEAD, h->appdataSize);
        h->consoles    = net->total_nodes;
        h->maxConsoles = net->max_nodes;
        h->scanIndex   = (int)i;
        count++;
    }
    // What the scans see, each time it changes: a host the joiner never
    // takes shows here as not the port's, or full.
    if ((int)W.numScan != lastSeen || count != lastCount
        || foreign != lastForeign || full != lastFull) {
        lastSeen    = (int)W.numScan;
        lastCount   = count;
        lastForeign = foreign;
        lastFull    = full;
        LOG("wireless: scan sees %u network(s): %d to join, %d not the "
            "port's, %d full", (unsigned)W.numScan, count, foreign, full);
    }
    return count;
}

int wireless_join(int scanIndex)
{
    char   name[WIRELESS_NAME_MAX];
    Result r;

    if (!W.up || W.network || scanIndex < 0
        || (size_t)scanIndex >= W.numScan)
        return 0;
    memset(name, 0, sizeof name);
    (void)udsGetNodeInfoUsername(&W.scan[scanIndex].nodes[0], name);
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
    W.state    = WIRELESS_CONNECTED;
    W.statusAt = W.now - STATUS_POLL_MS;
    clear_peers();
    add_peer(UDS_HOST_NETWORKNODEID, name);
    free_scan();
    LOG("wireless: joined \"%s\"", name);
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
    W.open    = 0;
    W.self    = 0;
    W.goneMask = 0;
    clear_peers();
    W.state   = W.up ? WIRELESS_IDLE : WIRELESS_OFF;
    LOG("wireless: left");
}

// A client new to the host's network: a place with a link, while it is
// open; once it is closed, out again.
static void client_came(uint16_t node)
{
    udsNodeInfo info;
    char        name[WIRELESS_NAME_MAX];

    if (!W.open) {
        W.goneMask |= (uint16_t)(1u << (node - 1));
        udsEjectClient(node);
        LOG("wireless: node %u came after closing, sent away", node);
        return;
    }
    memset(name, 0, sizeof name);
    if (R_SUCCEEDED(udsGetNodeInformation(node, &info)))
        (void)udsGetNodeInfoUsername(&info, name);
    if (add_peer(node, name) == NULL) {
        W.goneMask |= (uint16_t)(1u << (node - 1));
        udsEjectClient(node);
        LOG("wireless: node %u came with no place for it", node);
        return;
    }
    LOG("wireless: node %u (%s) joined", node, name);
}

// Who is on the network: the host gives each client that comes a place
// and marks each that goes; a client marks the link lost when the host's
// node goes.
static void read_status(void)
{
    udsConnectionStatus st;
    int                 event = udsWaitConnectionStatusEvent(false, false);
    Result              r;
    int                 i;

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
    W.self        = st.cur_NetworkNodeID;
    W.stats.nodes = st.total_nodes;
    if (W.host) {
        uint16_t node;

        for (i = 0; i < W.numPeers; i++) {
            Peer *p = &W.peers[i];

            if (p->alive && !(st.node_bitmask & (1u << (p->node - 1))))
                peer_lost(p, "left", 0);
        }
        W.goneMask &= st.node_bitmask;
        for (node = 2; node <= UDS_MAXNODES; node++) {
            uint16_t bit = (uint16_t)(1u << (node - 1));

            if ((st.node_bitmask & bit) && !(W.goneMask & bit)
                && !alive_peer(node))
                client_came(node);
        }
    } else if (W.state == WIRELESS_CONNECTED && !(st.node_bitmask & 1u)) {
        peer_lost(&W.peers[0], "left", 0);
    }
}

void wireless_pump(uint32_t nowMs)
{
    int i;

    W.now = nowMs;
    if (!W.network)
        return;
    read_status();
    // What came, each packet to its sender's link; anything from a node
    // with none, or one that has gone, is let go.
    for (i = 0; i < PULLS_A_PUMP; i++) {
        size_t   got = 0;
        uint16_t src = 0;
        Peer    *p;
        Result   r = udsPullPacket(&W.bind, s_in, sizeof s_in, &got, &src);

        if (R_FAILED(r)) {
            if (W.stats.pullErrors++ == 0)
                LOG("wireless: udsPullPacket %08lx", (unsigned long)r);
            break;
        }
        if (got == 0)
            break;
        p = alive_peer(src);
        if (p == NULL) {
            W.stats.strays++;
            continue;
        }
        wl_link_packet_in(&p->link, s_in, got);
    }
    for (i = 0; i < W.numPeers; i++) {
        Peer *p = &W.peers[i];

        if (!p->alive)
            continue;
        wl_link_tick(&p->link, nowMs);
        if (p->link.heard ? !wl_link_alive(&p->link)
                          : (int32_t)(nowMs - p->joinedAt) >= JOIN_QUIET_MS)
            peer_lost(p, p->link.heard ? "timed out" : "was never heard",
                      1);
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

int wireless_peer_count(void)
{
    return W.numPeers;
}

int wireless_peer_alive(int i)
{
    return i >= 0 && i < W.numPeers && W.peers[i].alive;
}

uint16_t wireless_peer_node(int i)
{
    return i >= 0 && i < W.numPeers ? W.peers[i].node : 0;
}

const char *wireless_peer_name(int i)
{
    return i >= 0 && i < W.numPeers ? W.peers[i].name : "";
}

WlLink *wireless_peer_link(int i)
{
    return wireless_peer_alive(i) ? &W.peers[i].link : NULL;
}

void wireless_forget_lost(void)
{
    int i, j = 0;

    if (!W.host)
        return;
    for (i = 0; i < W.numPeers; i++)
        if (W.peers[i].alive) {
            if (j != i)
                W.peers[j] = W.peers[i];
            j++;
        }
    W.numPeers = j;
    memset(&W.peers[j], 0, sizeof W.peers[0] * (size_t)(WIRELESS_MAX_PEERS - j));
}

void wireless_stats(WirelessStats *out)
{
    *out = W.stats;
    out->self = W.self;
}
