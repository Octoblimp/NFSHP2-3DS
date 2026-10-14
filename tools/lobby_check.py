#!/usr/bin/env python3
"""Checks the Local Wireless lobby (`3DS Files/source/lobby.c`).

TASKS 37b: Players' "Local Wireless" goes to a screen of popups where a
console hosts a race or joins one, the host starts it, and every console
goes on to car select with the link up. Nothing of retail's is ported
here (the PS2 had two pads on one console), so there is no model to diff
against. tools/src/lobby_test.c runs the lobby with the flow and its
popups (gameflow.c, bpopup.c) over a scripted fake of the link and checks
what it shows and does each frame (the harness's header has the list):

  - B on the question, back from car select, and the lobby left some
    other way, take the link down;
  - a host with one client, none, seven that come and go, eight with one
    going to let the last in, one or both going as Start is pressed, one
    late; no wireless, no network, the network gone while hosting;
  - a joiner finding a race and started by it (after a message that is
    not a start), finding none, walking three with Next and scanning again
    past the last, going back after a Next, refused, the host lost,
    leaving, the race gone before Join;
  - French, no language chosen yet, and console names past ASCII, broken
    UTF-8 among them;
  - the host's CPU racers (TASKS 37c-2): a Full Grid, none counted on to
    six and round, five that fit fewer as consoles come and more as they
    go, eight consoles with no room and A on CPU Racers as the eighth
    comes, no choice, hosting again, French;
  - the console's wireless communication off (TASKS 62): on Host and on
    Join (UDS never asked to start), with UDS failing too, in French and
    with no language, turned on again; turned off while hosting,
    searching, on a race found and joined; on the frame of a press (Join,
    Next past the last, Start, B) before the network is seen to go; and
    during the race's setup, back in the lobby, against the race's own
    notice with it on.

The harness prints "faults 0" after each scenario that holds and "total
faults 0" at the end. A mutant is caught only when the harness finds a
fault: the transcript moves with any change at all, so a diff of it would
say nothing.

    python tools/lobby_check.py
    python tools/lobby_check.py --mutate [--only a,b]
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

HARNESS = "tools/src/lobby_test.c"
LOBBY = "3DS Files/source/lobby.c"
SOURCES = [HARNESS, LOBBY,
           "3DS Files/source/portlang.c",
           "3DS Files/source/gameflow.c",
           "3DS Files/source/bpopup.c",
           "3DS Files/source/memcard.c",
           "3DS Files/source/banim.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]


def build_harness(tmp):
    return hostbuild.build(tmp, SOURCES, name="lobby_test")


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
    return (name, LOBBY, before, after)


MUTATIONS = [
    # -- text
    M("lb-clock", "return gf->realTimer / 4;", "return gf->realTimer;"),
    M("lb-latin1-at", "if (c == '@' || c < 0x20", "if (c < 0x20"),
    M("lb-latin1-high", "|| c > 0xff)", ")"),
    M("lb-latin1-two", "else if ((*s & 0xe0) == 0xc0) { c = *s & 0x1f;",
      "else if ((*s & 0xe0) == 0xc0) { c = *s & 0x3f;"),
    M("lb-latin1-cont", "if ((*s & 0xc0) != 0x80) { c = '?'; break; }",
      "if (!*s) { c = '?'; break; }"),
    M("lb-fill-name", "            put  = name;\n            skip = 5;",
      "            put  = name;\n            skip = 2;"),
    M("lb-fill-order", "if (!strncmp(tmpl, \"$NAME\", 5)) {",
      "if (!strncmp(tmpl, \"$NAMEX\", 6)) {"),
    # -- the popup
    M("lb-popup-cancel", "| BPOPUP_CANCELABLE\n", "\n"),
    M("lb-popup-parent", "cfg.parent         = gf->screen;",
      "cfg.parent         = NULL;"),
    M("lb-popup-stay", "cfg.buttonParam[0] = buttons > 0 ? a0 : A_STAY;",
      "cfg.buttonParam[0] = a0;"),
    M("lb-popup-back", "cfg.cancelParam    = A_BACK;",
      "cfg.cancelParam    = A_STAY;"),
    M("lb-popup-start", "    cfg.startButton    = start;\n", ""),
    M("lb-hide-quiet", "    L.quiet = 1;\n    bpopup_dismiss", "    bpopup_dismiss"),
    M("lb-hide-index", "    L.quiet = 0;\n    L.popup = -1;\n",
      "    L.quiet = 0;\n"),
    # -- the link
    M("lb-down-off", "if (L.net.state() == WIRELESS_OFF) return;\n    L.net.leave();",
      "if (L.net.state() != WIRELESS_HOSTING) return;\n    L.net.leave();"),
    M("lb-down-stop", "    L.net.leave();\n    L.net.stop();\n",
      "    L.net.leave();\n"),
    M("lb-down-leave", "    L.net.leave();\n    L.net.stop();\n",
      "    L.net.stop();\n"),
    M("lb-alive", "n += L.net.peerAlive(i) != 0;", "n++;"),
    # -- asking
    M("lb-ask-down", "    linkDown();\n    hidePopup(gf);\n    L.state = LS_ASK;",
      "    hidePopup(gf);\n    L.state = LS_ASK;"),
    M("lb-ask-hide", "    linkDown();\n    hidePopup(gf);\n    L.state = LS_ASK;",
      "    linkDown();\n    L.state = LS_ASK;"),
    M("lb-notice-hide", "    hidePopup(gf);\n    L.state       = LS_NOTICE;",
      "    L.state       = LS_NOTICE;"),
    M("lb-notice-after", "            if (L.afterNotice == LS_SEARCHING) "
      "startSearching(gf, 0);", "            if (0) startSearching(gf, 0);"),
    # -- hosting
    M("lb-list-self", "    strncat(msg, \"@\", sizeof msg - strlen(msg) - 1);\n"
      "    strncat(msg, name, sizeof msg - strlen(msg) - 1);\n    for (i = 0;",
      "    for (i = 0;"),
    M("lb-list-alive", "        if (!L.net.peerAlive(i)) continue;\n"
      "        lobby_latin1(name", "        lobby_latin1(name"),
    M("lb-list-latin1", "lobby_latin1(name, sizeof name, L.net.peerName(i));",
      "snprintf(name, sizeof name, \"%s\", L.net.peerName(i));"),
    M("lb-list-same", "if (L.popup >= 0 && !strcmp(msg, L.message)) return;",
      "if (L.popup >= 0) return;"),
    M("lb-list-shown", "if (L.popup >= 0 && !strcmp(msg, L.message)) return;",
      "if (!strcmp(msg, L.message)) return;"),
    M("lb-list-say", "if (strcmp(msg, L.message)) say(\"lobby: list", "say(\"lobby: list"),
    M("lb-list-buttons", "showPopup(gf, clients > 0, PORTLANG_START",
      "showPopup(gf, 1, PORTLANG_START"),
    M("lb-host-fail-down", "        linkDown();\n        offNotice(gf);\n"
      "        return;\n    }\n    L.state   = LS_HOSTING;",
      "        offNotice(gf);\n        return;\n    }\n"
      "    L.state   = LS_HOSTING;"),
    M("lb-host-max", "L.net.host(WIRELESS_MAX_CONSOLES, NULL, 0)",
      "L.net.host(2, NULL, 0)"),
    M("lb-host-gone", "            if (L.net.state() != WIRELESS_HOSTING) {",
      "            if (0) {"),
    M("lb-forget", "if (clientsAlive() != L.net.peerCount()) L.net.forgetLost();",
      "(void)0;"),
    M("lb-start-alone", "    if (consoles < 2) {", "    if (consoles < 1) {"),
    M("lb-start-close", "    L.net.setOpen(0);\n", ""),
    M("lb-start-alive", "        if (!L.net.peerAlive(i)) continue;\n"
      "        msg[0]", "        msg[0]"),
    M("lb-start-count", "msg[0] = (uint8_t)consoles;",
      "msg[0] = (uint8_t)(consoles - 1);"),
    M("lb-start-place", "msg[1] = (uint8_t)++place;", "msg[1] = (uint8_t)place++;"),
    M("lb-start-send", "        L.net.send(i, LOBBY_MSG_START, msg, sizeof msg);\n",
      ""),
    # -- the CPU racers
    M("lb-cpu-wish", "L.cpuWant = L.cpuFn ? L.cpuFn() : LOBBY_CPU_NONE;",
      "L.cpuWant = L.cpuFn ? L.cpuFn() : 0;"),
    M("lb-cpu-wish-once", "    L.cpuWant = L.cpuFn ? L.cpuFn() : LOBBY_CPU_NONE;\n",
      "    if (!L.cpuWant) L.cpuWant = L.cpuFn ? L.cpuFn() : LOBBY_CPU_NONE;\n"),
    M("lb-cpu-oncpu-reset", "    L.onCpu   = 0;\n    say(\"lobby: hosting\");",
      "    say(\"lobby: hosting\");"),
    M("lb-cpu-room", "    int room = LOBBY_GRID - (clientsAlive() + 1);\n\n"
      "    if (room <= 0)", "    int room = LOBBY_GRID - clientsAlive();\n\n"
      "    if (room <= 0)"),
    M("lb-cpu-full", "    if (room <= 0) return -1;\n", ""),
    M("lb-cpu-fit", "return L.cpuWant < room ? L.cpuWant : room;",
      "return L.cpuWant;"),
    M("lb-cpu-line", "        strncat(msg, line, sizeof msg - strlen(msg) - 1);\n", ""),
    M("lb-cpu-line-n", "text(gf, PORTLANG_CPU_RACERS_N), \"\", cpu, 0);",
      "text(gf, PORTLANG_CPU_RACERS_N), \"\", L.cpuWant, 0);"),
    M("lb-cpu-alone", "    else if (clients == 0)\n        showPopup(gf, 1,",
      "    else if (0)\n        showPopup(gf, 1,"),
    M("lb-cpu-keep", "PORTLANG_CPU_RACERS, A_CPU,\n                  L.onCpu);",
      "PORTLANG_CPU_RACERS, A_CPU,\n                  0);"),
    M("lb-cpu-answer", "            else if (a == A_CPU) nextCpu(gf);\n", ""),
    M("lb-cpu-wrap", "L.cpuWant = cpu < room ? cpu + 1 : 0;",
      "L.cpuWant = cpu + 1;"),
    M("lb-cpu-wrap-edge", "L.cpuWant = cpu < room ? cpu + 1 : 0;",
      "L.cpuWant = cpu <= room ? cpu + 1 : 0;"),
    M("lb-cpu-on", "        L.onCpu   = 1;\n        say(\"lobby: cpu", "        say(\"lobby: cpu"),
    M("lb-cpu-filled", "    if (cpu >= 0) {   // not if", "    if (1) {   // not if"),
    M("lb-cpu-move", "                L.onCpu = data->itemHash == BPOPUP_OBJ_BUTTON2;",
      "                L.onCpu = data->itemHash == BPOPUP_OBJ_BUTTON1;"),
    M("lb-cpu-move-none", "        case BMSG_POPUP_NEXT:\n        case BMSG_POPUP_PREV:\n"
      "            if (L.state == LS_HOSTING && data)",
      "        case BMSG_POPUP_NEXT:\n        case BMSG_POPUP_PREV:\n"
      "            if (0)"),
    M("lb-cpu-start", "race.cpu = cpu > 0 ? cpu : 0;", "race.cpu = cpu;"),
    M("lb-cpu-start-want", "race.cpu = cpu > 0 ? cpu : 0;",
      "race.cpu = L.cpuWant > 0 ? L.cpuWant : 0;"),
    M("lb-cpu-start-say", "    if (cpu >= 0)\n        say(\"lobby: start, %d consoles, %d",
      "    if (0)\n        say(\"lobby: start, %d consoles, %d"),
    M("lb-gone-state", "    L.state = LS_GONE;\n", ""),
    M("lb-gone-push", "bgf_change_to_screen(gf, LOBBY_NEXT_SCREEN, 1);",
      "bgf_change_to_screen(gf, LOBBY_NEXT_SCREEN, 0);"),
    # -- searching
    M("lb-search-flag", "    L.scanned = justScanned;\n", ""),
    M("lb-scan-at", "    L.scanAt   = nowMs(gf);\n", ""),
    M("lb-scan-interval", "nowMs(gf) - L.scanAt < LOBBY_SCAN_MS) break;",
      "nowMs(gf) - L.scanAt < LOBBY_SCAN_MS / 4) break;"),
    M("lb-scan-scanned", "if (L.scanned && nowMs(gf)", "if (nowMs(gf)"),
    M("lb-found-first", "                L.hostIndex = 0;\n"
      "                showFound(gf, 0);", "                showFound(gf, 0);"),
    M("lb-found-on-next", "showFound(gf, 1);\n            } else if (a == A_BACK)",
      "showFound(gf, 0);\n            } else if (a == A_BACK)"),
    M("lb-next-wrap", "if (++L.hostIndex >= L.numHosts) {",
      "if (++L.hostIndex > L.numHosts) {"),
    M("lb-next-rescan", "                    if (scanNow(gf) == 0) {",
      "                    if (L.numHosts == 0) {"),
    M("lb-next-none", "                        startSearching(gf, 1);",
      "                        startSearching(gf, 0);"),
    M("lb-search-stay", "            if (a == A_BACK) toAsk(gf);\n"
      "            else showPopup(gf, 0, 0, 0, 0, 0, 0);\n            break;\n\n"
      "        case LS_FOUND:",
      "            if (a == A_BACK) toAsk(gf);\n"
      "            else startSearching(gf, 0);\n            break;\n\n"
      "        case LS_FOUND:"),
    # -- joining
    M("lb-join-index", "if (!L.net.join(h->scanIndex)) {",
      "if (!L.net.join(L.hostIndex)) {"),
    M("lb-join-after", "notice(gf, PORTLANG_JOIN_FAILED, L.hostName, LS_SEARCHING);",
      "notice(gf, PORTLANG_JOIN_FAILED, L.hostName, LS_ASK);"),
    M("lb-join-name", "lobby_latin1(L.hostName, sizeof L.hostName, h->name);",
      "snprintf(L.hostName, sizeof L.hostName, \"%s\", h->name);"),
    M("lb-recv-type", "if (m.type != LOBBY_MSG_START || m.len < 2) continue;",
      "if (m.len < 2) continue;"),
    M("lb-recv-goon", "                goOn(gf);\n                return;\n",
      "                return;\n"),
    M("lb-lost", "            if (L.net.state() != WIRELESS_CONNECTED) {",
      "            if (L.net.state() == WIRELESS_OFF) {"),
    M("lb-lost-down", "                say(\"lobby: lost %s\", L.hostName);\n"
      "                linkDown();\n",
      "                say(\"lobby: lost %s\", L.hostName);\n"),
    M("lb-joined-back", "            if (a == A_BACK) toAsk(gf);\n"
      "            else showPopup(gf, 0, 0, 0, 0, 0, 0);\n            break;\n\n"
      "        default:",
      "            showPopup(gf, 0, 0, 0, 0, 0, 0);\n            break;\n\n"
      "        default:"),
    # -- the screen
    M("lb-back", "                L.state = LS_OFF;\n"
      "                bgf_move_back_screen(gf, 1);\n",
      "                L.state = LS_OFF;\n"),
    M("lb-activate", "                break;\n            }\n            toAsk(gf);\n",
      "                break;\n            }\n"),
    M("lb-unactivate", "            if (L.state != LS_GONE) {",
      "            if (1) {"),
    M("lb-unactivate-down", "                hidePopup(gf);\n"
      "                linkDown();\n            }",
      "                hidePopup(gf);\n            }"),
    M("lb-quiet-noise", "                if (data) data->noise = BSND_NONE;\n"
      "                break;", "                break;"),
    M("lb-back-noise", "if (data->param == A_BACK) data->noise = BSND_MENU_CANCEL;",
      "if (0) data->noise = BSND_MENU_CANCEL;"),
    M("lb-stay-noise", "else if (data->param == A_STAY) data->noise = BSND_NONE;",
      "else if (0) data->noise = BSND_NONE;"),
    M("lb-dismiss-index", "            L.popup = -1;\n            if (data) {",
      "            if (data) {"),
    # -- the console's wireless off (TASKS 62)
    M("lb-radio-never", "return L.net.radioOff && L.net.radioOff();",
      "return 0;"),
    M("lb-radio-host", "if (radioOff() || !L.net.start()) {",
      "if (!L.net.start()) {"),
    M("lb-radio-join", "if (!radioOff() && L.net.start())",
      "if (L.net.start())"),
    M("lb-radio-line", "    if (radioOff()) {\n        say(", "    if (0) {\n        say("),
    M("lb-radio-say", "        say(\"lobby: wireless communication off\");\n", ""),
    M("lb-radio-id", "notice(gf, PORTLANG_WIRELESS_DISABLED, \"\", LS_ASK);",
      "notice(gf, PORTLANG_WIRELESS_OFF, \"\", LS_ASK);"),
    M("lb-radio-after", "notice(gf, PORTLANG_WIRELESS_DISABLED, \"\", LS_ASK);",
      "notice(gf, PORTLANG_WIRELESS_DISABLED, \"\", LS_SEARCHING);"),
    M("lb-radio-hosting", "if (L.state != LS_HOSTING && L.state != LS_SEARCHING",
      "if (L.state != LS_SEARCHING"),
    M("lb-radio-searching", " && L.state != LS_SEARCHING\n", "\n"),
    M("lb-radio-found", "        && L.state != LS_FOUND && L.state != LS_JOINED)",
      "        && L.state != LS_JOINED)"),
    M("lb-radio-joined", "        && L.state != LS_FOUND && L.state != LS_JOINED)",
      "        && L.state != LS_FOUND)"),
    M("lb-radio-went-down", "    if (!radioOff()) return 0;\n    linkDown();\n",
      "    if (!radioOff()) return 0;\n"),
    M("lb-radio-tick", "    if (radioWent()) {\n        offNotice(gf);\n"
      "        return;\n    }\n", ""),
    M("lb-radio-press", "if (a != A_BACK && radioWent()) {", "if (0) {"),
    M("lb-radio-press-back", "if (a != A_BACK && radioWent()) {",
      "if (radioWent()) {"),
    M("lb-radio-return", "                if (radioOff()) offNotice(gf);\n"
      "                else notice(gf, id, L.nextName, LS_ASK);\n",
      "                notice(gf, id, L.nextName, LS_ASK);\n"),
    M("lb-radio-return-on", "                if (radioOff()) offNotice(gf);\n"
      "                else notice(gf, id, L.nextName, LS_ASK);\n",
      "                offNotice(gf);\n"),
]

EQUIVALENT = {
    # A two-byte lead is 110xxxxx: its bit 5 is clear, so 0x3f masks it as
    # 0x1f does.
    "lb-latin1-two",
    # Every hidePopup is followed by a showPopup, which sets the index, or
    # by the lobby leaving its screen, whose next ACTIVATE resets it.
    "lb-hide-index",
    # toAsk is entered only from a dismiss (the popup already down and its
    # index -1) or from ACTIVATE (which sets -1 first): nothing to hide.
    "lb-ask-hide",
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
        todo, SOURCES, "lobby_test",
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
        print(ln)
    sys.exit(1 if rc or faults(lines) != 0 else 0)


if __name__ == "__main__":
    main()
