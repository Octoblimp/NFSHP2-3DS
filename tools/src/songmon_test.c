// Drives songmon.c for tools/songmon_check.py. A script of ops, one per
// line, fields split on '|':
//
//   playing|N          what IsPlaying answers
//   track|N            what GetCurrentTrack answers
//   field|F|text       the current tune's field F; "~" is NULL, "^" empty
//   timer|N            RealTimer
//   text|NAME|W        a text object on CHYRON, GetWidth W
//   bitmap|NAME|TW|SX|SY   a bitmap: GetWidth is (int)(TW * its scale X)
//   gone|NAME          no such object
//   update             tNewSongMonitor::Update
//   dump               the monitor
//
// Every hook prints what it was asked, as the model's stubs do.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "songmon.h"

#define MAX_OBJECTS 32

typedef struct {
    uint32_t hash;
    int      kind;       // 0 none, 1 text, 2 bitmap
    int32_t  width;      // text
    int32_t  texW;       // bitmap
    float    sx, sy;
} Object;

static Object objects[MAX_OBJECTS];
static int numObjects;
static int playing;
static uint32_t track;
static char fieldText[3][128];
static int fieldNull[3] = {1, 1, 1};
static uint32_t timer;

static uint32_t fbits(float f)
{
    uint32_t u;
    memcpy(&u, &f, 4);
    return u;
}

static float bitsf(uint32_t u)
{
    float f;
    memcpy(&f, &u, 4);
    return f;
}

static Object* find(uint32_t hash)
{
    for (int i = 0; i < numObjects; i++) {
        if (objects[i].hash == hash && objects[i].kind) {
            return &objects[i];
        }
    }
    return NULL;
}

static Object* slot(const char* name)
{
    uint32_t hash = bchunk_hash(name);
    for (int i = 0; i < numObjects; i++) {
        if (objects[i].hash == hash) {
            return &objects[i];
        }
    }
    if (numObjects == MAX_OBJECTS) {
        exit(3);
    }
    Object* o = &objects[numObjects++];
    memset(o, 0, sizeof *o);
    o->hash = hash;
    return o;
}

static int h_playing(void* u)
{
    (void)u;
    printf("  isplaying\n");
    return playing;
}

static uint32_t h_current(void* u)
{
    (void)u;
    printf("  current\n");
    return track;
}

static const char* h_track(void* u, int field)
{
    (void)u;
    printf("  track %d\n", field);
    if (field < 0 || field > 2 || fieldNull[field]) {
        return NULL;
    }
    return fieldText[field];
}

static uint32_t h_timer(void* u)
{
    (void)u;
    return timer;
}

static void h_vis(void* u, uint32_t screen, int visible)
{
    (void)u;
    printf("  vis %08x %d\n", screen, visible);
}

static void h_print(void* u, uint32_t screen, uint32_t object, const char* s)
{
    (void)u;
    printf("  print %08x %08x %s\n", screen, object, s);
}

static int32_t h_width(void* u, uint32_t screen, uint32_t object)
{
    (void)u;
    Object* o = find(object);
    int32_t w = 0;
    if (o && o->kind == 1) {
        w = o->width;
    } else if (o && o->kind == 2) {
        w = (int32_t)((float)o->texW * o->sx);
    }
    printf("  width %08x %08x %d\n", screen, object, w);
    return w;
}

static void h_scale(void* u, uint32_t screen, uint32_t object, float* sx,
                    float* sy)
{
    (void)u;
    Object* o = find(object);
    printf("  scale %08x %08x\n", screen, object);
    if (o) {
        *sx = o->sx;
        *sy = o->sy;
    }
}

static void h_setx(void* u, uint32_t screen, uint32_t object, float sx)
{
    (void)u;
    Object* o = find(object);
    printf("  setx %08x %08x %08x\n", screen, object, fbits(sx));
    if (o) {
        o->sx = sx;
    }
}

static const BSongMonitorHooks hooks = {
    NULL, h_playing, h_current, h_track, h_timer, h_vis, h_print, h_width,
    h_scale, h_setx,
};

static BSongMonitor mon;

static uint32_t num(const char* s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

int main(int argc, char** argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: songmon_test script\n");
        return 2;
    }
    FILE* sc = fopen(argv[1], "r");
    if (!sc) {
        return 2;
    }
    bsm_init(&mon, &hooks);
    static char line[512];
    while (fgets(line, sizeof line, sc)) {
        line[strcspn(line, "\r\n")] = 0;
        if (!line[0]) {
            continue;
        }
        printf("> %s\n", line);
        char* arg[8];
        int n = 0;
        for (char* t = strtok(line, "|"); t && n < 8; t = strtok(NULL, "|")) {
            arg[n++] = t;
        }
        const char* op = arg[0];
        if (!strcmp(op, "playing")) {
            playing = (int)num(arg[1]);
        } else if (!strcmp(op, "track")) {
            track = num(arg[1]);
        } else if (!strcmp(op, "field")) {
            int f = (int)num(arg[1]);
            fieldNull[f] = !strcmp(arg[2], "~");
            snprintf(fieldText[f], sizeof fieldText[f], "%s",
                     strcmp(arg[2], "^") ? arg[2] : "");
        } else if (!strcmp(op, "timer")) {
            timer = num(arg[1]);
        } else if (!strcmp(op, "text")) {
            Object* o = slot(arg[1]);
            o->kind = 1;
            o->width = (int32_t)strtol(arg[2], NULL, 0);
            o->sx = o->sy = 1.0f;
        } else if (!strcmp(op, "bitmap")) {
            Object* o = slot(arg[1]);
            o->kind = 2;
            o->texW = (int32_t)strtol(arg[2], NULL, 0);
            o->sx = bitsf(num(arg[3]));
            o->sy = bitsf(num(arg[4]));
        } else if (!strcmp(op, "gone")) {
            slot(arg[1])->kind = 0;
        } else if (!strcmp(op, "update")) {
            bsm_update(&mon);
        } else if (!strcmp(op, "dump")) {
            printf("  mon %08x %08x %08x %d %d %d\n", mon.track, mon.start,
                   mon.screen, mon.starts, mon.printed, mon.titleWidth);
            for (int i = 0; i < numObjects; i++) {
                printf("  obj %08x %d %08x\n", objects[i].hash,
                       objects[i].kind, fbits(objects[i].sx));
            }
        }
    }
    return 0;
}
