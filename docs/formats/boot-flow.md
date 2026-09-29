# The boot flow: `main()` to the main menu

Everything here was decompiled out of `PS2 Files/NFSHP2.ELF` with
`tools/mipsdis.py`; each rule cites the address it came from. Nothing in this
document ships as a chunk -- the boot sequence is C++ in the image, the way
`FlailerMenu` was (see [flailer-menu.md](flailer-menu.md)).

Three object files hold all of it:

| object | address | what is in it |
|--------|---------|---------------|
| `Main.obj` | `0x0012da88` | `main`, `MainLoop` |
| `GameFlow.obj` | `0x001636b0` | the top-level state machine and its table |
| `Frontend.obj` | `0x00169e68` | `LaunchFrontendMenus`, `TitleScreen`, `MumboJumboScreen` |

plus `BootAutoLoader` over in `Memcard.obj` (`0x00231370`).

## The short version

```
main()
  InitializeEverything()
  LoadLanguageInfo()
  ChangeGameFlow(GAMEFLOW_STATE_LOADING_FRONTEND, GAMEFLOW_STATE_NONE)
  bDoWithStack(MainLoop, 0x70004000)      <- runs on the scratchpad

MainLoop()  forever:
  ServiceGameFlow()                       <- runs Begin/End/Loop off a table
  ... RaceCoordinator, input, timestep, render ...

GAMEFLOW_STATE_LOADING_FRONTEND
  Begin: load FRONTA.BUN + FRONTB.BUN + the frontend sound regions
  Loop : wait for both, then ChangeGameFlow(GAMEFLOW_STATE_IN_FRONTEND)
  End  : eFixUpTables, InitCarEffects, InitFrontendSounds,
         InitSelectCarScreen, InitMoviePlayer, hide LOADING_TRACK,
         LaunchFrontendMenus()

Retail (SLES_507.31), which the port runs:

InitializeEverything()
  ... LoadGlobalChunks()                  <- English, LOADING_TRACK, one frame
LOADING_FRONTEND
  Begin: BeginScreenFadeTime = RealTime; FRONTA.BUN, FRONTB.LZC
  FRONTB's callback: LoadCurrentSpeech, then the sound regions
  their callback   : ChangeGameFlow(GAMEFLOW_STATE_IN_FRONTEND)
  Loop : the demo slideshow only
  End  : hide LOADING_TRACK and its copyright line, LaunchFrontendMenus()

LaunchFrontendMenus()
  push "Title Screen"            if ShouldSeeTitleSequence()
  push "Legal MumboJumbo"        if ShouldSeeLegalMumboJumbo()
  push "Language Options Pre FE" if ShouldSeeLanguageSelectScreen()
  push "BootAutoload"            if ShouldSeeAutoloadScreen()
  ChangeToScreen(top of stack, popping it)

  each of those screens ends with MoveBackScreen(1), which pops the next
  one off the stack; an empty stack lands on "New Main Menu".
```

So the on-disc boot order is **BootAutoload -> Language Options -> Legal
MumboJumbo -> Title Screen (EA logo, NFS intro, PRESS START) -> New Main
Menu**, with three of those five skipped in the shipped US PS2 build (see
[The predicates](#the-predicates)). On the PAL retail disc the player sees
LOADING first, before `MainLoop` runs, then the language screen, then the
title's movies. See
[Retail's `LOADING_FRONTEND`](#retails-loading_frontend-sles_50731).

## `main` (`0x0012da88`)

```c
int main(int argc, char **argv)
{
    __main();
    InitializeEverything(argc, argv);
    if (SkipFE) {                                   /* 0x00322f04, ships 0 */
        StartSkipFEGame(&Fred);
    } else {
        LoadLanguageInfo();
        ChangeGameFlow(GAMEFLOW_STATE_LOADING_FRONTEND, GAMEFLOW_STATE_NONE);
    }
    bDoWithStack(MainLoop, 0x70004000, 0, 0);       /* scratchpad stack */
    return 0;
}
```

`0x70004000` is the EE scratchpad; `MainLoop` runs with its stack there, which
is why nothing in the flow code may recurse deeply. Irrelevant on the 3DS, but
it explains the shape of the code -- everything is a flat state machine.

## `GameFlowStateInfoTable` (`0x002f2eb0`)

Ten 16-byte `GameFlowStateInfo` records, straight out of the `.mdebug` type
info (type#2158):

```c
struct GameFlowStateInfo {
    const char *Name;           /* +0  */
    void      (*BeginFunction)(void);  /* +4  */
    void      (*EndFunction)(void);    /* +8  */
    void      (*LoopFunction)(void);   /* +12 */
};
```

| # | state | Begin | End | Loop |
|---|-------|-------|-----|------|
| 0 | `GAMEFLOW_STATE_NONE` | `0x00163ac0` (empty) | -- | -- |
| 1 | `GAMEFLOW_STATE_LOADING_FRONTEND` | `0x00163ad8` | `0x00163c58` | `0x00163b78` |
| 2 | `GAMEFLOW_STATE_UNLOADING_FRONTEND` | `0x00163cc8` | -- | -- |
| 3 | `GAMEFLOW_STATE_IN_FRONTEND` | -- | -- | -- |
| 4 | `GAMEFLOW_STATE_LOADING_TRACK_COMMON` | `0x001641b8` | -- | -- |
| 5 | `GAMEFLOW_STATE_LOADING_TRACK_SPECIFIC` | `0x001644e0` | `0x001645e8` | `0x001645a8` |
| 6 | `GAMEFLOW_STATE_RACING` | -- | -- | -- |
| 7 | `GAMEFLOW_STATE_UNLOADING_TRACK_SPECIFIC` | `0x001646e0` | -- | -- |
| 8 | `GAMEFLOW_STATE_UNLOADING_TRACK_COMMON` | `0x001642a0` | -- | -- |
| 9 | `GAMEFLOW_STATE_EXIT_DEMO_DISC` | `0x00164878` | `0x00164910` | `0x00164888` |

The port has the first nine. State 9 is only the demo disc's, and the port
has no demo disc (see [Demo disc](#demo-disc)).

`IN_FRONTEND` and `RACING` are the two resting states and have no functions at
all: once the flow reaches them it stops doing anything and the screen list
(or the race coordinator) takes over.

Three `int`s in `.sdata` drive it:

| symbol | address | meaning |
|--------|---------|---------|
| `CurrentGameFlowState` | `0x0032362c` | where the machine is |
| `DesiredGameFlowState` | `0x00323630` | where `ChangeGameFlow` asked it to go |
| `PendingGameFlowState` | `0x00323634` | written, never read by `ServiceGameFlow`; `BeginGameFlowUnloadingTrackSpecific` reads it ([track-flow.md](track-flow.md)) |

### `ServiceGameFlow` (`0x001636f8`)

```c
void ServiceGameFlow(void)
{
    for (;;) {
        if (CurrentGameFlowState != DesiredGameFlowState) {
            if (Table[CurrentGameFlowState].EndFunction)
                Table[CurrentGameFlowState].EndFunction();
            CurrentGameFlowState = DesiredGameFlowState;
            if (Table[CurrentGameFlowState].BeginFunction)
                Table[CurrentGameFlowState].BeginFunction();
        }
        if (Table[CurrentGameFlowState].LoopFunction)
            Table[CurrentGameFlowState].LoopFunction();
        if (CurrentGameFlowState == DesiredGameFlowState)
            return;
    }
}
```

Two details a reimplementation gets wrong by guessing. The **old** state's
`End` runs before the **new** state's `Begin` -- so `EndGameFlowLoadingFrontEnd`,
which is what actually starts the frontend, runs on the way *out* of
`LOADING_FRONTEND`, not on the way in to `IN_FRONTEND`. And the whole thing is
a loop, not a single pass: a `Loop` function that calls `ChangeGameFlow` gets
serviced in the same call, which is how `LOADING_FRONTEND -> IN_FRONTEND`
completes without a wasted frame. `MainLoop` calls it twice per frame anyway
(`0x0012dc18` and `0x0012dc4c`), once before and once after the race
coordinator's queued messages.

`ChangeGameFlow(desired, pending)` (`0x001636e8`) is two stores and nothing
else -- no validation, no transition table.

`IsGameFlowPaused` (`0x001636c8`) has nothing to do with the game flow: it
returns `pRaceCoordinator && pRaceCoordinator->State == 6`.

## `GAMEFLOW_STATE_LOADING_FRONTEND`

### Begin (`0x00163ad8`)

```c
InitWithDefaults(&TheRaceParameters);              /* 0x00312520 */
FreeMemoryBeforeLoadingFrontEnd = bCountFreeMemory(16);
LoadSoundRegionsFrontEnd();
BeginScreenFadeTime = 0;
LoadResourceFile("FRONTEND\\FRONTA.BUN", 1, 0, NULL, 0);
if (TheLanguageManager.CurrLanguage == -1) NeedToSetLanguage = 1;
LoadLanguage(&TheLanguageManager, <CurrLanguage or 0>, 1);
rf = LoadResourceFile("FRONTEND\\FRONTB.LZC", 1, 9, NULL, 0);
ChangeFilenameForHotChunking(rf, "FRONTEND\\FRONTB.BUN");
```

`FRONTA.BUN` is the *loading* bundle, meant to stay resident while `FRONTB`
streams in. **On this disc it is a zero-byte file** -- so are `GLOBALA.BUN`
and `INGAMEA.BUN`. The split exists in the code and was not used by the time
the disc was cut.

The `.LZC` / `.BUN` pair is the hot-chunking trick: the loader is handed the
compressed name, then told to report the decompressed one, so the resource
system's own bookkeeping sees `FRONTB.BUN`. Both names hash into `ZDIR.BIN`
(see [zdir-archive.md](zdir-archive.md)); only `FRONTB.LZC` is really there.

### Loop (`0x00163b78`)

```c
elapsed = RealTime - BeginScreenFadeTime;          /* RealTime ticks at 60Hz */
if (TheDemoDiscManager.bActive && elapsed < 541) {
    if (elapsed >= 361) {                          /*  6.0s .. 9.0s */
        SetFlailerScreenVisibility(0xa7227ae8, FLAILER_SCREEN_INVISIBLE);
        SetFlailerScreenVisibility(0x8254cc20, FLAILER_SCREEN_VISIBLE);
    } else if (elapsed >= 181) {                   /*  3.0s .. 6.0s */
        SetFlailerScreenVisibility(0x8139ec90, FLAILER_SCREEN_INVISIBLE);
        SetFlailerScreenVisibility(0xa7227ae8, FLAILER_SCREEN_VISIBLE);
    }
    return;                                        /* 0s .. 3.0s: as loaded */
}
if (!IsResourceLoadingComplete())   return;
if (!IsSoundRegionLoadingComplete()) return;
if (NeedToSetLanguage) { SetCurrLanguage(&TheLanguageManager, -1);
                         NeedToSetLanguage = 0; }
ChangeGameFlow(GAMEFLOW_STATE_IN_FRONTEND, GAMEFLOW_STATE_NONE);
```

**`FLAILER_SCREEN_VISIBLE` is 0 and `FLAILER_SCREEN_INVISIBLE` is 1** (from the
`.mdebug` enum `FlailerScreenVisibility`), so the literal `1`s above are
*hides*. Read the other way round the sequence makes no sense; read this way
it is a plain three-panel slideshow, three seconds each, over a loading
screen. The three screens are in `GLOBALB.BUN` and their names did not survive
as literals, but their single bitmaps did:

| screen hash | texture | shown |
|-------------|---------|-------|
| `0x8139ec90` | `FIRSTLEGAL` | 0.0s -- 3.0s |
| `0xa7227ae8` | (unnamed, `0x03312a84`) | 3.0s -- 6.0s |
| `0x8254cc20` | `DISCLAIMER` | 6.0s -- 9.0s |

This is demo-disc-only and never runs on the retail disc, because
`TheDemoDiscManager.bActive` is 0 -- see [Demo disc](#demo-disc).

`BeginScreenFadeTime` is set by `BeginGameFlowLoadingFrontEndTextureCallback`
(`0x00163ac8`, `BeginScreenFadeTime = RealTime`), which is a
`LoadResourceFile` completion callback -- and which nothing on this build
passes, so `BeginScreenFadeTime` stays 0 and `elapsed` is just `RealTime`. One
more piece of the same unfinished loading-screen path.

### End (`0x00163c58`)

```c
eDisableFixUpTables = 0;
eFixUpTables();
InitCarEffects();
InitFrontendSounds();
InitSelectCarScreen();
InitMoviePlayer();
if (TheDemoDiscManager.bActive)
    SetFlailerScreenVisibility(0x8254cc20 /*DISCLAIMER*/, INVISIBLE);
else
    SetFlailerScreenVisibility(0xd0131dd1 /*LOADING_TRACK*/, INVISIBLE);
LaunchFrontendMenus();
```

`LOADING_TRACK` is in `GLOBALB.BUN` and is the screen with `GLOBAL_LOADING_STRING`
("LOADING...") on it. It is *hidden* here, which means something made it
visible earlier -- `BeginGameFlowLoadingTrackCommon` and friends do.

### Retail's `LOADING_FRONTEND` (SLES_507.31)

Everything above is the demo's. The PAL retail disc moved the language out
of this state and drives it with load callbacks instead of a polling
`Loop`. The port runs retail's.

| function | address |
|----------|---------|
| `main` | `0x0012f000` |
| `InitializeEverything` | `0x0012ee98` |
| `LoadGlobalChunks` | `0x001682d0` |
| Begin | `0x00168698` |
| Loop | `0x00168718` |
| End | `0x001687a8` |
| FRONTB's load callback | `0x00168668` |
| the sound regions' callback | `0x00168658` |
| `ChangeGameFlow` | `0x001680d8` |

Retail's `main` has no `LoadLanguageInfo`. It is `InitializeEverything`,
then `ChangeGameFlow(LOADING_FRONTEND, NONE)` unless `SkipFE` is set, then
`MainLoop` on the scratchpad. `InitializeEverything` calls
`LoadGlobalChunks` near its end (`0x0012efa4`):

```c
LoadResourceFile("GLOBAL\\GLOBALA.BUN", 0, 6, NULL, 0);        /* 0x00199640 */
rf = LoadResourceFile("GLOBAL\\GLOBALB.LZC", 0, 9, NULL, 0);
ChangeFilenameForHotChunking(rf, "GLOBAL\\GLOBALB.BUN");        /* 0x00199720 */
while (!IsResourceLoadingComplete())                            /* 0x00199818 */
    ServiceResourceLoading();                                   /* 0x00199788 */
... size the language buffer (0x0021dfe8), build pDynamicTexturePack ...
SetCurrLanguage(&TheLanguageManager, l_ENGLISH);   /* 0x00100808 -> 0x00100818 */
... load LOADING (0xab0e817d), or the demo's FIRSTLEGAL, and wait ...
if (TheDemoDiscManager.bActive)
    SetFlailerScreenVisibility(FIRSTLEGAL, VISIBLE);              /* 0x0014cbf8 */
else {
    SetFlailerScreenVisibility(LOADING_TRACK, VISIBLE);           /* 0xd0131dd1 */
    FlailerSetVisibility(LOADING_TRACK, COPYRIGHT_TEXT, VISIBLE); /* 0x00144968, 0x807d4c5c */
}
eDisplayFrame();                                   /* 0x00112858 */
```

**This is the first thing retail shows.** `LOADING_TRACK` is the logo over
the bar reading `LOADING...`. `eDisplayFrame` draws it once, outside
`MainLoop`, and nothing draws again until `MainLoop` runs. So that frame
stays up while the frontend loads. The copyright line is FRONTB's, on
`TITLE_IMAGE`, and FRONTB is not in yet: the second call finds nothing, and
retail makes it anyway.

Begin (`0x00168698`):

```c
BeginScreenFadeTime = RealTime;                    /* gp-21400 = gp-19604 */
LoadResourceFile("FRONTEND\\FRONTA.BUN", ..., NULL);             /* 0x00199640 */
rf = LoadResourceFile("FRONTEND\\FRONTB.LZC", ..., 0x00168668);
ChangeFilenameForHotChunking(rf, "FRONTEND\\FRONTB.BUN");        /* 0x00199720 */
```

The demo's `NeedToSetLanguage` and `LoadLanguage` are gone, because
`LoadGlobalChunks` has already set a language. `BeginScreenFadeTime` is now
set here, so the demo slideshow's clock starts at Begin.

The two callbacks move the flow on, one after the other:

```c
void FrontBLoaded(void)          /* 0x00168668 */
{
    LoadCurrentSpeech(&TheLanguageManager);        /* 0x0021e250 */
    LoadSoundRegionsFrontEnd(0x00168658, 0);       /* 0x001ae9a0 */
}
void FrontEndSoundsLoaded(void)  /* 0x00168658 */
{
    ChangeGameFlow(GAMEFLOW_STATE_IN_FRONTEND, GAMEFLOW_STATE_NONE);
}
```

Loop (`0x00168718`) is only the demo's slideshow now, on signed compares
(`slti`) against 541, 361 and 181. It returns at once when
`TheDemoDiscManager.bActive` is 0, which it always is on retail. The port
has no Loop for this state. `bootflow_check` still runs retail's, with
`bActive` 0, and it does nothing.

End (`0x001687a8`) hides `DISCLAIMER` on the demo disc. Off it, it hides
`LOADING_TRACK` and object 0, `COPYRIGHT_TEXT`, then jumps
(`j`, not `jal`) to `LaunchFrontendMenus` (`0x0016f950`).

#### `LanguageManager` (`0x0031c1c8`)

`CurrLanguage` is at `+0`, and `+20` says the speech is loaded.
`SetLanguage` (`0x0021e0d0`) returns early when the language does not
change. Otherwise:

1. It unloads the outgoing `FE_<language>.BIN` chunks (`UnloadChunks`,
   `0x001992a8`).
2. It loads the new ones into the buffer `LoadGlobalChunks` sized for the
   longest table.
3. The tail (`0x0021e1e0`) swaps the speech if `+20` is set: unload, then
   `LoadCurrentSpeech`. Speech that was not loaded stays unloaded. FRONTB's
   callback is what first loads it.
4. `0x001681b0` swaps the logo art. `LOADING` and `NFS_LOGO_ALPHA` have
   French versions, `LOADING_FR` and `NFS_LOGO_ALPHA_FR`, remapped through
   `0x001ac548`. `gp-21404` says which set is loaded, and it flips only when
   French is entered or left.
5. `FlailerUpdateLanguageText` (`0x00141648`) re-reads every text object's
   string.

#### The language screen

`Language Options Pre FE` (the boot's) and `Language Options` (from the
Options menu) share one `Callback`, `0x001f1dd8`, called with `(msg, data)`.
It tells them apart by `strcmp` (`0x002535f8`) on the name the screen was
entered under: `0x002b9eb8` and `0x002b9b98`. On `SCREEN_ACTIVATE` it
`bMalloc`s (`0x00257690`) the class and runs the constructor (`0x001f1a78`).
The instance is kept at `gp-16972`. On `SCREEN_UNACTIVATE` it frees the
instance. Every other message goes to `HandleScreenCallback` (`0x001f1b08`),
a 19-entry jump table on `msg - 1` at `0x002b9e30`. Only `MENUITEM_SELECT`,
`SCREEN_BACK_BUTTON` and `TICK` have cases, and `TICK` is a virtual that
does nothing in this class.

`ScreenCallbackData` is `ItemHash` at `+0`, `Port` at `+4`, `Param` at
`+8` and `Noise` at `+12`.

The constructor keeps the flailer and whether it came from the Options
menu. It sets `selected` to `CurrLanguage`, or 0 when that is -1. It grays
`MENUITEM_7`, "Load All Languages", in mode 2 (`GrayMenuItem`,
`0x0016d2a8`), because `0x0016fdb0` is `return 0`. `MENUITEM_1` to
`MENUITEM_6` are English, French, German, Italian, Spanish and Swedish in
order. The code adds `-MENUITEM_1` and takes anything under 6, unsigned.

```c
case MENUITEM_SELECT:
    LanguageOfItem(data->ItemHash, &selected);
    if (item < MENUITEM_1) return;
    if (item > MENUITEM_6) {
        if (item != MENUITEM_7) return;
        LoadAllLanguages = 1;                      /* gp-16016 */
        MoveBackScreen(1);
        return;
    }
    Chosen(0);
    break;
case SCREEN_BACK_BUTTON:
    data->Param = 0;                               /* the list's pop, vetoed */
    if (CurrLanguage == -1) return;
    item = GetActiveMenuItem();                    /* 0x0016d3f0 */
    LanguageOfItem(item, &selected);
    if ((int)item > (int)MENUITEM_6 || (int)item < (int)MENUITEM_1) {
        MoveBackScreen(1);
        return;
    }
    Chosen(1);
    break;

void Chosen(int backOnUnset)
{
    SetCurrLanguage(&TheLanguageManager, selected);
    if (CurrLanguage == -1) { if (backOnUnset) MoveBackScreen(1); return; }
    if (!fromOptions) FrontendDatabase::InitWithDefaults(0x002fc050); /* 0x00183830 */
    MoveBackScreen(1);
}
```

**BACK takes the highlighted language.** A BACK on Italian's highlight
leaves in Italian, as a SELECT would. Only an unset language vetoes it.
The signed compares mean that with no menu (item 0), BACK moves back as it
is.

`MoveBackScreen` (`0x00170320`) is `lw a0,-21324(gp); j 0x0016c670`, which
is `MoveToPreviousScreen(n, 0, -1)`: no button event, no port. The pad's
BACK is `MoveToPreviousScreen(1, 1, port)`. `MoveToPreviousScreen` memsets
the event data before it sends anything, so its `ItemHash` is 0: BACK
names no item.

`FlailerScreen::Activate` builds the menu, then sends `SCREEN_ACTIVATE`,
then activates the menu. The constructor's `GrayMenuItem` therefore lands on
a menu that exists but is not yet live.

## The screen stack

`FlailerScreenList` derives from `ScreenStack`, whose layout the `.mdebug`
gives exactly (type#724, 388 bytes):

```c
struct ScreenStack {
    char ScreenNames[12][32];   /* +0   */
    int  Index;                 /* +384 */
};
```

| | address | |
|---|---|---|
| `ScreenStack::Push(name)` | `0x00166780` | `bStrCpy(Names[Index++], name)` -- no bound check |
| `ScreenStack::Pop()` | `0x001667a0` | returns `Names[--Index]`, or NULL when empty |
| `ScreenStack::Reset()` | `0x001667c8` | `bMemSet(this, 0, 388)` |
| `ScreenStack::Print()` | `0x001667d8` | `jr ra` -- compiled out of the release build |

`FlailerScreenList::GetCurrentScreenNameFromStack` (`0x00167bf0`) returns
`&Names[Index - 1]`, or the empty string at `0x00323670` when `Index == 0`.

That empty string is a sentinel the *callers* test, not something
`ChangeToScreen` handles. `ChangeToScreen` unactivates the outgoing screen and
clears `pCurrent` **before** it looks the new name up (`0x001678a4`), so a name
that does not resolve -- `NULL`, `""`, or a name in no config -- leaves the
list with no current screen at all, not with the old one still up. That is why
`MoveToPreviousScreen` runs `bStrLen(name)` first (`0x00167aac`) and simply
does not call `ChangeToScreen` when the stack has been popped to nothing.

### `ChangeToScreen` (`0x00167850`)

```c
void ChangeToScreen(FlailerScreenList *this, const char *name, int bPushCurrent)
{
    FlailerScreenNode *old = this->pCurrent;              /* +412 */
    if (old) {
        old->SetVisibility(FLAILER_SCREEN_INVISIBLE);
        if (bPushCurrent) Push(this, old->Config->ScreenName);
        old->UnActivate();
        this->pCurrent = NULL;
    }
    if (name) {
        FlailerScreenNode *n = FindScreen(this, name);
        if (n) {
            this->pCurrent = n;
            n->SetVisibility(FLAILER_SCREEN_VISIBLE);
            n->Activate();
            tGlobalBackgroundAnimation::ChangeScreenHash(
                this->pBackground, n->Config->FlailerHashes[0]);
        }
    } else {
        tGlobalBackgroundAnimation::ChangeScreenHash(this->pBackground, 0);
    }
    /* a screen appearing from nothing adds the 16 MenuJoyEvents on both
       ports; one disappearing to nothing removes them (0x00167928 /
       0x00167978) */
    if (name && this->pMainScreenName && !bStrCmp(name, this->pMainScreenName))
        ScreenStack::Reset(this);
}
```

`bPushCurrent` pushes the name of the screen being *left*, which is what makes
BACK come back to it.

That last `Reset` is dead. `pMainScreenName` is `FlailerScreenList + 388`, the
first field after the inherited `ScreenStack`; the constructor sets it to NULL
(`0x00167678`), `SetMainScreen` (`0x00167738`) is its only setter and has
exactly one caller -- `UnlaunchFrontendMenus+0xcc`, which also passes NULL. So
nothing in the image ever makes it non-NULL, and "changing to the main screen
empties the back stack" never happens.

`PopUntil` (`0x00167b48`) is the piece that does the same job in practice: it
pops while the top is neither the empty string nor `name`, and leaves `name`
itself on the stack.

`MoveToPreviousScreen(n, bSendBackButton, port)` (`0x00167a00`) builds a
16-byte `ScreenCallbackData` with `Param = 1` and `Noise = FE_SOUND_MENU_CANCEL`
(6). Only when `bSendBackButton` is set does it call the current screen's
callback with `SCREEN_BACK_BUTTON` and then `MakeFrontendSound(data.Noise)` --
reading `Noise` back *after* the callback, which is how the title screen
silences the click by writing 0 into it. A callback that clears `Param` vetoes
the move entirely.

`FlailerScreenList::PopScreens(n)` (`0x00167af8`) pops `n` and discards them.
`MoveToPreviousScreen(n, sound, port)` (`0x00167a00`) is the one screens
actually call, through `MoveBackScreen(n)` (`0x0016b220`): it gives the current
screen a `SCREEN_BACK_BUTTON` first (so it can veto), plays
`FE_SOUND_MENU_CANCEL`, pops `n`, and changes to whatever it popped -- unless
that name is empty, in which case it changes to nothing and returns 0.

## `LaunchFrontendMenus` (`0x0016aa40`)

```c
void LaunchFrontendMenus(void)
{
    if (FrontendLaunchType == 2 && Fred.DemoModeStatus == 2) {
        FlailerScreenList::ResetStack(CurrentMenuSystem);
        ChangeToScreen("New Main Menu", 1);
        return;
    }
    if (ShouldSeeTitleSequence())        Push("Title Screen");
    if (ShouldSeeLegalMumboJumbo())      Push("Legal MumboJumbo");
    if (ShouldSeeLanguageSelectScreen()) Push("Language Options Pre FE");
    if (ShouldSeeAutoloadScreen())       Push("BootAutoload");

    name = GetCurrentScreenNameFromStack();   /* the top, i.e. the LAST push */
    PopScreens(1);
    if (!bStrCmp(name, "View Event Tree")) Fred.SelectedEventData.<+12> = 0;
    ChangeToScreen(name, 0);
}
```

The push order is the reverse of the display order, which is the one thing
here that reads backwards on a first pass: the stack is LIFO and the function
immediately pops its own top. So the last predicate that fires is the first
screen the player sees.

`"Legal MumboJumbo"` and `"View Event Tree"` are **not registered screens** --
neither name appears in the 49-entry screen registry below. The first is
guarded by a predicate that returns 0, and the second is only ever compared
against, never entered. Dead references both.

`UnlaunchFrontendMenus` (`0x0016ab70`) is the mirror, run when a race starts.
It switches on `FrontendLaunchType - 2` through a jump table at `0x002966e0`
and then sets `FrontendLaunchType = (TheRaceParameters.<+24> ||
TheRaceParameters.<+28>) ? 2 : 3`, which is how a second visit to the frontend
skips the boot sequence.

### The predicates

All four live in `Frontend.obj` and all four read `FrontendLaunchType`
(`0x00323724`, **ships as 1** and is written only by `UnlaunchFrontendMenus`).

```c
int ShouldSeeTitleSequence(void)            /* 0x0016aa30 */
{   return (unsigned)(FrontendLaunchType - 1) < 2; }

int ShouldSeeLegalMumboJumbo(void)          /* 0x0016aa28 */
{   return 0; }

int ShouldSeeLanguageSelectScreen(void)     /* 0x0016a9b8 */
{
    if (FrontendLaunchType == 1 && TheLanguageManager.CurrLanguage == -1)
        return 1;
    if (TheDemoDiscManager.bActive) return 0;
    if (GetVideoMode() != 0)        return 0;
    return FrontendLaunchType == 1;
}

int ShouldSeeAutoloadScreen(void)           /* 0x0016a990 */
{
    if (TheDemoDiscManager.bActive) return 0;
    return FrontendLaunchType == 1;
}
```

### `GetVideoMode`, and the one thing here the ELF cannot settle

`GetVideoMode` (`0x001992a0`) returns the `int` at `0x00323ccc`. The enum is
`VIDEO_MODE { MODE_PAL = 0, MODE_NTSC = 1 }` -- from the `.mdebug` type info,
and note which way round that is: `ShouldSeeLanguageSelectScreen` bails on
**non-zero**, so it is NTSC that skips the language screen and PAL that shows
it. The `.data` value is 1, but that means nothing, because
`InitDisplaySystem` (`0x00100750`) overwrites it on the way up:

```c
if (bFileExists("PAL.TAG")) SetVideoMode(MODE_PAL);   /* 0x0010076c */
else                        SetVideoMode(MODE_NTSC);  /* 0x0010077c */
```

`PAL.TAG` (`0x00322390`) **is** in `ZDIR.BIN` -- entry 132, hash `0xbf0a6606`.
But its `Size` is 0 and it shares its `Fad` with entry 133, which is exactly
the signature of `FRONTEND\FRONTA.BUN`, `GLOBAL\GLOBALA.BUN` and
`GLOBAL\INGAMEA.BUN`: entries that are there and hold nothing. A tag file is
*supposed* to be zero bytes, so the bytes are equally consistent with "this is
a PAL disc" and with "this entry is a leftover".

`bFileExists` (`0x0023c3a0`) is `bOpen(path, 0) != NULL`, and `bOpen` goes
through `OpenCodeineFile` (`0x0023bee0`) into the IOP module by `bFunkCallSync`
-- so whether a zero-size entry opens is decided inside `IRX243`, not in this
ELF, and this cannot be settled by reading the ELF further. Evidence pulls both
ways: the disc carries all eight `FE_*.BIN` language tables (European), but of
the six per-language EA logos named in `TitleMoviesToPlay` only `EALOGO_EN.AVI`
is on it (English-only).

So the retail boot is one of two orders, differing by one screen:

| predicate | value | screen |
|-----------|-------|--------|
| `ShouldSeeTitleSequence` | 1 | `Title Screen` pushed |
| `ShouldSeeLegalMumboJumbo` | 0 | -- |
| `ShouldSeeLanguageSelectScreen` | PAL only | `Language Options Pre FE` |
| `ShouldSeeAutoloadScreen` | 1 | `BootAutoload` pushed |

**BootAutoload -> Title Screen -> New Main Menu** on NTSC, and
**BootAutoload -> Language Options Pre FE -> Title Screen -> New Main Menu**
on PAL. `3DS Files/source/gameflow.c` defaults to NTSC and reaches the other
by setting one field, and `tools/bootflow_check.py` runs both.

There is one case where the language screen appears whichever way that goes:
`CurrLanguage == -1`, no language chosen yet, which is the
first-boot-before-a-memory-card case. That test is first in the predicate and
does not consult the video mode at all.

## `TitleScreen` (`0x0016a1d0`)

The EA logo and the NFS intro, then "PRESS START". A 20-byte object built on
`SCREEN_ACTIVATE` and destroyed on `SCREEN_UNACTIVATE`:

```c
struct TitleScreen {
    FlailerBitmapChunk *pMoviePlane;  /* +0  the plane being blitted into  */
    int                 Port;         /* +4                                */
    int                 MovieIndex;   /* +8                                */
    int                 Mode;         /* +12 1 = idle, 2 = playing         */
    int                 Timer;        /* +16 RealTimer at the last change  */
};
```

Its three objects on screen `0xb5761d00` (`FRONTB.BUN`, 7 objects):

| hash | what |
|------|------|
| `0x3acf2d73` | bitmap at (-10, 0) scaled 1.25 x 1.875 -- the 4:3 movie plane |
| `0xbfaebf79` | bitmap at (-1, 65) scaled 1.25 x 1.188 -- the letterboxed plane |
| `0xb070dbc9` | text "PRESS START" |

`Callback` (`0x0016a590`) is the standard shape every screen class here uses:

```c
case SCREEN_ACTIVATE:   pInstance = new TitleScreen(data->ItemHash); break;
case SCREEN_UNACTIVATE: delete pInstance; pInstance = NULL;          break;
case SCREEN_TICK:       HandleTick(pInstance, SCREEN_TICK, data);    break;
default:                HandleEvent(pInstance, msg, data);           break;
```

### Which movies play

```c
int GetNumTitleMovies(void)                 /* 0x0016a130 */
{   return TheDemoDiscManager.bActive ? 1 : 2; }

TitleMovie *GetTitleMovieDescription(int i) /* 0x0016a0e0 */
{
    int lang = TheLanguageManager.CurrLanguage;
    return TheDemoDiscManager.bActive
         ? &DemoDiscTitleMoviesToPlay[lang + i]        /* 1 per language  */
         : &TitleMoviesToPlay[lang * 2 + i];           /* 2 per language  */
}
```

`TitleMoviesToPlay` (`0x002f3770`) is eight rows of two `{ const char *Name;
int Letterboxed; }`:

| language | movie 0 | movie 1 |
|----------|---------|---------|
| `l_EN` | `MOVIES\INTRO\EALOGO_EN.AVI` (0) | `MOVIES\INTRO\NFSINTRO_EN.AVI` (1) |
| `l_FR` | `...EALOGO_FR.AVI` (0) | `...NFSINTRO_EN.AVI` (1) |
| `l_DE` | `...EALOGO_GE.AVI` (0) | `...NFSINTRO_EN.AVI` (1) |
| `l_IT` | `...EALOGO_IT.AVI` (0) | `...NFSINTRO_EN.AVI` (1) |
| `l_ES` | `...EALOGO_SP.AVI` (0) | `...NFSINTRO_EN.AVI` (1) |
| `l_SE` | `...EALOGO_SW.AVI` (0) | `...NFSINTRO_EN.AVI` (1) |
| `l_LONGEST_STRING`, `l_ID_NUM` | all zero | all zero |

The second field picks the plane: 0 uses `0x3acf2d73`, non-zero uses
`0xbfaebf79`. `DemoDiscTitleMoviesToPlay` (`0x002f37f0`) is the same table with
the EA logo only.

**Only `MOVIES\INTRO\EALOGO_EN.AVI` is actually on this disc.** Hashing the
other twelve paths against `ZDIR.BIN` finds nothing, including
`NFSINTRO_EN.AVI` -- all 223 entries are in `docs/zdir_names.txt` and only
the one EA logo is there -- so the second title movie fails to open and it is
in practice one movie long. (The one that is there is MV3-in-AVI, 512x256,
90 frames -- see [mv3-video.md](mv3-video.md).)

### `HandleTick` (`0x0016a360`)

```c
if (Mode == 2) {                                    /* playing */
    if (DriveMovie(pMoviePlane) != 1) return;       /* still running */
    MovieIndex++;
    if (TheDemoDiscManager.bActive)
        SetFlailerScreenVisibility(0xb5761d00, FLAILER_SCREEN_INVISIBLE);
    else
        FlailerSetVisibility(0xb5761d00, 0xb070dbc9, FLAILER_OBJECT_VISIBLE);
    MoviePlayer::Close(&TheMoviePlayer);
    FlailerSetVisibility(0xb5761d00, 0x3acf2d73, FLAILER_OBJECT_INVISIBLE);
    FlailerSetVisibility(0xb5761d00, 0xbfaebf79, FLAILER_OBJECT_INVISIBLE);
    if (MovieIndex == GetNumTitleMovies()) {
        Timer = RealTimer;
        Mode  = 1;                                  /* idle: PRESS START */
        if (!TheDemoDiscManager.bActive) sound::jukebox::Start(true);
        return;
    }
    d = GetTitleMovieDescription(MovieIndex);
    MoviePlayer::InitFile(&TheMoviePlayer, d->Name);
    FlailerSetVisibility(0xb5761d00,
                         d->Letterboxed ? 0xbfaebf79 : 0x3acf2d73,
                         FLAILER_OBJECT_VISIBLE);
    return;
}
if (Mode == 1) ConsiderStartDemoMode(Timer);        /* attract countdown */
```

Note `FLAILER_OBJECT_VISIBLE` is **1** and `FLAILER_OBJECT_INVISIBLE` is **0** --
the opposite polarity to `FlailerScreenVisibility` above. Two enums, two
conventions, one line apart in `HandleTick`. `FlailerObjectVisibility` also has
`FLAILER_OBJECT_PSX2_ONLY = 2` and `FLAILER_OBJECT_XBOX_ONLY = 3`, which is how
one authored bundle served both ports.

The constructor (`0x0016a1d0`) is the same thing at index 0, with one extra
branch at the top:

```c
if (SkipMovies) {                                   /* 0x00322fbc, ships 0 */
    Mode = 1; sound::jukebox::Start(true); Timer = RealTimer;
} else {
    Mode = 2;
    pMoviePlane = FindFlailerObject(0xb5761d00, 0x3acf2d73,
                                    FLAILER_OBJECT_TYPE_BITMAP /* 2 */);
    ...open movie 0, show its plane, hide "PRESS START"...
}
```

`pMoviePlane` is fixed to the 4:3 plane at construction and never re-fetched,
even when a letterboxed movie makes the *other* plane visible. `DriveMovie`
(`0x0016a060`) decodes into `pMoviePlane->TextureInfo` (`+60`, then `+144`) and
returns `!MoviePlayer::Update(...)`, i.e. 1 when the movie is finished.

### `HandleEvent` (`0x0016a148`)

A 17-entry jump table at `0x00296610` indexed by `message - 1`:

| message | handler |
|---------|---------|
| `MENUITEM_SELECT` (1) | the advance below |
| `MENUITEM_PAD_*`, `MENUITEM_SQUARE`, `SCREEN_START_BUTTON` | `data->Noise = 0` (swallow the UI click) |
| `SCREEN_BACK_BUTTON` (17) | `data->Param = 0; data->Noise = 0` |
| everything else | ignored |

and the advance:

```c
if (Mode == 1 || (Mode == 2 && MovieIndex != 0)) {
    if (TheDemoDiscManager.bActive) { data->Noise = 0; return; }
    ChangeToScreen("New Main Menu", 1);
}
data->Noise = 0;
```

So **the EA logo cannot be skipped and the NFS intro can**: during movie 0
`MovieIndex` is still 0 and the test fails. Once `MovieIndex` has advanced past
the first movie, or the screen is idle on "PRESS START", any select jumps
straight to the main menu.

The screen has a `MENUITEM_1` text object on it, which is how START gets there
at all: `FlailerScreen`'s handler passes START to the screen as
`SCREEN_START_BUTTON` first, and the title screen does not consume it (it
writes `Noise`, not `Param`), so it reaches the item and comes back as
`MENUITEM_SELECT`. See [flailer-menu.md](flailer-menu.md).

### Retail's `TitleScreen` (SLES_507.31)

Everything above is the demo's. The PAL retail disc rewrote the screen, and
the rewrite is what the port runs. The retail functions are:

| function | address |
|----------|---------|
| `Callback` | `0x0016f440` |
| constructor | `0x0016f000` |
| destructor | `0x0016f190` |
| `HandleTick` | `0x0016f1f0` |
| `HandleEvent` | `0x0016eef8` (jump table at `0x002b2f10`) |
| the one new helper | `0x0016f4f8` |

The object is 56 bytes: the demo's 20, then a second `Timer` at `+20`, then
a `tHighlightAnimation` at `+24`.

**Retail's object chunks carry their names**, a `char[24]` the demo's lack.
So the screen's objects can be read by name, and there are more of them:

| object | layer | what |
|--------|-------|------|
| `TITLE_FULLSCREEN` `3acf2d73`, `TITLE_LETTERBOX` `bfaebf79` | 0 | the two movie planes, `SPLASH_SCREEN` |
| `LOADING`, `TOP_BORDER` | 24 | the logo at (0, 81) and the bar at (0, 280) |
| `COPYRIGHT_TEXT` `807d4c5c` | 0 | authored invisible |
| `PRESS_START_1` `b070dbc9`, `ANIMATING_MENUITEM` `ab671c9a` | 13 | the words, and the object the bloom draws |
| `MENUITEM_1` | | off-screen, there for the menu |

`LOADING`, `TOP_BORDER` and `COPYRIGHT_TEXT` form the group `TITLE_IMAGE`
(`bStringHash`, `0xb73c8d23`, hashed at run time from `0x002b2f58`).

The constructor:

1. Builds the bloom, `tHighlightAnimation(TITLE, ANIMATING_MENUITEM,
   gp-16136)`. That colour is `0x00000080`, the one every frontend screen
   blooms in.
2. Hides the 4:3 plane, `COPYRIGHT_TEXT` and the letterboxed plane.
3. With `SkipMovies` set: `Mode = 1` and the jukebox starts. Otherwise
   `Mode = 2`, movie 0 opens and its plane shows.
4. Sets `Timer = RealTimer` and points the bloom at `PRESS_START_1`.

`HandleTick` still steps the movies as the demo's did, with one change. When
the last movie ends it no longer shows `PRESS START`: it only sets
`Mode = 1` and `Timer` and starts the jukebox. Then, on **every tick,
whatever the mode**:

```c
FlailerSetGroupVisibility(TITLE, TITLE_IMAGE, Mode != 2);     /* 0x001454e8 */
if (Mode != 2 && !TimerSet(+20)) +20 = RealTimer;             /* first tick at rest */
FlailerSetVisibility(TITLE, PRESS_START_1, PressStartReady()); /* 0x0016f4f8 */
if (Mode == 1) { ConsiderStartDemoMode(Timer); bloom.Animate(); }
```

`PressStartReady` (`0x0016f4f8`) is `(float)(int)(RealTimer - +20) *
0.00025f > 4.0f`, with the factor at `gp-30496`. So `PRESS START` appears
four seconds after the title first comes to rest, and the logo sits alone
until then. A `Timer` counts as unset at 0 and at `0x7fffffff`.
`FlailerSetGroupVisibility` does a `FindFlailerObjectByGroup` (`0x00143dd8`)
whose result it throws away, then stores byte `+41` (`Visibility`) on each
object in the group.

`HandleEvent` keeps the demo's swallowing of `PAD_*`, `SQUARE` and
`SCREEN_START_BUTTON`, and its veto of `SCREEN_BACK_BUTTON`. The select is
new:

```c
if (Mode == 1) {
    if (!PressStartReady() || TheDemoDiscManager.bActive) { data->Noise = 0; return; }
    Timer = RealTimer;
    ChangeToScreen("New Main Menu", 1);              /* Noise left: the click plays */
} else if (Mode == 2) {
    if (MovieIndex == 0) { data->Noise = 0; return; } /* the EA logo */
    MoviePlayer::Close(&TheMoviePlayer);
    Mode = 1; Timer = RealTimer;
    bloom.ForceStart();
}
```

**A select during the intro stops the movie. It does not leave the title.**
The screen comes to rest where it is, and `PRESS START` follows four
seconds later, as if the movie had ended. Nothing hides the movie plane. It
stays visible until the screen is built again, and the title still shows,
because of the renderer rule described next. The demo went straight to
`New Main Menu`, and the port did too until this was read.

### Movie planes draw nothing without a movie

`RenderFlailerBitmap` (`0x00143078`) never draws `SPLASH_SCREEN`
(`0xf9117c29`) or `PANELMOVIE` (`0xc3f0caef`) as a picture. A bitmap
carrying either is drawn as the movie. That is five passes over the
player's `MOVIE_<w>_<h>_Y`, `_UA`, `_VA`, `_US` and `_VS` textures.
`MoviePlayer::InitFile` (`0x00237ad8`) looks those up with `GetTextureInfo`
(`0x001abf48`) and calls `BuildYUV2ABGRPalettes` (`0x00238520`).
`Update` (`0x002380a8`) points their `+144` `ImageData` at each decoded
frame. The five passes run only if `TheMoviePlayer` (`0x00300000-19704`)
has all five slots (`+1056` to `+1072`) and its frame-ready flag (`+1088`)
non-zero. Otherwise the bitmap is **not drawn at all**.

`MoviePlayer::Close` (`0x00237fc8`) zeroes those slots. So a movie plane
left visible after its movie stops shows whatever is behind it. That is how
a skipped intro uncovers the title.

`gp-22348` would send the two textures down the ordinary path instead.
`Update` copies `gp-22348 == 0` into `+1048`. On the disc it is 1, and
nothing writes it.

### The menus' movie

Behind the menus, in `PANELMOVIE`, a movie loops: the screen list's, on the
same `TheMoviePlayer` as the title's. Three functions of
`FlailerScreenList` drive it, and `+460` of the list is their gate.

`StartMovie(name)` (`0x0016ce30`):

1. Nothing while `SkipMovies` (`gp-23036`) is set.
2. With a movie started, nothing if `name` is the same one (`bStrCmp`,
   `0x002535f8`, a `strcmp`). Otherwise `StopMovie` first.
3. Six textures by `bStringHash` and `GetTextureInfo`: `PANELMOVIE`, then
   `MOVIE_256_384_Y`, `_UA`, `_VA`, `_US` and `_VS`. Each one's `+144` goes
   into `+460..+480`. `PANELMOVIE`'s is read without a null test, so it is
   always there, and `+460` is never 0 after this.
4. `Close` on the player, whatever it held, then `+484 = name` (kept, not
   copied; every caller passes a literal) and a tail-jump to `InitFile`,
   whose answer nobody reads.

`UpdateMovie` (`0x0016d028`) runs from `FlailerScreenList::Tick`
(`0x0016cca8`) after the two popups:

1. Nothing while `+460` is 0.
2. With `InGameFlag` (`gp-21424`) set, `StopMovie`.
3. Otherwise `Update` on the player, with `RealTimeElapsed` in `$f12`,
   which `Update` does not read. Any answer but 1 runs `InitFile(+484)`
   again. That is the loop, and for a file that is not there, a try every
   frame.

`StopMovie` (`0x0016d0a0`) closes the player and zeroes `+460..+480` when
`+460` is set. `+484` is kept.

The callers:

| name | string | called from |
|------|--------|-------------|
| `MOVIES\mainmenu_movie.AVI` | `0x002bc430` | `NewMainMenu`'s `SCREEN_ACTIVATE` (`0x00216544`) |
| `MOVIES\options_movie_new.AVI` | `0x002ba010` | `OptionsScreenBase`'s ctor (`0x001f4da4`), `CreditsScreen` |
| the mode-select movies | | `CopsOnModeSelect`, `CopsOffModeSelect`, `StartTheRightMovie` |

`StopMovie` is called by `StartDemoMode` first of all, and by
`UnlaunchFrontendMenus` (`0x0016fb74`) after the launch type.
`GetDefaultMovieFilename` (`0x0016d0f0`) returns `MOVIES\options_movie.AVI`
for `StartDefaultMovie` (`0x0016d100`), which nothing calls.

The title's movie and the menus' share the player, and nothing keeps them
apart. In the demo, BACK from the main menu left the gate up on the title
screen, so `UpdateMovie` drove the title's movie too, as the title's
`DriveMovie` does. When it ended, `Update` answered 0 and `UpdateMovie`
reopened `mainmenu_movie` under the title. Retail's main menu vetoes BACK
(below), so on the disc that cannot happen.

The movies are 256x384 and anamorphic. `NEW_MAIN_MENU`'s `PANELMOVIE`
plane sits at (141, 73) with a scale of 1.95 x 0.698 and its UVs starting
0.006 down, so it draws them at 499x268. `docs/formats/mv3-video.md` has
the frames and `Update`'s pacing.

## `NewMainMenu` (retail `0x00216460`)

Hot Pursuit, World Racing and Options. Retail's object is 636 bytes, and
its one instance is at `gp-16132`.

| function | retail | demo |
|----------|--------|------|
| `Callback` | `0x00216a10` | `0x00203a48` |
| constructor | `0x00216460` | |
| destructor | `0x00216598` | |
| `HandleEvent` | `0x00216638` (jump table at `0x002bc480`) | `0x00203768` |
| `OnTick` | `0x00216718` | |
| `OnHighlight` | `0x00216938` | |
| `HighlightMenuItem` | `0x00216880` | |

`Callback` builds the object on `SCREEN_ACTIVATE`: `new(636)`, then the
constructor with the screen's hash. On `SCREEN_UNACTIVATE` it deletes the
object if there is one and clears the instance. Every other message goes to
`HandleEvent` without checking.

The constructor, in order:

1. `tAnimatedBlurb` at `+4` (`0x002491b0`), on text objects `0x75980cf0`
   (twice) and `0x70a404ec`.
2. `tHighlightAnimation` at `+424` on `ANIMATING_MENUITEM` (`0xab671c9a`),
   in `gp-16136`'s `0x80`, the title's bloom colour.
3. `tSlideInAnimation` at `+456` (`0x00248fd0`), from
   `FlailerGetTopLeftX(NEW_MAIN_MENU, 0x6e34e350)`.
4. `+476`, the idle `Timer`, and `+632` zeroed, and a `SelectionSet` at
   `+480` (`0x0016e120`).
5. `FrontendDatabase::MakeChallengeCarsAvailable(&Fred)` (`0x00183af8`) and
   `RaceParameters::InitWithDefaults` (`0x001ed5c8`) on `0x0031a898`.
6. `+476 = RealTimer`, and the jukebox's `Start(1)` (`0x001aeab0`).
7. `SelectionSet::AddItems` (`0x0016e1f8`): the five menu items at
   `0x0031be40`.
8. `StartMovie("MOVIES\mainmenu_movie.AVI")`.
9. `TheEasterEggs.Start()` (`0x0024f488`), then
   `FlailerSetGroupVisibility(NEW_MAIN_MENU, 0x74e404b4, 0)`.
10. `+628 = 0`.

The destructor runs `TheEasterEggs.Stop()` (`0x0024f610`), hides the same
group again, and then runs the four members' destructors, last built first.

`HandleEvent`'s table is on `message - 1`, 24 entries:

| message | what |
|---------|------|
| `MENUITEM_SELECT` (1) | the demo's three-way test |
| `MENUITEM_HIGHLIGHT` (4) | `OnHighlight` |
| `SCREEN_BACK_BUTTON` (17) | `Param = 0` and `Noise = 0` |
| `SCREEN_TICK` (18) | `OnTick` |
| `ANY_BUTTON_PRESSED` (24) | `+476 = RealTimer` |

The select is the demo's. `MENUITEM_1` sets `Fred.MainMenuOpts.mPolice`
(`0x002fc070`, `Fred+32`) to 1 and goes to `"Cops On Mode Select"`.
`MENUITEM_2` clears it and goes to `"Cops Off Mode Select"`. `MENUITEM_3`
goes to `"Options"`. All three push `New Main Menu`.

**BACK is retail's.** The demo's table sent it nowhere, so
`MoveToPreviousScreen` popped the stack back to the title. Retail's clears
`Param`, so the move goes nowhere, and `Noise`, so it makes no sound. The
main menu is where the frontend begins.

`OnTick`:

```c
if (tHelpMenu::IsActive(list+452)) { TheEasterEggs.+0 = 0; Timer = RealTimer; }
else {
    TheEasterEggs.+0 = 1;
    if (TheEasterEggs.+4) {                       /* a code just entered */
        Timer = RealTimer;
        MakeFrontendSound(30);
        FlailerSetGroupVisibility(NEW_MAIN_MENU, 0x74e404b4, 1);
        FlailerSetLanguageID(NEW_MAIN_MENU, 0xf58c1a4b, TheEasterEggs.+8);
        TheEasterEggs.+4 = 0; +628 = 1; +632 = RealTimer;
    }
}
if (gp-16120) 0x0024f968();                       /* never set; a no-op */
if (GetPopupActiveState(list, 0)) Timer = RealTimer;
ConsiderStartDemoMode(&Timer);
blurb.Animate(); bloom.Animate(); slide.Animate();
if (+628 && (RealTimer - +632) * 0.00025f > 3.0f) { +628 = 0; /* hide the group */ }
```

`OnHighlight` points the bloom at the item (`SetCurrentMenuItem`,
`0x002488d0`), then calls `HighlightMenuItem`. That takes the item's
`FlailerGetBoundingBox` (`0x00144280`) and frames it with two objects, both
moved by `0x001b9ae8`, which sets an object's top-left Y. `0x32c91dae` goes
to its bottom plus `gp-16112`, and `0xc671680c` to its top minus
`gp-16116`. It then gives the blurb new text (`NewText`, `0x002494e8`) and
tells the `SelectionSet` (`SetCurrentItem`, `0x0016e270`).

`gp-16112` is -3.0 and `gp-16116` is 6.0, so the brackets sit 3 above the
item's bottom and 6 above its top. These are `bscreens.h`'s
`BSCR_UNDER_MODE_SELECT` and `BSCR_OVER_MODE_SELECT`, the Mode Selects'
offsets. The box comes back as four ints, which `HighlightMenuItem`
converts with `cvt.s.w`. `OnHighlight`'s switch on the item:

| item | mask | blurb |
|------|------|-------|
| `MENUITEM_1` (`0x52e039f3`) | `MI_1_MASK` (`0x6e34e350`) | 10016, "Be the cops or beat the cops!" |
| `MENUITEM_2` (`0x52e039f4`) | `MI_2_MASK` (`0x708a0bf1`) | 10015, "Take on the world's best sports cars!" |
| `MENUITEM_3` (`0x52e039f5`) | `MI_3_MASK` (`0x72df3492`) | 10009, "Customize your settings." |

For any other hash the bloom has moved, but the brackets and the blurb stay
where they were.

### `TheEasterEggs` (`0x0031d7e8`)

Retail named neither the object nor the group. The port calls them
`TheEasterEggs` and `BGF_GROUP_EASTER_EGG`.

The group is two text objects of `NEW_MAIN_MENU`: "Unlocked" (LanguageID
62001, at (10, 376)) and "Easter Egg" (`0xf58c1a4b`, at (10, 400)). Both are
authored visible. The constructor's hide is all that keeps them off the
menu, and a code entered shows them for three seconds, with that code's
name in place of "Easter Egg".

The object's constructor (`0x0024f420`) puts its vtable at `+60` and a table
of 78 codes at `+12` (`0x0031d828`, count at `+16`). A code is 56 bytes:

* eight pad events, from 133 to 148;
* a type (`+32`) and a parameter (`+36`);
* a group (`+40`);
* the LanguageID of its name (`+44`, for example `0xf1ba2`);
* an active flag (`+48`) and one more field (`+52`).

`Start` registers a handler (`0x0024fa88`) with `AddJoyHandler`
(`0x00154140`) for events 133 to 148. It matches the last eight presses, a
ring, against the table (`0x0024f748`). `Stop` takes the handler back with
`RemoveJoyHandler` (`0x001541e8`). `+0` gates it, and `OnTick` keeps it
clear while a help menu is up. `+4` is set when a code comes in, and `+8`
holds that code's name.

### What the port has

`gameflow.c` has:

* the callback, and the constructor in retail's order: the four members
  (`menuBlurbInit`, `menuBloomInit`, `menuSlideInInit`, then the
  `SelectionSet` with IndicatorMode 1 and `menuSelAddItems` over the five
  masks), the idle Timer, the jukebox's `Start(1)`, the movie, the eggs'
  `Start` and the hide;
* the destructor: `Stop`, the hide, then the members, last built first.
  `SelectionSet`'s and `tHighlightAnimation`'s only free.
  `tSlideInAnimation`'s is `tSlideAnimation`'s (`0x00248c08`), which puts
  its groups back, and `tAnimatedBlurb`'s releases its two alphas and its
  group;
* the select and the BACK veto;
* `OnTick` (`mainMenuTick`): the Timer reset while popup 0 is up, the three
  Animates (blurb `0x00249348`, bloom `0x00248970`, slide `0x00248d20`),
  and the group down three seconds after it went up;
* message 24, which resets the Timer;
* `OnHighlight`: the bloom's `SetCurrentMenuItem` first, then
  `HighlightMenuItem` (`hooks.moveBrackets`, the blurb's `NewText`,
  `hooks.setBlurb` and `SetCurrentItem`). The Mode Selects' hooks move the
  brackets on the 3DS. The top screen still hides `SCROLLING_TEXT`, and the
  bottom panel shows the sentence.

Before `OnHighlight`, the brackets stayed where `NEW_MAIN_MENU` authors
them, around Hot Pursuit. On the Mode Selects they moved, because
`bscreens.c` ports their highlight, so the menu looked like it lost the
highlight only after coming back.

### The echo

The echo is the bloom: `tHighlightAnimation` on `ANIMATING_MENUITEM`. Every
tick of its first half second, `Animate` (`0x00248970`, the demo's
`0x00232418` but for the Visibility byte's offset) copies the highlighted
item onto `ANIMATING_MENUITEM` (`CopyFlailerText`), scales the copy about
its centre from 1x to 2x, fades it from alpha 128 to 0, and colours it
`0x80`, red. After four seconds (`HighlightTimeout`) it starts again, and
each highlight restarts it.

`CopyFlailerText` (`0x0013ec18`, retail `0x001410a0`) copies the 64 bytes
from `ObjectType` on: visibility, Z, position, scale, font, format, colour,
LanguageID and the `String` pointer. It keeps the two hashes and
`pFlailerStrip`, which its `jal`'s delay slot saves, and sets
`DirtyFlag` 8. The port's hook used to copy only the string. Every screen
authors `ANIMATING_MENUITEM` off the bottom of the screen: at y 534 on the
main menu and 676 on the title. So none of the port's blooms had ever
shown. `bui_copy_text` is the whole copy now. On Azahar a red "Hot Pursuit"
grows out of the label and fades, every four seconds.

`hooks.easterEggs` only logs on the 3DS. The 78 codes are not ported, so
nothing is handed the pad, and the group can never come back.

Still owed:

* the eggs' half of `OnTick`, and the 78 codes;
* `MakeChallengeCarsAvailable` and `InitWithDefaults`, which car select and
  its race read;
* the jukebox itself: `hooks.jukebox` only logs;
* attract mode from the main menu. `StartDemoMode` has no race yet, so all
  it could do is stop the menu's movie.

`bootflow_check` runs retail's `Callback`, `HandleEvent` and `OnTick` on the
image (`RetailMainMenu`). The members are said as the port traces them:
"blurb init", "bloom init", "slide in" (with `FlailerGetTopLeftX` answering
0.0, as the harness's world does), "sel items", "menu animate" once,
"bloom item", "menu kit released" and "jukebox 1". The two `Fred` calls
and `ConsiderStartDemoMode` are stubbed, silently, as the port owes them.
`HighlightMenuItem` runs. `FlailerGetBoundingBox` answers one box for every
mask, and the two brackets' Ys are given relative to it, as the offsets the
port's hook takes. 48 scenarios, 27,890 lines, 0 differ. Of 190 mutations,
187 are caught and 3 are equivalent.

## `MumboJumboScreen` (`0x0016a8b0`)

The legal and anti-piracy panels. Dead on this build -- both
`MumboJumboScreen::ShouldSeeLegalScreen` (`0x0016a648`) and
`ShouldSeeAntiPiracy` (`0x0016a650`) are `return 0`, and `ShouldSeeLegalMumboJumbo`
never pushes the screen in the first place -- but the state machine is intact
and worth having, because it is the shape every "show a picture for N seconds"
screen in the game uses.

State in `+12`, a single bitmap object `0xdd479599` on the screen whose texture
is swapped:

```
0 -> if ShouldSeeLegalScreen:  state 1, hide the plane,
                               LoadTexturesFromFile(pDynamicTexturePack,
                                   { 0xa7ebc389 }, 1,
                                   CallbackFinishedLegalScreen)
     else if ShouldSeeAntiPiracy: state 3, same with 0x38258033
     else MoveBackScreen(1)
1 -> when LegalScreenLoaded:   state 2, FlailerChangeTexture(.., 0xa7ebc389),
                               show the plane, Timer = RealTimer
2 -> after LegalScreenTimeout: UnloadTexturesFromFile(0xa7ebc389), then
                               anti-piracy (state 3) or MoveBackScreen(1)
3 -> when AntiPiracyScreenLoaded: state 4, texture 0x38258033, show, Timer
4 -> after AntiPiracyTimeout:  unload, MoveBackScreen(1)
```

`LegalScreenTimeout` (`0x00323710`) and `AntiPiracyTimeout` (`0x00323714`) are
both **7.0f**, and both are compared against `RealTimer` differences through
`Timer::SetTime`, i.e. in units of 1/4000 s -- see [Clocks](#clocks).

The two textures are loaded on demand out of `GLOBAL\DYNTEX.BIN` rather than
living in a bundle, which is what `pDynamicTexturePack` (`0x00323620`) is for.

## `BootAutoLoader` (`0x00231370`)

The first screen on a retail boot: "checking memory card". It is an 84-byte
object wrapping four memcard helpers --

```c
struct BootAutoLoader {
    MemcardLoader   Loader;      /* +0  */
    MemcardSaver    Saver;       /* +28 */
    SavegameData    Data;        /* +48 */
    MemcardTester   Tester;      /* +52 */
    MemcardPrompter Prompter;    /* +72 */
    int             Port;        /* +76 */
    int             State;       /* +80 -- 1 loading, 2 saving, 0 done */
};
```

-- whose constructor calls `FlailerScreenList::StopMovie` and then
`MemcardLoader::StartLoadSequence`. `HandleEvent` (`0x00231488`) forwards to
`MemcardLoader::HandleEvent` while `State == 1` and to `MemcardSaver::HandleEvent`
while `State == 2`; either returning 1 clears `State`, and the next
`SCREEN_TICK` with `State == 0` calls `MoveBackScreen(1)`.

That is the demo's. Retail's is the whole load, below.

## The memory card

Retail's `BootAutoload` screen is `BootAutoLoader::Callback` (`0x00247ab0`):
a `BootAutoLoader` built on `SCREEN_ACTIVATE`, every event handed to it, and
deleted on `SCREEN_UNACTIVATE`. The constructor calls `StopMovie` and
`StartLoadSequence`, as the demo's does. What is under it is five classes,
all in `memcard.c`, each rule there naming its address.

### `MemcardTester` (`0x002457c0`)

The constructor makes the card's file system, a `cDBFileSys`, and services
it until `mLastError` (+292) is no longer 16 (error), 15 (in progress) or 2
(new card). The loop has no bound in the original, and none in the port.
`HandleEvent` (`0x00245900`) services the card once a tick, and the loader
only sends it the tick while the tester is `Active`.

There are three jobs:

| Job | Address | `SetState` | What it does |
|---|---|---|---|
| `Verify` | `0x00245c40` | 7 | is there a card, and is it formatted |
| `Load` | `0x00245ba0` | 2 | `settings.db` into the cleared local copy |
| `CheckForSavegameFile` | `0x00245ca8` | 3 | is `settings.db` there |

Each sets `Active`, and the job's callback clears it. A card that refuses
the job (`SetState` returning 0) clears it at once. `GetPort` and `GetSlot`
(`0x00245600`, `0x00245608`) are 0 for every device.

### `SavegameData` and `OverwriteFred`

The save is `settings.db` (`0x002bebe0`), 0x114e0 bytes. Its last word, at
0x114dc, is the sum of every word before it (`VerifyChecksumAfterLoad`,
`0x00245780`). `SetupForLoad` (`0x00245700`) zeroes the local copy before
every read.

`OverwriteFred` (`0x00245d30`) copies the loaded file over `Fred`, clears
+904 (the word after `DemoModeStatus`), and puts back the language the boot
just chose at +372, so the file's language never wins. Then it makes six
calls that carry the loaded settings into the frontend, and the port owes
all six:

* `0x001fe988` twice, on Fred+392 and Fred+648 (256 bytes each), into
  gp-16700 and gp-16696;
* `0x001ef120(Fred+148)`;
* `0x00154308` and `0x00155000` for each pad, with Fred+376[pad];
* `0x001f4b10(Fred+324)`.

### `MemcardPrompter`

The prompter has two builders onto the popup screen (`0x0ce3f7ce`), both
titled 150004, "Memory Card (PS2)":

* **`DisplayMessage`** (`0x00245e30`) shows a message with no buttons.
  Its flags are horizontal and "select does nothing", so SELECT cannot take
  it down.
* **`DisplayYesNoMessage`** (`0x00245f60`) shows Yes and No, left to right,
  starting on No. BACK does nothing to it.

Every string gets the slot, counting from 1. The table at `0x002bed90` says
which strings take more:

* 151011 and 151027 take the kilobytes a save needs as well;
* 151028 takes nothing.

Both builders leave `CancelParam`, `DismissParam` and `PopupID` as stack
garbage. No state that reads a dismissal's `Param` ever sees one of those,
and the port zeroes them.

### `MemcardLoader::HandleEvent` (`0x00246c00`)

The state machine, `State - 1` through the table at `0x002bee80`:

| State | On a tick |
|---|---|
| 1 `CHECK_FOR_CARD` | After two seconds of "Checking" (151013) and with the Verify done, it acts on the result. Not formatted leaves with 151101. OK or a new card goes on to look for the file. Anything else is no card: 151025 on the boot, and the retry question 151006 on a manual load. |
| 2 `CHECK_IF_CARD_OK` | Once the check is done. The file is there: the boot reads it, and a manual load asks 151022 (overwrite the settings in use?) first. It is not: the boot checks the free space, and asks 151011 if a save would not fit, before it leaves with 151003. Any other error: the boot asks 151027, a manual load 151006. |
| 3 `READING_FILE` | After two seconds of "Loading" (151001) and with the read done. If the checksum holds, it shows "Loaded" (151002) and runs `OverwriteFred`. Otherwise the boot says 151024 and a manual load asks 151018. |
| 6 `SHOW_STATUS` | A manual Yes checks for the file again. After two seconds it acts on the second look, through the table at `0x002beea0`: OK reads the file, not formatted leaves with 151101, a new card with 151014, no file with 151003. Anything else is treated as no card. |
| 7 `READY_TO_LEAVE` | After four seconds it becomes `DONE`. |
| 8 `DONE` | The popup comes down and `HandleEvent` returns 1. |

`POPUP_DISMISS` is `State - 3` through `0x002beec0`:

* **The two questions.** Yes on a retry (param 0) starts the sequence
  over, and No (1) is `DONE`. Yes on the overwrite question (2) shows
  "Checking" and goes to `SHOW_STATUS`, and No (3) is `DONE`.
* **States 3, 7 and 8.** These clear `Noise`, so the message taken down to
  put the next one up makes no click.

This is why the original has two orders for "leave with a message":

* **Quiet**: set the state, then put the message up. Taking the old message
  down is silent.
* **Loud**: put the message up, then set the state. The old message's
  dismissal clicks.

The port keeps each where the original has it.

The timers are `(float)(int)(RealTimer - start) * 0.00025f`, compared
strictly against the literal (`2.0f`, and `4.0f` for `READY_TO_LEAVE`).
0.00025f is a hair over 1/4000, so a whole number of seconds comes out a
little over itself. At one-second frames, 12000 ticks is 3.0000002, and a
two-second wait and a three-second one end on the same frame. The checker's
`manualhalf` row runs at half-second frames, where they do not.

The free-space test is `GetFreeSpace < CalculateFreeSpaceRequired`, strict.
The requirement is the file rounded up to kilobytes, plus five for the
directory: `(0x114e0 + 1023) / 1024 + 5`, which is 75. A card with exactly
75 KB free is not asked about (`tight`).

On a blank card at 1/60 s, the boot spends:

* 122 frames on "Checking";
* 1 frame looking for the file;
* 243 frames on "no save file" (151003).

It moves back in frame 368. The checker's rows written before the card add
`BOOT60` (365) frames at 1/60, and `BOOT1` (8) at a second a frame, so their
frame numbers still count from where they did.

### `tPopupMenu` and the screen list's popups

`FlailerScreenList` holds two popups, at +392 and +396.

* **`Tick`** (`0x0016cca8`) ticks both, active or not.
* **`JoyHandler`** (`0x0016cab0`) hands an event to every active popup
  whose `JoyPort` is the event's port or -1. If any popup took it, that is
  the end of the event. Otherwise:
  * the current screen gets message 24, `ANY_BUTTON_PRESSED`, whether or
    not the button is down. **The port owes this.**
  * BACK then moves to the previous screen, and anything else goes to the
    screen's own `JoyHandler`.

`tPopupMenu`'s methods (`bpopup.c`):

* **The constructor** (`0x0016b478`) builds the bloom, clears the config
  and makes three `FlailerMenuItem`s on `BUTTON1..3`.
* **`Summon`** (`0x0016b660`):
  1. un-highlights the three buttons, last first, and shows the screen;
  2. sends `POPUP_ACTIVE` (20) to the parent's callback, which it reads
     from the config;
  3. starts on `StartButton` and highlights it;
  4. word-wraps the message into the `MESSAGE` group;
  5. puts the buttons ten pixels under the last line, if the flags say
     buttons go below;
  6. sets the buttons' and the title's language IDs.
* **`Dismiss`** (`0x0016b9c0`) hides the screen, unless the config keeps it
  up, and sends `POPUP_DISMISS` (21) with the button's param and a select
  click the parent may silence.
* **`HandleJoy`** (`0x0016bac0`) takes every event.
  * A horizontal popup's left and right are its up and down, and its own
    up and down do nothing.
  * Up and down wrap round and send `POPUP_NEXT` (22) or `POPUP_PREV` (23).
  * SELECT or START dismisses with the current button's param, unless the
    flags say select does nothing.
  * BACK dismisses only a cancelable popup.
* **`Tick`** (`0x0016ba50`) advances a phase by `9 * RealElapsed`, wraps it
  at 6.283185, and passes it to `bSin`. The answer is thrown away, so the port
  keeps the phase and skips the sine.

`FlailerMenuItem`'s recolour, retail's, is the popup buttons' (`0x00169bd0`,
`0x00169cb0`). `State & 3` picks the colour:

* the saved colour when enabled;
* the highlight, `0x004080`, when enabled and highlighted;
* gray, `0x181818`, otherwise.

`bmenu.c`'s menus still recolour the demo's way.

### `RenderTextIntoGroup` (`0x00144b38`)

This is the popup's word wrap. It takes the group's text objects in file
order, and cuts each line at the last space, tab or `@`. Two details
matter:

* **It cuts late.** The cut happens only once the line has reached
  `MaxChars - 2`, so a word longer than a line runs on past `MaxChars`.
* **An `@` always cuts.** The next line starts after the break, and the
  loop's own step skips that character unexamined. So `@ @` is a blank
  line.

Each line is copied into a zeroed 256-byte buffer, and the chunk is made
visible and set (`WriteTextIntoChunk`, `0x00144ae8`). Lines past the text
are hidden. The answer is the bottom of the first unused line: its
`TopLeftY` plus `GetScaledHeight`, truncated.

In the checker, the popup screen's first two message lines have `MaxChars`
29 and 30 rather than the file's 40. At 40, none of the scenarios' messages
breaks where the "less two" matters.

## Clocks

`AdvanceRealTime` (`0x00199410`) drives both counters the flow code uses:

```c
Accum += RealTimestep;                 /* seconds, float */
n = (int)(Accum * 60.0f);
RealTime += (n != 0) ? n : 1;          /* 0x00323cd4 -- 60 Hz ticks   */
Accum -= n * (1.0f / 60.0f);
Timer t; Timer::SetTime(&t, RealTimestep);
RealTimer += t;                        /* 0x00323cd0 -- 1/4000 s units */
FrameCounter++;                        /* 0x00323cc8                   */
```

`Timer` is a fixed-point second: `Timer::SetTime(f)` (`0x00134ef0`) stores
`(int)(f * 4000.0f)`. So:

* `GameFlowLoadingFrontEnd`'s 181 / 361 / 541 are `RealTime` ticks -- 3, 6 and
  9 seconds.
* `TitleScreen::Timer`, `MumboJumboScreen`'s timeouts and the demo-mode
  countdowns are `RealTimer`, 1/4000 s.

`RealTime` advances by at least 1 per frame even when the timestep rounds to
zero, so it is a frame counter that tracks wall-clock when frames are slow.

## Attract mode

`ConsiderStartDemoMode(Timer &since)` (`0x00169f98`):

```c
idle = (RealTimer - since) * (1.0f / 4000.0f);      /* 0x003213fc */
if (idle > BeginDemoModeTimeout || TheDemoDiscManager.bActive_and_attract) {
    if (TheDemoModeReplay.<+4>) return;             /* already going */
    if (TheDemoModeReplay.<+8>) { DemoModeReplay::Launch(); StartDemoMode(); }
    else if (!DemoModeReplay::ConsiderLaunching()) StartDemoMode();
}
```

`BeginDemoModeTimeout` (`0x00322f78`) is **30.0f** and `DemoModeTimeout`
(`0x00322f7c`) is **120.0f** -- half a minute idle on "PRESS START" starts the
attract demo, which runs for two minutes.

### Retail's `ConsiderStartDemoMode` (`0x0016ed50`)

The same shape. The differences:

* `BeginDemoModeTimeout` is at `0x0032feb4`, still 30.0f.
* The idle time is compared signed.
* The demo-disc test is `bActive && IsAttractMode()` (`0x0012eaf0`). The
  attract flag is asked only of the demo disc, so on the retail disc the
  flag alone never starts it. The port leaves the test out.

`TheDemoModeReplay` is at `0x002f0960`, with +4 set while a replay loads and
+8 once it has loaded:

* **Loading**: wait.
* **Loaded**: `Launch` (`0x0013f1c0`), then `StartDemoMode` (`0x0016ecd8`).
* **Neither**: `ConsiderLaunching` (`0x0013f120`). `StartDemoMode` runs only
  if it found nothing to launch, so a replay found now plays when it has
  loaded.

`bootflow_check` runs this on the image under the title's `HandleTick`. The
replay is the harness's world: a `replays` count of replays to find, each
landing three frames after it is asked for.

`StartDemoMode` (`0x0016ecd8`):

1. `StopMovie` on the screen list (`gp-21324`).
2. `BuildDemoTrackList` (`0x0016ec10`).
3. The index is `DemoTrackIndex` (`gp-21160`), which is then stored back
   7 on.
4. The track is `0x002fb288[index % NumDemoableTracks]` (`gp-21168`). The
   table is all zeros in the image and is filled at run time. On the demo
   disc (`IsActive`, `0x002effe0`) it is 12 instead.
5. A tail-jump to `FrontendDatabase::StartDemoMode` (`0x00184d48`), with
   `0x002fc050` in `a0`.

`bootflow_check` runs it on the image too, with `BuildDemoTrackList` giving
one track and the database's half saying "attract". The port runs
`StopMovie`, traces "demo mode" and leaves the rest to the host's
`startDemoMode`. `DemoModeReplay`'s own internals are owed.

## Demo disc

`TheDemoDiscManager` (`0x002e8120`) is a 48-byte `DemoDiscManager` *object*, not
a pointer, so every `if (TheDemoDiscManager)` in the disassembly is really
`if (TheDemoDiscManager.bActive)` -- `bActive` is field 0. Its constructor
(`0x0012d118`) sets `bActive = 0`, has exactly one caller
(`_GLOBAL_$I$TheDemoDiscManager`), and nothing in the image ever writes
`bActive`. So on this disc every demo-disc branch in the boot flow is dead:
no legal slideshow during loading, two title movies rather than one, and the
title screen falls through to `ConsiderStartDemoMode`.

The ctor's other defaults, for the record: `InactiveTimeout = 60`,
`TotalTimeout = 600`, `PlayMode = 1`, `MediaType = 10`,
`nDemoDiscEndReason = -1`.

The port leaves all of this out. It is written as if `bActive` were 0,
which it always is, so it has none of the following:

* the `EXIT_DEMO_DISC` state;
* the loading slideshow (`FIRSTLEGAL`, `SLIDE2`, `DISCLAIMER`) or the
  Loop that runs it;
* `BeginScreenFadeTime`, which only that Loop reads;
* the one-movie title;
* the title's `StartDemoDiscGame`;
* `CheckForDemoDiscTimeout`;
* `demodisc.c`, removed on 2026-09-28.

Attract mode is not the demo disc's. It stays: `StartDemoMode`,
`ConsiderStartDemoMode`, `TheDemoModeReplay` and `Fred.DemoModeStatus`.

Retail's generated event table is also kept whole:

* `JOY_EVENT_EXIT_DEMO_DISC` (2);
* its START+SELECT scanner row.

Removing them would renumber every event after them. The checkers hold
`bActive` at 0 on the image, so retail's code there takes the same
branches as the port.

## The screen registry

`ChangeToScreen` takes a *name*, not a hash, and `FlailerScreenList::FindScreen`
(`0x00167c58`) walks a linked list of `FlailerScreenConfig` looking for it:

```c
struct FlailerScreenConfig {          /* 56 bytes, .mdebug type#602 */
    bTNode<FlailerScreenConfig> link; /* +0, +4                      */
    const char *ScreenName;           /* +8                          */
    void      (*Callback)(ScreenMessage, ScreenCallbackData *);  /* +12 */
    int         NumScreens;           /* +16                         */
    int         FlailerHashes[4];     /* +20                         */
    JoystickPort Ports[4];            /* +36                         */
    int        *HelpMenuItems;        /* +52                         */
};
```

`Populate` (`0x00166150`) fills it in and links it into `FlailerScreenConfigList`
(`0x003236c0`). There is no table to read -- the ~49 configs are built one
`jal` at a time by `_GLOBAL_$I$*` constructors spread across a dozen object
files -- so `tools/screen_registry.py` walks `.text`, finds every call to
either `FlailerScreenConfig` constructor, and back-propagates the argument
registers to recover the triple. It resolves **49 of the 51 call sites**; the
two it does not are the 4-argument constructor forwarding to the 7-argument
one inside `FlailerScreenConfig` itself, which register nothing.

All 49 hashes exist as `0x80010200` screens in the three bundles (of 73 screens
total; the other 24 are reached as sub-screens or are unused). The ones the
boot flow needs:

| name | hash | callback |
|------|------|----------|
| `BootAutoload` | `0xfa2ac5c6` | `BootAutoLoader::Callback` |
| `Language Options Pre FE` | `0x632b068e` | `LanguageOptionsScreenBase::Callback` |
| `Title Screen` | `0xb5761d00` | `TitleScreen::Callback` |
| `New Main Menu` | `0xae0f8aa1` | `NewMainMenu::Callback` |
| `Popup` | `0x037f3133` | -- |

Run `python tools/screen_registry.py` for the rest.

### `ScreenName` and `FlailerHashes[0]` are two different strings

This trips you up the first time. `FlailerScreenConfig::ScreenName` is the C++
string literal the flow code passes to `ChangeToScreen` -- `"Title Screen"`,
`"New Main Menu"`. `FlailerHashes[0]` is *not* `bStringHash` of that literal.
It is the hash of the name the artist gave the screen in the Flailer authoring
tool, which is the same word in `SCREAMING_SNAKE`:

| `ScreenName` (C++) | authored name | `bhash(authored)` |
|--------------------|---------------|-------------------|
| `Title Screen` | `TITLE_SCREEN` | `0xb5761d00` |
| `New Main Menu` | `NEW_MAIN_MENU` | `0xae0f8aa1` |
| `Language Options Pre FE` | `LANGUAGE_OPTIONS` | `0x632b068e` |
| (gameflow, not a config) | `LOADING_TRACK` | `0xd0131dd1` |

`bhash("Title Screen")` is `0x0ae7daa1`, which is in no bundle. So there are
two namespaces, and the port has to keep both: the flow code and the screen
stack speak `ScreenName`, `uirender_find_screen()` speaks `FlailerHashes[0]`,
and `FlailerScreenConfig` is the only thing that joins them. `gameflow.c`
carries the same join as a static table.

The mapping is not mechanical enough to compute -- `Language Options Pre FE`
loses its `Pre FE`, and `BootAutoload`'s `0xfa2ac5c6` does not match
`BOOT_AUTOLOAD`, `BOOTAUTOLOAD` or `AUTOLOAD`. A `tools/bhash.py` crack over
`[A-Z0-9_]` to 8 characters, and to 8 plus a `_1`.`_BG`-style suffix, finds
nothing readable for it, so its authored name is longer than that and stays
unrecovered. It does not matter: the hash is what the lookup wants.

Object names inside a screen are in the same namespace. The one recovered so
far is the title screen's `0xb070dbc9` = `PRESS_START_1` -- note the `_1`,
which is Flailer's own uniquifying suffix and is part of the hashed string.
The two movie planes (`0x3acf2d73` 4:3, `0xbfaebf79` letterboxed) did not fall
to the same crack.

One more thing the registry says about the boot flow: screen `0xdd4197c9` in
`FRONTB.BUN` holds an object `0xdd479599` whose text is the legal notice, and
**no config registers it**. The `Legal MumboJumbo` screen was authored and
shipped; `ShouldSeeLegalMumboJumbo` just returns 0 (see above), so nothing can
ever reach it. The art is on the disc, the road to it is not.

Two configs can carry two hashes, one per joystick port -- `Joystick Config
Port1`/`Port2` and `Joystick Calibration Port1`/`Port2` register the *same*
screen hash against ports 0 and 1, which is how one authored screen serves
split-screen. Everything else registers one hash with `Port == -1` (any).

## What the four boot screens actually hold

Cross-checking two implementations proves they agree, not that they are right,
so the boot sequence was also rendered with `tools/flailer_render.py` and
looked at. All four screens live in `FRONTEND\FRONTB.BUN`:

| index | hash | name | objects |
|---|---|---|---|
| 21 | `b5761d00` | `Title Screen` | 7 |
| 20 | `dd4197c9` | `Legal MumboJumbo` | 1 |
| 29 | `632b068e` | `Language Options Pre FE` | 14 |
| 35 | `fa2ac5c6` | `BootAutoload` | 0 |

`BootAutoload` really is empty -- no objects at all, in `FRONTB.BUN` and in
`GLOBAL\INGAMEB.BUN` (index 22) alike. It exists only to own a tick while the
memory card job runs, which is why cracking its name turned up no object names
to go with it.

### The title screen renders black, and that is correct

Rendered as authored, `Title Screen` is 640x480 of solid black. The object
table says why:

```
TEXT   z=13  @ 328,282  b070dbc9  PRESS_START_1   font=FONT_HUD  'PRESS START'
TEXT   z=0   @ 138,525  6eb9985d  "There's 2 Bitmaps here!!!!!"
BITMAP z=0   @  -1, 65  bfaebf79  tex=SPLASH_SCREEN  scale=1.25,1.19
BITMAP z=0   @ -10,  0  3acf2d73  tex=SPLASH_SCREEN  scale=1.25,1.88
TEXT   z=0   @ 183,596  MENUITEM_1  'menuitem 1'
BITMAP z=24  @   0, 81  6eb9985d  tex=LOADING     scale=1.25,1.07
BITMAP z=24  @   0,280  6eb9985d  tex=TOP_BORDER  scale=1.25,1
```

Three things are going on at once:

* **`SPLASH_SCREEN` is a blank buffer.** It is a 512x256 32-bit texture in the
  `FRONTEND` pack whose 131072 pixels are every one of them `00 00 00 fe` --
  opaque black. It is not artwork; it is the target the movie player blits
  decoded frames into. `bfaebf79` and `3acf2d73` are the letterboxed and 4:3
  movie planes, `BGF_OBJ_MOVIE_PLANE_LB` and `BGF_OBJ_MOVIE_PLANE_43`.
* **Layer 0 is the frontmost layer of the main pass**, not the backmost --
  `eDisplayFrame` counts 15 down to 0 (see `LAYER_ORDER` in
  `tools/flailer_render.py`). So the two black movie planes, scaled to
  640x304 and 640x481, are drawn over everything in the main pass, including
  `PRESS START` at layer 13.
* **The two leftover texts are parked off-screen**, at y=525 and y=596 on a
  480-tall screen. `There's 2 Bitmaps here!!!!!` is a note the artist left
  themselves about the two movie planes.

So the authored state is the *during a movie* state, and the screen is only
ever black when there is no movie running. `HandleTick` (`0x0016a360`) is what
turns it into a title screen: when the last movie ends it sets both movie
planes `INVISIBLE` and `PRESS_START_1` `VISIBLE`, which uncovers the layer-24
pair -- `LOADING` (512x184, scaled to 640x196) is the Need for Speed logo and
`TOP_BORDER` (512x24) is the bar the words sit on. Rendered in that state the
screen is the retail title screen, logo and flashing `PRESS START` included.

The black is only `flailer_render.py`'s, which used to draw `SPLASH_SCREEN`
as the picture it holds. The game never does. With no movie open, a movie
plane draws nothing (see
[Movie planes draw nothing without a movie](#movie-planes-draw-nothing-without-a-movie)).
So the retail title shows through a plane that is still visible, and
retail's skip relies on that. `flailer_render.py` and `uirender.c` now both
skip `SPLASH_SCREEN` and `PANELMOVIE` bitmaps unless a movie stands in for
them. Rendered that way, the authored screen shows the layer-24 logo and
bar.

### `Legal MumboJumbo` shipped as a placeholder

Its one object `dd479599` draws texture `a7ebc389`, which is not in
`FRONTB.BUN` or `GLOBALB.BUN` at all -- it is `EA_LEGAL`, 512x448 8-bit, in
the `DYNAMIC` pack in `GLOBAL\DYNTEX.BIN`, which is what the screen's
`loadTexture` / `textureReady` / `unloadTexture` dance is for. Decoded, it
reads:

```
PLACEHOLDER
LEGAL SCREEN
```

in blue on white. `BGF_TEX_ANTIPIRACY` (`38258033`) is not on the disc in any
pack. Both corroborate the ELF: `shouldSeeLegalScreen` and
`shouldSeeAntiPiracy` return 0 in this build, the screen was never reachable,
and so nobody ever replaced the placeholder. The port keeps the screen and
gates it behind a `forceLegalScreens` flag that is off by default.

## What the 3DS port does with this

`3DS Files/source/gameflow.c` is the reimplementation: the same table-driven
`Begin`/`End`/`Loop` machine, the same 12-deep 32-byte screen stack, the same
`LaunchFrontendMenus` push order and predicates, and the same title-movie
sequencer, and retail's `LOADING_FRONTEND` and language screen.
`main.c` holds the concrete stage table, the way
`kVideoStages[]` does in NFSU2-3DS. `tools/bootflow_check.py` runs an
identical script through a second implementation in Python and diffs the
transcript, the way `tools/bmenu_check.py` does for the menus.

The title movies play, straight off the card: `avimovie.c` streams the
disc's `.AVI` and `mv3.c` decodes its MV3 frames (`docs/formats/mv3-video.md`),
and `hookMovieOpen` points the title screen's movie plane at the texture by
overriding the plane's own texture hash. `TitleScreen`'s `pMoviePlane` is
fixed to the 4:3 plane at construction, so `main.c` reads that object's
`textureHash` rather than assuming `SPLASH_SCREEN`.

START goes to the screen's menu, as `FlailerMenu`'s `JoyHandler` takes it:
`main.c` hands `BJOY_START` to `bmenu_joy`, which sends
`SCREEN_START_BUTTON` and then, since the title screen does not consume it,
`MENUITEM_SELECT` to the current item. It used to send
`SCREEN_START_BUTTON` straight to the flow. That is only the first half, so
START could neither skip the intro nor leave PRESS START; only A could. A
screen with no menu still gets `SCREEN_START_BUTTON` alone.

The title screen is retail's (see
[Retail's `TitleScreen`](#retails-titlescreen-sles_50731)):

* a select during the intro stops it and the title comes to rest;
* `PRESS START`, and the select that leaves, wait four seconds;
* `TITLE_IMAGE` shows at rest;
* `PRESS START` blooms.

`hookMovieClose` drops the texture override as it closes the movie.
`uirender.c` draws a `SPLASH_SCREEN` or `PANELMOVIE` bitmap only while an
override stands in for it, which is `RenderFlailerBitmap`'s rule. Before
that rule, a skipped intro left the frozen last frame over the logo.

The menus' movie goes through `hookPanelMovieOpen` and
`hookPanelMovieUpdate` (`aviplayer_init` and `aviplayer_update`). Unlike
the title's, it is drawn in its own plane, at the plane's size, and only
from its first decoded frame: retail's planes are empty until `Update`
fills them. A menu movie missing from the card is logged once, though
`UpdateMovie` tries it every frame. Its frames are decoded on another core,
ahead of the picture, so the menu keeps its own rate
(`docs/formats/mv3-video.md`, "The player"). `hookMovieClose` stops that
worker before it logs the movie's cost and closes it.

The boot is retail's, in retail's order:

1. **LOADING.** `main.c` adds the `GLOBAL` and `DYNTEX` bundles, then calls
   `bgf_load_global_chunks`. `hookDisplayFrame` draws that one frame, as
   `eDisplayFrame` does: `LOADING_TRACK` on the top screen and a blank
   bottom screen. The `FRONTEND` and `INGAME` bundles decode after it, the
   slow part of the boot, so LOADING stays up while they do.
2. **`BootAutoload`**, retail's (see [The memory card](#the-memory-card)).
   It shows "Checking" for two seconds on the popup. With a save it then
   shows "Loading" and "Loaded"; without one, "no save file". Then it moves
   back.
3. **The language screen.** `Language Options Pre FE` comes up. A picks a
   language, and so does B on a highlighted language.
4. **The movies**, then the title.

The memory card is the SD card. `main.c`'s `hookNewFileSys` hands the
tester an `SdCard`, a `cDBFileSys` whose jobs finish on the next Service:

* `LOAD` reads `sdmc:/NFSHP2/SAVES/settings.db` whole, or answers error.
* `SAVE` writes it, making `sdmc:/NFSHP2` and `SAVES` first.
* `CHECK_EXISTENCE` is a `stat`.
* Every other job is OK.

`GetFreeSpace` is the SD card's free clusters in kilobytes, from
`FSUSER_GetSdmcArchiveResource`, or 8192 if that fails. `CalculateFreeSpace`
is retail's `(size + 1023) / 1024 + 5`. The flow's `fred` is a
`BMC_SAVE_SIZE` buffer in `main.c`, which nothing reads yet.

While a popup is up, `main.c` gives it the pad before the menus see it:

* the D-pad and A through `kBinds`;
* START as `BJOY_START`;
* B as `BJOY_MENU_BACK`.

The keys the popup took are then cleared. The animation kit gained the
four answers `RenderTextIntoGroup` asks for: the next text object in a
group, `MaxChars`, the scaled height and the colour.

`gameflow.c` runs the loads through a queue in `main.c` (`hookLoadResource`,
`hookLoadSoundRegions`). A load lands at the end of the frame it is asked
in, and its callback moves the flow on, as retail's do. The bundles are
already in memory by then, so nothing waits on the card.
`uirender_draw_visible` draws every visible screen, one layer at a time
across all of them, which is what `eDisplayFrame`'s single layer table
does. The port used to draw only the current screen, and `LOADING_TRACK` is
never current: it is only made visible.

`bootflow_check` runs retail's `LoadGlobalChunks`, Begin, Loop, End, both
load callbacks and the language screen's `Callback` on the image, as it
does the title. Its world queues the loads and lands them a frame later,
and a `slow<n>` input holds them back until frame `n`. It fakes the screen list at `gp-21324` so
that `strcmp` sees the name the screen was entered under.

`BootAutoload` runs on the image too: `BootAutoLoader::Callback` and
everything under it, the popup and its word wrap. The card is scripted,
with a table of cards in both harnesses: `good`, `badsum`, `nocard`,
`full`, `tight`, `busy`, `slow`, `gone`, `swapped`, `pulled` and so on.
Each gives its jobs' answers, the free space, and how many Services a job
takes. `Service` must call back into retail code, so on the image it is a
hook in front of four instructions that jump to what the hook leaves in
`t9`.

The class's stubs are its own only while it runs, and are put back after,
because the language screen calls `MoveBackScreen` for real.

One input rule matters for these rows. An input at frame N is handled before
frame N's tick, so a question put up in frame N's tick answers only from
frame N+1.

The menus' movie runs on the image as well: `StartMovie`, `UpdateMovie`
and `StopMovie` as shipped, called from the flow's frame as `Tick` calls
them, with `InitFile`, `Close` and `Update` stubbed onto the world. The
world's movie answers 0 on its 90th update, so a loop comes round within a
row. The rows:

* **`menumovie`**: the main menu's movie opens, loops, and stops when a
  race's world comes in (`ingame`). When the flag drops again
  (`outgame`), nothing reopens it: `StopMovie` took the gate down.
* **`menuagain`**: into the third item and back. The main menu's
  `StartMovie` on its return names the movie already started, so nothing
  reopens. Then the options movie twice: the first closes the main menu's
  and opens its own, and the second is a no-op.
* **`menuidle`**: the main menu, and BACK there, which retail's vetoes
  without a sound. The movie plays on, loop after loop, for forty seconds.
  It was `menuattract` while the model was the demo's, whose BACK went to
  the title and whose attract mode stopped the movie. Retail's `OnTick`
  would start attract mode at thirty seconds, which the port owes.
* **`attractmovie`**: `StartDemoMode`'s `StopMovie` with a movie open.
  With BACK vetoed, the main menu's movie can no longer be left playing
  under the title. The options movie is opened under the title at rest
  instead, and attract mode stops it before it starts. Retail reaches this
  from a screen that plays a movie and calls `ConsiderStartDemoMode`, as
  the main menu's `OnTick` does.
* **`select`** also presses BACK on the title, in the EA logo and at
  rest, which the title vetoes. It used to reach the title's BACK only
  from the main menu.
* **`menuhighlight`**: the main menu's highlight on World Racing and
  Options, and on `MENUITEM_9`, which moves nothing. Then into Options
  and back, and on Hot Pursuit and World Racing again.

`mainmenu` was retimed to select after `PRESS START` shows, 243 frames in;
before, it never reached the main menu.

`--mutate` now breaks `gameflow.c`, `bpopup.c` and `memcard.c` 171 ways
(the demo disc's mutants went with its code). Of those, 168 are caught. Three survivors are equivalent by construction:

* **`back-names-screen`**: no screen's callback reads `ItemHash` on BACK.
* **`mc-loadfailed-quiet`**: the message before `LOAD_FAILED` is
  "Loading". It comes down in `READING_FILE`, which silences dismissals as
  `READY_TO_LEAVE` does, so both orders sound the same.
* **`mc-autoload-plays-on`**: nothing the boot reaches has a movie open
  when `BootAutoload` starts.

Not yet on the host:

* **Speech.** `hookLoadSpeech` and `hookUnloadSpeech` only log, since the
  speech banks are not ported.
* **The French logo art.** `hookSwapLogoArt` only logs. `LOADING_FR` and
  `NFS_LOGO_ALPHA_FR` are not swapped in.
* **`Language Options`**, the Options menu's copy, gets the class without
  its `tSlideOnScreen` (`0x001ee918`).
* **`ANY_BUTTON_PRESSED`** (message 24), which `JoyHandler` sends the
  current screen when no popup takes a button.
* **`OverwriteFred`'s six calls** into the frontend. The loaded `Fred` is
  copied, and nothing reads it yet.
* **`MemcardSaver`**, the other half of `BootAutoLoader`, and the Options
  screen's manual load, which is reached only in the checker.
* **`StartDemoMode`'s track and `DemoModeReplay`'s internals.** The port
  stops the movie, traces "demo mode" and goes to attract.

The popup's title strip runs off the right of the top screen. The popup
screen is authored that way for a 640-wide TV, and it is left as it is.

`bootflow_check` does not write the title again. It runs retail's
`TitleScreen::Callback` itself on `SLES_507.31` under `tools/mipsemu.py`,
with the calls out of the screen stubbed onto its flow. Its `--mutate` pass
breaks `gameflow.c`'s title 25 ways and checks that the diff notices each
one. For the harness to see them, it needed:

* events that start with the `Noise` their `JoyHandler` gives them;
* a world that traces a movie being closed;
* a `start` input;
* two idle scenarios at a second a frame, `skipidle` and `restidle`, where
  attract mode counts from the skip or from coming to rest.

Retail's `TitleMoviesToPlay` is at `0x002fb750`. It differs from the demo's
in one entry: French plays `NFSINTRO_FR.AVI` second, where the demo had
`NFSINTRO_EN.AVI` in every row. `bootflow_check` holds its table to the
image.

Three deliberate differences. The first two are there because the data may
be missing:

* **A movie missing from the card is skipped.** `GAMESTAGE_TITLE` treats a
  movie it cannot open as one that has ended instead of hanging on it. The
  original would have hung; with the whole disc it never had to.
* **The memory card is a folder.** `settings.db` lives in
  `sdmc:/NFSHP2/SAVES`, which the user chose for every save. There is no
  card to pull or swap, so the SD card is always there and formatted, and
  "no card" and "new card" never come up. The strings still say "Memory
  Card (PS2)".
* **The movies fill the top screen, which the user asked for.** Retail puts
  them in the two planes, laid out for a TV. The 4:3 plane is at (-10, 0),
  640x481, pushed 10 px left for overscan. The letterboxed plane is at
  (-1, 65), 640x304, so it shows the intro at 2.1:1. Drawn in those planes,
  the EA logo left a gap down the right of the 3DS screen, and the intro
  came out 400x152. `hookMovieOpen` now passes `fill` to
  `uirender_override_texture`, and any plane drawing the movie covers the
  whole target instead of its own rectangle:
  - The EA logo is stretched from 4:3 to 5:3, as every menu is.
  - The intro is wider than the screen. It loses a 32nd of its width each
    side, about what a TV's overscan hid, and the rest is stretched.
    Keeping its shape outright would crop a tenth each side, and the EA
    TRAX song credit is burned into the frame 23 texels from the left
    edge, in both the English and the French intro.
  Both planes stay visible exactly when retail's are, and the flow never
  knows.
