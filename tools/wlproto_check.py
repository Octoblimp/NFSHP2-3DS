#!/usr/bin/env python3
"""Checks the wireless link's protocol (`3DS Files/source/wlproto.c`).

TASKS 37a: two consoles race over UDS, which loses, repeats and reorders
frames. wlproto is the layer above it: reliable messages acked and resent
and delivered once, in order; unreliable ones for the next packet only; a
keepalive, a timeout, and a CRC. Nothing of retail's is ported here (the
PS2 shared one console), so there is no model to diff against. Instead
tools/src/wlproto_test.c runs two links over a simulated channel and
checks what each side reads against what the other sent (the harness's
header has the list), scenario by scenario:

  - clean channels, at 0 to 40 ms of delay and 10 to 33 ms ticks, with
    messages of 0 to 240 bytes, packets that split, and a full queue;
  - lossy ones, up to half the packets lost, a fifth repeated, delays to
    200 ms that reorder them, and damaged packets;
  - cuts short of the timeout and past it, and the receiver not reading
    for up to ten seconds, so its inbox fills;
  - sequence numbers that wrap (over 32,768 messages a side);
  - traffic one way only, and none.

The harness prints "faults 0" when every property holds. A mutant is
caught only when the harness finds a fault: the transcript's counts move
with any change at all, so a diff of them would say nothing.

    python tools/wlproto_check.py
    python tools/wlproto_check.py --mutate [--only a,b]
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

HARNESS = "tools/src/wlproto_test.c"
WL = "3DS Files/source/wlproto.c"
SOURCES = [HARNESS, WL]


def S(drop=0, dup=0, garbage=0, dmin=0, dmax=0, cut=(0, 0), tick=33,
      length=20000, rel=4, unrel=4, maxlen=240, stall=(0, 0), seed=1,
      senders=3):
    return (drop, dup, garbage, dmin, dmax, cut[0], cut[1], tick, length,
            rel, unrel, maxlen, stall[0], stall[1], seed, senders)


SCENARIOS = [
    # -- clean
    S(seed=1),
    S(seed=2, tick=16, rel=8, unrel=8, maxlen=64),
    S(seed=3, dmin=10, dmax=10, tick=16),
    S(seed=4, dmin=40, dmax=40),
    S(seed=5, rel=8, maxlen=0),
    S(seed=6, rel=8, unrel=8),
    S(seed=7, unrel=10, maxlen=32),
    S(seed=8, rel=8, tick=10, dmin=25, dmax=25),
    # -- lossy
    S(seed=11, drop=100, dup=50, garbage=20, dmax=50),
    S(seed=12, drop=300, dup=100, garbage=50, dmax=120, tick=16),
    S(seed=13, drop=500, dup=200, garbage=100, dmax=200),
    S(seed=14, drop=50, dup=300, dmin=5, dmax=80),
    S(seed=15, dmax=150),
    S(seed=16, garbage=300),
    S(seed=17, drop=200, dmax=30, tick=10, rel=8, unrel=8, maxlen=64),
    # -- cuts
    S(seed=21, cut=(8000, 14000), drop=50, dmax=30),
    S(seed=22, cut=(8000, 14000)),
    S(seed=23, cut=(5000, 6000)),
    S(seed=24, cut=(3000, 4500), drop=100, dmax=40),
    S(seed=25, cut=(5000, 25000), length=30000),
    # -- the reader stalls
    S(seed=31, stall=(5000, 9000)),
    S(seed=32, stall=(5000, 9000), drop=100, dup=50, garbage=20, dmax=50),
    S(seed=33, stall=(2000, 12000), rel=8, unrel=8),
    S(seed=34, stall=(3000, 8000), dmax=150),
    S(seed=35, stall=(3000, 8000), dmax=150, rel=8, unrel=2),
    S(seed=36, stall=(4000, 6000), drop=200, dup=100, dmax=100, tick=16),
    S(seed=37, stall=(1000, 15000), dmax=60, rel=8, unrel=0, maxlen=8),
    S(seed=38, stall=(5000, 7000), senders=1, rel=8, unrel=8, dmax=80),
    # -- the numbers wrap
    S(seed=41, tick=10, length=150000, rel=8, unrel=1, maxlen=16),
    S(seed=42, tick=10, length=150000, rel=8, unrel=1, maxlen=16,
      drop=100, dmax=20),
    # -- one way
    S(seed=51, senders=1, rel=1, unrel=0, tick=10),
    S(seed=52, senders=2, rel=1, unrel=0, tick=10, drop=100, dmax=20),
    S(seed=53, senders=1, rel=8),
    # -- quiet
    S(seed=61, senders=0),
    S(seed=62, senders=0, tick=10),
    S(seed=63, senders=0, tick=50),
    S(seed=64, senders=0, cut=(5000, 10000)),
]


def write_scenarios(tmp):
    p = Path(tmp) / "scenarios.txt"
    p.write_text("".join(" ".join(str(v) for v in sc) + "\n"
                         for sc in SCENARIOS))
    return p


def build_harness(tmp):
    return hostbuild.build(tmp, SOURCES, name="wlproto_test")


def faults(lines):
    for ln in reversed(lines):
        if ln.startswith("faults "):
            return int(ln.split()[1])
    return -1


def diff(base, got, quiet=False):
    """How badly `got` fails: its faults, or 1 for a transcript with no
    tally. 0 when the harness found nothing wrong."""
    n = faults(got)
    if n == 0:
        return 0
    if not quiet:
        for ln in got:
            if ln.startswith("  FAULT"):
                print(ln)
    return n if n > 0 else 1


# ============================================================= mutations

def M(name, before, after):
    return (name, WL, before, after)


MUTATIONS = [
    # -- numbers and bytes
    M("wl-diff-mask", "return (uint16_t)((a - b) & WL_SEQ_MASK);",
      "return (uint16_t)(a - b);"),
    M("wl-next-mask", "return (uint16_t)((s + 1u) & WL_SEQ_MASK);",
      "return (uint16_t)(s + 1u);"),
    M("wl-rd16", "return (uint16_t)(p[0] | p[1] << 8);",
      "return (uint16_t)(p[0] << 8 | p[1]);"),
    M("wl-crc-ack", "crc16(buf, 5, 0xffffu));", "crc16(buf + 4, 1, 0xffffu));"),
    # -- sending
    M("wl-send-window", "if (seq_diff(l->next, l->base) >= WL_WINDOW)",
      "if (seq_diff(l->next, l->base) > WL_WINDOW)"),
    M("wl-send-max", "    if (n > WL_MSG_MAX)\n        return 0;",
      "    if (n > WL_MSG_MAX + 1)\n        return 0;"),
    M("wl-send-max-eq", "    if (n > WL_MSG_MAX)\n        return 0;",
      "    if (n >= WL_MSG_MAX)\n        return 0;"),
    M("wl-send-due", "l->dueAt[k] = l->now;",
      "l->dueAt[k] = l->now + WL_RESEND_MS;"),
    M("wl-unrel-max", "if (l->numUnrel >= WL_UNREL_MAX)",
      "if (l->numUnrel > WL_UNREL_MAX)"),
    M("wl-unrel-seq", "m->seq = WL_UNRELIABLE;", "m->seq = 0;"),
    # -- the packets out
    M("wl-put-split", "if (p->n + need > WL_PACKET_MAX || p->count == 255)",
      "if (p->n + need > WL_PACKET_MAX + 200 || p->count == 255)"),
    M("wl-put-count", "p->buf[4] = (uint8_t)p->count;",
      "p->buf[4] = (uint8_t)(p->count - 1);"),
    M("wl-put-reset", "    p->n     = WL_HEADER;\n    p->count = 0;\n}\n\n"
      "static void packet_put", "}\n\nstatic void packet_put"),
    M("wl-last-sent", "    l->lastSent = l->now;\n", ""),
    M("wl-tick-now", "    l->now = now;\n    packet_begin", "    packet_begin"),
    M("wl-due-late", "if ((int32_t)(now - l->dueAt[k]) < 0)",
      "if ((int32_t)(now - l->dueAt[k]) <= 0)"),
    M("wl-resend-slow", "l->dueAt[k] = now + WL_RESEND_MS;",
      "l->dueAt[k] = now + 10 * WL_RESEND_MS;"),
    M("wl-resend-fast", "l->dueAt[k] = now + WL_RESEND_MS;",
      "l->dueAt[k] = now;"),
    M("wl-unrel-clear", "    l->numUnrel = 0;\n", ""),
    M("wl-last-packet", "    if (p.count > 0\n", "    if (p.count > 1\n"),
    M("wl-ack-due", "&& (l->ackDue || (int32_t)", "&& ((int32_t)"),
    M("wl-ack-clear", "    l->ackDue = 0;\n}", "}"),
    M("wl-keepalive", "(int32_t)(now - l->lastSent) >= WL_KEEPALIVE_MS",
      "(int32_t)(now - l->lastSent) >= WL_TIMEOUT_MS"),
    # -- taking messages
    M("wl-inbox-full", "if (l->inCount >= WL_INBOX)",
      "if (l->inCount > WL_INBOX)"),
    M("wl-drain-full", "        if (!inbox_put(l, &l->held[k]))\n"
      "            return;\n", "        inbox_put(l, &l->held[k]);\n"),
    M("wl-drain-seq", "if (!l->isHeld[k] || l->held[k].seq != l->expect)",
      "if (!l->isHeld[k])"),
    M("wl-take-unrel", "            l->dropped++;\n        return;\n",
      "            l->dropped++;\n"),
    M("wl-drain-clear", "        l->isHeld[k] = 0;\n        l->expect",
      "        l->expect"),
    M("wl-take-old", "if (d >= WL_WINDOW || l->isHeld[k])",
      "if (l->isHeld[k])"),
    M("wl-take-copy", "    l->held[k]   = *m;\n", ""),
    M("wl-take-held", "    l->isHeld[k] = 1;\n    drain_held(l);\n}",
      "    drain_held(l);\n}"),
    M("wl-take-drain", "    l->isHeld[k] = 1;\n    drain_held(l);\n}",
      "    l->isHeld[k] = 1;\n}"),
    M("wl-take-ackdue", "    l->ackDue = 1;\n", ""),
    # -- a packet in
    M("wl-in-short", "if (n < WL_HEADER || buf[0] != WL_MAGIC",
      "if (buf[0] != WL_MAGIC"),
    M("wl-in-magic", "|| buf[0] != WL_MAGIC ", ""),
    M("wl-in-version", "|| buf[1] != WL_VERSION)", ")"),
    M("wl-in-crc", "    if (rd16(buf + 5) != packet_crc(buf, n))\n"
      "        goto bad;\n", ""),
    M("wl-in-ackbit", "    if (ack & WL_UNRELIABLE)\n        goto bad;\n", ""),
    M("wl-in-msg-header", "        if (at + WL_MSG_HEADER > n)\n"
      "            goto bad;\n", ""),
    M("wl-in-unrel-seq", "        if ((seq & WL_UNRELIABLE) && "
      "seq != WL_UNRELIABLE)\n            goto bad;\n", ""),
    M("wl-in-len-max", "        if (len > WL_MSG_MAX)\n            goto bad;\n",
      ""),
    M("wl-in-trailing", "    if (at != n)\n        goto bad;\n", ""),
    M("wl-in-heard", "    l->heard     = 1;\n", ""),
    M("wl-in-last-heard", "    l->lastHeard = l->now;\n", ""),
    M("wl-in-ack-le",
      "if (seq_diff(ack, l->base) <= seq_diff(l->next, l->base))",
      "if (seq_diff(ack, l->base) < seq_diff(l->next, l->base))"),
    M("wl-in-ack-any",
      "if (seq_diff(ack, l->base) <= seq_diff(l->next, l->base))",
      "if (1)"),
    M("wl-in-ack-skip", "        l->base = ack;\n", ""),
    M("wl-recv-drain", "    // Room again: the next message held for it.\n"
      "    drain_held(l);\n", ""),
    # -- the link's state
    M("wl-alive-heard", "return l->heard && (int32_t)", "return (int32_t)"),
    M("wl-alive-timeout", "< WL_TIMEOUT_MS;", "< 10 * WL_TIMEOUT_MS;"),
]

EQUIVALENT = {
    "wl-drain-seq":
        "A held message's number is from expect to expect + 31, so the "
        "slot of expect holds expect's or nothing: every path that moves "
        "expect past a number clears its slot.",
    "wl-in-msg-header":
        "A guard on the read of a message's header past the packet's end, "
        "which the length test then rejects anyway: the harness's "
        "buffers are longer than their packets, so the read is not seen.",
}


def run_harness(exe, scen, out, timeout):
    return mutpar.run_exe([exe, scen], out, timeout)


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    keep = tempfile.TemporaryDirectory()
    scen = write_scenarios(keep.name)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        rc = run_harness(exe, scen, out, 600)
        took = time.monotonic() - t0
        base = out.read_text(encoding="latin-1").splitlines()
        if rc != 0 or "faults 0" not in base:
            print("base already fails -- fix that before mutating")
            return 1
        print("base: %d lines, 0 faults, %.1f s" % (len(base), took),
              flush=True)

    limit = mutpar.timeout_for(took)
    try:
        tally = mutpar.run_pass(
            todo, SOURCES, "wlproto_test",
            lambda exe, out: run_harness(exe, scen, out, limit),
            base, diff, EQUIVALENT, jobs)
    finally:
        keep.cleanup()
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
        scen = write_scenarios(tmp)
        out = Path(tmp) / "out.txt"
        rc = run_harness(exe, scen, out, 600)
        lines = out.read_text(encoding="latin-1").splitlines()
    for ln in lines:
        print(ln)
    sys.exit(1 if rc or "faults 0" not in lines else 0)


if __name__ == "__main__":
    main()
