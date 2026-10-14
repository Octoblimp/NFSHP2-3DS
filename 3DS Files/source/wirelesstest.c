// wirelesstest -- TASKS 37a's link soak: see wirelesstest.h.

#include "wirelesstest.h"

#include <3ds.h>
#include <stdio.h>
#include <string.h>

#define TICK_MS   33         // the race's 30 a second
#define SCAN_MS   2000
#define LINGER_MS 1500       // after the end: the last acks go out
#define FRAME_LEN 24

enum { T_REL = 1, T_FRAME = 2, T_END = 3 };

// One link's soak, a peer's: the host keeps one for each client.
typedef struct Soak {
    int      me, them;                 // 1 sent by the host, 2 by a client
    uint16_t node;                     // the peer's, 0 before it came
    uint32_t relSent, frameSent;
    uint32_t relGot, frameGot, frameRepeats, frameBack, frameGap;
    uint32_t lastFrame;
    int      anyFrame;
    uint8_t  seen[1 << 13];            // the frames had, a bit each
    uint32_t faults;
    int      endSent, endGot;
    uint32_t theirTotal;
    uint32_t rng;
    uint32_t connectedAt, doneAt;
    int      finished;                 // lingered after the end
    int      lost;                     // its console went before that
} Soak;

static Soak s_soak[WIRELESS_MAX_PEERS];

static uint32_t hash3(uint32_t a, uint32_t b, uint32_t c)
{
    uint32_t h = a * 0x9e3779b1u ^ b * 0x85ebca77u ^ c * 0xc2b2ae3du;

    h ^= h >> 15;
    h *= 0x2c1b3c6du;
    h ^= h >> 12;
    h *= 0x297a2d39u;
    h ^= h >> 15;
    return h;
}

static uint32_t rnd(Soak *s)
{
    s->rng ^= s->rng << 13;
    s->rng ^= s->rng >> 17;
    s->rng ^= s->rng << 5;
    return s->rng;
}

static int rel_len(int id, uint32_t i)
{
    return (int)(hash3((uint32_t)id, i, 0x11u) % 201u);
}

static void rel_bytes(int id, uint32_t i, uint8_t *out, int len)
{
    int j;

    for (j = 0; j < len; j++)
        out[j] = (uint8_t)hash3((uint32_t)id, i, 0x100u + (uint32_t)j);
}

static void frame_bytes(int id, uint32_t k, uint8_t *out)
{
    int j;

    memcpy(out, &k, 4);
    for (j = 4; j < FRAME_LEN; j++)
        out[j] = (uint8_t)hash3((uint32_t)id | 0x80u, k, 0x100u + (uint32_t)j);
}

static void fault(Soak *s, WirelessLogFn log, const char *what, uint32_t a)
{
    if (s->faults++ < 20 && log)
        log("wltest: FAULT node %u: %s (%lu)", s->node, what,
            (unsigned long)a);
}

static void read_all(Soak *s, WlLink *l, WirelessLogFn log)
{
    WlMsg   m;
    uint8_t want[WL_MSG_MAX];

    while (wl_link_recv(l, &m)) {
        if (m.type == T_REL) {
            int len = rel_len(s->them, s->relGot);

            rel_bytes(s->them, s->relGot, want, len);
            if (m.seq == WL_UNRELIABLE || m.len != len
                || memcmp(m.data, want, (size_t)len) != 0)
                fault(s, log, "reliable message out of order or changed",
                      s->relGot);
            if (s->endGot)
                fault(s, log, "reliable message after the end", s->relGot);
            s->relGot++;
        } else if (m.type == T_FRAME) {
            uint32_t k;

            if (m.seq != WL_UNRELIABLE || m.len != FRAME_LEN) {
                fault(s, log, "frame message malformed", m.len);
                continue;
            }
            memcpy(&k, m.data, 4);
            frame_bytes(s->them, k, want);
            if (memcmp(m.data, want, FRAME_LEN) != 0) {
                fault(s, log, "frame message changed", k);
                continue;
            }
            if (k < (uint32_t)sizeof s->seen * 8) {
                if (s->seen[k >> 3] & (1u << (k & 7)))
                    s->frameRepeats++;
                s->seen[k >> 3] |= (uint8_t)(1u << (k & 7));
            }
            if (s->anyFrame && k <= s->lastFrame)
                s->frameBack++;
            if (s->anyFrame && k > s->lastFrame + 1
                && k - s->lastFrame - 1 > s->frameGap)
                s->frameGap = k - s->lastFrame - 1;
            if (!s->anyFrame || k > s->lastFrame)
                s->lastFrame = k;
            s->anyFrame = 1;
            s->frameGot++;
        } else if (m.type == T_END) {
            if (m.seq == WL_UNRELIABLE || m.len != 4 || s->endGot) {
                fault(s, log, "end message malformed", m.len);
                continue;
            }
            memcpy(&s->theirTotal, m.data, 4);
            s->endGot = 1;
            if (s->theirTotal != s->relGot)
                fault(s, log, "reliable messages missing at the end",
                      s->theirTotal - s->relGot);
        } else {
            fault(s, log, "message of no type sent", m.type);
        }
    }
}

static void send_some(Soak *s, WlLink *l)
{
    uint8_t buf[WL_MSG_MAX];
    int     n = (int)(rnd(s) % 3u), i;

    for (i = 0; i < n; i++) {
        int len = rel_len(s->me, s->relSent);

        rel_bytes(s->me, s->relSent, buf, len);
        if (!wl_link_send(l, T_REL, buf, (size_t)len, 1))
            break;
        s->relSent++;
    }
    frame_bytes(s->me, s->frameSent, buf);
    if (wl_link_send(l, T_FRAME, buf, FRAME_LEN, 0))
        s->frameSent++;
}

// A peer's link this tick: what came, what goes, and its end.
static void soak_tick(Soak *s, int i, int seconds, uint32_t now,
                      uint32_t seed, WirelessLogFn log)
{
    WlLink *l = wireless_peer_link(i);

    if (s->finished || s->lost)
        return;
    if (s->connectedAt == 0) {
        if (l == NULL)
            return;
        memset(s, 0, sizeof *s);
        s->me          = wireless_is_host() ? 1 : 2;
        s->them        = 3 - s->me;
        s->node        = wireless_peer_node(i);
        s->rng         = (seed ^ (uint32_t)s->node * 0x9e3779b1u) | 1u;
        s->connectedAt = now;
        if (log)
            log("wltest: node %u (%s) connected", s->node,
                wireless_peer_name(i));
    }
    if (l == NULL) {
        // The other side may leave first once both are done.
        if (s->doneAt)
            s->finished = 1;
        else
            s->lost = 1;
        return;
    }
    read_all(s, l, log);
    if ((int32_t)(now - s->connectedAt) < seconds * 1000)
        send_some(s, l);
    else if (!s->endSent && wl_link_send(l, T_END, &s->relSent, 4, 1))
        s->endSent = 1;
    if (s->endSent && s->endGot && wl_link_unacked(l) == 0
        && s->doneAt == 0)
        s->doneAt = now;
    if (s->doneAt && (int32_t)(now - s->doneAt) >= LINGER_MS)
        s->finished = 1;
}

static const char *state_name(WirelessState st)
{
    switch (st) {
    case WIRELESS_OFF:       return "off";
    case WIRELESS_IDLE:      return "idle";
    case WIRELESS_HOSTING:   return "hosting";
    case WIRELESS_CONNECTED: return "connected";
    default:                 return "LOST";
    }
}

static const char *soak_state(const Soak *s)
{
    if (s->lost)
        return "lost";
    if (s->finished)
        return "done";
    if (s->doneAt)
        return "lingering";
    if (s->endSent)
        return "ending";
    return "sending";
}

static void show(int mode, int consoles, uint32_t secs, int scans,
                 const char *result)
{
    WirelessStats ws;
    int           i, n = wireless_peer_count();

    wireless_stats(&ws);
    printf("\x1b[1;1HNFSHP2-3DS wireless link test (TASKS 37a)\n");
    if (mode == 1)
        printf("host, for %d consoles                         \n", consoles);
    else
        printf("join                                          \n");
    printf("state: %-10s t %4lus  tries %d          \n",
           state_name(wireless_state()), (unsigned long)secs, scans);
    printf("node %u, %u on the network                    \n", ws.self,
           ws.nodes);
    printf("node name        reliable      frames    faults\n");
    for (i = 0; i < WIRELESS_MAX_PEERS; i++) {
        const Soak *s = &s_soak[i];

        if (i >= n || s->node == 0) {
            printf("%-50s\n%-50s\n", "", "");
            continue;
        }
        printf("%4u %-10.10s %6lu/%-6lu %6lu/%-6lu %lu   \n", s->node,
               wireless_peer_name(i), (unsigned long)s->relSent,
               (unsigned long)s->relGot, (unsigned long)s->frameSent,
               (unsigned long)s->frameGot, (unsigned long)s->faults);
        {
            WlLink *l = wireless_peer_link(i);

            printf("     %-9s resends %lu repeats %lu unacked %d  \n",
                   soak_state(s), (unsigned long)(l ? l->resends : 0),
                   (unsigned long)(l ? l->repeats : 0),
                   l ? wl_link_unacked(l) : 0);
        }
    }
    printf("uds errors: send %lu pull %lu strays %lu     \n",
           (unsigned long)ws.sendErrors, (unsigned long)ws.pullErrors,
           (unsigned long)ws.strays);
    printf("\n%-50s\n", result ? result : "");
    printf("START leaves.\n");
}

static void log_second(WirelessLogFn log, uint32_t secs)
{
    WirelessStats ws;
    int           i, n = wireless_peer_count();

    if (log == NULL)
        return;
    wireless_stats(&ws);
    if (n == 0)
        log("wltest: t %lu %s, %u on the network; uds send %lu pull %lu "
            "strays %lu", (unsigned long)secs, state_name(wireless_state()),
            ws.nodes, (unsigned long)ws.sendErrors,
            (unsigned long)ws.pullErrors, (unsigned long)ws.strays);
    for (i = 0; i < n; i++) {
        const Soak *s = &s_soak[i];
        WlLink     *l = wireless_peer_link(i);

        log("wltest: t %lu %s, node %u %s; reliable %lu/%lu, frames %lu/%lu "
            "(twice %lu, back %lu, gap %lu); faults %lu; link in %lu out %lu "
            "resends %lu repeats %lu malformed %lu dropped %lu unacked %d; "
            "uds send %lu pull %lu strays %lu",
            (unsigned long)secs, state_name(wireless_state()),
            wireless_peer_node(i), soak_state(s),
            (unsigned long)s->relSent, (unsigned long)s->relGot,
            (unsigned long)s->frameSent, (unsigned long)s->frameGot,
            (unsigned long)s->frameRepeats, (unsigned long)s->frameBack,
            (unsigned long)s->frameGap, (unsigned long)s->faults,
            (unsigned long)(l ? l->packetsIn : 0),
            (unsigned long)(l ? l->packetsOut : 0),
            (unsigned long)(l ? l->resends : 0),
            (unsigned long)(l ? l->repeats : 0),
            (unsigned long)(l ? l->malformed : 0),
            (unsigned long)(l ? l->dropped : 0), l ? wl_link_unacked(l) : 0,
            (unsigned long)ws.sendErrors, (unsigned long)ws.pullErrors,
            (unsigned long)ws.strays);
    }
}

int wirelesstest_run(int mode, int seconds, int consoles, WirelessLogFn log)
{
    WirelessHost  hosts[WIRELESS_MAX_HOSTS];
    uint32_t      start = (uint32_t)osGetTime(), lastTick = start;
    uint32_t      lastScan = start - SCAN_MS, lastSecond = start;
    int           scans = 0, rc = 2, i, together = 0;
    const char   *result = NULL;
    uint32_t      relSent = 0, relGot = 0, frameSent = 0, frameGot = 0;

    memset(s_soak, 0, sizeof s_soak);
    if (seconds <= 0)
        seconds = 120;
    if (consoles < 2 || consoles > WIRELESS_MAX_CONSOLES)
        consoles = 2;
    if (log)
        log("wltest: mode %d, %d s, %d consoles", mode, seconds, consoles);
    printf("\x1b[2J");
    while (aptMainLoop()) {
        uint32_t now;
        int      n, finished = 0, lost = 0;

        hidScanInput();
        if (hidKeysDown() & KEY_START)
            break;
        gspWaitForVBlank();
        now = (uint32_t)osGetTime();
        if ((int32_t)(now - lastTick) < TICK_MS)
            continue;
        lastTick = now;
        // UDS, the host's network and the join's scan, each again every
        // SCAN_MS until it takes: on Azahar they wait on the room.
        if (wireless_state() <= WIRELESS_IDLE
            && (int32_t)(now - lastScan) >= SCAN_MS) {
            lastScan = now;
            scans++;
            if (wireless_state() == WIRELESS_OFF) {
                wireless_start(log, now);
            } else if (mode == 1) {
                wireless_host(consoles, "SOAK", 4);
            } else {
                int found = wireless_scan(hosts, WIRELESS_MAX_HOSTS);

                lastScan = (uint32_t)osGetTime();
                if (found > 0) {
                    if (log)
                        log("wltest: %d host(s), joining \"%s\" (%d of %d)",
                            found, hosts[0].name, hosts[0].consoles,
                            hosts[0].maxConsoles);
                    wireless_join(hosts[0].scanIndex);
                }
            }
        }
        wireless_pump(now);
        n = wireless_peer_count();
        // A race needs every console on the network at once, so the soak
        // does too.
        {
            WirelessStats ws;

            wireless_stats(&ws);
            if (wireless_state() >= WIRELESS_HOSTING && ws.nodes >= consoles)
                together = 1;
        }
        // The host closes its network once all have come.
        if (mode == 1 && wireless_state() == WIRELESS_HOSTING) {
            int alive = 0;

            for (i = 0; i < n; i++)
                alive += wireless_peer_alive(i);
            if (alive == consoles - 1)
                wireless_set_open(0);
        }
        for (i = 0; i < n; i++) {
            soak_tick(&s_soak[i], i, seconds, now, start, log);
            finished += s_soak[i].finished;
            lost     += s_soak[i].lost;
        }
        if (result == NULL && lost) {
            result = "FAIL: a console was lost.";
            rc = 1;
        } else if (result == NULL
                   && finished == (mode == 1 ? consoles - 1 : 1)) {
            uint32_t faults = 0;

            for (i = 0; i < n; i++)
                faults += s_soak[i].faults;
            rc = faults || !together ? 1 : 0;
            result = faults    ? "FAIL: see the faults."
                     : !together ? "FAIL: never all on the network at once."
                     : "PASS";
        }
        if ((int32_t)(now - lastSecond) >= 1000 || result != NULL) {
            uint32_t secs = (now - start) / 1000u;

            lastSecond = now;
            show(mode, consoles, secs, scans, result);
            log_second(log, secs);
        }
        gfxFlushBuffers();
        gfxSwapBuffers();
        if (result != NULL)
            break;
    }
    for (i = 0; i < wireless_peer_count(); i++) {
        const Soak *s = &s_soak[i];

        relSent   += s->relSent;
        relGot    += s->relGot;
        frameSent += s->frameSent;
        frameGot  += s->frameGot;
        if (log)
            log("wltest: node %u %s: reliable %lu sent, %lu got of %lu; "
                "frames %lu sent, %lu got; faults %lu", s->node,
                soak_state(s), (unsigned long)s->relSent,
                (unsigned long)s->relGot, (unsigned long)s->theirTotal,
                (unsigned long)s->frameSent, (unsigned long)s->frameGot,
                (unsigned long)s->faults);
    }
    if (log)
        log("wltest: %s (%d peer(s); reliable %lu sent, %lu got; frames %lu "
            "sent, %lu got)", result ? result : "left with START",
            wireless_peer_count(), (unsigned long)relSent,
            (unsigned long)relGot, (unsigned long)frameSent,
            (unsigned long)frameGot);
    wireless_stop();
    return rc;
}
