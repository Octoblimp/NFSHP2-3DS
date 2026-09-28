// Harness for tools/carinit_check.py: runs the checker's scenarios on
// carinit.c and prints what the model prints for the retail image.
// carcontroller.c, cardriver.c, espresso.c and vtable.c are the real ones;
// every other callee is a stub here, and each logs its name and its
// arguments, then the car, field by field in retail's order. See the
// checker's docstring.
//
//     carinit_test scenarios.txt > out.txt

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "car.h"
#include "carcontroller.h"
#include "cardriver.h"
#include "carinit.h"
#include "carmodes.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "collisionbody.h"
#include "drivetarget.h"
#include "espresso.h"
#include "physicscar.h"
#include "realtime.h"
#include "topology.h"
#include "trackpath.h"
#include "vtable.h"

int32_t WorldTimer;

#define PATTERN 0xa5
#define NHEAP   8
#define NCTI    8
#define CTI0    2                       // g_ctis[CTI0] is type 0

// ------------------------------------------------------------ the world

static Car          g_car;
static DriverInfo   g_di;
static CarTypeInfo  g_ctis[NCTI];
static _Alignas(16) unsigned char g_heap[NHEAP][4096];
static int          g_nheap;
static _Alignas(16) unsigned char g_snd[64], g_dmg_alt[256], g_ccb_alt[512],
                                  g_ri[64];
static _Alignas(16) unsigned char g_ctlobj[256], g_movobj[256],
                                  g_ccbobj[1024], g_dmgobj[256], g_riobj[64],
                                  g_cafobj[64], g_sndobj[64];
static emEvent      g_evt;

static int g_dret, g_cret, g_ri_knob, g_pos_null;

#define FAKE_VT_CTL 0x0fa00000u
#define FAKE_VT_MOV 0x0fa00100u
#define FAKE_VT_CCB 0x0fa00200u

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, sizeof u);
    return u;
}

static float flt(uint32_t u)
{
    float f;

    memcpy(&f, &u, sizeof f);
    return f;
}

static int all_pattern(const void *p, size_t n)
{
    const unsigned char *b = p;
    size_t i;

    for (i = 0; i < n; i++)
        if (b[i] != PATTERN)
            return 0;
    return 1;
}

static int within(const void *p, const void *base, size_t n, int *off)
{
    uintptr_t a = (uintptr_t)p, b = (uintptr_t)base;

    if (a < b || a >= b + n)
        return 0;
    *off = (int)(a - b);
    return 1;
}

static const char *lab(const void *p)
{
    static char buf[16][40];
    static int k;
    char *b = buf[k++ & 15];
    int i, off;

    if (p == NULL)
        return "null";
    if (all_pattern(&p, sizeof p))
        return "a5";
    if (p == (void *)&g_car)
        return "car";
    if (p == (void *)&g_car.State)
        return "state";
    if (p == (void *)&g_car.TheTopologyCoordinate)
        return "topo";
    if (p == (void *)&g_car.TheTrackPathCoordinate)
        return "tpc";
    if (p == (void *)&g_di)
        return "di";
    if (p == (void *)&g_di.CurrentRideInfo)
        return "ride";
    if (p == (void *)g_snd)
        return "snd";
    if (p == (void *)g_dmg_alt)
        return "dmg'";
    if (p == (void *)g_ccb_alt)
        return "ccb'";
    if (p == (void *)g_ri)
        return "ri";
    if (p == (void *)car_reflect_event_handler)
        return "CarReflectEventHandler";
    if (p == (void *)&g_evt)
        return "evt";
    for (i = 0; i < NHEAP; i++)
        if (p == (void *)g_heap[i]) {
            sprintf(b, "h%d", i);
            return b;
        }
    for (i = 0; i < NCTI; i++)
        if (p == (void *)&g_ctis[i]) {
            sprintf(b, "cti%d", i - CTI0);
            return b;
        }
    {
        static const struct { const unsigned char *base; size_t n;
                              const char *name; } objs[] = {
            { g_ctlobj, sizeof g_ctlobj, "ctlobj" },
            { g_movobj, sizeof g_movobj, "movobj" },
            { g_ccbobj, sizeof g_ccbobj, "ccbobj" },
            { g_dmgobj, sizeof g_dmgobj, "dmgobj" },
            { g_riobj,  sizeof g_riobj,  "riobj" },
            { g_cafobj, sizeof g_cafobj, "cafobj" },
            { g_sndobj, sizeof g_sndobj, "sndobj" },
        };
        for (i = 0; i < (int)(sizeof objs / sizeof objs[0]); i++)
            if (within(p, objs[i].base, objs[i].n, &off)) {
                if (off == 0)
                    return objs[i].name;
                sprintf(b, "%s+%d", objs[i].name, off);
                return b;
            }
    }
    sprintf(b, "?%p", p);
    return b;
}

static const char *vtname(uint32_t v)
{
    static char buf[4][16];
    static int k;
    char *b;

    switch (v) {
    case CARCONTROLLER_VTABLE:  return "CarController";
    case NULLCONTROLLER_VTABLE: return "NullController";
    case CARDRIVER_VTABLE:      return "CarDriver";
    case NULLDRIVER_VTABLE:     return "NullDriver";
    case NULLMOVER_VTABLE:      return "NullMover";
    case 0xa5a5a5a5u:           return "a5";
    }
    b = buf[k++ & 3];
    sprintf(b, "%08x", (unsigned)v);
    return b;
}

// ------------------------------------------------------------ the dump

static void w(uint32_t v)            { printf(" %08x", (unsigned)v); }
static void h(uint16_t v)            { printf(" %04x", (unsigned)v); }
static void p(const void *v)         { printf(" %s", lab(v)); }
static void f(float v)               { w(bits(v)); }

static uint32_t bytes4(const void *q)
{
    const unsigned char *b = q;

    return (uint32_t)b[0] | (uint32_t)b[1] << 8 | (uint32_t)b[2] << 16
        | (uint32_t)b[3] << 24;
}

static uint32_t word_of(uint8_t first, const uint8_t *rest)
{
    return (uint32_t)first | (uint32_t)rest[0] << 8 | (uint32_t)rest[1] << 16
        | (uint32_t)rest[2] << 24;
}

// A vector's four lanes; `maskw` prints its w as `*`, a lane the console
// takes from the stack.
static void v(const bVector3 *q, int maskw)
{
    f(q->x);
    f(q->y);
    f(q->z);
    if (maskw)
        printf(" *");
    else
        f(q->pad);
}

static void dump_car(void)
{
    const Car *c = &g_car;
    const OverrideRenderingPosition *o = &c->TheOverrideRenderingPosition;
    uint8_t t[3];

    printf("  =");
    h((uint16_t)c->CarIndex);
    h((uint16_t)c->DriverNumber);
    p(c->pCarTypeInfo);
    p(c->pRideInfo);
    p(c->MyDriver);
    p(c->pPlayer);
    p(c->pRacingCar);
    w((uint32_t)c->TheControlMode);
    w((uint32_t)c->TheMovementMode);
    p(c->pCarController);
    p(c->pCarDriver);
    p(c->pCarMover);
    p(c->pDynamicCollisionBody);
    w(bytes4(&c->_hole56[0]));
    w(bytes4(&c->_hole56[4]));
    printf(" |");
    v(&c->State.Position, g_pos_null);
    h(c->State.Angle);
    w((uint32_t)c->State.CurrentGear);
    printf(" |");
    w((uint32_t)c->DispGear);
    f(c->FrictionBoost);
    f(c->DraftFactor);
    f(c->fTractionBoostOverride);
    f(c->fDamageBoostOverride);
    w(bytes4(&c->_hole1108[0]));
    w(bytes4(&c->_hole1108[4]));
    w(bytes4(&c->_hole1108[8]));
    printf(" |");
    v(&c->vOldPos, g_pos_null);
    v(&c->vOldVel, 1);
    v(&c->vOldAngVel, 1);
    printf(" |");
    f(c->OldSpeed);
    f(c->AirTimeSwitch);
    w(word_of((uint8_t)c->RenderingEnabled, c->_hole1161));
    w((uint32_t)c->DriverRenderingEnabled);
    p(c->pRenderInfo);
    p(c->pAnimatedDriver);
    w(bytes4(&c->_hole1176[0]));
    w(bytes4(&c->_hole1176[4]));
    printf(" |");
    w(o->OverrideViewBits);
    w(o->VisibleViewBits);
    w(o->BlinkingViewBits);
    w(o->_pad92);
    printf(" |");
    w(word_of((uint8_t)c->CopLights, c->_hole1881));
    w((uint32_t)c->SignalLightState);
    w((uint32_t)c->NitroEffectFlag);
    w((uint32_t)c->WantToBlinkHeadlights);
    w((uint32_t)c->WantToHonkHorn);
    w((uint32_t)c->WantTwoHonksAndOrBlinks);
    w((uint32_t)c->HeadlightsAndHornStartTime);
    f(c->HeadlightsAndHornOnDuration);
    f(c->HeadlightsAndHornSecondOnDuration);
    f(c->HeadlightsAndHornOffDuration);
    w((uint32_t)c->ForceHeadlightsOn);
    w((uint32_t)c->HeadlightsState);
    w((uint32_t)c->TheSirenMode);
    w(c->WiperOnTime);
    w(c->WiperOffTime);
    w((uint32_t)c->WiperState);
    printf(" |");
    p(c->pCarDamage);
    t[0] = c->NumBlownTires;
    t[1] = c->_hole1946[0];
    t[2] = c->_hole1946[1];
    w(word_of(c->BlownTireBits, t));
    f(c->fBlownTireControllerRumbleTimer);
    p(c->pBaseCarSound);
    w((uint32_t)c->ResetMe);
    w((uint32_t)c->JustResetFrames);
    w((uint32_t)c->BlinkTimer);
    f(c->BlinkDuration);
    f(c->LastInTroughPosition.x);
    f(c->LastInTroughPosition.y);
    w((uint32_t)c->bPoofed);
    w((uint32_t)c->bVisibleOnTrackMap);
    w(bytes4(c->NumTimesSkidding));
    w(word_of(c->RoadBumpBits, c->_hole1989));
    p(c->pCaffeineObj);
    p(c->pLastCarTrailObj);
    w((uint32_t)c->LeaveCarTrails);
    w((uint32_t)c->ForceBuzzTime);
    f(c->fAngleToCamera);
    w((uint32_t)c->InDeepWaterRegistered);
    printf("\n");
}

static void say(const char *fmt, ...)
{
    va_list ap;

    printf("  ");
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    printf("\n");
    dump_car();
}

// ------------------------------------------------------------ the stubs

void carstate_init(CarState *s, TopologyCoordinate *topo,
                   CarTypeInfoPrefix *info)
{
    say("CarState %s %s %s", lab(s), lab(topo), lab(info));
    s->Position.x = flt(0x11111111u);
    s->Position.y = flt(0x11111111u);
    s->Position.z = flt(0x11111111u);
    s->Position.pad = flt(0x11111111u);
    s->Angle = 0x1234;
    s->CurrentGear = 0x55;
}

void topology_init(TopologyCoordinate *tc)
{
    say("TopologyCoordinate %s", lab(tc));
}

void topology_destroy(TopologyCoordinate *tc)
{
    say("~TopologyCoordinate %s", lab(tc));
}

void trackpath_coord_init(TrackPathCoordinate *c)
{
    say("TrackPathCoordinate %s", lab(c));
}

void trackpath_coord_reset_position(TrackPathCoordinate *c,
                                    const bVector2 *pos)
{
    say("ResetPosition %s %08x %08x", lab(c), (unsigned)bits(pos->x),
        (unsigned)bits(pos->y));
}

void trackpath_coord_reset_position_near(TrackPathCoordinate *c,
                                         const bVector2 *pos, float dist)
{
    say("ResetPositionNear %s %08x %08x %08x", lab(c),
        (unsigned)bits(pos->x), (unsigned)bits(pos->y),
        (unsigned)bits(dist));
}

const CarTypeInfo *cartypeinfo_get(int32_t carType)
{
    return &g_ctis[CTI0 + carType];
}

static void *heap_next(void)
{
    void *m;

    if (g_nheap >= NHEAP) {
        fprintf(stderr, "harness heap exhausted\n");
        exit(3);
    }
    m = g_heap[g_nheap++];
    memset(m, PATTERN, sizeof g_heap[0]);
    return m;
}

// The console's sizes: sizeof on the host is wider where a class has a
// pointer.
static int console_size(int size)
{
    if (size == (int)sizeof(NullController))
        return 12;
    if (size == (int)sizeof(NullDriver))
        return 560;
    return size;
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *m = heap_next();

    say("bMalloc %d %s %d %d -> %s", console_size(size), name, flags, pool,
        lab(m));
    return m;
}

void bFree(void *q)
{
    say("bFree %s", lab(q));
}

NullMover *nullmover_new(void)
{
    void *m = heap_next();

    say("bOMalloc NullMoverSlotPool -> %s", lab(m));
    return m;
}

void *carcollisionbody_new(void)
{
    void *m = heap_next();

    say("bOMalloc CarCollisionBodySlotPool -> %s", lab(m));
    return m;
}

CarCollisionBody *carcollisionbody_init(CarCollisionBody *b, struct Car *car)
{
    say("CarCollisionBody %s %s", lab(b), lab(car));
    return g_cret ? (CarCollisionBody *)g_ccb_alt : b;
}

DriveTarget *drivetarget_init(DriveTarget *t)
{
    say("DriveTarget %s", lab(t));
    return t;
}

void drivetarget_clear(DriveTarget *t, Car *car, float speed)
{
    say("DriveTarget::Clear %s %s %08x", lab(t), lab(car),
        (unsigned)bits(speed));
}

// carcontroller.c's and cardriver.c's, which the constructor never reaches.
static void never(const char *name)
{
    fprintf(stderr, "harness: %s reached\n", name);
    exit(4);
}

void car_set_movement_mode(Car *c, MovementMode mode)
{
    (void)c;
    (void)mode;
    never("car_set_movement_mode");
}

DriveTarget *drivetarget_assign(DriveTarget *dst, const DriveTarget *src)
{
    (void)src;
    never("drivetarget_assign");
    return dst;
}

void car_put_flat_on_track(Car *c)
{
    say("PutFlatOnTrack %s", lab(c));
    c->State.Position.x = 12.5f;
    c->State.Position.y = -3.25f;
    c->State.CurrentGear = 7;
    c->DispGear = 9;
    c->OldSpeed = 3.0f;
    c->pRenderInfo = (CarRenderInfo *)g_ri;
}

void car_stop_blinking(Car *c)
{
    say("StopBlinking %s", lab(c));
}

void car_event_handler(Car *c, void *event)
{
    say("EventHandler %s %s", lab(c), lab(event));
}

// ------------------------------------------------------------ the seams

static BaseCarSound *create_player(Car *c)
{
    say("CreatePlayerCarSound %s", lab(c));
    return (BaseCarSound *)g_snd;
}

static BaseCarSound *create_ai(Car *c)
{
    say("CreateAICarSound %s", lab(c));
    return (BaseCarSound *)g_snd;
}

static BaseCarSound *create_cop(Car *c)
{
    say("CreateAICopCarSound %s", lab(c));
    return (BaseCarSound *)g_snd;
}

static void sound_destroy(BaseCarSound *s, int32_t flags)
{
    say("~BaseCarSound %s %d", lab(s), (int)flags);
}

static CarDamage *damage_ctor(void *mem, Car *c)
{
    say("CarDamage %s %s", lab(mem), lab(c));
    return g_dret ? (CarDamage *)g_dmg_alt : (CarDamage *)mem;
}

static void damage_parts(CarDamage *d)
{
    say("CarDamage::parts %s", lab(d));
}

static void damage_destroy(CarDamage *d, int32_t flags)
{
    say("~CarDamage %s %d", lab(d), (int)flags);
}

static void init_render_info(Car *c, RideInfo *ride)
{
    say("InitRenderInfo %s %s", lab(c), lab(ride));
    switch (g_ri_knob) {
    case 1:
        c->pRenderInfo = (CarRenderInfo *)g_ri;
        break;
    case 2:
        c->pRenderInfo = (CarRenderInfo *)g_ri;
        c->pCarDamage = NULL;
        break;
    case 3:
        c->pCarDamage = (CarDamage *)g_dmg_alt;
        break;
    case 4:
        c->State.Position.x = 1.5f;
        c->State.Position.y = 2.5f;
        break;
    }
}

static void render_info_destroy(CarRenderInfo *ri, int32_t flags)
{
    say("~CarRenderInfo %s %d", lab(ri), (int)flags);
}

static int32_t em_add(EmHandlerFn fn, uint32_t mask)
{
    say("emAddHandler %s %08x", lab((void *)fn), (unsigned)mask);
    return 1;
}

static void em_remove(EmHandlerFn fn)
{
    say("emRemoveHandler %s", lab((void *)fn));
}

static void esp_set_attr(uint32_t obj, const char *name, int32_t value)
{
    say("espSetAttributeInt %08x %s %d", (unsigned)obj, name, (int)value);
}

static void esp_delete(void *obj)
{
    say("espDeleteObject %s", lab(obj));
}

// The destructor scenarios' fakes, each at its own image address.
static void fake_ctl_dtor(void *self, int32_t flags)
{
    say("~ctl %s %d", lab(self), (int)flags);
}

static void fake_mov_dtor(void *self, int32_t flags)
{
    say("~mover %s %d", lab(self), (int)flags);
}

static void fake_ccb_dtor(void *self, int32_t flags)
{
    say("~ccb %s %d", lab(self), (int)flags);
}

// vt_install keeps the pointer, so each table is its own static.
static void install_fake(uint32_t image, VtEntry *e, VtFn fn, int delta)
{
    memset(e, 0, 2 * sizeof *e);
    e[1].delta = (int16_t)delta;
    e[1].fn = fn;
    vt_install(image, e, 2);
}

static VtEntry g_vt_ctl[2], g_vt_mov[2], g_vt_ccb[2];

// ------------------------------------------------------------ the ops

static uint32_t tok(char **s)
{
    char *end;
    uint32_t u = (uint32_t)strtoul(*s, &end, 16);

    *s = end;
    return u;
}

static void fill_car(void)
{
    memset(&g_car, PATTERN, sizeof g_car);
}

static void op_ctor(char *s, int n)
{
    int32_t dn = (int32_t)tok(&s), type = (int32_t)tok(&s);
    int i, haspos;
    bVector3 pos;
    uint16_t angle;
    float dist;
    Car *ret;

    for (i = 0; i < NCTI; i++) {
        memset(&g_ctis[i], PATTERN, sizeof g_ctis[i]);
        g_ctis[i].UsageType = (int32_t)tok(&s);
    }
    SoundEnabled = (int32_t)tok(&s);
    haspos = (int)tok(&s);
    pos.x = flt(tok(&s));
    pos.y = flt(tok(&s));
    pos.z = flt(tok(&s));
    pos.pad = flt(tok(&s));
    angle = (uint16_t)tok(&s);
    dist = flt(tok(&s));
    WorldTimer = (int32_t)tok(&s);
    g_dret = (int)tok(&s);
    g_cret = (int)tok(&s);
    g_ri_knob = (int)tok(&s);
    g_pos_null = !haspos;

    fill_car();
    memset(&g_di, 0x5a, sizeof g_di);
    g_di.UniqueDriverNumber = (int8_t)dn;
    g_di.CurrentRideInfo.Type = type;
    g_nheap = 0;

    printf("C %d\n", n);
    ret = car_construct(&g_car, &g_di, haspos ? &pos : NULL, angle, dist);
    printf("  ret %s\n", lab(ret));
    dump_car();
    {
        const CarController *ctl = g_car.pCarController;
        const CarDriver *d = g_car.pCarDriver;
        const NullMover *m = (const NullMover *)g_car.pCarMover;

        printf("  ctl %s %s %s\n", lab(ctl->pCar), lab(ctl->Driver),
               vtname(ctl->_vtable));
        printf("  drv %04x %08x %08x %08x %08x %08x %08x %s\n",
               (unsigned)d->Steering, (unsigned)bits(d->Throttle),
               (unsigned)bits(d->Brake), (unsigned)bits(d->EBrake),
               (unsigned)d->DesiredGear, (unsigned)d->SportGear,
               (unsigned)d->NitroFlag, vtname(d->_vtable));
        printf("  mover %s %s %s\n", lab(m->Mover.Driver),
               vtname(m->Mover._vtable), lab(m->pState));
    }
}

static void op_dtor(char *s, int n)
{
    int ctl = (int)tok(&s), mov = (int)tok(&s), ccb = (int)tok(&s);
    int dmg = (int)tok(&s), ri = (int)tok(&s), caf = (int)tok(&s);
    int snd = (int)tok(&s);
    int32_t flags = (int32_t)tok(&s);
    int dctl = (int)(int32_t)tok(&s), dmov = (int)(int32_t)tok(&s);
    int dccb = (int)(int32_t)tok(&s);

    fill_car();
    g_pos_null = 0;
    memset(g_ctlobj, PATTERN, sizeof g_ctlobj);
    memset(g_movobj, PATTERN, sizeof g_movobj);
    memset(g_ccbobj, PATTERN, sizeof g_ccbobj);
    ((CarController *)g_ctlobj)->_vtable = FAKE_VT_CTL;
    ((CarMover *)g_movobj)->_vtable = FAKE_VT_MOV;
    ((CarCollisionBody *)g_ccbobj)->Dynamic.Body._vtable = FAKE_VT_CCB;
    install_fake(FAKE_VT_CTL, g_vt_ctl, (VtFn)fake_ctl_dtor, dctl);
    install_fake(FAKE_VT_MOV, g_vt_mov, (VtFn)fake_mov_dtor, dmov);
    install_fake(FAKE_VT_CCB, g_vt_ccb, (VtFn)fake_ccb_dtor, dccb);

    g_car.pCarController = ctl ? (CarController *)g_ctlobj : NULL;
    g_car.pCarMover = mov ? (CarMover *)g_movobj : NULL;
    g_car.pDynamicCollisionBody = ccb ? (CarCollisionBody *)g_ccbobj : NULL;
    g_car.pCarDamage = dmg ? (CarDamage *)g_dmgobj : NULL;
    g_car.pRenderInfo = ri ? (CarRenderInfo *)g_riobj : NULL;
    g_car.pCaffeineObj = caf ? (void *)g_cafobj : NULL;
    g_car.pBaseCarSound = snd ? (BaseCarSound *)g_sndobj : NULL;

    printf("D %d\n", n);
    car_destruct(&g_car, flags);
    printf("  end\n");
    dump_car();
}

static void op_event(char *s, int n)
{
    int car = (int)tok(&s);

    fill_car();
    g_pos_null = 0;
    memset(&g_evt, PATTERN, sizeof g_evt);
    g_evt.CarPtr = car ? &g_car : NULL;
    printf("E %d\n", n);
    car_reflect_event_handler(&g_evt);
    printf("  end\n");
}

int main(int argc, char **argv)
{
    FILE *in;
    char line[1024];
    int n = 0;

    if (argc != 2) {
        fprintf(stderr, "usage: carinit_test scenarios.txt\n");
        return 2;
    }
    in = fopen(argv[1], "r");
    if (in == NULL) {
        perror(argv[1]);
        return 2;
    }

    gCreatePlayerCarSoundFn = create_player;
    gCreateAICarSoundFn = create_ai;
    gCreateAICopCarSoundFn = create_cop;
    gBaseCarSoundDestroyFn = sound_destroy;
    gCarDamageCtorFn = damage_ctor;
    gCarDamageFindItemPartsFn = damage_parts;
    gCarDamageDestroyFn = damage_destroy;
    gCarInitRenderInfoFn = init_render_info;
    gCarRenderInfoDestroyFn = render_info_destroy;
    gEmAddHandlerFn = em_add;
    gEmRemoveHandlerFn = em_remove;
    gEspSetAttributeIntFn = esp_set_attr;
    gEspDeleteObjectFn = esp_delete;

    while (fgets(line, sizeof line, in) != NULL) {
        char *s = line + 1;

        switch (line[0]) {
        case 'C': op_ctor(s, n++); break;
        case 'D': op_dtor(s, n++); break;
        case 'E': op_event(s, n++); break;
        default: break;
        }
        fflush(stdout);
    }
    fclose(in);
    return 0;
}
