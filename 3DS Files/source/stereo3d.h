// stereo3d -- the top screen for two eyes (TASKS 59).
//
// The 3D slider alone sets the depth; there is no option for it, as there
// is none on the PS2. Only the race is drawn in 3D: its world, its NIS
// and its flybys. The menus, the title, the pause, the results and the
// loading screens are one image for both eyes (the user, 2026-10-16), and
// with nothing drawn for the right eye the screen's 3D is off, so its
// light is too. The movies are flat as well: the user saw them flicker in
// 3D on their 3DS (59c, taken back on 2026-10-16).
//
// The race's view is drawn once (docs/formats/stereo-3d.md). Its lists go
// to the GPU twice: for the right eye onto a target of its own, then for
// the left onto the top screen's, each after its eye's clear. The depth
// buffer is the top screen's for both, cleared between them: VRAM has
// room for the right eye's colour and no more. Each eye's lists start
// with its target and its term, which the world's shaders add to each
// vertex (georender_set_stereo): the eye's shift, the most at the horizon
// and none at the convergence, a fixed 3 m, or nearer. The world is all
// behind the screen, and the HUD and the mirror, on its plane, in front.
// The effects' sprites take the term for their depth, and the sun and the
// sky for the horizon.
//
// A frame is drawn for two eyes only when its lists are sent in parts
// (hangwatch.h's sends: the clears have to go between them), so never in
// a timing frame.

#ifndef STEREO3D_H
#define STEREO3D_H

#include <stdbool.h>
#include <stdint.h>

#include <citro3d.h>

// At boot, after the top screen's target: the right eye's, over its depth
// buffer, with the same transfer to the screen. False when VRAM has no
// room: the game is flat then.
bool stereo3d_init(C3D_RenderTarget* top, uint32_t transferFlags);

// Whether this race frame is drawn for two eyes: `scene` (the race is in
// a state that is), the slider up, the frame sent in parts and the eyes
// made.
bool stereo3d_race_wanted(bool scene);

// In place of the top screen's clear and C3D_FrameDrawOn before the
// race's view, when stereo3d_race_wanted: the right eye's clear, target
// and term sent, the left's made for later, and the world's shaders
// switched to the eye's.
void stereo3d_race_begin(uint32_t clear);

// Between race_begin and race_end, around the main view's sky: with `on`
// the world's draws take the horizon's shift at any depth, as the sky's
// dome is the furthest thing in the picture whatever its size; off, the
// convergence again. Nothing outside the eyes' frame.
void stereo3d_race_far(bool on);

// After the HUD's send: the left eye's clear, its target and term, and
// the view's lists again. The top screen's target is current after it.
void stereo3d_race_end(uint32_t clear);

#endif
