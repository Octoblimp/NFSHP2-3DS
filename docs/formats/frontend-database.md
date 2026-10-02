# Fred, TheRaceParameters and the characters (step 8l-1)

Retail's frontend database (`Fred`, `0x002fc050`), the race parameters
(`TheRaceParameters`, `0x0031a898`) and the character data, as the boot
sets them up. `fred.c`, `raceparams.c`, `characterinfo.c` and
`edisplay.c` are the port, checked against the image by
`tools/fred_check.py`.

## When they run

| when | what | retail |
|------|------|--------|
| static init [34] | `_GLOBAL_$I$Fred`, FrontendDatabase's constructor | `0x00187c58`, `0x001836a0` |
| static init [73] | `_GLOBAL_$I$TheRaceParameters` | `0x001ee590` |
| InitializeEverything | LoadGlobalChunks, InitCarInfo, InitializeSoundDriver, then InitFred | `0x00183820` |
| BeginLoadingFrontEnd | RaceParameters::InitWithDefaults on TheRaceParameters | `0x001ed5c8` |
| a language chosen, not from the options | FrontendDatabase::InitWithDefaults again | `0x00183830` |
| NewMainMenu's constructor | MakeChallengeCarsAvailable, then RaceParameters::InitWithDefaults | `0x00183af8` |

InitFred is `j 0x00183830` with `a0 = Fred`. A memory card's save loads
over whatever InitWithDefaults left.

The static constructor [73] runs before LoadConfig and before the
LanguageManager's constructor [88], so its InitWithDefaults reads SkipFE
and CurrLanguage as 0. It draws one number from bDefaultSeed
(`0x00332068`, `0x12345678` on the disc), which leaves the seed at
`0x807d9be9`.

## FrontendDatabase

`0x114e0` bytes. The memory card saves it whole, so the port keeps the
image's offsets. `pUltimateState` is the image's word, not a host pointer.

| offset | member | default |
|--------|--------|---------|
| 0 | SomeStupidFieldForMemcard | |
| 4 | Autosave | 0 |
| 8 | ChallengeScreenData[5] (`0x001b5e10`) | 1, 3, 1, 1, 0 |
| 28 | MainMenuOpts[2] | 0, 1 |
| 36 | SingleRaceSetupData[7] (`0x001b8af0`) | 2, 2, 0, 1, 3, 0, 1 |
| 64 | BeTheCopSetupData[5] (`0x001b93e0`) | 2, 0, 1, 0, 1 |
| 84 | FreeRunSetupData[3] (`0x001b8ca0`) | 3, 0, 1 |
| 96 | RaceKnockoutSetupData[7] (`0x001b9218`) | 7, 0, 1, 3, 0, 0, 1 |
| 124 | LapKnockoutSetupData[6] (`0x001b8f38`) | 4, 0, 1, 3, 0, 1 |
| 148 | AudioOptionsScreenData, 176 bytes (`0x001ef1c8`) | the jukebox's |
| 324 | DisplayCalibrationData[2] (`0x001f4ad8`) | the current mode's screen offsets |
| 332 | DisplayOptionsData, tGlobalDisplaySettings | see below |
| 340 | SelectTrackScreenData[4] (`0x0019dd78`) | track 11's twin, 2, 0, track 11's time of day |
| 356 | SelectedEventData[4] (`0x001f5ce8`) | 0, 1, 1, 0 |
| 372 | SelectedLanguage | |
| 376 | DesiredControllerConfig[2] | 0, 0 |
| 384 | DemoModeStatus | |
| 388 | SavedSizeofFred | `0x114e0` |
| 392 | ChampionshipState, 256 bytes | 0 |
| 648 | HotPursuitState, 256 bytes | 0 |
| 904 | pUltimateState | 0 |
| 908 | TransientStatsTable, 812 bytes | |
| 1720 | ChallengeHighScores, 64000 bytes | InitStatsTables |
| 65720 | HighScoreNameTable, 1536 bytes | 0 |
| 67256 | RewardStates, 112 bytes | |
| 67368 | bRaceWasAborted | 0 |
| 67372 | GameType | 0 |
| 67376 | nCurrentEvent | 0 |
| 67380 | NumPlayerCars | 1 |
| 67384 | FrontendPlayers[2], 1744 bytes each | |
| 70872 | a new word | |
| 70876 | Checksum | |

A FrontendPlayerInfo is 64 CarStatus records of 24 bytes, the
CharacterInfo at 1536, the cPlayerSettings at 1604, eleven RideInfos at
1652 (one per game mode) and AccumulatedPoints at 1740.

A CarStatus is the status (0 available, 3 hidden) at +0, ten skin bytes
at +4, the number of skins offered at +16 and the dash flag at +20. The
count can pass ten; only ten bytes are kept.

### The constructor

`0x001836a0` only touches the members with constructors of their own:

- the first three bytes of each of the audio list's 32 entries (+28,
  four bytes apart) and the byte at 175;
- the eight stats' two Timers and their eleven lap Timers;
- every Time in both high score tables;
- for each player, every car's status 3 with no skins and no dash, both
  settings' records, and every game mode's ride type -1 with its four
  bytes 0.

### InitWithDefaults

`0x00183830`, in effect:

1. GameType 0, and each player's character by index: Rick for the first,
   Wayne for the second.
2. MakeChallengeCarsAvailable.
3. Each player's default car (gp-23136 and gp-23132, type 37) made
   available with its default skin (gp-23128 and gp-23124, 1) and the
   dash, then set as every game mode's ride. That ride has the dash only
   under SkipFE.
4. Both players' settings reset, their points 0, NumPlayerCars 1,
   Autosave 0 and SavedSizeofFred.
5. Each block's defaults, as in the table above, the audio options
   through the jukebox and the display options through
   tGlobalDisplaySettings'.
6. The display calibration's defaults first store the current offsets in
   gp-16896 and gp-16892, then in the block.
7. The championship and pursuit states, pUltimateState and the name table
   cleared, and InitStatsTables.
8. The two players' names: GetTranslatedString(`0x27165`) and
   (`0x27166`), bStrNCpy'd 11 bytes into the settings' name. A string
   with no translation is the image's "NOT TRANSLATED PROPERLY", cut to
   11 bytes with no terminator.
9. bRaceWasAborted 0.

### MakeChallengeCarsAvailable

`0x00183af8`. Each of the 64 car types with a geometry filename gets a
status and all its skins (SetCarAvailability with skin -1), and no dash.

For any game type but 7 (You're The Cop), both players get the same:

- available if IsCarUnlocked(type, GameType);
- otherwise its InitialLockStatus (+1340);
- in the E3 build (gp-23224), a hidden car stays hidden and the rest are
  available, except a cop (UsageType 1), which is hidden.

For game type 7, the first player gets the cops and the second the rest:

- the first player: anything but a cop is hidden; a cop is available if
  IsCarUnlocked(type, 7), otherwise its BeACopLockStatus (+1344);
- the second player: a cop is hidden; anything else is available if
  IsCarUnlocked(type, 3), otherwise its InitialLockStatus. The E3 build
  makes it available unless that status is hidden.

IsCarUnlocked (`0x0024b208`) asks the task, event and points rewards.
None of them is ported, so the port's seam answers 0 by default, which is
a new database's answer.

### The cars and skins

- **SetCarAvailability** (`0x001878e0`) stores the status, the dash flag
  and a 0 count. Skin -1 offers all the car's skins (`0x00187b08`):
  GetNumSkins of them, GetSkinNumber of each, the first ten kept and all
  of them counted. Any other skin is stored as a byte, with a count of 1.
- **GetSkinNumber** gives a cop skin 1, or 2 in any language but the
  first. Any other car gives `AvailableSkins[i % NumAvailableSkins]`.
- **BuildRideInfo** (`0x001879b8`) looks for the skin among the bytes
  from +4, as many as the count says, even past the ten kept. The skin is
  compared as a full word against each byte, so a skin above 255 never
  matches. With no match the first skin is taken. With a negative count
  the asked-for skin stands. The dash needs all three: asked for,
  offered, and a dash geometry filename (+128) on the car. The instance
  and vertex damage are 0.
- **AssignCarOfType** (`0x00187a68`) builds the mode's ride (+1652 +
  8 x mode), and **SetDefaultCarType** (`0x00187a78`) does all eleven.
- **SetCharacterInfo(int)** (`0x00187ce0`) copies GetCharacterInfo(i) in,
  68 bytes at +1536, and does nothing for NULL.

### InitStatsTables

`0x00186708`, on ChallengeHighScores:

1. The first pass walks tracks 1 to HighestTrackNumber that
   GetTrackInfo returns, that are valid and whose own number is their
   high score track (TrackNumber == SameAsTrackNumber). The first sixteen
   are numbered 0 to 15, and any after them get 0.
2. The second pass gives every other valid track its twin's index. The
   image reads the twin through NULL when GetTrackInfo has none. The port
   skips it.
3. Both tables are cleared, and every Time is set to `0x7fffffff`.

On the disc, the fifteen high score tracks are 11-13, 21-23, 31-33,
41-43 and 61-63, numbered 0 to 14. Each overcast, sunset or sunrise
version takes its daytime twin's index.

## TheRaceParameters

788 bytes, then the 14 DriverInfos at `0x0031abb0`. race.h has the
struct, and its per-field names are macros on it.

**InitWithDefaults** (`0x001ed5c8`) clears all 788 bytes, then sets:

- TrackNumber 11, TimeOfDay 3, TrafficOncoming 0.5 and TrafficDensity 1;
- start positions 7 and 8, two tickets before an arrest, Boost on with
  both scales 1;
- two laps, one player car and seven AI cars;
- NFSRaceMode, the four cop flags, the word at 624 and the reset after an
  arrest all 1.

It clears the driver table and points +772 at it with no drivers, resets
both player settings, sets the display settings' defaults, and draws +780
with bRandom(-1) from the default seed. The seed is the only thing it
changes outside the record.

**tGlobalDisplaySettings' defaults** (`0x001ee0a0`): under SkipFE, the
rear view, units, jump cams and zone cams are the low bytes of the SkipFE
words at gp-23168, gp-23152, gp-23144 and gp-23140. Otherwise the mirror
and both cams are on, and the units are 1 in any language but the first.
The three track map modes are 0, 7 and 8, and the leaderboard is 2.

**The static constructor** (`0x001ee590`) zeroes the Timers, runs
InitWithDefaults, then gives each DriverInfo rank 0 and a ride of type -1
with its four bytes 0.

The port's DriverInfo keeps the demo's field order (car.h), and its
character pointer is a host pointer. The checker prints the drivers by
field, not by byte.

## The characters

GLOBALB's chunk loader slot 22, LoaderCharacterInfo (`0x001d9330`),
handles two chunks:

| id | records | GLOBALB |
|----|---------|---------|
| `0x34301` | BodyTypeInfo, 180 bytes, at gp-17700 (count gp-17696) | 4: Male, Female, Cop, Cop3 |
| `0x34300` | CharacterInfo, 68 bytes, at gp-17692 (count gp-17688) | 10: Rick, Wayne, Mika, Ashley, Dom, Juan, Alexis, Liv, Cop, FatCop |

Either id answers 1, and any other id answers 0. The count is the chunk
size divided by the record size, unsigned. The unloader (`0x001d93b0`)
clears the pointer and the count.

The getters:

- GetBodyTypeInfo(char*) (`0x001d93f8`) and GetCharacterInfo(char*)
  (`0x001d9480`) return the first match by bStrICmp;
- `0x001d9508` returns the first character whose name's bStringHash
  matches;
- `0x001d9588` returns the count;
- GetCharacterInfo(int) (`0x001d9590`) returns NULL outside 0 to count-1.

bStrICmp folds lowercase letters only, so a prefix never matches.

## The display offsets

ScreenDisplayOffsets (`0x002c79c0`) holds an x and a y per video mode:
(56, 27) for mode 0 and (0, 0) for mode 1. CurrentVideoMode (gp-19612)
is 1 on the disc. eGetScreenDisplayOffsets (`0x00105728`) and the set
(`0x001056d8`) index it with GetVideoMode.

## The seams

| seam | retail | NULL means |
|------|--------|------------|
| `gIsCarUnlockedFn` | IsCarUnlocked, `0x0024b208` | 0, locked |
| `gFredTranslateFn` | GetTranslatedString(int), `0x0021e560` | "NOT TRANSLATED PROPERLY" |
| `gFredAudioOptionsDefaultsFn` | DataAudioOptionsScreen::InitWithDefaults, `0x001ef1c8` | the bytes are left |
| `gCurrLanguageFn` (cartypeinfo.h) | CurrLanguage, `0x0031c1c8` | 0, English |
| `gPlayerCamSkipFE` (playercam.h) | SkipFE, gp-23220 | 0 |

`main.c` sets the translation to the language table's strings and the
audio defaults to the jukebox's. It runs `init_fred` after the global
chunks load, as InitializeEverything does. The flow's three hooks are
`raceDefaults`, `frontendDefaults` and `challengeCars`, and they run
where BeginLoadingFrontEnd, the language screen and the main menu run
them in retail.

The image reads through NULL in two places, and the port reads 0
instead:

- InitStatsTables, for a track whose twin GetTrackInfo refuses;
- the track select's defaults, which read track 11 with no test.

## The checks

`tools/fred_check.py` runs the image's own code in RetailEmu: both static
constructors, InitFred and everything under it, MakeChallengeCarsAvailable,
the four FrontendPlayerInfo methods, InitStatsTables, RaceParameters'
defaults and the display settings', the character loader, unloader and
getters, LoaderTrackGeometry and the display offsets.

Three callees are stubs on both sides: IsCarUnlocked answers by a rule
the script sets, GetTranslatedString answers the script's strings, and
the audio defaults write a pattern. The harness, `tools/src/fred_test.c`,
runs the port over the same script.

The data are GLOBALB's own: 64 car records, 66 track records, four bodies
and ten characters. The scenarios then change those records field by
field, vary every global the defaults read, and start each record from a
fill pattern, so that a byte one side writes and the other leaves shows
up.

The checker has nine scenarios with 668 ops, and their 54344 lines show
0 differ. All 103 mutations are caught. Four of them needed scenarios
written for them:

- a dash asked for on a car whose dash geometry is there but not offered;
- both default cars of one type, with the first player's skin -1;
- a fallback string that differs within its first 11 bytes, since
  bStrNCpy keeps only 11;
- New784 set to something other than 0, since the memset already
  clears it.
