# event-tree-view -- the career's screen, "View Event Tree"

The career is played from one screen, "View Event Tree" (`0x147f8a59`),
reached from World Racing's "World Championship" (the Championship tree)
and Hot Pursuit's "Ultimate Road Racer" (the Hot Pursuit tree). The screen
draws the tree's 32 events as leaves joined by lines, moves a highlight
between them, zooms and pans, shows the highlighted event's details, and
starts the event.

Retail has it in EventTreeView.obj, `0x001f5d50` .. `0x001fbb00`, with
ModelViewer.obj's tCarModelViewer and tTrackModelViewer (`0x0023c108` ..
`0x0023c810`) for the rewards. The demo ELF has most of it under its
names, at `0x001e6338` .. `0x001ea5b8`; retail rewrote a good part and
added 6.6 KB of code with no demo twin. This file is the decode (TASKS
69a); the port is `eventtreeview.{c,h}` (69b to 69e).

EventTree.obj's own BuildTree, FlushTree, Update, Render and
FindNeighbours are dead in retail: nothing calls them. The tree drawn is
this screen's.

## The callback

`tEventTreeView::Callback` (`0x001fb218`) is the screen's FlailerScreen
callback, on `pInstance` (gp-16772):

| message | what |
|---|---|
| 11 (create) | `bMalloc(2144)`, the constructor with the screen's hash (data+0) and `FrontendDatabase::GetEventTree` |
| 12 (destroy) | the destructor (flags 3), `pInstance` 0 |
| 19 (render) | `OnRender` |
| 18 (tick) | `OnTick` |
| any other | `HandleMessage(msg, data)` |

The demo's object was 1456 bytes; retail's is 2144.

## Already ported

- `FormatEventDescription` and its token (`0x001f5dd0`, `0x001f5f88`):
  `eventrace.c`. `FormatStatus` (`0x001f60e8`) and `FormatReward`
  (`0x001f6220`) were not; they are in `eventtreeview.c`.
- DataEventSelectScreen (`0x001f5ce8` .. `0x001f5d50`): `fred.h`,
  `fredevent.c`.
- The events-opened list (`0x001f7280` .. `0x001f7458`): `fredevent.c`
  (`TheEventsOpened`, `0x0031b7b0`).
- `MakeEventCarsAvailable` (`0x00183d80`), `ContinueMultiTrackEvent`
  (`0x001843e8`), `GetEventTree` (`0x00185568`): `fredevent.c`.
- `tAnimatedBlurb` (`0x002491b0`): `banim.c`. `StillCameraMover`
  (`0x0015e6a0`): `stillcam.c`.

## tEventLeaf (96 bytes)

One per event, made by the view's constructor from the tree's EventInfo
records in order.

| offset | field | |
|---|---|---|
| 0 | bTNode next, prev | the view's `Leaves` |
| 8 | `nIndex` | `EventTree::GetEventIndex(number)` |
| 12 | `ScaleFactor` | 1.0 |
| 16 | the reward's name | retail; the car's short name or the track's name, translated |
| 20 | `pInfo` | the EventInfo |
| 24 | `pTree` | |
| 28 | `Generation` | the parents' chain length (CalculateGeneration) |
| 32 | `Parents` | bPList of leaves: the events whose goals open this one |
| 40 | `Children` | bPList of leaves: the events this one opens |
| 48 | `Center` | x the default H position, y the default V, z 0, w 1 |
| 64 | `MasterCenter` | the template bitmap's centre (its top left + half its size) |
| 72 | `MasterFlailerObject` | the template's bitmap `0xa3b23510` |
| 76 | `FlailerObjects` | bPList: every object of group `0xa01bcdc6` |
| 84 | `pTextureInfo` | the event's icon by status (`0x001f75f0`) |
| 88 | `TrackModel` | tTrackModelViewer for a track reward, else NULL |
| 92 | `CarModel` | tCarModelViewer for a car reward, else NULL |

**The constructor** (`0x001f6fa0`, `(screen, info, tree)`): the three
lists empty, `pInfo` and `pTree`, the icon (`0x001f75f0`), `nIndex`, the
default H and V positions into `Center` (z 0, w 1), the template bitmap
`0xa3b23510` on the screen and its texture set to the icon's
(FlailerChangeTexture with `pTextureInfo+32`), `MasterCenter` from its
top left and half its width and height, then every object of group
`0xa01bcdc6` on the screen into `FlailerObjects`
(FindFlailerObjectByGroup, from NULL, then from each). `Generation`,
`TrackModel` and `CarModel` 0, `ScaleFactor` 1. Then the event's first
reward (GetReward 0): a car (type 0) makes a 28-byte tCarModelViewer
and the name is `GetTranslatedString(GetShortName(car type))`; a track
(type 1) a 4-byte tTrackModelViewer and the name is
`GetTranslatedString(GetTheRightTrackLanguageID(track, direction))`.

**The destructor** (`0x001f7200`): the two viewers deleted, then the
three lists.

**The icon** (`0x001f75f0`): by the tree's type (`pTree+8`), 0 for
Championship and 1 for Hot Pursuit, and the event's status (GetStatus
with no goal), through the jump tables at `0x002ba820` and `0x002ba840`:

| status | Championship | Hot Pursuit |
|---|---|---|
| 0 | `SPEED_EVENT_PANEL_LOCKED` | `PURSUIT_EVENT_PANEL_LOCKED` |
| 1, 2, 3 | `SPEED_EVENT_PANEL_UNLOCKED` | `PURSUIT_EVENT_PANEL_UNLOCKED` |
| 4 | `SPEED_EVENT_PANEL_WON` | `PURSUIT_EVENT_PANEL_WON` |
| 5, other | none | none |

With no name (status 5 or above, or a tree type above 1) the icon stays
as it was. Else `pTextureInfo = GetTextureInfo(bStringHash(name), 1, 0)`.

**Small methods:**

- `GetDefaultHPos` (`0x001f7710`): the float table at `0x0031b240`
  indexed by `nIndex`.
- `GetDefaultVPos` (`0x001f7730`): `Generation * gp-16820`.
- `IsFogOfWarred` (`0x001f7748`): the event is locked (status 0) and no
  parent's status is above 0.
- `IsVisible` (`0x001f77f0`): event 31 when not locked; event 32 (the
  Ultimate) when not locked or when either tree's event 31 is passed
  (4); every other event always.
- `GetEventIconTexture` (`0x001f78b0`): `pTextureInfo`. For a locked
  event 32 it asks the tree's event 31's status first and ignores it.
- `GetBoundingBox` (`0x001f7ee8`, `(min, max)`): `Center` set again from
  the default positions, then `Center` -/+ half the template's width and
  height.
- `CalculateGeneration` (`0x001f7fa8`): how many first-parent links lead
  up from the leaf.
- `0x001f7708`: the reward's name. `0x001f7918`: the event's state
  unlocked (EventInfo::UnlockState) and the icons of the leaf and each
  child set again.
- `0x001f7480` (`(leaf, list)`): TheEventsOpened for StartEvent: the list
  cleared, then for each child, each of the child's goals that names this
  event (and the child is not event 32) added with the child's number;
  and when this is the last event open (`0x00200f98`), the event's own
  objective with 32.

**Render** (`0x001f7978`, `(matrix, alpha)`): nothing unless visible.
`Center` from the default positions; the colour table `0x0031b590`, or
`0x0031b5a0` when fogged (both are (128, 128, 128, 128) in retail; see
"The colours"). The matrix's four rows are scaled by gp-16812.
Each object in `FlailerObjects`:

- a bitmap (type 2) is copied, moved by the leaf's `Center` less
  `MasterCenter` (its own centre in the template, so the copy keeps its
  place relative to the template's bitmap) through the matrix, scaled by
  the matrix's x and y scale, and drawn (RenderFlailerBitmap, at the
  alpha); the template bitmap itself (`0xa3b23510`) draws the icon's
  texture.
- a text (type 1) is copied, put at the leaf's `Center` through the
  matrix, its centre Y set to it, scaled likewise, flag 0x10 set; the
  number text `0x16b7d629` prints the event's number (`0x00331748`); its
  alpha is the colour table's fourth float; drawn with RenderFlailerText.

Then a line to the first parent: the two bounding boxes, a vertical line
(`0x001f6df8`) from 5 px right of this leaf's top to the midpoint
between this top and the parent's bottom, at this leaf's x, through the
matrix, coloured `0x0031b560` when the event is not locked and
`0x0031b570` when it is; and a dot (`0x001f6f00`) at the end. And a line
to the first child, when it is visible: from the child's top up to the
midpoint below this leaf's bottom, coloured by this event passed (4) or
not, 16 px left of the child's top (5 px in the Hot Pursuit tree), and a
dot.

## tEventGroup (40 bytes)

The demo's group was 16 bytes (a node and `Members`). Retail's also
holds two generation lists and the bars that join the members:

| offset | field |
|---|---|
| 0 | bPNode next, prev (the view's `Groups`) |
| 8 | `Members`, bPList of leaves |
| 16 | the members of the lowest generation |
| 24 | the members of the highest generation |
| 32 | the bars, a list of 24-byte nodes: x1 (+8), x2 (+12), y (+16), colour* (+20) |

- `IsMember` (`0x001f7fe8`): the leaf is in `Members`.
- `MaybeAdd` (`0x001f84c8`): adds the leaf unless it is a member.
- `0x001f8020`: the two generation lists emptied and filled again: the
  members whose `Generation` is the lowest of the members, and those
  whose is the highest, in `Members` order.
- `0x001f81b8`: `Members` sorted by `Center.x` (bList::Sort,
  `0x001fb9a0`, with the comparator `0x001f8188`), then a bar between
  each pair of neighbours: x1 the first's `Center.x`, x2 the next's, y
  the mean of the first low member's and the first high member's
  `Center.y`, colour `0x0031b570`.
- `0x001f8300`: the bars coloured by what is won. For each member of the
  highest generation whose status is above 0, for each of its goals:
  `M = 0x001f8410(goal's event number)` (the member with that number,
  or NULL); when `GetStatus(M.info, goal) >= 2`, `0x001f8450(lo, hi,
  0x0031b560)` with lo and hi the two leaves' `Center.x` in order: every
  bar whose midpoint `(x1 + x2) / 2` lies in `[lo, hi]` takes the colour.
- `0x001f8520` (`(matrix)`, the group's Render): for each bar, (x1, y)
  and (x2, y) through the matrix, then `RenderHLine(x1', x2', y',
  colour)`.
- The destructor (`0x001fb9c8`): the bars (`0x001fbc28`), the lists, and
  the node (bPNode's delete).

The demo's `RenderConnectionBar` (`0x001f85e0`) is dead in retail: the
bounding box of the visible members, their least and greatest status,
a colour by status (any 4 or above: `0x0031b560`; all 0:
`0x0031b580`; else `0x0031b570`) and one HLine at the middle Y.

## tEventBlurb (20 bytes)

The highlighted event's caption: its number, status and reward, slid in
from the right when the highlight moves.

| offset | field |
|---|---|
| 0 | `NewEventTime` (a RealTimer) |
| 4 | `pActiveEvent` (EventInfo) |
| 8 | `ScreenHash` |
| 12 | `MasterObject`, the text `0xcea3b7c2` |
| 16 | `StartAlpha` |

- The constructor (`0x001f87d8`, `(screen)`): `pActiveEvent` 0, the
  screen, the object.
- `SetActiveEvent(info)`: when it changes, `NewEventTime` now, the info,
  `StartAlpha` the object's alpha, and group `0xa2a16ea1`'s alpha 0.
- `RedrawActiveEvent`: `FormatStatus` into the text `0x87cfd6c6`,
  `FormatReward` into `0x35b77247`, and `FlailerPrintf(0xcea3b7c2,
  GetTranslatedString(0x111af), info+40)` (the event's number).
- `Animate`: `t = (now - NewEventTime) * 0.00025` (seconds; the RealTimer
  counts 4000 a second).
  - X: the object's own X (+48) while `t <= 0.15`; while `t < 0.35`,
    `382 + (640 - 382) * (0.35 - t) / 0.2`, and RedrawActiveEvent; from
    0.35, 382 and RedrawActiveEvent.
  - Alpha: `t < 0.15`: `StartAlpha * (1 - t / 0.15)`; `t > 0.15`: 128;
    exactly 0.15: 0.
  - `FlailerSetGroupPosition(screen, 0xa2a16ea1, obj+8, x, obj+52)` and
    the group's alpha.
- `RewindTimer`: `NewEventTime += SetTime(0.15)` (ticks), so the next
  Animate starts at the slide.

`FormatReward` (`0x001f6220`, `(info, buf)`): no reward:
`GetTranslatedString(0x101d8)`; a car: its translated short name; a
track: `GetTranslatedString(GetTheRightTrackLanguageID(track,
direction))`; another type: nothing.

## tParallaxer (100 bytes)

`ScreenHash` (0) and a tCubic2D (4). The constructor (`0x001f8ad8`): the
spline's value (320, 240) and its durations 0.5. `SetDesiredPos(x, y)`:
the spline's desired value. `Animate`: the spline seeks by the frame's
time and its value is read; nothing uses it.

## The view: tEventTreeView (2144 bytes)

| offset | field | |
|---|---|---|
| 0 | `pTree` | |
| 4 | `ScreenHash` | `0x147f8a59` |
| 8 | `Leaves` | bTList of tEventLeaf |
| 16 | `Groups` | bTList of tEventGroup |
| 24 | `CurrentLeaf` | |
| 28 | `mEventBlurb` | tEventBlurb |
| 48 | `ViewMatrix` | bMatrix4 |
| 112 | `IndicatorAnimate` | float, the indicator's phase |
| 116 | `ViewState` | retail moved it here (the demo had it at 312) |
| 120 | `AnimateZoom` | tCubic1D (48) |
| 168 | `AnimatePan` | tCubic2D (96): x at 168, y at 216 |
| 264 | `AnimateAlpha` | tCubic1D |
| 312 | `ZoomIndex` | |
| 316 | `mDetails` | tTreeDetails (596) |
| 912 | `IdleOnLeafTimer` | |
| 916 | `mParallaxer` | tParallaxer (100) |
| 1016 | `ClipMin` | x, y: object `0xaa5d7d3f`'s bounding box |
| 1024 | `ClipMax` | x, y |
| 1032 | `mBlurbyText` | tAnimatedBlurb (retail's 420) |
| 1452 | `mReward` | tTreeReward (16) |
| 1468 | `pStillCameraMover` | |
| 1472 | the car logos | the slideshow (64) |
| 1536 | the track logo | (84) |
| 1620 | the help popup | (12, then its 512-byte text) |

**The view states** (`eViewStates`):

| state | name | what draws |
|---|---|---|
| 0 | TREE | the tree |
| 1 | TRANSIT_TO_DETAILS | the tree and the details |
| 2 | DETAILS | the details |
| 3 | TRANSIT_TO_TREE | the tree and the details |
| 4 | TRANSIT_TO_REWARD | the details and the reward |
| 5 | REWARD | the reward |
| 6 | TRANSIT_FROM_REWARD_TO_DETAILS | the details and the reward |
| 7 | retail's help popup | the tree and the popup |

`ShouldRenderTree`: state below 2, or 3. `ShouldRenderDetailView`: 1 to
4, or 6. `ShouldRenderRewardView`: 4 to 6. `0x001fa448`: state 7.
`IsInTransit` (`0x001faf48`): 1, 3, 4 or 6.

### The constructor (`0x001f96b8`, `(screen, tree)`)

1. The lists empty; `mEventBlurb(screen)`; the four cubics zeroed, each
   with duration 1.0 (+36 and +40), state 0 and flags 1;
   `mDetails(tree, 0xa744ba7b)`; `IdleOnLeafTimer` 0;
   `mParallaxer(screen)`; `mBlurbyText(screen, 0xfecebef6, 0xfecebef6,
   0x70a404ec)`; `mReward(tree, 0xf1eed4cd)`; the car logos (screen);
   the track logo (screen); the popup (`0xfd297fd4`).
2. `ScreenHash`, `pTree`; the jukebox's `Start(1)`.
3. A leaf for each of the tree's events (`tree+68` of them, at `tree+60`,
   188 bytes apart), `bMalloc(96)`, appended in order.
4. The links: for each leaf L, for each goal of L's event, `P =
   FindLeafByEventNumber(goal+2)`; `L.Parents += P` and `P.Children +=
   L`.
5. Each leaf's `Generation = CalculateGeneration`.
6. The groups: for each leaf L, if L's first child is in a group, that
   group's `MaybeAdd(L)`; else a new group (`bMalloc(40)`, appended)
   with L and each of its children.
7. The H table: for each leaf, the layout string (`0x0031b3c0` for
   Championship, `tree+8` 0; `0x0031b490` for Hot Pursuit) is searched
   for its N-th non-space character, N the event's number, at most 201
   characters in; the table `0x0031b240[N - 1] = 130.0 * (index % 20)`.
   Then each leaf's `Center.x`, `Center.y` from GetDefaultH/VPos.
8. `CurrentLeaf = FindLeafByEventNumber(GetSelectedEvent(0x002fc1b4,
   tree+8))`, else the first leaf; event 31 or 32 with status 0 gives
   the first leaf instead.
9. `mEventBlurb.SetActiveEvent(info)`, `StartAlpha` 0, `RewindTimer`;
   `IndicatorAnimate` 0; StopMovie; group `0xa01bcdc6` (the template
   leaf) hidden.
10. The cubics' +36 0.5; `AnimateAlpha`'s desired value 1 (state 2 when
    it differs); then zoom, pan and alpha snapped (`Val = ValDesired`,
    `dVal = dValDesired`, state 0); `ZoomIndex` 0; `MaybeChangeZoom(0)`;
    `SetDesiredScreenCoordinates(320, 240, CurrentLeaf)`.
11. `FlailerSetLanguageID(screen, 0xa01f24f0, id)`, the id by the game
    type (`Fred+0x10000+1836`): 8 gives 10026, 9 gives 10029, else 0.
12. When `0x001f9f10` (event 32's status above 0 and not 4: the Ultimate
    is open and not won): `ViewState` 7 and `mBlurbyText`'s freeze
    (`0x002492f0`). Else `ViewState = 0x002fc1c0` (DataEventSelectScreen
    +12, the state kept from the last visit); 2 runs
    `TransitFromTreeToDetails`; then `mBlurbyText.NewText(info+176)`.
13. `IdleOnLeafTimer` = the RealTimer (gp-19608); `SyncHelpMenu`; object
    `0xaa5d7d3f`'s bounding box (ints) into `ClipMin` and `ClipMax` as
    floats; `pStillCameraMover = new StillCameraMover(1)` (112 bytes);
    the car logos' `SetEvent(info)`.
14. Each group: `0x001f8020`, `0x001f81b8`, `0x001f8300`.

### The destructor (`0x001fa2b8`)

`SetHelpOverride(0)`; the camera mover deleted (virtual, flags 3); the
popup (`0x001fb948`), the track logo (`0x001f9168`), the car logos
(`0x001f8c88`), `mReward` (`0x001f63e8`), `mBlurbyText` (`0x00249280`),
the parallaxer, `mDetails`, the groups (`0x001fb868`: each deleted, then
the list), the leaves (`0x001fb8d8`).

### The methods

- `SyncHelpMenu` (`0x001f9f50`): in state 1, `mDetails`'s SyncHelp
  (`0x001f6930`) with the current event. Else `SetHelpOverride` by the
  tree: `0x0031a590` (Championship) or `0x0031a5d8` (Hot Pursuit). Then
  in state 7, `0x001e3dd0()` (gp-17344 = 0) and the objects `0x0880ac4c`
  and `0x027f7503` hidden; in any other state both shown.
- `IsMemberOfGroup` (`0x001fa038`).
- `FindLeafByEventNumber(n)`: the leaf whose `info+40` (a signed byte)
  is n.
- `FindClosestInGeneration(leaf, gen, dir)`: among the leaves of that
  `Generation` but the leaf itself; dir -1: the greatest x below the
  leaf's (from -999999); +1: the least x above (from 999999).
- `FindClosestInList(leaf, list)`: the least `|x - leaf.x|` (from
  999999).
- `MaybeChangeLeaf(dir)`: ±1 by the generation search, 2 among the
  `Parents`, -2 among the `Children`. A leaf found that is not current
  and is visible: the old `ScaleFactor` 1, `CurrentLeaf` the new one,
  its `ScaleFactor` 2, `mEventBlurb.SetActiveEvent`,
  `mBlurbyText.NewText(info+176)`, the car logos' and the track logo's
  `SetEvent`; returns 1. Else 0.
- `SetDesiredScreenCoordinates(x, y, leaf)`: the pan's desired value
  `(x - leaf.x * zoom.ValDesired, y - leaf.y * zoom.ValDesired)`.
- `MaybeChangeZoom(d)`: `n = clamp(ZoomIndex + d, 0, 1)`; n unchanged
  and d not 0 returns 0. Else `ZoomIndex = n`, the zoom's desired value
  `{0.4, 1.0}[n]` (gp-16760), `SetDesiredScreenCoordinates(320, 240,
  CurrentLeaf)`, 1. Only the constructor calls it, with 0: the zoom is
  never changed by a button in retail.
- `MaybeChangeView`: `SetDesiredScreenCoordinates(320, 240,
  CurrentLeaf)`; the parallaxer's `SetDesiredPos(RandomRange(0, 320),
  RandomRange(0, 240))`.
- `RenderIndicator` (`0x001fa098`, `(leaf, matrix, alpha)`): the leaf's
  bounding box inflated by 1.05; the colour (128, 128, 128, `(sin(
  IndicatorAnimate) + 1) * 64`); both corners through the matrix; four
  HLines and four VLines as brackets at the corners, each 0.15 of the
  box's width or height long (one HLine's x2 + 2.0);
  `IndicatorAnimate += 0.2`.

### The transits

| function | what |
|---|---|
| `TransitFromTreeToDetails` (`0x001fac78`) | state 1; alpha to 0; zoom to 3.0; SetDesired(320, 240); the current leaf's car model `Load` (`0x001fba58`); `mDetails`'s SyncHelp |
| `TransitFromDetailsToTree` (`0x001fad20`) | the car model `Unload` (`0x001fba38`); alpha to 1; state 3; zoom to `{0.4, 1.0}[ZoomIndex]`; SetDesired; `SyncHelpMenu` |
| `0x001fadd8` (reward to details) | state 6; alpha to 0; the car logos and the track logo shown; `mDetails`'s SyncHelp |
| `TransitFromDetailsToReward` (`0x001fae40`) | state 4; alpha to 1; the track logo and the car logos hidden; `mReward`'s SyncHelp (`0x001f6590`) |
| `0x001faea8` (the popup closed) | `ViewState = 0x002fc1c0`; `SyncHelpMenu`; 2 runs TreeToDetails; `mBlurbyText.NewText`; `0x0880ac4c` and `0x027f7503` shown |

"To" a value is the cubic's SetValDesired (state 2 when it differs).

### OnRender (`0x001fa458`)

When `ShouldRenderTree`:

1. `ViewMatrix` the identity, rows 0 and 1 scaled by `AnimateZoom.Val`,
   its translation (+96, +100) the pan's value.
   `SetFlailerTextClipWindow(ClipMin, ClipMax)`.
2. Each group's Render (`0x001f8520`) at `AnimateAlpha.Val`.
3. Each leaf's Render: a leaf not current with the clip and alpha 0.2;
   the current leaf with the clip only in state 0 (else
   `ResetFlailerTextClipWindow`) and alpha `AnimateAlpha.Val` (0.2 for a
   locked event 32).
4. The clip again; `RenderIndicator(CurrentLeaf, ViewMatrix,
   AnimateAlpha.Val)`; the clip reset.

Then `mDetails.Render(info, 1 - AnimateAlpha.Val)` when
`ShouldRenderDetailView`; `mReward.Render(leaf, AnimateAlpha.Val)`
(`0x001f6440`) when `ShouldRenderRewardView`, else `mReward.Hide(leaf)`
(`0x001f6520`); in state 7 the popup's Render (`0x001f95d8`) at
`AnimateAlpha.Val`.

### OnTick (`0x001fa698`)

1. The zoom, pan and alpha seek by the frame time (gp-19596); the blurb
   animates.
2. When the alpha has arrived (its state, the short at +44, is 0):
   state 1 becomes 2 (`0x002fc1c0` = 2, `mDetails.Activate`); 3 becomes
   0 (`0x002fc1c0` = 0); 6 becomes 2 (`0x002fc1c0` = 2,
   `mReward.Hide(current)`, `mDetails.Activate`); 4 becomes 5
   (`mReward`'s SyncHelp, `0x001f6588`).
3. Group `0xa2a16ea1` (the blurb) visible only in state 0.
4. The parallaxer, `mBlurbyText`, `mReward.Tick(current, camera)`, the
   car logos (`0x001f8fb0`), the track logo (`0x001f9318`).

### HandleMessage (`0x001faf60`, `(msg, data)`)

In a transit every message is eaten: `data+12` (the sound) 0, `data+8`
(go on) 0. Else by the state:

- 2 (details): back (17): `TransitFromDetailsToTree`, `data+8` 0, sound
  21. Square (10): with a reward (`info+62 > 0`), sound 24 and
  `TransitFromDetailsToReward`; else sound 8. Anything else:
  `mDetails.HandleMessages`.
- 5 (reward): when `mReward.HandleMessages` returns 0, sound 24 and the
  reward-to-details transit.
- 7 (popup): when the popup's HandleMessages (`0x001f9598`) returns 0,
  `0x001faea8`.
- 0 (tree), through the jump table `0x002ba8b0`:

| message | what |
|---|---|
| 1 select | `SetSelectedEvent(0x002fc1b4, tree+8, info+40)`, `TransitFromTreeToDetails`, sound 21 |
| 6 left, 7 right | `MaybeChangeLeaf(-1 / +1)`: moved, `MaybeChangeView` and sound 20; else sound 0 |
| 8 up | `MaybeChangeLeaf(2)` (to a parent), sound 19 |
| 9 down | `MaybeChangeLeaf(-2)` (to a child) |
| 15 L1 | the debug unlock: `0x0016fdb0` returns 0 in retail, so nothing |
| 17 back | `SetSelectedEvent`, and the back goes on to the frontend |

## tTreeDetails (596 bytes)

The highlighted event's panel, screen `0xa744ba7b`.

| offset | field |
|---|---|
| 0 | `FlailerObjects`, bPList: the objects of group `0x2d3f3165` |
| 8 | `LastKnownEvent` |
| 12 | `DescriptionText` (512) |
| 524 | `TrackName` (64) |
| 588 | `ScreenHash` |
| 592 | `pTree` |

- The constructor (`0x001f6678`, `(tree, screen)`): the group's objects.
- `Render` (`0x001f6770`, `(info, alpha)`): when the event is not
  `LastKnownEvent`: the description, `FormatEventDescription(tree, info,
  GetTranslatedString(info+180), DescriptionText, 512)`;
  `FlailerSetLanguageID(0xf601f2d4, the track's language id)`, the
  track `GetTrack(GetRaceIndex)` or track 0; `LastKnownEvent`; and,
  unless the event is multi-track with status 2 (a tournament under
  way), the game type (`tree+8` ? 9 : 8), `MakeEventCarsAvailable` and
  `0x00183ec0` (Select Car's preload). Then each object at the alpha,
  and `RenderTextIntoRectangle(screen, 0x7a31036b, 0x7ad2801e,
  DescriptionText)`.
- `SyncHelp` (`0x001f6930`, `(info)`): resume = multi-track and status 2.
  Championship: `0x0031a5b0` to resume, else `0x0031a5a0`. Hot Pursuit:
  `0x0031a5b0`, else `0x0031a5e8`.
- `Activate`: empty.
- `StartEvent` (`0x001f6a28`, `(msg, data, leaf)`): `Fred+16` 1;
  `RaceParameters+596` 1; `Fred+0x10000+1840` the event's number;
  `EventTree::SetRace(tree, RaceParameters, info)`; `0x001f7480(leaf,
  TheEventsOpened)`. A tournament under way: when `data+4` is 0,
  `PushScreenOntoStack("View Event Tree")`, then
  `ContinueMultiTrackEvent`. Else the game type (8 or 9),
  `MakeEventCarsAvailable`, `ChangeToScreen("Select Car", 1)`.
- `HandleMessages` (`0x001f6b70`): select with the status above 0: sound
  22 and StartEvent; status 0 (locked): sound 23. Left, right, up and
  down: 0.

## tTreeReward (16 bytes)

The reward's 3D view, screen `0xf1eed4cd`: `ScreenHash` (0), the
objects of group `0x461d42d0` (4), `pTree` (12).

- The constructor (`0x001f6328`) and destructor (`0x001f63e8`).
- `Render` (`0x001f6440`, `(leaf, alpha)`): a track model's Render; a car
  model's `MakeCarVisible` and Render; the objects.
- `Hide` (`0x001f6520`, `(leaf)`): a car model's `MakeCarInvisible`;
  `FlailerPrintf(0x7e428084, "%s", the leaf's reward name)`.
- `SyncHelp` (`0x001f6588` calls `0x001f6590`): `SetHelpOverride`,
  `0x00331538` (Championship) or `0x00331540` (Hot Pursuit).
- `HandleMessages` (`0x001f65c8`): square (10) returns 0; back (17):
  `data+8` and `data+12` 0, returns 0; left, right, up, down: `data+12`
  0, 1; else 1.
- `Tick` (`0x001f6620`, `(leaf, camera)`): the models' Ticks.

## The car logos (64 bytes, at 1472)

A slideshow of the event's cars' logos on the details panel, object
`0xc6398c48`.

| offset | field |
|---|---|
| 0 | `ScreenHash` |
| 4 | the timer |
| 8 | 8 texture hashes |
| 40 | how many |
| 44 | the one shown |
| 48 | the fade-in pending flag |
| 52 | the object's own alpha (read in the constructor) |
| 56 | the Y slot |
| 60 | the X slot |

- The constructor (`0x001f8c10`), destructor (`0x001f8c88`: the kept
  textures released, `0x00249828`, and the alpha restored).
- `Show` / `Hide` (`0x001f8cf0`, `0x001f8d08`): the object's visibility.
- `SetImage` (`0x001f8d20`, `(move)`): the texture `hashes[index]`; with
  move, `y = (y + bRandom(3) + 1) % 4` and `x = (x + bRandom(2)) & 1`;
  `TopLeftY = {70, 150, 210, 260}[y]`, `TopLeftX = {140, 280}[x]`.
- `SetEvent` (`0x001f8e18`, `(info)`): the kept textures released; for
  each of the event's cars (GetCar, at most 8),
  `bStringHash(short name, bStringHash("CARLOGO_"))`, each kept
  (`0x00249730`); index, x and y 0; the flag 1; `SetImage(0)`; the
  timer now less 5.5 s; Show.
- `Tick` (`0x001f8fb0`): t the timer's seconds. 5.0 < t < 5.5 fades out
  and clears the flag; 5.5 <= t < 6.0 moves to the next logo once
  (wrapping, `SetImage(1)`) and fades in; t >= 6.0 restarts the timer.
  `0x001f8f68` is the unit ramp `(t - lo) / (hi - lo)`.

The kept textures (`0x00249730`, `0x00249828`) are an 8-slot list at
FlailerScreenList (gp-21324) +456 +124 of texture hashes the frontend
must not unload; its defaults are `GRID_BLUEPRINT1` and
`GRID_BLUEPRINT2`.

## The track logo (84 bytes, at 1536)

The event's track logo on the details panel, object `0xf60114e4`.

| offset | field |
|---|---|
| 0 | `ScreenHash` |
| 4 | 12 texture hashes |
| 52 | how many |
| 56 | the one shown (always 0) |
| 60 | the object |
| 64 | its original X |
| 68 | the timer |
| 72 | the alpha |
| 76 | the change pending flag |

- The constructor (`0x001f90f0`), destructor (`0x001f9168`), `Show` and
  `Hide` (`0x001f91d0`, `0x001f91e0`).
- `SetEvent` (`0x001f91f0`): the hashes from `0x0019fb00(track number
  (trackinfo+66), direction)`: `"LOGOTRACK%2d"`, then `"R"` when
  reversed, then `"_FR"` when the global `0x0031c1c8` is 1. When the
  last change was under 0.35 s ago, X 640. Index 0, the timer now, Show.
- `Tick` (`0x001f9318`): t < 0.35 fades out (flag cleared); 0.35 < t <=
  0.62 changes the texture once and slides X from 640 to the original;
  later X stays the original.

## The help popup (at 1620)

Shown in state 7, when the Ultimate is open and not won. Screen
`0xfd297fd4`; the objects of group `0x2d3f3165` but `0x03c8f634` and
`0xf601f2d4` (4); the text `GetTranslatedString(0xe32c9)` (12).

- `HandleMessages` (`0x001f9598`): select: sound 5, returns 0 (closes);
  left, right, up, down: sound 0, 1; else 1.
- `Render` (`0x001f95d8`, `(alpha)`): the objects, then
  `RenderTextIntoRectangle(screen, 0x7a31036b, 0x7ad2801e, text)`.
- The destructor (`0x001fb948`).

## The lines

- `SetObjectColor` (`0x001f6c18`, `(object, colour)`): r, g, b as ints
  into `r | g << 8 | b << 16`, then the object's alpha from w.
- `RenderHLine` (`0x001f6cf0`, `(x1, x2, y, colour)`): a copy of bitmap
  `0x02eca94f` (screen `0x147f8a59`); X the lesser x, Y less half the
  height, ScaleX (+56) `(x2 - x1) / width`; the colour;
  `RenderFlailerBitmap(1.0)`.
- `RenderVLine` (`0x001f6df8`, `(y1, y2, x, colour)`): bitmap
  `0x03ea005d`; Y the lesser y, X less half the width, ScaleY (+60)
  `(y2 - y1) / height`.
- `RenderDot` (`0x001f6f00`): empty.
- `InflateRect`: scales a box about its centre.
- FlailerBitmapChunk: X +48, Y +52, ScaleX +56, ScaleY +60.

## The colours

The static initializer (`0x001fb790`) fills the tables, then builds the
FlailerScreenConfig for "View Event Tree" (callback `0x001fb218`, hash
`0x147f8a59`):

| table | r, g, b, a | used for |
|---|---|---|
| `0x0031b560` | 0, 80, 0, 80 | lines and bars of what is open or won |
| `0x0031b570` | 60, 0, 0, 80 | lines and bars of what is locked |
| `0x0031b580` | 60, 60, 60, 80 | the dead RenderConnectionBar's locked bar |
| `0x0031b590` | 128, 128, 128, 128 | a leaf |
| `0x0031b5a0` | 128, 128, 128, 128 | a fogged leaf |

## ModelViewer.obj

**tTrackModelViewer** (4 bytes, the model):

- `Render` (`0x0023c108`): a pooled matrix, the identity, the diagonal
  times `TrackModelScale` (gp-15272), rotated about Z by
  `TrackModelAngle` (gp-15268) times gp-26720, `eModel::Render(m, NULL,
  0)`.
- `Tick` (`0x0023c1f8`, `(camera)`): the camera's eye (+48) and look
  (+64) from `0x0031cc50` and `0x0031cc60`; the angle plus gp-15264,
  wrapped at gp-26716.
- `SetModel` (`0x0023c248`): `eModel::Init(SprintfAndHash("TRACK%d_MINI",
  trackinfo+66))`, made with `bOMalloc(gp-25200)`.
- The constructors (`0x0023c2b8`, `0x0023c2e0` with the reward: track
  +1, direction +2), the destructor (`0x0023c310`).

**tCarModelViewer** (28 bytes): car type 0, skin 4, ViewID 8, loaded
12, ride info 16 (8), the FrontEndRenderingCar* 24.

- The constructor (`0x0023c368`, `(reward)`): type `reward+1`, skin
  `reward+2`, ViewID 1, `new FrontEndRenderingCar(ride, 1)` (656
  bytes), loaded 0, `car+628` (drawn) 0.
- The destructor (`0x0023c410`); `Render` (`0x0023c480`): empty.
- `Load` (`0x0023c488`): the CarLoader (`0x00313a38`) +4 and +8 1,
  `Load`, `BeginLoading(NULL)`, loaded 1. `Unload` (`0x0023c4f8`).
- `Tick` (`0x0023c520`, `(camera)`): the car at the origin, turned about
  Z by an angle (gp-15240, plus gp-15236 a frame, wrapped at gp-26712,
  times gp-26708) into `car+48`; its four wheel matrices (the front two
  turned by gp-20106) at CarTypeInfo+288's positions (32 apart) into
  `car+112` and `car+368`; the camera's look (+64) `0x0031cc80` and eye
  (+48) `0x0031cc90`.
- `MakeCarVisible` (`0x0023c7c8`): ReInit and `car+628` 1.
  `MakeCarInvisible` (`0x0023c810`): `car+628` 0.

## Constants

| gp | value | |
|---|---|---|
| -16816 | 130.0 | the H spacing |
| -16820 | 350.0 | the V spacing (a generation) |
| -16812 | 1.0 | the leaf's matrix scale |
| -16752 | 1.05 | the indicator's inflation |
| -16748 | 0.15 | the indicator's bracket length |
| -16768, -16744 | 0.2 | the indicator's step; a dimmed leaf's alpha |
| -16760 | 0.4, 1.0 | the zoom table |
| -16784 | 140, 280 | the car logo's X slots |
| -16800, -16804 | 0.15 | the blurb's fade |
| -16796 | 0.35 | the blurb's slide end |
| -16792 | 382 | the blurb's X |
| -16776 | 0.27 | the track logo's slide length |
| -27856, -27852, -27844 | 0.00025 | the RealTimer's ticks to seconds |
| -27848, -27840 | 0.35 | the track logo's fade |
| -27868, -27864 | 99999, -99999 | bounding box seeds |
| -27836 | -999999 | a search seed |
| -27832, -27828 | 999999 | search seeds |
| -16700, -16696 | | the Championship and Hot Pursuit trees |
| -16772 | | `pInstance` |

`0x00331748` is `"%2d"` and `0x00331738` `"%s"`.

## The screens' objects (FRONTB)

| screen | objects | what |
|---|---|---|
| `0x147f8a59` | 40 | the tree, the template leaf, the blurb, the clip box |
| `0xa744ba7b` | 5 | the details panel |
| `0xfd297fd4` | 4 | the help popup |
| `0xf1eed4cd` | 2 | the reward view |
| `0x492e86e9` | 26 | (a template; not used here) |

## The port

`eventtreeview.{c,h}` (TASKS 69b to 69e), wired in `main.c`. It was played
on Azahar on both trees (`tools/run_azahar_career.ps1`, `-CopsOn` for Hot
Pursuit, `-Back` for B from Select Car). Porting it showed these points
the decode above leaves out or has wrong:

- **The Mode Selects.** Their event tree rows (CopsOffModeSelect
  `0x002045f8`, CopsOnModeSelect `0x00203f50`) write Fred's GameType,
  NumPlayerCars and the selected event's tree type. `bscreens.c` kept these
  in its own state, so `GetEventTree` found no tree. The `setEventTree`
  hook writes them now.
- **The group's members** are sorted by x, greatest first. bList::Sort
  with `b.x <= a.x` is a stable bubble sort.
- **The constructor's cubics.** Zoom, pan and alpha have flags 0.
  `mBlurbyText.NewText` takes the event's title by its string ID, the int
  form.
- **The lines.** The line down to a parent starts 5 below the leaf's
  centre (`y1 + 5`).
- **The copies.** A copied text object gets MaxChars 4, as
  `0x001410e8`'s text twin does. The clip window cuts the bitmaps as well
  as the texts whose FormatOptions has `0x10`.
- **The details' description.** RenderTextIntoRectangle's pen starts at the
  text object `0x7a31036b` (TRACK_LINE_1, 147, 126, under the track's
  name). The line breaks at the right edge of box `0x7ad2801e` (BLURB_BOX,
  the whole panel from 140, 64). The port draws it after the layers, in
  its own wrapped style, as it does car select's blurb.
- **The parallaxer** is ticked and given a random desired position, but
  nothing reads it.

Not ported:

- The reward's turning model (ModelViewer.obj). The reward page shows
  its name and its Flailer objects.
- The help menu (tHelpMenu). SetHelpOverride is logged.
- The constructor's StillCameraMover.
- The kept textures' hooks and the debug unlock. They are NULL, and the
  unlock answers 0, as in retail.
