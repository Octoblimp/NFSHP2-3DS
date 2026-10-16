#!/usr/bin/env python3
"""Checks a local wireless race in lockstep (`3DS Files/source/netstep.c`).

TASKS 37d: from GO on, each console sends its pad for the frame
NETSTEP_DELAY ahead, the host puts every place's pad and its own step
into each frame's record and sends the records on, and every console runs
each frame on its record alone. Nothing of retail's is ported here (the
PS2's two players shared one console), so there is no model to diff
against. tools/src/netstep_test.c runs up to eight consoles of it in one
process over a fake link that loses, repeats and reorders, and checks
each record each console runs (the harness's header has the list):

  - two consoles on a clean link, a lossy one, a slow one and one slower
    than the delay; the host slow, the client slow, the client's GO
    late, the first frame's drawing stalling each for seconds; eight on
    a lossy link;
  - a client gone, of two and of three; the host gone, of two and of
    three; every client gone; a second with nothing through;
  - a checksum that differs, the host as fast and slower, and the
    NetStepDifferFn told of each, as the line says (37e); a place not
    racing; junk of netstep's own types on the race's link, its lengths
    off;
  - the end (37f): every console stopping on the same frame, on a clean
    link, a lossy one, the host or the client slow, eight at once; a
    loop held seconds after its stop (the save); a client gone, the link
    out at the stop, a console's link lost at its stop; the lobby's
    message after the stop, at once or seconds on, never read by
    netstep; the parted ends (the host's stop alone, the client's
    alone, the client's first, the host's lobby before the client's
    stop); the client's stop unheard, given up on or heard by its
    lobby's message;
  - the hold (37g): a console lost holds every console for the hold,
    then is built without (a client, of two and of three, on a lossy
    link), each line and netstep_held checked every ms against it; a
    place gone at the start, and the host gone at the start, not held
    for; a client's loop frozen 6 s and 2 s, the host's 5 s, place 2's
    5 s on a lossy link; place 2 lost to the host and then the host
    lost while it holds, the client held on its word, then for it, then
    alone; nothing sent over a lost link;
  - back (37g-2): a client's link cut, each end on, re-peered in the hold
    and the race on from the frame it held on; re-peered as the client's
    hold ends, the host's word waited for past it; the rejoin half up
    (the client sees the host, the host never sees it), the client alone
    once it has waited; the rejoin up at the host's end alone, no pad
    ever from it (a console restarted), gone once the host has waited
    past the hold; the link cut twice, back each time; the rejoin too
    late; two links cut at once, back one after the other; place 2's on
    a lossy link;
  - a restart (37g-3): a client's console off mid-race, its link and its
    netstep gone, back in from its menus while the host holds for it,
    loading, then running the race again from frame 0 on the host's
    records kept since GO, undrawn while they are well ahead, the race
    held until it has caught up: of two, of three on a lossy link, of
    eight, and of eight on a link slower than a burst's gap, caught up
    in time; both clients, one caught up while the other loads; the same
    one twice; place 2 gone first, its records with it and then without;
    a load most of the hold, junk pads on the link while it loads; late
    in the race, most of the records kept; the host gone while it is
    still behind; too late, gone after the hold; past the records kept
    (the history 16 KB here), refused. The pads change between the keys
    of the records kept, in their presses or their last byte alone.
    netstep_rejoining checked every ms against the log
    on the host and the host's word on a client; the host's messages to
    a place catching up NETSTEP_BURST at a time, never past the ring it
    has, nor any to one loading, whose netrace's word netstep leaves on
    the link; caught up on the frame held on, its pad for it put.

The harness prints "faults 0" after each scenario that holds and "total
faults 0" at the end. A mutant is caught only when the harness finds a
fault.

    python tools/netstep_check.py
    python tools/netstep_check.py --mutate [--only a,b]
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

HARNESS = "tools/src/netstep_test.c"
NETSTEP = "3DS Files/source/netstep.c"
SOURCES = [HARNESS, NETSTEP]
# The history of records in 256-byte blocks, 16 KB in all (37g-3): records
# across blocks, and eight consoles' race that outruns it.
FLAGS = hostbuild.FLAGS + ["-DNETSTEP_HIST_BLOCK=256", "-DNETSTEP_HIST_MAX=64"]


def build_harness(tmp):
    return hostbuild.build(tmp, SOURCES, name="netstep_test", flags=FLAGS)


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
    return (name, NETSTEP, before, after)


MUTATIONS = [
    # -- the wire
    M("ns-put32-byte1", "    b[1] = (uint8_t)(v >> 8);\n", "    b[1] = 0;\n"),
    M("ns-get32-byte1", "(uint32_t)b[1] << 8", "(uint32_t)b[1] << 9"),
    M("ns-bits", "for (; v; v &= (uint8_t)(v - 1)) n++;",
      "for (; v; v >>= 1) n++;"),
    M("ns-rest-buttons", "    pad->ds2[0] = 0xff;   // no button down",
      "    pad->ds2[0] = 0x00;   // no button down"),
    M("ns-rest-stick", "    pad->ds2[5] = 0x80;\n", "    pad->ds2[5] = 0x7f;\n"),
    M("ns-rest-menu", "    pad->menu   = 0;\n", "    pad->menu   = 1;\n"),
    M("ns-padin", "return S->padFor[p][n & MASK] == n;",
      "return S->padFor[p][n & MASK] != NETSTEP_NONE;"),
    M("ns-recin", "return S->recs[n & MASK].n == n;",
      "return S->recs[n & MASK].n != NETSTEP_NONE;"),
    M("ns-alive", "return S->net.peerAlive(S->peer[p]);", "return 1;"),
    M("ns-encode-ds2", "    memcpy(b, pad->ds2, NETSTEP_PAD_BYTES);\n    b[6]",
      "    memcpy(b, pad->ds2, NETSTEP_PAD_BYTES - 1);\n    b[6]"),
    M("ns-encode-menu", "    b[7] = (uint8_t)(pad->menu >> 8);\n",
      "    b[7] = 0;\n"),
    M("ns-decode-ds2", "    memcpy(pad->ds2, b, NETSTEP_PAD_BYTES);\n",
      "    memcpy(pad->ds2, b, NETSTEP_PAD_BYTES - 1);\n"),
    M("ns-decode-menu", "pad->menu = (uint16_t)(b[6] | b[7] << 8);",
      "pad->menu = (uint16_t)b[6];"),
    # -- the records
    M("ns-build-q", "    r->q    = q;\n", "    r->q    = NETSTEP_Q_FIRST;\n"),
    M("ns-build-live", "    r->live = live;\n", "    r->live = 0xff;\n"),
    M("ns-build-padin", "if (((live >> p) & 1) && padIn(p, n))",
      "if ((live >> p) & 1)"),
    M("ns-build-rest", "        else\n            netstep_rest(&r->pad[p]);",
      "        else\n            memset(&r->pad[p], 0, sizeof r->pad[p]);"),
    M("ns-build-n", "    r->n = n;\n}", "    r->n = n + 1;\n}"),
    M("ns-hostbuild-wait",
      "if (((S->live >> p) & 1) && !padIn(p, n)) return;",
      "if (p == S->place && !padIn(p, n)) return;"),
    M("ns-hostbuild-q", "buildRecord(n, S->live, S->q[n & MASK]);",
      "buildRecord(n, S->live, NETSTEP_Q_FIRST);"),
    M("ns-hostbuild-fresh",
      "        for (p = 0; p < NETSTEP_MAX; p++) S->fresh[p] = 1;\n", ""),
    M("ns-alone-q", "buildRecord(S->built, S->live, S->q[S->built & MASK]);",
      "buildRecord(S->built, S->live, NETSTEP_Q_FIRST);"),
    # -- checksums
    M("ns-puthash-frame", "    put32(b, last);\n", "    put32(b, S->frame);\n"),
    M("ns-puthash-hi", "    b[5] = (uint8_t)(S->hash[last & MASK] >> 8);\n",
      "    b[5] = 0;\n"),
    M("ns-check-theirs", "S->theirFor[p][i] != n || ", ""),
    M("ns-check-ran", " || S->hashFor[i] != n || S->differs[p]",
      " || S->differs[p]"),
    M("ns-check-once", " || S->differs[p]\n        || (S->alone",
      "\n        || (S->alone"),
    M("ns-check-alone", "\n        || (S->alone && n >= S->aloneFrom))", ")"),
    M("ns-check-cmp", "if (S->theirHash[p][i] == S->hash[i]) return;",
      "if (S->theirHash[p][i] != S->hash[i]) return;"),
    M("ns-check-mark", "    S->differs[p] = 1;\n", ""),
    M("ns-check-tell", "    if (S->differ) S->differ(p, n);\n", ""),
    M("ns-check-tell-place", "S->differ(p, n);", "S->differ(S->place, n);"),
    M("ns-check-tell-frame", "S->differ(p, n);", "S->differ(p, n - 1);"),
    M("ns-takehash-none", "    if (n == NETSTEP_NONE) return;   // none run yet\n",
      ""),
    M("ns-takehash-hi",
      "S->theirHash[p][n & MASK] = (uint16_t)(b[4] | b[5] << 8);",
      "S->theirHash[p][n & MASK] = (uint16_t)b[4];"),
    M("ns-takehash-for", "    S->theirFor[p][n & MASK]  = n;\n", ""),
    M("ns-takehash-check", "    checkHash(p, n);\n}", "}"),
    # -- the host's
    M("ns-takepads-len",
      "if (m->len != HEADER + (size_t)count * PAD_WIRE) return 0;",
      "if (m->len < HEADER) return;"),
    M("ns-takepads-first", "    first = get32(d + 4);\n    stop  = get32(d + 15);",
      "    first = get32(d + 4) + 1;\n    stop  = get32(d + 15);"),
    M("ns-takepads-need", "    if (need > S->need[p]) S->need[p] = need;\n",
      ""),
    M("ns-takepads-hash", "    takeHash(p, d + 9);\n", ""),
    M("ns-takepads-pad",
      "decodePad(&S->pads[p][n & MASK], d + HEADER + (size_t)i * PAD_WIRE);",
      "decodePad(&S->pads[p][n & MASK], d + HEADER);"),
    M("ns-takepads-mark", "        S->padFor[p][n & MASK] = n;\n", ""),
    M("ns-sendframes-need",
      "    put32(b, S->built);\n    put32(b + 4, first);\n"
      "    for (n = first; n < end; n++) {",
      "    put32(b, S->built + 1);\n    put32(b + 4, first);\n"
      "    for (n = first; n < end; n++) {"),
    M("ns-sendframes-first",
      "    put32(b + 4, first);\n    for (n = first; n < end; n++) {",
      "    put32(b + 4, first + 1);\n    for (n = first; n < end; n++) {"),
    M("ns-sendframes-fit", "        if (o + size > WL_MSG_MAX) break;\n", ""),
    M("ns-sendframes-q", "        b[o++] = r->q;\n",
      "        b[o++] = NETSTEP_Q_FIRST;\n"),
    M("ns-sendframes-live", "        b[o++] = r->live;\n",
      "        b[o++] = 0xff;\n"),
    M("ns-sendframes-skip",
      "            if (!((r->live >> q) & 1)) continue;\n", ""),
    M("ns-sendframes-count",
      "    b[8] = (uint8_t)count;\n    putHash(b + 9);\n"
      "    put32(b + 15, S->stopAt);\n    b[19] = hostHeld(",
      "    b[8] = (uint8_t)(count ? count - 1 : 0);\n    putHash(b + 9);\n"
      "    put32(b + 15, S->stopAt);\n    b[19] = hostHeld("),
    M("ns-sendframes-hash",
      "    putHash(b + 9);\n    put32(b + 15, S->stopAt);\n"
      "    b[19] = hostHeld(",
      "    memset(b + 9, 0xff, 6);\n    put32(b + 15, S->stopAt);\n"
      "    b[19] = hostHeld("),
    M("ns-sendframes-stop",
      "    put32(b + 15, S->stopAt);\n    b[19] = hostHeld(",
      "    put32(b + 15, NETSTEP_NONE);\n    b[19] = hostHeld("),
    M("ns-sendframes-held", "    b[19] = hostHeld(now, &left);\n",
      "    b[19] = 0;\n    (void)hostHeld(now, &left);\n"),
    M("ns-sendframes-heldleft", "b[20] = (uint8_t)((left + 999) / 1000);",
      "b[20] = (uint8_t)(left / 1000);"),
    M("ns-sendframes-type",
      "S->net.send(S->peer[p], NETSTEP_MSG_FRAMES, b, o)",
      "S->net.send(S->peer[p], NETSTEP_MSG_PADS, b, o)"),
    M("ns-sendframes-last", "    S->lastSend[p] = now;\n", ""),
    M("ns-sendframes-fresh", "    S->fresh[p]    = 0;\n", ""),
    M("ns-serving-live", "return p != S->place && ((S->live >> p) & 1) && ",
      "return p != S->place && "),
    M("ns-serving-left", " && !S->left[p] && alive(p);", " && alive(p);"),
    M("ns-serving-alive", " && !S->left[p] && alive(p);", " && !S->left[p];"),
    M("ns-hostread-type",
      "            if (m.type != NETSTEP_MSG_PADS) {\n"
      "                if (S->lost[p]) break;",
      "            if (0) {\n                if (S->lost[p]) break;"),
    M("ns-hostread-lost", "                if (S->lost[p]) break;\n", ""),
    M("ns-hostread-goneon",
      "                S->left[p] = 1;\n                say(\"netstep: place %d has gone on",
      "                say(\"netstep: place %d has gone on"),
    M("ns-hostpoll-left",
      "        if (S->left[p]) {\n            say(\"netstep: place %d left",
      "        if (0) {\n            say(\"netstep: place %d left"),
    M("ns-hostpoll-alive", "        } else if (alive(p) && !S->lost[p]) {",
      "        } else if (!S->lost[p]) {"),
    M("ns-hostpoll-drop", "        S->live &= (uint8_t)~(1u << p);\n", ""),
    M("ns-hostpoll-build", "    from = S->built;\n    hostBuild();\n",
      "    from = S->built;\n"),
    M("ns-hostpoll-sendlive",
      "if (p == S->place || !((S->live >> p) & 1)\n"
      "            || (S->lost[p] && (!alive(p) || S->rejoin[p] == 1)))",
      "if (p == S->place\n"
      "            || (S->lost[p] && (!alive(p) || S->rejoin[p] == 1)))"),
    # -- the hold (37g)
    M("ns-start-hold", "    S->holdMs = holdMs;\n", ""),
    M("ns-poll-polled", "    S->polled = 1;\n", ""),
    M("ns-hostpoll-polled", "        } else if (!S->polled) {",
      "        } else if (0) {"),
    M("ns-hostpoll-lostmark",
      "            S->lost[p]   = 1;\n            S->back[p]   = 0;\n",
      "            S->back[p]   = 0;\n"),
    M("ns-hostpoll-lostat",
      "            S->lostAt[p] = now;\n            say(\"netstep: place %d lost",
      "            say(\"netstep: place %d lost"),
    M("ns-hostpoll-hold",
      "                   < S->holdMs + (alive(p) ? NETSTEP_BACK_MS : 0)) {",
      "                   < S->holdMs / 2 + (alive(p) ? NETSTEP_BACK_MS : 0)) {"),
    M("ns-hostpoll-sendlost",
      "            || (S->lost[p] && (!alive(p) || S->rejoin[p] == 1)))\n",
      "            || 0)\n"),
    M("ns-hostheld-left",
      "        since = since < S->holdMs ? S->holdMs - since : 0;\n",
      "        since = S->holdMs;\n"),
    M("ns-hostheld-min", "if (!mask || since < left) left = since;",
      "left = since;"),
    M("ns-hostheld-mark",
      "if (!mask || since < left) left = since;\n"
      "        mask |= (uint8_t)(1u << p);\n",
      "if (!mask || since < left) left = since;\n"),
    M("ns-hostpoll-resend",
      "        } else if (S->fresh[p] || now - S->lastSend[p] >= "
      "NETSTEP_RESEND_MS) {",
      "        } else if (S->fresh[p]) {"),
    M("ns-hostpoll-fresh",
      "        } else if (S->fresh[p] || now - S->lastSend[p] >= "
      "NETSTEP_RESEND_MS) {",
      "        } else if (now - S->lastSend[p] >= NETSTEP_RESEND_MS) {"),
    # -- the host's end
    M("ns-hostdrain-read",
      "    hostRead();\n    for (p = 0; p < NETSTEP_MAX; p++) {\n"
      "        if (!serving(p)) continue;\n        waiting = p;",
      "    for (p = 0; p < NETSTEP_MAX; p++) {\n"
      "        if (!serving(p)) continue;\n        waiting = p;"),
    M("ns-hostdrain-send",
      "        waiting = p;\n        if (S->fresh[p] || now - S->lastSend[p]"
      " >= NETSTEP_RESEND_MS)\n"
      "            sendFrames(p, S->need[p], S->built, now);\n",
      "        waiting = p;\n"),
    M("ns-hostdrain-resend",
      "        waiting = p;\n        if (S->fresh[p] || now - S->lastSend[p]"
      " >= NETSTEP_RESEND_MS)",
      "        waiting = p;\n        if (S->fresh[p])"),
    M("ns-hostdrain-done",
      "        S->ending = 0;\n        say(\"netstep: every client stopped",
      "        say(\"netstep: every client stopped"),
    M("ns-hostdrain-limit", "now - S->endFrom >= NETSTEP_DRAIN_MS",
      "now - S->endFrom >= 1000"),
    M("ns-hostdrain-giveup",
      "        S->ending = 0;\n        say(\"netstep: place %d never said",
      "        say(\"netstep: place %d never said"),
    M("ns-takepads-stop", "    if (stop != NETSTEP_NONE && !S->left[p]) {",
      "    if (0) {"),
    M("ns-takepads-left",
      "        S->left[p] = 1;\n        say(\"netstep: place %d stopped after",
      "        say(\"netstep: place %d stopped after"),
    # -- a client's
    M("ns-takeframes-walk",
      "        o += 2 + (size_t)bits(d[o + 1]) * PAD_WIRE;\n",
      "        o += 2;\n"),
    M("ns-takeframes-len", "    if (i < count || o != m->len) return 0;\n", ""),
    M("ns-takeframes-first",
      "    first = get32(d + 4);\n    if (need > S->padNeed)",
      "    first = get32(d + 4) + 1;\n    if (need > S->padNeed)"),
    M("ns-takeframes-padneed",
      "    if (need > S->padNeed) S->padNeed = need;\n", ""),
    M("ns-takeframes-hash", "    takeHash(0, d + 9);\n", ""),
    M("ns-takeframes-q", "        r.q    = d[o];\n",
      "        r.q    = NETSTEP_Q_FIRST;\n"),
    M("ns-takeframes-live", "        r.live = d[o + 1];\n",
      "        r.live = (uint8_t)(d[o + 1] & 0x7f);\n"),
    M("ns-takeframes-rest",
      "            } else {\n                netstep_rest(&r.pad[p]);\n"
      "            }",
      "            }"),
    M("ns-takeframes-n", "        r.n = n;\n", "        r.n = n + 1;\n"),
    M("ns-takeframes-built", "    while (recIn(S->built)) S->built++;\n", ""),
    M("ns-takeframes-built-once", "    while (recIn(S->built)) S->built++;",
      "    if (recIn(S->built)) S->built++;"),
    M("ns-sendpads-need",
      "    put32(b, S->built);\n    put32(b + 4, first);\n"
      "    for (n = first; n < end && o",
      "    put32(b, S->built + 1);\n    put32(b + 4, first);\n"
      "    for (n = first; n < end && o"),
    M("ns-sendpads-first",
      "    put32(b + 4, first);\n    for (n = first; n < end && o",
      "    put32(b + 4, first + 1);\n    for (n = first; n < end && o"),
    M("ns-sendpads-end",
      "uint32_t end = S->stopAt == NETSTEP_NONE ? S->put : first;",
      "uint32_t end = S->put;"),
    M("ns-sendpads-count",
      "    b[8] = (uint8_t)count;\n    putHash(b + 9);\n"
      "    put32(b + 15, S->stopAt);\n    b[19] = 0;",
      "    b[8] = (uint8_t)(count ? count - 1 : 0);\n    putHash(b + 9);\n"
      "    put32(b + 15, S->stopAt);\n    b[19] = 0;"),
    M("ns-sendpads-stop",
      "    put32(b + 15, S->stopAt);\n    b[19] = 0;",
      "    put32(b + 15, NETSTEP_NONE);\n    b[19] = 0;"),
    M("ns-sendpads-own", "encodePad(b + o, &S->pads[S->place][n & MASK]);",
      "encodePad(b + o, &S->pads[0][n & MASK]);"),
    M("ns-sendpads-type", "S->net.send(S->peer[0], NETSTEP_MSG_PADS, b, o)",
      "S->net.send(S->peer[0], NETSTEP_MSG_FRAMES, b, o)"),
    M("ns-sendpads-last", "    S->lastSend[S->place] = now;\n", ""),
    M("ns-clientpoll-type",
      "            if (m.type != NETSTEP_MSG_FRAMES) {\n                on = 1;",
      "            if (0) {\n                on = 1;"),
    M("ns-clientpoll-on", "                on = 1;\n                break;",
      "                break;"),
    M("ns-clientpoll-past", "&& S->frame >= S->hostStop)) {",
      "&& S->frame > S->hostStop)) {"),
    M("ns-clientpoll-stopat", "            S->stopAt    = S->frame;\n", ""),
    M("ns-clientpoll-tells", "            S->tells     = NETSTEP_TELLS;\n", ""),
    M("ns-takeframes-hoststop",
      "    if (get32(d + 15) != NETSTEP_NONE && S->hostStop == NETSTEP_NONE) {",
      "    if (0) {"),
    M("ns-takeframes-hoststop-once",
      "    if (get32(d + 15) != NETSTEP_NONE && S->hostStop == NETSTEP_NONE) {",
      "    if (get32(d + 15) != NETSTEP_NONE) {"),
    # -- a client's end
    M("ns-tell-none", "    if (S->tells <= 0) return;\n    if (!alive(0))",
      "    if (!alive(0))"),
    M("ns-tell-alive", "    if (!alive(0)) {\n        S->tells = 0;",
      "    if (0) {\n        S->tells = 0;"),
    M("ns-tell-resend",
      "    if (now - S->lastSend[S->place] < NETSTEP_RESEND_MS) return;\n"
      "    sendPads(now);\n    if (--S->tells",
      "    sendPads(now);\n    if (--S->tells"),
    M("ns-tell-count", "    if (--S->tells == 0) say(", "    if (S->tells == 0) say("),
    M("ns-clientpoll-alive", "        if (!alive(0) || S->lost[0]) {\n",
      "        if (S->lost[0]) {\n"),
    M("ns-clientpoll-alone", "                S->alone     = 1;\n", ""),
    M("ns-clientpoll-alone-live",
      "                S->live      = (uint8_t)(1u << S->place);\n", ""),
    M("ns-clientpoll-polled", "            if (S->polled && !S->lost[0]) {",
      "            if (!S->lost[0]) {"),
    M("ns-clientpoll-lostmark",
      "                S->lost[0]   = 1;\n                S->lostAt[0] = now;\n",
      "                S->lostAt[0] = now;\n"),
    M("ns-clientpoll-lostat",
      "                S->lostAt[0] = now;\n"
      "                say(\"netstep: the host lost",
      "                say(\"netstep: the host lost"),
    M("ns-clientpoll-hold",
      "uint32_t hold = S->holdMs + (alive(0) ? NETSTEP_BACK_MS : 0);",
      "uint32_t hold = S->holdMs / 2 + (alive(0) ? NETSTEP_BACK_MS : 0);"),
    M("ns-clientpoll-nopads", "    if (S->lost[0]) return;\n", ""),
    M("ns-takeframes-held", "    S->held      = d[19];\n", ""),
    M("ns-takeframes-heldleft", "    S->heldLeft  = d[20];\n", ""),
    M("ns-held-on",
      "    if (!S->on || S->alone) return 0;\n"
      "    if (S->host) return hostHeld(now, msLeft);",
      "    if (!S->on) return 0;\n"
      "    if (S->host) return hostHeld(now, msLeft);"),
    M("ns-held-host", "    if (S->host) return hostHeld(now, msLeft);\n", ""),
    M("ns-held-client-left",
      "        if (msLeft && held) *msLeft = (uint32_t)S->heldLeft * 1000u;\n",
      ""),
    M("ns-held-client", "        return held;\n", "        return 0;\n"),
    M("ns-held-client-self", "S->held & (uint8_t)~(1u << S->place);",
      "S->held;"),
    M("ns-held-client-none", "if (msLeft && held) *msLeft", "if (msLeft) *msLeft"),
    M("ns-held-lost-left",
      "    if (msLeft) *msLeft = since < S->holdMs ? S->holdMs - since : 0;\n"
      "    return 1;",
      "    if (msLeft) *msLeft = S->holdMs;\n    return 1;"),
    M("ns-held-lost", "S->holdMs - since : 0;\n    return 1;\n}",
      "S->holdMs - since : 0;\n    return S->held;\n}"),
    M("ns-clientpoll-alone-return", "        aloneBuild();\n        return;\n",
      "        aloneBuild();\n"),
    # -- back (37g-2)
    M("ns-back-host-clear",
      "            S->lost[p] = 0;\n            say(\"netstep: place %d back",
      "            say(\"netstep: place %d back"),
    M("ns-back-host-pads", "        } else if (S->lost[p] && S->back[p]) {",
      "        } else if (S->lost[p] && alive(p)) {"),
    M("ns-back-host-heard", "            if (S->lost[p]) S->back[p] = 1;\n",
      ""),
    M("ns-back-host-reset", "            S->back[p]   = 0;\n", ""),
    M("ns-back-host-grace", "S->holdMs + (alive(p) ? NETSTEP_BACK_MS : 0)",
      "S->holdMs"),
    M("ns-back-host-grace-alive", "(alive(p) ? NETSTEP_BACK_MS : 0)",
      "NETSTEP_BACK_MS"),
    M("ns-back-host-send",
      "            || (S->lost[p] && (!alive(p) || S->rejoin[p] == 1)))\n",
      "            || S->lost[p])\n"),
    M("ns-takepads-taken",
      "        S->padFor[p][n & MASK] = n;\n    }\n    return 1;\n}",
      "        S->padFor[p][n & MASK] = n;\n    }\n    return 0;\n}"),
    M("ns-back-host-after", "(unsigned long)(now - S->lostAt[p]));",
      "(unsigned long)S->holdMs);"),
    M("ns-back-client-clear",
      "            S->lost[0] = 0;\n            say(\"netstep: the host back",
      "            say(\"netstep: the host back"),
    M("ns-back-client-got", "if (S->lost[0] && got) {",
      "if (S->lost[0] && alive(0)) {"),
    M("ns-back-client-lost", "if (!alive(0) || S->lost[0]) {",
      "if (!alive(0)) {"),
    M("ns-back-grace", "S->holdMs + (alive(0) ? NETSTEP_BACK_MS : 0)",
      "S->holdMs"),
    M("ns-back-grace-alive", "(alive(0) ? NETSTEP_BACK_MS : 0)",
      "NETSTEP_BACK_MS"),
    M("ns-takeframes-taken",
      "    while (recIn(S->built)) S->built++;\n    return 1;\n}",
      "    while (recIn(S->built)) S->built++;\n    return 0;\n}"),
    # -- a restart (37g-3): every record kept
    M("ns-hist-byte", "S->hist[b][S->histLen % NETSTEP_HIST_BLOCK] = v;",
      "S->hist[b][S->histLen % NETSTEP_HIST_BLOCK] = (uint8_t)(v & 0xfe);"),
    M("ns-hist-len", "    S->histLen++;\n    return 1;", "    return 1;"),
    M("ns-hist-max", "    if (b >= NETSTEP_HIST_MAX) return 0;\n",
      "    if (b >= NETSTEP_HIST_MAX / 4) return 0;\n"),
    M("ns-hist-alloc", "    if (S->hist[b] == NULL) {\n        S->hist[b] = ",
      "    if (1) {\n        S->hist[b] = "),
    M("ns-hist-at",
      "return S->hist[o / NETSTEP_HIST_BLOCK][o % NETSTEP_HIST_BLOCK];",
      "return S->hist[0][o % NETSTEP_HIST_BLOCK];"),
    M("ns-hist-same-bytes", "memcmp(a->ds2, b->ds2, NETSTEP_PAD_BYTES) == 0",
      "memcmp(a->ds2, b->ds2, NETSTEP_PAD_BYTES - 1) == 0"),
    M("ns-hist-same-menu", "\n        && a->menu == b->menu;", ";"),
    M("ns-hist-key", "int      key = r->n % NETSTEP_HIST_KEY == 0,",
      "int      key = r->n % NETSTEP_HIST_KEY == 1,"),
    M("ns-hist-keypads",
      "            && (key || !samePad(&r->pad[p], &S->histLast.pad[p])))",
      "            && !samePad(&r->pad[p], &S->histLast.pad[p]))"),
    M("ns-hist-keyat", "        if (ok) S->histKey[k] = S->histLen;\n", ""),
    M("ns-hist-live", "        if (((r->live >> p) & 1)\n            && (key",
      "        if ((key"),
    M("ns-hist-full", "        S->histFull = 1;\n        S->histLen  = start;",
      "        S->histLen  = start;"),
    M("ns-hist-fullcheck", "    if (S->histFull) return;\n    if (key) {",
      "    if (key) {"),
    M("ns-hist-recs", "    S->histRecs++;\n", ""),
    M("ns-histget-back",
      "if (!(r->n < n && r->n / NETSTEP_HIST_KEY == n / NETSTEP_HIST_KEY))",
      "if (!(r->n / NETSTEP_HIST_KEY == n / NETSTEP_HIST_KEY))"),
    M("ns-histget-seekat",
      "        S->histReadAt = S->histKey[from / NETSTEP_HIST_KEY];\n",
      "        S->histReadAt = 0;\n"),
    M("ns-histget-seekn", "        r->n          = from - 1;\n",
      "        r->n          = from;\n"),
    M("ns-histget-q", "        r->q    = histAt(o++);\n",
      "        r->q    = NETSTEP_Q_FIRST;\n        o++;\n"),
    M("ns-histget-rest",
      "            if (!((r->live >> p) & 1)) {\n"
      "                netstep_rest(&r->pad[p]);\n",
      "            if (!((r->live >> p) & 1)) {\n"),
    M("ns-histget-changed", "            } else if ((changed >> p) & 1) {",
      "            } else if (1) {"),
    M("ns-histget-readat", "        S->histReadAt = o;\n", ""),
    M("ns-recat-ring", "&S->recs[n & MASK] : histGet(n);",
      "&S->recs[n & MASK] : NULL;"),
    M("ns-recat-hist", "return recIn(n) ? &S->recs[n & MASK] : histGet(n);",
      "return histGet(n);"),
    M("ns-hostbuild-hist", "        histPut(&S->recs[n & MASK]);\n", ""),
    M("ns-start-hist", "        if (S->host) histPut(&S->recs[n]);\n", ""),
    M("ns-start-histread",
      "    S->histRead.n = NETSTEP_NONE;\n    S->net    = net;",
      "    S->net    = net;"),
    # -- let back in
    M("ns-rejoin-full", "    if (S->histFull) {\n        say(",
      "    if (0) {\n        say("),
    M("ns-rejoin-fullret",
      "(unsigned long)S->histRecs);\n        return 0;\n    }",
      "(unsigned long)S->histRecs);\n    }"),
    M("ns-rejoin-lost", "p >= NETSTEP_MAX || !S->lost[p]\n",
      "p >= NETSTEP_MAX\n"),
    M("ns-rejoin-host", "if (!S->on || !S->host || p <= 0",
      "if (!S->on || p <= 0"),
    M("ns-rejoin-state", "    S->rejoin[p]   = 1;\n", ""),
    M("ns-rejoin-state2", "    S->rejoin[p]   = 1;\n",
      "    S->rejoin[p]   = 2;\n"),
    M("ns-rejoin-at", "    S->rejoinAt[p] = now;\n", ""),
    M("ns-rejoin-lostat", "    S->lostAt[p]   = now;\n    S->back[p]",
      "    S->back[p]"),
    M("ns-rejoin-need", "    S->need[p]      = 0;\n", ""),
    M("ns-rejoin-ran", "    S->ran[p]       = 0;\n", ""),
    M("ns-rejoin-padfor",
      "    for (i = 0; i < NETSTEP_RING; i++) {\n"
      "        S->padFor[p][i]   = NETSTEP_NONE;\n"
      "        S->theirFor[p][i] = NETSTEP_NONE;\n    }\n    say(",
      "    for (i = 0; i < NETSTEP_RING; i++) {\n"
      "        S->theirFor[p][i] = NETSTEP_NONE;\n    }\n    say("),
    M("ns-hostread-rejoin2",
      "            if (S->rejoin[p] == 1) S->rejoin[p] = 2;\n", ""),
    M("ns-hostread-taken", "            if (!takePads(p, &m)) continue;\n",
      "            takePads(p, &m);\n"),
    M("ns-takepads-ran", "        S->ran[p] = get32(d + 9) + 1;\n", ""),
    M("ns-caught-reset",
      "        S->rejoin[p] = 0;\n        say(\"netstep: place %d caught up",
      "        say(\"netstep: place %d caught up"),
    M("ns-caught-built", "p < NETSTEP_MAX && S->built > from; p++)",
      "p < NETSTEP_MAX && S->built >= from; p++)"),
    M("ns-caught-frame",
      "            (unsigned long)from, (unsigned long)(now - S->rejoinAt[p]));",
      "            (unsigned long)S->built, "
      "(unsigned long)(now - S->rejoinAt[p]));"),
    # -- how far
    M("ns-rejoining-mark",
      "        mask |= (uint8_t)(1u << p);\n    }\n    if (pct) *pct = mask",
      "    }\n    if (pct) *pct = mask"),
    M("ns-rejoining-least", "        if (got < least) least = got;\n",
      "        least = got;\n"),
    M("ns-rejoining-pct", "    if (pct) *pct = mask ? (uint8_t)least : 0;",
      "    if (pct) *pct = (uint8_t)least;"),
    M("ns-rejoining-scale", "(uint64_t)S->need[p] * 100u / S->built",
      "(uint64_t)S->need[p] * 10u / S->built"),
    M("ns-sendframes-rejoining", "    b[21] = hostRejoining(&b[22]);\n",
      "    b[21] = 0;\n    b[22] = 0;\n"),
    M("ns-sendframes-pct", "    b[21] = hostRejoining(&b[22]);\n",
      "    b[21] = hostRejoining(&b[22]);\n    b[22] = 0;\n"),
    M("ns-takeframes-rejoining", "    S->rejoining = d[21];\n", ""),
    M("ns-takeframes-pct", "    S->rejoinPct = d[22];\n", ""),
    M("ns-rejoining-alone",
      "    if (!S->on || S->alone) return 0;\n"
      "    if (S->host) return hostRejoining",
      "    if (!S->on) return 0;\n    if (S->host) return hostRejoining"),
    M("ns-rejoining-self",
      "mask = S->rejoining & (uint8_t)~(1u << S->place);",
      "mask = S->rejoining;"),
    M("ns-rejoining-client-pct", "    if (pct && mask) *pct = S->rejoinPct;",
      "    if (pct) *pct = S->rejoinPct;"),
    M("ns-behind-alone", "S->host || S->alone || S->padNeed <= S->frame",
      "S->host || S->padNeed <= S->frame"),
    M("ns-behind-value", "    return S->padNeed - S->frame;\n",
      "    return 0;\n"),
    # -- caught up
    M("ns-burst-wait",
      "            if (now - S->lastSend[p] < NETSTEP_RESEND_MS) continue;\n",
      ""),
    M("ns-burst-moved",
      "            if (S->need[p] != S->burstNeed[p]) S->burstStill[p] = 0;\n",
      ""),
    M("ns-burst-needset", "            S->burstNeed[p] = S->need[p];\n", ""),
    M("ns-burst-from",
      "            if (S->burstStill[p] < 2 && S->burstTo[p] > n) "
      "n = S->burstTo[p];\n",
      ""),
    M("ns-burst-still",
      "            S->burstStill[p] = S->burstStill[p] < 2 ? "
      "S->burstStill[p] + 1 : 0;\n",
      ""),
    M("ns-burst-ring", "            uint32_t end = S->ran[p] + NETSTEP_RING;\n",
      "            uint32_t end = S->built;\n"),
    M("ns-burst-word",
      "            if (n >= end) {\n                sendFrames(p, n, n, now);\n",
      "            if (n >= end) {\n"),
    M("ns-burst-count", "for (k = 0; k < NETSTEP_BURST && n < end; k++)",
      "for (k = 0; k < 1 && n < end; k++)"),
    M("ns-burst-to", "            S->burstTo[p] = n;\n", ""),
    M("ns-burst-loading",
      "(S->lost[p] && (!alive(p) || S->rejoin[p] == 1))",
      "(S->lost[p] && !alive(p))"),
    M("ns-sendframes-ret", "    S->fresh[p]    = 0;\n    return n;\n}",
      "    S->fresh[p]    = 0;\n    return first;\n}"),
    # -- the race's
    M("ns-clientpoll-resend",
      "now - S->lastSend[S->place] >= NETSTEP_RESEND_MS) sendPads",
      "now - S->lastSend[S->place] >= 4 * NETSTEP_RESEND_MS) sendPads"),
    M("ns-start-on", "    S->on     = 1;\n", ""),
    M("ns-start-host", "    S->host   = place == 0;\n",
      "    S->host   = place == 1;\n"),
    M("ns-start-differ", "    S->differ = differ;\n", ""),
    M("ns-ondiffer", "    S->differ = fn;\n", ""),
    M("ns-start-peer", "S->peer[p] = p < consoles ? peer[p] : -1;",
      "S->peer[p] = peer[p];"),
    M("ns-start-padfor", "            S->padFor[p][i]   = NETSTEP_NONE;\n", ""),
    M("ns-start-theirfor", "            S->theirFor[p][i] = NETSTEP_NONE;\n",
      ""),
    M("ns-start-hashfor",
      "    for (i = 0; i < NETSTEP_RING; i++) S->hashFor[i] = NETSTEP_NONE;\n",
      ""),
    M("ns-start-live", "    S->live = racing;\n",
      "    S->live = (uint8_t)((1u << consoles) - 1u);\n"),
    M("ns-start-first-q", "        buildRecord(n, S->live, NETSTEP_Q_FIRST);\n",
      "        buildRecord(n, S->live, 0);\n"),
    M("ns-start-first", "    for (n = 0; n < NETSTEP_DELAY; n++) {\n",
      "    for (n = 0; n < NETSTEP_DELAY - 1; n++) {\n"),
    M("ns-start-built", "    S->built = NETSTEP_DELAY;\n", "    S->built = 0;\n"),
    M("ns-start-put", "    S->put   = NETSTEP_DELAY;\n", "    S->put   = 0;\n"),
    M("ns-start-stopat", "    S->stopAt   = NETSTEP_NONE;\n", ""),
    M("ns-start-hoststop", "    S->hostStop = NETSTEP_NONE;\n", ""),
    M("ns-stop-off", "    S->on = 0;\n", ""),
    M("ns-stop-at", "    if (S->stopAt == NETSTEP_NONE) S->stopAt = S->frame;",
      "    S->stopAt = S->frame;"),
    M("ns-stop-from", "    S->endFrom = now;\n", ""),
    M("ns-stop-host", "        S->ending = 1;\n    } else {",
      "        S->ending = 0;\n    } else {"),
    M("ns-stop-tells", "        if (!S->alone) S->tells = NETSTEP_TELLS;\n", ""),
    M("ns-stop-tells-alone", "        if (!S->alone) S->tells = NETSTEP_TELLS;",
      "        S->tells = NETSTEP_TELLS;"),
    M("ns-stop-client", "        S->ending = S->tells > 0;", "        S->ending = 0;"),
    M("ns-drain-off", "    if (!S->ending) return;\n    if (S->host) {",
      "    if (S->host) {"),
    M("ns-drain-tell", "    tell(now);\n    if (S->tells <= 0) S->ending = 0;",
      "    if (S->tells <= 0) S->ending = 0;"),
    M("ns-drain-end", "    if (S->tells <= 0) S->ending = 0;\n}", "}"),
    M("ns-put-pad", "    S->pads[S->place][i]   = *pad;\n", ""),
    M("ns-put-mark", "    S->padFor[S->place][i] = S->put;\n", ""),
    M("ns-put-q", "    S->q[i]                = q;\n", ""),
    M("ns-poll-off", "    if (!S->on) return 0;\n    if (S->host)",
      "    if (S->host)"),
    M("ns-poll-settle", "S->built >= NETSTEP_DELAY + NETSTEP_SETTLE",
      "S->built >= NETSTEP_DELAY"),
    M("ns-poll-settled", "        S->settled = 1;\n", ""),
    M("ns-poll-patience", "        S->net.setPatience(0);\n", ""),
    M("ns-poll-return", "    return recIn(S->frame);\n}", "    return 1;\n}"),
    M("ns-current-on", "return S->on && recIn(S->frame) ?",
      "return recIn(S->frame) ?"),
    M("ns-done-hash", "    S->hash[n & MASK]    = hash;\n", ""),
    M("ns-done-hashfor", "    S->hashFor[n & MASK] = n;\n", ""),
    M("ns-done-log", "if (n % NETSTEP_LOG_EVERY == 0)",
      "if (n % NETSTEP_LOG_EVERY == 1)"),
    M("ns-done-check",
      "    for (p = 0; p < NETSTEP_MAX; p++) checkHash(p, n);\n", ""),
    M("ns-done-next", "    S->frame++;\n", ""),
]

EQUIVALENT = {
    # Frame NETSTEP_NONE's checksum, said before a console has run any,
    # lands in slot 63 with both checksums still 0 there; once frame 63
    # has run, the slot is not that frame's.
    "ns-takehash-none",
    # The peers past the consoles are never read: every loop over the
    # places goes by the places racing, which netrace gives inside them.
    "ns-start-peer",
    # A place out of the live bits is one that left (the next test), one
    # whose link was lost, held for and dropped, or one never racing, its
    # link never up: alive() is 0 for the last two, as a link lost comes
    # back only by a rejoin the host takes while it holds for that place
    # (37g-2, main.c's lockRejoinOk), never once it has dropped it.
    "ns-serving-live",
    # A client's lost bits mark its host's place alone, which p <= 0
    # refuses: a client's netstep_rejoin is 0 with or without the host
    # test, and only the host's netrace calls it.
    "ns-rejoin-host",
    # A pad of a place not live is sent nowhere (sendFrames encodes the
    # live ones), and a place out of a record is out of every later one;
    # a read from a key starts with each live pad the key keeps.
    "ns-histget-rest",
    # The word alone goes to a place catching up that has every record
    # its ring takes: it needs none until it runs one, when the next
    # burst brings the same word; the word keeps the hold's count on it
    # current meanwhile, which the harness checks only as seen at all.
    "ns-burst-word",
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
        todo, SOURCES, "netstep_test",
        lambda exe, out: run_harness(exe, out, limit),
        base, diff, EQUIVALENT, jobs, flags=FLAGS)
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
