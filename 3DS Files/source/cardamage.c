// cardamage -- see cardamage.h.

#include "cardamage.h"

#include "race.h"

float bodydamage_get_visible_total_damage(const BodyDamage *b)
{
    if (RaceParametersDamageEnabled == 0)
        return 0.0f;
    // `lhu`, `mtc1`, `cvt.s.w`: the halfword is widened unsigned and then
    // converted as a signed word, which for 16 bits is the same thing.
    return (float)(int32_t)b->CompressedTotalDamage * 0.000244140625f;
}
