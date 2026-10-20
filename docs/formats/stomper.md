# The render eggs

What five of the cheat codes (`easter-eggs.md`) do to the picture: the
Stomper, retail `0x0024b918` to `0x0024c420`, new in retail but for a
demo version of it that only the demo's own seven eggs use. Ported in
`stomper.c` (TASKS 50b); `tools/stomper_check.py` runs it beside retail's
code.

## The Stomper

A render egg is a list of StompEntry, 12 bytes: a type, a pointer and a
value. Set walks the list and "stomps" each global, keeping its old value
on the Stomper's stack, a word an entry; Clear walks it again in the same
order and puts them back.

| type | Set | Clear |
| --- | --- | --- |
| 0, 1, 2, 3 | byte, half, word or float: the old value kept, the new poked | the old value back |
| 4, 5 | the function called with 1 and the value (int or float); what it returns kept | called with 0 and what it returned |
| 6 | the nested list, on the same stack | the same |
| 7 | the list's end | |

Any other type does nothing and takes no word.

The Stomper is 12 bytes: `bEnabled`, the stack (1 KB, bMalloc'd
"Stomper Stack" in pool 16) and `nCurrent`, the egg that is set.
InitStomper (`0x0024bbd0`), InitializeEverything's last, makes the one
there is, `pStomper` (gp-14932).

| retail | port | what |
| --- | --- | --- |
| `0x0024bcd0` Clear | `stomper_clear` | the egg's values back, if one of 1 to 12 is set; none set |
| `0x0024bd20` Set | `stomper_set` | egg `e` set from the stack's start, if it is 1 to 12 |
| `0x0024c3e8` ClearSet | `stomper_clear_set` | the two |
| `0x0024bd78` Suspend | `stomper_suspend` | Clear, `nCurrent` kept |
| `0x0024bdb0` Resume | `stomper_resume` | Set `nCurrent` again |
| `0x0024bdc0` | `ResetRenderEggs` | Clear (BeginGameFlowUnloadingTrackSpecific) |
| `0x0024bf18` | `SetRenderEggFromEasterEggs` | the first of codes 0, 1, 2, 3, 4 and 8 that is on sets 8, 9, 10, 11, 9 or 12 (EndGameFlowLoadingTrackSpecific, not for a demo) |
| `0x0024bfc0`, `0x0024bfe0` | `SuspendRenderEggs`, `ResumeRenderEggs` | around the mirror and the HUD, each frame |
| `0x0024c000` | `DisableRenderEggs` | Clear and `bEnabled` 0 (the AI demo's InitForRace) |
| `0x0024c030` | `EnableRenderEggs` | `bEnabled` 1; nothing calls it |

Set does not clear the egg set before, and saves from the stack's start,
so a second Set overwrites the first's saves. `bEnabled` is read only by
RandomRenderEgg (`0x0024bde0`), which nothing calls. Each of the six
render-egg calls does nothing with no `pStomper`. `main.c` makes it and
binds the three that `trackflow.c` and `racecoord.c` call.

## The eggs

`StomperTable` (`0x0031d718`) holds 13 lists by eStomper. 1 to 7 are the
demo's (CARTOON to HOT_MAGENTA), set only by RandomRenderEgg: their slots
are an empty list in the port. The lists' floats are filled at boot by
`_GLOBAL_$I$StomperRenderEggs` (`0x0024c048`); the port's are initialised
data.

| eStomper | code | list | stomps |
| --- | --- | --- | --- |
| 8 | 0 Motion Blur | `0x0031d410` | `RadialBlurOnOff(bool, int)` (`0x0010f1f8`) with player 0 |
| 9 | 1 Black & White, 4 Video Mode | `0x0031d440` | `ForceBlackAndWhite` (gp-24048) 1 |
| 10 | 2 Heavy Fog | `0x0031d6a8` | `WeatherHeavyFog` (gp-19256) 1 |
| 11 | 3 R/C Car | `0x0031d508` | `CarRenderMatrix`'s diagonal 0.5, then the big head (`0x0031d4b0`): `OverrideAnimatedDriverLOD` 1, `ForceRenderDriver` 1, `nBoneScale` 15, `vBoneScale` 5.5 three times |
| 12 | 8 Chrome Cars | `0x0031d6c0` | `EnvPassAlphaA` .. `D` 2, 2, 1, 0, `EnvPassAlphaFix` 128 |

The suspend comes after the radial blur and before the mirror
(`0x00113a90`), the resume at the frame's end (`0x00113d7c`), after the
HUD's EndFrame: so the mirror and the HUD draw with every global as it
was. The port resumes at `trackview_draw`'s end, before the HUD, which
reads nothing the eggs stomp.

**Motion Blur.** RadialBlurOnOff has no `jal` caller in the image; the
list calls it through its pointer. On turns the player's view's blur on
(`radial-blur.md`), the edges at 160 and the centre at 0, and it returns
the player, which Clear hands back with 0 to turn it off. So each frame's
suspend turns the blur off after it is drawn, and the resume on again.

**Black & White.** `eAttachBlackAndWhite` (`0x0011a9f0`), the main
chain's last after the fog, with InGameFlag set: with ForceBlackAndWhite,
or either player view's word at `+116`, it reads the frame as PSMCT16 in
128 page passes of four eight-column sprites and writes it into a second
buffer through FBMSK `0x7fff`, so each pixel's alpha byte gets its
green's top seven bits. Then each player view, with the egg whatever it
is, or else Active with an Active target and its own `+116`, draws that
alpha back over itself as PSMT8H through SetupBlackAndWhite's grey ramp
(`0x0011a990`: entry i is `0x80000000 | i * 0x010101`, through
RemapLinearIntoClut8), unblended. The grey is the green. The mirror and
the HUD come after and stay in colour. Video Mode is the same egg, with
the HUD's group `0x06d1f9fb` (`easter-eggs.md`).

The view's `+116` is retail's NIS flag: `NisManager::EnableOverrideRendering`
(`0x001b1ce0`) sets it and `DisableOverrideRendering` (`0x001b24a8`)
clears it, so a NIS plays in black and white. The port's NIS player does
not have them yet, so `NisBlackAndWhite` stays 0 (`eview.h`).

**Heavy Fog.** WeatherManQuery (`0x001a84f0`) takes it before the
tweaker's and the regions: a fog of 0.957753, colour `0x00887062`,
starting at -1000 plus three slow sines of WorldTimeFrames, of 200, 150
and 100 (`weatherman.h`).

**R/C Car.** `CarRenderMatrix` goes into every car's world matrix
(`carrender.c`), so the cars draw at half size about their origin;
`ForceRenderDriver` draws the driver whatever the car's size on screen.
The big head's LOD and bones are AnimatedDriver's, which the port does
not have: they are poked and nothing reads them. The demo's list scales
the car 0.6, 0.7 and 1.1 instead and has no `ForceRenderDriver`.

**Chrome Cars.** Out of the frontend AttachDrawEnvironment (`0x0010ac50`)
builds the second context's ALPHA_2 from the five: by default
`(Cs - 0) * Ad + Cd`, the environment map added by the paint's alpha;
with the egg `(0 - 0) * Ad + Cs`, the map in place of the paint. The
frontend's ALPHA_2 is its own.

## On the 3DS

- **Black & White** is `trackview.c`'s `black_and_white`, after
  `georender_set_fog(NULL, 0)` and before `display_radial_blur`. It
  copies the top screen as the blur's last frame is (`copy_top_screen`:
  what is drawn so far sent, `GX_TextureCopy` into a 256 by 512 RGBA8
  texture, made at the egg's first frame and freed with the track), but
  read nearest, and draws it back over the screen with
  `georender_draw_green_quad`: the combiner takes the texture's green
  into all three colours, alpha 1, no blend. The 3DS has one player view.
- **Chrome Cars** is `georender_set_env_replace`, set in `begin_frame`
  when `EnvPassAlphaA == EnvPassAlphaB` and `EnvPassAlphaD == 0`: the
  environment pass then draws with the blend `(1, 0)`, the map alone,
  where it adds by default. The frontend's frame sets it off.
- The rest stomp globals the port already reads: the radial blur, the
  weather query and the car matrix.

The race's log line counts the grey frames: `race: radial blur N frames
blended, M failed; black and white N, M failed` (no copy, or no room in
the command buffer).

`EggCodes N` in `nfshp2_config.txt` turns codes on at boot by N's bits,
as entering them does: 1 Motion Blur, 2 Black & White, 4 Heavy Fog, 8
R/C Car, 16 Video Mode, 256 Chrome Cars. It is the port's own, off by
default, for checking an egg in an R-held race.

Seen in Azahar (2026-10-20), track 42 held at the gas: Black & White
(`EggCodes 2`) grey with the mirror and HUD in colour, upright, 101
frames, none failed; Chrome Cars (256) every car the environment map
alone, the lights and plates as they were; R/C Car (8) every car half
size and lit as before.

## The check

`tools/stomper_check.py` runs retail's StompEntry and Stomper code, the
six render-egg calls and WeatherManQuery's Heavy Fog in `tools/mipsemu.py`,
with bMalloc and `__builtin_delete` stubbed to log and RadialBlurOnOff
stubbed on both sides, against `tools/src/stomper_test.c`: the calls
before InitStomper, every egg on the first values and on junk, eggs out
of range, Set over Set, Suspend and Resume with and without an egg, the
codes, Disable and Enable, the weather query with the egg and the
tweaker, lists of the script's own (every type, nested, one global
twice, a type that is none, empty), a second Stomper and a long random
run.

    python tools/stomper_check.py           # 1524 ops, 1736 lines, 0 differ; 0 facts wrong
    python tools/stomper_check.py --mutate  # 92 mutations, 92 caught

`tools/radialblur_check.py` runs the real RadialBlurOnOff, on and off by
player, and what it returns (`radial-blur.md`).
