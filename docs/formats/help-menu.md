# The HELP panel: tHelpMenu (TASKS 48)

Retail's frontend draws a Circle and "help" bottom left on every screen
that has help lines. Circle (MENU_HELP) slides the HELP panel in over the
screen; Circle again sends it out. `helpmenu.c` ports tHelpMenu and
FlailerScreenList's part in it; `main.c`'s `flowInput` sends it the key.

| Retail | Address | Port |
|---|---|---|
| tHelpMenu::tHelpMenu | 0x001e3b88 | `helpmenu_construct` |
| tHelpMenu::Summon(FlailerScreenNode *) | 0x001e3c50 | `helpmenu_lines` + `helpmenu_summon` |
| IsHelpSpace | 0x001e3c68 | `helpmenu_is_help_space` |
| tHelpMenu::SplitHelp | 0x001e3c98 | `helpmenu_split` |
| tHelpMenu::Reset | 0x001e3db8 | `helpmenu_reset` (empty) |
| the help turned off (gp-17344 = 0) | 0x001e3dd0 | `helpmenu_disable` |
| tHelpMenu::Summon(int *) | 0x001e3dd8 | `helpmenu_summon` |
| tHelpMenu::Dismiss | 0x001e3fa0 | `helpmenu_dismiss` |
| tHelpMenu::Tick | 0x001e4028 | `helpmenu_tick` |
| tHelpMenu::IsActive | 0x001e4170 | `helpmenu_is_active` |
| SetHelpOverride(int *) | 0x0016d448 | `helpmenu_set_override` |
| FlailerScreenList::JoyHandler's help | 0x0016cab0, 0x0016ca40 | `flowInput`, `helpmenu_toggle` |
| IsHelpCharacter | 0x00141db0 | `helpmenu_is_help_character` |

## The screen

GLOBALB's screen 0x087cd45c, loaded with the global chunks:

| Object | Hash | Use |
|---|---|---|
| backdrop | 7830fd99 | the one object of the fade (an feAlphaAnimation) |
| anchor | 49b30391 | the group's place: x 53 in, its Y kept |
| group | 3c86db48 | everything that slides |
| buttons, row i | 8c92aa9a + i | the line's buttons, x 69 |
| text, row i | eacf0330 + i | the line's text, x 190 |

There are eight rows. The HELP title is part of the group.

## Summon, Dismiss, Tick

- **Summon(lines)**: nothing when the help is off. Otherwise one more
  summons; with lines, the select sound (the common region's MenuSelect,
  MakeFrontendSound's event 5, when SoundEnabled), the slide in to 53,
  and each row up to the first 0 translated, split and shown. The rows
  after it are hidden.
- **Dismiss**: the slide out to 650 (gp-0x6e44), and the sound if
  anything was ever summoned.
- **The key** (0x0016ca40): Summon with the override's lines or the
  screen's when the panel is not active, else Dismiss. 0x0016cab0 only
  passes MENU_HELP on when no popup is up and the screen hears the port.
  While the panel is active, the list gives nothing to the popups, the
  screen or its menu.
- **IsActive**: the slide's target is short of 640: coming in or there.
  CarSelector::CanEnterOrbitMode (0x001968e0) asks it too.
- **Tick**, after the screen's: the screen is shown when the slide's
  value goes under 640 and hidden when it goes back over (only once
  anything was summoned; Tick tests before it steps, so the screen shows
  on the tick after it crosses). The group moves to the slide's x
  (truncated), the backdrop's alpha is scaled by
  1 - (x - 320) / 320 from x 320 on (DAT_0032eab4 is 0.003125), and the
  slide steps.

The slide is a tCubic1D of half a second (`BSpline`, arrival threshold
1), bMalloc'd in retail and inline here.

## SplitHelp

A translated line is its buttons, then its text: "\x81 Enter game mode".
The leading run of help characters (0x80..0x9d but 0x92, the
apostrophe), help spaces (space, tab) and '+' goes to the buttons, with
the spaces dropped and '+' as " + ". The rest is the text. Retail would
read past the end of a line of nothing but buttons and bounds neither
buffer; the port stops at the terminator and at 128 bytes.

The buttons column draws each help character as the 3DS key
(`helpglyph.c`): Cross A, Triangle B, Square X, Circle Y, L1 L.

The "Help" mark bottom left of each screen is not a help character but
BUTTONSOUT text, `k` (Circle). `uirender.c` draws such a glyph as the 3DS
key as well (flailer-ui.md, "Help characters"), so it shows Y.

## The lines

A screen's lines are its FlailerScreenConfig's HelpMenuItems (+0x34,
from 0x0031a438). `helpmenu_screen_lines` has those of every screen the
port registers. SetHelpOverride replaces them while a screen wants its
own (the setups, car select, the event tree) and turns the help back
on; NULL puts the screen's back. The event tree's popup turns the help
off (0x001e3dd0) until the next override.

Port changes:

- Joystick PreConfig shows 802202 and 802203 only: the port's page has
  one row and no vibration.
- The Controller page (Joystick Config Port1) has none: its keys are on
  the bottom screen.

## The 3DS keys

The user, 2026-10-16: Help is Y. Y was MENU_SQUARE, so Square moved:

| Key | Menus (`main.c`'s `kBinds`) | joyhid's frontend layout |
|---|---|---|
| A | MENU_SELECT (Cross) | Cross |
| B | MENU_BACK | Triangle (B and X swap) |
| X | MENU_SQUARE | Square: car select's orbit view |
| Y | MENU_HELP, the HELP panel | Circle |
| L | MENU_L1, and held, the Mode Selects' manual transmission | L1 |

The Mode Selects' quick race reads the transmission from L1 held (line
802231, "L1 + Cross Manual Transmission in Quick Race"); the port held X
until Square moved there. It is the Mode Selects' own handler, so the
panel does not stop it.

## Checks

- `tools/helpmenu_check.py` (`tools/src/helpmenu_test.c`): SplitHelp,
  the summon and dismiss, the slide and its screen, the override and
  the screens' lines.
- `tools/joyhid_check.py`, `tools/helpglyph_check.py`: the frontend
  layout's keys and their icons.
- `tools/run_azahar_help.ps1`: Y on the main menu, Hot Pursuit's Mode
  Select and Options; A does nothing while the panel is up.
