// Host harness for 3DS Files/source/camera.c and the base of cammover.c.
// Runs the op script tools/cambase_check.py writes and prints the transcript
// it diffs against the retail image, run in mipsemu over the same script.
//
// The test vtable is the base's with Update, Render, Enable and Disable
// replaced by recorders that print and do nothing else.
//
// Every camera and mover is filled with 0xa5 before it is built, so a field
// the port leaves alone and retail writes (or the other way round) shows.
// A float prints as its bits, every NaN as "nan", and a pointer by what it
// points at: a camera or one of its current key's vectors, a mover, a view
// or its list's head, a vtable. Anything else prints as its low 32 bits,
// which for the fill pattern is the same on both sides.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "camera.h"
#include "cammover.h"
#include "emath.h"
#include "eview.h"

// The clock object's frame step. Only the orbit mover's thunk reads it, and
// nothing here builds one.
float RealTimeElapsed = 1.0f / 60.0f;

#define NCAM 12
#define NMOV 10

static Camera cams[NCAM];
static CameraMover movs[NMOV];
static CameraMoverVtbl TestVtbl;

static const char *nm(const void *p)
{
    static char buf[16][32];
    static int slot;
    char *b = buf[slot++ & 15];
    int i;

    if (p == 0)
        return "null";
    if (p == &CameraMoverBaseVtbl)
        return "base";
    if (p == &TestVtbl)
        return "test";
    for (i = 0; i < NCAM; i++) {
        if (p == &cams[i]) {
            sprintf(b, "c%d", i);
            return b;
        }
        if (p == &cams[i].CurrentKey.Position) {
            sprintf(b, "c%d.pos", i);
            return b;
        }
        if (p == &cams[i].CurrentKey.Direction) {
            sprintf(b, "c%d.dir", i);
            return b;
        }
        if (p == &cams[i].CurrentKey.Target) {
            sprintf(b, "c%d.tgt", i);
            return b;
        }
    }
    for (i = 0; i < NMOV; i++) {
        if (p == &movs[i]) {
            sprintf(b, "m%d", i);
            return b;
        }
    }
    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {
        if (p == &eViews[i]) {
            sprintf(b, "v%d", i);
            return b;
        }
        if (p == &eViews[i].CameraMoverList) {
            sprintf(b, "v%d.list", i);
            return b;
        }
    }
    sprintf(b, "?%08lx", (unsigned long)(uint32_t)(uintptr_t)p);
    return b;
}

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float from_bits(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static const char *fx(float f)
{
    static char buf[16][12];
    static int slot;
    char *b = buf[slot++ & 15];
    uint32_t u = bits(f);

    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08lx", (unsigned long)u);
    return b;
}

static void pvec(const char *tag, const bVector3 *v)
{
    printf(" %s %s %s %s %s", tag, fx(v->x), fx(v->y), fx(v->z), fx(v->pad));
}

static void pkey(const char *tag, const CameraParams *k)
{
    const bMatrix4 *m = &k->Matrix;
    int i;

    printf("    %s m %s %s %s %s %s %s %s %s", tag,
           fx(m->v0.x), fx(m->v0.y), fx(m->v0.z), fx(m->v0.w),
           fx(m->v1.x), fx(m->v1.y), fx(m->v1.z), fx(m->v1.w));
    printf(" %s %s %s %s %s %s %s %s\n",
           fx(m->v2.x), fx(m->v2.y), fx(m->v2.z), fx(m->v2.w),
           fx(m->v3.x), fx(m->v3.y), fx(m->v3.z), fx(m->v3.w));
    printf("    %s", tag);
    pvec("p", &k->Position);
    pvec("d", &k->Direction);
    pvec("t", &k->Target);
    printf("\n");
    printf("    %s s %s %s %s %s %s fov %04x pad ", tag,
           fx(k->TargetDistance), fx(k->FocalDistance), fx(k->DepthOfField),
           fx(k->NearZ), fx(k->FarZ), (unsigned)k->FieldOfView);
    for (i = 0; i < 10; i++)
        printf("%02x", k->Pad[i]);
    printf("\n");
}

static void pcam(int k)
{
    const Camera *c = &cams[k];

    printf("  c%d\n", k);
    pkey("cur", &c->CurrentKey);
    pkey("prev", &c->PreviousKey);
    pkey("vel", &c->VelocityKey);
    printf("    clear %08lx elapsed %s last %08lx carnot %08lx dash %08lx\n",
           (unsigned long)(uint32_t)c->ClearVelocity, fx(c->ElapsedTime),
           (unsigned long)c->LastUpdateTime,
           (unsigned long)(uint32_t)(uintptr_t)c->CarNotToRender,
           (unsigned long)(uint32_t)c->RenderDash);
}

static void pmov(int j)
{
    const CameraMover *m = &movs[j];

    printf("  m%d type %d view %d en %d pview %s pcam %s player %08lx"
           " carnot %08lx dash %08lx vtbl %s next %s prev %s\n",
           j, (int)m->Type, m->ViewID, m->Enabled, nm(m->pView),
           nm(m->pCamera), (unsigned long)(uint32_t)(uintptr_t)m->pPlayer,
           (unsigned long)(uint32_t)(uintptr_t)m->CarNotToRender,
           (unsigned long)(uint32_t)m->RenderDash, nm(m->vtbl),
           nm(m->Node.next), nm(m->Node.prev));
    if (m->pCamera)
        printf("    cam %s near %s far %s carnot %08lx dash %08lx\n",
               nm(m->pCamera), fx(m->pCamera->CurrentKey.NearZ),
               fx(m->pCamera->CurrentKey.FarZ),
               (unsigned long)(uint32_t)(uintptr_t)m->pCamera->CarNotToRender,
               (unsigned long)(uint32_t)m->pCamera->RenderDash);
}

static void pviews(void)
{
    int i, any = 0;

    printf("  views");
    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {
        const bNode *head = &eViews[i].CameraMoverList, *n = head->next;
        int k = 0;

        if (n == head)
            continue;
        printf(" v%d:", i);
        any = 1;
        for (; n != head && k < 20; n = n->next, k++)
            printf("%s%s", k ? "," : "", nm(n));
    }
    printf("%s mode %d\n", any ? "" : " -", (int)CurrentViewMode);
}

static void rec_update(CameraMover *m)
{
    printf("  update %s\n", nm(m));
}

static void rec_render(CameraMover *m, eView *view)
{
    printf("  render %s %s\n", nm(m), nm(view));
}

static void rec_enable(CameraMover *m)
{
    printf("  enable %s\n", nm(m));
}

static void rec_disable(CameraMover *m)
{
    printf("  disable %s\n", nm(m));
}

static void reset(void)
{
    int i;

    memset(cams, 0xa5, sizeof cams);
    memset(movs, 0xa5, sizeof movs);
    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {
        eViews[i].pCamera = 0;
        eViews[i].CameraMoverList.next = &eViews[i].CameraMoverList;
        eViews[i].CameraMoverList.prev = &eViews[i].CameraMoverList;
    }
    CameraStopUpdating = 0;
    CurrentViewMode = 0;
}

static void query(int j, int attached)
{
    CameraMover *m = &movs[j];
    const CameraMoverVtbl *vt = m->vtbl;
    CameraInfo *info = vt->GetCameraInfo(m);
    POV *pov0 = vt->GetPOV(m, 0), *pov3 = 0;
    int ext = vt->IsExteriorView(m);
    int lb = vt->IsLookingBack(m);
    float gap = vt->GetWallGap(m);
    void *car = vt->GetCarToFollow(m);

    if (!attached) {
        printf("  q0 m%d info %s pov %s ext %d lb %d gap %s car %s\n",
               j, nm(info), nm(pov0), ext, lb, fx(gap), nm(car));
        return;
    }
    pov3 = vt->GetPOV(m, 3);
    printf("  q m%d info %s pov %s %s ext %d lb %d gap %s car %s"
           " tgt %s pos %s dir %s\n",
           j, nm(info), nm(pov0), nm(pov3), ext, lb, fx(gap), nm(car),
           nm(vt->GetTarget(m)), nm(camera_mover_get_position(m)),
           nm(camera_mover_get_direction(m)));
}

static void vslot(int j, const char *slot)
{
    CameraMover *m = &movs[j];
    const CameraMoverVtbl *vt = m->vtbl;

    if (!strcmp(slot, "destroy"))
        vt->Destroy(m);
    else if (!strcmp(slot, "update"))
        vt->Update(m);
    else if (!strcmp(slot, "render"))
        vt->Render(m, eGetView(3));
    else if (!strcmp(slot, "addjoy"))
        vt->AddJoyHandlers(m);
    else if (!strcmp(slot, "remjoy"))
        vt->RemoveJoyHandlers(m);
    else if (!strcmp(slot, "reset"))
        vt->ResetState(m);
    else if (!strcmp(slot, "enable"))
        vt->Enable(m);
    else if (!strcmp(slot, "disable"))
        vt->Disable(m);
    else {
        fprintf(stderr, "bad slot %s\n", slot);
        exit(2);
    }
}

static void set_field(int k, const char *f, uint32_t v)
{
    Camera *c = &cams[k];
    CameraParams *cur = &c->CurrentKey;

    if (!strcmp(f, "clear"))
        c->ClearVelocity = (int32_t)v;
    else if (!strcmp(f, "elapsed"))
        c->ElapsedTime = from_bits(v);
    else if (!strcmp(f, "last"))
        c->LastUpdateTime = v;
    else if (!strcmp(f, "carnot"))
        c->CarNotToRender = (void *)(uintptr_t)v;
    else if (!strcmp(f, "dash"))
        c->RenderDash = (int)v;
    else if (!strcmp(f, "td"))
        cur->TargetDistance = from_bits(v);
    else if (!strcmp(f, "fd"))
        cur->FocalDistance = from_bits(v);
    else if (!strcmp(f, "dof"))
        cur->DepthOfField = from_bits(v);
    else if (!strcmp(f, "near"))
        cur->NearZ = from_bits(v);
    else if (!strcmp(f, "far"))
        cur->FarZ = from_bits(v);
    else if (!strcmp(f, "fov"))
        cur->FieldOfView = (uint16_t)v;
    else {
        fprintf(stderr, "bad field %s\n", f);
        exit(2);
    }
}

static char *tok(void)
{
    char *t = strtok(NULL, " \t\r\n");

    if (t == NULL) {
        fprintf(stderr, "short line\n");
        exit(2);
    }
    return t;
}

static int itok(void) { return atoi(tok()); }
static uint32_t xtok(void) { return (uint32_t)strtoul(tok(), NULL, 16); }

int main(int argc, char **argv)
{
    static char line[4096];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: cambase_test SCRIPT\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    TestVtbl = CameraMoverBaseVtbl;
    TestVtbl.Update = rec_update;
    TestVtbl.Render = rec_render;
    TestVtbl.Enable = rec_enable;
    TestVtbl.Disable = rec_disable;

    while (fgets(line, sizeof line, fp) != NULL) {
        char echo[64];
        char *t;

        line[strcspn(line, "\r\n")] = 0;
        snprintf(echo, sizeof echo, "%.40s", line);
        t = strtok(line, " \t");
        if (t == NULL)
            continue;
        if (!strcmp(t, "B")) {
            printf("B %d\n", itok());
            reset();
            continue;
        }
        printf("> %s\n", echo);

        if (!strcmp(t, "C")) {
            int k = itok();

            memset(&cams[k], 0xa5, sizeof cams[k]);
            camera_init(&cams[k]);
            pcam(k);
        } else if (!strcmp(t, "P")) {
            int d = itok(), s = itok();

            memset(&cams[d], 0xa5, sizeof cams[d]);
            camera_copy(&cams[d], &cams[s]);
            pcam(d);
            pcam(s);
        } else if (!strcmp(t, "F")) {
            int k = itok();
            const char *f = tok();

            set_field(k, f, xtok());
        } else if (!strcmp(t, "S")) {
            int k = itok(), i;
            float el = from_bits(xtok());
            float w[16];
            bMatrix4 m;

            for (i = 0; i < 16; i++)
                w[i] = from_bits(xtok());
            m.v0.x = w[0];  m.v0.y = w[1];  m.v0.z = w[2];  m.v0.w = w[3];
            m.v1.x = w[4];  m.v1.y = w[5];  m.v1.z = w[6];  m.v1.w = w[7];
            m.v2.x = w[8];  m.v2.y = w[9];  m.v2.z = w[10]; m.v2.w = w[11];
            m.v3.x = w[12]; m.v3.y = w[13]; m.v3.z = w[14]; m.v3.w = w[15];
            camera_set_matrix(&cams[k], &m, el);
            pcam(k);
        } else if (!strcmp(t, "Z")) {
            CameraStopUpdating = itok();
        } else if (!strcmp(t, "V")) {
            int i = itok();

            eViews[i].pCamera = &cams[itok()];
        } else if (!strcmp(t, "K")) {
            int ty = itok();

            printf("  name %d %s\n", ty,
                   camera_mover_type_name((CameraMoverType)ty));
        } else if (!strcmp(t, "N")) {
            int j = itok(), view = itok(), ty = itok();

            memset(&movs[j], 0xa5, sizeof movs[j]);
            camera_mover_init(&movs[j], view, (CameraMoverType)ty);
            pmov(j);
            pviews();
        } else if (!strcmp(t, "E") || !strcmp(t, "X") || !strcmp(t, "D")) {
            int j = itok();

            if (*t == 'E')
                camera_mover_enable(&movs[j]);
            else if (*t == 'X')
                camera_mover_disable(&movs[j]);
            else
                camera_mover_destroy(&movs[j]);
            pmov(j);
            pviews();
        } else if (!strcmp(t, "v")) {
            int j = itok();

            vslot(j, tok());
            pmov(j);
            pviews();
        } else if (!strcmp(t, "Q")) {
            query(itok(), 1);
        } else if (!strcmp(t, "Q0")) {
            query(itok(), 0);
        } else if (!strcmp(t, "T")) {
            int j = itok();

            movs[j].vtbl = itok() ? &TestVtbl : &CameraMoverBaseVtbl;
        } else if (!strcmp(t, "U")) {
            update_camera_movers();
            printf("  updated\n");
        } else if (!strcmp(t, "R")) {
            int i = itok();

            render_camera_movers(eGetView(i));
            printf("  rendered v%d\n", i);
        } else if (!strcmp(t, "L")) {
            int j = itok();

            camera_mover_set_player(&movs[j], (void *)(uintptr_t)xtok());
            pmov(j);
        } else {
            fprintf(stderr, "bad op %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
