// rendercars_test -- the host half of tools/rendercars_check.py: reads its
// scenarios, lays each world out, calls render_cars, and prints what every
// stand-in was asked, in the model's words.
//
// A scenario is a run of lines, "S" first and "G" to go; every value is
// hex, a float by its bits.

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "camera.h"
#include "car.h"
#include "carrenderinfo.h"
#include "cartypeinfo.h"
#include "emath.h"
#include "eview.h"
#include "player.h"
#include "realtime.h"
#include "world.h"

#define PATTERN 0xa5
#define MAXCARS 128
#define NCTI    4

// ------------------------------------------------ what RenderCars reads

World         *pCurrentWorld;
float          WorldTimeElapsed;
uint32_t       eFrameCounter;
struct Player *PlayerPlayersByIndex[2];

// ------------------------------------------------------------ the world

static World         g_world;
static eView         g_view;
static Camera        g_cam;
static struct Player g_players[2];
static CarTypeInfo   g_ctis[NCTI];
static Car           g_cars[MAXCARS];
static uint8_t       g_ris[MAXCARS][64];   // labels only
static int32_t       g_poof[MAXCARS], g_blink[MAXCARS];
static int           g_ncars;

// The callee that moves pCurrentWorld onto car g_swap_j at its
// g_swap_k-th call, and how often each of the four has been called.
static char g_swap_who;
static int  g_swap_k, g_swap_j;
static int  g_calls[4];

static uint32_t u(void)
{
    char *t = strtok(NULL, " \t\r\n");

    if (t == NULL) {
        fprintf(stderr, "rendercars_test: short line\n");
        exit(2);
    }
    return (uint32_t)strtoul(t, NULL, 16);
}

static float bits_f(uint32_t w)
{
    float f;

    memcpy(&f, &w, 4);
    return f;
}

// ------------------------------------------------------------ the labels

static const char *label(const void *p)
{
    static char buf[8][32];
    static int next;
    char *b;
    int i;

    if (p == NULL)
        return "null";
    if (p == (const void *)&g_world)
        return "world";
    if (p == (const void *)&g_view)
        return "view";
    if (p == (const void *)&g_cam.CurrentKey.Position)
        return "cam.eye";
    if (p == (const void *)&g_cam.CurrentKey.Direction)
        return "cam.dir";
    b = buf[next];
    next = (next + 1) & 7;
    for (i = 0; i < MAXCARS; i++) {
        const Car *c = &g_cars[i];
        const OverrideRenderingPosition *o = &c->TheOverrideRenderingPosition;

        if (p == (const void *)c)
            sprintf(b, "car%d", i);
        else if (p == (const void *)&c->State.GeometryPosition)
            sprintf(b, "car%d.pos", i);
        else if (p == (const void *)&c->State.BodyMatrix)
            sprintf(b, "car%d.body", i);
        else if (p == (const void *)&o->BodyMatrix)
            sprintf(b, "car%d.obody", i);
        else if (p == (const void *)&o->GeometryPosition)
            sprintf(b, "car%d.opos", i);
        else if (p == (const void *)g_ris[i])
            sprintf(b, "ri%d", i);
        else
            continue;
        return b;
    }
    return "-";
}

static void words(const void *p, int n)
{
    const uint8_t *b = p;
    int i;

    for (i = 0; i < n; i++) {
        uint32_t w;

        memcpy(&w, b + 4 * i, 4);
        printf(" %08x", (unsigned)w);
    }
}

// ----------------------------------------------------------- the stand-ins

static void after(char who)
{
    const char *whos = "pbrd";
    int k = (int)(strchr(whos, who) - whos);

    g_calls[k]++;
    if (g_swap_who == who && g_calls[k] == g_swap_k)
        pCurrentWorld = (World *)&g_cars[g_swap_j];
}

int32_t car_is_poofed(Car *c)
{
    int32_t v = g_poof[c - g_cars];

    printf("  poof %s -> %d\n", label(c), (int)v);
    after('p');
    return v;
}

int32_t car_is_blinking(Car *c)
{
    int32_t v = g_blink[c - g_cars];

    printf("  blink %s -> %d\n", label(c), (int)v);
    after('b');
    return v;
}

void carrenderinfo_render(CarRenderInfo *ri, eView *view,
                          const bVector3 *position,
                          const bMatrix4 *body_matrix,
                          bMatrix4 *tire_matrices, bMatrix4 *brake_matrices,
                          uint32_t extra_render_flags,
                          uint32_t forced_lights)
{
    printf("  render %s %s %s %s %d %d |", label(ri), label(view),
           label(position), label(body_matrix), (int)extra_render_flags,
           (int)forced_lights);
    words(tire_matrices, 64);
    printf(" |");
    words(brake_matrices, 64);
    printf("\n");
    after('r');
}

static void st_damage_above(Car *c, bVector3 *eye, bVector3 *direction)
{
    printf("  dmg %s %s %s\n", label(c), label(eye), label(direction));
    after('d');
}

// ------------------------------------------------------------ the lines

static void line_s(void)
{
    int32_t hidden;
    int i;

    g_view.ID = (int32_t)u();
    hidden = (int32_t)u();
    pCurrentWorld = u() ? &g_world : NULL;
    WorldTimeElapsed = bits_f(u());
    eFrameCounter = u();
    g_ncars = (int)u();

    memset(&g_world, PATTERN, sizeof g_world);
    memset(&g_cam, PATTERN, sizeof g_cam);
    memset(g_players, PATTERN, sizeof g_players);
    memset(g_ctis, PATTERN, sizeof g_ctis);
    memset(g_cars, PATTERN, sizeof(Car) * (g_ncars ? g_ncars : 1));

    g_view.pCamera = &g_cam;
    g_cam.CarNotToRender = hidden >= 0 ? (void *)&g_cars[hidden] : NULL;
    g_world.CarList.next = g_ncars ? (void *)&g_cars[0] : (void *)&g_world;
    g_world.CarList.prev =
        g_ncars ? (void *)&g_cars[g_ncars - 1] : (void *)&g_world;
    for (i = 0; i < g_ncars; i++) {
        g_cars[i].Link.next =
            i + 1 < g_ncars ? (void *)&g_cars[i + 1] : (void *)&g_world;
        g_cars[i].Link.prev = i ? (void *)&g_cars[i - 1] : (void *)&g_world;
    }
    PlayerPlayersByIndex[0] = PlayerPlayersByIndex[1] = NULL;
    g_swap_who = 0;
    memset(g_calls, 0, sizeof g_calls);
}

static void line_p(void)
{
    uint32_t k = u();
    uint32_t present = u();
    int32_t view_id = (int32_t)u();
    int32_t zone = (int32_t)u();

    if (!present)
        return;
    PlayerPlayersByIndex[k] = &g_players[k];
    g_players[k].ViewID = view_id;
    g_players[k].nZoneCurrent = zone;
}

static void line_k(void)
{
    uint32_t j = u();
    int w, q;

    for (w = 0; w < 4; w++)
        for (q = 0; q < 4; q++) {
            uint32_t v = u();

            memcpy((uint8_t *)&g_ctis[j].Wheels[w] + 4 * q, &v, 4);
        }
}

static void line_c(void)
{
    uint32_t i = u();
    Car *c = &g_cars[i];
    OverrideRenderingPosition *o = &c->TheOverrideRenderingPosition;
    int32_t ri;

    c->RenderingEnabled = (int8_t)u();
    g_poof[i] = (int32_t)u();
    g_blink[i] = (int32_t)u();
    o->OverrideViewBits = u();
    o->VisibleViewBits = u();
    o->BlinkingViewBits = u();
    c->pCarTypeInfo = &g_ctis[u()];
    ri = (int32_t)u();
    c->pRenderInfo = ri >= 0 ? (CarRenderInfo *)(void *)g_ris[ri] : NULL;
}

static void line_m(void)
{
    uint32_t i = u();
    uint8_t *wheel = (uint8_t *)g_cars[i].State.WheelMatrix;
    uint8_t *brake = (uint8_t *)g_cars[i].State.BrakeMatrix;
    int q;

    for (q = 0; q < 64; q++) {
        uint32_t v = u();

        memcpy(wheel + 4 * q, &v, 4);
    }
    for (q = 0; q < 64; q++) {
        uint32_t v = u();

        memcpy(brake + 4 * q, &v, 4);
    }
}

static void line_x(void)
{
    char *t = strtok(NULL, " \t\r\n");

    g_swap_who = t[0];
    g_swap_k = (int)u();
    g_swap_j = (int)u();
}

int main(int argc, char **argv)
{
    static char line[16384];
    FILE *fp;
    int n = 0;

    if (argc != 2) {
        fprintf(stderr, "usage: rendercars_test scenarios.txt\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    eMathInit();
    gCarDamageAboveFn = st_damage_above;

    while (fgets(line, sizeof line, fp) != NULL) {
        char *t = strtok(line, " \t\r\n");

        if (t == NULL)
            continue;
        switch (t[0]) {
        case 'S': line_s(); break;
        case 'P': line_p(); break;
        case 'K': line_k(); break;
        case 'C': line_c(); break;
        case 'M': line_m(); break;
        case 'X': line_x(); break;
        case 'G':
            printf("R %d\n", n++);
            render_cars(&g_view);
            printf("E %s\n", label(pCurrentWorld));
            break;
        default:
            fprintf(stderr, "rendercars_test: bad line %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
