// Drives hudnis.c for tools/hudnis_check.py: NISOverlayManager's Start,
// Update, UpdateDateAndTime, SetVisible and the three Start*, on one
// overlay over flailer.c with INGAMEB's screens loaded, and banim.c's
// SplineSeek for its two tracks. A script of ops, one per line, fields
// split on '|'; numbers are C literals, floats their bits. An object is
// b:HASH (a bitmap) or t:HASH (a text) on the overlay's screen, or none:
//
//   load|PATH              a bundle: bui_open, then flailer_add_project
//   o|NAME|V               an overlay field: last, screen, state, busted
//                          (an object), points (an object), sx, sy,
//                          scalex, scaley
//   t|K|OFF|V              track K's (0 scale, 1 alpha) word at OFF
//   g|NAME|V               elapsed (WorldTimeElapsed), rframes
//                          (RealTimeFrames), wframes (WorldTimeFrames),
//                          lang (CurrLanguage)
//   rp|NAME|V              BeACop or Players (NumPlayerCars)
//   rc|STATE|DEMO          the coordinator's state, and IsReplayDemoMode
//   clock|RET|B0..B7       what sceCdReadClock writes and answers
//   local|B0..B7           what sceScfGetLocalTimefromRTC writes; local|-
//                          leaves the clock as it is
//   xl|ID|TEXT             GetTranslatedString's answer for ID
//   pos|OBJ|X|Y|SX|SY      an object's top left and scale
//   start, arrest, ticket, busted, date
//   update|PLAYING         Update
//   visible|ON             SetVisible
//
// After each op every line that changed: the overlay's fields, both
// tracks' 48 bytes and every Flailer object's bytes. The seams log their
// calls.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "banim.h"
#include "bui.h"
#include "flailer.h"
#include "hudnis.h"
#include "hudrender.h"
#include "nisoverlay.h"
#include "race.h"
#include "raceparams.h"
#include "realtime.h"
#include "trackflow.h"

#define MAX_LOADS  4
#define NUM_ARGS   48
#define MAX_XL     32

// ------------------------------------------------------------ the globals
//
// What the linked sources read and the rest of the game defines.

RaceParameters   TheRaceParameters;
RaceCoordinator *pRaceCoordinator;
int32_t          RealTimeFrames;
int32_t          WorldTimeFrames;
float            WorldTimeElapsed;
void (*gSetFlailerScreenVisibilityFn)(uint32_t screen, int visibility);
const char *(*gHudTranslateFn)(int32_t id);
int32_t (*gCurrLanguageFn)(void);

// ------------------------------------------------------- the coordinator

static uint8_t coordinator[64];
static int32_t rcState;
static int32_t rcDemo;

// Retail reads the state at +0, inlined.
RCState racecoordinator_get_current_state(const RaceCoordinator *rc)
{
    (void)rc;
    return (RCState)rcState;
}

int32_t racecoordinator_is_replay_demo_mode(const RaceCoordinator *rc)
{
    printf("  demo? %d -> %d\n",
           rc == (const RaceCoordinator *)(const void *)coordinator ? 1 : 0,
           (int)rcDemo);
    return rcDemo;
}

// ------------------------------------------------------------ the seams

static uint8_t clockBytes[8];
static int32_t clockRet;
static uint8_t localBytes[8];
static int     localSet;
static int32_t language;

static struct {
    int32_t id;
    char    text[64];
} xl[MAX_XL];
static int numXl;
static char xlOut[64];

static void hex8(char *out, const uint8_t *b)
{
    for (int i = 0; i < 8; i++)
        sprintf(out + 2 * i, "%02x", b[i]);
}

static int32_t seam_read_clock(NisClock *c)
{
    char h[17];

    memcpy(c, clockBytes, 8);
    hex8(h, clockBytes);
    printf("  clock %s -> %d\n", h, (int)clockRet);
    return clockRet;
}

static void seam_local(NisClock *c)
{
    char h[17];

    hex8(h, (const uint8_t *)c);
    printf("  local %s\n", h);
    if (localSet)
        memcpy(c, localBytes, 8);
}

static const char *seam_translate(int32_t id)
{
    for (int i = 0; i < numXl; i++)
        if (xl[i].id == id) {
            printf("  xl %#x -> %s\n", (unsigned)id, xl[i].text);
            return xl[i].text;
        }
    snprintf(xlOut, sizeof xlOut, "M%x", (unsigned)id);
    printf("  xl %#x -> %s\n", (unsigned)id, xlOut);
    return xlOut;
}

static int32_t seam_language(void)
{
    return language;
}

static void seam_screen_visibility(uint32_t screen, int v)
{
    printf("  screen %08x vis %d\n", screen, v);
}

// ------------------------------------------------------- Flailer's seams
//
// The renderer's answers, from the object alone, as flailer_test.c's are.

static uint32_t text_len(const struct FlailerTextChunk *t)
{
    uint32_t n = 0;
    while ((int32_t)n < t->MaxChars && t->String[n]) n++;
    return n;
}

static float text_w(struct FlailerTextChunk *t)
{
    uint32_t k = text_len(t) * 9 + t->Object.NameHash % 7;
    return t->Object.ScaleX * (float)k;
}

static float text_h(struct FlailerTextChunk *t)
{
    return t->Object.ScaleY * (float)(t->Object.NameHash % 23 + 8);
}

static bool texture_size(struct FlailerBitmapChunk *b, int32_t *w,
                         int32_t *h)
{
    *w = (int32_t)(b->TextureHash % 509 + 1);
    *h = (int32_t)(b->TextureHash % 251 + 1);
    return true;
}

// ------------------------------------------------------------ the world

static BUI      loads[MAX_LOADS];
static uint8_t *bufs[MAX_LOADS];
static int      numLoads;

static NISOverlayManager overlay;
static BSpline           tracks[2];

// --------------------------------------------------------- number parsing

static uint32_t num(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static int32_t inum(const char *s)
{
    return (int32_t)strtol(s, NULL, 0);
}

static float fnum(const char *s)
{
    uint32_t v = num(s);
    float    f;
    memcpy(&f, &v, 4);
    return f;
}

static uint32_t fbits(float f)
{
    uint32_t v;
    memcpy(&v, &f, 4);
    return v;
}

// ----------------------------------------------------------------- names

static int load_of(const BUI *ui)
{
    for (int i = 0; i < numLoads; i++)
        if (&loads[i] == ui) return i;
    return -1;
}

static const char *obj_name(const void *p, char *buf, size_t n)
{
    BUI     *ui = NULL;
    uint32_t idx = 0;
    if (p == NULL) return "none";
    if (!flailer_object_index((const struct FlailerObjectChunk *)p, &ui,
                              &idx))
        return "stray";
    snprintf(buf, n, "%d:%u", load_of(ui), idx);
    return buf;
}

// An object of the overlay's screen: t:HASH, b:HASH or none.
static struct FlailerObjectChunk *object(const char *s)
{
    uint32_t screen = overlay.ScreenHash;

    if (!strncmp(s, "t:", 2))
        return flailer_find_object(screen, num(s + 2), FLAILER_TYPE_TEXT);
    if (!strncmp(s, "b:", 2))
        return flailer_find_object(screen, num(s + 2), FLAILER_TYPE_BITMAP);
    return NULL;
}

// ------------------------------------------------------------- the dump

typedef struct Line {
    char *key;
    char *text;
} Line;

static Line  *lines;
static size_t numLines, capLines;

// strdup, which -std=c11 does not declare.
static char *dup(const char *s)
{
    size_t n = strlen(s) + 1;
    return (char *)memcpy(malloc(n), s, n);
}

static void note(const char *key, const char *text)
{
    for (size_t i = 0; i < numLines; i++) {
        if (strcmp(lines[i].key, key) != 0) continue;
        if (strcmp(lines[i].text, text) != 0) {
            free(lines[i].text);
            lines[i].text = dup(text);
            printf("  %s %s\n", key, text);
        }
        return;
    }
    if (numLines == capLines) {
        capLines = capLines ? capLines * 2 : 1024;
        lines = (Line *)realloc(lines, capLines * sizeof *lines);
    }
    lines[numLines].key = dup(key);
    lines[numLines].text = dup(text);
    numLines++;
    printf("  %s %s\n", key, text);
}

static void hex(char *out, const uint8_t *p, uint32_t from, uint32_t to)
{
    static const char digits[] = "0123456789abcdef";
    for (uint32_t i = from; i < to; i++) {
        *out++ = digits[p[i] >> 4];
        *out++ = digits[p[i] & 15];
    }
    *out = 0;
}

// flailer_test.c's dump: all but the bTNode and pFlailerStrip, and a text
// object's characters up to the NUL.
static void dump_objects(void)
{
    static char text[8192];
    char        key[32];

    for (int l = 0; l < numLoads; l++) {
        BUI *ui = &loads[l];
        for (uint32_t s = 0; s < ui->numScreens; s++) {
            const BUIScreen *sc = &ui->screens[s];
            for (uint32_t i = 0; i < sc->count; i++) {
                const BUIObjectRef *r = &ui->objects[sc->first + i];
                const uint8_t      *p = r->payload;
                char               *o = text;
                snprintf(key, sizeof key, "obj %d:%u", l, sc->first + i);
                hex(o, p, 8, 44);
                o += strlen(o);
                *o++ = ' ';
                if ((int8_t)p[40] == FLAILER_TYPE_TEXT && r->size >= 100) {
                    const struct FlailerTextChunk *t =
                        (const struct FlailerTextChunk *)(const void *)p;
                    hex(o, p, 48, 100);
                    o += strlen(o);
                    snprintf(o, sizeof text - (size_t)(o - text),
                             " \"%.*s\"", (int)text_len(t), t->String);
                } else {
                    hex(o, p, 48, r->size);
                }
                note(key, text);
                // A drawn frame clears DirtyFlag, so the next dump shows
                // only what the next op stamps.
                ((uint8_t *)(uintptr_t)p)[43] = 0;
            }
        }
    }
}

static const char *track_name(const BSpline *t)
{
    return t == &tracks[0] ? "t0" : t == &tracks[1] ? "t1" : "stray";
}

static void dump(void)
{
    char text[512], nb[2][16];

    snprintf(text, sizeof text,
             "last %08x screen %08x state %d tracks %s %s busted %s "
             "points %s sx %08x sy %08x scale %08x %08x",
             overlay.LastDateTimeUpdate, overlay.ScreenHash,
             (int)overlay.State, track_name(overlay.ScaleAnimationTrack),
             track_name(overlay.AlphaAnimationTrack),
             obj_name(overlay.BustedDisplay, nb[0], sizeof nb[0]),
             obj_name(overlay.PointsDisplay, nb[1], sizeof nb[1]),
             fbits(overlay.sx), fbits(overlay.sy), fbits(overlay.ScaleX),
             fbits(overlay.ScaleY));
    note("ovl", text);
    for (int k = 0; k < 2; k++) {
        char key[8];
        snprintf(key, sizeof key, "t%d", k);
        hex(text, (const uint8_t *)&tracks[k], 0, 48);
        note(key, text);
    }
    dump_objects();
}

// ------------------------------------------------------------------- ops

static void load(const char *path)
{
    FILE *f = fopen(path, "rb");
    long  len;
    BUI  *ui = &loads[numLoads];
    if (!f) {
        printf("  cannot open %s\n", path);
        exit(2);
    }
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    bufs[numLoads] = (uint8_t *)malloc((size_t)len);
    if (fread(bufs[numLoads], 1, (size_t)len, f) != (size_t)len) exit(2);
    fclose(f);
    if (!bui_open(ui, bufs[numLoads], 0, (size_t)len)) {
        printf("  bui_open failed\n");
        exit(2);
    }
    numLoads++;
    printf("  loaded %d\n", flailer_add_project(ui) ? 1 : 0);
}

static void set_overlay(const char *n, const char *v)
{
    if (!strcmp(n, "last")) overlay.LastDateTimeUpdate = num(v);
    else if (!strcmp(n, "screen")) overlay.ScreenHash = num(v);
    else if (!strcmp(n, "state")) overlay.State = inum(v);
    else if (!strcmp(n, "busted")) overlay.BustedDisplay = object(v);
    else if (!strcmp(n, "points")) overlay.PointsDisplay = object(v);
    else if (!strcmp(n, "sx")) overlay.sx = fnum(v);
    else if (!strcmp(n, "sy")) overlay.sy = fnum(v);
    else if (!strcmp(n, "scalex")) overlay.ScaleX = fnum(v);
    else if (!strcmp(n, "scaley")) overlay.ScaleY = fnum(v);
    else {
        printf("  no overlay field %s\n", n);
        exit(2);
    }
}

static void set_global(const char *k, const char *v)
{
    if (!strcmp(k, "elapsed")) WorldTimeElapsed = fnum(v);
    else if (!strcmp(k, "rframes")) RealTimeFrames = inum(v);
    else if (!strcmp(k, "wframes")) WorldTimeFrames = inum(v);
    else if (!strcmp(k, "lang")) language = inum(v);
    else {
        printf("  no global %s\n", k);
        exit(2);
    }
}

static void bytes8(uint8_t *b, char **a)
{
    for (int i = 0; i < 8; i++)
        b[i] = (uint8_t)num(a[i]);
}

static void run(char *line)
{
    char *a[NUM_ARGS];
    int   n = 0;
    char *s = line;

    while (n < NUM_ARGS) {
        a[n++] = s;
        s = strchr(s, '|');
        if (!s) break;
        *s++ = 0;
    }
    if (!strcmp(a[0], "load")) {
        load(a[1]);
        return;
    }
    if (!strcmp(a[0], "o")) set_overlay(a[1], a[2]);
    else if (!strcmp(a[0], "t")) {
        uint32_t v = num(a[3]);
        memcpy((uint8_t *)&tracks[inum(a[1])] + inum(a[2]), &v, 4);
    } else if (!strcmp(a[0], "g")) set_global(a[1], a[2]);
    else if (!strcmp(a[0], "rp")) {
        if (!strcmp(a[1], "BeACop"))
            TheRaceParameters.BeACop = inum(a[2]);
        else if (!strcmp(a[1], "Players"))
            TheRaceParameters.NumPlayerCars = inum(a[2]);
        else {
            printf("  no rp %s\n", a[1]);
            exit(2);
        }
    } else if (!strcmp(a[0], "rc")) {
        rcState = inum(a[1]);
        rcDemo = inum(a[2]);
    } else if (!strcmp(a[0], "clock")) {
        clockRet = inum(a[1]);
        bytes8(clockBytes, a + 2);
    } else if (!strcmp(a[0], "local")) {
        localSet = strcmp(a[1], "-") != 0;
        if (localSet) bytes8(localBytes, a + 1);
    } else if (!strcmp(a[0], "xl")) {
        int32_t id = inum(a[1]);
        int     i;
        for (i = 0; i < numXl && xl[i].id != id; i++)
            ;
        if (i == numXl) numXl++;
        xl[i].id = id;
        snprintf(xl[i].text, sizeof xl[i].text, "%s", a[2]);
    } else if (!strcmp(a[0], "pos")) {
        struct FlailerObjectChunk *o = object(a[1]);
        o->X = fnum(a[2]);
        o->Y = fnum(a[3]);
        o->ScaleX = fnum(a[4]);
        o->ScaleY = fnum(a[5]);
    } else if (!strcmp(a[0], "start")) nisoverlay_start(&overlay);
    else if (!strcmp(a[0], "arrest")) nisoverlay_start_arrest(&overlay);
    else if (!strcmp(a[0], "ticket")) nisoverlay_start_ticket(&overlay);
    else if (!strcmp(a[0], "busted")) nisoverlay_start_busted(&overlay);
    else if (!strcmp(a[0], "date")) nisoverlay_update_date_and_time(&overlay);
    else if (!strcmp(a[0], "update"))
        nisoverlay_update(&overlay, inum(a[1]) != 0);
    else if (!strcmp(a[0], "visible"))
        nisoverlay_set_visible(&overlay, num(a[1]));
    else {
        printf("  no op %s\n", a[0]);
        exit(2);
    }
    dump();
}

// The word a fresh block holds at offset o, as the model's.
static uint32_t pattern(int o)
{
    return 0x3f800000u + (uint32_t)o * 16u;
}

static float fpat(int o)
{
    uint32_t w = pattern(o);
    float    f;
    memcpy(&f, &w, 4);
    return f;
}

int main(int argc, char **argv)
{
    static char line[4096];
    FILE       *f;

    if (argc < 2) return 2;
    f = fopen(argv[1], "r");
    if (!f) return 2;

    gFlailerTextScaledWidthFn = text_w;
    gFlailerTextScaledHeightFn = text_h;
    gFlailerBitmapTextureSizeFn = texture_size;
    gCdReadClockFn = seam_read_clock;
    gScfGetLocalTimeFn = seam_local;
    gHudTranslateFn = seam_translate;
    gCurrLanguageFn = seam_language;
    gSetFlailerScreenVisibilityFn = seam_screen_visibility;
    pRaceCoordinator = (RaceCoordinator *)(void *)coordinator;

    for (int k = 0; k < 2; k++)
        for (int o = 0; o < 48; o += 4) {
            uint32_t w = pattern(o);
            memcpy((uint8_t *)&tracks[k] + o, &w, 4);
        }
    overlay.LastDateTimeUpdate = pattern(0);
    overlay.ScreenHash = 0;
    overlay.State = 0;
    overlay.ScaleAnimationTrack = &tracks[0];
    overlay.AlphaAnimationTrack = &tracks[1];
    overlay.sx = fpat(28);
    overlay.sy = fpat(32);
    overlay.ScaleX = fpat(36);
    overlay.ScaleY = fpat(40);

    while (fgets(line, sizeof line, f)) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
            line[--n] = 0;
        if (!n) continue;
        printf("> %s\n", line);
        run(line);
    }
    fclose(f);
    return 0;
}
