// FRONTB's Flailer chunk with the port's main menu rows, Local Wireless
// and the debug menu, and the debug menu's screens in it (debugmenu.h).
//
// The chunk is written out again rather than patched in place, because
// what is added has to sit between what is there: flailer_object_index
// (flailer.c) binary-searches a project's payload addresses, so the objects
// must rise in file order, and NEW_MAIN_MENU's new objects belong inside
// its container, before the screens after it. Every chunk goes across in
// order and byte for byte, but for the main menu's object count and its
// bottom filler's height; the padding between chunks (type 0, size 0) is
// dropped, which neither reader counts (bchunk_next skips it). Every size
// in the chunk is a multiple of 4, so a malloc'd buffer keeps every
// payload 4-aligned.
//
// The main menu's rows are then laid out in the port's order (TASKS 68):
// only their Ys and visibility change, in the buffer the patch returned,
// which bui reads live. The panel holds five rows; past that they scroll.
//
// Free of <3ds.h>, like bui.c, for tools/debugmenu_check.py.

#include "debugmenu.h"

#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bui.h"
#include "portlang.h"

// Retail's object fields, as offsets from the payload: flailer.h's
// FlailerObjectChunk, FlailerTextChunk and FlailerScreenChunk.
#define OBJ_NAME_HASH   8
#define OBJ_NAME        16      // char[24], the authoring name
#define OBJ_VISIBILITY  41
#define OBJ_X           48
#define OBJ_Y           52
#define OBJ_SCALE_Y     60
#define TEXT_MAX_CHARS  84
#define TEXT_LANGUAGE   96
#define TEXT_STRING     100
#define SCREEN_NAME     8
#define SCREEN_NUM_OBJS 28

#define CHUNK_TEXT      0x00010212u

// NEW_MAIN_MENU's objects the new rows are made from (gameflow.h).
#define MAIN_MENU       0xae0f8aa1u
#define MENUITEM(n)     (0x52e039f2u + (uint32_t)(n))
#define MI_1_MASK       0x6e34e350u
#define MI_2_MASK       0x708a0bf1u
#define MI_3_MASK       0x72df3492u
#define MI_4_MASK       0x75345d33u
#define MI_5_MASK       0x778985d4u
#define BOTTOM_MASK     0xaa5d7d3fu
// Be The Cop Setup's, for the debug screen.
#define LINE(n)         (0x69a2c756u + (uint32_t)(n))
#define TITLE           0x5e9f4683u   // CHALLENGE_TITLE
#define HELP            0x75980cf0u   // SCROLLING_TEXT

// The mask texture (e2a5c626) is 16 high at ScaleY 1: MI_n_MASK's 2.813
// is the row's 45 pixels, and the two thin BOTTOM_MASKs' 0.625 the 10
// between rows. The third BOTTOM_MASK, at 7.063, fills the panel below
// Options: 113 pixels, room for two more rows and their separators. It
// becomes the separator under the third row, and the fillers the port
// adds under the fourth and fifth each the separator under its row or,
// under the last row shown, the panel down to where the third ended.
#define MASK_UNIT       16.0f
#define SEPARATOR_SCALE 0.625f

// The main menu's order (TASKS 68, the user's ask of 2026-10-15): every
// row above Options but the debug menu's, which is the only one under it.
// Hot Pursuit, World Racing, Local Wireless, Options, then Debug Menu once
// shown. MAIN_SLOTS rows fit the panel, a row's step (55 px) apart; with
// more, the window of rows shown follows the highlight.
#define MAIN_SLOTS      5
#define MAIN_ROWS       5

// What the debug screens leave out of Be The Cop Setup: its eighth row
// (label, value, mask), the two blooms' spare texts, and the scroll clip.
// A screen with fewer rows loses their labels and values as well, and
// keeps their masks, which darken the panel under its last row.
static const uint32_t kLeftOut[] = {
    0x52e039fau, 0x69a2c75eu, 0x7e88ffb7u, 0xab671c9au, 0x1042eac3u,
    0xc67cfb4au,
};

// The rooms the debug screen's texts get: Be The Cop Setup's are its own
// strings' (10 and 6), and the help line's 100. 128 is all flailer_printf
// writes.
#define LABEL_ROOM 24
#define VALUE_ROOM 40
#define TITLE_ROOM 16
#define HELP_ROOM  128

typedef struct {
    uint8_t* p;
    size_t   len, cap;
    int      failed;
} Out;

// A row added under Options: its label, its mask and the filler under
// it, as offsets of their payloads in the buffer the patch returned.
typedef struct {
    size_t item, mask, fill;
} Row;

// The two rows, which debugmenu_reveal changes.
static uint8_t* sBuf;
static Row      sWireless, sDebug;
static int      sRevealed;

// A main menu row in the port's order: its MENUITEM_n, and its label's and
// mask's payloads in sBuf.
typedef struct {
    uint32_t item;
    size_t   label, mask;
} MainRow;

static MainRow sRows[MAIN_ROWS];
static int     sNumRows;
// Each slot's label and mask Y: retail's three rows, then a row's step at
// a time below Options' (put_row's). The filler under each slot's mask
// that the layout sets, 0 under the first two (retail's thin separators,
// left as they are). Where retail's filler ended.
static float   sLabelY[MAIN_SLOTS], sMaskY[MAIN_SLOTS];
static size_t  sFill[MAIN_SLOTS];
static float   sBottom;
// The slots in use (MAIN_SLOTS but in tools/debugmenu_check.py), the
// first row shown, and the highlighted row, whose mask SelectionSet's
// IndicatorMode 1 keeps off; -1 for none.
static int     sSlots = MAIN_SLOTS, sTop, sCurrent = -1;

static uint32_t rd32(const uint8_t* p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16
           | (uint32_t)p[3] << 24;
}

static void wr32(uint8_t* p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

static float rdf(const uint8_t* p)
{
    uint32_t v = rd32(p);
    float    f;
    memcpy(&f, &v, sizeof f);
    return f;
}

static void wrf(uint8_t* p, float f)
{
    uint32_t v;
    memcpy(&v, &f, sizeof v);
    wr32(p, v);
}

// `n` more bytes at the end, zeroed; their offset, or 0 once out of memory
// (no chunk starts at 0 but the container's header, written first).
static size_t grow(Out* o, size_t n)
{
    size_t at = o->len;
    if (o->failed) return 0;
    if (o->len + n > o->cap) {
        size_t   cap = o->cap ? o->cap : 1u << 16;
        uint8_t* p;
        while (cap < o->len + n) cap *= 2;
        p = (uint8_t*)realloc(o->p, cap);
        if (!p) {
            o->failed = 1;
            return 0;
        }
        o->p   = p;
        o->cap = cap;
    }
    memset(o->p + at, 0, n);
    o->len += n;
    return at;
}

// A chunk's header with its size still 0; close() writes it.
static size_t open_chunk(Out* o, uint32_t type)
{
    size_t at = grow(o, 8);
    if (!o->failed) wr32(o->p + at, type);
    return at;
}

static void close_chunk(Out* o, size_t hdr)
{
    if (!o->failed) wr32(o->p + hdr + 4, (uint32_t)(o->len - hdr - 8));
}

// A whole chunk; the payload's offset.
static size_t put_chunk(Out* o, uint32_t type, const uint8_t* payload,
                        uint32_t size)
{
    size_t hdr = open_chunk(o, type);
    size_t at  = grow(o, size);
    if (o->failed) return 0;
    if (size) memcpy(o->p + at, payload, size);
    close_chunk(o, hdr);
    return at;
}

// A text with `room` characters: its 100 bytes of fields, MaxChars set to
// the room, and its string, cut to fit if need be. flailertext_set_string
// writes up to MaxChars, so the chunk has exactly that many.
static size_t put_text(Out* o, const uint8_t* payload, uint32_t size,
                       uint32_t room)
{
    size_t   hdr = open_chunk(o, CHUNK_TEXT);
    size_t   at  = grow(o, TEXT_STRING + room);
    uint32_t old = size > TEXT_STRING ? size - TEXT_STRING : 0;
    if (o->failed) return 0;
    memcpy(o->p + at, payload, TEXT_STRING);
    memcpy(o->p + at + TEXT_STRING, payload + TEXT_STRING,
           old < room ? old : room);
    o->p[at + TEXT_STRING + room - 1] = 0;
    wr32(o->p + at + TEXT_MAX_CHARS, room);
    close_chunk(o, hdr);
    return at;
}

static void set_string(Out* o, size_t at, const char* s)
{
    uint32_t room = rd32(o->p + at + TEXT_MAX_CHARS);
    if (o->failed) return;
    memset(o->p + at + TEXT_STRING, 0, room);
    strncpy((char*)o->p + at + TEXT_STRING, s, room - 1);
    wr32(o->p + at + TEXT_LANGUAGE, 0);
}

static void set_name(Out* o, size_t at, uint32_t hash, const char* name)
{
    if (o->failed) return;
    wr32(o->p + at + OBJ_NAME_HASH, hash);
    memset(o->p + at + OBJ_NAME, 0, 24);
    strncpy((char*)o->p + at + OBJ_NAME, name, 23);
}

static uint32_t screen_hash(const uint8_t* payload, uint32_t size)
{
    BChunkIter it;
    bchunk_begin(&it, payload, 0, size);
    while (bchunk_next(&it))
        if (it.type == BUI_CHUNK_SCREENDEF && it.size >= 40)
            return rd32(it.payload + SCREEN_NAME);
    return BUI_HASH_NONE;
}

// The object of a screen container named `hash`, or NULL. `big` picks,
// among several, the one with the largest ScaleY.
static const uint8_t* find_object(const uint8_t* payload, uint32_t size,
                                  uint32_t hash, int big, uint32_t* outSize)
{
    const uint8_t* best = NULL;
    BChunkIter     it;
    bchunk_begin(&it, payload, 0, size);
    while (bchunk_next(&it)) {
        if (it.type == BUI_CHUNK_SCREENDEF || it.size < 64) continue;
        if (rd32(it.payload + OBJ_NAME_HASH) != hash) continue;
        if (best && !(big && rdf(it.payload + OBJ_SCALE_Y)
                                 > rdf(best + OBJ_SCALE_Y)))
            continue;
        best = it.payload;
        if (outSize) *outSize = it.size;
    }
    return best;
}

// Retail's three rows, the last two of which the new rows are copied from,
// and the filler under them.
typedef struct {
    const uint8_t *item1, *item2, *item3, *mask1, *mask2, *mask3, *fill;
    uint32_t       s3, sm3, sf;
} MenuParts;

// The row `row` below MENUITEM_3 (1 the first): MENUITEM_3 as far below
// itself, at MENUITEM_2's X (3's is two pixels right of 1's and 2's);
// MI_3_MASK as far below itself; and the rest of the filler under the
// mask, down to where the filler ends. Each stays in its group, so it
// slides in with the rest, and is named and shown as asked.
static int put_row(Out* o, const MenuParts* m, int row, Row* r,
                   uint32_t itemHash, const char* itemName,
                   uint32_t maskHash, const char* maskName,
                   uint32_t fillHash, const char* fillName, int shown)
{
    float rowY   = rdf(m->item3 + OBJ_Y)
                 + (rdf(m->item3 + OBJ_Y) - rdf(m->item2 + OBJ_Y)) * row;
    float maskY  = rdf(m->mask3 + OBJ_Y)
                 + (rdf(m->mask3 + OBJ_Y) - rdf(m->mask2 + OBJ_Y)) * row;
    float fillY  = maskY + rdf(m->mask3 + OBJ_SCALE_Y) * MASK_UNIT;
    float bottom = rdf(m->fill + OBJ_Y)
                 + rdf(m->fill + OBJ_SCALE_Y) * MASK_UNIT;

    r->item = put_text(o, m->item3, m->s3, rd32(m->item3 + TEXT_MAX_CHARS));
    set_name(o, r->item, itemHash, itemName);
    if (o->failed) return 0;
    wrf(o->p + r->item + OBJ_X, rdf(m->item2 + OBJ_X));
    wrf(o->p + r->item + OBJ_Y, rowY);
    o->p[r->item + OBJ_VISIBILITY] = (uint8_t)shown;

    r->mask = put_chunk(o, BUI_CHUNK_BITMAP, m->mask3, m->sm3);
    set_name(o, r->mask, maskHash, maskName);
    if (o->failed) return 0;
    wrf(o->p + r->mask + OBJ_Y, maskY);
    o->p[r->mask + OBJ_VISIBILITY] = (uint8_t)shown;

    r->fill = put_chunk(o, BUI_CHUNK_BITMAP, m->fill, m->sf);
    set_name(o, r->fill, fillHash, fillName);
    if (o->failed) return 0;
    wrf(o->p + r->fill + OBJ_Y, fillY);
    wrf(o->p + r->fill + OBJ_SCALE_Y, (bottom - fillY) / MASK_UNIT);
    o->p[r->fill + OBJ_VISIBILITY] = (uint8_t)shown;
    return 1;
}

// NEW_MAIN_MENU as it is, but for its bottom filler cut to a separator,
// then six objects after its own, and its NumObjects up by six: Local
// Wireless's row, shown, and the debug menu's under it, hidden. The
// fourth and fifth slots' rows and fillers, which the layout then moves:
// Local Wireless goes up into the third slot, Options down into the
// fourth. Retail's rows kept in sRows, and the slots.
static int put_main_menu(Out* o, const uint8_t* payload, uint32_t size)
{
    MenuParts  m;
    uint32_t   s2 = 0, sm2 = 0;
    size_t     hdr, def = 0, filler = 0, label[3] = {0}, mask[3] = {0};
    BChunkIter it;
    int        i;

    memset(&m, 0, sizeof m);
    m.item1 = find_object(payload, size, MENUITEM(1), 0, NULL);
    m.item2 = find_object(payload, size, MENUITEM(2), 0, &s2);
    m.item3 = find_object(payload, size, MENUITEM(3), 0, &m.s3);
    m.mask1 = find_object(payload, size, MI_1_MASK, 0, NULL);
    m.mask2 = find_object(payload, size, MI_2_MASK, 0, &sm2);
    m.mask3 = find_object(payload, size, MI_3_MASK, 0, &m.sm3);
    m.fill  = find_object(payload, size, BOTTOM_MASK, 1, &m.sf);
    if (!m.item1 || !m.item2 || !m.item3 || !m.mask1 || !m.mask2
        || !m.mask3 || !m.fill)
        return 0;

    hdr = open_chunk(o, BUI_CHUNK_SCREEN);
    bchunk_begin(&it, payload, 0, size);
    while (bchunk_next(&it)) {
        size_t at = put_chunk(o, it.type, it.payload, it.size);
        if (it.type == BUI_CHUNK_SCREENDEF) def = at;
        if (it.payload == m.fill) filler = at;
        if (it.payload == m.item1) label[0] = at;
        if (it.payload == m.item2) label[1] = at;
        if (it.payload == m.item3) label[2] = at;
        if (it.payload == m.mask1) mask[0] = at;
        if (it.payload == m.mask2) mask[1] = at;
        if (it.payload == m.mask3) mask[2] = at;
    }
    if (o->failed || !def || !filler) return 0;
    o->p[def + SCREEN_NUM_OBJS] += 6;     // 31 on disc, so no carry
    wrf(o->p + filler + OBJ_SCALE_Y, SEPARATOR_SCALE);

    // Local Wireless (TASKS 63): its LanguageID the port's (portlang.h),
    // the inline string the same in English.
    if (!put_row(o, &m, 1, &sWireless, BGF_ITEM_MENUITEM_4, "MENUITEM_4",
                 MI_4_MASK, "MI_4_MASK", DEBUGMENU_FILL_4, "PORT_FILL_4", 1))
        return 0;
    set_string(o, sWireless.item, "Local Wireless");
    wr32(o->p + sWireless.item + TEXT_LANGUAGE, PORTLANG_LOCAL_WIRELESS);

    // The debug menu, under names the menu does not look for until it is
    // shown.
    if (!put_row(o, &m, 2, &sDebug, DEBUGMENU_ITEM_HIDDEN, "MENUITEM_5",
                 DEBUGMENU_MASK_HIDDEN, "MI_5_MASK", DEBUGMENU_FILL_5,
                 "PORT_FILL_5", 0))
        return 0;
    set_string(o, sDebug.item, "Debug Menu");
    close_chunk(o, hdr);
    if (o->failed) return 0;

    // The slots: retail's three rows, then the two put_row put below them.
    for (i = 0; i < 3; i++) {
        sLabelY[i] = rdf(o->p + label[i] + OBJ_Y);
        sMaskY[i]  = rdf(o->p + mask[i] + OBJ_Y);
    }
    sLabelY[3] = rdf(o->p + sWireless.item + OBJ_Y);
    sMaskY[3]  = rdf(o->p + sWireless.mask + OBJ_Y);
    sLabelY[4] = rdf(o->p + sDebug.item + OBJ_Y);
    sMaskY[4]  = rdf(o->p + sDebug.mask + OBJ_Y);
    sFill[2]   = filler;
    sFill[3]   = sWireless.fill;
    sFill[4]   = sDebug.fill;
    sBottom    = rdf(m.fill + OBJ_Y) + rdf(m.fill + OBJ_SCALE_Y) * MASK_UNIT;

    sRows[0] = (MainRow){MENUITEM(1), label[0], mask[0]};
    sRows[1] = (MainRow){MENUITEM(2), label[1], mask[1]};
    sRows[2] = (MainRow){BGF_ITEM_MENUITEM_4, sWireless.item, sWireless.mask};
    sRows[3] = (MainRow){MENUITEM(3), label[2], mask[2]};
    sNumRows = 4;
    return 1;
}

// The rows from sTop in the slots, the rest hidden, label and mask: a
// row's label and mask Y are its slot's, its X its own (Options' stays two
// pixels right of the rest, as retail has it). The masks shown but the
// highlighted row's. Under the slots in use, each filler a separator but
// the last row's, which runs down to the panel's bottom; none under a slot
// not in use.
static void layout(void)
{
    int n = sNumRows < sSlots ? sNumRows : sSlots;
    int i;

    if (!sBuf || !sNumRows) return;
    if (sTop > sNumRows - n) sTop = sNumRows - n;
    if (sTop < 0) sTop = 0;
    for (i = 0; i < sNumRows; i++) {
        const MainRow* r    = &sRows[i];
        int            slot = i - sTop;
        int            in   = slot >= 0 && slot < n;
        if (in) {
            wrf(sBuf + r->label + OBJ_Y, sLabelY[slot]);
            wrf(sBuf + r->mask + OBJ_Y, sMaskY[slot]);
        }
        sBuf[r->label + OBJ_VISIBILITY] = (uint8_t)in;
        sBuf[r->mask + OBJ_VISIBILITY]  = (uint8_t)(in && i != sCurrent);
    }
    for (i = 0; i < MAIN_SLOTS; i++) {
        size_t fill = sFill[i];
        if (!fill) continue;
        sBuf[fill + OBJ_VISIBILITY] = (uint8_t)(i < n);
        wrf(sBuf + fill + OBJ_SCALE_Y,
            i < n - 1 ? SEPARATOR_SCALE
                      : (sBottom - rdf(sBuf + fill + OBJ_Y)) / MASK_UNIT);
    }
}

static int main_row(uint32_t itemHash)
{
    int i;
    for (i = 0; i < sNumRows; i++)
        if (sRows[i].item == itemHash) return i;
    return -1;
}

static int left_out(uint32_t hash, int rows)
{
    for (size_t i = 0; i < sizeof kLeftOut / sizeof kLeftOut[0]; i++)
        if (kLeftOut[i] == hash) return 1;
    return (hash > MENUITEM(rows) && hash <= MENUITEM(7))
           || (hash > LINE(rows) && hash <= LINE(7));
}

// Be The Cop Setup again, as one of the port's own screens: renamed and
// titled, its eighth row, the rows past `rows` and the blooms' texts gone,
// and the texts given room.
static int put_debug_screen(Out* o, const uint8_t* payload, uint32_t size,
                            uint32_t name, const char* title, int rows)
{
    size_t     hdr = open_chunk(o, BUI_CHUNK_SCREEN);
    size_t     def = 0;
    uint32_t   count = 0;
    BChunkIter it;

    bchunk_begin(&it, payload, 0, size);
    while (bchunk_next(&it)) {
        uint32_t hash;
        size_t   at;

        if (it.type == BUI_CHUNK_SCREENDEF) {
            def = put_chunk(o, it.type, it.payload, it.size);
            if (!o->failed) wr32(o->p + def + SCREEN_NAME, name);
            continue;
        }
        hash = it.size >= 64 ? rd32(it.payload + OBJ_NAME_HASH) : 0;
        if (left_out(hash, rows)) continue;
        count++;
        if (it.type != CHUNK_TEXT || it.size < TEXT_STRING) {
            put_chunk(o, it.type, it.payload, it.size);
        } else if (hash >= MENUITEM(1) && hash <= MENUITEM(7)) {
            put_text(o, it.payload, it.size, LABEL_ROOM);
        } else if (hash >= LINE(1) && hash <= LINE(7)) {
            put_text(o, it.payload, it.size, VALUE_ROOM);
        } else if (hash == HELP) {
            put_text(o, it.payload, it.size, HELP_ROOM);
        } else if (hash == TITLE) {
            at = put_text(o, it.payload, it.size, TITLE_ROOM);
            set_string(o, at, title);
        } else {
            put_chunk(o, it.type, it.payload, it.size);
        }
    }
    if (o->failed || !def) return 0;
    o->p[def + SCREEN_NUM_OBJS]     = (uint8_t)count;
    o->p[def + SCREEN_NUM_OBJS + 1] = (uint8_t)(count >> 8);
    close_chunk(o, hdr);
    return !o->failed;
}

uint8_t* debugmenu_patch_frontend(const uint8_t* data, size_t len,
                                  size_t* outLen)
{
    Out            o;
    uint32_t       size = 0;
    const uint8_t* flailer, *source = NULL;
    uint32_t       sourceSize = 0;
    size_t         hdr;
    int            mainMenu = 0;
    BChunkIter     it;

    memset(&o, 0, sizeof o);
    memset(&sWireless, 0, sizeof sWireless);
    memset(&sDebug, 0, sizeof sDebug);
    memset(sFill, 0, sizeof sFill);
    sBuf      = NULL;
    sRevealed = 0;
    sNumRows  = 0;
    sTop      = 0;
    sCurrent  = -1;
    flailer = bchunk_find(data, 0, len, BUI_CHUNK_FLAILER, &size);
    if (!flailer) return NULL;

    hdr = open_chunk(&o, BUI_CHUNK_FLAILER);
    bchunk_begin(&it, flailer, 0, size);
    while (bchunk_next(&it)) {
        uint32_t screen = it.type == BUI_CHUNK_SCREEN
                              ? screen_hash(it.payload, it.size)
                              : BUI_HASH_NONE;
        if (it.size & 3u) {           // would leave what follows unaligned
            free(o.p);
            return NULL;
        }
        if (screen == MAIN_MENU && !mainMenu) {
            if (!put_main_menu(&o, it.payload, it.size)) break;
            mainMenu = 1;
            continue;
        }
        if (screen == DEBUGMENU_SOURCE && !source) {
            source     = it.payload;
            sourceSize = it.size;
        }
        put_chunk(&o, it.type, it.payload, it.size);
    }
    if (!o.failed && mainMenu && source) {
        put_debug_screen(&o, source, sourceSize, DEBUGMENU_SCREEN,
                         "Debug Menu", DEBUGMENU_ROWS);
        put_debug_screen(&o, source, sourceSize, DEBUGMENU_RACE_SCREEN,
                         "Debug Race", 7);
    }
    close_chunk(&o, hdr);

    if (o.failed || !mainMenu || !source || !sDebug.item) {
        free(o.p);
        memset(&sWireless, 0, sizeof sWireless);
        memset(&sDebug, 0, sizeof sDebug);
        sNumRows = 0;
        return NULL;
    }
    sBuf = o.p;
    layout();
    if (outLen) *outLen = o.len;
    return o.p;
}

int debugmenu_reveal(void)
{
    if (!sBuf || !sDebug.item || sRevealed || sNumRows == MAIN_ROWS)
        return 0;
    wr32(sBuf + sDebug.item + OBJ_NAME_HASH, BGF_ITEM_MENUITEM_5);
    wr32(sBuf + sDebug.mask + OBJ_NAME_HASH, MI_5_MASK);
    sRows[sNumRows++] = (MainRow){BGF_ITEM_MENUITEM_5, sDebug.item,
                                  sDebug.mask};
    sRevealed = 1;
    layout();
    return 1;
}

int debugmenu_revealed(void)
{
    return sRevealed;
}

int debugmenu_main_rank(uint32_t itemHash)
{
    int i = main_row(itemHash);
    return i < 0 ? MAIN_ROWS : i;
}

int debugmenu_main_show(uint32_t itemHash)
{
    int i = main_row(itemHash);
    int n = sNumRows < sSlots ? sNumRows : sSlots;

    if (!sBuf || i < 0) return -1;
    if (i < sTop) sTop = i;
    else if (i >= sTop + n) sTop = i - n + 1;
    sCurrent = i;
    layout();
    return sTop;
}

void debugmenu_main_tick(void)
{
    layout();
}

void debugmenu_main_set_slots(int slots)
{
    sSlots = slots < 3 ? 3 : slots > MAIN_SLOTS ? MAIN_SLOTS : slots;
    layout();
}
