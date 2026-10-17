// stereo3d -- the top screen for two eyes (stereo3d.h).

#include "stereo3d.h"

#include <3ds.h>
#include <citro3d.h>

#include "georender.h"
#include "hangwatch.h"

// citro3d's own (base.o): the state its next draw would send, sent now.
// Each eye's list sets its target with it.
void C3Di_UpdateContext(void);

// The eye's shift at the horizon at the slider's top, in pixels across the
// top screen's 400: the two eyes' images are twice this apart there, and
// nothing is further apart. The user, on their 3DS (2026-10-16), could
// not stand 12 with the near road out of the screen.
#define SHIFT_PX 5.0f

// The depth on the screen's plane, in the view's units (metres), the same
// in every camera: nothing nearer moves, so nothing comes out of the
// screen, past its edges or through the HUD. The chase camera has the
// player's car 4.2 m off (the device log, 2026-10-16), just behind it.
#define CONVERGENCE 3.0f

// The clip axis across the screen: Mtx_PerspTilt turns the view a quarter
// so that the view's x is clip's y, the framebuffer's 400 (trackview's
// projection). And which way is the right eye's: far things move to the
// right in the right eye's image, which is clip's -y (Azahar's side by
// side, 2026-10-16: +y put the horizon 10 pixels the other way).
#define AXIS      1
#define AXIS_SIGN -1.0f

static C3D_RenderTarget* s_left;
static C3D_RenderTarget* s_right;
static bool              s_drawing;     // between race_begin and race_end
static u32*              s_leftList;    // the left eye's target and term
static u32               s_leftWords;
static bool              s_leftMade;

bool stereo3d_init(C3D_RenderTarget* top, uint32_t transferFlags)
{
    s_left  = top;
    s_right = C3D_RenderTargetCreate(top->frameBuf.width,
                                     top->frameBuf.height,
                                     top->frameBuf.colorFmt, -1);
    if (!s_right) {
        return false;
    }
    C3D_FrameBufDepth(&s_right->frameBuf, top->frameBuf.depthBuf,
                      top->frameBuf.depthFmt);
    C3D_RenderTargetSetOutput(s_right, GFX_TOP, GFX_RIGHT, transferFlags);
    return true;
}

bool stereo3d_race_wanted(bool scene)
{
    return scene && s_right && osGet3DSliderState() > 0.0f
        && georender_stereo_uniform() >= 0 && hangwatch_gpu_sending();
}

// The eye's term, into the list being made: clip + stereo[0] *
// max(w + stereo[1], 0) on the axis across the screen. At depth w the
// vertex moves by side * shift * max(1 - convergence / w, 0) of the
// screen's half-width: none at the convergence and nearer, `shift` at the
// horizon. The registers are the uniform's own, which nothing sets
// through citro3d, so its uploads never send them: each eye's value
// stands for all its lists. A C3D_FVec is w, z, y, x in memory, as the GPU
// takes a float uniform's four words.
static void eye_term(float side, float shift)
{
    C3D_FVec v[2];

    v[0] = FVec4_New(0.0f, 0.0f, 0.0f, 0.0f);
    v[1] = FVec4_New(0.0f, 0.0f, 0.0f, 0.0f);
    v[0].c[3 - AXIS] = side * AXIS_SIGN * shift;
    v[1].c[3 - AXIS] = -CONVERGENCE;
    GPUCMD_AddWrite(GPUREG_VSH_FLOATUNIFORM_CONFIG,
                    0x80000000u | (u32)georender_stereo_uniform());
    GPUCMD_AddWrites(GPUREG_VSH_FLOATUNIFORM_DATA, (const u32*)v, 8);
}

// stereo[1] alone, the same for both eyes, so the shared lists can change
// it: a convergence of 0 puts everything at the horizon's shift.
static void convergence_term(float convergence)
{
    C3D_FVec v = FVec4_New(0.0f, 0.0f, 0.0f, 0.0f);

    v.c[3 - AXIS] = -convergence;
    GPUCMD_AddWrite(GPUREG_VSH_FLOATUNIFORM_CONFIG,
                    0x80000000u | (u32)(georender_stereo_uniform() + 1));
    GPUCMD_AddWrites(GPUREG_VSH_FLOATUNIFORM_DATA, (const u32*)&v, 4);
}

void stereo3d_race_begin(uint32_t clear)
{
    float shift = osGet3DSliderState() * SHIFT_PX / 200.0f;
    u32*  list;
    u32   words;

    // The right eye's lists go first: its clear into the queue now, after
    // the mirror's send, then its target and term, sent.
    C3D_RenderTargetClear(s_right, C3D_CLEAR_ALL, clear, 0);
    C3D_FrameDrawOn(s_right);
    C3Di_UpdateContext();
    eye_term(1.0f, shift);
    if (hangwatch_gpu_split(&list, &words)) {
        hangwatch_gpu_send_list(list, words, true);
    }

    // The left eye's target and term, made now and sent after the right
    // eye's view and the left's clear. citro3d is left with the top
    // screen's target as the current one, which the view and the HUD
    // then draw on without sending it: the target is the eyes' alone.
    C3D_FrameDrawOn(s_left);
    C3Di_UpdateContext();
    eye_term(-1.0f, shift);
    s_leftMade = hangwatch_gpu_split(&s_leftList, &s_leftWords);

    // The view's lists send all they read but the target, so they draw
    // the same after either eye's list; the world's batches take the eye's
    // shaders; and each send's list is kept for the left eye.
    hangwatch_gpu_state_again();
    georender_set_stereo(true);
    hangwatch_gpu_keep(true);
    s_drawing = true;
}

void stereo3d_race_far(bool on)
{
    if (s_drawing) {
        convergence_term(on ? 0.0f : CONVERGENCE);
    }
}

void stereo3d_race_end(uint32_t clear)
{
    int kept;

    if (!s_drawing) {
        return;
    }
    s_drawing = false;
    // Anything drawn after the last send, sent and kept with the rest.
    hangwatch_gpu_send();
    kept = hangwatch_gpu_keep(false);
    georender_set_stereo(false);

    // The left eye: its clear after the right eye's lists, the shared depth
    // buffer's with it, then its target and term, then the lists again.
    // The left eye's list was made before the view's first send, whose
    // flush took it; with no send, it is flushed here.
    C3D_RenderTargetClear(s_left, C3D_CLEAR_ALL, clear, 0);
    if (s_leftMade) {
        hangwatch_gpu_send_list(s_leftList, s_leftWords, kept == 0);
    }
    if (kept != 0) {
        hangwatch_gpu_resend();
    }
}

// citro3d's C3D_FrameEnd, linked through this (the Makefile's --wrap): the
// screen's 3D is on for a frame that drew the right eye's image, and off
// for one that did not, before C3D_FrameEnd asks for the right eye's
// framebuffer and the frame is shown. With it off, libctru shows the left
// eye's image alone, and the slider's light is off.
//
// The swap is citro3d's, when its queue ends after C3D_FrameEnd, which
// adds the targets' transfers bottom screen, right eye, left eye, and
// marks the top screen for the swap after the right eye's. The race's
// sends leave the queue running, and one that ended between the eyes'
// transfers swapped the top screen then, and again after the left eye's,
// which went to the other buffer: every other blank showed one stale eye
// and one black (Azahar, 2026-10-16, the LOADING screen's). So the queue
// is let go of when idle, and the left eye's transfer goes first, here:
// any end after the mark is after both eyes'.
void __real_C3D_FrameEnd(u8 flags);
void __wrap_C3D_FrameEnd(u8 flags);

void __wrap_C3D_FrameEnd(u8 flags)
{
    bool stereo = s_right != NULL && s_right->used;
    u32* list;
    u32  words;

    gfxSet3D(stereo);
    // What was drawn since the last send, which C3D_FrameEnd would send:
    // before the left eye's transfer (the HUD's send leaves none).
    if (stereo && hangwatch_gpu_split(&list, &words)) {
        hangwatch_gpu_send_list(list, words, true);
    }
    hangwatch_gpu_queue_rest();
    if (stereo && s_left->used) {
        s_left->used = false;
        C3D_FrameBufTransfer(&s_left->frameBuf, s_left->screen, s_left->side,
                             s_left->transferFlags);
    }
    __real_C3D_FrameEnd(flags);
}
