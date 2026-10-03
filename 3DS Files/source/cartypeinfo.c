// cartypeinfo -- see cartypeinfo.h.

#include "cartypeinfo.h"
#include "langtab.h"
#include "bchunk.h"
#include "bmath.h"
#include "car.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>

// gp-15456. The image's global seed for the skin draw. Its owner is the
// startup code, which is not ported; the port keeps its own copy so the
// cross-checker can set it.
uint32_t CarTypeInfoSkinSeed = 0;

const char *cartypeinfo_get_full_name(const CarTypeInfo *ct,
                                      const LangTable *t,
                                      size_t *outLen)
{
    return langtab_get(t, ct->pCarSpecs->FullName, outLen);
}

const char *cartypeinfo_get_short_name(const CarTypeInfo *ct,
                                       const LangTable *t,
                                       size_t *outLen)
{
    return langtab_get(t, ct->pCarSpecs->ShortName, outLen);
}

const char *cartypeinfo_get_car_spec_0_to_60(const CarTypeInfo *ct,
                                             const LangTable *t,
                                             size_t *outLen)
{
    return langtab_get(t, ct->pCarSpecs->ZeroTo60, outLen);
}

const char *cartypeinfo_get_car_spec_top_speed(const CarTypeInfo *ct,
                                               int32_t units,
                                               const LangTable *t,
                                               size_t *outLen)
{
    int32_t id = 0;

    // 0x00187f38: 1 the km/h, 0 the mph, anything else id 0.
    if (units == 1)
        id = ct->pCarSpecs->TopSpeedKph;
    else if (units == 0)
        id = ct->pCarSpecs->TopSpeedMph;
    return langtab_get(t, id, outLen);
}

const char *cartypeinfo_get_car_spec_bhp(const CarTypeInfo *ct,
                                         const LangTable *t,
                                         size_t *outLen)
{
    return langtab_get(t, ct->pCarSpecs->BHP, outLen);
}

const char *cartypeinfo_get_manufacturer_name(const CarTypeInfo *ct,
                                              const LangTable *t,
                                              size_t *outLen)
{
    // `addiu a0,a0,192` -- the address of the field, not a load through
    // it. The manufacturer is stored as text in CarTypeInfo and looked up
    // by name, where every other accessor looks up by id. The field is 16
    // bytes and the original relies on it being NUL-terminated inside
    // them, so a full-width name would run on; the port inherits that.
    return langtab_get_english(t,
                               (int32_t)bchunk_hash(ct->ManufacturerName),
                               outLen);
}

int32_t cartypeinfo_get_random_skin(const CarTypeInfo *ct)
{
    // v0 is cleared in the branch's delay slot, so the no-skins answer is
    // a literal 0 rather than AvailableSkins[0].
    if (ct->NumAvailableSkins == 0)
        return 0;

    // lb, so the skin id is sign-extended from a byte.
    return ct->AvailableSkins[bRandomI(ct->NumAvailableSkins,
                                       &CarTypeInfoSkinSeed)];
}

int32_t (*gCurrLanguageFn)(void);

int32_t cartypeinfo_get_num_skins(const CarTypeInfo *ct)
{
    if (ct->UsageType == CAR_USAGE_TYPE_COP)
        return 1;
    return ct->NumAvailableSkins;
}

int32_t cartypeinfo_get_skin_number(const CarTypeInfo *ct, int32_t i)
{
    if (ct->UsageType == CAR_USAGE_TYPE_COP) {
        int32_t lang = gCurrLanguageFn != NULL ? gCurrLanguageFn() : 0;

        return lang != 0 ? 2 : 1;
    }
    return ct->AvailableSkins[i % ct->NumAvailableSkins];
}

// 0x00323930. Set up by the car data loader, which is not ported.
const CarTypeInfo *CarTypeInfoArray = NULL;

const CarTypeInfo *cartypeinfo_get(int32_t carType)
{
    // The image multiplies by a literal 1376 and adds. On a 64-bit host
    // the record is wider, so indexing has to go through the array type
    // rather than a byte offset; the element *identity* is what carries
    // over, not the arithmetic.
    return &CarTypeInfoArray[carType];
}

// 0x00323934 and 0x00323938 in the demo. Set up by the car data loader.
SkinInfo *SkinInfoTable = NULL;
int32_t   NumSkinInfo = 0;

SkinInfo *cartypeinfo_get_skin_info(int32_t car_type, int32_t skin_number,
                                    int use_default)
{
    int32_t i;

    for (i = 0; i < NumSkinInfo; i++) {
        SkinInfo *s = &SkinInfoTable[i];

        if (s->TheCarType == car_type && s->SkinNumber == skin_number)
            return s;
    }
    return use_default ? SkinInfoTable : NULL;
}

// bSPrintf into a 64-byte buffer on the stack, then bStringHash. The
// longest name here is a 31-character model name and "_BRAKELIGHT_DAMAGE0".
static uint32_t name_hash(const char *fmt, const char *name, int n)
{
    char buf[64];

    snprintf(buf, sizeof buf, fmt, name, n);
    return bchunk_hash(buf);
}

void cartypeinfo_get_used_car_texture_info(UsedCarTextureInfo *u,
                                           const RideInfo *ride,
                                           int front_end)
{
    const CarTypeInfo *ct = cartypeinfo_get(ride->Type);
    const char *name = ct->BaseModelName;
    int skin = ride->SkinNumber;
    int n = 1;
    uint32_t h;
    int i;

    memset(u, 0, sizeof *u);

    u->MappedSkinHash = name_hash("%s_SKIN1", name, 0);
    u->MappedSkinBHash = name_hash("%s_SKIN1B", name, 0);
    h = name_hash("%s_SKIN%d", name, skin);
    u->TexturesToLoad[0] = h;
    u->ReplaceSkinHash = h;
    if (!front_end) {
        n = 2;
        h = name_hash("%s_SKIN%dB", name, skin);
        u->TexturesToLoad[1] = h;
        u->ReplaceSkinBHash = h;
    }

    if (ride->HasDash) {
        u->MappedDashSkinHash = name_hash("%s_DASHSKIN1", name, 0);
        h = name_hash("%s_DASHSKIN%d", name, skin);
        u->ReplaceDashSkinHash = h;
        u->TexturesToLoad[n++] = h;
    } else {
        u->MappedDashSkinHash = 0;
        u->ReplaceDashSkinHash = 0;
    }

    u->MappedLightHash[0] = name_hash("%s_HEADLIGHT_LEFT", name, 0);
    u->MappedLightHash[1] = name_hash("%s_HEADLIGHT_RIGHT", name, 0);
    u->MappedLightHash[2] = name_hash("%s_BRAKELIGHT_LEFT", name, 0);
    u->MappedLightHash[3] = name_hash("%s_BRAKELIGHT_RIGHT", name, 0);
    u->MappedLightHash[4] = name_hash("%s_REVERSELIGHT", name, 0);
    u->ReplaceHeadlightHash[0] = name_hash("%s_HEADLIGHT", name, 0);
    u->ReplaceHeadlightHash[1] = name_hash("%s_HEADLIGHT_ON", name, 0);
    u->ReplaceHeadlightHash[2] = name_hash("%s_HEADLIGHT_DAMAGE0", name, 0);
    u->ReplaceBrakelightHash[0] = name_hash("%s_BRAKELIGHT", name, 0);
    u->ReplaceBrakelightHash[1] = name_hash("%s_BRAKELIGHT_ON", name, 0);
    u->ReplaceBrakelightHash[2] = name_hash("%s_BRAKELIGHT_DAMAGE0", name, 0);
    u->ReplaceReverselightHash[0] = name_hash("%s_REVERSELIGHT", name, 0);
    u->ReplaceReverselightHash[1] = name_hash("%s_REVERSELIGHT_ON", name, 0);
    // REVERSELIGHT again, where the other two have their DAMAGE0: the
    // reversing light has no broken look of its own.
    u->ReplaceReverselightHash[2] = name_hash("%s_REVERSELIGHT", name, 0);
    for (i = 0; i < 3; i++)
        u->TexturesToLoad[n++] = u->ReplaceHeadlightHash[i];
    for (i = 0; i < 3; i++)
        u->TexturesToLoad[n++] = u->ReplaceBrakelightHash[i];
    for (i = 0; i < 3; i++)
        u->TexturesToLoad[n++] = u->ReplaceReverselightHash[i];

    h = name_hash(front_end ? "%s_SHADOWFE" : "%s_SHADOWIG", name, 0);
    u->ShadowHash = h;
    u->TexturesToLoad[n++] = h;

    // The Mapped pair from the model's name, the Replace pair from the
    // car's own: cars that share a body keep their own wheels.
    u->MappedTireHash = name_hash("%s_TIRE", name, 0);
    u->ReplaceTireHash = name_hash("%s_TIRE", ct->CarTypeName, 0);
    u->MappedTireBlurHash = name_hash("%s_WHEEL_BLUR", name, 0);
    u->ReplaceTireBlurHash = name_hash("%s_WHEEL_BLUR", ct->CarTypeName, 0);
    u->TexturesToLoad[n++] = u->ReplaceTireHash;
    u->TexturesToLoad[n++] = u->ReplaceTireBlurHash;

    h = name_hash("%s_LICENSE_PLATE", name, 0);
    u->MappedLicensePlateHash = h;
    u->TexturesToLoad[n++] = h;
    u->NumTexturesToLoad = n;
}
