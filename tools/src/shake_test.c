// Host harness for 3DS Files/source/shake.c and player.c's
// IsCameraPOVInCar. Runs the op script tools/shake_check.py writes and
// prints the transcript it diffs against the retail image, run in mipsemu
// over the same script.
//
// The movers' vtable has GetCameraInfo and GetPOV replaced by recorders
// that print their arguments and answer what the script set; nothing else
// in it is called.
//
// The scratch envelopes and shakers are filled with 0xa5 at the start of
// each scenario, so a field the port leaves alone and retail writes (or the
// other way round) shows. A float prints as its bits, every NaN as "nan",
// and an envelope pointer by what it points at.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cammover.h"
#include "car.h"
#include "player.h"
#include "realtime.h"
#include "shake.h"
#include "world.h"

// world.c's and realtime.c's, which the harness does not link.
World *pCurrentWorld;
float WorldTimeElapsed;

#define NENV 8
#define NPTS 17
#define NXS 4
#define NPOV 4

static tEnvelope envs[NENV];
static sEnvelopePoint pts[NENV][NPTS];
static tShaker xs[NXS];
static World world;
static struct Player players[2];
static CameraMover movs[2];
static CameraMoverVtbl TestVtbl;
static POV povs[NPOV];
static Car car;
static int info_answer[2];
static int pov_answer[2];
static CameraInfo camera_info_dummy;

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
    static char buf[32][12];
    static int slot;
    char *b = buf[slot++ & 31];
    uint32_t u = bits(f);

    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08lx", (unsigned long)u);
    return b;
}

static const char *env_name(const tEnvelope *e)
{
    static char buf[8][16];
    static int slot;
    char *b = buf[slot++ & 7];
    int k;

    if (e == NULL)
        return "null";
    if (e == &ShakeAmplitudeEnvelope)
        return "global";
    for (k = 0; k < NENV; k++) {
        if (e == &envs[k]) {
            sprintf(b, "e%d", k);
            return b;
        }
    }
    sprintf(b, "?%08lx", (unsigned long)(uint32_t)(uintptr_t)e);
    return b;
}

static int mov_index(const CameraMover *m)
{
    return m == &movs[0] ? 0 : m == &movs[1] ? 1 : -1;
}

static const CameraInfo *rec_info(CameraMover *m)
{
    int k = mov_index(m);

    printf("  info m%d\n", k);
    return info_answer[k] ? &camera_info_dummy : NULL;
}

static const POV *rec_pov(CameraMover *m, int index)
{
    int k = mov_index(m);

    printf("  pov m%d %d\n", k, index);
    return pov_answer[k] < 0 ? NULL : &povs[pov_answer[k]];
}

// A shaker by the script's name: x0..x3 the scratch ones, c0 and c1 the
// players'. `full` is whether its fourth lane is printed.
static tShaker *shaker(const char *name, int *full)
{
    int i = atoi(name + 1);

    *full = name[0] == 'x';
    return name[0] == 'x' ? &xs[i] : &CameraShakers[i];
}

static void pshaker(const char *name)
{
    int full;
    const tShaker *s = shaker(name, &full);

    printf("  %s v %s %s %s", name, fx(s->vShake.x), fx(s->vShake.y),
           fx(s->vShake.z));
    if (full)
        printf(" %s", fx(s->vShake.pad));
    printf(" amp %s t %s d %s f %s\n", env_name(s->pAmplitude),
           fx(s->fTime), fx(s->fDuration), fx(s->fFrequency));
}

static void pcams(void)
{
    pshaker("c0");
    pshaker("c1");
}

static void pvec4(const char *tag, const bVector3 *v)
{
    printf(" %s %s %s %s %s", tag, fx(v->x), fx(v->y), fx(v->z), fx(v->pad));
}

static void pglobals(void)
{
    int i;

    printf("  glob");
    pvec4("test", &vShakeTest);
    pvec4("rot", &vShakeRotation);
    pvec4("bias", &vShakeAccelBias);
    printf(" flag %ld\n", (long)bShakeTest);
    printf("  env %s n %ld pts",
           ShakeAmplitudeEnvelope.pPoints == ShakeAmplitudePoints ? "pts"
                                                                  : "?",
           (long)ShakeAmplitudeEnvelope.nPoints);
    for (i = 0; i < 5; i++)
        printf(" %s %s", fx(ShakeAmplitudePoints[i].fTime),
               fx(ShakeAmplitudePoints[i].fValue));
    printf(" k");
    for (i = 0; i < 6; i++)
        printf(" %s", fx(fShakeIntensityCoeffs[i]));
    printf("\n");
    pcams();
}

static void reset(void)
{
    memset(envs, 0xa5, sizeof envs);
    memset(pts, 0xa5, sizeof pts);
    memset(xs, 0xa5, sizeof xs);
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
static float ftok(void) { return from_bits((uint32_t)strtoul(tok(), NULL, 16)); }

static void shaker_op(const char *op)
{
    const char *name = tok();
    int full;
    tShaker *s = shaker(name, &full);

    if (!strcmp(op, "hi")) {
        tshaker_init(s);
        pshaker(name);
    } else if (!strcmp(op, "hs")) {
        bVector3 v;
        float d, f;

        v.x = ftok();
        v.y = ftok();
        v.z = ftok();
        v.pad = ftok();
        d = ftok();
        f = ftok();
        tshaker_start_shaking(s, &v, d, f);
        pshaker(name);
    } else if (!strcmp(op, "hu")) {
        tshaker_update(s, ftok());
        pshaker(name);
    } else if (!strcmp(op, "hv")) {
        bVector3 out;

        memset(&out, 0xa5, sizeof out);
        tshaker_get_value(s, &out);
        printf("  value");
        pvec4("v", &out);
        printf("\n");
    } else if (!strcmp(op, "ha")) {
        printf("  amp %s\n", fx(tshaker_get_amplitude(s)));
    } else if (!strcmp(op, "hf")) {
        const char *f = tok();

        if (!strcmp(f, "time"))
            s->fTime = ftok();
        else if (!strcmp(f, "dur"))
            s->fDuration = ftok();
        else if (!strcmp(f, "freq"))
            s->fFrequency = ftok();
        else if (!strcmp(f, "amp")) {
            int k = itok();

            s->pAmplitude = k == -1 ? NULL
                          : k == -2 ? &ShakeAmplitudeEnvelope : &envs[k];
        } else {
            fprintf(stderr, "bad field %s\n", f);
            exit(2);
        }
    }
}

int main(int argc, char **argv)
{
    static char line[4096];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: shake_test SCRIPT\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    TestVtbl.GetCameraInfo = rec_info;
    TestVtbl.GetPOV = rec_pov;
    movs[0].vtbl = &TestVtbl;
    movs[1].vtbl = &TestVtbl;
    pCurrentWorld = &world;
    shake_static_init();

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

        if (!strcmp(t, "E")) {
            int k = itok(), n = itok(), i;

            for (i = 0; i <= n; i++) {
                pts[k][i].fTime = ftok();
                pts[k][i].fValue = ftok();
            }
            envs[k].pPoints = pts[k];
            envs[k].nPoints = n;
        } else if (!strcmp(t, "I")) {
            int k = itok();

            printf("  idx %ld\n", (long)tenvelope_get_index(&envs[k], ftok()));
        } else if (!strcmp(t, "O")) {
            int k = itok();

            printf("  oor %ld\n",
                   (long)tenvelope_out_of_range(&envs[k], ftok()));
        } else if (!strcmp(t, "s")) {
            int k = itok();

            printf("  slope %s\n", fx(tenvelope_get_slope_at(&envs[k],
                                                             itok())));
        } else if (!strcmp(t, "S")) {
            int k = itok();

            printf("  slope %s\n", fx(tenvelope_get_slope(&envs[k], ftok())));
        } else if (!strcmp(t, "V")) {
            int k = itok();

            printf("  value %s\n", fx(tenvelope_get_value(&envs[k], ftok())));
        } else if (!strcmp(t, "G")) {
            int k = itok();
            float a = ftok(), b = ftok();

            printf("  integral %s\n",
                   fx(tenvelope_get_integral(&envs[k], a, b)));
        } else if (t[0] == 'h' && t[1] != 0) {
            shaker_op(t);
        } else if (!strcmp(t, "R")) {
            reset_camera_shakers();
            pcams();
        } else if (!strcmp(t, "U")) {
            WorldTimeElapsed = ftok();
            update_camera_shakers();
            printf("  flag %ld\n", (long)bShakeTest);
            pcams();
        } else if (!strcmp(t, "T")) {
            bShakeTest = itok();
        } else if (!strcmp(t, "g")) {
            bVector3 out;

            get_shake(itok(), &out);
            printf("  shake %s %s %s\n", fx(out.x), fx(out.y), fx(out.z));
        } else if (!strcmp(t, "a")) {
            printf("  active %ld\n", (long)is_shake_active(itok()));
        } else if (!strcmp(t, "W")) {
            world.fTimeScale = ftok();
        } else if (!strcmp(t, "X")) {
            vShakeRotation.x = ftok();
            vShakeRotation.y = ftok();
            vShakeRotation.z = ftok();
        } else if (!strcmp(t, "A")) {
            int view = itok(), i;
            float w[16];
            bMatrix4 m;

            for (i = 0; i < 16; i++)
                w[i] = ftok();
            m.v0.x = w[0];  m.v0.y = w[1];  m.v0.z = w[2];  m.v0.w = w[3];
            m.v1.x = w[4];  m.v1.y = w[5];  m.v1.z = w[6];  m.v1.w = w[7];
            m.v2.x = w[8];  m.v2.y = w[9];  m.v2.z = w[10]; m.v2.w = w[11];
            m.v3.x = w[12]; m.v3.y = w[13]; m.v3.z = w[14]; m.v3.w = w[15];
            apply_camera_shake(view, &m);
            printf("  m %s %s %s %s %s %s %s %s",
                   fx(m.v0.x), fx(m.v0.y), fx(m.v0.z), fx(m.v0.w),
                   fx(m.v1.x), fx(m.v1.y), fx(m.v1.z), fx(m.v1.w));
            printf(" %s %s %s %s %s %s %s %s\n",
                   fx(m.v2.x), fx(m.v2.y), fx(m.v2.z), fx(m.v2.w),
                   fx(m.v3.x), fx(m.v3.y), fx(m.v3.z), fx(m.v3.w));
        } else if (!strcmp(t, "P")) {
            int p = itok(), mv;
            struct Player *pl = &players[p];

            pl->PlayerNumber = itok();
            pl->PlayerSettings.DriveCameraPOVIndex = (int8_t)itok();
            pl->nZoneCurrent = itok();
            mv = itok();
            pl->pCameraMover = mv < 0 ? NULL : &movs[mv];
        } else if (!strcmp(t, "pp")) {
            int slot = itok(), p = itok();

            PlayerPlayersByNumber[slot] = p < 0 ? NULL : &players[p];
        } else if (!strcmp(t, "M")) {
            int k = itok();

            movs[k].Type = (CameraMoverType)itok();
            movs[k].Enabled = itok();
            info_answer[k] = itok();
            pov_answer[k] = itok();
        } else if (!strcmp(t, "v")) {
            int k = itok();

            povs[k].Type = itok();
        } else if (!strcmp(t, "Q")) {
            printf("  incar %ld\n",
                   (long)player_is_camera_pov_in_car(&players[itok()]));
        } else if (!strcmp(t, "C")) {
            int i = itok();
            bVector3 a;

            a.x = ftok();
            a.y = ftok();
            a.z = ftok();
            a.pad = 0.0f;
            maybe_camera_shake(i, &a);
            pcams();
        } else if (!strcmp(t, "c")) {
            int p = itok();

            car.pPlayer = p < 0 ? NULL : &players[p];
            car.State.Acceleration.x = ftok();
            car.State.Acceleration.y = ftok();
            car.State.Acceleration.z = ftok();
            car_maybe_camera_shake(&car);
            pcams();
        } else if (!strcmp(t, "D")) {
            pglobals();
        } else {
            fprintf(stderr, "bad op %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
