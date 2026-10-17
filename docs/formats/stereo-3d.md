# Stereo 3D (TASKS 59)

The PS2 has no stereo picture, so this is the port's own. The 3D slider
alone sets it, and there is no option for it. The user set the scope on
2026-10-16: 3D in the game and the movies only. The menus, the title
screen, the loading screens, the pause and the results are one image for
both eyes. With no image drawn for the right eye, the screen's 3D is off
and so is the slider's light. After their first test on a 3DS the same
day, the movies went back to flat too (see "The movies").

What the slices cover:

- **59a**, the race's world for two eyes. Done, and checked in Azahar.
- **59b**, the screen-space effects at their depth: the effects' sprites
  and the sun. Done; the sprites are checked in Azahar, the sun is not
  (see below). The light flares were already strips, so 59a covered
  them.
- **59c**, the full-screen movies, behind the screen. Done, then taken
  back at the user's word: they flickered on the 3DS.
- **59d**, the race's depth made comfortable: nothing in front of the
  screen, a fixed convergence, a smaller budget, the sky at the horizon.
  Done, and checked in Azahar.

## What is in 3D

`main.c`'s `raceIn3D` lists the race coordinator's states that are drawn
for two eyes:

| State | 3D |
|---|---|
| RCSTATE_CAMERA_FLYBY 1, PRERACE 2, RACE_IN_PROGRESS 3 | yes |
| INSTANT_REPLAY 4, AUTO_REPLAY 5 | yes |
| AI_DEMO_MODE 8, REPLAY_DEMO_MODE 9 | yes |
| NONE 0, PAUSE 6, POSTRACE 7 | no |

`stereo3d_race_wanted` also needs four things. Without all of them the
frame is flat:

- the slider above 0;
- the right eye's target, made at boot;
- the stereo shaders, which `georender.c` checks at boot;
- a frame sent in parts (`hangwatch_gpu_sending`). Each eye's clear goes
  between the lists, so a timing frame is never in 3D.

The HUD, the rear-view mirror, the bottom screen and the song box are
drawn once. They sit on the screen's plane, and both eyes show them at
the same place. The effects' sprites (smoke, dust, sparks) and the sun
are in the screen's pixels too, but they take the eye's shift for their
depth; see "The screen's own draws" below. The movies are flat.

## The eye's term

The vertex shaders `geosolid.v.pica` and `geolit.v.pica` each get a copy,
made by a Makefile rule (`%_st.v.pica`). The copy:

- writes the position to `r1` instead of `outpos`;
- adds `outpos = r1 + stereo[0] * max(r1.w + stereo[1], 0)`, in three
  instructions (`add`, `max`, `mad`);
- declares `.fvec stereo[2]`;
- renames its procedures with `_st`, because picasso's names belong to
  the whole shbin.

The shbin then holds four DVLEs: 0 is geosolid, 1 is geolit, and 2 and 3
are their stereo copies. Picasso shares uniforms across a shbin by name,
so the copies keep every register the plain programs have. `stereo` is
the one new uniform, and it lands at c25–c26, which nothing else uses.
`georender.c`'s `init_stereo` checks each shared uniform's register
against the plain program's. On any mismatch it frees the copies, and the
game stays flat.

While `georender_set_stereo` is on, the world binds the copies
(`bind_mesh`, `bind_lit` and `bind_strips`), and so do the sprites and
the sun's quads. The other screen quads (the mirror, the HUD's polys)
and the sphere map's fold keep the plain programs. Flat frames never
bind the copies, so they cost nothing.

`stereo3d.c`'s `eye_term` writes the two registers straight into each
eye's command list: the config word, then eight data words in w, z, y, x
order. citro3d never sets c25–c26 itself, so its uniform uploads never
overwrite them. One write stands for all of that eye's lists.

On clip axis y (`Mtx_PerspTilt` turns the view's x into clip y, the
framebuffer's 400 pixels):

```
a           = side * AXIS_SIGN * shift
stereo[0].y = a
stereo[1].y = -convergence
y'          = y + a * max(w - convergence, 0)
```

A vertex at depth `w` moves by `a * max(1 - convergence / w, 0)` of the
screen's half-width:

- none at the convergence, or nearer;
- `a` at the horizon.

So nothing comes out of the screen. The HUD and the mirror are on the
screen's plane, in front of the whole world.

Its values:

- **`shift`**: `slider * 5 px / 200`. At the slider's top, the two images
  are 10 pixels apart at the horizon, and nothing is further apart.
- **The convergence**: a fixed 3 m, the same in every camera. The chase
  camera has the player's car 4.2 m off (the 3DS's log), so the car sits
  just behind the screen.
- **`AXIS_SIGN`**: −1. The right eye's far things must sit right of the
  left eye's. Azahar's side by side showed +1 put the horizon 10 pixels
  the wrong way.

**The sky** is the furthest thing in the picture whatever its dome's
size. Around the main view's sky (`trackview.c`, `stereo3d_race_far`)
the shared lists set `stereo[1]` to 0, which puts every depth at the
horizon's shift, and then back to the convergence. `stereo[1]` is the
same for both eyes, so the change can sit in the lists both eyes run.

### Why: the first test on a 3DS

59a's term put the car's depth on the screen's plane and let anything
nearer come out of the screen, by `a * (1 - convergence / w)` with no
limit. The user tried it on their 3DS on 2026-10-16: "Depth is not
comfortable at all".

- The near road, the walls and the poles going past the screen's edges
  came out of it by up to 9 px in Azahar, more the nearer they were.
  Things cut off by the screen's edge in front of it are the classic
  cause of eye strain.
- The world in front of the screen also crossed the HUD, which is on
  it: two depth cues that disagree.
- The convergence followed the car every frame, and went to 12 m in
  the flybys, so the whole picture's depth moved.

59d follows the usual rules for comfortable stereo instead: the world
behind the screen only, a convergence that does not move, and a small
budget, 10 px at most.

## The screen's own draws

The sprites and the sun's quads come in the top screen's pixels, with
no view depth for the term to work on: their clip w is 1. In 3D each
vertex is sent as (x d, y d, d) instead, d being a view depth, and the
screen's mapping is changed to match (`screen_for_depth`):

- its third column moves to the fourth's place, and the fourth is left
  empty, so the position comes out as d times the flat one, and its w
  is d;
- the divide by d puts the vertex back where it was, and the term then
  shifts it by `a * max(1 - convergence / d, 0)`, as it does the world.

For each kind:

- **A sprite's corner** has its PICA depth z, from the GS Z
  (`sprite_depth`). Its d is the view's depth there, as the perspective
  maps it: `d = near far / (near + z (far - near))`. The z row gives the
  depth back from d: `-z d = near (d - far) / (far - near)`, so the depth
  test is the flat one's.
- **The sun's quads** (`render_epoly`, `SunPoly`) take d = the far
  plane, so the glare stays round the sun in both eyes. Their depth is
  `C3D_DepthMap`'s constant, as when flat.

Flat, both draw as before: the plain program and the screen's mapping.

## The movies

59c (c9614c5) put the five movies that fill the top screen behind it:
the EA logo, the Black Box Games logo, the intro, the making-of and the
reward, 8 px apart at the slider's top. On the user's 3DS they
flickered, and the user asked for them flat: "There is flicker on the
movies, I think remove 3D support for movies." 59d takes 59c's code out
again. The flicker was not looked into, since the movies are flat now.

## The frame on the GPU

The race's view is drawn once. Its lists go to the GPU twice:

1. The mirror's view, as when flat.
2. The right eye's clear: its own colour, and the top screen's depth.
3. A list holding the right eye's target and its term.
4. The view's lists, W1 and W2, split at the models' send, followed by
   the HUD. hangwatch keeps each list it sends (`hangwatch_gpu_keep`).
5. The left eye's clear: the top screen's colour, and the shared depth.
6. A list holding the left eye's target and its term. It was made in
   step 3's time and flushed with the view's first send.
7. The kept lists again (`hangwatch_gpu_resend`), with no flush.
8. The bottom screen, then the transfers.

The left eye comes last, so the depth buffer and the capture both read
the left eye's image. Before the view, `hangwatch_gpu_state_again` marks
all citro3d state dirty except the framebuffer, so the view's lists set
everything they read except the target. That way they draw the same
after either eye's list.

VRAM holds the right eye's colour, an RGBA8 240x400 target (384 KB),
and no more. The right eye shares the top screen's D24S8 depth buffer,
which is cleared between the eyes. The target is made at boot, before
textures take VRAM. When there is no room, the log says
`stereo 3D: no VRAM for the right eye's target; flat`.

## The swap

The swap is citro3d's. Its queue-finish callback swaps every screen
that `C3D_FrameEnd` marked. `C3D_FrameEnd` queues the targets'
transfers in this order: bottom screen, right eye, left eye. It marks
the top screen right after queueing the right eye's transfer.

The race's sends leave the queue running. libctru starts anything
added to a running, idle queue at once (`gxCmdQueueAdd`). So the queue
could finish right after the right eye's transfer, which swapped the top
screen too early. The left eye's transfer then landed in the other
buffer and swapped it again. That was two swaps a frame: Azahar counted
59 a second while the game ran at 30. Every other vertical blank showed
a stale left eye (the LOADING screen) and a black right eye. The user
saw it flicker on 2026-10-16.

`__wrap_C3D_FrameEnd` does three things first:

- sends anything drawn since the last send;
- lets the queue go with `hangwatch_gpu_queue_rest`, only when it has
  finished everything. That leaves the queue as `C3D_FrameBegin` does,
  so `C3D_FrameEnd`'s transfers wait for its run. Stopping a busy queue
  instead loses the interrupts of what it still has out, and the next
  frame's wait would never end;
- queues the left eye's transfer itself and clears that target's
  `used`.

After that, the top screen is marked only after both eyes' transfers
are queued, so any finish after the mark comes after both. The wrapper
also turns the screen's 3D on (`gfxSet3D`) when the right eye's target
was drawn this frame, and off when it was not.

## Checked in Azahar

The test sets `[Layout] render_3d=1` (side by side) and `factor_3d=100`
in qt-config.ini, then restores them. The shots compare the two halves
row band by row band: the right image's x minus the left image's.

59a's shots:

| Shot | Far trees | Horizon | Car | Near road |
|---|---|---|---|---|
| Race, 3D | +10 to +11 | +10 to +11 | 0 to +5 | 0 to −9 |
| Pause | 0 | 0 | 0 | 0 |
| Slider at 0 | 0 | 0 | 0 | 0 |

59d's shots (track 12, gas held, four race shots):

| Where | Right minus left |
|---|---|
| The far trees, the top of the picture | +9 |
| The horizon, the cabin across the road | +8 to +9 |
| The roadside at the horizon's height | +8 |
| The player's car | +3 to +4 |
| The near road | 0 to +4 |
| The mirror, the speedo, the song box | 0 |

Nothing is in front of the screen. The LOADING screen before the race
and all 32 shots of the boot walk, the EA logo and the intro among
them, differ by 0.00 between the eyes.

59b's shots (track 12, gas held): the chimneys' smoke, which is
sprites, sits at +10 like the chimneys and the roof under it. Before
59b it was at 0. The song box stays at 0.

The sun was drawn in 3D (4 quads, none failed) but never seen: in every
test it was behind the trees (track 12) or a hill (track 31), with at
most 171 of its 1,024 test pixels sky and its alpha 6 of 128. Its path
is the sprites' mapping with a fixed d, so it should sit with the
horizon, at +11 or so.

Before 59c, the boot flow's 32 shots differed by 0.00 between the
eyes. These cover the loading screen, the language and autoload screens,
the movies, the title, the main menu, Be A Cop's setup and the options.

In 59a, with the swap fix,
the game logs 30 frames a second, Azahar's App FPS is back to the flat
game's (21 to 30 under load), and none of seven 3D race shots has a
stale eye.

On the user's New 3DS XL (2026-10-16, 59c's build) the frame rate in
3D was "pretty much the same" as flat.

Not checked yet:

- the sun's shift, in a shot where it shows;
- the sky's shift: the forest's sky is in gaps too small to measure;
- whether 59d's depth is comfortable on a real 3DS. If it is not, the
  fallback is no 3D at all, with the slider doing nothing.
