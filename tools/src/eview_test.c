// eview_test -- the harness tools/eview_check.py runs against eView.obj's
// port: 3DS Files/source/eview.c (the views, the render targets, the movers'
// lists and the view modes) and eviewmatrix.c (the projection and the
// frame's matrices), with the frame malloc (eframe.c) under them.
//
// It reads a script of hex words from argv[1], one op and its operands at a
// time (the checker has the list), and prints what the model prints. No
// address is printed:
//
//   V<n>      eViews[n]; V<n>.L its mover list's head
//   RT<n>     RenderTargets[n]
//   C0..C3    the flailer's, player 1's, player 2's and the mirror's camera
//   C4..C7    four more cameras the script fills
//   M<n>      the nth made-up mover, by its Node
//   X<n>      the nth matrix the script fills
//   F+o       o bytes into the frame memory
//   I         eMathIdentityMatrix; DMP DefaultMatrixPack; HM hack_man_matrix
//   ?         anything else
//
// Floats are printed as their bits, every NaN as the one quiet NaN.

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "camera.h"
#include "cammover.h"
#include "eframe.h"
#include "emath.h"
#include "eview.h"
#include "eviewmatrix.h"

enum {
    OP_TAG = 1, OP_INIT, OP_INITVIEWS, OP_DUMPVIEWS, OP_DUMPRTS, OP_NAME,
    OP_GETS, OP_CURVIEW, OP_ATTACH, OP_UNATTACH, OP_MTYPE, OP_NULLLIST,
    OP_RESETLIST, OP_UPDATEMODE, OP_SETMODES, OP_MAYBE, OP_SETRT, OP_SETVIEW,
    OP_SETCAM, OP_GLOBALS, OP_CALCH, OP_CREATE, OP_FRAME, OP_CALC, OP_MAT,
    OP_SETRTM, OP_PACKS, OP_SETVM, OP_L2C, OP_BIAS, OP_PIX, OP_PIXS, OP_PIXB,
    OP_SCREENPOS, OP_SWH, OP_LIGHT, OP_SUN, OP_SETH,
};

#define NMOVER   8
#define NMAT     8
#define NTCAM    4
#define FRAMESZ  2048

static FILE *script;

static CameraMover movers[NMOVER];
static bMatrix4    mats[NMAT];
static Camera      tcams[NTCAM];
// 64 bytes over, so the end of the frame is not the next array's start.
static uint8_t     frame[FRAMESZ + 64] __attribute__((aligned(16)));

// ---------------------------------------------------------------- output

static void out(const char *fmt, ...)
{
    va_list ap;

    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
}

static uint32_t fb(float f)
{
    uint32_t b;

    memcpy(&b, &f, 4);
    return b;
}

static uint32_t fx(float f)
{
    uint32_t b = fb(f);

    if ((b & 0x7f800000u) == 0x7f800000u && (b & 0x007fffffu))
        return 0x7fc00000u;
    return b;
}

static float bf(uint32_t b)
{
    float f;

    memcpy(&f, &b, 4);
    return f;
}

static Camera *cam_at(int i)
{
    static Camera *const globals[4] = {
        &FlailerCamera, &Player1Camera, &Player2Camera, &Player1RVMCamera,
    };

    if (i < 0)
        return 0;
    return i < 4 ? globals[i] : &tcams[i - 4];
}

static char namebuf[32][48];
static int  nameslot;

static const char *name_of(const void *vp)
{
    uintptr_t p = (uintptr_t)vp;
    char *s = namebuf[nameslot++ & 31];
    int k;

    if (p == 0)
        return "null";
    if (vp == &eMathIdentityMatrix)
        return "I";
    if (vp == &DefaultMatrixPack)
        return "DMP";
    if (vp == &hack_man_matrix)
        return "HM";
    if (vp == &SunPosition)
        return "SUN";
    for (k = 0; k < EVIEW_NUM_VIEWS; k++) {
        if (vp == &eViews[k]) {
            sprintf(s, "V%d", k);
            return s;
        }
        if (vp == &eViews[k].CameraMoverList) {
            sprintf(s, "V%d.L", k);
            return s;
        }
    }
    for (k = 0; k < EVIEW_NUM_RENDER_TARGETS; k++) {
        if (vp == &RenderTargets[k]) {
            sprintf(s, "RT%d", k);
            return s;
        }
    }
    for (k = 0; k < 4 + NTCAM; k++) {
        if (vp == cam_at(k)) {
            sprintf(s, "C%d", k);
            return s;
        }
    }
    for (k = 0; k < NMOVER; k++) {
        if (vp == &movers[k].Node) {
            sprintf(s, "M%d", k);
            return s;
        }
    }
    for (k = 0; k < NMAT; k++) {
        if (vp == &mats[k]) {
            sprintf(s, "X%d", k);
            return s;
        }
    }
    if (p >= (uintptr_t)frame && p <= (uintptr_t)frame + FRAMESZ) {
        sprintf(s, "F+%d", (int)(p - (uintptr_t)frame));
        return s;
    }
    return "?";
}

static void dump_words(const char *label, const void *p, int n)
{
    const uint8_t *b = p;
    int i;

    out("   %s", label);
    for (i = 0; i < n; i++) {
        float f;

        memcpy(&f, b + 4 * i, 4);
        out(" %08x", fx(f));
    }
    out("\n");
}

static void dump_matrix(const char *label, const bMatrix4 *m)
{
    dump_words(label, m, 16);
}

static void dump_key(const char *label, const CameraParams *k)
{
    int i;

    dump_matrix(label, &k->Matrix);
    out("    pos %08x %08x %08x %08x dir %08x %08x %08x %08x"
        " tgt %08x %08x %08x %08x\n",
        fx(k->Position.x), fx(k->Position.y), fx(k->Position.z),
        fx(k->Position.pad), fx(k->Direction.x), fx(k->Direction.y),
        fx(k->Direction.z), fx(k->Direction.pad), fx(k->Target.x),
        fx(k->Target.y), fx(k->Target.z), fx(k->Target.pad));
    out("    td %08x fd %08x dof %08x near %08x far %08x fov %u pad",
        fx(k->TargetDistance), fx(k->FocalDistance), fx(k->DepthOfField),
        fx(k->NearZ), fx(k->FarZ), (unsigned)k->FieldOfView);
    for (i = 0; i < 10; i++)
        out(" %02x", k->Pad[i]);
    out("\n");
}

static void dump_camera(int i)
{
    Camera *c = cam_at(i);

    out("  C%d\n", i);
    dump_key("cur", &c->CurrentKey);
    dump_key("prev", &c->PreviousKey);
    dump_key("vel", &c->VelocityKey);
    out("    elapsed %08x last %08x car %s dash %d\n", fx(c->ElapsedTime),
        (unsigned)c->LastUpdateTime, name_of(c->CarNotToRender),
        c->RenderDash);
}

static void dump_view(int k)
{
    eView *v = &eViews[k];

    out("  V%d id %d active %d lb %d h %08x near %08x far %08x bias %08x"
        " deg %08x dir %08x %08x %08x %08x rt0 %s rt1 %s cam %s\n",
        k, v->ID, v->Active, v->LetterBox, fx(v->H), fx(v->NearZ),
        fx(v->FarZ), fx(v->FovBias), fx(v->FovDegrees),
        fx(v->ViewDirection.x), fx(v->ViewDirection.y),
        fx(v->ViewDirection.z), fx(v->ViewDirection.pad),
        name_of(v->pRenderTarget0), name_of(v->pRenderTarget1),
        name_of(v->pCamera));
    out("   list %s %s mats %s %s %s %s %s %s %s %s %s wq %u blend %s wlc %s"
        " bw %d\n",
        name_of(v->CameraMoverList.next), name_of(v->CameraMoverList.prev),
        name_of(v->WorldViewMatrix), name_of(v->WorldClipMatrix),
        name_of(v->WorldScreenMatrix), name_of(v->WorldScreenClipMatrix),
        name_of(v->ClipScreenMatrix), name_of(v->ViewScreenMatrix),
        name_of(v->VUClipScreenMatrix), name_of(v->VUClipScreenMatrix1),
        name_of(v->VUClipScreenMatrix2), (unsigned)v->WeatherQueryCounter, name_of(v->pBlendMask),
        name_of(v->WorldLightContext), v->BlackAndWhiteMode);
}

static void dump_views(void)
{
    int k;

    for (k = 0; k < EVIEW_NUM_VIEWS; k++)
        dump_view(k);
}

static void dump_rt(int k)
{
    eRenderTarget *r = &RenderTargets[k];

    out("  RT%d id %d active %u sc %d %d %d %d ar %08x %08x bias %08x"
        " z %d packs %s %s %s wc %s wv %s cs %s vu %s vu1 %s vu2 %s\n",
        k, r->ID, (unsigned)r->Active, r->ScissorX, r->ScissorY,
        r->ScissorW, r->ScissorH, fx(r->AspectRatioX), fx(r->AspectRatioY),
        fx(r->FovBias), r->ZBufferMode, name_of(r->MatrixPack0),
        name_of(r->MatrixPack1), name_of(r->MatrixPack2),
        name_of(r->WorldClip), name_of(r->WorldView), name_of(r->ClipScreen),
        name_of(r->VUClipScreen), name_of(r->VUClipScreen1),
        name_of(r->VUClipScreen2));
}

static void dump_modes(void)
{
    out("  mode cur %d rend %d tweak %d\n", CurrentViewMode,
        RenderingViewMode, TweakerViewMode);
}

static void dump_lists(void)
{
    int k;

    for (k = 0; k < EVIEW_NUM_VIEWS; k++) {
        bNode *head = &eViews[k].CameraMoverList, *n = head->next;
        int i = 0;

        out("  V%d list prev %s:", k, name_of(head->prev));
        while (n != head && i < 12) {
            if (n == 0) {
                out(" null");
                break;
            }
            out(" %s(n %s p %s)", name_of(n), name_of(n->next),
                name_of(n->prev));
            n = n->next;
            i++;
        }
        out("\n");
    }
    dump_modes();
}

static void dump_frame(void)
{
    out("  frame pos %s end %s failed %d amount %u\n",
        name_of(CurrentBufferPos), name_of(CurrentBufferEnd),
        FrameMallocFailed, (unsigned)FrameMallocFailAmount);
}

// Frame memory from its start to where the allocations reached, sixteen
// words a line.
static void dump_frame_memory(void)
{
    int used, o;
    char label[16];

    if ((uintptr_t)CurrentBufferPos < (uintptr_t)frame
        || (uintptr_t)CurrentBufferPos > (uintptr_t)frame + FRAMESZ)
        return;
    used = (int)(CurrentBufferPos - frame);

    for (o = 0; o < used; o += 64) {
        sprintf(label, "F+%d", o);
        dump_words(label, frame + o, (used - o) / 4 < 16 ? (used - o) / 4 : 16);
    }
}

// The pattern a buffer is filled with before a call, so what the call
// leaves alone shows. No word of it is a NaN.
static uint32_t pat(uint32_t seed, uint32_t i)
{
    return 0x4a000000u | ((seed * 0x10001u + i * 0x9e37u) & 0x00ffffffu);
}

static void fill(void *p, int nwords, uint32_t seed)
{
    uint8_t *b = p;
    int i;

    for (i = 0; i < nwords; i++) {
        uint32_t w = pat(seed, (uint32_t)i);

        memcpy(b + 4 * i, &w, 4);
    }
}

// ---------------------------------------------------------------- seams

static void wait_seam(void)
{
    out("  wait\n");
}

static void light_seam(eLightContext *lc, const bMatrix4 *local_world,
                       const bMatrix4 *hack, const bVector4 *eye, eView *view)
{
    out("  light %s local %s hack %s eye %08x %08x %08x %08x view %s\n",
        name_of(lc), name_of(local_world), name_of(hack), fx(eye->x),
        fx(eye->y), fx(eye->z), fx(eye->w), name_of(view));
}

// ---------------------------------------------------------------- script

static uint32_t rd(void)
{
    unsigned x;

    if (fscanf(script, "%x", &x) != 1) {
        fprintf(stderr, "script ended early\n");
        exit(2);
    }
    return x;
}

static int32_t rdi(void)
{
    return (int32_t)rd();
}

static float rdf(void)
{
    return bf(rd());
}

static void rdm(bMatrix4 *m)
{
    float f[16];
    int i;

    for (i = 0; i < 16; i++)
        f[i] = rdf();
    memcpy(m, f, sizeof f);
}

static void rdv3(bVector3 *v)
{
    v->x = rdf();
    v->y = rdf();
    v->z = rdf();
    v->pad = rdf();
}

static eRenderTarget *rt_at(int i)
{
    return i < 0 ? 0 : &RenderTargets[i];
}

static bMatrix4 *mat_at(int i)
{
    return i < 0 ? 0 : &mats[i];
}

static uint32_t opno;

static void run(void)
{
    unsigned code;

    while (fscanf(script, "%x", &code) == 1) {
        opno++;
        switch (code) {
        case OP_TAG:
            out("tag %d\n", rdi());
            break;

        case OP_INIT: {
            int i;

            out("init\n");
            eview_static_init();
            for (i = 0; i < 4; i++)
                dump_camera(i);
            dump_views();
            out("  fov mip %u z %u maindraw %s\n", (unsigned)aBaselineFovMip,
                (unsigned)aBaselineFovZ, name_of(MainDraw0Context));
            break;
        }

        case OP_INITVIEWS:
            out("initviews\n");
            eInitViews();
            dump_views();
            break;

        case OP_DUMPVIEWS:
            out("views\n");
            dump_views();
            break;

        case OP_DUMPRTS: {
            int lo = rdi(), hi = rdi(), k;

            out("rts %d %d\n", lo, hi);
            for (k = lo; k < hi; k++)
                dump_rt(k);
            break;
        }

        case OP_NAME: {
            int id = rdi();

            out("name %d %s\n", id, eGetViewIDName(id));
            break;
        }

        case OP_GETS: {
            int k;

            out("gets\n");
            out(" ");
            for (k = 0; k < EVIEW_NUM_VIEWS; k++)
                out(" %s", name_of(eGetView(k)));
            out("\n ");
            for (k = 0; k < EVIEW_NUM_RENDER_TARGETS; k++)
                out(" %s", name_of(eGetRenderTarget(k)));
            out("\n  mode %d view %s camera %s\n", eGetCurrentViewMode(),
                name_of(eGetCurrentView()), name_of(eGetCurrentCamera()));
            out("  ztab");
            for (k = 0; k < 2; k++)
                out(" %08x %08x %08x %08x %08x %08x", fx(ZRanges[k].ZMin),
                    fx(ZRanges[k].ZMax), fx(ZRanges[k].ZMin1),
                    fx(ZRanges[k].ZMax1), fx(ZRanges[k].ZMin2),
                    fx(ZRanges[k].ZMax2));
            out("\n");
            break;
        }

        case OP_CURVIEW: {
            int v = rdi();

            out("curview %d\n", v);
            eSetCurrentView(v < 0 ? 0 : &eViews[v]);
            break;
        }

        case OP_ATTACH: {
            int v = rdi(), m = rdi();

            out("attach V%d M%d\n", v, m);
            eview_attach_camera_mover(&eViews[v], &movers[m].Node);
            dump_lists();
            break;
        }

        case OP_UNATTACH: {
            int v = rdi(), m = rdi();

            out("unattach V%d M%d\n", v, m);
            eview_unattach_camera_mover(&eViews[v], &movers[m].Node);
            dump_lists();
            break;
        }

        case OP_MTYPE: {
            int m = rdi(), t = rdi();

            movers[m].Type = (CameraMoverType)t;
            break;
        }

        case OP_NULLLIST: {
            int v = rdi();

            eViews[v].CameraMoverList.next = 0;
            break;
        }

        case OP_RESETLIST: {
            int v = rdi();

            eViews[v].CameraMoverList.next = &eViews[v].CameraMoverList;
            eViews[v].CameraMoverList.prev = &eViews[v].CameraMoverList;
            break;
        }

        case OP_UPDATEMODE:
            out("updatemode\n");
            eUpdateViewMode();
            dump_modes();
            break;

        case OP_SETMODES:
            CurrentViewMode = rdi();
            RenderingViewMode = rdi();
            TweakerViewMode = rdi();
            break;

        case OP_MAYBE: {
            int k;

            out("maybe\n");
            MaybeChangeViewMode();
            dump_modes();
            for (k = 0; k < EVIEW_NUM_RENDER_TARGETS; k++)
                out("  RT%d act %u sc %d %d %d %d\n", k,
                    (unsigned)RenderTargets[k].Active,
                    RenderTargets[k].ScissorX, RenderTargets[k].ScissorY,
                    RenderTargets[k].ScissorW, RenderTargets[k].ScissorH);
            out("  active");
            for (k = 0; k < EVIEW_NUM_VIEWS; k++)
                out(" %d", eViews[k].Active);
            out("\n");
            break;
        }

        case OP_SETRT: {
            eRenderTarget *r = &RenderTargets[rdi()];

            r->Active = rd();
            r->ScissorX = rdi();
            r->ScissorY = rdi();
            r->ScissorW = rdi();
            r->ScissorH = rdi();
            r->AspectRatioX = rdf();
            r->AspectRatioY = rdf();
            r->FovBias = rdf();
            r->ZBufferMode = rdi();
            break;
        }

        case OP_SETVIEW: {
            eView *v = &eViews[rdi()];

            v->ID = rdi();
            v->Active = (uint8_t)rd();
            v->pRenderTarget0 = rt_at(rdi());
            v->pRenderTarget1 = rt_at(rdi());
            v->pCamera = cam_at(rdi());
            break;
        }

        case OP_SETCAM: {
            Camera *c = cam_at(rdi());

            rdm(&c->CurrentKey.Matrix);
            rdv3(&c->CurrentKey.Position);
            rdv3(&c->CurrentKey.Direction);
            c->CurrentKey.NearZ = rdf();
            c->CurrentKey.FarZ = rdf();
            c->CurrentKey.FieldOfView = (uint16_t)rd();
            break;
        }

        case OP_GLOBALS: {
            int k;

            ScreenWidth = rdi();
            ScreenHeight = rdi();
            ClipVolumeScaleX = rdf();
            ClipVolumeScaleY = rdf();
            CenterX = rdf();
            CenterY = rdf();
            for (k = 0; k < 2; k++) {
                ZRanges[k].ZMin = rdf();
                ZRanges[k].ZMax = rdf();
                ZRanges[k].ZMin1 = rdf();
                ZRanges[k].ZMax1 = rdf();
                ZRanges[k].ZMin2 = rdf();
                ZRanges[k].ZMax2 = rdf();
            }
            aBaselineFovMip = (uint16_t)rd();
            aBaselineFovZ = (uint16_t)rd();
            MainDraw0Context = rt_at(rdi());
            break;
        }

        case OP_CALCH: {
            uint16_t fov = (uint16_t)rd();

            out("calch %u %08x\n", (unsigned)fov, fx(CalculateH(fov)));
            break;
        }

        case OP_CREATE: {
            int k = rdi(), mask = rdi();
            float nearz = rdf(), farz = rdf(), efarz = rdf();
            eView *v = &eViews[k];
            bMatrix4 m[6];
            int i;

            out("create V%d mask %d %08x %08x %08x\n", k, mask, fx(nearz),
                fx(farz), fx(efarz));
            for (i = 0; i < 6; i++)
                fill(&m[i], 16, opno * 8 + (uint32_t)i);
            CreateViewMatricies(v, &m[0], &m[1], &m[2],
                                (mask & 1) ? &m[3] : 0,
                                (mask & 4) ? &m[5] : 0,
                                (mask & 2) ? &m[4] : 0, nearz, farz, efarz);
            dump_matrix("a", &m[0]);
            dump_matrix("b", &m[1]);
            dump_matrix("c", &m[2]);
            dump_matrix("d", &m[3]);
            dump_matrix("e", &m[4]);
            dump_matrix("d2", &m[5]);
            dump_view(k);
            if (v->pRenderTarget0 != 0)
                out("  rt0 bias %08x\n", fx(v->pRenderTarget0->FovBias));
            if (v->pRenderTarget1 != 0)
                out("  rt1 bias %08x\n", fx(v->pRenderTarget1->FovBias));
            break;
        }

        case OP_FRAME: {
            int pos = rdi(), end = rdi();
            uint32_t seed = rd();

            fill(frame, FRAMESZ / 4, seed);
            CurrentBufferPos = frame + pos;
            CurrentBufferEnd = frame + end;
            FrameMallocFailed = 0;
            FrameMallocFailAmount = 0;
            break;
        }

        case OP_CALC: {
            int k = rdi();
            float nearz = rdf(), farz = rdf(), efarz = rdf();
            eView *v = &eViews[k];

            out("calc V%d %08x %08x %08x\n", k, fx(nearz), fx(farz),
                fx(efarz));
            eview_calculate_view_matrices(v, nearz, farz, efarz);
            dump_view(k);
            if (v->pRenderTarget0 != 0) {
                dump_rt((int)(v->pRenderTarget0 - RenderTargets));
                out("  rt0 bias %08x\n", fx(v->pRenderTarget0->FovBias));
            }
            if (v->pRenderTarget1 != 0) {
                dump_rt((int)(v->pRenderTarget1 - RenderTargets));
                out("  rt1 bias %08x\n", fx(v->pRenderTarget1->FovBias));
            }
            dump_frame();
            dump_frame_memory();
            break;
        }

        case OP_MAT: {
            int k = rdi();

            rdm(&mats[k]);
            break;
        }

        case OP_SETRTM: {
            eRenderTarget *r = &RenderTargets[rdi()];

            r->WorldClip = mat_at(rdi());
            r->WorldView = mat_at(rdi());
            r->ClipScreen = mat_at(rdi());
            r->VUClipScreen = mat_at(rdi());
            r->VUClipScreen1 = mat_at(rdi());
            r->VUClipScreen2 = mat_at(rdi());
            break;
        }

        case OP_PACKS: {
            int k = rdi();

            out("packs RT%d\n", k);
            erender_setup_matrix_packs(&RenderTargets[k]);
            dump_rt(k);
            dump_frame();
            dump_frame_memory();
            break;
        }

        case OP_SETVM: {
            eView *v = &eViews[rdi()];
            int slot = rdi();
            bMatrix4 *m = mat_at(rdi());

            switch (slot) {
            case 0: v->WorldViewMatrix = m; break;
            case 1: v->WorldClipMatrix = m; break;
            case 2: v->WorldScreenMatrix = m; break;
            case 3: v->WorldScreenClipMatrix = m; break;
            case 4: v->ClipScreenMatrix = m; break;
            case 5: v->ViewScreenMatrix = m; break;
            case 6: v->VUClipScreenMatrix = m; break;
            default: v->VUClipScreenMatrix1 = m; break;
            }
            break;
        }

        case OP_L2C: {
            int k = rdi(), which = rdi(), o = rdi(), l = rdi();

            out("l2c V%d %d X%d X%d\n", k, which, o, l);
            if (which == 0)
                eview_local_to_screen_clip(&eViews[k], &mats[o], &mats[l]);
            else
                eview_local_to_clip(&eViews[k], &mats[o], &mats[l]);
            dump_matrix("o", &mats[o]);
            break;
        }

        case OP_BIAS: {
            int k = rdi(), m = rdi();
            float s = rdf();

            out("bias V%d X%d %08x\n", k, m, fx(s));
            eview_bias_matrix_for_z_sorting(&eViews[k], &mats[m], s);
            dump_matrix("m", &mats[m]);
            break;
        }

        case OP_PIX: {
            int k = rdi();
            float r = rdf(), d = rdf();

            out("pix V%d %08x %08x -> %d\n", k, fx(r), fx(d),
                eview_get_pixel_size(&eViews[k], r, d));
            break;
        }

        case OP_PIXS: {
            int k = rdi();
            bVector3 p;
            float r;

            rdv3(&p);
            r = rdf();
            out("pixs V%d %08x %08x %08x %08x -> %d\n", k, fx(p.x), fx(p.y),
                fx(p.z), fx(r), eview_get_pixel_size_sphere(&eViews[k], &p, r));
            break;
        }

        case OP_PIXB: {
            int k = rdi();
            bVector3 mn, mx;

            rdv3(&mn);
            rdv3(&mx);
            out("pixb V%d %08x %08x %08x %08x %08x %08x -> %d\n", k,
                fx(mn.x), fx(mn.y), fx(mn.z), fx(mx.x), fx(mx.y), fx(mx.z),
                eview_get_pixel_size_box(&eViews[k], &mn, &mx));
            break;
        }

        case OP_SCREENPOS: {
            int k = rdi();
            bVector3 p, o;

            rdv3(&p);
            fill(&o, 4, opno);
            eview_get_screen_position(&eViews[k], &o, &p);
            out("spos V%d %08x %08x %08x -> %08x %08x %08x %08x\n", k,
                fx(p.x), fx(p.y), fx(p.z), fx(o.x), fx(o.y), fx(o.z),
                fx(o.pad));
            break;
        }

        case OP_SWH: {
            int k = rdi();

            out("swh V%d %08x %08x\n", k,
                fx(eview_get_screen_width(&eViews[k])),
                fx(eview_get_screen_height(&eViews[k])));
            break;
        }

        case OP_LIGHT: {
            int k = rdi();
            eView *v = &eViews[k];

            out("light V%d\n", k);
            eview_setup_world_light_context(v);
            out("  wlc %s\n", name_of(v->WorldLightContext));
            dump_frame();
            dump_frame_memory();
            break;
        }

        case OP_SUN:
            rdv3(&SunPosition);
            break;

        case OP_SETH: {
            eView *v = &eViews[rdi()];

            v->H = rdf();
            break;
        }

        default:
            fprintf(stderr, "bad op %x\n", code);
            exit(2);
        }
    }
}

int main(int argc, char **argv)
{
    if (argc < 2 || (script = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: eview_test script\n");
        return 2;
    }
    eMathInit();
    gEWaitUntilRenderingDoneFn = wait_seam;
    gElSetupLightContextFn = light_seam;
    run();
    fclose(script);
    return 0;
}
