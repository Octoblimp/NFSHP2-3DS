// Harness for tools/speechmgr_check.py: runs the checker's script on
// speechmgr.c and prints what the model prints for the retail image.
// SpeechNoise's calls, the wedge's, SPCH_AddEventV, bRandom and the race
// coordinator are logging fakes, the same fakes the checker gives
// retail's code. See the checker's docstring.
//
//     speechmgr_test script.txt > out.txt

#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "race.h"
#include "sedwedge.h"
#include "spch.h"
#include "speechmgr.h"
#include "speechnoise.h"

static uint32_t bits(float f)
{
    uint32_t v;

    memcpy(&v, &f, 4);
    return v;
}

static float fl(uint32_t v)
{
    float f;

    memcpy(&f, &v, 4);
    return f;
}

// ------------------------------------------------------------- the fakes

#define MAXQ 256

static SpeechMgr   M;
static SpeechNoise fakenoise;
static SedWedge    fakewedge;
static int         haveWedge;
static int32_t     radio;
static int32_t     randQ[MAXQ];
static int         nRand, atRand;

struct RaceCoordinator {
    int32_t CurrentRCState;
};
static RaceCoordinator fakerc;
RaceCoordinator *pRaceCoordinator;
uint32_t bDefaultSeed;

static const char *nname(const SpeechNoise *n)
{
    return n == &fakenoise ? "noise" : "?";
}

static const char *wname(const SedWedge *w)
{
    return w == &fakewedge ? "wedge" : "?";
}

SpeechNoise *speechnoise_get_instance(void)
{
    return &fakenoise;
}

void speechnoise_begin_squelch_noise(SpeechNoise *n)
{
    printf("  squelch %s\n", nname(n));
}

void speechnoise_start_helicopter_noise(SpeechNoise *n)
{
    printf("  heli on %s\n", nname(n));
}

void speechnoise_stop_helicopter_noise(SpeechNoise *n)
{
    printf("  heli off %s\n", nname(n));
}

void speechnoise_start_radio_noise(SpeechNoise *n)
{
    printf("  radio on %s\n", nname(n));
    radio = 1;
}

void speechnoise_stop_radio_noise(SpeechNoise *n)
{
    printf("  radio off %s\n", nname(n));
    radio = 0;
}

int32_t speechnoise_is_radio_noise(const SpeechNoise *n)
{
    printf("  isradio %s -> %d\n", nname(n), radio);
    return radio;
}

SedWedge *sedwedge_sound_instance(void)
{
    return haveWedge ? &fakewedge : NULL;
}

int32_t sedwedge_clear_event_queue(SedWedge *w)
{
    printf("  clearq %s\n", wname(w));
    return 1;
}

void sedwedge_fade(SedWedge *w, float fade)
{
    printf("  fade %s %08x\n", wname(w), bits(fade));
}

void sedwedge_mute(SedWedge *w, bool on)
{
    printf("  wmute %s %d\n", wname(w), on ? 1 : 0);
}

int32_t spch_add_event_v(uint32_t id, int32_t count, ...)
{
    va_list ap;
    int32_t i;

    printf("  spch %u %d:", id, count);
    va_start(ap, count);
    for (i = 0; i < count; i++)
        printf(" %x", (uint32_t)va_arg(ap, int));
    va_end(ap);
    printf("\n");
    return 1;
}

int32_t bRandomI(int32_t range, uint32_t *seed)
{
    int32_t r = atRand < nRand ? randQ[atRand++] : 0;

    if (range > 0)
        r %= range;
    printf("  rand %d -> %d%s\n", range, r,
           seed == &bDefaultSeed ? "" : " (seed?)");
    return r;
}

RCState racecoordinator_get_current_state(const RaceCoordinator *rc)
{
    return rc->CurrentRCState;
}

int32_t racecoordinator_is_replay_demo_mode(const RaceCoordinator *rc)
{
    return rc->CurrentRCState == RCSTATE_REPLAY_DEMO_MODE;
}

// ------------------------------------------------------------- the dump

static void dump(void)
{
    const uint32_t *t;
    int k, i;

    printf("  st=%d q=%d,%d %d,%d r=%d w=%d full=%d nc=%d cc=%d sp=%d\n",
           M.state, M.queue[0].event, M.queue[0].contextNum,
           M.queue[1].event, M.queue[1].contextNum, M.read, M.write,
           M.full, M.nextContext, M.currContext, M.previousSedPlaybackState);
    for (k = 0; k < SPEECHMGR_CONTEXTS; k++) {
        const uint32_t *w = (const uint32_t *)(const void *)&M.contexts[k];

        printf("  c%d", k);
        for (i = 0; i < 14; i++)
            printf(" %x", w[i]);
        printf("\n");
    }
    printf("  ids");
    for (k = 0; k < 3; k++) {
        t = speechcontext_id_table(k);
        printf(" %x %x %x %x", t[0], t[1], t[2], t[3]);
    }
    printf("\n");
}

// --------------------------------------------------------------- the ops

static uint32_t U(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static int32_t I(const char *s)
{
    return (int32_t)strtol(s, NULL, 0);
}

static int raise_op(char **f, int nf)
{
    const char *n = f[1];
    SpeechMgr *m = &M;

    (void)nf;
#define A(k) U(f[2 + (k)])
#define B(k) I(f[2 + (k)])
#define F(k) fl(U(f[2 + (k)]))
    if (!strcmp(n, "pcophit"))
        speechmgr_raise_pursuit_cop_hit(m, A(0), B(1));
    else if (!strcmp(n, "bpcophitrun"))
        speechmgr_raise_begin_pursuit_cop_hit_run(m, A(0), B(1));
    else if (!strcmp(n, "bpgeneral"))
        speechmgr_raise_begin_pursuit_general(m, A(0));
    else if (!strcmp(n, "bperratic"))
        speechmgr_raise_begin_pursuit_erratic(m, A(0));
    else if (!strcmp(n, "bpnoid"))
        speechmgr_raise_begin_pursuit_no_id(m, A(0));
    else if (!strcmp(n, "bphitruntraffic"))
        speechmgr_raise_begin_pursuit_hit_run_traffic(m, A(0), B(1));
    else if (!strcmp(n, "bpidgeneral"))
        speechmgr_raise_begin_pursuit_id_general(m, A(0), B(1), B(2));
    else if (!strcmp(n, "bpidspecific"))
        speechmgr_raise_begin_pursuit_id_specific(m, A(0), B(1), B(2), B(3));
    else if (!strcmp(n, "bpagain"))
        speechmgr_raise_begin_pursuit_again(m, A(0), B(1), B(2));
    else if (!strcmp(n, "bpidrepeated"))
        speechmgr_raise_begin_pursuit_id_repeated(m, A(0), B(1), B(2), B(3));
    else if (!strcmp(n, "bpspeed"))
        speechmgr_raise_begin_pursuit_speed(m, A(0), F(1));
    else if (!strcmp(n, "backupreq"))
        speechmgr_raise_backup_request(m, A(0));
    else if (!strcmp(n, "backupconfirm"))
        speechmgr_raise_backup_confirm(m, A(0), A(1));
    else if (!strcmp(n, "backupreqloc"))
        speechmgr_raise_backup_request_location(m, A(0), B(1));
    else if (!strcmp(n, "crash"))
        speechmgr_raise_crash(m, A(0), A(1));
    else if (!strcmp(n, "flattire"))
        speechmgr_raise_flat_tire(m, A(0), A(1));
    else if (!strcmp(n, "crashtow"))
        speechmgr_raise_crash_tow(m, A(0), A(1));
    else if (!strcmp(n, "avoidance"))
        speechmgr_raise_cop_pursuit_avoidance(m, A(0));
    else if (!strcmp(n, "subjectloc"))
        speechmgr_raise_pursuit_update_subject_location(m, A(0), B(1), B(2));
    else if (!strcmp(n, "suspectfound"))
        speechmgr_raise_suspect_found(m, A(0), B(1), B(2));
    else if (!strcmp(n, "tactichit"))
        speechmgr_raise_tactic_hit(m, A(0), A(1));
    else if (!strcmp(n, "tacticdivert"))
        speechmgr_raise_tactic_divert(m, A(0));
    else if (!strcmp(n, "tacticcutoff"))
        speechmgr_raise_tactic_cutoff(m, A(0));
    else if (!strcmp(n, "reckless"))
        speechmgr_raise_update_reckless(m, A(0), B(1));
    else if (!strcmp(n, "racercaught"))
        speechmgr_raise_racer_caught(m, A(0), B(1), B(2));
    else if (!strcmp(n, "superbackoff"))
        speechmgr_raise_super_back_off(m);
    else if (!strcmp(n, "copbackoff"))
        speechmgr_raise_cop_back_off(m, A(0), B(1));
    else if (!strcmp(n, "carstopped"))
        speechmgr_raise_car_stopped(m, A(0), B(1));
    else if (!strcmp(n, "radioarrest"))
        speechmgr_raise_radio_arrest(m, A(0));
    else if (!strcmp(n, "rotorrequest"))
        speechmgr_raise_rotor_request(m, A(0), B(1));
    else if (!strcmp(n, "rotorconfirm"))
        speechmgr_raise_rotor_confirm(m);
    else if (!strcmp(n, "rotorlocation"))
        speechmgr_raise_rotor_location(m, B(0));
    else if (!strcmp(n, "rotorchatter"))
        speechmgr_raise_rotor_chatter(m, B(0));
    else if (!strcmp(n, "rotorspikefailed"))
        speechmgr_raise_rotor_spike_failed(m, A(0), B(1));
    else if (!strcmp(n, "rotortraffic"))
        speechmgr_raise_rotor_traffic(m);
    else if (!strcmp(n, "rbfailavoid"))
        speechmgr_raise_road_block_failure_avoid(m, A(0), B(1), A(2));
    else if (!strcmp(n, "rbfailthrough"))
        speechmgr_raise_road_block_failure_through(m, A(0), B(1), A(2));
    else if (!strcmp(n, "rbrequest"))
        speechmgr_raise_roadblock_request(m, A(0), B(1));
    else if (!strcmp(n, "anotherrb"))
        speechmgr_raise_request_another_roadblock(m, A(0), B(1));
    else if (!strcmp(n, "rbset"))
        speechmgr_raise_road_block_set(m, A(0), B(1), B(2));
    else if (!strcmp(n, "rbsetting"))
        speechmgr_raise_road_block_setting(m, A(0), B(1));
    else if (!strcmp(n, "spikefail"))
        speechmgr_raise_spike_strip_failure(m, A(0), B(1), A(2));
    else if (!strcmp(n, "spikerequest"))
        speechmgr_raise_spike_strip_request(m, A(0), B(1));
    else if (!strcmp(n, "spikeset"))
        speechmgr_raise_spike_strip_set(m, A(0), B(1), B(2));
    else if (!strcmp(n, "spikesetleft"))
        speechmgr_raise_spike_strip_set_left(m, A(0), B(1), B(2));
    else if (!strcmp(n, "spikesetright"))
        speechmgr_raise_spike_strip_set_right(m, A(0), B(1), B(2));
    else if (!strcmp(n, "tireblow"))
        speechmgr_raise_spike_strip_tire_blow(m, A(0), B(1));
    else if (!strcmp(n, "superrequest"))
        speechmgr_raise_super_request(m, A(0));
    else if (!strcmp(n, "superinitiate"))
        speechmgr_raise_super_initiate(m, A(0), F(1), B(2), B(3), B(4));
    else if (!strcmp(n, "currentspeed"))
        speechmgr_raise_current_speed(m, A(0), F(1));
    else if (!strcmp(n, "crashtraffic"))
        speechmgr_raise_suspect_crash_traffic(m, A(0), B(1));
    else if (!strcmp(n, "lookout"))
        speechmgr_raise_dispatch_be_on_lookout(m, B(0));
    else if (!strcmp(n, "rbna"))
        speechmgr_raise_dispatch_road_block_na(m, A(0));
    else if (!strcmp(n, "helina"))
        speechmgr_raise_dispatch_helicopter_na(m, A(0));
    else
        return 0;
#undef A
#undef B
#undef F
    return 1;
}

static void op(char **f, int nf)
{
    const char *o = f[0];

    if (!strcmp(o, "ctor")) {
        speechmgr_construct(&M);
    } else if (!strcmp(o, "inst")) {
        // The instance is constructed once; the second call keeps it.
        SpeechMgr *a = speechmgr_get_instance();
        SpeechMgr *b = speechmgr_get_instance();

        printf("  inst %d st=%d nc=%d sp=%d\n", a == b, a->state,
               a->nextContext, a->previousSedPlaybackState);
        return;
    } else if (!strcmp(o, "update")) {
        speechmgr_update(&M);
    } else if (!strcmp(o, "push")) {
        speechmgr_push_speech_event(&M, I(f[1]));
    } else if (!strcmp(o, "flush")) {
        speechmgr_flush_queue(&M);
    } else if (!strcmp(o, "alloc")) {
        speechmgr_allocate_voices(&M);
    } else if (!strcmp(o, "fade")) {
        speechmgr_fade(&M, fl(U(f[1])));
    } else if (!strcmp(o, "mute")) {
        speechmgr_mute(&M, I(f[1]));
    } else if (!strcmp(o, "r")) {
        if (!raise_op(f, nf)) {
            printf("  ? %s\n", f[1]);
            return;
        }
    } else if (!strcmp(o, "conv")) {
        printf("  conv %08x -> %d\n", U(f[1]), speech_convert_speed(fl(U(f[1]))));
        return;
    } else if (!strcmp(o, "wedge")) {
        haveWedge = strcmp(f[1], "none") != 0;
        if (haveWedge)
            fakewedge.status = I(f[1]);
        return;
    } else if (!strcmp(o, "rc")) {
        if (!strcmp(f[1], "none")) {
            pRaceCoordinator = NULL;
        } else {
            pRaceCoordinator = &fakerc;
            fakerc.CurrentRCState = I(f[1]);
        }
        return;
    } else if (!strcmp(o, "radio")) {
        radio = I(f[1]);
        return;
    } else if (!strcmp(o, "rand")) {
        int i;

        nRand = atRand = 0;
        for (i = 1; i < nf && nRand < MAXQ; i++)
            randQ[nRand++] = I(f[i]);
        return;
    } else if (!strcmp(o, "ctx")) {
        uint32_t *w = (uint32_t *)(void *)&M.contexts[I(f[1])];

        w[I(f[2]) / 4] = U(f[3]);
        return;
    } else if (!strcmp(o, "state")) {
        M.state = I(f[1]);
        return;
    } else if (!strcmp(o, "curr")) {
        M.currContext = I(f[1]);
        return;
    } else if (!strcmp(o, "next")) {
        M.nextContext = I(f[1]);
        return;
    } else if (!strcmp(o, "nd")) {
        dump();
        return;
    } else {
        printf("  ? %s\n", o);
        return;
    }
    dump();
}

int main(int argc, char **argv)
{
    char line[512];
    FILE *fh;

    if (argc < 2) {
        fprintf(stderr, "usage: speechmgr_test script.txt\n");
        return 2;
    }
    fh = fopen(argv[1], "r");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
    while (fgets(line, sizeof(line), fh)) {
        char *f[32];
        int nf = 0;
        char *p;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0] || line[0] == '#')
            continue;
        printf("> %s\n", line);
        p = line;
        f[nf++] = p;
        while ((p = strchr(p, '|')) != NULL && nf < 32) {
            *p++ = 0;
            f[nf++] = p;
        }
        op(f, nf);
        fflush(stdout);
    }
    fclose(fh);
    return 0;
}
