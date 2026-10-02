// hudtex -- see hudtex.h.

#include "hudtex.h"

#include <stdio.h>
#include <string.h>

#include "bchunk.h"
#include "cartypeinfo.h"
#include "eefpu.h"

// CarHudInfo, the 80 bytes at CarTypeInfo+1232 that cartypeinfo.h keeps as
// bytes: IsIntegrated is the int at +0 and MaxRPM the float at +16.
#define HUD_IS_INTEGRATED 0
#define HUD_MAX_RPM       16

void ChooseLoadableTextures(int32_t car, int32_t units,
                            tLoadableHudTextures *t)
{
    const CarTypeInfo *ct = cartypeinfo_get(car);
    char name[64], base[64];
    float max_rpm;
    int32_t integrated;

    // `cvt.w.s`: the gauge's top end, truncated.
    memcpy(&max_rpm, ct->HudInfo + HUD_MAX_RPM, sizeof max_rpm);
    snprintf(name, sizeof name, "3RDPERSON_%d", (int)ee_trunc_w(max_rpm));
    t->ThirdPerson = bchunk_hash(name);

    // The gauges' base name: the car's, less a COP or HP on the end. The
    // Lamborghini cop's are the Murcielago's. The two tails are compared
    // at len-3 and len-2 without a check, so a name of one or two letters
    // reads before it: the disc has none.
    if (strcmp("LAMBOCOP", ct->CarTypeName) == 0) {
        snprintf(base, sizeof base, "MURCIELAGO");
    } else {
        size_t len = strlen(ct->CarTypeName);
        size_t cut = strcmp(ct->CarTypeName + len - 3, "COP") == 0 ? 3 : 0;

        if (strcmp(ct->CarTypeName + len - 2, "HP") == 0)
            cut = 2;
        memset(base, 0, sizeof base);
        memcpy(base, ct->CarTypeName, len - cut);
    }

    if (units == UNITS_KPH)
        snprintf(name, sizeof name, "%s_KMH", base);
    else if (units == UNITS_MPH)
        snprintf(name, sizeof name, "%s_MPH", base);
    t->Speedo = bchunk_hash(name);

    memcpy(&integrated, ct->HudInfo + HUD_IS_INTEGRATED, sizeof integrated);
    if (integrated != 0) {
        t->Tach = 0;
        snprintf(name, sizeof name, "OVERLAY_%s", base);
    } else {
        snprintf(name, sizeof name, "%s_TACH", base);
        t->Tach = bchunk_hash(name);
        snprintf(name, sizeof name, "OVERLAY_GENERIC");
    }
    t->Shadow = bchunk_hash(name);
}
