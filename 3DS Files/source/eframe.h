// eframe -- Ecstasy's frame malloc (0x0019d9e0 .. 0x0019db2c): memory that
// lives for one frame, from two buffers that swap.
//
// The renderer takes what a frame needs from CurrentBufferPos up to
// CurrentBufferEnd, and eDisplayFrame swaps the buffers once the frame is
// sent, so what the last frame took stays good while the hardware draws it.
// Nothing is ever freed on its own: the swap starts the other buffer over.
//
// The allocation is inline wherever it is made, never a call. DrawAScenery
// has the one the port has so far, for an object's 64-byte matrix;
// eframe_malloc is that inline, word for word.
//
// eInitEngine asks for 2.5 MB (0x4a200000, 2621440.0, through cvt.w.s):
// two buffers of 1.25 MB.

#ifndef EFRAME_H
#define EFRAME_H

#include <stdint.h>

// Ecstasy.obj's .sdata, all 0 in the image.
extern uint32_t  FrameMemoryBufferSize;         // 0x00323da0 gp-20048
extern uint8_t  *CurrentBufferPos;              // 0x00323da4 gp-20044
extern uint8_t  *CurrentBufferEnd;              // 0x00323da8 gp-20040
extern int32_t   PrintFrameMalloc;              // 0x00323dac
extern int32_t   FrameMallocAllocNum;           // 0x00323db0 gp-20032
extern int32_t   FrameMallocFailed;             // 0x00323db4 gp-20028
extern uint32_t  FrameMallocFailAmount;         // 0x00323db8 gp-20024
extern uint32_t  FrameMallocMaxFailAmount;      // 0x00323dbc gp-20020
extern uint8_t  *FrameMemoryBuffer[2];          // 0x00323de8 gp-19976
extern int32_t   FrameMemoryBufferAmountUsed[2];// 0x00323df0 gp-19968

// What eInitEngine asks for.
#define EFRAME_INIT_SIZE 2621440u

// eAllocateFrameMallocBuffers(unsigned int), 0x0019d9e0. Each buffer is
// `(size >> 5) << 4` bytes, but the end is set `size >> 1` past the first:
// for a size that is not a multiple of 32 the end is past the buffer by up
// to 15 bytes. eInitEngine's is a multiple.
void eAllocateFrameMallocBuffers(uint32_t size);

// eFreeFrameMallocBuffers, 0x0019da68.
void eFreeFrameMallocBuffers(void);

// eSwapFrameMallocBuffers, 0x0019dab0: the high-water mark of a failed
// frame, the two frames' usage, and the other buffer from its start.
void eSwapFrameMallocBuffers(void);

// eGetSizeofFrameMallocBuffers(int *), 0x0019db10: the last two frames'
// usage into *used, and both buffers' size.
int32_t eGetSizeofFrameMallocBuffers(int32_t *used);

// The inline. The end is exclusive, and the test is unsigned: a frame
// that would reach the end exactly fails. A failure is counted and
// returns NULL; nothing counts a success.
//
// Before the buffers are made both words are 0, so every call fails. The
// sum is taken on the address, not the pointer, so that holds in C too.
static inline void *eframe_malloc(uint32_t n)
{
    uintptr_t p = (uintptr_t)CurrentBufferPos;

    if (p + n < (uintptr_t)CurrentBufferEnd) {
        CurrentBufferPos = (uint8_t *)(p + n);
        return (void *)p;
    }
    FrameMallocFailed = 1;
    FrameMallocFailAmount += n;
    return 0;
}

#endif
