// Harness for tools/sound3d_check.py: runs the checker's script on
// sound3d.c and prints what the model prints for the retail image. bSample,
// the slot pool, the views and GetInGameSample are logging fakes, the same
// fakes the checker gives retail's code. See the checker's docstring.
//
//     sound3d_test script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bslotpool.h"
#include "bsound.h"
#include "camera.h"
#include "eview.h"
#include "player.h"
#include "realtime.h"
#include "sound.h"
#include "sound3d.h"
#include "vtable.h"

int32_t        SoundEnabled = 1;
int32_t        PlayerNumPlayers;
struct Player *PlayerPlayersByIndex[2];
int32_t        PlayerNetLocal = -1;
float          WorldTimeElapsed;

static uint32_t bits(float f)
{
    uint32_t v;
    memcpy(&v, &f, 4);
    return v;
}

static float unbits(uint32_t v)
{
    float f;
    memcpy(&f, &v, 4);
    return f;
}

// ------------------------------------------------------------- the objects

#define MAXOBJ 64

static Sound3d       *objs[MAXOBJ];
static int            nobjs;
static Sound3dSample *samples[MAXOBJ];
static int            nsamples;
static BSample        srcs[4];
static eView          views[3];
static Camera         cams[3];
static int            players[2];
static int            fakepool;
static SoundModule    fakemod;

static void *pattern(size_t n)
{
    void *p = malloc(n);

    memset(p, 0xa5, n);
    return p;
}

static const char *sname(const void *p)
{
    static char buf[8][24];
    static int k;
    char *b = buf[k++ & 7];
    int i;

    if (p == NULL)
        return "0";
    if (p == &Sound3dOneshotList)
        return "L";
    for (i = 0; i < nobjs; i++) {
        if (p == objs[i]) {
            sprintf(b, "o%d", i);
            return b;
        }
    }
    for (i = 0; i < nsamples; i++) {
        if (p == samples[i]) {
            sprintf(b, "s%d", i);
            return b;
        }
        if (p == &samples[i]->Sound) {
            sprintf(b, "s%d.3d", i);
            return b;
        }
        if (p == &samples[i]->Sample) {
            sprintf(b, "s%d.b", i);
            return b;
        }
    }
    for (i = 0; i < 4; i++) {
        if (p == &srcs[i]) {
            sprintf(b, "src%d", i);
            return b;
        }
    }
    return "?";
}

static const char *cname(const Camera *c)
{
    if (c == NULL)
        return "0";
    if (c == &cams[1])
        return "c1";
    if (c == &cams[2])
        return "c2";
    return "?";
}

static const char *pname(const BSlotPool *p)
{
    if (p == NULL)
        return "0";
    return p == (const BSlotPool *)&fakepool ? "pool" : "?";
}

#define PROBE_VT 0x00500000u

static const char *vtname(uint32_t v)
{
    if (v == SOUND3D_VTABLE)
        return "s3d";
    if (v == SOUND3DSAMPLE_VTABLE)
        return "sample";
    if (v == PROBE_VT)
        return "probe";
    return "?";
}

static const char *cbname(BSoundCallback cb)
{
    if (cb == NULL)
        return "0";
    return cb == sound3d_remove_sample ? "remove" : "?";
}

// ------------------------------------------------------------- bSample

void bsample_construct(BSample *s, int8_t type)
{
    printf("  bctor %s %d\n", sname(s), type);
    s->voice = NULL;
    s->callback = NULL;
    s->paused = 0;
}

void bsample_destruct(BSample *s)
{
    printf("  bdtor %s\n", sname(s));
}

void bsample_initialize_copy(BSample *s, const BSample *other)
{
    printf("  binit %s from %s\n", sname(s), sname(other));
}

bool bsample_is_playing(const BSample *s)
{
    int v = s->voice != NULL;

    printf("  bisplaying %s %d\n", sname(s), v);
    return v;
}

BVoice *bsample_play(BSample *s, float volume, float pan, float pitch)
{
    printf("  bplay %s %08x %08x %08x\n", sname(s), bits(volume), bits(pan),
           bits(pitch));
    s->voice = (BVoice *)(uintptr_t)1;
    return s->voice;
}

// As bSample::Stop: with a voice, the voice dropped and the callback told,
// and the pause cleared after it.
void bsample_stop(BSample *s)
{
    printf("  bstop %s\n", sname(s));
    if (s->voice == NULL)
        return;
    s->voice = NULL;
    if (s->callback != NULL)
        s->callback(BSOUND_SAMPLE_STOPPED, s, s->callbackData);
    s->paused = 0;
}

void bsample_pause(BSample *s, bool pause)
{
    printf("  bpause %s %d\n", sname(s), pause);
    if (s->voice != NULL)
        s->paused = pause;
}

void bsample_set_azimuth(BSample *s, uint16_t azimuth)
{
    printf("  baz %s %d\n", sname(s), azimuth);
}

void bsample_set_volume(BSample *s, float volume)
{
    printf("  bvol %s %08x\n", sname(s), bits(volume));
}

int32_t bsample_set_pitch(BSample *s, float pitch)
{
    printf("  bpitch %s %08x\n", sname(s), bits(pitch));
    return 0;
}

// ------------------------------------------------------------- the pool

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *name,
                        int memoryPool)
{
    printf("  newpool %d %s %d size-ok=%d\n", numSlots, name, memoryPool,
           slotSize == (int)sizeof(Sound3dSample));
    return (BSlotPool *)&fakepool;
}

void bDeleteSlotPool(BSlotPool *pool)
{
    printf("  delpool %s\n", pname(pool));
}

void *bSlotOMalloc(BSlotPool *pool)
{
    Sound3dSample *s = pattern(sizeof *s);

    samples[nsamples] = s;
    printf("  omalloc %s -> s%d\n", pname(pool), nsamples);
    nsamples++;
    return s;
}

// Given back and kept: the model's slots are never used again either.
void bSlotFree(BSlotPool *pool, void *slot)
{
    printf("  slotfree %s %s\n", pname(pool), sname(slot));
}

void bFree(void *p)
{
    printf("  delete %s\n", sname(p));
}

// ------------------------------------------------------------- the game

eView *eGetView(int32_t id)
{
    printf("  view %d\n", id);
    return &views[id];
}

BSample *sound_get_in_game_sample(SoundModule *m, const char *name)
{
    (void)m;
    printf("  getsample %s\n", name);
    if (!strcmp(name, "glass"))
        return &srcs[0];
    if (!strcmp(name, "bush"))
        return &srcs[1];
    if (!strcmp(name, "boom"))
        return &srcs[2];
    return NULL;
}

// ------------------------------------------------------------- the probe

// A derived class for a plain Sound3d: the pure slots print, and
// UpdateCamRelativeDistAndVelocity prints and runs Sound3d's.
static void probe_update(void *self, float volume, uint16_t azimuth,
                         float pitch)
{
    printf("  p-update %s %08x %d %08x\n", sname(self), bits(volume),
           azimuth, bits(pitch));
}

static void probe_mute(void *self, int32_t on)
{
    printf("  p-mute %s %d\n", sname(self), on);
}

static void probe_deactivate(void *self)
{
    printf("  p-deactivate %s\n", sname(self));
}

static void probe_activate_sound(void *self)
{
    printf("  p-activatesound %s\n", sname(self));
}

static void probe_camrel(void *self, const bVector3 *pos)
{
    printf("  p-camrel %s\n", sname(self));
    sound3d_update_cam_relative_dist_and_velocity(self, pos);
}

static const VtEntry probe_vt[8] = {
    { 0, 0, NULL },
    { 0, 0, NULL },
    { 0, 0, (VtFn)sound3d_activate },
    { 0, 0, (VtFn)probe_update },
    { 0, 0, (VtFn)probe_mute },
    { 0, 0, (VtFn)probe_deactivate },
    { 0, 0, (VtFn)probe_activate_sound },
    { 0, 0, (VtFn)probe_camrel },
};

// ------------------------------------------------------------- the dumps

static void dump3d(const Sound3d *s, const char *label)
{
    printf("  3d %s act=%d dop=%d vol=%08x pitch=%08x az=%d pad=%04x "
           "vel=%08x dist=%08x vt=%s\n", label, (int)s->Activated,
           (int)s->DopplerIsActive, bits(s->Volume), bits(s->Pitch),
           s->Azimuth, s->_pad18[0] | s->_pad18[1] << 8,
           bits(s->SndToCameraVelocity), bits(s->SndToCameraDistance),
           vtname(s->_vtable));
}

static void dump_sample(const Sound3dSample *s)
{
    char label[32];

    printf("  sample %s next=%s prev=%s env=%08x,%08x,%08x dwd=%08x "
           "pid=%08x pos=%08x,%08x,%08x,%08x voice=%d cb=%s data=%s "
           "paused=%d\n", sname(s), sname(s->Node.next), sname(s->Node.prev),
           bits(s->Envelope.MaxVolAtSource), bits(s->Envelope.CutOffDistance),
           bits(s->Envelope.Coeff), (uint32_t)s->DeleteWhenDone,
           (uint32_t)s->PositionIsDefined, bits(s->Position.x),
           bits(s->Position.y), bits(s->Position.z), bits(s->Position.pad),
           s->Sample.voice != NULL, cbname(s->Sample.callback),
           sname(s->Sample.callbackData), (int)s->Sample.paused);
    sprintf(label, "%s.3d", sname(s));
    dump3d(&s->Sound, label);
}

// The list both ways, stopping at anything that is not one of ours.
static void dump_list(void)
{
    const bNode *n;
    const char *nm;
    int k;

    printf("  list");
    for (n = Sound3dOneshotList.next, k = 0; n != &Sound3dOneshotList
         && k < 40; n = n->next, k++) {
        nm = sname(n);
        printf(" %s", nm);
        if (nm[0] != 's' || strchr(nm, '.'))
            break;
    }
    printf(" /");
    for (n = Sound3dOneshotList.prev, k = 0; n != &Sound3dOneshotList
         && k < 40; n = n->prev, k++) {
        nm = sname(n);
        printf(" %s", nm);
        if (nm[0] != 's' || strchr(nm, '.'))
            break;
    }
    printf("\n");
}

static const char *fname(VtFn fn)
{
    if (fn == NULL)
        return "pure";
    if (fn == (VtFn)sound3d_destroy)
        return "destroy";
    if (fn == (VtFn)sound3d_activate)
        return "activate";
    if (fn == (VtFn)sound3d_update_cam_relative_dist_and_velocity)
        return "camrel";
    if (fn == (VtFn)sound3d_sample_destroy)
        return "sdestroy";
    if (fn == (VtFn)sound3d_sample_update)
        return "supdate";
    if (fn == (VtFn)sound3d_sample_mute)
        return "smute";
    if (fn == (VtFn)sound3d_sample_deactivate_sound)
        return "sdeactivate";
    if (fn == (VtFn)sound3d_sample_activate_sound)
        return "sactivate";
    if (fn == (VtFn)sound3d_sample_update_at)
        return "supdateat";
    return "?";
}

static void dump_table(const char *label, uint32_t image)
{
    const VtEntry *t;
    int n, k;

    t = vt_table(image, &n);
    for (k = 1; k < n; k++) {
        char d[16];

        if (t[k].delta == 0)
            strcpy(d, "0");
        else if (t[k].delta == -(int)offsetof(Sound3dSample, Sound))
            strcpy(d, "sub");
        else
            sprintf(d, "%d", t[k].delta);
        printf("  vt %s %d %s %s\n", label, 8 * k, d, fname(t[k].fn));
    }
}

// ------------------------------------------------------------- the script

static char *arg[16];
static int   nargs;

static int32_t I(int k)
{
    return k < nargs ? (int32_t)strtol(arg[k], NULL, 0) : 0;
}

static float F(int k)
{
    return k < nargs ? unbits((uint32_t)strtoul(arg[k], NULL, 16)) : 0.0f;
}

static bVector3 V(int k)
{
    bVector3 v;

    v.x = F(k);
    v.y = F(k + 1);
    v.z = F(k + 2);
    v.pad = F(k + 3);
    return v;
}

static Sound3d *T(int k)
{
    const char *a = arg[k];

    if (a[0] == 'o')
        return objs[atoi(a + 1)];
    if (a[0] == 's')
        return &samples[atoi(a + 1)]->Sound;
    return NULL;
}

static Sound3dSample *S(int k)
{
    const char *a = arg[k];

    return a[0] == 's' ? samples[atoi(a + 1)] : NULL;
}

static BSample *SRC(int k)
{
    const char *a = arg[k];

    return !strncmp(a, "src", 3) ? &srcs[atoi(a + 3)] : NULL;
}

typedef void (*IntFn)(void *self, int32_t v);
typedef void (*VoidFn)(void *self);
typedef void (*UpdFn)(void *self, float volume, uint16_t azimuth,
                      float pitch);
typedef void (*PosFn)(void *self, const bVector3 *pos);
typedef void (*UpdAtFn)(void *self, const bVector3 *pos, float volume,
                        uint16_t azimuth, float pitch);

static void vcall(void)
{
    int slot = I(2);
    Sound3d *t = T(1);
    void *base = slot == 64 ? (void *)S(1) : (void *)t;
    const VtEntry *e = vt_slot(t->_vtable, slot);
    void *self = vt_this(base, e);
    bVector3 p;

    switch (slot) {
    case 8:
    case 16:
    case 32:
        ((IntFn)e->fn)(self, I(3));
        break;
    case 24:
        ((UpdFn)e->fn)(self, F(3), (uint16_t)I(4), F(5));
        break;
    case 40:
    case 48:
        ((VoidFn)e->fn)(self);
        break;
    case 56:
        p = V(3);
        ((PosFn)e->fn)(self, &p);
        break;
    case 64:
        p = V(3);
        ((UpdAtFn)e->fn)(self, &p, F(7), (uint16_t)I(8), F(9));
        break;
    default:
        printf("  bad slot %d\n", slot);
    }
}

static void run(void)
{
    const char *o = arg[0];
    bVector3 p;

    if (!strcmp(o, "se")) {
        SoundEnabled = I(1);
    } else if (!strcmp(o, "np")) {
        PlayerNumPlayers = I(1);
    } else if (!strcmp(o, "pl")) {
        PlayerPlayersByIndex[I(1)] =
            I(2) ? (struct Player *)&players[I(1)] : NULL;
    } else if (!strcmp(o, "dt")) {
        WorldTimeElapsed = F(1);
    } else if (!strcmp(o, "mpaz")) {
        CarSoundMultiPlayerAzimuth = (uint16_t)I(1);
    } else if (!strcmp(o, "cam")) {
        Camera *c = &cams[I(1)];

        c->CurrentKey.Position.x = F(2);
        c->CurrentKey.Position.y = F(3);
        c->CurrentKey.Position.z = F(4);
        c->CurrentKey.Direction.x = F(5);
        c->CurrentKey.Direction.y = F(6);
        c->CurrentKey.Direction.z = F(7);
    } else if (!strcmp(o, "cams")) {
        struct Camera **c = get_active_cameras();

        printf("  cams %s %s\n", cname(c[0]), cname(c[1]));
    } else if (!strcmp(o, "new")) {
        objs[nobjs] = pattern(sizeof(Sound3d));
        printf("  o%d\n", nobjs);
        nobjs++;
    } else if (!strcmp(o, "ctor")) {
        sound3d_construct(T(1));
    } else if (!strcmp(o, "dtor")) {
        const VtEntry *e = vt_slot(SOUND3D_VTABLE, SOUND3D_VT_DESTROY);

        ((IntFn)e->fn)(vt_this(T(1), e), I(2));
    } else if (!strcmp(o, "probe")) {
        T(1)->_vtable = PROBE_VT;
    } else if (!strcmp(o, "dop")) {
        T(1)->DopplerIsActive = I(2);
    } else if (!strcmp(o, "act")) {
        sound3d_activate(T(1), I(2));
    } else if (!strcmp(o, "dist")) {
        p = V(1);
        printf("  = %08x\n", bits(sound3d_get_dist_to_closest_camera(&p)));
    } else if (!strcmp(o, "camrel")) {
        p = V(2);
        sound3d_update_cam_relative_dist_and_velocity(T(1), &p);
    } else if (!strcmp(o, "upd")) {
        Sound3dEnvelope env;

        p = V(2);
        if (!strcmp(arg[6], "~")) {
            sound3d_update(T(1), &p, NULL);
        } else {
            env.MaxVolAtSource = F(6);
            env.CutOffDistance = F(7);
            env.Coeff = F(8);
            sound3d_update(T(1), &p, &env);
        }
    } else if (!strcmp(o, "az")) {
        p = V(1);
        printf("  = %d\n", sound3d_compute_azimuth(&p));
    } else if (!strcmp(o, "cvol")) {
        p = V(1);
        printf("  = %08x\n", bits(sound3d_compute_volume(&p, F(5))));
    } else if (!strcmp(o, "a2p")) {
        printf("  = %08x\n", bits(sound3d_azimuth_to_pan((uint16_t)I(1))));
    } else if (!strcmp(o, "p2a")) {
        printf("  = %d\n", sound3d_pan_to_azimuth(F(1)));
    } else if (!strcmp(o, "getaz")) {
        printf("  = %08x\n", bits(sound3d_get_azimuth(T(1))));
    } else if (!strcmp(o, "d")) {
        dump3d(T(1), arg[1]);
    } else if (!strcmp(o, "snew")) {
        printf("  -> %s\n", sname(sound3d_sample_new()));
    } else if (!strcmp(o, "sctor")) {
        sound3d_sample_construct(S(1));
    } else if (!strcmp(o, "sctorat")) {
        p = V(2);
        sound3d_sample_construct_at(S(1), &p, F(6));
    } else if (!strcmp(o, "vc")) {
        vcall();
    } else if (!strcmp(o, "sdwd")) {
        sound3d_sample_set_delete_when_done(S(1), I(2));
    } else if (!strcmp(o, "sas")) {
        sound3d_sample_activate_sound(S(1));
    } else if (!strcmp(o, "sds")) {
        sound3d_sample_deactivate_sound(S(1));
    } else if (!strcmp(o, "spos")) {
        p = V(2);
        sound3d_sample_set_position(S(1), &p);
    } else if (!strcmp(o, "saz")) {
        sound3d_sample_set_azimuth(S(1), (uint16_t)I(2));
    } else if (!strcmp(o, "svol")) {
        sound3d_sample_set_volume(S(1), F(2));
    } else if (!strcmp(o, "spitch")) {
        sound3d_sample_set_pitch(S(1), F(2));
    } else if (!strcmp(o, "smute")) {
        sound3d_sample_mute(S(1), I(2));
    } else if (!strcmp(o, "sfree")) {
        sound3d_sample_free(S(1));
    } else if (!strcmp(o, "supd")) {
        sound3d_sample_update(S(1), F(2), (uint16_t)I(3), F(4));
    } else if (!strcmp(o, "supdat")) {
        p = V(2);
        sound3d_sample_update_at(S(1), &p, F(6), (uint16_t)I(7), F(8));
    } else if (!strcmp(o, "voice")) {
        S(1)->Sample.voice = I(2) ? (BVoice *)(uintptr_t)1 : NULL;
    } else if (!strcmp(o, "pause")) {
        S(1)->Sample.paused = I(2);
    } else if (!strcmp(o, "end")) {
        bsample_stop(&S(1)->Sample);
    } else if (!strcmp(o, "remove")) {
        Sound3dSample *s = S(2);

        sound3d_remove_sample((uint32_t)I(1), s ? &s->Sample : NULL, s);
    } else if (!strcmp(o, "sd")) {
        dump_sample(S(1));
    } else if (!strcmp(o, "list")) {
        dump_list();
    } else if (!strcmp(o, "oinit")) {
        sound3d_oneshot_init();
    } else if (!strcmp(o, "oreset")) {
        sound3d_oneshot_reset();
    } else if (!strcmp(o, "oclose")) {
        sound3d_oneshot_close();
    } else if (!strcmp(o, "oupd")) {
        sound3d_oneshot_update();
    } else if (!strcmp(o, "omute")) {
        sound3d_oneshot_mute(I(1));
    } else if (!strcmp(o, "oplay")) {
        p = V(2);
        printf("  -> %s\n",
               sname(sound3d_oneshot_play(SRC(1), &p, F(6), F(7))));
    } else if (!strcmp(o, "oplayn")) {
        p = V(2);
        printf("  -> %s\n", sname(sound3d_oneshot_play_named(
                                &fakemod, arg[1], &p, F(6), F(7))));
    } else if (!strcmp(o, "pool")) {
        printf("  pool %s\n", pname(Sound3dSampleSlotPool));
    } else if (!strcmp(o, "tables")) {
        dump_table("s3d", SOUND3D_VTABLE);
        dump_table("sample", SOUND3DSAMPLE_VTABLE);
    } else {
        printf("  unknown op %s\n", o);
    }
}

int main(int argc, char **argv)
{
    static char line[512];
    FILE *sc;
    int i;

    if (argc < 2) {
        fprintf(stderr, "usage: sound3d_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (!sc)
        return 2;
    for (i = 1; i < 3; i++)
        views[i].pCamera = &cams[i];
    sound3d_install_vtables();
    vt_install(PROBE_VT, probe_vt, 8);
    while (fgets(line, sizeof line, sc)) {
        char *t;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        printf("> %s\n", line);
        nargs = 0;
        for (t = strtok(line, "|"); t && nargs < 16; t = strtok(NULL, "|"))
            arg[nargs++] = t;
        run();
        fflush(stdout);
    }
    fclose(sc);
    return 0;
}
