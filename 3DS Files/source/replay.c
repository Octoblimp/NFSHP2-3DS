// replay -- see replay.h.

#include "replay.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "p32.h"
#include "realtime.h"

ReplayManager *pReplayManager;

ReplayGetDataFn gReplayManagerGetData;
ReplayAddDataFn gReplayManagerAddData;

int32_t replay_breaks;

// ---------------------------------------------------------- ReplaySnapshot

// The section at `depth`, as retail finds it: 76 + depth * 16 bytes in,
// with no bound. So a MoveData outside every section (depth -1) counts
// itself in PrintDepth's third byte, and a seventeenth level would land on
// TotalInterestingValue and the data's place; no caller does either.
static ReplaySectionInfo *section_at(ReplaySnapshot *s, int32_t depth)
{
    return (ReplaySectionInfo *)((uint8_t *)s + 76 + depth * 16);
}

// 0x0013cce8. Init leaves the list node, EndTime and the section stack.
void ReplaySnapshot_Init(ReplaySnapshot *s, const char *name)
{
    strcpy(s->Name, name);
    s->Time = WorldTimer;
    s->BeginLoopTime = WorldLoopCounter;
    s->CurrentSectionDepth = -1;
    s->PrintDepth = -1;
    s->SizeofData = 0;
    s->EndLoopTime = 0;
    s->MemoryImageLoadedFlag = 0;
    s->TakingSnapshotFlag = 0;
    s->RestoringSnapshotFlag = 0;
    s->TakingChecksumFlag = 0;
    s->VerifyingChecksumFlag = 0;
    s->OverflowedFlag = 0;
    s->CurrentSectionNumber = 0;
    s->PrintLoopCounter = 0;
    s->TotalInterestingValue = 0.0f;
    s->DataPosition = 0;
}

// 0x0013cd60.
void ReplaySnapshot_ChangeName(ReplaySnapshot *s, const char *name)
{
    strcpy(s->Name, name);
}

// 0x0013cd68.
uint32_t ReplaySnapshot_GetChecksum(ReplaySnapshot *s, const void *data,
                                    int32_t n)
{
    const uint8_t *p = data;
    uint32_t h = 0xffffffffu;
    int32_t i;

    (void)s;
    for (i = 0; i < n; i++)
        h = h * 33u + p[i];
    return h;
}

// 0x0013cda0. A value that would reach the data's last byte overflows: it
// is not written, and OverflowedFlag goes up. Bytes past `stored` that are
// not the sign of the last one stored (or zeros) are a bBreak.
void ReplaySnapshot_WriteData(ReplaySnapshot *s, const void *data,
                              int32_t stored, int32_t size,
                              int32_t is_signed)
{
    const uint8_t *src = data;
    int32_t pos = s->DataPosition;
    uint8_t last = 0;
    uint8_t fill;
    int32_t i;

    if (pos + stored > REPLAY_SNAPSHOT_DATA_SIZE - 1) {
        if (!s->OverflowedFlag)
            s->OverflowedFlag = 1;
        return;
    }
    for (i = 0; i < stored; i++) {
        last = src[i];
        s->Data[pos++] = last;
    }
    if (i < size) {
        fill = (is_signed && (last & 0x80)) ? 0xff : 0;
        for (; i < size; i++)
            if (src[i] != fill) {
                replay_breaks++;
                break;
            }
    }
    s->DataPosition = pos;
}

// 0x0013ce78. Past SizeofData nothing is read, and `data` is left alone.
void ReplaySnapshot_ReadData(ReplaySnapshot *s, void *data, int32_t stored,
                             int32_t size, int32_t is_signed)
{
    uint8_t *dst = data;
    int32_t pos = s->DataPosition;
    uint8_t last = 0;
    uint8_t fill;
    int32_t i;

    if (s->SizeofData < pos + stored)
        return;
    for (i = 0; i < stored; i++) {
        last = s->Data[pos++];
        dst[i] = last;
    }
    if (i < size) {
        fill = (is_signed && (last & 0x80)) ? 0xff : 0;
        for (; i < size; i++)
            dst[i] = fill;
    }
    s->DataPosition = pos;
}

// 0x0013cf08. A checksum is the low 16 bits of `stored` bytes'. A section's
// first checksum that does not verify marks it and is a bBreak; retail
// also measures the section's name for a print that is gone.
//
// Verifying past SizeofData reads nothing, and retail then compares with
// whatever its stack held at sp+2; the port compares with 0.
void ReplaySnapshot_MoveData(ReplaySnapshot *s, void *p, int32_t stored,
                             int32_t size, int32_t is_signed)
{
    ReplaySectionInfo *sec = section_at(s, s->CurrentSectionDepth);

    if (size == -1)
        size = stored;
    sec->NumMoveData++;
    if (s->TakingSnapshotFlag) {
        ReplaySnapshot_WriteData(s, p, stored, size, is_signed);
    } else if (s->RestoringSnapshotFlag) {
        ReplaySnapshot_ReadData(s, p, stored, size, is_signed);
    } else if (s->TakingChecksumFlag) {
        uint16_t h = (uint16_t)ReplaySnapshot_GetChecksum(s, p, stored);

        ReplaySnapshot_WriteData(s, &h, 2, 2, 0);
    } else if (s->VerifyingChecksumFlag) {
        uint16_t h = (uint16_t)ReplaySnapshot_GetChecksum(s, p, stored);
        uint16_t was = 0;

        ReplaySnapshot_ReadData(s, &was, 2, 2, 0);
        if (h != was && !sec->ChecksumErrorDetected) {
            sec->ChecksumErrorDetected = 1;
            replay_breaks++;
        }
    }
}

// 0x0013d0d0. The two checksum flags, 62 and 63, as one halfword.
void ReplaySnapshot_VerifyData(ReplaySnapshot *s, void *p, int32_t stored,
                               int32_t size, int32_t is_signed)
{
    if (s->TakingChecksumFlag || s->VerifyingChecksumFlag)
        ReplaySnapshot_MoveData(s, p, stored, size, is_signed);
}

// 0x0013d100. The compares are c.eq.s, so -0 is 0 and a NaN is not; the
// code is worked out in every mode and a restore reads it over the one
// worked out.
void ReplaySnapshot_MoveMatrix(ReplaySnapshot *s, bMatrix4 *m)
{
    int8_t code = 0;

    if (m->v0.w == 0.0f && m->v1.w == 0.0f && m->v2.w == 0.0f
        && m->v3.w == 1.0f) {
        if (m->v3.x == 0.0f && m->v3.y == 0.0f && m->v3.z == 0.0f)
            code = 1;
        else
            code = 2;
    }
    ReplaySnapshot_MoveChar(s, &code, 1);
    if (code == 0) {
        ReplaySnapshot_MoveData(s, m, 64, -1, 0);
        return;
    }
    ReplaySnapshot_MoveData(s, &m->v0, 12, -1, 0);
    ReplaySnapshot_MoveData(s, &m->v1, 12, -1, 0);
    ReplaySnapshot_MoveData(s, &m->v2, 12, -1, 0);
    m->v3.w = 1.0f;
    m->v0.w = 0.0f;
    m->v1.w = 0.0f;
    m->v2.w = 0.0f;
    if (code == 2) {
        ReplaySnapshot_MoveData(s, &m->v3, 12, -1, 0);
    } else {
        m->v3.z = 0.0f;
        m->v3.x = 0.0f;
        m->v3.y = 0.0f;
    }
}

// 0x0013d288. The first level of a snapshot numbers its sections from 0.
// Its Size is where its data starts until EndSection makes it the length.
// Retail then prints the section's name when PrintDepth asks for it, and
// calls VerifyMoveDataInSync (0x0013d0f8), which is empty; both are gone.
void ReplaySnapshot_BeginSection(ReplaySnapshot *s, void *object,
                                 const char *name)
{
    ReplaySectionInfo *sec;
    uint16_t n;
    int32_t pos;

    if (s->CurrentSectionDepth == -1)
        s->CurrentSectionNumber = 0;
    s->CurrentSectionDepth = (int8_t)(s->CurrentSectionDepth + 1);
    sec = section_at(s, s->CurrentSectionDepth);
    n = s->CurrentSectionNumber;
    s->CurrentSectionNumber = (uint16_t)(n + 1);
    sec->NumMoveData = 0;
    sec->ChecksumErrorDetected = 0;
    sec->Number = n;
    pos = s->DataPosition;
    sec->Object = p32_of(object);
    sec->Size = pos;
    sec->Name = p32_of(name);
}

// 0x0013d358. A level below PrintDepth ends the printing.
void ReplaySnapshot_EndSection(ReplaySnapshot *s)
{
    ReplaySectionInfo *sec = section_at(s, s->CurrentSectionDepth);

    sec->Size = s->DataPosition - sec->Size;
    s->CurrentSectionDepth = (int8_t)(s->CurrentSectionDepth - 1);
    if (s->CurrentSectionDepth < s->PrintDepth)
        s->PrintDepth = -1;
}

// ------------------------------------------------------------------ bRepeat

// 0x0013cb90. Every value is an int, all four bytes stored.
void bRepeat_DoSnapshot(bRepeat *r, ReplaySnapshot *s, int32_t adding)
{
    int32_t i;

    ReplaySnapshot_BeginNamedSection(s, "bRepeat");
    if (adding) {
        ReplaySnapshot_MoveInt(s, &r->AddLocation, 4);
        ReplaySnapshot_MoveInt(s, &r->NumItemsAdded, 4);
        for (i = 0; i < r->NumChannels; i++) {
            ReplaySnapshot_MoveInt(s, &r->Channel[i].AddRepeatCount, 4);
            ReplaySnapshot_MoveInt(s, &r->Channel[i].AddLocation, 4);
            ReplaySnapshot_MoveInt(s, &r->Channel[i].AddData, 4);
        }
    } else {
        r->RemoveDataError = 0;
        ReplaySnapshot_MoveInt(s, &r->RemoveLocation, 4);
        ReplaySnapshot_MoveInt(s, &r->NumItemsRemoved, 4);
        for (i = 0; i < r->NumChannels; i++) {
            ReplaySnapshot_MoveInt(s, &r->Channel[i].RemoveRepeatCount, 4);
            ReplaySnapshot_MoveInt(s, &r->Channel[i].RemoveLocation, 4);
            ReplaySnapshot_MoveInt(s, &r->Channel[i].RemoveData, 4);
        }
    }
    ReplaySnapshot_EndNamedSection(s);
}

// ------------------------------------------------------------ ReplayManager

static void no_replay(void)
{
    fprintf(stderr, "replay: ReplayManager is not ported\n");
    abort();
}

int32_t ReplayManager_GetData(ReplayManager *rm, int32_t bits,
                              int32_t channel)
{
    if (gReplayManagerGetData == NULL)
        no_replay();
    return gReplayManagerGetData(rm, bits, channel);
}

void ReplayManager_AddData(ReplayManager *rm, int32_t value, int32_t bits,
                           int32_t channel)
{
    if (gReplayManagerAddData == NULL)
        no_replay();
    gReplayManagerAddData(rm, value, bits, channel);
}

// 0x0013e270. The compare is against the string at 0x002aef60,
// "INSTANT_REPLAY", and never against `description`: every caller's event
// lands on the instant-replay snapshots and no others. The image's compare
// is bStrCmp, a signed-char difference that is 0 exactly when the two
// strings are equal, and only its zero is tested, so strcmp stands in.
void ReplayManager_RegisterInterestingEvent(ReplayManager *rm, float value,
                                            const char *description)
{
    const void *head = rm->ReplaySnapshotList;
    ReplaySnapshot *s;

    (void)description;
    if (!rm->CapturingFlag)
        return;
    for (s = p32_ptr(rm->ReplaySnapshotList[0]); (const void *)s != head;
         s = p32_ptr(s->pNext))
        if (strcmp(s->Name, "INSTANT_REPLAY") == 0)
            s->TotalInterestingValue = s->TotalInterestingValue + value;
}

// 0x0013e2f0.
void ReplayManager_InvalidateInterestingEvents(ReplayManager *rm)
{
    ReplayManager_RegisterInterestingEvent(rm, -99.0f, "Invalidate");
}
