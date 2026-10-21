# The depth of field

TASKS 84. This page holds what retail's code does, read on 2026-10-21,
and how the port draws it on the PICA (the last part). The port's code is
`3DS Files/source/efocus.c` and `trackview.c`'s `depth_of_field`; the
cross-check is `tools/dof_check.py`.

The depth of field is the last piece of `EcstasyE.obj`'s attaches, after
the fog (`docs/formats/weather-fog.md`). Each frame retail blurs what is
out of the camera's focus, by each pixel's depth. The functions are
retail's (`SLES_507.31`):

| Address | Function |
|---|---|
| `0x00119b28` | `GetFocusPalette(eView *)` |
| `0x00119b58` | `MapScreenZToPaletteIndex` |
| `0x00119b70` | `MapPaletteIndexToScreenZ` |
| `0x00119b90` | `MapScreenZToViewZ` |
| `0x00119bd8` | `MapViewZToScreenZ` (not used by the depth of field) |
| `0x00119c20` | `CreateFocusPalette(eView *, unsigned *)` |
| `0x00119f70` | `eAttachDepthOfField(eDmaChain *, a1, a2)` |

eDisplayFrame's chain (`0x001138ac`) runs depth into alpha, the fog, then
the depth of field. Black and white (`0x00113900`) and the radial blur
(`0x00113a54`) come after, then the rear-view mirrors (DisplayRVMs,
`0x00113af4`) and the HUD, so neither is blurred.

## The globals

Retail's GP is `0x003358f0`. The values are the image's.

| GP offset | Address | Global | Value |
|---|---|---|---|
| -24136 | `0x0032faa8` | `DrawDepthOfField` | 1 |
| -24132 | `0x0032faac` | `FocusPrintPalette` | 0 |
| -24128 | `0x0032fab0` | `FocusAlphaMin` | 0.0 |
| -24124 | `0x0032fab4` | `FocusAlphaMax` | 128.0 |
| -24120 | `0x0032fab8` | `FocalDistance` (an override, 0 = the camera's) | 0 |
| -24116 | `0x0032fabc` | `DepthOfField` (an override, 0 = the camera's) | 0 |
| -24112 | `0x0032fac0` | `JitterBlend` | 64 (the demo's is 27) |
| -24108 .. -24092 | | `AddaA`, `AddaB`, `AddaC`, `AddaD`, `AddaF` | 0, 0, 0, 1, 128 |
| -24088 .. -24072 | | `FocusA`, `FocusB`, `FocusC`, `FocusD`, `FocusF` | 0, 1, 1, 1, 128 |
| -24068 | | the number of jitter samples (retail only) | 2 |
| -24064, -24060 | | the upsample's X and Y offsets | `0x4008` each (-0.5 px) |
| -24056 | `0x0032faf8` | the ramp's length in entries | 24 |
| -24052 | `0x0032fafc` | the first "previous" distance | -FLT_MAX |

The Adda blend keeps the RGB and writes the palette's alpha. The Focus
blend is (Cs - Cd) * Ad / 128 + Cd: a lerp from the sharp frame to the
blur by the destination's alpha.

The jitter table at `0x002da750` holds (x, y) pairs in sixteenths of a
texel: (0, 0), (32, 32), (32, 0), (32, 32), (0, 32), (0, 0). With two
samples retail takes (0, 0) and (+2, +2) PS2 pixels.

## The helpers

`ZRanges[1]` (`0x002c9e20` + 24) is the race's range: `ZMin` bits
`0x40000010` (2.0000038), `ZMax` 4.0.

- `GetFocusPalette` returns `FocusPalettes[ID - 1]` for views 1 to 4,
  else NULL. `FocusPalettes` is at `0x002db380`, `FogPalette` + 3072,
  1,024 bytes each.
- `MapScreenZToPaletteIndex(z)` is `(bits(z) >> 12) & 0xff`.
- `MapPaletteIndexToScreenZ(i)` is the float with the bits
  `bits(ZMin) | (i & 0xff) << 12`.
- `MapScreenZToViewZ(near, far, sz)` is
  `(near * far * (ZMax - ZMin) / (far - near)) / (sz - (ZMin * far - ZMax * near) / (far - near))`.

The demo used `ZRanges[0]` and a shift of 10.

## CreateFocusPalette

```c
if (!view || !palette) return 0;
near = view->NearZ; far = view->FarZ;               // +12, +16
dof = cam->DepthOfField; focal = cam->FocalDistance; // pCamera +56: +120, +116
for (i = 0; i < 256; i++)                           // d[] rises with k
    d[255 - i] = MapScreenZToViewZ(near, far, MapPaletteIndexToScreenZ(i));
f = FocalDistance ? FocalDistance : focal;
w = DepthOfField ? DepthOfField : dof;
if (w == 0 && f == 0) { bMemSet(palette, 0, 1024); return 0; }
range = FocusAlphaMax - FocusAlphaMin;
nearEdge = f - w * 0.5; farEdge = f + w * 0.5;
t0 = 0; t1 = 255; prev = -FLT_MAX;
for (k = 0; k < 256; k++) {
    if (prev < nearEdge && nearEdge <= d[k]) t0 = k;
    if (prev < farEdge  && farEdge  <= d[k]) t1 = k;
    prev = d[k];
}
max = (int)FocusAlphaMax << 24 | 0x808080;
min = (int)FocusAlphaMin << 24 | 0x808080;
for (k = 0; k < 256; k++) lin[255 - k] = (k < t0 || k > t1) ? max : min;
for (a = 1; a < 24; a++) if ((unsigned)(t0 - a) < 256)
    lin[255 - (t0 - a)] = (int)(FocusAlphaMin + (float)a / 24 * range) << 24 | 0x808080;
for (a = 1; a < 24; a++) if ((unsigned)(t1 + a) < 256)
    lin[255 - (t1 + a)] = (int)(FocusAlphaMin + (float)a / 24 * range) << 24 | 0x808080;
if (FocusPrintPalette) { /* 256 index-to-Z calls, the print stripped */ FocusPrintPalette = 0; }
RemapLinearIntoClut8(palette, lin);
return 1;
```

Both ramps rise from the edge outwards the same way, so an entry just
past the far edge gets a little blur and one 23 past it nearly the full
128. Note that the near ramp is written the same way: an entry just in
front of the near edge also gets the small blur, rising to near full
23 entries nearer.

## eAttachDepthOfField

- If `DrawDepthOfField` is 0, return 0.
- Views 1 and 2: for each active view (`+4`), GetFocusPalette and
  CreateFocusPalette; the palette goes up as a CLUT
  (AttachImageDataPacket). If no view's palette came back 1, return 0.
- Per active view with a palette, pass 1 draws the view's rectangle: it
  reads the buffer at gp-24920's target `+40` as PSMT8H (its alpha as an
  8-bit index) through the focus CLUT, and writes the frame at
  gp-24912's target `+40` with the Adda blend, so each pixel's alpha
  becomes its blur amount. ATST NEVER with AFAIL FB_ONLY, ZTST ALWAYS,
  the Z buffer masked.
- The blur: a half-size buffer (FRAME at `a1`, width / 2) is cleared to
  black with FBA 1. Two jitter passes draw the full frame into it with
  bilinear filtering (TEX1 `0x61`), in 32-pixel source strips to 16-pixel
  destination strips, added at `JitterBlend` / 128 each (64: half each,
  so the two average).
- The last pass stretches the half buffer back over the full frame,
  bilinear, with the Focus blend, so each pixel goes from sharp to the
  blur by the alpha pass 1 wrote. XYOFFSET is 1024.5.
- Return 1.

eAttachFog (`0x001197ac`) reads the same gp-24920 buffer, the one
eAttachDepthIntoAlpha (`0x00118a60`, `lw s6,-24920(gp)` at `0x00118ad4`)
fills with the depth's alpha.

## The cameras' focus

| Camera | Focal distance | Depth of field |
|---|---|---|
| drivecam (the chase view) | 15 | 65 (0 with PerfectFocus) |
| trackcarcam | dist + 2 * val | 7.5 |
| trackflycam | dist, at least 2 | 30 |
| bumpercam | dist, at least 2 | 7.5 |
| orbitcam | Radius | 8 |

The player's own chase view has PerfectFocus: ChangeCameraMover
(`0x00176ae8`) builds its DriveCameraMover with the last argument 1
(`addiu t2,zero,1` at `0x00176c58`). Its focus and depth stay 0, so
CreateFocusPalette clears the palette and eAttachDepthOfField returns 0:
a race behind the car is never blurred. The other cameras set a focus:
the camera coordinator's drive camera (perfect focus off,
`camera-coordinator.md`) in attract mode and the replays, the fly-bys and
the close-ups.

## Retail's 16x mismatch

The frame's alpha from eAttachDepthIntoAlpha is `Z >> 8`, or 255 past
`0xffff` (weather_check's GS run, `weather-fog.md`). The focus palette
is built as if entry i stood for Z `i << 12`. The two are 16 apart:

- with near 0.5, entry i is about 1024 / i m away, and a pixel D m away
  gets alpha about 16384 / D for D of 64 m or more, else 255, the entry
  for 4 m;
- so everything nearer than about 64 m takes the 4 m entry's verdict,
  and a farther pixel is judged as if it were 1/16 as far.

In a drive camera with a focus (15, depth 65) t0 is 0 and t1 is 234
(index 21): sharp out to about 780 m, then the ramp, and index 0 (the
sky, Z = 0) gets 112 of 128. The close-up cameras whose band leaves out
4 m blur everything within 64 m, the car they look at too. That is the
game as shipped; the demo was consistent (alpha `min(Z >> 6, 0xfc)` and
a shift of 10). The port does what retail does: the palette by retail's
code, looked up by the depth as the PS2's index (the last part).

## The 3DS pass

TASKS 84b, built 2026-10-21.

- **The code.** `efocus.c` has the helpers, GetFocusPalette,
  CreateFocusPalette and eAttachDepthOfField's control flow. Its seams
  are `gEDofAttachFn(view, palette, band)`, where the image builds a
  view's pass, and `gEDofBlurFn`, where it builds the blur.
  `trackview.c`'s `fog_frame` runs it after `eattach_fog`, inside the
  same test. View 1's palette becomes a plan (`efocus_plan`) before the
  draws. `depth_of_field` draws the plan after the scene's alpha lists
  and before black and white, the radial blur, the mirror and the HUD, so
  those stay sharp as on the PS2.
- **The frame's alpha.** `GX_TextureCopy` copies the D24S8 depth buffer
  into a 256 x 512 linear texture, read as RGBA8. There G is the depth's
  top byte and B its middle byte. In player 1's Z range (16 to
  `0x800000`) the PS2's index, `Z >> 8`, is `128 G + B / 2` for G of 0
  and 1, and 255 past them. So up to three full-screen quads write the
  frame's alpha, with only the alpha written:
  - one with the depth test ALWAYS, for G 0;
  - one at the constant depth 1/256, with LEQUAL, for G 1;
  - one at 2/256, also LEQUAL, for G of 2 and up.

  Each quad is a constant, or the palette's two ramps about the band's
  edges, made in the combiners (`EFocusStep`, `efocus.h`). The plan
  merges the last two quads where they are the same.
- **The blur.** The colour is copied the same way and read bilinear.
  Each jitter sample goes into a 256 x 256 target in VRAM, half across as
  retail's, at JitterBlend 64 by 2, so 0.5 each. The first sample
  replaces and the next adds. Retail's jitter of (0, 0) and (2, 2) PS2
  pixels is (0, 0) and (1.56, 1.07) here. Then the target is laid over
  the frame by the frame's alpha (DST_ALPHA), writing RGB only.
- **The approximations.** `dof_check.py` tests them all with its bound:
  for each depth from 0 to `0x20400`, and at the far ends, the PICA's
  alpha must be within 2 of 255 of the palette's alpha at the pixel's
  index or a neighbour.
  - The index from B / 2. On the PS2, the ZMin's 16 and a low byte of 224
    or more carry an odd B into the next index. The port takes the index
    B / 2 gives, at most one entry off.
  - The combiners are 8-bit, and each product is taken down: within 2 of
    255.
  - The quads' depths are floats, so a region's edge may be one d24 unit
    off.
  - A FocusRampLength under 1 is a step. Its slope is 256 where retail's
    is 255, which gives the same alphas.
  - Each jitter sample is stretched by its offset so that its right and
    bottom edges are the frame's. Past those edges the copy's texture
    holds what the copy left. The stretch is at most 1.56 of 400 across
    and 1.07 of 240 down.
  - A view in another Z range is left sharp, and counted as failed. The
    3DS draws only view 1.
- **The cost.** Two 512 KB copies in linear memory and the 256 KB target
  in VRAM, made at the first frame that blurs and freed with the track.
  Each frame takes two copies, up to three alpha quads, two half quads
  and the full-screen lay. The debug log's "race:" line counts the
  frames: "depth of field N, M failed".
- **Seen.** In Azahar's attract demo, every frame blurred (1,214 drawn,
  0 failed) and the frame rate held at 30 FPS. The drive camera kept the
  near scenery sharp and softened the sky. The close-ups blurred the car,
  as retail's 16x mismatch does. A SkipFE race drew none, as retail does
  behind the player's car. It has not been run on a 3DS yet.
