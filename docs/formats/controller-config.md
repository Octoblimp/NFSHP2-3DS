# Options' Controller: the remap page (TASKS 71d)

Options' Controller is retail's `JoystickPreConfig`, and its
Configuration row opens `JoystickConfigScreen` for port 1
(`joyconfig.c`, `joyconfig.h`). Both are OptionsScreenBase pages
(`bscreens.c`'s `bscr_optbase_*`). The keys themselves are `joyhid.c`'s
`gJoyHidBindings` (joystick.md, "The 3DS").

| Config name | Flailer screen | Callback |
|---|---|---|
| "Joystick PreConfig" | 8bd5060b | `joypreconfig_callback` (0x002400c0 ..) |
| "Joystick Config Port1" | b6657464 | `joyconfig_callback` (0x0023e578 ..) |
| "Joystick Config Port2" | b6657464 | not registered (Player 2) |
| Calibration, Vibration | | not registered (nothing to work on with a 3DS) |

## PreConfig

Retail's page has each player's Configuration, Calibration and
Vibration/Feedback. The port keeps MENUITEM_1, Player 1's Configuration:
MENUITEM_2 to 6 are grayed and hidden with their masks, as are the "Off"
texts (3fabc377, e2f33138), the value arrows (7bcd6704, 7c51b6d7,
7bcd6705, 7c51b6d8) and the "Player 2" text (LanguageID 160206). Up and
Down are consumed, so the one row never moves. Its blurb is 150600.

## Configuration

Retail's page shows one of a few fixed pad layouts, Left and Right
cycling them, each action's button by `GetButtonChar` (0x0023ee48). The
port's picks each action's key, in the racer's table or the cop's car's.
The page has no bloom, blurb or brackets: the line under the cursor is
lit by its mask (MI_1 to MI_7; line 8 has none) and its label drawn
white, the rest grey.

The left panel (x 0 to 133) is the table's name, MENUITEM_1, "Racer" or
"Cop", between the arrows d1cda594 and 9345e4a7, scaled to fit. The
DualShock picture (0b2ad6df) is hidden.

| Line | Left column | Right column |
|---|---|---|
| 1 | Steering (fixed: Circle Pad, D-pad Left and Right) | E-Brake |
| 2 | Throttle (C-Stick up fixed beside it) | Horn |
| 3 | Brake (C-Stick down fixed beside it) | Camera |
| 4 | Speed Boost (the cop only) | Look Back |
| 5 | Pause (fixed: START) | the racer's Zone Freeze (shift down) or the cop's Roadblock |
| 6 | HUD | the racer's Zone Zoom (shift up) or the cop's Helicopter |
| 7 | Shift Up | the racer's Manual Zone Freeze (camera + shift down) |
| 8 | Shift Down | the racer's Manual Zone Zoom (camera + shift up) |

The racer's Zone rows show the keys they use and cannot be picked; the
cop's lines 7 and 8 on the right are empty.

### Keys on the page

| Key | On the top line | On an action |
|---|---|---|
| Up, Down | to an action / from line 1 to the top line | the next action in the column |
| Left, Right | the other table (`PORTLANG_RACER`, `PORTLANG_COP`) | the other column's nearest line |
| A | the other table | wait for a key |
| X | the shown table's defaults | the shown table's defaults |
| B | leave (the save prompt when changed) | leave (the save prompt when changed) |

While it waits, the action's glyph blinks (0.6 s, on for 0.35), the
bottom screen asks for the key, and the next of the ten bind keys pressed
(A, B, X, Y, L, R, ZL, ZR, D-pad Up, D-pad Down) is the action's:
`joyhid_bind` gives the action that had the key the moved action's old
key. START stops the wait. A bind that would leave the throttle or the
brake with no key (`joyhid_bind_keeps_drive`, the cop's E-Brake on A, for
one) is refused with the cancel noise. `joyconfig_input` takes these
keys from `hidKeysDown` before the flow hears them, so the Circle Pad's
menu directions never bind.

While the page is up with no popup over it, uirender's
`gUiHelpLayoutFn` is `joyconfig_help_layout`, so every help character
draws as the 3DS key it names (helpglyph.h's `HELPGLYPH_LAYOUT_KEYS`).

### Bottom screen

The body is `PORTLANG_CONTROLS_BLURB`, or `PORTLANG_CONTROLS_PRESS` with
the action's label in it while waiting. The hint is two lines, A's (or
the arrows') and B's on top and X's under them; `drawBotDialog` lifts a
hint of more than one line into the gap under the popup, so its last line
is where a one-line hint goes.

| Where | Hint |
|---|---|
| the top line | Left/Right Racer/Cop, B Back; X Defaults |
| an action | A Change, B Back; X Defaults |
| waiting | START Cancel |

## Leaving

Retail's B saves with autosave on (`SaveConfiguration`, then the Autosave
screen). The port's leaves at once with the keys unchanged; changed, it
asks (the save prompt, as Display Options): Yes goes to the Autosave
screen, No puts both tables back as they were on the way in and leaves,
and B stays.

## controls.bin

`NFSHP2/SAVES/controls.bin`, written by `sdSave` (main.c) right after
settings.db and read in `hookFredLoaded` whenever settings.db loads. No
file, or one that is not one, keeps the defaults.

| Offset | Size | What |
|---|---|---|
| 0 | 4 | "HP2K" |
| 4 | 1 | version, 1 (`JOYHID_FILE_VERSION`) |
| 5 | 1 | the number of actions, 12 (`JOYHID_ACT_COUNT`) |
| 6 | 12 | the racer's table, a `JOYHID_BIND_*` (or 0xff, none) an action |
| 18 | 12 | the cop's table |

30 bytes (`JOYHID_FILE_SIZE`). `joyhid_bindings_unpack` refuses a wrong
size, magic or action count, a newer version, and tables that fail
`joyhid_bindings_valid` (a key on two actions).

## The checks

- `joyhid_check`: pack and unpack round trips, the five bad files
  refused, and `joyhid_bind_keeps_drive`'s cases.
- `helpglyph_check`: `HELPGLYPH_LAYOUT_KEYS` gives each key's own glyph,
  and rebinding does not change it.
- `tools/run_azahar_controller.ps1`: PreConfig, both tables, the racer's
  HUD put on Y, the cop's E-Brake refused A, a wait stopped with START,
  X's defaults, the prompt stayed, No (the tables put back) and Yes
  (controls.bin's bytes checked), then a second boot that reads it back.
