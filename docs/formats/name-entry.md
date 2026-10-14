# Player Names (TASKS 54)

Options' Player Names is retail's `NameEntry` screen
(`nameentry.c`, `nameentry.h`; "NameEntry" in main.c's `kScreens[]`,
FlailerScreenConfig hash 617a4e0a). Retail types the names on
`tKeyboard`, a letter grid drawn on the screen. The port types them on
the 3DS's own keyboard, libctru's swkbd applet, and keeps tKeyboard's
rules.

| Retail function | Address | Port |
|---|---|---|
| NameEntry::NameEntry | 0x0024d408 | `construct` |
| NameEntry::~NameEntry | 0x0024d548 | `destroy` |
| MaybeActivateKeyboard | 0x0024d5c0 | `maybeKeyboard` |
| ChangeGender | 0x0024d660 | `changeGender` |
| RedrawGenders | 0x0024d7b0 | `redrawGenders` |
| HandleEvent | 0x0024d870 | `nameentry_callback` |
| Callback | 0x0024dbd8 | `nameentry_callback` |
| tNameEntryData::Init | 0x0024d2f0 | `dataInit` |
| tNameEntryData::Different | 0x0024d370 | `dataDifferent` |
| tKeyboard::SetVisible | 0x0024c5d0 | `hideKeyboard` (with 0) |
| tKeyboard::Activate | 0x0024c708 | main.c's `hookNameKeyboard` |
| cPlayerSettings::SetName | 0x00187de8 | `b_strncpy` of 11 |

## The rows

| Row | Item | Value object | A | Left / Right |
|---|---|---|---|---|
| Player 1's name | MENUITEM_1 | P1_NAME 71450a81 | The keyboard | -- |
| Player 1's gender | MENUITEM_2 | P1_GENDER d6f9d954 | Nothing | Male / Female |
| Player 2's name | MENUITEM_3 | P2_NAME 71572302 | Hidden | -- |
| Player 2's gender | MENUITEM_4 | P2_GENDER c33bae35 | Hidden | -- |

The blurb is string 150800 + row ("Enter name for Player 1." .. "Set
the gender for Player 2."). The genders are 160004 Male and 160005
Female. RedrawGenders gives a gender that is neither 0 nor 1 no string
on Player 1's row, and Player 1's string on Player 2's row (its s0 is
kept). ChangeGender turns 0 into 1 and anything else into 0.

Each row answers only its own player's pad (`data->port`), as in retail.

**Player 2 is hidden.** The 3DS has one pad and no split screen, so
Player 2's rows could never be used (the user's word, 2026-10-13).
`hidePlayer2` grays MENUITEM_3 and MENUITEM_4 with mode 2 (disabled and
hidden), so the menu passes over them. It also hides their values, their
bars (MI_3_MASK 72df3492, MI_4_MASK 75345d33) and the "Player 2" label.
That label is a text in the screen's group 457755c9, found by its
string, 160206. Player 2's name and gender stay in the save, as retail
keeps them.

tKeyboard's own objects stay hidden, as retail leaves them until its
keyboard opens: the grid (group 670b6fdd), each player's seven boxes
(7b95e55c, 7deb0dfd) and the cursor (c01086b5).

## The keyboard

A on a name calls `NameEntryHooks.keyboard`, main.c's
`hookNameKeyboard`:

- `swkbdInit(SWKBD_TYPE_QWERTY, 2 buttons, 7 characters)`. Seven is
  tKeyboard's limit: its EditBuffer is eight bytes, the last always 0.
- The hint is the row's blurb, turned from Latin-1 into UTF-8.
- The initial text is the current name.
- A filter callback allows only tKeyboard's characters
  (`nameentry_char_ok`): a-z, A-Z, 0-9, `!`, `.`, `#` and the space, from
  its DefaultMap and ShiftMap (0x0031d750, 0x0031d780). Anything else
  keeps the keyboard open with "Names can have letters, numbers, spaces,
  ! . and #."
- `SWKBD_DARKEN_TOP_SCREEN`.

**OK** writes the name with SetName's copy of 11 bytes, prints it on the
row, and plays FrontendSoundEvent 29, NameFinalSelect (tKeyboard's done
key). **Cancel** keeps the old name, silently, because the applet has
made its own noise.

The applet runs on the main thread, between frames: the flow's input
comes before C3D_FrameBegin. `hangwatch_applet` marks the wait, so the
watchdog doesn't call it a stall.

### The sound while it is open

The user heard the sound go wrong when the keyboard closed (2026-10-13).
`holdAudio` pauses every ndsp channel that is playing (bsnd's voices and
streams, the jukebox's, the movies'), and sets the master volume to 0.
The streams' workers only queue waves, so their queues fill and stop.

When the applet returns:

- **On a 3DS**, the channels go on at once, and the volume fades back in
  over 250 ms.
- **On Azahar**, the hold lasts 3.5 s first. Azahar's keyboard is a Qt
  dialog that `QtKeyboard::Execute` waits on with a
  BlockingQueuedConnection, so the whole emulated console stops while it
  is open. Its audio stretcher (`TimeStretcher::Process`) is then fed
  nothing, and its tempo slows to the floor of 5%. Fed again, the tempo
  rises to about 1.3x at 1.5 s, falls to about 0.88x at 2.8 s, and is
  within 5% of normal by 3.5 s (`tools/azahar_stretch_sim.py`, its code
  simulated). That swing was
  the wrong sound. Held over silence, it can't be heard.

`svcGetSystemInfo(0x20000, 0)` tells the two apart. Type 0x20000 is
Citra's and Azahar's own (EMULATOR_ID: 1 on Citra, 2 on Azahar). A 3DS's
kernel has no such type and returns an error. `audioHoldTick` runs once a
frame in the main loop and lets go when the time comes, logging "audio:
back after the applet".

Azahar's dialog does not show the initial text: its edit starts empty.

## Leaving

Retail's BACK saves on the Autosave screen only when something changed
and autosave is on. With autosave off it leaves, and the changes stay
unsaved.

The port's BACK asks first, with autosave on or off (the user's word,
2026-10-13). If anything differs from the names and genders on entry,
it holds the move back and opens memcard.c's popup, titled "Save"
(150000): "Save your changes to the card?". The screen hides under it,
as the debug menu's does.

| Answer | What happens |
|---|---|
| Yes (150103) | The Autosave screen takes NameEntry's place, and its end moves back to Options. |
| No (150104) | The names and genders go back to how the screen found them, and the screen moves back. |
| B | Stays on Player Names. |

With a save already on the card, the Autosave screen then asks its own
question, retail's "Overwrite existing game settings...?", opened on No.
The end of a race asks the same one.

## Testing

`tools/run_azahar_nameentry.ps1` boots the game in Azahar and walks to
Player Names (Options, then four rows down). It drives Azahar's
keyboard dialog through UI Automation: the edit's ValuePattern, then the
button invoked by name. The dialog is titled "Azahar", so the script
takes the process's new window. Azahar sometimes drops an A posted just
after its dialog closed, so the script presses A again while no keyboard
opens. The steps:

1. A, "Racer7", OK: the name lands.
2. A, "Zzz", Cancel: "Racer7" kept.
3. Down, Right: the gender switched.
4. Down: no Player 2 row in the log.
5. "audio: back after the applet" twice.
6. B: the prompt. B on it: stay.
7. B, Yes, and Yes to the overwrite question: back on Options.
8. In again: "Racer7" kept.
9. Down, Right, B, No: the gender back as it was.

`NFSHP2/SAVES/settings.db` is put back afterwards. The verdict on
2026-10-13: "PASS (keyboard, OK, Cancel, sound, prompt: stay, yes, no)".
