// netrace -- a local wireless race's setup: see netrace.h.

#include "netrace.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "bmath.h"
#include "bpopup.h"
#include "fred.h"
#include "fredrace.h"
#include "gameflow.h"
#include "portlang.h"
#include "race.h"
#include "raceevent.h"
#include "raceparams.h"

#define SETUP_VERSION 1

// The popup's answers: BACK's, and what SELECT gives a popup with no
// buttons, which only puts it back.
enum { A_BACK = 1, A_STAY };

// What the setup carries ahead of the records. Every console runs the
// same build, so the records go as they are, and their sizes say so.
typedef struct SetupHeader {
    uint8_t         magic[2];           // 'N', 'R'
    uint8_t         version;
    uint8_t         consoles;
    int32_t         gameType;           // Fred's
    int32_t         numPlayerCars;      // Fred's
    uint32_t        seed;               // bDefaultSeed, the race built
    int8_t          driver[WIRELESS_MAX_CONSOLES];
    uint16_t        rpSize, driverSize, eventSize;
    uint8_t         numDrivers;
    uint8_t         stateInEvent;       // the event's state its own
    cPlayerSettings settings[WIRELESS_MAX_CONSOLES];   // each place's
} SetupHeader;

static NetRace  s_own = { .popup = -1 };
static NetRace* R     = &s_own;

static void say(const char* fmt, ...)
{
    char    line[640];
    va_list ap;

    if (!R->log) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    R->log(line);
}

static const char* text(const BGameFlow* gf, int32_t id)
{
    const char* s = portlang_get(gf->currLanguage, id, NULL);
    return s ? s : "";
}

// `tmpl` with "$NAME" put in.
static void fillName(char* out, size_t cap, const char* tmpl,
                     const char* name)
{
    size_t o = 0;

    while (*tmpl && o + 1 < cap) {
        if (!strncmp(tmpl, "$NAME", 5)) {
            const char* p = name;
            while (*p && o + 1 < cap) out[o++] = *p++;
            tmpl += 5;
        } else {
            out[o++] = *tmpl++;
        }
    }
    out[o] = 0;
}

// ------------------------------------------------------------- the places

// Place `p` still on: this console always, and the others by their link
// (a client knows only the host's).
static int placeAlive(int p)
{
    int peer;

    if (p == R->race.place) return 1;
    if (p < 0 || p >= R->race.consoles) return 0;
    peer = R->race.peer[p];
    return peer >= 0 && R->net.peerAlive && R->net.peerAlive(peer);
}

// Its console's name, Latin-1.
static void placeName(int p, char* out, size_t cap)
{
    int peer = p >= 0 && p < WIRELESS_MAX_CONSOLES ? R->race.peer[p] : -1;

    if (p == 0 || !R->net.peerName || peer < 0)
        snprintf(out, cap, "%s", p == 0 ? R->race.hostName : "");
    else
        lobby_latin1(out, cap, R->net.peerName(peer));
}

static int clientsLeft(void)
{
    int p, n = 0;
    for (p = 1; p < R->race.consoles; p++) n += placeAlive(p);
    return n;
}

// Each place that has gone, said once.
static void noticeGone(void)
{
    int  p;
    char name[WIRELESS_NAME_MAX];

    for (p = 0; p < R->race.consoles; p++) {
        if (R->gone[p] || placeAlive(p)) continue;
        if (!R->host && p != 0) continue;   // a client knows only the host
        R->gone[p]  = 1;
        R->lastGone = p;
        placeName(p, name, sizeof name);
        say("netrace: place %d (%s) is gone", p, name);
    }
}

// ------------------------------------------------------------- the popup

static void hidePopup(BGameFlow* gf)
{
    if (R->popup < 0) return;
    R->quiet = 1;
    bpopup_dismiss(gf, R->popup);
    R->quiet = 0;
    R->popup = -1;
}

// The lobby's look: the memory card's popup screen, the lobby's name over
// it, no buttons, BACK the way out.
static void showPopup(BGameFlow* gf)
{
    BPopupConfig cfg;

    memset(&cfg, 0, sizeof cfg);
    cfg.numButtons     = 0;
    cfg.flags          = BPOPUP_HORIZONTAL | BPOPUP_CANCELABLE
                       | BPOPUP_BUTTONS_BELOW;
    cfg.parent         = gf->screen;
    cfg.screen         = BPOPUP_SCREEN_MEMCARD;
    cfg.message        = R->message;
    cfg.buttonParam[0] = A_STAY;
    cfg.cancelParam    = A_BACK;
    cfg.dismissParam   = A_STAY;
    cfg.joyPort        = -1;
    cfg.title          = PORTLANG_LOCAL_WIRELESS;
    R->popup = bpopup_summon(gf, &cfg);
    if (R->popup < 0) say("netrace: no popup free");
}

// "Wireless Race"'s line: a client's wait for the host, or the host's
// for each console still on that has no car in yet. Put up again only
// when it changed, or when none is up.
static void showWait(BGameFlow* gf)
{
    char msg[sizeof R->message];

    if (R->stage != NR_WAIT) return;   // the screen's stage
    if (R->host) {
        char name[WIRELESS_NAME_MAX];
        int  p;

        snprintf(msg, sizeof msg, "%s", text(gf, PORTLANG_WAITING_FOR_CARS));
        for (p = 1; p < R->race.consoles; p++) {
            if (!placeAlive(p) || R->cars[p].in) continue;
            placeName(p, name, sizeof name);
            strncat(msg, "@", sizeof msg - strlen(msg) - 1);
            strncat(msg, name, sizeof msg - strlen(msg) - 1);
        }
    } else {
        fillName(msg, sizeof msg, text(gf, PORTLANG_WAITING_FOR_HOST),
                 R->race.hostName);
    }
    if (R->popup >= 0 && !strcmp(msg, R->message)) return;
    hidePopup(gf);
    if (strcmp(msg, R->message)) say("netrace: wait %s", msg);
    memcpy(R->message, msg, sizeof msg);
    showPopup(gf);
}

// --------------------------------------------------------------- leaving

// Back to the lobby, which takes the link down and shows the line: the
// race lost the console named.
static void backToLobby(BGameFlow* gf, const char* name)
{
    int k, n = 0;

    R->stage = NR_OFF;
    if (R->net.setPatience) R->net.setPatience(0);
    lobby_notice_next(PORTLANG_LINK_LOST, name);
    for (k = gf->stack.index - 1; k >= 0; k--) {
        n++;
        if (!strcmp(gf->stack.names[k], LOBBY_SCREEN_NAME)) break;
    }
    if (k < 0) {
        say("netrace: no lobby to go back to");
        return;
    }
    say("netrace: back to the lobby");
    bgf_move_back_screen(gf, n);
}

static void lostAll(BGameFlow* gf)
{
    char name[WIRELESS_NAME_MAX];

    noticeGone();   // one gone since this frame's look
    placeName(R->lastGone, name, sizeof name);
    say("netrace: every other console is gone");
    backToLobby(gf, name);
}

// ------------------------------------------------------------ the start

static void start(uint32_t seed)
{
    if (!R->host)
        say("netrace: go, seed %08lx, this console's %08lx",
            (unsigned long)seed, (unsigned long)bDefaultSeed);
    else
        say("netrace: go, seed %08lx", (unsigned long)seed);
    bDefaultSeed = seed;
    // The patience stays: the race's first frame, its drawing's
    // preparation, stops each console's loop for seconds too. The race
    // gives the link its own back once every console's frames come in.
    R->stage = NR_RACING;
    if (R->game.goRacing) R->game.goRacing();
}

// The host's: every console racing and still on has loaded.
static void maybeGo(void)
{
    uint8_t m[4];
    int     p;

    for (p = 1; p < R->race.consoles; p++)
        if (R->driver[p] >= 0 && placeAlive(p) && !R->loaded[p]) return;
    R->seed = bDefaultSeed;
    m[0] = (uint8_t)R->seed;
    m[1] = (uint8_t)(R->seed >> 8);
    m[2] = (uint8_t)(R->seed >> 16);
    m[3] = (uint8_t)(R->seed >> 24);
    for (p = 1; p < R->race.consoles; p++)
        if (R->driver[p] >= 0 && placeAlive(p))
            R->net.send(R->race.peer[p], NETRACE_MSG_GO, m, sizeof m);
    start(R->seed);
}

// ------------------------------------------------------------ the build

// gFredNetRideFn: AI racer `ai`'s place, a player's. The players start
// behind the CPU racers and the two players, in the order of their places;
// the CPU racers, past them, take the front by performance as retail's do.
static int32_t aiRide(int32_t ai, RideInfo* ride, int32_t* startPos)
{
    if (ai < 0 || ai >= R->humanAI) return 0;
    *ride = R->cars[R->aiPlace[ai]].ride;
    ride->InstanceIndex      = 0;
    ride->CanBeVertexDamaged = 0;   // as retail's AI racers
    *startPos = R->race.cpu + 3 + ai;
    return 1;
}

static void pack(void)
{
    SetupHeader h;
    uint8_t*    s = R->setup;
    int         p, n = TheRaceParameters.NumDriverInfo;

    if (n < 0) n = 0;
    if (n > RACE_PARAMETERS_MAX_DRIVERS) n = RACE_PARAMETERS_MAX_DRIVERS;
    memset(&h, 0, sizeof h);
    h.magic[0]      = 'N';
    h.magic[1]      = 'R';
    h.version       = SETUP_VERSION;
    h.consoles      = (uint8_t)R->race.consoles;
    h.gameType      = Fred.GameType;
    h.numPlayerCars = Fred.NumPlayerCars;
    h.seed          = bDefaultSeed;
    memcpy(h.driver, R->driver, sizeof h.driver);
    h.rpSize        = (uint16_t)sizeof(RaceParameters);
    h.driverSize    = (uint16_t)sizeof(DriverInfo);
    h.eventSize     = (uint16_t)sizeof(RaceEvent);
    h.numDrivers    = (uint8_t)n;
    h.stateInEvent  = TheRaceEvent.pState == TheRaceEvent.aOldState;
    for (p = 0; p < R->race.consoles; p++)
        if (R->driver[p] >= 0) h.settings[p] = R->cars[p].settings;

    memcpy(s, &h, sizeof h);
    s += sizeof h;
    memcpy(s, &TheRaceParameters, sizeof(RaceParameters));
    s += sizeof(RaceParameters);
    memcpy(s, DriverInfoTable, (size_t)n * sizeof(DriverInfo));
    s += (size_t)n * sizeof(DriverInfo);
    memcpy(s, &TheRaceEvent, sizeof(RaceEvent));
    s += sizeof(RaceEvent);
    R->setupLen = (size_t)(s - R->setup);
}

static void sendSetup(int p)
{
    uint8_t m[WL_MSG_MAX];
    size_t  off;

    for (off = 0; off < R->setupLen; off += NETRACE_PIECE) {
        size_t n = R->setupLen - off;

        if (n > NETRACE_PIECE) n = NETRACE_PIECE;
        m[0] = (uint8_t)off;
        m[1] = (uint8_t)(off >> 8);
        m[2] = (uint8_t)R->setupLen;
        m[3] = (uint8_t)(R->setupLen >> 8);
        memcpy(m + 4, R->setup + off, n);
        if (!R->net.send(R->race.peer[p], NETRACE_MSG_SETUP, m, n + 4)) {
            say("netrace: the setup to place %d did not go", p);
            return;
        }
    }
}

// The host's: retail's StartRace with the first client as the second
// player and the rest in AI racers' places, the frontend's second player
// put back after, and what it made to every client racing.
static void build(BGameFlow* gf)
{
    RaceParameters* rp = &TheRaceParameters;
    RideInfo*       r1;
    RideInfo        keepRide;
    cPlayerSettings keepSettings;
    int             p, second = -1;

    for (p = 0; p < WIRELESS_MAX_CONSOLES; p++) R->driver[p] = -1;
    R->humanAI = 0;
    for (p = 1; p < R->race.consoles; p++) {
        if (!placeAlive(p) || !R->cars[p].in) continue;
        if (second < 0) {
            second       = p;
            R->driver[p] = 1;
        } else if (R->humanAI < NETRACE_MAX_HUMAN_AI) {
            R->aiPlace[R->humanAI] = p;
            R->driver[p]           = (int8_t)(100 + R->humanAI);
            R->humanAI++;
        }
    }
    if (second < 0) {
        lostAll(gf);
        return;
    }
    R->driver[0]        = 0;
    R->cars[0].settings = Fred.FrontendPlayers[0].mPlayerSettings;
    // The host's CPU racers and the players still on in AI racers' places,
    // the two players behind the CPU racers; a Lap Knockout's laps are one
    // fewer than the cars, as track select counts them.
    rp->NumAICars              = R->race.cpu + R->humanAI;
    rp->PlayerStartPosition[0] = (int8_t)(R->race.cpu + 1);
    rp->PlayerStartPosition[1] = (int8_t)(R->race.cpu + 2);
    if (Fred.GameType == 5)
        rp->NumLapsInRace = rp->NumAICars + rp->NumPlayerCars - 1;

    r1           = R->game.selectedRide(1);
    keepRide     = *r1;
    keepSettings = Fred.FrontendPlayers[1].mPlayerSettings;
    *r1          = R->cars[second].ride;
    Fred.FrontendPlayers[1].mPlayerSettings = R->cars[second].settings;
    gFredNetRideFn = aiRide;
    R->game.startRace();
    gFredNetRideFn = NULL;
    *r1 = keepRide;
    Fred.FrontendPlayers[1].mPlayerSettings = keepSettings;

    // The load's flow leaves the screen, its popup with it, this frame.
    R->stage = NR_LOADING;
    pack();
    say("netrace: built, track %d, %d drivers, %d players in AI places, "
        "seed %08lx, %u bytes", (int)rp->TrackNumber, (int)rp->NumDriverInfo,
        R->humanAI, (unsigned long)bDefaultSeed, (unsigned)R->setupLen);
    for (p = 1; p < R->race.consoles; p++)
        if (R->driver[p] >= 0) sendSetup(p);
}

// A client's: the host's race in place of this console's own. This
// console's display settings stay, but for the two cameras, which the
// race runs with.
static void take(BGameFlow* gf)
{
    SetupHeader            h;
    RaceParameters         rp;
    const uint8_t*         s = R->setup;
    tGlobalDisplaySettings own = Fred.DisplayOptionsData;
    EventTree*             tree  = TheRaceEvent.pTree;
    uint8_t*               state = TheRaceEvent.pState;
    size_t                 need = 0;
    int                    i, p;

    if (R->setupLen >= sizeof h) {
        memcpy(&h, s, sizeof h);
        need = sizeof h + h.rpSize + (size_t)h.numDrivers * h.driverSize
             + h.eventSize;
        memcpy(&rp, s + sizeof h, sizeof rp < R->setupLen - sizeof h
                                  ? sizeof rp : R->setupLen - sizeof h);
    }
    if (R->setupLen < sizeof h || h.magic[0] != 'N' || h.magic[1] != 'R'
        || h.version != SETUP_VERSION || h.consoles != R->race.consoles
        || h.rpSize != sizeof(RaceParameters)
        || h.driverSize != sizeof(DriverInfo)
        || h.eventSize != sizeof(RaceEvent)
        || h.numDrivers > RACE_PARAMETERS_MAX_DRIVERS
        || need != R->setupLen || rp.NumDriverInfo != h.numDrivers) {
        say("netrace: the setup is not this build's (%u bytes)",
            (unsigned)R->setupLen);
        backToLobby(gf, R->race.hostName);
        return;
    }

    s += sizeof h + sizeof(RaceParameters);
    TheRaceParameters                  = rp;
    TheRaceParameters.pDriverInfoTable = DriverInfoTable;
    own.JumpCams = rp.GlobalDisplaySettings.JumpCams;
    own.ZoneCams = rp.GlobalDisplaySettings.ZoneCams;
    TheRaceParameters.GlobalDisplaySettings = own;
    memcpy(DriverInfoTable, s, (size_t)h.numDrivers * sizeof(DriverInfo));
    s += (size_t)h.numDrivers * sizeof(DriverInfo);
    for (i = 0; i < h.numDrivers; i++)
        DriverInfoTable[i].pCharacterInfo = R->game.characterInfo
            ? R->game.characterInfo(DriverInfoTable[i].CharacterNumber)
            : NULL;
    memcpy(&TheRaceEvent, s, sizeof(RaceEvent));
    TheRaceEvent.pTree  = tree;
    TheRaceEvent.pState = h.stateInEvent ? TheRaceEvent.aOldState : state;
    Fred.GameType        = h.gameType;
    Fred.NumPlayerCars   = h.numPlayerCars;
    Fred.bRaceWasAborted = 0;
    bDefaultSeed         = h.seed;
    memcpy(R->driver, h.driver, sizeof R->driver);
    for (p = 0; p < WIRELESS_MAX_CONSOLES; p++)
        R->cars[p].settings = h.settings[p];

    R->stage = NR_LOADING;
    say("netrace: setup taken, track %d, %d drivers, driver %d, seed %08lx",
        (int)TheRaceParameters.TrackNumber, (int)h.numDrivers,
        R->driver[R->race.place], (unsigned long)h.seed);
    if (R->game.startLoading) R->game.startLoading();
}

static void setupPiece(BGameFlow* gf, const WlMsg* m)
{
    size_t off, total, n;

    if (m->len < 4) return;
    off   = (size_t)m->data[0] | (size_t)m->data[1] << 8;
    total = (size_t)m->data[2] | (size_t)m->data[3] << 8;
    n     = (size_t)m->len - 4;
    if (off == 0) {
        R->setupGot = 0;
        R->setupLen = total;
    }
    if (off != R->setupGot || total != R->setupLen
        || total > NETRACE_SETUP_MAX || off + n > total) {
        say("netrace: a setup piece out of place (%u of %u)", (unsigned)off,
            (unsigned)total);
        R->setupGot = R->setupLen = 0;
        return;
    }
    memcpy(R->setup + off, m->data + 4, n);
    R->setupGot = off + n;
    if (R->setupGot == R->setupLen) take(gf);
}

// ------------------------------------------------------------ the frame

static void hostRead(void)
{
    WlMsg m;
    int   p;

    for (p = 1; p < R->race.consoles; p++) {
        int peer = R->race.peer[p];

        if (peer < 0) continue;
        while (R->net.recv(peer, &m)) {
            switch (m.type) {
                case NETRACE_MSG_CAR:
                    if (m.len < 1 + sizeof(RideInfo) + sizeof(cPlayerSettings)
                        || R->stage > NR_WAIT)
                        break;
                    memcpy(&R->cars[p].ride, m.data + 1, sizeof(RideInfo));
                    memcpy(&R->cars[p].settings, m.data + 1 + sizeof(RideInfo),
                           sizeof(cPlayerSettings));
                    R->cars[p].in = 1;
                    say("netrace: place %d's car, type %d skin %d, "
                        "transmission %d", p, (int)R->cars[p].ride.Type,
                        (int)R->cars[p].ride.SkinNumber,
                        (int)R->cars[p].settings.TransmissionType);
                    break;
                case NETRACE_MSG_UNCAR:
                    if (R->stage > NR_WAIT) break;
                    R->cars[p].in = 0;
                    say("netrace: place %d took its car back", p);
                    break;
                case NETRACE_MSG_LOADED:
                    if (R->stage < NR_LOADING) break;
                    R->loaded[p] = 1;
                    say("netrace: place %d loaded", p);
                    break;
                default:
                    break;
            }
        }
    }
}

static void clientRead(BGameFlow* gf)
{
    WlMsg m;

    // Not past GO: what follows it is the race's.
    while (R->stage != NR_OFF && R->stage != NR_RACING
           && R->net.recv(0, &m)) {
        if (m.type == NETRACE_MSG_SETUP && R->stage <= NR_WAIT) {
            setupPiece(gf, &m);
        } else if (m.type == NETRACE_MSG_GO && m.len >= 4
                   && R->stage == NR_HOLD) {
            // Sent only once this console has said it held.
            R->seed = (uint32_t)m.data[0] | (uint32_t)m.data[1] << 8
                    | (uint32_t)m.data[2] << 16 | (uint32_t)m.data[3] << 24;
            start(R->seed);
        }
    }
}

void netrace_frame(BGameFlow* gf)
{
    if (R->stage == NR_OFF) return;
    // Only the lobby takes it down, its screen up.
    if (R->net.state && R->net.state() == WIRELESS_OFF) {
        say("netrace: the link is down");
        R->stage = NR_OFF;
        return;
    }
    // The race's messages are the race's (37d).
    if (R->stage == NR_RACING) return;
    if (R->host) hostRead();
    else clientRead(gf);
    if (R->stage == NR_OFF) return;
    noticeGone();

    switch (R->stage) {
        case NR_CARS:
        case NR_WAIT:
            if (!R->host && !placeAlive(0)) {
                backToLobby(gf, R->race.hostName);
                break;
            }
            if (R->host && clientsLeft() == 0) {
                lostAll(gf);
                break;
            }
            if (R->stage != NR_WAIT) break;
            if (R->host) {
                int p, ready = 1;
                for (p = 1; p < R->race.consoles; p++)
                    if (placeAlive(p) && !R->cars[p].in) ready = 0;
                if (ready) {
                    build(gf);
                    break;
                }
            }
            showWait(gf);
            break;

        case NR_HOLD:
            if (R->host) {
                maybeGo();
            } else if (!placeAlive(0)) {
                say("netrace: the host is gone; racing alone");
                start(bDefaultSeed);
            }
            break;

        default:
            break;
    }
}

// ------------------------------------------------------- the frontend's

void netrace_bind(NetRace* r)
{
    R = r ? r : &s_own;
}

void netrace_init(const NetRaceNet* net, const NetRaceGame* game,
                  NetRaceLogFn log)
{
    memset(R, 0, sizeof *R);
    if (net) R->net = *net;
    if (game) R->game = *game;
    R->log      = log;
    R->popup    = -1;
    R->lastGone = -1;
}

void netrace_begin(const LobbyRace* race)
{
    NetRaceNet   net  = R->net;
    NetRaceGame  game = R->game;
    NetRaceLogFn log  = R->log;
    int          p;

    memset(R, 0, sizeof *R);
    R->net      = net;
    R->game     = game;
    R->log      = log;
    R->popup    = -1;
    R->lastGone = -1;
    R->stage    = NR_CARS;
    R->race     = *race;
    R->host     = race->place == 0;
    for (p = 0; p < WIRELESS_MAX_CONSOLES; p++) R->driver[p] = -1;
    if (R->net.setPatience) R->net.setPatience(NETRACE_PATIENCE_MS);
    say("netrace: begin, place %d of %d", race->place, race->consoles);
    // The host's CPU racers, and the third to eighth consoles in AI racers'
    // places, so there are as many by track select (Lap Knockout counts
    // its laps there).
    if (R->host) {
        TheRaceParameters.NumAICars = race->cpu + race->consoles - 2;
        say("netrace: %d AI racers, %d CPU", (int)TheRaceParameters.NumAICars,
            race->cpu);
    }
}

int netrace_active(void)
{
    return R->stage != NR_OFF;
}

NetRaceStage netrace_stage(void)
{
    return R->stage;
}

int netrace_place(void)
{
    return R->race.place;
}

const LobbyRace* netrace_race(void)
{
    return &R->race;
}

int netrace_driver(int p)
{
    return p >= 0 && p < WIRELESS_MAX_CONSOLES ? R->driver[p] : -1;
}

int netrace_car_chosen(BGameFlow* gf)
{
    uint8_t   m[1 + sizeof(RideInfo) + sizeof(cPlayerSettings)];
    int       place = R->race.place;
    RideInfo* ride;

    if (R->stage != NR_CARS || R->host) return 0;
    if (!placeAlive(0)) {
        backToLobby(gf, R->race.hostName);
        return 1;
    }
    ride = R->game.selectedRide(0);
    m[0] = (uint8_t)place;
    memcpy(m + 1, ride, sizeof(RideInfo));
    memcpy(m + 1 + sizeof(RideInfo), &Fred.FrontendPlayers[0].mPlayerSettings,
           sizeof(cPlayerSettings));
    R->net.send(0, NETRACE_MSG_CAR, m, sizeof m);
    R->stage = NR_WAIT;
    say("netrace: car sent, type %d skin %d, transmission %d",
        (int)ride->Type, (int)ride->SkinNumber,
        (int)Fred.FrontendPlayers[0].mPlayerSettings.TransmissionType);
    bgf_change_to_screen(gf, NETRACE_SCREEN_NAME, 1);
    return 1;
}

int netrace_host_start(BGameFlow* gf)
{
    RideInfo* ride;
    int       p, ready = 1;

    if (R->stage != NR_CARS || !R->host) return 0;
    R->stage = NR_WAIT;
    ride     = R->game.selectedRide(0);
    say("netrace: the host's start, type %d skin %d, transmission %d",
        (int)ride->Type, (int)ride->SkinNumber,
        (int)Fred.FrontendPlayers[0].mPlayerSettings.TransmissionType);
    // With no client left the build goes back to the lobby.
    for (p = 1; p < R->race.consoles; p++)
        if (placeAlive(p) && !R->cars[p].in) ready = 0;
    if (ready) build(gf);
    else bgf_change_to_screen(gf, NETRACE_SCREEN_NAME, 1);
    return 1;
}

int netrace_hold(void)
{
    if (R->stage != NR_LOADING) return 0;
    R->stage = NR_HOLD;
    if (R->host) {
        say("netrace: loaded, holding for the rest");
    } else {
        uint8_t place = (uint8_t)R->race.place;

        R->net.send(0, NETRACE_MSG_LOADED, &place, 1);
        say("netrace: loaded, holding for the host");
    }
    return 1;
}

void netrace_end(void)
{
    if (R->stage != NR_RACING) return;
    R->stage = NR_OFF;
    if (R->net.setPatience) R->net.setPatience(NETRACE_PATIENCE_MS);
    say("netrace: the race is over; the lobby next");
    lobby_back_next();
}

// BACK on "Wireless Race": a client's car taken back and on to car
// select again; the host back to track select.
static void back(BGameFlow* gf)
{
    if (R->stage != NR_WAIT) return;
    R->stage = NR_CARS;
    if (!R->host) {
        uint8_t place = (uint8_t)R->race.place;

        R->net.send(0, NETRACE_MSG_UNCAR, &place, 1);
        say("netrace: back to car select");
    } else {
        say("netrace: back to track select");
    }
    bgf_move_back_screen(gf, 1);
}

void netrace_callback(BGameFlow* gf, BScreenMessage msg,
                      BScreenCallbackData* data)
{
    switch (msg) {
        case BMSG_SCREEN_ACTIVATE:
            R->message[0] = 0;
            showWait(gf);
            break;

        // Every way off the screen, the popup with it.
        case BMSG_SCREEN_UNACTIVATE:
            hidePopup(gf);
            break;

        case BMSG_POPUP_DISMISS:
            if (R->quiet) {
                if (data) data->noise = BSND_NONE;
                break;
            }
            R->popup = -1;
            if (data && data->param == A_BACK) {
                data->noise = BSND_MENU_CANCEL;
                back(gf);
            } else {
                if (data) data->noise = BSND_NONE;
                showWait(gf);
            }
            break;

        default:
            break;
    }
}
