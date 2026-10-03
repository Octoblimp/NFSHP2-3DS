// Host harness for tools/bprintf_check.py: runs b_snprintf over the
// checker's script and prints what it wrote and what it answered.
//
// Each line is p|SIZE|FMT|TYPES|ARG... -- FMT in hex, TYPES one letter an
// argument: f a float (hex bits, passed as a double), d an int, s a string
// (hex), p a pointer (hex). The buffer is SIZE bytes, with a guard behind
// it that must come back untouched.

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bprintf.h"

#define GUARD 16

static char sFmt[256];
static char sStr[6][256];
static double sF[6];
static int sD[6];
static void *sP[6];
static char sBuf[4096 + GUARD];

static void unhex(char *out, const char *s)
{
    while (s[0] && s[1]) {
        unsigned v;

        sscanf(s, "%2x", &v);
        *out++ = (char)v;
        s += 2;
    }
    *out = '\0';
}

#define F(i) sF[i]
#define D(i) sD[i]
#define S(i) sStr[i]
#define P(i) sP[i]
#define CASE(t, ...)                                                    \
    if (!strcmp(types, t))                                              \
        return b_snprintf(sBuf, size, sFmt, __VA_ARGS__);

// The argument lists the script uses; bprintf_check.py's TYPES is the same.
static int call(const char *types, size_t size, int *ok)
{
    *ok = 1;
    if (!*types)
        return b_snprintf(sBuf, size, sFmt, 0);
    CASE("f", F(0))
    CASE("d", D(0))
    CASE("s", S(0))
    CASE("p", P(0))
    CASE("dd", D(0), D(1))
    CASE("df", D(0), F(1))
    CASE("dp", D(0), P(1))
    CASE("ds", D(0), S(1))
    CASE("sd", S(0), D(1))
    CASE("sf", S(0), F(1))
    CASE("ff", F(0), F(1))
    CASE("ddd", D(0), D(1), D(2))
    CASE("ddf", D(0), D(1), F(2))
    CASE("ddp", D(0), D(1), P(2))
    CASE("dfd", D(0), F(1), D(2))
    CASE("fff", F(0), F(1), F(2))
    CASE("sdf", S(0), D(1), F(2))
    CASE("fffd", F(0), F(1), F(2), D(3))
    CASE("ffffff", F(0), F(1), F(2), F(3), F(4), F(5))
    *ok = 0;
    return 0;
}

int main(int argc, char **argv)
{
    static char line[4096];
    FILE *f;

    if (argc < 2 || !(f = fopen(argv[1], "r"))) {
        fprintf(stderr, "usage: bprintf_test SCRIPT\n");
        return 2;
    }
    while (fgets(line, sizeof line, f)) {
        char *tok[12];
        int nt = 0, i, r, ok, bad = 0;
        size_t size;
        const char *types;
        char *p;

        line[strcspn(line, "\r\n")] = '\0';
        printf("> %s\n", line);
        for (p = strtok(line, "|"); p && nt < 12; p = strtok(NULL, "|"))
            tok[nt++] = p;
        if (nt < 4 || strcmp(tok[0], "p"))
            continue;
        size = (size_t)strtoul(tok[1], NULL, 10);
        unhex(sFmt, tok[2]);
        types = strcmp(tok[3], "-") ? tok[3] : "";
        for (i = 0; types[i] && i < 6 && 4 + i < nt; i++) {
            const char *a = tok[4 + i];

            switch (types[i]) {
            case 'f': {
                uint32_t b = (uint32_t)strtoul(a, NULL, 16);
                float v;

                memcpy(&v, &b, 4);
                sF[i] = v;
                break;
            }
            case 'd':
                sD[i] = (int)strtol(a, NULL, 10);
                break;
            case 's':
                unhex(sStr[i], a);
                break;
            case 'p':
                sP[i] = (void *)(uintptr_t)strtoul(a, NULL, 16);
                break;
            }
        }
        memset(sBuf, 0xee, sizeof sBuf);
        r = call(types, size, &ok);
        if (!ok) {
            printf("  no case for %s\n", types);
            continue;
        }
        for (i = 0; i < GUARD; i++)
            if ((unsigned char)sBuf[size + i] != 0xee)
                bad = 1;
        printf("  %d \"%s\"%s\n", r, size ? sBuf : "",
               bad ? " OVERRUN" : "");
    }
    fclose(f);
    return 0;
}
