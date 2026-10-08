// Host harness for the 3DS Flailer menu system.
//
// Builds "3DS Files/source/bmenu.c" for the host, opens a menu on every
// screen of a bundle that has one, and runs a fixed script of pad events
// over it, printing the whole menu state after each step:
//
//     menu <screenHash> <numItems> <highlightBarObject>
//     item <itemID> <itemHash> <objectIndex> <savedColor>
//     msg  <message> <itemHash> <port> <noise>
//     step <label> <current> <id:state:color> ...
//
// tools/bmenu_check.py prints the same from an independent Python model
// built on tools/flailer_dump.py and diffs the two. The point is the same
// as for the other modules: two implementations written from the same
// disassembly, disagreeing wherever one of them misread it.
//
// Usage: bmenu_test <file.BUN> [--also <file.BUN>]...

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmenu.h"

#define MAX_BUNDLES 4

static uint8_t* slurp(const char* path, size_t* outLen)
{
    FILE* fh = fopen(path, "rb");
    if (!fh) { perror(path); return NULL; }
    fseek(fh, 0, SEEK_END);
    long len = ftell(fh);
    fseek(fh, 0, SEEK_SET);
    uint8_t* buf = (uint8_t*)malloc((size_t)len);
    if (!buf || fread(buf, 1, (size_t)len, fh) != (size_t)len) {
        fprintf(stderr, "read failed: %s\n", path);
        free(buf);
        fclose(fh);
        return NULL;
    }
    fclose(fh);
    *outLen = (size_t)len;
    return buf;
}

// Echo every message the menu raises, so the check covers the callback
// traffic and not just the end state. Consumes nothing.
static void trace(BMenu* m, BScreenMessage msg, BScreenCallbackData* data,
                  void* user)
{
    (void)m;
    (void)user;
    printf("msg %d %08x %d %d %d\n", (int)msg, data->itemHash, data->port,
           data->param, data->noise);
}

static void dump(BMenu* m, const char* label)
{
    const BMenuItem* cur = bmenu_current(m);
    printf("step %s %d", label, cur ? cur->itemID : -1);
    for (int i = 0; i < m->numItems; i++) {
        BUIObject obj;
        uint32_t  colour = 0;
        if (bui_object(m->ui, m->items[i].object, &obj)) colour = obj.color;
        printf(" %d:%u:%08x", m->items[i].itemID, m->items[i].state, colour);
    }
    putchar('\n');
}

static void run(BUI* ui, BUIScreen* screen)
{
    BMenu m;
    if (!bmenu_open(&m, ui, screen, trace, NULL)) return;
    if (m.numItems == 0) return;

    printf("menu %08x %d %d\n", screen->nameHash, m.numItems,
           (int)m.highlightBar);
    for (int i = 0; i < m.numItems; i++)
        printf("item %d %08x %u %08x\n", m.items[i].itemID, m.items[i].itemHash,
               m.items[i].object, m.items[i].savedColor);

    bmenu_activate(&m, 0);
    dump(&m, "activate");

    // Down past the end and back up past the start, so both the wrapping
    // and the non-wrapping paths get exercised on a real item list.
    static const struct { const char* name; BJoyEvent ev; } script[] = {
        { "down",   BJOY_SCROLL_DOWN },
        { "down",   BJOY_SCROLL_DOWN },
        { "down",   BJOY_SCROLL_DOWN },
        { "down",   BJOY_SCROLL_DOWN },
        { "up",     BJOY_SCROLL_UP },
        { "left",   BJOY_SCROLL_LEFT },
        { "right",  BJOY_SCROLL_RIGHT },
        { "select", BJOY_MENU_SELECT },
        { "square", BJOY_MENU_SQUARE },
        { "back",   BJOY_MENU_BACK },
        { "aup",    BJOY_ANALOG_UP },
        { "adown",  BJOY_ANALOG_DOWN },
    };
    const int steps = (int)(sizeof(script) / sizeof(script[0]));

    for (int pass = 0; pass < 2; pass++) {
        m.looping = (pass == 0);
        printf("mode %s\n", m.looping ? "looping" : "linear");
        for (int i = 0; i < steps; i++) {
            bool acted = bmenu_joy(&m, 0, script[i].ev, true);
            printf("acted %d\n", acted ? 1 : 0);
            dump(&m, script[i].name);
        }
        // Key-up is ignored at every level in the engine.
        printf("acted %d\n", bmenu_joy(&m, 0, BJOY_SCROLL_DOWN, false) ? 1 : 0);
    }

    // Graying the second item and walking again: the looping mode skips it,
    // the linear mode does not.
    if (m.numItems > 1) {
        bmenu_set_item_enabled(&m, m.items[1].itemID, false);
        dump(&m, "grayed");
        m.looping = true;
        bmenu_activate(&m, 0);
        dump(&m, "reactivate");
        bmenu_joy(&m, 0, BJOY_SCROLL_DOWN, true);
        dump(&m, "skip");
        bmenu_set_item_enabled(&m, m.items[1].itemID, true);
        dump(&m, "ungrayed");
    }

    // FilterPort: a menu bound to port 0 must ignore port 1 entirely.
    m.filterPort = 0;
    printf("acted %d\n", bmenu_joy(&m, 1, BJOY_SCROLL_DOWN, true) ? 1 : 0);
    m.filterPort = -1;

    bmenu_unactivate(&m);
    dump(&m, "unactivate");
}

int main(int argc, char** argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <file.BUN> [--also <file.BUN>]...\n",
                argv[0]);
        return 2;
    }

    uint8_t* bufs[MAX_BUNDLES];
    BUI      uis[MAX_BUNDLES];
    int      n = 0;

    for (int i = 1; i < argc && n < MAX_BUNDLES; i++) {
        if (!strcmp(argv[i], "--also")) continue;
        size_t len = 0;
        bufs[n] = slurp(argv[i], &len);
        if (!bufs[n]) return 1;
        if (!bui_open(&uis[n], bufs[n], 0, len)) {
            fprintf(stderr, "no Flailer chunk in %s\n", argv[i]);
            free(bufs[n]);
            continue;
        }
        n++;
    }

    for (int i = 0; i < n; i++)
        for (uint32_t s = 0; s < uis[i].numScreens; s++)
            run(&uis[i], &uis[i].screens[s]);

    for (int i = 0; i < n; i++) { bui_close(&uis[i]); free(bufs[i]); }
    return 0;
}
