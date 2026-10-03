// bprintf -- bSPrintf (0x00251398) and bVSPrintf (0x00251440) from retail,
// as far as the C library's printf differs from them. tools/bprintf_check.py
// holds the two side by side.
//
// They take printf's flags, width, precision and '*', and d i u x X o c s %
// print as the C library's do. The rest differ:
//
//   %f with no precision has 3 places, not 6: 12.3455 is "12.345"
//   the last place rounds half away from 0: %.1f of 0.25 is "0.3", of
//     -7.25 "-7.3", where the C library's "0.2" and "-7.2" go to even
//   the sign is for a value below 0 only: -0.0 is "0", but -0.4 at %.0f
//     is still "-0"
//   past about 1e23 retail's digits drift from the exact value (2^77 is
//     "151115727451828659421184", not "...646838272"); these print the
//     exact one, and nothing the game shows gets near
//   the size letters are h, l and L, and any h makes a short: %lhd of
//     70000 is "4464". The rest are 32 bits, as every integer on the EE
//   %p is eight hex digits, upper case, padded to the width
//   %n takes its pointer and writes nothing
//   a letter it does not know prints as itself and takes no argument:
//     %q%d of 1 is "q1", and so are %a %j %k %m %r and most capitals
//
// The rest are not ported, since nothing the port prints uses them. %e, %g
// and %F go to the C library as they are: retail has three exponent digits
// and three places, its %g is %e, and its %F prints nothing and then the
// next spec as text. %b %t %v %w %y %z %B %C %S %I and %N print as unknown
// letters here, but are bWare's own in retail -- fixed point, vectors
// ("bPrintf:invalid bVector" when the argument is not one), the vector
// printer's "[%*.*z,%*.*z]" at 0x002bf728.
//
// Like snprintf, these cut the result to `n` bytes and answer its whole
// length. Retail's have no bound.

#ifndef BPRINTF_H
#define BPRINTF_H

#include <stdarg.h>
#include <stddef.h>

int b_vsnprintf(char *out, size_t n, const char *fmt, va_list ap);
int b_snprintf(char *out, size_t n, const char *fmt, ...);

#endif
