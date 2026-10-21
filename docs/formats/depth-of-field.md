# The depth of field

TASKS 84, in progress. This page holds what retail's code does, read on
2026-10-21. The port draws none of it yet; the plan for the 3DS is at the
end.

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

## Retail's 16x mismatch

The frame's alpha from eAttachDepthIntoAlpha is `Z >> 8`, or 255 past
`0xffff` (weather_check's GS run, `weather-fog.md`). The focus palette
is built as if entry i stood for Z `i << 12`. The two are 16 apart:

- with near 0.5, entry i is about 1024 / i m away, and a pixel D m away
  gets alpha about 16384 / D for D of 64 m or more, else 255, the entry
  for 4 m;
- so everything nearer than about 64 m takes the 4 m entry's verdict,
  and a farther pixel is judged as if it were 1/16 as far.

In the chase view (focus 15, depth 65) t0 is 0 and t1 is 234 (index
21): sharp out to about 780 m, then the ramp, and index 0 (the sky,
Z = 0) gets 112 of 128. The close-up cameras whose band leaves out 4 m
blur everything within 64 m, the car they look at too. That is the game
as shipped; the demo was consistent (alpha `min(Z >> 6, 0xfc)` and a
shift of 10). The port will do what retail does: the palette by retail's
code, looked up by `efog_depth_alpha`.

## The 3DS plan (not built yet)

- `efog.c/.h` (or a new `efocus.c`) gets the helpers, GetFocusPalette,
  CreateFocusPalette and eAttachDepthOfField's control flow, with a seam
  `gEDofAttachFn(view, palette)` as the fog has; `tools/` gets a mipsemu
  checker in the pattern of `weather_check.py`.
- `trackview_draw` makes the palette with the fog's frame and draws the
  blur after the scene's alpha lists, before black and white, so the
  mirror and the HUD stay sharp as on the PS2.
- The draw: `copy_top_screen` into a texture; two jittered quads into a
  half-size render target (half across only, 256 x 256, matches retail's
  blur size on the 400 x 240 screen; retail's +2, +2 PS2 pixels are about
  +1.56, +1.07 here), averaged; back on the top target, a few full-screen
  quads of the half texture at fixed depths from `depth_of_gs_z`, depth
  tested, each at a constant alpha, as steps of the palette's alpha by
  index (far entries and near entries).
- Not chosen: reading the depth buffer as a texture (a non-power-of-two
  texture and 8-bit combiner sums) and GX_DisplayTransfer's scaling from
  tiled to tiled (unproven).
- The cost to watch: the 384 KB copy, the half pass (about 96k pixels)
  and each layer (about 96k pixels). A race has about 13 MB of linear
  heap free (13,146 KB in the last Azahar log).
