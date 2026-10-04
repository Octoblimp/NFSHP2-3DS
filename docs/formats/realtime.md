# The clock object -- the video mode, the real clock and the world clock

    0x001992a0 .. 0x001995d8    nine functions, 824 bytes
    0x001995d8                  WorldTimeDoSnapshot (not ported)
    0x00323cc8 .. 0x00323d0c    eighteen globals in .sdata, gp-20264 up

These are free functions and plain globals, with no class. In the image
they sit between CopMover's inline setters and the string helpers
(`IntToString`, 0x00199678). MainLoop (0x0012dbd0) prepares and advances
both clocks.

The port is `3DS Files/source/realtime.{c,h}`. It is cross-checked by
`tools/realtime_check.py` against `tools/src/realtime_test.c`, with the
image running in mipsemu as the oracle. Everything is ported except
`WorldTimeDoSnapshot`, which waits on ReplaySnapshot like every
`DoSnapshot`.

The addresses here are the demo's. Retail has the same nine at
0x001a3390 .. 0x001a36c0 and the globals at 0x00330c50 (gp-19616 up), and
the checker runs retail's. Retail differs in two places:

- **Timer::SetTime rounds.** Retail's (0x00136dd0, and the copies other
  objects carry) is `cvt.w.s(seconds * 4000 + 0.5)`; the demo's
  (0x00134ef0) had no 0.5. A sixtieth of a second is 66.67 ticks, so
  retail's clocks step 67 a frame where the demo's stepped 66. The port's
  `timer_set_time` is retail's.
- **ResetWorldTime** loads 4000.5 from gp-29404 for its one second, the
  rounding folded in, where the demo built 4000.0 with `lui`. Both
  truncate to 4000.

## The globals

| gp | Address | Name | .sdata | What it is |
|---:|---------|------|-------:|------------|
| -20264 | 0x00323cc8 | FrameCounter | 0 | vertical blanks since boot |
| -20260 | 0x00323ccc | CurrentVideoMode | 1 | 0 PAL, 1 NTSC |
| -20256 | 0x00323cd0 | RealTimer | 0 | 1/4000 s |
| -20252 | 0x00323cd4 | RealTime | 1 | a copy of RealTimeFrames |
| -20248 | 0x00323cd8 | RealTimeFrames | 1 | sixtieths, at least one a frame |
| -20244 | 0x00323cdc | RealTimeElapsed | 0.0 | the frame's step, in seconds |
| -20240 | 0x00323ce0 | RealTimeElapsedQuantized | 0 | the step, in 1/3600 s |
| -20236 | 0x00323ce4 | RealTimeElapsedFrame | 0.0 | what is left under a sixtieth |
| -20232 | 0x00323ce8 | RealTimeElapsedError | 0.0 | the step's rounding, carried |
| -20228 | 0x00323cec | RealLoopCounter | 0 | AdvanceRealTime calls |
| -20224 | 0x00323cf0 | WorldTimer | 0 | 1/4000 s |
| -20220 | 0x00323cf4 | WorldTimeSeconds | 1.0 | WorldTimer in seconds |
| -20216 | 0x00323cf8 | WorldTime | 1 | a copy of WorldTimeFrames |
| -20212 | 0x00323cfc | WorldTimeFrames | 1 | sixtieths |
| -20208 | 0x00323d00 | WorldTimeElapsed | 0.0 | the prepared step, in seconds |
| -20204 | 0x00323d04 | WorldTimeElapsedFrame | 0.0 | what is left under a sixtieth |
| -20200 | 0x00323d08 | WorldLoopCounter | 100000 | AdvanceWorldTime steps |
| -20196 | 0x00323d0c | NeedToPrepareWorldTimestep | 1 | set by Advance, cleared by Prepare |

`WorldTimer` starts at 0, while `WorldTimeSeconds` starts at 1.0. The two
agree only after the World's constructor calls ResetWorldTime.
`FrameCounter` belongs to the vertical-blank handler. MainLoop only reads
it, to wait out the frame.

The port used to define four of these elsewhere. `WorldTimer` was in
`engine.c`, `WorldTimeElapsed` in `drivetrain.c`, `WorldLoopCounter` in
`world.c`, and `RealTimeElapsed` in `cammover.c` (at 1/60). All eighteen
are in `realtime.c` now. A harness that does not link it defines the ones
its files read.

## The video mode

- **GetVideoMode** (0x001992a0) returns `CurrentVideoMode`.
- **SetVideoMode(m)** (0x001992a8) stores `m` and returns the mode it
  replaced.

InitDisplaySystem (0x00100750) is the one caller. It sets PAL if
`PAL.TAG` exists (`bFileExists`) and NTSC if not, then hands the mode to
`eSetDisplaySystem`. The port keeps the image's NTSC. Anything but 0
counts as NTSC, because PrepareRealTimestep tests for PAL.

## The quantisation

- **GetRealTimeElapsedFromQuantized(q)** (0x001992b8) returns
  `(float)q * 0x3991a2b4`, which is 1/3600, from gp-29848.
- **GetQuantizedRealTimeElapsed(s)** (0x001992d0) returns
  `cvt.w.s(s * 3600.0 + 0.5)`. Both constants are immediates. The add is
  a separate rounding, and `cvt.w.s` saturates by sign.

## PrepareRealTimestep(s), 0x00199300

MainLoop passes it the ticker's measure of the last frame:
`bGetTickerDifference` times gp-32124.

    loop = RealLoopCounter & 15                  read before anything else
    if Joylog::ReplayingFlag:
        q = Joylog::GetData(8, channel 2)
        Joylog::GetData(4, channel 4)            read, and dropped
    else:
        s = s * 1.0167 + RealTimeElapsedError    gp-29844, 0x3f82233a
        if GetVideoMode() == PAL:
            s = min(0.06, max(s, 0.02))          gp-29840, gp-29836
        else:
            s = min(0x3d4cccce, max(s, 1/60))    gp-29832, gp-29828
        q = GetQuantizedRealTimeElapsed(s)
        Timer::SetTime(&t, GetRealTimeElapsedFromQuantized(q))
        RealTimeElapsedError = s - (float)(int)t * 0.00025
        Joylog::AddData(q, 8, channel 2)
        Joylog::AddData(loop, 4, channel 4)
    RealTimeElapsedQuantized = q
    RealTimeElapsed = GetRealTimeElapsedFromQuantized(q)

Four things here are easy to get wrong.

**NTSC's ceiling is 0x3d4cccce**, one ulp above 0.05f (0x3d4ccccd). The
port spells it `0.050000004f`. Clamping to 0.05f changes the error term
by that ulp, and the checker catches it.

**The error is what the timer loses, not what the quantisation loses.**
The quantised step goes back to seconds and then to whole ticks of
0.00025 s through Timer::SetTime. The error is the clamped step minus
those ticks. So `RealTimer`, which AdvanceRealTime adds those same ticks
to, tracks the scaled ticker to within a tick. The error goes into the
next step *after* the 1.0167 scale.

**Replaying, the step comes out of the log unclamped**, and the loop
count's four bits are read and dropped. Recording writes them, and
replaying only reads past them. With no repeat, both reads give 0, so the
step is 0.

**The clamp is `max.s` then `min.s`.** The port writes it as two compares:
`s < lo` takes lo, and `hi < s` takes hi. That is the same thing for every
step the ticker can measure.

## AdvanceRealTime, 0x00199410

    acc = RealTimeElapsedFrame + RealTimeElapsed
    n = cvt.w.s(acc * 60.0)
    RealTimeFrames += (n != 0 ? n : 1)           movn
    RealTime = RealTimeFrames
    RealTimeElapsedFrame = acc - (float)n * 0x3c888889
    Timer::SetTime(&t, RealTimeElapsed)
    RealTimer += t
    RealLoopCounter += 1

The minimum of one is a `movn`, so only a zero count is replaced. A
negative step's negative count is kept. The remainder uses `n` itself, not
the count that was added, so a fast frame's time is still carried. The
adds are `addu` and wrap.

## The world clock

**ResetWorldTime** (0x001994a8) sets the frame counts to 1, the timer to
`cvt.w.s(4000.0)`, and the step, the remainder and the loop count to 0.
It sets the seconds to those ticks times 0.00025, which is 1.0. It does
not touch `NeedToPrepareWorldTimestep`. The World's constructor and
destructor call it.

**PrepareWorldTimestep(s)** (0x001994f8) stores the step and clears
`NeedToPrepareWorldTimestep`. MainLoop gives it one of three things:

- `World::GetTimestep` in a race;
- 0 while the game flow, the world or the replay is paused;
- `RealTimeElapsed` when there is no race.

**AdvanceWorldTime** (0x00199508):

    NeedToPrepareWorldTimestep = 1               the branch's delay slot
    if WorldTimeElapsed == 0.0: return           c.eq.s, so -0.0 too
    acc = WorldTimeElapsedFrame + WorldTimeElapsed
    n = cvt.w.s(acc * 60.0)
    WorldTimeFrames += n                         no minimum
    WorldTime = WorldTimeFrames
    WorldTimeElapsedFrame = acc - (float)n * 0x3c888889
    Timer::SetTime(&t, WorldTimeElapsed)
    WorldTimer += t
    WorldTimeElapsed = 0.0                       the step is used up
    WorldLoopCounter += 1
    WorldTimeSeconds = (float)WorldTimer * 0.00025

A step of 0 sets the flag and changes nothing else. So a paused world
keeps its frame count and its loop count. The seconds come from the
*signed* timer after the add. Once the timer wraps, they are negative.

## MainLoop's order

The demo's addresses, then retail's (MainLoop is `0x0012f378` there):

    s2 = bGetTicker()                                      retail 0x0012f3a0
    loop:
    LastFrameCounter = FrameCounter                        gp-23228
    ... the flow, the coordinator, the pads ...
    PrepareRealTimestep(ticker difference * 0.001)  0x0012dc98, 0x0012f454
    s2 = bGetTicker()                                      0x0012f45c
    PrepareWorldTimestep(...)                              0x0012dce8 ..
    GenerateJoyEvents()
    ... the frame, eDisplayFrame ...
    AdvanceRealTime()                               0x0012de70, 0x0012f62c
    AdvanceWorldTime()                              0x0012de78, 0x0012f634
    wait until FrameCounter - LastFrameCounter > 0         0x0012f648

**The measure** is `bGetTickerDifference(s2, bGetTicker())`, in
milliseconds, times gp-32048 (gp-32124 in the demo), which is 0.001. It
runs from the last frame's tick, read just after that frame's prepare, to
this one's. bGetTickerDifference divides the EE's 294.912 MHz count by
300 MHz, so its milliseconds are 1.7% short. The 1.0167 in
PrepareRealTimestep puts that back: 294.912 × 1.0167 / 300 is 0.99946.
So RealTimeElapsed is the frame's real time, held to 1/60 to 0.05 s on
NTSC. The game runs in real time down to 20 frames a second, and slows
below that.

**The wait** makes every frame at least one vertical blank long, so
retail never runs faster than 60. `FrameCounter` is the count PSX2VBlank
keeps.

## The frame on the 3DS (step 13b-1)

The port's main loop makes the same calls in the same order. It advances
both clocks at the top of the next frame instead of the end of this one.

- **The measure** is `prepare_real_timestep_from_ticker(&frameTicker)`
  in `realtime.c`, retail's fragment line for line. `frameTicker` is s2,
  read first just before the loop. `bGetTicker` scales the 3DS's system
  tick to the EE's 294.912 MHz (`bticker.h`), so the difference means
  what it meant on the PS2. Until 13b-1 the measure was a constant 1/60,
  and a race drawn at 20 frames a second ran at a third of real time.
- **FrameCounter** is the top screen's vertical-blank count,
  `C3D_FrameCounter(0)`, set at the top of each frame. citro3d counts it
  in its own blank handler, at its default rate of 60. The joy events'
  repeats (6 and 25 blanks) and the jukebox's seed read it.
- **The pacing.** In a race (the track's view attached) a frame takes at
  least two blanks. C3D_FrameBegin's sync waits for the next blank, and
  when none has come since the last frame's, the loop waits one more
  first. So a frame that fits in 33.3 ms is shown for exactly 33.3 ms,
  and no frame is 16.7 ms between two of 33.3. A slower frame is not held
  back further: it waits for the next blank, as on the PS2. The frontend
  and the movies stay at 60.
- **The other clocks** take the real step too: the flow's own copy
  (`bgf_frame`), the blurb's fade, the UI's scrolling-texture counter and
  the two viewers. The jukebox's delayed start counts down by
  `WorldTimeElapsed` (gp-19560), as sound::Update does. sound::Update's
  8 ms gate passes at any rate up to 125 frames a second, so the port
  leaves it out.
- **The log.** Each world second of a race logs `race: clock`, with the
  wall clock, RealTimer, WorldTimeSeconds, the step, the blanks and the
  frames drawn. Two lines apart give the frame rate, the blanks a frame,
  and whether the clocks keep pace with the wall.

**On Azahar** (track 12, Speed 101%):

- The race draws 20 frames a second, three blanks each, and the blanks
  come at 59.8 a wall second.
- The step sits at NTSC's ceiling, 0.05 s, with a few at 0.048 to 0.0497.
  A 50 ms frame scaled by 1.0167 is just over it.
- While the frames take 50 ms or less, the world keeps pace with the
  wall: 5.986 world seconds in 6.017 wall seconds. When they run past
  50 ms the ceiling drops the excess, as on the PS2, and the world gets
  about 0.93 of a wall second.

The race used to run at a third of real time. It now runs at real time.

## Checking it

    python tools/realtime_check.py
    python tools/realtime_check.py --mutate

Both sides walk one script of ops: set and get the mode, the two
conversions, prepare and advance each clock, reset the world, set the
joylog's flags, feed the log, and poke a global. After each op, both
print the eighteen globals as words. The model reads them out of the
image's own .sdata, so the port's initial values are checked as well. The
joylog is the image's `Joylog::GetData` and `AddData` on one side and
`joylog.c` on the other. Each sits over a repeat that logs every call and
answers from the script's feed.

The script covers:

- both conversions, from 0 to the saturating ends;
- thirty NTSC frames and twenty-five PAL frames at their rates;
- a spread of steps, from negative to a second;
- each window's edges, exactly and one ulp either side, with the step
  poked into the error term so it arrives unscaled;
- mode 5, which counts as NTSC;
- replaying: with steps from the feed, with a dry feed, and with no
  repeat;
- not capturing;
- the loop count's four bits across both wraps;
- AdvanceRealTime from poked steps: zero, negative, huge and tiny, and
  the timer and frame count wrapping;
- the world clock before a reset, after it, at 0 and -0, with negative
  and huge steps, and wrapping;
- a 600-op random walk.

Since 13b-1 it runs MainLoop's measure too. The model runs retail's
fragment from `0x0012f43c`, with s2 set, and the stub for
IsGameFlowPaused (`0x001680b8`) ends the run; s2 then holds the new tick.
The harness calls `prepare_real_timestep_from_ticker`. On both sides
bGetTicker answers from the script and logs each read, so the number of
reads and their order against the joylog's calls are compared. The frames
are:

- 90 at 30 a second, 40 at 20, 60 at 60, and 30 at two of the 3DS's
  blanks (59.83 Hz);
- 200 jittered, from 10 to 70 ms;
- twelve across the 32-bit counter's wrap;
- a second's load, 14 and 15 s (past the wrap, so the difference wraps
  small), no time at all, and backwards, with the difference's top bit
  set;
- PAL at 25 and 60 a second;
- replaying, where the step comes from the log but both ticks are still
  read;
- a dry ticker, which reads 0.

The result is 28 scenarios, 2016 ops and 8781 lines, with 0 differ.
There are 103 mutations: 101 are caught and 2 are equivalent by
construction. `ml-ticker-kept` and `ml-one-read` leave a tick unread each
frame, so the script's ticks overflow the harness's queue and it exits
(caught). The two equivalent mutations:

- `pr-error-unsigned` reads the timer as unsigned in the error term. A
  clamped step is 66 to 240 ticks, so the top bit is never set.
- `rw-seconds-one` writes ResetWorldTime's seconds as 1.0f.
  `(float)4000 * 0x3983126f` rounds to exactly that.
