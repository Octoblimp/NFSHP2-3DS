#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// bWare language tables -- chunk 0x00039000, one whole `LANGUAGES\FE_*.BIN`.
// Layout and provenance: docs/formats/language-table.md.
//
// Every string the UI shows comes from here. A Flailer text object carries a
// LanguageID and the string baked in beside it is only the authoring
// placeholder, so the renderer must look the ID up in this table and draw
// that instead.
//
// Host-buildable: no <3ds.h> here.

#define LANGTAB_CHUNK 0x00039000u

// e_Languages, the value in LanguageEnum. The last two are build tools, not
// languages: LONGEST holds each ID's longest translation in any language so
// layouts can be tested against the worst case, and ID_NUM maps each ID to
// its own number as text so a QA build can read IDs off the screen.
typedef enum {
    LANG_EN = 0, LANG_FR, LANG_DE, LANG_IT, LANG_ES, LANG_SE,
    LANG_LONGEST, LANG_ID_NUM,
} LangEnum;

typedef struct {
    int32_t        languageEnum;
    uint32_t       numHash;    // entries in the English-hash table
    uint32_t       numID;      // entries in the ID table
    uint32_t       textSize;
    const uint8_t* hashTable;  // numHash 8-byte { s32 Hash; u32 Offset; }
    const uint8_t* idTable;    // numID of the same, keyed by LanguageID
    const char*    text;       // textSize bytes; the last string has no NUL
    const char*    fileName;   // the authoring path baked into the header
} LangTable;

// Parses the chunk whose payload is `payload` and whose Size is `size`.
bool langtab_parse(LangTable* t, const uint8_t* payload, uint32_t size);

// The string for a numeric LanguageID. Returns NULL when the ID is absent.
// The result points into the table and is *not* NUL-terminated -- the last
// string in the pool ends on the pool's final byte -- so use *outLen.
const char* langtab_get(const LangTable* t, int32_t id, size_t* outLen);

// langtab_get with no port strings (portlang.h): the disc's string for a
// retail ID, as GetString finds it. langtab_check reads the disc with it.
const char* langtab_get_disc(const LangTable* t, int32_t id,
                             size_t* outLen);

// The same string copied into `out` and NUL-terminated, which is what a
// drawing call wants. Returns the number of bytes copied, 0 when absent.
size_t langtab_copy(const LangTable* t, int32_t id, char* out, size_t cap);

// Lookup by bStringHash of the *English* text, for code that holds a literal
// rather than an ID. Prefer langtab_get(): in a translated file 55 English
// hashes map to more than one distinct string, because the same English
// wording is translated differently by context, and this returns whichever
// the binary search lands on.
const char* langtab_get_english(const LangTable* t, int32_t hash,
                                size_t* outLen);
