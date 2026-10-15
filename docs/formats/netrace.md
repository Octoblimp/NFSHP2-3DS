# A local wireless race's setup (TASKS 37c)

The port's own. The lobby (`docs/formats/lobby.md`) leaves every console
on its way to "Select Car" with the link up and a place each: the
host's 0, the clients' 1 on. `netrace.c` takes it from there to a race
loaded on every console and started on the same seed. Racing it
together, frame by frame, is 37d's (`docs/formats/netstep.md`).

- `netrace.c` has no `<3ds.h>`. The link comes in through `NetRaceNet`
  and what of the game it does not reach through globals through
  `NetRaceGame` (`netrace.h`); `main.c` fills both. Its state is a
  `NetRace`, so the check can run up to eight consoles in one process
  (`netrace_bind`).
- `main.c` hooks it in at three places: car select's change to "Select
  Track" (`netrace_car_chosen`), the start that car select, track select
  and the debug menu share (`hookCarSelStartRace`: `netrace_host_start`,
  or `netrace_car_chosen` for a client), and each frame after the link's
  pump (`netrace_frame`). The lobby's Start calls `netrace_begin`.
- Two hooks in retail's code, NULL unless a race is being set up:
  `gFredNetRideFn` in StartRace's AI racers (`fredrace.c`: the ride and
  the starting position, 0 by performance as retail's) and
  `gTrackFlowHoldRaceFn` at the end of the load (`trackflow.c` Part6).
- `portlang.c` has the host's new line, "Waiting for a car from:", in
  retail's six languages.

## The stages

| Stage | Where | Moves on |
|---|---|---|
| `NR_CARS` | Car select, and the host's track select | A client's car chosen: `NR_WAIT`. The host's start: `NR_WAIT`, or built at once. |
| `NR_WAIT` | "Wireless Race" | The host: every car in, the build. A client: the whole setup in. BACK: `NR_CARS`. |
| `NR_LOADING` | The load, retail's own | Its end: `NR_HOLD` (`netrace_hold`). |
| `NR_HOLD` | The loading screen, held | The host: every console racing has loaded. A client: GO. |
| `NR_RACING` | The race, in lockstep (`netstep.c`) | Lockstep's stop: `NR_ENDED` (`netrace_end`, 37f). |
| `NR_ENDED` | The race over: its save, its unload | The frontend's load: `NR_OFF`. The event's next race loaded: `NR_HOLD` (`netrace_hold`, 37f-2). |
| `NR_OFF` | No wireless race | `netrace_begin`. |

### The cars

Each console picks its own car and transmission on its own car select.
On a client, the
continue that would go on to "Select Track" sends the car instead
(`NETRACE_MSG_CAR`: the place, the `RideInfo` of player 0's ride for
Fred's game type, and player 0's `cPlayerSettings`), and goes on to
"Wireless Race". BACK there sends `NETRACE_MSG_UNCAR` and goes back to
car select, where a new car can be picked and sent.

The host goes on to track select as usual. Its start there (the press
that would call StartRace) builds the race at once if every client still
on has a car in. Otherwise it goes on to "Wireless Race" too, and builds
the frame the last car comes in. BACK there goes back to track select.

### "Wireless Race"

A screen with no Flailer hash of its own, drawn as the lobby's: one
popup on the memory card's popup screen, "Local Wireless" over it, no
buttons, BACK the way out. A on it only puts it back, with no sound.
BACK plays the cancel sound.

- The host's line: "Waiting for a car from:", then the name of each
  client still on whose car is not in, in place order. It is put up again
  only when that changes.
- A client's line: "Waiting for $NAME to start the race." with the
  host's name, the lobby's wait.

Leaving the screen any way takes the popup with it (SCREEN_UNACTIVATE).
The load's flow leaves it the same frame as the build or the setup.

### The build

The host runs retail's StartRace (`fred_start_race`) with:

- its own car and settings as player 0's;
- the first client's car and settings as player 1's, in place of the
  frontend's second player, which is put back after;
- every other client's car in an AI racer's place, in place order
  (`gFredNetRideFn`), at instance 0 and not vertex-damageable, as
  retail's AI racers are;
- the host's CPU racers from the lobby (`LobbyRace.cpu`, TASKS 37c-2,
  `docs/formats/lobby.md`) after them, StartRace's own, drawn as
  retail's.

NumAICars is the CPU racers and the clients in AI racers' places.
`netrace_begin` sets it to the CPU racers and the consoles less two, so
track select already counts them (a Lap Knockout's laps are one fewer
than the cars). The build sets it again to the clients still on, and a
Lap Knockout's laps with it.

The grid: the CPU racers take the front, places 1 to n, by performance,
as retail's AI racers do (a starting position of 0). The host starts
at n + 1 and the first client at n + 2 (`PlayerStartPosition`), and the
client in AI racer k's place at n + 3 + k, the hook's starting position.
With no CPU racers that is the consoles in place order.

Each place's driver (its UniqueDriverNumber) is 0 for the host, 1 for
the first client, and 100 + k for the client in AI racer k's place; the
CPU racers are the AI racers after them.

What StartRace made goes to every client racing as `NETRACE_MSG_SETUP`,
in pieces of `WL_MSG_MAX - 4` bytes, each with its offset and the total
(two bytes each, little-endian):

| Part | Bytes | What |
|---|---|---|
| Header | `sizeof(SetupHeader)` | "NR", version 1, the consoles; Fred's GameType and NumPlayerCars; `bDefaultSeed` as built; the driver of each place; the sizes of the three records; the drivers in the table; whether the event's state is in the event (`aOldState`, a knockout's); each racing place's `cPlayerSettings` |
| Race parameters | `sizeof(RaceParameters)` | `TheRaceParameters` |
| Drivers | n × `sizeof(DriverInfo)` | `DriverInfoTable`'s first n |
| Event | `sizeof(RaceEvent)` | `TheRaceEvent` |

Every console runs the same build, so the records go as they are. A
client checks the magic, the version, the console count, each record's
size and the total, and goes back to the lobby if any is off.

### Taking it

A client puts the host's race in place of its own: the race parameters
(but for its own display settings, with the host's jump and zone
cameras, which the race runs with), the driver table (each driver's
`pCharacterInfo` looked up again on this console), the event (its own
tree pointer, and its own state unless the event's is in it), Fred's
game type and player count, `bRaceWasAborted` cleared, `bDefaultSeed`,
and each place's driver and settings. Then it starts its own load, as
StartRace would.

### The hold and GO

At the end of its load each console holds before going racing
(`gTrackFlowHoldRaceFn`), the loading screen still up. A client says so
with `NETRACE_MSG_LOADED`. Once every console racing and still on has
loaded, the host sends `NETRACE_MSG_GO` with `bDefaultSeed` as it is
then (4 bytes, little-endian) and goes racing on it. Each client goes
racing on the seed it was sent. The loads draw different numbers of
randoms on each console, so the seed at GO is the one that counts.

From the lobby's Start on, the link waits up to `NETRACE_PATIENCE_MS`
(30 s) for a quiet console (`wireless_set_patience`). A load stops a
console's loop for seconds, and so does the race's first frame, whose
drawing prepares the track and the cars (8.9 s on Azahar). The first
run on Azahar put the link's own 3 s timeout back at GO, and each
console timed the other out during that frame. The patience now stays
through GO. The race (37d, `docs/formats/netstep.md`) gives the link
its own timeout back once every console's frames come in, and going back to the lobby does too.

## The messages

All reliable, after the lobby's (`LOBBY_MSG_START` 0x10):

| Type | From | Bytes |
|---|---|---|
| 0x11 `NETRACE_MSG_CAR` | A client | place (1), `RideInfo` (8), `cPlayerSettings` (48) |
| 0x12 `NETRACE_MSG_UNCAR` | A client | place (1) |
| 0x13 `NETRACE_MSG_SETUP` | The host | offset (2), total (2), the piece |
| 0x14 `NETRACE_MSG_LOADED` | A client | place (1) |
| 0x15 `NETRACE_MSG_GO` | The host | seed (4) |

The host takes a car or its taking back only up to the build, and LOADED
only after it. A client takes the setup only up to its load, and GO only
while it holds, which it says before the host can send it. Nothing past
GO is read: what comes next is the race's.

## A console lost

- Before the build, the host races without a client that went: its name
  leaves the host's line, and the build waits only for those still on.
  With none left, the host goes back to the lobby, which shows "The link
  to $NAME was lost." with the last one gone.
- A client that loses the host before the setup goes back to the lobby
  with that line.
- Once built, nobody gone is waited for: the host sends GO when the rest
  have loaded. A client that loses the host while it holds starts the
  race alone, on its own seed.
- Only the lobby takes the link down, with its screen up. If the link is
  down anyway, netrace stops (`NR_OFF`).

What a race does with a console gone is 37g's.

## The race's end (TASKS 37f)

Where the race leaves lockstep (`netstep.md`, "The end": after the end's
save is asked for, or with the race gone by the pause's Quit), `main.c`
calls `netrace_end`. From `NR_RACING` only, it:

- goes to `NR_ENDED`: the race is over, and the frontend or the
  event's next race comes next (37f-2);
- forgets which consoles had loaded, for the next race's hold;
- gives the link `NETRACE_PATIENCE_MS` again: from here each console
  saves on its own card, unloads, and loads the frontend or the next
  race, in its own time;
- says "netrace: the race is over; the lobby or the next race next";
- and calls `lobby_back_next`, so the frontend comes back to the lobby
  with the link up (`lobby.md`, "After the race").

Anywhere else it does nothing.

At `NR_ENDED` netrace reads and sends nothing. Once the flow is loading
the frontend, or is in it already (a load can end between two of
netrace's frames), it goes to `NR_OFF` ("netrace: off, the frontend
next"): no wireless race from here, so `netrace_active` answers 0, car
select's and track select's hooks are retail's, and the link's messages
are the lobby's.

### The next race (TASKS 37f-2)

Next Race and Restart Event on the End Game Menu go through the end's
save, where lockstep stops, and load the event's next race: a
Knockout's (GameType 4, the race event's mode). Every console runs the
same results on the same pads up to the stop, so each loads the same
next race. Two of the event's calls would make the consoles' races
differ, and `main.c` keeps them the same:

- `raceevent_setup_next_race` puts Fred's player 1 settings, each
  console's own from its car select, into the race's;
  `fedSetupNextRace` keeps the settings as raced.
- `raceevent_restart` (Restart Event) puts the event's first grid back
  in retail's order for one player; `netRaceGrid` puts netrace's back:
  the CPU racers first, the two players behind them, then the consoles
  in AI racers' places, and `fred_calculate_starting_positions`.

A Knockout puts the last racer out between races, and racecoord makes
no car for a player put out. That console then shows the other player
(`netShownPlayer`, `PlayerNetLocal`) and runs on in lockstep, its pad
driving nothing.

The next race's load ends in the hold as the first did: `netrace_hold`
takes `NR_ENDED` as it takes `NR_LOADING`, counts the race ("netrace:
race N loaded") and holds. The host's GO waits for every console still
on, on the seed as it is then.

The last race's end may still be on the link then: the host serving its
last frames to a client whose stop it has not heard, or a client saying
its stop (`netstep_ending`, which `main.c` gives netrace as
`NetRaceNet.busy`). Until it is through, netrace reads and sends
nothing, so a client's LOADED comes after its stop and the host's GO
after its last frames; else the next race's lockstep would take the
last race's stop for its own. A client's LOADED goes on its first frame
held and not busy. The last race's leftovers (the host's last frames, a
client's further stops) are read and dropped while it holds.

Restart Race, from the pause or the End Game Menu, resets the race in
place without the save: the coordinator stays, and so does lockstep,
with nothing of netrace's. On two Azahars (Session 107) it did, once
the race's reset stopped leaking smokeables (`smokeable.md`, "Where the
port differs"). Next Race passed on two Azahars in Session 108
(`netstep.md`), once the race's view of the track let go in the Begin
of unloading (`track-flow.md`, "The race's view"); Restart Event is
checked by the harness only.

For Azahar, where the gas alone never finishes a race,
`WirelessTestFinish n` in `nfshp2_config.txt` finishes a wireless race
on lockstep frame n, or the first racing frame after it, on every
console (`lockTestFinish`, `racecoordinator_the_race_has_finished`).
It is off by default.

## The check

`tools/netrace_check.py` builds `tools/src/netrace_test.c` with
`netrace.c`, `portlang.c` and the real flow and popups (`gameflow.c`,
`bpopup.c`, `memcard.c`, `banim.c`); the lobby's two calls are faked,
the notice recorded. It runs up to eight
consoles in one process, each with its own flow, its own `NetRace` and
its own copy of the globals netrace reaches, swapped in for its turn.
Between them is a fake link: reliable, in order, each message a few
frames on the way. The game is a fake too: a StartRace that builds the
two players and the AI racers (asking `gFredNetRideFn` first, and else
drawing a ride from `bDefaultSeed`), and a load of the scenario's
frames, the loop stalled for most of them, that draws a different count
of randoms on each console.

36 scenarios: two consoles; the host waiting on two cars; a client's and
the host's BACK; eight consoles; a client gone before its car, with its
car in, of two waited for, while waiting, at car select, during the
load; every client gone at the start, at car select, while the host
waits; the host gone while a client waits, at car select, during the
load; a knockout (the event's state in the event); a setup from another
build; a client leaving; French; the host's CPU racers with two and
three consoles, with one gone before its car, and in a Lap Knockout;
and no wireless race at all. Three are the race's end (37f,
`netrace_end` at the scenario's event "end"): two consoles' race over,
the end asked of the client while it still loads and of the host a
second time changing nothing; a client that lost the host and raced
alone; and the end of a race with no wireless race on.

Eight are 37f-2's: the frontend after the end, loading on one console
and loaded on the other, the host's lobby message to the client left
unread; the event's next race ("next") on two consoles; with the host's
last frames served long after the end (a client's stop unheard); with a
client still saying its stop when its next race has loaded; on three
consoles, the one in an AI racer's place loading last; with a client
gone, and with the host gone, while it loads (the client racing alone);
and a next race, its end, and the frontend.

After each end a console's fake netstep is busy for the scenario's
frames: the host sends each racing client its last frames and reads the
clients' messages of the race; a client sends its stop. Each ended
console must be `NR_ENDED`, the lobby told once for each end, and the
link's patience NETRACE_PATIENCE_MS; anywhere else the end changes
nothing. Nothing of netrace's may be read or sent while its console is
busy, and a client sends one LOADED a race.

Every frame it checks the popup (one at most, only on "Wireless Race",
the lobby's look), each console's line, the sounds, the link's patience,
the messages (none too long, none to a peer not there), and that GO
comes only once every console racing has held, once to each. At the end
it checks each console's screen, stage and log lines, and that each
racing client's race is the host's at the last GO: the parameters, the driver
table, the event, Fred's game type and players, the drivers, and the
seed. The host's table must have the first client as the second player
and the rest in AI racers' places, and the frontend's second player put
back; exactly as many AI racers as CPU racers and clients in them; each
driver's starting position (the CPU racers 0, the players behind them in
place order); and the laps (a Lap Knockout's one fewer than the cars,
any other race's as track select left them).

The last line is `total faults N`, and the check passes at 0.

`--mutate` makes 194 mutations of `netrace.c`. 182 are caught and 12 are
equivalent, each named in the script with its reason.

## On Azahar

`tools/run_azahar_lobby.ps1 -Race` goes on from the lobby's run, the
host's CPU racers set to `-Cpu` (2 unless said). Each copy picks a car
of its own: the host the profile's, with Automatic; copy i the first
unlocked car (the unlocked cars come first, and left stops there), then
(i - 1) mod (u - 1) + 1 to the right of the u unlocked, with Manual
where i is odd; each the first handling. Each client
sends its car and waits on "Wireless Race". The host picks the first
track and starts. It passes when every copy has logged GO on the host's
seed and reached `flow state RACING`, with its sound up and no unmapped
reads in Azahar's log; the race built with as many drivers as consoles
and CPU racers; and each client's car and transmission ("car sent, type
t skin s, transmission x") as it chose them and as the host got them.
Each copy's card gets the DSP firmware (`sdmc:/3ds/dspfirm.cdc`) from
Azahar's own card.

Two copies passed in Session 98: track 11 with four drivers, GO 4 s
after the build, both racing on seed 248fe492 with the same Starting
Grid.

Two copies passed in Session 99 with `-Cpu 2`: the client sent its
Vauxhall VX220 (type 35, skin 7) on Manual and the host got it as
sent; the host started with its Opel Speedster on Automatic. Track 11
built with four drivers, GO 3 s after, both racing on seed ced6d9c3.
Each Starting Grid has the two CPU racers first (Mercedes CL55 AMG, Ford
TS50), then the host and the client.
