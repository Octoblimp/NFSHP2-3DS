# The world's checksum in parts (TASKS 37e)

`3DS Files/source/lockhash.c`, the port's own. A wireless race runs in
lockstep (`netstep.md`): every console runs every frame on the same
record, and each says its checksum of the world after it. A checksum that
differs tells that the race went two ways, not where. Here the checksum
is the fold of seven parts, each a hash of its own state after the frame,
and a console that is told a frame differs logs what it needs to find the
first part that went, and what drew from the seed before it.

## The parts

| part | what |
|---|---|
| time | WorldTimer, the World's pause and time scale (`fTimeToRemainPaused` to `fTimeScaleTimer`, `TimeScaleCallbackParam`), and retail's own debug checksum (each car's x + y; it also fills `CarPositionTable`, as for 37d) |
| seeds | `bDefaultSeed` and the World's `WorldRandomSeed` |
| players | the cars of slots 0 to `AICarPos` |
| racers | the cars of `AICarPos` to `CopCarPos` |
| cops | the cars of `CopCarPos` to `TrafficCarPos`, then the helicopter: `TimeUntilThink`, `Plan`, `MoveMode`, `TargetDistance`, and `BombRunType` to `New960` (salvos, position, matrix, speed, roll, pitch) |
| traffic | the cars of `TrafficCarPos` to `TotalNumCars` |
| race | the coordinator's state, executing message, countdown and state before pause; the Race's stage to `DetectedOneCarRemaining`, its laps and forced finish; each RacingCar up to `NumRacingCars` from `CurrentBoundaryRegion` to `AverageSpeed` |

A car is its slot, its control and movement modes, and its CarState from
`GeometryPosition` to `DistanceMoved`, every float as its bits. None of
these hold a pointer, and none of the padding, tails or pointers around
them is read: a console's heap is its own. A range is clamped to the cars
there are; a NULL slot still counts.

Each part is FNV-1a over 32-bit words with a final `h ^ (h >> 15)`. The
fold is `s = s * 33 + part` over the seven, then `(s >> 16) + s` to 16
bits, the checksum netstep sends. Every bit of every part moves it.

## The draws

`bmath.h`'s `bDefaultSeedWatch`, the port's: while set, every
`bRandomI`, `bRandomF` and `bSetRandomSeed` on `bDefaultSeed` tells it the
address the draw returns to (`__builtin_return_address(0)`). From GO,
`lockhash_start` sets it, and each draw is kept in a ring of 1024 with the
frame it was made in: the draws between the end of frame n - 1 and the end
of frame n are frame n's.

## The log

- `lockhash: frame N time ... race ...`: every 150 frames (netstep's
  NETSTEP_LOG_EVERY), the seven parts in hex, beside netstep's "frame N
  hash h".
- At the first frame netstep finds differing from another console's
  (`netstep_on_differ`), once a race: `lockhash: frame N differs; the 16
  frames up to it`, then for each of those frames that this console has
  run, `lockhash: parts N ...` and `lockhash: draws N: count`, then
  `lockhash: at N: a1 a2 ...`, eight addresses to a line, then
  `lockhash: cars N timer t loop l: w0 ... w13`: WorldTimer and
  WorldLoopCounter as the frame left them, and a word for each of the
  World's 14 slots. Last, if the frame itself has run, `lockhash: fields
  N s: p0 ... p9` for each slot with a car: the car in ten pieces.

## The cars in pieces

Not in the fold, only for the window (Session 108): a frame that differs
in a cars part says which part, not which car or what in it. Each frame
also keeps, for each slot, the car in ten pieces, each FNV-1a as the
parts are:

| piece | what |
|---|---|
| modes | `TheControlMode`, `TheMovementMode` |
| place | `GeometryPosition`, `Position` |
| motion | `Velocity`, `Acceleration` |
| body | `BodyMatrix` |
| spin | `AngularVelocity`, `AngularAcceleration` |
| wheelmats | `WheelMatrix`, `BrakeMatrix` |
| wheels | `WheelAngularVelocity` to `WheelTractionUsage` |
| drive | `Angle` to `BurnOutAllow`: steering, odometer, gear, throttle, RPM |
| rel | `RelCoordMatrix` to `DistanceMoved` |
| driver | the `CarDriver`'s `Steering` to `NitroFlag`, and its `DriveTarget`'s `NumPoints` and each point's x, y, z and speed up to it |

The eight CarState pieces together are the span the parts read, cut at
the fields named. A NULL slot, or one past `TotalNumCars`, is all 0, and
the cars line folds each slot's ten into one word. `run_azahar_lobby.ps1`
compares them with the host's at the first frame that differs and names
each slot that differs and its pieces, so "slot 2: differs in drive"
says an AI racer's steering or throttle went first, which only its
controller sets, and "place" with nothing else a move from outside the
physics. It then finds the first frame of the window where the slot's
word differs.

The driver piece came in Session 109. A Next Race run split after the
finish, with only slot 0, the host's car, differing, in every CarState
piece at once and its modes the same: after the finish the car is the
AI's (`race_finish_car`), and what the AI chose went into the CarState
the frame it drove, so a CarState piece only says when. The driver is in
no part: a part with it would only say the same frame sooner, and a
driver's target is made on the stack and copied in, its fourth lanes and
the points past `NumPoints` whatever the stack held. In the window,
though, the slot's word folds the driver, so the frame the AI's choice
first went is the first where the word differs, and the fields line
says whether it was the driver.

Map an address with `arm-none-eabi-addr2line -f -e "3DS Files/build/..."`
on the .elf of that build.

## The view seed

`bmath.h`'s `bViewSeed`, the port's, is the seed what is only heard or
shown draws on. It is `&bDefaultSeed`, so every draw is retail's, except
from GO to the race's end in a wireless race, where `lockhash_start`
points it at a seed of its own (`bDefaultSeed ^ 0x5bd1e995` at GO) and
`lockhash_stop` puts it back.

Each console runs every player's logic as retail ran its two players,
cameras and NIS included, so most draws from what is shown come out the
same on each. Cop speech does not: `copmanager_time_based_speech` waits
for the console's own audio to be quiet (`gCopSpeechPlaybackStateFn`), and
then draws the filler line and the next gap. A console whose sound plays
a line longer, or not at all (no DSP firmware: the NULL driver, 22d),
would draw those at another frame and move `bDefaultSeed` for the world.
On the view seed:

- speech: the filler gap (`copmgr.c`), the filler line and its swap
  (`fillerspeech.c`), race speech's coin (`racespeech.c`), pursuit
  speech's `random_below` (`pursuitspeech.c`), the roadblock and spike
  strip places and the shuffle (`speechmgr.c`);
- cameras: the camera shake (`cameracoord.c`) and the track car camera's
  focal start (`trackcarcam.c`), reached only from the attract demo and
  the zone cameras, which retail turns off with two players;
- models: a flagged solid's start time (`emodel.c`) and a car's render
  timebase (`carrenderinfo.c`).

Speech writes back into a pursuit (`PursuitSubState`, the speakers, the
chased car) only where the simulation calls it, at the same frame on each
console, and draws nothing there that the simulation reads. Left on
`bDefaultSeed`: everything the world reads -- the AI, the pursuits, the
physics, the race's setup -- and the bust NIS's choice (`playernis.c`),
whose length ends the pullover. The attract demo's camera (`democam.c`)
never runs in a race.

## The check

`python tools/lockhash_check.py` builds `tools/src/lockhash_test.c` with
`lockhash.c` and `bmath.c`. It makes a World of its own (two players, two
AI racers, two cops, two traffic cars, a helicopter, a Race and a
coordinator, every byte filled) and checks that each part moves with each
field it reads and with no other, that every bit of every part moves the
fold, the frame lines and the window (once a race, frames not run left
out, nothing before start or after stop), each draw's address, the view
seed from start to stop, and that a watched draw gives what an unwatched
one does. Since Session 108 it also checks the cars in pieces: a change
to each field moves its own slot's own piece and no other, a pointer,
the tail or the hole none, a NULL slot or one past `TotalNumCars` is 0,
the driver's inputs, its points and speeds up to `NumPoints`, and
`NumPoints` itself move the driver piece, as a car with no driver does;
the points past it, the fourth lanes and the target's route move none;
the clocks are the frame's, and the window's cars lines (one a frame, a
slot's word moving with its car alone) and the frame's fields lines,
never a frame not run whose ring slot holds an older one. Faults 0.
`--mutate`: 105 mutations, 101 caught, 4 equivalent
(named in the check); Session 109's driver piece added 7, all caught.

Moving the draws to `bViewSeed` changed no harness's model: with the
pointer on `bDefaultSeed` each draw is the one it was, and copmanager,
cop, pursuit, fillerspeech, racespeech, pursuitspeech, speechmgr,
cameracoord, democam, trackcarcam, carrenderinfo and loadertable each
gave 0 differ.

## On Azahar

`tools/run_azahar_lobby.ps1 -Race` compares every copy's parts with the
host's, frame by frame, and fails a copy at the first that differs,
printing both copies' parts and draws there, then the clocks if they
differ and each car slot that differs with its pieces. `-CopsOn` walks through Hot
Pursuit, so the race has cops; `-Steer` steers each copy left and right
by turns, its own period each.

Session 102's runs, track 11, 2 laps, 4 cops, two consoles and two CPU
racers, gas and steering for 240 s:

- `-CopsOn -Steer`: GO on seed 1d32acf8; the client's parts the same as
  the host's on all 39 frames logged (0..5700). A CPU racer was busted.
- `-CopsOn -Steer -SilentClients`: the client "ndsp unavailable", its
  speech bank not loaded; GO on seed 825af1a5, 39 frames the same.
- Two controls with `lockhash_start` leaving `bViewSeed` on
  `bDefaultSeed`: the silent client again, 34 frames the same with a
  chase on most of the race; `-Cpu 0`, 38 frames the same and no chase.

The controls kept in step because filler speech needs a chase of a
player (`copmanager_find_player_pursuit`), and the scripted drives, gas
and steering into the trees, never drew one. So the speech drift is
shown by the code path and the harnesses, not yet on Azahar; a run in
which a player is chased (a playtest, or a drive that keeps to the road)
would show it.
