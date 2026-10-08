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
