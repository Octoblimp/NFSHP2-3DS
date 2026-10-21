# The frame profiler (steps 13b-2 and 13b-3)

Where a race frame's time goes, so 13b-4 cuts the largest cost first.
It has two halves:

- **Retail's own.** MainLoop stamps ten ticks through each frame into
  MainLoopTiming. CalculateFrameRate turns two of them, and two times
  from the display, into a CPU rate and a GPU rate.
  Player::DisplayDebugInfo prints those rates on the HUD as `C: %dfps` and
  `G: %dfps`. `mainloop.c` and `edisplay.c` port them, and
  `tools/mainloop_check.py` holds them to the image.
- **The port's log.** `frameprof.c` adds each phase up and logs a line
  each second of a race. Nothing like it is in either image.

## MainLoopTiming, 0x002f0058

MainLoop (`0x0012f378`) reads bGetTicker at each phase's end and stores
the tick in the struct, which the mdebug types name (type 3247):

| Offset | Field | Retail's tick, after |
|---|---|---|
| 0 | StartTime | the top of the frame (`0x0012f3b0`) |
| 4 | ServiceGameFlow | ServiceGameFlow, the second one |
| 8 | GenerateJoyEvents | GenerateJoyEvents, before World::DoTimestep |
| 12 | WorldDoTimestep | the world's step and ReplayManager::EndFrame |
| 16 | MenuSystemTick | MenuSystemTick |
| 20 | UpdateCameraMovers | the coordinators and UpdateCameraMovers |
| 24 | UpdateSound | sound::Update |
| 28 | DisplayFrame | eDisplayFrame |
| 32 | ServiceFileSystem | ServiceResourceLoading and two debug calls |
| 36 | LimitFrameRate | the wait for the vertical blank |

Then it calls CalculateFrameRate and MaybePrintTiming. MaybePrintTiming
is `jr ra` in both images. The demo's PrintTimingStat (`0x0012d7a0`),
which pads a phase's name and takes a tick difference, has no caller and
prints nothing. The per-phase print was compiled out.

## The two times, 16.16 milliseconds

eDisplayFrame times its wait for the GPU, eWaitUntilRenderingDone, with
bGetFixTickerDifference (`0x00250fa0`), and stores it at gp-24456
(`0x00113e00`). ServiceRenderStageQueue stores the VIF's time for the
frame at gp-24452 (`0x001119f4`). The difference is `((to - from) << 6) /
293`: milliseconds in 16.16 at bGetTickerDifference's 300 MHz, wrapping
past 2^26 ticks (227 ms).

| | Address | Port |
|---|---|---|
| GetWaitForBufferSwapTime | `0x00111f28` | `(float)WaitBufferSwapTime * 2^-16` |
| GetVifTime | `0x00111f40` | `(float)VifTime * 2^-16` |

Each is `cvt.s.w` of the signed word, times `0x37800000`.

## CalculateFrameRate, 0x0012f090

1. The wait, then the GPU's time, are read.
2. **The CPU's time** is bGetTickerDifference(StartTime,
   LimitFrameRate) less the wait, floored at 0.1 ms (gp-32052,
   `0x3dcccccd`). Its rate is 1000 / it.
3. **The GPU's time** is the VIF's, floored at 0.1 ms. Its rate is 1000 /
   it.
4. **The four are kept** when bit 3 of RealTimeFrames differs from the
   kept count's (gp-13416, a function static). The whole count is kept.
   RealTimeFrames counts sixtieths, so the numbers change every eight of
   them, slowly enough to read.

| Global | Address | Demo |
|---|---|---|
| PreviousCpuFrameTime | gp-23248 `0x0032fe20` | gp-23816 |
| PreviousGpuFrameTime | gp-23244 `0x0032fe24` | gp-23812 |
| PreviousCpuFrameRate | gp-23240 `0x0032fe28` | gp-23808 |
| PreviousGpuFrameRate | gp-23236 `0x0032fe2c` | gp-23804 |

All start at 0.

**What the port leaves out.** Retail adds a loop the demo has not. With
DoScreenPrintf (gp-23064, the pause debug menu's "Screen Print") set and
a World, it calls `0x00132620` for each of the World's cars. That
function reads the race and calls DisplayCullingStats (`0x0010cea0`,
`return 0`) and Race::GetRacingCar. Its prints are compiled out, and it
changes nothing. `carfinish.c` leaves out the same tail in
Car::FinishMovement.

**Where the rates show.** Player::DisplayDebugInfo (`hudrender.c`)
prints PreviousCpuFrameRate and PreviousGpuFrameRate, truncated, into
two of the one-player HUD's texts:

| Text | Where (640x480) | Prints |
|---|---|---|
| `fa10332f` | 16, 225 | `C: %dfps` |
| `2df92633` | 16, 248 | `G: %dfps` |
| `d8f8bd54` | 16, 271 | the car's position and zone |
| `f8c20c4a` | 16, 296 | the odometer |

They show only with DisplayPlayerDebugInfo (gp-20700), which the pause
debug menu's "Show debug Info" item turns on and off.

## On the 3DS

`main.c` stamps the ticks at the port's own phase ends (`frameprof.h`
has the list). The port's loop runs sound first and the flow's service
and menus together, so the order is not MainLoop's. CalculateFrameRate
reads only StartTime and LimitFrameRate, and those mean what they meant
on the PS2: the frame's start and its end.

- **The GPU wait.** C3D_FrameBegin(C3D_FRAME_SYNCDRAW) is split into
  C3D_FrameSync, which waits for the vertical blank, and
  C3D_FrameBegin(0), which waits for the GPU to finish the last frame.
  The second is eWaitUntilRenderingDone's place, so its
  bGetFixTickerDifference is WaitBufferSwapTime.
- **The GPU's time.** VifTime is citro3d's C3D_GetDrawingTime, the last
  frame's GPU time, turned into EE ticks and through
  bGetFixTickerDifference, so it is on retail's scale.
- **The vertical blank** is waited for at the start of the port's draw,
  not at the frame's end. So the CPU's time, the frame less the GPU
  wait, includes it, as retail's includes its spin.
- **The switch.** `SHOW_FRAME_RATES` in `main.c` sets
  DisplayPlayerDebugInfo for the race. It is 0 in the build the user
  plays.

## The log

Each second of a race, `frameprof` logs a line (wrapped here):

    frame: 20.0 fps, 50.1 ms, worst 50.8; sound 0.0, flow 0.0, race 0.1,
    world 1.9, cameras 0.1, draw 45.2, loads 0.0; draw: prep 0.0, cull
    2.3, envmap 8.9, sky 0.8, models 16.4, scenery 1.8, cars 4.5, hud 4.7,
    bottom 5.4, submit 0.3; waits: vsync 2.8, gpu 0.0, replay 0.0;
    jukebox: decode 0.00, read 0.00; citro3d cpu 44.8, gpu 0.8; C 20 fps,
    G 1362 fps

- The frame rate, the mean frame and the longest.
- Each phase's mean in milliseconds:
  - sound: the jukebox and the sample's callbacks;
  - flow: the clocks, the pads, the flow and the menus (bgf_frame);
  - race: the coordinator, the flow's second service and the events,
    less a replay's wait;
  - world: World::DoTimestep;
  - cameras: the players and the camera movers;
  - draw: the CPU's side of the draw, less the two waits;
  - loads: the resource loading.
- The draw's stages, which add up to it. `main.c` and `trackview.c`
  stamp each one's end with `FRAMEPROF_STAMP`:

  | Stage | From the last stamp to |
  |---|---|
  | prep | the waits: the track's attach, the log, the blurb |
  | cull | after the waits: the sun's Z rects read back, then `begin_frame`: the frame's memory, the views' matrices, and `scenery_do_culling` for every view |
  | envmap | the cars' cube map: its six views drawn, and the fold to the sphere map |
  | mirror | the rear-view mirror's view, 3, drawn into its target, and its frame (since 11g-2e) |
  | sky | StuffSky and its lists drawn |
  | models | `scenery_stuff_scenery`: eModel::Render for each model the cull kept, its batches drawn or put on the lists |
  | scenery | StuffSun, and the scenery's solid list drawn |
  | cars | RenderCars, the cars' solids, and both alpha lists |
  | hud | the rest of `trackview_draw`, and the top screen's Flailer layers |
  | bottom | the bottom screen: its Flailer layers and the minimap |
  | submit | C3D_FrameEnd |

  A stage that a frame does not stamp takes no time in it.

  Before 13b-3 the stages were named wrongly. 13b-2's "cull" ended at
  `scenery_stuff_scenery`, so it timed the models' render, and the cull
  itself was inside "envmap". 13b-3 stamps the cull's end in
  `begin_frame` and names the old stage "models".
- The three waits. Since TASKS 46 the third is a replay's: in a
  replay World::GetTimestep spins until the frame is as long as the
  step the capture logged, `MAX_TIME_TO_WASTE` (0.3 s) at most, so
  the replay plays at the race's own rate. A stretch the race ran at
  20 FPS replays at 20 FPS whatever the replay's own work. Before,
  the spin was in "race", which read 20 to 34 ms in the device's
  View Replay while the world and the draw were light.
- The jukebox's worker (since 13b-3): the milliseconds it spent
  decoding, and reading the card, while the frame ran. The worker
  preempts the game on core 0, so this time is also inside whichever
  phase it interrupted. Only the decode is CPU time
  (`new3ds-mode.md`).
- citro3d's own times: the CPU's from C3D_FrameBegin to C3D_FrameEnd,
  and the GPU's. The GPU's runs from C3D_FrameEnd, where it starts its
  clock, to the queue's end. Since the race's frame goes to the GPU in
  parts by default (`GpuSends`, TASKS 57), the GPU has done part of the
  frame by then, and this is only what is left after C3D_FrameEnd. The
  frame rate and the GPU wait are the measures then; "GpuSends 0"
  gives the whole time back.
- Retail's two rates, as the HUD would print them.

Since 13b-4 a `models:` line follows each `frame:` line, with
`render_model`'s counts for the second (`draw-cuts.md`):

    models: view 306 models, 988 batches at once, 22 lit, 33 held,
    50588 words; envmap 121 models, 517 batches at once, 0 lit, 62
    held, 22772 words

- **view** is the player's view, and **envmap** the faces the envmap
  drew. Since 11g-2e a third half, **mirror**, is the rear-view mirror's
  view. Each is a mean a frame: the models rendered, the batches drawn
  in the model's own call, the lit batches, the batches held for the
  lists, and the GPU command words the models wrote.
- It has no times. A tick read is an SVC, and timing each model's parts
  cost 5 ms a frame on Azahar.
- Since 13b-4f each half ends with its batches' indices, three a
  triangle (`63274 words, 96333 indices`).

The milliseconds are exact: 294912 EE ticks to the millisecond, not
bGetTickerDifference's 300000.

At boot the log has a `console:` line: the model, whether it is a New 3DS,
whether the speedup was asked for, the memory type, the memory grant, the
heap, and core 1's time limit. Since 13b-3 a `clock:` line follows it,
and out of a race the jukebox has a line of its own every five seconds
(`new3ds-mode.md`).

## Checking it

    python tools/mainloop_check.py
    python tools/mainloop_check.py --mutate

The model runs CalculateFrameRate and the two times out of the image,
with the image's bGetTickerDifference. The harness runs `mainloop.c` and
`edisplay.c`. After each op both print the four kept numbers, the ten
ticks, the two times and RealTimeFrames.

The script covers:

- the two times, from 0 through both ends of a word, past 2^24 where the
  conversion rounds;
- frames at 30, 20 and 60 a second, kept every eight sixtieths;
- the floors: all wait, a wait longer than the frame, a GPU time of 0,
  below 0, and 0.1 either side;
- bit 3 of the frame count, with other bits changing alone, and negative
  counts;
- each other field off the frame's end, so only LimitFrameRate counts;
- the counter's wrap, a second, 14 and 15 s, a still frame and backwards
  ones;
- a 400-op random walk.

The result is 11 scenarios, 4195 ops, 5097 lines, 0 differ. The
mutation pass ran 46 mutations and caught all 46. `hudrender_check`'s
`debug-fps-rounded` now rounds PreviousCpuFrameRate, and it is caught.

`frameprof.c` has no checker, since nothing in either image is like it.
It only adds and prints.

## On Azahar

The race on track 12, holding the gas, at Speed 100%
(`out/azahar_13b2b`):

- The boot's line: `console: New 3DS XL (model 4), New 3DS, speedup
  asked, memory type 6, grant 126976KB, heap 49152KB, linear 76420KB,
  core 1 limit 80%`.
- 18 to 20 frames a second. Frames of 50 ms on the straight; 54 to 56 ms
  where the world takes 4 to 7 ms.
- **The draw is the frame.** It takes 44 to 46 ms of the 50:

  | Stage | ms |
  |---|---|
  | cull | 15 to 18 |
  | envmap | 10 to 13 |
  | bottom | 5.3 |
  | hud | 4.7 to 5.4 |
  | cars | 4.3 to 4.6 |
  | scenery | 0.9 to 1.8 |
  | sky | 0.8 |
  | submit | 0.3 |
  | prep | 0.1 |

  The world takes 2 to 7 ms. Sound, flow, race, cameras and loads each
  take 0.1 ms or less.
- citro3d's CPU time, 44 to 46 ms, matches the draw. Its GPU time is 0.7
  to 0.8 ms, and the wait for the GPU 0.0. Azahar's GPU takes almost no
  emulated time over a frame, so the GPU's numbers mean little there.
  Retail's G reads 1362.
- Retail's C reads 15 to 21, as the HUD would show it. The kept value
  comes from one frame every eight sixtieths, so it jumps.

Azahar's CPU clock is a count of instructions, not a New 3DS's. So the
proportions are what count.

The table's "cull" is the models' render (see the stages, above). The
13b-3 build, which names the stages rightly, on the same race
(`out/azahar_13b3b`):

| Stage | ms |
|---|---|
| models | 12.6 to 17.8 |
| envmap | 7.8 to 10.0 |
| bottom | 5.3 to 5.4 |
| hud | 4.7 to 4.8 |
| cars | 4.4 to 4.6 |
| cull | 2.2 to 2.9 |
| scenery | 0.9 to 1.8 |
| sky | 0.8 |
| submit | 0.3 |
| prep | 0.0 to 0.1 |

Frames of 50.1 ms on the straight, and 52 to 54.5 where the world takes
4 to 4.7 ms. The jukebox reads 0.00: no music plays in a race
(`new3ds-mode.md`).

The cull itself is cheap. The models' render and the envmap are more
than half the frame (25 of 50 ms), and step 13b-4 starts on the models.

13b-4's cuts, and the frames after each, are in `draw-cuts.md`. After
13b-4e the race on Azahar runs at 27.5 to 30 FPS, with a draw of 23 ms.

## The cars stage's parts (Session 53)

The `cars:` line follows the models'. It gives the cars
carrenderinfo_render drew past its cull, a frame, and the milliseconds
of each part of the player's view's cars stage:

- **setup:** the cull, the light context, the flares and the driver.
- **shadows:** the hull's and the grid's, built and put on the lists.
- **body:** the body, the mirrors, the plates and the scuffs.
- **wheels:** the tyres, their blur, the brakes and the wipers.
- **lists:** the solid list and both alpha lists, which draw the
  shadows' strips, the held batches and the sprites.

The mirror's cars are left out of the parts: the mirror has its own
stage. The models' line gives each view's lit batches' words in
brackets after its words.

On track 45 at the start, with eight cars in view: setup 0.2, shadows
4.1, body 3.4, wheels 3.0, lists 7.4 ms. The 143 lit batches wrote 453
words each, about half the view's 127,676.

## The sends (TASKS 65, Session 105)

Since TASKS 57 a race's frame goes to the GPU in five parts
(`hangwatch_gpu_send`, `draw-cuts.md`). A send is the split, the
linear heap's flush, and the list's add to the GX queue and the queue's
run. The flush and the queue are timed apart, and the `sends:` line
follows the cars':

    sends: 5.0 a frame; flush 0.12, queue 0.04, worst 0.10

- **a frame:** the parts sent, five in a race.
- **flush:** the milliseconds a frame in the flushes.
- **queue:** the milliseconds a frame in `GX_ProcessCommandList` and
  `gxCmdQueueRun`, which can send GSP its trigger.
- **worst:** the longest single send in the second, both together.

The send is not in a stage of its own: each is inside the stage it
ends. Those are mirror (the envmap's), sky (the mirror's), models (its
own), bottom (the top screen's) and submit (the last).

**Why.** The user's device log of 3545f0e (track 31) has one slow
second at world 186 s, 10.7 FPS after 23.1, then 20.2. The draw was
70.5 ms where it was about 30: mirror 17.3, sky 13.0, models 15.8 and
bottom 13.9, each about 10 ms over the seconds either side, and every
other stage as before (envmap 2.9, scenery 1.5, cars 3.2, hud 0.9).
Those four are the stages a mid-frame send ends. The models drawn, the
words, the flares, the effects and the sprites were as in the seconds
around it. The same corner on lap 2 ran at its usual rate, and the
helicopter flies as close at other places without a dip. Only submit,
which holds the last send and `C3D_FrameEnd`'s own flush, stayed at
0.3 ms.

A send's flush was a GSP request: `GSPGPU_FlushDataCache` asks GSP's
thread on the system core to call `svcFlushProcessDataCache` on the
range for us, and waits. Since TASKS 65 a send makes that call itself
(`hangwatch.c`, `flush_heap`). The kernel's work is the same, on the
same range, with no wait on GSP's thread. The CIA's exheader allows the
call (`app.rsf`, `FlushProcessDataCache: 84`, checked in the built CIA's
ACI and AccessDesc). A 3DSX from a homebrew launcher still asks GSP: its
host title might not allow the call, and a call not allowed ends the
app. A failed call goes back to GSP's for good, and says so in the log,
as does the first send ("gpu sends: the linear heap flushed by the
kernel"). "KernelFlush 0" asks GSP in the CIA too.

Whether GSP's thread was what the sends waited on is not proven. The
next device log's `sends:` line says: a slow second with the flush high
and the kernel doing it would put the wait in the kernel's flush. Azahar
does no cache work for the call (its `FlushProcessDataCache` returns
success), so it cannot tell.

## The sampler (TASKS 46, Session 130)

The stages say how long the models take, not where in a model the time
goes: 10.7 ms for 624 models and 1,394 batches a frame in the device's
slow seconds (2026-10-18 log), 17 us a model. Azahar's numbers are no
guide here. Its models stage is as long, 12.5 ms for 620, but its GPU
runs inside the send that ends the stage, and its sampling profiles were
of a start with few models. A system tick read is an SVC, so timing a
model's parts would cost several a model.

So `coresample.c` samples. The game's thread stores a byte where each
part starts: `CoreSampleStage` at the waits, at `frameprof_begin_draw`,
at each `FRAMEPROF_STAMP` (the next stage's start) and after
`C3D_FrameEnd`; `CoreSamplePart` in `render_model` (the solid, the
matrix, the batches, a lit batch's lighting), in `georender.c` (the
bind, `set_model`, a batch's pass and combiner, its clusters, the draw)
and in `hangwatch_gpu_send`. A part runs until the next one starts, and
the draws set none again at their ends. A thread on the third core reads
the two bytes every 200 us and counts each pair, so the game's core does
nothing more than the stores.

"CoreSample 1" in `nfshp2_config.txt` starts the thread (off by
default), and with "DebugLog 1" each second's frame lines are followed
by two more:

    samples: 4870; stages other 12.1% waits 20.3% cull 7.0% ...
    samples, models: none 3.1% solid 9.0% matrix 2.2% batches 8.0% ...

- **stages:** each stage's share of the second's samples. "other" is
  outside the draw: the main loop's phases and the draw's prep.
- **samples, stage:** for the envmap, models, scenery and cars stages,
  each part's share of that stage's samples: times the stage's
  milliseconds, the part's. "none" is the stage's own code, the models'
  loop over the cull's list among it.

On an Old 3DS, or if the thread cannot be made, the log says "no third
core, no samples" and there are no sample lines.
