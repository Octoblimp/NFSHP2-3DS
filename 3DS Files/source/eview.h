// eview -- eView, Ecstasy's record of one view of the world (128 bytes,
// .mdebug type#2524), the table of ten the renderer keeps at 0x002ab230
// (eGetView, 0x001071f0, is `&table[id]`), and the render targets the views
// draw into (RenderTargets, 0x002c9a20, 22 of 1168 bytes).
//
// A view is a camera, the matrices the renderer made from it this frame, and
// the render targets it draws into. The cull reads the camera, H, the ID,
// WorldViewMatrix and WorldScreenClipMatrix, and StuffScenery hands
// WorldLightContext to the models it draws.
//
// View 0 is the frontend's, 1 to 3 are the players', and 4 to 9 are the
// environment maps. eDisplayFrame culls the scenery for 1..3 and, when
// EnvironmentMappingEnable is set, for 4..9.
//
// This file is eView.obj's list half (0x00106650 .. 0x001075a8, less the
// matrices) and the words beside it in EcstasyE.obj: the view modes, the
// render target table, the four cameras and the static constructor's share
// of them. eviewmatrix.h has the matrices. Written up with addresses in
// docs/formats/eview.md; checked by tools/eview_check.py.

#ifndef EVIEW_H
#define EVIEW_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bmatrix.h"
#include "bvector.h"
#include "camera.h"

#define EVIEW_NUM_VIEWS 10       // TextureDownloader follows at 0x002ab730
#define EVIEW_NUM_RENDER_TARGETS 22

// The view ids, from eGetViewIDName's strings.
#define EVIEW_ID_NONE       (-1)
#define EVIEW_ID_FRONTEND   0    // EVIEW_FLAILER
#define EVIEW_ID_PLAYER1    1
#define EVIEW_ID_PLAYER2    2
#define EVIEW_ID_PLAYER1_RVM 3
#define EVIEW_ID_ENVMAP_LO  4    // ENVMAP0F, R, B, L, U, D
#define EVIEW_ID_ENVMAP_HI  9

// eRenderTargetMatrixPack, 192 bytes (.mdebug type#4358): what the VU1
// microcode is handed per target.
typedef struct eRenderTargetMatrixPack {
    bMatrix4 WorldView;          //   0
    bMatrix4 WorldClip;          //  64
    bMatrix4 VUClipScreen;       // 128
} eRenderTargetMatrixPack;

// eRenderTarget, 1168 bytes (.mdebug type#3199). Every field is named; the
// two blocks of GS packets are kept as bytes so the offsets stay the disc's.
// Retail's is 176 bytes and not yet ported. One of its fields is, MaxZ, at
// retail's offset, 116, where the demo's packets start.
typedef struct eRenderTarget {
    int32_t     ID;                     //    0
    const char *Name;                   //    4
    uint32_t    Active;                 //    8
    int32_t     RelativeToFrameBuffer;  //   12
    int32_t     CenterRelativeToFrame;  //   16
    int32_t     ScissorX;               //   20
    int32_t     ScissorY;               //   24
    int32_t     ScissorW;               //   28
    int32_t     ScissorH;               //   32
    int32_t     FrameMode;              //   36
    int32_t     FrameAddress;           //   40
    int32_t     FrameWriteMask;         //   44
    int32_t     FrameWidth;             //   48
    int32_t     FrameHeight;            //   52
    int32_t     ZBufferMode;            //   56
    int32_t     ZBufferAddress;         //   60
    int32_t     ZBufferMask;            //   64
    int32_t     ZTest;                  //   68
    int32_t     AlphaTest;              //   72
    int32_t     FBA;                    //   76
    int32_t     IgnoreAlphaTextures;    //   80
    float       AspectRatioX;           //   84
    float       AspectRatioY;           //   88
    float       AspectRatio2DX;         //   92
    float       AspectRatio2DY;         //   96
    float       FovBias;                //  100
    uint32_t    BackgroundColour;       //  104
    int32_t     ClearBackground;        //  108
    uint8_t     ClearZBuffer[4];        //  112 GS packets
    float       MaxZ;                   //  116 retail's; see eview_set_max_z
    uint8_t     ClearZBuffer1[120];     //  120 GS packets
    uint8_t     DrawContexts[896];      //  240 GS packets
    eRenderTargetMatrixPack *MatrixPack0;   // 1136
    eRenderTargetMatrixPack *MatrixPack1;   // 1140
    bMatrix4   *WorldClip;              // 1144
    bMatrix4   *WorldView;              // 1148
    bMatrix4   *ClipScreen;             // 1152
    bMatrix4   *VUClipScreen;           // 1156
    bMatrix4   *VUClipScreen1;          // 1160
    uint32_t    pad;                    // 1164
} eRenderTarget;

// OverrideRendering is retail's byte 6: NisManager::EnableOverrideRendering
// (0x001b1ce0) sets it and the word at 116 to 1 for the view a NIS takes
// over, and DisableOverrideRendering (0x001b24a8) clears both. RenderSkids
// draws nothing in such a view. The NIS player isn't ported, so it stays
// 0.
typedef struct eView {
    int32_t   ID;                       //   0
    uint8_t   Active;                   //   4
    uint8_t   LetterBox;                //   5
    uint8_t   OverrideRendering;        //   6  a NIS's; see below
    uint8_t   pad1;                     //   7
    float     H;                        //   8  focal length in pixels
    float     NearZ;                    //  12
    float     FarZ;                     //  16
    float     FovBias;                  //  20
    float     FovDegrees;               //  24
    uint32_t  pad2;                     //  28
    bVector3  ViewDirection;            //  32
    eRenderTarget *pRenderTarget0;      //  48
    eRenderTarget *pRenderTarget1;      //  52
    Camera   *pCamera;                  //  56
    bNode     CameraMoverList;          //  60  CameraMovers, by their Node
    bMatrix4 *WorldViewMatrix;          //  68
    bMatrix4 *WorldClipMatrix;          //  72
    bMatrix4 *WorldScreenMatrix;        //  76
    bMatrix4 *WorldScreenClipMatrix;    //  80
    bMatrix4 *ClipScreenMatrix;         //  84
    bMatrix4 *ViewScreenMatrix;         //  88
    bMatrix4 *VUClipScreenMatrix;       //  92
    bMatrix4 *VUClipScreenMatrix1;      //  96
    uint32_t  WeatherQueryCounter;      // 100
    void     *pBlendMask;               // 104
    void     *WorldLightContext;        // 108  eLightContext *
    int32_t   BlackAndWhiteMode;        // 112
    int32_t   NisBlackAndWhite;         // 116  retail's: see below
    uint8_t   pad3[8];                  // 120
} eView;                                // 128

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char eview_layout_check[
    (sizeof(eView) == 128 && offsetof(eView, H) == 8
     && offsetof(eView, ViewDirection) == 32
     && offsetof(eView, pCamera) == 56
     && offsetof(eView, WorldViewMatrix) == 68
     && offsetof(eView, WorldScreenClipMatrix) == 80
     && offsetof(eView, WorldLightContext) == 108
     && offsetof(eView, BlackAndWhiteMode) == 112
     && offsetof(eView, NisBlackAndWhite) == 116
     && sizeof(eRenderTarget) == 1168
     && offsetof(eRenderTarget, AspectRatioX) == 84
     && offsetof(eRenderTarget, MaxZ) == 116
     && offsetof(eRenderTarget, DrawContexts) == 240
     && offsetof(eRenderTarget, MatrixPack0) == 1136
     && offsetof(eRenderTarget, VUClipScreen1) == 1160) ? 1 : -1];
#endif

// ------------------------------------------------------------ the globals

// The table, 0x002ab230, and eGetView.
extern eView eViews[EVIEW_NUM_VIEWS];
eView *eGetView(int32_t id);

// RenderTargets, 0x002c9a20, zero in the image: SetScreenBuffers fills it.
// eGetRenderTarget (0x00104d00) is `&RenderTargets[id]`.
//
// ZBufferMode is a GS PSM: PSMZ24, 0x31, is the one retail tells apart.
#define GS_PSMZ24 0x31
extern eRenderTarget RenderTargets[EVIEW_NUM_RENDER_TARGETS];
eRenderTarget *eGetRenderTarget(int32_t id);

// MainDraw0Context, 0x00322860 (gp-25488): the render target the frame is
// drawn into, which is where MaybeChangeViewMode takes the screen's size
// from. The image starts it at RenderTargets[16]; the display modes move it
// among 15, 16, 18, 19 and 20.
extern eRenderTarget *MainDraw0Context;

// The view modes, EcstasyE.obj's .sdata, all 0 in the image.
// CurrentViewMode (0x00322898, gp-25432) is what the movers ask for,
// RenderingViewMode (0x0032289c) what the render targets were last cut for,
// TweakerViewMode (0x003228a0) a debug override that wins when non-zero.
// Mode 0 and 1 are one player, 2 adds the rear-view mirror, 3 is two
// players one above the other and 4 side by side.
extern int32_t CurrentViewMode;
extern int32_t RenderingViewMode;
extern int32_t TweakerViewMode;
int32_t eGetCurrentViewMode(void);      // 0x00107238

// EnvironmentMappingEnable, 0x00323758 (gp-21656): whether eDisplayFrame
// culls the six environment-map views. 1 in the image's .sdata.
extern int32_t EnvironmentMappingEnable;

// Two of the render eggs' (stomper.h), new in retail, and the port's names.
// ForceBlackAndWhite (gp-24048, 0): the Black & White egg's. With it set,
// or a player view's NisBlackAndWhite, eAttachBlackAndWhite (0x0011a9f0),
// the main chain's last, greys the frame after its fog and before the
// blur, the mirror and the HUD, which stay in colour. It reads the frame
// as 16-bit, eight columns at a time, and writes each pixel's green byte
// into a second buffer's alpha byte (FBMSK 0x7fff keeps bits 9 to 15 of
// each half: the green's top seven bits, onto the alpha's); then each
// player view with the egg, or Active with its target and its own flag,
// draws that alpha back over itself as an 8-bit index through
// SetupBlackAndWhite's grey ramp (0x0011a990: entry i is i, i, i and an
// alpha of 0x80). So the grey is the green. trackview.c's black_and_white.
// NisBlackAndWhite, the view's word at 116, is retail's:
// NisManager::EnableOverrideRendering (0x001b1ce0) sets it to 1 with the
// OverrideRendering byte, and DisableOverrideRendering (0x001b24a8)
// clears both, so a NIS plays in black and white. The port's NIS player
// does not have them yet (nismanager.h), so it stays 0.
// EnvPassAlphaA .. EnvPassAlphaFix (gp-25060 .. gp-25044; 0, 2, 1, 1 and
// 16): Chrome Cars' 2, 2, 1, 0 and 128. Out of the frontend,
// AttachDrawEnvironment (0x0010ac50) builds the second context's ALPHA_2
// from them, A | B << 2 | C << 4 | D << 6 | FIX << 32, and that context
// draws the environment map's pass: (Cs - 0) * Ad + Cd, the map added by
// the paint's alpha, by default, and (0 - 0) * Ad + Cs, the map in place
// of the paint, for the egg. The frontend's is 72, Cs * As + Cd, FIX 64,
// whatever these say. trackview.c's begin_frame reads them.
extern int32_t ForceBlackAndWhite;
extern int32_t EnvPassAlphaA;
extern int32_t EnvPassAlphaB;
extern int32_t EnvPassAlphaC;
extern int32_t EnvPassAlphaD;
extern int32_t EnvPassAlphaFix;

// Two of the five list heads the static constructor empties first, beside
// InactiveActiveTextureList, SolidTextureList and AlphaTextureList, which
// are the texture manager's and not ported. SolidList (0x00322780,
// gp-25712) holds every eSolid loaded, by the bNode at its start, and is
// what eFindSolid walks; ModelList (0x00322788, gp-25704) every eModel that
// eModel::Init was given a name. emodel.h has both users.
extern bNode SolidList;
extern bNode ModelList;

// The current view, gp-25436: eGetCurrentView (0x00107208),
// eSetCurrentView (0x00107210) and eGetCurrentCamera (0x00107218), which is
// the view's camera or NULL with no view.
eView  *eGetCurrentView(void);
void    eSetCurrentView(eView *v);
Camera *eGetCurrentCamera(void);

// The four cameras eInitViews hands out, 448 bytes apart from 0x002a9a50.
extern Camera FlailerCamera;            // 0x002a9a50, view 0
extern Camera Player1Camera;            // 0x002a9c10, view 1
extern Camera Player2Camera;            // 0x002a9dd0, view 2
extern Camera Player1RVMCamera;         // 0x002a9f90, view 3

// 0x00325300 and 0x00325302, .sbss: the fields of view the projection is
// measured against. The static constructor sets them to 16384 (90
// degrees) and 9102 (50, which the compiler folded from 50 * 65536 / 360).
extern uint16_t aBaselineFovMip;
extern uint16_t aBaselineFovZ;

// The screen, EcstasyE.obj's .sdata. The projections are in the GS's
// coordinates: a 4096-pixel square with the screen in its middle, centred
// on 2048, and a depth range just above 2.
extern int32_t ScreenWidth;             // 0x003227c8  512
extern int32_t ScreenHeight;            // 0x003227cc  448
extern float   ClipVolumeScaleX;        // 0x00322920  0.5
extern float   ClipVolumeScaleY;        // 0x00322924  0.5
extern float   CenterX;                 // 0x00322928  2048
extern float   CenterY;                 // 0x0032292c  2048
extern float   ZMin;                    // 0x00322930  0x40000010
extern float   ZMax;                    // 0x00322934  0x400ff000
extern float   ZMin1;                   // 0x00322938  0x40000040
extern float   ZMax1;                   // 0x0032293c  0x400ffff0

// eFrameCounter, 0x00322740 (gp-25776): the frames eDisplayFrame has
// finished. It counts one at its very end, and so does the port's
// trackview_draw. eView::GetWeatherQuery queries once per count.
extern uint32_t eFrameCounter;

// ------------------------------------------------------------- the views

// eView::eView (0x00106650): all 128 bytes zeroed, the mover list empty and
// FovBias 1. ~eView (0x001066a8) is not ported: it runs from the global
// destructors at exit, which the handheld does not reach.
void eview_construct(eView *v);

// The static constructor's share (0x00114098): the four cameras, the two
// baseline fields of view, and the ten views. The port calls it once at
// start-up where the disc's crt0 calls it.
void eview_static_init(void);

// eInitViews (0x001070f8): the ids, render targets and cameras of views 0
// to 3. Only view 0 is made active here; 4..9 are left alone.
void eInitViews(void);

// eGetViewIDName (0x00107010). -1 is "EVIEW_NONE"; an id past 9
// "EVIEW_UNKNOWN(?)".
const char *eGetViewIDName(int32_t id);

// eView::AttachCameraMover (0x00106b18) and UnattachCameraMover
// (0x00106b38). The mover goes on the head of the list; either way the
// mode is worked out again. `mover` is a CameraMover, by its Node.
void eview_attach_camera_mover(eView *v, bNode *mover);
void eview_unattach_camera_mover(eView *v, bNode *mover);

// eUpdateViewMode (0x00107240): 3 when players 1 and 2 both have movers,
// else 2 when player 1 and the mirror have, else 1 for player 1 alone,
// else 0.
void eUpdateViewMode(void);

// The port's (TASKS 37d): nonzero in a wireless race, whose console shows
// view 1 alone, its own player's, whatever mover view 2 has (player.h,
// PlayerNetLocal). eUpdateViewMode then never answers 3.
extern int32_t eViewShowOne;

// MaybeChangeViewMode (0x00107310): once the mode to draw differs from the
// one the targets were cut for, waits for the GS and cuts players 1 and
// 2's targets and the mirror's out of MainDraw0Context's scissor, and sets
// which of them are active.
void MaybeChangeViewMode(void);

// Retail's 0x00105ac0 builds a render target's GS packets every frame. On
// the way it sets MaxZ, the largest Z the target's buffer holds: 16777215
// (gp-32736) for PSMZ24, else 65535 (gp-32732). The sun and its glare draw
// at it. The packets are the GS's and are not ported; this is the rest.
void eview_set_max_z(eRenderTarget *rt);

// eWaitUntilRenderingDone (0x00110770), the seam: the GS and the DMA
// drained. The renderer sets it; NULL does nothing.
extern void (*gEWaitUntilRenderingDoneFn)(void);

#endif
