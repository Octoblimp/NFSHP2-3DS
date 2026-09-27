#ifndef NFSHP2_GEOMETRY_H
#define NFSHP2_GEOMETRY_H

// bWare eSolid geometry: the 0x80034000 chunk tree, and the VU1 packets
// inside it turned into triangle lists.
//
// Everything this reads is specified in docs/formats/solid-geometry.md, which
// is where the addresses and the reasoning live. The short version:
//
//   * a solid list is a chunk tree -- one 0x00034003 eSolid header, one
//     0x00034004 table of 64-byte eStripEntry, and one 0x00034005 blob
//     holding every strip's VU1 packet back to back;
//   * a strip's packet is raw VIF1 code, a run of UNPACKs then MSCAL. Replay
//     the UNPACKs into an image of quadwords and the vertices are readable
//     by VU address;
//   * XYZ, ST and the normals are stored transposed in groups of four
//     vertices, so vertex v lives in lane v % 4 of three consecutive quads;
//   * a per-vertex ADC bitfield says which vertices do not kick a triangle,
//     and a suppressed pair restarts both the strip and its winding.
//
// Nothing here allocates. A strip is bounded at 30 vertices by the format --
// GetElementXYZ cannot address more -- so GeoStrip is a fixed-size scratch
// buffer the caller owns and reuses, which is what makes it possible to walk
// a 1,135-solid track bundle on a handheld at all. The solid *index* is the
// caller's array too; geo_open fills it in and never keeps a pointer to
// anything but the caller's own buffer.

#include <stddef.h>
#include <stdint.h>

// eStripData addresses the vertex fields with a 48-byte stride per group of
// four, and the VU1 microprogram's input buffer is what bounds it. No strip
// on the disc exceeds 30.
#define GEO_MAX_STRIP_VERTS 30
#define GEO_MAX_STRIP_TRIS  (GEO_MAX_STRIP_VERTS - 2)

// eSolid::Name is a fixed 24-byte field and is not always NUL terminated.
#define GEO_NAME_LEN        24

// eSolidListHeader is 52 bytes of authoring path -- "..\Psx2\CD\CARS\..." --
// worth keeping because it names which build the data came from.
#define GEO_SOURCE_LEN      52

typedef struct {
    float    pos[3];
    float    st[2];
    // RGBA5551 exactly as the V4-5 unpack stored it: R in bits 0..4, G in
    // 5..9, B in 10..14, A in bit 15. Kept packed rather than expanded so
    // nothing is lost on the way through.
    uint16_t colour;
    // Signed bytes: a unit vector quantised onto a radius-127 sphere, so the
    // integer length is 125..127. A few dozen across the car set are exactly
    // zero, which is in the data. All zero when the strip carries no normal
    // field at all, which is about 17% of them -- check hasNormals, do not
    // test for a zero vector.
    int8_t   normal[3];
} GeoVertex;

typedef struct {
    int       numVerts;
    int       numTris;
    int       hasNormals;
    int       lightMaterial;            // -1 = none
    // The ADC quadword as read, low word first. Diagnostic only: the decoded
    // bits are already applied to tri[].
    uint32_t  adc[4];
    GeoVertex vert[GEO_MAX_STRIP_VERTS];
    uint8_t   tri[GEO_MAX_STRIP_TRIS][3];
} GeoStrip;

// One eStripEntry, decoded. The per-strip counts are the truth; eSolid's own
// NumPolys is stale for 19 of the disc's 1,465 solids.
typedef struct {
    int      numVerts;
    int      numPolys;
    // Indexes this solid's texture table. 25 strips on the disc carry
    // exactly numTextures here -- one past the end -- which is the
    // untextured sentinel; a caller must range-check rather than index.
    int      textureNumber;
    int      lightMaterial;             // -1 = none
    int      dataQWordSize;             // * 16 = this strip's slice
    uint16_t texWidthScale;             // 1.15 fixed point, 32768 == 1.0
    uint16_t texHeightScale;
    uint16_t flags;
    uint8_t  polyGroup;
    float    aabbMin[3];
    float    aabbMax[3];
} GeoStripEntry;

typedef struct {
    uint32_t       nameHash;
    uint32_t       version;
    char           name[GEO_NAME_LEN + 1];
    uint16_t       flags;
    uint16_t       stripFlags;
    int            numStrips;
    int            numPolys;            // stale on 19 solids; see above
    int            numVerts;
    int            numOriginalVerts;
    float          aabbMin[3];
    float          aabbMax[3];
    float          pivot[16];
    int            numTextures;
    int            numLightMaterials;
    // Into the caller's buffer, not copies. 8 bytes per entry, a bStringHash
    // name followed by a pointer the engine fixes up at load time; the
    // pointer half is meaningless in a file.
    const uint8_t* textureTable;
    const uint8_t* lightMaterialTable;
    const uint8_t* stripEntries;        // 0x00034004 payload, past the filler
    const uint8_t* packet;              // 0x00034005 payload, past the filler
    size_t         packetSize;
    // The 0x00034003 payload itself, past the filler: the 192-byte eSolid
    // as it sits in the file, which is what LoaderSolidList links onto
    // SolidList in place and what an eModel's Solid points at.
    const uint8_t* header;
} GeoSolid;

typedef struct {
    char      source[GEO_SOURCE_LEN + 1];
    GeoSolid* solid;
    int       numSolids;                // how many are in solid[]
    int       numSolidsInFile;          // how many the file has; >= numSolids
} GeoSolidList;

enum {
    GEO_OK            =  0,
    GEO_ETRUNCATED    = -1,   // a chunk runs past the end of the buffer
    GEO_EMALFORMED    = -2,   // a chunk is the wrong size for what it holds
    GEO_ENOSOLIDLIST  = -3,   // no 0x80034000 anywhere in the buffer
    GEO_EEND          =  1    // geo_decode_next: no strips left
};

// Index every solid in a buffer that has already been decompressed. `storage`
// is the caller's array of at least `maxSolids`; if the file holds more, the
// first maxSolids are indexed, numSolidsInFile says how many there were, and
// the return is still GEO_OK. Nothing is decoded here beyond the headers, so
// this is cheap enough to run on a whole bundle.
//
// `data` must outlive `list`: the solids point into it.
int geo_open(const void* data, size_t bytes, GeoSolidList* list,
             GeoSolid* storage, int maxSolids);

// One eStripEntry out of the 64-byte table.
int geo_strip_entry(const GeoSolid* solid, int index, GeoStripEntry* out);

// Replay strip `index`'s VU1 packet and read the vertices back out of it.
// `out` is scratch the caller owns; nothing inside it points anywhere.
//
// A strip's slice of the packet is found by adding up the DataQWordSize of
// every strip before it, so this is O(index) and walking a 253-strip solid
// with it is quadratic. Use the cursor below for that; this one is for
// reaching a single strip.
int geo_decode_strip(const GeoSolid* solid, int index, GeoStrip* out);

// Sequential decode, which is what both the harness and a renderer actually
// want: the running offset is carried rather than recomputed.
typedef struct {
    int    index;
    size_t offset;
} GeoStripCursor;

void geo_strip_begin(GeoStripCursor* cursor);

// Decodes the cursor's strip and advances it. Returns GEO_OK, GEO_EEND when
// the solid is exhausted, or a negative GEO_E*.
//
// The cursor advances on every outcome except GEO_EEND -- a strip that will
// not decode is stepped over, not retried -- so the obvious loop
//
//     geo_strip_begin(&cursor);
//     while ((rc = geo_decode_next(solid, &cursor, &strip)) != GEO_EEND) {
//         if (rc != GEO_OK) { report(rc); continue; }
//         ...
//     }
//
// terminates on damaged data instead of spinning. It is worth being explicit
// about because the first version of this did not, and a caller written that
// way printed 72 million lines before anything caught it.
int geo_decode_next(const GeoSolid* solid, GeoStripCursor* cursor,
                    GeoStrip* out);

// R, G, B in 0..31 and A in 0..1, out of the packed halfword.
void geo_unpack_colour(uint16_t rgba5551, uint8_t out[4]);

const char* geo_error(int rc);

#endif
