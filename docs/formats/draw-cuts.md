# The draw's cuts (step 13b-4)

What step 13b-4 takes out of the race's draw, and why each cut leaves
the picture as it was. The profile (`frame-profiler.md`) picks the
order. 13b-4a to 13b-4c have no retail function behind them: the PS2
drew through VU1 and the GS, and those cuts are in how the port feeds
citro3d. 13b-4d draws the Flailer layers the way retail's
LayerRenderInfoTable does. 13b-4f is the first cut for the device's
GPU rather than the CPU: indexed meshes.

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
- **indices** (since 13b-4f) are the batches' indices, three a
  triangle, the held ones' too.

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

## 13b-4e: the strips' flushes, and the last runs

The cars stage was 4.3 ms for one car. A probe build timed its parts
with `svcGetSystemTick`: RenderCars 1.5 ms, the solid list 0.1, and the
alpha list 2.7. In the alpha list, 27 strips took 2.33 ms, 86 µs each,
against about 20 µs for a held batch. A strip is eBeginStrip's
vertices, here the car's shadows and the road's strips.

`georender_draw_strip` copied each strip into its ring and called
`GSPGPU_FlushDataCache` on it, as `draw_screen_quad` did for each quad.
That is a request to the GSP service each time. Neither is needed.
`C3D_FrameEnd(0)` flushes the whole linear heap
(`__ctru_linear_heap`, `__ctru_linear_heap_size`) after it queues the
frame's commands and before `gxCmdQueueRun` starts them. Both rings are
`linearAlloc`'d, and every `C3D_FrameEnd` in `main.c` passes 0. With
the flushes gone, the 27 strips take 0.68 ms.

The same step brackets the sky, the scenery's solid list and the cars'
chain with `georender_run_begin` and `_run_end`, as 13b-4a did the
models. Every path that sets citro3d's state itself forgets the run
first: the screen quads, the strips, the lit batches and the envmap's
fold. `georender_draw` sets its own depth test, so it clears the run's
pass. That saved 0.5 ms (`out/azahar_13b4f`: the draw 25.6).

**Why the picture is the same.** The GPU reads the same vertices: the
flush still comes before the GPU runs the frame, only once and for the
whole heap. The runs send the same state, only not twice.

**On Azahar** (`out/azahar_13b4g`): the cars stage takes 2.6 ms, from
4.3; the scenery's 0.5, from 1.1, with the sun's quads; and the bottom
screen 0.5, from 0.9, with the minimap's. The shots match 13b-4d's: the
sun and its glare, the car's shadow, and the road's strips.

## 13b-4f: indexed meshes

Session 36's timing frames on the New 3DS XL split the models' list (895
draws) like this:

| What | GPU ms |
|---|---|
| the texture fetch | about 6.5 |
| the fill, the fetch included | about 10.2 |
| the vertex work | about 7.5 |
| each draw's own cost, all of them | about 1.44 |
| the texture cache clears | about 0.35 |

With 200 to 380 models in view the GPU takes 43 to 47 ms a frame. Of
these, only the vertex work can be cut without changing a pixel.

**What the strips are.** TRACKB12 has 133,795 triangles in 10,394
strips, 12.87 triangles and 22.88 vertices a strip. Most strips are runs
of separate quads, cut by the ADC bit's restarts, so a strip shares
little with itself. The vertices the GPU fetches and shades:

| Drawn as | Vertices |
|---|---|
| a triangle list (13b-3 to 13b-4e) | 401,385 |
| GPU strips joined by degenerate triangles | 335,909 |
| an indexed list, each distinct vertex once a solid | 176,505 |

The PICA's post-vertex cache then shades once a vertex that the last
few triangles shared. Simulated as first in, first out, in the strips'
order, it shades this many vertices a triangle:

| Cache entries | Vertices shaded a triangle |
|---|---|
| none (the list) | 3 |
| 4 | 1.70 |
| 8 | 1.62 |
| 16 | 1.54 |

**The bake.** `georender_bake` sizes its buffers from the strip
entries' NumVerts and NumPolys, then decodes the strips in the batches'
order.
- Each vertex goes through an open-addressing hash of its 28 bytes, so
  one already in the mesh gets the same index.
- Each triangle goes in as three 16-bit indices. A batch's `first` and
  `count` are now indices.
- The mesh is one `linearAlloc` block: the vertices, then the indices
  from the next 16 bytes.
- A strip that would take the mesh past 65,536 vertices is skipped and
  counted. None on the disc does.

TRACKB12's meshes take 5.8 MB of the linear heap, down from 11.2.

**The draw.** `C3D_DrawElements` with `C3D_UNSIGNED_SHORT`. citro3d
gives the PICA the indices' address less the attribute buffers' base.
The mesh's vertex buffer is at its own offset from that base, so index
0 is the mesh's first vertex.
- Around each draw, citro3d turns the triangle element mode on and off
  (GEOSTAGE_CONFIG). That is 8 command words a draw more than
  `C3D_DrawArrays`: 63,274 words a frame for 312 models, where the list
  wrote 54,338.
- The lit pass, the env pass and the capture's frames draw the same
  way. `batch_centres` reads the vertices through the indices.
- The timing frame already counted `GPUREG_DRAWELEMENTS`. Its
  "vertices" are now the indices.

**Why the picture is the same.** The triangles are the list's, in the
list's order, with the same vertex bytes. The cull is off on every mesh
path, so a triangle's winding does not matter.

On Azahar, the capture's first frame 6 s in was taken with both builds
(`out/cap_list`, `out/cap_idx`):
- the depth buffers are the same to the bit;
- the colour differs in 85 pixels, by at most 5, all round the car.

The car's reflection is the envmap's. The envmap's faces draw on a
schedule, and the capture's hitch moves where that schedule falls.

**The capture's own fault.** The comparison found one, now fixed. The
numbered frame painted the envmap's faces and its fold in their numbers
too. A face keeps what it drew until it draws again, so the car's
reflection in the level-0 frame showed the numbers. `capture_offscreen`
now leaves those draws as they always are in both frames.

**On Azahar** (`out/azahar_idx2`): 29.2 FPS with 300 to 380 models in
view, and 0 unmapped accesses. Azahar does not model the PICA's cost,
so the saving can only show in a New 3DS's lines: the `models:` line's
indices, and the timing frame's "1-pixel scissor" less "3 vertices a
draw".

### The next cuts' probes

The timing frame (`hangwatch.c`) sends the models' and the first envmap
view's lists again onto its VRAM target, a way at a time. 13b-4f adds
three ways, so that one device run says what the next two cuts would
save:

| Way | What it changes in the copied list |
|---|---|
| early depth >= | `GPUREG_EARLYDEPTH_TEST1` and `_TEST2` on, `_FUNC` GEQUAL, `_DATA` 0 |
| early depth <= | the same with `_FUNC` LEQUAL |
| RGB8 for RGBA8 | each texture unit's `_TYPE` of RGBA8 made RGB8 |

- **The early depth test** is the PICA's depth test ahead of the
  texture fetch and the combiners, against a buffer of its own. citro3d
  writes its four registers with every effect, and clears its buffer
  with each framebuffer flush (`C3Di_SplitFrame`). 3dbrew and GBATEK
  give the registers' fields and nothing of how the buffer updates:
  its resolution, or whether a fragment that the alpha test later
  kills still writes it. Azahar does not emulate it.
- So each early way's target is read back and compared with "as
  drawn"'s, pixel by pixel, colour and depth. Its copy starts with four
  words more: `_DATA` 0, then `_CLEAR`.
- The port's depth is nearer-greater: GEQUAL and GREATER, the buffer
  cleared to 0. The registers do not say which side of the compare
  the early buffer is on, so both ways are tried. The right one should
  match "as drawn" and be quicker; the wrong one should drop most of
  the picture.
- **RGB8** reads the same addresses as three bytes a texel. Its texels
  are wrong, but its fetch is the one the lossless RGB8 textures (the
  ones of one alpha, memory: gpu-speed-plan) would have. Its pixels are
  counted too: they must differ, which shows the compare works.

On Azahar (`out/azahar_probe`), both early ways match "as drawn" to the
pixel. RGB8 differs in 4,096 of the envmap face's 4,096 pixels and
95,999 of the models' 96,000. The times are Azahar's 0.12 ms.

## Where 13b-4 stands

On Azahar, track 12, holding the gas, the mean of each second's line
over a run of about 25 seconds:

| | 13b-3 | 13b-4a | 13b-4b | 13b-4c | 13b-4d | 13b-4e |
|---|---|---|---|---|---|---|
| models | 16.4 to 17.8 | 12.1 to 13.8 | 11.8 | 9.2 | 9.3 | 9.2 |
| envmap | 7.8 to 10.0 | 6.7 to 8.6 | 7.8 | 6.3 | 6.3 | 6.2 |
| scenery | | | | | 1.1 | 0.5 |
| cars | 4.4 to 4.6 | 4.4 | 4.4 | 4.3 | 4.3 | 2.6 |
| hud | 4.7 to 4.8 | 4.8 | 4.8 | 4.7 | 0.3 | 0.2 |
| bottom | 5.3 to 5.4 | 5.4 | 5.4 | 5.4 | 0.9 | 0.5 |
| the draw | 44 to 46 | 39.6 to 40.6 | 39.2 | 35.0 | 26.1 | 23.3 |
| the frame | 50.1 ms | 50.1 ms | 51.1 ms | 50.6 ms | 34.2 ms | 33.8 ms |
| FPS | 20 | 20 | 19.6 | 19.8 | 29.2 | 29.6 |

After 13b-4e, the seconds run from 27.5 to 30.0 FPS: frames of 33.3 ms,
two blanks, with some of three. The CPU's frame is about 26 ms: the
draw is 23.3 and the world 1.4 to 4.5. The wait for the blank is 7.9
ms a frame. Where a second's models or world run long, a frame passes
33.3 ms and takes three blanks; the worst frame of a second is still
34 to 67 ms.

Azahar runs the CPU at 268 MHz, about an instruction a tick. A New 3DS
runs at 804 MHz with its L2 cache, so the same work should take well
under these times there. Only a New 3DS's `frame:` lines can say how
much. On Azahar, what is left to cut is the models (9.2), the envmap
(6.2), the cull (2.7) and the cars (2.6), and the long frames' spikes.

## 13b-5: the lit batches and the strips (commit 569dfde)

Session 53's profile of track 45's start, eight cars in view: a frame
of 66.7 ms, the cars stage 18.2 ms with its lists 7.4, and each lit
batch 453 command words against a scenery batch's 43.

- geolit is linked into geosolid's shbin (the Makefile hands picasso
  both files): one DVLP with two DVLEs, so a switch between the two
  programs sends no shader code, and the uniforms they share sit in the
  same registers.
- `c3d_unif_set`, `_vec`, `_mtx` and `_bool` (c3dwrap.c) leave a
  uniform alone when citro3d's copy holds its value for a register the
  GPU has. `__wrap_C3D_BindProgram` skips the program already bound.
- `bind_lit` keeps the run: the program, the attributes, the cull, the
  pass and the combiner stand between lit batches. `bind_strips` does
  the same for the strips.

The lit batches went from 453 words each to about 248, the view's words
from 127,676 to about 104,700, and the lists from 7.4 ms to 4.3. The
frame stayed at 15 FPS: about 50 ms of CPU, still over two blanks.

## 13b-6: citro3d's draws in one go (commit ba9ef1f)

A pair of timers round render_model's draw (taken out again) put the
view's draw at 16.9 ms for about 660 models and 1,470 batches: about
11 us a batch, or about 3,000 instructions at Azahar's instruction a
tick. Disassembled, `C3D_DrawElements` writes 15 single registers, each
through libctru's `GPUCMD_Add` at about 40 instructions: about 700 a
draw before any state. `C3D_DrawArrays` writes 11. The words are the
same every time but for the indices' offset and the count.

- `__wrap_C3D_DrawElements` (triangles) and `__wrap_C3D_DrawArrays`
  bring the state up to date with `C3Di_UpdateContext`, as citro3d's
  do. They then copy the draw's 30 or 22 words from a template, patch
  in the offset, count and first vertex, and set `C3DiF_DrawUsed` in
  the context's flags. `C3DiContextHead` is citro3d 1.7.1's
  `C3D_Context` (devkitPro's, 2023-10-28) up to its buffers.
- **The self-check.** The first draw of each kind is citro3d's own,
  after a `C3Di_UpdateContext` so that it writes nothing else. Its
  words must match the template's, and the context's head must hold:
  the flags show Active and DrawUsed, the command buffer lies inside
  the context's, and the buffers' base is BufInfo_Init's 0x18000000.
  Otherwise that kind stays citro3d's. The log says which:
  `c3d: indexed draws written here` and `c3d: array draws written
  here`, or `citro3d's (its words differ)`.
- `__wrap_GPUCMD_Add` writes a single register's two words itself;
  anything longer is libctru's.
- `__wrap_C3D_UpdateUniforms` returns at once for the geometry shader
  while the program bound has none.

On Azahar at Speed 100%, track 45's start with eight cars in view, the
range of each second's line over a run:

| | 13b-5 | 13b-6 |
|---|---|---|
| models | 17 | 10.3 to 11.7 |
| envmap | 3.3 | 1.7 to 2.1 |
| mirror | 3.1 | 1.9 to 2.4 |
| cars | 15 | 11.5 to 14.3 |
| the draw | | 33.0 to 36.0 |
| the CPU's frame | about 50 ms | about 40 ms |
| the frame | 66.6 ms | 49.8 to 50.9 ms |
| FPS | 15 | 19.7 to 20.1 |

With the pack gone it runs at 29.6 to 29.9 FPS. The user, 2026-10-08:
"It now runs at 20 FPS with all AI cars in view! That's pretty
respectable." They let the last 10 FPS go for now; the cops and the
helicopter may need more.

### What is left, for when the cops need it

From the same profile, with eight cars in view:

- **The cars' shadows, 4.1 ms.** Each car's hull fan is a draw a quad
  (about 15), with three edge strips and the grid's strips after it,
  each through `georender_draw_strip`. The CPU side also asks the
  topology for 20 to 30 elevations a car. Joining a car's shadow strips
  into one draw in trackview's strip layer cuts the draws.
- **The lists, 3.3 ms.** `draw_deferred` sorts, then draws each held
  batch alone with its own model-view.
- **A model's matrix.** When a model-view changes, citro3d's
  `C3D_UpdateUniforms` walks the 96 dirty bytes one at a time: about
  1,000 times a frame. An upload of the port's own would scan a word at
  a time. It would keep its own mask of the registers ever sent, for
  `C3Di_DirtyUniforms` after the HOME menu.
- **The world, 5 ms, and the cull, 3.6.**

## TASKS 46: the shader, the sends and the clusters (Session 81)

The user's ask of 2026-10-12: "a smooth 30 FPS" where many cars and the
fog are on the screen at once. The device's GPU is the bottleneck, at
about 32 ms a frame against the CPU's 20, so each of these lightens the
GPU and changes no pixel.

- **The solid shader in 17 instructions** (b293a76), where it took 31.
  The model-view and the projection go as one matrix, and the fog's row
  and the light's direction are carried into the model's space, once a
  model on the CPU (`geosolidunif.c`), with the 1/127 and 1/255 scales
  folded in. geolit takes the same `mvp` and `fogModel`, so the car's
  environment pass meets the solid pass's depth to the bit.
  `tools/geosolid_check.py` runs both shaders and the old one through a
  PICA interpreter of its own on 48 scenes: colour, texture
  coordinates and fog equal, the position as accurate on the PICA's
  16-bit mantissas as before. 14 of 14 mutations caught.
- **The frame to the GPU in parts** (9e044f3), opt-in.
  `hangwatch_gpu_send` hands the GPU what was drawn so far after the
  mirror, the models and the top screen's HUD, so it draws while the
  CPU builds the rest, rather than idling until `C3D_FrameEnd`.
  Azahar draws the same frames with it. "GpuSends 1" in
  nfshp2_config.txt turns it on; it stays off until a device run has
  shown it never stops the GPU. (On by default since TASKS 57, below.)
- **The clusters** (bb70171). Each batch of a baked mesh keeps a box
  round it and one round each 32 of its triangles, in their order,
  after its indices in the same linear block (`geocull.c`). A batch
  goes whole when its box is inside the view's four side planes, not
  at all when it is beyond one, and otherwise as one draw for each run
  of its clusters that are not beyond one. The planes are rows of the
  matrix the shader is handed, made with it in `set_model`. A box is
  beyond a plane only by more than the PICA's 24-bit rounding could
  make up (2e-4 of the terms, about four times the worst of seven roundings),
  so what is left out is what the GPU would have clipped whole.
  `tools/geocull_check.py` runs every vertex of 36 scenes' strips
  through geosolid.v.pica on the PICA's floats: 0 faults, 8 of 8
  mutations caught. "ClusterCull 0" draws every batch whole, for a
  timing run to compare.

Azahar's track 12, a frame:

| Pass       | Triangles before | After  | Draws before | After |
|------------|------------------|--------|--------------|-------|
| The envmap | 36,000           | 18,500 | 567          | 335   |
| The mirror | 15,000           | 6,400  | 247          | 157   |
| The view   | 3 to 15% fewer   |        | fewer        |       |

A quick race from the title then ran at 29.9 FPS, 33.5 ms a frame,
the worst 35.4, with the draw's CPU at 14.5 ms (the envmap 2.7, the
mirror 2.2, the models 2.7, the cars 2.5). Azahar's GPU times mean
nothing; the device's timing lines are what will say how much of the
32 ms these took.

### What is left

- **The device's numbers** at the laggy places: the fog, the desert's
  end with the chopper. A timing run (`sdmc:/nfshp2_gputiming.txt`,
  `DebugLog 1`) with and without `ClusterCull 0` and `GpuSends 0`.
- **The envmap a face a frame.** Its six faces are a third of a light
  frame's GPU. Drawing one face a frame would cut most of that, but the
  cars' reflections would lag the world by a few frames: a change to the
  look, so the user decides.
- **Early depth and RGB8.** The timing frame's probes (2fc77fc) still
  wait for a device run.

## TASKS 57: the fire on track 11 (Session 88)

The user's report of 2026-10-12: the track with the fire truck, its
fire, smoke and fog, "is a bit laggy". It is track 11 (TRACKB11.BUN,
Coastal Parklands). Its acid emitters put the forest fire (the
`XE_FFire_` flames, black and white smoke and sparks) at about x -580
to -700, y 145 to 240, and the truck's four water jets
(`XE_FireTruck_WaterA` to `D`) at about -584 to -570, 151.

**The user's device log** (`3DS Files/nfshp2_debug.txt`, track 11 with
four AI and two cops) is slow from about (434, 229) through
(-106, -144) to the fire at (-588, 220): 13 to 18 FPS. The worst
second:

    13.8 fps, 72.6 ms: world 4.5, draw 23.1 (envmap 4.4, mirror 2.9,
    models 6.9, scenery 2.1, cars 2.2), vsync 8.7, gpu wait 35.2;
    citro3d cpu 22.8, gpu 49.6

The GPU is the bottleneck, and it only started once the CPU's whole
draw was done, so the frame was roughly the draw plus the GPU,
23 + 50 ms. A least-squares fit over 274 s of the log (rms 2.4 ms) puts
the GPU's time at about 0.09 to 0.14 ms per 1,000 indices and 2.3 to
2.5 ms per 100 sprites. Its worst second split as the view about 22 ms
(119,832 indices in 1,170 batches), the envmap about 16 (146,145 in
715), the mirror about 5.5 (60,700 in 437), and up to 12.8 ms of
sprites at the fire (511 of them).

What was weighed, lossless only:

- **A smaller vertex.** GeoRenderVertex is 28 bytes, with float
  positions and texture coordinates. Retail's strips hold both as
  32-bit floats, so 16-bit ones would not be exact. Not done.
- **The frame to the GPU in parts.** Done: `GpuSends` is now 1 by
  default (`configitems.c`). One more send goes between the envmap and
  the mirror (`main.c`), so the GPU starts on the envmap's faces as
  soon as they are built, not after the mirror too. The sends are now:
  after the envmap, after the mirror, after the models, after the top
  screen's HUD and before `C3D_FrameEnd`. The pixels are the same:
  the parts run in order on one queue, each clear still runs before
  the draws to its own target, and each send flushes the linear heap
  after its split (04aa510). Expected at the fire: about 4.4 + 50 ms a frame,
  where it was 23 + 50, so about 18 FPS from 13.8. Not measured on the
  device yet. "GpuSends 0" sends the frame whole, as before. Since
  TASKS 65 a send flushes by the kernel's own call, not by a request to
  GSP, and is timed (`frame-profiler.md`, "The sends").
- **The smoke's fill.** The sprites are fill-bound (25 µs each, four
  vertices). A quad cut to its texture's non-zero alpha, over every mip
  level and with the filter's texel of margin, would draw the same
  pixels if the sprites write no depth. Not done.
- **The envmap a face a frame** (TASKS 46) would cut most of its
  16 ms, but it changes the look, so it is the user's call.

On Azahar (AC power, speed 100%, `run_azahar_race.ps1 -HoldKeys 65`
with `nfshp2_warp.txt` at the fire): the whole race ran with the sends
on, with no hang and the GX queue at most 17 of 32 entries. The shots
at the fire (`$TEMP\nfshp2_fire57`) match the run without the sends
(`$TEMP\nfshp2_fire1`): the flames, the truck's jets, the smoke, the
fog and the mirror, whole. Azahar's GPU takes no time, so only the
device can show the gain.

## TASKS 46: the smoke's alpha test, and the timing frame in a race (Session 128)

The device log puts up to 12.8 ms of the fire's frame in its sprites.
A counting build on Azahar (not kept) read their textures from the
game's memory at the fire; the worst frame drew 1.3 million sprite
pixels:

| Texture   | Format | Blend | Atlas            | Texels of alpha 0 |
|-----------|--------|-------|------------------|-------------------|
| FIREA_CS  | RGBA8  | add   | 4x2 cells of 64  | none: 250 throughout, 44% black |
| SMOKE_CS  | LA8    | alpha | 4x4 cells of 32  | 36% |
| DUSTA_CS  | LA8    | alpha | 4x2 cells of 64  | 43% |
| SMOKEB_CS | LA8    | alpha | 4x4 cells of 64  | 17% |

- **The alpha test (done).** The sprites, and every other draw that
  blends with no alpha test and writes no depth, now test for an alpha
  over 0 (`georender.c`, `set_pass`). Each of `set_blend`'s three blends
  takes the source by its alpha and keeps the destination whole at 0,
  its alpha too, so a fragment of alpha 0 changes nothing. The test
  drops it before its depth read and its blend.
  - A draw that writes depth changes the buffer at any alpha, so it is
    left as it was.
  - The mirror's quads (`set_blend_source_alpha`) write their own
    alpha, and they do not go through `set_pass`.
  - The test kills 17 to 43% of the smoke's and the dust's fragments.
    The fire's own, alpha 250 everywhere, all pass.
  - On the PS2 the GS's `(Cs - Cd) * As >> 7 + Cd` is Cd at As 0. Should
    the PICA's blend round at alpha 0, the test makes it retail's.
  - On Azahar the timing frame's "alpha test 0 off" replay of the
    sprites' list differs from as drawn in 0 pixels.
- **The quads cut to their alpha (not done).** A polygon round each
  cell's visible texels, with the filter's texel of margin, keeps 0.79
  to 1.0 of the cell. That is about 15% less fill on top of the test,
  which gets most of it for nothing.
- **The clusters with no pixel centre (not done).** A cluster whose
  projected box holds no pixel centre draws nothing, so leaving it out
  would be exact. Counted on Azahar at the fire, they are 0.0 to 0.3%
  of the indices in every view, the envmap's 64-pixel faces included.

### The timing frame in a race

The replays had never run in a race. Their target needs 768 KB of
VRAM, and a race's textures leave less: track 11's leave 512 KB.

- Now, when VRAM has no room, the replays borrow the top screen's own
  buffers. They are the same size and formats, in the same banks. What
  the buffers hold is kept in the linear heap and put back after
  (`hangwatch.c`, `borrow_top` and `give_back`).
- The GPU puts them back (`GX_TextureCopy`, as `texpack.c` fills a VRAM
  texture). The CPU may read VRAM but not write it: the first device run
  (2026-10-18, Coastal Parklands' countdown) stopped on a permission
  fault in `give_back`'s `memcpy` into the top screen's colour buffer,
  at 0x1f000000. Azahar lets the write through. `give_back` reads the
  buffers back and logs how many words differ, the first time and after
  only when some do; on Azahar it was 0 of 96,000 each.
- The sprites' stage, "the sun and the scenery's list", is replayed
  too.
- There are two more ways:
  - "alpha test 0 off": the tests of reference 0 off, with its picture
    compared;
  - "texture unit 1 off": the fog's fraction unread. The sprites' fog
    stage reads unit 1's texture of one value.
- On Azahar's track 11 every replay ran. Early depth's pictures matched
  as drawn's to the pixel, but Azahar does not emulate early depth.

### What is left

- **The device's timing run** at the fire and the desert's end with
  this build: `sdmc:/nfshp2_gputiming.txt` (empty) and `DebugLog 1`.
  For each stage it shows how the time splits:
  - fill (the 1-pixel scissor);
  - the cost of each draw (3 vertices a draw);
  - the textures (8x8, RGB8, unit 1).

  It also shows whether early depth is exact on the PICA, and what it
  saves.
- **The envmap a face a frame**, the user's call.

## TASKS 46: the draw's per-batch work (Session 128, continued)

The first device run (6dd7060) found Alpine Trail bound by the CPU, with
the models the biggest share of its draw. A sampling profile of the same
race's start on Azahar showed where a batch's CPU time goes:

- `gdbprof.py` (scratchpad) stops Azahar through its GDB stub, reads
  the registers and 1 KB of the stack, and lets it go on.
- `gdbprof_report.py` maps the samples to the ELF's functions.
- At 100 stops a second Azahar stutters badly; the user saw it
  ("HOLY ITS DYING"). Next time: 5 a second, and say so first.

Of 1,552 samples, 12% were Azahar's own GPU work
(`svcSendSyncRequest`) and 6% waits. The next ten, by their own time:

| function | samples |
|---|---|
| `geocull_box` | 5.8% |
| `memcpy` | 5.3% |
| `__wrap_C3D_UpdateUniforms` | 4.1% |
| `__wrap_GPUCMD_Add` | 4.0% |
| `C3D_UpdateUniforms` | 3.2% |
| `set_model` | 2.9% |
| `c3d_unif_vec` | 2.0% |
| `memcmp` | 1.9% |
| `memset` | 1.7% |
| `GPUCMD_Add` | 1.6% |

Most of it is a model's matrices. Each model sends its mvp, fog and
light rows as float uniforms. They go through citro3d's walk of the 96
dirty bytes, one at a time, and libctru's `GPUCMD_Add`. The 64-byte
matrices are also compared and copied through newlib's `memcmp` and
`memcpy` calls.

### The cuts

- **The float uniforms, sent by the port** (`c3dwrap.c`,
  `send_floats`). citro3d 1.7.1's `C3D_UpdateUniforms`, disassembled,
  does this for each run of dirty float registers:
  - it writes the run's first register to `FLOATUNIFORM_CONFIG`, and
    the run's words to `FLOATUNIFORM_DATA` as one `GPUCMD_Add`;
  - it clears the run's dirty bytes;
  - it marks the run "ever dirty", in a table of `uniforms.o`'s own,
    so that `C3Di_DirtyUniforms` (after the HOME menu) sends it again.

  `send_floats` scans the dirty bytes a word at a time and writes the
  same words into the command buffer itself, the padding word too,
  with no calls. `s_ever` is its own "ever dirty" table, which
  `__wrap_C3Di_DirtyUniforms` adds after citro3d's. The shader's
  constants, the integers and the bools are still citro3d's to send. So
  is a run of more than 64 registers.
- **The self-check.** The first 64 sends go both ways:
  - `send_floats`'s words are kept;
  - the buffer and the flags are put back, and citro3d's function
    runs;
  - the two are compared word for word.

  One that differs leaves the floats to citro3d for good. The log says
  `c3d: float uniforms sent here (64 sends matched citro3d's)`, or
  `citro3d's (send N of M words differs ...)`.
- **The draws' templates** are copied as two blocks the compiler moves
  with `ldm` and `stm`. A copy over 64 bytes was a `memcpy` call.
- **The matrices' compares** (`c3d_unif_set`, `bind_mesh`,
  `set_model`): memcmp's equality, the same bits, as a word loop with
  no call.
- **The clusters** (`geocull.c`):
  - each plane's far and near corner is found once, in
    `geocull_planes`, not for each box;
  - a batch's clusters are tested only against the planes the batch's
    box is across (`geocull_box_in`).

  A box inside another is wholly inside every plane the other is
  wholly inside. The products and sums round monotonically, so a
  cluster's near corner cannot come out below its batch's.

**Why the picture is the same.**

- The float words are citro3d's own, checked word for word in each run.
- The compares are memcmp's equality.
- The clusters' verdicts are the old ones:
  - A host comparison with the old `geocull.c` (scratchpad
    `cull46/same.c`, 200,000 random views): 927,451 boxes have the same
    verdict, and 603,073 clusters tested against their batch's planes
    alone match the test against all four.
  - `tools/geocull_check.py` gives the same counts as before: of 5,524
    clusters 1,383 out, 3,730 across and 411 in, with 24% of the
    triangles left unsent. It catches its 10 mutations, two of them
    new.
- The race-start shots match the baseline's to the pixel; only
  Azahar's status bar differs.

**On Azahar**: Alpine Trail (track 42, 3 AI, 4 cops), gas only. The
means of seconds 2 to 8 after the attach, in ms:

| | before | the uniforms and copies | and the clusters |
|---|---|---|---|
| models | 14.4 | 12.5 | 12.6 |
| mirror | 3.6 | 3.3 | 3.3 |
| envmap | 2.4 | 2.3 | 2.2 |
| the draw | 39.8 | 37.3 | 37.0 |
| citro3d's CPU | 39.3 | 36.9 | 36.6 |
| FPS | 19.8 | 20.0 | 20.0 |

The models are 13% cheaper. The clusters' change shows nothing on
Azahar beyond the noise, for two reasons:

- Most tests are the batches' own, which still try all four planes.
- Azahar's JIT does not charge for the VFP's flag transfers (`vmrs`).
  The change takes those from 11 a box to 3, plus 2 for each plane a
  cluster is tested against.

What it saves on the 3DS is not measured yet.

### The ticker and the vtables

A second profile of the same start, after those cuts, took 888 samples
at 5 a second. Two of the world step's helpers came next, by their own
time:

| function | samples |
|---|---|
| `vt_slot` | 6.4% |
| `__udivmoddi4` and `__aeabi_uldivmod`, called by `bGetTicker` | 5.4% |

- **`vt_slot`** (`vtable.c`) finds a port entry from a vtable's image
  address. It searched the sixty-odd tables from the front, and the
  physics and the AI dispatch through it many times a car a frame. It
  now looks the address up in 256 open-addressed buckets. Its refusals
  are the same: a missing table, a misaligned or out-of-range slot, or
  an empty entry still abort with the same message.
- **`bGetTicker`** (`bticker.c`) scales the ARM11's tick to the EE's
  294.912 MHz with two 64-bit divisions by 268,111,856. The ARM11 has
  no divide instruction, and libgcc's 64-bit one is a loop. The
  physics' stopwatches read the ticker several times a car a step.
  Each division is now a multiply by the reciprocal, rounded down,
  then one correction step (`div_3ds_hz`). The reciprocal's error times
  a tick is under one, so the multiply comes out at most one short.

**Why nothing changes.**

- **The ticks**: `tools/bticker_check.py` runs `bTickerFromSystemTick`
  beside the old division over 106,027,970 ticks: random ones of every
  size, a year of uptime, each second's edges, the top of the range,
  and each step of the remainder. None differ. It catches its 6
  mutations.
- **The vtables**: `car_check.py` gives the same transcript, its eight
  refusals included. Its `[vtable]` scenario now also has two addresses
  that share the last bucket, and a table installed again after a
  reset. It catches its 14 vtable mutations, four of them new.
  `cardriver_check.py`, `aidriver_check.py` and `aisnap_check.py` give
  the same output.
- **The race-start shot** matches the baseline's to the pixel; only
  Azahar's title and status bars differ.

**On Azahar**, the same race, seconds 2 to 8, in ms:

| | after the per-batch cuts | and these |
|---|---|---|
| the world step | 3.4 | 2.8 |
| the draw | 37.0 | 36.6 |
| citro3d's CPU | 36.6 | 36.2 |
| FPS | 20.0 | 20.0 |

The world step is 18% cheaper.

### The textures and the sun's read-back

A third profile (884 samples at 5 a second, its ELF kept) showed two of
`trackview.c`'s own loops by their own time:

| function | samples |
|---|---|
| `load_texture`, almost all of it `find_texture` | 1.7% |
| `floorf` | 1.6% |
| `trackview_read_depth` | 1.2% |

- **`find_texture`** looked a TextureInfo up by scanning the texture list
  from the front. The list holds every texture seen so far, 659 at
  Alpine Trail's start. Every scenery piece and car part drawn through
  `render_model` and `render_epoly` looks its textures up there, every
  frame. The track's own models keep their entries and do not. The list
  is now found through 2,048 open-addressed buckets, twice
  `TRACKVIEW_MAX_TEXTURES`, so one is always empty. Each bucket holds an
  entry's index plus one. `load_texture` fills the bucket as it
  appends, and `forget_all` empties them all with the list. A
  TrackView's other lifetimes start and end with a `memset` of the
  whole struct. A bucket's entry is still compared by its TextureInfo,
  and `load_texture` puts a TextureInfo in the list only once, so the
  entry found is the one the scan found.
- **The sun's read-back** (`read_sun_rect`) worked out each pixel's place
  on the screen with `target_to_screen`, two `floorf`s and two clamps,
  then the tiled word. Its x depends only on the column and its y only
  on the row. The word's x bits and y bits do not overlap, so the word
  is the x part plus the y part (`tiled_x`, `tiled_y`). Each column and
  row of a rect is now worked out once, not once a pixel.

**Why nothing changes.** `tools/trackview_cuts_check.py` cuts the
functions out of `trackview.c` as they are now and builds them on the
host, with test bodies from `tools/src`:

- `trackview_sun_test.inc` holds `read_sun_rect` to the old per-pixel
  loop over 400,000 rects on random targets, aspect ratios and depth
  buffers: 137,500,738 pixels, none differ. It also holds the split
  `tiled_index` to the whole one.
- `trackview_tex_test.inc` holds `find_texture` to the old scan over
  3,999,906 lookups, 94 resets and the list filled to its end: none
  differ.
- It catches its 14 mutations, 8 in the sun's code and 6 in the
  buckets. One of them, buckets kept over a reset, is caught by a hang
  once the list is full.
- The race-start shot matches the baseline's to the pixel; only Azahar's
  title and status bars differ.

**On Azahar**, the same race. Seconds 2 to 8 after the attach, in ms:

| | after the ticker and the vtables | and these |
|---|---|---|
| scenery | 2.9 | 1.1 |
| cars | 8.6 | 5.9 |
| cull | 3.7 | 3.0 |
| models | 12.4 | 12.1 |
| envmap | 2.3 | 2.3 |
| the draw | 36.6 | 31.0 |
| citro3d's CPU | 36.2 | 30.6 |
| FPS | 20.0 | 22.3 |

The cars' seconds 6 and 7 are lower than the baseline's: the new run
was under 33 ms there and ran at 30 FPS (29.7 and 26.5), so the grid
had spread out sooner. Over the whole race (58 seconds each) the draw
is 23.2 ms from 25.5, and 6 seconds were under 28 FPS, down from 13.
The sun's change shows nothing in the envmap stage on Azahar, where
`floorf` is cheap. On the 3DS it is a libm call, and is not measured
yet.

### The scenery's boxes

A fourth profile (953 samples at 5 a second, its ELF kept) put
`scenery_classify_aabb` first among the game's own functions, at 5.0%:
2.6 called from `scenery_draw_a_scenery` and 2.4 from
`scenery_tree_cull`. `scenery_draw_a_scenery` itself was another 2.6%.
Each view's cull runs it, the envmap's active faces included.

- **An early answer.** The box test builds its eight corners in clip
  space and gives 2 when every corner is inside, 0 when one plane has
  every corner outside it, and 1 otherwise. It now keeps the OR and the
  AND of the corners' flags as it goes. Once some corner is outside a
  plane and no plane has every corner so far outside it, the box is
  across: more corners can only add to the OR and take from the AND, so
  the answer is 1 and the rest are not built. Each corner is still the
  listing's sum (`c2` is `c1 + ey`, the same adds as `(c0 + ex) + ey`).
  Boxes inside or outside still take all eight.
- **The box last.** `scenery_draw_a_scenery` classified a piece's box
  before its other tests: the exclude flags, its size on the screen and
  the LOD with a model for that size. Those only read and return, so a
  piece that fails one is not drawn whatever its box. The box now waits
  until the piece would be drawn.

**Why nothing changes.** `tools/scenerycull_check.py` holds the port to
the retail ELF run in `mipsemu.py`, `ClassifyAABB` (0x0010b940) on inside,
across and outside boxes, NaN, infinity, -0 and random matrices among
them: 9 scenarios, 46,687 lines, none differ. Its 10 box-test mutations
were rewritten for the new code (the AND and the OR, the first corner,
a top corner left out, a 2 from the bottom face alone, and others), and
all 150 of its mutations are caught but `facade-z`, equivalent as
before. The race-start shot matches the baseline's to the pixel; only
Azahar's title and status bars differ.

**On Azahar**, the same race. Seconds 2 to 5, in the same place on the
start straight in both runs, in ms:

| | after the textures and the sun | and these |
|---|---|---|
| cull | 3.05 | 2.58 |
| models | 12.5 | 12.5 |
| the draw | 32.4 | 32.2 |
| citro3d's CPU | 32.0 | 31.8 |
| FPS | 20.0 | 20.0 |

The cull is about 0.5 ms lower in each of those seconds, and 2.1 ms
from 2.5 over the whole race. After second 6 the two races went
different ways: at 26 seconds the baseline's car was 4th and this one's
1st, in another part of the track. From there the draw follows what the
camera saw (seconds 42 and 43: the models 11.2 ms here, 6.8 there), so
the whole race's draw and slow seconds do not compare.

### The sound banks' flush

The fourth profile's 2.2% in `DSP_FlushDataCache`, all of it from
`bsnd.c`'s `hw_start`, made each sound's start a DSP service call: the
patch's bytes out of the CPU's cache before ndsp reads them. A bank's
image is written once, by `bsnd_bank_load`'s `fread` into linear
memory, and after that only read (`sndbank.c` copies records out and
hands back pointers). So `bsnd_bank_register` now flushes the whole
image once, through the driver's `registered` hook (the 3DS half's
`hw_registered`, none on the host), and `hw_start` flushes nothing. The
DSP reads the same bytes either way. The streams (`bsndstream.c`,
`jbstream.c`, the movies) write their buffers as they go and keep their
own flushes.

`tools/bsnd_check.py out/SOUND` is unchanged by it: 449 of 5,162 lines
differ, as they do on the commit before. The checker last passed at 0
in Session 65; the drift is older and is its own task. Azahar does not
model the caches, so only the 3DS can show a flush missing, as
crackle or old sound in a patch.

### The fog's texture

`trackview.c`'s `fog_frame` makes the view's fog each frame: `fog_attach`
works out the fog's 129 fractions twice, once for the scenery and once
for the sky, and `georender_fog_fill` wrote each into its 256-by-8 A8
texture, a fraction for each of its 2,048 texels, then flushed it with
`GSPGPU_FlushDataCache`. That flush is a request to GSP's own thread on
the system core, which the main thread waits on (the fourth profile's 6
samples of GSP's flush were all this). Two a frame, for a palette that
changes only with the weather.

- **The same fractions, nothing done.** The texture's bytes are its
  fractions' alone, so `GeoFog` now keeps the fractions its texture was
  last filled with. Fractions the same to the bit leave the texture as
  it is, with no write and no flush. A new texture fills whatever the
  fractions, and a failed one keeps none.
- **A column's byte once.** Every row of the texture is the same, so
  each column's byte is worked out once (256) and laid into the tiles,
  not once a texel (2,048), when the fractions are new.

**Why nothing changes.** `tools/georender_cuts_check.py` cuts the
function out of `georender.c` and holds it to the fill it replaced
(`tools/src/georender_fog_test.inc`) over 300,000 fills: mostly the same
fractions again, as a race has them, and else one, a few or all of them
changed, a single bit flipped, -0, NaN, infinity and any bits among
them, with the texture now and then made again or failing to be. A stub
flush copies the range it is given into what the GPU would read, and
after each fill that must be the old fill's bytes, as must the texture's,
and a fill must flush exactly when its fractions are new. 0 of 300,000
differ, and its 12 mutations (the skip without a texture, the new
texture kept as filled, the last step not compared, the fractions not
kept, the flush left out or halved, the columns, the clamp, the
rounding and the tiles) are all caught.

### What is left

- **The device's numbers** for these builds on Alpine Trail's start
  straight, with "DebugLog 1" and no `nfshp2_gputiming.txt`.
- **After the finish, the race phase: not a cost.** In the device log's
  post-race and instant replay (rc 7 and 4) it took 13.5 ms a frame on
  average over 40 s, and up to 34 ms. That is retail's pacing, not
  work. In a replay `world_get_timestep` (`worldstep.c`, World::
  GetTimestep) takes the step the capture logged and spins until the
  frame is that long, `MAX_TIME_TO_WASTE` (0.3 s) at most. So a replay
  plays at the race's own rate: a stretch the race ran at 20 FPS
  replays at 20, whatever the replay's own work. The device's View
  Replay matches its race second by second (20, 20, 20, 22, 23, ... 30
  FPS both). Cutting the spin would play the replay fast, so the way to
  a 30 FPS replay is a 30 FPS race. Since then the frame line times the
  spin apart, as "replay" in its waits, and takes it out of "race"
  (`frameprof.h`).
- **The world step** (4.9 ms on the device before these cuts) and
  **the cars** (2.9).
- **The fourth profile's next functions**, by their own time (its ELF
  is kept beside its samples, as each profile's should be):
  - `vt_slot` (2.7%), already through its buckets: what is left is how
    often the physics and the AI call it;
  - `memset` (2.5%) and `physicscar_iterate_forces` (2.5%);
  - `bTickerFromSystemTick` (2.5%). Azahar's samples land where its
    compiled blocks start, so the `svcGetSystemTick` before it is
    counted here. The reads are retail's stopwatches in the physics,
    kept so the checks count them as retail does;
  - `scan` (2.5%), `threadguard.c`'s: the tripwire over the audio
    workers' stacks from the race-end crash hunt of 2026-10-11. It is a
    diagnostic, not the game's code, so whether it stays on is the
    user's call.
