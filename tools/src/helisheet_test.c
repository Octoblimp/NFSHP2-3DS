// helisheet_test -- the port's half of tools/helisheet_check.py: runs
// helisheet.c over the checker's script and prints what the model prints.

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "helisheet.h"
#include "p32.h"

#define ROOM     0x14000
#define SENTINEL 0xa5a5a5a5u

static _Alignas(128) uint8_t base[ROOM + 64];
static uint8_t *chunk = base;

static uint32_t hex(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 16);
}

static float bf(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static uint32_t fb(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static const char *sym(const void *p)
{
    static char b[4][24];
    static int  k;
    const uint8_t *q = (const uint8_t *)p;

    k = (k + 1) & 3;
    if (p == NULL)
        snprintf(b[k], sizeof b[k], "0");
    else if (q >= chunk && q < chunk + ROOM)
        snprintf(b[k], sizeof b[k], "C+%d", (int)(q - chunk));
    else
        snprintf(b[k], sizeof b[k], "?");
    return b[k];
}

static void op(char **a, int na)
{
    const char *k = a[0];

    (void)na;
    if (strcmp(k, "chunk") == 0) {
        FILE  *f = fopen(a[1], "rb");
        size_t n;

        if (f == NULL) {
            perror(a[1]);
            exit(2);
        }
        memset(base, 0, sizeof base);
        chunk = base + atoi(a[2]);
        n = fread(chunk, 1, ROOM, f);
        (void)n;
        fclose(f);
    } else if (strcmp(k, "load") == 0) {
        int        r = loader_heli_sheet(chunk);
        HeliSheet *s = TheHeliSheet;

        if (r && s != NULL)
            printf("load -> %d sheet %s polys %s n %d\n", r, sym(s),
                   sym(p32_ptr(s->Polys)), s->NumPolys);
        else
            printf("load -> %d sheet %s\n", r, sym(s));
    } else if (strcmp(k, "unload") == 0) {
        int r = unloader_heli_sheet(chunk);

        printf("unload -> %d sheet %s\n", r, sym(TheHeliSheet));
    } else if (strcmp(k, "id") == 0) {
        uint32_t v = hex(a[1]);

        memcpy(chunk, &v, 4);
    } else if (strcmp(k, "p16") == 0) {
        int16_t v = (int16_t)atoi(a[2]);

        memcpy(chunk + atoi(a[1]), &v, 2);
    } else if (strcmp(k, "p8") == 0) {
        chunk[atoi(a[1])] = (uint8_t)(atoi(a[2]) & 0xff);
    } else if (strcmp(k, "p32") == 0) {
        uint32_t v = hex(a[2]);

        memcpy(chunk + atoi(a[1]), &v, 4);
    } else if (strcmp(k, "find") == 0) {
        HeliSheet *s = TheHeliSheet;
        bVector2   pt;
        uint32_t   zb = SENTINEL, f = SENTINEL;
        float      z = bf(SENTINEL);
        int32_t    r;

        pt.x = bf(hex(a[1]));
        pt.y = bf(hex(a[2]));
        r = helisheet_find_z_value(s, &pt, a[3][0] == '1' ? &z : NULL,
                                   a[4][0] == '1' ? &f : NULL);
        zb = fb(z);
        printf("find %s %s -> %d z %08x f %08x recent %d %d %d\n", a[1],
               a[2], (int)r, (unsigned)zb, (unsigned)f, s->Recent[0],
               s->Recent[1], s->Recent[2]);
    } else {
        fprintf(stderr, "bad op %s\n", k);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[1 << 12];
    FILE       *f;

    if (argc != 2) {
        fprintf(stderr, "usage: helisheet_test script.txt\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    while (fgets(line, sizeof line, f) != NULL) {
        char *a[16], *s = line;
        int   na = 0;

        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        while (na < 16) {
            a[na++] = s;
            s = strchr(s, '|');
            if (s == NULL)
                break;
            *s++ = 0;
        }
        op(a, na);
    }
    fclose(f);
    return 0;
}
