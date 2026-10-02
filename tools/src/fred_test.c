// fred_test -- the port side of tools/fred_check.py.
//
// Reads the checker's script and runs it over the port's frontend database
// (fred.c), race parameters (raceparams.c), character data
// (characterinfo.c) and display offsets (edisplay.c), printing what each
// op leaves in the same lines the model prints from the retail image:
//
//   F b                 fill Fred, TheRaceParameters, DriverInfoTable, the
//                       scratch settings and the calibration's start with
//                       byte b, silently
//   SF / SR             _GLOBAL_$I$Fred / _GLOBAL_$I$TheRaceParameters
//   I / C / R / D / H   InitWithDefaults, MakeChallengeCarsAvailable,
//                       RaceParameters::InitWithDefaults, the display
//                       settings' on the scratch, InitStatsTables
//   G v                 Fred.GameType = v
//   A p st ty sk da     SetCarAvailability on player p
//   O p mo ty sk da     AssignCarOfType
//   T p ty sk da        SetDefaultCarType
//   c p i               SetCharacterInfo(int)
//   E x y               eSetScreenDisplayOffsets
//   K k hex / L k / U k a chunk into slot k, its loader, its unloader
//   KC hex / KT hex     the 64 car records; the track info chunk, loaded
//   cr ty off n v       a car record's n bytes at off
//   tr i off n v        track i's (from 1)
//   th n                HighestTrackNumber
//   qb / qc hex, qh h, qi i, qn
//                       the character data's five getters
//   v name val          a global; u a b c m the unlock rule; n id hex|-
//                       a translation; w s the audio stub's salt; o m x y
//                       ScreenDisplayOffsets[m]
//
// After every op but F the state that changed since it was last printed.

#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "cartypeinfo.h"
#include "characterinfo.h"
#include "configitems.h"
#include "edisplay.h"
#include "fred.h"
#include "playercam.h"
#include "playersettings.h"
#include "raceparams.h"
#include "realtime.h"
#include "track.h"

const int *gPlayerCamSkipFE;
RaceParameters TheRaceParameters;

#define SPAN      0x40000
#define NSLOTS    4
#define NREC_CARS 64
#define CAR_REC   1376
#define TRK_REC   164
#define RP_COMMON 772             // the bytes before pDriverInfoTable

static uint8_t chunkmem[NSLOTS][SPAN] __attribute__((aligned(16)));
static uint8_t cars[NREC_CARS * CAR_REC] __attribute__((aligned(16)));
static CarTypeInfo hostcars[NREC_CARS];
static uint8_t trackchunk[SPAN] __attribute__((aligned(16)));
static int32_t trackRecords;
static tGlobalDisplaySettings scratch;

static int skipfe;
static int32_t lang;
static int32_t unlockA, unlockB, unlockC, unlockM;
static int32_t audioSalt;

#define NNAMES 8
static struct { int32_t id; int set; char s[64]; } names[NNAMES];
static int nnames;

static int quiet;

static void emit(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void emit(const char *fmt, ...)
{
    va_list ap;

    if (quiet)
        return;
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    putchar('\n');
}

// ---------------------------------------------------------------- the seams

static int32_t currLanguage(void) { return lang; }

static int32_t isCarUnlocked(int32_t type, int32_t game)
{
    int32_t r = unlockM != 0
        && ((uint32_t)(type * unlockA + game * unlockB + unlockC)
            % (uint32_t)unlockM) == 0;

    emit("u %d %d -> %d", (int)type, (int)game, (int)r);
    return r;
}

static const char *translate(int32_t id)
{
    int i;

    emit("n %x", (unsigned)id);
    for (i = 0; i < nnames; i++)
        if (names[i].id == id)
            return names[i].set ? names[i].s : NULL;
    return NULL;
}

static void audioDefaults(uint8_t *ao)
{
    int i;

    emit("a +%d", (int)(ao - fred_bytes()));
    for (i = 0; i < 176; i++)
        ao[i] = (uint8_t)(i * 7 + audioSalt);
}

// ---------------------------------------------------------------- the prints

static const char *label(const void *p)
{
    static char buf[4][48];
    static int n;
    const uint8_t *a = (const uint8_t *)p;
    char *s = buf[n++ & 3];
    int k;

    if (p == NULL)
        return "NULL";
    if (p == (const void *)DriverInfoTable)
        return "DIT";
    for (k = 0; k < NSLOTS; k++)
        if (a >= chunkmem[k] && a < chunkmem[k] + SPAN) {
            snprintf(s, 48, "k%d+%d", k, (int)(a - chunkmem[k]));
            return s;
        }
    if (a >= (const uint8_t *)hostcars
        && a < (const uint8_t *)hostcars + sizeof hostcars) {
        snprintf(s, 48, "cars+%d", (int)(a - (const uint8_t *)hostcars));
        return s;
    }
    if (a >= trackchunk && a < trackchunk + SPAN) {
        snprintf(s, 48, "trk+%d", (int)(a - trackchunk));
        return s;
    }
    return "?";
}

static void hex(char *out, const uint8_t *p, int n)
{
    int i;

    for (i = 0; i < n; i++)
        sprintf(out + 2 * i, "%02x", p[i]);
    out[2 * n] = 0;
}

static uint8_t shownFred[sizeof(FrontendDatabase)];
static uint8_t shownRP[RP_COMMON];
static char    shownRPTail[128];
static char    shownDI[RACE_PARAMETERS_MAX_DRIVERS][128];
static uint8_t shownTrk[SPAN];
static char    shownG[256];
static uint8_t shownScratch[8];

static void print_rows(char tag, const uint8_t *cur, uint8_t *shown,
                       int size, int width)
{
    char h[2 * 64 + 1];
    int off;

    for (off = 0; off < size; off += 32) {
        int n = size - off < 32 ? size - off : 32;

        if (memcmp(cur + off, shown + off, n) == 0)
            continue;
        hex(h, cur + off, n);
        if (width == 5)
            emit("%c %05x %s", tag, off, h);
        else
            emit("%c %03x %s", tag, off, h);
        memcpy(shown + off, cur + off, n);
    }
}

static void print_state(void)
{
    const RaceParameters *rp = &TheRaceParameters;
    char s[256];
    int i;

    print_rows('f', fred_bytes(), shownFred, (int)sizeof(FrontendDatabase),
               5);
    print_rows('r', (const uint8_t *)rp, shownRP, RP_COMMON, 3);
    snprintf(s, sizeof s, "rp %s %d %08x %08x", label(rp->pDriverInfoTable),
             (int)rp->NumDriverInfo, (unsigned)rp->New780,
             (unsigned)rp->New784);
    if (strcmp(s, shownRPTail) != 0) {
        emit("%s", s);
        strcpy(shownRPTail, s);
    }
    for (i = 0; i < RACE_PARAMETERS_MAX_DRIVERS; i++) {
        const DriverInfo *d = &DriverInfoTable[i];
        char h[17];

        hex(h, (const uint8_t *)&d->CurrentRideInfo, 8);
        snprintf(s, sizeof s, "d %d %d %d %d %d %d %d %s %s", i,
                 d->EliminatedRank, d->UniqueDriverNumber,
                 d->CharacterNumber, d->SkillLevel, d->StartingPosition,
                 (int)d->TheDriverType, h, label(d->pCharacterInfo));
        if (strcmp(s, shownDI[i]) != 0) {
            emit("%s", s);
            strcpy(shownDI[i], s);
        }
    }
    for (i = 0; i < trackRecords; i++) {
        uint8_t *rec = trackchunk + 8 + TRK_REC * i;
        char h[2 * TRK_REC + 1];

        if (memcmp(rec, shownTrk + 8 + TRK_REC * i, TRK_REC) == 0)
            continue;
        hex(h, rec, TRK_REC);
        emit("t %d %s", i + 1, h);
        memcpy(shownTrk + 8 + TRK_REC * i, rec, TRK_REC);
    }
    snprintf(s, sizeof s,
             "g seed=%08x ox=%d oy=%d high=%d tab=%s ct=%s bt=%s nb=%d "
             "ci=%s nc=%d off=%d,%d,%d,%d",
             (unsigned)bDefaultSeed, (int)DisplayCalibrationOriginalX,
             (int)DisplayCalibrationOriginalY, (int)HighestTrackNumber,
             label(TrackInfoTable), label(CarTypeInfoArray),
             label(pBodyTypeInfo), (int)NumBodyTypeInfo,
             label(pCharacterInfo), (int)NumCharacterInfo,
             (int)ScreenDisplayOffsets[0][0], (int)ScreenDisplayOffsets[0][1],
             (int)ScreenDisplayOffsets[1][0], (int)ScreenDisplayOffsets[1][1]);
    if (strcmp(s, shownG) != 0) {
        emit("%s", s);
        strcpy(shownG, s);
    }
    if (memcmp(&scratch, shownScratch, 8) != 0) {
        char h[17];

        hex(h, (const uint8_t *)&scratch, 8);
        emit("s %s", h);
        memcpy(shownScratch, &scratch, 8);
    }
}

// ---------------------------------------------------------------- the ops

static int unhex(uint8_t *out, const char *h, int cap)
{
    int n = 0;

    while (h[0] && h[1] && n < cap) {
        unsigned v;

        sscanf(h, "%2x", &v);
        out[n++] = (uint8_t)v;
        h += 2;
    }
    return n;
}

static void put_le(uint8_t *p, int n, long v)
{
    int i;

    for (i = 0; i < n; i++)
        p[i] = (uint8_t)((unsigned long)v >> (8 * i));
}

// The records as the image lays them out, 1376 bytes each, into the
// port's: pCarSpecs is a host pointer, so the host record is wider and
// everything from it on is placed by field.
static void sync_cars(void)
{
    int t;

    for (t = 0; t < NREC_CARS; t++) {
        const uint8_t *r = cars + CAR_REC * t;

        memcpy(&hostcars[t], r, offsetof(CarTypeInfo, pCarSpecs));
        hostcars[t].pCarSpecs = NULL;
        memcpy(&hostcars[t].Pad1, r + 1372, 4);
    }
}

static FrontendPlayerInfo *fpi(int p)
{
    return &Fred.FrontendPlayers[p];
}

static int32_t *var(const char *name)
{
    static int32_t pov;

    if (!strcmp(name, "skipfe")) return (int32_t *)&skipfe;
    if (!strcmp(name, "e3")) return &bVersionE3;
    if (!strcmp(name, "rearview")) return &SkipFERearView;
    if (!strcmp(name, "speedo")) return &SkipFESpeedoMode;
    if (!strcmp(name, "jump")) return &SkipFEEnableJumpCam;
    if (!strcmp(name, "zone")) return &SkipFEEnableZoneCam;
    if (!strcmp(name, "dp1type")) return &DefaultPlayer1CarType;
    if (!strcmp(name, "dp2type")) return &DefaultPlayer2CarType;
    if (!strcmp(name, "dp1skin")) return &DefaultPlayer1SkinIndex;
    if (!strcmp(name, "dp2skin")) return &DefaultPlayer2SkinIndex;
    if (!strcmp(name, "lang")) return &lang;
    if (!strcmp(name, "video")) return &CurrentVideoMode;
    if (!strcmp(name, "seed")) return (int32_t *)&bDefaultSeed;
    if (!strcmp(name, "pov")) return &pov;
    fprintf(stderr, "no variable %s\n", name);
    exit(2);
}

static void op_fill(int b)
{
    uint32_t w = 0x01010101u * (uint32_t)b;

    memset(&Fred, b, sizeof Fred);
    memset(&TheRaceParameters, b, sizeof TheRaceParameters);
    memset(DriverInfoTable, b, sizeof DriverInfoTable);
    memset(&scratch, b, sizeof scratch);
    DisplayCalibrationOriginalX = (int32_t)w;
    DisplayCalibrationOriginalY = (int32_t)w;
    quiet = 1;
    print_state();
    quiet = 0;
}

static char line[1 << 21];
static char str[4096];

int main(int argc, char **argv)
{
    FILE *f;

    if (argc < 2 || !(f = fopen(argv[1], "r"))) {
        fprintf(stderr, "usage: fred_test script\n");
        return 2;
    }
    gPlayerCamSkipFE = &skipfe;
    gCurrLanguageFn = currLanguage;
    gIsCarUnlockedFn = isCarUnlocked;
    gFredTranslateFn = translate;
    gFredAudioOptionsDefaultsFn = audioDefaults;

    while (fgets(line, sizeof line, f)) {
        char op[8] = "";
        char a1[64] = "";
        int p = 0, q = 0, r = 0, s = 0, t = 0;
        long v = 0;
        char *rest;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        sscanf(line, "%7s", op);
        rest = line + strlen(op);
        while (*rest == ' ')
            rest++;
        if (!strcmp(op, "B")) {
            printf("%s\n", line);
            continue;
        }
        printf("> %.40s\n", line);
        if (!strcmp(op, "F")) {
            sscanf(rest, "%x", &p);
            op_fill(p);
            continue;
        } else if (!strcmp(op, "SF")) {
            fred_static_init();
        } else if (!strcmp(op, "SR")) {
            race_parameters_static_init();
        } else if (!strcmp(op, "I")) {
            init_fred();
        } else if (!strcmp(op, "C")) {
            fred_make_challenge_cars_available(&Fred);
        } else if (!strcmp(op, "R")) {
            race_parameters_init_with_defaults(&TheRaceParameters);
        } else if (!strcmp(op, "D")) {
            global_display_settings_init_with_defaults(&scratch);
        } else if (!strcmp(op, "H")) {
            high_score_table_init_stats_tables(&Fred.ChallengeHighScores);
        } else if (!strcmp(op, "G")) {
            sscanf(rest, "%d", &p);
            Fred.GameType = p;
        } else if (!strcmp(op, "A")) {
            sscanf(rest, "%d %d %d %d %d", &p, &q, &r, &s, &t);
            fpi_set_car_availability(fpi(p), q, r, s, t);
        } else if (!strcmp(op, "O")) {
            sscanf(rest, "%d %d %d %d %d", &p, &q, &r, &s, &t);
            fpi_assign_car_of_type(fpi(p), q, r, (uint32_t)s, t);
        } else if (!strcmp(op, "T")) {
            sscanf(rest, "%d %d %d %d", &p, &q, &r, &s);
            fpi_set_default_car_type(fpi(p), q, (uint32_t)r, s);
        } else if (!strcmp(op, "c")) {
            sscanf(rest, "%d %d", &p, &q);
            fpi_set_character_info_index(fpi(p), q);
        } else if (!strcmp(op, "E")) {
            sscanf(rest, "%d %d", &p, &q);
            eSetScreenDisplayOffsets(p, q);
        } else if (!strcmp(op, "K")) {
            int k;

            sscanf(rest, "%d", &k);
            memset(chunkmem[k], 0, SPAN);
            unhex(chunkmem[k], strchr(rest, ' ') + 1, SPAN);
            continue;
        } else if (!strcmp(op, "L") || !strcmp(op, "U")) {
            int ret;

            sscanf(rest, "%d", &p);
            ret = op[0] == 'L' ? loader_character_info(chunkmem[p])
                               : unloader_character_info(chunkmem[p]);
            emit("%s %d -> %d", op, p, ret);
        } else if (!strcmp(op, "KC")) {
            memset(cars, 0, sizeof cars);
            unhex(cars, rest, (int)sizeof cars);
            sync_cars();
            CarTypeInfoArray = hostcars;
        } else if (!strcmp(op, "KT")) {
            int n, ret;

            memset(trackchunk, 0, SPAN);
            n = unhex(trackchunk, rest, SPAN);
            trackRecords = (n - 8) / TRK_REC;
            memcpy(shownTrk, trackchunk, SPAN);
            ret = track_loader_geometry(trackchunk);
            emit("KT -> %d", ret);
        } else if (!strcmp(op, "cr")) {
            sscanf(rest, "%d %d %d %ld", &p, &q, &r, &v);
            put_le(cars + CAR_REC * p + q, r, v);
            sync_cars();
        } else if (!strcmp(op, "tr")) {
            sscanf(rest, "%d %d %d %ld", &p, &q, &r, &v);
            put_le(trackchunk + 8 + TRK_REC * (p - 1) + q, r, v);
        } else if (!strcmp(op, "th")) {
            sscanf(rest, "%d", &p);
            HighestTrackNumber = p;
        } else if (!strcmp(op, "qb") || !strcmp(op, "qc")) {
            memset(str, 0, sizeof str);
            unhex((uint8_t *)str, rest, (int)sizeof str - 1);
            emit("%s -> %s", op, op[1] == 'b'
                 ? label(get_body_type_info(str))
                 : label(get_character_info_by_name(str)));
        } else if (!strcmp(op, "qh")) {
            unsigned h;

            sscanf(rest, "%x", &h);
            emit("qh -> %s", label(get_character_info_from_name_hash(h)));
        } else if (!strcmp(op, "qi")) {
            sscanf(rest, "%d", &p);
            emit("qi -> %s", label(get_character_info(p)));
        } else if (!strcmp(op, "qn")) {
            emit("qn -> %d", (int)get_num_character_infos());
        } else if (!strcmp(op, "v")) {
            sscanf(rest, "%63s %li", a1, &v);
            *var(a1) = (int32_t)v;
            if (!strcmp(a1, "pov"))
                PlayerSkipFEPOVIndex = (uint8_t)v;
        } else if (!strcmp(op, "u")) {
            sscanf(rest, "%d %d %d %d", &unlockA, &unlockB, &unlockC,
                   &unlockM);
            continue;
        } else if (!strcmp(op, "n")) {
            unsigned id;
            char h[160] = "";

            sscanf(rest, "%x %159s", &id, h);
            names[nnames].id = (int32_t)id;
            names[nnames].set = strcmp(h, "-") != 0;
            memset(names[nnames].s, 0, sizeof names[nnames].s);
            if (names[nnames].set)
                unhex((uint8_t *)names[nnames].s, h, 63);
            nnames++;
            continue;
        } else if (!strcmp(op, "nr")) {
            nnames = 0;
            continue;
        } else if (!strcmp(op, "w")) {
            sscanf(rest, "%d", &audioSalt);
            continue;
        } else if (!strcmp(op, "o")) {
            sscanf(rest, "%d %d %d", &p, &q, &r);
            ScreenDisplayOffsets[p][0] = q;
            ScreenDisplayOffsets[p][1] = r;
        } else {
            fprintf(stderr, "bad op %s\n", line);
            return 2;
        }
        print_state();
    }
    return 0;
}
