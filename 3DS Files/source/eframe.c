// eframe -- Ecstasy's frame malloc. See eframe.h.

#include "eframe.h"

#include "bmem.h"

uint32_t  FrameMemoryBufferSize;
uint8_t  *CurrentBufferPos;
uint8_t  *CurrentBufferEnd;
int32_t   PrintFrameMalloc;
int32_t   FrameMallocAllocNum;
int32_t   FrameMallocFailed;
uint32_t  FrameMallocFailAmount;
uint32_t  FrameMallocMaxFailAmount;
uint8_t  *FrameMemoryBuffer[2];
int32_t   FrameMemoryBufferAmountUsed[2];

void eAllocateFrameMallocBuffers(uint32_t size)
{
    int32_t each = (int32_t)((size >> 5) << 4);
    uint32_t half = size >> 1;

    FrameMemoryBuffer[0] = bMalloc(each, "eFrameMallocBuffer0", 0, 16);
    FrameMemoryBuffer[1] = bMalloc(each, "eFrameMallocBuffer1", 0, 16);
    FrameMemoryBufferSize = half;
    CurrentBufferEnd = FrameMemoryBuffer[0] + half;
    CurrentBufferPos = FrameMemoryBuffer[0];
    FrameMallocAllocNum = 0;
}

void eFreeFrameMallocBuffers(void)
{
    bFree(FrameMemoryBuffer[0]);
    bFree(FrameMemoryBuffer[1]);
    FrameMemoryBuffer[0] = 0;
    FrameMemoryBuffer[1] = 0;
    FrameMemoryBufferSize = 0;
    CurrentBufferPos = 0;
    CurrentBufferEnd = 0;
    FrameMallocAllocNum = 0;
}

void eSwapFrameMallocBuffers(void)
{
    uint8_t *next = FrameMemoryBuffer[1];
    uint8_t *done = FrameMemoryBuffer[0];

    if (FrameMallocFailed && FrameMallocMaxFailAmount < FrameMallocFailAmount)
        FrameMallocMaxFailAmount = FrameMallocFailAmount;

    FrameMemoryBufferAmountUsed[1] = FrameMemoryBufferAmountUsed[0];
    FrameMemoryBufferAmountUsed[0] = (int32_t)(CurrentBufferPos - done);
    FrameMemoryBuffer[1] = done;
    CurrentBufferEnd = next + FrameMemoryBufferSize;
    FrameMallocFailed = 0;
    FrameMallocFailAmount = 0;
    FrameMemoryBuffer[0] = next;
    CurrentBufferPos = next;
    FrameMallocAllocNum = 0;
}

int32_t eGetSizeofFrameMallocBuffers(int32_t *used)
{
    *used = FrameMemoryBufferAmountUsed[0] + FrameMemoryBufferAmountUsed[1];
    return (int32_t)(FrameMemoryBufferSize << 1);
}
