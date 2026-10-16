// lobby -- the Local Wireless lobby: see lobby.h.

#include "lobby.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "bpopup.h"
#include "gameflow.h"
#include "portlang.h"

// "OK", the language table's (END_GAME_LANG_OK, endgame.h).
#define LANG_OK 0x38277
// The main menu's two modes, its MENUITEM_1 and MENUITEM_2.
#define LANG_HOT_PURSUIT  10023
#define LANG_WORLD_RACING 10022

#define MESSAGE_MAX 512

typedef enum {
    LS_OFF,         // not the current screen
    LS_ASK,         // Host or Join, with the link down
    LS_MODE,        // the host's: Hot Pursuit or World Racing
    LS_NOTICE,      // a line and OK
    LS_HOSTING,     // the names on this console's network
    LS_SEARCHING,   // scanning, with nothing found yet
    LS_FOUND,       // a race found: Join or Next
    LS_JOINED,      // on a host's network, until it starts
    LS_RESUMING,    // back in a race after a restart (37g-3): its setup
                    // coming, then its load
    LS_GONE         // on to car select, with the link up
} LobbyState;

// The popups' answers: each button's Param, BACK's, and the Param a popup
// with no buttons gives SELECT, which only puts it back.
enum {
    A_HOST = 1, A_JOIN, A_BACK, A_STAY, A_START, A_NEXT, A_OK, A_CPU,
    A_COPS_ON, A_COPS_OFF
};

static struct {
    LobbyNet     net;
    LobbyLogFn   log;
    LobbyState   state;
    LobbyState   afterNotice;    // where OK goes: the question or a scan
    int          popup;          // the one up, or -1
    int          quiet;          // a dismiss of the lobby's own
    int          scanned;        // a scan since the search began
    uint32_t     scanAt;         // when, in ms
    WirelessHost hosts[WIRELESS_MAX_HOSTS];
    int          numHosts, hostIndex;
    char         hostName[WIRELESS_NAME_MAX];   // the one joined, Latin-1
    char         message[MESSAGE_MAX];          // the popup's
    LobbyStartFn onStart;
    int32_t      nextNotice;                    // lobby_notice_next's, or 0
    char         nextName[WIRELESS_NAME_MAX];   // Latin-1
    LobbyCpuFn   cpuFn;
    int          cpuWant;        // the host's CPU racers, or LOBBY_CPU_NONE
    int          onCpu;          // the host's highlight on CPU Racers
    LobbySetupFn setupFn;
    int          setup;          // the host's setup screens up, over this
    int          copsOff;        // the mode last hosted: the highlight
    int          listKey;        // the host's list's buttons, as shown
    // Back from the race (37f): next time the lobby comes up; which this
    // console was; the link's timeout still the race's; and by peer
    // whether it has yet to say it is back (a client's: the host).
    int          backNext;
    int          wasHost;
    int          waiting;
    int          awaited[WIRELESS_MAX_CONSOLES];
} L = { .popup = -1 };

static void say(const char* fmt, ...)
{
    char    line[MESSAGE_MAX + 64];
    va_list ap;

    if (!L.log) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    L.log(line);
}

static uint32_t nowMs(const BGameFlow* gf)
{
    return gf->realTimer / 4;   // 1/4000 s
}

// English until a language is chosen (-1): portlang_get's own fallback.
static const char* text(const BGameFlow* gf, int32_t id)
{
    const char* s = portlang_get(gf->currLanguage, id, NULL);
    return s ? s : "";
}

void lobby_latin1(char* out, size_t cap, const char* utf8)
{
    const unsigned char* s = (const unsigned char*)(utf8 ? utf8 : "");
    size_t               o = 0;

    if (!cap) return;
    while (*s && o + 1 < cap) {
        uint32_t c;
        int      more;

        if (*s < 0x80)                { c = *s;        more = 0; }
        else if ((*s & 0xe0) == 0xc0) { c = *s & 0x1f; more = 1; }
        else if ((*s & 0xf0) == 0xe0) { c = *s & 0x0f; more = 2; }
        else if ((*s & 0xf8) == 0xf0) { c = *s & 0x07; more = 3; }
        else                          { c = '?';       more = 0; }
        s++;
        // A sequence cut short is one '?', and what cut it starts over.
        for (; more > 0; more--) {
            if ((*s & 0xc0) != 0x80) { c = '?'; break; }
            c = (c << 6) | (*s++ & 0x3f);
        }
        if (c == '@' || c < 0x20 || (c >= 0x7f && c < 0xa0) || c > 0xff)
            c = '?';
        out[o++] = (char)c;
    }
    out[o] = 0;
}

// A line with "$NAME", "$N" and "$MAX" put in (portlang.c).
static void fill(char* out, size_t cap, const char* tmpl, const char* name,
                 int n, int max)
{
    size_t o = 0;

    while (*tmpl && o + 1 < cap) {
        char        num[12];
        const char* put  = NULL;
        size_t      skip = 0;

        if (!strncmp(tmpl, "$NAME", 5)) {
            put  = name;
            skip = 5;
        } else if (!strncmp(tmpl, "$MAX", 4)) {
            snprintf(num, sizeof num, "%d", max);
            put  = num;
            skip = 4;
        } else if (!strncmp(tmpl, "$N", 2)) {
            snprintf(num, sizeof num, "%d", n);
            put  = num;
            skip = 2;
        }
        if (put) {
            while (*put && o + 1 < cap) out[o++] = *put++;
            tmpl += skip;
        } else {
            out[o++] = *tmpl++;
        }
    }
    out[o] = 0;
}

// ------------------------------------------------------------- the popup

// The memory card's popup screen, as the debug menu's question has it:
// the buttons side by side under the message, BACK the way out, the
// lobby's name over it.
static void showPopup(BGameFlow* gf, int buttons, int32_t b0, int a0,
                      int32_t b1, int a1, int start)
{
    BPopupConfig cfg;

    memset(&cfg, 0, sizeof cfg);
    cfg.numButtons     = buttons;
    cfg.flags          = BPOPUP_HORIZONTAL | BPOPUP_CANCELABLE
                       | BPOPUP_BUTTONS_BELOW;
    cfg.parent         = gf->screen;
    cfg.screen         = BPOPUP_SCREEN_MEMCARD;
    cfg.message        = L.message;
    cfg.button[0]      = b0;
    cfg.button[1]      = b1;
    cfg.buttonParam[0] = buttons > 0 ? a0 : A_STAY;
    cfg.buttonParam[1] = a1;
    cfg.cancelParam    = A_BACK;
    cfg.dismissParam   = A_STAY;
    cfg.startButton    = start;
    cfg.joyPort        = -1;
    cfg.title          = PORTLANG_LOCAL_WIRELESS;
    L.popup   = bpopup_summon(gf, &cfg);
    if (L.popup < 0) say("lobby: no popup free");
}

// The lobby's popup down, with no answer and no sound.
static void hidePopup(BGameFlow* gf)
{
    if (L.popup < 0) return;
    L.quiet = 1;
    bpopup_dismiss(gf, L.popup);
    L.quiet = 0;
    L.popup = -1;
}

// ------------------------------------------------------------- the link

static void linkDown(void)
{
    L.waiting = 0;
    memset(L.awaited, 0, sizeof L.awaited);
    if (L.net.state() == WIRELESS_OFF) return;
    L.net.leave();
    L.net.stop();
    say("lobby: link down");
}

// The console's wireless communication turned off (TASKS 62): nothing
// local starts, and what was up has gone.
static int radioOff(void)
{
    return L.net.radioOff && L.net.radioOff();
}

static int clientsAlive(void)
{
    int i, n = 0;
    for (i = 0; i < L.net.peerCount(); i++) n += L.net.peerAlive(i) != 0;
    return n;
}

// The consoles still on that have yet to say they are back from the race
// (a client's: the host).
static int awaiting(void)
{
    int i, n = 0;

    for (i = 0; i < L.net.peerCount() && i < WIRELESS_MAX_CONSOLES; i++)
        n += L.awaited[i] && L.net.peerAlive(i);
    return n;
}

// Each one back, or gone: the link's own timeout again.
static void backDone(void)
{
    if (!L.waiting || awaiting()) return;
    L.waiting = 0;
    if (L.net.setPatience) L.net.setPatience(0);
    say("lobby: every console back");
}

// What came from client `i`: whether it says it is back. Nothing else is
// the lobby's (the race's last, its stop said again), and none of it may
// reach the next race. A client that joined (37g-3: one that restarted
// and came back as the race ended) waits in its lobby, as good as back.
static void readBack(int i)
{
    WlMsg m;
    char  name[WIRELESS_NAME_MAX];

    while (L.net.recv(i, &m)) {
        if ((m.type != LOBBY_MSG_BACK && m.type != LOBBY_MSG_REJOIN)
            || i >= WIRELESS_MAX_CONSOLES || !L.awaited[i])
            continue;
        L.awaited[i] = 0;
        lobby_latin1(name, sizeof name, L.net.peerName(i));
        say("lobby: %s is back", name);
    }
}

// The places of those gone go, and the next in line take theirs, as
// wireless_forget_lost does the peers.
static void forgetLost(void)
{
    int i, n = 0;

    for (i = 0; i < L.net.peerCount() && i < WIRELESS_MAX_CONSOLES; i++)
        if (L.net.peerAlive(i)) L.awaited[n++] = L.awaited[i];
    for (; n < WIRELESS_MAX_CONSOLES; n++) L.awaited[n] = 0;
    L.net.forgetLost();
}

// ------------------------------------------------------------ the states

static void toAsk(BGameFlow* gf)
{
    linkDown();
    hidePopup(gf);
    L.state = LS_ASK;
    snprintf(L.message, sizeof L.message, "%s",
             text(gf, PORTLANG_HOST_OR_JOIN));
    say("lobby: ask");
    showPopup(gf, 2, PORTLANG_HOST, A_HOST, PORTLANG_JOIN, A_JOIN, 0);
}

static void notice(BGameFlow* gf, int32_t id, const char* name,
                   LobbyState after)
{
    hidePopup(gf);
    L.state       = LS_NOTICE;
    L.afterNotice = after;
    fill(L.message, sizeof L.message, text(gf, id), name, 0, 0);
    say("lobby: notice %s", L.message);
    showPopup(gf, 1, LANG_OK, A_OK, 0, 0, 0);
}

// Local wireless would not come up, or went: that the console's wireless
// is off when it is, so it can be turned on; OK, then the question.
static void offNotice(BGameFlow* gf)
{
    if (radioOff()) {
        say("lobby: wireless communication off");
        notice(gf, PORTLANG_WIRELESS_DISABLED, "", LS_ASK);
    } else {
        notice(gf, PORTLANG_WIRELESS_OFF, "", LS_ASK);
    }
}

// Turned off with the link up (from the HOME Menu, the game suspended):
// the network went with it, so the lobby's link goes, before a tick or a
// press asks anything more of it. Whether it did.
static int radioWent(void)
{
    if (L.state != LS_HOSTING && L.state != LS_SEARCHING
        && L.state != LS_FOUND && L.state != LS_JOINED
        && L.state != LS_RESUMING)
        return 0;
    if (!radioOff()) return 0;
    linkDown();
    return 1;
}

// The CPU racers the host's list shows: as many as wished, of those that
// fit beside the consoles on the network; below 0 with no choice (the
// wish's own), or no room.
static int cpuShown(void)
{
    int room = LOBBY_GRID - (clientsAlive() + 1);

    if (room <= 0) return -1;
    return L.cpuWant < room ? L.cpuWant : room;
}

// The host's list: the line, then this console, then each client still
// on, in the order they came, then the CPU racers if there is a choice.
// Start once there is a client, then CPU Racers, the highlight where the
// host left it. Put up again only when it or its buttons changed, or
// when there is none up (a press took it down). Back from a race, a
// client is listed once it says it is back, and Start waits for every
// client still on.
static void showList(BGameFlow* gf)
{
    char msg[MESSAGE_MAX];
    char name[WIRELESS_NAME_MAX];
    int  i, clients = clientsAlive(), cpu = cpuShown(), key;

    snprintf(msg, sizeof msg, "%s", text(gf, PORTLANG_WAITING_FOR_PLAYERS));
    lobby_latin1(name, sizeof name, L.net.selfName());
    strncat(msg, "@", sizeof msg - strlen(msg) - 1);
    strncat(msg, name, sizeof msg - strlen(msg) - 1);
    for (i = 0; i < L.net.peerCount(); i++) {
        if (!L.net.peerAlive(i)
            || (i < WIRELESS_MAX_CONSOLES && L.awaited[i]))
            continue;
        lobby_latin1(name, sizeof name, L.net.peerName(i));
        strncat(msg, "@", sizeof msg - strlen(msg) - 1);
        strncat(msg, name, sizeof msg - strlen(msg) - 1);
    }
    if (cpu >= 0) {
        char line[64];

        fill(line, sizeof line, text(gf, PORTLANG_CPU_RACERS_N), "", cpu, 0);
        strncat(msg, "@", sizeof msg - strlen(msg) - 1);
        strncat(msg, line, sizeof msg - strlen(msg) - 1);
    }
    if (awaiting()) clients = 0;
    key = (cpu >= 0) * 2 + (clients > 0);
    if (L.popup >= 0 && !strcmp(msg, L.message) && key == L.listKey) return;
    hidePopup(gf);
    if (strcmp(msg, L.message)) say("lobby: list %s", msg);
    memcpy(L.message, msg, sizeof msg);
    L.listKey = key;
    if (cpu < 0)
        showPopup(gf, clients > 0, PORTLANG_START, A_START, 0, 0, 0);
    else if (clients == 0)
        showPopup(gf, 1, PORTLANG_CPU_RACERS, A_CPU, 0, 0, 0);
    else
        showPopup(gf, 2, PORTLANG_START, A_START, PORTLANG_CPU_RACERS, A_CPU,
                  L.onCpu);
}

// A on CPU Racers: one more, none again past as many as fit, and the
// highlight kept on it, so A counts on.
static void nextCpu(BGameFlow* gf)
{
    int cpu  = cpuShown();
    int room = LOBBY_GRID - (clientsAlive() + 1);

    if (cpu >= 0) {   // not if a console filled the room as A was pressed
        L.cpuWant = cpu < room ? cpu + 1 : 0;
        L.onCpu   = 1;
        say("lobby: cpu %d", L.cpuWant);
    }
    showList(gf);
}

static void startHosting(BGameFlow* gf)
{
    if (radioOff() || !L.net.start()) {
        offNotice(gf);
        return;
    }
    if (!L.net.host(WIRELESS_MAX_CONSOLES, NULL, 0)) {
        linkDown();
        offNotice(gf);
        return;
    }
    L.state   = LS_HOSTING;
    L.cpuWant = L.cpuFn ? L.cpuFn() : LOBBY_CPU_NONE;
    L.onCpu   = 0;
    say("lobby: hosting");
    showList(gf);
}

// Host's question (TASKS 63): the main menu's two modes, the one hosted
// last highlighted.
static void toMode(BGameFlow* gf)
{
    hidePopup(gf);
    L.state = LS_MODE;
    snprintf(L.message, sizeof L.message, "%s",
             text(gf, PORTLANG_HOST_MODE));
    say("lobby: mode");
    showPopup(gf, 2, LANG_HOT_PURSUIT, A_COPS_ON, LANG_WORLD_RACING,
              A_COPS_OFF, L.copsOff);
}

// A mode chosen: the cops on or off, as the main menu's two items set
// them, then retail's Challenge for the rest, the lobby pushed under it.
// Players there reads Local Wireless until the lobby is back (the setup
// function, bsetup.c's wirelessPlayers).
static void startSetup(BGameFlow* gf, int copsOn)
{
    hidePopup(gf);
    L.copsOff  = !copsOn;
    gf->copsOn = copsOn;
    if (gf->hooks.setPolice) gf->hooks.setPolice(gf->hooks.user, copsOn);
    L.setup = 1;
    if (L.setupFn) L.setupFn(1);
    say("lobby: setup, cops %s", copsOn ? "on" : "off");
    bgf_change_to_screen(gf, LOBBY_SETUP_SCREEN, 1);
}

// Back from the setup. A select there pushed the lobby again, over the
// setup's screens and the lobby that went to them: the stack goes back to
// under that lobby, as if this one had been it all along, and hosting
// begins. BACK from the Challenge popped that lobby instead: the question
// of the mode again.
static void setupOver(BGameFlow* gf)
{
    int k;

    L.setup = 0;
    if (L.setupFn) L.setupFn(0);
    for (k = gf->stack.index - 1; k >= 0; k--)
        if (!strcmp(gf->stack.names[k], LOBBY_SCREEN_NAME)) break;
    if (k < 0) {
        say("lobby: setup left");
        toMode(gf);
        return;
    }
    bgf_pop_until(gf, LOBBY_SCREEN_NAME);
    bgf_pop_screen(gf);
    say("lobby: setup done");
    startHosting(gf);
}

static void goOn(BGameFlow* gf)
{
    hidePopup(gf);
    L.wasHost = L.state == LS_HOSTING;
    L.state   = LS_GONE;
    bgf_change_to_screen(gf, LOBBY_NEXT_SCREEN, 1);
}

// Start: no more in, and each client told how many there are, which
// place is its, the host's being 0, and the host's mode.
static void raceInit(LobbyRace* r, int consoles, int place)
{
    int i;

    memset(r, 0, sizeof *r);
    r->consoles = consoles;
    r->place    = place;
    r->gameType = -1;
    for (i = 0; i < WIRELESS_MAX_CONSOLES; i++) r->peer[i] = -1;
}

static void startRace(BGameFlow* gf)
{
    int       i, place = 0, consoles = clientsAlive() + 1, cpu = cpuShown();
    uint8_t   msg[4];
    LobbyRace race;

    if (consoles < 2 || awaiting()) {
        showList(gf);   // the last one went as Start was pressed
        return;
    }
    L.net.setOpen(0);
    raceInit(&race, consoles, 0);
    race.cpu      = cpu > 0 ? cpu : 0;
    race.gameType = gf->hooks.gameType ? gf->hooks.gameType(gf->hooks.user)
                                       : 0;
    race.copsOn   = gf->copsOn != 0;
    lobby_latin1(race.hostName, sizeof race.hostName, L.net.selfName());
    for (i = 0; i < L.net.peerCount(); i++) {
        if (!L.net.peerAlive(i)) continue;
        msg[0] = (uint8_t)consoles;
        msg[1] = (uint8_t)++place;
        msg[2] = (uint8_t)race.gameType;
        msg[3] = (uint8_t)race.copsOn;
        race.peer[place] = i;
        L.net.send(i, LOBBY_MSG_START, msg, sizeof msg);
    }
    if (cpu >= 0)
        say("lobby: start, %d consoles, %d CPU racers", consoles, cpu);
    else
        say("lobby: start, %d consoles", consoles);
    if (L.onStart) L.onStart(&race);
    goOn(gf);
}

static void startSearching(BGameFlow* gf, int justScanned)
{
    hidePopup(gf);
    L.state   = LS_SEARCHING;
    L.scanned = justScanned;
    snprintf(L.message, sizeof L.message, "%s",
             text(gf, PORTLANG_SEARCHING));
    say("lobby: searching");
    showPopup(gf, 0, 0, 0, 0, 0, 0);
}

static int scanNow(BGameFlow* gf)
{
    int n = L.net.scan(L.hosts, WIRELESS_MAX_HOSTS);
    L.scanned  = 1;
    L.scanAt   = nowMs(gf);
    L.numHosts = n > 0 ? n : 0;
    say("lobby: scan %d", n);
    return L.numHosts;
}

// Next keeps the highlight on Next, so A walks the races.
static void showFound(BGameFlow* gf, int onNext)
{
    const WirelessHost* h = &L.hosts[L.hostIndex];
    char                name[WIRELESS_NAME_MAX];

    hidePopup(gf);
    lobby_latin1(name, sizeof name, h->name);
    L.state = LS_FOUND;
    fill(L.message, sizeof L.message, text(gf, PORTLANG_FOUND), name,
         h->consoles, h->maxConsoles);
    say("lobby: found %d of %d, %s", L.hostIndex + 1, L.numHosts, name);
    showPopup(gf, 2, PORTLANG_JOIN, A_JOIN, PORTLANG_NEXT, A_NEXT,
              onNext);
}

// A client's wait for the host's Start.
static void showJoined(BGameFlow* gf)
{
    hidePopup(gf);
    L.state = LS_JOINED;
    fill(L.message, sizeof L.message, text(gf, PORTLANG_WAITING_FOR_HOST),
         L.hostName, 0, 0);
    showPopup(gf, 0, 0, 0, 0, 0, 0);
}

// Joined, it says so: a host racing takes it back into its place
// (37g-3), and one in its lobby lets it be.
static void joinFound(BGameFlow* gf)
{
    const WirelessHost* h = &L.hosts[L.hostIndex];
    uint8_t             none = 0;

    lobby_latin1(L.hostName, sizeof L.hostName, h->name);
    if (!L.net.join(h->scanIndex)) {
        notice(gf, PORTLANG_JOIN_FAILED, L.hostName, LS_SEARCHING);
        return;
    }
    say("lobby: joined %s", L.hostName);
    L.net.send(0, LOBBY_MSG_REJOIN, &none, 1);
    showJoined(gf);
}

// The racing host's answer to the join (37g-3): this console back in its
// place, Start's mode, and the race's setup after, which the race takes
// while the wait stays up; it loads from here. Nothing in it: the race
// would not take it back.
static void resumed(BGameFlow* gf, const WlMsg* m)
{
    LobbyRace race;

    if (m->len < 4) {
        say("lobby: %s's race would not take this console back",
            L.hostName);
        linkDown();
        notice(gf, PORTLANG_JOIN_FAILED, L.hostName, LS_ASK);
        return;
    }
    say("lobby: back in %s's race, place %d of %d, game type %d, cops %s",
        L.hostName, m->data[1], m->data[0], m->data[2],
        m->data[3] ? "on" : "off");
    raceInit(&race, m->data[0], m->data[1]);
    race.gameType = m->data[2];
    race.copsOn   = m->data[3] != 0;
    race.resume   = 1;
    race.peer[0]  = 0;
    memcpy(race.hostName, L.hostName, sizeof race.hostName);
    L.wasHost = 0;
    L.state   = LS_RESUMING;
    if (L.onStart) L.onStart(&race);
}

// Back from the race (lobby_back_next), the link as the race left it:
// the host's list, open to joiners again, each client still on awaited;
// a client's wait for the next Start. Each console says it is back. The
// link gone on the way, or the console's wireless off: the line, as on
// any other screen of the lobby.
static void backFromRace(BGameFlow* gf)
{
    uint8_t none = 0;
    int     i;

    if (radioOff()) {
        say("lobby: back from the race, wireless communication off");
        linkDown();
        offNotice(gf);
        return;
    }
    if (L.wasHost && L.net.state() == WIRELESS_HOSTING) {
        L.state = LS_HOSTING;
        L.onCpu = 0;
        L.net.setOpen(1);
        for (i = 0; i < L.net.peerCount() && i < WIRELESS_MAX_CONSOLES;
             i++) {
            L.awaited[i] = L.net.peerAlive(i) != 0;
            if (L.awaited[i]) L.net.send(i, LOBBY_MSG_BACK, &none, 1);
        }
        L.waiting = 1;
        say("lobby: back from the race, hosting, %d to come", awaiting());
        backDone();
        showList(gf);
        return;
    }
    if (!L.wasHost && L.net.state() == WIRELESS_CONNECTED
        && L.net.peerAlive(0)) {
        L.awaited[0] = 1;
        L.waiting    = 1;
        L.net.send(0, LOBBY_MSG_BACK, &none, 1);
        say("lobby: back from the race, waiting for %s", L.hostName);
        showJoined(gf);
        return;
    }
    if (L.wasHost) {
        say("lobby: back from the race, the network went");
        linkDown();
        offNotice(gf);
    } else {
        say("lobby: back from the race, %s lost", L.hostName);
        linkDown();
        notice(gf, PORTLANG_LINK_LOST, L.hostName, LS_ASK);
    }
}

static void tick(BGameFlow* gf)
{
    if (radioWent()) {
        offNotice(gf);
        return;
    }
    switch (L.state) {
        case LS_HOSTING:
            if (L.net.state() != WIRELESS_HOSTING) {
                say("lobby: the network went");
                linkDown();
                offNotice(gf);
                break;
            }
            for (int i = 0; i < L.net.peerCount(); i++) readBack(i);
            // A place kept for one that went would keep the next out.
            if (clientsAlive() != L.net.peerCount()) forgetLost();
            backDone();
            showList(gf);
            break;

        case LS_SEARCHING:
            if (L.scanned && nowMs(gf) - L.scanAt < LOBBY_SCAN_MS) break;
            if (scanNow(gf) > 0) {
                L.hostIndex = 0;
                showFound(gf, 0);
            }
            break;

        case LS_JOINED: {
            WlMsg m;
            while (L.net.recv(0, &m)) {
                LobbyRace race;

                if (m.type == LOBBY_MSG_BACK && L.awaited[0]) {
                    L.awaited[0] = 0;
                    say("lobby: %s is back", L.hostName);
                    backDone();
                }
                // What follows it is the race's.
                if (m.type == LOBBY_MSG_RESUME) {
                    resumed(gf, &m);
                    return;
                }
                if (m.type != LOBBY_MSG_START || m.len < 2) continue;
                say("lobby: started by %s, place %d of %d", L.hostName,
                    m.data[1], m.data[0]);
                raceInit(&race, m.data[0], m.data[1]);
                if (m.len >= 4) {
                    race.gameType = m.data[2];
                    race.copsOn   = m.data[3] != 0;
                    say("lobby: the host's game type %d, cops %s",
                        race.gameType, race.copsOn ? "on" : "off");
                }
                race.peer[0] = 0;
                memcpy(race.hostName, L.hostName, sizeof race.hostName);
                if (L.onStart) L.onStart(&race);
                goOn(gf);
                return;
            }
            if (L.net.state() != WIRELESS_CONNECTED) {
                say("lobby: lost %s", L.hostName);
                linkDown();
                notice(gf, PORTLANG_LINK_LOST, L.hostName, LS_ASK);
            }
            break;
        }

        // The race reads the link; the host lost is the lobby's to say.
        case LS_RESUMING:
            if (L.net.state() != WIRELESS_CONNECTED) {
                say("lobby: lost %s as the race came back", L.hostName);
                linkDown();
                notice(gf, PORTLANG_LINK_LOST, L.hostName, LS_ASK);
            }
            break;

        default:
            break;
    }
}

// What a popup's button, or BACK, says in each state.
static void answer(BGameFlow* gf, int a)
{
    if (a != A_BACK && radioWent()) {
        offNotice(gf);
        return;
    }
    switch (L.state) {
        // Host asks the mode, then sets the race up, before the network
        // is made; with the console's wireless off it says so first.
        case LS_ASK:
            if (a == A_HOST) {
                if (radioOff()) offNotice(gf);
                else toMode(gf);
            } else if (a == A_JOIN) {
                if (!radioOff() && L.net.start()) startSearching(gf, 0);
                else offNotice(gf);
            } else if (a == A_BACK) {
                say("lobby: back");
                L.state = LS_OFF;
                bgf_move_back_screen(gf, 1);
            } else {
                toAsk(gf);
            }
            break;

        case LS_MODE:
            if (a == A_COPS_ON || a == A_COPS_OFF)
                startSetup(gf, a == A_COPS_ON);
            else if (a == A_BACK) toAsk(gf);
            else toMode(gf);
            break;

        case LS_NOTICE:
            if (L.afterNotice == LS_SEARCHING) startSearching(gf, 0);
            else toAsk(gf);
            break;

        case LS_HOSTING:
            if (a == A_START) startRace(gf);
            else if (a == A_CPU) nextCpu(gf);
            else if (a == A_BACK) toAsk(gf);
            else showList(gf);
            break;

        case LS_SEARCHING:
            if (a == A_BACK) toAsk(gf);
            else showPopup(gf, 0, 0, 0, 0, 0, 0);
            break;

        case LS_FOUND:
            if (a == A_JOIN) {
                joinFound(gf);
            } else if (a == A_NEXT) {
                if (++L.hostIndex >= L.numHosts) {
                    L.hostIndex = 0;
                    if (scanNow(gf) == 0) {
                        startSearching(gf, 1);
                        break;
                    }
                }
                showFound(gf, 1);
            } else if (a == A_BACK) {
                toAsk(gf);
            } else {
                showFound(gf, 0);
            }
            break;

        case LS_JOINED:
        case LS_RESUMING:
            if (a == A_BACK) toAsk(gf);
            else showPopup(gf, 0, 0, 0, 0, 0, 0);
            break;

        default:
            break;
    }
}

// ------------------------------------------------------------ the screen

void lobby_init(const LobbyNet* net, LobbyLogFn log)
{
    memset(&L, 0, sizeof L);
    if (net) L.net = *net;
    L.log   = log;
    L.popup = -1;
}

void lobby_on_start(LobbyStartFn fn)
{
    L.onStart = fn;
}

void lobby_cpu_wish(LobbyCpuFn fn)
{
    L.cpuFn = fn;
}

void lobby_back_next(void)
{
    L.backNext = 1;
}

void lobby_resume_failed(BGameFlow* gf, int32_t id, const char* name)
{
    if (L.state != LS_RESUMING) return;
    say("lobby: the race did not come back");
    linkDown();
    notice(gf, id, name, LS_ASK);
}

void lobby_notice_next(int32_t id, const char* name)
{
    L.nextNotice = id;
    snprintf(L.nextName, sizeof L.nextName, "%s", name ? name : "");
}

void lobby_on_setup(LobbySetupFn fn)
{
    L.setupFn = fn;
}

void lobby_callback(BGameFlow* gf, BScreenMessage msg,
                    BScreenCallbackData* data)
{
    switch (msg) {
        // Back from the host's setup: hosting, or the mode again. Back from
        // the race: hosting, or the wait for the host, the link kept.
        // Coming back from car select takes the link down: the question
        // again, as at the start, after the race's notice if it left one.
        // A console lost with this one's wireless off was this one: that
        // is the notice.
        case BMSG_SCREEN_ACTIVATE:
            L.popup = -1;
            if (L.setup) {
                setupOver(gf);
                break;
            }
            if (L.backNext && !L.nextNotice) {
                L.backNext = 0;
                backFromRace(gf);
                break;
            }
            L.backNext = 0;
            if (L.nextNotice) {
                int32_t id = L.nextNotice;

                L.nextNotice = 0;
                linkDown();
                if (radioOff()) offNotice(gf);
                else notice(gf, id, L.nextName, LS_ASK);
                break;
            }
            toAsk(gf);
            break;

        // Gone on with the race, or to its load: the link stays. Gone any
        // other way: down.
        case BMSG_SCREEN_UNACTIVATE:
            hidePopup(gf);
            if (L.state != LS_GONE && L.state != LS_RESUMING) linkDown();
            L.state = LS_OFF;
            break;

        case BMSG_SCREEN_TICK:
            tick(gf);
            break;

        // The host's two buttons are Start and CPU Racers.
        case BMSG_POPUP_NEXT:
        case BMSG_POPUP_PREV:
            if (L.state == LS_HOSTING && data)
                L.onCpu = data->itemHash == BPOPUP_OBJ_BUTTON2;
            break;

        case BMSG_POPUP_DISMISS:
            if (L.quiet) {
                if (data) data->noise = BSND_NONE;
                break;
            }
            L.popup = -1;
            if (data) {
                if (data->param == A_BACK) data->noise = BSND_MENU_CANCEL;
                else if (data->param == A_STAY) data->noise = BSND_NONE;
            }
            answer(gf, data ? data->param : A_STAY);
            break;

        default:
            break;
    }
}
