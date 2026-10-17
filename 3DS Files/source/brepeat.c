// brepeat -- see brepeat.h.

#include "brepeat.h"

#include <string.h>

// The stream is full once AddLocation reaches this many bits.
static int32_t add_limit(const bRepeat *r)
{
    return (int32_t)((uint32_t)r->AddBufferSize * 8u - 68u);
}

static bRepeatChannel *channel_at(bRepeat *r, int32_t channel)
{
    return (bRepeatChannel *)((uint8_t *)r + 48 + 36 * channel);
}

// 0x001eb050. The shifts are the EE's `srav`, by the bit's number mod 32.
void bRepeat_WriteToLocation(bRepeat *r, int32_t location, int32_t value,
                             int32_t bits)
{
    uint8_t *p = (uint8_t *)r + location / 8;
    int32_t bit = location & 7;
    int32_t i;

    for (i = 0; i < bits; i++) {
        *p = (uint8_t)((*p & ~(1 << bit))
                       | (((value >> (i & 31)) & 1) << bit));
        bit = (bit + 1) & 7;
        if (bit == 0)
            p++;
    }
}

// 0x001eb0c0.
int32_t bRepeat_ReadFromLocation(bRepeat *r, int32_t location, int32_t bits)
{
    const uint8_t *p = (const uint8_t *)r + location / 8;
    int32_t bit = location & 7;
    uint32_t v = 0;
    int32_t i;

    for (i = 0; i < bits; i++) {
        v |= (uint32_t)((*p >> bit) & 1) << (i & 31);
        bit = (bit + 1) & 7;
        if (bit == 0)
            p++;
    }
    return (int32_t)v;
}

// 0x001eb120. A size under the head's 48 bytes would send retail's bMemSet
// through all of memory; the port's clears nothing then. The size the
// replay passes is 0x32000.
void bRepeat_PrepareToAddData(bRepeat *r, int32_t size, int32_t channels,
                              int32_t codeine)
{
    r->Magic = BREPEAT_MAGIC;
    r->CodeineNeedsUpdating = 0;
    r->RemoveLocation = 0;
    r->NumItemsAdded = 0;
    r->NumItemsRemoved = 0;
    r->RemoveDataError = 0;
    r->HeaderSize = (channels - 1) * 36 + 84;
    r->AddLocation = r->HeaderSize * 8;
    r->NumChannels = channels;
    r->EnableCodeineCapturing = codeine;
    r->AddBufferSize = size;
    if (size > 48)
        memset((uint8_t *)r + 48, 0, (size_t)(size - 48));
    r->RecordingTime = 0;
}

// Inline in MarkTheBeginningOfTime.
void bRepeat_InitChannel(bRepeat *r, int32_t channel, int32_t repeat_size,
                         int32_t default_data)
{
    bRepeatChannel *c = channel_at(r, channel);

    c->RepeatSize = repeat_size;
    c->DefaultRemoveData = default_data;
}

// 0x001eb1a8. Retail first sends the stream from the head to its last
// whole byte, 2016 bytes a message; with no host link that is gone. What
// is left is the same: every channel without a last item, and the bits of
// the part byte at the start of the stream.
void bRepeat_ShovelDataOffToCodeine(bRepeat *r)
{
    int32_t start = r->HeaderSize * 8;
    int32_t whole = r->AddLocation & ~7;
    int32_t left;
    int32_t i;

    for (i = 0; i < r->NumChannels; i++)
        channel_at(r, i)->AddLocation = 0;
    left = r->AddLocation - whole;
    if (left != 0)
        bRepeat_WriteToLocation(
            r, start, bRepeat_ReadFromLocation(r, r->AddLocation - left, left),
            left);
    r->AddLocation = start + left;
}

// 0x001eb2d8. With Codeine, the first item since the host last took the
// stream told it so (bFunkCallASync, message 63).
int32_t bRepeat_AddData(bRepeat *r, int32_t value, int32_t bits,
                        int32_t channel)
{
    bRepeatChannel *c;

    if (r == NULL)
        return 0;
    if (!(r->AddLocation < add_limit(r)))
        return 0;
    r->NumItemsAdded++;
    c = channel_at(r, channel);
    if (c->AddLocation != 0 && c->AddDataSize == bits
        && c->AddRepeatCount
               != (int32_t)((1u << (c->RepeatSize & 31)) - 1u)
        && c->AddData == value) {
        c->AddRepeatCount++;
        bRepeat_WriteToLocation(r, c->AddLocation, c->AddRepeatCount,
                                c->RepeatSize);
    } else {
        bRepeat_WriteToLocation(r, r->AddLocation, channel, 4);
        r->AddLocation += 4;
        c->AddLocation = r->AddLocation;
        bRepeat_WriteToLocation(r, r->AddLocation, 0, c->RepeatSize);
        c->AddRepeatCount = 0;
        r->AddLocation += c->RepeatSize;
        c->AddData = value;
        bRepeat_WriteToLocation(r, r->AddLocation, value, bits);
        r->AddLocation += bits;
        c->AddDataSize = bits;
    }
    if (r->EnableCodeineCapturing)
        r->CodeineNeedsUpdating++;
    if (!(r->AddLocation < add_limit(r)) && r->EnableCodeineCapturing)
        bRepeat_ShovelDataOffToCodeine(r);
    return 1;
}

// 0x001eb498.
void bRepeat_PrepareToRemoveData(bRepeat *r)
{
    int32_t i;

    r->NumItemsRemoved = 0;
    r->RemoveLocation = r->HeaderSize * 8;
    r->RemoveDataError = 0;
    for (i = 0; i < r->NumChannels; i++) {
        channel_at(r, i)->RemoveRepeatCount = 0;
        channel_at(r, i)->RemoveLocation = 0;
    }
}

// 0x001eb4e8. A repeat of the channel's last item first; else the next
// item in the stream, which must be this channel's.
int32_t bRepeat_RemoveData(bRepeat *r, int32_t bits, int32_t channel)
{
    bRepeatChannel *c = channel_at(r, channel);
    int32_t v;

    if (c->RemoveLocation != 0
        && c->RemoveRepeatCount
               < bRepeat_ReadFromLocation(r, c->RemoveLocation,
                                          c->RepeatSize)) {
        c->RemoveRepeatCount++;
        v = c->RemoveData;
    } else if (!(r->NumItemsRemoved < r->NumItemsAdded)) {
        r->RemoveDataError = 1;
        v = c->DefaultRemoveData;
    } else {
        int32_t ch = bRepeat_ReadFromLocation(r, r->RemoveLocation, 4);

        r->RemoveLocation += 4;
        if (ch != channel) {
            r->RemoveDataError = 1;
            v = c->DefaultRemoveData;
        } else {
            c->RemoveLocation = r->RemoveLocation;
            c->RemoveRepeatCount = 0;
            r->RemoveLocation += c->RepeatSize;
            v = bRepeat_ReadFromLocation(r, r->RemoveLocation, bits);
            c->RemoveData = v;
            r->RemoveLocation += bits;
        }
    }
    r->NumItemsRemoved++;
    return v;
}
