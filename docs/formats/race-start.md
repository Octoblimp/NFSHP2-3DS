# The race start (step 8l-2)

How retail turns the frontend's choices into a race's drivers:
StartSkipFEGame, StartRace, SetupCarsForRace and what they call, and the
RaceParameters methods under them. `fredrace.c` and the new half of
`raceparams.c` are the port, checked against the image by
`tools/fredrace_check.py`.

## Who calls it

| caller | retail | when |
|--------|--------|------|
| main | `0x0012f000` | SkipFE set: StartSkipFEGame on Fred in place of ChangeGameFlow(LOADING_FRONTEND) |
| SelectTrackScreen's StartRace | `0x001a0918` | the frontend's track select (not ported) |
| car select's MaybeContinueToNextScreen | `0x00198b64` | the frontend's car select (not ported) |

Retail's `main` is InitializeEverything, then that one test, then
MainLoop on its own stack. SkipFE (gp-23220) comes only from a joylog's
config items (LoadConfigItems, `0x0012faf0`, channel 32). Nothing else on
the disc sets it, and DemoDiscManager::Init clears it only on the demo
disc.

SkipFE is read in more places than `main`. InitFred and
cPlayerSettings::ResetToDefaults read it, so it has to be set before
InitFred runs. The other readers are BeginGameFlowLoadingTrackCommon,
Part3 (no PRERACEANIM), RaceCoordinator::InitForRace, the POV cycle, two
AICarController methods and tCopManager's speed-trap spawn time.
BeginGameFlowUnloadingTrackSpecific clears it.

### The port's switch

The port reads no joylog. Instead, `main.c` reads the pad once, right
after `bgf_init` and before InitFred, and holding R sets the flow's
`skipFE`, the word `gPlayerCamSkipFE` and `config_skip_fe()` read. The
boot then calls `fred_start_skip_fe_game(&Fred)` and logs the drivers
it built. Azahar's keyboard profile puts R on W.

## StartSkipFEGame (`0x00184bd8`)

It fills TheRaceParameters from the SkipFE words (configitems.h), as
shipped:

| field | from | shipped |
|-------|------|---------|
| TrackNumber | TrackSelectedInConfigFile, 12 when that is -1 | 12 |
| TrackTimeOfDay | 3 | |
| TrafficDensity, TrafficOncoming | SkipFETrafficDensity, SkipFETrafficOncoming | 0.0, 0.5 |
| RaceType | SkipFERaceType | 1 |
| NumLapsInRace | SkipFENumLaps | 8 |
| NumPlayerCars (and the argument's) | SkipFENumPlayerCars | 1 |
| NumAICars | SkipFENumAICars | 0 |
| nMaxCops | SkipFEMaxCops | 0 |
| bTickets, bRoadBlocks | SkipFETickets, SkipFERoadBlocks | 1, 1 |
| bHelicopter (+620), bSpikeStrips (+616) | gp-23188, gp-23184 | 1, 1 |
| New624 | gp-23180, retail's new word | 1 |
| TrackWeather, TrackDirection, EventTreeRace | 0 | |
| BeACop | SkipFEBeACop | 0 |
| TimeTrialTime | 1200000.5f as an int, only for a cop | |
| PlayerStartPosition[0], [1] | the AI count plus 1 and plus 2, as bytes | 1, 2 |
| both players' DriveCameraPOVIndex | PlayerSkipFEPOVIndex | |
| OpponentStrength, CopStrength | SkipFEDifficulty | 0 |
| BoostScale[0], [1] | TheDifficultyInfo's AINonExplicitMode BoostScale[difficulty][class], by the class of DefaultPlayer1CarType and DefaultPlayer2CarType | |

Then it jumps into StartRace on the global Fred, not on its argument.

## StartRace (`0x00184f68`)

1. GameType 4 (the challenge knockout): TheRaceEvent's player count
   (+118) takes NumPlayerCars, and SetupFakeRaceEventForChallengeKnockout
   (`0x001849f0`) runs.
2. UseTheRaceEvent (`0x001841a8`, GameTypes 4, 8 and 9): ResetState unless
   GetStatus answers 2. Otherwise the player count takes NumPlayerCars.
3. With the race event: EventTrack::SetRace on track
   `GetRaceIndex % NumTracks` (+112). The image divides with no test, and
   traps on an event with no tracks, so the port skips the call there. A
   knockout (type 3) past its first race takes both players' starting
   positions from GetKoState. A tournament (type 4) with status 2 takes
   the first player's from UserRank.
4. The event's word (+120) is 0, or with the race event the current
   event tree event's word (`0x00200f98`). A NULL tree leaves 0.
5. Boost: a challenge (GameTypes 3 to 7, IsChallengeGame `0x001855f0`) or
   GameType 2 gives each player BoostScale[OpponentStrength][class]. A
   GameType 1 that is not an event game sets both scales to 1.0.
6. NumAICars is capped at MaximumNumAICars (gp-23112, 7), then at 8 less
   the players.
7. Point2Point is set when the track's TrackInfo says so.
8. SetupCarsForRace.
9. The display settings come from Fred's DisplayOptionsData, and both
   players' settings from Fred's two FrontendPlayerInfos.
10. An event game (GameTypes 8 and 9) whose driver 0 has a dash gets POV
    index 3.
11. SetRecordTimesToBeat for each player. ChooseHudTextures
    (`0x001ee388`) is an empty function.
12. MaybeSetSelectedCarForMultiTrackEvent, then TheDemoModeReplay's
    restore and unload when its first word is set.
13. EventTreeRace is set for GameTypes 8 and 9. New784 takes the count
    of unlocked reward cars (`0x001ff978`).
14. ChangeGameFlow(UNLOADING_FRONTEND, NONE) from IN_FRONTEND, and
    ChangeGameFlow(LOADING_TRACK_COMMON, NONE) from any other state.
15. bRaceWasAborted is cleared.

## SetupCarsForRace (`0x00185690`)

1. The eliminated drivers come back (`0x001edc50`). bDefaultSeed is
   seeded from New780. The character list is 0 to 7.
2. Players, AI and cops are capped at 8 by cutting cops, never below 0.
   The driver table is cleared.
3. **The players** (unless AIDemoMode). Each takes the first free
   character of its gender (cPlayerSettings' New7). The first player of
   a Be-the-Cop race takes the track's cop character instead. The
   player's selected ride, for Fred's GameType, is marked
   vertex-damageable. The driver's number is the player's index, its
   skill is -2 and its grid slot is PlayerStartPosition. A knockout's
   eliminated driver (RaceEvent::DriverEliminated) takes its rank and is
   left out of NumPlayerCars.
4. **The class range.** In an AI demo it is one random class from 0 to
   4. With one player it is that player's car class. With two it runs
   from the lower class to the higher.
5. **The AI racers**, numbered from 100, each on the next free character
   of any gender:
   - an event game's opponent (OpponentSelect 2) is the event's record:
     type, skin (an unused one when negative) and skill;
   - otherwise the skill is a draw against TheDifficultyInfo's
     SkillLevelDistribution[no cops][OpponentStrength], 10 cumulative
     weights, 0 when none passes;
   - ForceAllAICarsToBeThisType (gp-23116), or OpponentSelect 1 (the
     first player's car), gives a car of that type with an unused skin;
   - otherwise up to 500 attempts. Each draws a ride of the lowest class
     first, then the highest, then random ones in the range, falling back
     to any class. It redraws (up to 1001 times) while the race would draw
     six models or more (`0x001ede08`). The first 100 attempts reject a
     car type already racing, and the first 200 a colour already racing.
6. **The traffic**: six cars numbered from 50, or none when
   TrafficDensity is 0.001 or less. Each tries up to 100 traffic draws
   for a type not yet racing, with skin -1, no character and skill -1.
7. **The cops**, numbered from 10, each on the track's cop character.
   Each drives the cop car with geometry whose class is nearest the
   lowest class racing so far (traffic included, never above 5). The
   first such car wins a tie. With no cop car the type is -1. Skin 1.
8. CalculateStartingPositions.

### What it calls

- **GenerateRandomRideInfo** (`0x00188218`) inlines CarTypeInfoIterator
  (`0x00189130`). It walks the cars of the usage that have geometry, are
  of the class (unless -1) and have a skin, and sums their LocationProb
  for the race's location (GetLocationIndex `0x001eddd8`: track / 10
  less 1, 4 for the sixth). A sum of 0.001 or less answers 0 and leaves
  the ride. Otherwise it draws bRandom(sum) and walks again until the
  draw runs out. The ride gets that car's type, GetRandomSkin and three
  0 flags. A track below 10 has location -1, and the image reads the
  word before the five weights.
- **GetRandomSkin** (`0x00188460`): a cop's is GetSkinNumber's first, a
  car with no skins answers 0, and the rest draw one of AvailableSkins
  on bDefaultSeed.
- **PickCharacterNumberThatIsntRacing** (`0x001840a0`): the first entry
  that is not -1 and fits the gender. -1 fits any; otherwise 0 is a body
  named "MALE" (bStrICmp) and 1 is any other. The entry is taken (set to
  -1). It answers 0 when none fits.
- **PickCopCharacterNumber** (`0x00185640`) ignores its argument. It
  looks up the character by TheRaceParameters' track's
  CopCharacterNameHash, or by "Cop" when that is 0, and answers -1 when
  no character has that hash.
- **AreThereAnyCarsOfType** (`0x00183ed0`) and **OfColour**
  (`0x00183f68`) look at drivers still in the race. Colour compares
  GetSkinInfo's PaintType, with the table's first skin standing in for a
  missing one.
- **The unused-skin pick** (`0x00184018`): up to 100 random skins until
  one's colour is not racing. The last drawn wins either way.
- **DriverInfo's constructor** (`0x00188610`) runs the ride's own
  constructor (type -1, four 0 bytes), then copies the ride over it. It
  sets the number, type, character, GetCharacterInfo (NULL out of range),
  skill and grid slot, with rank 0.
- **RideInfo::Init** (`0x00187dd0`): type, skin, dash, vertex damage,
  instance 0.

### The RaceParameters methods

| method | retail | what |
|--------|--------|------|
| AddDriverInfo | `0x001eda40` | copies onto the table while it has fewer than 14; looks up the ride's SkinInfo and drops it |
| GetDriverInfoByDriverNumber | `0x001edb40` | first by number, or NULL |
| restore the eliminated | `0x001edc50` | rank above 0 back to 0, and the player or AI count up one |
| eliminate | `0x001edbc8` | a driver still in goes out at the rank, and its count down one |
| too many models | `0x001ede08` | see below |
| GetLocationNumber, GetLocationIndex | `0x001eddb8`, `0x001eddd8` | |

The model count runs over each driver still in, then the new ride, and
skips traffic. A vertex-damageable ride always counts. Any other counts
when no earlier driver (still in, and not vertex-damageable) has the same
CompressedGeometryFilename. Six or more is too many. For the new ride's
turn the image reads the table one record past its end, and skips the
ride when that stale record has a rank.

## CalculateStartingPositions (`0x00185fe8`)

With the race event, the event's own (`0x002022c0`) runs first. Then
every player and AI racer still in with no grid slot is ranked by how
quickly its car pulls away: the torque curve's highest point (of nine)
over the mass, times first gear's ratio (`GearRatios[2]`: the index is
the Gear enum, with reverse and neutral first), times the rear axle's
final drive (`FinalDrive[1]`), over the rear wheel's radius
(`Wheels[3]`). Ranking is
n passes of a bubble sort, quickest first, and equal cars keep their
order. Each in turn takes the lowest slot from 1 that no driver holds, or
9 when 1 to 8 are all taken.

## The records

SetRecordTimesToBeat (`0x00184490`) gives a player's settings in
TheRaceParameters the challenge table's best total time (only when the
race has laps) and best lap. The table is indexed by track, the class of
the player's car, direction and laps. The ride is the database's
FrontendPlayerInfo, but for the global Fred's GameType. `0x001842a8`
does it for each player.

| index | retail | value |
|-------|--------|-------|
| GetUniqueTrackIndex | `0x001868a0` | the TrackInfo's HighScoreIndex, 0 for a missing or invalid track |
| GetUniqueLapIndex | `0x001868d8` | place in 1, 2, 3, 4, 5, 6, 7, 8, 10; 0 for any other |
| GetTotalTimesIndex | `0x00186938` | track * 450 + laps * 5 + (direction != 0) * 45 + class * 90 |
| GetLapTimesIndex | `0x001869d0` | track * 50 + class * 10 + (direction != 0) * 5 |

## The seams

The race events and the event trees are not ported. StartRace and
SetupCarsForRace reach them only for GameTypes 4, 8 and 9, and only an
event game's opponents read a tree. The four words of TheRaceEvent
(`0x0031b600`) the other game types touch are `TheRaceEventFields`: type
(+106), track count (+112), player count (+118) and the event's word
(+120).

| seam | retail | NULL means |
|------|--------|------------|
| `gSetupFakeRaceEventForChallengeKnockoutFn` | `0x001849f0` | nothing |
| `gRaceEventGetStatusFn` | `0x00202658` | 0 |
| `gRaceEventResetStateFn` | `0x00202698` | nothing |
| `gRaceEventGetRaceIndexFn` | `0x00202010` | 0 |
| `gEventTrackSetRaceFn` | `0x001fec20` | nothing |
| `gRaceEventKoStartPositionFn` | `0x00200598` on GetKoState | 0 |
| `gRaceEventTournamentUserRankFn` | `0x00200768` on GetTournamentState | 0 |
| `gFredEventWordFn` | `0x00200f98` on the tree's event | 0 |
| `gRaceEventDriverEliminatedFn` | `0x00201708` | not eliminated |
| `gRaceEventEliminatedRankFn` | GetRank on GetKoState | 0 |
| `gRaceEventStartingPositionsFn` | `0x002022c0` | nothing |
| `gFredEventOpponentFn` | the event's opponent record | four 0 bytes |
| `gFredMaybeSetSelectedCarForMultiTrackEventFn` | `0x00184318` | nothing |
| `gDemoModeReplayStartRaceFn` | TheDemoModeReplay's restore and unload | nothing |
| `gEventRewardCarsUnlockedFn` | `0x001ff978` | 0 |
| `gFredGameFlowStateFn` | CurrentGameFlowState, gp-21420 | state 0 |
| `gFredChangeGameFlowFn` | ChangeGameFlow, `0x001680d8` | nothing |

`main.c` sets only the last two, to the flow's current state and
`bgf_change_state(state, BGF_NONE)`.

Where the image reads past what it has, the port reads something safe
instead:

- a CarTypeInfo for any type, -1 too (1376 bytes before the array). The
  port gives a type outside 0 to 63 class 5, no model and no pull;
- the word before LocationProb for a track below 10, which the port's
  record holds too;
- the body name of a NULL CharacterInfo, which the port takes as fitting
  no gender;
- the divide by an event's track count of 0.

## Not ported here

Retail's BeginGameFlowUnloadingFrontEnd (`0x00168830`), the state
StartRace asks for from the frontend, waits for the frontend's own way
into a race. Before ChangeGameFlow(LOADING_TRACK_COMMON) it calls:

- eWaitUntilRenderingDone and UnlaunchFrontendMenus (`0x0016fa80`,
  changed from the demo's);
- CloseMoviePlayer, CloseSelectCarScreen and CarLoader::UnloadEverything
  (new in retail);
- UnInitFrontendSounds, CloseCarEffects and UnLoadSoundRegions;
- every type 1 ResourceFile's unload, then UnloadAllLanguages;
- DemoModeReplay's UnloadResourceFile and FlailerUpdateLanguageText (new
  in retail);
- CleanupExpandedSlotPools, and a wait on bIsAsyncDone;
- the green-flash leak check against gp-21448.

UnlaunchFrontendMenus pops the stack by GameType. It also stops the
jukebox, the movie, the song monitor and the help menu, and sets
FrontendLaunchType for the way back. The SkipFE path never enters this
state. The frontend's Quick Race does, and the port's
`bgf_begin_unloading_frontend` runs UnlaunchFrontendMenus as retail's
(`boot-flow.md`).

## The checks

`tools/fredrace_check.py` runs the image's own code in RetailEmu:
StartSkipFEGame, StartRace, SetupCarsForRace and
CalculateStartingPositions with all their helpers, SetRecordTimesToBeat
and the four indexes, RaceParameters' methods, and under them bRandom,
the skin and track getters, the character lookups and the string
compares. InitFred, RaceParameters' defaults, LoaderCharacterInfo and
LoaderTrackGeometry set the scene.

The race events, the event trees, the replay, the reward cars and
ChangeGameFlow are stubs on both sides. Each prints its call, and the
script sets what it answers. The harness, `tools/src/fredrace_test.c`,
runs the port over the same script.

The data are GLOBALB's: 64 cars, 235 skins, 66 tracks, the characters
and TheDifficultyInfo. The scenarios change them field by field: cars
without geometry or skins, other classes and usages, location weights
moved, paint types, cop characters and records. The race parameters,
Fred, a second database, the driver table and the SkipFE words vary
around them. Each record starts from a fill pattern.

The checker has 8 scenarios, 2527 ops and 50503 lines, with 0 differ.

```bash
python tools/fredrace_check.py
python tools/fredrace_check.py --mutate [--only a,b]
```

Of its 217 mutations, the first full pass caught 200. A scenario of
their own, `s_holes`, took in the other 17, and a rerun of those 17
caught 16. The last, `cp_pos1`, is equivalent. The driver being placed
keeps slot 0 until it is given one, so the search for a free slot never
stops at 0.

On Azahar, `tools/run_azahar_race.ps1` holds R through the boot. The log
reads:

```
SkipFE: R held at boot
flow want LOADING_TRACK_COMMON
race start: track 12, 8 laps, race type 1, 1 player, 0 AI, 0 cops, 1 drivers
  driver 0: type 1, car 37 skin 1, character 0, skill -2, grid 1
flow state LOADING_TRACK_COMMON
flow begin LOADING_TRACK_COMMON
```

The flow goes from NONE to LOADING_TRACK_COMMON and runs its Begin. It
then stays on LOADING at 60 fps. By the code, Part1 asks the car loader
for car 37's skin. LoadTexturesFromFile is still a NULL seam, so the load
never calls back (8l-3). Nothing logs that step. A boot without R walks
the frontend as before.
