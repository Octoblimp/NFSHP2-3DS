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

#define MESSAGE_MAX 512

typedef enum {
    LS_OFF,         // not the current screen
    LS_ASK,         // Host or Join, with the link down
    LS_NOTICE,      // a line and OK
    LS_HOSTING,     // the names on this console's network
    LS_SEARCHING,   // scanning, with nothing found yet
    LS_FOUND,       // a race found: Join or Next
    LS_JOINED,      // on a host's network, until it starts
    LS_GONE         // on to car select, with the link up
} LobbyState;

// The popups' answers: each button's Param, BACK's, and the Param a popup
// with no buttons gives SELECT, which only puts it back.
enum { A_HOST = 1, A_JOIN, A_BACK, A_STAY, A_START, A_NEXT, A_OK, A_CPU };

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
    if (L.net.state() == WIRELESS_OFF) return;
    L.net.leave();
    L.net.stop();
    say("lobby: link down");
}

static int clientsAlive(void)
{
    int i, n = 0;
    for (i = 0; i < L.net.peerCount(); i++) n += L.net.peerAlive(i) != 0;
    return n;
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
// host left it. Put up again only when it changed, or when there is none
// up (a press took it down); the lines say which buttons there are, so
// they alone say what changed.
static void showList(BGameFlow* gf)
{
    char msg[MESSAGE_MAX];
    char name[WIRELESS_NAME_MAX];
    int  i, clients = clientsAlive(), cpu = cpuShown();

    snprintf(msg, sizeof msg, "%s", text(gf, PORTLANG_WAITING_FOR_PLAYERS));
    lobby_latin1(name, sizeof name, L.net.selfName());
    strncat(msg, "@", sizeof msg - strlen(msg) - 1);
    strncat(msg, name, sizeof msg - strlen(msg) - 1);
    for (i = 0; i < L.net.peerCount(); i++) {
        if (!L.net.peerAlive(i)) continue;
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
    if (L.popup >= 0 && !strcmp(msg, L.message)) return;
    hidePopup(gf);
    if (strcmp(msg, L.message)) say("lobby: list %s", msg);
    memcpy(L.message, msg, sizeof msg);
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
    if (!L.net.start()) {
        notice(gf, PORTLANG_WIRELESS_OFF, "", LS_ASK);
        return;
    }
    if (!L.net.host(WIRELESS_MAX_CONSOLES, NULL, 0)) {
        linkDown();
        notice(gf, PORTLANG_WIRELESS_OFF, "", LS_ASK);
        return;
    }
    L.state   = LS_HOSTING;
    L.cpuWant = L.cpuFn ? L.cpuFn() : LOBBY_CPU_NONE;
    L.onCpu   = 0;
    say("lobby: hosting");
    showList(gf);
}

static void goOn(BGameFlow* gf)
{
    hidePopup(gf);
    L.state = LS_GONE;
    bgf_change_to_screen(gf, LOBBY_NEXT_SCREEN, 1);
}

// Start: no more in, and each client told how many there are and which
// place is its, the host's being 0.
static void raceInit(LobbyRace* r, int consoles, int place)
{
    int i;

    memset(r, 0, sizeof *r);
    r->consoles = consoles;
    r->place    = place;
    for (i = 0; i < WIRELESS_MAX_CONSOLES; i++) r->peer[i] = -1;
}

static void startRace(BGameFlow* gf)
{
    int       i, place = 0, consoles = clientsAlive() + 1, cpu = cpuShown();
    uint8_t   msg[2];
    LobbyRace race;

    if (consoles < 2) {
        showList(gf);   // the last one went as Start was pressed
        return;
    }
    L.net.setOpen(0);
    raceInit(&race, consoles, 0);
    race.cpu = cpu > 0 ? cpu : 0;
    lobby_latin1(race.hostName, sizeof race.hostName, L.net.selfName());
    for (i = 0; i < L.net.peerCount(); i++) {
        if (!L.net.peerAlive(i)) continue;
        msg[0] = (uint8_t)consoles;
        msg[1] = (uint8_t)++place;
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

static void joinFound(BGameFlow* gf)
{
    const WirelessHost* h = &L.hosts[L.hostIndex];

    lobby_latin1(L.hostName, sizeof L.hostName, h->name);
    if (!L.net.join(h->scanIndex)) {
        notice(gf, PORTLANG_JOIN_FAILED, L.hostName, LS_SEARCHING);
        return;
    }
    hidePopup(gf);
    L.state = LS_JOINED;
    fill(L.message, sizeof L.message, text(gf, PORTLANG_WAITING_FOR_HOST),
         L.hostName, 0, 0);
    say("lobby: joined %s", L.hostName);
    showPopup(gf, 0, 0, 0, 0, 0, 0);
}

static void tick(BGameFlow* gf)
{
    switch (L.state) {
        case LS_HOSTING:
            if (L.net.state() != WIRELESS_HOSTING) {
                say("lobby: the network went");
                linkDown();
                notice(gf, PORTLANG_WIRELESS_OFF, "", LS_ASK);
                break;
            }
            // A place kept for one that went would keep the next out.
            if (clientsAlive() != L.net.peerCount()) L.net.forgetLost();
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

                if (m.type != LOBBY_MSG_START || m.len < 2) continue;
                say("lobby: started by %s, place %d of %d", L.hostName,
                    m.data[1], m.data[0]);
                raceInit(&race, m.data[0], m.data[1]);
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

        default:
            break;
    }
}

// What a popup's button, or BACK, says in each state.
static void answer(BGameFlow* gf, int a)
{
    switch (L.state) {
        case LS_ASK:
            if (a == A_HOST) startHosting(gf);
            else if (a == A_JOIN) {
                if (L.net.start()) startSearching(gf, 0);
                else notice(gf, PORTLANG_WIRELESS_OFF, "", LS_ASK);
            } else if (a == A_BACK) {
                say("lobby: back");
                L.state = LS_OFF;
                bgf_move_back_screen(gf, 1);
            } else {
                toAsk(gf);
            }
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

void lobby_notice_next(int32_t id, const char* name)
{
    L.nextNotice = id;
    snprintf(L.nextName, sizeof L.nextName, "%s", name ? name : "");
}

void lobby_callback(BGameFlow* gf, BScreenMessage msg,
                    BScreenCallbackData* data)
{
    switch (msg) {
        // Coming back from car select takes the link down: the question
        // again, as at the start, after the race's notice if it left one.
        case BMSG_SCREEN_ACTIVATE:
            L.popup = -1;
            if (L.nextNotice) {
                int32_t id = L.nextNotice;

                L.nextNotice = 0;
                linkDown();
                notice(gf, id, L.nextName, LS_ASK);
                break;
            }
            toAsk(gf);
            break;

        // Gone on with the race: the link stays. Gone any other way: down.
        case BMSG_SCREEN_UNACTIVATE:
            if (L.state != LS_GONE) {
                hidePopup(gf);
                linkDown();
            }
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
