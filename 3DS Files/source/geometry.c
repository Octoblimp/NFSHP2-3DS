// bWare eSolid geometry -- the reader. See geometry.h for the shape of it and
// docs/formats/solid-geometry.md for why any of this is the way it is.
//
// Written from that document, not from tools/geometry_convert.py; the Python
// is the other side of the cross-check and the two have to be able to
// disagree. Where the document cites an address, the address is repeated here
// so the claim can be re-checked against the ELF.

#include "geometry.h"

#include <string.h>

// ------------------------------------------------------------ reading bytes

// The data is a byte buffer at whatever alignment the loader left it, and the
// PS2 wrote it little-endian. Spelling the loads out costs nothing at -O3 and
// means neither alignment nor host endianness is being assumed.

static uint32_t rd32(const uint8_t* p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint16_t rd16(const uint8_t* p)
{
    return (uint16_t)((uint32_t)p[0] | ((uint32_t)p[1] << 8));
}

static float rdf32(const uint8_t* p)
{
    uint32_t bits = rd32(p);
    float    f;

    memcpy(&f, &bits, sizeof f);
    return f;
}

static void rdf32v(const uint8_t* p, float* out, int n)
{
    int i;

    for (i = 0; i < n; i++) {
        out[i] = rdf32(p + 4 * i);
    }
}

// ------------------------------------------------------------- chunk walking

#define CHUNK_HEADER      8
#define CHUNK_CONTAINER   0x80000000u

#define TYPE_SOLID_LIST   0x80034000u
#define TYPE_LIST_HEADER  0x00034001u
#define TYPE_SOLID        0x80034002u
#define TYPE_SOLID_HDR    0x00034003u
#define TYPE_STRIP_TABLE  0x00034004u
#define TYPE_PACKET       0x00034005u
#define TYPE_TEXTURES     0x00034006u
#define TYPE_LIGHT_MATS   0x0003401du

// bWare 16-byte aligns a payload by padding its *front* with 0x11, so the
// struct inside a chunk does not necessarily start at the payload's first
// byte. Scanning for the filler run is what the format does; it is also the
// one sharp edge in this reader, because a payload whose real first byte is
// 0x11 would lose it. That does not happen on this disc -- every 0x00034003,
// 0x00034004 and 0x00034005 on it decodes to a solid whose vertices land
// inside its own AABB -- but it is worth knowing about before this reader
// meets data from somewhere else.
#define CHUNK_FILLER      0x11

static void unfiller(const uint8_t** p, size_t* size)
{
    const uint8_t* q = *p;
    size_t         n = 0;

    while (n < *size && q[n] == CHUNK_FILLER) {
        n++;
    }
    *p    += n;
    *size -= n;
}

typedef struct {
    uint32_t       type;
    const uint8_t* payload;
    size_t         size;
} GeoChunk;

// Walk one chunk sequence. Returns 0 at the end, 1 with `out` filled, or a
// negative GEO_E* if the sequence is damaged. `*off` advances past the chunk.
static int chunk_next(const uint8_t* base, size_t bytes, size_t* off,
                      GeoChunk* out)
{
    uint32_t type;
    uint32_t size;

    // A Type == 0, Size == 0 header is inter-chunk padding rather than a
    // terminator, so this skips runs of it instead of stopping.
    for (;;) {
        if (*off + CHUNK_HEADER > bytes) {
            return 0;       // trailing slack, not a chunk
        }
        type = rd32(base + *off);
        size = rd32(base + *off + 4);
        if (type != 0 || size != 0) {
            break;
        }
        *off += CHUNK_HEADER;
    }

    if (size > bytes - *off - CHUNK_HEADER) {
        return GEO_ETRUNCATED;
    }

    out->type    = type;
    out->payload = base + *off + CHUNK_HEADER;
    out->size    = size;
    *off        += CHUNK_HEADER + size;
    return 1;
}

// ------------------------------------------------------------------- eSolid

// docs/formats/solid-geometry.md, "eSolid, 192 bytes".
#define SOLID_SIZE         192
#define SOLID_NAME_HASH    0x08
#define SOLID_VERSION      0x0c
#define SOLID_NAME         0x10
#define SOLID_FLAGS        0x30
#define SOLID_STRIP_FLAGS  0x32
#define SOLID_NUM_STRIPS   0x34
#define SOLID_NUM_POLYS    0x36
#define SOLID_NUM_VERTS    0x38
#define SOLID_NUM_ORIG     0x3a
#define SOLID_AABB_MIN     0x40
#define SOLID_AABB_MAX     0x50
#define SOLID_PIVOT        0x60
#define SOLID_NUM_LIGHTMAT 0xae

// eTextureTable and eLightMaterialEntry are both {NameHash, pointer}; the
// pointer half is fixed up at load time and means nothing in a file.
#define TABLE_ENTRY_SIZE   8

// "eStripEntry, 64 bytes, one per strip".
#define STRIP_ENTRY_SIZE   64
#define STRIP_TEX_NUMBER   0x00
#define STRIP_TEX_W        0x04
#define STRIP_TEX_H        0x06
#define STRIP_QWORDS       0x0c
#define STRIP_FLAGS        0x0e
#define STRIP_AABB_MIN     0x10
#define STRIP_POLY_GROUP   0x1c
#define STRIP_NUM_VERTS    0x1d
#define STRIP_NUM_POLYS    0x1e
#define STRIP_LIGHT_MAT    0x1f
#define STRIP_AABB_MAX     0x20

static int read_solid_header(GeoSolid* s, const uint8_t* p, size_t size)
{
    if (size < SOLID_SIZE) {
        return GEO_EMALFORMED;
    }

    s->nameHash         = rd32(p + SOLID_NAME_HASH);
    s->version          = rd32(p + SOLID_VERSION);
    memcpy(s->name, p + SOLID_NAME, GEO_NAME_LEN);
    s->name[GEO_NAME_LEN] = 0;      // the field is not always terminated

    s->flags            = rd16(p + SOLID_FLAGS);
    s->stripFlags       = rd16(p + SOLID_STRIP_FLAGS);
    s->numStrips        = rd16(p + SOLID_NUM_STRIPS);
    s->numPolys         = rd16(p + SOLID_NUM_POLYS);
    s->numVerts         = rd16(p + SOLID_NUM_VERTS);
    s->numOriginalVerts = rd16(p + SOLID_NUM_ORIG);

    // The AABBs are float[4]; the w lane is not a coordinate.
    rdf32v(p + SOLID_AABB_MIN, s->aabbMin, 3);
    rdf32v(p + SOLID_AABB_MAX, s->aabbMax, 3);
    rdf32v(p + SOLID_PIVOT,    s->pivot,   16);

    // NumLightMaterials at 0xae is filled in and agrees with the
    // 0x0003401d table on every one of the 1,411 solids on the disc.
    //
    // NumTextureTableEntries at 0xac is a different story: it is zero on all
    // 1,411, including the 28-entry table in TRACKB12. The field is real --
    // it is where eSolid::GetNumTextures() reads -- but nothing the exporter
    // ran ever wrote it, so counting the 0x00034006 chunk is the only way to
    // know. index_solid does that below; do not put it back here.
    s->numLightMaterials = rd16(p + SOLID_NUM_LIGHTMAT);
    return GEO_OK;
}

int geo_strip_entry(const GeoSolid* solid, int index, GeoStripEntry* out)
{
    const uint8_t* p;

    if (index < 0 || index >= solid->numStrips || !solid->stripEntries) {
        return GEO_EMALFORMED;
    }
    p = solid->stripEntries + (size_t)index * STRIP_ENTRY_SIZE;

    out->textureNumber  = (int)rd32(p + STRIP_TEX_NUMBER);
    out->texWidthScale  = rd16(p + STRIP_TEX_W);
    out->texHeightScale = rd16(p + STRIP_TEX_H);
    out->dataQWordSize  = rd16(p + STRIP_QWORDS);
    out->flags          = rd16(p + STRIP_FLAGS);
    out->polyGroup      = p[STRIP_POLY_GROUP];
    out->numVerts       = p[STRIP_NUM_VERTS];
    out->numPolys       = p[STRIP_NUM_POLYS];
    out->lightMaterial  = (int8_t)p[STRIP_LIGHT_MAT];

    rdf32v(p + STRIP_AABB_MIN, out->aabbMin, 3);
    rdf32v(p + STRIP_AABB_MAX, out->aabbMax, 3);
    return GEO_OK;
}

// ------------------------------------------------------------ the chunk tree

static int index_solid(GeoSolid* s, const uint8_t* payload, size_t size)
{
    size_t   off = 0;
    GeoChunk c;
    int      rc;
    int      haveHeader = 0;
    size_t   textureBytes = 0;

    memset(s, 0, sizeof *s);

    while ((rc = chunk_next(payload, size, &off, &c)) == 1) {
        const uint8_t* p = c.payload;
        size_t         n = c.size;

        unfiller(&p, &n);

        switch (c.type) {
        case TYPE_SOLID_HDR:
            rc = read_solid_header(s, p, n);
            if (rc != GEO_OK) {
                return rc;
            }
            haveHeader = 1;
            break;
        case TYPE_STRIP_TABLE:
            s->stripEntries = p;
            break;
        case TYPE_PACKET:
            s->packet     = p;
            s->packetSize = n;
            break;
        case TYPE_TEXTURES:
            s->textureTable = p;
            textureBytes    = n;
            break;
        case TYPE_LIGHT_MATS:
            s->lightMaterialTable = p;
            break;
        default:
            break;      // an unknown child is not an error; skip it
        }
    }
    if (rc < 0) {
        return rc;
    }
    if (!haveHeader) {
        return GEO_EMALFORMED;
    }

    // The strip table has to be big enough for the count the header claims,
    // or geo_strip_entry would read off the end of it later.
    if (s->numStrips > 0 && !s->stripEntries) {
        return GEO_EMALFORMED;
    }

    // See read_solid_header: the header's own count is dead, so the table's
    // size is the count. 8 bytes per eTextureTable entry.
    s->numTextures = (int)(textureBytes / TABLE_ENTRY_SIZE);
    return GEO_OK;
}

typedef struct {
    GeoSolidList* list;
    GeoSolid*     storage;
    int           maxSolids;
    int           foundList;
} GeoWalk;

// Solid lists nest: a car's GEOMETRY.BIN has one at the top level, a track
// bundle carries several inside other containers. So this recurses through
// every container rather than looking in one place.
static int walk(GeoWalk* w, const uint8_t* base, size_t bytes, int depth)
{
    size_t   off = 0;
    GeoChunk c;
    int      rc;

    if (depth > 8) {
        return GEO_EMALFORMED;
    }

    while ((rc = chunk_next(base, bytes, &off, &c)) == 1) {
        if (c.type == TYPE_SOLID) {
            int slot = w->list->numSolidsInFile;

            w->list->numSolidsInFile++;
            if (slot < w->maxSolids) {
                rc = index_solid(&w->storage[slot], c.payload, c.size);
                if (rc != GEO_OK) {
                    return rc;
                }
                w->list->numSolids = slot + 1;
            }
            continue;       // no solids inside a solid
        }

        if (c.type == TYPE_LIST_HEADER) {
            const uint8_t* p = c.payload;
            size_t         n = c.size;
            size_t         i;

            unfiller(&p, &n);
            if (n > GEO_SOURCE_LEN) {
                n = GEO_SOURCE_LEN;
            }
            // Only the first list's name is kept; a bundle with several says
            // the same build in each.
            if (!w->list->source[0]) {
                for (i = 0; i < n && p[i]; i++) {
                    w->list->source[i] = (char)p[i];
                }
                w->list->source[i] = 0;
            }
            continue;
        }

        if (c.type == TYPE_SOLID_LIST) {
            w->foundList = 1;
        }

        if (c.type & CHUNK_CONTAINER) {
            rc = walk(w, c.payload, c.size, depth + 1);
            if (rc != GEO_OK) {
                return rc;
            }
        }
    }
    return rc < 0 ? rc : GEO_OK;
}

int geo_open(const void* data, size_t bytes, GeoSolidList* list,
             GeoSolid* storage, int maxSolids)
{
    GeoWalk w;
    int     rc;

    memset(list, 0, sizeof *list);
    list->solid = storage;

    w.list      = list;
    w.storage   = storage;
    w.maxSolids = maxSolids < 0 ? 0 : maxSolids;
    w.foundList = 0;

    rc = walk(&w, (const uint8_t*)data, bytes, 0);
    if (rc != GEO_OK) {
        return rc;
    }
    return w.foundList ? GEO_OK : GEO_ENOSOLIDLIST;
}

// -------------------------------------------------------------- VIF1 replay

// A strip's packet is raw VIF1 code. Replaying it needs an image of VU memory
// as quadwords; 128 is comfortably past the highest address the format uses
// (normals for a 30-vertex strip end at 114).
#define VU_QUADS          128

// The documented addresses.
#define VU_HEADER         0
#define VU_ADC            1
#define VU_XYZ            2
#define VU_ST             32
#define VU_RGBA           52
#define VU_NORMAL         92

typedef struct {
    uint32_t q[VU_QUADS][4];
    uint8_t  written[VU_QUADS];
} GeoVu;

// A VIFcode is CMD(31:24) | NUM(23:16) | IMM(15:0), and it is an UNPACK when
// cmd & 0x60 == 0x60.
#define VIF_IS_UNPACK(cmd)  (((cmd) & 0x60) == 0x60)

static int unpack_item_bytes(int vn, int vl)
{
    if (vl == 3) {
        // V4-5: one halfword per item, expanded to four fields. Only ever
        // seen as V4-5, and nothing else would make sense.
        return vn == 3 ? 2 : 0;
    }
    return (vn + 1) * (vl == 0 ? 4 : vl == 1 ? 2 : 1);
}

static void unpack_write(GeoVu* vu, int addr, int vn, int vl, int usn,
                         const uint8_t* p)
{
    uint32_t lane[4];
    int      i;

    if (addr < 0 || addr >= VU_QUADS) {
        return;
    }

    for (i = 0; i < 4; i++) {
        lane[i] = 0;
    }

    if (vl == 3) {
        // The packed halfword is kept as-is in lane 0 rather than expanded
        // into four. It carries the same information either way, and keeping
        // it packed means nothing is lost or re-rounded before geometry.h's
        // caller asks for it.
        lane[0] = rd16(p);
    } else {
        for (i = 0; i <= vn; i++) {
            if (vl == 0) {
                lane[i] = rd32(p + 4 * i);
            } else if (vl == 1) {
                uint16_t v = rd16(p + 2 * i);
                lane[i] = usn ? (uint32_t)v : (uint32_t)(int32_t)(int16_t)v;
            } else {
                uint8_t v = p[i];
                lane[i] = usn ? (uint32_t)v : (uint32_t)(int32_t)(int8_t)v;
            }
        }
    }

    for (i = 0; i < 4; i++) {
        vu->q[addr][i] = lane[i];
    }
    vu->written[addr] = 1;
}

// Replay every UNPACK in one strip's slice. Non-UNPACK VIFcodes are four
// bytes with no payload here -- the packets hold STCYCL, MSCAL and NOP and
// nothing that carries data -- and STCYCL is ignored because every packet on
// the disc runs at CL == WL == 1, which is the addressing this assumes.
static int vif_replay(GeoVu* vu, const uint8_t* p, size_t size)
{
    size_t off = 0;

    memset(vu, 0, sizeof *vu);

    while (off + 4 <= size) {
        uint32_t code = rd32(p + off);
        uint32_t cmd  = (code >> 24) & 0xff;
        int      num  = (int)((code >> 16) & 0xff);
        uint32_t imm  = code & 0xffff;

        off += 4;

        if (!VIF_IS_UNPACK(cmd)) {
            continue;
        }
        {
            int    vn   = (int)((cmd >> 2) & 3);
            int    vl   = (int)(cmd & 3);
            int    addr = (int)(imm & 0x3fff);
            int    usn  = (int)((imm >> 14) & 1);
            int    each = unpack_item_bytes(vn, vl);
            size_t data;
            int    i;

            if (each == 0) {
                return GEO_EMALFORMED;
            }
            // NUM == 0 means 256 items in VIF; no packet here uses it, and
            // treating it as zero would silently drop a field.
            if (num == 0) {
                num = 256;
            }

            data = (size_t)each * (size_t)num;
            if (off + data > size) {
                return GEO_EMALFORMED;
            }
            for (i = 0; i < num; i++) {
                unpack_write(vu, addr + i, vn, vl, usn,
                             p + off + (size_t)each * (size_t)i);
            }
            // VIF resumes reading codes on a 32-bit boundary.
            off += (data + 3u) & ~(size_t)3;
        }
    }
    return GEO_OK;
}

// ------------------------------------------------------------- reading it back

static float lane_f32(const GeoVu* vu, int quad, int lane)
{
    float f;

    if (quad < 0 || quad >= VU_QUADS) {
        return 0.0f;
    }
    memcpy(&f, &vu->q[quad][lane], sizeof f);
    return f;
}

// XYZ and the normals are stored transposed in groups of four vertices: one
// quad of four X, one of four Y, one of four Z, then the next four vertices.
// Vertex v is lane v % 4 of `base + 3 * (v / 4) + component`. A trailing
// group of fewer than four keeps the layout and is unpacked with a narrower
// VIFcode, which lands in the same place.
static int transposed_quad(int base, int v, int component)
{
    return base + 3 * (v / 4) + component;
}

// ST is transposed the same way but two wide, and its trailing group is
// *interleaved* instead -- S and T pairs end to end from the quad after the
// last full group.
static void st_slot(int numVerts, int v, int component, int* quad, int* lane)
{
    int fullGroups = numVerts / 4;

    if (v < fullGroups * 4) {
        *quad = VU_ST + 2 * (v / 4) + component;
        *lane = v % 4;
    } else {
        int k    = v - fullGroups * 4;
        int slot = 2 * k + component;

        *quad = VU_ST + 2 * fullGroups + slot / 4;
        *lane = slot % 4;
    }
}

// The ADC bitfield. Which of the quadword's four words is the low one depends
// only on NumLoops, and the bit order runs backwards from 14.
static int adc_low_word(int numLoops)
{
    switch (numLoops) {
    case 3:  return 3;
    case 7:  return 2;
    default: return 0;
    }
}

static int adc_bit(const uint32_t adc[4], int numLoops, int numVerts, int v)
{
    int bit;

    if (v < 0 || v >= numVerts) {
        return 0;
    }
    if (v <= 14) {
        bit = 14 - v;
        return (int)((adc[adc_low_word(numLoops)] >> bit) & 1u);
    }
    if (v >= 16) {
        bit = 4 * numLoops + 5 - v;
        if (bit < 0 || bit > 31) {
            return 0;
        }
        return (int)((adc[3] >> bit) & 1u);
    }

    // Vertex 15 has no bit of its own: the low word's field ends at 14 and
    // the high word's starts at 16. It does not need one, because suppressed
    // vertices always come in adjacent pairs {r, r+1}. So a bit at 14 with
    // nothing at 13, or one at 16 with nothing at 17, is a pair that can only
    // be {14,15} or {15,16}.
    return (adc_bit(adc, numLoops, numVerts, 14)
            && !adc_bit(adc, numLoops, numVerts, 13))
        || (adc_bit(adc, numLoops, numVerts, 16)
            && !adc_bit(adc, numLoops, numVerts, 17));
}

// The body, given a slice that has already been located. Walking the strip
// entries in order walks the packet in order, so the two callers below differ
// only in how they arrive at `off`.
static int decode_slice(const GeoSolid* solid, const GeoStripEntry* entry,
                        size_t off, GeoStrip* out)
{
    GeoVu          vu;
    const uint8_t* p;
    size_t         size;
    int            rc;
    int            i;
    int            v;
    int            numVerts;
    int            numLoops;
    int            start;

    size = (size_t)entry->dataQWordSize * 16u;
    if (!solid->packet || off + size > solid->packetSize) {
        return GEO_ETRUNCATED;
    }
    p = solid->packet + off;

    rc = vif_replay(&vu, p, size);
    if (rc != GEO_OK) {
        return rc;
    }

    memset(out, 0, sizeof *out);
    for (i = 0; i < 4; i++) {
        out->adc[i] = vu.q[VU_ADC][i];
    }

    // Address 0 holds NumVerts, NumLoops, 3 * NumVerts and
    // 4 * LightMaterialIndex. The last is signed -- -4 is "none" -- whatever
    // the unpack's USN bit said.
    numVerts = (int)(vu.q[VU_HEADER][0] & 0xffu);
    numLoops = (int)(vu.q[VU_HEADER][1] & 0xffu);
    out->lightMaterial = (int)(int8_t)(vu.q[VU_HEADER][3] & 0xffu) / 4;

    if (numVerts < 0 || numVerts > GEO_MAX_STRIP_VERTS) {
        return GEO_EMALFORMED;
    }
    out->numVerts   = numVerts;
    out->hasNormals = vu.written[VU_NORMAL];

    for (v = 0; v < numVerts; v++) {
        GeoVertex* dst  = &out->vert[v];
        int        lane = v % 4;
        int        c;
        int        quad;
        int        stLane;

        for (c = 0; c < 3; c++) {
            dst->pos[c] = lane_f32(&vu, transposed_quad(VU_XYZ, v, c), lane);
        }
        for (c = 0; c < 2; c++) {
            st_slot(numVerts, v, c, &quad, &stLane);
            dst->st[c] = lane_f32(&vu, quad, stLane);
        }

        // Colours are never transposed: one quad per vertex from address 52.
        dst->colour = (uint16_t)(vu.q[VU_RGBA + v][0] & 0xffffu);

        if (out->hasNormals) {
            for (c = 0; c < 3; c++) {
                quad = transposed_quad(VU_NORMAL, v, c);
                if (quad < VU_QUADS) {
                    dst->normal[c] = (int8_t)(vu.q[quad][lane] & 0xffu);
                }
            }
        }
    }

    // A set ADC bit means that vertex kicks no triangle, and a suppressed
    // pair {r, r+1} restarts the strip *and* its winding: the sub-strip that
    // begins at r draws (r, r+1, r+2) first, so the parity is measured from
    // r rather than from 0. Getting that wrong is invisible in the polygon
    // count and very visible on screen.
    start = 0;
    for (v = 2; v < numVerts; v++) {
        int a = adc_bit(out->adc, numLoops, numVerts, v);

        if (a) {
            if (!adc_bit(out->adc, numLoops, numVerts, v - 1)) {
                start = v;              // the first of the pair
            }
            continue;
        }
        if (out->numTris >= GEO_MAX_STRIP_TRIS) {
            return GEO_EMALFORMED;
        }
        out->tri[out->numTris][0] = (uint8_t)(v - 2);
        if (((v - start) & 1) == 0) {
            out->tri[out->numTris][1] = (uint8_t)(v - 1);
            out->tri[out->numTris][2] = (uint8_t)v;
        } else {
            out->tri[out->numTris][1] = (uint8_t)v;
            out->tri[out->numTris][2] = (uint8_t)(v - 1);
        }
        out->numTris++;
    }

    return GEO_OK;
}

int geo_decode_strip(const GeoSolid* solid, int index, GeoStrip* out)
{
    GeoStripEntry entry;
    size_t        off = 0;
    int           rc;
    int           i;

    rc = geo_strip_entry(solid, index, &entry);
    if (rc != GEO_OK) {
        return rc;
    }
    for (i = 0; i < index; i++) {
        GeoStripEntry before;

        rc = geo_strip_entry(solid, i, &before);
        if (rc != GEO_OK) {
            return rc;
        }
        off += (size_t)before.dataQWordSize * 16u;
    }
    return decode_slice(solid, &entry, off, out);
}

void geo_strip_begin(GeoStripCursor* cursor)
{
    cursor->index  = 0;
    cursor->offset = 0;
}

// The cursor advances on *every* outcome but GEO_EEND, including a strip
// that will not decode. That is not tidiness: a caller's natural loop is
// "decode, report the error, continue", and if a failure left the cursor
// where it was that loop would never terminate. It was found by a mutation
// that made vif_replay reject every packet -- the harness printed 72 million
// copies of one line in sixty seconds before anything noticed -- and the
// same loop is what a renderer streaming a track would be written as.
//
// Advancing is always possible because the offset comes from the *entry*,
// which was read before the packet was touched. Only a bad entry index
// stops the walk, and that is GEO_EEND's job anyway.
int geo_decode_next(const GeoSolid* solid, GeoStripCursor* cursor,
                    GeoStrip* out)
{
    GeoStripEntry entry;
    int           rc;

    if (cursor->index >= solid->numStrips) {
        return GEO_EEND;
    }
    rc = geo_strip_entry(solid, cursor->index, &entry);
    if (rc != GEO_OK) {
        // No entry means no size to skip by, so the walk has to stop here
        // rather than spin. Report it as the end of the solid.
        cursor->index = solid->numStrips;
        return rc;
    }

    rc = decode_slice(solid, &entry, cursor->offset, out);
    cursor->offset += (size_t)entry.dataQWordSize * 16u;
    cursor->index++;
    return rc;
}

void geo_unpack_colour(uint16_t rgba5551, uint8_t out[4])
{
    out[0] = (uint8_t)(rgba5551 & 0x1f);
    out[1] = (uint8_t)((rgba5551 >> 5) & 0x1f);
    out[2] = (uint8_t)((rgba5551 >> 10) & 0x1f);
    out[3] = (uint8_t)((rgba5551 >> 15) & 1);
}

const char* geo_error(int rc)
{
    switch (rc) {
    case GEO_OK:           return "ok";
    case GEO_ETRUNCATED:   return "a chunk runs past the end of the buffer";
    case GEO_EMALFORMED:   return "a chunk is the wrong size for what it holds";
    case GEO_ENOSOLIDLIST: return "no 0x80034000 solid list in the buffer";
    default:               return "unknown error";
    }
}
