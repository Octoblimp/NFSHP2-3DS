# Azahar's TimeStretcher::Process (audio_core/time_stretch.cpp), simulated:
# a 10 s freeze (no input), then input at the native rate. Prints the
# tempo and backlog over the recovery. Azahar stops the whole console
# while its keyboard dialog is open, and this is why the port holds the
# sound 3.5 s after it there (main.c's holdAudio, docs/formats/name-entry.md).
#
# Usage: python tools/azahar_stretch_sim.py
import math

rate = 32728.0
num_out = 512                      # samples per output callback
dt = num_out / rate
ratio = 1.0
backlog = 0.5 * 0.25 * rate        # settled: half of 0.25 s
t = 0.0
freeze = 10.0
fifo = 0.0                         # samples the DSP made, not yet popped
log_every = 0.25
next_log = freeze
while t < freeze + 6.0:
    produced = 0.0 if t < freeze else rate * dt
    fifo += produced
    num_in = fifo
    fifo = 0.0
    cur = num_in / num_out
    fullness = backlog / (0.25 * rate)
    if fullness > 4.0:
        num_in = 0
    tweak = (fullness - 0.5) * (dt / 0.05)
    cur *= math.pow(1.0 + 2.0 * tweak, 3.0 if tweak < 0 else 1.0) if 1.0 + 2.0 * tweak > 0 else 0.0
    gain = 1.0 - math.exp(-dt / 0.712)
    ratio += gain * (cur - ratio)
    ratio = max(ratio, 0.05)
    backlog += num_in
    used = min(backlog, num_out * ratio)
    backlog -= used
    t += dt
    if t >= next_log:
        print("t=%5.2f after  tempo=%.3f  backlog=%.3fs" % (t - freeze, ratio, backlog / rate))
        next_log += log_every
