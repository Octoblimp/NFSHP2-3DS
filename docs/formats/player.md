# `Player.obj` -- the player's lifetime

A `Player` is one person at the controller: the car they drive, the view
it is drawn in, the camera movers, the HUD's Flailer objects, the NIS
overlay that plays over a ticket or an arrest, and the settings they chose
in the frontend. `RaceCoordinator::InitForRace` builds one or two of them
(`bMalloc(2752)` each), `InitPlayers` hands each its car, and
`CleanupPlayers` takes the cars back after the race.

The port is `3DS Files/source/player.h` (the record and the class's
statics), `playerinit.c`/`playerinit.h` (the lifetime, step 8a),
`nisoverlay.c`/`nisoverlay.h` (the overlay) and `playercam.c` (the
cameras, step 7d, written up in [camera.md](camera.md)). Everything here is
retail's. `tools/player_check.py` runs the retail image itself in
RetailEmu as the oracle: 8 scenarios, 3659 ops, 501513 transcript lines,
0 differ. All 287 of its mutations are caught, three of them by crashing
the harness. Before the run it also compiles `player.h` with devkitARM and
asserts every field the transcript names at its retail offset.

## Where things are

| retail | what |
|--------|------|
| `0x001751d8` | `Player::Player(JoystickPort, int)`, 2580 bytes |
| `0x00175bf0` | `Player::~Player` |
| `0x00176ab0` | `Player::CleanUpJumpCam` |
| `0x00181920` | `Player::InitForRace(Car *)`, 80 bytes |
| `0x00181970` | `Player::CleanupAfterRace`, 112 bytes |
| `0x001819e0` | `Player::PredetermineNisNumbers` |
| `0x00181a28` | `Player::CreateRandomNisArray`, a seam |
| `0x001edf90` | `cPlayerSettings::ResetToDefaults` |
| `0x001ee2d8` | `cPlayerSettings::ToggleLookback` |
| `0x00182350` | `NISOverlayManager::NISOverlayManager`, 220 bytes |
| `0x00182430` | `NISOverlayManager::~NISOverlayManager` |
| `0x001829a8` | `NISOverlayManager::SetScreen`, new in retail |
| `0x00182948` | `NISOverlayManager::Finish` |
| `0x001788b0` | `Player::AutoPilotOff`, a bare `jr ra` |
| `0x0031a898` | `TheRaceParameters` |
| `0x0031ab24` | `TheRaceParameters.PlayerSettings[2]` (+652) |
| gp-20920 | `Player::NumPlayers` |
| gp-20928 | `Player::pPlayersByIndex[2]` |
| gp-20936 | `Player::pPlayersByNumber[2]` |
| gp-20916 | `0.9`, the constructor's `SpeedFactor` |
| gp-23220 | SkipFE |
| gp-23172 | the POV byte `ResetToDefaults` takes under SkipFE, 1 on the disc |
| gp-23564 | `bResetGlare` |
| gp-19576 | `WorldTimer` |

The seams, NULL until their classes are ported:

| retail | what |
|--------|------|
| `0x001b0fe0`, `0x001b1110`, `0x001b1388` | `NisManager`'s constructor, destructor and `Stop` |
| `0x001ae280` | `GetInGameSample` |
| `0x00143d50` | `FindFlailerObject` |
| `0x00140978` | `FlailerObjectChunk::GetTopLeft` |
| `0x001407d0`, `0x001407f8`, `0x00140a48` | `FlailerObjectChunk::SetScaleX`, `SetScaleY`, `SetTopLeftY` |
| `0x001444e8` | `FlailerGetScale` |
| `0x00144168` | `FlailerGetTopLeftY`, the float one |
| `0x0017bd20` | `Player::ResetFlailerMovement` |
| `0x001796b0` | `Player::SetHudFeatures` |
| `0x001776b0` | `Player::SetInputMode`, 1240 bytes |
| `0x00175030` | `VisibleDrivingLine::~VisibleDrivingLine` |
| `0x0023b168` | `HudAnimator::~HudAnimator` |
| `0x0010f1b0` | `RadialBlurOff` |

These callees are ported already: `TopologyCoordinate`'s constructor and
destructor (`topology_init`, [topology.md](topology.md)), `Average`'s
(`average_init`), `GetJoystickType`, `RealDriver::SetManualTransmission`
(`0x0013b390`) and `Player::RemoveCameraMovers`.

## The record

Retail's `Player` is 2752 bytes; the demo's (.mdebug type#2091) is 2480.
Retail has no symbols. The map comes from lining up the two constructors
(the demo's at `0x0016ee50`, 2104 bytes) and from the methods that read
each field. The fields retail added are named by the port, `NewNNN` where
nothing says more. `player.h` has every field, with its offset, and
asserts them where pointers are 4 bytes.

Against the demo, retail's fields move in bands:

| demo | retail | what |
|------|--------|------|
| 0-16 | 0-16 | the callback, `MyCar`, the joystick, `PlayerNumber` |
| | 20 | `pOtherPlayer`, new |
| 20-64 | 24-76 | the views and `PlayerSettings`, 48 bytes now |
| 68-164 | 80-176 | the race and zone words (+12) |
| | 180, 184 | a float `FillInRaceOverMessages` reads, and a Timer for the zone sound |
| | 188-228 | `DrivingControls`, `nGlueCount`, `PlayerInputMode`, the camera words with `pSavedCameraMover2` at 208 |
| 208-1316 | 232-1340 | the NIS words and arrays, `bWrongWay`, `bLookBack`, the HUD hashes, the flailers (+24) |
| | 1300-1403 | the live-split arrays, 68 bytes where the demo's were 36; Be The Cop's flailers |
| 1340- | 1404- | the radar, the score strings, the HUD animators, the jump cam, `Topology` (+64) |
| | 2472-2480 | the auto-replay words (+208) |
| | 2540 | `New2540`: the constructor makes it 1 and `UpdateScoring` clears it |
| | 2560 | `mFlailerNIS`, 56 bytes where the demo's was 40 |
| | 2616 | `lastCar` |
| | 2696-2740 | the score display: four flailers, their tops, a Timer and `New2736` |

Some smaller changes:

* Retail's 152 is a Timer, `tIgnoreNextPovChange`, where the demo had the
  int `bIgnoreNextPovChange`. `RacingJoyHandler` reads and writes it, and
  `ChangeCameraMover` zeroes it.
* The demo's `bLiveSplitOffset` and `fInitialLiveSplitY` are gone.
* The constructor clears five bits of `DrivingControls` (188) through a
  64-bit `ld`/`sd` at 184. The port clears the same bits in the 32-bit
  word.

### `cPlayerSettings`

48 bytes in retail; the demo's (.mdebug type#3426) is 40. The save game
will read it in place (step 17), so it has retail's layout too.

| offset | field | default |
|--------|-------|---------|
| 0 | `PlayersHudState` | 0 |
| 1 | `Rumble` | 1 |
| 2 | `DrivingStyle` | 0; `InitForRace` gives it to the car |
| 3 | `TransmissionType` | 0; `InitForRace` gives it to the driver |
| 4 | `DriveCameraPOVIndex` | 1, or the byte at gp-23172 under SkipFE |
| 5 | `SplitTimeType` | 0 |
| 6 | `PreferredGender` | 0 |
| 7 | `New7` | 0; padding in the demo |
| 8 | `CameraSpring` | 0 |
| 12 | `Lookback` | 1 |
| 16 | `PreferredHudFeatures` | 853 |
| 20 | `PlayerName[12]` | `"PLAYER"` |
| 32 | `BestTotalTimeRecord` | 0 |
| 36 | `BestLapTimeRecord` | 0 |
| 40 | `New40` | 1 |
| 44 | `New44` | 1; `0x001ee020` toggles it |

The seven bytes are type 2, `char`, which the image loads with `lb`.
Retail's word at 12 is an int, where the demo's was the float
`LookbackSpeed`. `ToggleLookback` turns 0 and 1 into each other and leaves
anything else, and the drive camera counts a look back only while it is 0.

`ResetToDefaults` writes in this order: `Rumble`, the other three leading
bytes, the POV, bytes 5-7, `CameraSpring`, `Lookback`, the name through
`bStrCpy`, `PreferredHudFeatures`, `New44`, `New40`, then the two records.

### `TheRaceParameters`

The port keeps `RaceParameters` as loose globals in `race.h`. Retail's
offsets match the demo's through 596: `AIDemoMode` 24, `ReplayDemoMode` 28,
`NumPlayerCars` 48, `NFSRaceMode` 596 and `nMaxCops` 604. Past that
retail has one int more. `DoSnapshot` (`0x001ed6f8`) snapshots eleven ints
at 604-644 where the demo has ten, then `CopStrength` at 648. `BeACop` is
at 628. The two `PlayerSettings` follow at 652, which is `0x0031ab24`.
They are all zeroes on the disc, and `RaceParameters::InitWithDefaults`
resets both.

## The constructor

`Player(JoystickPort port, int number)`, on memory the caller allocated.
In order:

1. **The Timers' constructors**, in declaration order: the two settings
   records, the eight zone timers, 152, 164, 172, 176, 184 and 1408. Then
   `topology_init` on `Topology` (1768), the overlay's constructor on
   `mFlailerNIS` (2560), and 2620 and 2732 zeroed.
2. **The tables.** The player goes into `pPlayersByIndex[NumPlayers]`,
   the count goes up, and it goes into `pPlayersByNumber[number]`. It
   copies `TheRaceParameters.PlayerSettings[number]`. `pOtherPlayer` is
   zeroed. When the count is 2 after the increment, the two players'
   `pOtherPlayer` point at each other.
3. **The identity.** `JoyPort`, `JoyType` from `GetJoystickType(port)`,
   and `PlayerNumber`. Then `PlayerInputMode`, the finish and record words,
   the zone words and the zone sample are zeroed, and the eight zone timers
   are zeroed again, each with its credit byte.
4. **The views**, from `NumPlayerCars`. With anything but two player cars,
   `ViewID` is 1 and `RearViewMirrorViewID` 3. With two, `ViewID` is 1 for
   number 0 and 2 otherwise, and there is no mirror (0).
5. **The cameras and the HUD's screens.** `pRoute`, the camera words
   200-228 and 768-776 are zeroed. The two screen hashes are set only
   when neither `AIDemoMode` nor `ReplayDemoMode` is:

   | case | `HudScreenHash` | `NisOverlayHash` |
   |------|-----------------|------------------|
   | not two player cars | `0xf1f1f8e5` | `0x3ea89b7c` |
   | two, number 0 | `0xa8eb7af0` | `0xd4d25ee7` |
   | two, number 1 | `0x6283be92` | `0xc17316c9` |
   | two, any other number | 0 | 0 |

   After that, a nonzero `BeACop` makes `NisOverlayHash` `0x3ea89b7c`,
   whatever the rest says. Then the overlay's `SetScreen` takes
   `NisOverlayHash`.
6. **The flailer words** are zeroed, except `pFlailerBigRacePosition2`
   (984), `pFlailerDebugBacking` (1068) and `DriftTime` (1512).
7. **The NIS manager.** `bSPrintf(name, "Player%d", 1 - number)` (the
   manager is named for the *other* player's number), `bMalloc(320,
   "NisManager", 0, 16)`, and `NisManager(mem, name, number)` into
   `pNisManager`. `ArrestNisIndex` and `TicketNisIndex` are -1, the
   callback and its parameter 0, the four 32-word NIS arrays 0, and
   `nGlueCount` 0.
8. **What it owns.** `bMalloc(16, "..\indep\src\player.cpp", 520, 16)`
   and `Average(10)` into `pAverageSpeedRatio`. Then 164, 168, the 20 HUD
   animators, 1620, 2544 and 180 are zeroed. `myCD` is `bMalloc(164, ...,
   531, 16)`, the jump cam's `CameraDataItems`. `FOVtable` is a `new[]` of
   32 `bVector3`, 512 bytes, at line 532. `pJumpCamRoute`, `bWrongWay`,
   `bLookBack` and two auto-replay words are zeroed.
9. **The strings and the lights.** `strEventScore` and `strPrevScore`
   become `"0"`, and `strEventTitle` is left. The radar, nitrous, damage,
   ticket, tracker and place arrays are zeroed, high index first, and the
   helicopters and roadblocks low index first.
10. **The rest.** `pRadarBeep = GetInGameSample("RadarBeep")`. The radar
    timer is zeroed again, then a run of words. `SpeedFactor` is 0.9.
    `LastCrossingTime` is `(int)(WorldTimer * f(gp-30476) * 4000 + 0.5)`,
    with gp-30476 being 1/4000 (WorldTimer to seconds and back, rounded).
    `CurrentJukeboxIndex` is -1. Five bits of `DrivingControls` are
    cleared, and `New2540` and `bCheckTopSpeed` are 1.
11. **The score display.** `FindFlailerObject(0x49c15518, h, 2)`, type 2
    being a bitmap, in this order:

    | hash | into |
    |------|------|
    | `0x464ba8ea` | `pFlailerScore[1]` (2704) |
    | `0xd911beac` | `pFlailerScore[0]` (2700) |
    | `0xf7f1cfb3` | `pFlailerScore[2]` (2708) |
    | `0xf88dd0b1` | `pFlailerScore[3]` (2712) |

    Then `GetTopLeft` on each, in the same order, for `fScoreTop`. The
    third and fourth are less the first and second: `fScoreTop[2]` is
    `y(2) - fScoreTop[0]`, and `fScoreTop[3]` is `y(3) - fScoreTop[1]`.
12. `tScoreAnimation` is `0x7fffffff`, for none yet, and `New2736` 0.

The constructor leaves alone the tach point list, the live-split arrays,
`_new1396`, `EyeVerts`, `BankVerts`, `mAutoReplayTimeMarker`,
`PursuitObjectPos` and `PursuitOffsetState`, as well as the words in step 6.

### Where the port differs

* **Both tables stop at two.** Retail indexes them unchecked. A third
  player's `pPlayersByIndex[2]` is gp-20920, which would overwrite the
  count. The destructor's two stores are bounded the same way.
* **`GetTopLeft` is not called on a missing object.** Retail calls it
  without testing, and reads through NULL. The port reads 0 for both
  coordinates then, or with the seam NULL.
* **`bSPrintf` is `snprintf`** into the 32-byte buffers.
* **The `Average` is the port's size.** Retail's `Average` is 16 bytes
  with a new layout, whose first three fields are bytes and whose buffer
  pointer is at 12. The port's is still the demo's, so the bMalloc takes
  `sizeof(Average)`.
* **A NULL seam allocates nothing.** With `gNewNisManagerFn` NULL there
  is no `bMalloc(320)`, and `pNisManager` stays NULL. Every other seam is
  skipped when NULL.

## The destructor

In order:

1. `ResetFlailerMovement`, then `SetHudFeatures(0)`.
2. `pRoute` through `PreviewRoute`'s destructor, and `pZoneSample`
   through its virtual destructor (the vtable at +184), flag 3.
3. `myCD` and `FOVtable` freed, each tested for NULL.
4. `CleanUpJumpCam`.
5. `pVisibleDrivingLine` through its destructor and cleared, the NIS
   manager through its destructor, and the `Average` with flag 3.
6. Each of the 20 HUD animators that is set, through its destructor.
7. `NumPlayers` goes down. `LastSpeed`, `PrevPursuitLevel` and
   `PrevTicketLevel` are zeroed. `pPlayersByIndex[NumPlayers]` is
   cleared. `LastSpeedSet` is zeroed, and `pPlayersByNumber[PlayerNumber]`
   is cleared.
8. `bResetGlare = 1`.
9. The overlay's destructor with flag 2, then the topology's.
10. With bit 0 of the flags, the player itself is freed.

The destructor doesn't clear `pOtherPlayer` on the other player.

`CleanUpJumpCam` deletes `pJumpCamRoute`, if there is one, and clears
it. Car's `FinishMovement` calls it through `gPlayerCleanUpJumpCamFn`.

## The race's two

`InitForRace(Car *c)`:

1. `c->pPlayer` is set to this player and `MyCar` to `c`.
2. `c->State.DriverMode` becomes the settings' `DrivingStyle`, a signed
   byte.
3. When the car's `TheControlMode` is `REAL_CONTROL` (1), its driver
   (`pCarDriver`) gets `SetManualTransmission(TransmissionType)`.
4. It tail-calls `PredetermineNisNumbers`.

`PredetermineNisNumbers` runs `CreateRandomNisArray` with type 1, the
tickets, and sets `TicketNisIndex` to -1. Then it does the same with
type 2, the arrests, for `ArrestNisIndex`.

`CleanupAfterRace`, which `RaceCoordinator::CleanupPlayers` calls, undoes
it in order:

1. `AutoPilotOff`, which does nothing in retail.
2. `RadialBlurOff(PlayerNumber)`.
3. `RemoveCameraMovers`.
4. While the NIS manager plays one (its word at +68 is set), the manager
   gets `Stop` and the overlay gets `Finish`.
5. `SetInputMode(0)`.
6. `MyCar` is cleared, then the car's `pPlayer`.

The demo cleared `MyCar` first. Retail stores through `MyCar` without
testing it; the port skips a NULL car.

## `NISOverlayManager`

The HUD overlay a ticket, an arrest or a bust plays over. 56 bytes in
retail; the demo's (.mdebug type#3487) is 40.

| offset | field | |
|--------|-------|--|
| 0 | `LastDateTimeUpdate` | |
| 4 | `ScreenHash` | the overlay's Flailer screen |
| 8 | `State` | `eFLAILER_NIS`: idle, ticket, arrest, busted |
| 12 | `ScaleAnimationTrack` | a `tCubic1D`, 48 bytes |
| 16 | `AlphaAnimationTrack` | the same |
| 20 | `BustedDisplay` | the BUSTED text's chunk |
| 24 | `New24` | retail's; unread so far |
| 28, 32 | `sx`, `sy` | |
| 36, 40 | `ScaleX`, `ScaleY` | |
| 44, 48, 52 | `SavedScaleX`, `SavedScaleY`, `SavedTopLeftY` | retail's: what `SetScreen` read |

Retail's word at 24 moved `sx` to `ScaleY` down by 4. The three saved
words are new.

* **The constructor** zeroes `ScreenHash` and `State`. It makes two
  `bMalloc(48, "NISCubicAnimation", 0, 16)`, scale first, each with
  `tCubic1D`'s constructor inlined: the four values zeroed, `duration`
  and `arrivalThreshold` 1, `state` 0 and `flags` 1. A track's
  coefficients and time are left. Then `ScaleY` and `ScaleX` are 1, and
  `sx` and `sy` 0. `LastDateTimeUpdate`, `BustedDisplay` and `New24` are
  left.
* **The destructor** frees both tracks without testing them, and frees
  the overlay too with bit 0 of the flags. The Player's passes 2.
* **`SetScreen(hash)`**, new in retail, stores the hash. It calls
  `FlailerGetScale(ScreenHash, 0x76494c5b)` twice, each time from a 1.0
  pair, keeping the first call's x and the second call's y. Then it calls
  `FlailerGetTopLeftY` on the same object. `0x76494c5b` is the BUSTED
  text.
* **`Finish`** returns without a screen. Otherwise it hides the screen
  (`SetFlailerScreenVisibility(hash, 1)`, 1 being INVISIBLE). If
  `BustedDisplay` is set, it puts back the saved scale x, scale y and top,
  in that order.

`Start`, `Update` and the three `Start*` that play the overlay belong to
the NIS, and wait for it.

## The checker

`tools/player_check.py` lays out two Players at retail's offsets, four
cars with a fake driver each, `TheRaceParameters`' words and its two
settings, and the gp words. Every callee outside the functions above is a
stub that prints its arguments. `AutoPilotOff` and `bStrCpy` run as
shipped. The harness (`tools/src/player_test.c`) builds the port over the
same script.

Each Player is filled before it is built, mostly with `0xa5` and
sometimes with `0xff`, `0x5a` or 0. The bMalloc arena is filled with
`0xa5`. So any field a call leaves alone shows in the dump.

The script keeps to what retail survives: no third player, no destructor
with none left, numbers 0 and 1, and `CleanupAfterRace` only with a car
and a NIS manager. Retail's `GetTopLeft` on a missing score object reads
the object. The model's stub answers 0 for it and prints nothing,
matching the port, which reads 0 without calling.

    python tools/player_check.py
    python tools/player_check.py --mutate [--only a,b]
    python tools/player_check.py --dump out/player
