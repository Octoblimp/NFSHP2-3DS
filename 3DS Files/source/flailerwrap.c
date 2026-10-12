// flailerwrap -- see flailerwrap.h. Slice RE-2c.

#include "flailerwrap.h"

#include <stddef.h>
#include <string.h>

#include "eefpu.h"
#include "flailer.h"

// The objects a group can have, `slti 32`. Retail's array is 32 words; the
// one past it is the stack's, and the port's is NULL.
#define WRAP_MAX_OBJECTS 32

// WriteTextIntoChunk's buffer, bMemSet to 0 first.
#define WRAP_LINE_BYTES 256

// isspace(int), 0x00144a68: a space, a tab or the NUL.
static int is_space(int c)
{
    return c == ' ' || c == '\t' || c == 0;
}

// WriteTextIntoChunk, 0x00144ae8. Retail's bMemCpy has no bound; the port
// stops short of the buffer's end, and no line on the disc is that long.
static void write_text_into_chunk(struct FlailerTextChunk *t,
                                  const char *start, const char *end)
{
    char buf[WRAP_LINE_BYTES];
    size_t n = (size_t)(end - start);

    memset(buf, 0, sizeof buf);
    if (n > sizeof buf - 1)
        n = sizeof buf - 1;
    memcpy(buf, start, n);
    flailerobject_set_visibility(&t->Object, FLAILER_OBJECT_VISIBLE);
    flailertext_set_string(t, buf);
}

int32_t flailer_render_text_into_group(uint32_t screen, uint32_t group,
                                       const char *str)
{
    struct FlailerTextChunk *chunks[WRAP_MAX_OBJECTS + 1];
    struct FlailerObjectChunk *o = NULL;
    struct FlailerTextChunk *last;
    const char *p = str, *line = str, *brk_at = str, *end;
    int32_t count = 0, cur = 0, next = 1, n = 0, brk = 0, maxc, i;
    float h;

    memset(chunks, 0, sizeof chunks);
    while (count < WRAP_MAX_OBJECTS
           && (o = flailer_find_object_by_group(screen, group,
                                                FLAILER_TYPE_TEXT, o))
                  != NULL)
        chunks[count++] = (struct FlailerTextChunk *)o;
    if (count == 0)
        return 0;

    end = str + strlen(str);
    maxc = chunks[0]->MaxChars;
    if (p < end && *p != 0) {
        do {
            if (is_space(*p) || *p == '@') {
                brk_at = p;
                brk = 1;
            }
            if (!brk) {
                n++;
            } else if (n < maxc - 2 && (n++, *p != '@')) {
                // Room left on the line, and not an '@'.
            } else {
                n = 0;
                if (chunks[cur] != NULL)
                    write_text_into_chunk(chunks[cur], line, brk_at);
                cur = next;
                // The loop's step skips the character after the break.
                p = brk_at + 1;
                line = p;
                if (chunks[cur] == NULL)
                    return 0;
                maxc = chunks[cur]->MaxChars;
                brk = 0;
                next = cur + 1;
            }
            p++;
        } while (p < end && *p != 0);
    }
    write_text_into_chunk(chunks[cur], line, p);

    last = chunks[next] != NULL ? chunks[next] : chunks[next - 1];
    h = gFlailerTextScaledHeightFn != NULL ? gFlailerTextScaledHeightFn(last)
                                           : 0.0f;
    // `sb zero, 41`: the byte alone, not SetVisibility.
    for (i = next; i < count; i++)
        chunks[i]->Object.Visibility = FLAILER_OBJECT_INVISIBLE;
    return ee_trunc_w(last->Object.Y + h);
}

void (*gFlailerTextIntoRectangleFn)(struct FlailerTextChunk *t,
                                    const char *str, float tlx, float tly,
                                    float brx, float bry, float scale);

void flailer_render_text_into_rectangle(uint32_t screen, uint32_t text,
                                        uint32_t rect, const char *str,
                                        float scale)
{
    struct FlailerObjectChunk *r =
        flailer_find_object(screen, rect, FLAILER_TYPE_BITMAP);
    struct FlailerTextChunk *t = (struct FlailerTextChunk *)
        flailer_find_object(screen, text, FLAILER_TYPE_TEXT);
    float tlx, tly, brx, bry;

    if (r == NULL || t == NULL || str == NULL)
        return;
    tlx = r->X;
    tly = r->Y;
    brx = r->X + (float)flailerobject_get_width(r);
    bry = r->Y + (float)flailerobject_get_height(r);
    flailertext_set_string(t, str);
    if (gFlailerTextIntoRectangleFn != NULL)
        gFlailerTextIntoRectangleFn(t, str, tlx, tly, brx, bry, scale);
}
