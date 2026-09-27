# The rain and the storm

The shipped image draws no rain, snow or storm. Rain.obj and the storm in
EcstasyE.obj are compiled and linked, but the four entry points the game
calls are empty, and nothing reaches the rest. This page records that
finding, how it was checked, and what the port keeps.

The image is the demo disc's `PS2 Files/NFSHP2.ELF`. Whether the retail
build's rain is live is not known yet: its ELF has not been looked at.

The port is `3DS Files/source/rain.c` and `rain.h`. The cross-check is
`tools/rain_check.py`.

## The entry points

Rain.obj runs from `0x001282d8` to `0x00128c18`. The game calls four of
its functions:

| Function | Address | Body | Called from |
|---|---|---|---|
| `rain_Load()` | `0x00128bf8` | `jr ra ; nop` | EndGameFlowLoadingTrackSpecific `+0x54`, after SkyLoader |
| `rain_Unload()` | `0x00128c00` | `jr ra ; nop` | BeginGameFlowUnloadingTrackSpecific `+0xb4`, after SkyUnloader |
| `rain_TimeStep(float)` | `0x00128c08` | `jr ra ; nop` | World::DoTimestep `+0x500`, after UpdatePlayersGameState |
| `rain_Render(eView *)` | `0x00128c10` | `jr ra ; nop` | nothing |

Each one is a return and its delay slot. The build that shipped had the
rain compiled out behind these four.

## The rest of Rain.obj

| Function | Address | Size | Reached from |
|---|---|---|---|
| RainSplash::Cache(Car *) | `0x001282d8` | 80 | RainSplash::Respawn (a tail `j`) |
| RainSplash::Recalc(float, bVector3 *) | `0x00128328` | 104 | RainSplash::Render |
| RainSplash::Render(eView *) | `0x00128390` | 256 | RainSystem::SplashLoop |
| RainSystem::TweakSplashes() | `0x00128490` | 180 | nothing |
| RainSystem::RainSystem() | `0x00128548` | 532 | nothing |
| RainSystem::~RainSystem() | `0x00128760` | 212 | nothing |
| RainSplash::Respawn(bVector3 &, float, Car *) | `0x00128838` | 264 | RainSystem::SplashLoop |
| RainSystem::SplashLoop(eView *) | `0x00128940` | 224 | nothing |
| RainSystem::Update(eView *) | `0x00128ad8` | 252 | nothing |
| RainSystem::Render(eView *) | `0x00128bd8` | 28 | nothing |

| Global | Address | Size | Read by |
|---|---|---|---|
| `rain_active` | `0x00322e34` | 4 | nothing |
| `rainSystems` | `0x00322e38` | 8 | nothing |
| `rain_default_texture` | `0x00322e40` | 4 | RainSplash::Render (gp-relative) |
| `rain_pos` | `0x002910e8` | 48 | RainSystem::Update |

`rainSystems` is two `RainSystem *`, one for each player. The `.mdebug`
stabs give RainSystem as 384 bytes:

| Offset | Field |
|---|---|
| 0 | `plyIndex` |
| 16 | `view_world`, a bMatrix4 |
| 80 | `pSystem` |
| 84 | `pStaticData` |
| 88 | `pEmitters[4]` |
| 112 | `matrices`, four bMatrix4s |
| 368 | `last_timestep` |
| 372 | `last_num_splashes` |
| 376 | `splashes` |

RainSystem has no virtuals. Nothing constructs one: its constructor and
destructor have no caller, and neither's address is taken.

## The storm

EcstasyE.obj has a second weather effect, the storm:

| Function | Address | Size | Reached from |
|---|---|---|---|
| SetStormType(int) | `0x00111090` | 8 | PauseDebugMenu::OnMenuItemScroll |
| GetStormType() | `0x00111098` | 8 | PauseDebugMenu's constructor and OnMenuItemScroll |
| GetStormTypeString(int) | `0x001110a0` | 12 | PauseDebugMenu's constructor and OnMenuItemScroll |
| UpdateStorm(eView *) | `0x001110b0` | 1428 | nothing |
| RenderStorm(eView *, eDmaChain *) | `0x00111648` | 1016 | RenderAllStorms |
| RenderAllStorms(eDmaChain *) | `0x00111a40` | 76 | nothing |

- SetStormType is `jr ra ; nop`.
- GetStormType is `jr ra ; move v0,zero`, so it always returns 0.
- GetStormTypeString returns `0x00322980`, which holds "None", whatever
  type it is given.

So the debug menu's storm entry can show only "None" and changes nothing.

The data:

| Global | Address | Size | Read by |
|---|---|---|---|
| `DrawStorm` | `0x0032297c` | 4 | nothing |
| `RainStorm` | `0x002ad0a0` | 76 | UpdateStorm, RenderStorm |
| `SnowStorm` | `0x002ad0f0` | 76 | nothing |
| `WaterSpray` | `0x002ad140` | 76 | nothing |
| `StormInfo` | `0x002ad190` | 98592 | UpdateStorm, RenderStorm; stamped by the static constructor |

StormInfo is three entries of `0x8060` bytes each. For each entry, the
static constructor (`_GLOBAL_$I$FloatingVBlankTimeMin` `+0x440`):
- runs an empty 512-count loop, the trivially built array;
- stores `0x98476894` at `+0x8054`;
- stores 0 at `+0x8050`, in the branch's delay slot.

Apart from the two dead functions, it is the only code that touches
StormInfo.

RainStorm and SnowStorm are the storm's two presets:

| | RainStorm | SnowStorm |
|---|---|---|
| word 2 (fall speed) | -0.5 | -0.02 |
| words 4, 5 | 0.1, 0.1 | 0.1, 0.1 |
| word 8 (colour) | `0x40646060` | `0x80bec4c4` |
| words 12, 13 | 1.0, 1.0 | 0.1, 0.1 |

The names in the first column are guesses from the values.

## The weather query's readers

The query has these callers:

- **eView::GetWeatherQuery** (`0x001123f8`), the per-view cache. Its
  callers are CreateFogPalette (`0x001196dc`) and UpdateStorm
  (`0x00111154`).
- **SoundScape::UpdateWeather** (`0x001c53c8`), which calls
  WeatherManQuery directly (`0x001c544c`). It has no caller.
  SoundScape::Update runs the reverb areas and the two ambients, but not
  the weather.

So CreateFogPalette is the query's one live reader. A track's rain, snow
and wind regions load onto their lists (`weatherman.c`) and nothing uses
them. TRACKB12 has none.

## How it was checked

`tools/rain_check.py` scans every loaded section (SHF_ALLOC) for
references to each function and global above. It counts:

- a `jal` or `j` whose target is the function;
- a `lui` followed, in the same function, by an `addiu` or a load or store
  based on that register, where the lui is forgotten once its register is
  written;
- a gp-relative access;
- a word in a data section.

`ori` is not counted. SN's compiler builds addresses with `addiu`, and
the `lui`/`ori` pairs that land in StormInfo's range are GS register
constants, such as `0x2c0400` and `0x2c0800`, which eDisplayFrame hands
to eAttachDepthIntoAlpha and eAttachFog.

The scan finds 30 references, and each is in `EXPECTED`. Three are data
words that fall in StormInfo's range: two in LumaQuant, the IPU's
quantiser, and one in `ascii_special`. Neither table holds pointers. The
`.mdebug` line tables name all of these functions too, but they are not
loaded, and the scan skips them.

The checker also:

- reads each entry point's two words;
- runs each entry point in mipsemu and counts one instruction, since the
  delay slot's `nop` is skipped;
- runs SetStormType's words, and GetStormType and GetStormTypeString for
  the types -1, 0, 1, 2, 3 and 99.

That makes 41 image facts, and none is wrong.

## The 3DS side

`rain.c` has the four entry points, empty, as the image has them. The
End and the Begin of the track flow call `rain_Load()` and
`rain_Unload()` directly now, and World::DoTimestep calls
`rain_TimeStep(dt)`. The seams `gRainLoadFn`, `gRainUnloadFn` and
`gRainTimeStepFn` are gone. `rain_Render` has no caller here either.

Nothing of the RainSystem, the RainSplashes or the storm is ported. The
image never runs them, so neither the PS2 demo nor the port shows them.
Their code is intact in the image, so it could be ported and checked
function by function, if the retail build turns out to use it.

## The cross-check

```
rain_check          31 calls, 31 lines, 0 differ
                    41 image facts, 30 references, 0 wrong
                    5 mutations: 5 caught, 0 equivalent
```

`rain_check` runs the image's four entry points in mipsemu and the
port's on the host, in the same order. Each is handed a view filled with
a pattern, and dt across zero, both signs, the denormals, the infinities
and a NaN. Each side prints whether its memory came through unchanged.
The model compares all 32 MB, the saved registers and f20-f31.

rain.c's mutations make rain_Render write or clear the view, read it when
it is NULL, or spin on it, and make rain_TimeStep spin on a NaN. The
harness crashes on the NULL read and hangs on the two spins.

Where the three calls are made is checked by the flow's own checkers:

- **`trackflow_check`** stubs rain_Load and rain_Unload by name now,
  rather than as seams, so the null-seam scenarios print them. Its
  mutations move rain_Load after SunTrackLoader, drop it, turn it into
  rain_Unload, call rain_Unload before CloseTrackMarkers, and drop
  rain_Unload.
- **`world_check`**'s mutations hand rain_TimeStep 0, drop it, and move
  it before UpdatePlayersGameState.
