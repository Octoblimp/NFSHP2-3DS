// eview -- the table of views, the render targets and the view modes. See
// eview.h.
//
// The tables are .bss or zeroed .data on the disc: the static constructor
// builds the cameras and the views, eInitViews wires views 0..3, and
// SetScreenBuffers fills the render targets.

#include <string.h>

#include "eview.h"

eView eViews[EVIEW_NUM_VIEWS];
eRenderTarget RenderTargets[EVIEW_NUM_RENDER_TARGETS];
eRenderTarget *MainDraw0Context = &RenderTargets[16];

int32_t CurrentViewMode;
int32_t RenderingViewMode;
int32_t TweakerViewMode;
int32_t EnvironmentMappingEnable = 1;

bNode SolidList;
bNode ModelList;

static eView *pCurrentView;

Camera FlailerCamera;
Camera Player1Camera;
Camera Player2Camera;
Camera Player1RVMCamera;

uint16_t aBaselineFovMip;
uint16_t aBaselineFovZ;

int32_t ScreenWidth = 512;
int32_t ScreenHeight = 448;
float   ClipVolumeScaleX = 0.5f;
float   ClipVolumeScaleY = 0.5f;
float   CenterX = 2048.0f;
float   CenterY = 2048.0f;
float   ZMin = 2.0000038146972656f;     // 0x40000010
float   ZMax = 2.2490234375f;           // 0x400ff000
float   ZMin1 = 2.0000152587890625f;    // 0x40000040
float   ZMax1 = 2.2499961853027344f;    // 0x400ffff0

uint32_t eFrameCounter;

void (*gEWaitUntilRenderingDoneFn)(void);

// ------------------------------------------------------------ the lookups

eView *eGetView(int32_t id)
{
    return &eViews[id];
}

eRenderTarget *eGetRenderTarget(int32_t id)
{
    return &RenderTargets[id];
}

int32_t eGetCurrentViewMode(void)
{
    return CurrentViewMode;
}

eView *eGetCurrentView(void)
{
    return pCurrentView;
}

void eSetCurrentView(eView *v)
{
    pCurrentView = v;
}

Camera *eGetCurrentCamera(void)
{
    return pCurrentView != 0 ? pCurrentView->pCamera : 0;
}

// ------------------------------------------------------------ the views

// The list head is linked to itself both before and after the bMemSet,
// which clears the first pair.
void eview_construct(eView *v)
{
    memset(v, 0, sizeof *v);
    v->CameraMoverList.next = &v->CameraMoverList;
    v->CameraMoverList.prev = &v->CameraMoverList;
    v->FovBias = 1.0f;
}

void eview_static_init(void)
{
    int i;

    // The list heads come first, each linked to itself; the other three are
    // the texture manager's.
    SolidList.prev = &SolidList;
    ModelList.prev = &ModelList;
    SolidList.next = &SolidList;
    ModelList.next = &ModelList;
    camera_init(&FlailerCamera);
    camera_init(&Player1Camera);
    camera_init(&Player2Camera);
    camera_init(&Player1RVMCamera);
    aBaselineFovZ = 9102;
    aBaselineFovMip = 16384;
    for (i = 0; i < EVIEW_NUM_VIEWS; i++)
        eview_construct(&eViews[i]);
}

void eInitViews(void)
{
    eView *v;

    v = eGetView(0);
    v->ID = 0;
    v->pRenderTarget0 = eGetRenderTarget(0);
    v->pRenderTarget1 = eGetRenderTarget(3);
    v->Active = 1;
    v->pCamera = &FlailerCamera;

    v = eGetView(1);
    v->ID = 1;
    v->pRenderTarget0 = eGetRenderTarget(1);
    v->pRenderTarget1 = eGetRenderTarget(4);
    v->pCamera = &Player1Camera;

    v = eGetView(2);
    v->ID = 2;
    v->pRenderTarget0 = eGetRenderTarget(2);
    v->pRenderTarget1 = eGetRenderTarget(5);
    v->pCamera = &Player2Camera;

    v = eGetView(3);
    v->ID = 3;
    v->pRenderTarget0 = eGetRenderTarget(7);
    v->pCamera = &Player1RVMCamera;
}

static const char *const VIEW_NAMES[EVIEW_NUM_VIEWS] = {
    "EVIEW_FLAILER", "EVIEW_PLAYER1", "EVIEW_PLAYER2", "EVIEW_PLAYER1_RVM",
    "EVIEW_ENVMAP0F", "EVIEW_ENVMAP0R", "EVIEW_ENVMAP0B", "EVIEW_ENVMAP0L",
    "EVIEW_ENVMAP0U", "EVIEW_ENVMAP0D",
};

const char *eGetViewIDName(int32_t id)
{
    if (id == -1)
        return "EVIEW_NONE";
    if (id >= 0 && id < EVIEW_NUM_VIEWS)
        return VIEW_NAMES[id];
    return "EVIEW_UNKNOWN(?)";
}

// ------------------------------------------------------------ the movers

void eview_attach_camera_mover(eView *v, bNode *mover)
{
    bNode *head = v->CameraMoverList.next;

    v->CameraMoverList.next = mover;
    head->prev = mover;
    mover->next = head;
    mover->prev = &v->CameraMoverList;
    eUpdateViewMode();
}

// The view is not read: the mover unlinks itself.
void eview_unattach_camera_mover(eView *v, bNode *mover)
{
    bNode *prev = mover->prev, *next = mover->next;

    (void)v;
    prev->next = next;
    next->prev = prev;
    eUpdateViewMode();
}

// The first mover on a view's list, or NULL when the list is empty. A list
// whose head reads NULL counts as empty too.
static bNode *first_mover(eView *v)
{
    bNode *n = v->CameraMoverList.next;

    return n != &v->CameraMoverList ? n : 0;
}

void eUpdateViewMode(void)
{
    eView *v1 = eGetView(1), *v2 = eGetView(2), *v3 = eGetView(3);

    if (first_mover(v1) != 0 && first_mover(v2) != 0)
        CurrentViewMode = 3;
    else if (first_mover(v1) != 0 && first_mover(v3) != 0)
        CurrentViewMode = 2;
    else if (first_mover(v1) != 0)
        CurrentViewMode = 1;
    else
        CurrentViewMode = 0;
}

// ------------------------------------------------------ the view modes

// The stores are made in the listing's order, which only shows when two of
// the targets are one: player 1's second target is its first when it has
// none, player 2's the same.
void MaybeChangeViewMode(void)
{
    eView *v1, *v2, *v3;
    eRenderTarget *p1, *p2, *p1b, *p2b, *mirror;
    int32_t w, h, half;

    if (TweakerViewMode != 0) {
        if (RenderingViewMode != TweakerViewMode) {
            if (gEWaitUntilRenderingDoneFn != 0)
                gEWaitUntilRenderingDoneFn();
            RenderingViewMode = TweakerViewMode;
        }
    } else if (RenderingViewMode != CurrentViewMode) {
        if (gEWaitUntilRenderingDoneFn != 0)
            gEWaitUntilRenderingDoneFn();
        RenderingViewMode = CurrentViewMode;
    }

    v1 = eGetView(1);
    v2 = eGetView(2);
    v3 = eGetView(3);
    p1 = v1->pRenderTarget0;
    p2 = v2->pRenderTarget0;
    p1b = v1->pRenderTarget1 != 0 ? v1->pRenderTarget1 : p1;
    p2b = v2->pRenderTarget1 != 0 ? v2->pRenderTarget1 : p2;
    mirror = v3->pRenderTarget0;
    h = MainDraw0Context->ScissorH;
    w = MainDraw0Context->ScissorW;

    switch ((uint32_t)RenderingViewMode) {
    case 0:
    case 1:
        p1->ScissorX = 0; p1->ScissorY = 0;
        p1->ScissorW = w; p1->ScissorH = h;
        p2->ScissorX = 0; p2->ScissorY = 0;
        p2->ScissorW = 0; p2->ScissorH = 0;
        mirror->ScissorX = 0; mirror->ScissorY = 0;
        mirror->ScissorW = 0; mirror->ScissorH = 0;
        p1b->ScissorH = h; p1b->ScissorW = w;
        p1b->ScissorX = 0; p1b->ScissorY = 0;
        p2b->ScissorH = 0; p2b->ScissorX = 0;
        p2b->ScissorY = 0; p2b->ScissorW = 0;
        p1->Active = 1; v1->Active = 1;
        p2->Active = 0; v2->Active = 0;
        mirror->Active = 0; v3->Active = 0;
        break;
    case 2:
        p1->ScissorX = 0; p1->ScissorY = 0;
        p1->ScissorW = w; p1->ScissorH = h;
        p2->ScissorX = 0; p2->ScissorY = 0;
        p2->ScissorW = 0; p2->ScissorH = 0;
        mirror->ScissorW = 256; mirror->ScissorH = 64;
        mirror->ScissorX = 0; mirror->ScissorY = 0;
        p1b->ScissorH = h; p1b->ScissorW = w;
        p1b->ScissorX = 0; p1b->ScissorY = 0;
        p2b->ScissorH = 0; p2b->ScissorX = 0;
        p2b->ScissorY = 0; p2b->ScissorW = 0;
        p1->Active = 1; v1->Active = 1;
        p2->Active = 0; v2->Active = 0;
        mirror->Active = 1; v3->Active = 1;
        break;
    case 3:
        half = h >> 1;
        p1->ScissorX = 0; p1->ScissorY = 0;
        p1->ScissorW = w; p1->ScissorH = half;
        p2->ScissorX = 0; p2->ScissorY = half;
        p2->ScissorW = w; p2->ScissorH = half;
        mirror->ScissorX = 0; mirror->ScissorY = 0;
        mirror->ScissorW = 0; mirror->ScissorH = 0;
        p1b->ScissorH = half; p1b->ScissorX = 0;
        p1b->ScissorY = 0; p1b->ScissorW = w;
        p2b->ScissorH = half; p2b->ScissorW = w;
        p2b->ScissorX = 0; p2b->ScissorY = half;
        p1->Active = 1; v1->Active = 1;
        p2->Active = 1; v2->Active = 1;
        mirror->Active = 0; v3->Active = 0;
        break;
    case 4:
        half = w >> 1;
        p1->ScissorX = 0; p1->ScissorY = 0;
        p1->ScissorW = half; p1->ScissorH = h;
        p2->ScissorX = half; p2->ScissorY = 0;
        p2->ScissorW = half; p2->ScissorH = h;
        mirror->ScissorX = 0; mirror->ScissorY = 0;
        mirror->ScissorW = 0; mirror->ScissorH = 0;
        p1b->ScissorH = h; p1b->ScissorX = 0;
        p1b->ScissorY = 0; p1b->ScissorW = half;
        p2b->ScissorH = h; p2b->ScissorW = half;
        p2b->ScissorX = half; p2b->ScissorY = 0;
        p1->Active = 1; v1->Active = 1;
        p2->Active = 1; v2->Active = 1;
        mirror->Active = 0; v3->Active = 0;
        break;
    default:
        break;
    }
}

// --------------------------------------------------- retail's packet build

void eview_set_max_z(eRenderTarget *rt)
{
    rt->MaxZ = rt->ZBufferMode == GS_PSMZ24 ? 16777215.0f : 65535.0f;
}
