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
[The predicates](#the-predicates)).

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

On the 3DS there is no memory card, so this collapses to "look for the save
file, then move on" -- but the *shape* (a screen that ticks until an
asynchronous job finishes and then pops itself) is the one the port needs.

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

For the port this means the title screen must hide both planes whenever a
movie is not driving, or it shows a black screen. `bgf_title` already does,
because it is a transcription of `HandleTick`; it is worth knowing why.

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
sequencer. `main.c` holds the concrete stage table, the way
`kVideoStages[]` does in NFSU2-3DS. `tools/bootflow_check.py` runs an
identical script through a second implementation in Python and diffs the
transcript, the way `tools/bmenu_check.py` does for the menus.

The title movie plays. MV3 is not decoded on the handheld -- see
`docs/formats/mv3-video.md` -- so `tools/movie_bake.py` turns the disc's one
movie into `MOVIES/INTRO/EALOGO_EN.M3V` beside the rest of the data, and
`hookMovieOpen` points the title screen's movie plane at it by overriding the
plane's own texture hash. `TitleScreen`'s `pMoviePlane` is fixed to the 4:3
plane at construction, so `main.c` reads that object's `textureHash` rather
than assuming `SPLASH_SCREEN`.

Two deliberate differences, both because the data is not there:

* **`MOVIES\INTRO\NFSINTRO_EN.AVI` does not exist**, and neither do the other
  six entries of `TitleMoviesToPlay`, so `GAMESTAGE_TITLE` skips a movie it
  cannot open instead of hanging on it. The original would have hung; it never
  had to. The same path covers a movie that exists but has not been baked.
* **`BootAutoload` has no memory card to wait for.** The port keeps the screen
  and the "tick until the job finishes, then pop" shape, and finishes the job
  immediately.
