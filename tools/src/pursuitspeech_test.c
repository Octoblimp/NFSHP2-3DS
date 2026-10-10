// pursuitspeech_test -- tools/pursuitspeech_check.py's harness.
//
// Runs pursuitspeech.c and speechconv.c over the checker's script.
// Everything they call is a stub here that logs its arguments and answers
// from the script, as the model's stubs do. Pointers print as names: M the
// manager, SP the speech manager, SK the skin, L the landmark, RB0.. the
// roadblocks, U0.. chases and A0.. cars; anything else is "?".
//
//     pursuitspeech_test script.txt > out.txt

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "car.h"
#include "cartypeinfo.h"
#include "copmanager.h"
#include "copmgr.h"
#include "coputil.h"
#include "pursuit.h"
#include "pursuitspeech.h"
#include "race.h"
#include "racecoord.h"
#include "speechconv.h"
#include "speechmgr.h"

#define NP     3
#define NCARS  4
#define NRB    2
#define NTYPES 73       // -2 .. 70
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

tCopManager     *pCopManager;
RaceParameters   TheRaceParameters;
RaceCoordinator *pRaceCoordinator;
uint32_t         bDefaultSeed;
int32_t        (*gCurrLanguageFn)(void);

static tCopManager     mgr;
static RaceCoordinator rc;
static uint64_t        speech[4];
static CarTypeInfo     cti[NTYPES];
static SkinInfo        skin;
static Landmark        lm;
static int             lm_on;
static tRoadBlock      rbs[NRB];
static tPursuit        ps[NP];
static Car             cars[NCARS];
static RideInfo        rides[NCARS];
static DriverInfo      drivers[NCARS];
static char            player[16];

static int32_t  lang;
static uint32_t spk, cur, res;
static int32_t  tickets;
static int      coll = -1;
static int32_t  randq[QN];
static int      nrandq, randqi;
static int32_t  rand_answer;
static uint32_t speedq[QN];
static int      nspeedq, speedqi;
static uint32_t speed_answer;

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
    if (p == (const void *)speech)
        return "SP";
    if (p == &skin)
        return "SK";
    if (p == &lm)
        return "L";
    for (i = 0; i < NRB; i++)
        if (p == &rbs[i]) {
            snprintf(b, 16, "RB%d", i);
            return b;
        }
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
    return "?";
}

static const char *mgr_ok(const SpeechMgr *m)
{
    return (const void *)m == (const void *)speech ? "" : " ?mgr";
}

// ---------------------------------------------------------------- stubs

static int32_t get_lang(void)
{
    return lang;
}

const CarTypeInfo *cartypeinfo_get(int32_t carType)
{
    return &cti[carType + 2];
}

SkinInfo *cartypeinfo_get_skin_info(int32_t car_type, int32_t skin_number,
                                    int32_t use_default)
{
    printf("  skin %d %d %d -> SK\n", (int)car_type, (int)skin_number,
           (int)use_default);
    return &skin;
}

uint32_t tpursuit_get_cop_speaker(const tPursuit *p)
{
    uint32_t r = spk++;

    printf("  speaker %s -> %08x\n", sym(p), (unsigned)r);
    return r;
}

uint32_t copmanager_get_current_cop_speaker(tCopManager *m)
{
    printf("  cur %s -> %08x\n", sym(m), (unsigned)cur);
    return cur;
}

void copmanager_next_cop_speaker(tCopManager *m)
{
    printf("  next %s\n", sym(m));
    cur++;
}

uint32_t copmanager_reserve_cop_speaker(tCopManager *m)
{
    uint32_t r = res++;

    printf("  reserve %s -> %08x\n", sym(m), (unsigned)r);
    return r;
}

int32_t copmanager_get_num_tickets(tCopManager *m, struct Car *c)
{
    printf("  tickets %s %s -> %d\n", sym(m), sym(c), (int)tickets);
    return tickets;
}

Landmark *copmgr_find_landmark(const bVector2 *pos)
{
    Landmark *r = lm_on ? &lm : NULL;

    printf("  landmark %08x %08x -> %s\n", (unsigned)fb(pos->x),
           (unsigned)fb(pos->y), sym(r));
    return r;
}

struct Car *car_caused_recent_collision(struct Car *car)
{
    struct Car *r = coll >= 0 ? &cars[coll] : NULL;

    printf("  collision %s -> %s\n", sym(car), sym(r));
    return r;
}

void tpursuit_switch_state(tPursuit *p, ePursuitState s)
{
    printf("  switch %s %d\n", sym(p), (int)s);
    p->PursuitState = s;
}

int32_t tpursuit_is_player_involved(const tPursuit *p)
{
    int32_t r = p->pChasedCar->pPlayer != NULL
                || TheRaceParameters.BeACop != 0;

    printf("  involved %s -> %d\n", sym(p), (int)r);
    return r;
}

float tpursuit_get_speed_mph_or_kph(const tPursuit *p)
{
    uint32_t r = speedqi < nspeedq ? speedq[speedqi++] : speed_answer;

    printf("  speed %s -> %08x\n", sym(p), (unsigned)r);
    return bf(r);
}

int32_t bRandomI(int32_t range, uint32_t *seed)
{
    int32_t r = randqi < nrandq ? randq[randqi++] : rand_answer;

    printf("  random%s %d -> %d\n", seed == &bDefaultSeed ? "" : " ?seed",
           (int)range, (int)r);
    return r;
}

SpeechMgr *speechmgr_get_instance(void)
{
    return (SpeechMgr *)(void *)speech;
}

void speechmgr_flush_queue(SpeechMgr *m)
{
    printf("  flush%s\n", mgr_ok(m));
}

// The raises: the name and the arguments after the manager, ints signed
// and floats as bits.

#define R1(fn, nm)                                                          \
    void fn(SpeechMgr *m, uint32_t a)                                       \
    {                                                                       \
        printf("  " nm "%s %d\n", mgr_ok(m), (int)a);                       \
    }
#define R2(fn, nm, A, B)                                                    \
    void fn(SpeechMgr *m, A a, B b)                                         \
    {                                                                       \
        printf("  " nm "%s %d %d\n", mgr_ok(m), (int)a, (int)b);            \
    }
#define R3(fn, nm, A, B, C)                                                 \
    void fn(SpeechMgr *m, A a, B b, C c)                                    \
    {                                                                       \
        printf("  " nm "%s %d %d %d\n", mgr_ok(m), (int)a, (int)b, (int)c); \
    }
#define R4(fn, nm, A, B, C, D)                                              \
    void fn(SpeechMgr *m, A a, B b, C c, D d)                               \
    {                                                                       \
        printf("  " nm "%s %d %d %d %d\n", mgr_ok(m), (int)a, (int)b,       \
               (int)c, (int)d);                                             \
    }

R3(speechmgr_raise_begin_pursuit_id_general, "id_general", uint32_t,
   int32_t, int32_t)
R4(speechmgr_raise_begin_pursuit_id_specific, "id_specific", uint32_t,
   int32_t, int32_t, int32_t)
R4(speechmgr_raise_begin_pursuit_id_repeated, "id_repeated", uint32_t,
   int32_t, int32_t, int32_t)
R3(speechmgr_raise_begin_pursuit_again, "again", uint32_t, int32_t, int32_t)
R1(speechmgr_raise_begin_pursuit_erratic, "erratic")
R1(speechmgr_raise_begin_pursuit_general, "general")
R1(speechmgr_raise_begin_pursuit_no_id, "no_id")
R1(speechmgr_raise_cop_pursuit_avoidance, "avoidance")
R2(speechmgr_raise_begin_pursuit_cop_hit_run, "cop_hit_run", uint32_t,
   int32_t)
R2(speechmgr_raise_begin_pursuit_hit_run_traffic, "hit_run_traffic",
   uint32_t, int32_t)
R1(speechmgr_raise_backup_request, "backup_request")
R2(speechmgr_raise_backup_request_location, "backup_request_location",
   uint32_t, int32_t)
R2(speechmgr_raise_backup_confirm, "backup_confirm", uint32_t, uint32_t)
R3(speechmgr_raise_suspect_found, "suspect_found", uint32_t, int32_t,
   int32_t)
R2(speechmgr_raise_rotor_spike_failed, "rotor_spike_failed", uint32_t,
   int32_t)
R3(speechmgr_raise_spike_strip_failure, "spike_strip_failure", uint32_t,
   int32_t, uint32_t)
R3(speechmgr_raise_road_block_failure_through, "rb_failure_through",
   uint32_t, int32_t, uint32_t)
R3(speechmgr_raise_road_block_failure_avoid, "rb_failure_avoid", uint32_t,
   int32_t, uint32_t)
R2(speechmgr_raise_request_another_roadblock, "request_another", uint32_t,
   int32_t)
R3(speechmgr_raise_spike_strip_set, "spike_set", uint32_t, int32_t, int32_t)
R3(speechmgr_raise_spike_strip_set_right, "spike_set_right", uint32_t,
   int32_t, int32_t)
R3(speechmgr_raise_spike_strip_set_left, "spike_set_left", uint32_t,
   int32_t, int32_t)
R2(speechmgr_raise_road_block_setting, "rb_setting", uint32_t, int32_t)
R3(speechmgr_raise_road_block_set, "rb_set", uint32_t, int32_t, int32_t)
R2(speechmgr_raise_cop_back_off, "cop_back_off", uint32_t, int32_t)
R1(speechmgr_raise_radio_arrest, "radio_arrest")
R2(speechmgr_raise_car_stopped, "car_stopped", uint32_t, int32_t)

void speechmgr_raise_super_back_off(SpeechMgr *m)
{
    printf("  super_back_off%s\n", mgr_ok(m));
}

void speechmgr_raise_begin_pursuit_speed(SpeechMgr *m, uint32_t speaker,
                                         float speed)
{
    printf("  speed_raise%s %d %08x\n", mgr_ok(m), (int)speaker,
           (unsigned)fb(speed));
}

void speechmgr_raise_super_initiate(SpeechMgr *m, uint32_t speaker,
                                    float speed, int32_t location,
                                    int32_t exact, int32_t color)
{
    printf("  super_initiate%s %d %08x %d %d %d\n", mgr_ok(m), (int)speaker,
           (unsigned)fb(speed), (int)location, (int)exact, (int)color);
}

// ---------------------------------------------------------------- dumps

static void pdump(int k)
{
    const tPursuit *p = &ps[k];

    printf("U%d state %d sub %d prim %08x sec %08x joined %d hit %d\n", k,
           (int)p->PursuitState, (int)p->PursuitSubState,
           (unsigned)p->PrimaryCopSpeaker, (unsigned)p->SecondaryCopSpeaker,
           (int)p->bAlreadyJoined, (int)p->bAlreadyBeenHit);
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
        if (strcmp(t[1], "BeACop") == 0)
            TheRaceParameters.BeACop = (int32_t)hx(t[2]);
        else
            TheRaceParameters.NumPlayerCars = (int32_t)hx(t[2]);
    } else if (strcmp(o, "lang") == 0) {
        lang = (int32_t)hx(t[1]);
    } else if (strcmp(o, "rc") == 0) {
        rc.CurrentRCState = (RCState)hx(t[1]);
    } else if (strcmp(o, "m") == 0) {
        if (strcmp(t[1], "beacopid") == 0)
            mgr.BeACopId = hx(t[2]);
        else
            mgr.fSupervisorTimer = bf(hx(t[2]));
    } else if (strcmp(o, "cti") == 0) {
        cti[ix(t[1]) + 2].UsageType = (int32_t)hx(t[2]);
    } else if (strcmp(o, "skin") == 0) {
        skin.PaintType = (int32_t)hx(t[1]);
    } else if (strcmp(o, "lm") == 0) {
        lm_on = ix(t[1]) >= 0;
        lm.LandmarkType = (int32_t)hx(t[2]);
    } else if (strcmp(o, "ride") == 0) {
        RideInfo *r = &rides[ix(t[1])];

        r->Type = (int32_t)hx(t[2]);
        r->SkinNumber = (int8_t)hx(t[3]);
    } else if (strcmp(o, "car") == 0) {
        int k = ix(t[1]);

        cars[k].pPlayer = hx(t[2]) ? (Player *)(void *)player : NULL;
        drivers[k].TheDriverType = (DriverType)hx(t[3]);
    } else if (strcmp(o, "rb") == 0) {
        tRoadBlock *b = &rbs[ix(t[1])];

        b->nSpikeSide = (int32_t)hx(t[2]);
        b->v2Position.x = bf(hx(t[3]));
        b->v2Position.y = bf(hx(t[4]));
        b->CopSpeaker = hx(t[5]);
    } else if (strcmp(o, "p") == 0) {
        tPursuit *p = &ps[ix(t[1])];

        p->pChasedCar = AT(cars, t[2]);
        p->pRoadBlock = AT(rbs, t[3]);
        p->nNumCops = (int32_t)hx(t[4]);
        p->PursuitState = (ePursuitState)hx(t[5]);
        p->PursuitSubState = (eLogicSubState)hx(t[6]);
        p->PrimaryCopSpeaker = hx(t[7]);
        p->SecondaryCopSpeaker = hx(t[8]);
        p->CurrentLandmark = (int32_t)hx(t[9]);
        p->bAlreadyJoined = (int32_t)hx(t[10]);
        p->bAlreadyBeenHit = (int32_t)hx(t[11]);
        p->ChopperState = (eChopperState)hx(t[12]);
        p->BehaviourFlags = hx(t[13]);
    } else if (strcmp(o, "spk") == 0) {
        spk = hx(t[1]);
    } else if (strcmp(o, "cur") == 0) {
        cur = hx(t[1]);
    } else if (strcmp(o, "res") == 0) {
        res = hx(t[1]);
    } else if (strcmp(o, "tickets") == 0) {
        tickets = (int32_t)hx(t[1]);
    } else if (strcmp(o, "coll") == 0) {
        coll = ix(t[1]);
    } else if (strcmp(o, "randq") == 0) {
        int i;

        nrandq = 0;
        randqi = 0;
        for (i = 1; i < n && nrandq < QN; i++)
            randq[nrandq++] = (int32_t)hx(t[i]);
    } else if (strcmp(o, "rand") == 0) {
        rand_answer = (int32_t)hx(t[1]);
    } else if (strcmp(o, "speedq") == 0) {
        int i;

        nspeedq = 0;
        speedqi = 0;
        for (i = 1; i < n && nspeedq < QN; i++)
            speedq[nspeedq++] = hx(t[i]);
    } else if (strcmp(o, "speed") == 0) {
        speed_answer = hx(t[1]);
    } else if (strcmp(o, "conv") == 0) {
        int32_t v = (int32_t)hx(t[1]);

        printf("conv %d -> %d\n", (int)v, (int)speech_convert_car_type(v));
    } else {
        int k = ix(t[1]);
        tPursuit *p = &ps[k];

        if (strcmp(o, "colour") == 0)
            printf("colour U%d -> %d\n", k,
                   (int)tpursuit_get_chased_car_colour(p));
        else if (strcmp(o, "exact") == 0)
            printf("exact U%d -> %d\n", k,
                   (int)tpursuit_get_exact_description(p));
        else if (strcmp(o, "cansup") == 0)
            printf("cansup U%d -> %d\n", k,
                   (int)tpursuit_can_supervisor_initiate(p));
        else if (strcmp(o, "backup") == 0)
            tpursuit_raise_backup_speech(p);
        else if (strcmp(o, "declare") == 0)
            tpursuit_declare_pursuit_speech(p);
        else if (strcmp(o, "collspeech") == 0)
            tpursuit_begin_pursuit_collision_speech(p, &cars[ix(t[2])]);
        else if (strcmp(o, "start") == 0)
            tpursuit_start_pursuit_speech(p);
        else if (strcmp(o, "join") == 0)
            tpursuit_join_pursuit_speech(p);
        else if (strcmp(o, "rbfail") == 0)
            tpursuit_roadblock_failed_speech(p, (int32_t)hx(t[2]));
        else if (strcmp(o, "rbset") == 0)
            tpursuit_road_block_set_speech(p);
        else if (strcmp(o, "backoff") == 0)
            tpursuit_cop_back_off_speech(p);
        else if (strcmp(o, "ticket") == 0)
            tpursuit_ai_ticket_speech(p);
        else if (strcmp(o, "super") == 0)
            tpursuit_super_initiates(p);
        else {
            fprintf(stderr, "unknown op %s\n", o);
            exit(2);
        }
        printf("%s U%d\n", o, k);
        pdump(k);
    }
}

int main(int argc, char **argv)
{
    static char line[4096];
    char *t[MAXT];
    FILE *f;
    int k;

    if (argc != 2) {
        fprintf(stderr, "usage: pursuitspeech_test script\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    pCopManager = &mgr;
    pRaceCoordinator = &rc;
    gCurrLanguageFn = get_lang;
    for (k = 0; k < NCARS; k++) {
        cars[k].pRideInfo = &rides[k];
        cars[k].MyDriver = &drivers[k];
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
