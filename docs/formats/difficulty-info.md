# DifficultyInfo (chunk `0x00034b00`)

`TheDifficultyInfo` is the AI's and the catchup's tuning: how far behind
or ahead the AI is pushed, how each of the ten skill levels drives, which
skills a race's opponents are drawn from, and the two-player catchup.
It is one chunk in GLOBALB.BUN, copied whole into a static table. The
port has it in `difficultyinfo.{c,h}`.

The record is all floats and bytes, with no pointer, so it is the same
size on every target and the loader's straight copy is right on the 3DS.

## The loader

```
LoaderDifficultyInfo(chunk)      retail 0x0012ff68, demo 0x0012e7b0
    if chunk->id != 0x34b00: return 0
    bMemCpy(&TheDifficultyInfo, chunk + 8, 992)
    return 1

UnloaderDifficultyInfo(chunk)    retail 0x0012ffb0, demo 0x0012e7f8
    return chunk->id == 0x34b00
```

- **The size is the record's, not the chunk's.** The chunk's size field
  is never read. A short chunk's copy runs on past it: the demo's
  744-byte chunk, handed to retail's loader, loads with the 248 bytes
  after it.
- **The id is the whole word.** An id one bit off in any byte, the
  container bit among them, is not the table's, and the table is left as
  it was.
- **The unloader does nothing.** It answers whether the chunk is the
  table's. The table keeps its values after the unload.
- The demo's is the same code, copying 744 bytes.

## The record

The demo's is 744 bytes, `.mdebug` type#2830. Retail's is 992, and retail's
ELF is stripped, so its layout is taken from the code that reads it. The
names are the demo's.

| offset | field | |
|---:|---|---|
| 0 | `bVector2 AIDistanceBoostLoSkill[7]` | |
| 56 | `bVector2 AIDistanceBoostHiSkill[7]` | |
| 112 | `float AIPositionBoostLoSkill[16]` | |
| 176 | `float AIPositionBoostHiSkill[16]` | |
| 240 | `float PositionRatioOverOne[8][2]` | new in retail |
| 304 | `float PositionRatioUnderOne[8][2]` | new in retail |
| 368 | `SkillLevelEntry AISkillLevel[10]` | the demo's 240 |
| 648 | `NonExplicitModeData AINonExplicitMode` | the demo's 520; 300 bytes, the demo's 180 |
| 948 | `bVector2 TwoPlayerCatchup[4]` | the demo's 700 |
| 980 | `MiscData Misc` | the demo's 732 |

`SkillLevelEntry`, 28 bytes: `TakeSignChance[3]`,
`CollisionAvoidanceChance`, `SpeedFactor` and `SlowFactor` as floats,
then the byte `RoutePointVariance`, a byte `pad` and two more.

`NonExplicitModeData`, 300 bytes:
- `float BoostScale[3][5]` at 0. The demo's stab names the 20-byte row
  by number only. StartRace and StartDemoDiscGame read it as five floats,
  by `OpponentStrength` and then a byte of the driver's.
- `float SkillLevelDistribution[2][3][10]` at 60.

`MiscData`, 12 bytes: `RoutePointChangeFrequency`,
`BoostCalculationFrequency` and `MaxDistanceForBoost`.

### What retail changed

- **The position ratios moved into the table.** The demo's
  DecideBoostFactor read two static tables, `fPositionRatioOverOne`
  (`0x00307fe0`) and `fPositionRatioUnderOne` (`0x00308020`). Each is
  eight rows of two floats, one row per race position from 1, and each
  row is a two-knee Table over skill 0 to 9. The first is used for a car
  whose ratio is 1 or more, the second for one under 1. Retail's reads
  them from the table at 240 and 304, in the same order. Its values are
  retuned: the first row of the first is (0.8, 1.05) in both, but the
  demo's second row is (0.7, 1) and retail's (0.7, 0.9).
- **A second set of skill distributions.** The demo's SetupCarsForRace
  drew each opponent's skill from `SkillLevelDistribution[strength]`.
  Retail's indexes `[TheRaceParameters.nMaxCops < 1][strength]`: `[0]`
  for races with cops, `[1]` for races with none. In GLOBALB.BUN the two
  sets differ in one value, strength 2's at skill 7: 0.5 with cops, 0.8
  without.
- Everything else is the demo's, 128 bytes on from `AISkillLevel` and 248
  from `TwoPlayerCatchup`. GLOBALB.BUN's `TwoPlayerCatchup` is (-500,
  1.08), (-200, 1.03), (-100, 1.01), (-40, 1) on both discs.
- The table is at `0x002f0080` in retail's `.data`, `0x002e81c0` in the
  demo's.

### The readers

Eleven functions in retail form an address in the table. These are the
instructions that fix the layout, as `difficulty_check` holds them:

| function | address | instruction | what it fixes |
|---|---|---|---|
| LoaderDifficultyInfo | `0x0012ff90` | `addiu a0,a0,128` | the table at `0x002f0080` |
| | `0x0012ff98` | `addiu a2,zero,992` | its size |
| CalculateNewCatchupMultipliers | `0x00135238` | `addiu a1,a1,1076` | `TwoPlayerCatchup` at 948 |
| | `0x00135248` | `addiu a2,zero,4` | four knees |
| ShouldWeAvoidThisCar | `0x00130850` | `lwc1 $f1,380(v1)` | `AISkillLevel` at 368, `CollisionAvoidanceChance` at 12 |
| SignPostDecision | `0x00191fdc` | `addiu v0,v0,496` | `TakeSignChance` at 368 |
| DecideBoostFactor | `0x001929a0` | `lwc1 $f1,984(v1)` | `BoostCalculationFrequency` at 984 |
| | `0x00192bb0` | `lwc1 $f23,388(v0)` | `SlowFactor` at 20 of a skill |
| | `0x00192bf4`, `0x00192bf8` | `addiu v0,s3,232`, `296` | the ratios at 240 and 304, a row back for position 1 |
| | `0x00192bfc` | `sll a1,s0,3` | 8-byte rows |
| CalculateDistanceAndPositionBoost | `0x00192d58` | `lwc1 $f0,988(s5)` | `MaxDistanceForBoost` at 988 |
| | `0x00192d84` | `addiu a1,s5,56` | `AIDistanceBoostHiSkill` at 56 |
| | `0x00192e9c`, `0x00192ea4` | `lwc1 ...,176`, `112` | the position boosts |
| ExecuteCurrentAction | `0x0019344c` | `lwc1 $f1,980(a1)` | `RoutePointChangeFrequency` at 980 |
| | `0x0019347c` | `lbu s0,392(v0)` | `RoutePointVariance` at 24 of a skill |
| StartSkipFEGame | `0x00184cec` | `addiu a1,a1,648` | `AINonExplicitMode` at 648 |
| StartDemoDiscGame, StartRace | `0x00184f48`, `0x001851e4` | `lwc1 $f0,648(...)` | `BoostScale`, 20-byte rows |
| SetupCarsForRace | `0x00185ad0` | `lwc1 $f0,708(a0)` | `SkillLevelDistribution` at 60 |
| | `0x00185aac`, `0x00185ab0` | `addiu ...,40`, `120` | rows of 10, sets of 3 |

The demo's image has ten of these readers, the same scan finds. The
eleventh, ExecuteCurrentAction, is retail's alone. In the demo, only
DecideBoostFactor reads the two position ratio statics.

## In the port

These readers are in the port, each checked against retail:
- Car's `CalculateNewCatchupMultipliers` (`car.md`) reads
  `TwoPlayerCatchup`.
- FredRace's race set-up reads `AINonExplicitMode`'s `BoostScale` and
  `SkillLevelDistribution`.
- AICarController (`ai-car-controller.md`) reads the rest:
  - SignPostDecision reads `TakeSignChance` (11e-2).
  - DecideBoostFactor reads `BoostCalculationFrequency`, the skills'
    `SlowFactor` and the two position-ratio tables (11e-3).
  - CalculateDistanceAndPositionBoost reads `MaxDistanceForBoost`, the
    two distance graphs and the two position-boost rows (11e-3).

Every other AI field is laid out so its offset is checked. These are
still to come:
- ExecuteCurrentAction's `RoutePointChangeFrequency` and
  `RoutePointVariance` (11e-4);
- AIDriver's ShouldWeAvoidThisCar, reading `CollisionAvoidanceChance`
  (11f).

## Checking it

```bash
python tools/difficulty_check.py
python tools/difficulty_check.py --mutate
```

The model runs retail's loader and unloader out of the retail image,
bMemCpy and all. The chunks are:

- retail GLOBALB.BUN's own;
- five copies with the id one bit or one byte off, the container bit
  among them;
- one whose every payload byte is its own;
- the demo's 744-byte chunk;
- one whose size field says 0.

Each chunk has 256 bytes of a pattern after it. Between the loads the
table is filled with a pattern, so a load that copies nothing shows. Both
sides print the table field by field. The model also fails if the image
writes outside the table or the stack.

The image facts are the instructions above and more, 68 in all. Each is
decoded at its address and must lie in the function named for it. The
number it carries must equal its layout expression, which is evaluated
over the model's layout and again over the port's `offsetof`s. A scan
of retail's code for every address formed in the table's 992 bytes
must find the eleven readers and no others.

`carmode_check` still runs the catchup on the demo image. Its harness
loads retail's chunk and the image loads the demo's, and it dumps only the
knees, which are the same in both.

Results: 42 ops, 374 lines, 0 differ; 68 facts and 11 readers, 0 wrong.
All 24 mutations are caught, with none equivalent. They include the loader's id
test, size and header, the unloader, and layouts that pass the size check:
the two ratio tables swapped or moved after the skills, the distribution
indexed the other way, the catchup and `Misc` swapped, fields swapped
within `MiscData` and `SkillLevelEntry`, and the two distance boosts
swapped.
