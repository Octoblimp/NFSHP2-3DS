// Host harness for tools/rain_check.py: runs rain.c's four entry points in
// the scenario's order and prints, for each call, whether the view it was
// handed and the harness's own state came through unchanged.
//
// Scenario lines:
//   L          rain_Load
//   U          rain_Unload
//   T <bits>   rain_TimeStep, dt as a float's bits
//   R <k>      rain_Render on a view filled with pattern k
//   N          rain_Render on NULL

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "rain.h"

static unsigned char view[128], view_copy[128];
static unsigned char guard[256], guard_copy[256];

static void fill(unsigned char *p, int n, int k)
{
    int i;

    for (i = 0; i < n; i++)
        p[i] = (unsigned char)(k * 37 + i * 11 + 5);
}

static const char *kept(void)
{
    if (memcmp(view, view_copy, sizeof view) != 0)
        return "view changed";
    if (memcmp(guard, guard_copy, sizeof guard) != 0)
        return "memory changed";
    return "kept";
}

int main(int argc, char **argv)
{
    char line[64];
    FILE *f;

    if (argc < 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: rain_test <scenarios>\n");
        return 2;
    }
    fill(guard, sizeof guard, 99);
    memcpy(guard_copy, guard, sizeof guard);
    while (fgets(line, sizeof line, f) != NULL) {
        unsigned int bits;
        int k;
        float dt;

        fill(view, sizeof view, 0);
        memcpy(view_copy, view, sizeof view);
        switch (line[0]) {
        case 'L':
            rain_Load();
            printf("L %s\n", kept());
            break;
        case 'U':
            rain_Unload();
            printf("U %s\n", kept());
            break;
        case 'T':
            if (sscanf(line + 1, "%x", &bits) != 1)
                return 3;
            memcpy(&dt, &bits, 4);
            rain_TimeStep(dt);
            printf("T %08x %s\n", bits, kept());
            break;
        case 'R':
            if (sscanf(line + 1, "%d", &k) != 1)
                return 3;
            fill(view, sizeof view, k);
            memcpy(view_copy, view, sizeof view);
            rain_Render((struct eView *)(void *)view);
            printf("R %d %s\n", k, kept());
            break;
        case 'N':
            rain_Render(NULL);
            printf("N %s\n", kept());
            break;
        default:
            break;
        }
    }
    fclose(f);
    return 0;
}
