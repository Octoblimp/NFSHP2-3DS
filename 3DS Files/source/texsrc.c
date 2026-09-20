#include "texsrc.h"

#include <stdlib.h>
#include <string.h>

#include "bchunk.h"

// --------------------------------------------------------------- the walk
//
// The same tree bchunk_walk() walks, but over a file rather than a buffer:
// only the 8-byte headers are read, so indexing a 15 MB pack costs a handful
// of seeks. A Type == 0, Size == 0 header is inter-chunk padding and not a
// terminator, exactly as in bchunk_next().

static bool read_header(FILE* fp, long off, uint32_t* type, uint32_t* size)
{
    uint8_t hdr[8];

    if (fseek(fp, off, SEEK_SET) != 0) {
        return false;
    }
    if (fread(hdr, 1, sizeof hdr, fp) != sizeof hdr) {
        return false;
    }
    *type = bchunk_u32(hdr);
    *size = bchunk_u32(hdr + 4);
    return true;
}

static uint8_t* read_block(FILE* fp, long off, uint32_t size)
{
    uint8_t* buf;

    if (size == 0) {
        return NULL;
    }
    buf = (uint8_t*)malloc(size);
    if (!buf) {
        return NULL;
    }
    if (fseek(fp, off, SEEK_SET) != 0 || fread(buf, 1, size, fp) != size) {
        free(buf);
        return NULL;
    }
    return buf;
}

// One 0xb0300001, whose payload is at `off` and runs `len` bytes.
static void add_pack(TexSource* ts, long off, uint32_t len)
{
    TexSrcPack* p;
    long        end     = off + (long)len;
    long        at      = off;
    long        hdrOff  = 0, infoOff = 0, dataOff = 0;
    uint32_t    hdrSize = 0, infoSize = 0, dataSize = 0;
    long        pad;

    if (ts->numPacks >= TEXSRC_MAX_PACKS) {
        return;
    }

    while (at + 8 <= end) {
        uint32_t type, size;

        if (!read_header(ts->fp, at, &type, &size)) {
            return;
        }
        if (type == 0 && size == 0) {
            at += 8;
            continue;
        }
        if (at + 8 + (long)size > end) {
            break;
        }
        if (type == TEXPACK_HEADER_CHUNK) { hdrOff  = at + 8; hdrSize  = size; }
        if (type == TEXPACK_INFO_CHUNK)   { infoOff = at + 8; infoSize = size; }
        if (type == TEXPACK_DATA_CHUNK)   { dataOff = at + 8; dataSize = size; }
        at += 8 + (long)size;
    }
    if (!infoOff || !dataOff || infoSize < TEXPACK_RECORD_SIZE) {
        return;
    }

    // ImagePlacement and PalettePlacement are relative to the data payload
    // rounded UP to 128, not to the payload itself -- LoaderTexturePack
    // (0x00100830) aligns the loaded address and the bundle is loaded 128-
    // aligned, so aligning the file offset comes out the same. texpack.c has
    // the disassembly; this is the same arithmetic on an offset rather than
    // on a pointer.
    pad = (long)((uint32_t)(-(int32_t)dataOff) & 127u);
    if ((uint32_t)pad >= dataSize) {
        return;
    }

    p = &ts->pack[ts->numPacks];
    memset(p, 0, sizeof *p);
    p->info = read_block(ts->fp, infoOff, infoSize);
    if (!p->info) {
        return;
    }
    p->infoSize = infoSize;
    p->count    = infoSize / TEXPACK_RECORD_SIZE;
    p->dataOff  = dataOff + pad;
    p->dataSize = dataSize - (uint32_t)pad;

    if (hdrOff && hdrSize) {
        uint32_t n = hdrSize < sizeof(p->name) - 1
                   ? hdrSize : (uint32_t)(sizeof(p->name) - 1);
        uint8_t* nm = read_block(ts->fp, hdrOff, n);
        if (nm) {
            memcpy(p->name, nm, n);
            p->name[n] = 0;
            free(nm);
        }
    }
    if (p->count == 0) {
        free(p->info);
        return;
    }
    ts->numPacks++;
}

static void scan(TexSource* ts, long off, long end, int depth)
{
    // A .BUN nests its packs a few containers deep; nothing on the disc goes
    // anywhere near this, and the limit is only here so a damaged file
    // cannot recurse forever.
    if (depth > 8) {
        return;
    }
    while (off + 8 <= end && ts->numPacks < TEXSRC_MAX_PACKS) {
        uint32_t type, size;

        if (!read_header(ts->fp, off, &type, &size)) {
            return;
        }
        if (type == 0 && size == 0) {
            off += 8;
            continue;
        }
        if (off + 8 + (long)size > end) {
            return;
        }
        if (type == TEXPACK_CHUNK) {
            add_pack(ts, off + 8, size);
        } else if (BCHUNK_IS_CONTAINER(type)) {
            scan(ts, off + 8, off + 8 + (long)size, depth + 1);
        }
        off += 8 + (long)size;
    }
}

// ------------------------------------------------------------- open/close

bool texsrc_open(TexSource* ts, const char* path)
{
    long end;

    memset(ts, 0, sizeof *ts);
    snprintf(ts->path, sizeof ts->path, "%s", path);

    ts->fp = fopen(path, "rb");
    if (!ts->fp) {
        return false;
    }
    if (fseek(ts->fp, 0, SEEK_END) != 0) {
        texsrc_close(ts);
        return false;
    }
    end = ftell(ts->fp);
    if (end <= 8) {
        texsrc_close(ts);
        return false;
    }

    scan(ts, 0, end, 0);
    if (ts->numPacks == 0) {
        texsrc_close(ts);
        return false;
    }
    return true;
}

void texsrc_close(TexSource* ts)
{
    int i;

    for (i = 0; i < ts->numPacks; i++) {
        free(ts->pack[i].info);
    }
    if (ts->fp) {
        fclose(ts->fp);
    }
    memset(ts, 0, sizeof *ts);
}

// ---------------------------------------------------------------- lookup
//
// texpack_get() reads nothing but the info table, so a TexPack with its data
// half left null is enough to reuse it rather than re-deriving the record
// layout here.

static void view_of(const TexSrcPack* p, TexPack* tp)
{
    memset(tp, 0, sizeof *tp);
    tp->info     = p->info;
    tp->infoSize = p->infoSize;
    tp->count    = p->count;
}

bool texsrc_find(const TexSource* ts, uint32_t hash, TexSrcEntry* out)
{
    int i;

    for (i = 0; i < ts->numPacks; i++) {
        TexPack tp;

        view_of(&ts->pack[i], &tp);
        if (texpack_find(&tp, hash, &out->info)) {
            out->pack = i;
            return true;
        }
    }
    return false;
}

uint32_t texsrc_count(const TexSource* ts)
{
    uint32_t n = 0;
    int      i;

    for (i = 0; i < ts->numPacks; i++) {
        n += ts->pack[i].count;
    }
    return n;
}

bool texsrc_at(const TexSource* ts, uint32_t index, TexSrcEntry* out)
{
    int i;

    for (i = 0; i < ts->numPacks; i++) {
        if (index < ts->pack[i].count) {
            TexPack tp;

            view_of(&ts->pack[i], &tp);
            out->pack = i;
            return texpack_get(&tp, index, &out->info);
        }
        index -= ts->pack[i].count;
    }
    return false;
}

// ---------------------------------------------------------------- staging

bool texsrc_stage(TexSource* ts, const TexSrcEntry* e, int level,
                  uint8_t** outStage, TexPack* outPack, TexInfo* outInfo)
{
    const TexSrcPack* p;
    const TexInfo*    ti     = &e->info;
    uint32_t          lvlOff = 0, lvlBytes = 0;
    size_t            pixels, total;
    uint8_t*          stage;

    *outStage = NULL;
    if (e->pack < 0 || e->pack >= ts->numPacks) {
        return false;
    }
    p = &ts->pack[e->pack];

    if (!texpack_level(ti, level, NULL, NULL, &lvlOff, &lvlBytes)
        || lvlBytes == 0) {
        return false;
    }

    // Levels are packed base-first, so reading 0..level and leaving pixelOff
    // at zero keeps texpack_level()'s own arithmetic valid inside the
    // staging buffer without rewriting it per level.
    pixels = (size_t)lvlOff + lvlBytes;
    total  = pixels + ti->clutBytes;

    if ((size_t)ti->pixelOff + pixels > p->dataSize) {
        return false;
    }
    if (ti->clutBytes && (size_t)ti->clutOff + ti->clutBytes > p->dataSize) {
        return false;
    }

    stage = (uint8_t*)malloc(total);
    if (!stage) {
        return false;
    }
    if (fseek(ts->fp, p->dataOff + (long)ti->pixelOff, SEEK_SET) != 0
        || fread(stage, 1, pixels, ts->fp) != pixels) {
        free(stage);
        return false;
    }
    if (ti->clutBytes) {
        if (fseek(ts->fp, p->dataOff + (long)ti->clutOff, SEEK_SET) != 0
            || fread(stage + pixels, 1, ti->clutBytes, ts->fp)
               != ti->clutBytes) {
            free(stage);
            return false;
        }
    }

    memset(outPack, 0, sizeof *outPack);
    outPack->data     = stage;
    outPack->dataSize = (uint32_t)total;

    *outInfo          = *ti;
    outInfo->pixelOff = 0;
    outInfo->clutOff  = (uint32_t)pixels;

    *outStage = stage;
    return true;
}

// ---------------------------------------------------------------- upload

#ifdef __3DS__

bool texsrc_upload(TexSource* ts, const TexSrcEntry* e, int level,
                   C3D_Tex* out)
{
    uint8_t* stage = NULL;
    TexPack  tp;
    TexInfo  local;
    bool     ok;

    if (!texsrc_stage(ts, e, level, &stage, &tp, &local)) {
        return false;
    }
    ok = texpack_upload(&tp, &local, level, out);
    free(stage);
    return ok;
}

#endif
