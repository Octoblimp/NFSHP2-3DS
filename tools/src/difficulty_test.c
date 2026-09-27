// Host harness for tools/difficulty_check.py: runs difficultyinfo.c's
// loader and unloader over the scenario's chunks and prints the table
// field by field, and the layout the checker holds to retail's readers.
//
// Scenario lines:
//   C <k> <n> <hex>   chunk k, n bytes
//   Y                 the layout: each field's offset and size
//   P <k>             fill the table with pattern k
//   L <k>             loader_difficulty_info on chunk k
//   U <k>             unloader_difficulty_info on chunk k
//   D                 the table, field by field

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "difficultyinfo.h"

#define NCHUNKS 16

static uint8_t *chunks[NCHUNKS];
static char     line[8192];

static int hexval(int c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    return -1;
}

static int read_chunk(const char *s)
{
    int k, n, used, i;

    if (sscanf(s, "%d %d %n", &k, &n, &used) != 2 || k < 0 || k >= NCHUNKS
        || n <= 0)
        return 0;
    s += used;
    chunks[k] = malloc((size_t)n);
    if (chunks[k] == NULL)
        return 0;
    for (i = 0; i < n; i++) {
        int hi = hexval(s[2 * i]), lo = hexval(s[2 * i + 1]);

        if (hi < 0 || lo < 0)
            return 0;
        chunks[k][i] = (uint8_t)(hi << 4 | lo);
    }
    return 1;
}

static uint32_t word(const void *p)
{
    uint32_t w;

    memcpy(&w, p, 4);
    return w;
}

static void words(const char *name, const void *p, int n)
{
    const uint8_t *b = p;
    int i;

    printf("%s", name);
    for (i = 0; i < n; i++)
        printf(" %08x", (unsigned)word(b + 4 * i));
    printf("\n");
}

#define LAYOUT(name, type, field)                                        \
    printf("layout %s %u %u\n", name, (unsigned)offsetof(type, field),   \
           (unsigned)sizeof(((type *)0)->field))

static void layout(void)
{
    printf("layout DifficultyInfo 0 %u\n", (unsigned)sizeof(DifficultyInfo));
    LAYOUT("DifficultyInfo.AIDistanceBoostLoSkill", DifficultyInfo,
           AIDistanceBoostLoSkill);
    LAYOUT("DifficultyInfo.AIDistanceBoostHiSkill", DifficultyInfo,
           AIDistanceBoostHiSkill);
    LAYOUT("DifficultyInfo.AIPositionBoostLoSkill", DifficultyInfo,
           AIPositionBoostLoSkill);
    LAYOUT("DifficultyInfo.AIPositionBoostHiSkill", DifficultyInfo,
           AIPositionBoostHiSkill);
    LAYOUT("DifficultyInfo.PositionRatioOverOne", DifficultyInfo,
           PositionRatioOverOne);
    LAYOUT("DifficultyInfo.PositionRatioUnderOne", DifficultyInfo,
           PositionRatioUnderOne);
    LAYOUT("DifficultyInfo.AISkillLevel", DifficultyInfo, AISkillLevel);
    LAYOUT("DifficultyInfo.AINonExplicitMode", DifficultyInfo,
           AINonExplicitMode);
    LAYOUT("DifficultyInfo.TwoPlayerCatchup", DifficultyInfo,
           TwoPlayerCatchup);
    LAYOUT("DifficultyInfo.Misc", DifficultyInfo, Misc);
    printf("layout SkillLevelEntry 0 %u\n", (unsigned)sizeof(SkillLevelEntry));
    LAYOUT("SkillLevelEntry.TakeSignChance", SkillLevelEntry, TakeSignChance);
    LAYOUT("SkillLevelEntry.CollisionAvoidanceChance", SkillLevelEntry,
           CollisionAvoidanceChance);
    LAYOUT("SkillLevelEntry.SpeedFactor", SkillLevelEntry, SpeedFactor);
    LAYOUT("SkillLevelEntry.SlowFactor", SkillLevelEntry, SlowFactor);
    LAYOUT("SkillLevelEntry.RoutePointVariance", SkillLevelEntry,
           RoutePointVariance);
    LAYOUT("SkillLevelEntry.pad", SkillLevelEntry, pad);
    printf("layout NonExplicitModeData 0 %u\n",
           (unsigned)sizeof(NonExplicitModeData));
    LAYOUT("NonExplicitModeData.BoostScale", NonExplicitModeData, BoostScale);
    LAYOUT("NonExplicitModeData.SkillLevelDistribution", NonExplicitModeData,
           SkillLevelDistribution);
    printf("layout MiscData 0 %u\n", (unsigned)sizeof(MiscData));
    LAYOUT("MiscData.RoutePointChangeFrequency", MiscData,
           RoutePointChangeFrequency);
    LAYOUT("MiscData.BoostCalculationFrequency", MiscData,
           BoostCalculationFrequency);
    LAYOUT("MiscData.MaxDistanceForBoost", MiscData, MaxDistanceForBoost);
}

static void dump(void)
{
    const DifficultyInfo *d = &TheDifficultyInfo;
    char name[64];
    int i, c, s;

    words("AIDistanceBoostLoSkill", d->AIDistanceBoostLoSkill, 14);
    words("AIDistanceBoostHiSkill", d->AIDistanceBoostHiSkill, 14);
    words("AIPositionBoostLoSkill", d->AIPositionBoostLoSkill, 16);
    words("AIPositionBoostHiSkill", d->AIPositionBoostHiSkill, 16);
    words("PositionRatioOverOne", d->PositionRatioOverOne, 16);
    words("PositionRatioUnderOne", d->PositionRatioUnderOne, 16);
    for (i = 0; i < 10; i++) {
        const SkillLevelEntry *e = &d->AISkillLevel[i];

        printf("AISkillLevel[%d] %08x %08x %08x %08x %08x %08x %02x %02x "
               "%02x%02x\n", i, (unsigned)word(&e->TakeSignChance[0]),
               (unsigned)word(&e->TakeSignChance[1]),
               (unsigned)word(&e->TakeSignChance[2]),
               (unsigned)word(&e->CollisionAvoidanceChance),
               (unsigned)word(&e->SpeedFactor), (unsigned)word(&e->SlowFactor),
               e->RoutePointVariance, e->pad, e->_pad26[0], e->_pad26[1]);
    }
    for (i = 0; i < 3; i++) {
        snprintf(name, sizeof name, "BoostScale[%d]", i);
        words(name, d->AINonExplicitMode.BoostScale[i], 5);
    }
    for (c = 0; c < 2; c++)
        for (s = 0; s < 3; s++) {
            snprintf(name, sizeof name, "SkillLevelDistribution[%d][%d]", c, s);
            words(name, d->AINonExplicitMode.SkillLevelDistribution[c][s], 10);
        }
    words("TwoPlayerCatchup", d->TwoPlayerCatchup, 8);
    printf("Misc %08x %08x %08x\n",
           (unsigned)word(&d->Misc.RoutePointChangeFrequency),
           (unsigned)word(&d->Misc.BoostCalculationFrequency),
           (unsigned)word(&d->Misc.MaxDistanceForBoost));
}

static void fill(int k)
{
    uint8_t *p = (uint8_t *)&TheDifficultyInfo;
    size_t i;

    for (i = 0; i < sizeof TheDifficultyInfo; i++)
        p[i] = (uint8_t)(k * 37 + (int)i * 11 + 5);
}

int main(int argc, char **argv)
{
    FILE *f;
    int k;

    if (argc < 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: difficulty_test <scenarios>\n");
        return 2;
    }
    while (fgets(line, sizeof line, f) != NULL) {
        switch (line[0]) {
        case 'C':
            if (!read_chunk(line + 1))
                return 3;
            break;
        case 'Y':
            layout();
            break;
        case 'P':
            if (sscanf(line + 1, "%d", &k) != 1)
                return 3;
            fill(k);
            break;
        case 'L':
            if (sscanf(line + 1, "%d", &k) != 1 || k < 0 || k >= NCHUNKS
                || chunks[k] == NULL)
                return 3;
            printf("L %d -> %d\n", k, loader_difficulty_info(chunks[k]));
            break;
        case 'U':
            if (sscanf(line + 1, "%d", &k) != 1 || k < 0 || k >= NCHUNKS
                || chunks[k] == NULL)
                return 3;
            printf("U %d -> %d\n", k, unloader_difficulty_info(chunks[k]));
            break;
        case 'D':
            dump();
            break;
        default:
            break;
        }
    }
    fclose(f);
    return 0;
}
