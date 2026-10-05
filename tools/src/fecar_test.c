// Host harness for 3DS Files/source/fecar.c, the frontend's cars, and the
// frontend half of elight.c: SetSelectCarLighting and elSetupLightContext's
// frontend lights. Runs the op script tools/fecar_check.py writes and
// prints the transcript it diffs against the retail image, run in mipsemu
// over the same script.
//
// The harness owns what fecar.c calls outside itself, and prints each
// call: CarRenderInfo's constructor, deleting destructor and Render,
// eModel::Render, eModel::GetBoundingBox (which answers the script's box),
// the eModel's deleting destructor, eWaitUntilRenderingDone, bMalloc and
// bFree. ForceCarLOD and ForceTireLOD are its own, and Render can change
// them as the script says.
//
// Every car is filled with 0xa5 before it is built, so a field the port
// leaves alone and retail writes (or the other way round) shows. A float
// prints as its bits, every NaN as "nan", and a pointer by what it points
// at.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "carrenderinfo.h"
#include "elight.h"
#include "emodel.h"
#include "eview.h"
#include "fecar.h"
#include "scenerycull.h"

#define NF 4        // cars
#define NC 64       // CarRenderInfos a scenario may build
#define NM 3        // eModels
#define NV 3        // views, IDs 0 .. 2

// What fecar.c and elight.c link against, the harness's own.
int32_t ForceCarLOD = -1;
int32_t ForceTireLOD = -1;
void (*gEModelRenderFn)(eModel *m, bMatrix4 *matrix, void *light,
                        uint32_t flags);
void (*gEWaitUntilRenderingDoneFn)(void);

static int32_t s_view_mode;

int32_t eGetCurrentViewMode(void)
{
    return s_view_mode;
}

static FrontEndRenderingCar fers[NF];
static eModel models[NM];
static eView views[NV];
static bMatrix4 vmats[NV];

static uint8_t pool[NC][sizeof(CarRenderInfo)] __attribute__((aligned(16)));
static int npool;
static CarRenderInfo *cris[NC];
static int ncri;

static bVector3 box_min, box_max;
static int lod_set[2];
static int32_t lod_to[2];
static int fe_on, cs_on;

// The light pack the script can put in the database, the same as
// fecar_check.py's PACK_LIGHTS and PACK_NODES: a root over two leaves
// that overlap at x = 0, and six lights.
static const struct {
    int      type, att;
    uint32_t colour;
    float    x, y, z, size, far_start, intensity;
} kLights[6] = {
    { 0, 0, 0x00305070u, -60.0f, 10.0f, -20.0f, 150.0f, 60.0f, 0.4375f },
    { 2, 0, 0x00c08040u, -10.0f, 20.0f, 5.0f, 120.0f, 40.0f, 0.75f },
    { 0, 2, 0x00204060u, 60.0f, -10.0f, 10.0f, 130.0f, 30.0f, 0.625f },
    { 2, 1, 0x0010e0a0u, 40.0f, -40.0f, 30.0f, 140.0f, 140.0f, 1.25f },
    { 0, 2, 0x00ff00ffu, -70.0f, -30.0f, 40.0f, 100.0f, 0.0f, 1.75f },
    { 1, 0, 0x00ffffffu, 0.0f, 0.0f, 0.0f, 500.0f, 0.0f, 1.0f },
};
static const struct {
    float   x, extent;
    int16_t num_children;
    int16_t children[4];
} kNodes[3] = {
    { 0.0f, 101.0f, 2, { 1, 2 } },
    { -50.0f, 51.0f, -3, { 0, 1, 4 } },
    { 50.0f, 51.0f, -4, { 1, 2, 3, 5 } },
};
static eLight pack_lights[6];
static vAABB pack_nodes[3];
static vAABBTree pack_tree;
static eLightPack pack;

static void build_pack(void)
{
    int i, j;

    memset(pack_lights, 0, sizeof pack_lights);
    for (i = 0; i < 6; i++) {
        eLight *l = &pack_lights[i];

        l->Type = (uint8_t)kLights[i].type;
        l->AttenuationType = (uint8_t)kLights[i].att;
        l->Colour = kLights[i].colour;
        l->PositionX = kLights[i].x;
        l->PositionY = kLights[i].y;
        l->PositionZ = kLights[i].z;
        l->Size = kLights[i].size;
        l->FarStart = kLights[i].far_start;
        l->Intensity = kLights[i].intensity;
    }
    memset(pack_nodes, 0, sizeof pack_nodes);
    for (i = 0; i < 3; i++) {
        vAABB *n = &pack_nodes[i];
        int count = kNodes[i].num_children;

        n->PositionX = kNodes[i].x;
        n->ExtentX = kNodes[i].extent;
        n->ExtentY = n->ExtentZ = 101.0f;
        n->ParentIndex = (int16_t)(i ? 0 : -1);
        n->NumChildren = (int16_t)count;
        for (j = 0; j < (count < 0 ? -count : count); j++)
            n->ChildrenIndicies[j] = kNodes[i].children[j];
    }
    memset(&pack_tree, 0, sizeof pack_tree);
    pack_tree.NodeArray = pack_nodes;
    pack_tree.NumLeafNodes = 2;
    pack_tree.NumParentNodes = 1;
    pack_tree.TotalNodes = 3;
    pack_tree.Depth = 2;
    memset(&pack, 0, sizeof pack);
    pack.Version = 1;
    pack.LightTree = &pack_tree;
    pack.NumTreeNodes = 3;
    pack.LightArray = pack_lights;
    pack.NumLights = 6;
}

static void link_pack(int on)
{
    if (on) {
        eLightPackList.next = eLightPackList.prev = &pack.Node;
        pack.Node.next = pack.Node.prev = &eLightPackList;
    } else {
        eLightPackList.next = eLightPackList.prev = &eLightPackList;
    }
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

static const char *nm(const void *p)
{
    static char buf[16][32];
    static int slot;
    char *b = buf[slot++ & 15];
    int i;

    if (p == 0)
        return "null";
    if (p == &FrontEndRenderingCarList)
        return "head";
    for (i = 0; i < NF; i++) {
        if (p == &fers[i]) {
            sprintf(b, "f%d", i);
            return b;
        }
        if (p == &fers[i].Ride) {
            sprintf(b, "f%d.ride", i);
            return b;
        }
        if (p == &fers[i].BodyMatrix) {
            sprintf(b, "f%d.body", i);
            return b;
        }
    }
    for (i = 0; i < ncri; i++) {
        if (p == cris[i]) {
            sprintf(b, "c%d", i);
            return b;
        }
        if (p == &cris[i]->Body[0]) {
            sprintf(b, "c%d.body", i);
            return b;
        }
    }
    for (i = 0; i < NM; i++) {
        if (p == &models[i]) {
            sprintf(b, "m%d", i);
            return b;
        }
    }
    for (i = 0; i < NV; i++) {
        if (p == &views[i]) {
            sprintf(b, "v%d", i);
            return b;
        }
    }
    return "?";
}

static void pmat(const char *tag, const bMatrix4 *m)
{
    const float *f = &m->v0.x;
    int i;

    printf("    %s", tag);
    for (i = 0; i < 16; i++)
        printf(" %s", fx(f[i]));
    printf("\n");
}

// ---------------------------------------------------------- the stubs

static void *h_malloc(int size, const char *name, int flags, int p)
{
    (void)size;
    (void)name;
    (void)flags;
    printf("  alloc pool %d\n", p);
    if (npool >= NC) {
        fprintf(stderr, "out of CarRenderInfos\n");
        exit(2);
    }
    return pool[npool++];
}

static void h_free(void *p)
{
    printf("  free %s\n", nm(p));
}

CarRenderInfo *carrenderinfo_construct(CarRenderInfo *ri, RideInfo *ride,
                                       Car *car)
{
    const uint8_t *r = (const uint8_t *)ride;

    cris[ncri++] = ri;
    printf("  cri new %s ride %s %08lx %02x%02x%02x%02x car %s\n", nm(ri),
           nm(ride), (unsigned long)(uint32_t)ride->Type, r[4], r[5], r[6],
           r[7], nm(car));
    return ri;
}

void carrenderinfo_delete(CarRenderInfo *ri, int32_t flags)
{
    printf("  cri del %s %d\n", nm(ri), (int)flags);
}

void carrenderinfo_render(CarRenderInfo *ri, eView *view,
                          const bVector3 *position,
                          const bMatrix4 *body_matrix,
                          bMatrix4 *tire_matrices, bMatrix4 *brake_matrices,
                          uint32_t extra_render_flags,
                          uint32_t forced_lights)
{
    int i;

    printf("  render %s view %s pos %s %s %s %s body %s flags %lu forced"
           " %lu lod %d %d\n", nm(ri), nm(view), fx(position->x),
           fx(position->y), fx(position->z), fx(position->pad),
           nm(body_matrix), (unsigned long)extra_render_flags,
           (unsigned long)forced_lights, (int)ForceCarLOD,
           (int)ForceTireLOD);
    for (i = 0; i < 4; i++) {
        char tag[8];

        sprintf(tag, "t%d", i);
        pmat(tag, &tire_matrices[i]);
        sprintf(tag, "k%d", i);
        pmat(tag, &brake_matrices[i]);
    }
    if (lod_set[0])
        ForceCarLOD = lod_to[0];
    if (lod_set[1])
        ForceTireLOD = lod_to[1];
}

static void h_model_render(eModel *m, bMatrix4 *matrix, void *light,
                           uint32_t flags)
{
    printf("  model render %s mat %s light %s flags %lu\n", nm(m),
           nm(matrix), nm(light), (unsigned long)flags);
}

void emodel_delete(eModel *m, int32_t flags)
{
    printf("  model del %s %d\n", nm(m), (int)flags);
}

void emodel_get_bounding_box(const eModel *m, bVector3 *mn, bVector3 *mx)
{
    printf("  bbox %s\n", nm(m));
    mn->x = box_min.x;
    mn->y = box_min.y;
    mn->z = box_min.z;
    mx->x = box_max.x;
    mx->y = box_max.y;
    mx->z = box_max.z;
}

static void h_wait(void)
{
    printf("  wait\n");
}

// ---------------------------------------------------------- the dumps

static void pfer(int k)
{
    const FrontEndRenderingCar *f = &fers[k];
    const uint8_t *r = (const uint8_t *)&f->Ride;
    int i;

    printf("  f%d next %s prev %s ri %s ride %08lx %02x%02x%02x%02x"
           " view %ld\n", k, nm(f->Node.next), nm(f->Node.prev),
           nm(f->pRenderInfo), (unsigned long)(uint32_t)f->Ride.Type, r[4],
           r[5], r[6], r[7], (long)f->ViewID);
    printf("    pos %s %s %s %s model %s en %ld u %ld rf %ld hd %ld cp %ld\n",
           fx(f->Position.x), fx(f->Position.y), fx(f->Position.z),
           fx(f->Position.pad), nm(f->pModel), (long)f->Enabled,
           (long)f->Unused632, (long)f->Reflection, (long)f->Headlights,
           (long)f->CopLights);
    pmat("body", &f->BodyMatrix);
    for (i = 0; i < 4; i++) {
        char tag[8];

        sprintf(tag, "t%d", i);
        pmat(tag, &f->TireMatrices[i]);
        sprintf(tag, "k%d", i);
        pmat(tag, &f->BrakeMatrices[i]);
    }
}

static void plist(void)
{
    const bNode *n;
    int guard = 0;

    printf("  list");
    for (n = FrontEndRenderingCarList.next; n != &FrontEndRenderingCarList
         && guard < 16; n = n->next, guard++)
        printf(" %s", nm(n));
    printf(" /");
    guard = 0;
    for (n = FrontEndRenderingCarList.prev; n != &FrontEndRenderingCarList
         && guard < 16; n = n->prev, guard++)
        printf(" %s", nm(n));
    printf("\n");
}

static void pvec(const char *tag, const bVector4 *v, int w)
{
    printf("    %s %s %s %s %s\n", tag, fx(v->x), fx(v->y), fx(v->z),
           w ? fx(v->w) : "-");
}

static void plights(void)
{
    int s, i;

    for (s = 0; s < 2; s++) {
        const eSelectCarLights *l = &elSelectCarLights[s];

        printf("  lights %d\n", s);
        for (i = 0; i < 3; i++) {
            char tag[8];

            sprintf(tag, "c%d", i);
            pvec(tag, &l->Light[i].Colour, 0);
            sprintf(tag, "d%d", i);
            pvec(tag, &l->Light[i].Direction, 1);
        }
        pvec("amb", &l->Ambient, 0);
    }
}

// The light context, word by word. With the world's lights retail leaves
// the second direction on its stack when no point light is near, and the
// third when fewer than two are, so the words those reach print as "-":
// the direction matrix's y or z column and the light's position. How many
// are near is query_light_database's, asked first with the same position.
static void plc(const eLightContext *lc, int world, int near)
{
    const float *f = (const float *)lc;
    int row, i;

    for (row = 0; row < 18; row++) {
        printf("    lc%02d", row);
        for (i = 0; i < 4; i++) {
            int w = row * 4 + i;
            int masked = world
                && ((w >= 16 && w < 28
                     && ((i == 1 && near < 1) || (i == 2 && near < 2)))
                    || (w >= 36 && w < 40 && near < 1)
                    || (w >= 40 && w < 44 && near < 2));

            printf(" %s", masked ? "-" : fx(f[w]));
        }
        printf("\n");
    }
}

// ---------------------------------------------------------- the ops

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

static void read_mat(bMatrix4 *m)
{
    float *f = &m->v0.x;
    int i;

    for (i = 0; i < 16; i++)
        f[i] = ftok();
}

// "-", or the type and four bytes.
static RideInfo *read_ride(RideInfo *r)
{
    char *t = tok();
    uint8_t *b = (uint8_t *)r;
    int i;

    if (!strcmp(t, "-"))
        return NULL;
    r->Type = (int32_t)strtoul(t, NULL, 16);
    for (i = 4; i < 8; i++)
        b[i] = (uint8_t)strtoul(tok(), NULL, 16);
    return r;
}

static int fe_fn(void) { return fe_on; }
static int cs_fn(void) { return cs_on; }

static void reset(void)
{
    int i;

    for (i = 0; i < NF; i++)
        memset(&fers[i], 0xa5, sizeof fers[i]);
    memset(models, 0xa5, sizeof models);
    memset(pool, 0xa5, sizeof pool);
    memset(elSelectCarLights, 0, sizeof elSelectCarLights);
    npool = 0;
    ncri = 0;
    FrontEndRenderingCarList.next = &FrontEndRenderingCarList;
    FrontEndRenderingCarList.prev = &FrontEndRenderingCarList;
    ForceCarLOD = -1;
    ForceTireLOD = -1;
    FrontEndCarForceFlag8 = 0;
    FrontEndCarForceFlag16 = 0;
    s_view_mode = 1;
    lod_set[0] = lod_set[1] = 0;
    memset(&box_min, 0, sizeof box_min);
    memset(&box_max, 0, sizeof box_max);
    fe_on = cs_on = 0;
    build_pack();
    link_pack(0);
    for (i = 0; i < NV; i++) {
        memset(&views[i], 0, sizeof views[i]);
        views[i].ID = i;
        views[i].WorldViewMatrix = &vmats[i];
        memset(&vmats[i], 0, sizeof vmats[i]);
    }
}

static void op(char *t)
{
    if (!strcmp(t, "I")) {
        int k = itok(), v = itok();
        RideInfo r, *rp = read_ride(&r);

        fecar_init(&fers[k], rp, v);
        pfer(k);
    } else if (!strcmp(t, "R")) {
        int k = itok();
        RideInfo r, *rp = read_ride(&r);

        fecar_reinit(&fers[k], rp);
        pfer(k);
    } else if (!strcmp(t, "D")) {
        int k = itok(), flags = itok();

        fecar_delete(&fers[k], flags);
        plist();
    } else if (!strcmp(t, "S")) {
        int k = itok();
        FrontEndRenderingCar *f = &fers[k];
        char *w = tok();

        if (!strcmp(w, "en"))
            f->Enabled = itok();
        else if (!strcmp(w, "u"))
            f->Unused632 = itok();
        else if (!strcmp(w, "rf"))
            f->Reflection = itok();
        else if (!strcmp(w, "hd"))
            f->Headlights = itok();
        else if (!strcmp(w, "cp"))
            f->CopLights = itok();
        else if (!strcmp(w, "vw"))
            f->ViewID = itok();
        else if (!strcmp(w, "md")) {
            int j = itok();

            f->pModel = j < 0 ? NULL : &models[j];
        } else if (!strcmp(w, "p")) {
            f->Position.x = ftok();
            f->Position.y = ftok();
            f->Position.z = ftok();
        } else if (!strcmp(w, "b"))
            read_mat(&f->BodyMatrix);
        else if (!strcmp(w, "t"))
            read_mat(&f->TireMatrices[itok()]);
        else if (!strcmp(w, "k"))
            read_mat(&f->BrakeMatrices[itok()]);
        else {
            fprintf(stderr, "bad field %s\n", w);
            exit(2);
        }
    } else if (!strcmp(t, "Q")) {
        pfer(itok());
    } else if (!strcmp(t, "W")) {
        plist();
    } else if (!strcmp(t, "G")) {
        s_view_mode = itok();
    } else if (!strcmp(t, "F")) {
        FrontEndCarForceFlag8 = itok();
        FrontEndCarForceFlag16 = itok();
    } else if (!strcmp(t, "L")) {
        ForceCarLOD = itok();
        ForceTireLOD = itok();
    } else if (!strcmp(t, "K")) {
        int i;

        for (i = 0; i < 2; i++) {
            char *v = tok();

            lod_set[i] = strcmp(v, "-") != 0;
            lod_to[i] = lod_set[i] ? atoi(v) : 0;
        }
    } else if (!strcmp(t, "X")) {
        box_min.x = ftok();
        box_min.y = ftok();
        box_min.z = ftok();
        box_max.x = ftok();
        box_max.y = ftok();
        box_max.z = ftok();
    } else if (!strcmp(t, "P")) {
        int v = itok(), cars = itok(), refl = itok(), p8 = itok();
        int p16 = itok();

        render_front_end_cars(&views[v], cars, refl, p8, p16);
        printf("  lod %d %d\n", (int)ForceCarLOD, (int)ForceTireLOD);
    } else if (!strcmp(t, "C")) {
        int v = itok(), locked = itok();
        float bright = ftok();

        el_set_select_car_lighting(v, locked, bright);
        plights();
    } else if (!strcmp(t, "U")) {
        fe_on = itok();
        cs_on = itok();
    } else if (!strcmp(t, "M")) {
        read_mat(&vmats[itok()]);
    } else if (!strcmp(t, "Z")) {
        int v = itok();
        bMatrix4 lw, hack;
        bVector4 eye;
        eLightContext lc;
        eLightQuery q;
        int has_hack, has_eye, r, near;
        char *s;

        read_mat(&lw);
        s = tok();
        has_hack = strcmp(s, "-") != 0;
        if (has_hack) {
            float *f = &hack.v0.x;
            int i;

            f[0] = from_bits((uint32_t)strtoul(s, NULL, 16));
            for (i = 1; i < 16; i++)
                f[i] = ftok();
        }
        s = tok();
        has_eye = strcmp(s, "-") != 0;
        if (has_eye) {
            eye.x = from_bits((uint32_t)strtoul(s, NULL, 16));
            eye.y = ftok();
            eye.z = ftok();
            eye.w = ftok();
        }
        near = query_light_database(&q, (const bVector3 *)&lw.v3);
        memset(&lc, 0xa5, sizeof lc);
        r = el_setup_light_context(&lc, &lw, has_hack ? &hack : NULL,
                                   has_eye ? &eye : NULL, &views[v]);
        printf("  lc -> %d near %d\n", r, near);
        plc(&lc, !fe_on, near);
    } else if (!strcmp(t, "Y")) {
        link_pack(itok());
    } else {
        fprintf(stderr, "bad op %s\n", t);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[4096];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: fecar_test SCRIPT\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (!fp) {
        perror(argv[1]);
        return 2;
    }
    bSetMemoryHooks(h_malloc, h_free);
    gEModelRenderFn = h_model_render;
    gEWaitUntilRenderingDoneFn = h_wait;
    gElInFrontendFn = fe_fn;
    gElCarSelectActiveFn = cs_fn;
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
        op(t);
    }
    fclose(fp);
    return 0;
}
