# `RaceCoordinator` -- the race's lifetime and its message queue

The `RaceCoordinator` owns a race from the moment the track is loaded to
the moment it is unloaded. Its constructor builds everything a race needs
through `InitForRace`, and its destructor takes it all down again through
`CleanupAfterRace`. In between, the race runs as a state machine. There are
ten states, and each one is a callback that answers messages. The messages
go through a queue, and `ChangeState` is three of them in a row.

Step 8e ported the lifetime and the queue. Step 8f ported the first four
states, `NONE` through `RACE_IN_PROGRESS`, with the countdown and the
finish (see "The states up to the finish", below). Step 8g ports `PAUSE`
and `POSTRACE` (see "The pause and the post-race"). TASKS 72g-3 and
72g-4 brought the two replays, and 72h-2b the two demos (see
[replay.md](replay.md)); every table entry is set. The coordinator's
DoSnapshot (0x001498f0), which takes the world's,
the race's and the players', came with TASKS 72d-2 in `worldsnap.c`; see
[replay.md](replay.md).

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
touches it otherwise. It is `PostRacePlayerNumber`, the player whose car
the post-race follows (see "The pause and the post-race").

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

## The states up to the finish (8f)

`3DS Files/source/rcstates.c`/`rcstates.h` port the first four states,
the countdown, the finish and the small methods around them.
`racefinish.c`/`racefinish.h` port the six `Race` methods those states
ask. `rcstates.c` defines the state table with the four at their
`RCState`s. The other six came with later slices (8g, 72g-3, 72g-4
and 72h-2b).

| retail | what |
|--------|------|
| `0x0014a668` | `RCStateNoneCallback`, 396 bytes |
| `0x0014a7f8` | `RaceCoordinatorJoystickHandler`, 32 bytes |
| `0x0014a818` | `ResumeDemoCameras()`, 92 bytes |
| `0x0014a878` | `SuspendDemoCameras()`, 68 bytes |
| `0x0014abe0` | `RCStateCameraFlybyCallback`, 276 bytes |
| `0x0014acf8` | `RCStatePreRaceCallback`, 392 bytes |
| `0x0014ae80` | `RCStateRaceInProgressCallback`, 648 bytes |
| `0x0014b108` | `Animate321GoElement`, 344 bytes |
| `0x0014b260` | `DisplayCountdownNumber(int)`, 376 bytes |
| `0x0014bce0` | `TheRaceHasFinished()`, 248 bytes |
| `0x00174e00` | `RequestUnPause(UnPauseReasonType)`, 12 bytes |
| `0x001832a8` | `RequestPause(int)`, 12 bytes |
| `0x001842a8` | FrontendDatabase's record-times loop, no symbol, 112 bytes |
| `0x001480c0` | `Race::GetCountdownNumberToDisplay()`, 200 bytes |
| `0x00148188` | `Race::GetCountdownProgress()`, 140 bytes |
| `0x00148f68` | `Race::SimulateRaceFinish()`, 144 bytes |
| `0x00148ff8` | `Race::NotifyTheRaceIsOver()`, 128 bytes |
| `0x001490b0` | `Race::AreAllPlayersFinishedRacing()`, 72 bytes |
| `0x001490f8` | `Race::GetMostRecentlyFinishedPlayer()`, 92 bytes |
| gp-19564 | `WorldTimeFrames` |
| gp-19028 | the jukebox's delayed-start timer |
| gp-31436, gp-31428 | 0.9, a count in seconds |
| gp-31432, -31424, -31420 | 1/60, a frame in seconds |
| gp-31376 | 0.8, the GO's sample limit |
| gp-31384 | 9e9 (`0x50061c46`), the music's "never" |
| `0x002fc050` | `TheFrontendDatabase`; its display settings are at +332 |
| `0x0031a898`+748 | `TheRaceParameters.GlobalDisplaySettings`, 8 bytes |
| `0x0031b600` | `TheRaceEvent` |

The `Race` words read here are `RaceStage` +0, `StartGoTimeFrames` +4,
`StartCountdownTimeFrames` +8, `NumRacingCars` +24 and `pRacingCars`
+1572. A `RacingCar`'s `RacePosition` is the signed byte at +10 and its
`FinishReason` the signed half at +18. A `Player`'s `MyCar` is at +4,
`TimeFinishedRacing` at +80 and `FinishAnimationLength` at +84. A `Car`'s
`pAnimatedDriver` is retail's +1204.

Every callback answers 1 for a message it takes and 0 otherwise.

### `RCSTATE_NONE`

It takes `ACTIVATE`, `UNACTIVATE` and `TICK`, and does nothing with them.

- `RESTART_RACE`: `CleanupAfterRace`, `InitForRace`, `sound::Mute(false)`,
  the record times, the display settings copied, and the jukebox's
  delayed-start timer set to 9e9. The music then waits for the next
  race's start.
- `NEXT_RACE`: `SetupNextRace` if the parameter is nonzero, then the
  record times and the display settings, then
  `ChangeGameFlow(UNLOADING_TRACK_SPECIFIC, LOADING_TRACK_SPECIFIC)`.
- `QUIT_RACE`: `ChangeGameFlow(UNLOADING_TRACK_SPECIFIC, NONE)`. Retail
  asks `DemoDiscManager` first, and an active demo disc ends its attract
  mode instead. It is never active on the retail disc, so the port drops
  the branch.

The record times are `SetRecordTimesToBeat(i)` for each player car, with
`NumPlayerCars` re-read every pass. The display settings are the eight
bytes at the frontend database's +332, copied with `ldl/ldr` into
`TheRaceParameters.GlobalDisplaySettings`.

### `RCSTATE_CAMERA_FLYBY`

- `ACTIVATE`: if there is no flyby camera,
  `new FlyByCameraCoordinator(1)` on `bMalloc(40,
  "..\indep\src\racecoordinator.cpp", 1289, 16)`. Then
  `EnableStartRaceScreens`.
- `UNACTIVATE`: `DisableStartRaceScreens`.
- `TICK`: once `FlyByCameraCoordinator::IsFinished`,
  `SetRaceStage(PRERACE)` and `ChangeState(PRERACE)`. Retail tests
  `BeACop` here and does the same on both branches.
- `SKIP`: the same, without the wait.
- `REQUEST_PAUSE`: `PausedJoystickPort` = the parameter,
  `BeforePauseRCState` = the current state, `ChangeState(PAUSE)`.

### `RCSTATE_PRERACE`

- `ACTIVATE`: if there is no prerace camera,
  `new PreRaceCameraCoordinator(1)` on `bMalloc(188, ..., 1378, 16)`.
  Then the flyby camera, if there is one, is deleted through its virtual
  destructor (flags 3) and cleared.
- `UNACTIVATE`: `AnimatedDriver::CancelAllAnimations` on the driver of
  each car on the World's `CarList` that has one. `pCurrentWorld` is
  re-read after each call. Then `"GLOBAL\PRERACEANIM.LZC"` is unloaded if
  it is loaded.
- `TICK`: only on the `PRERACE` stage. Once the prerace camera's word at
  +184 is nonzero, `SetRaceStage(COUNTDOWN)` and
  `ChangeState(RACE_IN_PROGRESS)`.
- `SKIP`: the same, without the stage test or the wait.
- `REQUEST_PAUSE`: as the flyby.

### `RCSTATE_RACE_IN_PROGRESS`

- `ACTIVATE`: the prerace camera, if there is one, is deleted (flags 3)
  and cleared.
- `UNACTIVATE`: `DisplayCountdownNumber(0)`.
- `TICK`, in order:
  1. `DisplayCountdownNumber(GetCountdownNumberToDisplay())`.
  2. If the replay's `BeginningOfTime` (the `Timer` at the
     ReplayManager's +92) is 0 or unset (`0x7fffffff`), and the stage is
     `RACING`: `MarkTheBeginningOfTime`, and the jukebox's
     `DelayedStart(6.0)`. A `bCountFreeMemory(16)` between the two is
     unused. The port's ReplayManager is a zeroed stand-in; main.c keeps
     the Timer at +92 in it, so this starts the race's music six seconds
     after GO (`jukebox.md`, "The race's music").
  3. If every player has finished, the most recently finished player is
     found. Once that player's `TimeFinishedRacing +
     FinishAnimationLength` is below `WorldTimeFrames` (signed),
     `TheRaceHasFinished`.
  4. With two or more players, each player who has finished and whose
     finish has been shown watches a car. If not every player has
     finished, it is the car of the first other player who has not:
     `Player::BeginDemoCameras(p, q->MyCar)`. `NumPlayers` is re-read
     after each `AreAllPlayersFinishedRacing` and each `BeginDemoCameras`.
- `SKIP`: `TheRaceHasFinished` if every player has finished.
- `REQUEST_PAUSE`: as the flyby.
- `REQUEST_AUTO_REPLAY`: `ChangeState(AUTO_REPLAY)`.
- `NEXT_RACE`: `ChangeState(NONE)`, then `SendMessage(NEXT_RACE, param)`.
  The send queues behind the message running now, so `NONE` answers it.
- `TAKE_AUTOSNAPSHOT` is taken and does nothing.

### The countdown

`GetCountdownNumberToDisplay`, where a count is 0.9 s (1.0 s for the cop)
and a frame is 1/60 s:

- With `StartGoTimeFrames` set: 4 (the GO) while `WorldTimeFrames -
  StartGoTimeFrames` is 60 or less, then 0.
- With `StartCountdownTimeFrames` set: 3, 2 and 1 for each count after
  it, then 4.
- With neither: 0.

The frame differences are `subu`, so they wrap. They are converted to
float signed, then multiplied by the frame (`mul.s`, not a division).

`GetCountdownProgress` is the time over four counts. After
`StartGoTimeFrames` it starts at three counts. Before either start time
is set it is 0.

`DisplayCountdownNumber(n)`:

1. If `n` is 4 and the progress is below 0.8, the in-game sample
   `"CountDownHigh"` is played at (1.0, 0.0, 0.0), unless it is playing
   already.
2. If the progress is above 1.0, or `n` is 0 or 4, the countdown screen
   (`0x936ace42`) is made visible, and that is all.
3. Otherwise the screen is hidden, and `Animate321GoElement` runs for the
   3 (`0x93667af3`) over 0 to 0.25, the 2 (`0x93667af2`) over 0.25 to 0.5
   and the 1 (`0x93667af1`) over 0.5 to 0.75.

`Animate321GoElement(start, end, progress, screen, object)`:

- Until `progress` is past `start`, the object is hidden.
- From then, `t` is the share of the window gone, or 1 past its end.
  `t` is then multiplied by 6 and held at 1, so the animation takes the
  window's first sixth.
- If the object was not visible (its byte at +41 is 0), the
  `"CountDownLow"` sample plays.
- The object is made visible, with alpha `(int)(t * 128)` (`cvt.w.s`,
  towards zero) and scale `t * -3 + 4`, shrinking from four times its
  size to its own.

### The finish

`TheRaceHasFinished`:

1. `MarkTheEndOfTime` on the ReplayManager.
2. `CheckForAbortion`.
3. `SimulateRaceFinish`.
4. `NotifyTheRaceIsOver`.
5. The frontend's `TheRaceIsOver(race)`.
6. What comes next: `NEXT_RACE` (1) if `IsThereAnotherRace`, else `NONE`
   (0) if `IsMultiTrack`, else `RESTART` (2).
7. `new EndGameScreens(next)` on `bMalloc(72, "EndGameScreens", 0, 16)`,
   kept in `pEndGameScreens` ([end-game.md](end-game.md)).
8. `ChangeState(POSTRACE)`.

Retail's active demo disc ends the race between steps 6 and 7 instead
(`SetEndReason`, `ChangeState(NONE)`, `SendMessage(QUIT_RACE)`). The port
drops that branch.

`SimulateRaceFinish` calls `FinishCar(i, 0, false, NORMAL_COMPLETION)`
([race-update.md](race-update.md), through `gRaceFinishCarFn`) on
each racing car whose `FinishReason` is still 0, then
`SortRacingCarsByLeadership`. `NumRacingCars` is re-read only after a car
is finished. `NotifyTheRaceIsOver` calls `TheRaceEvent.RecordResults`
for each racing car with its signed `RacePosition`, re-reading the count
every pass.

`AreAllPlayersFinishedRacing` is whether every player has a nonzero
`TimeFinishedRacing`. With no players, it answers yes.
`GetMostRecentlyFinishedPlayer` answers the player with the largest
`TimeFinishedRacing` above 0, compared signed. A tie keeps the earlier
player, and with no such player it answers NULL.

### The small methods

- The joystick handler posts `SKIP` to `pRaceCoordinator` on
  `JOY_EVENT_SKIP_DEMO_MODE` (22).
- `RequestPause(port)` posts `REQUEST_PAUSE` with the port, and
  `RequestUnPause(reason)` posts `REQUEST_UNPAUSE` with the reason.
- `ResumeDemoCameras` makes `new DemoCameraCoordinator(1, car)` on
  `bMalloc(52, ..., 1082, 16)` for the first player's car, if there is no
  demo camera.
- `SuspendDemoCameras` deletes the demo camera (flags 3) and clears it.

### Where the port reads differently

Retail reads these unchecked. The port guards each one, so a race without
the object still goes on:

- A NULL flyby camera, or a NULL prerace camera, counts as finished.
- With no ReplayManager, the `TICK` neither marks the beginning of time
  nor starts the music, and `TheRaceHasFinished` marks no end of time.
- With no players, all have finished but none is the latest, so the
  `TICK` does not finish the race. Retail reads the NULL player's times
  there.

The demo-disc branches are dropped, as above. So are the
`bCountFreeMemory` calls whose answers nothing reads.

The other callees are seams in `rcstates.h` and `racefinish.h`, each
listed with its retail address. A NULL seam does nothing.

### The cross-check

`tools/rcstates_check.py` runs these in the retail image, on top of the
8e queue they use. The harness takes `racecoord.c` through a wrapper the
checker generates, which renames `InitForRace` and `CleanupAfterRace` out
of the way so the harness's stubs can stand in for them.

Scenario families:

- **countdown**: the number and the progress over the clock, both start
  times, the cop's count, the samples and the three numbers' objects.
- **finish**: `TheRaceHasFinished` and its `Race` halves, over the racing
  cars, `FinishCar` taking cars off the count, and what comes next.
- **tick**: the race's `TICK` over the beginning of time, the stage, the
  players' finishes and the two-player hand-over.
- **flow**: the four states run on the queue from `NONE` or the flyby to
  the finish, with reactions from the six fake states.
- **direct**: each of the four callbacks called once with every message,
  and -1, 15 and 100.
- **small**: the joystick handler, the pause requests and the demo
  camera.
- **edges**: each count's boundary frame for both counts, the GO's 60
  frames, the GO's sample either side of 0.8, the finish animation's
  last frame, and every pair of answers for what comes next.

402 scenarios, 17258 ops, 40165 transcript lines, 0 differ. Of 148
mutations, 143 are caught and 5 are equivalent. The equivalent ones are
the two-player hand-over's guards, which at most two players cannot tell
apart, and the countdown's clamp at the end of a window, which the clamp
at 1 repeats. The first pass left two holes, which new scenarios close:
a flyby `TICK` with no camera, and `RecordResults` taking a car off the
count.

## The pause and the post-race (8g)

`3DS Files/source/rcpost.c`/`rcpost.h` port `PAUSE` and `POSTRACE`, and
the four small Player calls the pause makes. `rcstates.c`'s state table
has the two at their `RCState`s now. The two replays and the two demos
are the last four entries, NULL until their slices. Since TASKS 72g-4
only the demos' two are.

| retail | what |
|--------|------|
| `0x0014b3d8` | `RCStatePauseCallback`, 400 bytes |
| `0x0014bdd8` | `RCStatePostRaceCallback`, 796 bytes; jump table `0x002afb50`, messages 1 to 13 |
| `0x00181bd0` | `Player::BeginPause()`, a tail call to `ClearHudAnimations` (`0x0017c7c8`) |
| `0x00181bd8` | `Player::EndPause()`, 44 bytes |
| `0x00181c88` | `TellPlayersToPause()`, 92 bytes |
| `0x00181ce8` | `TellPlayersToUnPause()`, 92 bytes |
| `0x00154308` | `GetJoystickType(JoystickPort)`, `lbu` of gp-21920 plus the port |
| `0x0014d668`, `0x0014d670` | `World::BeginPause()` and `EndPause()`, both empty |
| `0x001543f0` | no symbol: for ports 0 and 1, `RemoveJoyHandler` and `AddJoyHandler` of `JOY_EVENT_TYPE_CHANGED` with `TypeChangedHandler` (`0x001542a8`) |
| gp-21064 | `ThePauseMenu` |
| gp-19552 | `WorldLoopCounter` |
| gp-21920 | `CurrentJoystickTypes`, a byte per port |
| `0x002afa38` | `"Pause Menu"` |
| `0x002fc3dc` | `TheTransientStats` |

`RaceCoordinator`+140 is `PostRacePlayerNumber` now: the player whose car
the post-race's demo camera follows. The constructor, the post-race's
`ACTIVATE` and its `UNACTIVATE` are the only writers.

The `Player` words are `JoyPort` +8, `JoyType` +12 and `PlayerNumber`
+16. The `ReplayManager` words are retail's new word at +12, which mutes
the replay's sound for the highlights, and `EndCurrentHighlightTime`
+160, a `WorldLoopCounter`. `World::CarTable` is at +44. Retail's
`TransientStatsElement` is 100 bytes, with `FinishPosition` at +0.

### `RCSTATE_PAUSE`

- `ACTIVATE`: `World::BeginPause`, `TellPlayersToPause`,
  `PauseMenu::EnterPause(ThePauseMenu, PausedJoystickPort)`,
  `ChangeToScreen("Pause Menu", 1)` and `sound::Mute(1)`.
- `UNACTIVATE`: `ChangeToScreen(NULL, 0)`, `PauseMenu::ExitPause`,
  `TellPlayersToUnPause`, then `World::EndPause` when there is a World.
- `TICK` is taken.
- `REQUEST_UNPAUSE`, on its `UnPauseReasonType`:
  - `RESUME_RACE` (1) unmutes and goes back to `BeforePauseRCState`.
  - `INSTANT_REPLAY` (4) goes to `INSTANT_REPLAY`.
  - `QUIT_RACE` (3) is `TheRaceWasQuit` on the frontend database, then
    `NONE` and `QUIT_RACE` sent. An active demo disc would record its end
    reason (5) between the two; the port drops it.
  - `RESTART_RACE` (2) goes to `NONE` and sends `RESTART_RACE`.
  - Any other reason is taken and does nothing.
- Anything else answers 0.

The menu itself, and what main.c does around it, is in
[pause-menu.md](pause-menu.md).

### `RCSTATE_POSTRACE`

- `ACTIVATE`:
  1. Each player's camera mover goes to `CM_NONE`, without keeping the
     old one. The loop re-reads `NumPlayers` each pass.
  2. `sound::Mute(0)`, and the speech manager's queue flushed.
  3. `sound::MuteReplay(1)` if the `ReplayManager`'s +12 is set, then
     `BeginRaceHighlights` and the end-game screens' `ResumeScreens`.
  4. `PostRacePlayerNumber` is 0. With two players or more, each player's
     `TransientStats::GetDriver(PlayerNumber)` is asked, and a driver
     whose `FinishPosition` is below the best so far (8 to start) makes
     that player's number the one. Ties keep the first.
  5. A 52-byte `DemoCameraCoordinator(1, World.CarTable[number])`, from
     line 2361. Retail does not delete a camera it already has.
- `UNACTIVATE`: the end-game screens' `SuspendScreens`, the demo camera
  deleted, `PostRacePlayerNumber` and the camera pointer zeroed, then
  `0x001543f0`.
- `TICK`: once `WorldLoopCounter` reaches the `ReplayManager`'s +160,
  `BeginNextRaceHighlight` and a new demo camera (line 2396) in place of
  the old. Before that it is taken and does nothing.
- `SKIP_REPLAY` (11): `MuteReplay(1)`, `BeginNextRaceHighlight` and a new
  demo camera (line 2418).
- `START_REPLAY` (12) goes to `INSTANT_REPLAY`.
- `RESTART_RACE` (8) is `TheRaceWasRestarted`, then `NONE` and
  `RESTART_RACE` sent. `NEXT_RACE` (9) goes to `NONE` and sends
  `NEXT_RACE` with its parameter. `QUIT_RACE` (10) goes to `NONE` and
  sends `QUIT_RACE`.
- `TAKE_AUTOSNAPSHOT` (13) is taken. Messages 4 to 7, 14 and above, and 0
  and below answer 0.

### The Player calls

`TellPlayersToPause` and `TellPlayersToUnPause` call `BeginPause` and
`EndPause` on each of `pPlayersByIndex`, re-reading `NumPlayers` each
pass. `BeginPause` is `ClearHudAnimations`. `EndPause` stores
`GetJoystickType(JoyPort)` in `JoyType`, so a pad changed during the
pause is picked up when it ends. The port's `GetJoystickType` is
`joystick.c`'s.

### Where the port reads differently

- Retail reads the `ReplayManager` in the post-race's `ACTIVATE`, `TICK`
  and `SKIP_REPLAY` without a test. The port's `TICK` does nothing with no
  `ReplayManager`, and `ACTIVATE` does not mute the replay's sound.
- The replay's two words are seams (`gReplayMuteHighlightsFn`,
  `gReplayEndCurrentHighlightTimeFn`), as the 8f marks are, because the
  port's `ReplayManager` is not retail's layout. With the second NULL, the
  `TICK` never begins the next highlight.
- With no `DemoCameraCoordinator` constructor, the camera pointer is
  NULL and nothing is allocated. With no World, the camera follows no car.
- The demo disc's end reason on `QUIT_RACE` is dropped.

### The cross-check

`rcstates_check` runs both callbacks, the four Player calls,
`GetJoystickType` and the two empty World methods as shipped, alongside
8f's. States 4, 5, 8 and 9 stay fake. New stubs print the pause menu's
`EnterPause` and `ExitPause`, `ChangeToScreen`, the frontend's quit and
restart, `ChangeCameraMover`, the speech queue, the replay's highlights
and `MuteReplay`, the end-game screens, `GetDriver`, `ClearHudAnimations`
and `0x001543f0`. `GetDriver` answers from four 16-byte elements, any of
which can be missing. The dump gains `PostRacePlayerNumber` and both
players' `JoyType`.

600 scenarios, 29584 ops, 64046 transcript lines, 0 differ. Of 230 mutations, 225
are caught and 5 are equivalent.

## Seams

The two demos' states and most of what `InitForRace` and the cleanups
call are seams, NULL until their slices land. CleanUpAutoReplay is
bound since TASKS 72g-4. `racecoord.h` lists each one with its
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
