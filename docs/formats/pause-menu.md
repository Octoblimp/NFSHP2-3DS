# The pause menu

START in a race brings up the "Pause Menu". The code is retail's PAUSE_MAIN
module, `0x00170560` to `0x001710f4`. Step 11g-2d ported it in
`3DS Files/source/pausemenu.c`.

The coordinator side is in [race-coordinator.md](race-coordinator.md):

- The player's handler turns START into `JOY_EVENT_PAUSE` and calls
  `RequestPause` with its port.
- `RCSTATE_PAUSE`'s ACTIVATE (`rcpost.c`) pauses the players, calls
  `EnterPause` on `ThePauseMenu`, pushes "Pause Menu" and calls
  `sound::Mute(1)`.
- Its UNACTIVATE changes to no screen, calls `ExitPause` and unpauses the
  players.
- `RequestUnPause` carries the reason:
  - RESUME_RACE calls `sound::Mute(0)` and goes back to the state before
    the pause.
  - RESTART_RACE leaves through `RCSTATE_NONE` with `RC_RESTART_RACE`.
  - QUIT_RACE leaves through `RCSTATE_NONE` with `RC_QUIT_RACE`, whose
    callback calls `ChangeGameFlow(BGF_UNLOADING_TRACK_SPECIFIC,
    BGF_NONE)`.

## The screen

`PAUSE_MENU` in INGAMEB, hash `0x605d2bf1`. Its eight items are
`MENUITEM_1` to `MENUITEM_8`, `0x52e039f3` on. `ANIMATING_MENUITEM`
(`0xab671c9a`) is the text the highlight's bloom draws into.

| Item | SELECT does |
|---|---|
| Resume Race | `MaybeResume`: `RequestUnPause(RESUME_RACE)`, but only for the player who paused and only with every pad in |
| Restart | `MaybeRestart`: the Restart popup, with every pad in |
| Options | "Pause Options" |
| View Replay | `RequestUnPause(INSTANT_REPLAY)` |
| View Objective | "Race Objective", or "Race Objective 2PBAC" for two players in Be A Cop |
| View Cop Controls | "Pause BAC controls" |
| Quit Race | `MaybeQuit`: the Quit popup |
| Debug | "Debug Menu" |

SELECT is acted on only while the menu is up (state 1). START does what
Resume does and plays the start noise when it unpauses. BACK does nothing.

`Activate` grays the items for the race:

| Item | Mode |
|---|---|
| View Replay | on with an instant-replay snapshot and the replay's highlights not muted, else grayed |
| View Objective | on with an objective or in Be A Cop, else hidden |
| View Cop Controls | on in Be A Cop, else hidden |
| Quit Race | grayed once every player has finished, else on |
| Debug | always hidden (`0x0016fdb0` is `return 0` on the disc) |

A hidden item leaves its gap: the menu is not laid out again. So a quick
race's menu has a space between Options and Quit Race, as retail's has.
`bmenu` skips grayed and hidden items and wraps, so Up from Resume Race
lands on Quit Race.

`Activate` also names three items for the kind of race:

| Race | Quit | Resume | Restart |
|---|---|---|---|
| free run | 0x30d48 | 0x30d4c | 0x30d4e |
| event tree | 0x30d4a | 0x30d4b | 0x30d45 |
| Be A Cop | 0x30d52 | 0x30d50 | 0x30d51 |
| anything else | 0x30d46 | 0x30d4f | 0x30d45 |

## `PauseMenu`, 56 bytes

| Offset | Field |
|---:|---|
| 0 | `State`: 0 not paused, 1 the menu, 2 the Restart popup, 3 the Quit popup |
| 4 | `ScreenHash`, from `Activate` |
| 8 | `Port`: the port that paused, or -1 |
| 12 | `OptionsChooser` |
| 16 | `ReplayChooser` |
| 20 | `PausingPlayer`: player 0 by number on that port, else player 1 |
| 24 | `Highlight`: the bloom, a `tHighlightAnimation` |

`EnterPause` stops both players' rumble. It then gives the port to the
eight pause screens with `SetScreenFilterPort`, so only that pad drives
them.

## The popups

Both popups use `POPUP` (`0x037f3133`), with two buttons: Yes `0x38273`
and No `0x38274`. No is highlighted first. Left and right move between the
buttons, and BACK answers No. While a popup is up, the menu is hidden.

| Race | Restart message, title | Quit message, title |
|---|---|---|
| free run | 0x3827f, 0x38289 | 0x3827d, 0x38288 |
| event tree | 0x38271, 0x38279 | 0x3827e, 0x38284 |
| Be A Cop | 0x38281, 0x38285 | 0x38282, 0x38283 |
| anything else | 0x38271, 0x38279 | 0x38272, 0x3827b |

The answers:

- **Yes on Restart** copies each player's `PlayerSettings` back to
  `TheRaceParameters`, by `PlayerNumber`, and asks for RESTART_RACE.
- **Yes on Quit** asks for QUIT_RACE.
- **No** shows the menu again.

The Quit popup has `KEEP_VISIBLE` (0x10), so the dismiss leaves it on
screen. No hides it by hand. Yes leaves it up over the unloading, as
retail does.

## The port

The seams are in `pausemenu.h`. main.c fills them:

| Seam | main.c |
|---|---|
| `gPauseMenuCtorFn`, `DestroyFn`, `EnterPauseFn`, `ExitPauseFn` | `pause_menu_*` |
| `gGrayMenuItemFn` | `hookGrayMenuItem` on the screen's item |
| `gSummonPopupFn` | `bpopup_summon` on the flow |
| `gFlailerCurrentScreenFn` | the flow's screen |
| `gPauseTranslateFn` | the start-race screens' `GetTranslatedString` |
| `gPauseMenuAnimFn` | the flow's `BAnim`, its clock set to the real timer |
| `gChangeGameFlowFn` | `bgf_change_state` |
| `gSoundMuteFn` | `jb_sound_mute` |

Five seams are left NULL, and each does nothing:

- `gSetScreenFilterPortFn`: there is one pad.
- `gPortStopForceFn`: there is no rumble.
- `gReplayNumInstantReplaySnapshotsFn`: no replay, so View Replay stays
  grayed.
- `gRestoreTypeChangedHandlersFn`.
- the `gFED*` seams.

### Three things main.c had to change

**The input order.** Retail's `GenerateJoyEvents` runs after
`ExecuteQueuedMessages`. It hands the same pad events to the Flailer and
then to the players. So in a race main.c reads the pad for the screens
(`flowInput`) after `raceFrame`, not before. If the order is the other way
round, the START that pauses also reaches the menu, which unpauses at once.

**Screens not yet ported.** `flowChangeToScreen` keeps the current screen
up when it is asked for one the flow does not have. It logs "screen not
ported". Pause Options, Race Objective and the BAC controls are not ported
yet, so selecting them leaves the menu where it is.

**Screens left up after a quit.** Retail loads INGAMEB with the track and
unloads it with the track's common files. FRONTB goes with the frontend.
The port loads both at boot and keeps them. `POPUP` is in both, and
`uirender_find_screen` finds FRONTB's first, so the Quit popup is drawn
from FRONTB. Because it is `KEEP_VISIBLE`, it stayed drawn over the
frontend after the quit. So `flowBeginUnloadingTrackCommon` now hides
every screen of INGAMEB and FRONTB, which is what dropping them does in
retail.

### After a quit

The quit goes UNLOADING_TRACK_SPECIFIC, UNLOADING_TRACK_COMMON,
LOADING_FRONTEND, IN_FRONTEND.

Where it lands depends on `frontendLaunchType`, as in retail:

- It is 1 from boot. Only `UnlaunchFrontendMenus` writes it: 3, or 2 for a
  demo.
- A SkipFE race never left the frontend through it, so a quit runs the
  boot stages again: the autoload, the language screen, the title.
- A race started from the frontend pops back: to "New Main Menu" for game
  types 2 to 7, or to "View Event Tree" for 8 and 9.

The music after a quit follows the jukebox's first-pick rule
([jukebox.md](jukebox.md)). The menu's opener, "Fever for the Flava", is
played once a boot. Every later menu visit carries on down the menu list,
so the frontend comes back with a different tune.

The track's memory comes back. On Azahar the linear heap is 69397 KB free
before the first load, 23844 KB in the race, and 68926 KB once the track
detaches.

## Checking

`tools/pausemenu_check.py` runs retail's PAUSE_MAIN in
`retail_model.RetailEmu` next to `tools/src/pausemenu_test.c`. Under it
run `tHighlightAnimation`'s destructor and its HandleMessage
(`0x00248ae0`).

The result is 14633 ops, 28698 lines, 0 differ. `--mutate` catches all
198 mutations.

`sound::Mute` (`0x001af850`) is in `tools/jukebox_check.py`. It is checked
under each enable, category and volume, with `on` at 0, 1 and 2.

On Azahar (`tools/run_azahar_race.ps1 -Presses`, and
`run_azahar_quickrace.ps1 -Presses` from the frontend's Quick Race):

- the menu draws and mutes the music;
- Resume unmutes and does not pause again;
- Restart works with both Cancel and OK;
- Quit unloads to the frontend, with no popup left over.
