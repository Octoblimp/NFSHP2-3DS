// brepeat -- bRepeat, bWare's recorder: a bit stream of small integers on
// numbered channels, written while a race is captured and read back, in
// the same order, when it is replayed (retail 0x001eb050 .. 0x001eb6a8).
//
// The replay records every frame's timestep and pad events on it, so a
// replay is the race run again on the same inputs (TASKS 72).
//
// One allocation holds the header, NumChannels channels of 36 bytes, and
// the stream after them. Every location is in bits from the start of the
// allocation, and the stream starts at HeaderSize * 8. Bits go in least
// significant first, into each byte from its bit 0 up, so the stream is
// the PS2's bit for bit and the disc's attract-mode replays (TASKS 72h)
// read back here.
//
// An item is the channel in 4 bits, a repeat count in the channel's
// RepeatSize bits, then the value in the caller's bit count. The same
// value of the same size on the same channel again bumps that channel's
// last count in place, even past other channels' items, until the count
// is full.
//
// Codeine was the PS2 development kit's host link: with
// EnableCodeineCapturing a full stream went to the PC (bFunkCallASync to
// "CODEINE"). Every caller on the disc passes 0, and the port has no host
// link, so the calls are gone. The three that ask the host for a stream
// (0x001eb610 on) are only Joylog's, the development kit's, and are not
// ported.

#ifndef BREPEAT_H
#define BREPEAT_H

#include <stddef.h>
#include <stdint.h>

// bRepeatChannel, 36 bytes.
typedef struct bRepeatChannel {
    int32_t RepeatSize;              // 0   bits of an item's repeat count
    int32_t DefaultRemoveData;       // 4   RemoveData's answer on an error
    int32_t AddDataSize;             // 8   the last item's bits
    int32_t AddRepeatCount;          // 12  the last item's repeats
    int32_t AddLocation;             // 16  its repeat count's bit, 0 none
    int32_t AddData;                 // 20  its value
    int32_t RemoveRepeatCount;       // 24
    int32_t RemoveLocation;          // 28
    int32_t RemoveData;              // 32
} bRepeatChannel;

// bRepeat, a 48-byte head; the channels follow it, then the stream.
typedef struct bRepeat {
    int32_t Magic;                   // 0   0x12345678
    int32_t CodeineNeedsUpdating;    // 4
    int32_t AddLocation;             // 8   the next bit to write
    int32_t HeaderSize;              // 12  bytes, 48 + 36 a channel
    int32_t RemoveLocation;          // 16  the next bit to read
    int32_t AddBufferSize;           // 20  bytes, the whole allocation
    int32_t NumChannels;             // 24
    int32_t EnableCodeineCapturing;  // 28
    int32_t NumItemsAdded;           // 32
    int32_t NumItemsRemoved;         // 36
    int32_t RemoveDataError;         // 40
    int32_t RecordingTime;           // 44
    bRepeatChannel Channel[];        // 48, NumChannels of them
} bRepeat;

typedef char brepeat_layout_check[
    (sizeof(bRepeatChannel) == 36
     && offsetof(bRepeat, RemoveDataError) == 40
     && offsetof(bRepeat, Channel) == 48) ? 1 : -1];

#define BREPEAT_MAGIC 0x12345678

// 0x001eb050. Writes the low `bits` bits of `value` at bit `location`.
void bRepeat_WriteToLocation(bRepeat *r, int32_t location, int32_t value,
                             int32_t bits);

// 0x001eb0c0. The `bits` bits at bit `location`, zero-extended.
int32_t bRepeat_ReadFromLocation(bRepeat *r, int32_t location,
                                 int32_t bits);

// 0x001eb120. Lays a new stream over `r`, `size` bytes in all, with
// `channels` channels; clears everything after the head.
void bRepeat_PrepareToAddData(bRepeat *r, int32_t size, int32_t channels,
                              int32_t codeine);

// InitChannel, inline in MarkTheBeginningOfTime (0x0013d798 on).
void bRepeat_InitChannel(bRepeat *r, int32_t channel, int32_t repeat_size,
                         int32_t default_data);

// 0x001eb2d8. 1 when the item went in, 0 with no stream or a full one.
int32_t bRepeat_AddData(bRepeat *r, int32_t value, int32_t bits,
                        int32_t channel);

// 0x001eb498. Back to the stream's first item. Joylog's on the disc; the
// replay's snapshots set the remove side themselves.
void bRepeat_PrepareToRemoveData(bRepeat *r);

// 0x001eb4e8. The channel's next item. Past the last item added, or on
// another channel's item, it sets RemoveDataError and answers the
// channel's DefaultRemoveData.
int32_t bRepeat_RemoveData(bRepeat *r, int32_t bits, int32_t channel);

// 0x001eb1a8. Codeine's: the full stream sent off, and the part byte that
// is left moved down to the start of the stream.
void bRepeat_ShovelDataOffToCodeine(bRepeat *r);

#endif
