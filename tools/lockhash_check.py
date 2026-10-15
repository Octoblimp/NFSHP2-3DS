#!/usr/bin/env python3
"""Checks the world's checksum in parts (`3DS Files/source/lockhash.c`).

TASKS 37e: each console of a wireless race hashes the world after every
frame in seven parts -- the time, the seeds, the players, the AI racers,
the cops with the helicopter, the traffic and the race -- folds them into
the 16-bit checksum netstep sends, logs them every NETSTEP_LOG_EVERY
frames, and at the first frame whose checksum differs logs the parts and
the draws on bDefaultSeed of the 16 frames up to it. Nothing of retail's
is ported here, so there is no model to diff against.
tools/src/lockhash_test.c builds a World of its own with bmath.c's draws
and checks (the harness's header has the list):

  - each part moves with every field it reads and with no other: no
    pointer, padding or tail, and no RacingCar past NumRacingCars;
  - the fold moves with each part;
  - the frame lines every NETSTEP_LOG_EVERY frames and the window at a
    difference, once a race, each frame's parts as ran and its draws;
    nothing before start or after stop;
  - bViewSeed on a seed of its own from GO, its draws not the frame's,
    and back on bDefaultSeed after stop;
  - bDefaultSeedWatch told of each draw on bDefaultSeed, with the address
    it returns to, and of none on another seed; the draws' values as
    without it.

The harness prints "total faults 0" at the end when everything holds. A
mutant is caught only when the harness finds a fault.

    python tools/lockhash_check.py
    python tools/lockhash_check.py --mutate [--only a,b]
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

HARNESS = "tools/src/lockhash_test.c"
LOCKHASH = "3DS Files/source/lockhash.c"
BMATH = "3DS Files/source/bmath.c"
SOURCES = [HARNESS, LOCKHASH, BMATH, "3DS Files/source/bmathtab.c"]


def build_harness(tmp):
    return hostbuild.build(tmp, SOURCES, name="lockhash_test")


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
            if ln.startswith("  FAULT"):
                print(ln)
    return n if n > 0 else 1


# ============================================================= mutations

def M(name, before, after):
    return (name, LOCKHASH, before, after)


def B(name, before, after):
    return (name, BMATH, before, after)


MUTATIONS = [
    # -- the hash
    M("lh-mix-xor", "    h ^= v;\n", "    h += v;\n"),
    M("lh-mix-shift", "    return h ^ (h >> 15);\n", "    return h;\n"),
    M("lh-bytes-last", "    for (i = 0; i + 4 <= n; i += 4) {\n",
      "    for (i = 0; i + 8 <= n; i += 4) {\n"),
    M("lh-car-mode", "    h = mix(h, (uint32_t)c->TheControlMode);\n", ""),
    M("lh-car-move", "    h = mix(h, (uint32_t)c->TheMovementMode);\n", ""),
    M("lh-car-span", "SPAN(CarState, GeometryPosition, DistanceMoved)",
      "SPAN(CarState, GeometryPosition, MatrixValid)"),
    M("lh-car-from", "    return mixBytes(h, &c->State.GeometryPosition,\n",
      "    return mixBytes(h, &c->State._hole8,\n"),
    M("lh-cars-first", "    if (first < 0) first = 0;\n", ""),
    M("lh-cars-last", "    if (last > w->TotalNumCars) last = w->TotalNumCars;\n",
      ""),
    M("lh-cars-slot", "        h = mix(h, (uint32_t)i);\n", ""),
    M("lh-cars-null", "        if (w->CarTable[i] != NULL) h = mixCar",
      "        if (w->CarTable[i] != NULL) (void)mixCar"),
    M("lh-chopper-null", "    if (c == NULL) return mix(h, 0);\n",
      "    if (c == NULL) return h;\n"),
    M("lh-chopper-think",
      "    h = mixBytes(h, &c->TimeUntilThink, sizeof c->TimeUntilThink);\n",
      ""),
    M("lh-chopper-plan", "SPAN(struct Chopper, Plan, MoveMode)",
      "sizeof c->Plan"),
    M("lh-chopper-target",
      "    h = mixBytes(h, &c->TargetDistance, sizeof c->TargetDistance);\n",
      ""),
    M("lh-chopper-last", "SPAN(struct Chopper, BombRunType, New960)",
      "SPAN(struct Chopper, BombRunType, EmitDust)"),
    M("lh-chopper-pad", "SPAN(struct Chopper, BombRunType, New960)",
      "SPAN(struct Chopper, BombRunType, _pad964)"),
    M("lh-rc-state", "        h = mix(h, (uint32_t)rc->CurrentRCState);\n", ""),
    M("lh-rc-exec", "        h = mix(h, (uint32_t)rc->RCExecutingMessage);\n",
      ""),
    M("lh-rc-count",
      "        h = mix(h, (uint32_t)rc->DisplayingCountdownNumber);\n", ""),
    M("lh-rc-before", "        h = mix(h, (uint32_t)rc->BeforePauseRCState);\n",
      ""),
    M("lh-race-null", "    if (r == NULL) return mix(h, 0);\n",
      "    if (r == NULL) return h;\n"),
    M("lh-race-span", "SPAN(Race, RaceStage, DetectedOneCarRemaining)",
      "SPAN(Race, RaceStage, NumRacingCarsFinished)"),
    M("lh-race-laps", "    h = mix(h, (uint32_t)r->NumLapsInRace);\n", ""),
    M("lh-race-forcepos",
      "    h = mix(h, (uint32_t)r->ForceRaceFinishPosition);\n", ""),
    M("lh-race-forceplayer",
      "    h = mix(h, (uint32_t)r->ForceRaceFinishPlayerNum);\n", ""),
    M("lh-race-max",
      "    if (n > RACE_MAX_RACING_CARS) n = RACE_MAX_RACING_CARS;\n"
      "    for (i = 0; i < n; i++)\n",
      "    if (n > RACE_MAX_RACING_CARS) n = RACE_MAX_RACING_CARS;\n"
      "    for (i = 0; i < RACE_MAX_RACING_CARS; i++)\n"),
    M("lh-race-fewer", "    for (i = 0; i < n; i++)\n",
      "    for (i = 0; i + 1 < n; i++)\n"),
    M("lh-racing-span", "                          AverageSpeed));\n",
      "                          TopSpeed));\n"),
    M("lh-world-null", "    if (w == NULL) return;\n",
      "    if (w == NULL) w = &(World){0};\n"),
    M("lh-world-clear", "    memset(h, 0, sizeof *h);\n", ""),
    M("lh-time-timer", "    t = mix(0x811c9dc5u, (uint32_t)WorldTimer);\n",
      "    t = 0x811c9dc5u;\n"),
    M("lh-time-span", "SPAN(World, fTimeToRemainPaused, fTimeScaleTimer)",
      "SPAN(World, fTimeToRemainPaused, fTimeScale)"),
    M("lh-time-callback", "SPAN(World, fTimeToRemainPaused, fTimeScaleTimer)",
      "SPAN(World, fTimeToRemainPaused, TimeScaleCallback)"),
    M("lh-time-param", "    t = mix(t, (uint32_t)w->TimeScaleCallbackParam);\n",
      ""),
    M("lh-time-retail",
      "    h->part[LOCKHASH_TIME] = mix(t, world_calculate_debug_checksum(w));\n",
      "    h->part[LOCKHASH_TIME] = t;\n"),
    M("lh-seeds-default", "mix(mix(0x811c9dc5u, bDefaultSeed), w->WorldRandomSeed)",
      "mix(0x811c9dc5u, w->WorldRandomSeed)"),
    M("lh-seeds-world", "mix(mix(0x811c9dc5u, bDefaultSeed), w->WorldRandomSeed)",
      "mix(0x811c9dc5u, bDefaultSeed)"),
    M("lh-players-to", "mixCars(w, 0, w->AICarPos);",
      "mixCars(w, 0, w->CopCarPos);"),
    M("lh-racers-from", "mixCars(w, w->AICarPos, w->CopCarPos);",
      "mixCars(w, 0, w->CopCarPos);"),
    M("lh-cops-to", "mixCars(w, w->CopCarPos, w->TrafficCarPos), w->Helicopter);",
      "mixCars(w, w->CopCarPos, w->TotalNumCars), w->Helicopter);"),
    M("lh-cops-chopper", "w->TrafficCarPos), w->Helicopter);",
      "w->TrafficCarPos), NULL);"),
    M("lh-traffic-from", "        mixCars(w, w->TrafficCarPos, w->TotalNumCars);\n",
      "        mixCars(w, w->CopCarPos, w->TotalNumCars);\n"),
    M("lh-race-part", "mixRace(pCurrentRace, pRaceCoordinator);",
      "mixRace(pCurrentRace, NULL);"),
    M("lh-fold-part", "    for (i = 0; i < LOCKHASH_PARTS; i++) s = s * 33u",
      "    for (i = 1; i < LOCKHASH_PARTS; i++) s = s * 33u"),
    M("lh-fold-high", "    return (uint16_t)((s >> 16) + s);\n",
      "    return (uint16_t)s;\n"),

    # -- the draws and the log
    M("lh-watch-frame", "    d->frame = L.frame;\n", "    d->frame = 0;\n"),
    M("lh-watch-at", "    d->at    = (uint32_t)(uintptr_t)at;\n", ""),
    M("lh-watch-count", "    L.drawn++;\n", ""),
    M("lh-start-on", "    L.on  = 1;\n", ""),
    M("lh-start-ring", "    for (i = 0; i < NETSTEP_RING; i++) L.ringFor[i] = NETSTEP_NONE;\n",
      ""),
    M("lh-start-watch", "    bDefaultSeedWatch = watch;\n", ""),
    M("lh-start-view", "    bViewSeed  = &L.viewSeed;\n", ""),
    M("lh-stop-off", "    L.on = 0;\n", ""),
    M("lh-stop-view", "    if (bViewSeed == &L.viewSeed) bViewSeed = &bDefaultSeed;\n",
      ""),
    M("lh-stop-watch",
      "    if (bDefaultSeedWatch == watch) bDefaultSeedWatch = NULL;\n", ""),
    M("lh-ran-for", "    L.ringFor[n & MASK] = n;\n", ""),
    M("lh-ran-frame", "    L.frame = n + 1;\n", "    L.frame = n;\n"),
    M("lh-ran-every", "    if (n % NETSTEP_LOG_EVERY == 0) logParts",
      "    if (n % NETSTEP_LOG_EVERY == 1) logParts"),
    M("lh-ran-fold", "    return lockhash_fold(h);\n", "    return 0;\n"),
    M("lh-parts-order",
      "        (unsigned long)h->part[LOCKHASH_RACERS],\n"
      "        (unsigned long)h->part[LOCKHASH_COPS],\n",
      "        (unsigned long)h->part[LOCKHASH_COPS],\n"
      "        (unsigned long)h->part[LOCKHASH_RACERS],\n"),
    M("lh-draws-first",
      "    first = L.drawn > LOCKHASH_DRAWS ? L.drawn - LOCKHASH_DRAWS : 0;\n",
      "    first = L.drawn > 4 ? L.drawn - 4 : 0;\n"),
    M("lh-draws-count",
      "        if (L.draws[i & DRAW_MASK].frame == n) count++;\n",
      "        count++;\n"),
    M("lh-draws-frame", "        if (d->frame != n) continue;\n", ""),
    M("lh-draws-line", "        if (++onLine == LOCKHASH_LINE) {\n",
      "        if (++onLine == LOCKHASH_LINE + 1) {\n"),
    M("lh-draws-rest", "    if (onLine) say(\"%s\", line);\n", ""),
    M("lh-differs-on", "    if (!L.on || L.logged) return;\n",
      "    if (L.logged) return;\n"),
    M("lh-differs-once", "    if (!L.on || L.logged) return;\n",
      "    if (!L.on) return;\n"),
    M("lh-differs-window", "    for (k = 0; k < LOCKHASH_WINDOW; k++) {\n",
      "    for (k = 1; k < LOCKHASH_WINDOW; k++) {\n"),
    M("lh-differs-zero", "        if (n < LOCKHASH_WINDOW - 1 - k) continue;",
      "        if (n < LOCKHASH_WINDOW - k) continue;"),
    M("lh-differs-ran", "        if (L.ringFor[f & MASK] != f) continue;\n",
      ""),
    M("lh-differs-draws", "        logDraws(f);\n", ""),

    # -- bmath.c's watch
    B("bm-watch-seed", "if ((seed) == &bDefaultSeed && bDefaultSeedWatch != NULL)",
      "if (bDefaultSeedWatch != NULL)"),
    B("bm-watch-i", "    WATCH(seed);\n    return randomI(range, seed);\n",
      "    return randomI(range, seed);\n"),
    B("bm-watch-set", "    WATCH(seed);\n    *seed = s;\n", "    *seed = s;\n"),
    B("bm-watch-f", "    WATCH(seed);\n    r = randomI(0x7fffffff, seed);\n",
      "    r = randomI(0x7fffffff, seed);\n"),
    B("bm-watch-f-twice", "    r = randomI(0x7fffffff, seed);\n",
      "    r = bRandomI(0x7fffffff, seed);\n"),
]

EQUIVALENT = {
    # The mix needs only to move with every word: an odd multiply is a
    # bijection, so xor or add, with the shift or without, each does.
    "lh-mix-xor",
    "lh-mix-shift",
    # No helicopter or no Race marked by a 0 or by nothing: either way
    # the part differs from one with it, which mixes its fields.
    "lh-chopper-null",
    "lh-race-null",
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
        todo, SOURCES, "lockhash_test",
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
