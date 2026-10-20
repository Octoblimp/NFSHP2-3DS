// Harness for tools/eastereggs_check.py: runs the checker's script on the
// port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out.
//
//     eastereggs_test script.txt > out.txt

#include <inttypes.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "eastereggs.h"

#define NOBJ  2
#define NCUST 16

static EasterEggs    objs[NOBJ];
static EasterEggCode cust[NCUST];

static const char *label(const void *a)
{
    static char buf[4][32];
    static int  k;
    char       *b = buf[k++ & 3];
    int         i;

    if (a == NULL)
        return "null";
    for (i = 0; i < NOBJ; i++)
        if (a == (const void *)&objs[i]) {
            snprintf(b, 32, "e%d", i);
            return b;
        }
    if (a == (const void *)TheEasterEggCodes)
        return "tab";
    if (a == (const void *)cust)
        return "cust";
    return "?";
}

// joyevent.c's two, logged; the model's stubs of retail's print the same.
void AddJoyHandler(JoystickPort port, JoyEvent ev, JoyHandler fn, void *obj)
{
    printf("  add %d %d %s %s\n", (int)port, (int)ev,
           fn == eastereggs_joy_handler ? "handler" : "?", label(obj));
}

void RemoveJoyHandler(JoystickPort port, JoyEvent ev)
{
    printf("  remove %d %d\n", (int)port, (int)ev);
}

static EasterEggCode *table(int t)
{
    return t ? cust : TheEasterEggCodes;
}

static void dump(int k)
{
    const EasterEggs *e = &objs[k];
    int               i;

    printf("e%d act %" PRId32 " just %" PRId32 " lang %" PRId32
           " codes %s n %" PRIu32 " count %" PRIu32 " head %" PRIu32
           " vptr %08" PRIx32 " ring", k, e->Active, e->JustEntered,
           e->LanguageID, label(e->Codes), e->NumCodes, e->Count, e->Head,
           e->vptr);
    for (i = 0; i < EASTEREGGS_CODE_LENGTH; i++)
        printf(" %" PRId32, e->Ring[i]);
    printf("\n");
}

static void dump_on(int t, int n)
{
    const EasterEggCode *c = table(t);
    int                  i;

    printf("on %s ", t ? "cust" : "tab");
    for (i = 0; i < n; i++)
        printf("%" PRId32 "%s", c[i].On, i + 1 < n ? "," : "");
    printf("\n");
}

static void dump_codes(int t, int n)
{
    const EasterEggCode *c = table(t);
    int                  i, j;

    for (i = 0; i < n; i++) {
        printf("code %s %d", t ? "cust" : "tab", i);
        for (j = 0; j < EASTEREGGS_CODE_LENGTH; j++)
            printf(" %" PRId32, c[i].Buttons[j]);
        printf(" | %" PRId32 " %" PRId32 " %" PRId32 " %" PRId32 " %" PRId32
               " %" PRId32 "\n", c[i].Type, c[i].Param, c[i].Group,
               c[i].LanguageID, c[i].On, c[i].Kept);
    }
}

static void poke(int k, int field, int64_t v)
{
    EasterEggs *e = &objs[k];
    uint32_t    u = (uint32_t)v;

    switch (field) {
    case 0: e->Active = (int32_t)u; break;
    case 1: e->JustEntered = (int32_t)u; break;
    case 2: e->LanguageID = (int32_t)u; break;
    case 3: e->Codes = v == 0 ? TheEasterEggCodes : v == 1 ? cust : NULL;
            break;
    case 4: e->NumCodes = u; break;
    case 13: e->Count = u; break;
    case 14: e->Head = u; break;
    case 15: e->vptr = u; break;
    default:
        if (field >= 5 && field < 13) {
            e->Ring[field - 5] = (int32_t)u;
            break;
        }
        fprintf(stderr, "bad field %d\n", field);
        exit(2);
    }
}

static void cpoke(int t, int i, int field, int64_t v)
{
    EasterEggCode *c = &table(t)[i];
    int32_t        s = (int32_t)(uint32_t)v;

    if (field < EASTEREGGS_CODE_LENGTH) {
        c->Buttons[field] = s;
        return;
    }
    switch (field) {
    case 8: c->Type = s; break;
    case 9: c->Param = s; break;
    case 10: c->Group = s; break;
    case 11: c->LanguageID = s; break;
    case 12: c->On = s; break;
    case 13: c->Kept = s; break;
    default:
        fprintf(stderr, "bad code field %d\n", field);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    FILE   *f;
    char    line[512];
    int64_t a[8];

    if (argc < 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: eastereggs_test script.txt\n");
        return 2;
    }
    while (fgets(line, sizeof line, f)) {
        char *tok = strtok(line, " \r\n");
        char *op;
        int   n = 0;

        if (tok == NULL)
            continue;
        op = tok;
        if (strcmp(op, "T") == 0) {
            tok = strtok(NULL, "\r\n");
            printf("[%s]\n", tok ? tok : "");
            continue;
        }
        while ((tok = strtok(NULL, " \r\n")) != NULL && n < 8)
            a[n++] = strtoll(tok, NULL, 0);
        fflush(stdout);
        if (strcmp(op, "N") == 0) {
            EasterEggs *r = eastereggs_construct(&objs[a[0]]);
            printf("ctor e%d -> %s\n", (int)a[0], label(r));
        } else if (strcmp(op, "S") == 0) {
            printf("start e%d\n", (int)a[0]);
            eastereggs_start(&objs[a[0]]);
        } else if (strcmp(op, "X") == 0) {
            printf("stop e%d\n", (int)a[0]);
            eastereggs_stop(&objs[a[0]]);
        } else if (strcmp(op, "B") == 0) {
            printf("press e%d %d %d %d\n", (int)a[0], (int)a[1], (int)a[2],
                   (int)a[3]);
            eastereggs_joy_handler((JoystickPort)a[1], (JoyEvent)a[2],
                                   (uint8_t)a[3], &objs[a[0]]);
        } else if (strcmp(op, "R") == 0) {
            printf("reset e%d\n", (int)a[0]);
            eastereggs_reset(&objs[a[0]]);
        } else if (strcmp(op, "D") == 0) {
            dump((int)a[0]);
        } else if (strcmp(op, "O") == 0) {
            dump_on((int)a[0], (int)a[1]);
        } else if (strcmp(op, "F") == 0) {
            dump_codes((int)a[0], (int)a[1]);
        } else if (strcmp(op, "P") == 0) {
            poke((int)a[0], (int)a[1], a[2]);
        } else if (strcmp(op, "C") == 0) {
            cpoke((int)a[0], (int)a[1], (int)a[2], a[3]);
        } else if (strcmp(op, "CT") == 0) {
            printf("clear temporary e%d\n", (int)a[0]);
            eastereggs_clear_temporary(&objs[a[0]]);
        } else if (strcmp(op, "CG") == 0) {
            printf("clear group e%d %d\n", (int)a[0], (int)a[1]);
            eastereggs_clear_group(&objs[a[0]], (int32_t)a[1]);
        } else if (strcmp(op, "I") == 0) {
            printf("is_on e%d %d %d -> %d\n", (int)a[0], (int)a[1],
                   (int)a[2], (int)eastereggs_is_on(&objs[a[0]],
                                                    (int32_t)a[1],
                                                    (int32_t)a[2]));
        } else if (strcmp(op, "CA") == 0) {
            printf("car e%d %d %d -> %d\n", (int)a[0], (int)a[1], (int)a[2],
                   (int)eastereggs_car_on(&objs[a[0]], (int32_t)a[1],
                                          (int32_t)a[2]));
        } else if (strcmp(op, "TR") == 0) {
            printf("track e%d %d %d -> %d\n", (int)a[0], (int)a[1],
                   (int)a[2], (int)eastereggs_track_on(&objs[a[0]],
                                                       (int32_t)a[1],
                                                       (int32_t)a[2]));
        } else if (strcmp(op, "E") == 0) {
            printf("egg e%d %d -> %d\n", (int)a[0], (int)a[1],
                   (int)eastereggs_egg_on(&objs[a[0]], (int32_t)a[1]));
        } else if (strcmp(op, "TK") == 0) {
            printf("take e%d -> %d\n", (int)a[0],
                   (int)eastereggs_take_language_id(&objs[a[0]]));
        } else if (strcmp(op, "JE") == 0) {
            printf("just e%d -> %d\n", (int)a[0],
                   (int)eastereggs_just_entered(&objs[a[0]]));
        } else if (strcmp(op, "IA") == 0) {
            printf("active e%d -> %d\n", (int)a[0],
                   (int)eastereggs_is_active(&objs[a[0]]));
        } else if (strcmp(op, "EN") == 0) {
            printf("enable e%d\n", (int)a[0]);
            eastereggs_enable(&objs[a[0]]);
        } else if (strcmp(op, "DI") == 0) {
            printf("disable e%d\n", (int)a[0]);
            eastereggs_disable(&objs[a[0]]);
        } else {
            fprintf(stderr, "bad op %s\n", op);
            return 2;
        }
    }
    fclose(f);
    return 0;
}
