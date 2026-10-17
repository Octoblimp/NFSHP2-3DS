# NISes (step 12l-2)

A NIS is a short scene in the game's own engine. Hot Pursuit plays one
when a cop pulls the player over: the two cars posed side by side, the
cop walking up, the driver's hands on the wheel. There are eight on the
disc, five tickets and three arrests. Each one is a `.BIN` of animation
and a `.CAM` of cameras in `NIS/`. The HUD plays its camcorder overlay
over the scene ([hud-nis](hud-nis.md)), and the pullover that started it
ends when it does ([pullover](pullover.md)).

This page covers the table of NISes, the NisManager that times one, and
the Player methods that pick, start and stop it, along with the rest of
UpdateGameState. The port has them in `nisinfo.{c,h}`,
`nismanager.{c,h}` and `playernis.{c,h}`. `tools/nis_check.py` and
`tools/playernis_check.py` run retail's code against them.

The NIS player is not ported: loading the `.BIN` and `.CAM`, posing the
cars and the characters, animating them, and the NIS camera. So the port
plays a NIS for its time with the view still on the stopped car, under
the overlay (see "What the port shows" below).

| function | retail | port |
|---|---|---|
| LoaderNisInfo | `0x001b3358` | `loader_nis_info` |
| UnloaderNisInfo | `0x001b33a0` | `unloader_nis_info` |
| GetNumNisInfo(NisType) | `0x001b3490` | `get_num_nis_info` |
| GetNisInfo(int) | `0x001b3608` | `get_nis_info` |
| GetNisInfo(int, NisType) | `0x001b3638` | `get_nis_info_by_type` |
| NisManager::NisManager | `0x001b0fe0` | `nismanager_construct` |
| NisManager::~NisManager | `0x001b1110` | `nismanager_destruct` |
| NisManager::DoSnapshot | `0x001b11f8` | `nismanager_do_snapshot` ([replay](replay.md)) |
| NisManager::Start | `0x001b1318` | `nismanager_start` |
| NisManager::Stop | `0x001b1388` | `nismanager_stop` |
| NisManager::AllowDebugLooping | `0x001b13e8` | `nismanager_allow_debug_looping` |
| NisManager::Unload | `0x001b1658` | `nismanager_unload` |
| (Start's load check) | `0x001b16e0` | in `nismanager_start` |
| Player::PlayNextNis | `0x00176308` | `player_play_next_nis` |
| Player::ServiceNis | `0x00176530` | `player_service_nis` |
| Player::UpdateGameState | `0x00180c28` | `player_update_game_state` |
| Player::DetectWrongWay | `0x00181058` | `player_detect_wrong_way` |
| Player::CreateRandomNisArray | `0x00181a28` | `player_create_random_nis_array` |
| UpdatePlayersGameState | `0x00181de8` | `player_update_players_game_state` |
| Player::IsAllowedToReset | `0x00181e98` | `player_is_allowed_to_reset` |
| Player::ChooseToDisplayReset | `0x00181f68` | `player_choose_to_display_reset` |

Retail's ELF is stripped. The names are the demo's (its `.mdebug`), and
so are the field names.

## The table

GLOBALB.BUN carries one chunk of type `0x00037010` at `0x9fe80`: 1280
bytes, eight NisInfo records of 160 bytes. LoaderNisInfo (slot 20 of the
LoaderTable) keeps a pointer to the records where the bundle has them,
at chunk + 8, in `NisInfoTable` (gp-18844). It keeps the count, size /
160, in `NumNisInfos` (gp-18848). UnloaderNisInfo empties both.

The port gives GLOBALB's chunks to its loaders by hand, in `main.c`'s
`loadGlobalCarInfo`. Before 12l-2 that list did not have
`loader_nis_info`, so the table stayed NULL, every NIS was 0 frames long,
and a pullover's NIS ended the moment it began. The boot log's "car
data:" line now counts the NISes: 8.

| offset | field | |
|---:|---|---|
| 0 | `Name[32]` | "NIS_Ticket01" |
| 32 | `Type` | 1 ticket, 2 arrest |
| 36 | `ApplyDriverOffsets` | |
| 40 | `NisNumber` | its index in the table |
| 44 | `NumFrames` | at 30 a second |
| 48 | `NumCameras` | in its `.CAM` |
| 52, 56 | `PlayerAnimation`, `OtherAnimation` | name hashes |
| 64, 68 | `NumAllowable{Player,Other}BodyTypes` | |
| 80, 88 | `PlayerProps[2]`, `OtherProps[2]` | |
| 96, 128 | `Allowable{Player,Other}BodyTypes[8]` | |

| # | name | type | frames | cameras |
|---:|---|---|---:|---:|
| 0 | NIS_Arrest01 | arrest | 121 | 2 |
| 1 | NIS_Arrest02 | arrest | 154 | 3 |
| 2 | NIS_Arrest03 | arrest | 149 | 3 |
| 3 | NIS_Ticket01 | ticket | 141 | 3 |
| 4 | NIS_Ticket02 | ticket | 141 | 2 |
| 5 | NIS_Ticket03 | ticket | 141 | 3 |
| 6 | NIS_Ticket04 | ticket | 141 | 3 |
| 7 | NIS_Ticket06 | ticket | 141 | 3 |

There is no Ticket05 in the table, although `NIS/` has its files.

The three lookups:

- **GetNumNisInfo(type)** counts the records of that Type. It is 0
  without a table.
- **GetNisInfo(n)** is record n. It is NULL without a table, or when n
  is past the end. The compare is signed, so a negative n gets through
  in retail and in the port.
- **GetNisInfo(n, type)** is the n'th record of that Type, counting from
  0. It is NULL when there are not that many.

## The NisManager

Each player has one: 320 bytes, `bMalloc`ed in the Player constructor
and named "Player%d". The demo's layout names the fields. Retail added
the player's number at 32, which moves Name through
PlayerCarMovementModeBeforeNIS four bytes on, into the demo's hole at
108.

| offset | field | |
|---:|---|---|
| 0 | `Node` | on `NisManagerList` (gp-18840) |
| 12, 16, 20 | `LoadedNisNumber`, `LoadingNisNumber`, `LoadNisNumber` | -1 for none |
| 24, 28 | `NisResourceFile`, `CamResourceFile` | |
| 32 | `PlayerNumber` | retail's |
| 36 | `Name[32]` | |
| 68 | `Playing` | |
| 72, 76 | `StartTime`, `EndTime` | in WorldTimeFrames |
| 80 | `NisNumber` | -1 for none |
| 84 | `CamNumber` | |
| 88, 92 | `PlayerCar`, `OtherCar` | |
| 112 | `NisRendInfo` | 112 bytes |
| 224, 272 | `PlayerCharProps[2]`, `OtherCharProps[2]` | eModels |

- **Start(nis, camera, player, other).** StartTime is WorldTimeFrames,
  and EndTime is that plus twice the NIS's NumFrames. The table counts
  at 30 a second and WorldTimeFrames at 60, so a ticket lasts 282 world
  frames, 4.7 s. Retail reads the record untested; the port reads 0
  frames without a table. Playing goes to 1, and the NIS, the camera
  and the two cars are kept. Then comes the load check: Load when the
  NIS is not the loaded one, then EnsureNisIsLoaded. Then
  SetupCarsBeforeNIS and StartAnimating.
- **Stop.** While Playing: StopAnimating, RestoreCarsAfterNIS, and the
  record back to idle. The cars go NULL, the NIS and the camera -1, and
  Playing, StartTime and EndTime 0.
- **AllowDebugLooping** is always 0.
- **Unload** waits out a load (EnsureNisIsLoaded). Then, when a NIS is
  loaded, it unloads the two resource files and sets LoadedNisNumber to
  -1.

The NIS player's calls are seams that do nothing while NULL:
`gNisManagerLoadFn`, `gNisSetupCarsBeforeNisFn`, `gNisStartAnimatingFn`,
`gNisStopAnimatingFn`, `gNisRestoreCarsAfterNisFn`,
`gNisUnloadResourceFileFn` and `gNisServiceResourceLoadingFn`. With the
service seam NULL, EnsureNisIsLoaded's wait ends at once.

## The player's side

The Player keeps two shuffled lists of each type. TicketNisNumbers[32]
is at 248, TicketCameraNumbers at 376, ArrestNisNumbers at 504 and
ArrestCameraNumbers at 632. ArrestNisIndex is at 232, TicketNisIndex at
236, and the callback and its parameter are at 0 and 240.

- **CreateRandomNisArray(type)** runs twice in the Player constructor,
  once per type. The NisNumbers of the table's NISes of that type are
  drawn without repeats into the type's list. Each draw is
  bRandom(how many are left) on bDefaultSeed, counted through the ones
  not drawn yet. Each NIS's camera is bRandom(its NumCameras). A NIS the
  lookup misses would be the first ticket's. That cannot happen, since
  the lookup finds every one it counted, and the port skips the read of
  `pool[-1]` that retail would make.
- **PlayNextNis(car, cop, done, param)** keeps the callback and its
  parameter, then:
  1. reads the car's tickets from pCopManager;
  2. calls ClearZone(1) and RadialBlurOff for the cop's player's view;
  3. stops the car blinking and sets bResetGlare;
  4. raises both indices to at least 0.

  It is an arrest when the race is not a free run and the tickets have
  reached nNumTicketsBeforeArrest; otherwise it is a ticket. Either way
  the NIS and its camera are read at TicketNisIndex, the arrest's too.
  A camera that the other player's playing NIS is on moves to the next
  of the NIS's NumCameras. Then come NisManager::Start, the overlay's
  StartTicket or StartArrest, and, outside a replay, ChangeCameraMover(NONE)
  and CreateNisCameraCoordinator. A player without a NisManager plays
  nothing in the port, and the callback runs at once.
- **ServiceNis.** Once WorldTimeFrames reaches EndTime:
  1. outside a replay, the drive camera comes back;
  2. NisManager::Stop runs;
  3. the callback runs with its parameter, and then both are cleared;
  4. NisManager::Unload and the overlay's Finish run.

  For a pullover, the callback is EndPullover.
- **DetectWrongWay(was).** The car's Angle is compared with the track
  path's direction (bATan of its x and y), folded to 0..32768, with 1820
  more when `was` is set. Under 20024 (110 degrees) is the right way.
  Wrong and faster than 10 mph, forwards or backwards: the velocity's
  heading decides, wrong being `was` or else all four wheels down. Wrong
  and slower: `was`.
- **IsAllowedToReset.** Not in a zone that blocks requests (zones 6 and
  7 do not), not while a NIS plays, not above 60 mph, and in Be A Cop
  only from 5 s into the race.
- **ChooseToDisplayReset** is the trouble watch. LastTimeCarInTrouble is
  set to WorldTimer when either of these holds:
  - within 3 s of the car's last penetration, it is above 60 mph and
    yawing more than 50 degrees a second;
  - it was above 60 at the last half-second sample and is losing more
    than 70 mph a second.

  It is also set when the car is below 10 mph upside down. Five seconds
  on, it is let go. While it holds, with the car allowed to reset and
  not chased, it is let go unless TimeToDisplayResetPrompt is showing.
  Nothing in retail sets that, because the reset prompt was cut; this
  is what is left of it.
- **UpdateGameState** runs, in order:
  1. ServiceNis;
  2. the wrong-way flag (`bWrongWay`, which RealController and
     CarFinish read);
  3. the trouble watch;
  4. in a race or a replay, once a second, the car's speed over its
     driving line's speed into pAverageSpeedRatio, and its peak into
     fMaxSpeedRatio. The ratio is 1 off a line that is neither valid
     nor fake;
  5. the freeze zone's delay, counted down. When it runs out the zone is
     requested and, if given, PlayBustRoadBlock plays at the car.
- **UpdatePlayersGameState** runs each player by index, reading the
  count again each time. World's step calls it
  (`gUpdatePlayersGameStateFn`).

## What the port shows

`main.c` binds `gNewNisManagerFn`, `gDeleteNisManagerFn`,
`gNisManagerIsPlayingFn`, `gNisManagerStopFn`,
`gPlayerCreateRandomNisArrayFn`, `gPlayerPlayNextNisFn` and
`gUpdatePlayersGameStateFn`. Player::LoadNextNis (`0x001761e8`), which a
pursuit calls to load a NIS ahead of time (`gPlayerLoadNextNisFn`), is
the NIS player's and stays NULL. So does
`gNisCreateCameraCoordinatorFn`.

When a cop pulls the player over, the NisManager plays the NIS for its
time. The view keeps following the stopped car under the camcorder
overlay: REC blinking, the date and the time, the frame, and BUSTED!
shrinking in. The HUD is hidden. When the time is up, the drive camera
is already there, the pullover ends, and the car is put back on the road
blinking.

The race log's "race: player NIS" line, once a second, gives the
manager, Playing, the NIS and the camera, EndTime, the next index of
each kind, and the tickets so far.

## Where retail and the port differ

- Retail's ServiceNis and IsNisPlaying read pNisManager without a NULL
  test. The port tests it.
- Retail's Start reads NisInfoTable untested. The port reads 0 frames
  without one.
- CreateRandomNisArray's not-found path, which cannot be reached, would
  read `pool[-1]`. The port does not read it.

## The checks

- `tools/nis_check.py` runs the table's loader, unloader and lookups and
  the NisManager's calls against retail's: 17,748 ops, 40,372 lines, 0
  differ. Of its 97 mutations, 96 are caught. `n_null` is equivalent:
  NumNisInfos is 0 whenever NisInfoTable is NULL, so the loop does not
  run.
- `tools/playernis_check.py` runs the eight Player functions and 40 races
  of them in sequence: 173,532 ops, 89,260 lines, 0 differ. Of its 150
  mutations, 147 are caught. Three are equivalent:
  - `k_half`: the only case left between 32767 and 32768 as the fold's
    edge is 32768 itself, which folds to 32768;
  - `c_fallback`: the lookup finds every NIS it counted;
  - `d_hit3`: no whole number of 0.00025 ticks makes 3.0f exactly.
- Azahar (2026-10-09), a Hot Pursuit quick race on track 26. The cop
  caught the stopped car, NIS_Ticket04 played on camera 1 for 282
  world frames under the overlay, and the race went on with one ticket.
