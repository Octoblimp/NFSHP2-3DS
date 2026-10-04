# The draw's cuts (step 13b-4)

What step 13b-4 takes out of the race's draw, and why each cut leaves
the picture as it was. The profile (`frame-profiler.md`) picks the
order. 13b-4a to 13b-4c have no retail function behind them: the PS2
drew through VU1 and the GS, and those cuts are in how the port feeds
citro3d. 13b-4d draws the Flailer layers the way retail's
LayerRenderInfoTable does.

## What a model costs

13b-3's profile on Azahar put the models' render first, at 12.6 to 17.8
ms of a 50 ms frame. The `models:` line (since 13b-4, after each
`frame:` line) counts what `render_model`, eModel::Render, draws:

    models: view 311 models, 1070 batches at once, 22 lit, 74 held,
    103104 words; envmap 96 models, 477 batches at once, 0 lit, 70 held,
    40143 words

- **view** is the player's view, and **envmap** the faces the envmap
  drew that frame, three of the six (`light.md`).
- **batches at once** are those `georender_draw_mask` draws in the
  model's own call. **lit** batches draw alone, each with its light.
  **held** ones go on the lists for later (sorted, or of a later
  rendering order).
- **words** are the GPU command words written, from `gpuCmdBufOffset`.

A first build also timed `render_model`'s parts with the system tick.
That cost 5 ms a frame, since a tick read is an SVC, so the line keeps
only the counts. What it showed: `georender_draw_mask` was 16.7 of the
21.5 ms the models took in that build. The solid's lookup and the
batches' flags were 3 ms together.

**One model's commands.** A one-run diagnostic dumped the words of one
model, a redwood with six batches, and decoded them (454 words):

| What | Words | Sent |
|---|---|---|
| the uniforms: the projection, the model-view, the light, the ambient, the fog's row | about 60 | each model |
| the vertex buffer (citro3d writes all twelve slots) | 40 | each model |
| the attributes, the cull mode, and the depth, alpha and blend state | about 30 | each model |
| texture unit 0 | 16 | each batch |
| the combiner's stage 0 | 6 | each batch |
| the ST scale, (1, 1) for nearly every texture | 8 | each batch |
| the draw | 22 | each batch |

Only the model-view, the vertex buffer, the texture and the draw change
between one model's batches, or from one model to the next. Everything
else was sent again because georender set its whole state for every
model and every batch.

## 13b-4a: georender's runs

`georender_run_begin` and `georender_run_end` bracket a run of draws
with nothing else drawn between them. `trackview.c` makes each
eModel::Render loop one run: `scenery_stuff_scenery` for the player's
view, and for each envmap face. In a run, georender sends:

- the program, the attributes, and the projection, light, ambient and
  fog-row uniforms, once, and again only if the projection changes;
- the cull mode once;
- the pass (blend, depth write, alpha test) only when the next batch's
  differs from the last one sent;
- the combiner's stage 0 and the ST scale only when they differ;
- texture unit 0 only when it is another texture.

The model-view, the vertex buffer and the draw go for every model and
batch, as before (13b-4b cuts the first two).

**Why the picture is the same.** Each skipped write would have set a
register to the value it already held. Nothing else draws inside a run,
so nothing else can change those registers. Anything that could is a
reason to forget:

- a lit batch binds geolit's program, whose uniforms and constants use
  the same registers, and the environment pass binds the sphere map;
- `georender_set_light`, `_set_fog`, `_set_depth_range` and
  `_set_zwrite` change what the next draw would send.

Each of these clears what the run has sent, so the next draw sends its
whole state. Outside a run, every draw sends its whole state, as
before.

**On Azahar** (track 12, holding the gas; `out/azahar_13b4b`, with
13b-3's `out/azahar_13b3b` before it):

| | 13b-3 | 13b-4a |
|---|---|---|
| models | 16.4 to 17.8 ms | 12.1 to 13.8 ms |
| envmap | 7.8 to 10.0 ms | 6.7 to 8.6 ms |
| the draw | 44 to 46 ms | 39.6 to 40.6 ms |
| the view's words a frame | 103,000 | 63,000 |
| the envmap's | 40,000 | 24,000 |
| frames | 50.1 ms, 20 FPS | 50.1 ms, 20 FPS |

The counts are the same in both runs: 310 to 375 models and 1,060 to
1,100 batches in the view. The frame is still three blanks, 50 ms,
because the frame's CPU is still over 33 ms. The shots match 13b-3's:
the scenery, the textures, the sun, the car and its reflection
(`out/13b4a_before_after.png`). The pixels differ only by the race's
timing, a speed of 56 against 54.

## 13b-4b: a mesh's buffer as one register

Every mesh's vertex buffer has the same layout: one buffer, 32-byte
vertices, four attributes in the order 0x3210. citro3d's `BufInfo`
sends all twelve buffer slots, 40 words, for each one. What changes
from one mesh to the next is only where its buffer starts.

So, in a run, `bind_mesh` sends citro3d's buffers once. After the
draw that sends them, a mesh's buffer is one write of
`GPUREG_ATTRIBBUFFER0_OFFSET`, its physical address less the base
that citro3d sent. The model-view goes only when it differs from the
last one sent.

**Why the picture is the same:**

- **The offset's register.** citro3d sends a `BufInfo` the next time
  something draws, so a write of the offset before that draw would be
  overwritten. The run counts the buffers as sent only after
  `draw_batch` has drawn, so a first mesh whose batches are all held
  for later gets citro3d's whole `BufInfo` again on the next mesh.
- **citro3d's copy.** It still holds the run's first mesh. At
  `georender_run_end`, `C3D_GetBufInfo` marks it changed, so citro3d
  sends it whole before the next draw and the GPU's matches it.
  `run_forget` (a lit batch, the fog, the light) does the same through
  `bind_mesh`'s full path.
- **The model-view.** citro3d keeps the uniforms it was given, so one
  left as it was still holds the value the GPU has.

**On Azahar** (`out/azahar_13b4c`): the view's words go from about 200
a model to 164 (50,500 for 308 models, from 61,800), and the envmap's
from 220 to 190. The models take 11.8 ms on average (7.4 to 13.4)
against 13b-4a's 12.1 to 13.8. The shots match 13b-4a's, apart from
where the car drove. In shot 3 it ran into the roadside ferns, which
draw in front of it.

## 13b-4c: citro3d's uniform upload, skipped when nothing changed

After 13b-4b a model costs about 160 words, and most batches send only
their texture and the draw. The models still took 9 to 13 ms. The
cost was no longer the words. It was the draw itself.

`C3D_DrawArrays` calls `C3Di_UpdateContext`, which ends with
`C3D_UpdateUniforms` for the vertex shader and again for the geometry
shader. Each call tests the 96 float uniforms' dirty bytes one at a
time, then the integer and bool ones, which is about 600 instructions
(disassembled out of `libcitro3d.a`). That is 1,200 for every draw,
even with nothing to send, and the port has no geometry shader. A race
frame has two thousand and more draws.

`c3dwrap.c` is linked with `--wrap` (the Makefile's `C3DWRAP`), so
`base.o`'s calls go through it:

- `__wrap_C3D_UpdateUniforms` reads the public dirty flags
  (`C3D_FVUnifDirty`, `C3D_IVUnifDirty`, `C3D_BoolUnifsDirty`) a word
  at a time. It calls citro3d's function only if one is set.
- A shader's own constants have a dirty flag local to `uniforms.o`
  (`C3Di_ShaderFVecData`). The two functions that set it,
  `C3Di_LoadShaderUniforms` (from `C3D_BindProgram`) and
  `C3Di_DirtyUniforms`, are called from `base.o`. Their wrappers note
  that constants may be waiting, and the next upload calls citro3d's.

**Why the picture is the same.** Whenever anything is waiting,
citro3d's own function runs with its own flags, so it sends exactly
what it would have sent. The wrapper skips a call only when that call
would have sent nothing. The `models:` line's words agree: 50,588 for
306 models, as 13b-4b's 50,523 for 308.

**On Azahar** (`out/azahar_13b4d`): the models take 9.2 ms on average,
from 11.8, and the envmap 6.3, from 7.8. The draw is 35.0 ms, from
39.2. The frame stays at 50 ms. The HUD and the bottom screen are
unchanged at 4.7 and 5.4 ms, so their cost is elsewhere.

## 13b-4d: the Flailer layers from one walk

Retail draws the Flailer screens from a table of 29 layer lists.
AddFlailerStrip (`0x00143990`) appends each visible object's strip to
`LayerRenderInfoTable[Z]`, and RenderLayer (`0x00143a68`) walks one
list in that order. The port walked every visible screen's objects
once for each of the 29 layers. Each time it unpacked the whole object
(`bui_object`: a memset and some thirty fields) only to compare its Z.
That made a frame's two Flailer stages 4.7 and 5.4 ms.

`uirender.c`'s `draw_visible` builds the lists as retail does, in one
walk. `bui_object_layer` reads only an object's Visible and Z bytes,
and each visible object goes on its Z's list, in bundle, screen and
file order. Then the layers are drawn in `BUI_LAYER_ORDER`, each from
its list. The draw is `draw_object`, the old loop's body, which
unpacks the object and checks it as before. Past 1,024 objects
(`UIR_LAYER_ITEMS`) the walk goes a layer at a time, as it did.
`uirender_draw_screen`, for one screen, keeps the old walk.

**Why the picture is the same.** Each layer draws the same objects in
the same order: bundles, then screens, then the file's order. Drawing
does not change an object's Z or visibility.

**On Azahar** (`out/azahar_13b4e`): the HUD takes 0.3 ms, from 4.7,
and the bottom screen 0.9, from 5.4. Both screens match 13b-4c's shots:
the tachometer, the gear and the speed on top, and the player's panel,
the lap times and the minimap below.

## Where 13b-4 stands

On Azahar, track 12, holding the gas, the mean of each second's line
over a run of about 25 seconds:

| | 13b-3 | 13b-4a | 13b-4b | 13b-4c | 13b-4d |
|---|---|---|---|---|---|
| models | 16.4 to 17.8 | 12.1 to 13.8 | 11.8 | 9.2 | 9.3 |
| envmap | 7.8 to 10.0 | 6.7 to 8.6 | 7.8 | 6.3 | 6.3 |
| cars | 4.4 to 4.6 | 4.4 | 4.4 | 4.3 | 4.3 |
| hud | 4.7 to 4.8 | 4.8 | 4.8 | 4.7 | 0.3 |
| bottom | 5.3 to 5.4 | 5.4 | 5.4 | 5.4 | 0.9 |
| the draw | 44 to 46 | 39.6 to 40.6 | 39.2 | 35.0 | 26.1 |
| the frame | 50.1 ms | 50.1 ms | 51.1 ms | 50.6 ms | 34.2 ms |
| FPS | 20 | 20 | 19.6 | 19.8 | 29.2 |

After 13b-4d, the seconds run from 27.9 to 30.0 FPS: frames of 33.3 ms,
two blanks, with some of three. The CPU's frame is about 29 ms: the
draw is 26.1 and the world 1.4 to 3.7. Where a second's models or
world run long, a frame passes 33.3 ms and takes three blanks.

Azahar runs the CPU at 268 MHz, about an instruction a tick. A New 3DS
runs at 804 MHz with its L2 cache, so the same work should take well
under these times there. Only a New 3DS's `frame:` lines can say how
much. On Azahar, what is left to cut is the models (9.3), the envmap
(6.3), the cars (4.3) and the cull (2.7).
