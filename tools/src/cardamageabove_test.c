// cardamageabove_test -- the host half of tools/cardamageabove_check.py:
// reads its scenarios, lays each car out, calls car_damage_above or
// car_damage_cap, and prints what every stand-in was asked, in the
// model's words.
//
// A scenario is a run of lines, "S" first and "G" to go; every value is
// hex, a float by its bits.

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "car.h"
#include "cardamageabove.h"
#include "cartypeinfo.h"
#include "copmanager.h"
#include "eframe.h"
#include "emath.h"
#include "epoly.h"
#include "player.h"
#include "playerhud.h"
#include "race.h"
#include "texturepack.h"

#define PATTERN 0xa5
#define FRAME_BYTES 1024

// ------------------------------------------------- what the two read

struct Player     *PlayerPlayersByIndex[2];
RaceParameters     TheRaceParameters;
RaceCoordinator   *pRaceCoordinator;
tCopManager       *pCopManager;
uint8_t           *CurrentBufferPos;
uint8_t           *CurrentBufferEnd;
int32_t            FrameMallocFailed;
uint32_t           FrameMallocFailAmount;
bVector3           ObjectPoints[13];
bVector4           DamageAboveMatrix[4];

// ------------------------------------------------------------ the world

static Car           g_car;
static CarTypeInfo   g_cti;
static DriverInfo    g_driver;
static struct Player g_players[2];
static tCopManager   g_cm;
static uint32_t      g_rc[4];
static TextureInfo   g_tex;
static uint8_t       g_frame[FRAME_BYTES] __attribute__((aligned(16)));
static bVector3      g_eye, g_dir;
static int32_t       g_nis[2];
static uint32_t      g_pursued, g_has_tex, g_nobuf;

static uint32_t u(void)
{
    char *t = strtok(NULL, " \t\r\n");

    if (t == NULL) {
        fprintf(stderr, "cardamageabove_test: short line\n");
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

static void put_words(void *p, int n)
{
    uint8_t *b = p;
    int i;

    for (i = 0; i < n; i++) {
        uint32_t w = u();

        memcpy(b + 4 * i, &w, 4);
    }
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

// ------------------------------------------------------------ the labels

static const char *label(const void *p)
{
    static char buf[4][32];
    static int next;
    const uint8_t *b = p;
    char *s;

    if (p == NULL)
        return "null";
    if (p == (const void *)&g_car)
        return "car";
    if (p == (const void *)&g_cm)
        return "cm";
    if (p == (const void *)&g_tex)
        return "tex";
    if (p == (const void *)&g_players[0])
        return "p0";
    if (p == (const void *)&g_players[1])
        return "p1";
    if (b >= g_frame && b < g_frame + FRAME_BYTES) {
        s = buf[next];
        next = (next + 1) & 3;
        sprintf(s, "f+%x", (unsigned)(b - g_frame));
        return s;
    }
    return "-";
}

// ----------------------------------------------------------- the stand-ins

RCState racecoordinator_get_current_state(const RaceCoordinator *rc)
{
    return *(const RCState *)(const void *)rc;
}

int32_t player_is_nis_playing(const struct Player *p)
{
    int32_t v = g_nis[p == &g_players[1]];

    printf("  nis %s -> %x\n", label(p), (unsigned)v);
    return v;
}

tPursuit *copmanager_is_being_pursued(tCopManager *m, struct Car *c)
{
    printf("  pursued %s %s -> %x\n", label(m), label(c),
           (unsigned)g_pursued);
    return g_pursued ? (tPursuit *)(void *)&g_rc[2] : NULL;
}

TextureInfo *GetTextureInfo(uint32_t hash, int use_default,
                            int include_unloaded)
{
    printf("  tex %08x %x %x -> %s\n", (unsigned)hash,
           (unsigned)use_default, (unsigned)include_unloaded,
           g_has_tex ? "tex" : "null");
    return g_has_tex ? &g_tex : NULL;
}

static void st_render_3d(ePoly *p, TextureInfo *tex, bMatrix4 *m, int flags)
{
    int k;

    printf("  render %s %s %x |", label(tex), label(m), (unsigned)flags);
    for (k = 0; k < 4; k++)
        words(&p->Vertices[k], 3);
    printf(" |");
    words(p->Colours, 4);
    printf(" |");
    for (k = 0; k < 4; k++)
        words(p->UVs[k], 2);
    printf(" |");
    words(m, 16);
    printf("\n");
}

// ------------------------------------------------------------ the lines

// S: the players, the race, the cop manager, the texture, the frame.
static void line_s(void)
{
    uint32_t pos, end;
    int k;

    memset(&g_car, PATTERN, sizeof g_car);
    memset(&g_cti, PATTERN, sizeof g_cti);
    memset(&g_driver, PATTERN, sizeof g_driver);
    memset(&g_cm, PATTERN, sizeof g_cm);
    memset(g_rc, PATTERN, sizeof g_rc);
    memset(g_frame, PATTERN, sizeof g_frame);
    for (k = 0; k < 2; k++) {
        PlayerPlayersByIndex[k] = u() ? &g_players[k] : NULL;
        g_nis[k] = (int32_t)u();
    }
    TheRaceParameters.BeACop = (int32_t)u();
    pRaceCoordinator = u() ? (RaceCoordinator *)(void *)g_rc : NULL;
    g_rc[0] = u();
    pCopManager = u() ? &g_cm : NULL;
    g_pursued = u();
    g_has_tex = u();
    g_nobuf = u();
    pos = u();
    end = u();
    if (g_nobuf) {
        CurrentBufferPos = NULL;
        CurrentBufferEnd = NULL;
    } else {
        CurrentBufferPos = g_frame + pos;
        CurrentBufferEnd = g_frame + end;
    }
    FrameMallocFailed = (int32_t)u();
    FrameMallocFailAmount = u();
}

// C: the car.
static void line_c(void)
{
    g_car.CarIndex = (int16_t)u();
    g_car.pCarTypeInfo = &g_cti;
    g_car.MyDriver = &g_driver;
    g_driver.TheDriverType = (DriverType)u();
    g_car.pPlayer = u() ? &g_players[0] : NULL;
    g_cti.UsageType = (int32_t)u();
    put_words(&g_car.State.Position, 4);
    put_words(&g_car.State.BodyMatrix, 16);
}

// E: the eye and the direction.
static void line_e(void)
{
    put_words(&g_eye, 4);
    put_words(&g_dir, 4);
}

// D: the cop manager's damage, a car each.
static void line_d(void)
{
    put_words(g_cm.fCarDamage, COPMANAGER_NUM_CARS);
}

// O: ObjectPoints and DamageAboveMatrix.
static void line_o(void)
{
    put_words(ObjectPoints, 13 * 4);
    put_words(DamageAboveMatrix, 16);
}

static void end_line(void)
{
    uint32_t angle;

    memcpy(&angle, &g_car.fAngleToCamera, 4);
    printf("E %08x", (unsigned)angle);
    if (CurrentBufferPos == NULL)
        printf(" none");
    else
        printf(" %s", label(CurrentBufferPos));
    printf(" %x %x\n", (unsigned)FrameMallocFailed,
           (unsigned)FrameMallocFailAmount);
}

int main(int argc, char **argv)
{
    static char line[16384];
    FILE *fp;
    int n = 0;

    if (argc != 2) {
        fprintf(stderr, "usage: cardamageabove_test scenarios.txt\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    eMathInit();
    gEPolyRender3DFn = st_render_3d;

    while (fgets(line, sizeof line, fp) != NULL) {
        char *t = strtok(line, " \t\r\n");

        if (t == NULL)
            continue;
        switch (t[0]) {
        case 'S': line_s(); break;
        case 'C': line_c(); break;
        case 'E': line_e(); break;
        case 'D': line_d(); break;
        case 'O': line_o(); break;
        case 'G':
            printf("R %d\n", n++);
            car_damage_above(&g_car, &g_eye, &g_dir);
            end_line();
            break;
        case 'A': {
            // The cap alone: pursued, damage, distance.
            int32_t pursued = (int32_t)u();
            float damage = bits_f(u());
            float distance = bits_f(u());

            printf("R %d\n", n++);
            car_damage_cap(&g_car, pursued, damage, distance);
            end_line();
            break;
        }
        default:
            fprintf(stderr, "cardamageabove_test: bad line %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
