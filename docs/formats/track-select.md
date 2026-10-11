# Select Track

Retail's Select Track screen is the frontend's track picker. Car select
goes on to it for every game type except the event games. Its callback
is `TrackSelectScreenCallback` (`0x001a0920`), and its StartRace is
`0x001a0790`, reached from the callback's `0x001a0918`. The code runs
from `0x0019dd20` to `0x001a0c80`, plus the static init at `0x001a09e8`.

**Status (step 12m-3c).** Everything below is decoded from retail's
image. The still camera is `stillcam.c` (`docs/formats/camera.md`, "The
still camera"). 12m-3c-1 is done: `btracksel.c/.h` is the screen's
logic, its 2D, the `TRACK%d_MINI` model and StartRace, bound to "Select
Track" (`0x15417b53`) in main.c's screen table. `tools/tracksel_check.py`
with `tools/src/tracksel_test.c` runs it beside retail's: 3132 ops,
30026 lines, 0 differ; 171 mutations, 155 caught, 16 equivalent (the
`EQUIVALENT` table in the checker says why for each). On Azahar car
select goes on to it, with Coastal Parklands, its stats, the times of
day and the model; RIGHT shows National Forest locked with its blurb,
DOWN moves the time of day, and BACK returns to car select.

Not done yet (12m-3c-2): the TSELECT.BIN slideshow. main.c leaves the
`packNew`, `packDelete`, `packUnloadAll`, `packHasTexture` and `packLoad`
hooks NULL, so the slideshow shows nothing, and `eggActive` is NULL. In
the 12m-3c-1 Azahar run Y (SQUARE, the track's speech) did not reach the
screen: no `SQUARE` line in the log. Check the run script's key first.

The addresses are retail's (SLES_507.31). `gp` is `0x003358f0`.

## The plan

- `btracksel.c/.h`, on `bcarsel.c`'s pattern: a module `g_m` with a
  `BTrackSelHooks` table. The hooks cover:
  - translate, the sound and noise, the speech fade, and SPCH 155;
  - the track unlock blurb (`0x0024b6b0`, not ported);
  - `RenderTextIntoRectangle`;
  - the egg test;
  - `SetActiveMenuItem` and `GetActiveMenuItem`;
  - StartRace;
  - trace.

  Arrays replace the linked lists: there are about 64 tracks, with up to
  8 times of day each. Copy bcarsel's fade and slide helpers in
  privately (`fadeInit`, `fadeScale`, `fadeRestore`; `slideInit`,
  `slideSetup`, `slideAnimate`, `slidePlace`). Add a one-object `fadeAdd`
  for the slideshow.
- `texturestream.h` handles TSELECT.BIN:
  - `texturepack_construct(p, "TrackSelect", NULL)`;
  - `texturepack_load_texture_table_from_file`;
  - `texturepack_load_textures_from_file(p, &h, 1, cb, param)`;
  - `texturepack_unload_all_textures_from_file`;
  - `texturepack_get_texture`;
  - `texturepack_destruct`.

  main.c's `unloadTexturesFromFile` also forgets the view's cached
  textures.
- `bmenu_set_active_item(BMenu *m, uint32_t hash)`, mirroring
  `FlailerMenu::SetActiveMenuItem` (`0x0016a3a8`):
  - find the item;
  - return if there is none, if it is already current, or if it is not
    ENABLED (state & 1);
  - unhighlight the current item;
  - make the new one current and highlight it, which sends HIGHLIGHT and
    plays its noise.

  The global wrapper `0x0016d3d0` goes through `CurrentMenuSystem`
  (`gp-21324`, current node at +412).
- **ACTIVATE's reply.** Retail's `FlailerScreen::Activate` (`0x0016a858`)
  sends ACTIVATE with param = -1, port = screen+16 and itemHash = the
  screen's hash. If the reply's param is not -1, the menu starts at
  item param - 1. After that it plays the noise, calls
  `SetCurrentItemNumber`, then `Activate`.

  The port's `bgf_change_to_screen` memsets the data, so param is 0, and
  ignores the reply. main.c's `hookEnterScreen` always calls
  `bmenu_activate(&b->menu, 0)`. Select Track's constructor answers
  `TODMenuManager::SetCurrentTrack`, which is the time of day's item,
  1-based.
- **PAD_UP and PAD_DOWN.** When the time of day changes, the callback
  sets noise 11 or 10 and leaves param at 0, so bmenu then moves the
  selection to follow it. When it does not change, param = 1 consumes
  the event.
- **The 3D.** RENDER draws the `TRACK%d_MINI` model. As for car select,
  the frontend's draw goes through
  `trackview_draw_frontend(&g_feView, ...)`, with the still camera on
  view 1.
- **The checker.** `tools/tracksel_check.py` with
  `tools/src/tracksel_test.c` runs retail's code in mipsemu. It uses
  FRONTB's screen `0x15417b53` and GLOBALB's track table, and logs the
  stubs. `carsel_check.py` is the pattern.
- **The split.** 12m-3c-1, done, is the logic, the 2D, the model and
  StartRace, with the checker. 12m-3c-2 is the TSELECT.BIN slideshow on
  the device.

Be A Cop with one player cannot select laps, so SELECT goes straight to
StartRace. That is the path 12m-5 needs.

## Globals and offsets

- The SelectTrackScreen instance is at `gp-19760`.
- `CurrLanguage` is at `0x0031c1c8`; 0 is English and 1 is French.
- `TheEasterEggs` is at `0x0031d7e8`.
- `HighestTrackNumber` is at `gp-21944`.
- `RealTimer` is at `gp-19608` and `RealTimeElapsed` at `gp-19596`.
- `bDefaultSeed` is at `gp-14472`.
- The eModel slot pool is at `gp-25200`.
- `Camera::StopUpdating` is at `gp-21808`.

Fred's fields:

| Offset | Field |
| --- | --- |
| +28 | `MainMenuOpts[0]` |
| +333 | the units byte: 0 is imperial, anything else metric |
| +340 | `SelectTrackScreenData[4]`: base track, laps, direction, time of day |
| +67372 | `GameType` |
| +67380 | `NumPlayerCars` |

`InitWithDefaults` (`0x0019dd78`) sets the data to:

- [0], track 11's SameAs;
- [1], 2;
- [2], 0;
- [3], track 11's time of day.

The port already has this as `data_select_track_screen_defaults`.

RaceParameters' fields:

| Offset | Field |
| --- | --- |
| 0 | track |
| 12 | direction |
| 32 | race type |
| 40 | p2p |
| 44 | laps |
| 48 | np |
| 52 | nai |
| 600 | the tree race |

TrackInfo's fields (`track.h`, 164 bytes):

| Offset | Field |
| --- | --- |
| 65 | TrackNumber |
| 66 | SameAsTrackNumber |
| 67 | Point2Point (int8) |
| 68 | TimeOfDay (int16) |
| 72 | TrackLanguageID |
| 76 | ReverseTrackLanguageID |
| 80 | Length |
| 112 | MinElevation |
| 116 | MaxElevation |
| 120 | Difficulty |

The track table gives each base track two times of day: 0, and one
alternate.

| Base tracks | Variants | Alternate time of day |
| --- | --- | --- |
| 11, 12, 13 | 14, 15, 16 | 1 |
| 21, 22, 23 | 24, 25, 26 | 1 |
| 31, 32, 33 | 34, 35, 36 | 2 |
| 41, 42, 43 | 44, 45, 46 | 4 |
| 61, 62, 63 | 64, 65, 66 | 2 |

13, 23, 33, 43, 63 and their variants are point to point.

## Constants, strings and tables

| Where | Value | Use |
| --- | --- | --- |
| `gp-29580` | 530.0 | time-of-day icon x |
| `gp-29576` | 525.0 | highlight x |
| `gp-29572` | 401.0 | thumbnail y |
| `gp-29568`, -64, -60, -52 | 0.00025 | ticks to seconds |
| `gp-29556` | 650.0 | the locked box's start x |
| `gp-29548` | 1.6093 | miles to km |
| `gp-29544` | 0.3 | feet to metres |
| `gp-29540` | 2π | |
| `gp-29536` | 10430.378 | radians to bAngle |
| `gp-19768` | 0.5 | |
| `gp-19764` | 0.4 | |
| `gp-19708` | 9.0 | the arrows' pulse rate |
| `gp-19704` | 1.0 | the model's scale |
| `gp-19700` | 0.0 at start | the model's angle (static) |
| `gp-19696` | 0.01 | the angle's step a tick |
| `gp-16136` | | the highlight colour (`BANIM_BLOOM_COLOR`) |
| `gp-19840` | {edf2e4ee, 20d73d01} | the arrows |
| `0x00310ea0` | (25.12, -2.564, 16.9) | the camera's eye |
| `0x00310eb0` | (2.56, -0.512, 0.512) | the camera's look-at |

Strings:

- `"TRACK%d%s%s%s"` (`0x002b5500`): the base track, the direction, the
  pick, and the time of day.
- The direction part is `"R_"` for direction 1, else `""`.
- The picks are 3 pointers at `0x002b54d0`, to `"A"`, `"B"` and `"C"`.
- The time-of-day parts, by time of day: `""`, `"_OVERCAST"`,
  `"_SUNSET"`, `"_NIGHT"`. Time of day 4 reads past the table, onto the
  stack word at the buffer's start. The port should treat a time of day
  outside 0..3 as answering 0, or document what it does.
- `"TRACK%d_MINI"` (`0x002b54c0`), `"TN_TRACK%d"`, `"TN_TRACK%dR"`,
  `"TRACK%d"` (`0x00330ba8`), and `"%d"` (`0x00330c08`).
- `"LOGOTRACK%2d"` (`0x002b55d0`), with `"R"` and `"_FR"` as hash
  continuations.
- `"pTrackSelectTexturePack"` (`0x002b5540`), `"TrackSelect"`
  (`0x002b5558`), and `"FRONTEND\\TSELECT.BIN"` (`0x002b5568`).
- `"MENUITEM_%d"`, `"TOD_BACKING_%d"`, `"%f %s %s"`, `"%s %s"`; the units
  `"mi"`, `"ft"`, `"km"`, `"m"`.
- `"StillCameraMover"` (`0x002b55b8`) and `"TimeOfDayTrack"`
  (`0x002b54b0`) are allocation names.

Tables:

| Table | At | Values |
| --- | --- | --- |
| time-of-day icon | `0x00310e50` | 132521f5, a05ac96c, daa55f27, 72da223f, daa55f27 |
| time-of-day language | `0x00310e68` | 55008, 55009, 55010, 55011, 55050 |
| difficulty language | `0x00310e80` | 55004, 55005, 55006 |

Other language ids:

| Id | Text |
| --- | --- |
| d6eb | the elevation format |
| d995 | point to point |
| d994 | circuit |
| d6f1 | "Best Total Time (%d Laps)" |
| d6e9 | the best-total title for fewer than 2 laps |

`SprintfAndHash` (`0x001dc4d0`) is `bStringHash` of the sprintf. In the
port that is a vsnprintf and then `bchunk`'s hash, as in bcarsel.c.
`0x0025a488` is `bRandom(range)`, which is `bRandomI(range, &bDefaultSeed)`.

## The screen's objects

These are in screen `15417b53`, in FRONTB:

| Objects | What |
| --- | --- |
| MENUITEM_1 'Time of Day' (513, 137), MENUITEM_2 'Alternate' (514, 187) | the only menu items; there are no TOD_BACKING_n and no MENUITEM_3..5 |
| 132521f5 (530, 142), 72da223f, a05ac96c, daa55f27 | the time-of-day icons |
| 724e34b0 | the time-of-day highlight |
| 20d73d01, edf2e4ee (553) | the time-of-day arrows |
| 3b89e410, 3489f2a3 | the lap arrows |
| 7e544804 | the laps text |
| 883beb15, 886bfd7d | the slideshow's two bitmaps |
| TN_TRACK%d, TN_TRACK%dR (y 551 on) | the thumbnails |
| 84f544f3, abb370a6 | the thumbnail strip's left and right arrows |
| f60114e4 | the track logo |
| ab671c9a | Options |
| f601f2d4 | the track name |
| ae5a12cc, f3363be5, 5cc6e73e | the records |
| 79e8a895, 20a05a3a, 0145f386 | length, elevation, difficulty |
| 6a096871, a8af730b, bea3c79c, 2a67e2d5, 2a65daf9 | the locked box |
| fe9485f7 | the object whose width is the thumbnail spacing |

d1cda594 and 9345e4a7 are not on this screen, so their lookups return
NULL. Nor are the groups 7e9e3688 (the lap selector), b5caff20 (the
time-of-day menu), abcc6035 (the best lap) and f4bd8abc (the best
total), which are group hashes.

## The track helpers

- **`IsTrackUnavailable(track, dir)`.** For game types 5 and 7, it
  returns the track's Point2Point != 0. Otherwise it returns 0.
- **`CalculateTrackNumberToLoad(d)`.** For i = 0..Highest, the first
  track with SameAs == d[0] and TimeOfDay == d[3] gives its
  TrackNumber. If none matches, it returns d[0].
- **`Visibility(track, dir)`** (`0x0019e478`):
  - `IsTrackUnlocked(track, dir)` is called first; the port's is
    quickrace.h's `is_track_unlocked`.
  - v = unlocked ? 0 : 2.
  - If `IsTrackUnavailable`, v = 1.
- **The egg.** `0x0024f930(eggs, track, dir)` =
  `0x0024f9a0(eggs, dir ? 4 : 3, track)`. Hook it; it answers 0.

## SelectableTrack (48 bytes)

| Offset | Field |
| --- | --- |
| +8 | visibility |
| +12 | direction |
| +16 | the thumbnail's hash |
| +20 | x |
| +24 | the current time-of-day node |
| +28 | the time-of-day list (bTList) |
| +36 | the base TrackInfo |
| +40 | the eModel* |
| +44 | the list's total height |

- **The constructor** takes (ti a1, dir a2, vis a3, x f12, hash t0).
  - For i = 0..Highest, each track with SameAs == the base's
    TrackNumber gets a `TimeOfDayTrack`. That is 16 bytes: the node,
    then +8 ti and +12 a float offset (0, 50, 100, ...). Each is
    appended.
  - +44 = the total height.
  - Then `SetTimeOfDay(0)`.
  - Then the model: `bOMalloc` from the eModel slot pool, with +8 and
    +12 zeroed, then `eModel::Init(SprintfAndHash("TRACK%d_MINI",
    base))`, stored at +40.
- **The destructor** deletes the model (eModel dtor, flag 3), then the
  time-of-day list.
- **`SetTimeOfDay(tod)`.** +24 = the first node whose ti's TimeOfDay
  is tod, else NULL. It returns whether one was found. `HasTimeOfDay` is
  the same without the store.
- **`ScrollTimeOfDay(dir)`.**
  - 1 takes the next node, wrapping to the first.
  - -1 takes the previous node, wrapping to the last.
  - It stores the new node and returns old != new.
  - Any other dir returns 0.
- **`DrawTimeOfDay(screen, y)`.**
  - For each node: obj = `FindFlailerObject(screen, icon[tod], 2)`;
    `SetTopLeftY(obj, y + off)`; `SetTopLeftX(obj, 530.0)`;
    `SetVisibility(obj, 1)`.
  - Then `FlailerSetTopLeftPosition(screen, 0x724e34b0, (int)525.0,
    (int)(y + cur->off - 5.0))`.
- **`PickTrackTextureForSlideshow(pack)`.**
  - r = `bRandomI(3, &bDefaultSeed)`.
  - It sprintfs `"TRACK%d%s%s%s"` with the base's TrackNumber, the
    direction part, pick[r], and the time-of-day part for the current
    node's TimeOfDay.
  - h = `bStringHash` of that. It returns `GetTexture(pack, h) ? h : 0`.

## SelectableTrackManager

The list's head is at 0 and 4, the current track at +8, and the spacing
at +12. `AddTrack` bMallocs 48 bytes and appends at the tail.

- **`BuildList(screen, width)`.**
  - +12 = width, and x = 0. x is not reset between the direction 0 and
    direction 1 passes.
  - Each pass goes over the base tracks, i = 0..Highest where ti is
    set and SameAs == TrackNumber.
  - vis = `Visibility(base, dir)`. hash = `SprintfAndHash(dir ?
    "TN_TRACK%dR" : "TN_TRACK%d", base)`.
  - vis == 1: `FlailerSetVisibility(screen, hash, 0)`.
  - Otherwise: if the egg answers, vis = 0. Then
    `SetVisibility(hash, 1)`, `AddTrack(ti, dir, vis, x, hash)`, and
    x += spacing.
- **`FindTrack(track, dir)`.** base = `GetTrackInfo(track)->SameAs`.
  It returns the first node whose ti's TrackNumber is base and whose
  dir matches, else NULL.
- **`SetCurrentTrack(track, dir, tod)`.** cur = `FindTrack(track, dir)`,
  or the first node. If `!SetTimeOfDay(tod)`, then `SetTimeOfDay(0)`.
- **The getters.**
  - The base track is `cur->ti->TrackNumber`.
  - The track is `cur->curTOD->ti->TrackNumber`.
  - The time of day is `cur->curTOD->ti->TimeOfDay`.
  - The direction is `cur->dir`.
- **`GetNext` and `GetPrev`** stop at the ends. `ScrollSelectedTrack(±1)`
  stores the new current track and returns whether it changed.
- **`GetDesiredHorizThumbnailOffset`** is 244.0 - cur->x.
- **`DrawThumbnails(screen, x, y)`.** For each node,
  `FlailerSetTopLeftPosition(screen, hash, (int)x, (int)401.0)`, then
  x += spacing. Then `DrawTimeOfDay(cur, screen, y)`.
- **`AtLeftEdge`** is cur == the first node, and **`AtRightEdge`** is
  cur == the last.

## SelectTrackSlideshow

| Offset | Field |
| --- | --- |
| +0 | the screen |
| +4 | the pack |
| +8 | the track |
| +12 | t0 |
| +16 | t1 |
| +20 | the texture |
| +24 | loaded |
| +28 | state |
| +32 | feAlphaAnimation over 883beb15 |
| +44 | feAlphaAnimation over 886bfd7d |

- **The constructor.**
  - The pack is `bMalloc(148, "pTrackSelectTexturePack")` and
    `TexturePack("TrackSelect", NULL)`, then
    `LoadTextureTableFromFile("FRONTEND\\TSELECT.BIN")`. It goes at +4.
  - The other fields are zeroed.
  - `AddObject(+32, 0x883beb15)` and `AddObject(+44, 0x886bfd7d)`.
    `AddObject` finds the object (any type). If it exists, it appends an
    element that saves the object's alphas.
- **The destructor** calls `UnloadAllTexturesFromFile`, then
  `~TexturePack(3)` if there is a pack. Then the two animations'
  destructors run, which put the alphas back.
- **`Update`.**
  - now = RealTimer.
  - If state == 0, 4.0 < (now - t0) * 0.00025, and loaded is set:
    t1 = now and state = 1.
  - If state == 1, f = (now - t1) * 0.00025 * 0.5.
  - f < 1: `ChangeTexture(886bfd7d, tex)`; scale(+32, 1 - f);
    scale(+44, f); `SetVisibility(886bfd7d, 1)`.
  - f ≥ 1: `ChangeTexture(883beb15, tex)`; scale(+32, 1.0);
    `SetVisibility(886bfd7d, 0)`; state = 0; t0 = now; then
    `MaybeTriggerLoad`.
- **`MaybeTriggerLoad`.** It tries up to 10 times. Each try, h =
  `Pick(+8, pack)`, skipped if 0 or equal to tex. On the first other h:
  loaded = 0; `LoadTexturesFromFile(pack, &h, 1, cb, this)`, where the
  callback sets loaded = 1; tex = h; and it stops.
- **`SetCurrentTrack(t)`.** If t is +8 already, return. Otherwise:
  - +8 = t;
  - `ChangeTexture(883beb15, SprintfAndHash("TRACK%d", base))`;
  - scale(+32, 1.0) and scale(+44, 0.0);
  - state = 0 and t0 = now;
  - `UnloadAllTexturesFromFile(pack)`;
  - `MaybeTriggerLoad`.

## TODMenuManager

The screen is at +0 and the track at +4, which starts as 0.

`SetCurrentTrack(t)` returns -1 if t is +4 already. Otherwise it sets
+4 = t, r = -1 and n = 1, then for tod = 0..4:

- item = `SprintfAndHash("MENUITEM_%d", n)`, and back =
  `SprintfAndHash("TOD_BACKING_%d", n)`. The number n counts the times of
  day the track has, not tod.
- If `HasTimeOfDay(t, tod)`:
  - `SetVisibility(icon[tod], 1)`, `SetVisibility(back, 1)` and
    `SetVisibility(item, 1)`;
  - `SetLanguageID(item, lang[tod])`;
  - if it is the current time of day, `SetActiveMenuItem(item)` and
    r = n;
  - n += 1.
- Otherwise it hides icon[tod] and item n and backing n. A later time of
  day the track has shows them again.

It returns r.

## TrackRecordDisplayer

| Offset | Field |
| --- | --- |
| +0 | the screen |
| +4 | the track; never written, so `SetCurrentTrack` always runs |
| +8 | the time |
| +12 | the list (self-linked head) of `tTotalTimeRecord`, 16 bytes each: +8 laps, +12 the table |
| +20 | the current record |
| +24 | the count |
| +28 | a flag |

The constructor (`0x0019ef00`) sets +28 = 1 and the rest to 0.

- **`SetCurrentTrack(t)`.**
  - num = `t->ti->TrackNumber`. cls = `GetSelectedCarClass` of player 0,
    or with two players the lower of the two. dir = `t->dir`.
  - lap = `GetBestLapTimesTable(Fred, num, cls, dir)`; name =
    `LookupPlayerName(Fred, (short)lap[4])`.
  - If the time is neither 0 nor 0x7fffffff, and `MainMenuOpts[0]` is 0:
    `PrintToString(timer, buf, 0)`; `SetGroupVisibility(abcc6035, 1)`;
    `FlailerPrintf(f3363be5, "%s %s", buf, name)`. Otherwise
    `SetGroupVisibility(abcc6035, 0)`.
  - It clears the list. For a circuit, for laps 1, 2, 4 and 8: tbl =
    `GetBestTotalTimesTable(Fred, num, cls, dir, laps)`; if it is
    valid, it appends {laps, tbl}.
  - current = the first record; count = the list's length;
    `DisplayBestTotal`; +28 = 1; +8 = now.
- **`Update`.** e = (now - +8) * 0.00025. It returns unless 5.0 < e.
  - If count < 2: +8 = now and +28 = 1.
  - Else if e < 5.5: `SetGroupAlpha(f4bd8abc, (int)((5.5 - e) * 2 * 128))`.
  - Else if e < 6.0: `SetGroupAlpha(f4bd8abc, (int)((1 - (6.0 - e) * 2)
    * 128))`. If +28 is set: current = the next record, wrapping;
    `DisplayBestTotal`; +28 = 0.
  - Otherwise: +8 = now and +28 = 1.
- **`DisplayBestTotal`.**
  - If current is the head, count is 0, or `MainMenuOpts[0]` is set:
    `SetGroupVisibility(f4bd8abc, 0)` and return.
  - If the time is not valid, return.
  - It prints the time, then `FlailerPrintf(ae5a12cc, "%s %s", buf,
    name)`.
  - For laps ≥ 2: `FlailerPrintf(5cc6e73e, tr(d6f1), laps)`. Otherwise
    `FlailerPrintf(5cc6e73e, tr(d6e9))`.
  - `SetGroupVisibility(f4bd8abc, 1)`.

## TrackLockedDisplayer (352 bytes)

This mirrors bcarsel's `BCarSelUnlock`.

| Offset | Field |
| --- | --- |
| +0 | the track |
| +4 | the screen |
| +8 | x = `GetTopLeftX(a8af730b)` |
| +12 | alpha = `GetAlpha(bea3c79c)` |
| +16 | `AnimationGroup(screen, 6a096871, a8af730b, 640.0, x, 0.5)` |
| +92 | the blurb, 256 bytes |
| +348 | the start time |

- **`SetCurrentTrack(t)`.** If t is the same, return; otherwise set it.
  - vis < 2: `SetGroupVisibility(6a096871, 0)` and
    `SetVisibility(bea3c79c, 0)`.
  - vis == 2: `SetGroupVisibility(6a096871, 1)`,
    `SetVisibility(bea3c79c, 1)`, `SetVisibility(edf2e4ee, 0)` and
    `SetVisibility(20d73d01, 0)`.
  - Then `SetVisibility(2a67e2d5, 0)`;
    `FormatUnlockBlurbForTrack(+92, 256, TrackNumber, dir)`
    (`0x0024b6b0`, not ported, hooked); `SetupToAnimate(650.0, x)`;
    start = now.
- **`Update`.** e = (now - start) * 0.00025, and f = (e - 0.4) / 0.5.
  If 0.4 < e it animates; otherwise f = 0. Then `SetAlpha(bea3c79c, f <
  1 ? (int)(alpha * f) : alpha)`.
- **`Render`.** If the track's vis is not 0:
  `RenderTextIntoRectangle(screen, 2a67e2d5, 2a65daf9, blurb, 1.0)`.

## SelectTrackScreen (656 bytes)

| Offset | Field |
| --- | --- |
| +0 | 1 normally, 0 while the lap selector is up |
| +4..+19 | the copy of `SelectTrackScreenData` |
| +20 | the screen |
| +24 | the speech toggle |
| +32 .. +52 | the bitmaps d1cda594, 9345e4a7, 3b89e410, 3489f2a3, edf2e4ee, 20d73d01 |
| +56, +104 | two tCubic1D splines: x and y |
| +152 | the manager |
| +168 | the arrows' phase |
| +172 | the StillCameraMover* |
| +176 | the slideshow |
| +232 | the time-of-day menu |
| +240 | the records |
| +272 | the locked box |
| +624 | the highlight (`tHighlightAnimation`) |

The tCubic1D splines map onto banim.h's `BSpline`:

| tCubic1D | BSpline |
| --- | --- |
| +36 | duration |
| +40 | arrivalThreshold |
| +44 | state |
| +46 | flags |

To "aim" sets valDesired, and sets state = 2 if it differs. To "snap"
sets val = valDesired, state = 0 and dval = dvalDesired.

**The constructor, in order:**

1. Both splines are zeroed, with duration = threshold = 1.0, state 0
   and flags 1.
2. The slideshow, the time-of-day menu, the records, the locked box,
   and the highlight `(screen, 0xab671c9a, colour)` are built.
3. +20 = screen, +24 = 0, and `Fred.SelectTrackScreenData` is copied to
   +4.
4. The six bitmaps come from `FindFlailerObject(..., 2)`.
5. `StopLapSelector`.
6. Both splines get flags = 0 and duration = 0.5.
7. `BuildList(mgr, screen, (float)FlailerGetWidth(screen, 0xfe9485f7))`.
8. `SetCurrentTrack(d[0], d[2], d[3])`, then `ResyncData`.
9. Spline +56 aims at `GetDesiredHoriz`, then snaps.
10. Spline +104 aims at 130.0, then snaps.
11. data->param = `ResyncScreen()`. This is ACTIVATE's reply.
12. `DrawThumbnails(mgr, screen, GetDesiredHoriz, 130.0)`.
13. +168 = 0, and +172 = `new StillCameraMover(1)` (bMalloc 112).

**The destructor** copies +4 back to `Fred.SelectTrackScreenData` and
deletes the mover. Then it destroys the highlight, the locked box, the
records, the slideshow and the manager.

**`LogoHash(track, dir)`** (`0x0019fb00`).

- h = `SprintfAndHash("LOGOTRACK%2d", track)`.
- If dir == 1, h = `bStringHash("R", h)`.
- If `CurrLanguage` == 1, h = `bStringHash("_FR", h)`.

**`ResyncScreen`.**

- s4 = cur, s8 = cur->ti (the base) and s1 = cur->curTOD->ti.
- fmt = tr(d6eb), and kind = tr(P2P ? d995 : d994).
- **Imperial** (Fred+333 == 0): `Printf(79e8a895, "%f %s %s",
  (double)s8->Length, "mi", kind)` and `Printf(20a05a3a, fmt,
  (double)s1->Min, (double)s1->Max, "ft")`.
- **Metric:** the length × 1.6093 in "km", and the elevations × 0.3 in
  "m".
- `SetLanguageID(0145f386, diff[s1->Difficulty])`.
- `SetLanguageID(0xf601f2d4, dir == 0 ? s1->TrackLanguageID :
  s1->ReverseTrackLanguageID)`.
- Spline +56 aims at `GetDesiredHoriz`.
- With 2 or more times of day: `SetVisibility(edf2e4ee, 1)`,
  `SetVisibility(20d73d01, 1)`, and `SetTopLeftY(20d73d01,
  (int)(cur->+44 + 130.0))`. Otherwise both are hidden.
- The slideshow's `SetCurrentTrack`; r = the time-of-day menu's
  `SetCurrentTrack`; then the records' and the locked box's.
- `ChangeTexture(0xf60114e4, LogoHash(s8->TrackNumber, dir))`.
- `SetVisibility(84f544f3, !AtLeftEdge)` and `SetVisibility(abb370a6,
  !AtRightEdge)`.
- It returns r.

**`ResyncData`** sets +4 = the base track, +12 = the direction and
+16 = the time of day.

**`DoTick`.**

1. `DrawThumbnails(spline56.val, spline104.val)`, then both splines
   seek by `RealTimeElapsed`.
2. +168 += 9.0 × dt, wrapping at 2π. a = (int)((bSin(+168) + 1) × 64).
   `SetAlpha` of the +40 bitmap to (a, -1), and of +44 if it is
   not NULL.
3. The mover takes its eye and look-at from the camera constants. The
   model's angle (`gp-19700`) += 0.01, wrapping at 2π.
4. The slideshow's, the records' and the locked box's `Update`, and
   the highlight's `Animate`.

**`DoRender`** frame-mallocs a matrix. If the current track's model has
a solid (+12) and the matrix was allocated:

- `eIdentity`;
- scale the diagonal by 1.0;
- `eRotateZ(m, m, (uint16)(int)(angle × 10430.378))`;
- `eModel::Render(m, NULL, 0)`.

Then the locked box's `Render`.

**`PassJoystickTest(port)`.** Port 0 passes. Port 1 passes when
NumPlayerCars == 2. Any other port fails.

**`ScreenCallback`, normal mode (+0 != 0):**

| Message | What it does |
| --- | --- |
| 1 SELECT | If the port fails or cur->vis != 0, noise = 0. Otherwise `CanSelectLaps(ti) ? StartLapSelector : StartRace`. |
| 4 HIGHLIGHT | `SetCurrentMenuItem(highlight, itemHash)` |
| 6/7 PAD_LEFT/RIGHT | `ScrollSelectedTrack(-1/+1)`. If it changed: `ResyncData`, `ResyncScreen`, noise = 11/10, speech fade(1.0), +24 = 0. |
| 8/9 PAD_UP/DOWN | `ScrollTimeOfDay(-1/+1)`. If it changed: `ResyncData`, `ResyncScreen`, noise = 11/10, `SetCurrentMenuItem(highlight, itemHash)`. Otherwise noise = 0 and param = 1. |
| 10 SQUARE | If cur->vis == 0: +24 = !+24. If now set, `SPCH_AddEventV(155, 1, speech_convert_track_number(base))`; otherwise speech fade(1.0). |
| 13 START | noise = 0 |
| 15 L1 | dead (`0x0016fdb0` returns 0) |
| 18 TICK | `DoTick` |
| 19 RENDER | `DoRender` |

**`HandleLapSelection`, lap mode (+0 == 0):**

| Message | What it does |
| --- | --- |
| 1, 13 | If the port passes, `StartRace`; otherwise noise = 0. |
| 6 | noise = 1; laps /= 2, and below 2 wraps to 8. `Printf(7e544804, "%d", laps)` and `SetCurrentMenuItem(highlight, 0x7e544804)`. |
| 7 | noise = 2; laps *= 2, and above 8 wraps to 2. The same Printf and highlight. |
| 8/9 | noise = 0 and param = 1. |
| 17 BACK | `StopLapSelector`; param = 0; noise = 6; `ResyncScreen`; `SetCurrentMenuItem(highlight, GetActiveMenuItem())`. |
| 18 | `DoTick`. 19 is not handled, so lap mode does not render. |

- **`CanSelectLaps(ti)`** is !P2P && (GameType == 3 || (GameType == 7
  && NumPlayerCars == 2)).
- **`StartLapSelector`.** +0 = 0; `Printf(7e544804, "%d", laps)`;
  `SetGroupVisibility(7e9e3688, 1)`; `SetGroupVisibility(b5caff20, 0)`;
  `SetCurrentMenuItem(highlight, 0x7e544804)`.
- **`StopLapSelector`.** +0 = 1; `SetGroupVisibility(7e9e3688, 0)`;
  `SetGroupVisibility(b5caff20, 1)`.

**`StartRace`** (`0x001a0790`):

1. It copies +4 to `Fred.SelectTrackScreenData`.
2. It sets rp.dir = cur->dir and rp.p2p = ti->P2P.
3. Then, by GameType:

| GameType | Race type | Laps |
| --- | --- | --- |
| 3 | 1 | this screen's laps |
| 4 | 4 | 1 for point to point, else 2 |
| 5 | 3 | np + nai - 1, or 0 if that is 0 or less; its `IsTrackUnavailable` call is dead |
| 6 | 1 | 0 |
| 7 | 1 | 0 for one player, else this screen's laps |

4. It sets rp.track = `CalculateTrackNumberToLoad(&Fred.SelectTrackScreenData)`
   and rp.treerace (+600) = 0.
5. It calls `FrontendDatabase::StartRace(&Fred)`. The port's equivalent
   is main.c's `hookCarSelStartRace` pattern: `fred_start_race(&Fred)`,
   then `logRaceStart()`.

**`TrackSelectScreenCallback`** (`0x001a0920`):

- 11 ACTIVATE: `new SelectTrackScreen(data->itemHash, data)`, stored at
  `gp-19760`.
- 12 UNACTIVATE: the destructor, if there is a screen; then it clears
  `gp-19760` and fades the speech (1.0).
- Anything else goes to `ScreenCallback`, if there is a screen.
