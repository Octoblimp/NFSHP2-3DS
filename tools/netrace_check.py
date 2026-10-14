#!/usr/bin/env python3
"""Checks a local wireless race's setup (`3DS Files/source/netrace.c`).

TASKS 37c: from the lobby's Start, each console's car goes to the host,
the host builds the race with retail's StartRace and sends what it made
to every client, each console loads and holds, and the host's GO starts
them all on one seed. Nothing of retail's is ported here (the PS2's two
players shared one console), so there is no model to diff against.
tools/src/netrace_test.c runs up to eight consoles of it in one process,
each with its own flow, popups and copy of the game's globals, over a
fake link and a fake of StartRace and the load, and checks what each
shows, sends and ends with (the harness's header has the list):

  - two consoles; the host's start before the cars, A on its wait; a
    client's car taken back and sent again; the host back to track
    select; eight, six of them in AI racers' places;
  - a client gone before its car, while the host waits, while it loads;
    the only client gone, on the wait and on car select; the host gone
    while a client waits, picks its car, loads; a client leaving for the
    lobby;
  - Lap Knockout's event state; a setup from another build; French and
    names past ASCII; a console with no wireless race, which netrace
    leaves alone.

The harness prints "faults 0" after each scenario that holds and "total
faults 0" at the end. A mutant is caught only when the harness finds a
fault.

    python tools/netrace_check.py
    python tools/netrace_check.py --mutate [--only a,b]
"""
import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402

HARNESS = "tools/src/netrace_test.c"
NETRACE = "3DS Files/source/netrace.c"
SOURCES = [HARNESS, NETRACE,
           "3DS Files/source/portlang.c",
           "3DS Files/source/gameflow.c",
           "3DS Files/source/bpopup.c",
           "3DS Files/source/memcard.c",
           "3DS Files/source/banim.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]


def build_harness(tmp):
    return hostbuild.build(tmp, SOURCES, name="netrace_test")


def faults(lines):
    for ln in reversed(lines):
        if ln.startswith("total faults "):
            return int(ln.split()[2])
    return -1


def diff(base, got, quiet=False):
    """How badly `got` fails: its faults, or 1 for a transcript with no
    tally. 0 when the harness found nothing wrong."""
    n = faults(got)
    if n == 0:
        return 0
    if not quiet:
        for ln in got:
            if ln.startswith("  FAULT") or ln.startswith("scenario "):
                print(ln)
    return n if n > 0 else 1


# ============================================================= mutations

def M(name, before, after):
    return (name, NETRACE, before, after)


MUTATIONS = [
    # -- the places
    M("nr-fill-skip", "tmpl += 5;", "tmpl += 2;"),
    M("nr-alive-self", "    if (p == R->race.place) return 1;\n", ""),
    M("nr-alive-peer", "return peer >= 0 && R->net.peerAlive && "
      "R->net.peerAlive(peer);", "return peer >= 0;"),
    M("nr-name-latin1", "lobby_latin1(out, cap, R->net.peerName(peer));",
      "snprintf(out, cap, \"%s\", R->net.peerName(peer));"),
    M("nr-name-host", "p == 0 ? R->race.hostName : \"\"", "\"\""),
    M("nr-left", "for (p = 1; p < R->race.consoles; p++) n += placeAlive(p);",
      "for (p = 0; p < R->race.consoles; p++) n += placeAlive(p);"),
    M("nr-gone-once", "if (R->gone[p] || placeAlive(p)) continue;",
      "if (placeAlive(p)) continue;"),
    M("nr-gone-mark", "        R->gone[p]  = 1;\n", ""),
    M("nr-gone-client", "        if (!R->host && p != 0) continue;", ""),
    M("nr-gone-last", "        R->lastGone = p;\n", ""),
    # -- the popup
    M("nr-hide-guard", "    if (R->popup < 0) return;\n    R->quiet = 1;",
      "    R->quiet = 1;"),
    M("nr-hide-quiet", "    R->quiet = 1;\n    bpopup_dismiss", "    bpopup_dismiss"),
    M("nr-hide-index", "    R->quiet = 0;\n    R->popup = -1;", "    R->quiet = 0;"),
    M("nr-popup-cancel", "BPOPUP_HORIZONTAL | BPOPUP_CANCELABLE",
      "BPOPUP_HORIZONTAL"),
    M("nr-popup-parent", "cfg.parent         = gf->screen;",
      "cfg.parent         = NULL;"),
    M("nr-popup-memcard", "cfg.screen         = BPOPUP_SCREEN_MEMCARD;",
      "cfg.screen         = 0;"),
    M("nr-popup-title", "cfg.title          = PORTLANG_LOCAL_WIRELESS;",
      "cfg.title          = 0;"),
    M("nr-popup-stay", "cfg.buttonParam[0] = A_STAY;",
      "cfg.buttonParam[0] = A_BACK;"),
    M("nr-popup-cancelparam", "cfg.cancelParam    = A_BACK;",
      "cfg.cancelParam    = A_STAY;"),
    M("nr-popup-dismissparam", "cfg.dismissParam   = A_STAY;",
      "cfg.dismissParam   = A_BACK;"),
    M("nr-popup-joy", "cfg.joyPort        = -1;", "cfg.joyPort        = 0;"),
    # -- the wait
    M("nr-wait-stage", "if (R->stage != NR_WAIT) return;   // the screen's",
      "if (0) return;   // the screen's"),
    M("nr-wait-cars-text", "text(gf, PORTLANG_WAITING_FOR_CARS)",
      "text(gf, PORTLANG_WAITING_FOR_HOST)"),
    M("nr-wait-alive", "if (!placeAlive(p) || R->cars[p].in) continue;",
      "if (R->cars[p].in) continue;"),
    M("nr-wait-carin", "if (!placeAlive(p) || R->cars[p].in) continue;",
      "if (!placeAlive(p)) continue;"),
    M("nr-wait-at", "            strncat(msg, \"@\", sizeof msg - strlen(msg) - 1);\n",
      ""),
    M("nr-wait-host", "                 R->race.hostName);", "                 \"\");"),
    M("nr-wait-same", "if (R->popup >= 0 && !strcmp(msg, R->message)) return;",
      "if (R->popup >= 0) return;"),
    M("nr-wait-up", "if (R->popup >= 0 && !strcmp(msg, R->message)) return;",
      "if (!strcmp(msg, R->message)) return;"),
    M("nr-wait-say", "if (strcmp(msg, R->message)) say(\"netrace: wait %s\", msg);",
      "say(\"netrace: wait %s\", msg);"),
    # -- leaving
    M("nr-back-off", "    R->stage = NR_OFF;\n    if (R->net.setPatience) "
      "R->net.setPatience(0);\n", "    if (R->net.setPatience) "
      "R->net.setPatience(0);\n"),
    M("nr-back-patience", "    if (R->net.setPatience) R->net.setPatience(0);\n"
      "    lobby_notice_next", "    lobby_notice_next"),
    M("nr-back-notice", "    lobby_notice_next(PORTLANG_LINK_LOST, name);\n", ""),
    M("nr-back-name", "lobby_notice_next(PORTLANG_LINK_LOST, name);",
      "lobby_notice_next(PORTLANG_LINK_LOST, \"\");"),
    M("nr-back-walk", "if (!strcmp(gf->stack.names[k], LOBBY_SCREEN_NAME)) break;",
      "if (k == 0) break;"),
    M("nr-back-count", "        n++;\n        if (!strcmp(gf->stack.names[k], "
      "LOBBY_SCREEN_NAME)) break;", "        if (!strcmp(gf->stack.names[k], "
      "LOBBY_SCREEN_NAME)) break;\n        n++;"),
    M("nr-lostall-notice", "    noticeGone();   // one gone since this frame's look\n",
      ""),
    M("nr-lostall-name", "    placeName(R->lastGone, name, sizeof name);\n",
      "    name[0] = 0;\n"),
    # -- the start
    M("nr-start-seed", "    bDefaultSeed = seed;\n", ""),
    M("nr-start-stage", "    R->stage = NR_RACING;\n", ""),
    M("nr-start-go", "    if (R->game.goRacing) R->game.goRacing();\n", ""),
    M("nr-go-wait", "if (R->driver[p] >= 0 && placeAlive(p) && !R->loaded[p]) "
      "return;", "if (0) return;"),
    M("nr-go-wait-alive", "if (R->driver[p] >= 0 && placeAlive(p) && "
      "!R->loaded[p]) return;", "if (R->driver[p] >= 0 && !R->loaded[p]) "
      "return;"),
    M("nr-go-wait-driver", "if (R->driver[p] >= 0 && placeAlive(p) && "
      "!R->loaded[p]) return;", "if (placeAlive(p) && !R->loaded[p]) return;"),
    M("nr-go-seed", "    R->seed = bDefaultSeed;\n", ""),
    M("nr-go-bytes", "m[2] = (uint8_t)(R->seed >> 16);",
      "m[2] = (uint8_t)(R->seed >> 8);"),
    M("nr-go-alive", "        if (R->driver[p] >= 0 && placeAlive(p))\n"
      "            R->net.send", "        if (R->driver[p] >= 0)\n"
      "            R->net.send"),
    M("nr-go-start", "    start(R->seed);\n}", "}"),
    # -- the build
    M("nr-airide-range", "if (ai < 0 || ai >= R->humanAI) return 0;",
      "if (ai < 0) return 0;"),
    M("nr-airide-place", "*ride = R->cars[R->aiPlace[ai]].ride;",
      "*ride = R->cars[1 + ai].ride;"),
    M("nr-airide-instance", "    ride->InstanceIndex      = 0;\n", ""),
    M("nr-airide-damage", "    ride->CanBeVertexDamaged = 0;", ""),
    M("nr-airide-ret", "    ride->CanBeVertexDamaged = 0;   // as retail's AI "
      "racers\n    return 1;", "    ride->CanBeVertexDamaged = 0;   // as "
      "retail's AI racers\n    return 0;"),
    M("nr-pack-magic", "h.magic[0]      = 'N';", "h.magic[0]      = 'X';"),
    M("nr-pack-version", "h.version       = SETUP_VERSION;",
      "h.version       = 0;"),
    M("nr-pack-consoles", "h.consoles      = (uint8_t)R->race.consoles;",
      "h.consoles      = 0;"),
    M("nr-pack-gametype", "h.gameType      = Fred.GameType;",
      "h.gameType      = 0;"),
    M("nr-pack-players", "h.numPlayerCars = Fred.NumPlayerCars;",
      "h.numPlayerCars = 0;"),
    M("nr-pack-seed", "h.seed          = bDefaultSeed;", "h.seed          = 0;"),
    M("nr-pack-drivers", "memcpy(h.driver, R->driver, sizeof h.driver);",
      "memset(h.driver, 0, sizeof h.driver);"),
    M("nr-pack-state", "h.stateInEvent  = TheRaceEvent.pState == "
      "TheRaceEvent.aOldState;", "h.stateInEvent  = 0;"),
    M("nr-pack-settings", "if (R->driver[p] >= 0) h.settings[p] = "
      "R->cars[p].settings;", "if (p == 0) h.settings[p] = R->cars[p].settings;"),
    M("nr-pack-rp", "memcpy(s, &TheRaceParameters, sizeof(RaceParameters));",
      "memset(s, 0, sizeof(RaceParameters));"),
    M("nr-pack-table", "memcpy(s, DriverInfoTable, (size_t)n * sizeof(DriverInfo));",
      "memset(s, 0, (size_t)n * sizeof(DriverInfo));"),
    M("nr-pack-event", "memcpy(s, &TheRaceEvent, sizeof(RaceEvent));",
      "memset(s, 0, sizeof(RaceEvent));"),
    M("nr-piece-off", "m[1] = (uint8_t)(off >> 8);", "m[1] = 0;"),
    M("nr-piece-total", "m[3] = (uint8_t)(R->setupLen >> 8);", "m[3] = 0;"),
    M("nr-piece-size", "if (n > NETRACE_PIECE) n = NETRACE_PIECE;",
      "if (n > NETRACE_PIECE - 1) n = NETRACE_PIECE - 1;"),
    M("nr-build-second", "        if (second < 0) {\n            second       = p;",
      "        if (0) {\n            second       = p;"),
    M("nr-build-alive", "if (!placeAlive(p) || !R->cars[p].in) continue;",
      "if (!R->cars[p].in) continue;"),
    M("nr-build-lost", "    if (second < 0) {\n        lostAll(gf);\n",
      "    if (second < 0) {\n"),
    M("nr-build-host-settings", "R->cars[0].settings = "
      "Fred.FrontendPlayers[0].mPlayerSettings;",
      "R->cars[0].settings = Fred.FrontendPlayers[1].mPlayerSettings;"),
    M("nr-build-numai", "if (rp->NumAICars < R->humanAI) rp->NumAICars = "
      "R->humanAI;", "(void)0;"),
    M("nr-build-swap-ride", "    *r1          = R->cars[second].ride;\n", ""),
    M("nr-build-swap-set", "    Fred.FrontendPlayers[1].mPlayerSettings = "
      "R->cars[second].settings;\n", ""),
    M("nr-build-restore-ride", "    *r1 = keepRide;\n", ""),
    M("nr-build-restore-set", "    Fred.FrontendPlayers[1].mPlayerSettings = "
      "keepSettings;\n", ""),
    M("nr-build-hook", "    gFredNetRideFn = aiRide;\n", ""),
    M("nr-build-unhook", "    gFredNetRideFn = NULL;\n", ""),
    M("nr-build-stage", "    R->stage = NR_LOADING;\n    pack();", "    pack();"),
    M("nr-build-driver0", "    R->driver[0]        = 0;\n", ""),
    M("nr-build-send", "if (R->driver[p] >= 0) sendSetup(p);",
      "if (R->driver[p] == 1) sendSetup(p);"),
    # -- the take
    M("nr-take-version", "|| h.version != SETUP_VERSION || h.consoles",
      "|| h.consoles"),
    M("nr-take-back", "        backToLobby(gf, R->race.hostName);\n        return;\n"
      "    }\n\n    s += sizeof h", "        return;\n    }\n\n    s += sizeof h"),
    M("nr-take-ptr", "    TheRaceParameters.pDriverInfoTable = DriverInfoTable;\n",
      ""),
    M("nr-take-cams", "    own.JumpCams = rp.GlobalDisplaySettings.JumpCams;\n", ""),
    M("nr-take-zone", "    own.ZoneCams = rp.GlobalDisplaySettings.ZoneCams;\n", ""),
    M("nr-take-display", "    TheRaceParameters.GlobalDisplaySettings = own;\n", ""),
    M("nr-take-table", "memcpy(DriverInfoTable, s, (size_t)h.numDrivers * "
      "sizeof(DriverInfo));", "memset(DriverInfoTable, 0, (size_t)h.numDrivers "
      "* sizeof(DriverInfo));"),
    M("nr-take-chars", "        DriverInfoTable[i].pCharacterInfo = "
      "R->game.characterInfo\n", "        DriverInfoTable[i].pCharacterInfo = "
      "DriverInfoTable[i].pCharacterInfo; (void)R->game.characterInfo\n"),
    M("nr-take-tree", "    TheRaceEvent.pTree  = tree;\n", ""),
    M("nr-take-state-own", "TheRaceEvent.pState = h.stateInEvent ? "
      "TheRaceEvent.aOldState : state;", "TheRaceEvent.pState = state;"),
    M("nr-take-state-event", "TheRaceEvent.pState = h.stateInEvent ? "
      "TheRaceEvent.aOldState : state;",
      "TheRaceEvent.pState = TheRaceEvent.aOldState;"),
    M("nr-take-gametype", "    Fred.GameType        = h.gameType;\n", ""),
    M("nr-take-players", "    Fred.NumPlayerCars   = h.numPlayerCars;\n", ""),
    M("nr-take-aborted", "    Fred.bRaceWasAborted = 0;\n", ""),
    M("nr-take-seed", "    bDefaultSeed         = h.seed;\n", ""),
    M("nr-take-drivers", "    memcpy(R->driver, h.driver, sizeof R->driver);\n", ""),
    M("nr-take-settings", "        R->cars[p].settings = h.settings[p];",
      "        (void)0;"),
    M("nr-take-stage", "    R->stage = NR_LOADING;\n"
      "    say(\"netrace: setup taken", "    say(\"netrace: setup taken"),
    M("nr-take-load", "    if (R->game.startLoading) R->game.startLoading();\n",
      ""),
    M("nr-piece-len", "        R->setupGot = 0;\n        R->setupLen = total;\n",
      "        R->setupGot = 0;\n"),
    M("nr-piece-got", "    R->setupGot = off + n;\n", ""),
    M("nr-piece-early", "if (R->setupGot == R->setupLen) take(gf);",
      "if (R->setupGot >= NETRACE_PIECE) take(gf);"),
    # -- what comes in
    M("nr-car-in", "                    R->cars[p].in = 1;\n", ""),
    M("nr-car-ride", "memcpy(&R->cars[p].ride, m.data + 1, sizeof(RideInfo));",
      "memset(&R->cars[p].ride, 0, sizeof(RideInfo));"),
    M("nr-car-settings", "memcpy(&R->cars[p].settings, m.data + 1 + "
      "sizeof(RideInfo),", "memcpy(&R->cars[p].settings, m.data + 1,"),
    M("nr-uncar", "                    R->cars[p].in = 0;\n", ""),
    M("nr-loaded", "                    R->loaded[p] = 1;\n", ""),
    M("nr-client-racing-read", "    while (R->stage != NR_OFF && R->stage != "
      "NR_RACING\n           && R->net.recv(0, &m)) {",
      "    while (R->stage != NR_OFF && R->net.recv(0, &m)) {"),
    M("nr-go-decode", "| (uint32_t)m.data[2] << 16", "| (uint32_t)m.data[2] << 8"),
    M("nr-go-hold", "            start(R->seed);\n", ""),
    # -- the frame
    M("nr-frame-down", "if (R->net.state && R->net.state() == WIRELESS_OFF) {",
      "if (0) {"),
    M("nr-frame-off", "is down\");\n        R->stage = NR_OFF;\n",
      "is down\");\n"),
    M("nr-frame-racing", "    if (R->stage == NR_RACING) return;\n", ""),
    M("nr-client-lost", "            if (!R->host && !placeAlive(0)) {",
      "            if (0) {"),
    M("nr-host-lost", "            if (R->host && clientsLeft() == 0) {",
      "            if (0) {"),
    M("nr-wait-only", "            if (R->stage != NR_WAIT) break;\n", ""),
    M("nr-ready-alive", "                    if (placeAlive(p) && "
      "!R->cars[p].in) ready = 0;", "                    if (!R->cars[p].in) "
      "ready = 0;"),
    M("nr-ready-car", "                    if (placeAlive(p) && !R->cars[p].in) "
      "ready = 0;", "                    if (0) ready = 0;"),
    M("nr-frame-wait", "            showWait(gf);\n            break;\n\n"
      "        case NR_HOLD:", "            break;\n\n        case NR_HOLD:"),
    M("nr-hold-go", "                maybeGo();\n", ""),
    M("nr-hold-alone", "            } else if (!placeAlive(0)) {",
      "            } else if (0) {"),
    M("nr-hold-alone-seed", "                start(bDefaultSeed);",
      "                start(0);"),
    # -- the frontend's
    M("nr-begin-stage", "    R->stage    = NR_CARS;\n", ""),
    M("nr-begin-host", "R->host     = race->place == 0;", "R->host     = 0;"),
    M("nr-begin-drivers", "    for (p = 0; p < WIRELESS_MAX_CONSOLES; p++) "
      "R->driver[p] = -1;\n    if (R->net.setPatience)",
      "    if (R->net.setPatience)"),
    M("nr-begin-patience", "if (R->net.setPatience) "
      "R->net.setPatience(NETRACE_PATIENCE_MS);", "(void)0;"),
    M("nr-begin-ai", "if (R->host && TheRaceParameters.NumAICars < "
      "race->consoles - 2) {", "if (0) {"),
    M("nr-begin-ai-count", "TheRaceParameters.NumAICars = race->consoles - 2;",
      "TheRaceParameters.NumAICars = race->consoles - 1;"),
    M("nr-chosen-host", "if (R->stage != NR_CARS || R->host) return 0;",
      "if (R->stage != NR_CARS) return 0;"),
    M("nr-chosen-stage", "if (R->stage != NR_CARS || R->host) return 0;",
      "if (R->host) return 0;"),
    M("nr-chosen-lost", "    if (!placeAlive(0)) {\n        backToLobby(gf, "
      "R->race.hostName);\n        return 1;\n    }\n    ride",
      "    ride"),
    M("nr-chosen-settings", "&Fred.FrontendPlayers[0].mPlayerSettings,\n",
      "&Fred.FrontendPlayers[1].mPlayerSettings,\n"),
    M("nr-chosen-send", "    R->net.send(0, NETRACE_MSG_CAR, m, sizeof m);\n", ""),
    M("nr-chosen-wait", "    R->stage = NR_WAIT;\n    say(\"netrace: car sent",
      "    say(\"netrace: car sent"),
    M("nr-chosen-push", "    bgf_change_to_screen(gf, NETRACE_SCREEN_NAME, 1);\n"
      "    return 1;\n}\n\nint netrace_host_start",
      "    bgf_change_to_screen(gf, NETRACE_SCREEN_NAME, 0);\n"
      "    return 1;\n}\n\nint netrace_host_start"),
    M("nr-hoststart-host", "if (R->stage != NR_CARS || !R->host) return 0;",
      "if (R->stage != NR_CARS) return 0;"),
    M("nr-hoststart-wait", "    R->stage = NR_WAIT;\n    say(\"netrace: the host's",
      "    say(\"netrace: the host's"),
    M("nr-hoststart-ready", "        if (placeAlive(p) && !R->cars[p].in) ready = "
      "0;\n    if (ready) build(gf);", "        if (0) ready = 0;\n"
      "    if (ready) build(gf);"),
    M("nr-hoststart-push", "else bgf_change_to_screen(gf, NETRACE_SCREEN_NAME, 1);",
      "else bgf_change_to_screen(gf, NETRACE_SCREEN_NAME, 0);"),
    M("nr-hold-check", "if (R->stage != NR_LOADING) return 0;",
      "if (R->stage == NR_OFF) return 0;"),
    M("nr-hold-stage", "    R->stage = NR_HOLD;\n", ""),
    M("nr-hold-host", "    if (R->host) {\n        say(\"netrace: loaded, holding",
      "    if (0) {\n        say(\"netrace: loaded, holding"),
    M("nr-hold-send", "        R->net.send(0, NETRACE_MSG_LOADED, &place, 1);\n", ""),
    M("nr-back-guard", "    if (R->stage != NR_WAIT) return;\n    R->stage = NR_CARS;",
      "    R->stage = NR_CARS;"),
    M("nr-back-stage", "    if (R->stage != NR_WAIT) return;\n    R->stage = NR_CARS;",
      "    if (R->stage != NR_WAIT) return;"),
    M("nr-back-send", "        R->net.send(0, NETRACE_MSG_UNCAR, &place, 1);\n", ""),
    M("nr-back-move", "    bgf_move_back_screen(gf, 1);\n}", "}"),
    M("nr-cb-msg", "            R->message[0] = 0;\n", ""),
    M("nr-cb-unactivate-hide", "UNACTIVATE:\n            hidePopup(gf);\n",
      "UNACTIVATE:\n"),
    M("nr-cb-quiet", "            if (R->quiet) {", "            if (0) {"),
    M("nr-cb-quiet-noise", "                if (data) data->noise = BSND_NONE;\n"
      "                break;", "                break;"),
    M("nr-cb-index", "            R->popup = -1;\n            if (data && "
      "data->param == A_BACK) {", "            if (data && data->param == "
      "A_BACK) {"),
    M("nr-cb-back-noise", "data->noise = BSND_MENU_CANCEL;",
      "data->noise = BSND_NONE;"),
    M("nr-cb-back", "                back(gf);\n", ""),
    M("nr-cb-stay-noise", "                if (data) data->noise = BSND_NONE;\n"
      "                showWait(gf);", "                showWait(gf);"),
    M("nr-cb-stay", "                showWait(gf);\n            }\n",
      "            }\n"),
]

EQUIVALENT = {
    # bpopup_dismiss lets go of an index out of range.
    "nr-hide-guard",
    # The index is left only when the screen goes with its popup up, for
    # the load or the lobby; the race's popup is not summoned again, and
    # netrace_begin sets -1 for the next.
    "nr-hide-index",
    # Only bpopup_dismiss answers with it, and only hidePopup calls that,
    # quiet, where the answer is not read.
    "nr-popup-dismissparam",
    # Each caller is at NR_WAIT already: the screen comes up only from it,
    # A's dismiss is on it, and the frame calls it only there.
    "nr-wait-stage",
    # Once built every place still on drives: the build waits for every
    # car, and eight consoles fill at most the six AI racers' places.
    "nr-go-wait-driver",
    # A message to a place gone goes nowhere: wireless_pump ticks no link
    # of a peer it has lost, and the fake drops it.
    "nr-go-alive",
    # main.c's input comes before the link's pump and netrace_frame, so a
    # start or a car never finds a console gone that netrace_frame has not
    # already gone back to the lobby for; and in the harness, where it
    # can, the frame's look right after does the same.
    "nr-build-lost",
    "nr-chosen-lost",
    # Every console runs the same build, so the host's pointer is the same
    # static table.
    "nr-take-ptr",
    # BACK reaches back() only through the popup, which is up only at
    # NR_WAIT.
    "nr-back-guard",
    # A client never starts from car select: it comes through one of
    # Challenge's four setups, never the event trees' GameType 8 or 9, so
    # its car select goes on to Select Track, which netrace_car_chosen
    # takes.
    "nr-hoststart-host",
}


def run_harness(exe, out, timeout):
    return mutpar.run_exe([exe], out, timeout)


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        rc = run_harness(exe, out, 600)
        took = time.monotonic() - t0
        base = out.read_text(encoding="latin-1").splitlines()
        if rc != 0 or faults(base) != 0:
            print("base already fails -- fix that before mutating")
            return 1
        print("base: %d lines, 0 faults, %.1f s" % (len(base), took),
              flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "netrace_test",
        lambda exe, out: run_harness(exe, out, limit),
        base, diff, EQUIVALENT, jobs)
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="with --mutate, mutants at once (default %d)"
                    % mutpar.JOBS)
    ap.add_argument("--faults", action="store_true",
                    help="print only the scenarios, faults and tallies")
    args = ap.parse_args()
    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "out.txt"
        rc = run_harness(exe, out, 600)
        lines = out.read_text(encoding="latin-1").splitlines()
    sys.stdout.reconfigure(errors="backslashreplace")
    for ln in lines:
        if not args.faults or ln.startswith(("scenario ", "  FAULT",
                                             "faults ", "total faults ")):
            print(ln)
    sys.exit(1 if rc or faults(lines) != 0 else 0)


if __name__ == "__main__":
    main()
