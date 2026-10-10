// spchbank -- spchbank.o and spchsamp.o of SPP2A380.A: the bank table,
// a bank's repeat queue and cycle bits, and UnPackSample. See spch.h.

#include "spchi.h"

void spchi_init_banks(void)
{
    gSpch.banks = NULL;
    gSpch.numBanks = 0;
}

void spchi_dispose_banks(void)
{
    gSpch.banks = NULL;
    gSpch.numBanks = 0;
}

// Retail's is n << 2, for its 4-byte pointers.
int32_t spch_get_bank_ptr_mem_size(int32_t n)
{
    return n * (int32_t)sizeof(uint8_t *);
}

void spch_init_bank_mem(int32_t n, uint8_t **table)
{
    int32_t i;

    gSpch.numBanks = n;
    gSpch.banks = table;
    if (table != NULL)
        for (i = 0; i < n; i++)
            table[i] = NULL;
}

uint8_t *spch_get_bank_ptr(int32_t handle)
{
    if (gSpch.initialized != SPCH_MAGIC || gSpch.banks == NULL)
        return NULL;
    return gSpch.banks[handle];
}

int32_t spchi_get_free_bank(void)
{
    int32_t i;

    for (i = 0; i < gSpch.numBanks; i++)
        if (gSpch.banks[i] == NULL)
            return i;
    return -1;
}

int32_t spchi_find_bank(uint32_t id)
{
    int32_t i;

    id &= 0xffff;
    if (gSpch.banks == NULL) {
        spchi_abort("iSPCH_FindBank - bank mem not initialized.");
        return -1;
    }
    for (i = 0; i < gSpch.numBanks; i++) {
        const uint8_t *b = gSpch.banks[i];

        if (b != NULL && spch_u16(b) == id)
            return i;
    }
    return -1;
}

int32_t spchi_find_sub_bank(uint32_t id, uint32_t sub)
{
    int32_t i;

    id &= 0xffff;
    sub &= 0xffff;
    if (gSpch.banks == NULL) {
        spchi_abort("iSPCH_FindBank - bank mem not initialized.");
        return -1;
    }
    for (i = 0; i < gSpch.numBanks; i++) {
        const uint8_t *b = gSpch.banks[i];

        if (b != NULL && spch_u16(b) == id && spch_u16(b + 2) == sub)
            return i;
    }
    return -1;
}

int32_t spchi_test_sub_bank_bounds(int32_t handle, uint32_t v)
{
    uint32_t n;

    if (gSpch.banks == NULL) {
        spchi_abort("iSPCH_TestSubBankBounds - bank mem not initialized.");
        return 0;
    }
    if (handle < 0)
        return 0;
    n = spch_u16(gSpch.banks[handle] + 10);
    if (n == 0xffff)
        return 0;
    return v < n;
}

void spch_free_bank(int32_t handle)
{
    if (gSpch.banks == NULL) {
        spchi_abort("iSPCH_FreeBank - bank mem not initialized.");
        return;
    }
    gSpch.banks[handle] = NULL;
}

// The sample into the repeat queue's next slot.
void spchi_bank_add_to_queue(uint8_t *b, uint32_t sample)
{
    uint8_t *q;
    uint32_t idx;

    if (b[6] == 0)
        return;
    q = spch_bank_queue(b);
    idx = q[0];
    if (idx < b[6])
        q[1 + idx] = (uint8_t)sample;
    else
        spchi_abort("iSPCHBank_AddToQueue: queue index out of bounds.");
    idx = (idx + 1) & 0xff;
    if (idx >= b[6])
        idx = 0;
    q[0] = (uint8_t)idx;
}

// How long ago the sample played: 1 for the last one, 0 if it is not in
// the repeat queue.
int32_t spchi_bank_get_sample_time_in_queue(const uint8_t *b, uint32_t sample)
{
    const uint8_t *q;
    int32_t n = b[6], a, j;

    if (n <= 0)
        return 0;
    q = spch_bank_queue(b);
    j = q[0] - 1;
    for (a = 0; a < n; a++, j--) {
        if (j < 0)
            j = n - 1;
        if (q[1 + j] == sample)
            return a + 1;
    }
    return 0;
}

// The game's share of the samples: of every cycleLength games, game g
// gets the g'th slice.
void spchi_set_cycle_bits(uint8_t *b)
{
    uint8_t *c = spch_bank_cycle(b);
    uint32_t len = c[0], n = b[5], g, start, cnt, bit;
    uint8_t *p;

    if (len == 0) {
        spchi_abort("iSPCH_SetCycleBits - cycleLength = 0 bankType: %lu",
                    (unsigned long)spch_u16(b));
        return;
    }
    g = (uint32_t)gSpch.gameNum % len;
    start = g * n / len;
    cnt = (g * n + n) / len - start;
    p = c + 1 + (start >> 3);
    bit = start & 7;
    for (; (int32_t)cnt > 0; cnt--) {
        *p |= (uint8_t)(1u << bit);
        if (++bit == 8) {
            bit = 0;
            p++;
        }
    }
}

int32_t spch_add_bank(uint8_t *b)
{
    int32_t k, i;

    if (gSpch.banks == NULL) {
        spchi_abort("iSPCH_AddBank - bank mem not initialized.");
        return -1;
    }
    if (b[6] != 0) {
        const uint8_t *q = spch_bank_queue(b);

        if (q[0] != 0) {
            spchi_abort("SPCH_AddBank - bank %d - sampleRepeat not initialized properly.",
                        spch_u16(b));
            return -1;
        }
        for (i = 0; i < b[6]; i++) {
            if (q[1 + i] != 255) {
                spchi_abort("SPCH_AddBank - bank %d - sampleRepeat not initialized properly.",
                            spch_u16(b));
                return -1;
            }
        }
    }
    k = spchi_get_free_bank();
    if (k < 0) {
        spchi_abort("SPCH_addbank - out of bank mem.\n");
        return k;
    }
    if (b[4] & 0x80)
        spchi_set_cycle_bits(b);
    gSpch.banks[k] = b;
    return k;
}

// ---- spchsamp

void spchi_init_sample(SpchSample *r)
{
    r->size = 0;
    r->offset = -1;
    r->numParms = 0;
    memset(r->parms, 255, sizeof(r->parms));
}

// A sample's place in the bank data and its parameters. An entry with
// bit 7 set is an alias of the one its second byte names; a sample ends
// where the next one that is not an alias starts, or at the bank's end.
int32_t spchi_unpack_sample(const uint8_t *b, uint32_t idx, SpchSample *r)
{
    int32_t n = b[5], np = b[4] & 0xf, es = np + 2, i, j;
    int32_t unit = (b[7] + 1) << 8, end;
    const uint8_t *e;

    spchi_init_sample(r);
    if (!((int32_t)idx < n)) {
        spchi_abort("UnPackSample - invalid index.");
        return 0;
    }
    r->numParms = np;
    e = b + 12 + (int32_t)idx * es;
    // Retail copies all of them, over its stack past the fourth.
    for (i = 0; i < np && i < SPCH_SAMPLE_PARMS; i++)
        r->parms[i] = e[2 + i];
    if (e[0] & 0x80) {
        idx = e[1];
        e = b + 12 + (int32_t)idx * es;
    }
    if (!((int32_t)idx < n)) {
        spchi_abort("iSPCH_UnpackSample - alias resolved out of bounds.\n");
        return 0;
    }
    if (e[0] & 0x80) {
        spchi_abort("iSPCH_UnpackSample - alias resolved to another alias.\n");
        return 0;
    }
    r->offset = ((e[0] << 8) + e[1]) * unit;
    end = spch_u16(b + 8) * unit;
    for (j = (int32_t)idx + 1, e += es; j < n; j++, e += es) {
        if (!(e[0] & 0x80)) {
            end = ((e[0] << 8) + e[1]) * unit;
            break;
        }
    }
    r->size = end - r->offset;
    return 1;
}
