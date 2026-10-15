# A local wireless race in lockstep (TASKS 37d)

The port's own. Retail's two players share one PS2, so one game reads
both pads. The port's are on consoles of their own (TASKS 37, "The
design"): each console runs the whole race, and they stay one race by
running the same frames on the same input. `netrace.c`
(`docs/formats/netrace.md`) leaves every console at GO on one seed;
`netstep.c` runs the race from there, frame by frame.

- `netstep.c` has no `<3ds.h>`. The link comes in through `NetStepNet`
  and the time is given, so the check runs up to eight consoles in one
  process (`netstep_bind`). `main.c` fills the link (`kNetStepNet`).
- Retail is unchanged where `PlayerNetLocal` is -1 (`player.h`), which
  is every race but a wireless one.

## A frame

From GO on, each loop of `main.c` (`lockFrame`):

1. Measures its step, from the last frame's begin to this one's, as
   retail's MainLoop does (`prepare_real_timestep_from_ticker`).
2. Reads its own pad (`joyhid_read`, port 0, with this console's
   layout: the race's, a cop's, the menus') and puts it, with the step
   and the flow's presses since the last begin, for the frame
   `NETSTEP_DELAY` (3) ahead (`netstep_put`).
3. Waits up to 8 ms for the frame's record, pumping the link
   (`netstep_poll`). A record later than that leaves the loop drawing
   without stepping; the next loop asks again and puts nothing new.
4. Runs the frame on the record alone: its step for the world's
   (`RealTimeElapsedQuantized`), place p's pad on port p
   (`gJoypadRead = joypadRead`, `joyhid_from_wire`), and each live
   place's presses for the flow on its port (`lockFlowInput`).
   `bgf_frame`, `raceFrame` and the UI's timer run only on such a frame,
   and the clocks advance only after one (`g_lockRan`).
5. Gives the world's checksum after it (`netstep_done`, `lockhash_ran`:
   the fold of seven parts, retail's debug checksum among them; see
   `lockhash.md`).

Frames 0 to 2 need no wait: no pad is in for them, and each console
makes them as the host would, every pad at rest, each step 120 (1/30 s).

At GO (`netRaceGoRacing`, netrace's `goRacing`) the places racing are
those netrace gave a driver, and this console's. The pad port 0 last
read was this console's alone, so its ring's last entry is set to a pad
at rest: the first frame's edges are then the same on every console.
Port 1 has read nothing on any console before GO. The clocks at GO are
logged; they may differ between consoles (37e's).

Lockstep stops (`netstep_stop`) once the race coordinator is gone, after
a lockstep frame ran with it up (`g_lockRaced`): the coordinator is made
in the GO loop's own flow pass.

### The pad

Eight bytes: a DualShock 2 buffer's bytes 2 to 7 as `joyhid_build`
makes them (the sixteen buttons, active low, then the right and left
sticks' x and y), and a u16 of the 3DS keys newly pressed for the flow's
screens (`menu`: the pause menu, the results). The twelve pressure bytes
are not sent: each is 255 where its button is down, so
`joyhid_from_wire` makes them again, and its buffer is `joyhid_build`'s
byte for byte (joyhid_check's round trip over every set of keys and each
layout). A pad at rest is buttons 0xffff, sticks 0x80, no presses.

### What each console shows

Every console runs both players. `PlayerNetLocal` is this console's
player (place 1 is player 1, every other place player 0), set once
netrace's stage reaches `NR_LOADING` and back to -1 once the coordinator
is gone:

- `playerinit.c`: the local player gets view 1, mirror 3, the HUD's
  SINGLE screen and the NIS overlay; the other gets view 2, no mirror,
  no HUD and no NIS.
- `eview.c`: `eViewShowOne`, so `eUpdateViewMode` never answers the
  split screen; the mode is 2, view 1 and the mirror.
- `PLAYER_SHOWN_COUNT(n)`, `PLAYER_NUM_SHOWN()` and `player_shown(i)`
  (`player.h`) stand in for the player count and `PlayerPlayersByIndex`
  where only what is shown reads them: `playerhud.c`, `hudanim.c`,
  `hudscore.c`, `sound3d.c` (the active cameras and the azimuth),
  `eenvmap.c` (the fallback car), and `main.c`'s bottom screen, track
  map, sound players and race layout.
- Simulation and content stay retail's: carmove, traffictele, the AI,
  playerinput, playerupdate, playerzone, playernis, racespeech,
  trackmap's 2P draw, cameracoord, hudrender's tickets and places, warp,
  cardamageabove and rendercars.

### The screens' ports

Retail's SetScreenFilterPort (0x0016d4c8) gives a screen one port that
drives it; the pause sets it for its eight screens, so only the pad that
paused drives them. `hookSetScreenFilterPort` (`gSetScreenFilterPortFn`)
keeps it by the screen's hash. A menu made for the screen takes it
(`filterPort`), and the screen's own START and BACK filter on it in
`flowInput(kDown, port)`.

## The messages

Both unreliable (`wlproto.h`), after netrace's, each repeating what the
other side still needs, sent again every 16 ms:

| Type | Name | From | Body |
|---|---|---|---|
| 0x16 | `NETSTEP_MSG_PADS` | a client | header, then its pads from `first` |
| 0x17 | `NETSTEP_MSG_FRAMES` | the host | header, then the records from `first` |

The header, 15 bytes, little-endian:

| Offset | Size | |
|---|---|---|
| 0 | 4 | `need`: the sender's next record not in (a client's), or next built (the host's) |
| 4 | 4 | `first`: the first pad or record that follows |
| 8 | 1 | `count` |
| 9 | 4 | the frame of the sender's last checksum (0xffffffff: none run) |
| 13 | 2 | that checksum |

A pad is the 8 bytes above. A record is its step `q` (1/3600 s), the
live places' mask, then the pad of each live place in place order. A
message whose lengths do not add up is dropped. With two places a
FRAMES message holds 12 records and a PADS message 28 pads.

The host builds record n once every live place's pad for n is in, puts
its own step in it, and sends each client the records from the first it
said it lacks. A client sends its pads from the first the host said it
lacks.

## A console lost

The race's link keeps netrace's patience until frames have flowed for 30
past the delay (the first frame's long drawing), then has its own
timeout back (`setPatience(0)`, "frames flow"). The host builds without
a client whose link is lost, its pad at rest from then on ("place p is
gone"). A client that loses the host goes on alone, its own pad on its
place and the rest at rest. What more a race does then is 37f's and
37g's.

## The checksums

Every message carries the sender's checksum of the last frame it ran.
Each console keeps a ring of its own and compares a frame once both are
in, saying in the log once per place where one differs ("frame n
differs from place p's"), and tells the `NetStepDifferFn` set with
`netstep_on_differ`: main.c's has lockhash log the parts and draws of the
16 frames up to it (37e, `lockhash.md`). Every 150 frames each logs its
own ("frame n hash h").

## The check

`python tools/netstep_check.py` builds `tools/src/netstep_test.c`, which
runs up to eight consoles in one process over a fake link that loses,
repeats and reorders, and checks each record each console runs: a clean
link, a lossy one, a slow one and one slower than the delay; either side
slow, the client's GO late, the first frame stalling for seconds; eight
on a lossy link; clients and the host gone; a checksum differing; a
place not racing; the host stopping; netrace's messages on the same
link. 20 scenarios, faults 0. `--mutate`: 107 mutations, 104 caught, 3
equivalent (named in the check).

## On Azahar

`tools/run_azahar_lobby.ps1 -Consoles 2 -Race` takes two copies from the
lobby to the race, then holds A (the gas) on both for `-Drive` seconds
(30), a shot of each every 10 s. Every copy must log the lockstep's
start and its frames flowing; since 37e every copy's parts must match
the host's, frame by frame (`lockhash.md`).

The first run (Session 101): track 11, 2 laps, the host, the client and
2 CPU racers, GO on seed 793ca5cb. The clocks at GO differed (real
731666 on the host, 723683 on the client), yet every checksum logged
matched, frame 0 (bae8) to frame 1200 (323a), and neither copy said one
differed. Frames flowed from frame 32. Each copy showed its own car,
mirror and HUD: the host its Opel Speedster in 4th, the client its
Vauxhall VX220 in 3rd, with the same places and the same minimap on
both, at 28 FPS each. Not tried yet: the pause menu from either console
and the race's end (37f).
