// texturepack -- TexturePack.obj's in-memory half (0x001a1650 ..
// 0x001a1f00, with the list teardowns at 0x001a2d00 .. 0x001a2f08), and
// the loader that feeds it, LoaderTexturePack and UnloaderTexturePack
// (0x00100830 .. 0x00100a60), slot 2 of both chunk tables.
//
// The port follows retail (SLES_507.31), which changed the object: the
// header carries the pack's file name and TexturePack keeps it, every
// field past the name 16 bytes on; AttachTextureTable no longer looks each
// record up; GetTextureInfo takes a third argument, to look in records
// whose pixels are not loaded; and two new functions rename a texture and
// swap two textures' names. Each function below gives both addresses.
// docs/formats/texture-pack.md, "Retail", has the reading.
//
// A 0xb0300001 chunk is a texture pack: a 0x30300002 TexturePackHeader
// (its name and file name, and where the loader leaves the pack), the 0x30300003
// table of TextureInfo records, and the 0x30300004 blob of pixels and
// palettes, whose offsets count from its payload rounded up to 128. The
// loader makes a TexturePack, attaches the table and points each
// record's ImageData and PaletteData into the blob. A 0xb0300100 chunk
// is a pack's flipbooks: a 0x30300101 TextureAnimPackHeader, the
// 0x30300102 TextureAnim table and the 0x30300103 TextureAnimEntry
// table, one entry per frame. Neither loader reads a child's type.
//
// GetTextureInfo is what every other object asks for a texture by: the
// first loaded record of that name, in the order the packs were last
// hit, then the render targets', then with `use_default` the default
// texture, 0x19006835.
//
// Not ported: the streaming half (LoadTextureTableFromFile and the
// LoadedTextureData calls, 0x001a1f00 .. 0x001a28c0, StreamingTexturePack
// and QueuedFile), which LoadGlobalChunks and LoadHudTextures use. What
// the destructor needs of it is here: it waits out a streaming load and
// frees the LoadedTextureData list, both empty for a pack a bundle
// holds. Nor are the two lists' global destructors (0x001a2de0), which
// only run past the end of main.
//
// Where it depends on what is not ported, it goes through a seam:
// eGetRenderTargetTextureInfo (eRenderTarget.obj) and ServiceQueuedFiles
// (the streaming half). A seam left NULL does nothing, and one that
// returns a pointer returns NULL.
//
// Cross-check: tools/texturepack_check.py. Write-up:
// docs/formats/texture-pack.md.

#ifndef TEXTUREPACK_H
#define TEXTUREPACK_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"

struct TexturePack;
struct LoadedTextureData;

// TextureInfo, 164 bytes: one texture. docs/formats/texture-pack.md has
// every field. The loader fills the six from pTexturePack on.
typedef struct TextureInfo {
    bNode     Node;                         //   0
    char      DebugName[24];                //   8
    uint32_t  NameHash;                     //  32
    uint16_t  Width;                        //  36
    uint16_t  Height;                       //  38
    uint8_t   BitDepth;                     //  40
    uint8_t   RenderingOrder;               //  41
    uint16_t  NumPaletteEntries;            //  42
    uint16_t  PaletteVramBlocksRequired;    //  44
    uint16_t  ImageVramBlocksRequired;      //  46
    int32_t   ImagePlacement;               //  48
    int32_t   PalettePlacement;             //  52
    int32_t   ImageSize;                    //  56
    int32_t   PaletteSize;                  //  60
    uint32_t  ImageParentHash;              //  64
    int32_t   BaseImageSize;                //  68
    uint8_t   ShiftWidth;                   //  72
    uint8_t   ShiftHeight;                  //  73
    uint8_t   PixelStorageMode;             //  74
    uint8_t   ClutPixelStorageMode;         //  75
    uint8_t   TilableUV;                    //  76
    uint8_t   ApplyAlphaSorting;            //  77
    uint8_t   TextureFx;                    //  78
    uint8_t   IsAnySemitransparencyFlag;    //  79
    uint8_t   bWriteZ;                      //  80
    uint8_t   pad81;                        //  81
    uint8_t   ImageInfos[7][4];             //  82
    int8_t    NumMipMapLevels;              // 110
    uint8_t   MMag;                         // 111
    uint8_t   MMin;                         // 112
    uint8_t   MipMapL;                      // 113
    uint16_t  MipMapK;                      // 114
    uint8_t   GlossMapInAlpha;              // 116
    uint8_t   Padding;                      // 117
    uint8_t   AlphaBits;                    // 118
    uint8_t   AlphaFix;                     // 119
    uint8_t   UsedFlag;                     // 120
    uint8_t   ScrollType;                   // 121
    uint8_t   pad122[2];                    // 122
    float     ScrollSpeedS;                 // 124
    float     ScrollSpeedT;                 // 128
    float     ScrollTimeStep;               // 132
    struct TexturePack *pTexturePack;       // 136
    struct TextureInfo *pImageParent;       // 140
    uint8_t  *ImageData;                    // 144
    uint8_t  *PaletteData;                  // 148
    void     *pActiveTexture;               // 152
    void     *pStackedActiveTexture;        // 156
    uint16_t  PaletteVramAddress;           // 160
    uint16_t  ImageVramAddress;             // 162
} TextureInfo;                              // 164

// LoadedTextureData, 44 bytes: a range of a streamed pack's blob.
typedef struct LoadedTextureData {
    bNode     Node;                         //   0
    int32_t   LowPos;                       //   8
    int32_t   HighPos;                      //  12
    int32_t   NumAssignments;               //  16
    int32_t   MemoryPool;                   //  20
    uint8_t  *Buf;                          //  24
    int32_t   LoadingCompleted;             //  28
    int32_t   LoadingInProgress;            //  32
    void    (*Callback)(int32_t);           //  36
    int32_t   CallbackParam;                //  40
} LoadedTextureData;                        //  44

// TexturePack, 148 bytes in retail, the demo's 132. Retail's Filename is
// 64 bytes, the demo's 48, and the constructor fills it from the header;
// the demo's left it as the heap had it. Every field after it is 16 bytes
// on from the demo's.
typedef struct TexturePack {
    bNode        Node;                          //   0
    char         Name[32];                      //   8
    char         Filename[64];                  //  40
    uint32_t     NameHash;                      // 104
    int32_t      InventoryHandle;               // 108
    TextureInfo *pTextureInfo;                  // 112
    int32_t      NumTextures;                   // 116
    int32_t      pTextureInfoNeedsToBeFreed;    // 120
    int32_t      TextureDataFilePos;            // 124
    bNode        LoadedTextureDataList;         // 128
    LoadedTextureData *CurrentLoadingTextureData;  // 136
    int32_t      NumNotYetLoadedTextureDatas;   // 140
    int32_t      MemoryPool;                    // 144
} TexturePack;                                  // 148

// TexturePackHeader, 84 bytes in retail: the 0x30300002 payload. Retail
// put the pack's file name, "Global\FrontEndTextures.tpk" and the like,
// between the name and the pointer; the demo's header is 20 bytes.
typedef struct TexturePackHeader {
    char         Name[16];                  //   0
    char         Filename[64];              //  16
    TexturePack *pTexturePack;              //  80
} TexturePackHeader;                        //  84

// TextureAnimEntry, 16 bytes: one frame, and the pixels and palette its
// texture had when the flipbook was made.
typedef struct TextureAnimEntry {
    uint32_t     NameHash;                  //   0
    TextureInfo *pTextureInfo;              //   4
    uint8_t     *OriginalImageData;         //   8
    uint8_t     *OriginalPaletteData;       //  12
} TextureAnimEntry;                         //  16

// TextureAnim, 52 bytes: one flipbook. TimeBase 1 runs it on the real
// clock, anything else on the world's.
typedef struct TextureAnim {
    char      Name[24];                     //   0
    uint32_t  NameHash;                     //  24
    int32_t   NumFrames;                    //  28
    int32_t   FramesPerSecond;              //  32
    int32_t   TimeBase;                     //  36
    TextureAnimEntry *TextureAnimTable;     //  40
    int32_t   Valid;                        //  44
    int32_t   CurrentFrame;                 //  48
} TextureAnim;                              //  52

typedef struct TextureAnimPack {
    bNode        Node;                      //   0
    TextureAnim *TextureAnimTable;          //   8
    TextureAnimEntry *TextureAnimEntryTable;  // 12
    int32_t      NumTextureAnims;           //  16
    int32_t      NumTextureAnimEntries;     //  20
} TextureAnimPack;                          //  24

// TextureAnimPackHeader, 16 bytes: the 0x30300101 payload. Only version 1
// is loaded.
typedef struct TextureAnimPackHeader {
    int32_t          Version;               //   0
    TextureAnimPack *pTextureAnimPack;      //   4
    int32_t          pad[2];                //   8
} TextureAnimPackHeader;                    //  16

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char texturepack_layout_check[
    (sizeof(TextureInfo) == 164 && offsetof(TextureInfo, NameHash) == 32
     && offsetof(TextureInfo, ImagePlacement) == 48
     && offsetof(TextureInfo, ImageInfos) == 82
     && offsetof(TextureInfo, NumMipMapLevels) == 110
     && offsetof(TextureInfo, MipMapK) == 114
     && offsetof(TextureInfo, UsedFlag) == 120
     && offsetof(TextureInfo, ScrollSpeedS) == 124
     && offsetof(TextureInfo, pTexturePack) == 136
     && offsetof(TextureInfo, PaletteVramAddress) == 160
     && sizeof(LoadedTextureData) == 44 && sizeof(TexturePack) == 148
     && offsetof(TexturePack, Filename) == 40
     && offsetof(TexturePack, NameHash) == 104
     && offsetof(TexturePack, LoadedTextureDataList) == 128
     && offsetof(TexturePack, MemoryPool) == 144
     && sizeof(TexturePackHeader) == 84
     && offsetof(TexturePackHeader, pTexturePack) == 80
     && sizeof(TextureAnimEntry) == 16
     && sizeof(TextureAnim) == 52
     && offsetof(TextureAnim, TextureAnimTable) == 40
     && sizeof(TextureAnimPack) == 24
     && sizeof(TextureAnimPackHeader) == 16) ? 1 : -1];
#endif

// TexturePackList and TextureAnimPackList, 0x00323e98 and 0x00323ea0
// (gp-19800 and gp-19792; retail 0x00330e28 and 0x00330e30). Each starts
// empty, pointing at itself.
extern bNode TexturePackList;
extern bNode TextureAnimPackList;

// TweakFPS, 0x00323ea8 (gp-19784; retail 0x00330e38): a frame rate for
// every flipbook in place of its own, when not 0.
extern int32_t TweakFPS;

// How many times GetTextureInfo has reached bBreak (0x00238888, retail
// 0x00250ab0): a texture that is nowhere, not even the default.
extern int32_t texturepack_breaks;

// The seams.
extern TextureInfo *(*gERenderTargetTextureInfoFn)(uint32_t name_hash);
extern void (*gServiceQueuedFilesFn)(void);

// LoaderTexturePack(bChunk *), 0x00100830 (retail 0x00100820), and
// UnloaderTexturePack, 0x001009e0 (retail 0x001009d0). Each takes a
// 0xb0300001 or 0xb0300100 chunk and returns 1, and returns 0 for any
// other.
int loader_texture_pack(uint8_t *chunk);
int unloader_texture_pack(uint8_t *chunk);

// TexturePack::TexturePack, 0x001a1ae8, retail's (const char *, const
// char *) at 0x001ac0a8: the name, the file name when there is one, the
// name's hash, the debugger's handle, and the pack at the list's tail.
TexturePack *texturepack_construct(TexturePack *p, const char *name,
                                   const char *filename);

// TexturePack::~TexturePack, 0x001a1b98 (retail 0x001ac178): off the
// list, and its LoadedTextureData freed; with bit 0 of `flags`, the pack
// too. Its records keep what they point at.
void texturepack_destruct(TexturePack *p, int32_t flags);

// AttachTextureTable(TextureInfo *, int), 0x001a1c40 (retail 0x001ac220):
// the pack's records, each with its pack and its image parent, and its
// pixels, palette, active textures and VRAM addresses cleared.
void texturepack_attach_texture_table(TexturePack *p, TextureInfo *table,
                                      int32_t num);

// AssignTextureData(char *, int, int), 0x001a1cd8 (retail 0x001ac2b0), and
// UnAssignTextureData(int, int), 0x001a1d80 (retail 0x001ac358): the
// pixels and palette of every record that has them and whose placement is
// in [pos, pos+size), pointed into `data` (which holds that range), or
// cleared.
void texturepack_assign_texture_data(TexturePack *p, uint8_t *data,
                                     int32_t pos, int32_t size);
void texturepack_unassign_texture_data(TexturePack *p, int32_t pos,
                                       int32_t size);

// GetLoadedTexture(unsigned int), 0x001a1e18 (retail 0x001ac3f0): the
// first record of that name with its pixels, and its palette if it has
// one. GetTexture, 0x001a1e90 (retail 0x001ac468): the first of that name.
// GetNthTexture(int), 0x001a1ed8 (retail 0x001ac4b0).
TextureInfo *texturepack_get_loaded_texture(TexturePack *p, uint32_t hash);
TextureInfo *texturepack_get_texture(TexturePack *p, uint32_t hash);
TextureInfo *texturepack_get_nth_texture(TexturePack *p, int32_t n);

// GetTextureInfo, 0x001a19b0, retail's (unsigned int, int, int) at
// 0x001abf48. Each pack is asked for a loaded record of that name, or with
// `include_unloaded` for any record of it. A pack that has the texture
// goes to the list's head, and the record's UsedFlag is set. Then the
// render targets; then, with `use_default`, the default texture, looked
// for loaded. With no texture and no default, bBreak. Every retail caller
// but the two below passes 0 for `include_unloaded`.
TextureInfo *GetTextureInfo(uint32_t hash, int use_default,
                            int include_unloaded);

// GetNthTextureInfo(int), 0x001a1a90 (retail 0x001ac050): counting
// through every pack's records.
TextureInfo *GetNthTextureInfo(int32_t n);

// Retail's alone, and unnamed in the stripped ELF; the names are the
// port's. RenameTextureInfo(unsigned int, const char *), 0x001ac4d8: the
// texture of that name, loaded or not, takes the 24 bytes at `name` as its
// DebugName and their hash as its NameHash. Nothing in retail calls it.
// SwapTextureInfoNames(unsigned int, unsigned int), 0x001ac548: two
// textures trade their DebugNames and rehash them, which is how retail's
// ServiceGameFlow puts the French loading screen and logo in place of the
// English ones. Each returns 0 when a texture is not found, and 1.
int RenameTextureInfo(uint32_t hash, const char *name);
int SwapTextureInfoNames(uint32_t a, uint32_t b);

// MaybePrintUnusedTextures, 0x001a1ae0 (retail 0x001ac0a0): nothing, in
// this build.
void MaybePrintUnusedTextures(void);

// GetTextureInfo in the shape of esolid.h's seam, gGetTextureInfoFn. Every
// retail caller through the seam asks for loaded records only.
void *texturepack_get_texture_info(uint32_t hash, int use_default,
                                   int include_unloaded);

// TextureAnimPack::TextureAnimPack(TextureAnim *, TextureAnimEntry *,
// int, int), 0x001a1650 (retail 0x001abbe8): each flipbook's frames, in
// turn, from the entries, and the pack at the list's tail.
TextureAnimPack *textureanimpack_construct(TextureAnimPack *p,
                                           TextureAnim *anims,
                                           TextureAnimEntry *entries,
                                           int32_t num_anims,
                                           int32_t num_entries);

// ~TextureAnimPack, 0x001a16c8 (retail 0x001abc60): off the list; with
// bit 0 of `flags`, freed. Its textures keep the frame they were on.
void textureanimpack_destruct(TextureAnimPack *p, int32_t flags);

// InitAnims, 0x001a16e0 (retail 0x001abc78): every frame's loaded texture
// and the pixels and palette it has now. A flipbook with a frame nobody
// has is not valid.
void textureanimpack_init_anims(TextureAnimPack *p);

// UpdateTextureAnimations, 0x001a17e8 (retail 0x001abd80), once a frame
// from eDisplayFrame:
// each valid flipbook's frame from its clock, and on a new frame, each
// frame's texture given the pixels and palette of the frame that many on.
// A valid flipbook of no frames is a divide by zero on the console; the
// port leaves it alone.
void UpdateTextureAnimations(void);

// GetTextureAnim(unsigned int), 0x001a1950 (retail 0x001abee8): the first
// flipbook of that name.
TextureAnim *GetTextureAnim(uint32_t hash);

#endif
