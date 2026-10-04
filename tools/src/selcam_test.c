// Host harness for 3DS Files/source/selcam.c, the car select's turntable
// camera. Runs the op script tools/selcam_check.py writes and prints the
// transcript it diffs against the retail image, run in mipsemu over the
// same script.
//
// The harness owns what the mover reads from outside CameraMover.obj:
// RealTimeElapsed, SoundEnabled, and the four bSamples, whose calls it
// prints by the sample's name.
//
// Every camera and mover is filled with 0xa5 before it is built, so a field
// the port leaves alone and retail writes (or the other way round) shows.
// A float prints as its bits, every NaN as "nan", and a pointer by what it
// points at.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bquat.h"
#include "camera.h"
#include "cammover.h"
#include "eview.h"
#include "realtime.h"
#include "selcam.h"

#define NCAM 4
#define NMOV 3

// What selcam.c links against, the harness's own.
float   RealTimeElapsed = 1.0f / 60.0f;
int32_t SoundEnabled = 1;

static Camera cams[NCAM];
static SelectCarCameraMover movs[NMOV];

static const char *const kSample[SELCAM_SND_COUNT] = {
    "MenuCarDisplayOn", "MenuCarDisplayOff", "MenuCarDisplayActive",
    "MenuCarOrbitBump",
};

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
    if (p == &SelectCarCameraMoverVtbl)
        return "selcam";
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
    static char buf[32][12];
    static int slot;
    char *b = buf[slot++ & 31];
    uint32_t u = bits(f);

    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08lx", (unsigned long)u);
    return b;
}

// ------------------------------------------------------------ the sound

static void s_create(int s)
{
    printf("  snd new FrontEnd/%s cat 3\n", kSample[s]);
}

static void s_destroy(int s)
{
    printf("  snd del %s\n", kSample[s]);
}

static void s_play(int s, float v, float a, float b)
{
    printf("  snd play %s %s %s %s\n", kSample[s], fx(v), fx(a), fx(b));
}

static void s_stop(int s)
{
    printf("  snd stop %s\n", kSample[s]);
}

static void s_volume(int s, float v)
{
    printf("  snd vol %s %s\n", kSample[s], fx(v));
}

static void s_pitch(int s, float p)
{
    printf("  snd pitch %s %s\n", kSample[s], fx(p));
}

static const SelCamSoundFns kSound = {
    s_create, s_destroy, s_play, s_stop, s_volume, s_pitch,
};

// ------------------------------------------------------------ the dumps

static void pkey(const char *tag, const CameraParams *k)
{
    const bMatrix4 *m = &k->Matrix;

    printf("    %s m %s %s %s %s %s %s %s %s", tag,
           fx(m->v0.x), fx(m->v0.y), fx(m->v0.z), fx(m->v0.w),
           fx(m->v1.x), fx(m->v1.y), fx(m->v1.z), fx(m->v1.w));
    printf(" %s %s %s %s %s %s %s %s\n",
           fx(m->v2.x), fx(m->v2.y), fx(m->v2.z), fx(m->v2.w),
           fx(m->v3.x), fx(m->v3.y), fx(m->v3.z), fx(m->v3.w));
    printf("    %s p %s %s %s %s d %s %s %s %s t %s %s %s %s\n", tag,
           fx(k->Position.x), fx(k->Position.y), fx(k->Position.z),
           fx(k->Position.pad), fx(k->Direction.x), fx(k->Direction.y),
           fx(k->Direction.z), fx(k->Direction.pad), fx(k->Target.x),
           fx(k->Target.y), fx(k->Target.z), fx(k->Target.pad));
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

static void pquat(const char *tag, const bQuaternion *q)
{
    printf(" %s %s %s %s %s", tag, fx(q->x), fx(q->y), fx(q->z), fx(q->w));
}

static void pmov(int j)
{
    const SelectCarCameraMover *o = &movs[j];
    const CameraMover *m = &o->base;

    printf("  o%d type %d view %d en %d pview %s pcam %s player %08lx"
           " carnot %08lx dash %08lx vtbl %s next %s prev %s\n",
           j, (int)m->Type, m->ViewID, m->Enabled, nm(m->pView),
           nm(m->pCamera), (unsigned long)(uint32_t)(uintptr_t)m->pPlayer,
           (unsigned long)(uint32_t)(uintptr_t)m->CarNotToRender,
           (unsigned long)(uint32_t)m->RenderDash, nm(m->vtbl),
           nm(m->Node.next), nm(m->Node.prev));
    printf("    mode %ld blend %s u52 %08lx az %04x u58 %04x ts %04x to %04x"
           " rs %s\n",
           (long)o->Mode, fx(o->Blend), (unsigned long)(uint32_t)o->Unused52,
           (unsigned)o->AngleZ, (unsigned)o->Unused58,
           (unsigned)o->TiltStats, (unsigned)o->TiltOrbit,
           fx(o->RadiusStats));
    // The offsets' w lanes are left out: see selcam_check.py.
    printf("    os %s %s %s oo %s %s %s\n",
           fx(o->OffsetStats.x), fx(o->OffsetStats.y), fx(o->OffsetStats.z),
           fx(o->OffsetOrbit.x), fx(o->OffsetOrbit.y), fx(o->OffsetOrbit.z));
    printf("   ");
    pquat("qs", &o->QuatStats);
    pquat("qo", &o->QuatOrbit);
    printf("\n");
    printf("    fov %04x %04x hs %s %s vs %s %s or %s rsp %s %s snd %d%d%d%d"
           " n %ld\n",
           (unsigned)o->FOVStats, (unsigned)o->FOVOrbit, fx(o->HorizSpeed),
           fx(o->DesiredHorizSpeed), fx(o->VertSpeed),
           fx(o->DesiredVertSpeed), fx(o->OrbitRadius), fx(o->RadiusSpeed),
           fx(o->DesiredRadiusSpeed), o->Samples[0] != 0,
           o->Samples[1] != 0, o->Samples[2] != 0, o->Samples[3] != 0,
           (long)SelCamNormalizeCount);
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
    SoundEnabled = 1;
    SelCamNormalizeCount = 0;
}

// ------------------------------------------------------------ the script

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

static void read_quat(bQuaternion *q)
{
    q->x = ftok();
    q->y = ftok();
    q->z = ftok();
    q->w = ftok();
}

static void query(int j)
{
    CameraMover *m = &movs[j].base;
    const CameraMoverVtbl *vt = m->vtbl;

    printf("  q o%d mode %s info %s pov %s ext %d lb %d gap %s car %s"
           " tgt %s\n",
           j, fx(selcam_get_mode_param(&movs[j])), nm(vt->GetCameraInfo(m)),
           nm(vt->GetPOV(m, 0)), vt->IsExteriorView(m), vt->IsLookingBack(m),
           fx(vt->GetWallGap(m)), nm(vt->GetCarToFollow(m)),
           nm(vt->GetTarget(m)));
}

// Raw writes, for the states no setter reaches.
static void set_field(int j, const char *f, uint32_t v)
{
    SelectCarCameraMover *o = &movs[j];

    if (!strcmp(f, "mode"))
        o->Mode = (int32_t)v;
    else if (!strcmp(f, "blend"))
        o->Blend = from_bits(v);
    else if (!strcmp(f, "to"))
        o->TiltOrbit = (uint16_t)v;
    else if (!strcmp(f, "ts"))
        o->TiltStats = (uint16_t)v;
    else if (!strcmp(f, "az"))
        o->AngleZ = (uint16_t)v;
    else if (!strcmp(f, "hs"))
        o->HorizSpeed = from_bits(v);
    else if (!strcmp(f, "vs"))
        o->VertSpeed = from_bits(v);
    else if (!strcmp(f, "or"))
        o->OrbitRadius = from_bits(v);
    else if (!strcmp(f, "rsp"))
        o->RadiusSpeed = from_bits(v);
    else {
        fprintf(stderr, "bad field %s\n", f);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[4096];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: selcam_test SCRIPT\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (!fp) {
        perror(argv[1]);
        return 2;
    }
    gSelCamSound = &kSound;
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
        } else if (!strcmp(t, "V")) {
            int i = itok(), k = itok();

            eViews[i].pCamera = &cams[k];
        } else if (!strcmp(t, "Z")) {
            CameraStopUpdating = itok();
        } else if (!strcmp(t, "T")) {
            RealTimeElapsed = ftok();
        } else if (!strcmp(t, "E")) {
            SoundEnabled = itok();
        } else if (!strcmp(t, "N")) {
            SelCamNormalizeCount = (int32_t)xtok();
        } else if (!strcmp(t, "O")) {
            int j = itok(), view = itok();

            memset(&movs[j], 0xa5, sizeof movs[j]);
            selcam_init(&movs[j], view);
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
        } else if (!strcmp(t, "M")) {
            int j = itok();

            selcam_set_mode(&movs[j], itok());
            pmov(j);
        } else if (!strcmp(t, "R")) {
            int j = itok();

            selcam_set_radius_stats(&movs[j], ftok());
            pmov(j);
        } else if (!strcmp(t, "A") || !strcmp(t, "a")) {
            int j = itok();
            bVector3 v;

            read_vec(&v);
            if (*t == 'A')
                selcam_set_offset_stats(&movs[j], &v);
            else
                selcam_set_offset_orbit(&movs[j], &v);
            pmov(j);
        } else if (!strcmp(t, "W") || !strcmp(t, "w")) {
            int j = itok();
            uint16_t fov = (uint16_t)xtok();

            if (*t == 'W')
                selcam_set_fov_stats(&movs[j], fov);
            else
                selcam_set_fov_orbit(&movs[j], fov);
            pmov(j);
        } else if (!strcmp(t, "S")) {
            int j = itok();
            uint16_t angle = (uint16_t)xtok();

            selcam_set_orientation_stats(&movs[j], angle, (uint16_t)xtok());
            pmov(j);
        } else if (!strcmp(t, "s")) {
            int j = itok();

            selcam_set_vert_angle_orbit(&movs[j], (uint16_t)xtok());
            pmov(j);
        } else if (!strcmp(t, "P")) {
            int j = itok();
            const char *which = tok();
            float v = ftok();

            if (!strcmp(which, "r"))
                selcam_set_desired_radius_speed(&movs[j], v);
            else if (!strcmp(which, "v"))
                selcam_set_desired_vert_orbit_speed(&movs[j], v);
            else
                selcam_set_desired_horiz_orbit_speed(&movs[j], v);
            pmov(j);
        } else if (!strcmp(t, "G")) {
            query(itok());
        } else if (!strcmp(t, "F")) {
            int j = itok();
            const char *f = tok();

            set_field(j, f, xtok());
        } else if (!strcmp(t, "L")) {
            bQuaternion a, b, o;
            float tt;

            read_quat(&a);
            read_quat(&b);
            tt = ftok();
            memset(&o, 0xa5, sizeof o);
            selcam_slerp(&o, &a, &b, tt);
            printf("  slerp");
            pquat("o", &o);
            pquat("a", &a);
            pquat("b", &b);
            printf("\n");
        } else if (!strcmp(t, "X")) {
            bQuaternion a, b, o;

            read_quat(&a);
            read_quat(&b);
            memset(&o, 0xa5, sizeof o);
            selcam_quat_multiply(&o, &a, &b);
            printf("  mul");
            pquat("o", &o);
            selcam_quat_multiply(&b, &a, &b);
            pquat("b", &b);
            printf("\n");
        } else if (!strcmp(t, "Y")) {
            bQuaternion q;

            read_quat(&q);
            selcam_quat_normalize(&q);
            printf("  norm");
            pquat("q", &q);
            printf("\n");
        } else {
            fprintf(stderr, "bad op %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
