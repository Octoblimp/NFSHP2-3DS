// Host harness for the debug menu's FRONTB patch (debugmenu_patch.c).
//
// Rebuilds the bundle's Flailer chunk as the handheld does at boot, writes
// it out, then shows the item (debugmenu_reveal) and writes it again, and
// opens each with bui.c to say what the runtime's reader makes of it:
//
//     bui <numScreens> <numObjects>
//     reveal <first> <second>
//
// tools/debugmenu_check.py reads the two files with tools/flailer_dump.py
// and holds them against the bundle.
//
// Usage: debugmenu_test <FRONTB.BUN> <patched.bin> <revealed.bin>

#include <stdio.h>
#include <stdlib.h>

#include "bui.h"
#include "debugmenu.h"

static uint8_t* slurp(const char* path, size_t* len)
{
    FILE*    f = fopen(path, "rb");
    uint8_t* p;
    long     n;
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    p = (uint8_t*)malloc((size_t)n);
    if (p && fread(p, 1, (size_t)n, f) != (size_t)n) {
        free(p);
        p = NULL;
    }
    fclose(f);
    *len = (size_t)n;
    return p;
}

static int spill(const char* path, const uint8_t* p, size_t n)
{
    FILE* f = fopen(path, "wb");
    int   ok;
    if (!f) return 0;
    ok = fwrite(p, 1, n, f) == n;
    fclose(f);
    return ok;
}

int main(int argc, char** argv)
{
    size_t   len = 0, n = 0;
    uint8_t* data;
    uint8_t* out;
    BUI      ui;
    int      first, second;

    if (argc != 4) {
        fprintf(stderr, "usage: debugmenu_test FRONTB.BUN out1 out2\n");
        return 2;
    }
    data = slurp(argv[1], &len);
    if (!data) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 1;
    }
    out = debugmenu_patch_frontend(data, len, &n);
    if (!out) {
        fprintf(stderr, "patch refused the bundle\n");
        return 1;
    }
    if (!spill(argv[2], out, n)) return 1;
    if (!bui_open(&ui, out, 0, n)) {
        fprintf(stderr, "bui_open refused the patched chunk\n");
        return 1;
    }
    printf("bui %u %u\n", (unsigned)ui.numScreens, (unsigned)ui.numObjects);
    bui_close(&ui);
    first  = debugmenu_reveal();
    second = debugmenu_reveal();
    printf("reveal %d %d\n", first, second);
    if (!spill(argv[3], out, n)) return 1;
    free(out);
    free(data);
    return 0;
}
