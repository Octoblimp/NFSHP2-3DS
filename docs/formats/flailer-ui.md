# `0x80010200` -- Flailer, bWare's UI system

Every screen in the game is a Flailer screen: the frontend menus, the in-race
HUD, the pause menus, the results tables. "Flailer" is the name of both the
runtime (`FlailerRenderManager`) and the off-line authoring tool whose export
this chunk is.

Three files on this disc carry one Flailer project each:

| file | project hash | screens | bitmaps | text |
|------|-------------:|--------:|--------:|-----:|
| `FRONTEND\FRONTB.BUN` | `255842fd` | 39 | 875 | 480 |
| `GLOBAL\INGAMEB.BUN`  | `eca3270e` | 29 | 431 | 414 |
| `GLOBAL\GLOBALB.BUN`  | `e3448a8e` |  8 |  12 |  40 |

Reader: `tools/flailer_dump.py` (a screen-by-screen listing, `--stats`, or
`--json` for the whole tree; stdlib only).

Every struct below is the engine's own, taken verbatim from the recovered
`.mdebug` type information in `docs/mdebug_structs.txt`. The chunk sizes on
disc are literally `sizeof()` -- 20, 40, 120 -- so nothing here is inferred
from byte patterns. All three object classes derive from `bNode`, whose
`Next`/`Prev` occupy the first 8 bytes of every payload and hold stale PS2
pointers on disc; `LoaderFlailerChunk` (`0x0013d890`) relinks them.

## The tree

```
0x80010200  FlailerChunk               container, one per file
  0x00010213  FlailerProjectChunk        20 bytes
  0x80010201  (screen)                   container, one per screen
    0x00010203  FlailerScreenChunk         40 bytes
    0x00010210  FlailerBitmapChunk         120 bytes   } in any order,
    0x00010212  FlailerTextChunk           76 + MaxChars bytes  } any number
```

`LoaderFlailerChunk` walks the top level looking for exactly two types --
`0x00010213` and `0x80010201` -- and inside a screen container it special-cases
`0x00010203` and treats *every other chunk* as an object, appending its payload
to the screen's `ObjectList` without looking at the chunk id. Objects are told
apart at render time by `FlailerObjectChunk::ObjectType`, not by chunk type.
In this build the two always agree: all 934 `0x00010212` chunks carry
`ObjectType == FLAILER_TYPE_TEXT` and all 1,318 `0x00010210` chunks carry
`FLAILER_TYPE_BITMAP`. The `POINT`, `LINE` and `SCREEN` object types the enum
allows are never used.

## `FlailerProjectChunk`, 20 bytes

| offset | type    | field       | meaning |
|-------:|---------|-------------|---------|
| 0      | `bNode` | `Next/Prev` | stale |
| 8      | `u32`   | `NameHash`  | `bStringHash` of the project name |
| 12     | `bTList`| `ScreenList`| rebuilt by the loader |

## `FlailerScreenChunk`, 40 bytes

| offset | type     | field            | meaning |
|-------:|----------|------------------|---------|
| 0      | `bNode`  | `Next/Prev`      | stale |
| 8      | `u32`    | `NameHash`       | `bStringHash` of the screen name |
| 12     | `u32`    | `CallbackHash`   | `0xffffffff` on all 76 screens |
| 16     | `u32`    | `HelpMenuHash`   | `0xffffffff` on all 76 screens |
| 20     | `u32`    | `BackgroundHash` | `0xffffffff` on all 76 screens |
| 24     | `u16`    | `ResX`           | 640 on all 76 screens |
| 26     | `u16`    | `ResY`           | 480 on all 76 screens |
| 28     | `u16`    | `NumObjects`     | exactly the number of child object chunks |
| 30     | `u16`    | `Visible`        | **dead on disc** -- see below |
| 32     | `bTList` | `ObjectList`     | rebuilt by the loader |

`NumObjects` matches the parsed child count on every screen in all three
files, which is the check that validates the whole layout.

`Visible` is a `FlailerScreenVisibility` (`FLAILER_SCREEN_VISIBLE` 0,
`FLAILER_SCREEN_INVISIBLE` 1) but nothing on disc survives: the loader does

```
0013d974  sh     t3,0x1e(a2)        ; t3 == 1
```

on every screen it links, so screens always start out invisible and the game
turns them on with `FlailerSetScreenVisibility(hash, FLAILER_SCREEN_VISIBLE)`.
The exporter writes `0x0040` into the field on all 76 screens; it is padding.
`CallbackHash`/`HelpMenuHash`/`BackgroundHash` are the same story in reverse --
never authored, always the empty-string hash `0xffffffff`, wired up at runtime.

## `FlailerObjectChunk`, 56 bytes -- the shared object header

Both leaf object types begin with this.

| offset | type  | field           | meaning |
|-------:|-------|-----------------|---------|
| 0      | `bNode` | `Next/Prev`   | stale |
| 8      | `u32` | `NameHash`      | |
| 12     | `u32` | `GroupHash`     | for `FlailerSetGroupVisibility` |
| 16     | `s8`  | `ObjectType`    | `FlailerObjectType` |
| 17     | `s8`  | `Visible`       | `FlailerObjectVisibility` |
| 18     | `s8`  | `Z`             | render layer, 0..28 -- see below |
| 19     | `s8`  | `DirtyFlag`     | runtime only, 0 on disc |
| 20     | `ptr` | `pFlailerStrip` | runtime only |
| 24     | `f32` | `TopLeftX`      | pixels, 640x480 space |
| 28     | `f32` | `TopLeftY`      | |
| 32     | `f32` | `ScaleX`        | |
| 36     | `f32` | `ScaleY`        | |
| 40     | `s32` | `RotationAngle` | |
| 44     | `s32` | `AnimationMode` | `FlailerObjectRotation` |
| 48     | `u32` | `RenderOnPoly`  | `NameHash` of the object to draw onto |
| 52     | `u32` | `ClipToPoly`    | `NameHash` of the object to clip against |

Enums, straight from the type info:

```
FlailerObjectType        FLAILER_TYPE_NONE 0, TEXT 1, BITMAP 2,
                         POINT 3, LINE 4, SCREEN 5
FlailerObjectVisibility  FLAILER_OBJECT_INVISIBLE 0, VISIBLE 1,
                         PSX2_ONLY 2, XBOX_ONLY 3
FlailerObjectRotation    FLAILER_ROTATE_NONE 0, ROTATE_AROUND 1,
                         ROTATE_CENTER 2, ROTATE_LEFT 3, ROTATE_RIGHT 4,
                         TRANSLATE_LEFT 5, TRANSLATE_RIGHT 6,
                         ANIMATE_LEFT 7, ANIMATE_RIGHT 8, SLIDE_UP 9,
                         TACH_GRADIENT 10
```

`PSX2_ONLY`/`XBOX_ONLY` are a useful reminder that this data is shared with
the Xbox build. 1,838 objects are `VISIBLE` and 414 `INVISIBLE`; neither
platform-specific value is used. `AnimationMode` is almost always `NONE` --
across all 2,252 objects only 4 use `TACH_GRADIENT` (the in-game tachometer
sweep) and 3 use `ROTATE_CENTER`.

`Z` is not a sort key, it is a layer index. `FlailerRenderManager` opens with
`FlailerLayerRenderInfo LayerRenderInfoTable[29]`, and `AddFlailerStrip`
(`0x00143990`) does

```
001439b8  lb     v0,18(v0)          ; Z
001439c0  sll    v0,v0,3            ; * sizeof(FlailerLayerRenderInfo)
001439c4  addu   v0,t0,v0           ; &this->LayerRenderInfoTable[Z]
```

before appending the object's strip to that layer's list;
`RenderLayer(i, view)` then draws one layer at a time. The table has exactly
29 slots and the values on disc run 0..28, so the whole range is in use (only
9 is skipped). `SortFlailerObjectFunction` (`0x00144258`) orders by the same
byte ascending.

### Layer draw order

Higher `Z` is *further back*, and the order is not a plain sweep.
`eDisplayFrame` (`0x00112858`) calls `RenderLayer` from four separate loops,
and every one of them counts **down**:

| loop | layers | where in the frame |
|------|--------|--------------------|
| `0x00112b58` | 24 -> 20 | before the world, into the render targets |
| `0x00113680` | 15 -> 0  | the main pass |
| `0x001136c0` | 19 -> 16 | |
| `0x00113708` | 28 -> 25 | last, so 25 ends up frontmost of all |

Flattened, back to front:

```
24 23 22 21 20  15 14 13 .. 2 1 0  19 18 17 16  28 27 26 25
```

The four ranges cover 0..28 exactly once, which is how you know there is no
fifth loop hiding somewhere. Each loop looks like this -- the decrement and
the `slti` bound are the whole story:

```
001136ec  addiu  s0,s0,-1
001136f0  slti   v0,s0,16
001136f4  beq    v0,zero,0x001136c0
```

This matters: `NEW_MAIN_MENU` puts its 512x384 backgrounds at Z 7..10 and
the title logo at Z 0. Draw the layers ascending and the backgrounds bury
the menu. Within one layer the file order *is* the draw order, because
`AddFlailerStrip` appends to the tail of that layer's list.

## `FlailerBitmapChunk`, 120 bytes

Continues the object header at offset 56.

| offset | type     | field          | meaning |
|-------:|----------|----------------|---------|
| 56     | `u32`    | `TextureHash`  | a texture in a `0xb0300001` pack |
| 60     | `ptr`    | `pTextureInfo` | resolved at load |
| 64     | `u32[4]` | `GouradColors` | per-corner RGBA, `0x80808080` = opaque white |
| 80     | `u8`     | `StateFlags`   | 0 on all 1,318 bitmaps |
| 84     | `ptr`    | `pFlailerTachometerPointList` | |
| 88     | `f32[8]` | `UV`           | four `(u,v)` corners, usually `0,0 1,0 1,1 0,1` |

The colour bytes are PS2 GS convention: `0x80` is full intensity, not `0xff`,
so alpha `0x80` is opaque and the frequently-seen `0xff` corners are the GS
over-bright range. `tools/flailer_dump.py` prints them as `rrggbbaa`.

`TextureHash` resolves against the texture packs in the same bundle --
1,307 of 1,318 land on a real texture via `tools/texture_convert.py`.

## `FlailerTextChunk`, 76 + `MaxChars` bytes

The class is 80 bytes, but its last member is `char *String`; on disc the
string data sits inline where the pointer would be, so the chunk is
`76 + MaxChars` rounded up to a multiple of 4. That relationship holds for
every one of the 934 text chunks in this build.

| offset | type  | field           | meaning |
|-------:|-------|-----------------|---------|
| 56     | `u32` | `FontHash`      | |
| 60     | `u32` | `MaxChars`      | bytes of inline string that follow |
| 64     | `u32` | `FormatOptions` | bit field, below |
| 68     | `u32` | `GouradColor`   | RGBA |
| 72     | `u32` | `LanguageID`    | 0, or a key into `FE_*.BIN` |
| 76     | `char[MaxChars]` | `String` | the authoring placeholder |

### `LanguageID` beats `String`

**The inline string is not what the game draws.** When `LanguageID` is
non-zero the renderer calls `GetTranslatedString(LanguageID)` and draws that
instead, and the baked-in string is just whatever the author last typed --
routinely stale. The main menu ships `'Speed'`, `'Championship'` and
`'Mode Select'` where the game actually draws `'World Racing'`,
`'Hot Pursuit'` and `'Main Menu'`.

120 distinct `LanguageID`s are used across the three files. They resolve
against `LANGUAGES\FE_ENGLISH.BIN`; see `docs/formats/language-table.md` and
`tools/language_dump.py`. `flailer_dump.py` does this by default and prints
the placeholder after the real text as `(was ...)`.

### `FormatOptions`

These are `#define`s, so unlike everything else here they are *not* in the
type info -- only the seven predicates that read them:

```
IsCentered  IsLeftJustified  IsRightJustified  IsDarkBackground
IsToBeClipped  IsToBeWrapped  IsFixedWidthNumber
```

Declaration order is **not** bit order, which is the one trap in this format.
The bits below come from the renderer itself, `Render__16FlailerTextChunk`
(`0x0013ff40`; `RenderFlailerText` at `0x0013feb0` is a 144-byte wrapper
around it):

| bit | meaning | how it is pinned |
|----:|---------|------------------|
| `0x01` | right-justified | `sub.s $f26,$f26,$f1` -- pen X minus the full `GetScaledWidth()` |
| `0x02` | left-justified  | never tested; the default |
| `0x04` | centered        | `mul.s` by `0.5` then `sub.s` -- pen X minus half the width |
| `0x08` | dark background | branches to `RenderDarkBackground` (`0x0013fd80`) |
| `0x10` | clip            | carried into the per-glyph quad builder |
| `0x20` | word wrap       | tested inside the per-character loop |
| `0x40` | fixed width     | tail-calls `RenderStringFixedWidth` (`0x0013fb78`) |

Getting `0x01` and `0x04` the wrong way round -- which is what declaration
order suggests -- would right-align every centred label in the game. The data
confirms the code: over all three files the median `TopLeftX` is 490 for
`0x01`, 172 for `0x02` and 365 for `0x04` on a 640-wide screen.

Combinations actually used: `0x02` (689), `0x04` (180), `0x4a`
(`left|darkbg|fixedwidth`, 32), `0x01` (32), `0x41`
(`right|fixedwidth`, 1). Nothing uses wrap or clip in this build.

### Fonts

`FontHash` is matched against `tTTFontHeader::mHashID`, the first word of
each **`0x00015010`** font chunk's payload -- `FindFont` (`0x0013db08`) is a
linear walk of the loaded font list comparing that word. (`LoaderFontInfo`
also accepts `0x00030200` and then does nothing with it; no chunk of that
type exists on this disc. Layout in `docs/formats/bchunk.md`.) There is no
name string in the font chunk, but every font's glyph sheet is a texture of
the same name in the texture pack, so all ten fonts in use resolve for free:

| font | text objects |
|------|-------------:|
| `FONT_A` | 357 |
| `FONT_HUD` | 207 |
| `FONT_IMPACTSMALL` | 145 |
| `FONT_STATS` | 123 |
| `BUTTONSOUT` | 43 |
| `FONT_IMPACTBIG` | 25 |
| `FONT_IMPACTNORMAL` | 21 |
| `FONT_POSITION` | 6 |
| `FONT_GAUGE` | 4 |
| `FONT_EVENTNUMBERS` | 3 |

`GetScaledWidth` (`0x0013e8b0`) shows how text is measured: per character,
index `Font.CharacterLookupTable[c]`, take the float at `+20` of the glyph
record, sum, multiply by `ScaleX`. It measures the *translated* string when
`LanguageID` is set, which is why justification stays correct across
languages.

## Drawing a screen

The layout is data; these are the parts of the *behaviour* that a
reimplementation has to copy or the screens come out wrong.

### Bitmap size

`RenderSingleFlailerBitmap` (`0x00140538`) ignores the UV rectangle when
sizing the quad. It takes the width and height from the resolved
`TextureInfo` and truncates:

```
w = (int)(TextureInfo.Width  * ScaleX)
h = (int)(TextureInfo.Height * ScaleY)
```

The UVs only pick which part of the sheet is sampled. Every UV rect on disc
is axis-aligned, so the four corners collapse to a min/max box, but
`GouradColors` really is per-corner and the engine interpolates it.

### Glyph metrics, including the shipped bug

`RenderCharacter` (`0x0013f698`) multiplies the glyph's width by `ScaleX`
**twice** -- `mul.s` at `0x0013f750` and again at `0x0013f794` -- while the
height is scaled once and the pen advances once. The raw instruction words
were decoded by hand to rule out a disassembler artifact. It is a bug, but
the screens were authored against it, so a port has to reproduce it:

```
glyphW = Width  * ScaleX * ScaleX
glyphH = Height * ScaleY
penX  += Advance * ScaleX
```

Measurement is unaffected: `GetScaledWidth` sums the advances and scales
once, so justification uses the honest width.

### Fixed width

`RenderStringFixedWidth` (`0x0013fb78`) gives every character a cell of
`Font::FixedWidthCell` and centres the glyph in it:

```
inset = (FixedWidthCell - Advance) * 0.5      // added to an already-scaled pen
penX += FixedWidthCell * ScaleX
```

`FixedWidthCell` is not stored in the font chunk; `Font::Font`
(`0x0013dd60`) computes it as `GetWidestCharacter(this, "1234567890:- ")` --
the widest `mAdvance` among those thirteen characters. That is what makes
lap times and scores line up as they count.

`ColonCrapola`, a gp-relative global, would give `:` and `.` their own
proportional advance instead. It is 0 in initialised data and nothing on
this disc writes it, so that path is dead. The other three globals the
renderer reads -- `KerningEnabled`, `RenderFixedWidthStrings`,
`TranslationEnable` -- are all 1 and likewise never written.

### Help characters

Bytes `0x80`..`0x91` in a string are button icons, not text.
`RenderHelpCharacter` (`0x0013f9b8`) hashes `"BUTTONSOUT"`, calls `FindFont`,
and indexes an 18-byte table at `0x002e8a10` to get the glyph to draw:

```
0x80..0x91 -> 'a' 'b' 'd' 'e' 'f' 'g' 'i' 'j' 'h' 'k' 'n' 'o' 'l' 'm' 'c' 'c' 'c' 'c'
```

The last four all map to `'c'`. The glyph comes from `BUTTONSOUT` regardless
of the text object's own `FontHash`, and the pen advances by that glyph's
advance.

## The port

`3DS Files/source/bui.[ch]` parses the format; `3DS Files/source/uirender.c`
draws it with citro2d. Everything above is implemented there, including the
`ScaleX`-squared bug. Textures come from `texpack.c`, fonts from `bfont.c`,
strings from `langtab.c`.

`tools/flailer_render.py` is the same renderer in pure Python, compositing a
screen to a PNG with no dependencies. It exists to check the port by eye and
to make the format falsifiable: if a screen does not come out looking like
the game, something above is wrong. `tools/bui_check.py` does the exact
check, diffing `bui.c`'s parse against `flailer_dump.py` -- 2,331 lines
across the three bundles, 0 differ.

```
python3 tools/flailer_render.py extracted/FRONTEND/FRONTB.BUN 0 \
        --also extracted/GLOBAL/GLOBALB.BUN \
        --language extracted/LANGUAGES/FE_ENGLISH.BIN -o menu.png
```

## Names

Everything cross-references by `bStringHash` (`tools/bhash.py`); the empty
string hashes to `0xffffffff`, which is the "unset" sentinel throughout.
Resolution rates against ELF string literals plus the texture packs:

| hash | resolved |
|------|---------:|
| font | 934 / 934 |
| texture | 1307 / 1318 |
| screen | 18 / 76 |
| object | 217 / 2252 |
| group | 41 / 2252 |

The 18 named screens are the ones the C++ frontend code refers to by name
(`NEW_MAIN_MENU`, `RACE_RESULTS`, `PAUSE_AUDIO`, `PRERACE_STATS`, ...). The
rest, and most object names, exist only inside the authoring tool, so they
are reachable only by brute-forcing the hash -- `bhash.crack()` does that,
and the uppercase-plus-underscore alphabet these names use makes it cheap.

## The engine side

| symbol | address | role |
|--------|---------|------|
| `LoaderFlailerChunk__FP6bChunk` | `0x0013d890` | builds the screen/object lists |
| `FlailerPostLoadFixup__Fv` | `0x0013f2b8` | post-load relink |
| `UpdateLanguageText__18FlailerScreenChunk` | `0x0013df88` | called per screen at load |
| `Render__16FlailerTextChunkP8bVector2T1f` | `0x0013ff40` | the text renderer |
| `RenderSingleFlailerBitmap__20FlailerRenderManager...` | `0x00140538` | the bitmap renderer |
| `FindFont__Fi` | `0x0013db08` | font hash lookup |
| `LoaderFontInfo__FP6bChunk` | `0x0013db58` | parses the `0x00015010` font chunk |
| `GetScaledWidth__16FlailerTextChunk` | `0x0013e8b0` | text measurement |
| `FlailerSetScreenVisibility__FUi23FlailerScreenVisibility` | | show/hide by hash |
| `FlailerSetGroupVisibility__Fiii` | | show/hide by `GroupHash` |

`FlailerMenu`, `FlailerMenuItem`, `FlailerScreen` and `FlailerSlider` are all
in the type info but **never appear on disc** -- menus are assembled in code
from the objects a screen already contains. So a reimplementation needs this
format for the *layout* and the frontend C++ for the *behaviour*.

That behaviour is now decompiled and written up separately, in
[flailer-menu.md](flailer-menu.md): a menu is the screen's text objects
called `MENUITEM_0` through `MENUITEM_15`, navigation recolours them in
place through `SetColor__16FlailerTextChunk`, and `AlignBar` turns out to be
dead code -- no bundle on the disc contains the `HIGHLIGHT_BAR` object it
would move.
