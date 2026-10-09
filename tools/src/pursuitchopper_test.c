// pursuitchopper_test -- tools/pursuitchopper_check.py's harness.
//
// Runs pursuitchopper.c over the checker's script. Everything it calls is
// a stub here that logs its arguments and answers from the script, as the
// model's stubs do. Pointers print as names: M the manager, W the world,
// RB the roadblock, S the sample, U0.. chases, A0.. cars, H0..
// helicopters and C0.. cops; anything else is "?".
//
//     pursuitchopper_test script.txt > out.txt

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "car.h"
#include "chopper.h"
#include "copmanager.h"
#include "playerinit.h"
#include "pursuit.h"
#include "pursuitchopper.h"
#include "race.h"
#include "rcstates.h"
#include "realtime.h"
#include "world.h"

#define NP    3
#define NCARS 3
#define NH    2
#define NCOPS 3
#define RANDQ 16

static uint32_t fb(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float bf(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

// ---------------------------------------------------- what the port reads

World          *pCurrentWorld;
tCopManager    *pCopManager;
RaceParameters  TheRaceParameters;
float           WorldTimeElapsed;
struct bSample *(*gGetInGameSampleFn)(const char *name);
void (*gSamplePlayFn)(struct bSample *s, float volume, float a, float b);

static World          world;
static tCopManager    mgr;
static char           rb[16];
static char           smp[16];
static tPursuit       ps[NP];
static Car            cars[NCARS];
static struct Chopper hs[NH];
static tCop           cops[NCOPS];

static uint32_t spk;
static int32_t  randq[RANDQ];
static int      nrandq, randqi;
static int32_t  rand_answer;
static int      sample_on = 1;

static const char *sym(const void *p)
{
    static char buf[8][16];
    static int  k;
    char       *b = buf[k++ & 7];
    int         i;

    if (p == NULL)
        return "0";
    if (p == &mgr)
        return "M";
    if (p == &world)
        return "W";
    if (p == rb)
        return "RB";
    if (p == smp)
        return "S";
    for (i = 0; i < NP; i++)
        if (p == &ps[i]) {
            snprintf(b, 16, "U%d", i);
            return b;
        }
    for (i = 0; i < NCARS; i++)
        if (p == &cars[i]) {
            snprintf(b, 16, "A%d", i);
            return b;
        }
    for (i = 0; i < NH; i++)
        if (p == &hs[i]) {
            snprintf(b, 16, "H%d", i);
            return b;
        }
    for (i = 0; i < NCOPS; i++)
        if (p == &cops[i]) {
            snprintf(b, 16, "C%d", i);
            return b;
        }
    return "?";
}

// ---------------------------------------------------------------- stubs

uint32_t tpursuit_get_cop_speaker(const tPursuit *p)
{
    printf("  speaker %s -> %08x\n", sym(p), (unsigned)spk);
    return spk;
}

static void rotor_request(uint32_t speaker, int32_t supervisor)
{
    printf("  speech rotor_request %08x %d\n", (unsigned)speaker,
           (int)supervisor);
}

static void rotor_confirm(void)
{
    printf("  speech rotor_confirm\n");
}

static void heli_na(uint32_t speaker)
{
    printf("  speech heli_na %08x\n", (unsigned)speaker);
}

void chopper_abort_bombing_run(struct Chopper *h)
{
    printf("  abort %s\n", sym(h));
}

int32_t chopper_follow_this_car(struct Chopper *h, struct Car *car)
{
    printf("  follow %s %s\n", sym(h), sym(car));
    return 1;
}

int32_t chopper_attack_car(struct Chopper *h, ChopperAttackType type)
{
    printf("  attack %s %d\n", sym(h), (int)type);
    return 1;
}

int32_t world_random_i(World *w, int32_t range)
{
    int32_t r = randqi < nrandq ? randq[randqi++] : rand_answer;

    printf("  random%s %d -> %d\n", w == &world ? "" : " ?w", (int)range,
           (int)r);
    return r;
}

static struct bSample *get_sample(const char *name)
{
    struct bSample *r = sample_on ? (struct bSample *)(void *)smp : NULL;

    printf("  sample %s -> %s\n", name, sym(r));
    return r;
}

static void sample_play(struct bSample *s, float volume, float a, float b)
{
    printf("  play %s %08x %08x %08x\n", sym(s), (unsigned)fb(volume),
           (unsigned)fb(a), (unsigned)fb(b));
}

// ---------------------------------------------------------------- dumps

static void pdump(int k)
{
    const tPursuit *p = &ps[k];

    printf("U%d chopper %s timer %08x next %08x dir %08x state %08x "
           "flags %08x\n", k, sym(p->pChopper),
           (unsigned)fb(p->fChopperAttackTimer),
           (unsigned)fb(p->fChopperNextAttackTime),
           (unsigned)fb(p->fChaseDirection), (unsigned)p->ChopperState,
           (unsigned)p->BehaviourFlags);
}

static void mdump(void)
{
    printf("M busy %d attacks %d salvos %d %d\n", (int)mgr.bChopperBusy,
           (int)mgr.nBeACopNumChopperAttacks, (int)hs[0].TotalSalvos,
           (int)hs[1].TotalSalvos);
}

// ------------------------------------------------------------- the script

#define MAXT 24

static int split(char *line, char **t)
{
    int n = 0;
    char *s = line;

    for (;;) {
        char *bar = strchr(s, '|');

        if (n < MAXT)
            t[n++] = s;
        if (bar == NULL)
            break;
        *bar = 0;
        s = bar + 1;
    }
    return n;
}

static uint32_t hx(const char *s)
{
    return (uint32_t)strtoll(s, NULL, 0);
}

static int ix(const char *s)
{
    return (int)strtol(s, NULL, 0);
}

#define AT(arr, s) (ix(s) >= 0 ? &(arr)[ix(s)] : NULL)

static void run(char **t, int n)
{
    const char *o = t[0];

    if (strcmp(o, "rp") == 0) {
        if (strcmp(t[1], "New624") == 0)
            TheRaceParameters.New624 = (int32_t)hx(t[2]);
        else
            TheRaceParameters.BeACop = (int32_t)hx(t[2]);
    } else if (strcmp(o, "dt") == 0) {
        WorldTimeElapsed = bf(hx(t[1]));
    } else if (strcmp(o, "world") == 0) {
        world.Helicopter = AT(hs, t[1]);
    } else if (strcmp(o, "m") == 0) {
        uint32_t v = hx(t[2]);

        if (strcmp(t[1], "nrb") == 0)
            mgr.nBeACopNumRoadBlocks = (int32_t)v;
        else if (strcmp(t[1], "pcidx") == 0)
            mgr.nPlayerCopIndex = (int32_t)v;
        else if (strcmp(t[1], "busy") == 0)
            mgr.bChopperBusy = (int32_t)v;
        else if (strcmp(t[1], "beacopid") == 0)
            mgr.BeACopId = v;
        else if (strcmp(t[1], "super") == 0)
            mgr.fSupervisorTimer = bf(v);
        else if (strcmp(t[1], "attacks") == 0)
            mgr.nBeACopNumChopperAttacks = (int32_t)v;
        else
            fprintf(stderr, "no field %s\n", t[1]);
    } else if (strcmp(o, "mcop") == 0) {
        mgr.Cops[ix(t[1])] = AT(cops, t[2]);
    } else if (strcmp(o, "cop") == 0) {
        cops[ix(t[1])].pMyPursuit = AT(ps, t[2]);
    } else if (strcmp(o, "car") == 0) {
        Car *c = &cars[ix(t[1])];

        c->State.Position.x = bf(hx(t[2]));
        c->State.Position.y = bf(hx(t[3]));
        c->BlownTireBits = (uint8_t)hx(t[4]);
    } else if (strcmp(o, "h") == 0) {
        struct Chopper *h = &hs[ix(t[1])];

        h->CurrentCar = AT(cars, t[2]);
        h->BombRunType = (ChopperAttackType)hx(t[3]);
        h->TotalSalvos = (int32_t)hx(t[4]);
        h->CurrentPos.x = bf(hx(t[5]));
        h->CurrentPos.y = bf(hx(t[6]));
        h->New960 = (int32_t)hx(t[7]);
    } else if (strcmp(o, "p") == 0) {
        tPursuit *p = &ps[ix(t[1])];

        p->pChasedCar = AT(cars, t[2]);
        p->pRoadBlock = hx(t[3]) ? (tRoadBlock *)(void *)rb : NULL;
        p->pChopper = AT(hs, t[4]);
        p->fChopperAttackTimer = bf(hx(t[5]));
        p->fChopperNextAttackTime = bf(hx(t[6]));
        p->fChaseDirection = bf(hx(t[7]));
        p->ChopperState = (eChopperState)hx(t[8]);
        p->BehaviourFlags = hx(t[9]);
    } else if (strcmp(o, "spk") == 0) {
        spk = hx(t[1]);
    } else if (strcmp(o, "randq") == 0) {
        int i;

        nrandq = 0;
        randqi = 0;
        for (i = 1; i < n && nrandq < RANDQ; i++)
            randq[nrandq++] = (int32_t)hx(t[i]);
    } else if (strcmp(o, "rand") == 0) {
        rand_answer = (int32_t)hx(t[1]);
    } else if (strcmp(o, "sample") == 0) {
        sample_on = hx(t[1]) != 0;
    } else if (strcmp(o, "upd") == 0) {
        int k = ix(t[1]);

        tpursuit_update_chopper(&ps[k]);
        printf("upd U%d\n", k);
        pdump(k);
        mdump();
    } else if (strcmp(o, "avail") == 0) {
        printf("avail -> %d\n", (int)tcopmanager_is_chopper_available(&mgr));
    } else if (strcmp(o, "req") == 0) {
        struct Chopper *h = tcopmanager_request_chopper(&mgr);

        printf("req -> %s\n", sym(h));
        mdump();
    } else if (strcmp(o, "bacrc") == 0 || strcmp(o, "bacrr") == 0) {
        int k;

        if (o[4] == 'c')
            tcopmanager_be_a_cop_request_chopper(&mgr);
        else
            tcopmanager_be_a_cop_request_road_block(&mgr);
        printf("%s\n", o);
        for (k = 0; k < NP; k++)
            pdump(k);
        mdump();
    } else if (strcmp(o, "near") == 0) {
        int k = ix(t[1]);

        printf("near U%d -> %d\n", k, (int)tpursuit_is_chopper_near_car(&ps[k]));
    } else {
        fprintf(stderr, "unknown op %s\n", o);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[4096];
    char *t[MAXT];
    FILE *f;

    if (argc != 2) {
        fprintf(stderr, "usage: pursuitchopper_test script\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    pCurrentWorld = &world;
    pCopManager = &mgr;
    gGetInGameSampleFn = get_sample;
    gSamplePlayFn = sample_play;
    gSpeechRaiseRotorRequestFn = rotor_request;
    gSpeechRaiseRotorConfirmFn = rotor_confirm;
    gSpeechRaiseDispatchHelicopterNAFn = heli_na;
    while (fgets(line, sizeof line, f) != NULL) {
        char *e = line + strlen(line);
        int n;

        while (e > line && (e[-1] == '\n' || e[-1] == '\r'))
            *--e = 0;
        if (line[0] == 0)
            continue;
        n = split(line, t);
        run(t, n);
    }
    fclose(f);
    return 0;
}
