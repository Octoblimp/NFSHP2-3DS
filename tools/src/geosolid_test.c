// Harness for tools/geosolid_check.py: runs geosolidunif.c on the
// checker's lines and prints what it makes, each float as its bits in hex.
//
//     M p0..p15 mv0..mv15 fog0..fog3 l0..l2    geosolid_model: the 16 of
//                                              mvp, the fog's 4, the light's 4
//     C r g b ambient                          geosolid_colours: the light's
//                                              colour's 4, the ambient's 4
//
//     geosolid_test < script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "geosolidunif.h"

static int read_floats(float *f, int n)
{
    int i;

    for (i = 0; i < n; i++) {
        unsigned long u;
        uint32_t      w;

        if (scanf("%lx", &u) != 1) {
            return 0;
        }
        w = (uint32_t)u;
        memcpy(&f[i], &w, sizeof w);
    }
    return 1;
}

static void put(const float *f, int n)
{
    int i;

    for (i = 0; i < n; i++) {
        uint32_t w;

        memcpy(&w, &f[i], sizeof w);
        printf("%s%08lx", i ? " " : "", (unsigned long)w);
    }
}

int main(void)
{
    char cmd[8];

    while (scanf("%7s", cmd) == 1) {
        if (strcmp(cmd, "M") == 0) {
            float         p[4][4], mv[4][4], fog[4], l[3];
            GeoSolidModel out;

            if (!read_floats(&p[0][0], 16) || !read_floats(&mv[0][0], 16)
                || !read_floats(fog, 4) || !read_floats(l, 3)) {
                printf("BAD M\n");
                return 1;
            }
            geosolid_model((const float(*)[4])p, (const float(*)[4])mv, fog,
                           l, &out);
            printf("M ");
            put(&out.mvp[0][0], 16);
            printf(" ");
            put(out.fog, 4);
            printf(" ");
            put(out.light, 4);
            printf("\n");
        } else if (strcmp(cmd, "C") == 0) {
            float in[4], lightClr[4], ambientClr[4];

            if (!read_floats(in, 4)) {
                printf("BAD C\n");
                return 1;
            }
            geosolid_colours(in[0], in[1], in[2], in[3], lightClr,
                             ambientClr);
            printf("C ");
            put(lightClr, 4);
            printf(" ");
            put(ambientClr, 4);
            printf("\n");
        } else {
            printf("BAD %s\n", cmd);
            return 1;
        }
    }
    return 0;
}
