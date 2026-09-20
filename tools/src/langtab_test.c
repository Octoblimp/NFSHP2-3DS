// Host harness for the 3DS language-table reader.
//
// Builds "3DS Files/source/langtab.c" for the host and prints one line per
// entry of the ID table:
//
//     <id> <TAB> <the string, hex-encoded>
//
// tools/langtab_check.py prints the same from tools/language_dump.py and
// diffs the two, so the binary search, the offsets and the unterminated
// last string are all checked against the Python reader rather than by eye.
//
// Usage: langtab_test <FE_LANGUAGE.BIN> [--english]

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "langtab.h"

static void print_hex(const char* s, size_t n)
{
    // Hex rather than text: the tables are latin-1 with control bytes used as
    // button glyphs, and a raw dump would turn the diff against the Python
    // reader into an encoding argument instead of a correctness check.
    static const char* digits = "0123456789abcdef";
    for (size_t i = 0; i < n; i++) {
        unsigned char c = (unsigned char)s[i];
        putchar(digits[c >> 4]);
        putchar(digits[c & 15]);
    }
}

int main(int argc, char** argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <FE_LANGUAGE.BIN> [--english]\n", argv[0]);
        return 2;
    }
    int english = (argc > 2 && !strcmp(argv[2], "--english"));

    FILE* f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 1; }
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t* buf = (uint8_t*)malloc((size_t)len);
    if (!buf || fread(buf, 1, (size_t)len, f) != (size_t)len) {
        fprintf(stderr, "read failed\n");
        return 1;
    }
    fclose(f);

    uint32_t       size    = 0;
    const uint8_t* payload = bchunk_find(buf, 0, (size_t)len, LANGTAB_CHUNK,
                                         &size);
    if (!payload) { fprintf(stderr, "no 0x%08x chunk\n", LANGTAB_CHUNK); return 1; }

    LangTable t;
    if (!langtab_parse(&t, payload, size)) {
        fprintf(stderr, "parse failed\n");
        return 1;
    }
    fprintf(stderr, "enum=%d hash=%u id=%u text=%u file='%s'\n",
            (int)t.languageEnum, t.numHash, t.numID, t.textSize, t.fileName);

    // Walk the raw table for keys, but fetch every string back through the
    // binary search -- that is the code path the game uses.
    const uint8_t* table = english ? t.hashTable : t.idTable;
    uint32_t       count = english ? t.numHash : t.numID;
    for (uint32_t i = 0; i < count; i++) {
        int32_t key = (int32_t)bchunk_u32(table + (size_t)i * 8);
        size_t      n = 0;
        const char* s = english ? langtab_get_english(&t, key, &n)
                                : langtab_get(&t, key, &n);
        if (!s) { printf("%d\t<MISSING>\n", (int)key); continue; }
        printf("%d\t", (int)key);
        print_hex(s, n);
        putchar('\n');
    }
    free(buf);
    return 0;
}
