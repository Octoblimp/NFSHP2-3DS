# The preview comet

The glowing ribbon the Zone Preview draws along the road ahead while its
camera runs out and back: retail `0x001614c8` to `0x00161f90`, from
`zonecameras.cpp`, with its four params blocks filled by the static
initializer `_GLOBAL_$I$ZonePreviewCometParams` (`0x00167208`; the demo's
is `0x001629a0`, the same code). It is ported in `previewcomet.c`
(TASKS 80b). The Zone Preview's mover (`zonepreview.c`) owns one at
`+316`. The visible driving line (`VisibleDrivingLine`, not ported) owns
another and uses the other three params blocks.

## The params

`PreviewCometParams` is 208 bytes, the demo's `.mdebug` type#961. Retail's
initializer writes the same offsets.

| off | field | what |
| --- | --- | --- |
| 0 | `EmitterGroupName` | the effect group whose emitters ride the comet |
| 4 | `nPreviewCometSegments` | the ribbon's steps (see the loop) |
| 8 | `fPreviewCometTextureDV` | v scrolled per unit of t |
| 12 | `nPreviewCometTexture` | the texture's name hash |
| 16 | `fPreviewCometLineWidth` | the full width at a Width of 1 |
| 20 | `fPreviewCometLineHeight` | added to each corner's z |
| 24 | `fPreviewCometAltitude` | added to the spline point's z |
| 28 | `fPreviewCometLateralCoeff` | how far the ribbon banks per sideways pull |
| 32, 36 | `nPreviewCometWidths`, `vPreviewCometWidth[5]` | Width, over the ribbon (0 at the head end, 1 at the tail end) |
| 76, 80 | `nPreviewCometHeads`, `vPreviewCometHead[5]` | Head, over the run's t |
| 120, 124 | `nPreviewCometTails`, `vPreviewCometTail[5]` | Tail, over the run's t |
| 164 | padding | the `bVector4`s' alignment |
| 176 | `vPreviewCometColour0` | r, g, b, a at the head end |
| 192 | `vPreviewCometColour1` | the same at the tail end |

The four blocks follow each other at `0x002fa9f0`. The port keeps them as
plain C initializers, so nothing runs at startup.

| address | name | segments | texture | altitude | tail knees | Colour0 | Colour1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `0x002fa9f0` | `ZonePreviewCometParams` | 32 | `0x954c4637` | 0 | (0, -0.04) (0.5, 0.47) (0.95, 0.9) (1, 0.95) | 240 200 20 255 | 180 40 0 0 |
| `0x002faac0` | `DrivingLineCometParamsEasy` | 64 | `0x1fb22c32` | -1.25 | (0, -0.04) (1, 0.4) (0.95, 0.9) (1, 0.95) | 50 160 0 255 | 20 40 0 0 |
| `0x002fab90` | `...Medium` | 64 | `0x1fb22c32` | -1.25 | as Easy | 130 130 0 255 | 80 80 0 0 |
| `0x002fac60` | `...Hard` | 64 | `0x1fb22c32` | -1.25 | as Easy | 60 60 180 255 | 0 0 80 0 |

All four have the following in common:

- the group "ZONE_PREVIEW" (`0x002b2040`);
- DV -15;
- LineWidth 1.5, LineHeight 0, LateralCoeff 0.1;
- Width knees (0, 0.2) (0.05, 0.7) (0.1, 1) (0.5, 1) (1, 0.5);
- Head knees (0, 0.05) (0.8, 0.95) (1, 0.95).

The mover hands the constructor `0x002fa9f0` (`lui a2,0x30 ; addiu
a2,-22032`, `0x00162094`). `VisibleDrivingLine`'s constructor indexes a
table at `0x002fad30` of the other three, by difficulty.

## The comet

`PreviewComet` is 48 bytes, laid out from what the constructor writes. The
demo's type#2731 is 44 bytes: it has no flag at `+16` and its Graphs are
at `+20`.

| off | field | what |
| --- | --- | --- |
| 0 | `pLookSpline` | the caller's spline (the mover's look spline, `+108`) |
| 4 | `pParams` | the caller's params |
| 8 | `pEmitters` | `new AcidEmitter[n]`, or NULL |
| 12 | `nEmitters` | |
| 16 | `Enabled` | the emitters are on FrameEffects' auto list |
| 20 | `pCometTexture` | |
| 24, 32, 40 | `Width`, `Head`, `Tail` | Graphs over the params' knees |

## The calls

| retail | port | what |
| --- | --- | --- |
| `0x001614c8` constructor | `preview_comet_init` | builds the three Graphs and stores the spline and params; counts the group's emitter datas (`afxGetEmitterData(0, bStringHash(name), last)`, hashing again each time); with any, `new[]`s that many AcidEmitters ("ZonePreview Emitters", pool 16, a 16-byte cookie holding the count), constructs each inline (zeroes from `+8`, 184 bytes, and `NumAcidEmitters++`, gp-23516), then walks the datas again, giving each to the next emitter and turning it ON; then `Enabled = 0`, Enable, and `GetTextureInfo(nPreviewCometTexture, 1, 0)` |
| `0x00161678` destructor | `preview_comet_destroy` | Disable; with emitters, destroys each (`_$_11AcidEmitter`, flags 0) from the last, by the cookie's count, then `__builtin_vec_delete`s the block. The mover passes flags 2, so the comet itself is not freed |
| `0x00161720` | `preview_comet_enable` | unless already on, `AddAutoEmitter(&FrameEffects, e)` for each emitter; then the flag |
| `0x001617a0` | `preview_comet_disable` | unless already off, `RemoveAutoEmitter` for each; then the flag clear |
| `0x00161820` Render | `preview_comet_render` | the ribbon, below |
| `0x00189ad8` `Spline::GetSecondDerivative` | `spline_get_second_derivative` | below; only Render calls it |

The second walk over the datas is not bounded by the count. The two walks
see the same list, so it never overruns.

The emitters go on FrameEffects (`0x002ef5e0`), not WorldEffects. Each
frame drawn steps FrameEffects (eDisplayFrame's end), and the world being
frozen does not stop it, so the comet's sparks keep moving through the
preview.

Callers:

- the constructor, from the mover's constructor (`0x001620ac`) and
  VisibleDrivingLine's (`0x00174f30`);
- the destructor, from `0x0016369c` and `0x0017504c`;
- Enable, from the constructor, the mover's Enable (`0x00163998`) and a
  thunk at `0x00183208`;
- Disable, from the destructor, the mover's Disable (`0x001639b0`) and a
  thunk at `0x00183200`;
- Render, from the mover's Render (`0x001637b8`) and VisibleDrivingLine's
  (`0x001750ec`).

## The ribbon

`Render(view, t)` does not read the view. `t` is the run's progress: the
mover passes `fTime / (fOutTime + in)`, and only while that is at most 1.

1. **The matrix.** It takes 64 bytes of frame memory. If there is none
   left it sets FrameMallocFailed, adds 64 to FrameMallocFailAmount, and
   returns without drawing or moving anything. Otherwise the block is
   `bIdentity`, and each quad is drawn with it.
2. **The run's values.**
   - `head = Head(t)` and `tail = Tail(t)`, both fractions of the spline;
   - `step = (tail - head) / nSeg`;
   - `scroll = t * DV`, less its floor.
3. **The loop.** It runs for `i = 0, 2, 4, ...` while `i <= nSeg`. The
   image's counter is `i + 1` after the head's frame (`0x00161c20`,
   `0x00161cb4`) and goes up by one more at the loop's end (`0x00161f2c`).
   So the Zone Preview's 32 segments are 17 points and 16 quads. With an
   odd count the last point is never reached.
4. **Each point.**
   - The parameter is `u = end * (head + step * i)`. `end` is the
     spline's last parameter: `n` for a LOOP, `n - 1` for CLAMP and
     EXTRAPOLATE, 0 for any other type.
   - At `u` it reads the point P, the derivative D and the second
     derivative D2. P's z gets Altitude added.
5. **The frame.** It is all VU0 code. `norm` is `vrsqrt` (a zero length
   divides the EE's way, to FLT_MAX), and `x` is `vopmula/vopmsub`:
   - along `T = norm(D)`;
   - side `S = norm((0, 0, 1) x T)`;
   - `k = LateralCoeff * (D2 . S)`, so the ribbon leans into the curve;
   - up `U0 = S * k + (0, 0, 1)`;
   - side again, `S = norm(U0 x T)`;
   - up again, `U = norm(T x S)`.
6. **The emitters (first point only).** The emitters get the matrix
   `eIdentity`, with rows S, U, T and P (x, y and z each). Each emitter
   that is ON takes it while `t < vPreviewCometHead[1].x` (0.8 in all
   four blocks). Once t reaches that, the emitter is turned OFF instead,
   and nothing turns it on again. An emitter in any other state is left
   alone.
7. **The corners.**
   - `s = i / nSeg`;
   - `S *= LineWidth * (Width(s) * 0.5)`;
   - corner a is `P + S` and corner b is `P - S`, each z plus LineHeight;
   - both get `v = scroll + s`; u keeps the ePoly constructor's 0 and 1.
   - a and b start as 0 and 1 and are xored with 3 at each step. So a
     quad is always this point's pair (V0 and V1, or V3 and V2) and the
     last point's pair.
8. **The colours.**
   - Each channel is `cvt.w.s(rest * C0 + s * C1)`, with `rest = 1 - s`,
     stored as a byte. The values wrap, they do not clamp.
   - The alpha is multiplied by a fade first: 1 normally, but
     `1 - (t - x) / (1 - x)` once `t >= x` (x the same head knee).
   - Corner b copies corner a's bytes.
9. **The draw.** From the second point on, each quad goes through
   `ePoly::Render3D(&poly, texture, matrix, 0)`. Then comes the ePoly
   destructor.

The ribbon starts at the head (ahead on the road) in Colour0 at Width 0.2
and runs back to the tail in Colour1. The Zone Preview's comet is an
opaque yellow head fading to a clear red tail, and the texture scrolls
along the ribbon as t runs. Up to t = 0.8 the head runs from 5% to 95% of
the look spline. After that the whole ribbon fades out, and the sparks
stop where they are.

## Spline::GetSecondDerivative

`0x00189ad8` (`spline.cpp`; the demo's is `0x00181aa8`). It takes
`u = t - floor(t)` and calls `Evaluate(floor(t))` with the second
derivatives of the Catmull-Rom weights:

- `(u * -6 + 4) * 0.5`
- `(u * 18 - 10) * 0.5`
- `(u * -18 + 8) * 0.5`
- `(u * 6 - 2) * 0.5`

These are in the image's order, each halved last. It lives in
`previewcomet.c` until `spline.c` takes it.

## The textures

Both are in `GLOBAL/INGAMEB.BUN`, the race's pack:

| hash | name | size | flags |
| --- | --- | --- | --- |
| `0x954c4637` | ZONE_PREVIEW_RIBBON | 64 by 128, 4-bit | order 5, ApplyAlphaSorting, semitransparent, AlphaBits `0x48`, no Z write, TilableUV 3 |
| `0x1fb22c32` | COMET_RIBBON | 64 by 128, 4-bit | the same, but TilableUV 0 |

AlphaBits `0x48` is `(Cs - 0) * As + Cd`: an additive glow, faded by the
vertex alpha.

## On the 3DS

Nothing beyond `gEPolyRender3DFn` is needed. `trackview.c`'s
`render_epoly_3d`, the light flares' and skids' seam, takes each quad as a
strip of V0, V1, V3 and V2 in the matrix's space:

- **Texture.** `load_texture` loads it.
- **Blending.** `texture_pass` turns `0x48` into `GEO_BLEND_ADD`. The
  texture is semitransparent, so there is no alpha test.
- **Depth.** `bWriteZ` 0 gives no depth write.
- **Ordering.** ApplyAlphaSorting puts each quad on the sorted list by
  V0's view z, so sorted quads are never joined.
- **Wrap.** ZONE_PREVIEW_RIBBON repeats in v, from TilableUV.

The strip copies the matrix, so the frame-memory block may go at the
frame's end. The mover's Render has to run while the track view is
drawing. `trackview.c`'s `render_camera_movers`, between the skids and the
world objects, is where RenderCameraMovers runs on the PS2.

## The check

`tools/previewcomet_check.py` runs retail's constructor, destructor,
Enable, Disable and Render in mipsemu, with the Graph, Spline, ePoly,
bIdentity, eIdentity, bStringHash and bMemSet code under them. It runs the
static initializer over poisoned memory. It diffs all of that against a
host build of `previewcomet.c` (`tools/src/previewcomet_test.c`).

Stubs on both sides print what they get:

- bMalloc (its size in retail's 192-byte emitters), and the deletes;
- afxGetEmitterData, which answers from a scripted group;
- SetEmitterData and the emitter destructor;
- Add/RemoveAutoEmitter, naming the system;
- GetTextureInfo;
- `Render3D`, printing every vertex, UV, colour, the poly's flags, the
  matrix's place and its 16 floats.

The model passes Render a view outside RAM, to show it is never read.

The deterministic script covers:

- the four blocks, word for word;
- splines of every type, including one point five times over and a climb
  straight up;
- the Zone Preview's comet through a run, from t = 0 past the knee to 1.1;
- emitters ON, OFF and in other states;
- every Enable and Disable, including the no-op ones;
- frame memory of exactly 64 bytes (fails) and 65 (draws);
- no emitters, no texture, no segments, one segment;
- colours past a byte;
- short, unsorted and empty knee lists.

Then 40 cases at random. Image facts checked:

- every function's callers;
- the mover's params address;
- the driving line's table;
- FrameEffects in Enable and Disable;
- NumAcidEmitters and the frame memory's gp words;
- new[]'s name;
- the initializer's `__CTOR_LIST__` entry.

Kept out of the script: nSeg 0 and a head knee at x = 1, the two
divisors. The game's are 32 or 64, and 0.8. The port divides as C does
(infinity), not as the EE does (FLT_MAX).

    python tools/previewcomet_check.py           # 534 steps, 12442 lines, 0 differ; 14 facts
    python tools/previewcomet_check.py --mutate  # 97 mutations, 95 caught, 2 equivalent
