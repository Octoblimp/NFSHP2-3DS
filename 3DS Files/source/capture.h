// capture -- the top screen as the device drew it, onto the card.
//
// The New 3DS XL drew the race's first view with a dark box on the rock
// wall behind the car and a pale streak up from its roof (2026-10-05), and
// Azahar draws neither: what the device drew can only come from the device.
// When CAPTURE_FLAG is on the card as a race starts, the frame drawn
// CAPTURE_SECONDS in (or as many seconds as the file's first number says)
// and the one after it go next to the logs:
//
//   * nfshp2_cap_colour.bmp, the top screen as that frame left it, the HUD
//     and all;
//   * nfshp2_cap_depth.bmp, its depth buffer, the 24 bits as red (the top
//     8), green and blue;
//   * nfshp2_cap_ids.bmp, the next frame with each of georender's draws in
//     a flat colour that is its number, red its low byte, green its high
//     and blue 0x55: as its own colour alone, unfogged and unblended, and a
//     draw that blends cut to where its alpha shows. What draws after
//     georender, the HUD, draws as it always does;
//   * nfshp2_cap_ids.txt, what each number was: the stage the frame was
//     at, the kind of draw, its vertices, texture and blend; and first the
//     textures' names by their C3D_Tex;
//   * nfshp2_cap_lod0.bmp, the frame after that drawn as the first was,
//     but with every texture read from its level 0 alone, for what the
//     PICA's choice of mip level does to the frame.
//
// The envmap's faces draw as they always do in both (capture_offscreen).
//
// Never otherwise: the writes are a hitch of a second or so, and the frame
// of numbers is seen for a frame. Azahar's capture of the same frame is the
// same files in its sdmc folder, to compare.

#ifndef CAPTURE_H
#define CAPTURE_H

#include <stdbool.h>

#include <citro3d.h>

#define CAPTURE_FLAG    "sdmc:/nfshp2_capture.txt"
#define CAPTURE_SECONDS 6

// Each frame, before C3D_FrameBegin: whether a race is being drawn. A race
// that starts with the flag on the card is armed.
void capture_race(bool racing);

// After C3D_FrameBegin, which waits for the GPU, and before the top
// screen's clear: the last frame's buffers to the card when it was the one,
// and this frame's draws numbered. True when the numbered frame starts,
// for the textures' names to go into the legend first.
bool capture_read(C3D_RenderTarget* top);

// This frame's draws are to be numbered (georender's draws).
bool capture_ids_on(void);

// This frame's draws read their textures' level 0 alone.
bool capture_lod0_on(void);

// Draws into a texture -- the envmap's faces and its fold -- are drawn as
// they always are, neither numbered nor at level 0: a face keeps what it
// drew until it draws again, and the car's reflection would show the
// numbers in the frames after.
void capture_offscreen(bool on);

// The next draw's number, from 1, and a line of the legend for it.
int  capture_next_id(void);
void capture_note(const char* fmt, ...) __attribute__((format(printf, 1, 2)));

#endif
