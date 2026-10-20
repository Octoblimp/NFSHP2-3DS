# The cheat codes

The PS2 game's cheat codes: eight presses on the main menu, and the
menu says "Unlocked" and what. The reader is retail's alone. Its class has
no name in the ELF and none on the demo disc, so the port calls it
TheEasterEggs, after its LanguageIDs' strings. Ported in `eastereggs.c`
(TASKS 50); `tools/eastereggs_check.py` runs it beside retail's code.

## The object

One object, at `0x0031d7e8`, 64 bytes, built by retail's static
constructor `0x0024fa60` (the image's `__CTOR_LIST__` entry 99 of 111;
the demo's list has none). The port builds it in `main.c` right after
`sinit_run`, which follows the demo's list.

| off | field | what |
| --- | --- | --- |
| 0 | Active | the reader's switch |
| 4 | JustEntered | 1 from a match until the main menu takes it |
| 8 | LanguageID | the last match's name |
| 12 | Codes | the table, `0x0031d828` |
| 16 | NumCodes | 78 |
| 20 | Ring[8] | the last presses, as JoyEvents |
| 52 | Count | how many of the ring are presses |
| 56 | Head | the oldest's slot |
| 60 | vptr | `0x002bf470` |

A code is 56 bytes: its eight presses (JoyEvents), then Type, Param,
Group, LanguageID, On and Kept, a word each. Every On is 0 on the disc.

## The calls

| retail | port | what |
| --- | --- | --- |
| `0x0024f420` | `eastereggs_construct` | the vtable, the table and its count; the rest 0 |
| `0x0024f488` Start | `eastereggs_start` | a handler (`0x0024fa88`) for JoyEvents 133 to 148 on port 0, then JustEntered and LanguageID 0, Active 1, and the ring emptied |
| `0x0024f610` Stop | `eastereggs_stop` | the sixteen handlers removed; Active, JustEntered and LanguageID 0; the ring emptied |
| `0x0024f748` | `eastereggs_on_button` | a press (below) |
| `0x0024f8f0` | `eastereggs_reset` | Count 0 |
| `0x0024f700` | `eastereggs_clear_temporary` | every code not Kept goes off |
| `0x0024f9f8` | `eastereggs_clear_group` | every code of the group goes off; group 0 is no group |
| `0x0024f9a0` | `eastereggs_is_on` | the On of the first code with that Type and Param, else 0 |
| `0x0024f8f8` | `eastereggs_car_on` | `is_on(cop ? 2 : 1, car)` |
| `0x0024f930` | `eastereggs_track_on` | `is_on(backward ? 4 : 3, track)` |
| `0x0024fa70` | `eastereggs_egg_on` | code n's On, unchecked |
| `0x0024faa8` | `eastereggs_take_language_id` | LanguageID, JustEntered cleared |
| `0x0024fab8`, `0x0024fac0` | `eastereggs_just_entered`, `eastereggs_is_active` | the words |
| `0x0024fac8`, `0x0024fad8` | `eastereggs_enable`, `eastereggs_disable` | Active 1 or 0 |
| `0x0024fa48` | none | a type-0 code's action: empty |
| `0x0024f968` | none | a loop over the codes that does nothing; NewMainMenu's OnTick calls it when gp-16120 is set |

## A press

The handler takes `(port, event, value, object)` and passes the value as
a byte; the press does not read the port or the value.

1. Nothing while Active is 0.
2. A ring that already holds eight (only a Count poked to 8 or more, as
   unsigned) is emptied, and the press dropped.
3. The press goes in slot `(Head + Count) & 7`, and Count goes up.
4. At eight, each code in turn is compared with slots `(Head + j) & 7`.
   The first that matches wins: its group goes off, then it comes on,
   JustEntered is 1, LanguageID is its own, and the ring empties (Head
   stays where it is).
5. With no match, Head steps to `(Head + 1) & 7` and Count goes back to
   seven: the oldest press drops out.

So a code is the last eight presses, whatever came before them.

## Who calls it

| caller | what |
| --- | --- |
| NewMainMenu's constructor `0x00216550` and destructor `0x002165b4` | Start and Stop |
| NewMainMenu::OnTick `0x00216718` | the reader off while the help is up (`tHelpMenu::IsActive`), on otherwise; a code just entered resets the idle timer, makes FrontendSound 30, shows group `0x74e404b4` ("Unlocked") with the code's LanguageID in object `0xf58c1a4b`, and hides it three seconds on |
| BeginGameFlowUnloadingTrackSpecific | ClearTemporary, after every race |
| VisibleCarSet's constructor `0x001945bc` | a car whose code is on is available |
| SelectableTrackManager::BuildList `0x0019e588`, `0x0019e658` | a track whose code is on is unlocked, each way |
| Player n = 4, InitCars and Chopper's constructor n = 5, EventInfo::GetStatus n = 6 and 7 | `egg_on` (`gEggIsOnFn`, `raceinit.h`) |
| SetRenderEggFromEasterEggs `0x0024bf18` | eggs 0, 1, 2, 3, 4 and 8, the render eggs (TASKS 50b) |

`gameflow.c`'s `mainMenuTick` has OnTick's half, through three hooks
(`easterEggsActive`, `easterEggEntered`, `helpActive`); `main.c` binds them
and car select's and track select's `eggActive`.

Nothing is saved. A code that is not Kept goes off after the next race;
the rest stay on until the game is switched off.

## The keys

The reader's events are retail's scanners 214 to 229
(`scannertab.c`), `Scanner_DigitalDown`, so a press counts once. Only 133
to 140 are in codes. On the main menu joyhid's frontend layout holds,
which swaps B and X:

| event | PS2 | 3DS |
| --- | --- | --- |
| 133 | L1 | L |
| 134 | L2 | ZL |
| 135 | R1 | R |
| 136 | R2 | ZR |
| 137 | D-pad left | D-pad left |
| 138 | D-pad right | D-pad right |
| 139 | Square | X |
| 140 | Triangle | B |

B is the menus' back, but BACK on the main menu goes nowhere (retail's
Param 0), so a code can use it.

## The codes

Types: 0 an egg (its own number in Param), 1 a car in car select, 2 a cop
car in You're The Cop, 3 a track, 4 a track backward ("II"). The names are
the LanguageIDs' English. Code 5 has no presses (every event 0), so
nothing can enter it; the port's `ForceChopper` config key turns it on in
a SkipFE race instead.

| # | unlocks | PS2 | 3DS | type, param | group | kept |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | Motion Blur | L2 L1 R1 Square R1 R1 R1 L1 | ZL L R X R R R L | egg 0 | 1 | no |
| 1 | Black & White | R1 L1 Left Triangle Left Left Left L1 | R L Left B Left Left Left L | egg 1 | 1 | no |
| 2 | Heavy Fog | Triangle Square Right R2 Right Right Right Square | B X Right ZR Right Right Right X | egg 2 | 1 | no |
| 3 | R/C Car | Right Triangle L1 R1 L1 L1 L1 Triangle | Right B L R L L L B | egg 3 | 1 | no |
| 4 | Video Mode | L1 R1 Right Square Right Right Right R1 | L R Right X Right Right Right R | egg 4 | 1 | no |
| 5 | Pet Helicopter | none | none | egg 5 | 0 | no |
| 6 | Championship Bonus Event | L1 Square R2 R2 R2 R1 L1 Square | L X ZR ZR ZR R L X | egg 6 | 0 | yes |
| 7 | Ultimate Racer Bonus Event | Right Square Left Left Left R2 Right Square | Right X Left Left Left ZR Right X | egg 7 | 0 | yes |
| 8 | Chrome Cars | L2 R2 Left Square Left Left Left R2 | ZL ZR Left X Left Left Left ZR | egg 8 | 0 | no |
| 9 | McLaren F1 | Triangle L1 Triangle L1 R1 Left R1 Left | B L B L R Left R Left | car 7 | 0 | yes |
| 10 | McLaren F1: NFS | Left Triangle Triangle Triangle L2 Square Square Triangle | Left B B B ZL X X B | car 8 | 0 | yes |
| 11 | McLaren F1 LM | Square L1 Square L1 Triangle Right Triangle Right | X L X L B Right B Right | car 9 | 0 | yes |
| 12 | McLaren F1 LM: NFS | R1 Square Square Square R2 Left Left Square | R X X X ZR Left Left X | car 10 | 0 | yes |
| 13 | Mercedes CLK-GTR | R2 R1 R2 R1 Left Triangle Left Triangle | ZR R ZR R Left B Left B | car 5 | 0 | yes |
| 14 | Mercedes CLK-GTR: NFS | Triangle Left Left Left L1 L2 L2 Left | B Left Left Left L ZL ZL Left | car 6 | 0 | yes |
| 15 | Chevrolet Corvette Z06 | Left R2 Left R2 L1 R1 L1 R1 | Left ZR Left ZR L R L R | car 0 | 0 | yes |
| 16 | Chevrolet Corvette: NFS | Square Right Right Right R2 R1 R1 Right | X Right Right Right ZR R R Right | car 1 | 0 | yes |
| 17 | Dodge Viper GTS: NFS | L1 L2 L2 L2 Right Triangle Triangle L2 | L ZL ZL ZL Right B B ZL | car 3 | 0 | yes |
| 18 | Ferrari F50 | L1 Triangle L1 Triangle Right L2 Right L2 | L B L B Right ZL Right ZL | car 23 | 0 | yes |
| 19 | Ferrari F50: NFS | Triangle L1 L1 L1 Left Right Right L1 | B L L L Left Right Right L | car 24 | 0 | yes |
| 20 | Lamborghini Diablo 6.0 VT | Right R2 Right R2 R1 L1 R1 L1 | Right ZR Right ZR R L R L | car 45 | 0 | yes |
| 21 | Lamborghini Diablo: NFS | Square R2 R2 R2 Triangle R1 R1 R2 | X ZR ZR ZR B R R ZR | car 46 | 0 | yes |
| 22 | Lamborghini Murcielago | R1 L2 R1 L2 L1 Right L1 Right | R ZL R ZL L Right L Right | car 47 | 0 | yes |
| 23 | Lamborghini Murcielago: NFS | L1 R2 R2 R2 Left Square Square R2 | L ZR ZR ZR Left X X ZR | car 48 | 0 | yes |
| 24 | Porsche 911 Turbo: NFS | Right Left Left Left Triangle R1 R1 Left | Right Left Left Left B R R Left | car 40 | 0 | yes |
| 25 | Porsche Carrera GT | Left Right Left Right R1 R2 R1 R2 | Left Right Left Right R ZR R ZR | car 17 | 0 | yes |
| 26 | Porsche Carrera GT: NFS | R2 Triangle Triangle Triangle R1 Square Square Triangle | ZR B B B R X X B | car 18 | 0 | yes |
| 27 | Aston Martin V12 Vanquish | R2 Right R2 Right Triangle Left Triangle Left | ZR Right ZR Right B Left B Left | car 29 | 0 | yes |
| 28 | V12 Vanquish: NFS | Square Left Left Left R1 R2 R2 Left | X Left Left Left R ZR ZR Left | car 30 | 0 | yes |
| 29 | BMW Z8 | Square Right Square Right R2 Triangle R2 Triangle | X Right X Right ZR B ZR B | car 20 | 0 | yes |
| 30 | Ferrari 360 Challenge | Left Square Square Square R1 L2 L2 Square | Left X X X R ZL ZL X | car 22 | 0 | yes |
| 31 | Ferrari 360 Spider | R2 Square R2 Square Triangle L2 Triangle L2 | ZR X ZR X B ZL B ZL | car 21 | 0 | yes |
| 32 | Ferrari 550 Barchetta | L1 Square L1 Square Right R1 Right R1 | L X L X Right R Right R | car 25 | 0 | yes |
| 33 | Ferrari 550 Barchetta: NFS | Square R1 R1 R1 R2 Left Left R1 | X R R R ZR Left Left R | car 26 | 0 | yes |
| 34 | Mustang Cobra R: NFS | R1 Right Right Right Left R2 R2 Right | R Right Right Right Left ZR ZR Right | car 12 | 0 | yes |
| 35 | HSV Coupe GTS | L1 L2 L1 L2 R1 Triangle R1 Triangle | L ZL L ZL R B R B | car 15 | 0 | yes |
| 36 | HSV Coupe GTS: NFS | Right L2 L2 L2 L1 Left Left L2 | Right ZL ZL ZL L Left Left ZL | car 16 | 0 | yes |
| 37 | Jaguar XKR: NFS | L1 Right Right Right L2 R1 R1 Right | L Right Right Right ZL R R Right | car 28 | 0 | yes |
| 38 | Ford TS50 | Right Left Right Left R2 Square R2 Square | Right Left Right Left ZR X ZR X | car 13 | 0 | yes |
| 39 | Ford TS50: NFS | Right L1 L1 L1 R1 Left Left L1 | Right L L L R Left Left L | car 14 | 0 | yes |
| 40 | Lotus Elise | Triangle R2 Triangle R2 Left Square Left Square | B ZR B ZR Left X Left X | car 41 | 0 | yes |
| 41 | Lotus Elise: NFS | Square L1 L1 L1 R2 L2 L2 L1 | X L L L ZR ZL ZL L | car 42 | 0 | yes |
| 42 | Mercedes CL55 AMG | L1 Right L1 Right L2 Square L2 Square | L Right L Right ZL X ZL X | car 43 | 0 | yes |
| 43 | Mercedes CL55 AMG: NFS | Triangle R2 R2 R2 R1 L1 L1 R2 | B ZR ZR ZR R L L ZR | car 44 | 0 | yes |
| 44 | Opel Speedster: NFS | L2 R2 R2 R2 Square Left Left L2 | ZL ZR ZR ZR X Left Left ZL | car 38 | 0 | yes |
| 45 | Vauxhall VX220: NFS | L1 R1 R1 R1 Left Right Right L1 | L R R R Left Right Right L | car 36 | 0 | yes |
| 46 | Pursuit Corvette Z06 in You're The Cop Mode | R2 L1 L1 R2 R1 Right Right R1 | ZR L L ZR R Right Right R | cop car 33 | 0 | yes |
| 47 | Pursuit Corvette Z06 in all Challenge Modes | L2 R2 R2 L2 Triangle Right Triangle Right | ZL ZR ZR ZL B Right B Right | car 33 | 0 | yes |
| 48 | Pursuit Murcielago in You're The Cop Mode | Right L2 L2 Right Square Left Left Square | Right ZL ZL Right X Left Left X | cop car 32 | 0 | yes |
| 49 | Pursuit Murcielago in all Challenge Modes | R1 L1 L1 R1 Right R2 Right R2 | R L L R Right ZR Right ZR | car 32 | 0 | yes |
| 50 | Pursuit Mustang Cobra R in You're The Cop Mode | Left Triangle Triangle Left R1 R2 R2 R1 | Left B B Left R ZR ZR R | cop car 34 | 0 | yes |
| 51 | Pursuit Mustang Cobra R in all Challenge Modes | Left Square Left Square R2 R1 R2 R1 | Left X Left X ZR R ZR R | car 34 | 0 | yes |
| 52 | Pursuit M5 in You're The Cop Mode | Triangle Square Square Triangle L1 R1 R1 L1 | B X X B L R R L | cop car 31 | 0 | yes |
| 53 | Pursuit M5 in all Challenge Modes | Square Triangle Triangle Square Left R1 Left R1 | X B B X Left R Left R | car 31 | 0 | yes |
| 54 | Pursuit Crown Victoria in all Challenge Modes | Right Left Left Right Square Triangle Square Triangle | Right Left Left Right X B X B | car 4 | 0 | yes |
| 55 | Coastal Parklands II | R2 R2 Left Left Left R2 R1 L1 | ZR ZR Left Left Left ZR R L | track, backward 11 | 0 | yes |
| 56 | National Forest | Square Square L2 L2 R1 R1 Left Left | X X ZL ZL R R Left Left | track 12 | 0 | yes |
| 57 | National Forest II | Left Left L1 L1 L1 Left Right Square | Left Left L L L Left Right X | track, backward 12 | 0 | yes |
| 58 | Scenic Drive II | L2 L2 L1 L1 L1 L2 Triangle Square | ZL ZL L L L ZL B X | track, backward 13 | 0 | yes |
| 59 | Desert Heat II | R1 R1 R2 R2 R2 R1 L1 Left | R R ZR ZR ZR R L Left | track, backward 21 | 0 | yes |
| 60 | Outback | Triangle Triangle Right Right L1 L1 R1 R1 | B B Right Right L L R R | track 22 | 0 | yes |
| 61 | Outback II | L1 L1 Triangle Triangle Triangle L1 Square Right | L L B B B L X Right | track, backward 22 | 0 | yes |
| 62 | Rocky Canyons | R1 R1 Left Left Square Square Right Right | R R Left Left X X Right Right | track 23 | 0 | yes |
| 63 | Rocky Canyons II | Square Square Triangle Triangle Triangle Square L1 Left | X X B B B X L Left | track, backward 23 | 0 | yes |
| 64 | Ancient Ruins II | Right Right Left Left Left Right L1 Square | Right Right Left Left Left Right L X | track, backward 31 | 0 | yes |
| 65 | Calypso Coast | R2 R2 R1 R1 L1 L1 Triangle Triangle | ZR ZR R R L L B B | track 32 | 0 | yes |
| 66 | Calypso Coast II | Triangle Triangle Right Right Right Triangle Square L1 | B B Right Right Right B X L | track, backward 32 | 0 | yes |
| 67 | Mediterranean Paradise II | Square Square Right Right Right Square Left L2 | X X Right Right Right X Left ZL | track, backward 33 | 0 | yes |
| 68 | Fall Winds II | R2 R2 Square Square Square R2 Left R1 | ZR ZR X X X ZR Left R | track, backward 41 | 0 | yes |
| 69 | Alpine Trail | Square Square Triangle Triangle Left Left L2 L2 | X X B B Left Left ZL ZL | track 42 | 0 | yes |
| 70 | Alpine Trail II | Left Left R2 R2 R2 Left R1 Square | Left Left ZR ZR ZR Left R X | track, backward 42 | 0 | yes |
| 71 | Autumn Crossing | Right Right Triangle Triangle R1 R1 Left Left | Right Right B B R R Left Left | track 43 | 0 | yes |
| 72 | Autumn Crossing II | R1 R1 Right Right Right R1 R2 Triangle | R R Right Right Right R ZR B | track, backward 43 | 0 | yes |
| 73 | Island Outskirts II | L2 L2 R1 R1 R1 L2 Left R2 | ZL ZL R R R ZL Left ZR | track, backward 61 | 0 | yes |
| 74 | Palm City Island | Left Left R1 R1 Right Right Square Square | Left Left R R Right Right X X | track 62 | 0 | yes |
| 75 | Palm City Island II | Right Right R2 R2 R2 Right R1 Left | Right Right ZR ZR ZR Right R Left | track, backward 62 | 0 | yes |
| 76 | Tropical Circuit | R2 R2 Triangle Triangle Right Right R1 R1 | ZR ZR B B Right Right R R | track 63 | 0 | yes |
| 77 | Tropical Circuit II | L1 L1 Right Right Right L1 Square R2 | L L Right Right Right L X ZR | track, backward 63 | 0 | yes |

What the eggs do in the port now:

| egg | status |
| --- | --- |
| 0 Motion Blur, 1 Black & White, 2 Heavy Fog, 3 R/C Car, 8 Chrome Cars | entered and shown, but the render eggs (the Stomper) are TASKS 50b |
| 4 Video Mode | the HUD's group `0x06d1f9fb`; its render egg is TASKS 50b |
| 5 Pet Helicopter | no presses; `ForceChopper` |
| 6, 7 the bonus events | in the event tree (`eventtree.c`) |

Group 1 is the five visual eggs, Motion Blur to Video Mode: one at a time.

## The check

`tools/eastereggs_check.py` runs retail's code in `tools/mipsemu.py`, with
AddJoyHandler and RemoveJoyHandler stubbed to log, and the port in
`tools/src/eastereggs_test.c`. The script dumps the disc's whole table on
both sides, enters codes press by press, after stray presses, with the
last press or the first wrong, the groups, every car and track lookup, the
clears, the switch, the ring and Head poked past their ends, ports and
values that are not read, a table of its own (two codes with one sequence,
no codes, odd types and groups), 90 random runs, Stop, and a second
object: 2,084 ops, 1,999 lines, 0 differ. `--mutate`: 83 mutations, 83
caught.

`tools/run_azahar_cheat.ps1` enters code 46 on the main menu in Azahar:
the menu says "Unlocked / Pursuit Corvette Z06 in You're The Cop Mode",
and You're The Cop's car select goes from 1 car unlocked of 5 to 2.
