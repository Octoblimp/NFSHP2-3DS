// Host harness for the debug menu's FRONTB patch (debugmenu_patch.c).
//
// Rebuilds the bundle's Flailer chunk as the handheld does at boot, writes
// it out, then shows the item (debugmenu_reveal) and writes it again, and
// opens each with bui.c to say what the runtime's reader makes of it:
//
//     bui <numScreens> <numObjects>
//     reveal <first> <second>
//     rank <MENUITEM_1..5's> <MENUITEM_6's>
//
// Then the main menu's scroll (TASKS 68): for 3, 4 and 5 rows held, the
// highlight down the rows twice round and up them twice round, as the
// menu's looping moves go, and then up once more, round to the last row,
// so the next count's window starts past where it can. Each step is
// written to the fourth file as
//
//     held <rows held>                       (the count set)
//     show <rows held> <item> <first row shown>
//     tick <rows held> <item> <objects moved>
//     obj <index> <name hash> <visible> <y> <ScaleY>
//
// with an obj line for each of the main menu's labels, masks and
// BOTTOM_MASKs and the port's two fillers, as bui reads them. A tick is
// each label and mask moved down as the slide-in's groups move them, then
// debugmenu_main_tick, as the frame after the show.
//
// tools/debugmenu_check.py reads the files and holds them against the
// bundle.
//
// Usage: debugmenu_test <FRONTB.BUN> <patched.bin> <revealed.bin>
//                       <scroll.txt>

#include <stdio.h>
#include <stdlib.h>

#include "bui.h"
#include "debugmenu.h"

#define BOTTOM_MASK 0xaa5d7d3fu

static const uint32_t kNames[] = {
    BGF_ITEM_MENUITEM_1, BGF_ITEM_MENUITEM_2, BGF_ITEM_MENUITEM_3,
    BGF_ITEM_MENUITEM_4, BGF_ITEM_MENUITEM_5, BGF_MI_1_MASK, BGF_MI_2_MASK,
    BGF_MI_3_MASK, BGF_MI_4_MASK, BGF_MI_5_MASK, BOTTOM_MASK,
    DEBUGMENU_FILL_4, DEBUGMENU_FILL_5,
};

static void dump(FILE* f, const BUI* ui, const BUIScreen* s)
{
    for (uint32_t i = s->first; i < s->first + s->count; i++) {
        BUIObject o;
        if (!bui_object(ui, i, &o)) continue;
        for (size_t k = 0; k < sizeof kNames / sizeof kNames[0]; k++)
            if (o.nameHash == kNames[k])
                fprintf(f, "obj %u %08x %d %.4f %.6f\n", (unsigned)i,
                        (unsigned)o.nameHash, o.visible, o.y, o.scaleY);
    }
}

// Every label and mask a row's step and a bit down, each its own, as a
// group put back at a Y it saved would leave them. The count moved.
static int shake(BUI* ui, const BUIScreen* s)
{
    int moved = 0;
    for (uint32_t i = s->first; i < s->first + s->count; i++) {
        BUIObject o;
        if (!bui_object(ui, i, &o)) continue;
        for (size_t k = 0; k < 10; k++)
            if (o.nameHash == kNames[k]
                && bui_set_object_pos(ui, i, o.x,
                                      o.y + 55.0f + (float)k)) {
                moved++;
                break;
            }
    }
    return moved;
}

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

    if (argc != 5) {
        fprintf(stderr, "usage: debugmenu_test FRONTB.BUN out1 out2 "
                        "scroll.txt\n");
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

    {
        uint32_t   order[5];
        int        rows = 0;
        FILE*      f;
        BUIScreen* s;

        printf("rank");
        for (uint32_t i = 0; i < 5; i++)
            printf(" %d", debugmenu_main_rank(BGF_ITEM_MENUITEM_1 + i));
        printf(" %d\n", debugmenu_main_rank(BGF_ITEM_MENUITEM_6));
        // The rows in the order the rank gives, as bmenu_reorder sorts.
        for (int r = 0; r < 5; r++)
            for (uint32_t i = 0; i < 5; i++)
                if (debugmenu_main_rank(BGF_ITEM_MENUITEM_1 + i) == r)
                    order[rows++] = BGF_ITEM_MENUITEM_1 + i;

        if (!bui_open(&ui, out, 0, n)) return 1;
        s = bui_find_screen(&ui, BGF_SCREEN_NEW_MAIN_MENU);
        f = fopen(argv[4], "w");
        if (!s || !f) return 1;
        for (int held = 3; held <= 5; held++) {
            debugmenu_main_set_slots(held);
            fprintf(f, "held %d\n", held);
            dump(f, &ui, s);
            for (int k = 0; k <= 4 * rows; k++) {
                int      i    = k < 2 * rows ? k % rows
                                             : rows - 1 - (k % rows);
                uint32_t item = order[i];
                int      top  = debugmenu_main_show(item);
                fprintf(f, "show %d %08x %d\n", held, (unsigned)item, top);
                dump(f, &ui, s);
                {
                    int moved = shake(&ui, s);
                    debugmenu_main_tick();
                    fprintf(f, "tick %d %08x %d\n", held, (unsigned)item,
                            moved);
                    dump(f, &ui, s);
                }
            }
        }
        fclose(f);
        bui_close(&ui);
        debugmenu_main_set_slots(5);
    }
    free(out);
    free(data);
    return 0;
}
