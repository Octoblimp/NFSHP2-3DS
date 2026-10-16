# The debug menu (TASKS 53)

The port's own debug menu. Retail's frontend has none. Its "Debug Menu"
(INGAMEB d4742cd7, PauseDebugMenu) is a pause screen of in-race toggles,
and the disc never reaches it. This one is the main menu's fifth item,
"Debug Menu", the only one under Options (TASKS 68, "The main menu's
order" below). It stays hidden until one of two things shows it:

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

**The main menu.** NEW_MAIN_MENU gains six objects, two rows of three.
Its bottom filler (the tallest BOTTOM_MASK, from y 228 at ScaleY 7.063,
down to 341) is cut to a separator (ScaleY 0.625, 10 px) for good, and
the two rows take the 113 px it covered. Each label is a copy of
MENUITEM_3 (Options) at MENUITEM_2's X, each mask a copy of MI_3_MASK,
each filler a copy of the cut filler from under its slot's mask down to
where that filler ended. Then the rows are laid out in the port's order
(below), which puts Local Wireless in Options' place and Options a row
down:

| Object | Name | Shown | What it is |
|---|---|---|---|
| Local Wireless | MENUITEM_4 | yes | y 181, LanguageID 2000000 |
| Its mask | MI_4_MASK | yes | y 183 |
| The fourth slot's filler | `PORT_FILL_4` | yes | y 283 to 341, ScaleY 3.625 |
| The debug item | `PORT_DEBUG_ITEM` | no | y 291, "Debug Menu" |
| Its mask | `PORT_DEBUG_MASK` | no | y 293 |
| The fifth slot's filler | `PORT_FILL_5` | no | y 338 to 341, ScaleY 0.1875 |
| Options (retail's) | MENUITEM_3 | yes | y 236, was 181 |
| Its mask (retail's) | MI_3_MASK | yes | y 238, was 183 |

`debugmenu_reveal` writes MENUITEM_5 and MI_5_MASK over the two hidden
names, puts the row last in the order and lays the rows out again,
which shows its three objects and cuts the fourth slot's filler to a
separator above it. The main menu is entered again afterwards, so its
menu and SelectionSet find the item.

## The main menu's order

The user, 2026-10-15: "Every option should be above "Options" except
"Debug Menu"", and the menu should scroll "if there's too many items to
fit at once" (TASKS 68). The rows are:

| Row | Item | Mask |
|---|---|---|
| 1 | Hot Pursuit, MENUITEM_1 | MI_1_MASK |
| 2 | World Racing, MENUITEM_2 | MI_2_MASK |
| 3 | Local Wireless, MENUITEM_4 | MI_4_MASK |
| 4 | Options, MENUITEM_3 | MI_3_MASK |
| 5 | Debug Menu, MENUITEM_5, once shown | MI_5_MASK |

A row the port adds later goes above Options too.

The panel has five slots, 55 px apart: retail's three rows (labels at y
71, 126 and 181, masks at 73, 128 and 183), then two more a row's step
down. `debugmenu_patch.c` keeps the rows in that order and writes each
row's label and mask Y to its slot's, in the buffer bui reads live; X
stays the row's own, so Options keeps the two pixels it sits right of
the rest in retail. main.c's `bmenu_reorder` (bmenu.h) sorts the
screen's FlailerMenu by `debugmenu_main_rank`, so Up and Down go by the
rows as drawn, and gameflow's saved item (an index) means the same row
each time.

With more rows than slots, a window of five follows the highlight:
`debugmenu_main_show`, from main.c's menu callback on each highlight,
moves it just far enough to hold the row, and lays the rows out again.
Rows outside the window are hidden, label and mask. Under the slots in
use, each filler is a separator but the last row's, which runs down to
the panel's bottom (341); a slot not in use has none. Each slot's
filler is its own object: retail's two thin separators under the first
two, retail's cut filler under the third, `PORT_FILL_4` and
`PORT_FILL_5` under the last two. With the looping moves, Down from the
last row brings the window back to the top, and Up from the first takes
it to the bottom.

Three things on the screen move or read the rows and are kept in step:

- The brackets (MI_OVERSCORE and MI_UNDERSCORE) move to the
  highlighted row's mask in gameflow's OnHighlight. So the window moves
  before the highlight reaches the screen.
- SelectionSet (IndicatorMode 1) shows every mask but the highlighted
  row's. It shows the mask of the row left after the window has moved,
  and that row may be out of it now. So the rows are laid out again
  after the screen has had the highlight, with every mask in the
  window shown but the highlighted row's and the rest hidden.
- The slide-in (tSlideInAnimation, ticked by gameflow's mainMenuTick)
  moves each MENUITEM_n_GROUP to the Y its MI_n_MASK had when the
  screen opened, and the screen's close puts each group back there.
  The port's two rows are copies of Options' label and mask, group and
  all, so they slide with Options, as the third row does in retail. Once
  the window has moved, the groups' Ys are not the rows': the groups
  would put World Racing over Local Wireless on the way back from
  Options. So main.c lays the rows out again after each frame's tick
  on the main menu (`debugmenu_main_tick`), and only X is the slide's.

Five rows fit, so today the window never moves. The log says
`main menu: rows from n` when the window's first row changes. A test
build with the window cut to three rows, on Azahar (run_azahar_test):
down three from Hot Pursuit, the window moved ("rows from 1") to World
Racing, Local Wireless and Options, the brackets on Options; back from
Options, the same three, the brackets where they were. Before the
frame's layout, that return showed an empty first slot and World
Racing over Local Wireless.

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
  for byte but what it changes (the six objects, each row and filler
  where its slot puts it, Options' label and mask a row down, and the
  cut filler), and the reveal, which changes the debug row's three and
  the fourth slot's filler and nothing else. Then the order (the rank
  of MENUITEM_1 to 5) and the scroll: with 3, 4 and 5 slots, the
  highlight down the rows twice round, up twice round and up once more,
  each step's labels, masks and fillers against a model of the window,
  and the window clamped when the slots grow. After each step a tick:
  every label and mask moved down, as a group's saved Y leaves them,
  then `debugmenu_main_tick`, which must give the step back. Eighteen
  hand mutants of the layout and the tick, all caught.
- `tools/bmenu_check.py`: `bmenu_reorder` on every FRONTB menu, by the
  item's hash mod 3, against the Python model: the order kept for equal
  ranks, the current item kept, the moves by the new order.
- `tools/run_azahar_debugmenu.ps1`:
  - By default: the chord, the points, Set Save to 100%, B and B on
    the prompt, Debug Race's rows scrolled and wrapped, then Start
    Race, No, and the race.
  - `-Cop`: the config line, Unlock Everything, Be The Cop, B twice,
    Yes and the card's Yes. The save is written and the run returns to
    the main menu; then in again, and the race starts with no prompt.
    The config and `settings.db` are put back after.
