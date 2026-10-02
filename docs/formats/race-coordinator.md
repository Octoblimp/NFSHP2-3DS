# `RaceCoordinator` -- the race's lifetime and its message queue

The `RaceCoordinator` owns a race from the moment the track is loaded to
the moment it is unloaded. Its constructor builds everything a race needs
through `InitForRace`, and its destructor takes it all down again through
`CleanupAfterRace`. In between, the race runs as a state machine. There are
ten states, and each one is a callback that answers messages. The messages
go through a queue, and `ChangeState` is three of them in a row.

This step (8e) ports the lifetime and the queue. The ten callbacks are the
next slices; until then they are a table of seams.

The port is `3DS Files/source/racecoord.c`/`racecoord.h`. Everything there
is retail's. `race.c` adds `TheRaceParameters.NumAICars`.
`tools/racecoord_check.py` runs the retail image itself in RetailEmu as
the oracle: 175 scenarios, 7038 ops, 26129 transcript lines, 0 differ.
Of its 136 mutations, 135 are caught: eleven by crashing the harness and
one by hanging it. The other one is equivalent: the destructor emptying
the list, which no scenario leaves a message on (see the destructor,
below). Before the run it compiles `racecoord.h` with devkitARM and
asserts `RaceCoordinator`'s and `RCQueuedMessage`'s layout.

## Where things are

| retail | what |
|--------|------|
| `0x00149520` | `ChangeState(RCState)`, 84 bytes |
| `0x00149578` | `ExecuteQueuedMessages()`, 216 bytes |
| `0x00149650` | `SendMessage(RCMessage, int)`, 132 bytes |
| `0x001496d8` | `PostMessage(RCMessage, int)`, 96 bytes |
| `0x00149738` | the constructor, 284 bytes |
| `0x00149858` | the destructor, 148 bytes |
| `0x00149988` | `InitForRace()`, 512 bytes |
| `0x00149b88` | `CleanupAfterRace()`, 304 bytes |
| `0x00149d78` | `CleanupPlayers()`, 92 bytes |
| `0x0014a5f0` | `CleanupCars()`, 116 bytes |
| `0x001cd240` | `SetAIDriverModesFromPlayers()`, 456 bytes |
| `0x001edb40` | `RaceParameters::GetDriverInfoByDriverNumber(int)`, 132 bytes |
| `0x002f0bf0` | the state table: ten pointers to members, 8 bytes each |
| `0x002af838` | `"GLOBAL\PRERACEANIM.LZC"` |
| gp-22216 | `pRaceCoordinator`, `0x00330228` |
| gp-22192 | `RCQueuedMessageSlotPool`, `0x00330240` |
| gp-21064 | `ThePauseMenu`, `0x003306a8` |
| gp-22440 | `pReplayManager`, `0x00330148` |
| gp-22272 | `pCurrentRace` |
| gp-22120 | `pCurrentWorld` |
| gp-23220 | the flow's `SkipFE` |
| gp-20936, -20932 | `Player::pPlayersByNumber[2]` |
| gp-20928 | `Player::pPlayersByIndex[2]` |
| gp-20920 | `Player::NumPlayers` |

The `TheRaceParameters` words read here:

| offset | what |
|--------|------|
| +0 | `TrackNumber` |
| +24 | `AIDemoMode` |
| +28 | `ReplayDemoMode` |
| +48 | `NumPlayerCars` |
| +52 | `NumAICars`, 7 from `InitWithDefaults` (`0x0031a8cc`) |
| +628 | `BeACop` |
| +772 | the `DriverInfo` array |
| +776 | `NumDriverInfo` |

## `RaceCoordinator`, 144 bytes

`retail_layout` finds every field of the demo's type#1044 at the demo's
offset. Retail adds one word, at 140, in the demo's tail padding. The
constructor zeroes it, and only `RCStatePostRaceCallback` (`0x0014bdd8`)
touches it otherwise. The port calls it `PostRaceWord140` until that
callback is ported.

| offset | field |
|--------|-------|
| 0 | `CurrentRCState` |
| 4 | `RCQueuedMessageList`, a `bTList<RCQueuedMessage>`: next 4, prev 8 |
| 12 | `RCExecutingMessage` |
| 16 | `DisplayingCountdownNumber` |
| 20 | `PausedJoystickPort` |
| 24 | `BeforePauseRCState` |
| 28 | `pDemoCameraCoordinator` |
| 32 | `pFlyByCameraCoordinator` |
| 36 | `pPreRaceCameraCoordinator` |
| 40 | `pEndGameScreens` |
| 44 | `pReplayScreen` |
| 48 | `mNumRewinds` |
| 52 | `mpCameraMover` |
| 56 | `mpCD` |
| 60 | `mIncidentPoint` |
| 64, 80, 96 | `mIncidentCoord`, `mFinalPosition`, `mStartPosition` (`bVector3`) |
| 112 | `mpEyeVerts` |
| 116 | `mpBankVerts` |
| 120 | `mpFOVtable` |
| 124, 128 | `mpHighlightCar`, `mpHighlightCar2` |
| 132 | `mViewID` |
| 136 | `mpRoute` |
| 140 | retail's new word |

`RCQueuedMessage` is 16 bytes: a `bTNode` (next 0, prev 4), the
`RCMessage` at 8 and its parameter at 12.

`RCMessage`, from the `.mdebug` enum: 0 none, 1 `ACTIVATE`, 2
`UNACTIVATE`, 3 `TICK`, 4 `SKIP`, 5 `REQUEST_PAUSE`, 6 `REQUEST_UNPAUSE`,
7 `REQUEST_AUTO_REPLAY`, 8 `RESTART_RACE`, 9 `NEXT_RACE`, 10 `QUIT_RACE`,
11 `SKIP_REPLAY`, 12 `START_REPLAY`, 13 `TAKE_AUTOSNAPSHOT`, 14
`MOVE_REPLAY`.

## The queue

`SendMessage` and `PostMessage` both take a slot from the pool, fill it in
and link it onto the end of the list. `PostMessage` stops there.
`SendMessage` then runs the queue, unless a message is running already.
A callback that sends therefore queues its message behind the one it is
answering. It does not nest.

`ExecuteQueuedMessages` takes the head off the list and sets
`RCExecutingMessage`. If the message is `RC_ACTIVATE`, its parameter
becomes `CurrentRCState` before the call. It then calls the callback for
`CurrentRCState` with the message and the parameter. After the call, an
`RC_UNACTIVATE` leaves the state at 0 (`RCSTATE_NONE`). It clears
`RCExecutingMessage`, frees the slot back into the pool, and reads the head
again. That last read is what runs the messages a callback posted in the
same pass.

The state table holds pointers to members, `{short this-delta, short
index, function}`. All ten have delta 0 and index -1 (not virtual).
Retail indexes the table unchecked. The port guards the index, and a
state outside 0..9 runs nothing.

`ChangeState(s)` is `SendMessage(RC_UNACTIVATE, current)`,
`SendMessage(RC_ACTIVATE, s)`, `SendMessage(RC_TICK, 0)`.

A callback can run the queue itself. That nested pass clears
`RCExecutingMessage` after each message it runs, so for the rest of the
outer callback the flag is clear, and a send from there runs the queue at
once. Both sides do this, and the scenarios exercise it.

## The constructor

1. `RCExecutingMessage`, `CurrentRCState`, `BeforePauseRCState` and
   `DisplayingCountdownNumber` are zeroed, and the list is made empty.
2. If `bCountFreeMemory(16)` is 0x7cfff or less (`slt` on the signed
   word), `FindResourceFile("GLOBAL\PRERACEANIM.LZC")`. If that is
   loaded, it is unloaded. `InitForRace` then finds no prerace animation
   and starts at the countdown, not the flyby.
3. `bNewSlotPool(16, 8, "RCQueuedMessageSlotPool", 16)`.
4. +28 through +44 (the three camera coordinators, the end-game screens
   and the replay screen) are zeroed.
5. `ThePauseMenu = new PauseMenu`, `bMalloc(56, "PauseMenu", 0, 16)`.
6. `PausedJoystickPort = -1`.
7. `RaceParameters::Print`, which is empty in retail.
8. `InitForRace`.
9. `bCountFreeMemory(16)` and `bLargestMalloc(16)`, both unused.
10. +52, +56, +120, +136, +116, +112 and +140 are zeroed. Every state
    callback `InitForRace`'s `ChangeState` runs still sees the
    allocator's fill there.

`new RaceCoordinator` is `bMalloc(144, "RaceCoordinator", 0, 16)`.

## The destructor

If the state is not 0, `ChangeState(RCSTATE_NONE)`. Then
`CleanupAfterRace`, `CleanUpAutoReplay`, the pause menu's destructor
(flags 3) if there is one, and `ThePauseMenu = NULL`. Then
`bDeleteSlotPool`. `pRaceCoordinator` is left alone; trackflow clears it.

Retail then runs `~bTList<RCQueuedMessage>` with flags 2. That takes each
message still on the list off and deletes it through `RCQueuedMessage`'s
`operator delete` (`0x0014cd10`), which is `bFree` into the pool the
destructor has just deleted. The port does not copy this use-after-free.
It only empties the list. The scenarios never leave a message there at
the destructor, because the two sides cannot agree on what freeing into
a deleted pool does.

`flags & 1` then frees the coordinator through `__builtin_delete`.

## `InitForRace`

1. `Player1`: if `GetDriverInfoByDriverNumber(0)` exists with
   `EliminatedRank <= 0`, or `AIDemoMode` is set,
   `new Player(port 0, number 0)` on `bMalloc(2752, "Player1", 0, 16)`.
2. `Player2`: if driver 1 exists with `EliminatedRank <= 0`,
   `new Player(port 1, number 1)` on `bMalloc(2752, "Player2", 0, 16)`.
   The AI demo makes no second player.
3. `GetTrackInfo(TrackNumber)`, whose answer is dropped.
4. `pReplayManager = new ReplayManager` (20664 bytes),
   `pCurrentRace = new Race` (1716), and `new World` (5936). World's
   constructor sets `pCurrentWorld` itself.
5. `InitCars` and `InitPlayers` ([raceinit.md](raceinit.md)).
6. The first state and the race's stage, the first that applies:

   | when | state | stage |
   |------|-------|-------|
   | `AIDemoMode` (and `DisableRenderEggs`) | 8 `AI_DEMO_MODE` | `RACING` |
   | `ReplayDemoMode` | 9 `REPLAY_DEMO_MODE` | `RACING` |
   | `SkipFE` | 3 `RACE_IN_PROGRESS` | `RACING` |
   | `BeACop` | 1 `CAMERA_FLYBY` | `FLYBY` |
   | `PRERACEANIM.LZC` is loaded | 1 `CAMERA_FLYBY` | `FLYBY` |
   | otherwise | 3 `RACE_IN_PROGRESS` | `COUNTDOWN` |

   `BeACop` is tested first, so with it set the animation is not looked
   up.
7. `Race::Init(stage)`, `SetupGhostCars`, `SetAIDriverModesFromPlayers`,
   `collision_sound::Reset`, and the speech manager's `FlushQueue`.
8. `pRaceCoordinator = this`, then `ChangeState(state)` as a tail call.
   The callbacks of the first change already see `pRaceCoordinator` set.

## `CleanupAfterRace`

1. The prerace camera coordinator, then the flyby one: each one deleted
   through its virtual destructor, with flags 3, and its pointer cleared.
   The vtable is at +24, and the slot's delta and function are at +8 and
   +12.
2. `World::FlushCollisions` (empty in retail), `CleanupPlayers`,
   `CleanupCars`.
3. `AcidEffectSystem::KillAllActiveEffects` on `WorldEffects`
   (`0x002ef640`).
4. The Race, then the World, each destroyed with flags 3 if present, and
   both pointers cleared.
5. `jukebox::Stop`, `sound3d_oneshot::Reset`.
6. The ReplayManager destroyed (flags 3) and cleared, then the end-game
   screens destroyed and cleared.
7. The players, last to first. Each one's destructor takes it out of
   `pPlayersByIndex`. `NumPlayers` is re-read only after a player was
   destroyed, so a NULL entry would spin forever. Nothing makes one.

`CleanupPlayers` calls `Player::CleanupAfterRace` on each player in
`pPlayersByIndex` order, re-reading `NumPlayers` each pass.

`CleanupCars` unlinks each car on the World's `CarList` and destroys it
with flags 3, re-reading `pCurrentWorld` every pass. Then it destroys the
helicopter, if there is one, and clears the pointer. It reads the World
unchecked. Retail never calls it without one: the destructor runs once
with the race up, and `RCStateNoneCallback`'s restart is `CleanupAfterRace`
followed straight away by `InitForRace`.

## `SetAIDriverModesFromPlayers`

Nothing happens without both a World and a Race.

With two player cars, it reads both players' positions:
`Race::GetRacingCar(player->MyCar)->RacePosition`, a signed byte at +10.
The first player's `DrivingStyle` (signed byte +34) goes to the AI cars at
the front and the second player's to the rest. If the second player is
strictly ahead (a lower position), the two styles swap. The middle of the
field is `NumAICars / 2`, rounded towards zero (`srl 31; addu; sra`). It
moves one back for each player whose position is at or ahead of it. Each
AI car in `CarTable[AICarPos .. CopCarPos)` behind the middle gets the
second style, and the rest get the first. The World is re-read every
pass.

Otherwise every AI car gets `pPlayersByIndex[0]`'s style.

The style lands in the car's `DriverMode` (retail Car+988, the port's
`State.DriverMode`).

## `GetDriverInfoByDriverNumber`

This walks `0 .. NumDriverInfo` through `GetDriverInfo` and returns the
first record whose `UniqueDriverNumber` (signed byte 1) matches. It
returns NULL if none does. The count is re-read each pass.

## Seams

The callbacks and most of what `InitForRace` and the cleanups call are
seams, NULL until their slices land. `racecoord.h` lists each one with its
retail address. A NULL seam does nothing, and allocates nothing for the
object it would have built. With `gReplayManagerCtorFn` NULL,
`pReplayManager` stays NULL, which everything reads as not replaying.

`main.c` does not wire the coordinator into trackflow's
`gNewRaceCoordinatorFn` yet. That comes with the slice that flows into a
race. Until then, loading a track still builds no race.

## The cross-check

Scenario families:

- **the queue**: `ChangeState`, `SendMessage`, `PostMessage` and
  `ExecuteQueuedMessages` over the script's executing flag and state.
  Callbacks answer messages with sends, posts, changes and nested runs.
- **lifetimes**: constructions and destructions over every first state,
  driver tables, free memory either side of 0x7d000, the prerace
  animation, and coordinators and end-game screens set before the
  destructor, with destructor flags 0 to 3.
- **cycles**: `InitForRace` and `CleanupAfterRace` again and again on one
  coordinator, plus `CleanupPlayers` and `CleanupCars` on their own.
- **driving styles**: `SetAIDriverModesFromPlayers` over positions, styles
  and the AI count, with one and two player cars, and with no World or no
  Race.
- **drivers**: the lookup over tables with repeats and every count.
- **edges**: the free threshold, the rank of 0, and every pair of player
  positions around the middle.

The model stubs every callee the harness owns at its retail address. The
World's constructor stub builds the scenario's world at retail's offsets.
The state table's ten entries are patched to fake callbacks. A callback's
reaction runs `SendMessage`, `PostMessage`, `ChangeState` or
`ExecuteQueuedMessages` in the image from inside the stub, saving and
restoring the emulator's registers around the nested call. Each callback
line prints the coordinator's fields that the constructor sets around
`InitForRace`, which pins the order of those stores. The slot pool's free
prints the executing flag, which pins the flag being cleared before the
slot is freed. The Player's constructor stub fills in the scenario's
style and registers the player in the tables, as Player's own
constructor does. The `InitPlayers` stub hands each player its car.
