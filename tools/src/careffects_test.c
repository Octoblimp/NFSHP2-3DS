// Host harness for 3DS Files/source/careffects.c, Car::TriggerCarTerrainEffects.
// Runs the op script tools/careffects_check.py writes and prints the
// transcript it diffs against the retail image, run in mipsemu over the
// same script.
//
// The effect, the sound's splash, the replay's RegisterInterestingEvent and
// the topology's GetElevation are stand-ins that print their arguments; the
// elevation answers the terrain the case names. The wipers, the body
// damage, bMulMatrix and the terrain table are the port's own.
//
// A float prints as its bits.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "car.h"
#include "cardamage.h"
#include "carrenderinfo.h"
#include "collisionsound.h"
#include "epositionmarker.h"
#include "carstate.h"
#include "engine.h"
#include "physicscar.h"
#include "race.h"
#include "realtime.h"
#include "replay.h"
#include "terraintype.h"
#include "topology.h"

// realtime.c's, replay.c's, race.c's and carrace.c's, which the harness
// does not link.
int32_t WorldTimer = 0;
int32_t WorldTimeFrames = 0;
int32_t WorldLoopCounter = 0;
ReplayManager *pReplayManager;
RaceParameters TheRaceParameters;
CarTriggerEffectFn gCarTriggerEffectFn;

// cardamage.c's write side calls these; nothing this harness runs takes a
// hit, so each is a link stand-in that stops the run if reached.
static void unreached(const char *what)
{
    fprintf(stderr, "%s reached\n", what);
    exit(3);
}

ePositionMarker *eFindPositionMarker(uint32_t name_hash, uint32_t type_hash,
                                     ePositionMarker *prev)
{
    (void)name_hash; (void)type_hash; (void)prev;
    unreached("eFindPositionMarker");
    return NULL;
}

void collision_sound_play_glass(const bVector3 *pos)
{
    (void)pos;
    unreached("collision_sound_play_glass");
}

void carrenderinfo_update_car_replacement_textures(CarRenderInfo *ri)
{
    (void)ri;
    unreached("carrenderinfo_update_car_replacement_textures");
}

void emodel_set_environment_mapping(eModel *m, uint32_t hash, int32_t on)
{
    (void)m; (void)hash; (void)on;
    unreached("emodel_set_environment_mapping");
}

void bFree(void *p)
{
    (void)p;
    unreached("bFree");
}

static Car        car;
static CarDamage  cdmg;
static PhysicsCar pcar;
static Engine     engine;
static char       player[20];
static char       snd[16];
static ReplayManager rm;
static int32_t    g_ground;

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

static const char *label(const void *p)
{
    static char buf[32];

    if (p == NULL)
        return "NULL";
    if (p == &car)
        return "car";
    if (p == &car.TheTopologyCoordinate)
        return "car.tc";
    if (p == &car.State.Position)
        return "pos";
    if (p == snd)
        return "snd";
    if (p == &rm)
        return "rm";
    snprintf(buf, sizeof buf, "?");
    return buf;
}

// ---------------------------------------------------------- the stand-ins

static void fake_effect(Car *c, CarEffect fx, float scale, int32_t where,
                        bVector3 *pos)
{
    printf("effect car=%s fx=%d scale=%08x where=%08x", label(c), (int)fx,
           bits(scale), (unsigned)where);
    if (pos != NULL)
        printf(" at=%08x %08x %08x %08x", bits(pos->x), bits(pos->y),
               bits(pos->z), bits(pos->pad));
    else
        printf(" at=NULL");
    printf("\n");
}

static void fake_splash(BaseCarSound *s, int32_t right, int32_t level)
{
    printf("splash snd=%s right=%d level=%d\n", label(s), (int)right,
           (int)level);
}

void ReplayManager_RegisterInterestingEvent(ReplayManager *r, float value,
                                            const char *description)
{
    printf("interesting rm=%s value=%08x what=%s\n", label(r), bits(value),
           description);
}

float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    printf("elev tc=%s pos=%s tout=%s nout=%s found=%s\n", label(tc),
           label(pt), terrain != NULL ? "yes" : "NULL", label(normal),
           label(found));
    if (terrain != NULL)
        *terrain = g_ground;
    return 0.0f;
}

// ---------------------------------------------------------------- the ops

static char *tok(void)
{
    char *t = strtok(NULL, " \t");

    if (t == NULL) {
        fprintf(stderr, "careffects_test: short line\n");
        exit(2);
    }
    return t;
}

static int32_t itok(void)
{
    return (int32_t)strtol(tok(), NULL, 0);
}

static uint32_t xtok(void)
{
    return (uint32_t)strtoul(tok(), NULL, 16);
}

static float ftok(void)
{
    return from_bits(xtok());
}

// The state every case shares: the position, the velocity and the four
// wheel matrices, from the script's S lines.
static void op_state(void)
{
    CarState *cs = &car.State;
    const char *what = tok();
    int i, k;

    if (!strcmp(what, "pos")) {
        cs->Position.x = ftok();
        cs->Position.y = ftok();
        cs->Position.z = ftok();
        cs->Position.pad = ftok();
    } else if (!strcmp(what, "vel")) {
        cs->Velocity.x = ftok();
        cs->Velocity.y = ftok();
        cs->Velocity.z = ftok();
        cs->Velocity.pad = ftok();
    } else if (!strcmp(what, "wm")) {
        i = itok();
        for (k = 0; k < 16; k++)
            ((float *)(void *)&cs->WheelMatrix[i])[k] = ftok();
    } else {
        fprintf(stderr, "careffects_test: bad state %s\n", what);
        exit(2);
    }
}

// A case: every field TriggerCarTerrainEffects reads, then the call, then
// what it leaves in the car.
static void op_fx(void)
{
    CarState *cs = &car.State;
    TerrainTypeInfo *t4 = &TerrainTypeInfoTable[4];
    float min0 = t4->DriveOverMinSpeed, max0 = t4->DriveOverMaxSpeed;
    float dist, pmin, pmax;
    int32_t hasdmg, items, total, enabled, reg, patch;
    int i;

    dist = ftok();
    cs->VelocityMagnitude = ftok();
    for (i = 0; i < 4; i++)
        cs->WheelTouchingGround[i] = (int8_t)itok();
    for (i = 0; i < 4; i++)
        cs->WheelTerrain[i] = (TerrainType)itok();
    for (i = 0; i < 4; i++) {
        cs->WheelSlip[i].x = ftok();
        cs->WheelSlip[i].y = ftok();
    }
    for (i = 0; i < 4; i++)
        car.NumTimesSkidding[i] = (uint8_t)itok();
    g_ground = itok();
    for (i = 0; i < 4; i++)
        cs->WheelBottomOutMagnitude[i] = ftok();
    hasdmg = itok();
    items = (int32_t)xtok();
    total = itok();
    enabled = itok();
    if (hasdmg) {
        cdmg.BreakableCarItemDamageAmounts = (uint32_t)items;
        cdmg.TheBodyDamage.CompressedTotalDamage = (uint16_t)total;
        car.pCarDamage = &cdmg;
    } else {
        car.pCarDamage = NULL;
    }
    RaceParametersDamageEnabled = enabled;
    car.pPlayer = itok() ? (Player *)(void *)player : NULL;
    car.NitroEffectFlag = itok();
    car.TheMovementMode = (MovementMode)itok();
    engine.NitroFlag = itok();
    car.BlownTireBits = (uint8_t)itok();
    car.NumBlownTires = (uint8_t)itok();
    car.pBaseCarSound = itok() ? (BaseCarSound *)(void *)snd : NULL;
    car.WiperState = itok();
    car.WiperOnTime = (uint32_t)itok();
    car.WiperOffTime = (uint32_t)itok();
    WorldTimeFrames = itok();
    WorldLoopCounter = itok();
    reg = itok();
    if (reg >= 0)
        car.InDeepWaterRegistered = reg;
    patch = itok();
    pmin = ftok();
    pmax = ftok();
    if (patch) {
        t4->DriveOverMinSpeed = pmin;
        t4->DriveOverMaxSpeed = pmax;
    }

    car_trigger_car_terrain_effects(&car, dist);

    t4->DriveOverMinSpeed = min0;
    t4->DriveOverMaxSpeed = max0;
    printf("fx nts=%d %d %d %d wipers=%d %d %d reg=%d\n",
           (int)car.NumTimesSkidding[0], (int)car.NumTimesSkidding[1],
           (int)car.NumTimesSkidding[2], (int)car.NumTimesSkidding[3],
           (int)(int32_t)car.WiperOnTime, (int)(int32_t)car.WiperOffTime,
           (int)car.WiperState, (int)car.InDeepWaterRegistered);
}

int main(int argc, char **argv)
{
    static char line[4096];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: careffects_test SCRIPT\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    gCarTriggerEffectFn = fake_effect;
    gBaseCarSoundTriggerSplashFn = fake_splash;
    pReplayManager = &rm;
    pcar.pEngine = &engine;
    car.pCarMover = (CarMover *)(void *)&pcar;

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
            continue;
        }
        printf("> %s\n", echo);
        if (!strcmp(t, "S"))
            op_state();
        else if (!strcmp(t, "F"))
            op_fx();
        else {
            fprintf(stderr, "careffects_test: bad op %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
