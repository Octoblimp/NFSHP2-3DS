// previewcomet -- zonecameras.cpp's PreviewComet, the glowing trail the Zone
// Preview draws along its look spline, and the four PreviewCometParams the
// file's static initializer fills. The addresses are retail's.
//
// While the Zone Preview's camera runs out along the road, a ribbon of
// quads rises off the route ahead of it: its head and tail are two Graphs
// of the run's progress, its width a third along the ribbon, its texture
// scrolls with the progress and its colour runs from Colour0 at the head
// end to Colour1 at the tail, fading out once the head has reached the end
// of the route. The emitters of the params' effect group ride at the
// ribbon's first point, on FrameEffects' auto list, until then.
//
// Ported: the constructor (0x001614c8), the destructor (0x00161678),
// Enable (0x00161720), Disable (0x001617a0), Render (0x00161820) and the
// static initializer _GLOBAL_$I$ZonePreviewCometParams (0x00167208), as C
// initializers. Spline::GetSecondDerivative (0x00189ad8), which only Render
// calls, is here too until spline.c takes it.
//
// Written up in docs/formats/preview-comet.md; checked on retail's image by
// tools/previewcomet_check.py.

#ifndef PREVIEWCOMET_H
#define PREVIEWCOMET_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "graph.h"
#include "spline.h"

struct AcidEmitter;
struct TextureInfo;
struct eView;

// 208 bytes, the demo's .mdebug record (type#961); retail's initializer
// writes the same offsets. The three curves are knees of Graphs over the
// run's progress, 0 to 1 (Head, Tail), or over the ribbon, 0 at the head
// end to 1 at the tail (Width).
typedef struct PreviewCometParams {
    const char *EmitterGroupName;           //   0  the emitters' group
    int32_t     nPreviewCometSegments;      //   4  steps; a quad per two
    float       fPreviewCometTextureDV;     //   8  v scrolled per unit t
    uint32_t    nPreviewCometTexture;       //  12  the texture's name hash
    float       fPreviewCometLineWidth;     //  16  full width at Width 1
    float       fPreviewCometLineHeight;    //  20  added to every z
    float       fPreviewCometAltitude;      //  24  added to the spline's z
    float       fPreviewCometLateralCoeff;  //  28  bank per sideways pull
    int32_t     nPreviewCometWidths;        //  32
    bVector2    vPreviewCometWidth[5];      //  36
    int32_t     nPreviewCometHeads;         //  76
    bVector2    vPreviewCometHead[5];       //  80  [1].x ends the emitters
    int32_t     nPreviewCometTails;         // 120
    bVector2    vPreviewCometTail[5];       // 124
    int32_t     pad164[3];                  // 164  bVector4's alignment
    bVector4    vPreviewCometColour0;       // 176  r, g, b, a at the head
    bVector4    vPreviewCometColour1;       // 192  and at the tail
} PreviewCometParams;                       // 208

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char previewcometparams_layout_check[
    (offsetof(PreviewCometParams, nPreviewCometSegments) == 4
     && offsetof(PreviewCometParams, nPreviewCometTexture) == 12
     && offsetof(PreviewCometParams, fPreviewCometLateralCoeff) == 28
     && offsetof(PreviewCometParams, vPreviewCometWidth) == 36
     && offsetof(PreviewCometParams, nPreviewCometHeads) == 76
     && offsetof(PreviewCometParams, vPreviewCometHead) == 80
     && offsetof(PreviewCometParams, nPreviewCometTails) == 120
     && offsetof(PreviewCometParams, vPreviewCometTail) == 124
     && offsetof(PreviewCometParams, vPreviewCometColour0) == 176
     && offsetof(PreviewCometParams, vPreviewCometColour1) == 192
     && sizeof(PreviewCometParams) == 208) ? 1 : -1];
#endif

// 48 bytes, from what the constructor writes; the demo's .mdebug record
// (type#2731) is 44, without the flag at 16, and has its Graphs at 20.
typedef struct PreviewComet {
    Spline             *pLookSpline;        //   0  the caller's
    PreviewCometParams *pParams;            //   4
    struct AcidEmitter *pEmitters;          //   8  new[], or NULL
    int32_t             nEmitters;          //  12
    int32_t             Enabled;            //  16  on FrameEffects' list
    struct TextureInfo *pCometTexture;      //  20
    Graph               Width;              //  24  over the ribbon
    Graph               Head;               //  32  over the run
    Graph               Tail;               //  40
} PreviewComet;                             //  48

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char previewcomet_layout_check[
    (offsetof(PreviewComet, nEmitters) == 12
     && offsetof(PreviewComet, Enabled) == 16
     && offsetof(PreviewComet, pCometTexture) == 20
     && offsetof(PreviewComet, Width) == 24
     && offsetof(PreviewComet, Head) == 32
     && offsetof(PreviewComet, Tail) == 40
     && sizeof(PreviewComet) == 48) ? 1 : -1];
#endif

// The static initializer's four (0x00167208, the demo's 0x001629a0, the
// same code): the Zone Preview's at 0x002fa9f0, and the visible driving
// line's three after it, 208 bytes apart, which nothing ported reads yet.
// Plain C initializers: no call at startup.
extern PreviewCometParams ZonePreviewCometParams;
extern PreviewCometParams DrivingLineCometParamsEasy;
extern PreviewCometParams DrivingLineCometParamsMedium;
extern PreviewCometParams DrivingLineCometParamsHard;

// __12PreviewCometP6SplineP18PreviewCometParams, 0x001614c8. The three
// Graphs over the params' knees; then one AcidEmitter (new[], "ZonePreview
// Emitters", 192 bytes each) for every emitter data of the params' group,
// each given its data and turned ON; then Enable, and the texture,
// GetTextureInfo(nPreviewCometTexture, 1, 0). `look` and `params` stay the
// caller's.
void preview_comet_init(PreviewComet *c, Spline *look,
                        PreviewCometParams *params);

// _$_12PreviewComet, 0x00161678, as the mover calls it (flags 2, so not
// freed): Disable, then each emitter destroyed from the last, and the array
// deleted. pEmitters is left as it was.
void preview_comet_destroy(PreviewComet *c);

// 0x00161720 and 0x001617a0, unnamed in the stripped ELF. Each emitter onto
// or off FrameEffects' auto list (0x002ef5e0), the frontend's system, not
// WorldEffects; each does nothing when the flag already says so.
void preview_comet_enable(PreviewComet *c);
void preview_comet_disable(PreviewComet *c);

// Render__12PreviewCometP5eViewf, 0x00161820. `t` is the run out's
// progress, 0 to 1; `view` is not read. A 64-byte identity from the frame
// memory, or nothing at all when the frame memory is out; then the ribbon
// through every other of its nPreviewCometSegments + 1 points, a quad per
// two steps (16 for the Zone Preview's 32), through gEPolyRender3DFn with
// the texture and that matrix. At the ribbon's first point the ON emitters
// take its frame (side, up, along, the point) while t is short of the
// head's second knee, and turn OFF after.
void preview_comet_render(PreviewComet *c, struct eView *view, float t);

// Spline::GetSecondDerivative(bVector3 *, float), 0x00189ad8 (spline.cpp,
// the demo's 0x00181aa8): the Catmull-Rom weights' second derivatives in
// u = t - floor(t), then Evaluate at floor(t). spline.c's, to move there.
void spline_get_second_derivative(const Spline *s, bVector3 *o, float t);

#endif
