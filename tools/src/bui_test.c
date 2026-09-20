// Host harness for the 3DS Flailer reader.
//
// Builds "3DS Files/source/bui.c" for the host and prints the whole project
// as one line per screen and one per object, in file order:
//
//     project <hash> <numScreens> <numObjects>
//     screen <hash> <resX> <resY> <numObjects> <parsedCount>
//     obj <type> <visible> <z> <nameHash> <groupHash> <x> <y> <sx> <sy>
//         <rot> <anim> <renderOnPoly> <clipToPoly> [type-specific]
//
// tools/bui_check.py prints the same from tools/flailer_dump.py and diffs
// it, which is what pins the object walk: the loader identifies objects by
// ObjectType rather than chunk id, so a reader that keys off the chunk id
// agrees only as long as the two never disagree.
//
// Usage: bui_test <file.BUN>

#include <stdio.h>
#include <stdlib.h>

#include "bui.h"

static void print_string(const char* s, uint32_t max)
{
    // Hex, so the diff against the Python reader is about the bytes rather
    // than about latin-1. The inline string is NUL-terminated inside
    // MaxChars in this build; stop at the first NUL as the engine does.
    static const char* digits = "0123456789abcdef";
    for (uint32_t i = 0; i < max && s[i]; i++) {
        unsigned char c = (unsigned char)s[i];
        putchar(digits[c >> 4]);
        putchar(digits[c & 15]);
    }
}

int main(int argc, char** argv)
{
    if (argc < 2) { fprintf(stderr, "usage: %s <file.BUN>\n", argv[0]); return 2; }
    FILE* fh = fopen(argv[1], "rb");
    if (!fh) { perror(argv[1]); return 1; }
    fseek(fh, 0, SEEK_END);
    long len = ftell(fh);
    fseek(fh, 0, SEEK_SET);
    uint8_t* buf = (uint8_t*)malloc((size_t)len);
    if (!buf || fread(buf, 1, (size_t)len, fh) != (size_t)len) {
        fprintf(stderr, "read failed\n"); return 1;
    }
    fclose(fh);

    BUI ui;
    if (!bui_open(&ui, buf, 0, (size_t)len)) {
        fprintf(stderr, "no Flailer chunk in %s\n", argv[1]);
        return 1;
    }
    printf("project %08x %u %u\n", ui.projectHash, ui.numScreens,
           ui.numObjects);

    for (uint32_t i = 0; i < ui.numScreens; i++) {
        const BUIScreen* s = &ui.screens[i];
        printf("screen %08x %u %u %u %u\n", s->nameHash, s->resX, s->resY,
               s->numObjects, s->count);
        for (uint32_t j = 0; j < s->count; j++) {
            BUIObject o;
            if (!bui_object(&ui, s->first + j, &o)) { printf("obj BAD\n"); continue; }
            printf("obj %d %d %d %08x %08x %g %g %g %g %d %d %08x %08x",
                   (int)o.type, (int)o.visible, (int)o.z, o.nameHash,
                   o.groupHash, (double)o.x, (double)o.y, (double)o.scaleX,
                   (double)o.scaleY, (int)o.rotation, (int)o.animation,
                   o.renderOnPoly, o.clipToPoly);
            if (o.type == BUI_TYPE_BITMAP) {
                printf(" tex %08x %08x %08x %08x %08x", o.textureHash,
                       o.colors[0], o.colors[1], o.colors[2], o.colors[3]);
                for (int k = 0; k < 8; k++) printf(" %g", (double)o.uv[k]);
            } else if (o.type == BUI_TYPE_TEXT) {
                printf(" txt %08x %u %08x %08x %u ", o.fontHash, o.maxChars,
                       o.format, o.color, o.languageID);
                print_string(o.string, o.maxChars);
            }
            putchar('\n');
        }
    }
    bui_close(&ui);
    free(buf);
    return 0;
}
