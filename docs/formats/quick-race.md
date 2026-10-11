# Quick Race -- the Mode Selects' race

    StartQuickRace                        0x00216c18
    PickTrackNumberForExpressGame         0x00216aa8
    IsTrackUnlocked                       0x0024b760
    IsTrackAnEventReward                  0x001ffaa8
    EventTreeIsTrackUnlocked              0x001ffb18
    FrontendPlayerInfo::GetCarStatus      0x00187958
    BeginGameFlowUnloadingFrontEnd        0x00168830

Quick Race is the first item on both Mode Selects, Hot Pursuit's (Cops On)
and World Racing's (Cops Off). `CopsOnModeSelect::HandleEvent`
(`0x002170b0`) calls `StartQuickRace` at `0x002171a4` with the screen's
transmission flag (`this+628`, held while the item is picked) for pad 0;
on any other pad it denies the item. `StartQuickRace` fills the race,
gives the player a car and calls `FrontendDatabase::StartRace`, which
changes the game flow, so the frontend is left for the track.

The port is `3DS Files/source/quickrace.{c,h}`. `bscreens.c`'s
`startQuickRace` hands it the transmission flag through the
`startQuickRace` hook, and main.c's hook runs `start_quick_race` and
logs the race (`quickrace: track ...` and the `race start:` lines).
`tools/fredrace_check.py` runs retail's functions as shipped against the
port (the `s_quickrace` and `s_tracklocks` scenarios).

The demo's `StartQuickRace` (`0x00203ae0`, in
[frontend-screens](frontend-screens.md)) is the older one: it put the
player at grid 2 or 8 and neither set defaults, nor gave a car, nor
started the race.

## StartQuickRace (0x00216c18)

1. `TheRaceParameters.InitWithDefaults()`;
2. `TheFlailerScreenList->StopMovie()` (`gp-21324`);
3. `cops = Fred.MainMenuOpts[1]` (Fred+32), which `NewMainMenu` sets for
   the Mode Select the player went into: 1 for Hot Pursuit, 0 for World
   Racing. The word is stored as it is where retail stores `cops`;
4. `Fred.GameType = 2` (the express game) and `Fred.NumPlayerCars = 1`;
5. the track: `PickTrackNumberForExpressGame()` (below), then its
   `GetTrackInfo`, read with no NULL test;
6. the stores into `TheRaceParameters`:

| offset | field | value |
|---:|---|---|
| 0 | `TrackNumber` | the pick's track |
| 12 | `TrackDirection` | the pick's direction |
| 8 | `TrackTimeOfDay` | the TrackInfo's halfword at 68 |
| 52 | `NumAICars` | cops ? 3 : 7 |
| 40 | `Point2Point` | the TrackInfo's byte at 67 |
| 60 | `PlayerStartPosition[0]` | `(u8)NumAICars + 1`: the back of the grid |
| 768 | `BoostScale[1]` | 1.0 |
| 604 | `nMaxCops` | cops ? 4 : 0 |
| 636 | `nNumTicketsBeforeArrest` | cops ? 2 : 0 |
| 16 | `TrafficDensity` | 0.33 (`gp-27340`) |
| 20 | `TrafficOncoming` | 0.5 |
| 764 | `BoostScale[0]` | 1.0 |
| 648 | `CopStrength` | 1 |
| 32 | `RaceType` | 1 |
| 44 | `NumLapsInRace` | 2 |
| 600 | `EventTreeRace` | 0 |
| 756 | `OpponentStrength` | 1 |
| 760 | `Boost` | 1 |
| 48 | `NumPlayerCars` | 1 |
| 612, 616, 624, 620 | `bRoadBlocks`, `bSpikeStrips`, `New624`, `bHelicopter` | cops |
| 640, 644 | `nNumBeACopRoadBlocks`, `nNumBeACopChoppers` | 0 |
| 608 | `bTickets` | cops |
| 80 | `HasObjective` | 0 |
| 84 | `sObjective[0]` | 0 |
| 76 | `TrainingLinesEnabled` | 0 |

7. `Fred.MakeChallengeCarsAvailable()`;
8. the car. With a track named in the config file
   (`TrackSelectedInConfigFile`, `gp-23256`, 0 or more), player 0 gets
   `DefaultPlayer1CarType` (`gp-23136`), made available with all its
   skins and its dash, and assigned with `DefaultPlayer1SkinIndex`
   (`gp-23128`) and no dash. Otherwise a RideInfo starts at type -1 and
   zeroes, and `GenerateRandomRideInfo(&ride, racing, -1)` is drawn until
   `GetCarStatus` says the type is available (0); the ride's type and
   skin (sign-extended) are assigned with no dash. The loop has no limit:
   with no racing car available it would spin, and the disc's data always
   has some;
9. `FrontendPlayers[0].mPlayerSettings.TransmissionType` (player+1607)
   `= transmission != 0`;
10. `Fred.StartRace()`, which builds the drivers (the player, the AI
    racers, the cops and traffic by the parameters) and calls
    `ChangeGameFlow(UNLOADING_FRONTEND)`;
11. the pick's node is destroyed (`0x00218180`, `~bNode`, flags 2).

`GetCarStatus` (`0x00187958`) is `*(int *)(this + type * 24)`, the
`CarStatus` record's first word, with no range test.

## PickTrackNumberForExpressGame (0x00216aa8)

It returns a 16-byte node by value: a `bNode` (next, prev) with the track
at 8 and the direction at 12. The port's `ExpressTrack` is the last two.

- With `TrackSelectedInConfigFile` 0 or more, that track, forwards.
- Otherwise, for each track from 0 to `HighestTrackNumber` (`gp-21944`)
  that `GetTrackInfo` has (0 never is), and each direction, forwards
  first: if `IsTrackUnlocked(info->SameAsTrackNumber, direction)` (the byte
  at 66), a node with `info->TrackNumber` (the byte at 65) and the
  direction is `bMalloc`'d (16 bytes, flags 0, pool 16) and appended to
  a list on the stack. The pick is `GetNode(bRandom(count))`, copied out, and the list
  is destroyed with its nodes (`0x00218110`).

`bRandom(int)` (`0x0025a488`) draws on `bDefaultSeed` (`gp-14472`). With
no track unlocked the count is 0 and the image's divide traps; the port
answers track 0 forwards there.

The seed is `SeedRandomNumber`'s (`0x0012ee30`), which `InitializeEverything`
runs after `InitJoylog` and before `LoadConfig`: `bGetTicker() + 0x12345678`,
logged to the joylog with `AddData(seed, 32, 0)`, or the joylog's own
(`GetData(32, 0)`) when one is replaying. Then `bSetRandomSeed(seed,
&bDefaultSeed)`. Until Session 44 the port never ran it, so `bDefaultSeed`
kept its 0x12345678 and every boot's Quick Race drew the same track and car
(track 31 backwards, car 37). main.c's `seedRandomNumber` is retail's, run
at the same point, and the log has `seed:`. The car's draw is
`GenerateRandomRideInfo`'s, on the same seed. Both draw only among the
unlocked tracks and the available cars, which on a fresh profile are few,
so two boots can still land on the same pair.

## The track locks

`IsTrackUnlocked(track, direction)` (`0x0024b760`) is 1 unless
`IsTrackAnEventReward` says the track is some event tree's reward, in
which case it is `EventTreeIsTrackUnlocked`. Both walk the event trees'
`bList` at `gp-16712`:

- `IsTrackAnEventReward` (`0x001ffaa8`): 1 at the first tree whose
  `EventTree::TrackIsAReward(track, direction)` (`0x001ff6c8`) is not 0,
  else 0;
- `EventTreeIsTrackUnlocked` (`0x001ffb18`): at the first tree that has it
  as a reward, 1 if `EventTree::IsTrackUnlocked(track, direction)`
  (`0x001ff5c8`) is not 0 and 0 if it is; 1 when no tree has it.

The trees are loaded from FRONTB's chunk `0x80034a00` by
`LoaderEventTree` (`0x001ffc40`). The port's are eventtree.c's
([event-tree](event-tree.md)), so a track the trees still have locked is
locked for Quick Race too; `is_track_unlocked` calls eventtree.c's
`is_track_an_event_reward` and `event_tree_is_track_unlocked_any`.

## Leaving the frontend (0x00168830)

`StartRace`'s `ChangeGameFlow(UNLOADING_FRONTEND)` runs
`BeginGameFlowUnloadingFrontEnd`: it waits for the render, unlaunches the
frontend's menus, closes the movie player and the Select Car screen,
unloads the CarLoader, the frontend's sounds, the car effects, the sound
regions, every frontend resource file (type 1), the languages and the
demo replay's file, refreshes the language text, cleans up the expanded
slot pools, waits out the async reads, and ends with
`ChangeGameFlow(LOADING_TRACK_COMMON, NONE)`. The port's
`bgf_begin_unloading_frontend` does the screen list's part and the
`closeSelectCar` and `unloadFrontEnd` hooks (main.c unloads FRONTB),
then changes to `LOADING_TRACK_COMMON`, which [track-flow](track-flow.md)
takes from there. `tools/bootflow_check.py`'s `leavefe` scenario checks
the change. The screen list's part is retail's `UnlaunchFrontendMenus`
([boot-flow](boot-flow.md)), which stops the menu's tune before the
loading screen; the race's own starts six seconds after GO
([jukebox](jukebox.md), "The race's music").

## What the race asks for next

A Quick Race from the frontend sets `TrafficDensity` 0.33, and Hot
Pursuit's sets 4 cops. Neither had been asked for before: the SkipFE race
(the shipped words: no traffic, no cops) never placed a traffic car. The
first Azahar run loaded the race and stopped at the first traffic car,
where `World::AddTrafficCar` aborted on the unported
`TrafficTeleporter::PlaceNewCar`. That seam then placed nothing when
NULL, as `AddCopCarToRace`'s does, so the race ran with its AI racers and
without traffic or cops. The traffic is now ported (11h,
[traffic-teleporter.md](traffic-teleporter.md)); the cops are step 12.

The race then stayed at COUNTDOWN, since nothing ended the countdown.
Race::Update (11g-2b, [race-update.md](race-update.md)) does: GO starts
the race, and the laps and the finish run.

The countdown was then drawn from 1100 m above the track:
`BeginCountdownCameras` removed the player's mover and, with no
`CountdownCameraCoordinator` ported, built nothing in its place. With
the coordinator ported (11g-2c-1,
[camera-coordinator](camera-coordinator.md)) the 3-2-1 is in the drive
camera, as on retail. Retail's race start before the countdown, the
Starting Grid over the fly-by camera and the pre-race camera, comes
next (11g-2c-2).
