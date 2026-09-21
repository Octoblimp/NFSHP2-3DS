// cartypeinfo -- see cartypeinfo.h.

#include "cartypeinfo.h"
#include "langtab.h"
#include "bchunk.h"
#include "bmath.h"

#include <stddef.h>

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
                                               const LangTable *t,
                                               size_t *outLen)
{
    return langtab_get(t, ct->pCarSpecs->TopSpeed, outLen);
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
