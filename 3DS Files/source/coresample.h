// coresample -- where the game's thread is, sampled from the New 3DS's
// third core (TASKS 46).
//
// The device's frame lines time the draw by its stages, and the models
// stage is the longest where the frame rate drops: 10.7 ms for 624 models
// and some 1,390 batches a frame (2026-10-18 log), 17 us a model. Nothing
// says where in a model that goes. Azahar's profiles cannot: its GPU runs
// inside the sends, and they were of a scene with few models. Timing the
// parts with the system tick would cost an SVC a read, many a model.
//
// So the game's thread says where it is, with a byte store at each part's
// start: CoreSampleStage at the draw's stages (frameprof.h's stamps, the
// waits and the frame's end), and CoreSamplePart in the models' draw
// (trackview.c's render_model, georender.c's batches, the sends). A
// thread on the third core reads the two every 200 us or so and counts
// each pair. The game's core does nothing more than the stores. Once a
// second, after the frame's lines, the log has each stage's share of the
// samples and, for the stages that draw models, each part's share of the
// stage's.
//
// Off unless the config says "CoreSample 1" (configitems.h), and its line
// needs "DebugLog 1". Only with a third core: an Old 3DS has none.

#ifndef CORESAMPLE_H
#define CORESAMPLE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Where in the frame: outside the draw (the main loop's phases and the
// draw's prep), the waits for the blank and the GPU, then frameprof's
// stamped stages in their order, and the submit.
enum {
    CS_STAGE_OTHER,
    CS_STAGE_WAITS,
    CS_STAGE_CULL,      // frameprof's first stamped stage
    CS_STAGE_ENVMAP,
    CS_STAGE_MIRROR,
    CS_STAGE_SKY,
    CS_STAGE_MODELS,
    CS_STAGE_SCENERY,
    CS_STAGE_CARS,
    CS_STAGE_HUD,
    CS_STAGE_BOTTOM,
    CS_STAGE_SUBMIT,
    CS_STAGES
};

// What in a draw. A part runs until the next part's start.
enum {
    CS_PART_NONE,       // none of these: the stage's own code
    CS_PART_SOLID,      // render_model: the solid found, its table followed
    CS_PART_MATRIX,     // the model's matrices
    CS_PART_BATCHES,    // its batches' flags, uses and lists
    CS_PART_BIND,       // georender: the program, the buffer, the checks
    CS_PART_MODEL,      // set_model: the products, the planes, the uniforms
    CS_PART_PASS,       // a batch's pass and combiner
    CS_PART_CULL,       // its clusters against the view
    CS_PART_DRAW,       // the draw: citro3d's state and the draw's words
    CS_PART_LIT,        // a lit batch: its lighting, its uniforms
    CS_PART_SEND,       // a part of the frame sent to the GPU
    CS_PART_SKIN,       // a driver's vertices posed by its bones
    CS_PARTS
};

extern volatile uint8_t CoreSampleStage;
extern volatile uint8_t CoreSamplePart;

// The sampler's thread on the third core, once; false, with a line in the
// log, when there is none to be had. `log` is the game's.
bool coresample_start(void (*log)(const char* fmt, ...));

// Ends the thread and waits for it, before exit() frees its stack
// (main.c's atexit, as threadguard_stop).
void coresample_stop(void);

// The counts since the last line, as one: false when there are none.
bool coresample_line(char* buf, size_t n);

#endif
