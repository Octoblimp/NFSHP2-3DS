// Drives replay.c's ReplaySnapshot and brepeat.c's bRepeat for
// tools/replay_check.py. A script of ops, one per line, fields split on
// '|'; every number is decimal or 0x hex, taken mod 2^32:
//
//   timer|WT|LC        WorldTimer and WorldLoopCounter
//   init|NAME          ReplaySnapshot::Init        rename|NAME  ChangeName
//   flags|T|R|C|V      the four mode flags (bytes 60 .. 63)
//   set|FIELD|N        t, et, blt, elt, mil, depth, ovf, secnum, pd, plc,
//                      pos, size, tiv
//   val|HEX            the 64-byte value buffer: these bytes, then zeros
//   mv|ST|SZ|SG        MoveData(value, ST, SZ, SG), then the buffer and
//                      the breaks so far
//   vd|ST|SZ|SG        VerifyData, likewise
//   wd|ST|SZ|SG        WriteData; rd likewise, ReadData
//   ck|N               GetChecksum over N bytes of the buffer
//   ov|KIND|N          one of the inline overloads (see overload())
//   begin|OBJ|NAME     BeginSection; bnamed|NAME, end, bend
//   dump               the snapshot
//
//   rprep|SIZE|N|COD   bRepeat::PrepareToAddData   rchan|C|RS|DEF InitChannel
//   radd|V|BITS|C      AddData; raddnull|V|BITS|C, with no bRepeat
//   rrem|BITS|C        RemoveData                  rpr  PrepareToRemoveData
//   rshovel            ShovelDataOffToCodeine
//   rw|LOC|V|BITS      WriteToLocation             rr|LOC|BITS  ReadFrom..
//   rset|OFF|N         a word of the buffer        rsnap|ADD  DoSnapshot
//   rdump              the bRepeat
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "brepeat.h"
#include "p32.h"
#include "replay.h"

int32_t WorldTimer;
int32_t WorldLoopCounter;

#define RBUF 4096
#define RFILL 0xa5
#define MAX_NAMES 64

static ReplaySnapshot S;
static uint64_t rstore[RBUF / 8];
static uint8_t *const Rb = (uint8_t *)rstore;
#define R ((bRepeat *)Rb)
static uint8_t V[64];
static char *names[MAX_NAMES];
static int num_names;

static int32_t num(const char *s)
{
    return (int32_t)(uint32_t)strtoll(s, NULL, 0);
}

static const char *intern(const char *s)
{
    int i;

    for (i = 0; i < num_names; i++)
        if (strcmp(names[i], s) == 0)
            return names[i];
    if (num_names == MAX_NAMES) {
        fprintf(stderr, "too many names\n");
        exit(2);
    }
    names[num_names] = malloc(strlen(s) + 1);
    strcpy(names[num_names], s);
    return names[num_names++];
}

static uint32_t fnv(const uint8_t *p, size_t n)
{
    uint32_t h = 0x811c9dc5u;
    size_t i;

    for (i = 0; i < n; i++)
        h = (h ^ p[i]) * 0x01000193u;
    return h;
}

static void hex(const uint8_t *p, int n)
{
    int i;

    for (i = 0; i < n; i++)
        printf("%02x", p[i]);
}

static void print_value(void)
{
    printf("v ");
    hex(V, 16);
    printf(" b=%d\n", replay_breaks);
}

static void dump(void)
{
    uint32_t tiv;
    int i;

    memcpy(&tiv, &S.TotalInterestingValue, 4);
    printf("snap name=%.32s t=%d et=%d blt=%d elt=%d mil=%d "
           "flags=%d,%d,%d,%d depth=%d ovf=%d secnum=%u pd=%d plc=%d "
           "tiv=%08x pos=%d size=%d breaks=%d\n",
           S.Name, S.Time, S.EndTime, S.BeginLoopTime, S.EndLoopTime,
           S.MemoryImageLoadedFlag, S.TakingSnapshotFlag,
           S.RestoringSnapshotFlag, S.TakingChecksumFlag,
           S.VerifyingChecksumFlag, S.CurrentSectionDepth, S.OverflowedFlag,
           S.CurrentSectionNumber, S.PrintDepth, S.PrintLoopCounter, tiv,
           S.DataPosition, S.SizeofData, replay_breaks);
    for (i = 0; i < REPLAY_SNAPSHOT_SECTIONS; i++) {
        const ReplaySectionInfo *si = &S.SectionInfo[i];
        const char *nm = p32_ptr(si->Name);

        printf("sec %d name=%s obj=%08x num=%u nmd=%u err=%d size=%d\n", i,
               nm ? nm : "-", (uint32_t)(uintptr_t)p32_ptr(si->Object),
               si->Number, si->NumMoveData, si->ChecksumErrorDetected,
               si->Size);
    }
    printf("data %08x ", fnv(S.Data, sizeof S.Data));
    hex(S.Data, 48);
    printf("\n");
}

static void rdump(void)
{
    int32_t n = R->NumChannels;
    int32_t at = R->HeaderSize;
    int32_t c;

    printf("rep magic=%08x cnu=%d add=%d hdr=%d rem=%d bufsz=%d nch=%d "
           "codeine=%d nadd=%d nrem=%d err=%d rt=%d\n",
           (uint32_t)R->Magic, R->CodeineNeedsUpdating, R->AddLocation,
           R->HeaderSize, R->RemoveLocation, R->AddBufferSize,
           R->NumChannels, R->EnableCodeineCapturing, R->NumItemsAdded,
           R->NumItemsRemoved, R->RemoveDataError, R->RecordingTime);
    for (c = 0; c < n && c < 8; c++) {
        const bRepeatChannel *ch = &R->Channel[c];

        printf("ch %d rs=%d def=%d ads=%d arc=%d al=%d ad=%d rrc=%d rl=%d "
               "rd=%d\n", c, ch->RepeatSize, ch->DefaultRemoveData,
               ch->AddDataSize, ch->AddRepeatCount, ch->AddLocation,
               ch->AddData, ch->RemoveRepeatCount, ch->RemoveLocation,
               ch->RemoveData);
    }
    if (at < 0 || at > RBUF - 40)
        at = 0;
    printf("rbuf %08x ", fnv(Rb, RBUF));
    hex(Rb + at, 40);
    printf("\n");
}

static void overload(const char *kind, int32_t n)
{
    void *p = V;

    if (!strcmp(kind, "f"))
        ReplaySnapshot_MoveFloat(&S, p);
    else if (!strcmp(kind, "timer"))
        ReplaySnapshot_MoveTimer(&S, p);
    else if (!strcmp(kind, "v2"))
        ReplaySnapshot_MoveVector2(&S, p);
    else if (!strcmp(kind, "v3"))
        ReplaySnapshot_MoveVector3(&S, p);
    else if (!strcmp(kind, "i"))
        ReplaySnapshot_MoveInt(&S, p, n);
    else if (!strcmp(kind, "u"))
        ReplaySnapshot_MoveUInt(&S, p, n);
    else if (!strcmp(kind, "s"))
        ReplaySnapshot_MoveShort(&S, p, n);
    else if (!strcmp(kind, "us"))
        ReplaySnapshot_MoveUShort(&S, p, n);
    else if (!strcmp(kind, "c") || !strcmp(kind, "sc"))
        ReplaySnapshot_MoveChar(&S, p, n);
    else if (!strcmp(kind, "uc"))
        ReplaySnapshot_MoveUChar(&S, p, n);
    else if (!strcmp(kind, "b"))
        ReplaySnapshot_MoveBool(&S, p, n);
    else if (!strcmp(kind, "vf"))
        ReplaySnapshot_VerifyFloat(&S, p);
    else if (!strcmp(kind, "vv2"))
        ReplaySnapshot_VerifyVector2(&S, p);
    else if (!strcmp(kind, "vv3"))
        ReplaySnapshot_VerifyVector3(&S, p);
    else if (!strcmp(kind, "vi"))
        ReplaySnapshot_VerifyInt(&S, p, n);
    else if (!strcmp(kind, "vu"))
        ReplaySnapshot_VerifyUInt(&S, p, n);
    else if (!strcmp(kind, "vs"))
        ReplaySnapshot_VerifyShort(&S, p, n);
    else if (!strcmp(kind, "vus"))
        ReplaySnapshot_VerifyUShort(&S, p, n);
    else if (!strcmp(kind, "vsc"))
        ReplaySnapshot_VerifyChar(&S, p, n);
    else {
        fprintf(stderr, "no overload %s\n", kind);
        exit(2);
    }
}

static void set_field(const char *f, int32_t v)
{
    if (!strcmp(f, "t"))
        S.Time = v;
    else if (!strcmp(f, "et"))
        S.EndTime = v;
    else if (!strcmp(f, "blt"))
        S.BeginLoopTime = v;
    else if (!strcmp(f, "elt"))
        S.EndLoopTime = v;
    else if (!strcmp(f, "mil"))
        S.MemoryImageLoadedFlag = v;
    else if (!strcmp(f, "depth"))
        S.CurrentSectionDepth = (int8_t)v;
    else if (!strcmp(f, "ovf"))
        S.OverflowedFlag = (int8_t)v;
    else if (!strcmp(f, "secnum"))
        S.CurrentSectionNumber = (uint16_t)v;
    else if (!strcmp(f, "pd"))
        S.PrintDepth = v;
    else if (!strcmp(f, "plc"))
        S.PrintLoopCounter = v;
    else if (!strcmp(f, "pos"))
        S.DataPosition = v;
    else if (!strcmp(f, "size"))
        S.SizeofData = v;
    else if (!strcmp(f, "tiv"))
        memcpy(&S.TotalInterestingValue, &v, 4);
    else {
        fprintf(stderr, "no field %s\n", f);
        exit(2);
    }
}

static void set_value(const char *h)
{
    size_t n = strlen(h) / 2;
    size_t i;

    memset(V, 0, sizeof V);
    if (!strcmp(h, "~"))
        return;
    for (i = 0; i < n && i < sizeof V; i++) {
        char b[3] = {h[2 * i], h[2 * i + 1], 0};

        V[i] = (uint8_t)strtol(b, NULL, 16);
    }
}

int main(int argc, char **argv)
{
    char line[512];
    FILE *sc;

    if (argc < 2 || (sc = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: replay_test SCRIPT\n");
        return 2;
    }
    memset(Rb, RFILL, RBUF);
    while (fgets(line, sizeof line, sc)) {
        char *arg[8] = {0};
        int n = 0;
        char *t;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        printf("> %s\n", line);
        for (t = strtok(line, "|"); t && n < 8; t = strtok(NULL, "|"))
            arg[n++] = t;
        if (!strcmp(arg[0], "timer")) {
            WorldTimer = num(arg[1]);
            WorldLoopCounter = num(arg[2]);
        } else if (!strcmp(arg[0], "init")) {
            ReplaySnapshot_Init(&S, intern(arg[1]));
        } else if (!strcmp(arg[0], "rename")) {
            ReplaySnapshot_ChangeName(&S, intern(arg[1]));
        } else if (!strcmp(arg[0], "flags")) {
            S.TakingSnapshotFlag = (int8_t)num(arg[1]);
            S.RestoringSnapshotFlag = (int8_t)num(arg[2]);
            S.TakingChecksumFlag = (int8_t)num(arg[3]);
            S.VerifyingChecksumFlag = (int8_t)num(arg[4]);
        } else if (!strcmp(arg[0], "set")) {
            set_field(arg[1], num(arg[2]));
        } else if (!strcmp(arg[0], "val")) {
            set_value(arg[1]);
        } else if (!strcmp(arg[0], "mv")) {
            ReplaySnapshot_MoveData(&S, V, num(arg[1]), num(arg[2]),
                                    num(arg[3]));
            print_value();
        } else if (!strcmp(arg[0], "vd")) {
            ReplaySnapshot_VerifyData(&S, V, num(arg[1]), num(arg[2]),
                                      num(arg[3]));
            print_value();
        } else if (!strcmp(arg[0], "wd")) {
            ReplaySnapshot_WriteData(&S, V, num(arg[1]), num(arg[2]),
                                     num(arg[3]));
            print_value();
        } else if (!strcmp(arg[0], "rd")) {
            ReplaySnapshot_ReadData(&S, V, num(arg[1]), num(arg[2]),
                                    num(arg[3]));
            print_value();
        } else if (!strcmp(arg[0], "ck")) {
            printf("ck %08x\n", ReplaySnapshot_GetChecksum(&S, V,
                                                           num(arg[1])));
        } else if (!strcmp(arg[0], "ov")) {
            overload(arg[1], arg[2] ? num(arg[2]) : 0);
            print_value();
        } else if (!strcmp(arg[0], "begin")) {
            ReplaySnapshot_BeginSection(&S, (void *)(uintptr_t)(uint32_t)
                                        num(arg[1]), intern(arg[2]));
        } else if (!strcmp(arg[0], "bnamed")) {
            ReplaySnapshot_BeginNamedSection(&S, intern(arg[1]));
        } else if (!strcmp(arg[0], "end")) {
            ReplaySnapshot_EndSection(&S);
        } else if (!strcmp(arg[0], "bend")) {
            ReplaySnapshot_EndNamedSection(&S);
        } else if (!strcmp(arg[0], "dump")) {
            dump();
        } else if (!strcmp(arg[0], "rprep")) {
            bRepeat_PrepareToAddData(R, num(arg[1]), num(arg[2]),
                                     num(arg[3]));
        } else if (!strcmp(arg[0], "rchan")) {
            bRepeat_InitChannel(R, num(arg[1]), num(arg[2]), num(arg[3]));
        } else if (!strcmp(arg[0], "radd")) {
            printf("add %d\n", bRepeat_AddData(R, num(arg[1]), num(arg[2]),
                                               num(arg[3])));
        } else if (!strcmp(arg[0], "raddnull")) {
            printf("add %d\n", bRepeat_AddData(NULL, num(arg[1]),
                                               num(arg[2]), num(arg[3])));
        } else if (!strcmp(arg[0], "rrem")) {
            printf("rem %d\n", bRepeat_RemoveData(R, num(arg[1]),
                                                  num(arg[2])));
        } else if (!strcmp(arg[0], "rpr")) {
            bRepeat_PrepareToRemoveData(R);
        } else if (!strcmp(arg[0], "rshovel")) {
            bRepeat_ShovelDataOffToCodeine(R);
        } else if (!strcmp(arg[0], "rw")) {
            bRepeat_WriteToLocation(R, num(arg[1]), num(arg[2]),
                                    num(arg[3]));
        } else if (!strcmp(arg[0], "rr")) {
            printf("rr %d\n", bRepeat_ReadFromLocation(R, num(arg[1]),
                                                       num(arg[2])));
        } else if (!strcmp(arg[0], "rset")) {
            int32_t v = num(arg[2]);

            memcpy(Rb + num(arg[1]), &v, 4);
        } else if (!strcmp(arg[0], "rsnap")) {
            bRepeat_DoSnapshot(R, &S, num(arg[1]));
        } else if (!strcmp(arg[0], "rdump")) {
            rdump();
        } else {
            fprintf(stderr, "no op %s\n", arg[0]);
            return 2;
        }
    }
    fclose(sc);
    return 0;
}
