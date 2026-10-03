// Host harness for tools/carinfo_check.py: runs carinfo.c's static
// constructor, loader, unloader, GetAccelerationTable and
// MakeAccelerationTable over the scenario's chunks, and prints what each
// leaves: the three globals, what bMalloc handed out and the tables that
// changed.
//
// Scenario lines:
//   B <n>                    scenario n
//   K <k> <mis> <r|p> <hex>  chunk k at a 16-byte boundary plus `mis`. A
//                            `p` chunk is its bytes as they are. An `r`
//                            chunk is a header and then 1376-byte records,
//                            which go to the first 16-byte boundary past
//                            the header plus 7, widened to the host's
//                            CarTypeInfo, as the console's loader finds them
//   C                        the static constructor
//   L <k>                    loader_car_info on chunk k
//   U <k>                    unloader_car_info on chunk k
//   M <k> <rec> <n>          make_acceleration_table over a Table of n
//                            entries and chunk k's record rec
//   G <type>                 get_acceleration_table
//   S <up|down|method> <hex> a drivetrain global, as its bits
//   F <hex>                  the model's stack fill: nothing here
//   P <hex>                  every table's entries, count, range and
//                            multiplier set to the word, but its pointer
//   I                        init_car_info, then each type's CarSpecs row
//   Q <type>                 find_car_language_info: the row and its words
//
// Every op is echoed as "> " and its first 40 characters. Floats print as
// their bits.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "carinfo.h"
#include "cartypeinfo.h"
#include "drivetrain.h"
#include "table.h"

#define NCHUNKS   16
#define REC_SIZE  1376          // the console's CarTypeInfo
#define MAX_MALLOC 256

typedef struct Chunk {
    uint8_t *mem;               // what malloc gave
    size_t   span;
    uint8_t *c;                 // the chunk's header
    uint8_t *rec;               // its records, for an `r` chunk
} Chunk;

static Chunk chunks[NCHUNKS];

// The world clock the drivetrain and the engine read; nothing here does.
int32_t WorldTimer = 0;
float   WorldTimeElapsed = 0.0f;

typedef struct Malloc {
    void       *p;
    int         size;
    const char *name;
    int         flags;
    int         pool;
} Malloc;

static Malloc mallocs[MAX_MALLOC];
static int    nmallocs;

static char *line;
static size_t line_cap;

static char shown[CARINFO_NUM_TYPES][512];

void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *p = calloc(1, (size_t)(size > 0 ? size : 1));

    if (nmallocs < MAX_MALLOC) {
        mallocs[nmallocs].p = p;
        mallocs[nmallocs].size = size;
        mallocs[nmallocs].name = name;
        mallocs[nmallocs].flags = flags;
        mallocs[nmallocs].pool = pool;
    }
    nmallocs++;
    return p;
}

static uint32_t bits(float f)
{
    uint32_t w;

    memcpy(&w, &f, 4);
    return w;
}

static float from_bits(uint32_t w)
{
    float f;

    memcpy(&f, &w, 4);
    return f;
}

static int hexval(int c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    return -1;
}

static int read_line(FILE *f)
{
    size_t n = 0;
    int c;

    while ((c = fgetc(f)) != EOF && c != '\n') {
        if (n + 2 > line_cap) {
            line_cap = line_cap ? 2 * line_cap : 4096;
            line = realloc(line, line_cap);
            if (line == NULL)
                exit(3);
        }
        line[n++] = (char)c;
    }
    if (c == EOF && n == 0)
        return 0;
    if (line == NULL) {
        line_cap = 16;
        line = malloc(line_cap);
    }
    line[n] = '\0';
    return 1;
}

static const char *label(const void *p)
{
    static char buf[64];
    int k;

    if (p == NULL)
        return "NULL";
    for (k = 0; k < NCHUNKS; k++) {
        const Chunk *ch = &chunks[k];

        if (ch->mem != NULL && (const uint8_t *)p >= ch->mem
            && (const uint8_t *)p < ch->mem + ch->span) {
            snprintf(buf, sizeof buf, "chunk%d%+d", k,
                     (int)((const uint8_t *)p - ch->c));
            return buf;
        }
    }
    return "?";
}

static void op_chunk(const char *s)
{
    int k, mis, used, i;
    char kind;
    size_t n, count, len;
    uint8_t *bytes;
    Chunk *ch;

    if (sscanf(s, "%d %d %c %n", &k, &mis, &kind, &used) != 3 || k < 0
        || k >= NCHUNKS)
        exit(4);
    s += used;
    len = strlen(s) / 2;
    bytes = malloc(len ? len : 1);
    for (n = 0; n < len; n++) {
        int hi = hexval(s[2 * n]), lo = hexval(s[2 * n + 1]);

        if (hi < 0 || lo < 0)
            exit(5);
        bytes[n] = (uint8_t)(hi << 4 | lo);
    }
    ch = &chunks[k];
    free(ch->mem);
    count = kind == 'r' ? (len - 8) / REC_SIZE : 0;
    ch->span = 64 + len + count * (sizeof(CarTypeInfo) - REC_SIZE) + 64;
    ch->mem = calloc(1, ch->span);
    ch->c = (uint8_t *)(((uintptr_t)ch->mem + 15) & ~(uintptr_t)15) + mis;
    if (kind == 'r') {
        memcpy(ch->c, bytes, 8);
        ch->rec = (uint8_t *)(((uintptr_t)ch->c + 23) & ~(uintptr_t)15);
        for (i = 0; i < (int)count; i++) {
            const uint8_t *src = bytes + 8 + (size_t)i * REC_SIZE;
            CarTypeInfo *dst = (CarTypeInfo *)(void *)ch->rec + i;

            memcpy(dst, src, offsetof(CarTypeInfo, pCarSpecs));
            dst->pCarSpecs = NULL;
            memcpy(&dst->Pad1, src + REC_SIZE - 4, 4);
        }
    } else {
        memcpy(ch->c, bytes, len);
        ch->rec = NULL;
    }
    free(bytes);
}

static void print_mallocs(void)
{
    int i, j, n;

    for (i = 0; i < nmallocs && i < MAX_MALLOC; i++) {
        const Malloc *m = &mallocs[i];
        const uint32_t *w = m->p;

        n = 0;
        for (j = 0; j < m->size / 4; j++)
            if (w[j] != 0)
                n = j + 1;
        printf("m %d %s %d %d %d:", m->size, m->name, m->flags, m->pool, n);
        for (j = 0; j < n; j++)
            printf(" %08x", (unsigned)w[j]);
        printf("\n");
        free(m->p);
    }
    if (nmallocs > MAX_MALLOC)
        printf("m %d more\n", nmallocs - MAX_MALLOC);
    nmallocs = 0;
}

static void print_tables(void)
{
    char buf[512];
    int i, j, o;

    for (i = 0; i < CARINFO_NUM_TYPES; i++) {
        const AccelerationTable *a = &TheCarTypeAccelerationTable[i];
        const Table *t = &a->mTable;

        o = 0;
        for (j = 0; j < 32; j++)
            o += snprintf(buf + o, sizeof buf - (size_t)o, " %08x",
                          (unsigned)bits(a->Data[j]));
        snprintf(buf + o, sizeof buf - (size_t)o, " %s %d %08x %08x %08x",
                 t->pTable == a->Data ? "own" : label(t->pTable),
                 (int)t->NumEntries, (unsigned)bits(t->MinArg),
                 (unsigned)bits(t->MaxArg), (unsigned)bits(t->IndexMultiplier));
        if (strcmp(buf, shown[i]) != 0) {
            printf("T %d%s\n", i, buf);
            strcpy(shown[i], buf);
        }
    }
}

static void print_globals(const char *op, int k, int ret)
{
    printf("%s %d -> %d array=%s", op, k, ret, label(CarTypeInfoArray));
    printf(" skins=%s n=%d\n", label(SkinInfoTable), (int)NumSkinInfo);
}

static void op_make(int k, int rec, int n)
{
    float buf[64];
    Table t;
    int i;

    for (i = 0; i < 64; i++)
        buf[i] = 7.0f;
    t.pTable = buf;
    t.NumEntries = n;
    t.MinArg = 1.0f;
    t.MaxArg = 2.0f;
    t.IndexMultiplier = 3.0f;
    make_acceleration_table(&t, (const CarTypeInfo *)(void *)chunks[k].rec
                                    + rec);
    print_mallocs();
    printf("t %s %d %08x %08x %08x:", t.pTable == buf ? "own" : "other",
           (int)t.NumEntries, (unsigned)bits(t.MinArg),
           (unsigned)bits(t.MaxArg), (unsigned)bits(t.IndexMultiplier));
    for (i = 0; i < n && i < 64; i++)
        printf(" %08x", (unsigned)bits(buf[i]));
    printf("\n");
}

int main(int argc, char **argv)
{
    FILE *f;

    if (argc != 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: carinfo_test <scenarios>\n");
        return 2;
    }
    while (read_line(f)) {
        int k, a, b;
        char name[16];
        unsigned w;

        if (line[0] == 'B') {
            printf("%s\n", line);
            continue;
        }
        printf("> %.40s\n", line);
        switch (line[0]) {
        case 'K':
            op_chunk(line + 2);
            break;
        case 'C':
            carinfo_static_init();
            print_mallocs();
            print_tables();
            break;
        case 'L':
            sscanf(line + 2, "%d", &k);
            a = loader_car_info(chunks[k].c);
            print_globals("L", k, a);
            print_mallocs();
            print_tables();
            break;
        case 'U':
            sscanf(line + 2, "%d", &k);
            a = unloader_car_info(chunks[k].c);
            print_globals("U", k, a);
            print_mallocs();
            print_tables();
            break;
        case 'M':
            sscanf(line + 2, "%d %d %d", &k, &a, &b);
            op_make(k, a, b);
            break;
        case 'G': {
            const Table *t;
            ptrdiff_t d;

            sscanf(line + 2, "%d", &k);
            t = get_acceleration_table(k);
            d = (const char *)t
              - (const char *)&TheCarTypeAccelerationTable[0].mTable;
            printf("G %d = %d r%d\n", k,
                   (int)(d / (ptrdiff_t)sizeof(AccelerationTable)),
                   (int)(d % (ptrdiff_t)sizeof(AccelerationTable)));
            break;
        }
        case 'S':
            sscanf(line + 2, "%15s %x", name, &w);
            if (strcmp(name, "up") == 0)
                gShiftUpDetune = from_bits(w);
            else if (strcmp(name, "down") == 0)
                gShiftDownDetune = from_bits(w);
            else if (strcmp(name, "method") == 0)
                gGearShiftMethod = (int32_t)w;
            else
                return 6;
            break;
        case 'F':
            break;
        case 'I': {
            int i;

            init_car_info();
            for (i = 0; i < CARINFO_NUM_TYPES; i++)
                printf("i %d %d\n", i,
                       (int)(CarTypeInfoArray[i].pCarSpecs
                             - CarLanguageInfoTable));
            break;
        }
        case 'Q': {
            const CarSpecs *c;

            sscanf(line + 2, "%d", &k);
            c = find_car_language_info(k);
            printf("q %d = %d: %d %d %d %d %d %d %d\n", k,
                   (int)(c - CarLanguageInfoTable), (int)c->CarType,
                   (int)c->ZeroTo60, (int)c->TopSpeedMph,
                   (int)c->TopSpeedKph, (int)c->BHP, (int)c->FullName,
                   (int)c->ShortName);
            break;
        }
        case 'P': {
            int i, j;

            sscanf(line + 2, "%x", &w);
            for (i = 0; i < CARINFO_NUM_TYPES; i++) {
                AccelerationTable *t = &TheCarTypeAccelerationTable[i];

                for (j = 0; j < 32; j++)
                    t->Data[j] = from_bits(w);
                memcpy(&t->mTable.NumEntries, &w, 4);
                t->mTable.MinArg = from_bits(w);
                t->mTable.MaxArg = from_bits(w);
                t->mTable.IndexMultiplier = from_bits(w);
            }
            print_tables();
            break;
        }
        default:
            fprintf(stderr, "bad op %s\n", line);
            return 7;
        }
    }
    fclose(f);
    return 0;
}
