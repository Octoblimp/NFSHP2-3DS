// esolid -- see esolid.h.

#include "esolid.h"

#include <stdio.h>
#include <string.h>

#include "bchunk.h"
#include "bmath.h"
#include "eefpu.h"
#include "texturepack.h"

#define SOLID_LIST_ID       0x80034000u
#define SOLID_ID            0x00034003u
#define STRIP_ENTRIES_ID    0x00034004u
#define STRIP_DATA_ID       0x00034005u
#define TEXTURE_TABLE_ID    0x00034006u
#define ANIMATION_TREE_ID   0x00034007u
#define LABELLED_FRAMES_ID  0x00034011u
#define RIGID_ANIMATION_ID  0x00034012u
#define LIGHT_MATERIALS_ID  0x0003401du

// eSolid's Flags.
#define SOLID_DUPLICATE_NAME    0x0002u
#define SOLID_VERTEX_ANIMATED   0x0010u

BSlotPool *eVertexAnimatorSlotPool;

int32_t eDisableFixUpTables;
int32_t eDirtySolids;
int32_t eDirtyTextures;
int32_t eDirtyAnimations;

void *pTextureInfoRVMInfo;
void *pTextureInfoRVMMask;
void *pTextureInfoSolidGrey;
void *pTextureInfoFilterGrey;
void *pTextureInfoShadowMap1;
void *pTextureInfoRadialBlur;
void *pTextureInfoSpecularFalloff;
void *pTextureInfoFalloffRamp;
void *pTextureInfoCarSelectEnvMap;

void *(*gGetTextureInfoFn)(uint32_t name_hash, int use_default,
                           int include_unloaded);
void *(*gElGetLightMaterialFn)(uint32_t name_hash);
void (*gFixStripSTsFn)(eSolid *solid);
void (*gCalcAutoKFn)(eSolid *solid);
void (*gReconnectAllAnimationsFn)(void);

void *get_texture_info(uint32_t name_hash, int use_default,
                       int include_unloaded)
{
    if (gGetTextureInfoFn == NULL)
        return NULL;
    return gGetTextureInfoFn(name_hash, use_default, include_unloaded);
}

void *get_light_material(uint32_t name_hash)
{
    if (gElGetLightMaterialFn == NULL)
        return NULL;
    return gElGetLightMaterialFn(name_hash);
}

// A child's payload rounded up to 16, past the filler the tools put there.
static uint8_t *align16(uint8_t *p)
{
    return (uint8_t *)(((uintptr_t)p + 15u) & ~(uintptr_t)15u);
}

static uint8_t *next_chunk(uint8_t *c)
{
    return c + 8 + bchunk_u32(c + 4);
}

void esolid_init_slot_pool(void)
{
    if (eVertexAnimatorSlotPool != NULL)
        return;
    eVertexAnimatorSlotPool = bNewSlotPool((int)sizeof(eVertexAnimator), 16,
                                           "eVertexAnimatorSlotPool", 16);
}

void evertexanimator_delete(eVertexAnimator *va, int32_t flags)
{
    // ~bTNode<eVertexAnimator> is ~bNode with 0, which deletes nothing.
    if (flags & 1)
        bSlotFree(eVertexAnimatorSlotPool, va);
}

void esolid_fix_strip_entry_table(eSolid *s, uint8_t *data, int32_t size,
                                  uint8_t *base)
{
    eStripEntry *e = (eStripEntry *)s->StripEntryTable;
    int n = s->NumStrips;

    (void)size;
    for (; n > 0; n--, e++)
        e->Data = (uint8_t *)((uintptr_t)e->Data + (uintptr_t)data
                              - (uintptr_t)base);
}

void esolid_fix_texture_table(eSolid *s)
{
    int i;

    for (i = 0; i < s->NumTextureTableEntries; i++) {
        eTextureTable *t = (eTextureTable *)s->pTextureTable + i;

        t->pTextureInfo = get_texture_info(t->NameHash, 1, 0);
    }
}

void esolid_fix_light_material_table(eSolid *s)
{
    eLightMaterialEntry *e = (eLightMaterialEntry *)s->LightMaterialTable;
    int n = s->NumLightMaterials;

    for (; n > 0; n--, e++)
        e->LightMaterial = get_light_material(e->NameHash);
}

// One container's children, in the order they come. `s` is the eSolid
// the 0x34003 child names; every other child fills a field of it.
static eSolid *load_children(uint8_t *c)
{
    uint8_t *g = c + 8;
    uint8_t *end = next_chunk(c);
    eSolid *s = NULL;

    for (; g != end; g = next_chunk(g)) {
        uint32_t type = bchunk_u32(g);
        uint32_t size = bchunk_u32(g + 4);
        uint8_t *payload = g + 8;
        uint8_t *p = align16(payload);

        if (type == SOLID_ID) {
            s = (eSolid *)p;
        } else if (type == STRIP_ENTRIES_ID) {
            s->StripEntryTable = p;
        } else if (type == TEXTURE_TABLE_ID) {
            s->pTextureTable = payload;
            s->NumTextureTableEntries =
                (int16_t)(size / sizeof(eTextureTable));
        } else if (type == LIGHT_MATERIALS_ID) {
            s->LightMaterialTable = p;
        } else if (type == STRIP_DATA_ID) {
            uint32_t n = size - (uint32_t)(p - payload);

            s->StripEntryDataStart = p;
            s->SizeofStripEntryData = n;
            esolid_fix_strip_entry_table(s, p, (int32_t)n, NULL);
        } else if (type == ANIMATION_TREE_ID) {
            s->pAnimationTreeNodes = p;
            s->AnimationTreeNumNodes = (int32_t)(
                (size - (uint32_t)(p - payload)) / EANIMATIONTREENODE_SIZE);
        } else if (type == RIGID_ANIMATION_ID) {
            s->pRigidAnimation = p;
        } else if (type == LABELLED_FRAMES_ID) {
            ((eRigidAnimation *)(void *)s->pRigidAnimation)->pLabelledFrames =
                payload;
        }
    }
    return s;
}

int loader_solid_list(uint8_t *chunk)
{
    eSolidListHeader *header;
    uint8_t *end, *c;
    char buf[2048];

    if (bchunk_u32(chunk) != SOLID_LIST_ID)
        return 0;
    end = next_chunk(chunk);
    header = (eSolidListHeader *)(void *)(chunk + 16);
    c = next_chunk(chunk + 8);

    // bAddCodeineInventory(0, name, ...) tells the debugger's channel, which
    // the port does not have, and returns the name's hash.
    snprintf(buf, sizeof buf, "SolidList,%s", header->Filename);
    header->InventoryHandle = (int32_t)bchunk_hash(buf);

    for (; c < end; c = next_chunk(c)) {
        eSolid *s = load_children(c);
        eSolid *e;
        bNode *last;

        esolid_fix_texture_table(s);
        esolid_fix_light_material_table(s);
        if (s->ExternalRigidAnimationNameHash != 0) {
            e = (eSolid *)eFindSolid(s->ExternalRigidAnimationNameHash);
            if (e != NULL)
                s->pRigidAnimation = e->pRigidAnimation;
        }
        if (s->Flags & SOLID_VERTEX_ANIMATED) {
            // The frames of a vertex animation are solids of one name, one
            // after another; the first makes the animator, the rest join it.
            e = (eSolid *)eFindSolid(s->NameHash);
            if (e == NULL) {
                eVertexAnimator *va =
                    (eVertexAnimator *)bSlotOMalloc(eVertexAnimatorSlotPool);

                va->NumSolids = 0;
                s->pVertexAnimator = va;
                va->NumSolids = 1;
                va->FrameRate = 30;
                va->SolidTable[0] = s;
            } else {
                eVertexAnimator *va = (eVertexAnimator *)e->pVertexAnimator;

                if (va->NumSolids < EVERTEXANIMATOR_MAX_SOLIDS) {
                    va->SolidTable[va->NumSolids] = s;
                    va->NumSolids++;
                }
                s->pVertexAnimator = e->pVertexAnimator;
                s->pRigidAnimation = e->pRigidAnimation;
            }
        } else {
            e = (eSolid *)eFindSolid(s->NameHash);
            if (e != NULL) {
                s->Flags |= SOLID_DUPLICATE_NAME;
                e->Flags |= SOLID_DUPLICATE_NAME;
            }
        }
        eDirtySolids = 1;
        last = SolidList.prev;
        last->next = &s->Node;
        SolidList.prev = &s->Node;
        s->Node.next = &SolidList;
        s->Node.prev = last;
    }
    return 1;
}

int unloader_solid_list(uint8_t *chunk)
{
    uint8_t *end, *c;

    if (bchunk_u32(chunk) != SOLID_LIST_ID)
        return 0;
    end = next_chunk(chunk);
    c = next_chunk(chunk + 8);
    // bRemoveCodeineInventory only tells the debugger's channel.

    for (; c < end; c = next_chunk(c)) {
        uint8_t *g = c + 8;

        // The image reads the first child's type and never moves on: a
        // container whose eSolid is not first would hang it. The port
        // looks at the first child only, which comes to the same on every
        // container the image returns from.
        if (g != next_chunk(c) && bchunk_u32(g) == SOLID_ID) {
            eSolid *s = (eSolid *)align16(g + 8);
            eVertexAnimator *va = (eVertexAnimator *)s->pVertexAnimator;

            s->Node.prev->next = s->Node.next;
            s->Node.next->prev = s->Node.prev;
            if (va != NULL) {
                int n = va->NumSolids;
                int i;

                for (i = 0; i < n; i++)
                    va->SolidTable[i]->pVertexAnimator = NULL;
                va->NumSolids = 0;
                evertexanimator_delete(va, 3);
            }
        }
        eDirtySolids = 1;
    }
    return 1;
}

void efix_up_tables(void)
{
    if (eDisableFixUpTables)
        return;
    if (eDirtySolids || eDirtyTextures) {
        if (eDirtyTextures) {
            bNode *n;

            for (n = SolidList.next; n != &SolidList; n = n->next) {
                eSolid *s = (eSolid *)(void *)n;

                esolid_fix_texture_table(s);
                if (gFixStripSTsFn != NULL)
                    gFixStripSTsFn(s);
                if (gCalcAutoKFn != NULL)
                    gCalcAutoKFn(s);
            }
        }
        emodel_reconnect_all_models();
        if (gReconnectAllAnimationsFn != NULL)
            gReconnectAllAnimationsFn();
        pTextureInfoRVMInfo = get_texture_info(0x0000dbd4u, 0, 0);
        pTextureInfoRVMMask = get_texture_info(0xcf29d0dfu, 0, 0);
        pTextureInfoSolidGrey = get_texture_info(0x32283a11u, 0, 0);
        pTextureInfoFilterGrey = get_texture_info(0x02c8711cu, 0, 0);
        pTextureInfoShadowMap1 = get_texture_info(0xbad886d4u, 0, 0);
        pTextureInfoRadialBlur = get_texture_info(0xab9a6e21u, 0, 0);
        pTextureInfoSpecularFalloff = get_texture_info(0x0184d1f8u, 0, 0);
        pTextureInfoFalloffRamp = get_texture_info(0xb9ab56e4u, 0, 0);
        pTextureInfoCarSelectEnvMap = get_texture_info(0x4ecc769cu, 0, 0);
        efix_falloff_ramp();
        eDirtySolids = 0;
        eDirtyTextures = 0;
        eDirtyAnimations = 0;
        return;
    }
    if (eDirtyAnimations) {
        if (gReconnectAllAnimationsFn != NULL)
            gReconnectAllAnimationsFn();
        eDirtyAnimations = 0;
    }
}

void efix_falloff_ramp(void)
{
    TextureInfo *t = (TextureInfo *)pTextureInfoFalloffRamp;
    uint32_t *pal;
    int32_t n, i;

    if (t == NULL)
        return;
    // A loop of (int16_t)Width passes of four nops comes here, and does
    // nothing.
    pal = (uint32_t *)(void *)t->PaletteData;
    n = t->PaletteSize >> 2;
    if (pal == NULL || n <= 0)
        return;
    for (i = 0; i < n; i++) {
        float x = (float)i / (float)n * 1.57075f + 1.5707965f;
        float s = bSinF(x);
        float f, r;
        uint32_t bits;
        int32_t w, v;

        if (s < 0.01f)
            s = 0.01f;
        // pow(s, 1.0f), inlined: the bits of s as an integer, times the
        // power, plus (1 - power) times the bits of 1.0f, and back.
        memcpy(&bits, &s, sizeof bits);
        f = (float)(int32_t)bits * 1.0f
            + ((float)(int32_t)0x3f800000 - 1.0f * 1065353216.0f);
        w = ee_trunc_w(f);
        memcpy(&r, &w, sizeof r);
        v = ee_trunc_w(r * 128.0f) & 0xff;
        pal[i] = (uint32_t)v << 24 | (uint32_t)v
                 | ((uint32_t)v << 8 | (uint32_t)v << 16);
    }
}
