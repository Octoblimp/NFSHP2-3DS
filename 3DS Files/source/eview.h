// eview -- eView, Ecstasy's record of one view of the world (128 bytes,
// .mdebug type#2524), and the table of ten the renderer keeps at
// 0x002ab230 (eGetView, 0x001071f0, is `&table[id]`).
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
// The matrices are the renderer's and are made per frame in frame memory,
// so the record holds pointers to them. On the handheld the port's renderer
// fills them; see scenerycull.h for what the cull needs from them.

#ifndef EVIEW_H
#define EVIEW_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bmatrix.h"
#include "bvector.h"
#include "camera.h"

#define EVIEW_NUM_VIEWS 10       // TextureDownloader follows at 0x002ab730

// The view ids that matter to the cull.
#define EVIEW_ID_FRONTEND   0
#define EVIEW_ID_PLAYER1    1
#define EVIEW_ID_ENVMAP_LO  4
#define EVIEW_ID_ENVMAP_HI  9

// eRenderTarget, 1168 bytes on the disc (.mdebug type#3199). Only its head
// is named: the cull reads Active.
typedef struct eRenderTarget {
    int32_t     ID;                     //   0
    const char *Name;                   //   4
    uint32_t    Active;                 //   8
} eRenderTarget;

typedef struct eView {
    int32_t   ID;                       //   0
    uint8_t   Active;                   //   4
    uint8_t   LetterBox;                //   5
    uint8_t   pad0;                     //   6
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
    bNode     CameraMoverList;          //  60
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
    uint8_t   pad3[12];                 // 116
} eView;                                // 128

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char eview_layout_check[
    (sizeof(eView) == 128 && offsetof(eView, H) == 8
     && offsetof(eView, ViewDirection) == 32
     && offsetof(eView, pCamera) == 56
     && offsetof(eView, WorldViewMatrix) == 68
     && offsetof(eView, WorldScreenClipMatrix) == 80
     && offsetof(eView, WorldLightContext) == 108
     && offsetof(eView, BlackAndWhiteMode) == 112) ? 1 : -1];
#endif

// The table, 0x002ab230, and eGetView.
extern eView eViews[EVIEW_NUM_VIEWS];
eView *eGetView(int32_t id);

// CurrentViewMode, 0x00322898 (gp-25432), and eGetCurrentViewMode
// (0x00107238). Modes 3 and 4 are the split screens.
extern int32_t CurrentViewMode;
int32_t eGetCurrentViewMode(void);

// EnvironmentMappingEnable, 0x00323758 (gp-21656): whether eDisplayFrame
// culls the six environment-map views. 1 in the image's .sdata.
extern int32_t EnvironmentMappingEnable;

// The current view, gp-25436: eGetCurrentView (0x00107208),
// eSetCurrentView (0x00107210) and eGetCurrentCamera (0x00107218), which is
// the view's camera or NULL with no view.
eView  *eGetCurrentView(void);
void    eSetCurrentView(eView *v);
Camera *eGetCurrentCamera(void);

#endif
