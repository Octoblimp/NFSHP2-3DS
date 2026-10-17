#include "langtab.h"

#include <string.h>

#include "bchunk.h"
#include "portlang.h"

#define ENTRY_SIZE 8
// LanguageDescription is 100 bytes: bNode(8) + FileName[64] +
// LanguageEnum(4) + three counts(12) + three dead pointers(12). The
// offsets in docs/formats/language-table.md are from the chunk header,
// so they are 8 higher than these.
#define HEADER_END 100

bool langtab_parse(LangTable* t, const uint8_t* payload, uint32_t size)
{
    if (!payload || size < HEADER_END) return false;

    memset(t, 0, sizeof(*t));
    // bNode Next/Prev at 0 is stale, char FileName[64] at 8 is the authoring
    // path, and the three pointers at 88/92/96 are the PS2 addresses the
    // tables had when the file was built -- dead. The arrays simply follow.
    t->fileName     = (const char*)payload + 8;
    t->languageEnum = (int32_t)bchunk_u32(payload + 72);
    t->numHash      = bchunk_u32(payload + 76);
    t->numID        = bchunk_u32(payload + 80);
    t->textSize     = bchunk_u32(payload + 84);

    size_t hashBytes = (size_t)t->numHash * ENTRY_SIZE;
    size_t idBytes   = (size_t)t->numID * ENTRY_SIZE;
    size_t need      = HEADER_END + hashBytes + idBytes + t->textSize;
    if (need > size) return false;

    t->hashTable = payload + HEADER_END;
    t->idTable   = t->hashTable + hashBytes;
    t->text      = (const char*)(t->idTable + idBytes);
    return true;
}

// GetString (0x0020acd0) binary-searches with slt, so both tables are sorted
// as *signed* 32-bit ints and the English one therefore starts negative.
static const char* lookup(const LangTable* t, const uint8_t* table,
                          uint32_t count, int32_t key, size_t* outLen)
{
    uint32_t lo = 0, hi = count;
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        int32_t  k   = (int32_t)bchunk_u32(table + (size_t)mid * ENTRY_SIZE);
        if (k < key)      lo = mid + 1;
        else if (k > key) hi = mid;
        else {
            uint32_t off = bchunk_u32(table + (size_t)mid * ENTRY_SIZE + 4);
            if (off >= t->textSize) return NULL;
            // The pool's last string is not NUL-terminated -- it ends on the
            // pool's final byte -- so clamp instead of scanning for a NUL.
            const char* s   = t->text + off;
            size_t      max = t->textSize - off;
            const char* nul = (const char*)memchr(s, 0, max);
            if (outLen) *outLen = nul ? (size_t)(nul - s) : max;
            return s;
        }
    }
    return NULL;
}

const char* langtab_get(const LangTable* t, int32_t id, size_t* outLen)
{
    // The port's own IDs (portlang.h) are past every retail one, and a few
    // retail ones have the port's wording.
    if (id >= PORTLANG_FIRST) return portlang_get(t->languageEnum, id, outLen);
    const char* own = portlang_retail(t->languageEnum, id, outLen);
    if (own) return own;
    return langtab_get_disc(t, id, outLen);
}

const char* langtab_get_disc(const LangTable* t, int32_t id, size_t* outLen)
{
    if (!t->idTable) return NULL;
    return lookup(t, t->idTable, t->numID, id, outLen);
}

const char* langtab_get_english(const LangTable* t, int32_t hash,
                                size_t* outLen)
{
    if (!t->hashTable) return NULL;
    // GetString takes its count from NumIDEntries whichever table it was
    // asked for, so the engine searches this one with the other's length.
    // The two are equal in all eight files on disc, so the bug is latent --
    // but use the table's own count here rather than reproducing it.
    return lookup(t, t->hashTable, t->numHash, hash, outLen);
}

size_t langtab_copy(const LangTable* t, int32_t id, char* out, size_t cap)
{
    if (!out || cap == 0) return 0;
    out[0] = '\0';
    size_t      len = 0;
    const char* s   = langtab_get(t, id, &len);
    if (!s) return 0;
    if (len > cap - 1) len = cap - 1;
    memcpy(out, s, len);
    out[len] = '\0';
    return len;
}
