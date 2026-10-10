// spchrule -- spchrule.o and spchrand.o of SPP2A380.A: an event's rules
// and the library's random numbers. See spch.h.

#include "spchi.h"

// ---- spchrule

static const uint8_t *event_rules(const uint8_t *ev)
{
    return ev + 12 + ((ev[6] * 2 + 3) & 0x3fc);
}

// Whether a phrase of the sentence takes its subbank or a rule from the
// event parameter p.
int32_t spchi_sentence_uses_parm(const uint8_t *sent, uint32_t p)
{
    int32_t nph = sent[3] >> 2, i, j;

    for (i = 0; i < nph; i++) {
        const uint8_t *ph = sent + sent[4 + i] * 4;

        if (ph[2] == p)
            return 1;
        for (j = 0; j < 4; j++)
            if (ph[8 + j] == p)
                return 1;
    }
    return 0;
}

int32_t spchi_get_rule_id(const uint8_t *ev, uint32_t i)
{
    if (i >= 8) {
        spchi_abort("iSPCH_GetRuleID - ruleindex out of bounds.");
        return -1;
    }
    return event_rules(ev)[3 * i];
}

// The event's set rules (types 0 and 3) on the parameters the chosen
// sentence uses, through the rule set callback. Retail reads past the
// event's parameters for a parameter of 20 or more; the port takes 0.
void spchi_rule_set(uint32_t *event, const uint8_t *ev, int32_t si,
                    const uint32_t *parms)
{
    const uint8_t *sent, *r;
    int32_t d = 0, n, i;

    if (gSpch.ruleSet == NULL)
        return;
    spchi_get_dat_id((const uint8_t *)event, &d);
    sent = ev + spch_u16(ev + 12 + 2 * si) * 4;
    n = (int8_t)ev[7];
    r = event_rules(ev);
    for (i = 0; i < n; i++, r += 3) {
        uint32_t parm = r[1];

        if (r[2] != 0 && r[2] != 3)
            continue;
        if (spchi_sentence_uses_parm(sent, parm))
            gSpch.ruleSet(event, r[0],
                          (int32_t)(parm < SPCH_EVENT_PARMS ? parms[parm] : 0), d);
    }
}

// The event's rules tested on the parameters, a bit each (the first rule
// in bit 7): type 4 tests the parameter for non-zero, the others ask the
// rule test callback. A rule on parameter 0 is tested last, with 0. The
// bits that passed; *outFb gets those the callback answered below 0.
uint32_t spchi_get_rule_settings(uint32_t *event, const uint8_t *ev,
                                 const uint32_t *req, uint8_t *outFb)
{
    const uint8_t *rules = event_rules(ev), *r;
    uint32_t res = 0, fb = 0, bit, s2;
    int32_t d = 0, n = (int8_t)ev[7], p, j, v, value;

    spchi_get_dat_id((const uint8_t *)event, &d);
    for (p = 1; p <= SPCH_EVENT_PARMS; p++) {
        for (j = 0, r = rules; j < n; j++, r += 3) {
            if (p == SPCH_EVENT_PARMS) {
                if (r[1] != 0)
                    continue;
                value = 0;
            } else {
                if (r[1] != p)
                    continue;
                value = (int32_t)req[p];
            }
            bit = (1u << ((uint32_t)(7 - j) & 31)) & 0xff;
            s2 = 0;
            if (r[2] == 4) {
                if (req[r[1]] != 0)
                    s2 = bit;
            } else {
                v = gSpch.ruleTest != NULL
                    ? gSpch.ruleTest(event, r[0], value, d) : -1;
                if (v > 0)
                    s2 = bit;
                else if (v < 0)
                    fb |= bit;
            }
            res = (res | s2) & 0xff;
        }
    }
    *outFb = (uint8_t)fb;
    return res;
}

// Whether the sentence's rule values (byte 2) match the settings on its
// mask (byte 1), the fallback bits excepted.
int32_t spchi_check_sentence_rules(uint32_t a, uint32_t b, const uint8_t *sent)
{
    return ((sent[2] ^ (a & 0xff)) & sent[1] & ~(b & 0xff)) == 0;
}

// ---- spchrand: EA's add-with-carry generator, and a queue of the last
// values per key so that Rand avoids repeats

uint32_t spchi_eac_random(void)
{
    uint32_t *s = gSpch.seed, a, c, old;

    a = s[5] + s[4];
    c = a < s[5] || a < s[4];
    s[4] = a;
    old = s[3];
    a = a + old + c;
    c = a < old;
    s[3] = a;
    old = s[2];
    a = a + old + c;
    c = a < old;
    s[2] = a;
    old = s[1];
    a = a + old + c;
    c = a < old;
    s[1] = a;
    s[5]++;
    a = a + s[0] + c;
    s[0] = a;
    if (s[5] == 0 && ++s[4] == 0 && ++s[3] == 0 && ++s[2] == 0
        && ++s[1] == 0)
        a = ++s[0];
    return a;
}

void spchi_eac_seed_random(uint32_t x)
{
    uint32_t *s = gSpch.seed;

    s[0] = x + 0xf22d0e56u;
    s[1] = s[0] + 0x96041893u;
    s[2] = s[1] + 0x3df3b646u;
    s[3] = s[2] + 0x40dde76du;
    s[4] = s[3] + 0x97327ae1u;
    s[5] = s[4] + 0xd1a9fbe7u;
}

// How many of the key's last n values back val is (0 for the last), or
// -1.
int32_t spchi_find_rand_in_queue(uint32_t val, int32_t n, uint32_t key)
{
    int32_t j = gSpch.randIndex, cnt = 0, it;

    if (n >= SPCH_RAND_QUEUE + 1)
        n = SPCH_RAND_QUEUE;
    val &= 0xffff;
    key &= 0xffff;
    for (it = 0; it < SPCH_RAND_QUEUE + 1; it++) {
        if (cnt >= n)
            break;
        if (gSpch.randArr[j].key == key) {
            cnt++;
            if (gSpch.randArr[j].val == val)
                return cnt - 1;
        }
        if (--j < 0)
            j += SPCH_RAND_QUEUE;
    }
    return -1;
}

void spchi_add_rand_to_queue(uint32_t v, uint32_t key)
{
    if (++gSpch.randIndex >= SPCH_RAND_QUEUE)
        gSpch.randIndex = 0;
    gSpch.randArr[gSpch.randIndex].val = (uint16_t)v;
    gSpch.randArr[gSpch.randIndex].key = (uint16_t)key;
}

void spchi_init_random(int32_t game)
{
    int32_t i;

    for (i = 0; i < SPCH_RAND_QUEUE; i++) {
        gSpch.randArr[i].val = 0xffff;
        gSpch.randArr[i].key = 0xffff;
    }
    gSpch.randIndex = 0;
    spchi_eac_seed_random((uint32_t)game + ((uint32_t)game << 16));
}

static uint32_t rand_in(int32_t range)
{
    return ((spchi_eac_random() >> 16) * (uint32_t)range) >> 16;
}

// A number below range, avoiding the key's recent ones: up to 32 tries
// for one not among the last min(range / 2, 10), else the one seen
// longest ago goes into the queue. Retail returns the last try, which is
// not always the one it queued.
int32_t spchi_rand(int32_t range, int32_t key)
{
    int32_t m = range / 2, q, bq = -1, tries = 0;
    uint32_t k = (uint32_t)key & 0xffff, s1, s0;

    if (m >= 11)
        m = 10;
    s1 = rand_in(range);
    for (;;) {
        s0 = rand_in(range);
        q = spchi_find_rand_in_queue(s0, m, k);
        if (q == -1) {
            s1 = s0;
            break;
        }
        if (bq < q) {
            bq = q;
            s1 = s0;
        }
        if (++tries >= 32)
            break;
    }
    spchi_add_rand_to_queue(s1, k);
    return (int32_t)s0;
}
