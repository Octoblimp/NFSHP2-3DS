# The end of a race

When a race is over, the game shows a run of screens: rewards, results,
best times, and last the End Game Menu (Next Race, Restart, Quit...). The
code is retail's END_GAME_SCREENS module, `0x001dc6e8` to `0x001e25e8`.
Slice RE-1 ported its frame in `3DS Files/source/endgame.c`. The frame is
the list of screens, the class each screen gets, their shared callback and
the End Game Menu.

The coordinator side is in [race-coordinator.md](race-coordinator.md):

- `TheRaceHasFinished` (`rcstates.c`) works out what comes after the race.
  It is NEXT_RACE when the FED has another race, NONE for a multi-track
  event with none left, and RESTART otherwise. It then makes the list,
  `bMalloc(72, "EndGameScreens", 0, 16)`, and changes to
  `RCSTATE_POSTRACE`.
- `RCSTATE_POSTRACE`'s ACTIVATE (`rcpost.c`) calls `ResumeScreens`. Its
  UNACTIVATE calls `SuspendScreens`.
- The RaceCoordinator's destructor deletes the list.

## The list

`BuildScreenList` asks each test in turn. Each screen that passes is put
on the end of a `bPList` of names:

| Screen | Shown when |
|---|---|
| Points Rewards | `PointsRewardEarned` is not -1, and `IsCarUnlocked(GetCarTypeForPointsReward(it), 3)` (its answer as it is) |
| Task Rewards | `TaskRewardEarned` is not -1 |
| Events Unlocked | an event tree's race (`UseTreeEvent`), RaceEvent status 4, the status advanced, and more than 0 events opened (`0x001f7458`) |
| Reward menu | an event tree's race, and one of the reward cases below |
| Be The Cop Results 1P | Be A Cop with one player car |
| Be The Cop Results 2P | Be A Cop with two |
| Race Results | not Be A Cop, not GameType 6, and for GameType 8 or 9 a RaceEvent whose type is not 1 |
| Tourney Standings | not Be A Cop, GameType 8 or 9, and RaceEvent type 4 |
| Best Lap Times | not Be A Cop, not GameType 6, a lapped race (`Point2Point` 0), and not one lap |
| Best Total Times | as Race Results |
| End Game Menu | always |

The Reward menu shows for event 32, or for event 31 with its word at +120
clear. Otherwise it shows when one of the event's rewards fails its test
(`0x00200b30`) while the status is 3 or more. An event with no rewards
shows it when the status is 3 or more and has advanced; that test's
answer is returned as it is.

`ShouldAutoSave` is `Fred.Autosave != 0`. `0x001dcac0` is GameType not 6;
ShowPointsResults uses it (RE-2).

### `EndGameScreens`, 72 bytes

| Offset | Field |
|---:|---|
| 0 | `ScreensEnabled`: 1 between Resume and Suspend |
| 4 | `LatestConstructed`: never written |
| 8 | `ContinueRaceType`: the constructor's argument, never read |
| 12 | `ScreenList`: the head of the `bPList` (next, prev) |
| 20 | `CurrentScreen`: the node of the screen up |
| 24 | twelve words, zeroed and never read |

The constructor sets `pEndGameScreens` (gp-17628), builds the list, and
makes its first node current. The destructor changes to no screen if the
screens are enabled. It clears `pEndGameScreens`, gives every node back,
and deletes the list with flags & 1.

The list's members:

- **GetNextScreen**: the name after the current one, or NULL at the end.
- **AdvanceScreen**: the next node becomes current, unless at the end.
- **MoveBackScreen**: the node before becomes current, unless at the first.
- **AtRoot**: whether the first node is current.
- **RemoveScreen**: the first node with that name is taken off.
- **ResumeScreens**: once only, it brings the current screen up with a
  push, and shows the letterbox bars (`0x49c15518`). If the current screen
  is "Autosave", that node is taken off and the screen is pushed, and the
  autosave callback is set.
- **SuspendScreens**: once only, no screen and no bars.
- **AutosaveCompletedCallback**: the next screen up.
  `SetAutosaveCallback` hands that to `SetAutosaveCompletionCallback`
  through the bridge `0x001e25e8`, on `pEndGameScreens`.

Nothing on the retail disc puts "Autosave" on the list. The menu changes
to it straight, in its popups' answers (below).

## The screens

The screens are in INGAMEB. Each one's FlailerScreenConfig is made by a
global constructor (`0x001e1f4c` to `0x001e2140`), and all of them have
the callback `0x001dd278`:

| Name | Screen hash |
|---|---|
| Points Rewards, Task Rewards, Events Unlocked, Reward menu | `0x7e420558` |
| Race Results | `0xab049b2b` |
| Tourney Standings | `0x0532b6ff` |
| Best Lap Times | `0xacb2a4ca` |
| Best Total Times | `0xf5a3cf51` |
| End Game Menu | `0x1a64e903` |
| Be The Cop Results 1P, 2P | `0x67eb8d12`, `0x67eb8d33` |
| Lap Times 1P, 2P | `0xc4881cbd`, `0xc4881cde` |

`tools/screen_registry.py` reads the demo's ELF. Its list has "Be The
Cop Results" and no Events Unlocked, so `--check-port` flags those three
rows. Retail registers them, at `0x001e2018`, `0x001e20c8` and
`0x001e20f4`.

### The callback

- **ACTIVATE** reads the name of the screen that came up, from the Flailer
  list's current screen (+412, its config at +16, the name at +8). The
  class for that name is made with bMalloc in pool 16. Its constructor is
  given the item hash. Then `Constructed` runs, which is empty.
- **UNACTIVATE** calls the class's destructor with flags 3 and clears
  `pEndGameMenuInstance` (gp-17568).
- **Any other message** goes to the class's HandleEvent.

| Screen | Size | Allocation name | Constructor |
|---|---:|---|---|
| Points Rewards | 8 | Points Rewards | `0x001de568` |
| Task Rewards | 8 | Task Rewards | `0x001de6a8` |
| Events Unlocked | 8 | Events Unlocked | `0x001df180` |
| Reward menu | 8 | EventRewardScreen | `0x001def38` |
| Race Results | 60 | RaceResultsScreen | `0x001dffe8` |
| Tourney Standings | 8 | TourneyStandingsScreen | `0x001dd5d0` |
| Best Lap Times | 8 | BestLapTimes | `0x001ddc10` |
| Best Total Times | 8 | BestTotalTimes | `0x001ddfd0` |
| End Game Menu | 112 | EndGameMenu | `0x001e12b8` |
| Be The Cop Results 1P | 8 | BeACopResults1P | `0x001e0898` |
| Be The Cop Results 2P | 8 | BeACopResults2P | `0x001e0a10` |

A name with no class leaves the instance as it was. The Lap Times screens
have a callback of their own (`0x001e10f0`, [best-times.md](best-times.md)).

### `EndGameMenusBase`, 8 bytes

`ScreenHash` at 0 and the vtable at 4. The vtable entries are {short
delta, function}: Scroll +8, HandleEvent +16, Tick +24, Render +32 and the
destructor +40. Retail's base vtable is at `0x002b9148`.

The constructor shows the screen's "previous" prompt (`0xaf6f1cdc`)
unless the list is at its first screen. Its HandleEvent:

| Message | Does |
|---|---|
| SELECT | the next screen up. If it is "Autosave", that node is taken off first, and the autosave callback is set. |
| BACK | the screen before up, with the cancel noise (6). At the first screen it is silent. The param is cleared. |
| PAD_UP, PAD_DOWN | silent |
| PAD_LEFT, PAD_RIGHT | Scroll |
| TICK, RENDER | Tick, Render |

The destructor puts the base vtable back and deletes with flags & 1.

## The End Game Menu

`END_GAME_MENU` (`0x1a64e903`) has a title (`0x5964eab1`), the bloom's
text (`0xab671c9a`), and `MENUITEM_1` to `MENUITEM_6` (`0x52e039f3` on).
The constructor:

1. puts the bloom on the menu, colour `0x80`;
2. fills the labels for the race;
3. clears the ACTIVATE's param;
4. adds an item for each kind the race has, in this order.

| Item | When | Label |
|---|---|---|
| Next Race | multi-track, with another race | [10] |
| Restart Race | not GameType 8 or 9, or a multi-track one | [1] |
| Restart Event | multi-track, or a race event's (GameType 4, 8 or 9) | [4] |
| View Replay | the replay's word at +12 is 0 | [13] |
| View Lap Times | not Be A Cop | [14] |
| Quit Race | always | [7] |

Each item goes on the next MENUITEM: named with `SetLanguageID` and
turned on with GrayMenuItem mode 1. The MENUITEMs left over are hidden
(mode 2), and the title gets label [0].

### The labels

InitLabels fills fifteen words with -1, then:

| | event tree | Be A Cop | anything else |
|---|---|---|---|
| [0] title | `0x30da4` with another race, else `0x30da6` | `0x30da5` | `0x30da4` |
| [1] Restart Race | `0x30d45` | `0x30d51` | `0x30d45` |
| [2] its message | `0x38271` | `0x38281` | `0x38271` |
| [3] its title | `0x3827c` | `0x38285` | `0x3827c` |
| [7] Quit Race | `0x38338` (GameType 9), else `0x3833a` | `0x30d52` | `0x30d46` |
| [8] its message | `0x38339` (GameType 9), else `0x3833b` | `0x38282` | `0x38272` |
| [9] its title | `0x38287` | `0x38283` | `0x3827b` |

The rest are the same for every race: [4] Restart Event `0x30d4d`, [5]
`0x38280`, [6] `0x38286`, [10] Next Race `0x4baf2`, [11] `0x382d5`, [12]
`0x382d4`, [13] View Replay `0x30d43`, [14] View Lap Times `0x4bd49`.

### The items

SELECT finds the item by its MENUITEM:

| Item | Does |
|---|---|
| Next Race | popup: title [12], message [11] |
| Restart Race | popup: title [3], message [2] |
| Restart Event | popup: title [6], message [5] |
| View Replay | `PostMessage(RC_START_REPLAY, 0)` |
| View Lap Times | pushes "Lap Times 1P", or "Lap Times 2P" if the race has more than one player car |
| Quit Race | popup: title [9], message [8] |

The popup is `POPUP` (`0x037f3133`) with two buttons, OK `0x38277`
(param 1) and Cancel `0x38278` (param 0). The flags are horizontal and
cancelable, the start button is 1 and the port is -1. Its parent is the
screen up. The menu records which item asked, in `State`, and hides
itself.

The popup's dismiss:

| State | OK |
|---|---|
| Quit (2) | `KeepState` for a race event's race, then RC_QUIT_RACE (0). With autosave on, it changes to "Autosave" first and the quit is its callback. |
| Restart Race (0) | `KeepState` for a race event's race, then RC_RESTART_RACE (0). |
| Restart Event (1) | `0x00201b38` (the event back to its first race), then RC_NEXT_RACE (0). |
| Next Race (3) | RC_NEXT_RACE (1). With autosave on and the status not fallen (`0x00201bd8`), it goes through "Autosave" as Quit does. |

Cancel (param 0) shows the menu again. Any other state does nothing.

The menu's BACK is the base's but leaves the noise as it is. TICK
animates the bloom and HIGHLIGHT moves it (`tHighlightAnimation`'s
HandleMessage).

### `EndGameMenu`, 112 bytes

| Offset | Field |
|---:|---|
| 0 | the base |
| 8 | `State`: the popup's item, 0 to 3; the constructor leaves it unwritten |
| 12 | `Highlight`: the bloom |
| 44 | `Labels`: fifteen LanguageIDs |
| 104 | `Items`: a list of `EndGameMenuItem`s, 20 bytes each (node, Label, Hash, Kind) |

The destructor deletes the items, then runs the base's destructor.

## The port

The seams are in `endgame.h`. main.c fills them:

| Seam | main.c |
|---|---|
| `gEndGameScreensCtorFn`, `DestroyFn`, `ResumeFn`, `SuspendFn` | `endgame_screens_*` |
| `gEndGameTranslateFn` | `startRaceTranslate` |
| `gEndGameMenuAnimFn` | `pauseMenuAnim`, the pause menu's |
| `gSetAutosaveCompletionCallbackFn` | `endGameAutosaveNow`: no Autosave screen, so the callback runs at once |
| `gFEDIsThereAnotherRaceFn`, `gFEDIsMultiTrackFn` | `fedIsThereAnotherRace`, `fedIsMultiTrack`, on `Fred` |

The eleven screens are rows of `kScreens` with `endgame_screen_callback`.
Race Results, Points Rewards and Task Rewards have their classes
(`endresults.c`, RE-2b; [race-results.md](race-results.md)), and so do
Best Lap Times and Best Total Times (`endtimes.c`, RE-3;
[best-times.md](best-times.md)). Until the others are ported (RE-6),
each one shows the screen with a bare base, which only walks the list.
Lap Times 1P and 2P are rows of their own, with
`lap_times_display_callback`.

Three of retail's reads are tested first in the port:

- `pEndGameScreens` in the base's SELECT, BACK and the bridge.
- the instance for messages other than ACTIVATE and UNACTIVATE.
- `pReplayManager` for View Replay. The port has none yet, so View Replay
  stays hidden.

## Checking

`tools/endgame_check.py` runs the whole module in
`retail_model.RetailEmu`, next to `tools/src/endgame_test.c`. The other
screens' constructors are the base on both sides. Tourney Standings' can
be a probe instead, to show the base's Scroll, Tick and Render calls.

The result is 24325 ops, 78957 lines, 0 differ. `--mutate` catches 270 of
272 mutations; the other two are equivalent:

- the empty list's current screen: it cannot happen, as the End Game
  Menu is always on the list.
- InitLabels' memset of 0xff: every word is written after it.
