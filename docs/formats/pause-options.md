# The pause menu's pages

The pause menu ([pause-menu.md](pause-menu.md)) leads to five screens:

- Options, which leads to Audio and Display;
- View Objective;
- View Cop Controls.

Retail's code for them is the rest of the PAUSE_MAIN module, `0x001710f8`
to `0x00173e30`. Step 71e ported it in `3DS Files/source/pauseoptions.c`.
`main.c`'s `kScreens[]` registers the five names the menu changes to.

| Name | Screen | Callback |
|---|---|---|
| "Pause Options" | `PAUSE_OPTIONS`, `0x2b5a03a8` | `PauseOptionsCallback`, `0x001729f0` |
| "Pause audio" | `PAUSE_AUDIO`, `0x6b321e4e` | `PauseAudioCallback`, `0x00171898` |
| "Pause display" | `PAUSE_DISPLAY`, `0xcc36fab2` | `PauseDisplayCallback`, `0x00173d88` |
| "Race Objective" | `PRERACE_BLURB`, `0x887b4d37` | `PauseRaceObjective::Callback`, `0x00171bb8` |
| "Pause BAC controls" | `PRERACE_BLURB` again | `PauseViewControls`', `0x00171fd0` |

Each callback works the same way:

- ACTIVATE makes the page's object.
- UNACTIVATE deletes it.
- Every other message goes to the object.

The port keeps one static object per page instead of `bMalloc`.

None of the pages writes the save. They change these directly, as retail
does:

- `TheRaceParameters`;
- the players' `PlayerSettings`;
- bSound's volumes.

## The shared base

`0x001710f8` builds three things:

- a `tHighlightAnimation` on `ANIMATING_MENUITEM` (`0xab671c9a`), in the
  bloom colour;
- a second one on `0x1042eac3`, with colour -1, which blooms the value;
- the arrows `0xd1cda594` and `0x9345e4a7`.

`0x00171180` sends every message except ACTIVATE and UNACTIVATE to the first
highlight's `HandleMessage` (`0x00248ae0`), then to the arrows.

On HIGHLIGHT, each page puts the arrows and the value's bloom on the
highlighted row's value. Left or Right that changes something plays noise
1 or 2 and restarts the value's bloom. TICK animates it.

START on Options, Audio, Display or the objective calls
`PauseMenu::MaybeResume` with the pad's port. That goes back to the race
only for the player who paused, with noise 7. B goes back one page. Cop
Controls ignores START.

## Pause Options

There are 144 bytes, `0x00172068` to `0x001729f0`. The player is
`PlayersByNumber[0]` if its `JoyPort` is the menu's `OptionsChooser`, else
`[1]`. The title `0x18b2dbc8` reads PLAYER 1 (210101) or PLAYER 2 (210102)
to match. Retail leaves the player NULL for a port neither player is on.
No pause comes from such a port, so the port takes `player_shown(0)`.

| Item | Row | Value | Left/Right |
|---|---|---|---|
| `MENUITEM_1` | Audio | | SELECT: "Pause audio" |
| `MENUITEM_2` | Display | | SELECT: keeps the port (gp-21000), "Pause display" |
| `MENUITEM_3` | Vibration | `0x5deb55a3` | hidden on the 3DS |
| `MENUITEM_4` | Damage | `0xb6791614`, 210009/210010 | event 2 with `!DamageEnabled` |
| `MENUITEM_5` | Handling | `0xa2450f0f`, Classic 49050 / Extreme 49060 | event 1 with the other style |
| `MENUITEM_6` | Transmission | `0x6db88809`: 0 Automatic 49020, 1 Manual 49030, 2 Semi-Auto 49010 | event 3 with the type ±1, wrapping |
| `MENUITEM_7` | Jump Cams | `0x1f1b628b`, On/Off | event 4 with `JumpCams == 0` |
| `MENUITEM_8` | Zone Cams | `0x16e95f2b`, On/Off | event 5 with `ZoneCams == 0` |
| `MENUITEM_9` | Alternate Cam | `0xcb3bdd8f` | placed off the screen (y 559) |

`0x00172260` enables the two camera rows only with one player shown, and
hides them otherwise. Handling's change runs it again.

### The special events

Each change is a replay special event, as in retail (TASKS 72h-1). The
page calls `AddSpecialEvent` (`0x0013e3f8`) on the race's ReplayManager.
That makes the change at once, through `ReplayManager::HandleSpecialEvent`
(`0x0013e4a8`), which jumps to `HandlePauseMenuReplaySpecialEvents`
(`0x001703e0`, `pausereplay.c`). While the race is capturing, the manager
also keeps the event, and a replay makes it again on the loop it was made
on. So an instant replay drives with the race's settings as they were at
each moment. With no manager the port makes the change alone; retail
calls the manager with no test.

| Event | Made by | A, B | Effect |
|---|---|---|---|
| 0 | the debug menu's destructor | place, player | the Race's `ForceRaceFinishPosition` and `ForceRaceFinishPlayerNum` |
| 1 | Handling | player, style | the car's `State.DriverMode`, `PlayerSettings.DrivingStyle` (`Player::SetDrivingStyle`) and `NFSRaceMode` set to the style, then `SetAIDriverModesFromPlayers` |
| 2 | Damage | on | `DamageEnabled` is A != 0, then `CarDamage::RethinkDamage` for every car with damage |
| 3 | Transmission | player, type | `TransmissionType`, then `RealDriver::SetManualTransmission` |
| 4 | Jump Cams | on | `GlobalDisplaySettings.JumpCams`, A's low byte |
| 5 | Zone Cams | on | `GlobalDisplaySettings.ZoneCams`, A's low byte |
| 6 | the debug menu's Super Easy AI | on | `SuperEasyAI` |

The handler answers 1 for these seven and 0 for any other. The debug menu
(`PauseDebugMenu`) is not ported, since retail never shows its row, so
nothing makes 0 or 6. The handler still takes them, as a replay could.
Retail reads through the players, cars and world with no test. The port
skips what is NULL, and a player number off the table.

The page's arguments are retail's (`0x001723d8` to `0x00172558`): Damage
sends `DamageEnabled ^ 1`, Handling the player's number and
`DrivingStyle == 0`, Transmission the type stepped by Left or Right and
wrapped to 0..2, and the two cams `== 0` of their setting.
`tools/pausereplay_check.py` runs the handler beside retail's.

### Vibration

The 3DS has no rumble, so the port hides Vibration with GrayMenuItem mode
2 and moves the five rows under it up a row. Each label and value goes to
the place the one above it had. The places are read once, so coming back
to the page does not move them further.

The page's background has a strip for every row, and the strips share one
unnamed hash (`0x6eb9985d`). They cannot be moved one by one, so the
panel ends with two empty strips where retail has one.

## Pause audio

There are 288 bytes, `0x001711c8` to `0x00171898`. The page holds five
`FlailerSlider`s and copies of bSound's seven category volumes, read when
the page opens.

| Item | Row | Track | Knob | Category |
|---|---|---|---|---|
| `MENUITEM_1` | Racing Music | `0xa29f7a16` | `0xc866642b` | 4 |
| `MENUITEM_2` | Ambient Sound Effects | `0xa29f7a17` | `0xc866686c` | 0 |
| `MENUITEM_3` | Engine Sound Effects | `0xa29f7a18` | `0xc8666cad` | 2 |
| `MENUITEM_4` | Tire Sound Effects | `0xa29f7a19` | `0xc86670ee` | 1 |
| `MENUITEM_5` | Speech | `0xa29f7a1a` | `0xc866752f` | 6 |
| `MENUITEM_6` | Audio Mode | value `0x2932dfca` | | |

A slider's scale is 0.7 over the category's shipped volume (`0x001afa28`:
0.38, 0.55, 0.33, 0.31, 0.85, 0.45, 0.75). So the shipped volume sits at
0.7 of the track. A step works like this:

1. Add 0.05 to the copy. Scale it, clamp it to 0..1, and unscale it.
2. Call `SaveVolumesForSpeech`.
3. If the copy changed, play "MenuAdjustVolume" at the knob's new place.
4. Seek the knob's spline (0.25 s, threshold 1) there.

The step does not set the volume itself. The destructor (`0x001714f8`)
sets all seven, then calls `SaveVolumesForSpeech`. UNACTIVATE plays noise
6.

The audio mode changes at once (`0x001715f8`): one step along Mono 110009,
Stereo 110008 and Pro Logic II, wrapping. The port names Pro Logic II
"Surround" (see audio-options.md).

## Pause display

There are 108 bytes, `0x00172aa0` to `0x00173d88`. The player is found by
the port Display was chosen from, as on Options.

| Item | Row | Value | Left/Right |
|---|---|---|---|
| `MENUITEM_1` | HUD | `0x5b472b16`: 210004/210006/210005/210025 for states 0..3 | `Player::CycleHud(dir)` |
| `MENUITEM_2` | Rearview Mirror | `0x2e931f1b` | `RearViewMirror` toggled |
| `MENUITEM_3` | Track Map | `0x55cb09f2` | `CycleTrackMap(dir)` |
| `MENUITEM_4` | Leaderboard | `0x71a78ef4`: Off, Top 3 102001, On | anything but 2 becomes 2, 2 becomes 0 |
| `MENUITEM_5` | Lap Info | `0x8b788a68` | HUD bit `0x100` |
| `MENUITEM_6` | Position | `0xe8434eb4` | HUD bit `0x10` |
| `MENUITEM_7` | Gauges | `0x5d6c141b` | HUD bit `0x40` |
| `MENUITEM_8` | Split Time | `0x12b1ebd9`: 140108..140111, Off | 0..4 by dir, wrapping; bit `0x4` cleared at 4, else set |
| `MENUITEM_9` | Score | `0x5d2a9432` | `New44` toggled |
| `MENUITEM_10` (`0xaee77883`) | Camera Spring | `0xffc3dcd2`, Off when 1 | toggled, then `Player::SetCameraSpring` |
| `MENUITEM_11` (`0xaee77884`) | Lookback | `0x2e018745`: 0 Bird's Eye 140118, 1 Lookback 140113 | 0 and 1 swapped, then the drive camera's `LookbackSpeed` back to 300.9 |
| `MENUITEM_12` (`0xaee77885`) | HUD Hotkey | `0x4aff0df3` | `New40` toggled |

`Player::CycleHud` (`0x00178ba8`) steps through {0, 1, 3, 2}, or {0, 3, 2}
with two players shown, and wraps. A state that is not on the list counts
as the first. The port's HUD hotkey uses it too (`gPlayerCycleHudFn`).

`CycleTrackMap` (`0x001ee148`) uses one of three lists:

- Be A Cop's mode: {8, 6};
- two players': {7, 6};
- one player's: {0, 1, 2, 3, 4, 6}.

A mode that is not on its list becomes the list's first.

`0x00172bd0` grays the rows. With the HUD anything but On (state 0),
every row under it is grayed and its value hidden. Otherwise:

| Row | On when |
|---|---|
| Rearview Mirror | one player shown |
| Track Map | always |
| Leaderboard, Position | not Be A Cop, not a free run, and not a time trial against a set time |
| Lap Info | not Be A Cop, or player 2 |
| Gauges, Split Time | not Be A Cop |
| Score | not a free run |

"A set time" means `TimeTrialTime.PackedTime` is neither 0 nor
`0x7fffffff`. It counts in a lap race (type 2) or point to point.

`AdjustLapInfo` (`0x001731c0`) labels `MENUITEM_5` "Lap Info" (140016)
whoever is driving.

## Race Objective

There are 8 bytes, `0x00171948` to `0x00171bb8`. The heading
`0x6a77af98` shows one of these:

- an event-tree race: "Event %d Objective:" (63001) with the event's
  number;
- Be A Cop: "You're The Cop" (970000);
- anything else: "Objective:" (63000).

RENDER prints `pre_race_blurb_text(0)` into the blurb's rectangle. Its
`%c` is the horn's button, kept from the last frame a pad was in
(gp-21068). SELECT and BACK go back to the Pause Menu.

Retail leaves "previous" and "next" shown on the screen that the next
race's blurb shares. The port hides them on UNACTIVATE.

"Race Objective 2PBAC" (`0xb5ecd7a0`) is the two-player cop's. The port
races one player per console, so it is not registered.

## Pause BAC controls

The code runs `0x00171c50` to `0x00171fd0`. It shows You're The Cop's
controls over two pages. The heading is 200021. A shows the next page and
B the one before. Going past either end returns to the Pause Menu.

The text depends on the pad on port 0 and player 0's transmission:

| Pad | Page 1 / 2 |
|---|---|
| none | 900011 |
| wheel, type 22 | 200060 / 200061 |
| other wheel | 200054 / 200055 |
| pad, type not `0x41`, automatic | 200052 / 200053 |
| pad, type not `0x41`, manual or semi | 200050 / 200051 |
| pad `0x41`, automatic | 200058 / 200059 |
| pad `0x41`, manual or semi | 200056 / 200057 |

The port's text overrides draw the 3DS buttons in it (X, L, R, ZL).

## Tested

Step 71e was tested in Azahar, in a quick race and in a SkipFE Be A Cop
race (`SkipFEBeACop 1`, `SkipFENumAICars 2`):

- Options showed the values and the hidden Vibration. Every row changed,
  and events 1 to 5 reached the log.
- START on Options resumed the race.
- Audio stepped Racing Music from 0.85 to 0.95, which the log showed when
  the page closed.
- Display cycled the HUD 0 → 1 → 3 and grayed the rows under it.
- The objective showed the cop's text. Cop Controls paged 1, 2, 1, 2 and
  then returned to the menu.

While the race is paused, the bottom screen shows the logo. Before 71e it
was black: the pause takes the HUD down but leaves its screen up.
