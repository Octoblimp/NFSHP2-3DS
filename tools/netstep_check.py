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
    racing; the host stopping; netrace's messages on the same link,
    half of them shaped as netstep's.

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


def build_harness(tmp):
    return hostbuild.build(tmp, SOURCES, name="netstep_test")


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
    M("ns-check-once", " || S->differs[p])\n        return;",
      ")\n        return;"),
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
      "if (m->len != HEADER + (size_t)count * PAD_WIRE) return;",
      "if (m->len < HEADER) return;"),
    M("ns-takepads-first", "    first = get32(d + 4);\n    if (need > S->need[p])",
      "    first = get32(d + 4) + 1;\n    if (need > S->need[p])"),
    M("ns-takepads-need", "    if (need > S->need[p]) S->need[p] = need;\n",
      ""),
    M("ns-takepads-hash", "    takeHash(p, d + 9);\n", ""),
    M("ns-takepads-pad",
      "decodePad(&S->pads[p][n & MASK], d + HEADER + (size_t)i * PAD_WIRE);",
      "decodePad(&S->pads[p][n & MASK], d + HEADER);"),
    M("ns-takepads-mark", "        S->padFor[p][n & MASK] = n;\n", ""),
    M("ns-sendframes-need",
      "    put32(b, S->built);\n    put32(b + 4, first);\n"
      "    for (n = first; n < S->built",
      "    put32(b, S->built + 1);\n    put32(b + 4, first);\n"
      "    for (n = first; n < S->built"),
    M("ns-sendframes-first",
      "    put32(b + 4, first);\n    for (n = first; n < S->built",
      "    put32(b + 4, first + 1);\n    for (n = first; n < S->built"),
    M("ns-sendframes-fit", "        if (o + size > WL_MSG_MAX) break;\n", ""),
    M("ns-sendframes-q", "        b[o++] = r->q;\n",
      "        b[o++] = NETSTEP_Q_FIRST;\n"),
    M("ns-sendframes-live", "        b[o++] = r->live;\n",
      "        b[o++] = 0xff;\n"),
    M("ns-sendframes-skip",
      "            if (!((r->live >> q) & 1)) continue;\n", ""),
    M("ns-sendframes-count",
      "    b[8] = (uint8_t)count;\n    putHash(b + 9);\n"
      "    if (!S->net.send(S->peer[p]",
      "    b[8] = (uint8_t)(count ? count - 1 : 0);\n    putHash(b + 9);\n"
      "    if (!S->net.send(S->peer[p]"),
    M("ns-sendframes-hash",
      "    putHash(b + 9);\n    if (!S->net.send(S->peer[p]",
      "    memset(b + 9, 0xff, 6);\n    if (!S->net.send(S->peer[p]"),
    M("ns-sendframes-type",
      "S->net.send(S->peer[p], NETSTEP_MSG_FRAMES, b, o)",
      "S->net.send(S->peer[p], NETSTEP_MSG_PADS, b, o)"),
    M("ns-sendframes-last", "    S->lastSend[p] = now;\n", ""),
    M("ns-sendframes-fresh", "    S->fresh[p]    = 0;\n", ""),
    M("ns-hostpoll-peer", "if (p == S->place || S->peer[p] < 0) continue;",
      "if (p == S->place) continue;"),
    M("ns-hostpoll-type", "if (m.type == NETSTEP_MSG_PADS) takePads(p, &m);",
      "takePads(p, &m);"),
    M("ns-hostpoll-alive",
      "if (p == S->place || !((S->live >> p) & 1) || alive(p)) continue;",
      "if (p == S->place || !((S->live >> p) & 1)) continue;"),
    M("ns-hostpoll-drop", "        S->live &= (uint8_t)~(1u << p);\n", ""),
    M("ns-hostpoll-build", "    hostBuild();\n    for", "    for"),
    M("ns-hostpoll-sendlive",
      "if (p == S->place || !((S->live >> p) & 1)) continue;\n"
      "        if (S->fresh[p]",
      "if (p == S->place) continue;\n        if (S->fresh[p]"),
    M("ns-hostpoll-resend",
      "if (S->fresh[p] || now - S->lastSend[p] >= NETSTEP_RESEND_MS)",
      "if (S->fresh[p])"),
    M("ns-hostpoll-fresh", "if (S->fresh[p] || now - S->lastSend[p]",
      "if (now - S->lastSend[p]"),
    # -- a client's
    M("ns-takeframes-walk",
      "        o += 2 + (size_t)bits(d[o + 1]) * PAD_WIRE;\n",
      "        o += 2;\n"),
    M("ns-takeframes-len", "    if (i < count || o != m->len) return;\n", ""),
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
      "    for (n = first; n < S->put",
      "    put32(b, S->built + 1);\n    put32(b + 4, first);\n"
      "    for (n = first; n < S->put"),
    M("ns-sendpads-first",
      "    put32(b + 4, first);\n    for (n = first; n < S->put",
      "    put32(b + 4, first + 1);\n    for (n = first; n < S->put"),
    M("ns-sendpads-count",
      "    b[8] = (uint8_t)count;\n    putHash(b + 9);\n"
      "    if (!S->net.send(S->peer[0]",
      "    b[8] = (uint8_t)(count ? count - 1 : 0);\n    putHash(b + 9);\n"
      "    if (!S->net.send(S->peer[0]"),
    M("ns-sendpads-own", "encodePad(b + o, &S->pads[S->place][n & MASK]);",
      "encodePad(b + o, &S->pads[0][n & MASK]);"),
    M("ns-sendpads-type", "S->net.send(S->peer[0], NETSTEP_MSG_PADS, b, o)",
      "S->net.send(S->peer[0], NETSTEP_MSG_FRAMES, b, o)"),
    M("ns-sendpads-last", "    S->lastSend[S->place] = now;\n", ""),
    M("ns-clientpoll-type",
      "if (m.type == NETSTEP_MSG_FRAMES) takeFrames(&m);", "takeFrames(&m);"),
    M("ns-clientpoll-alive", "        if (!alive(0)) {\n", "        if (0) {\n"),
    M("ns-clientpoll-alone", "            S->alone = 1;\n", ""),
    M("ns-clientpoll-alone-live",
      "            S->live  = (uint8_t)(1u << S->place);\n", ""),
    M("ns-clientpoll-alone-return", "        aloneBuild();\n        return;\n",
      "        aloneBuild();\n"),
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
    M("ns-start-first", "    for (n = 0; n < NETSTEP_DELAY; n++)\n",
      "    for (n = 0; n < NETSTEP_DELAY - 1; n++)\n"),
    M("ns-start-built", "    S->built = NETSTEP_DELAY;\n", "    S->built = 0;\n"),
    M("ns-start-put", "    S->put   = NETSTEP_DELAY;\n", "    S->put   = 0;\n"),
    M("ns-stop-off", "    S->on = 0;\n", ""),
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
    # Every message netstep sends is as long as what it holds; the checks
    # are for one that is not.
    "ns-takepads-len",
    "ns-takeframes-len",
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
