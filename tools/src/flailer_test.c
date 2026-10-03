// Drives flailer.c for tools/flailer_check.py. A script of ops, one per
// line, fields split on '|'; numbers are C literals, floats their bits:
//
//   load|PATH                 a bundle: bui_open, then flailer_add_project
//   screen|S                  FindFlailerScreen
//   find|S|O|T                FindFlailerObject; the result is "cur"
//   group|S|G|T|A             FindFlailerObjectByGroup after cur (A 1) or
//                             from the head (A 0); the result is cur
//   order                     the project list and each one's screens
//   state                     a CRC of every object's and screen's bytes
//   m|NAME|args...            a method on cur, then cur's bytes
//   w|NAME|S|O|args...        a wrapper, then FindFlailerObject(S, O, 0)'s
//                             bytes
//
// Objects print as P:I, the project's load number and bui's object index.
// The seams answer from the object alone, as the model's stubs do: a text
// object is (strlen * 9 + NameHash % 7) * ScaleX wide and (NameHash % 23
// + 8) * ScaleY high, and a bitmap's texture TextureHash % 509 + 1 by
// TextureHash % 251 + 1.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bui.h"
#include "flailer.h"

#define MAX_LOADS 8

static BUI      loads[MAX_LOADS];
static uint8_t* bufs[MAX_LOADS];
static int      numLoads;
static struct FlailerObjectChunk* cur;

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

static uint32_t num(const char* s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static int32_t inum(const char* s)
{
    return (int32_t)strtol(s, NULL, 0);
}

static float fnum(const char* s)
{
    return bitsf(num(s));
}

// ------------------------------------------------------------------ seams

static uint32_t text_len(const struct FlailerTextChunk* t)
{
    uint32_t n = 0;
    while ((int32_t)n < t->MaxChars && t->String[n]) n++;
    return n;
}

static float text_w(struct FlailerTextChunk* t)
{
    uint32_t k = text_len(t) * 9 + t->Object.NameHash % 7;
    return t->Object.ScaleX * (float)k;
}

static float text_h(struct FlailerTextChunk* t)
{
    return t->Object.ScaleY * (float)(t->Object.NameHash % 23 + 8);
}

static bool texture_size(struct FlailerBitmapChunk* b, int32_t* w,
                         int32_t* h)
{
    *w = (int32_t)(b->TextureHash % 509 + 1);
    *h = (int32_t)(b->TextureHash % 251 + 1);
    return true;
}

// ------------------------------------------------------------------ output

static int load_of(const BUI* ui)
{
    for (int i = 0; i < numLoads; i++)
        if (&loads[i] == ui) return i;
    return -1;
}

static void print_obj(const char* what, const struct FlailerObjectChunk* o)
{
    BUI*     ui = NULL;
    uint32_t idx = 0;
    if (o == NULL) {
        printf("  %s none\n", what);
        return;
    }
    if (!flailer_object_index(o, &ui, &idx)) {
        printf("  %s stray\n", what);
        return;
    }
    printf("  %s %d:%u\n", what, load_of(ui), idx);
}

static void hex(const uint8_t* p, uint32_t from, uint32_t to)
{
    for (uint32_t i = from; i < to; i++) printf("%02x", p[i]);
}

// The bytes a setter may write: all but the bTNode and pFlailerStrip, and
// a text object's characters up to the NUL.
static void dump_obj(const char* what, const struct FlailerObjectChunk* o)
{
    BUI*           ui = NULL;
    uint32_t       idx = 0, size;
    const uint8_t* p = (const uint8_t*)o;
    if (o == NULL || !flailer_object_index(o, &ui, &idx)) {
        printf("  %s -\n", what);
        return;
    }
    size = ui->objects[idx].size;
    printf("  %s %d:%u ", what, load_of(ui), idx);
    hex(p, 8, 44);
    printf(" ");
    if (o->ObjectType == FLAILER_TYPE_TEXT && size >= 100) {
        const struct FlailerTextChunk* t = (const struct FlailerTextChunk*)o;
        hex(p, 48, 100);
        printf(" \"%.*s\"", (int)text_len(t), t->String);
    } else {
        hex(p, 48, size);
    }
    printf("\n");
}

// zlib's CRC-32, so the model can use zlib.crc32.
static uint32_t crc32_update(uint32_t crc, const uint8_t* p, size_t n)
{
    crc = ~crc;
    while (n--) {
        crc ^= *p++;
        for (int k = 0; k < 8; k++)
            crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1)));
    }
    return ~crc;
}

static void state(void)
{
    uint32_t crc = 0;
    for (int l = 0; l < numLoads; l++) {
        BUI* ui = &loads[l];
        for (uint32_t s = 0; s < ui->numScreens; s++) {
            const BUIScreen* sc = &ui->screens[s];
            if (sc->def) crc = crc32_update(crc, sc->def + 8, 24);
            for (uint32_t i = 0; i < sc->count; i++) {
                const BUIObjectRef* r = &ui->objects[sc->first + i];
                const uint8_t*      p = r->payload;
                crc = crc32_update(crc, p + 8, 36);
                if ((int8_t)p[40] == FLAILER_TYPE_TEXT && r->size >= 100) {
                    const struct FlailerTextChunk* t =
                        (const struct FlailerTextChunk*)p;
                    crc = crc32_update(crc, p + 48, 52);
                    crc = crc32_update(crc, p + 100, text_len(t));
                } else {
                    crc = crc32_update(crc, p + 48, r->size - 48);
                }
            }
        }
    }
    printf("  crc %08x\n", crc);
}

static void order(void)
{
    const uint32_t* ord;
    uint32_t        n;
    BUI*            ui;
    for (int k = 0; (ui = flailer_project_at(k, &ord, &n)) != NULL; k++) {
        printf("  project %d:", load_of(ui));
        for (uint32_t i = 0; i < n; i++) printf(" %u", ord[i]);
        printf("\n");
    }
}

// ------------------------------------------------------------------ ops

static void load(const char* path)
{
    FILE*  f = fopen(path, "rb");
    long   len;
    BUI*   ui = &loads[numLoads];
    if (!f) {
        printf("  cannot open %s\n", path);
        exit(2);
    }
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    bufs[numLoads] = (uint8_t*)malloc((size_t)len);
    if (fread(bufs[numLoads], 1, (size_t)len, f) != (size_t)len) exit(2);
    fclose(f);
    if (!bui_open(ui, bufs[numLoads], 0, (size_t)len)) {
        printf("  bui_open failed\n");
        exit(2);
    }
    numLoads++;
    printf("  loaded %d\n", flailer_add_project(ui) ? 1 : 0);
}

static bVector4 vec(char** a)
{
    bVector4 v;
    v.x = fnum(a[0]);
    v.y = fnum(a[1]);
    v.z = fnum(a[2]);
    v.w = fnum(a[3]);
    return v;
}

static void method(char** a)
{
    struct FlailerObjectChunk* o = cur;
    struct FlailerTextChunk*   t = (struct FlailerTextChunk*)cur;
    struct FlailerBitmapChunk* b = (struct FlailerBitmapChunk*)cur;
    const char*                m = a[0];
    float                      x = 0.0f, y = 0.0f;
    bVector4                   v;

    if (o == NULL) {
        printf("  no object\n");
        return;
    }
    if (!strcmp(m, "get_alpha"))
        printf("  = %d\n", flailerobject_get_alpha(o));
    else if (!strcmp(m, "set_z"))
        flailerobject_set_z(o, inum(a[1]));
    else if (!strcmp(m, "get_width"))
        printf("  = %d\n", flailerobject_get_width(o));
    else if (!strcmp(m, "get_height"))
        printf("  = %d\n", flailerobject_get_height(o));
    else if (!strcmp(m, "get_width_float"))
        printf("  = %08x\n", fbits(flailerobject_get_width_float(o)));
    else if (!strcmp(m, "get_height_float"))
        printf("  = %08x\n", fbits(flailerobject_get_height_float(o)));
    else if (!strcmp(m, "set_alpha"))
        flailerobject_set_alpha(o, inum(a[1]));
    else if (!strcmp(m, "set_rotation"))
        flailerobject_set_rotation(o, fnum(a[1]));
    else if (!strcmp(m, "set_visibility"))
        flailerobject_set_visibility(o, inum(a[1]));
    else if (!strcmp(m, "set_color")) {
        v = vec(a + 1);
        flailerobject_set_color(o, &v);
    } else if (!strcmp(m, "set_scale_x"))
        flailerobject_set_scale_x(o, fnum(a[1]));
    else if (!strcmp(m, "set_scale_y"))
        flailerobject_set_scale_y(o, fnum(a[1]));
    else if (!strcmp(m, "set_width"))
        flailerobject_set_width(o, fnum(a[1]));
    else if (!strcmp(m, "set_height"))
        flailerobject_set_height(o, fnum(a[1]));
    else if (!strcmp(m, "scale_about_center"))
        flailerobject_scale_about_center(o, fnum(a[1]));
    else if (!strcmp(m, "get_center")) {
        flailerobject_get_center(o, &x, &y);
        printf("  = %08x %08x\n", fbits(x), fbits(y));
    } else if (!strcmp(m, "set_center_x"))
        flailerobject_set_center_x(o, fnum(a[1]));
    else if (!strcmp(m, "set_center_y"))
        flailerobject_set_center_y(o, fnum(a[1]));
    else if (!strcmp(m, "get_top_left")) {
        flailerobject_get_top_left(o, &x, &y);
        printf("  = %08x %08x\n", fbits(x), fbits(y));
    } else if (!strcmp(m, "set_top_left_x"))
        flailerobject_set_top_left_x(o, fnum(a[1]));
    else if (!strcmp(m, "set_top_left_y"))
        flailerobject_set_top_left_y(o, fnum(a[1]));
    else if (!strcmp(m, "set_clip_to_poly"))
        flailerobject_set_clip_to_poly(o, num(a[1]));
    else if (!strcmp(m, "delete_strip"))
        flailerobject_delete_strip(o);
    else if (!strcmp(m, "t_set_format"))
        flailertext_set_format_options(t, num(a[1]));
    else if (!strcmp(m, "t_clear_format"))
        flailertext_clear_format_options(t, num(a[1]));
    else if (!strcmp(m, "t_set_color"))
        flailertext_set_color(t, num(a[1]));
    else if (!strcmp(m, "t_set_string"))
        flailertext_set_string(t, a[1]);
    else if (!strcmp(m, "t_update_language"))
        flailertext_update_language_text(t);
    else if (!strcmp(m, "t_set_language"))
        flailertext_set_language_id(t, num(a[1]));
    else if (!strcmp(m, "t_set_alpha"))
        flailertext_set_alpha(t, inum(a[1]));
    else if (!strcmp(m, "t_get_alpha"))
        printf("  = %d\n", flailertext_get_alpha(t));
    else if (!strcmp(m, "t_set_color_vector")) {
        v = vec(a + 1);
        flailertext_set_color_vector(t, &v);
    } else if (!strcmp(m, "b_set_alpha"))
        flailerbitmap_set_alpha(b, inum(a[1]), inum(a[2]));
    else if (!strcmp(m, "b_set_rotation"))
        flailerbitmap_set_rotation(b, fnum(a[1]));
    else if (!strcmp(m, "b_set_color"))
        flailerbitmap_set_color(b, num(a[1]));
    else if (!strcmp(m, "b_set_color_vector")) {
        v = vec(a + 1);
        flailerbitmap_set_color_vector(b, &v);
    } else if (!strcmp(m, "b_change_texture"))
        flailerbitmap_change_texture(b, num(a[1]));
    else if (!strcmp(m, "b_get_alpha"))
        printf("  = %d\n", flailerbitmap_get_alpha(b, inum(a[1])));
    else if (!strcmp(m, "printf_chunk"))
        printf("  = %d\n", flailer_printf_chunk(t, a[1], inum(a[2])));
    else {
        printf("  unknown method %s\n", m);
        exit(2);
    }
    dump_obj("cur", cur);
}

static void wrapper(char** a)
{
    const char* m = a[0];
    uint32_t    s = num(a[1]), o = num(a[2]);
    float       x = 1.25f, y = -3.5f;
    int32_t     ix = 7, iy = -9, ir = 11, ib = -13;
    bVector4    v;

    if (!strcmp(m, "printf_d"))
        printf("  = %d\n", flailer_printf(s, o, a[3], inum(a[4])));
    else if (!strcmp(m, "printf_s"))
        printf("  = %d\n", flailer_printf(s, o, a[3], a[4]));
    else if (!strcmp(m, "printf_dd"))
        printf("  = %d\n", flailer_printf(s, o, a[3], inum(a[4]),
                                          inum(a[5])));
    else if (!strcmp(m, "set_text_color"))
        flailer_set_text_color(s, o, num(a[3]));
    else if (!strcmp(m, "set_text_format"))
        flailer_set_text_format_option(s, o, num(a[3]));
    else if (!strcmp(m, "clear_text_format"))
        flailer_clear_text_format_option(s, o, num(a[3]));
    else if (!strcmp(m, "get_top_left")) {
        flailer_get_top_left_position(s, o, &x, &y);
        printf("  = %08x %08x\n", fbits(x), fbits(y));
    } else if (!strcmp(m, "get_top_left_int")) {
        flailer_get_top_left_position_int(s, o, &ix, &iy);
        printf("  = %d %d\n", ix, iy);
    } else if (!strcmp(m, "get_top_left_x"))
        printf("  = %08x\n", fbits(flailer_get_top_left_x(s, o)));
    else if (!strcmp(m, "get_top_left_y"))
        printf("  = %08x\n", fbits(flailer_get_top_left_y(s, o)));
    else if (!strcmp(m, "get_width"))
        printf("  = %d\n", flailer_get_width(s, o));
    else if (!strcmp(m, "get_height"))
        printf("  = %d\n", flailer_get_height(s, o));
    else if (!strcmp(m, "set_top_left"))
        flailer_set_top_left_position(s, o, inum(a[3]), inum(a[4]));
    else if (!strcmp(m, "set_z"))
        flailer_set_z(s, o, inum(a[3]));
    else if (!strcmp(m, "set_top_left_y"))
        flailer_set_top_left_y(s, o, inum(a[3]));
    else if (!strcmp(m, "set_top_left_x"))
        flailer_set_top_left_x(s, o, inum(a[3]));
    else if (!strcmp(m, "get_scale")) {
        flailer_get_scale(s, o, &x, &y);
        printf("  = %08x %08x\n", fbits(x), fbits(y));
    } else if (!strcmp(m, "set_scale_x"))
        flailer_set_scale_x(s, o, fnum(a[3]));
    else if (!strcmp(m, "set_scale_y"))
        flailer_set_scale_y(s, o, fnum(a[3]));
    else if (!strcmp(m, "set_center"))
        flailer_set_center(s, o, inum(a[3]), inum(a[4]));
    else if (!strcmp(m, "get_alpha"))
        printf("  = %d\n", flailer_get_alpha(s, o));
    else if (!strcmp(m, "set_alpha"))
        flailer_set_alpha(s, o, inum(a[3]));
    else if (!strcmp(m, "set_rotation"))
        flailer_set_rotation(s, o, fnum(a[3]));
    else if (!strcmp(m, "set_visibility"))
        flailer_set_visibility(s, o, inum(a[3]));
    else if (!strcmp(m, "set_language"))
        flailer_set_language_id(s, o, num(a[3]));
    else if (!strcmp(m, "set_object_color")) {
        v = vec(a + 3);
        flailer_set_object_color(s, o, &v);
    } else if (!strcmp(m, "change_texture"))
        flailer_change_texture(s, o, num(a[3]));
    else if (!strcmp(m, "set_group_visibility"))
        flailer_set_group_visibility(s, o, inum(a[3]));
    else if (!strcmp(m, "set_width"))
        flailer_set_width(s, o, fnum(a[3]));
    else if (!strcmp(m, "set_height"))
        flailer_set_height(s, o, fnum(a[3]));
    else if (!strcmp(m, "get_bounding_box")) {
        flailer_get_bounding_box(s, o, &ix, &iy, &ir, &ib);
        printf("  = %d %d %d %d\n", ix, iy, ir, ib);
    } else if (!strcmp(m, "set_clip_to_poly"))
        flailer_set_clip_to_poly(s, o, num(a[3]));
    else if (!strcmp(m, "scale_about_center"))
        flailer_scale_about_center(s, o, fnum(a[3]));
    else if (!strcmp(m, "set_center_y"))
        flailer_set_center_y(s, o, inum(a[3]));
    else if (!strcmp(m, "set_center_x"))
        flailer_set_center_x(s, o, inum(a[3]));
    else if (!strcmp(m, "get_center")) {
        flailer_get_center(s, o, &ix, &iy);
        printf("  = %d %d\n", ix, iy);
    } else if (!strcmp(m, "get_center_y"))
        printf("  = %d\n", flailer_get_center_y(s, o));
    else if (!strcmp(m, "get_center_x"))
        printf("  = %d\n", flailer_get_center_x(s, o));
    else if (!strcmp(m, "set_group_position"))
        flailer_set_group_position(s, o, num(a[3]), fnum(a[4]), fnum(a[5]));
    else if (!strcmp(m, "offset_group"))
        flailer_offset_group(s, o, inum(a[3]), inum(a[4]));
    else if (!strcmp(m, "set_group_render_on_poly"))
        flailer_set_group_render_on_poly(s, o, num(a[3]));
    else if (!strcmp(m, "set_group_alpha"))
        flailer_set_group_alpha(s, o, inum(a[3]));
    else if (!strcmp(m, "make_vertical_line_f"))
        flailer_make_vertical_line(s, o, fnum(a[3]), fnum(a[4]));
    else if (!strcmp(m, "make_vertical_line"))
        flailer_make_vertical_line_between(s, o, num(a[3]), num(a[4]));
    else {
        printf("  unknown wrapper %s\n", m);
        exit(2);
    }
    dump_obj("obj", flailer_find_object(s, o, FLAILER_TYPE_ANY));
}

int main(int argc, char** argv)
{
    static char line[4096];
    FILE*       f;

    if (argc < 2) return 2;
    f = fopen(argv[1], "r");
    if (!f) return 2;
    gFlailerTextScaledWidthFn   = text_w;
    gFlailerTextScaledHeightFn  = text_h;
    gFlailerBitmapTextureSizeFn = texture_size;

    while (fgets(line, sizeof(line), f)) {
        char* a[16];
        int   n = 0;
        char* p = line;
        line[strcspn(line, "\r\n")] = 0;
        if (!line[0]) continue;
        printf("> %s\n", line);
        a[n++] = p;
        while ((p = strchr(p, '|')) != NULL && n < 16) {
            *p++ = 0;
            a[n++] = p;
        }
        if (!strcmp(a[0], "load"))
            load(a[1]);
        else if (!strcmp(a[0], "screen")) {
            BUI*       ui = NULL;
            BUIScreen* s  = flailer_screen_of(flailer_find_screen(num(a[1])),
                                              &ui);
            if (s) printf("  screen %d:%u\n", load_of(ui),
                          (unsigned)(s - ui->screens));
            else   printf("  screen none\n");
        } else if (!strcmp(a[0], "find")) {
            cur = flailer_find_object(num(a[1]), num(a[2]), inum(a[3]));
            print_obj("found", cur);
        } else if (!strcmp(a[0], "group")) {
            cur = flailer_find_object_by_group(num(a[1]), num(a[2]),
                                               inum(a[3]),
                                               inum(a[4]) ? cur : NULL);
            print_obj("found", cur);
        } else if (!strcmp(a[0], "order"))
            order();
        else if (!strcmp(a[0], "state"))
            state();
        else if (!strcmp(a[0], "poke")) {
            // What the renderer would have cached: a word into the object.
            uint32_t v = num(a[2]);
            if (cur == NULL) printf("  no object\n");
            else {
                memcpy((uint8_t*)cur + inum(a[1]), &v, 4);
                dump_obj("cur", cur);
            }
        } else if (!strcmp(a[0], "m"))
            method(a + 1);
        else if (!strcmp(a[0], "w"))
            wrapper(a + 1);
        else {
            printf("  unknown op %s\n", a[0]);
            return 2;
        }
    }
    fclose(f);
    return 0;
}
