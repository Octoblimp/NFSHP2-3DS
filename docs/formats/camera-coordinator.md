# Camera coordinators and `TheCameraLoader`

`CameraCoordinator.obj` (retail `0x00199a98` .. `0x0019c0d0`) holds two
things:

- the camera data: `TheCameraLoader`, slot 13 of the loader table, which
  keeps pointers into each bundle's camera chunks;
- the coordinators: objects that own a `CameraMover` and swap it as the
  race goes on.

Step 11g-2c-1 ported part of it, in `3DS Files/source/cameracoord.c`:

- the loader;
- the `CameraDataItems` parser;
- the coordinators' base and their list;
- `CountdownCameraCoordinator`.

These are not ported yet:

- the Demo, FlyBy, PreRace, PostRace and NIS coordinators
  (`0x0019a440` .. `0x0019b6a4`);
- `BumperCameraMover` (`0x00158800`), which four of them build.

`tools/cameracoord_check.py` runs the port beside retail's own code (see
"The check").

## `TheCameraLoader`, 2596 bytes

`TheCameraLoader` is at retail `0x00310370`. The demo's `.mdebug` record
for it is 2528 bytes (type#2795). Retail inserted the two players' NIS lists
after the loader's own NIS list, which moves every later field 72 bytes
on. The table below gives retail's offsets, as its readers use them.

| Offset | Field |
|---:|---|
| 0 | `NumHighlightCameras` |
| 4 | `HighlightCameraData[512]` |
| 2052 | `NumFlyByCameras` |
| 2056 | `FlyByCameraData[32]` |
| 2184 | `NumPreRaceCameras` |
| 2188 | `PreRaceCameraData[32]` |
| 2316 | `NumPostRaceCameras` |
| 2320 | `PostRaceCameraData[32]` |
| 2448 | `NumNisCameras` |
| 2452 | `NisCameraData[8]` |
| 2484 | `NumPlayerNisCameras[2]` (retail's) |
| 2492 | `PlayerNisCameraData[2][8]` (retail's) |
| 2556 | `NumCameraShakes` |
| 2560 | `Shakes` |
| 2576 | `TuningVortex` (16 bytes) |
| 2592 | `VortexCount` |

The list is set up by its static constructor,
`_GLOBAL_$I$CameraCoordinatorList`. That is `__CTOR_LIST__[40]`, at
`0x00192398` in the demo and `0x0019c058` in retail. The port calls it
from `sinit_run`. It makes `CameraCoordinatorList` (gp-19920) empty and runs
the loader's constructor (`0x00199c80`), which zeroes:

- the five list counts;
- the two players' NIS counts;
- the vortex and its count.

It does not zero the shakes.

## The chunks

| Type | What | Child type | Where on the retail disc |
|---|---|---|---|
| `80034405` | highlights | `34450`, plus the vortex `34440` | each `TRACKB*.BUN`: 112 to 363 cameras of types 0, 1 and 2 |
| `80034425` | fly-bys | `34490` | each `TRACKB*.BUN`: one camera, `PreRace_01`, type 2 |
| `80034410` | pre-race | `34460` | `INGAMEB.BUN` +0x1d8500: `Cam_01`..`Cam_04`, type 1 |
| `80034415` | post-race | `34470` | `INGAMEB.BUN` +0x1da280: `Cam_01`..`Cam_11`, type 1 |
| `80034420` | NIS | `34480` | `NIS/*.CAM`, at offset 0: 2 or 3 cameras |
| `34492` | shakes | -- | `INGAMEB.BUN` +0x1e2f80: 5048 bytes, 9 shakes |

`Loader` (`0x00199cd8`) handles the chunks as follows:

- **A list container.** The list's count is set to 0. Then each child of
  the list's own type is appended by its payload, aligned to 16 bytes past
  the child's header as every chunk is. Children of other types are
  skipped. No count is bounded.
- **The NIS container.** Its cameras are appended without the list being
  cleared first.
- **The highlights' vortex child.** Its 16 bytes go to `TuningVortex` and
  the word after them to `VortexCount`.
- **The shakes chunk.** `Shakes` points at the payload, and the count is
  `size / 560`, unsigned.

Each of the six chunks marks every coordinator's camera data for a reload
and returns 1. Any other chunk returns 0.

`Unloader` (`0x0019a010`) zeroes the counts of the four lists and the
shakes, and leaves the vortex. It marks nothing. Any other chunk returns 0.

The NIS container is handled differently. Each of its cameras is looked up
in both players' NIS lists, not in the loader's own. Every hit adds one to a
total, and the total is subtracted from the count of the last list that had
a hit.

The NIS keeper (`0x0019a3e8`, no symbol; `camera_loader_keep_nis_cameras`)
is called by `NisManager::NisLoadedCallback` with its player's index. It:

- copies the NIS count and all eight NIS pointers to that player's lists;
- zeroes the loader's own NIS count.

The index is not bounded.

Two lookups read the lists:

- **`FindCameraData`** (`0x0019a280`) returns the first camera whose name
  matches under `bStrICmp`. It searches highlights, then fly-bys,
  pre-race and post-race, and never the NIS cameras. It returns NULL when
  nothing matches.
- **`FindRandomCameraShake`** (`0x0019a1b8`) returns NULL for bank 0. For
  any other bank it draws one shake with `bRandom` on `bDefaultSeed`, or
  returns NULL without a draw if there are none. Nothing in retail calls
  it.

## A camera's block

`CameraDataItems::CameraDataItems(char*)` (`0x0019b6b0`) parses a block in
place. Every type sets two fields:

- `Type`, the word at 0;
- `Name`, which points at the 32 bytes at 4.

Types 0, 1 and 2 then read the fields below, one word each, in order:

| Type 0 (the highlights' spring camera) | Types 1 and 2 |
|---|---|
| `SpringXVel`, `SpringYVel`, `SpringZVel`, `SpringDamp`, `SpringConst` | `EyeSplineSpeed`, `LookSplineSpeed` |
| `LookOffsetX`, `LookOffsetY`, `LookOffsetZ` | `FOVSplineSpeed` (type 2 only) |
| `EnterVertComp`, `EnterHorizComp`, `LeaveVertComp`, `LeaveHorizComp`, `IsLeaveSet` | `LockEyeSpeedToCar`, `LockLookSpeedToCar` |
| `EyeSplineSpeed`, `LockEyeSpeedToCar` | |
| `MinAreaPercent`, `MaxAreaPercent`, `IsFOVIso`, `MinPercent`, `MaxPercent` | the same five |
| `NumAreaVerts`, `NumAreaFaces`, `NumEyeVerts` | the same three, then `NumLookVerts` |
| `WipeDistance`, `WipeAutoDisable` | |
| `NearClip`, `FarClip`, `Backwards` | the same three |
| `ShakeBankNumber` | |
| a pad of 8 | a pad of 12 for type 1, 8 for type 2 |

After the pad come the arrays, each pointer set into the block right after
the one before:

1. `FOVTable`, 512 bytes.
2. `EyeVerts`.
3. `BankVerts`, as many as `EyeVerts`.
4. `LookVerts`, types 1 and 2 only.
5. `AreaFaces`.
6. `AreaVerts`.

Each element of the first five arrays is 16 bytes.

Type 0 has no look spline, so it zeroes:

- `LookVerts`;
- `LookSplineSpeed`;
- `NumLookVerts`;
- `LockLookSpeedToCar`.

Types 1 and 2 zero the five spring fields and `ShakeBankNumber`.

A type leaves every field it does not set as it was. The NIS `.CAM`
cameras have the text `Came` as their type word, so only `Type` and `Name`
are set for them.

## The coordinators

`BaseCameraCoordinator` is 28 bytes. The demo's type#2329 has the same
layout as retail's.

| Offset | Field |
|---:|---|
| 0 | `bNode`, on `CameraCoordinatorList` |
| 8 | `pCameraMover` |
| 12 | `Disabled` |
| 16 | `ViewID` |
| 20 | `NeedToReloadCameraData` |
| 24 | vptr |

The tables are `_vt$21BaseCameraCoordinator` (`0x002b52f8`), whose Update
is the pure virtual, and `_vt$26CountdownCameraCoordinator` (`0x002b5298`).
Slot 8 holds the destructor, with its flags, and slot 16 holds
`Update(float)`.

- **Constructor** (`0x00199a98`). The coordinator goes on the list's tail
  with:
  - the base's table;
  - the view;
  - no mover;
  - `Disabled` cleared;
  - nothing to reload.
- **Destructor** (`0x00199ad8`). It:
  1. puts the base's table back;
  2. deletes the mover through its own deleting destructor, leaving the
     pointer as it was;
  3. unlinks the coordinator from the list;
  4. frees it when flags has bit 0.

  Player's deletes and the race coordinator's call it through slot 8 with
  flags 3.
- **`Disable` and `Enable`** (`0x00199b48`, `0x00199b90`). Each does
  nothing if the coordinator is already in that state. Otherwise it sets
  `Disabled` and, if there is a mover, calls the mover's own Disable
  (+104) or Enable (+96).
- **`UpdateCameraCoordinators`** (`0x00199bd0`). It walks the list from the
  head and calls Update on each coordinator that is not disabled, reading
  the next node after the call. `MainLoop` calls it after
  `UpdatePlayersNonGameState` with the real step (`RealTimeElapsed`,
  gp-19596), and `UpdateCameraMovers` follows. `main.c`'s race frame does
  the same.
- **`MarkCameraDataAsNeedingToBeReloaded`** (`0x00199c40`) sets the flag
  on every coordinator on the list.

### `CountdownCameraCoordinator`, 36 bytes

`pPlayer` is at 28 and `CurrentCountdownNumber` at 32.

The constructor (`0x0019b130`) runs the base's constructor, then sets:

- the player;
- the countdown's table;
- the number to -1.

It ends with one `Update(0)`. The destructor (`0x0019b188`) puts the
countdown's table back and runs the base's destructor.

`Update` (`0x0019b1a0`) does nothing while `Race::GetCountdownNumberToDisplay`
returns the number it already has. When the number changes, it:

1. deletes the mover and clears it;
2. looks up the camera named `COUNTDOWN_<number>` with `FindCameraData`;
3. if one is found, builds a `BumperCameraMover` on it (1116 bytes of
   `bMalloc`, with the coordinator's view and its player's car);
4. keeps the number.

It never reads `dt`.

**No bundle on the retail disc has a `COUNTDOWN_n` camera.** So retail's
countdown coordinator never builds a mover. `Player::UpdateNonGameState`
sees the coordinator with no mover and gives the player the drive
camera. The 3-2-1 is shown from the chase camera, as the PCSX2 photos show
it.

Before this step the port had no coordinator. `BeginCountdownCameras` then
removed the player's mover and built nothing, so the countdown was drawn
from the default view, 1100 m above the track.

## The port

- **Loader table.** `bchunkload.c` puts `loader_cameras` and
  `unloader_cameras` in slot 13 of both tables. These are retail's
  `LoaderCameras` and `UnloaderCameras` (`0x0019a398`, `0x0019a3c0`) on
  `TheCameraLoader`.
- **Boot.** `sinit.c` calls `cameracoord_static_init` at index [40].
- **Seams.** `main.c` installs the two vtables and points the coordinator
  seams of `playerupdate.c` and `playercam.c` at the port:
  - `gCountdownCameraCoordinatorFn`;
  - `gCameraCoordinatorDeleteFn`;
  - `gCameraCoordinatorEnableFn`;
  - `gCameraCoordinatorDisableFn`.

  `racecoord.c`, `rcstates.c` and `rcpost.c` use the same delete seam.
- **`gBumperCameraMoverFn`** stays NULL until `BumperCameraMover` is
  ported. While it is NULL, a found countdown camera builds nothing. The
  retail disc never gets that far.

## The check

`tools/cameracoord_check.py` runs the port beside SLES_507.31's own code in
`tools/mipsemu.py`. It covers:

- every function above;
- the two tables, through which the destructor slots and Update are
  called;
- `bSPrintf`, `bStrICmp`, `bRandom` and bNode's destructor, run as shipped
  beneath them.

These are stood in on both sides, and each call prints a line:

- `Race::GetCountdownNumberToDisplay`;
- `BumperCameraMover`'s constructor, which prints everything the parser
  set;
- a test mover table;
- a test coordinator table;
- `bMalloc` and the two frees.

The chunks come from two sources:

- the retail disc: INGAMEB, six tracks, nine more fly-bys and the eight
  NIS files;
- built chunks for the edges: empty containers, other children, every
  alignment, a size-0 last child, shake sizes and one-camera NIS unloads.

There are also 600 random rounds over the coordinators.

The run gives 2973 ops and 5925 lines, with 0 differences. The mutation
pass catches all 167 of its mutations.

`tools/loadertable_check.py` holds slot 13 as ported. Its two
`slot-13-*` mutations are caught.
