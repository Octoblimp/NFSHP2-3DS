// Harness for tools/geocull_check.py: runs geocull.c on the checker's
// lines and prints what it makes, each float as its bits in hex.
//
//     P m0..m15                    geocull_planes of that mvp: P, the
//                                  planes' 16, their sizes' 16
//     K nv count v... i...         geocull_build of nv vertices, STRIDE
//                                  floats each (x y z, then two it must
//                                  skip), and `count` indices in decimal:
//                                  K, the boxes' number, then each box's
//                                  lo, hi and geocull_box against the last
//                                  P's planes: the batch's against all
//                                  four, its clusters', unless it is OUT,
//                                  only against those it is across, as
//                                  the draw tests them
//
//     geocull_test < script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "geocull.h"

#define STRIDE 5

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
    char          cmd[8];
    GeoCullPlanes planes;

    memset(&planes, 0, sizeof planes);
    while (scanf("%7s", cmd) == 1) {
        if (strcmp(cmd, "P") == 0) {
            float mvp[4][4];

            if (!read_floats(&mvp[0][0], 16)) {
                printf("BAD P\n");
                return 1;
            }
            geocull_planes((const float(*)[4])mvp, &planes);
            printf("P ");
            put(&planes.pl[0][0], 16);
            printf(" ");
            put(&planes.mag[0][0], 16);
            printf("\n");
        } else if (strcmp(cmd, "K") == 0) {
            int         nv, count, n, i, batch = GEOCULL_OUT;
            unsigned    across = 0;
            float*      pos;
            uint16_t*   idx;
            GeoCluster* box;

            if (scanf("%d %d", &nv, &count) != 2 || nv < 0 || count < 0) {
                printf("BAD K\n");
                return 1;
            }
            pos = (float*)malloc(((size_t)nv * STRIDE + 1) * sizeof *pos);
            idx = (uint16_t*)malloc(((size_t)count + 1) * sizeof *idx);
            box = (GeoCluster*)malloc(((size_t)geocull_count(count) + 1)
                                      * sizeof *box);
            if (!pos || !idx || !box || !read_floats(pos, nv * STRIDE)) {
                printf("BAD K\n");
                return 1;
            }
            for (i = 0; i < count; i++) {
                int k;

                if (scanf("%d", &k) != 1 || k < 0 || k >= nv) {
                    printf("BAD K\n");
                    return 1;
                }
                idx[i] = (uint16_t)k;
            }
            n = geocull_build(pos, STRIDE, idx, count, box);
            printf("K %d", n);
            for (i = 0; i < n; i++) {
                int v;

                if (i == 0) {
                    v = batch = geocull_box_in(&planes, &box[0], GEOCULL_ALL,
                                               &across);
                } else if (batch != GEOCULL_OUT) {
                    v = geocull_box_in(&planes, &box[i], across, NULL);
                } else {
                    v = geocull_box(&planes, &box[i]);
                }
                printf(" ");
                put(box[i].lo, 3);
                printf(" ");
                put(box[i].hi, 3);
                printf(" %d", v);
            }
            printf("\n");
            free(pos);
            free(idx);
            free(box);
        } else {
            printf("BAD %s\n", cmd);
            return 1;
        }
    }
    return 0;
}
