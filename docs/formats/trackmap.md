# The minimap: TrackMap's table, turn and draw (steps 8m-6a and 8m-6b)

TrackMap is the race's minimap. Each player has one while the HUD's
TRACK_MAP feature is on (`hud-features.md`): SetHudFeatures makes it
with `new TrackMap(CurrentTrackInfo, car, player)` and deletes it when
the feature goes off. SetTrackMapMode writes the mode into it.
Player::RenderTrackMap (`0x00181c08`) calls its Render each frame, after
StuffDemoPolys. Render arrives in 8m-6c, so nothing draws the map yet.

Retail's TrackMap has fourteen functions (CONTINUE.md lists them all).
8m-6a ports seven, plus EvalCubic: the table, the constructor and the
turn. 8m-6b ports five more, plus GetSideOfLine and
CalculateCentroidOfQuad: the map's own draw. All are in `trackmap.c`:

| step | function | address | size | port |
|------|----------|---------|------|------|
| 8m-6a | InitTrackMapModeInfo | `0x001bd1f8` | 1428 | `trackmap_init_mode_info` |
| 8m-6a | TrackMap(TrackInfo *, Car *, Player *) | `0x001babb8` | 528 | `trackmap_construct`, `trackmap_new` |
| 8m-6a | ~TrackMap | `0x001badc8` | 28 | `trackmap_delete` |
| 8m-6a | GetAngle | `0x001bb678` | 300 | `trackmap_get_angle` |
| 8m-6a | EvalCubic | `0x001bdad0` | 100 | `eval_cubic` |
| 8m-6a | GetCameraDirection | `0x001bd0b0` | 324 | `trackmap_get_camera_direction` |
| 8m-6a | GetCarUVPosition | `0x001bca50` | 148 | `trackmap_get_car_uv_position` |
| 8m-6a | GetBoxOnMap | `0x001bcae8` | 364 | `trackmap_get_box_on_map` |
| 8m-6b | DrawMap | `0x001bb7a8` | 1192 | `trackmap_draw_map` |
| 8m-6b | MapToScreen | `0x001bcc58` | 1112 | `trackmap_map_to_screen` |
| 8m-6b | ClipPolygon | `0x001bc140` | 2236 | `trackmap_clip_polygon` |
| 8m-6b | EmitPoint | `0x001bca08` | 72 | `emit_point`, static |
| 8m-6b | DrawOverOrUnderLay | `0x001bbf88` | 440 | `trackmap_draw_over_or_under_lay` |
| 8m-6b | GetSideOfLine | `0x001cb138` | 136 | `get_side_of_line` |
| 8m-6b | CalculateCentroidOfQuad | `0x001bda40` | 144 | `calculate_centroid_of_quad` |

The draws hand their polys to epoly.h's `gEPolyRenderFn`, as Flailer
polys with flags 0. That is ePoly::Render (`0x0010fa68`) in retail, and
trackview binds it in the port.

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
| 148 | CurrentViewDistanceForward | DrawMap's, when it scrolls |
| 152 | CurrentViewDistanceBackward | DrawMap's, when it scrolls |
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

The names f, b, l and r are the port's, and DrawMap's calls bear them
out. It passes its view distances forward and backward as f and b. It
passes one side distance as both l and r: the mean of the two, or the
zoom's distance.

## DrawMap

DrawMap(centre, outer[4], angle) draws the part of the map texture
about the car. Render (8m-6c) passes the angle GetAngle gave, and draws
the markers inside `outer`.

1. If the displayed mode's IsDrawn is 0, it returns, writing nothing.
2. A local ePoly is constructed. The car's UV comes from
   GetCarUVPosition of CarToTrack's position (Car +96).
3. **With HasScrolling,** it takes three distances, in UVs:
   - Zooming, when ZoomToKeepPursuedCarInView is set and there is a
     CurrentlyPursuedCar (mode 10): all three are
     `dist / MapWidthMetres × (Width / ClippingWidth) + 0.1`. Here dist is
     the distance in x and y from the car to the pursued car, and
     MapWidthMetres is the track's TrackMapCalibrationMapWidthMetres.
   - Otherwise, forward is ViewDistanceForward, backward is
     ViewDistanceBackward, and the side is their mean.
   - Forward and backward are stored in CurrentViewDistanceForward and
     CurrentViewDistanceBackward.
   - The box is GetBoxOnMap(carUV, forward, backward, side, side,
     angle). `outer` is the same box with each distance × 1.2.
4. **Without it,** the box and `outer` are the whole texture: (0, 0),
   (1, 0), (1, 1), (0, 1). The view distances are left alone.
5. The box's corners become the poly's u and v. `centre` is
   CalculateCentroidOfQuad of the box.
6. The four points (∓Width/2, ∓Height/2, 0), from the top left
   clockwise, go through MapToScreen.
7. Each vertex's alpha is multiplied by the mode's Alpha, and
   truncated.
8. Each vertex's u, v and q (1 from the constructor) are multiplied by
   1 / (z + H), where z is the tilted point's. That is the GS's
   perspective-correct texturing.
9. ClipPolygon draws it with TrackMapTexture, at layer 14.

The poly keeps the constructor's colour, 128 grey.

## MapToScreen

MapToScreen(poly, p0, p1, p2, p3) tilts and projects four points.

1. The tilt is the identity turned about X by the mode's AngleX. Each
   point is multiplied by it in place, so the caller sees the tilted
   points.
2. Each vertex is
   `(x·H / (z + H) + X, y·H / (z + H) + Y)`. H is the mode's distance,
   and X and Y are loaded as unsigned halfwords.
3. Each vertex's alpha fades with depth. For z > 0 it is
   `(1 − z / (Height × 0.666666687)) × 128`, truncated; otherwise it is
   128.

It writes only the vertices' x and y and the alphas.

## ClipPolygon and EmitPoint

ClipPolygon(poly, texture, layer) clips the poly to the mode's box and
draws what is left.

1. **The box** is (ClippingX, ClippingY) ± half the clipping width and
   height. The place is loaded as unsigned halfwords. Its corners run
   clockwise from the top left.
2. **The poly:** its vertices' x and y, its UVs (u, v, q) and its
   alphas are copied out.
3. **Sutherland-Hodgman**, once for each corner k from 0 to 3, against
   the line from corner k to the corner before it (3 for k = 0). A point
   is in unless GetSideOfLine calls it −1, so a point on the line is in.
   For each edge from point j to point i:
   - point j is emitted if it is in;
   - if one is in and the other out, the crossing is emitted, with
     `t = ((pᵢ.y − a.y)·lx − (pᵢ.x − a.x)·ly) / (dx·ly − dy·lx)`.
     Here a is corner k, (lx, ly) runs from it to the other corner, and
     (dx, dy) = pⱼ − pᵢ. The point, u, v and q are pᵢ + t·(pⱼ − pᵢ).
     The alpha is `aᵢ + t·(aⱼ − aᵢ)`, as floats, truncated.
   EmitPoint (`0x001bca08`) appends a point, its UV and its alpha, and
   counts it.
4. **The top point** is the one with the least y. A later point within
   0.001 of its y takes over if its x is less.
5. **The fan:** quads from the top point, each sharing its last point
   with the next. With n points, the first quad is the top point and the
   next three, the second starts from the third, and so on, while the
   start is less than n − 1. A point past the last repeats the last.
   Eight points make three quads, four make one, three make one with its
   last point twice, and fewer make none.
   - Each quad is a new ePoly, with Flailer set.
   - Its vertices take the clipped points' x, y, UVs and alphas, and z =
     (float)layer.
   - Vertex s takes the red, green and blue of the source poly's vertex
     s.
   - It goes to Render with the texture and flags 0.

## GetSideOfLine and CalculateCentroidOfQuad

**GetSideOfLine**(a, b, p) is a free function. With (dx, dy) = b − a and
(ex, ey) = p − a, it takes `c = ex·dy + ey·(−dx)`. It answers 1 for
c > 0, −1 for c < 0, and 0 on the line, or when a and b are one point.

**CalculateCentroidOfQuad**(out, q[4]) is another. It averages the
centroids of the triangles q0 q1 q2 and q0 q2 q3, each × 0.333333343.
It writes y before x.

## DrawOverOrUnderLay

DrawOverOrUnderLay(texture, layer) draws the frame (TRACKMAPFRAME, layer
0) or the backing (MAPBACK, layer 15) over the mode's box. Render
(8m-6c) chooses which.

1. If the mode's HasBorder is 0, it returns.
2. A local ePoly takes z = (float)layer at every vertex, and the box's
   corners, clockwise from the top left, as ClipPolygon builds them.
3. If the mode's IsDrawn is 0, it returns without drawing.
4. Otherwise it sets Flailer and goes to Render with the texture and
   flags 0, with the constructor's UVs and colours.

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
- **EmitPoint's buffers.** Retail's ClipPolygon keeps eight points in
  each buffer, and EmitPoint does not test the count.
  - A convex quad clipped to a box makes at most eight: each of the four
    lines adds at most one point.
  - DrawMap's quad is a projected rectangle, so it is convex.
  - The port drops a point past the eighth, where retail would write it
    over the next buffer. The checker clips only convex quads.
- **Float to integer.** The three alphas use eefpu.h's `ee_trunc_w`,
  which saturates by sign as the EE's `cvt.w.s` does. A plain cast on
  x86 gives 0x80000000 for any overflow. Only hand-set modes overflow,
  such as a negative Height or an Alpha of 3e7.
- **Division by zero.** z + H and Height are zero only in mode 6, which
  DrawMap does not draw (IsDrawn is 0). The EE would give ±FLT_MAX there,
  and the port an infinity. The checker keeps out of it.

## The checker

`tools/trackmap_check.py` runs retail's own functions, with bSPrintf,
bStringHash, the matrix code and ePoly's constructor under them, against
the harness (`tools/src/trackmap_test.c`) over `trackmap.c`, `emath.c`,
`bmath.c` and `epoly.c`.

**What is stubbed or set by hand:**

- **GetTextureInfo** answers each of the seven names from a mask, and
  logs the name and both flags.
- **eGetView** answers the one view and logs the id.
- **ePoly::Render** (`0x0010fa68`), the port's `gEPolyRenderFn`, logs
  the texture, the flags and the whole poly.
- **eMathInit and the static constructor at `0x0011bf70`** are run
  first. That constructor writes eMulVector's (0, 0, 0, 1). The
  emulator runs no static constructors, and without it w is 0, so row 3
  of the matrix would drop out.
- **WorldTimer, RaceStage and Point2Point** are set in memory.

**What is compared**, after each op:

- the map's fields by name, with its pointers named by what they point
  at;
- a test ePoly's fields, retail's offsets 16 to 152, and whether
  pDynamicFrameMemory is set;
- the tables, field by field, after InitTrackMapModeInfo;
- each call's answer, and what it wrote back.

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
    wraps past PreviousTime;
- GetSideOfLine, thirteen points against seven lines: either side, on
  the line, and a line of one point;
- CalculateCentroidOfQuad, with seven quads;
- MapToScreen:
  - five point sets in each drawn mode;
  - hand-set tilts, distances, heights, and places loaded without their
    sign;
  - fades to both saturations;
- ClipPolygon:
  - quads inside, outside on each side, across one edge and two, around
    the box, exactly on it, and as an octagon;
  - ties for the top point about 0.001, and both windings;
  - sixty seeded random convex quads;
  - each mode's box, and hand-set boxes;
  - UVs, colours, alphas, layers and textures, NULL included;
- DrawOverOrUnderLay, in each mode and with IsDrawn and HasBorder set by
  hand;
- DrawMap:
  - in every mode, from several places and turns;
  - zoomed to a pursued car at several distances, under two
    calibrations;
  - with zoom set but no pursued car, and a pursued car without zoom;
  - without scrolling, and with hand-set alphas, heights and view
    distances;
  - without a map texture.

**Not driven:**

- `trackmap_new` and `trackmap_delete`. They are bMalloc and the
  constructor, and bFree; the HUD checkers' harnesses stand in their
  own.
- The `return 0` after GetCameraDirection in GetAngle, which no call
  reaches: GetCameraDirection always answers 1.
- A NULL CarToTrack in DrawMap: retail reads its position without a
  test, and Render (8m-6c) is what keeps it from drawing then.

    python tools/trackmap_check.py
    python tools/trackmap_check.py --mutate

**Result:** after 8m-6a, 2399 ops and 6631 lines; after 8m-6b, 5092
ops and 12519 lines. 0 differ.

**The mutation pass:** 188 mutations, 187 caught, 1 equivalent, 0
unexplained (`out/trackmap_mutate.txt`): 8m-6a's 111 and 8m-6b's
77. The equivalent one,
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

After 8m-6b, the same race (`out/azahar_8m6b`) ran at 19 FPS with no
crash. The HUD and the log's `trackmap` line are as before. Nothing calls
the draws until Render, so the screen does not change.

## Left for 8m-6c

DrawMarker (`0x001bbc50`) with IsPointInPoly (`0x001cb1f0`), and Render
(`0x001bade8`), and the draw on the bottom screen. Render sets
CurrentlyDisplayedMode and calls the draws above.
