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

Lockstep stops (`netstep_stop`, "The end" below) after the frame that
asks for the end's save (`g_lockEnd`), or once the race coordinator is
gone (the pause's Quit), after a lockstep frame ran with it up
(`g_lockRaced`): the coordinator is made in the GO loop's own flow pass.

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

The header, 19 bytes, little-endian:

| Offset | Size | |
|---|---|---|
| 0 | 4 | `need`: the sender's next record not in (a client's), or next built (the host's) |
| 4 | 4 | `first`: the first pad or record that follows |
| 8 | 1 | `count` |
| 9 | 4 | the frame of the sender's last checksum (0xffffffff: none run) |
| 13 | 2 | that checksum |
| 15 | 4 | `stopAt`: the frames the sender ran before its stop (0xffffffff: still on; 37f) |

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
place and the rest at rest. What more a race does then is 37g's.

## The end (TASKS 37f)

Each console leaves lockstep after the same frame, as each runs the same
flow on the same pads (`main.c`, after the frame's checksum):

- the frame that asks for the end's save (`endGameAutosaveNow`, the
  autosave completion's seam, sets `g_lockEnd`): each console then saves
  its own player's progress on its own card, its own pad answering;
- or the frame the coordinator went in (the pause's Quit Race, whose
  screens the pausing pad drives on every console).

There `netstep_stop(now)`, `lockhash_stop`, `netrace_end` (the link
NETRACE_PATIENCE_MS again, through each console's save, unload and
frontend load, and the lobby next: `lobby.md`; or the event's next race:
`netrace.md`, "The next race") and a first `netstep_drain(now)`. The
loop drains on each pass while `netstep_ending` says so, and netrace
reads and sends nothing until it is through (`NetRaceNet.busy`), so the
next race's LOADED and GO come after the last race's stop and last
frames.

From the stop on, every message says how many frames its sender ran
(`stopAt`, 4 bytes after the checksum: the header is 19 bytes; none is
0xffffffff):

- The host serves its last records on (`netstep_drain`): a client still
  behind may need them. It ends once every client has said it stopped
  ("every client stopped, n ms after the host"), is gone, or
  `NETSTEP_DRAIN_MS` (10 s) have passed ("place p never said it
  stopped; given up").
- A client says its stop `NETSTEP_TELLS` (30) times, `NETSTEP_RESEND_MS`
  apart, a PADS message with no pads, and reads nothing more ("the stop
  said"): what comes next on the link is the lobby's.
- A client logs the host's stop as it hears it ("the host stopped after
  n frames"), the host each client's ("place p stopped after n frames").
- Should the consoles ever part, a client that stops first has left (the
  host goes on without it, "place p left, from frame n"), and a client
  still on past the host's last frame goes on alone ("past the host's
  stop, from frame n; racing alone") and says that as its stop.
- Neither reads past a message that is not the race's
  (`NetStepNet.peek`, `wl_link_peek`): it is the lobby's
  (`LOBBY_MSG_BACK`), left for it, and says its sender has gone on, as a
  stop would ("place p has gone on, its stop unheard"; a client's "the
  host has gone on, from frame n; racing alone").

The lobby gives the link its own timeout back once every other console
still on is back (`lobby.md`, "After the race").

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
place not racing; junk on the race's link. Since 37f, the end: both
or all stopping on a clean, lossy or slow link, either side slow or
held after its stop, a console gone or its link lost at the stop, the
link out at the stop, the lobby's back message coming before the race's
last, each side stopping alone or before the other, a client's stop
unheard. 39 scenarios, faults 0. `--mutate`: 148 mutations, 146
caught, 2 equivalent (named in the check).

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
both, at 28 FPS each.

Session 106 (37f-1), with `-Quit`: after the drive the host pauses,
moves to Quit Race and says OK. In two runs (seeds 441703d1 and
7c0a9c9c) both copies logged the pause on port 0 on the same frame and
the same item moves, stopped on the host's frame (2327, then 1924), and
the host logged every client stopped 1067 and 1050 ms after it. Both
logged the race over and came back to the lobby, and the host's next
Start took both to Select Car again, every logged frame's parts the
same. In the first run the host's pause was resumed at once and paused
again 13 s later by presses the script never made, on the host's port
alone; in the second, the host's log has D-pad left and right and A
presses through the drive that the script did not send, so someone was
most likely at the host's window. The pause took that A as Resume, as
retail does. Since then each frame's presses are logged ("lockstep:
frame N, port P's presses ..., screen ...") and so is each pause's
port and frame ("pause: port P, frame F"). The end after the results,
Quit or Next Race once the race is over, is 37f's and 37f-2's
(`netrace.md`).

Session 107 (37f-2), with `-Restart`: after the drive the host pauses,
moves down to Restart and says OK; every copy must show the race's
start again and race on for `-Drive` more seconds, never stopping its
lockstep, every logged frame's parts the host's. The first runs passed
(seed ec5fd1d5, 18 logged frames the same on both), but the restart
could hang in the world's update on a NULL WorldObject: GCC's strict
aliasing at -O3 had dropped the loop that destroys the race's
smokeables (`smokeable.md`, "Where the port differs"). With the local
list's head a whole CollisionBody and `-fno-strict-aliasing` in the
Makefile, both copies passed on seed 0ecec47b with no unmapped reads,
and the race's CPU stages averaged a little less than before (24.1 and
24.5 ms against 25.2 and 25.0).

`-NextRace` hosts Knockout, finishes the race on `-Finish`'s lockstep
frame on every copy (`WirelessTestFinish`, `netrace.md`), passes the
results with the host's A to Next Race and OK, says Yes to each copy's
save, and must see race 2 loaded, a second GO on the host's seed and
every copy racing again in step. The user stopped the Azahar runs on
2026-10-15 while its first run was going, and let them go on again the
same day.

Session 108 ran it through. The save's question opens on No, as
retail's DisplayYesNoMessage does (`memcard.c`), so the script moves
Left to Yes before its A. The run after that aborted both copies at the
second load: `bMalloc: 8995308 bytes for TRACKS\TRACKB11.LZC`, the heap
still holding the first race's view of the track, which the main loop
let go of only on a later pass; Next Race's unload goes on to the next
load in the same pass. The view now lets go in the Begin of unloading
(`track-flow.md`, "The race's view"), and the next run passed on seeds
0e7236cd and 3b4c87d1: both copies finished on frame 1800, stopped on
3023, saved, loaded race 2 with the heap back where the first load had
it (27.7 MB used and 62.5 MB linear free, against 27.9 and 62.9) and
raced it in step, all 28 logged frames' parts the host's.

The run that aborted had one checksum difference first: frame 1809,
nine frames after the test's finish, in the time and racers parts (an
AI racer's car, and with it retail's x + y), and every frame after it
differed too. The runs before and after it had none. Finding it is
still open (TASKS 37f-2).
