# Stereo 3D (TASKS 59)

The PS2 has no stereo picture, so this is the port's own. The 3D slider
alone sets it, and there is no option for it. The user set the scope on
2026-10-16: 3D in the game and the movies only. The menus, the title
screen, the loading screens, the pause and the results are one image for
both eyes. With no image drawn for the right eye, the screen's 3D is off
and so is the slider's light.

What the slices cover:

- **59a**, the race's world for two eyes. Done, and checked in Azahar.
- **59b**, the screen-space effects at their depth: the sun, its flares,
  the sprites and the screen quads. These stay on the screen's plane for
  now.
- **59c**, the movies.

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
the same place.

## The eye's term

The vertex shaders `geosolid.v.pica` and `geolit.v.pica` each get a copy,
made by a Makefile rule (`%_st.v.pica`). The copy:

- writes the position to `r1` instead of `outpos`;
- adds `outpos = r1 + stereo[0] * r1.w + stereo[1]`;
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

Only the world binds the copies (`bind_mesh`, `bind_lit` and
`bind_strips`, while `georender_set_stereo` is on). Screen quads, sprites
and the sphere map's fold keep the plain programs. Flat frames never
bind the copies, so they cost nothing.

`stereo3d.c`'s `eye_term` writes the two registers straight into each
eye's command list: the config word, then eight data words in w, z, y, x
order. citro3d never sets c25–c26 itself, so its uniform uploads never
overwrite them. One write stands for all of that eye's lists.

On clip axis y (`Mtx_PerspTilt` turns the view's x into clip y, the
framebuffer's 400 pixels):

```
a          = side * AXIS_SIGN * shift
stereo[0].y = a
stereo[1].y = -a * convergence
y'         = y + a * (w - convergence)
```

A vertex at depth `w` moves by `a * (1 - convergence / w)` of the
screen's half-width:

- none at the convergence;
- `a` at the horizon;
- the other way for anything nearer than the convergence, which comes
  out of the screen.

Its values:

- **`shift`**: `slider * 6 px / 200`. At the slider's top, the two images
  are 12 pixels apart at the horizon.
- **The convergence**: the player's car's depth in the player's view,
  clamped to 2–12 m.
- **`AXIS_SIGN`**: −1. The right eye's far things must sit right of the
  left eye's. Azahar's side by side showed +1 put the horizon 10 pixels
  the wrong way.

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

| Shot | Far trees | Horizon | Car | Near road |
|---|---|---|---|---|
| Race, 3D | +10 to +11 | +10 to +11 | 0 to +5 | 0 to −9 |
| Pause | 0 | 0 | 0 | 0 |
| Slider at 0 | 0 | 0 | 0 | 0 |

The boot flow's 32 shots differ by 0.00 between the eyes. These cover
the loading screen, the language and autoload screens, the movies, the
title, the main menu, Be A Cop's setup and the options. With the fix,
the game logs 30 frames a second, Azahar's App FPS is back to the flat
game's (21 to 30 under load), and none of seven 3D race shots has a
stale eye.

Not checked yet:

- the cost on a real 3DS: the view's lists run twice on the GPU;
- how deep it looks on a real 3DS.
