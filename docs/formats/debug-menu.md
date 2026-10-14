# The debug menu (TASKS 53)

The port's own debug menu. Retail's frontend has none. Its "Debug Menu"
(INGAMEB d4742cd7, PauseDebugMenu) is a pause screen of in-race toggles,
and the disc never reaches it. This one is a fourth item on the main
menu, "Debug Menu". It stays hidden until one of two things shows it:

- L, R and D-Pad Up pressed together on the main menu (an Easter egg's
  sound plays);
- `DebugMenu 1` in `nfshp2_config.txt`.

It leads to two screens in Be The Cop Setup's look.

The code has two halves:

- `debugmenu_patch.c` rebuilds FRONTB's Flailer chunk at boot. It is
  free of `<3ds.h>`, so `tools/debugmenu_check.py` runs it on the host.
- `debugmenu.c` is the screens' callbacks.

## The chunk

`debugmenu_patch_frontend` copies FRONTB's Flailer chunk with two
changes, and bui reads the copy in its place.

**The main menu.** NEW_MAIN_MENU gains three objects, all invisible:

| Object | Hidden name | What it is |
|---|---|---|
| The item | `PORT_DEBUG_ITEM` | A copy of MENUITEM_3 (Options), "Debug Menu" |
| Its mask | `PORT_DEBUG_MASK` | A copy of MI_3_MASK |
| A filler | `PORT_DEBUG_FILL` | Covers the panel down to its bottom |

`debugmenu_reveal` makes the three visible. It also writes MENUITEM_4
and MI_4_MASK over the two hidden names, and cuts the panel's bottom
filler (BOTTOM_MASK) to a separator above the item. The main menu is
entered again afterwards, so its menu and SelectionSet find the item.

**The two screens.** Both come after the last screen and are copies of
Be The Cop Setup (d1eadbca). Each copy is renamed and titled, and its
texts are given room for the port's strings. Both leave out Be The Cop
Setup's eighth row, the blooms' spare texts and the scroll clip.

| Screen | Name (bStringHash) | ChangeToScreen name | Rows |
|---|---|---|---|
| Debug Menu | `PORT_DEBUG_MENU` d98ab71e | "Port Debug Menu" | 5 |
| Debug Race | `PORT_DEBUG_RACE` d98d6284 | "Port Debug Race" | 7, scrolled |

Debug Menu loses rows 6 and 7's labels and values. Their masks stay
and darken the panel under its last row.

## Debug Menu

| Row | What it does |
|---|---|
| Start Debug Race | Goes to Debug Race (pushed, so B comes back). |
| NFS Points | Left and Right change the points by 10,000; A adds 100,000. Kept between 0 and 99,990,000. |
| Set Save to 100% | Every event of both careers won, plus every task and points reward. |
| Unlock Everything | Fills in only what falls short, and every reward. |
| Lock Everything | As a new profile. |

**Set Save to 100%.** This is retail's UnlockEvents (`unlock_events`),
which nothing on the disc calls. Every event of the Championship and
Hot Pursuit trees gets the best result its state holds:

- first place;
- the best time;
- a won knockout or tournament.

That includes the shared Ultimate. Every task reward
(`TaskRewardStates`, 10) and points reward (`PointsRewardStates`, 18)
is then taken. The NFS points are not touched.

Nothing in retail computes a career percentage. Its own "finished" test
is both Ultimates passed (`event_trees_both_ultimates_passed`).

**Unlock Everything.** Every car and track in this game comes from the
career: an event's rewards, a task or a points threshold
(`fred_make_challenge_cars_available`). So unlocking them means passing
events. This row unlocks only the events that fall short, meaning not
passed or with a reward not earned (`event_info_unlock_state`), and
takes every reward. Results already won are kept.

**Lock Everything.** Retail's LockEvents, with the rewards cleared.

Each of the three remakes the players' car lists afterwards and shows
"Done" on its row.

## Debug Race

Start Race is the top row, then Mode, Track, Time Of Day, Direction,
Car, Colour, Opponents, Laps, Traffic, Difficulty and Gearbox. A starts
the race. A Hot Pursuit or Single Race is StartQuickRace (Express, game
type 2). Be The Cop is what its setup, car select and track select
leave behind. The settings last until the next boot.

## The save prompt

The rows change Fred, not the card. Entering Debug Menu from the main
menu takes a copy of what they touch:

- both careers' states;
- the task and points rewards;
- the two players, who hold the points and car lists.

Two moves check the save against that copy: B on Debug Menu, and A on
Start Race. If anything differs, the screen hides and the memory card's
popup asks "Save your changes to the card?", titled "Save" (150000)
with Yes and No (150103, 150104):

| Answer | What happens |
|---|---|
| Yes | The Autosave screen replaces the current one and saves as the end of a race does, with the card's own overwrite or create question. Leaving: its end moves back to the main menu. Before a race: its completion callback starts the race. |
| No | The copy goes back into Fred. Then Debug Menu moves back to the main menu, or the race starts. |
| B | Nothing changes; the screen shows again. |

Points moved and then moved back count as no change.

The log says what was done and answered, as `debug menu: ...` lines.
For example: `points 21100`, `save set to 100%`, `unlocked, 63 events
filled in`, `asking to save`, `save: yes`, `race: Be The Cop, track 11,
car 4`.

## Checks

- `tools/debugmenu_check.py`: the patch against retail's FRONTB, byte
  for byte but what it changes, and the reveal.
- `tools/run_azahar_debugmenu.ps1`:
  - By default: the chord, the points, Set Save to 100%, B and B on
    the prompt, Debug Race's rows scrolled and wrapped, then Start
    Race, No, and the race.
  - `-Cop`: the config line, Unlock Everything, Be The Cop, B twice,
    Yes and the card's Yes. The save is written and the run returns to
    the main menu; then in again, and the race starts with no prompt.
    The config and `settings.db` are put back after.
