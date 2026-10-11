// logwriter -- nfshp2_debug.txt, written by a thread of its own
// (logwriter.h).

#include "logwriter.h"

#include <3ds.h>
#include <string.h>

// A race logs about 3 KB a second. A track's load logs a few hundred
// KB at once, and waits on the card for some of it, as it did before.
#define RING_BYTES (128u << 10)

// How long the writer lets lines pile up before it writes them: a race's
// two seconds are one write of a few KB instead of a handful of small ones.
#define GATHER_NS (2000LL * 1000 * 1000)

// The card's sector. A batch ends on one, so no write covers part of a
// sector; the part-sector tail waits for the next batch, TAIL_MS at most.
#define SECTOR  512u
#define TAIL_MS 5000u

// The FILE's own buffer, so a batch reaches FS in as few writes as it can.
#define FILE_BUFFER (32u << 10)

static char       s_ring[RING_BYTES];
static uint32_t   s_head;   // bytes put, ever; under s_lock
static uint32_t   s_tail;   // bytes written, ever; under s_lock
static bool       s_urgent; // write the tail as well; under s_lock
static LightLock  s_lock;
static LightEvent s_wake;   // something was put
static LightEvent s_kick;   // write now: a drain, or the ring filling
static LightEvent s_room;   // something was written
static FILE      *s_file;
static Thread     s_thread;

static void writer_main(void *arg)
{
    uint64_t lastMs = osGetTime();

    (void)arg;
    for (;;) {
        uint32_t head, tail;
        bool     urgent;

        LightEvent_Wait(&s_wake);
        LightEvent_WaitTimeout(&s_kick, GATHER_NS);
        LightLock_Lock(&s_lock);
        head = s_head;
        tail = s_tail;
        urgent = s_urgent;
        s_urgent = false;
        LightLock_Unlock(&s_lock);
        if (head == tail) continue;
        // The file holds every byte put, in order, from offset 0, so a
        // byte's count is its offset in the file.
        if (!urgent && osGetTime() - lastMs < TAIL_MS) {
            uint32_t end = head & ~(SECTOR - 1u);

            if ((int32_t)(end - tail) <= 0) {
                LightEvent_Signal(&s_wake);   // back for the tail later
                continue;
            }
            head = end;
        }
        while (tail != head) {
            uint32_t at = tail % RING_BYTES;
            uint32_t n  = head - tail;

            if (n > RING_BYTES - at) n = RING_BYTES - at;
            fwrite(s_ring + at, 1, n, s_file);
            tail += n;
        }
        fflush(s_file);
        lastMs = osGetTime();
        LightLock_Lock(&s_lock);
        s_tail = tail;
        LightLock_Unlock(&s_lock);
        LightEvent_Signal(&s_room);
    }
}

void logwriter_start(FILE *f)
{
    static const int kCores[3] = { 2, 1, -2 };
    bool n3ds = false;
    s32  prio = 0x30;
    int  i;

    s_file = f;
    if (f == NULL || s_thread != NULL) return;
    setvbuf(f, NULL, _IOFBF, FILE_BUFFER);
    LightLock_Init(&s_lock);
    LightEvent_Init(&s_wake, RESET_ONESHOT);
    LightEvent_Init(&s_kick, RESET_ONESHOT);
    LightEvent_Init(&s_room, RESET_STICKY);
    // Below the main loop, so that on its core it writes in the loop's
    // waits. Core 2 is the New 3DS's own; core 1 has what
    // APT_SetAppCpuTimeLimit gave the app (main.c).
    svcGetThreadPriority(&prio, CUR_THREAD_HANDLE);
    if (prio < 0x3f) prio++;
    APT_CheckNew3DS(&n3ds);
    for (i = n3ds ? 0 : 1; i < 3 && s_thread == NULL; i++)
        s_thread = threadCreate(writer_main, NULL, 16 << 10, prio, kCores[i],
                                true);
}

void logwriter_put(const char *s, size_t n)
{
    bool kick;

    if (s_file == NULL || n == 0) return;
    if (s_thread == NULL) {
        fwrite(s, 1, n, s_file);
        fflush(s_file);
        return;
    }
    // A line longer than the ring is cut to it.
    if (n > RING_BYTES) n = RING_BYTES;
    LightLock_Lock(&s_lock);
    while (RING_BYTES - (s_head - s_tail) < n) {
        LightEvent_Clear(&s_room);
        s_urgent = true;
        LightLock_Unlock(&s_lock);
        LightEvent_Signal(&s_kick);
        LightEvent_Signal(&s_wake);
        LightEvent_Wait(&s_room);
        LightLock_Lock(&s_lock);
    }
    {
        uint32_t at   = s_head % RING_BYTES;
        size_t   part = n < RING_BYTES - at ? n : RING_BYTES - at;

        memcpy(s_ring + at, s, part);
        memcpy(s_ring, s + part, n - part);
        s_head += (uint32_t)n;
    }
    kick = s_head - s_tail >= RING_BYTES / 2;
    LightLock_Unlock(&s_lock);
    if (kick) LightEvent_Signal(&s_kick);
    LightEvent_Signal(&s_wake);
}

void logwriter_flush_soon(void)
{
    if (s_thread == NULL) return;
    LightLock_Lock(&s_lock);
    s_urgent = true;
    LightLock_Unlock(&s_lock);
    LightEvent_Signal(&s_kick);
    LightEvent_Signal(&s_wake);
}

void logwriter_drain(void)
{
    // The writer's own abort cannot wait on itself.
    if (s_thread == NULL || threadGetCurrent() == s_thread) return;
    LightLock_Lock(&s_lock);
    while (s_tail != s_head) {
        LightEvent_Clear(&s_room);
        s_urgent = true;
        LightLock_Unlock(&s_lock);
        LightEvent_Signal(&s_kick);
        LightEvent_Signal(&s_wake);
        LightEvent_Wait(&s_room);
        LightLock_Lock(&s_lock);
    }
    LightLock_Unlock(&s_lock);
}
