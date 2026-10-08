// Host harness for 3DS Files/source/rvmcam.c, the rear-view mirror's mover
// and Player::SetRearViewMirrorCameraMover. Runs the op script
// tools/rvmcam_check.py writes and prints the transcript it diffs against
// the retail image, run in mipsemu over the same script.
//
// The harness owns what the mover reads from outside: the cars, the
// players, RealTimeElapsed, Camera::StopUpdating and RVMOffsetInCar. It
// stands in for ApplyCameraShake, printing the matrix and adding the
// script's delta to its translation, and for bMalloc, which hands out the
// arena's blocks in turn, and bFree, which prints the block.
//
// Every camera, mover and block is filled with 0xa5 before the script sets
// it, so a field the port leaves alone and retail writes (or the other way
// round) shows. A float prints as its bits, every NaN as "nan", and a
// pointer by what it points at.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "camera.h"
#include "cammover.h"
#include "car.h"
#include "eview.h"
#include "player.h"
#include "rvmcam.h"
#include "shake.h"

#define NCAM 4
#define NMOV 3
#define NCAR 3
#define NPLAYER 2
#define NARENA 8

float RealTimeElapsed = 1.0f / 30.0f;

static Camera cams[NCAM];
static RearViewMirrorCameraMover movs[NMOV];
static struct Car cars[NCAR];
static struct Player players[NPLAYER];
static _Alignas(16) RearViewMirrorCameraMover arena[NARENA];
static int arena_at;
static bVector3 shake_delta;

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
    if (p == &RearViewMirrorCameraMoverVtbl)
        return "rvm";
    for (i = 0; i < NCAM; i++) {
        if (p == &cams[i]) {
            sprintf(b, "c%d", i);
            return b;
        }
        if (p == &cams[i].CurrentKey.Target) {
            sprintf(b, "c%d.tgt", i);
            return b;
        }
    }
    for (i = 0; i < NMOV; i++) {
        if (p == &movs[i]) {
            sprintf(b, "o%d", i);
            return b;
        }
    }
    for (i = 0; i < NARENA; i++) {
        if (p == &arena[i]) {
            sprintf(b, "a%d", i);
            return b;
        }
    }
    for (i = 0; i < NCAR; i++) {
        if (p == &cars[i]) {
            sprintf(b, "k%d", i);
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
    static char buf[64][12];
    static int slot;
    char *b = buf[slot++ & 63];
    uint32_t u = bits(f);

    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08lx", (unsigned long)u);
    return b;
}

static const char *v4(const bVector3 *v)
{
    static char buf[8][48];
    static int slot;
    char *b = buf[slot++ & 7];

    sprintf(b, "%s %s %s %s", fx(v->x), fx(v->y), fx(v->z), fx(v->pad));
    return b;
}

static void pvec(const char *tag, const bVector3 *v)
{
    printf(" %s %s", tag, v4(v));
}

static void pmat(const bMatrix4 *m)
{
    printf(" %s %s %s %s %s %s %s %s",
           fx(m->v0.x), fx(m->v0.y), fx(m->v0.z), fx(m->v0.w),
           fx(m->v1.x), fx(m->v1.y), fx(m->v1.z), fx(m->v1.w));
    printf(" %s %s %s %s %s %s %s %s",
           fx(m->v2.x), fx(m->v2.y), fx(m->v2.z), fx(m->v2.w),
           fx(m->v3.x), fx(m->v3.y), fx(m->v3.z), fx(m->v3.w));
}

static void pkey(const char *tag, const CameraParams *k)
{
    printf("    %s m", tag);
    pmat(&k->Matrix);
    printf("\n");
    printf("    %s", tag);
    pvec("p", &k->Position);
    pvec("d", &k->Direction);
    pvec("t", &k->Target);
    printf("\n");
    printf("    %s s %s %s %s %s %s fov %04x\n", tag,
           fx(k->TargetDistance), fx(k->FocalDistance), fx(k->DepthOfField),
           fx(k->NearZ), fx(k->FarZ), (unsigned)k->FieldOfView);
}

static void pcam(const Camera *c)
{
    printf("  %s\n", nm(c));
    pkey("cur", &c->CurrentKey);
    pkey("prev", &c->PreviousKey);
    pkey("vel", &c->VelocityKey);
    printf("    clear %08lx elapsed %s last %08lx carnot %s dash %08lx\n",
           (unsigned long)(uint32_t)c->ClearVelocity, fx(c->ElapsedTime),
           (unsigned long)c->LastUpdateTime, nm(c->CarNotToRender),
           (unsigned long)(uint32_t)c->RenderDash);
}

// ------------------------------------------------------------ the stubs

void *bMalloc(int size, const char *name, int flags, int pool)
{
    RearViewMirrorCameraMover *a;

    (void)size;
    if (arena_at >= NARENA) {
        fprintf(stderr, "arena full\n");
        exit(2);
    }
    a = &arena[arena_at++];
    memset(a, 0xa5, sizeof *a);
    printf("  malloc %s %d %d -> %s\n", name, flags, pool, nm(a));
    return a;
}

void bFree(void *p)
{
    printf("  free %s\n", nm(p));
}

void apply_camera_shake(int32_t view, bMatrix4 *m)
{
    printf("  shake view %d\n   ", (int)view);
    pmat(m);
    printf("\n");
    m->v3.x = m->v3.x + shake_delta.x;
    m->v3.y = m->v3.y + shake_delta.y;
    m->v3.z = m->v3.z + shake_delta.z;
}

// ------------------------------------------------------------ the dumps

static void pmov(const RearViewMirrorCameraMover *o)
{
    const CameraMover *m = &o->base;

    printf("  %s type %d view %d en %d pview %s pcam %s player %08lx"
           " carnot %s dash %08lx vtbl %s next %s prev %s car %s\n",
           nm(o), (int)m->Type, m->ViewID, m->Enabled, nm(m->pView),
           nm(m->pCamera), (unsigned long)(uint32_t)(uintptr_t)m->pPlayer,
           nm(m->CarNotToRender),
           (unsigned long)(uint32_t)m->RenderDash, nm(m->vtbl),
           nm(m->Node.next), nm(m->Node.prev), nm(o->pCar));
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
    printf("%s\n", any ? "" : " -");
}

static void pplayer(int i)
{
    const struct Player *p = &players[i];

    printf("  p%d view %d car %s rvm %s\n", i, (int)p->RearViewMirrorViewID,
           nm(p->MyCar), nm(p->pRVMCameraMover));
}

static void reset(void)
{
    int i;

    memset(cams, 0xa5, sizeof cams);
    memset(movs, 0xa5, sizeof movs);
    memset(cars, 0xa5, sizeof cars);
    memset(arena, 0xa5, sizeof arena);
    arena_at = 0;
    for (i = 0; i < NPLAYER; i++) {
        players[i].MyCar = NULL;
        players[i].RearViewMirrorViewID = 0;
        players[i].pRVMCameraMover = NULL;
    }
    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {
        eViews[i].pCamera = 0;
        eViews[i].CameraMoverList.next = &eViews[i].CameraMoverList;
        eViews[i].CameraMoverList.prev = &eViews[i].CameraMoverList;
    }
    CameraStopUpdating = 0;
    RealTimeElapsed = 1.0f / 30.0f;
    RVMOffsetInCar.x = 0.0f;
    RVMOffsetInCar.y = 0.5f;
    RVMOffsetInCar.z = 0.0f;
    RVMOffsetInCar.pad = 0.0f;
    memset(&shake_delta, 0, sizeof shake_delta);
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
static float ftok(void) { return from_bits(xtok()); }

static void read_vec(bVector3 *v)
{
    v->x = ftok();
    v->y = ftok();
    v->z = ftok();
    v->pad = ftok();
}

static struct Car *car_at(int i)
{
    return i < 0 ? NULL : &cars[i];
}

// A mover by the script's name: "-" none, "oN" a script's, "aN" a block.
static RearViewMirrorCameraMover *mov_of(const char *s)
{
    if (!strcmp(s, "-"))
        return NULL;
    if (s[0] == 'o')
        return &movs[atoi(s + 1)];
    if (s[0] == 'a')
        return &arena[atoi(s + 1)];
    fprintf(stderr, "bad mover %s\n", s);
    exit(2);
}

static void query(RearViewMirrorCameraMover *o)
{
    CameraMover *m = &o->base;
    const CameraMoverVtbl *vt = m->vtbl;
    const CameraInfo *info = vt->GetCameraInfo(m);
    const POV *pov0 = vt->GetPOV(m, 0);
    int ext = vt->IsExteriorView(m);
    int lb = vt->IsLookingBack(m);
    float gap = vt->GetWallGap(m);
    void *car = vt->GetCarToFollow(m);

    printf("  q %s info %s pov %s ext %d lb %d gap %s car %s tgt %s\n",
           nm(o), nm(info), nm(pov0), ext, lb, fx(gap), nm(car),
           nm(vt->GetTarget(m)));
}

int main(int argc, char **argv)
{
    static char line[8192];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: rvmcam_test SCRIPT\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    printf("offset %s\n", v4(&RVMOffsetInCar));

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
        if (strchr("KM", t[0]) == NULL || t[1])
            printf("> %s\n", echo);

        if (!strcmp(t, "C")) {
            int k = itok();

            memset(&cams[k], 0xa5, sizeof cams[k]);
            camera_init(&cams[k]);
            pcam(&cams[k]);
        } else if (!strcmp(t, "Y")) {
            // What the camera renders and its field of view, left by
            // another mover.
            int k = itok();

            cams[k].CarNotToRender = car_at(itok());
            cams[k].RenderDash = itok();
            cams[k].CurrentKey.FieldOfView = (uint16_t)xtok();
        } else if (!strcmp(t, "L")) {
            // The camera's clip planes, left by another mover.
            int k = itok();

            cams[k].CurrentKey.NearZ = ftok();
            cams[k].CurrentKey.FarZ = ftok();
        } else if (!strcmp(t, "V")) {
            int i = itok();

            eViews[i].pCamera = &cams[itok()];
        } else if (!strcmp(t, "Z")) {
            CameraStopUpdating = itok();
        } else if (!strcmp(t, "T")) {
            RealTimeElapsed = ftok();
        } else if (!strcmp(t, "R")) {
            read_vec(&RVMOffsetInCar);
        } else if (!strcmp(t, "H")) {
            read_vec(&shake_delta);
        } else if (!strcmp(t, "K")) {
            read_vec(&cars[itok()].State.GeometryPosition);
        } else if (!strcmp(t, "M")) {
            bMatrix4 *b = &cars[itok()].State.BodyMatrix;

            read_vec((bVector3 *)(void *)&b->v0);
            read_vec((bVector3 *)(void *)&b->v1);
            read_vec((bVector3 *)(void *)&b->v2);
            read_vec((bVector3 *)(void *)&b->v3);
        } else if (!strcmp(t, "O")) {
            int j = itok(), view = itok(), car = itok();
            RearViewMirrorCameraMover *r;

            memset(&movs[j], 0xa5, sizeof movs[j]);
            r = rvm_camera_mover_init(&movs[j], view, car_at(car));
            printf("  -> %s\n", nm(r));
            pmov(&movs[j]);
            pviews();
            pcam(movs[j].base.pCamera);
        } else if (!strcmp(t, "D")) {
            RearViewMirrorCameraMover *o = mov_of(tok());
            Camera *c = o->base.pCamera;

            o->base.vtbl->Destroy(&o->base);
            pmov(o);
            pviews();
            pcam(c);
        } else if (!strcmp(t, "U")) {
            RearViewMirrorCameraMover *o = mov_of(tok());

            o->base.vtbl->Update(&o->base);
            pmov(o);
            pcam(o->base.pCamera);
        } else if (!strcmp(t, "G")) {
            query(mov_of(tok()));
        } else if (!strcmp(t, "P")) {
            // A player: its mirror's view, its car and its mirror mover.
            int i = itok();
            int view = itok();
            int car = itok();
            RearViewMirrorCameraMover *o = mov_of(tok());

            players[i].RearViewMirrorViewID = view;
            players[i].MyCar = car_at(car);
            players[i].pRVMCameraMover = o ? &o->base : NULL;
        } else if (!strcmp(t, "S")) {
            int i = itok();
            uint32_t on = xtok();
            struct Player *p = &players[i];

            player_set_rear_view_mirror_camera_mover(p, on);
            pplayer(i);
            pviews();
            if (p->pRVMCameraMover != NULL) {
                pmov((RearViewMirrorCameraMover *)p->pRVMCameraMover);
                pcam(p->pRVMCameraMover->pCamera);
            }
        } else {
            fprintf(stderr, "bad op %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
