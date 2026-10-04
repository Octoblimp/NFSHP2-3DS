# The minimap, part one: TrackMap's table, constructor and turn (step 8m-6a)

TrackMap is the race's minimap. Each player has one while the HUD's
TRACK_MAP feature is on (`hud-features.md`): SetHudFeatures makes it
with `new TrackMap(CurrentTrackInfo, car, player)` and deletes it when
the feature goes off. SetTrackMapMode writes the mode into it.
Player::RenderTrackMap (`0x00181c08`) calls its Render each frame, after
StuffDemoPolys. Render arrives in 8m-6c, so nothing draws the map yet.

Retail's TrackMap has fourteen functions (CONTINUE.md lists them all).
This part ports seven, plus EvalCubic, all in `trackmap.c`:

| function | address | size | port |
|----------|---------|------|------|
| InitTrackMapModeInfo | `0x001bd1f8` | 1428 | `trackmap_init_mode_info` |
| TrackMap(TrackInfo *, Car *, Player *) | `0x001babb8` | 528 | `trackmap_construct`, `trackmap_new` |
| ~TrackMap | `0x001badc8` | 28 | `trackmap_delete` |
| GetAngle | `0x001bb678` | 300 | `trackmap_get_angle` |
| EvalCubic | `0x001bdad0` | 100 | `eval_cubic` |
| GetCameraDirection | `0x001bd0b0` | 324 | `trackmap_get_camera_direction` |
| GetCarUVPosition | `0x001bca50` | 148 | `trackmap_get_car_uv_position` |
| GetBoxOnMap | `0x001bcae8` | 364 | `trackmap_get_box_on_map` |

`main.c` binds playerhud's `gDeleteTrackMapFn` to `trackmap_delete`,
and `gNewTrackMapFn` to `newTrackMapLogged`. That is `trackmap_new`
with a line in `sdmc:/nfshp2_debug.txt` for each map made, giving the
track and whether the map found its textures. SetTrackMapMode now
writes the `CurrentMode` field, where it used to write the word at 160.

## The record

176 bytes. The names and offsets are the demo's .mdebug record, and
retail's are the same.

| offset | field | |
|--------|-------|---|
| 0 | PreviousCameraDirection (bVector2) | the eased direction GetAngle keeps |
| 8 | CurrentCameraSpeed (bVector2) | the ease's speed |
| 16 | PreviousTime | WorldTimer at the last ease |
| 32 | MapRotationMatrix (bMatrix4) | the track's calibration turn |
| 96 | TrackMapTexture | TRACK%d_MAP |
| 100 | CarMarkerNonrotatingTexture | CAR_MARKER |
| 104 | CarMarkerRotatingTexture | CAR_MARKERB |
| 108 | OverlayTexture | TRACKMAPFRAME |
| 112 | UnderlayTexture | MAPBACK |
| 116 | StartLineTexture | never set |
| 120 | FinishLineTexture | never set |
| 124 | StartFinishLineTexture | START_LINE |
| 128 | RoadblockTexture | BKGBMP |
| 132 | CarToTrack | |
| 136 | PlayerToTrack | |
| 140 | CurrentTrack | |
| 144 | CurrentlyPursuedCar | |
| 148 | CurrentViewDistanceForward | not set here |
| 152 | CurrentViewDistanceBackward | not set here |
| 156 | SufficientDataToRenderMe | 0 when the map cannot be drawn |
| 160 | CurrentMode | SetTrackMapMode's |
| 164 | CurrentlyDisplayedMode | the one Render draws |

The twelve bytes at 20 align the matrix. The record ends with 8 bytes
of padding. The port's record is wider on a 64-bit host, where the
pointers are 8 bytes. The layout check holds the offsets above for
32-bit builds.

The textures are on the disc:

- each track's TRACKnn_MAP is in its `TRACKS\TEXnnTRACK.BIN`, for the
  tracks 11 to 16, 21 to 26 and 31 to 36;
- the other five are in `GLOBAL\INGAMEB.BUN`.

## The modes

InitTrackMapModeInfo fills eleven 68-byte TrackMapModeInformations at
`0x003140b8` and nine 3-byte marker colours at `0x003143a8`. It writes
every field of every mode, one store at a time, and leaves the padding
alone. The constructor runs it again each time. The port keeps the
values in const tables and copies them; nothing reads the padding.

The places are in the HUD's 640 × 480.

| mode | name | X, Y | W × H | clip X, Y, W × H | forward, back | rotation | scroll | rotating dots | alpha | border |
|------|------|------|-------|------------------|---------------|----------|--------|---------------|-------|--------|
| 0 | 3D | 92, 228 | 190 × 190 | 92, 240, 139 × 91.2864 | 0.441781, 0.202055 | 1 | 1 | 1 | 1 | 1 |
| 1 | 3D, no rotation | as 0 | | | | 0 | 1 | 1 | 1 | 1 |
| 2 | 2D | 72, 243 | 130 × 130 | 72, 243, 100 × 100 | 0.33, 0.33 | 1 | 1 | 1 | 1 | 1 |
| 3 | 2D, no rotation | as 2 | | | | 0 | 1 | 1 | 1 | 1 |
| 4 | fixed | 79, 256 | 130 × 130 | 79, 218, 1000 × 1000 | 1, 1 | 0 | 0 | 0 | 1 | 0 |
| 5 | maximum size | 320, 243 | 262 × 262 | 320, 243, 1000 × 1000 | 1, 1 | 0 | 0 | 1 | 0.29 | 0 |
| 6 | off | all zero | | | | | | | | |
| 7 | two players | 83, 245 | 130 × 130 | 83, 245, 140 × 140 | 1, 1 | 0 | 0 | 0 | 1 | 0 |
| 8 | Be The Cop, small | as 4 | | | | | | | | |
| 9 | Be The Cop, large | as 5 | | | | | | | | |
| 10 | Be The Cop, targeting | as 2 | | | | | | | | |

Some fields do not fit in the table:

- **AngleX** (the tilt) is `0xd5da` in modes 0 and 1, about -30°, and
  `0xffff` in the others. H, the projection's distance, is 200 in all
  modes but 6.
- **Mode 10** is mode 2 with ZoomToKeepPursuedCarInView set.
- **CarDotSize, and the start line's width and height:**

| modes | CarDotSize | line width | line height |
|-------|------------|------------|-------------|
| 0 | 0.09589 | 0.024999 | 0.134995 |
| 1 | 0.09589 | 0.03499 | 0.169987 |
| 2 and 10 | 0.1 | 0.039982 | 0.18498 |
| 3 | 0.1 | 0.03998 | 0.194978 |
| 4, 7 and 8 | 0.07 | 0.044977 | 0.149972 |
| 5 and 9 | 0.06 | 0.03 | 0.095 |

The marker colours, red, green and blue:

| | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| | 172, 53, 0 | 75, 85, 255 | 0, 0, 255 | 0, 100, 0 | 0, 0, 128 | 128, 128, 0 | 172, 53, 0 | 0, 64, 122 | 0, 0, 192 |

## The constructor

1. SufficientDataToRenderMe = 1 and PreviousTime = 0.
2. With no track, car or player, it sets SufficientDataToRenderMe to 0
   and returns. Nothing else is written.
3. Otherwise it runs InitTrackMapModeInfo and stores the car, the
   player and the track. Both modes become 6 (off), PreviousTime
   becomes WorldTimer, and the pursued car, the eased direction and the
   speed are cleared.
4. The textures, by GetTextureInfo(bStringHash(name), use_default, 0):
   - the map, `TRACK%d_MAP` with the track's TrackNumber (an int8,
     printed signed), with use_default 0;
   - the other five with use_default 1.
5. A missing map, CAR_MARKER, CAR_MARKERB, TRACKMAPFRAME or MAPBACK
   clears SufficientDataToRenderMe. So does a missing START_LINE when
   TheRaceParameters.Point2Point (+40, a word) is 0: a loop draws its
   start line. A missing BKGBMP does not.
6. MapRotationMatrix = identity turned about Z by the track's
   TrackMapCalibrationRotation (+104).

The words at 116, 120, 148 and 152 are left as they were.

`new TrackMap` is SetHudFeatures' (`0x0017abd4`): bMalloc(176,
"TrackMap", 0, 16), then the constructor, with no NULL test. The
destructor does nothing. The deleting one frees when its flags' low bit
is set, and SetHudFeatures passes 3, so `trackmap_delete` is bFree.

## GetAngle and EvalCubic

GetAngle gives the map's turn, as a BAM:

1. If the displayed mode's HasRotation is 0, the angle is `0x8000` and
   the answer 1.
2. Otherwise it asks GetCameraDirection, which always answers 1. Then
   it reads PreviousTime and the eased direction (x, y). It reads them
   after the call, because GetCameraDirection may have just started the
   ease.
3. t = ((float)(int)(WorldTimer - PreviousTime) × 0.00025) × 0.9. At
   4000 ticks a second, a 30 fps frame is t ≈ 0.0075.
4. EvalCubic moves x toward the direction's x, with the speed's x, over
   t; then y the same way with the speed's y.
5. It stores the eased (x, y) and PreviousTime = WorldTimer.
6. The angle is `(u16)(bATan(y, x) − 32768)`, in the port's argument
   order (retail passes `$f12` = y, `$f13` = x).

EvalCubic is a free function: one step of a cubic ease toward a target.

    d = target − x0
    a = (v0 − d) − d
    b = ((d + d) + d − v0) − v0
    x = ((a·t + b)·t + v0)·t + x0
    v = (((a + a) + a)·t + (b + b))·t + v0

## GetCameraDirection

1. It takes the first mover on the player's view's list:
   `eGetView(player->ViewID)`, then the list head's next, unless that
   is the head itself.
2. **The drive camera** (CM_DRIVE, 1):
   - the direction is the camera's (Camera +80), turned about Z by the
     mover's LookBackAngle (+140);
   - eMulVector takes it as a point (w = 1), but the turn has no
     translation;
   - if both parts of the eased direction are within 0.001 of zero
     (`|x| <= 0.001` and `|y| <= 0.001`), the ease starts there: the
     eased direction becomes the new one, and PreviousTime becomes
     WorldTimer.
3. **No mover, or another kind:**
   - while the race is not at RACE_STAGE_RACING, the direction is the
     car's BodyMatrix row 0, x and y;
   - while racing, it is the eased direction.
   - Only x and y are written; z keeps what it held.

## GetCarUVPosition and GetBoxOnMap

**GetCarUVPosition** takes a world point to the map texture's UVs:

    v = ((x − left) / width, (top − y) / width, 1)

Here (left, top) is the track's TrackMapCalibrationUpperLeft (+92) and
width its TrackMapCalibrationMapWidthMetres (+100). The y is negated
before the top is added. v is then multiplied by MapRotationMatrix, and
eMulVector's w = 1 picks up row 3. The answer is the x and y.

**GetBoxOnMap**(centre, f, b, l, r, angle, out[4]) turns a box about a
point on the map:

- T = R_z(angle) × translate(centre.x, centre.y, 0), in eMulMatrix's
  order.
- The corners, before T, are (r, f), (−l, f), (−l, −b) and (r, −b),
  each with z 0.
- Each corner goes through T, and out keeps its x and y.

The names f, b, l and r are the port's. Render's calls in 8m-6c will
show what retail passes.

## Where the port differs

- **The mode table** is copied whole, padding included. Retail stores
  the fields one by one and leaves the padding alone. Nothing reads the
  padding.
- **An overflow in the ease.** The EE saturates a float overflow to
  ±FLT_MAX, where the port gets an infinity. bATan of an infinity
  reaches a NaN and reads past bASinTable. On the PS2 a saturated value
  reads a wild table entry instead.
  - One step from a settled ease cannot overflow. The longest time step
    a 32-bit WorldTimer holds, 2³¹ ticks, gives t ≈ 483,000 and a
    direction near 2e17.
  - Only several such steps in a row reach the overflow. Each would be
    days of WorldTimer, so a game never sees one.
  - The checker takes the longest step once, from a settled ease, and
    not twice.

## The checker

`tools/trackmap_check.py` runs retail's own functions, with bSPrintf,
bStringHash and the matrix code under them, against the harness
(`tools/src/trackmap_test.c`) over `trackmap.c`, `emath.c` and
`bmath.c`.

**What is stubbed or set by hand:**

- **GetTextureInfo** answers each of the seven names from a mask, and
  logs the name and both flags.
- **eGetView** answers the one view and logs the id.
- **eMathInit and the static constructor at `0x0011bf70`** are run
  first. That constructor writes eMulVector's (0, 0, 0, 1). The
  emulator runs no static constructors, and without it w is 0, so row 3
  of the matrix would drop out.
- **WorldTimer, RaceStage and Point2Point** are set in memory.

**What is compared**, after each op:

- the map's fields by name, with its pointers named by what they point
  at;
- the tables, field by field, after InitTrackMapModeInfo;
- each call's answer.

**The script** covers:

- the tables built over a pattern, and again by the constructor;
- the constructor:
  - with each of the three pointers missing;
  - with all 128 texture masks, both with and without Point2Point;
  - with Point2Point's byte against its word;
  - with track numbers from −128 to 127, nine rotations and five
    WorldTimers;
- GetCarUVPosition, under seven calibrations and hand-set matrices
  (rows 2 and 3 included);
- GetBoxOnMap, with seven boxes at ten angles;
- EvalCubic alone;
- GetCameraDirection:
  - with no mover, other movers and the drive camera;
  - at each race stage;
  - with six look backs;
  - with the eased direction at and about the 0.001 test;
- GetAngle:
  - in every mode;
  - as the camera turns a whole circle a frame at a time;
  - looking back;
  - with the other movers before and during the race;
  - with time steps from none to 2³¹ either way, and a WorldTimer that
    wraps past PreviousTime.

**Not driven:**

- `trackmap_new` and `trackmap_delete`. They are bMalloc and the
  constructor, and bFree; the HUD checkers' harnesses stand in their
  own.
- The `return 0` after GetCameraDirection in GetAngle, which no call
  reaches: GetCameraDirection always answers 1.

    python tools/trackmap_check.py
    python tools/trackmap_check.py --mutate

**Result:** 2399 ops and 6631 lines, 0 differ.

**The mutation pass:** 111 mutations, 110 caught, 1 equivalent, 0
unexplained (`out/trackmap_mutate.txt`). The equivalent one,
`angle-plus-half-turn`, adds 0x8000 to the angle instead of taking it
away. On a 16-bit angle the two are the same.

**The HUD checkers** still pass with SetTrackMapMode's new write:
hudfeatures_check (1298 ops) and hudrender_check (1278 ops), 0 differ.
Their harnesses now make a `sizeof(TrackMap)` map, and dump its
`CurrentMode`.

## On Azahar

A race on track 12, played as `run_azahar_race.ps1` drives it
(`out/azahar_8m6a`):

- It ran at 20 FPS, with no crash, and the HUD looked as it did after
  8m-5.
- The debug log has `trackmap: track 12, sufficient 1`. The map was made
  once, when the race's HUD came up, and found all seven textures. That
  includes `TRACK12_MAP` in `TRACKS\TEX12TRACK.BIN`; the other six are
  in `GLOBAL\INGAMEB.BUN`.

## Left for 8m-6b and 8m-6c

- **8m-6b:** MapToScreen (the tilt by AngleX and the projection at H),
  ClipPolygon with EmitPoint, DrawOverOrUnderLay and DrawMap.
- **8m-6c:** DrawMarker and Render, and the draw on the bottom screen.
  Render sets CurrentlyDisplayedMode and the view distances.
