// bprintf -- see bprintf.h.

#include "bprintf.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

// %f's value, rounded as bVSPrintf rounds it to `prec` places, so that
// the C library's correct rounding then finds no tie. A float's value
// times 10^prec is exact in a double for any precision the game uses.
static double round_half_away(double v, int prec)
{
    double p10 = 1.0;
    double m = fabs(v);
    double r;
    int i;

    if (prec > 15)
        return v;
    for (i = 0; i < prec; i++)
        p10 *= 10.0;
    if (m * p10 >= 4503599627370496.0)      // 2^52: no fraction left
        return v;
    r = floor(m * p10 + 0.5) / p10;
    return v < 0.0 ? -r : r;
}

// Appends `k` bytes of `s` to the text, keeping count of the whole.
static void put(char *out, size_t n, size_t *len, int k, const char *s)
{
    if (k <= 0)
        return;
    if (*len < n) {
        size_t room = n - *len;
        size_t c = (size_t)k < room ? (size_t)k : room - 1;
        memcpy(out + *len, s, c);
        out[*len + c] = '\0';
    }
    *len += (size_t)k;
}

// One conversion through the C library, straight into what is left of
// `out`, with the '*' arguments in front. snprintf cuts it and counts it.
#define ONE(v) (star_w && star_p ? snprintf(dst, room, spec, w, pr, v) \
                : star_w ? snprintf(dst, room, spec, w, v)               \
                : star_p ? snprintf(dst, room, spec, pr, v)              \
                : snprintf(dst, room, spec, v))

int b_vsnprintf(char *out, size_t n, const char *fmt, va_list ap)
{
    size_t len = 0;
    char spec[40];

    if (n > 0)
        out[0] = '\0';
    while (*fmt) {
        const char *start = fmt;
        const char *wend;       // past the flags and the width
        size_t k;
        int prec = -1;
        int star_w = 0, star_p = 0, w = 0, pr = 0;
        int h = 0;
        char conv;
        char *dst;
        size_t room;
        int got;

        if (*fmt != '%') {
            while (*fmt && *fmt != '%')
                fmt++;
            put(out, n, &len, (int)(fmt - start), start);
            continue;
        }
        fmt++;
        while (*fmt && strchr("-+ #0", *fmt))
            fmt++;
        if (*fmt == '*') {
            star_w = 1;
            fmt++;
        } else {
            while (*fmt >= '0' && *fmt <= '9')
                fmt++;
        }
        wend = fmt;
        if (*fmt == '.') {
            fmt++;
            prec = 0;
            if (*fmt == '*') {
                star_p = 1;
                fmt++;
            } else {
                while (*fmt >= '0' && *fmt <= '9')
                    prec = prec * 10 + (*fmt++ - '0');
            }
        }
        // The size letters: any 'h' makes a short, and the rest change
        // nothing -- every integer is 32 bits on the EE, an int here.
        k = (size_t)(fmt - start);
        while (*fmt == 'h' || *fmt == 'l' || *fmt == 'L')
            h |= *fmt++ == 'h';
        conv = *fmt;
        if (conv == '\0')
            break;
        fmt++;
        if (k >= sizeof spec - 5) {
            put(out, n, &len, (int)(fmt - start), start);
            continue;
        }
        memcpy(spec, start, k);
        if (star_w)
            w = va_arg(ap, int);
        if (star_p) {
            pr = va_arg(ap, int);
            prec = pr < 0 ? -1 : pr;
        }
        dst = len < n ? out + len : NULL;
        room = len < n ? n - len : 0;

        switch (conv) {
        case 'f': {
            double v = va_arg(ap, double);

            if (prec < 0) {
                // No precision, or a '*' one below 0: three places.
                if (star_p) {
                    pr = 3;
                } else {
                    spec[k++] = '.';
                    spec[k++] = '3';
                }
                prec = 3;
            }
            spec[k++] = 'f';
            spec[k] = '\0';
            v = round_half_away(v, prec);
            got = ONE(v);
            break;
        }
        case 'e':
        case 'E':
        case 'g':
        case 'G':
        case 'F': {
            double v = va_arg(ap, double);

            spec[k++] = conv;
            spec[k] = '\0';
            got = ONE(v);
            break;
        }
        case 's': {
            const char *s = va_arg(ap, const char *);

            spec[k++] = 's';
            spec[k] = '\0';
            got = ONE(s);
            break;
        }
        case 'c':
        case 'd':
        case 'i':
        case 'u':
        case 'x':
        case 'X':
        case 'o': {
            int v = va_arg(ap, int);

            if (h && conv != 'c')
                spec[k++] = 'h';
            spec[k++] = conv;
            spec[k] = '\0';
            got = ONE(v);
            break;
        }
        case 'p': {
            // Eight hex digits, upper case, padded to the width.
            unsigned v = (unsigned)(uintptr_t)va_arg(ap, void *);

            k = (size_t)(wend - start);
            memcpy(spec + k, ".8X", 4);
            star_p = 0;
            got = ONE(v);
            break;
        }
        case 'n':
            (void)va_arg(ap, void *);
            got = 0;
            break;
        default:
            // '%', and a letter it does not know, print as themselves and
            // take no argument.
            put(out, n, &len, 1, &conv);
            got = 0;
            break;
        }
        if (got > 0)
            len += (size_t)got;
    }
    return (int)len;
}

int b_snprintf(char *out, size_t n, const char *fmt, ...)
{
    va_list ap;
    int r;

    va_start(ap, fmt);
    r = b_vsnprintf(out, n, fmt, ap);
    va_end(ap);
    return r;
}
