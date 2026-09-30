// Host harness for 3DS Files/source/orbitcam.c, the orbit camera. Runs the
// op script tools/orbit_check.py writes and prints the transcript it diffs
// against the retail image, run in mipsemu over the same script.
//
// The harness owns what the mover reads from outside CameraMover.obj: a
// World with a car list and a Helicopter, the cars, a Chopper, a race
// coordinator, RealTimeElapsed, and the joystick layer, whose AddJoyHandler
// and RemoveJoyHandler print their arguments and do nothing else.
//
// Every camera and mover is filled with 0xa5 before it is built, so a field
// the port leaves alone and retail writes (or the other way round) shows.
// A float prints as its bits, every NaN as "nan", and a pointer by what it
// points at.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "camera.h"
#include "cammover.h"
#include "car.h"
#include "chopper.h"
#include "emath.h"
#include "eview.h"
#include "joyevent.h"
#include "orbitcam.h"
#include "race.h"
#include "realtime.h"
#include "world.h"

#define NCAM 6
#define NMOV 6
#define NCAR 6

// What orbitcam.c links against, the harness's own.
float RealTimeElapsed = 1.0f / 60.0f;
World *pCurrentWorld;

static Camera cams[NCAM];
static OrbitCarCameraMover movs[NMOV];
static struct Car cars[NCAR];
static World world;
static struct Chopper chopper;
static int32_t coordinator[4];

// The statics as the port initialises them, put back for each scenario.
static int      initUse;
static float    initTRad, initLook, initTH;
static uint16_t initTAH, initTAV, initInGame, initFE, initTFov;
static bVector3 initBoom;

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
    if (p == &OrbitCarCameraMoverVtbl)
        return "orbit";
    if (p == (const void *)orbit_joy_handler)
        return "joy";
    if (p == &world)
        return "w";
    if (p == &chopper)
        return "h";
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
            sprintf(b, "o%d", i);
            return b;
        }
    }
    for (i = 0; i < NCAR; i++) {
        if (p == &cars[i]) {
            sprintf(b, "k%d", i);
            return b;
        }
        if (p == &cars[i].State.GeometryPosition) {
            sprintf(b, "k%d.gpos", i);
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
    printf("    clear %08lx elapsed %s last %08lx carnot %08lx dash %08lx\n",
           (unsigned long)(uint32_t)c->ClearVelocity, fx(c->ElapsedTime),
           (unsigned long)c->LastUpdateTime,
           (unsigned long)(uint32_t)(uintptr_t)c->CarNotToRender,
           (unsigned long)(uint32_t)c->RenderDash);
}

static void pmov(int j)
{
    const OrbitCarCameraMover *o = &movs[j];
    const CameraMover *m = &o->base;
    const uint8_t *tm = (const uint8_t *)&o->TM;
    int i;

    printf("  o%d type %d view %d en %d pview %s pcam %s player %08lx"
           " carnot %08lx dash %08lx vtbl %s next %s prev %s\n",
           j, (int)m->Type, m->ViewID, m->Enabled, nm(m->pView),
           nm(m->pCamera), (unsigned long)(uint32_t)(uintptr_t)m->pPlayer,
           (unsigned long)(uint32_t)(uintptr_t)m->CarNotToRender,
           (unsigned long)(uint32_t)m->RenderDash, nm(m->vtbl),
           nm(m->Node.next), nm(m->Node.prev));
    printf("    r %s dr %s h %04x v %04x dv %04x hs %ld vs %ld dhs %ld"
           " dvs %ld\n",
           fx(o->Radius), fx(o->DesiredRadius), (unsigned)o->AngleH,
           (unsigned)o->AngleV, (unsigned)o->DesiredAngleV,
           (long)o->HRotationSpeed, (long)o->VRotationSpeed,
           (long)o->DesiredHRotationSpeed, (long)o->DesiredVRotationSpeed);
    printf("    minr %s maxr %s minv %04x maxv %04x mult %s mrv %s acc %ld"
           " fe %ld appr %ld\n",
           fx(o->MinRadius), fx(o->MaxRadius), (unsigned)o->MinAngleV,
           (unsigned)o->MaxAngleV, fx(o->RadiusMultiplier),
           fx(o->MaxRadiusVel), (long)o->MaxRotationAccel, (long)o->FEMode,
           (long)o->ApproachAngleV);
    printf("    car %s chop %ld fecar %08lx port %ld ha %ld tm ",
           nm(o->CarToFollow), (long)o->FollowChopper,
           (unsigned long)(uint32_t)(uintptr_t)o->FECarToFollow,
           (long)o->JoyPort, (long)o->HandlersAdded);
    for (i = 0; i < 64; i++)
        printf("%02x", tm[i]);
    printf("\n");
    if (m->pCamera) {
        const Camera *c = m->pCamera;

        printf("    cam %s near %s far %s fd %s dof %s fov %04x carnot %08lx"
               " dash %08lx\n",
               nm(c), fx(c->CurrentKey.NearZ), fx(c->CurrentKey.FarZ),
               fx(c->CurrentKey.FocalDistance),
               fx(c->CurrentKey.DepthOfField),
               (unsigned)c->CurrentKey.FieldOfView,
               (unsigned long)(uint32_t)(uintptr_t)c->CarNotToRender,
               (unsigned long)(uint32_t)c->RenderDash);
    }
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

// The joystick layer, as a recorder.
void AddJoyHandler(JoystickPort port, JoyEvent ev, JoyHandler fn, void *obj)
{
    printf("  addjoy port %ld ev %d fn %s obj %s\n", (long)port, (int)ev,
           nm((const void *)fn), nm(obj));
}

void RemoveJoyHandler(JoystickPort port, JoyEvent ev)
{
    printf("  remjoy port %ld ev %d\n", (long)port, (int)ev);
}

static void link_cars(int n)
{
    CarNode *head = (CarNode *)(void *)&world.CarList;
    int i;

    for (i = 0; i < NCAR; i++) {
        cars[i].Link.next = &cars[i].Link;
        cars[i].Link.prev = &cars[i].Link;
    }
    head->next = head;
    head->prev = head;
    for (i = 0; i < n; i++) {
        CarNode *tail = head->prev;

        cars[i].Link.prev = tail;
        cars[i].Link.next = head;
        tail->next = &cars[i].Link;
        head->prev = &cars[i].Link;
    }
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
    RealTimeElapsed = 1.0f / 60.0f;
    pRaceCoordinator = NULL;
    world.Helicopter = NULL;
    link_cars(0);

    OrbitUseTweakables = initUse;
    OrbitTweakRadius = initTRad;
    OrbitTweakAngleH = initTAH;
    OrbitTweakAngleV = initTAV;
    OrbitLookHeight = initLook;
    OrbitInGameFOV = initInGame;
    OrbitFrontEndFOV = initFE;
    OrbitTargetHeight = initTH;
    OrbitTweakOrbitFOV = initTFov;
    OrbitBoomOffset = initBoom;
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

static void read_vec(bVector3 *v)
{
    v->x = from_bits(xtok());
    v->y = from_bits(xtok());
    v->z = from_bits(xtok());
    v->pad = from_bits(xtok());
}

static void read_mat(bMatrix4 *m)
{
    bVector4 *r[4];
    int i;

    r[0] = &m->v0; r[1] = &m->v1; r[2] = &m->v2; r[3] = &m->v3;
    for (i = 0; i < 4; i++) {
        r[i]->x = from_bits(xtok());
        r[i]->y = from_bits(xtok());
        r[i]->z = from_bits(xtok());
        r[i]->w = from_bits(xtok());
    }
}

static struct Car *car_at(int i)
{
    return i < 0 ? NULL : &cars[i];
}

static void set_static(const char *f, uint32_t v)
{
    if (!strcmp(f, "use"))
        OrbitUseTweakables = (int)v;
    else if (!strcmp(f, "trad"))
        OrbitTweakRadius = from_bits(v);
    else if (!strcmp(f, "tah"))
        OrbitTweakAngleH = (uint16_t)v;
    else if (!strcmp(f, "tav"))
        OrbitTweakAngleV = (uint16_t)v;
    else if (!strcmp(f, "look"))
        OrbitLookHeight = from_bits(v);
    else if (!strcmp(f, "ingame"))
        OrbitInGameFOV = (uint16_t)v;
    else if (!strcmp(f, "fefov"))
        OrbitFrontEndFOV = (uint16_t)v;
    else if (!strcmp(f, "th"))
        OrbitTargetHeight = from_bits(v);
    else if (!strcmp(f, "tfov"))
        OrbitTweakOrbitFOV = (uint16_t)v;
    else if (!strcmp(f, "bx"))
        OrbitBoomOffset.x = from_bits(v);
    else if (!strcmp(f, "by"))
        OrbitBoomOffset.y = from_bits(v);
    else if (!strcmp(f, "bz"))
        OrbitBoomOffset.z = from_bits(v);
    else if (!strcmp(f, "bw"))
        OrbitBoomOffset.pad = from_bits(v);
    else {
        fprintf(stderr, "bad static %s\n", f);
        exit(2);
    }
}

// The fields a script sets: through the setters where the class has one,
// as the car select and the geometry viewer do, and straight in where it
// has none.
static void set_field(int j, const char *f, uint32_t v)
{
    OrbitCarCameraMover *o = &movs[j];

    if (!strcmp(f, "radius"))
        orbit_set_radius(o, from_bits(v));
    else if (!strcmp(f, "dradius"))
        orbit_set_desired_radius(o, from_bits(v));
    else if (!strcmp(f, "minr"))
        orbit_set_min_radius(o, from_bits(v));
    else if (!strcmp(f, "maxr"))
        orbit_set_max_radius(o, from_bits(v));
    else if (!strcmp(f, "mult"))
        orbit_set_radius_multiplier(o, from_bits(v));
    else if (!strcmp(f, "angh"))
        orbit_set_angles(o, (uint16_t)v, o->AngleV);
    else if (!strcmp(f, "angv"))
        orbit_set_angle_v(o, (uint16_t)v);
    else if (!strcmp(f, "dangv"))
        orbit_set_desired_angle_v(o, (uint16_t)v);
    else if (!strcmp(f, "minv"))
        orbit_set_min_angle_v(o, (uint16_t)v);
    else if (!strcmp(f, "maxv"))
        orbit_set_max_angle_v(o, (uint16_t)v);
    else if (!strcmp(f, "hs"))
        orbit_set_h_rotation_speed(o, (int32_t)v);
    else if (!strcmp(f, "vs"))
        orbit_set_v_rotation_speed(o, (int32_t)v);
    else if (!strcmp(f, "dhs"))
        orbit_set_desired_h_rotation_speed(o, (int32_t)v);
    else if (!strcmp(f, "dvs"))
        orbit_set_desired_v_rotation_speed(o, (int32_t)v);
    else if (!strcmp(f, "acc"))
        orbit_set_max_rotation_accel(o, (int32_t)v);
    else if (!strcmp(f, "appr"))
        orbit_set_approach_angle_v(o, (int32_t)v);
    else if (!strcmp(f, "fe"))
        o->FEMode = (int32_t)v;
    else if (!strcmp(f, "chop"))
        o->FollowChopper = (int32_t)v;
    else if (!strcmp(f, "car"))
        o->CarToFollow = car_at((int32_t)v);
    else {
        fprintf(stderr, "bad field %s\n", f);
        exit(2);
    }
}

static void query(int j)
{
    CameraMover *m = &movs[j].base;
    const CameraMoverVtbl *vt = m->vtbl;
    const CameraInfo *info = vt->GetCameraInfo(m);
    const POV *pov0 = vt->GetPOV(m, 0), *pov3 = vt->GetPOV(m, 3);
    int ext = vt->IsExteriorView(m);
    int lb = vt->IsLookingBack(m);
    float gap = vt->GetWallGap(m);
    void *car = vt->GetCarToFollow(m);

    printf("  q o%d info %s pov %s %s ext %d lb %d gap %s car %s tgt %s\n",
           j, nm(info), nm(pov0), nm(pov3), ext, lb, fx(gap), nm(car),
           nm(vt->GetTarget(m)));
}

static void vslot(int j, const char *slot)
{
    CameraMover *m = &movs[j].base;
    const CameraMoverVtbl *vt = m->vtbl;

    if (!strcmp(slot, "addjoy"))
        vt->AddJoyHandlers(m);
    else if (!strcmp(slot, "remjoy"))
        vt->RemoveJoyHandlers(m);
    else if (!strcmp(slot, "reset"))
        vt->ResetState(m);
    else if (!strcmp(slot, "render"))
        vt->Render(m, eGetView(3));
    else if (!strcmp(slot, "enable"))
        vt->Enable(m);
    else if (!strcmp(slot, "disable"))
        vt->Disable(m);
    else {
        fprintf(stderr, "bad slot %s\n", slot);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[4096];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: orbit_test SCRIPT\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    pCurrentWorld = &world;
    initUse = OrbitUseTweakables;
    initTRad = OrbitTweakRadius;
    initTAH = OrbitTweakAngleH;
    initTAV = OrbitTweakAngleV;
    initLook = OrbitLookHeight;
    initInGame = OrbitInGameFOV;
    initFE = OrbitFrontEndFOV;
    initTH = OrbitTargetHeight;
    initTFov = OrbitTweakOrbitFOV;
    initBoom = OrbitBoomOffset;

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
            pcam(&cams[k]);
        } else if (!strcmp(t, "N")) {
            // Raw words, never followed: the mover only clears them.
            int k = itok();

            cams[k].CarNotToRender = (void *)(uintptr_t)xtok();
            cams[k].RenderDash = (int)xtok();
        } else if (!strcmp(t, "P")) {
            pcam(&cams[itok()]);
        } else if (!strcmp(t, "V")) {
            int i = itok();

            eViews[i].pCamera = &cams[itok()];
        } else if (!strcmp(t, "Z")) {
            CameraStopUpdating = itok();
        } else if (!strcmp(t, "T")) {
            RealTimeElapsed = from_bits(xtok());
        } else if (!strcmp(t, "Q")) {
            int s = itok();

            if (s < 0) {
                pRaceCoordinator = NULL;
            } else {
                coordinator[0] = s;
                pRaceCoordinator = (RaceCoordinator *)(void *)coordinator;
            }
        } else if (!strcmp(t, "L")) {
            link_cars(itok());
        } else if (!strcmp(t, "K")) {
            int i = itok();

            read_vec(&cars[i].State.GeometryPosition);
            read_mat(&cars[i].State.BodyMatrix);
        } else if (!strcmp(t, "H")) {
            char *p = tok();

            if (!strcmp(p, "-")) {
                world.Helicopter = NULL;
            } else {
                chopper.Plan = (ChopperPlan)atoi(p);
                read_vec(&chopper.CurrentPos);
                read_mat(&chopper.Matrix);
                world.Helicopter = &chopper;
            }
        } else if (!strcmp(t, "S")) {
            const char *f = tok();

            set_static(f, xtok());
        } else if (!strcmp(t, "O")) {
            int j = itok(), view = itok(), car = itok(), port = itok();

            memset(&movs[j], 0xa5, sizeof movs[j]);
            orbit_init(&movs[j], view, car_at(car), (JoystickPort)port);
            pmov(j);
            pviews();
        } else if (!strcmp(t, "D")) {
            int j = itok();

            movs[j].base.vtbl->Destroy(&movs[j].base);
            pmov(j);
            pviews();
        } else if (!strcmp(t, "U")) {
            int j = itok();

            movs[j].base.vtbl->Update(&movs[j].base);
            pmov(j);
            if (movs[j].base.pCamera)
                pcam(movs[j].base.pCamera);
        } else if (!strcmp(t, "J")) {
            int j = itok(), port = itok(), ev = itok();
            uint32_t value = xtok();

            orbit_joy_handler((JoystickPort)port, (JoyEvent)ev,
                              (uint8_t)value, &movs[j]);
            pmov(j);
        } else if (!strcmp(t, "v")) {
            int j = itok();

            vslot(j, tok());
            pmov(j);
            pviews();
        } else if (!strcmp(t, "G")) {
            query(itok());
        } else if (!strcmp(t, "F")) {
            int j = itok();
            const char *f = tok();

            set_field(j, f, xtok());
        } else {
            fprintf(stderr, "bad op %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
