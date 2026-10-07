# New 3DS mode (step 13b-3)

What the port asks of a New 3DS, how it checks that it got it, and what
it does with it. Nothing here is in either image: the PS2 had one CPU,
one clock and 32 MB. Each part is checked at runtime instead of being
assumed from `app.rsf`.

## What the CIA asks for

`3DS Files/meta/app.rsf` puts these in the ExHeader. The kernel applies
them at launch on a New 3DS, and an Old 3DS ignores them:

| Field | Value | What it gives |
|---|---|---|
| `SystemModeExt` | 178MB | the APPLICATION region, against an Old 3DS's 96MB (`SystemMode`) |
| `CpuSpeed` | 804MHz | three times the 268 MHz clock |
| `EnableL2Cache` | true | the New 3DS's 2 MB L2 cache |
| `CanAccessCore2` | true | the third core |
| `AffinityMask` | 3 | cores 0 and 1 |

The .3dsx gets none of it from the ExHeader. It runs inside the
Homebrew Launcher's process, with that process's memory and services.

## The clock

`initPlatformPerf` calls `osSetSpeedupEnable(true)` on a New 3DS. In
libctru 2.4.1 that is `ptmSysmInit` then
`PTMSYSM_ConfigureNew3DSCPU(3)` (804 MHz and the L2 cache). APT makes
the same call from `aptWaitForWakeUp`, each time the app wakes from
the HOME menu or from sleep.

**The CIA could not open ptm:sysm.** Its service list had `ptm:u` and
not `ptm:sysm`. So the call failed silently, and the CIA ran at the
ExHeader's clock. Nothing put that clock back after a trip to the HOME
menu. Step 13b-3 adds `ptm:sysm` to the list.

**The `clock:` line** at boot (`logClock`, `main.c`) checks it:

- whether ptm:sysm opened, or its Result;
- on a New 3DS with it, a loop of 2,000,000 `subs`/`bne` turns, timed by
  `svcGetSystemTick`, three times: as launched, with the speedup off,
  and with it back on;
- the last two's ratio, which is the clock's. It is about 3 when the
  speedup takes.

The system tick counts 268 MHz at either clock, so only the ratios mean
anything. The speedup is left on.

## The memory

`heapcfg.c` divides the grant between the linear heap (contiguous, for
the GPU: textures, vertex buffers, audio) and the malloc heap (the
bundles and everything else).

13b-2's log measured both in a race on track 12. Once the track is in,
the race uses about 43 MB of linear (33.6 MB free of 76) and 38 MB of
heap (23 MB at LOADING_TRACK_SPECIFIC and about 15 MB of the track's
bundles), with about 10 MB of heap to spare. The malloc heap is the
tighter of the two.

So since 13b-3:

- The linear heap asks for what is left after the heap's 48 MB, as
  before, but no more than 80 MB (`LINEAR_WANT`). That is the race's
  43 MB plus room for the AI's and the cops' cars. It also stays under
  one 128 MB FCRAM bank, as before.
- The malloc heap takes everything the linear heap left, up to its 96 MB
  window (`OS_HEAP_AREA_BEGIN` to `OS_HEAP_AREA_END`), and never less
  than its 48 MB.

| Grant | Linear | Malloc heap |
|---|---|---|
| New 3DS, CIA, 178 MB | 80 MB | 96 MB |
| New 3DS, .3dsx (Azahar's), 124 MB | 74.6 MB | 48 MB |
| Old 3DS, CIA, 96 MB | about 46 MB | 48 MB |

The bottom two divide as they did before 13b-3. Both step-downs stay:
an ask that the kernel refuses costs 4 MB a try, not a panic.

## An Old 3DS

Since 2026-10-05 the port is for the New 3DS alone, the user's call.
`main` checks `APT_CheckNew3DS` right after the `console:` line. On an
Old 3DS or 2DS it logs `console: not a New 3DS, so the port stops
here`, puts the reason on the top screen (`fatalConsole`, as for
missing data) and exits on START:

    This port needs a New 3DS, New 3DS XL
    or New 2DS XL.

    A race needs more memory and a faster CPU
    than an Old 3DS or 2DS can give it.

Why there is no Old 3DS mode:
- **Memory.** The user's Old 3DS ran the .3dsx under the Homebrew
  Launcher with 64 MB: a 31.8 MB heap and a 31.8 MB linear heap.
  Holding R went to the race, and loading TRACKB12 ran the heap out:
  bMalloc's abort, back to the launcher. The race needs about 43 MB of
  heap and 46 MB of linear heap. A CIA would get 96 MB (`SystemMode`),
  with little to spare once the AI's and the cops' cars load, and that
  Old 3DS would not install the CIA.
- **The CPU.** 268 MHz without the L2 cache, a third of the New 3DS's.
  The GPU is the same on both.

Azahar shows the message with `is_new_3ds=false` in
`%APPDATA%\Azahar\config\qt-config.ini`.

## The cores

- **Core 0** runs the game, as the PS2's one CPU did. Two other threads
  share it, since `-2` in threadCreate is the process's own core
  (`IdealProcessor: 0`):
  - the jukebox's stream worker (`jbstream.c`), which reads a tune's
    blocks off the card and decodes the SPU ADPCM;
  - libctru's ndsp thread.
- **Core 1**, the system core, lets the app have 80% of it
  (`APT_SetAppCpuTimeLimit(80)`). The movie decoder runs there on an Old
  3DS.
- **Core 2** runs the movie decoder on a New 3DS (`avimovie.c` tries 2,
  then 1).

The jukebox's worker preempts the game wherever it wakes, so its time is
inside whichever phase it interrupts. Since 13b-3 the worker sums its
own time, in EE ticks: decoding, and reading the card (`jbstream_busy`,
read without the worker's lock). Only the decode is CPU time; a read
sleeps in the kernel while the FS module works. The log has it twice:

- in a race, the `frame:` line's `jukebox:` section, per frame;
- out of a race, a line of its own every five seconds while a tune
  streams: `jukebox: decode 7.01 ms a second, read 7.84, over 5.0 s`.

The flow, the loads and the jukebox's poll each take 0.1 ms or less of
a race frame, and the draw is 45 of the 50. Moving the draw, or a stage
of it, changes the game's order of work. That is a 13b-4 decision, made
with a New 3DS's numbers.

## On Azahar

Two runs of the 13b-3 build: a race on track 12, holding the gas
(`out/azahar_13b3b`), and the boot to the menus (`out/azahar_13b3_fe`).

- **The memory.** Azahar runs the .3dsx with a 124 MB grant, so the
  split is as before: `heap 49152KB, linear 76416KB`. The CIA's 178 MB
  split is for the hardware to show.
- **The clock.** `clock: ptm:sysm open; 2000000 loops in 14.98 ms as
  launched, 14.98 ms without the speedup, 14.98 ms with it (x1.00)`.
  Azahar's own log has four ConfigureNew3DSCPU calls arriving at
  ptm:sysm, with 0, 3, 0 and 3: the launch's, then `logClock`'s off and
  on. It reports each one as unimplemented. The service opens and the
  calls go through, but Azahar keeps one clock. Only a New 3DS can show
  the x3.
- **The jukebox.** In the menus, with "Hot Action Cop" streaming, the
  worker decodes for 6.1 to 7.0 ms a second and is in its reads for 5.2
  to 7.8 ms a second. That is 0.35 ms of CPU in a 50 ms frame, under 1%
  of core 0.
- **No music in a race (fixed in Session 43).** The race's `jukebox:`
  section read 0.00 throughout. The flow stops the jukebox when the menus
  go (`bgf_unlaunch_frontend_menus`, as retail does), and retail starts it
  again from the race coordinator's TICK, with DelayedStart(6.0), once the
  ReplayManager has marked the beginning of time (`race-coordinator.md`).
  The port's stand-in ReplayManager now keeps that Timer, and main.c sets
  the jukebox's seams (`jukebox.md`, "The race's music"), so the race's
  tune starts six seconds after GO.

**The cores, decided.** The jukebox's worker stays on core 0. At under
1% of the core, moving it would save 0.35 ms a frame at most. Nothing else outside the draw is worth moving, so 13b-3 moves nothing.
13b-4 decides for the draw's stages.

**What the hardware has to show:** the clock line's x3, the CIA's
96 MB heap and 80 MB linear heap, and the `frame:` line at 804 MHz.
