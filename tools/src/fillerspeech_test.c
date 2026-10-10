// fillerspeech_test -- tools/fillerspeech_check.py's harness.
//
// Runs fillerspeech.c over the checker's script. Everything it calls is a
// stub here that logs its arguments and answers from the script, as the
// model's stubs do. Pointers print as names: U0.. the chases; anything
// else is "?".
//
//     fillerspeech_test script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "car.h"
#include "copmanager.h"
#include "fillerspeech.h"
#include "pursuit.h"
#include "pursuitchopper.h"
#include "race.h"
#include "speechmgr.h"

#define NP     3
#define NCOPS  4
#define NCARS  5
#define QN     16

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

RaceParameters TheRaceParameters;
uint32_t       bDefaultSeed;

static uint64_t speech[4];
static tPursuit ps[NP];
static tCop     cops[NCOPS];
static Car      cars[NCARS];
static uint32_t cookie;

typedef struct Queue {
    uint32_t q[QN];
    int      n, i;
    uint32_t answer;
} Queue;

static Queue chopq, spkq, secq, speedq, randq;

static uint32_t next(Queue *q)
{
    return q->i < q->n ? q->q[q->i++] : q->answer;
}

static const char *sym(const void *p)
{
    static char buf[8][16];
    static int  k;
    char       *b = buf[k++ & 7];
    int         i;

    if (p == NULL)
        return "0";
    for (i = 0; i < NP; i++)
        if (p == &ps[i]) {
            snprintf(b, 16, "U%d", i);
            return b;
        }
    return "?";
}

static const char *mgr_ok(const SpeechMgr *m)
{
    return (const void *)m == (const void *)speech ? "" : " ?mgr";
}

// ---------------------------------------------------------------- stubs

int32_t tpursuit_is_chopper_near_car(const tPursuit *p)
{
    int32_t r = (int32_t)next(&chopq);

    printf("  chopper %s -> %d\n", sym(p), (int)r);
    return r;
}

// A queue, then a counter.
uint32_t tpursuit_get_cop_speaker(const tPursuit *p)
{
    uint32_t r;

    if (spkq.i < spkq.n)
        r = spkq.q[spkq.i++];
    else
        r = spkq.answer++;
    printf("  speaker %s -> %08x\n", sym(p), (unsigned)r);
    return r;
}

uint32_t tpursuit_get_secondary_cop_speaker(const tPursuit *p)
{
    uint32_t r = next(&secq);

    printf("  secondary %s -> %08x\n", sym(p), (unsigned)r);
    return r;
}

float tpursuit_get_speed_mph_or_kph(const tPursuit *p)
{
    uint32_t r = next(&speedq);

    printf("  speed %s -> %08x\n", sym(p), (unsigned)r);
    return bf(r);
}

int32_t bRandomI(int32_t range, uint32_t *seed)
{
    int32_t r = (int32_t)next(&randq);

    printf("  random%s %d -> %d\n", seed == &bDefaultSeed ? "" : " ?seed",
           (int)range, (int)r);
    return r;
}

SpeechMgr *speechmgr_get_instance(void)
{
    return (SpeechMgr *)(void *)speech;
}

// The raises: the name and the arguments after the manager, ints signed
// and floats as bits.

void speechmgr_raise_rotor_location(SpeechMgr *m, int32_t location)
{
    printf("  rotor_location%s %d\n", mgr_ok(m), (int)location);
}

void speechmgr_raise_rotor_chatter(SpeechMgr *m, int32_t b)
{
    printf("  rotor_chatter%s %d\n", mgr_ok(m), (int)b);
}

void speechmgr_raise_rotor_traffic(SpeechMgr *m)
{
    printf("  rotor_traffic%s\n", mgr_ok(m));
}

void speechmgr_raise_pursuit_update_subject_location(SpeechMgr *m,
                                                     uint32_t speaker,
                                                     int32_t location,
                                                     int32_t b)
{
    printf("  subject_location%s %d %d %d\n", mgr_ok(m), (int)speaker,
           (int)location, (int)b);
}

void speechmgr_raise_tactic_divert(SpeechMgr *m, uint32_t speaker)
{
    printf("  tactic_divert%s %d\n", mgr_ok(m), (int)speaker);
}

void speechmgr_raise_tactic_cutoff(SpeechMgr *m, uint32_t speaker)
{
    printf("  tactic_cutoff%s %d\n", mgr_ok(m), (int)speaker);
}

void speechmgr_raise_current_speed(SpeechMgr *m, uint32_t speaker,
                                   float speed)
{
    printf("  current_speed%s %d %08x\n", mgr_ok(m), (int)speaker,
           (unsigned)fb(speed));
}

void speechmgr_raise_update_reckless(SpeechMgr *m, uint32_t speaker,
                                     int32_t b)
{
    printf("  update_reckless%s %d %d\n", mgr_ok(m), (int)speaker, (int)b);
}

void speechmgr_raise_tactic_hit(SpeechMgr *m, uint32_t speaker,
                                uint32_t target)
{
    printf("  tactic_hit%s %d %d\n", mgr_ok(m), (int)speaker, (int)target);
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

static void fill(Queue *q, char **t, int n)
{
    int i;

    q->n = 0;
    q->i = 0;
    for (i = 1; i < n && q->n < QN; i++)
        q->q[q->n++] = hx(t[i]);
}

static void run(char **t, int n)
{
    const char *o = t[0];

    if (strcmp(o, "rp") == 0) {
        if (strcmp(t[1], "BeACop") == 0)
            TheRaceParameters.BeACop = (int32_t)hx(t[2]);
        else
            TheRaceParameters.TrafficDensity = bf(hx(t[2]));
    } else if (strcmp(o, "car") == 0) {
        Car *c = &cars[ix(t[1])];

        c->State.Position.x = bf(hx(t[2]));
        c->State.Position.y = bf(hx(t[3]));
        c->State.Position.z = bf(hx(t[4]));
        c->State.ForwardSpeed = bf(hx(t[5]));
        c->State.VelocityMagnitude = bf(hx(t[6]));
    } else if (strcmp(o, "cop") == 0) {
        cops[ix(t[1])].pMyCar = &cars[ix(t[2])];
    } else if (strcmp(o, "p") == 0) {
        tPursuit *p = &ps[ix(t[1])];
        int c0 = ix(t[4]), c1 = ix(t[5]);

        p->pChasedCar = &cars[ix(t[2])];
        p->nNumCops = (int32_t)hx(t[3]);
        p->Cops[0] = c0 >= 0 ? &cops[c0] : NULL;
        p->Cops[1] = c1 >= 0 ? &cops[c1] : NULL;
        p->CurrentLandmark = (int32_t)hx(t[6]);
        p->BehaviourFlags = hx(t[7]);
    } else if (strcmp(o, "chopq") == 0) {
        fill(&chopq, t, n);
    } else if (strcmp(o, "chop") == 0) {
        chopq.answer = hx(t[1]);
    } else if (strcmp(o, "spkq") == 0) {
        fill(&spkq, t, n);
    } else if (strcmp(o, "spk") == 0) {
        spkq.answer = hx(t[1]);
    } else if (strcmp(o, "secq") == 0) {
        fill(&secq, t, n);
    } else if (strcmp(o, "sec") == 0) {
        secq.answer = hx(t[1]);
    } else if (strcmp(o, "speedq") == 0) {
        fill(&speedq, t, n);
    } else if (strcmp(o, "speed") == 0) {
        speedq.answer = hx(t[1]);
    } else if (strcmp(o, "randq") == 0) {
        fill(&randq, t, n);
    } else if (strcmp(o, "rand") == 0) {
        randq.answer = hx(t[1]);
    } else if (strcmp(o, "cookie") == 0) {
        cookie = hx(t[1]);
    } else {
        int k = ix(t[1]);
        tPursuit *p = &ps[k];

        if (strcmp(o, "near") == 0) {
            uint32_t d = hx(t[2]);

            printf("near U%d %08x -> %d\n", k, (unsigned)d,
                   (int)tpursuit_is_cop_near_chased_car(p, bf(d)));
        } else if (strcmp(o, "try") == 0) {
            int32_t r = try_filler_speech(p, &cookie);

            printf("try U%d -> %d cookie %08x\n", k, (int)r,
                   (unsigned)cookie);
        } else if (strcmp(o, "say") == 0) {
            say_filler_speech(p, &cookie);
            printf("say U%d cookie %08x\n", k, (unsigned)cookie);
        } else {
            fprintf(stderr, "unknown op %s\n", o);
            exit(2);
        }
    }
}

int main(int argc, char **argv)
{
    static char line[4096];
    char *t[MAXT];
    FILE *f;

    if (argc != 2) {
        fprintf(stderr, "usage: fillerspeech_test script\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
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
