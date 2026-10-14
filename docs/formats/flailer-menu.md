# Flailer menus -- the behaviour half of the UI

`docs/formats/flailer-ui.md` describes what is on disc: screens, bitmaps,
text, layers. This describes what is **not** on disc. `FlailerMenu`,
`FlailerMenuItem` and `FlailerScreen` are in the `.mdebug` type info but no
chunk of any of them ships, because a menu is assembled at runtime out of
objects the screen already contains. Everything below was decompiled from
`PS2 Files/NFSHP2.ELF`; every claim names the address it came from.

Read this together with `docs/mdebug_structs.txt`, which has the class
layouts verbatim.

## Where a menu comes from

There is exactly **one** call site that builds a menu --
`Activate__13FlailerScreen+0x3c` (`0x00165c5c`) -- and it passes a literal
format string at `0x00295DD0`:

```
MENUITEM_%d
```

So every menu in the game is discovered the same way. `FlailerMenu`'s
constructor (`0x001653b8`) loops `n` from 0 to 15, formats the name, hashes
it with `bStringHash` (`0x0023b280`), and asks the screen for a **text**
object of that name:

```
00165410  move   a1,s3                     ; the "MENUITEM_%d" literal
00165414  jal    bSPrintf__FPcPCce
00165418  move   a2,s2                     ; n
0016541c  jal    bStringHash__FPCc
00165424  lw     a0,20(s1)                 ; Menu->ScreenHash
0016542c  jal    FindFlailerObject__FUiUi17FlailerObjectType
00165430  addiu  a2,zero,1                 ; FlailerObjectType TEXT
00165434  beql   v0,zero,0x00165488        ; absent -> skip this index
...
00165488  slti   v0,s2,16                  ; all sixteen, no early exit
```

Consequences worth stating plainly:

* Menu items are **text objects named `MENUITEM_0` .. `MENUITEM_15`**. There
  is no other mechanism and no per-screen table.
* Gaps are allowed. The loop never breaks early, so a screen may define
  `MENUITEM_1`, `MENUITEM_2`, `MENUITEM_3` and nothing else -- which is
  exactly what `NEW_MAIN_MENU` does (`0x52e039f3`, `0x52e039f4`,
  `0x52e039f5`, the three hashes `OnHighlight__11NewMainMenu` switches on).
* `FlailerMenuItem::ItemID` is `n`, the index in the name, not the position
  in the list.
* Items come from `MenuThingsSlotPool` (`gp-21864`) via `bOMalloc`.

The last thing the constructor does is look up the highlight bar -- a
**bitmap** this time:

```
001654a4  lui    a1,0x27c5
001654a8  ori    a1,a1,-2901               ; 0x27c5f4ab == bhash("HIGHLIGHT_BAR")
001654ac  jal    FindFlailerObject__FUiUi17FlailerObjectType
001654b0  addiu  a2,zero,2                 ; BITMAP
001654b4  sw     v0,32(s1)                 ; FlailerMenu::HighlightBar
```

`FindFlailerObject` (`0x001419c8`) matches `NameHash`, and matches `Type`
only when the type argument is non-zero -- type 0 means "any".

That lookup never succeeds on this disc. **No object called
`HIGHLIGHT_BAR` exists in any bundle** -- all 2,252 objects across every
`.BUN`/`.BIN` were scanned for the hash and none matches -- so
`FlailerMenu::HighlightBar` is always NULL. Which is the data-side half of
why `AlignBar` is dead code (see below): there is nothing to align.

Running the discovery rule over the disc finds menus on 46 screens: 29 in
`FRONTEND/FRONTB.BUN` and 17 in `GLOBAL/INGAMEB.BUN`, none in
`GLOBAL/GLOBALB.BUN`. They range from one item to ten. `NEW_MAIN_MENU` has
three (`MENUITEM_1`, `2`, `3` -- note it does not use `MENUITEM_0`),
`PAUSE_DISPLAY` and `PAUSE_OPTIONS` have ten each.

## The classes

Offsets are bytes, taken from `docs/mdebug_structs.txt` and confirmed
against the code that uses them.

`FlailerMenu`, 36 bytes:

| off | field | notes |
|----:|-------|-------|
| 0 | `MenuItems.Head` | `bTList`; the empty-list sentinel is the menu itself |
| 4 | `MenuItems.Tail` | |
| 8 | `CurrentMenuItem` | |
| 12 | `Callback` | `void (*)(ScreenMessage, ScreenCallbackData*)` |
| 16 | `pParentScreen` | |
| 20 | `ScreenHash` | copied from the screen |
| 24 | `FilterPort` | copied from the screen |
| 28 | `NumMenuItems` | |
| 32 | `HighlightBar` | the `HIGHLIGHT_BAR` bitmap chunk, or NULL |

`FlailerMenuItem`, 40 bytes:

| off | field | notes |
|----:|-------|-------|
| 0 | `Next` | `bTNode`; the sentinel is the owning menu |
| 4 | `Prev` | |
| 8 | `State` | bit 0 = enabled, bit 1 = highlighted |
| 12 | `ItemHash` | `bhash("MENUITEM_n")` |
| 16 | `ItemID` | `n` |
| 20 | `SavedScaleX` | never written by anything in this build |
| 24 | `SavedScaleY` | likewise |
| 28 | `SavedColor` | the text object's authored `Color` |
| 32 | `FilterPort` | |
| 36 | `ScreenHash` | |

`FlailerScreen`, 28 bytes: `Menu` +8, `SavedMenuItemNumber` +12,
`FilterPort` +16, `ScreenHash` +20, `Callback` +24.

`ScreenCallbackData`, 16 bytes: `ItemHash` +0, `Port` +4, `Param` +8,
`Noise` +12. Every callback gets one of these, always zeroed first with
`memset` and then filled in.

The constructor (`0x00164b28`) sets `State = 1`, so **items start enabled
and unhighlighted**, and calls `ResetSavedParameters` (`0x00164c00`), which
is one line: `SavedColor = textChunk->Color`.

## State, and what it does to the colour

`SetMenuItemState` (`0x00164fb8`) and `ClearMenuItemState` (`0x001650e8`)
are the only writers of `State`. Both take a `FlailerBitmapChunk*` third
argument and **neither uses it** -- `a2` is overwritten with the constant 1
in the first instruction, for the `FindFlailerObject` call that fetches the
item's text object.

The colour globals are six gp-relative words, and they are components, not
packed colours: `HighlightR/G/B` at `gp-21832/-21828/-21824` and
`GrayedR/G/B` at `gp-21820/-21816/-21812`. Nothing in the image writes any
of them -- `SetIgnoreJoystick` (`0x00164aa0`) is the only writer of any
global in this group -- so their initialised values in `.data` are what the
game runs with:

| global | value | meaning |
|--------|------:|---------|
| `HighlightR` | 128 | full, on the GS 0..128 scale |
| `HighlightG` | 64 | half |
| `HighlightB` | 0 | |
| `GrayedR/G/B` | 24 | a dark neutral, about `0x30` once doubled |
| `LoopingMenuScrollMode` | 1 | so wrapping-with-skip is the shipped behaviour |
| `IgnoreJoystick` | 0 | |

The highlight is therefore the orange the frontend uses throughout, and it
is a constant -- screens do not get to choose it.

Net effect:

| call | resulting text colour |
|------|-----------------------|
| `SetMenuItemState(HIGHLIGHT)` | `HighlightR + (G<<8) + (B<<16)` |
| `SetMenuItemState(ENABLED)` | `SavedColor` |
| `SetMenuItemState(ENABLED+HIGHLIGHT)` | highlight |
| `ClearMenuItemState(HIGHLIGHT)` | `SavedColor` |
| `ClearMenuItemState(ENABLED)` | `GrayedR + (G<<8) + (B<<16)` |
| `ClearMenuItemState(ENABLED+HIGHLIGHT)` | grayed |

`SetMenuItemState` contains a branch that writes the *grayed* colour when
both bits are being set (`0x00165014`), but the second half of the function
then unconditionally overwrites it with the highlight colour, so that store
never survives. It is dead, and a reimplementation should not copy it.

**Alpha is preserved, not written.** `SetColor__16FlailerTextChunk`
(`0x0013e820`) is:

```
0013e828  lw     a0,68(a2)          ; the chunk's current Color
0013e830  ori    v0,v0,-1           ; v0 = 0x00ffffff
0013e834  and    a1,a1,v0           ; new RGB only
0013e838  and    v1,a0,0xff000000   ; old alpha
0013e83c  or     v1,v1,a1
0013e848  sw     v1,68(a2)
0013e84c  sb     v0,19(a2)          ; DirtyFlag = 7
```

which is why the `0x80000000` the highlight path ORs in (`lui a2,0x8000` at
`0x00165044`) is irrelevant -- it is masked straight back off. A port that
writes the whole word instead would make every highlighted label opaque
regardless of what the screen authored.

Note also that this writes **into the loaded chunk**. There is no separate
runtime colour; the renderer reads `FlailerTextChunk::Color` out of the
bundle every frame, and `DirtyFlag = 7` is what tells the render manager to
rebuild the strip.

## Navigation

`MoveToNextItem` (`0x001659a8`) and `MoveToPrevItem` (`0x00165a90`) are
mirror images. Both branch on `LoopingMenuScrollMode` (`gp-21844`):

```
001659c8  lw     v0,-21844(gp)
001659cc  beql   v0,zero,0x00165a38      ; == 0: the simple path
001659d0  lw     s0,0(v1)                ; next = current->Next
...
00165a38  xor    v0,s0,s1
00165a3c  movz   s0,v1,v0                ; next == sentinel ? stay put
```

* `LoopingMenuScrollMode == 0`: step one node. If that lands on the
  sentinel you are at the end, so stay where you are. **Disabled items are
  not skipped in this mode.**
* `LoopingMenuScrollMode != 0`: step, wrapping through the sentinel to the
  head, and keep stepping while `(State & 1) == 0`, giving up if you come
  all the way back to where you started.

If the item actually changed: `UnHighlight(old)`, store the new
`CurrentMenuItem`, `Highlight(new)`.

`Highlight` (`0x00164d50`) is `SetMenuItemState(HIGHLIGHT)` followed by
`Callback(MENUITEM_HIGHLIGHT, {ItemHash, FilterPort, 0, 0})` and then
`MakeFrontendSound(data.Noise)` -- so the *callback* chooses the sound by
writing `Noise`, and gets silence by leaving it zero. `UnHighlight`
(`0x00164de0`) is the same shape with `ClearMenuItemState(HIGHLIGHT)` and
`MENUITEM_UNHIGHLIGHT`.

`FlailerMenu::Activate` (`0x001655a0`) sends `MENUITEM_ACTIVATE` to every
item, then walks forward from `CurrentMenuItem` to the first item with bit 0
set and highlights it.

`SetCurrentItemNumber` (`0x00165530`) is `bList::GetNode(n)`, falling back
to the head when `n` is out of range and to NULL when the list is empty. It
does not highlight anything; `Activate` does that afterwards.

## Input

The frontend registers handlers for a fixed set of sixteen events, for ports
0 and 1, in `AddNormalMenuJoyHandlers__17FlailerScreenList` (`0x00167cc0`).
The table is `MenuJoyEvents` at `0x002f3030`:

```
START SELECT SCROLL_UP SCROLL_DOWN SCROLL_LEFT SCROLL_RIGHT MENU_SELECT
MENU_BACK MENU_HELP MENU_L1 MENU_R1 MENU_SQUARE ANALOG_LEFT ANALOG_RIGHT
ANALOG_DOWN ANALOG_UP
```

Events arrive at `FlailerScreenList`, which routes to the active
`FlailerScreen`, which routes to its `FlailerMenu`, which routes to the
current `FlailerMenuItem`. Each level handles what it owns and passes the
rest down. All three levels start by testing `IgnoreJoystick`
(`gp-21852`) and returning if it is set, and all three ignore key-up.

**`FlailerScreen::JoyHandler` (`0x00165dc0`)** filters on `FilterPort`
(`-1` means any port), then:

| event | message |
|-------|---------|
| `START` (7) | `SCREEN_START_BUTTON` (13); `Param == 1` consumes it |
| `SELECT` (8) | no message -- cycles `LanguageManager` when `TranslationEnable` (`gp-16768`) is on, then `MakeScreenDirty` |
| `MENU_L1` (13) | `SCREEN_L1` (15) |
| `MENU_R1` (15) | `SCREEN_R1` (16) |

then calls the menu's handler.

**`FlailerMenu::JoyHandler` (`0x00165820`)** builds one
`ScreenCallbackData` seeded with the *current item's* `ItemHash` and the
port, and maps:

| event | message | default `Noise` |
|-------|---------|-----------------|
| `SCROLL_UP` (3), `ANALOG_UP` (20) | `MENUITEM_PAD_UP` (8) | `FE_SOUND_MENU_UP` (3) |
| `SCROLL_DOWN` (4), `ANALOG_DOWN` (21) | `MENUITEM_PAD_DOWN` (9) | `FE_SOUND_MENU_DOWN` (4) |

It calls the callback *first*. If the callback sets `Param` non-zero the
event is consumed and the selection does not move; otherwise
`MoveToNextItem`/`MoveToPrevItem` runs and `MakeFrontendSound(Noise)` plays
whatever the callback left there. Unhandled events fall through to the item.

**`FlailerMenuItem::JoyHandler` (`0x001651d8`)** is a jump table at
`0x00295D90`, indexed by `event - 5`, fifteen entries wide:

| event | message | `Noise` |
|-------|---------|---------|
| `SCROLL_LEFT` (5), `ANALOG_LEFT` (18) | `MENUITEM_PAD_LEFT` (6) | 0 |
| `SCROLL_RIGHT` (6), `ANALOG_RIGHT` (19) | `MENUITEM_PAD_RIGHT` (7) | 0 |
| `START` (7), `MENU_SELECT` (9) | `MENUITEM_SELECT` (1) | `FE_SOUND_MENU_SELECT` (5) |
| `MENU_SQUARE` (17) | `MENUITEM_SQUARE` (10) | 0 |

Everything else -- including `SELECT`, `MENU_CANCEL`, `MENU_BACK`,
`MENU_HELP`, L1/L2/R1/R2 -- returns without doing anything at this level.

Note `START` reaches the item as `MENUITEM_SELECT` *after* the screen has
already had it as `SCREEN_START_BUTTON`, unless the screen consumed it.

## Screen activation

`FlailerScreen::Activate` (`0x00165c20`):

1. Build the `FlailerMenu` if `Menu` is NULL -- which it is every time,
   because `UnActivate` deletes it (below). Each activation rediscovers the
   items and reads each label's `SavedColor` afresh.
2. Send `SCREEN_ACTIVATE` (11) with `Param = -1`. If the callback writes
   anything else into `Param`, that becomes `SavedMenuItemNumber`, which is
   how a screen picks which item starts highlighted.
3. `MakeFrontendSound(data.Noise)`.
4. `SetCurrentItemNumber(SavedMenuItemNumber)`, then `Menu->Activate()`.

`FlailerScreen::UnActivate` (`0x00165d00`; `0x0016a940` in the retail
image) undoes it:

1. `SavedMenuItemNumber = Menu->GetCurrentItemNumber()`, so a screen whose
   callback leaves `Param` at -1 comes back on the item it was left on.
2. `Menu->UnActivate()`: the current item's `UnHighlight`, then
   `MENUITEM_UNACTIVATE` to every item.
3. `delete Menu` and `Menu = NULL`. `~FlailerMenu` (`0x001654e0`) deletes
   the item list, and `~FlailerMenuItem` (`0x00164b88`; `0x001697a0`
   retail) finds the item's text object and stores `SavedColor` back into
   its `Color` -- the whole word, with no `SetColor` and no `DirtyFlag`.
4. `SCREEN_UNACTIVATE` (12), then `MakeFrontendSound(data.Noise)`.

Step 3 matters to any screen that grays a label and leaves with it gray.
The race setups all run on one Flailer screen and each grays the rows past
its own, so a setup with more rows reached after one with fewer -- Knockout
Setup after Single Race -- has labels that were left gray. The chunk is
shared by every activation: without the restore the new menu reads gray as
the authored colour, and enabling the item recolours it gray. The port had
exactly that until `bmenu_close`, which main.c's leaveScreen hook calls
after `bmenu_unactivate`.

## The highlight bar is not moved by the menu system

`AlignBar__15FlailerMenuItem` (`0x00164e70`) exists, computes a sensible
position, and **has zero callers** -- `mipsdis.py --callers` finds none, and
the only four references to its address in the image are in the symbol and
debug sections. `Highlight` does not call it. So on this disc the generic
menu code never touches `FlailerMenu::HighlightBar` after looking it up --
and as noted above, that pointer is NULL on every screen anyway, because no
bundle contains a `HIGHLIGHT_BAR` object. Two independent reasons, one from
the code and one from the data, and they agree.

Screens move their own decoration instead. `NEW_MAIN_MENU` does it in
`OnHighlight__11NewMainMenu` (`0x00203970`), which drives a
`tHighlightAnimation` (`0x00232318`) -- a scale/alpha pulse on the item text
with its own timing globals -- and then sets the help blurb for that item.

What `AlignBar` *would* do, if a port wants the behaviour:

```
obj  = FindFlailerObject(item->ScreenHash, item->ItemHash, 0)   ; any type
bar->X = (int)(obj->X - 2.0)
bar->Y = (int)(obj->Y + GetHeight(obj)/2 - CalculateHeight(bar)/2)
; and if obj is TEXT with FormatOptions & 0x04 (CENTER):
bar->X = (int)(obj->X - CalculateWidth(bar)/2)
```

Both coordinates are rounded through `cvt.w.s` and converted straight back
to float, so the bar always lands on an integer pixel. `GetWidth(obj)` is
called at `0x00164ec8` and its result is discarded before it is ever used --
another shipped bug, harmless only because nothing calls the function.

## The port

`3DS Files/source/bmenu.[ch]` implements all of the above except the
callback-driven per-screen decoration: item discovery, state and colour,
looping and non-looping navigation, the three-level input routing, and the
`AlignBar` geometry (opt-in, since the original never calls it).

Because colours live in the chunk, `bmenu` writes them back through
`bui_set_text_color`, which reproduces `SetColor`'s alpha-preserving mask,
and `bmenu_close` through `bui_put_text_color`, the whole word as the
item destructor stores it. That is safe: `UIBundle::data` is a writable heap copy of the bundle, and
`bui.c` keeps pointers into it rather than copying object payloads.

`tools/bmenu_check.py` carries a second implementation of the same rules in
Python and runs an identical event script over both, diffing the whole
transcript -- every callback message, every item's state and live colour
after every step, and last a label left gray, `bmenu_close` and the colours
a second menu reads. 3,390 lines on `FRONTB.BUN` and 1,874 on `INGAMEB.BUN`,
0 differ. That catches a rule transcribed wrongly into C; it cannot catch a
rule read wrongly out of the disassembly, because both sides were written
from the same notes. For that there is the picture:

```
python3 tools/flailer_render.py extracted/FRONTEND/FRONTB.BUN 0 \
        --also extracted/GLOBAL/GLOBALB.BUN \
        --language extracted/LANGUAGES/FE_ENGLISH.BIN \
        --menu-item 1 --gray 3 -o menu.png
```

which applies the same recolouring to a composited screen. `NEW_MAIN_MENU`
comes out with the highlighted entry in the game's orange and the grayed one
in a dark neutral, which is what the shipped `HighlightR/G/B` of 128/64/0
and `GrayedR/G/B` of 24 are supposed to look like once the GS 0..128 scale
is doubled.

| symbol | address | role |
|--------|---------|------|
| `__11FlailerMenu...` | `0x001653b8` | discovers `MENUITEM_0..15` |
| `__15FlailerMenuItem...` | `0x00164b28` | `State = 1`, saves the colour |
| `_$_15FlailerMenuItem` | `0x00164b88` | puts the saved colour back |
| `_$_11FlailerMenu` | `0x001654e0` | deletes the item list |
| `UnActivate__13FlailerScreen` | `0x00165d00` | saves the item, deletes the menu |
| `Activate__13FlailerScreen` | `0x00165c20` | the only menu construction site |
| `Activate__11FlailerMenu` | `0x001655a0` | activates items, highlights the first enabled one |
| `SetMenuItemState__15FlailerMenuItem...` | `0x00164fb8` | set bits, recolour |
| `ClearMenuItemState__15FlailerMenuItem...` | `0x001650e8` | clear bits, recolour |
| `Highlight__15FlailerMenuItem...` | `0x00164d50` | + `MENUITEM_HIGHLIGHT` |
| `UnHighlight__15FlailerMenuItem...` | `0x00164de0` | + `MENUITEM_UNHIGHLIGHT` |
| `MoveToNextItem__11FlailerMenu` | `0x001659a8` | |
| `MoveToPrevItem__11FlailerMenu` | `0x00165a90` | |
| `AlignBar__15FlailerMenuItem...` | `0x00164e70` | dead in this build |
| `JoyHandler__13FlailerScreen...` | `0x00165dc0` | screen-level events |
| `JoyHandler__11FlailerMenu...` | `0x00165820` | up/down |
| `JoyHandler__15FlailerMenuItem...` | `0x001651d8` | left/right/select/square |
| `FindFlailerObject__FUiUi...` | `0x001419c8` | hash + optional type lookup |
| `SetColor__16FlailerTextChunkUi` | `0x0013e820` | RGB only, keeps alpha |
| `MenuJoyEvents` | `0x002f3030` | the sixteen registered events |
