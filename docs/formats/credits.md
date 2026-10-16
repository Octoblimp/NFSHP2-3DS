# Credits (TASKS 71a)

Options' Credits is retail's `CreditsScreen`, with the two credit rolls
(`CreditsScroller`) and the movie player behind its rows
(`credits.c`, `credits.h`). Seven names in main.c's `kScreens[]` reach
three callbacks:

| Config name | Flailer screen | Callback |
|---|---|---|
| "Credits" | fd8a3b6d | `credits_screen_callback` (0x001f21b0) |
| "EACredits", "BBGCredits" | 39c4c62c | `credits_scroller_callback` (0x001f3320) |
| "Credits FE Movie", "Credits Reward movie", "BBG Creation movie", "BBG Credits movie" | b5761d00, the title's | `credits_movie_callback` (0x001f2470) |

The scroller and the movie player tell what they are by the name the
screen was entered under (`gf->screen->name`), as retail's do.

| Retail function | Address | Port |
|---|---|---|
| CreditsScreen::CreditsScreen | 0x001f1f38 | `screenConstruct` |
| CreditsScreen::~CreditsScreen | 0x001f1ff0 | `screenDestruct` |
| CreditsScreen::HandleEvent | 0x001f2070 | `screenEvent` |
| the movie player's constructor | 0x001f2240 | `movieConstruct` |
| its destructor | 0x001f2358 | `movieDestruct` |
| its finish | 0x001f23b8 | `movieDone` |
| its HandleEvent | 0x001f23d8 | `movieEvent` |
| the markup's copy-until | 0x001f25c8 | `copyUntil` |
| `$RGB(..)` | 0x001f26c8 | `parseRGB` |
| `$FONT(..)` | 0x001f27b8 | `parseFont` |
| the markup parser | 0x001f2808 | `credits_parse` |
| CreditsLine::SetLanguageID | 0x001f2a30 | `lineSet` |
| CreditsLine::Animate | 0x001f2bc8 | `lineAnimate` |
| CreditsLine::PleaseResetMe | 0x001f2c20 | `lineGone` |
| the slideshow's constructor | 0x001f2c68 | `bgInit` |
| its picker | 0x001f2d28 | `bgPick` |
| its Tick | 0x001f2d90 | `bgTick` |
| CreditsScroller::CreditsScroller | 0x001f2e80 | `scrollerConstruct` |
| CreditsScroller::BuildCredits | 0x001f2fa0 | `scrollerBuild` |
| CreditsScroller::GetMaxY | 0x001f30f8 | `scrollerMaxY` |
| CreditsScroller::Tock | 0x001f31a8 | `scrollerTock` |
| CreditsScroller::HandleEvent | 0x001f3268 | `scrollerEvent` |

## The menu

The panel slides on over Options (`tSlideOnScreen`, object aed1a723,
group 718cd8c3, Options 95ad096b shown behind), with the bloom on the
selected row (`tHighlightAnimation`, ab671c9a, colour 0x00000080). The
constructor starts the menus' movie (`MOVIES\options_movie_new.AVI`), as
every Options page does.

| Row | Item | A |
|---|---|---|
| Electronic Arts | MENUITEM_1 | "EACredits" |
| Black Box Games | MENUITEM_2 | "BBG Credits movie" |
| View Intro Movie | MENUITEM_3 | "Credits FE Movie" |
| The Making of HP2 | MENUITEM_4 | "BBG Creation movie" |
| View Reward Movie | MENUITEM_5 | "Credits Reward movie" |

Each is ChangeToScreen with the menu pushed, so B comes back to it.
MENUITEM_5 is grayed with mode 1 (enabled) when both trees' Ultimates
are won (`event_trees_both_ultimates_passed`, 0x002026f8), and with mode
2 (hidden) otherwise.

## The rolls

Every text of group d2638b19 on screen 39c4c62c is a line (20 of them),
cut to the clip poly a94bd818. BuildCredits fills them with consecutive
LanguageIDs from y = 240 down:

| Roll | First | Last |
|---|---|---|
| Electronic Arts (type 0) | 501000 (0x7a508) | 501614 (0x7a76e) |
| Black Box Games (type 1) | 601000 (0x92ba8) | 601226 (0x92c8a) |

Each tick, a line whose top is above 0 takes the next id and goes below
the lowest line (GetMaxY, at least -10); when the ids pass the last they
start again from the first. Every other line moves up 30 pixels a
second. The pad's directions nudge the roll on by a second's worth
(sound 28), Y (SQUARE) pauses it and lets it go (MENU_SELECT), and A is
silent.

### The markup

The strings carry their own colour and font: `$RGB(r,g,b)` and
`$FONT(NAME)`, with `$$` for a dollar. The tags' arguments, brackets and
all, go to 32-byte buffers; everything outside them is the text. RGB is
the word `0x80000000 | b << 16 | g << 8 | r`, each part 128 when it is
missing. FONT is the bStringHash of the name.

| Font named | Scale | Font drawn |
|---|---|---|
| FONT_IMPACTBIG (2d213565) | 0.6 | it |
| FONT_IMPACTNORMAL (5f3a4a3c) | 0.6 | it |
| anything else, or none | 1.0 | FONT_STATS (a9bfda04) |

A line with no tag keeps its LanguageID, so the renderer translates it.
A line with a tag gets the parsed text through SetString. The colour is
0x80808080 when no RGB was given.

The headings' strings are long with their tags.
"$RGB(134,96,48)$FONT(FONT_IMPACTNORMAL)Senior Development Director" is
66 bytes. The port's GetTranslatedString (`fredTranslate`) held 64, and
cut the heading to "Senior Development Direc". It holds 512 now; retail
answers with the table's own string.

### The slideshow

Two bitmaps behind the lines, f947e681 under 4ef4d164, show
CREDITS_BG1..8 (e6196406 .. e619640d). A picture holds for four seconds,
and the next fades in over one on the upper bitmap while the lower fades
out. The lower then takes the picture and the clock starts again. The
next picture is a random one of the eight that is not the current one,
in up to ten tries (`bRandomI(8, bViewSeed)`). Both bitmaps' alphas are
feAnimAlphaElements, put back when the screen is left.

## The movies

| Screen | Movie | Plane | After |
|---|---|---|---|
| Credits FE Movie | `MOVIES\INTRO\NFSINTRO_EN.AVI` (`_FR` in French) | letterboxed | back |
| Credits Reward movie | `MOVIES\INTRO\REWARD_EN.AVI` (`_FR` in French) | letterboxed | back |
| BBG Creation movie | `MOVIES\INTRO\MAKEOF_EN.AVI` | 4:3 | back |
| BBG Credits movie | `MOVIES\INTRO\BBGLOGO_EN.AVI` | letterboxed | "BBGCredits" |

The planes are the title screen's: MOVIE_PLANE_43 3acf2d73 and
MOVIE_PLANE_LB bfaebf79, one shown and the other hidden. PRESS START
(b070dbc9) and the title's group b73c8d23 are hidden. The jukebox
stops, and the menus' movie with it. A ends the movie; the pad and START
are silent; B goes back as on any screen. When the movie ends, Black
Box's logo goes on to its roll (ChangeToScreen without a push, so B
from the roll comes back to the menu) and the rest move back. Leaving
closes the movie and starts the jukebox again.

A movie that is not on the card is one that has already ended, as the
title's are: the screen goes on at once. The card needs
`MOVIES\INTRO\REWARD_EN.AVI` (31 MB), `REWARD_FR.AVI` and
`MAKEOF_EN.AVI` (349 MB) from the disc for those two rows.

## Tested

`tools/run_azahar_credits.ps1` walks it on Azahar. Electronic Arts' roll
is paused and let go. Black Box Games plays its logo, then its roll.
View Intro Movie is ended with A, and The Making of HP2 is left with B.
View Reward Movie plays when the save has both Ultimates. B goes back to
Options. Back on the menu, the row last picked is still highlighted.
