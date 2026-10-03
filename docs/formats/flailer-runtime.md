# The Flailer runtime (step 8m-1)

The HUD, the pause menus and the frontend change their screens by calling
retail's Flailer runtime: look a screen up by hash, look an object up on
it by hash, then set its string, colour, alpha, position, scale or
texture. This step ports that runtime. `flailer.c` is the port, and
`tools/flailer_check.py` checks it against the image. The chunk layout is
in [flailer-ui.md](flailer-ui.md). This page covers the code that works
on the chunks after they load.

## The objects are the chunks

On the PS2, a `FlailerObjectChunk *` is the payload of the object's chunk
inside the loaded bundle, and every setter writes into those bytes. The
renderer reads the same bytes back each frame. The port keeps this
arrangement. `flailer.c` takes the payload pointers `bui.c` already holds
(`BUIObjectRef::payload`, and `BUIScreen::def` for the screen chunk) and
writes through retail's structs, so `uirender.c` draws whatever the game
last set.

The structs in `flailer.h` use retail's layout: the demo's fields, plus
the 24-byte name at +16. They have a compile-time check on every offset
the code uses:

| struct | size | fields the runtime touches |
|--------|-----:|----------------------------|
| `FlailerScreenChunk` | 40 | `NameHash` 8, `Visible` 30 (s16) |
| `FlailerObjectChunk` | 80 | `NameHash` 8, `GroupHash` 12, `ObjectType` 40, `Visibility` 41, `Z` 42, `DirtyFlag` 43, `pFlailerStrip` 44, `X/Y` 48, `ScaleX/Y` 56, `Rotation` 64, `ClipToPoly` 76 |
| `FlailerTextChunk` | 100 + `MaxChars` | `MaxChars` 84, `FormatOptions` 88, `Color` 92, `LanguageID` 96, `String` 100 |
| `FlailerBitmapChunk` | 144 | `TextureHash` 80, `pTextureInfo` 84, `Colors[4]` 88 |

`flailer_add_project` refuses any bundle whose objects are not retail's:
an object must have a name shift of 24, be at least 80 bytes, and be
word-aligned. The demo's bundles stay with `bui.c` alone.

## The project list and the screen order

LoaderFlailerChunk (`0x0013fba0`) appends each project to the list at
gp-22424 (tail at gp-22420) and links each project's screens in file
order. It links only screens that have a screen chunk. It sets each linked
screen's `Visible` to 1 (FLAILER_SCREEN_INVISIBLE) and runs the screen's
UpdateLanguageText (`0x001402a0`) on every text object, which stamps
`DirtyFlag` 5. `flailer_add_project` does the same over `bui.c`'s tables.
It keeps a list of project indices and, for each project, the order of its
linked screens.

FindFlailerScreen (`0x00140378`) walks the projects in list order and each
project's screens in their order. It counts every screen it passes over
and never resets the count between projects. If the match comes after two
or more skipped screens, the screen moves to the front of its project and
the project moves to the front of the list. A screen asked for every frame
therefore ends up first. The port's `find_screen` does the same with two
`memmove`s.

The order matters for more than speed. Three screens are in both FRONTB
and INGAMEB:

| hash | name | FRONTB | INGAMEB |
|------|------|-------:|--------:|
| `037f3133` | -- | 14 | 21 |
| `0ce3f7ce` | `BPOPUP_SCREEN_MEMCARD` | 35 | 24 |
| `fa2ac5c6` | `BGF_SCREEN_BOOT_AUTOLOAD` | 36 | 25 |

Which copy a find returns depends on the project order at that moment. The
port must therefore register projects in the order retail loads its
bundles: GLOBALB at boot, FRONTB with the frontend, INGAMEB with the
race. `main.c`'s `addBundle` registers each bundle that has a Flailer
chunk as it loads it. DYNTEX has none, so the race sees three projects.

Retail unloads FRONTB for the race, so during a race only INGAMEB's copies
of those three screens exist. The port keeps FRONTB loaded and its project
on the list. The first find of any INGAMEB screen still moves INGAMEB to
the front, because it passes over every FRONTB screen. The Player's
constructor makes such a find while the race loads: it looks up the score
display on INGAMEB's screen `49c15518`. After that, the shared screens
resolve to INGAMEB's copies, as on retail. From then on, only a find of a
FRONTB-only screen could put FRONTB ahead again.

FindFlailerObject (`0x00143d50`) finds the screen and walks its objects in
file order. It returns the first object whose `NameHash` matches and whose
type is the one asked for (0 means any). An object with the right name and
the wrong type is passed over, not returned as NULL. Names that two
objects on one screen share therefore resolve by type.
FindFlailerObjectByGroup (`0x00143dd8`) is the same walk over `GroupHash`,
resuming after `after` when one is given.

## The methods

Every setter that has a "same" test returns early when the value is
unchanged. Otherwise it writes the value and stamps `DirtyFlag`, which
tells the PS2 renderer which part of the strip to rebuild:

| DirtyFlag | stamped by |
|----------:|------------|
| 2 | SetZ |
| 3 | SetScaleX, SetScaleY (and so SetWidth, SetHeight); ScaleAboutCenter, always |
| 4 | SetTopLeftX, SetTopLeftY, SetClipToPoly |
| 5 | the text's SetFormatOptions, ClearFormatOptions, SetString, SetLanguageID, UpdateLanguageText |
| 6 | the text's SetAlpha; the bitmap's SetAlpha, always |
| 7 | the text's SetColor; the bitmap's SetColor when corner 0 changes |
| 9 | the bitmap's SetRotation |
| 10 | ChangeTexture |

| retail | address | port |
|--------|---------|------|
| FlailerObjectChunk::GetAlpha | `0x00140518` | `flailerobject_get_alpha` |
| ::SetZ | `0x00140568` | `flailerobject_set_z` |
| ::CalculateWidth / Height | `0x00140588` / `0x001405e0` | `flailerobject_get_width` / `_height` |
| ::CalculateWidthFloat / HeightFloat | `0x00140638` / `0x00140688` | `flailerobject_get_width_float` / `_height_float` |
| ::SetAlpha | `0x001406d8` | `flailerobject_set_alpha` |
| ::SetRotation | `0x00140708` | `flailerobject_set_rotation` |
| ::SetVisibility | `0x00140728` | `flailerobject_set_visibility` |
| ::SetColor | `0x00140740` | `flailerobject_set_color` |
| ::SetWidth / SetHeight | `0x00140770` / `0x001407a0` | `flailerobject_set_width` / `_height` |
| ::SetScaleX / Y | `0x001407d0` / `0x001407f8` | `flailerobject_set_scale_x` / `_y` |
| ::ScaleAboutCenter | `0x00140820` | `flailerobject_scale_about_center` |
| ::GetCenter | `0x00140850` | `flailerobject_get_center` |
| ::SetCenterX / Y | `0x001408e8` / `0x00140930` | `flailerobject_set_center_x` / `_y` |
| ::GetTopLeft | `0x00140978` | `flailerobject_get_top_left` |
| ::SetTopLeftX / Y | `0x00140a20` / `0x00140a48` | `flailerobject_set_top_left_x` / `_y` |
| ::SetClipToPoly | `0x00140a70` | `flailerobject_set_clip_to_poly` |
| ::DeleteFlailerStrip | `0x00140b78` | `flailerobject_delete_strip` |
| FlailerTextChunk::SetFormatOptions | `0x00140c68` | `flailertext_set_format_options` |
| ::ClearFormatOptions | `0x00140c80` | `flailertext_clear_format_options` |
| ::SetColor | `0x00140ca0` | `flailertext_set_color` |
| ::SetString | `0x00140e20` | `flailertext_set_string` |
| ::UpdateLanguageText | `0x00140e98` | `flailertext_update_language_text` |
| ::SetLanguageID | `0x00140ea8` | `flailertext_set_language_id` |
| ::SetAlpha / GetAlpha | `0x00140ed0` / `0x00140f08` | `flailertext_set_alpha` / `_get_alpha` |
| ::SetColor(bVector4) | `0x00140f10` | `flailertext_set_color_vector` |
| FlailerBitmapChunk::SetAlpha | `0x001411d8` | `flailerbitmap_set_alpha` |
| ::SetRotation | `0x00141258` | `flailerbitmap_set_rotation` |
| ::SetColor / SetColor(bVector4) | `0x00141288` / `0x001412b0` | `flailerbitmap_set_color` / `_color_vector` |
| ::ChangeTexture | `0x00141350` | `flailerbitmap_change_texture` |
| ::GetAlpha | `0x001413e8` | `flailerbitmap_get_alpha` |
| ::CalculateWidthFloat / HeightFloat | `0x00141448` / `0x00141488` | `flailerbitmap_width_float` / `_height_float` |

The text object's SetWidth and SetHeight (`0x00140f98`, `0x00140fa0`) are
empty. The bitmap's set the scale that makes the texture that many pixels
across.

The wrappers the game calls by (screen, object) hash run from `0x00143e70`
(FlailerPrintf) to `0x00144a28` (FlailerChangeTexture). Each one finds the
object and calls the method. FlailerPrintf, SetTextColor, the format
options and SetLanguageID ask for a text object. ChangeTexture asks for a
bitmap. The rest take any type. Getters on a missing object return 0.
GetTopLeft writes zeros. GetScale and GetBoundingBox write nothing.

Some wrappers do more than call one method:

| retail | address | does |
|--------|---------|------|
| FlailerGetBoundingBox | `0x00144280` | Truncates the top left, then adds GetWidth and GetHeight to get the bottom right |
| FlailerSetCenter / CenterY / CenterX | `0x001445f0` / `0x001446e0` / `0x00144760` | Moves the top left so that the middle is at the point given |
| FlailerGetCenter / CenterY / CenterX | `0x001447e0` / `0x00144860` / `0x00144888` | Returns the middle of the bounding box, with each half truncated |
| FlailerSetGroupPosition | `0x00145308` | Moves every object in the group by the offset that puts the anchor object at (x, y); does nothing if there is no anchor |
| FlailerOffsetGroup | `0x001453d0` | Moves every object in the group by (dx, dy) |
| FlailerSetGroupRenderOnPoly | `0x00145488` | Stores `RenderOnPoly` (+76) in each object with no dirty stamp |
| FlailerSetGroupVisibility | `0x001454e8` | Stores `Visibility` in each object with no DeleteFlailerStrip |
| FlailerSetGroupAlpha | `0x00145560` | Calls SetAlpha on each object of the group |
| FlailerMakeVerticalLine (y1, y2) | `0x001455e8` | Stretches a bitmap down from the smaller y to the larger through `ScaleY` |
| FlailerMakeVerticalLine (top, bottom) | `0x00145690` | The same, from 4 below the bottom of `top` to 3 below the top of `bottom` |

The second MakeVerticalLine finds both end objects before it uses either,
and does nothing unless both exist. Position, offset and RenderOnPoly
visit the group's screen list from the end (through the bTNode's `Prev`),
and the port does the same. Visibility and alpha visit it from the
start.

### Retail's own, kept

- **GetCenter adds half the *width* to both coordinates.** It asks for
  the height and discards it. The callers were laid out against this
  behaviour.
- **FlailerSetCenterX centres X using the object's *height*.**
  FlailerSetCenter and FlailerSetCenterY use the right size for each axis.
- **The text's ScaleAboutCenter tests the format flags in the order LEFT
  (2), CENTER (4), RIGHT (1).** It starts from half-sizes, hw = width /
  (2 · ScaleX) and hh = height / (2 · ScaleY). Each case moves the object
  as follows:

  | flag | moves Y by | moves X by |
  |------|------------|------------|
  | LEFT | hh · (ScaleY − s) | +hw · (ScaleX − s) |
  | CENTER | hh · (ScaleY − s) | nothing |
  | RIGHT | hh · (**ScaleX** − s) | −hw · (ScaleX − s) |
  | none | nothing | nothing |

  The RIGHT case uses `ScaleX` for Y. Every case then scales the object.
  The bitmap's ScaleAboutCenter moves X and Y by half the texture times the
  change in each scale.
- **A text's GetTopLeft takes `FORMAT_CENTER` before `FORMAT_RIGHT`.** A
  centred text's X is its middle, and a right-aligned text's X is its right
  edge. When both flags are set, centre applies. A bitmap's X is always its
  left edge.
- **The text's SetColor keeps the chunk's alpha.** Only SetAlpha changes
  the alpha. The bitmap's SetColor writes all four corners, alpha
  included, but checks only corner 0 to decide whether anything changed.
- **The bitmap's SetAlpha stamps `DirtyFlag` 6 even when nothing
  changes.** Corner −1 sets all four corners.
- **SetString clears `LanguageID`**, because the text is now its own. It
  then cuts the string at `MaxChars - 1`. SetLanguageID empties the
  string, and the string is looked up when it is drawn.
- **SetVisibility stores whatever byte it is given.** Only 0 releases the
  strip.
- **FlailerSetGroupVisibility searches for the group's first object once
  before its loop and discards the result.** That search is kept. It
  cannot change the order, because the loop's own first search finds the
  screen at the head where the discarded one left it (see the checks).
- **The float-to-int conversions truncate** (`cvt.w.s`, through
  `ee_trunc_w`). CalculateWidth and CalculateHeight are the float versions
  truncated. FlailerSetCenter truncates both sizes before it moves
  either edge.

### Where the port departs

- **The bitmap's SetAlpha with a corner outside −1..3.** Retail indexes
  `Colors` unchecked and writes past the array into the UVs. No caller in
  the game does this, and the port changes nothing.
- **FlailerPrintf's buffers.** Retail formats into two 128-byte buffers,
  `0x00333f80` (by hash) and `0x00334000` (by chunk), with an unbounded
  bVSPrintf, so a longer result overruns into the next buffer. The port
  uses `vsnprintf`, which cuts a longer result but still returns its full
  length.
- **SetString's copy.** Retail copies `MaxChars` bytes from the source
  whatever its length. The port stops at the NUL. Only the characters up to
  the NUL are ever read back.
- **The strips.** FlailerStrip is the PS2's cached geometry. `uirender.c`
  builds nothing ahead of time, so `pFlailerStrip` stays 0 (it is 0 on the
  disc too) and DeleteFlailerStrip has nothing to free.
- **FlailerGetCenter on a missing object.** Retail returns whatever was on
  its stack, because GetBoundingBox wrote nothing. The port returns 0, 0.
- **GetTextureInfo's cache.** Retail looks the texture up once and keeps
  the pointer in `pTextureInfo` (+84). The port asks the renderer every
  time and leaves the word as the disc has it, so an override that changes
  a texture's size takes effect at once.

## The seams

A text object's width comes from its font's glyphs, and a bitmap's from
its texture. The renderer owns both, so the size questions are function
pointers that `main.c` binds to `uirender.c`:

| seam | retail | answers | bound to |
|------|--------|---------|----------|
| `gFlailerTextScaledWidthFn` | GetScaledWidth `0x00140d30` | the advances of the shown string (the language string when `LanguageID` ≠ 0) × `ScaleX` | `uirender_text_scaled_width` |
| `gFlailerTextScaledHeightFn` | GetScaledHeight `0x00140cd8` | the font's height × `ScaleY` | `uirender_object_height` |
| `gFlailerBitmapTextureSizeFn` | GetTextureInfo `0x00141368` | the texture's Width and Height (+36, +38), an override's if it has one | `uirender_texture_size` |

Everything a bitmap measures is made from the texture's size: the width and
height floats, SetWidth, SetHeight, ScaleAboutCenter and MakeVerticalLine.
An unbound text seam answers 0. An unbound or failing texture seam has
these effects:

- The bitmap's sizes are 0.
- SetWidth and SetHeight do nothing.
- ScaleAboutCenter scales without moving.

On the PS2, a missing texture would read through NULL.

`main.c` also binds the race's own seams to the runtime: the Player's HUD
lookups, the countdown's (`rcstates.h`) and the NIS overlay's BUSTED.

## Not ported here

- **FlailerRenderManager**, its eight-slot table of visible screens, and
  the chunk version of FlailerSetScreenVisibility (`0x00145c50`). Screen
  visibility is still `main.c`'s hook over `BUIScreen::visible`.
- **The bTNode words.** The loader relinks them on the PS2. The port walks
  `bui.c`'s tables, which hold each screen's objects in the same file
  order, and leaves the node words as they are on disc.

## The checks

`tools/flailer_check.py` runs retail's own LoaderFlailerChunk on the
Flailer chunks of GLOBALB, FRONTB and INGAMEB, with INGAMEB loaded twice so
that every INGAMEB screen is in two projects. It then runs the lookups,
methods and wrappers in `retail_model.RetailEmu`, with the four sizes
stubbed by the same formula on both sides. `tools/src/flailer_test.c`
runs `flailer.c` over `bui.c` on the same files.

The checker compares each call's result, the bytes of the object it
touched, the project and screen orders, and periodic CRCs of every screen
and object. The script:

1. Finds screens both near and far through the lists.
2. Runs every method over every object on the HUD's screen (`f1f1f8e5`)
   and over every seventh object elsewhere.
3. Tests names that two objects on one screen share.
4. Walks each screen's first four groups by type.
5. Runs the wrappers on objects and screens that exist and on ones that
   do not.

6. Runs the size questions (SetWidth, SetHeight, ScaleAboutCenter under
   each alignment, MakeVerticalLine) with values that change something and
   values that do not. It also pokes `pTextureInfo` and the bitmap corners.

The result: 54,104 operations, 120,233 lines, 0 differ.

`--mutate` runs 110 mutations of `flailer.c`. 106 are caught. The other 4
are equivalent by construction:

- **group-after-restart.** This mutation restarts the walk when `after`
  belongs to another screen. Retail would loop forever on such an `after`,
  and every caller passes the object the last call returned, so the script
  cannot put the case to retail.
- **group-no-discarded-search.** The discarded search leaves the screen at
  the head of its project and the project at the head of the list. The
  loop's own first search therefore passes nothing and moves nothing.
- **visibility-deletes-always.** `pFlailerStrip` is always 0, so
  DeleteFlailerStrip has nothing to free.
- **strip-kept.** The same reason: there is no strip to keep.
