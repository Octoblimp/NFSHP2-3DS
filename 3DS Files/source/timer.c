// timer -- see timer.h.

#include "timer.h"

#include <string.h>

#include "eefpu.h"

void timer_set_time(Timer *t, float seconds)
{
    t->PackedTime = (uint32_t)ee_trunc_w(seconds * 4000.0f + 0.5f);
}

float timer_round_seconds(const Timer *t, float f)
{
    float q = (float)(int32_t)t->PackedTime * 0.00025f / f;
    float fl = (float)ee_trunc_w(q);
    float x, c;

    if (q < fl)
        fl = fl - 1.0f;
    if (0.5f <= q - fl)
        fl = fl + 1.0f;
    x = fl * f * 4000.0f;
    c = (float)ee_trunc_w(x);
    if (c < x)
        c = c + 1.0f;
    return c * 0.00025f;
}

void timer_round(Timer *t, float f)
{
    t->PackedTime = (uint32_t)ee_trunc_w(timer_round_seconds(t, f) * 4000.0f
                                         + 0.5f);
}

void timer_get_hours_mins_seconds(const Timer *t, int32_t *h, int32_t *m,
                                  int32_t *s, int32_t *ms)
{
    int32_t v = (int32_t)t->PackedTime;
    int32_t sec = v / 4000;
    int32_t rest;

    *h = sec / 3600;
    rest = sec - *h * 3600;
    *m = rest / 60;
    *s = rest - *m * 60;
    *ms = (v - sec * 4000) / 4;
}

// IntToString2, 0x001a37b8: `width` digits ending at p[width - 1], the
// last first. Without `pad` a leading 0 is a space.
static void int_to_string2(char *p, int32_t val, int32_t width, int pad)
{
    char *q = p + width - 1;

    for (; width > 0; width--, q--) {
        int32_t r = val % 10;

        if (pad || r != 0 || val >= 10)
            *q = (char)('0' + r);
        else
            *q = ' ';
        val /= 10;
    }
}

// The jump tables at 0x002b5bb0, 0x002b5bd0, 0x002b5bf0 and 0x002b5c10:
// 0 English, 1 French, 2 German, 3 Italian, 4 Spanish, 5 Swedish. A
// language past 5 takes the first.
static const char *pick(int32_t language, const char *dot,
                        const char *colon, const char *quote)
{
    switch (language) {
    case 1: case 3: return quote;
    case 2: case 4: case 5: return colon;
    default: return dot;
    }
}

void timer_print_to_string_hms(char *buf, int32_t flags, int32_t h,
                               int32_t m, int32_t s, int32_t cs,
                               int32_t language)
{
    int32_t lead = -1;

    if (h != 0) {
        strcpy(buf, (language == 1 || language == 3) ? "--h:--'--\""
                                                     : "--h:--:--");
        int_to_string2(buf, h, 2, 0);
        int_to_string2(buf + 4, m, 2, 1);
        int_to_string2(buf + 7, s, 2, 1);
        lead = h;
    } else if (m != 0) {
        strcpy(buf, pick(language, "--:--.--", "--:--:--", "--'--\"--"));
        int_to_string2(buf, m, 2, 0);
        int_to_string2(buf + 3, s, 2, 1);
        int_to_string2(buf + 6, cs, 2, 1);
        lead = m;
    } else if (s != 0) {
        strcpy(buf, pick(language, "   --.--", "   --:--", "   --\"--"));
        int_to_string2(buf + 3, s, 2, 0);
        int_to_string2(buf + 6, cs, 2, 1);
    } else {
        strcpy(buf, pick(language, "    0.--", "    0:--", "    0\"--"));
        int_to_string2(buf + 6, cs, 2, 1);
    }
    if (lead >= 10 && (flags & 3) != 0) {
        size_t n = strlen(buf) - 1;
        char copy[16];

        memcpy(copy, buf, n);
        memcpy(buf + 1, copy, n);
    }
    if (flags & TIMER_PRINT_MINUS)
        buf[0] = '-';
    else if (flags & TIMER_PRINT_SIGN)
        buf[0] = '+';
}

void timer_print_to_string(const Timer *t, char *buf, int32_t flags,
                           int32_t language)
{
    int32_t h, m, s, ms;
    Timer abs_t;

    if (!timer_is_valid(t)) {
        timer_print_to_string_hms(buf, flags, 0, 0, 0, 0, language);
        return;
    }
    // Retail negates the stamp in place and back; the port works on a
    // copy.
    abs_t.PackedTime = (int32_t)t->PackedTime < 0 ? 0u - t->PackedTime
                                                  : t->PackedTime;
    timer_get_hours_mins_seconds(&abs_t, &h, &m, &s, &ms);
    if ((int32_t)t->PackedTime < 0)
        flags |= TIMER_PRINT_MINUS;
    timer_print_to_string_hms(buf, flags, h, m, s, ms / 10, language);
}
