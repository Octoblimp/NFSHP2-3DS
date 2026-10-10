// spchpick -- spchpick.o of SPP2A380.A: choosing a sentence for an
// event, a sample for each of its phrases, and requesting them. See spch.h.

#include "spchi.h"

static const uint8_t *sentence_at(const uint8_t *ev, int32_t s)
{
    return ev + spch_u16(ev + 12 + 2 * s) * 4;
}

static const uint8_t *phrase_at(const uint8_t *sent, int32_t i)
{
    return sent + sent[4 + i] * 4;
}

// ---- the match parameter: a 254 rule's sample, matched by 255 rules

void spchi_set_match_parm(int32_t id, int32_t v)
{
    gSpch.lastMatchParmId = id;
    gSpch.lastMatchParmValue = v;
}

int32_t spchi_get_match_parm(int32_t id)
{
    if (gSpch.lastMatchParmId == id)
        return gSpch.lastMatchParmValue;
    spchi_print("Match parm not set.");
    return 0;
}

void spchi_clear_match_parm_value(void)
{
    gSpch.lastMatchParmId = -1;
    gSpch.lastMatchParmValue = 0;
}

// 0x00292680, iSPCH_MatchSampleDPRINT. Retail prints all the sample's
// parameters, past the record's four.
static void match_sample_dprint(int32_t handle, const SpchSample *rec,
                                const uint8_t *ph)
{
    int32_t i;

    spchi_print("bankID: %d bankHandle: %ld numRules: %ld\n", spch_u16(ph),
                (long)handle, (long)(int8_t)ph[4]);
    spchi_print("numParms: %ld - ", (long)rec->numParms);
    for (i = 0; i < rec->numParms && i < SPCH_SAMPLE_PARMS; i++)
        spchi_print("[%ld] = %d ", (long)i, rec->parms[i]);
    spchi_print("\n");
}

// Whether a sample suits the phrase: each of its rules' parameters must be
// in the rule's mask and, for a rule that names an event parameter, in
// that parameter's bits. Retail reads past the event's parameters for a
// reference of 20 or more; the port takes 0.
int32_t spchi_match_sample(int32_t handle, const SpchSample *rec,
                           const uint8_t *ph, const uint32_t *parms)
{
    int32_t nr = (int8_t)ph[4], t;

    if (nr >= 5) {
        spchi_abort("iSPCH_MatchSample - numRules > 4\n");
        return 0;
    }
    for (t = 0; t < nr; t++) {
        uint32_t v = rec->parms[t], bit, ref, pv;

        if (v >= 32) {
            match_sample_dprint(handle, rec, ph);
            spchi_abort("iSPCH_MatchSample error. bankID: %d\n", spch_u16(ph));
            return 0;
        }
        bit = 1u << v;
        if (!(bit & spch_u32(ph + 16 + 4 * t)))
            return 0;
        ref = ph[8 + t];
        if (ref == 0 || ref == 254 || ref == 255)
            continue;
        pv = ref < SPCH_EVENT_PARMS ? parms[ref] : 0;
        if (!(pv & bit))
            return 0;
    }
    return 1;
}

// The phrase's bank: by its ID (type 0), by its ID and the subbank an
// event parameter names (1), or by its ID with the parameter as the
// template's subbank index (2). Retail's type 2 reads past the event's
// parameters for a parameter of 20 or more; the port takes 0.
int32_t spchi_get_phrase_bank(const uint8_t *ph, const uint32_t *parms,
                              SpchPickEntry *out)
{
    uint32_t p = ph[2], id = spch_u16(ph), v;
    int32_t b;

    out->sub = -1;
    out->bank = -1;
    switch (ph[3]) {
    case 0:
        out->bank = (int16_t)spchi_find_bank(id);
        break;
    case 1:
        if (p >= SPCH_EVENT_PARMS) {
            spchi_print("iSPCH_GetPhraseBank - subBankID index = %ld - out of bounds\n",
                        (long)p);
            out->bank = -1;
            break;
        }
        // "bankID %d, subbank ID %d not found" went to the log.
        out->bank = (int16_t)spchi_find_sub_bank(id, parms[p] & 0xffff);
        break;
    case 2:
        b = spchi_find_bank(id);
        v = p < SPCH_EVENT_PARMS ? parms[p] : 0;
        if (spchi_test_sub_bank_bounds(b, v))
            out->sub = (int16_t)v;
        else
            b = -1;
        out->bank = (int16_t)b;
        break;
    }
    return out->bank > -1;
}

// ---- the cycle and template bits

void spchi_clear_cycle_bit(uint8_t *b, int32_t i)
{
    uint8_t *c = spch_bank_cycle(b);
    int32_t q = i / 8;

    c[1 + q] &= (uint8_t)~(1u << ((uint32_t)(i - 8 * q) & 31));
}

uint32_t spchi_test_bit(const uint8_t *p, int32_t i)
{
    int32_t q = i / 8;

    return p[q] & ((1u << ((uint32_t)(i - 8 * q) & 31)) & 0xff);
}

// The template bits: a bit a sample for each subbank, after the queue.
uint32_t spchi_check_template_sample(const SpchPickEntry *pair,
                                     const uint8_t *b, int32_t idx)
{
    const uint8_t *t;

    if (!(pair->sub < (int32_t)spch_u16(b + 10))) {
        spchi_abort("iSPCH_CheckTemplateSample - subBankIndex out of bounds. bankID: %d",
                    spch_u16(b));
        return 0;
    }
    t = spch_bank_queue(b);
    if (b[6] != 0)
        t += b[6] + 1;
    return spchi_test_bit(t, b[5] * pair->sub + idx);
}

// Whether the sample is in the template's subbank and in this game's
// share of the cycle. Retail lets idx == samples through.
uint32_t spchi_sample_exists(const SpchPickEntry *pair, const uint8_t *b,
                             int32_t idx)
{
    uint32_t r = 1;

    if (b[5] < idx) {
        spchi_abort("iSPCH_SampleExists - sampleIndex out of bounds.");
        return 0;
    }
    if (pair->sub != -1) {
        r = spchi_check_template_sample(pair, b, idx);
        if (r == 0)
            return 0;
    }
    if (b[4] & 0x80)
        r = spchi_test_bit(spch_bank_cycle(b) + 1, idx);
    return r;
}

// ---- choosing the samples

static int32_t add_sample_to_valid_picks(SpchPick *ctx, int32_t s)
{
    if (ctx->numPicks < SPCH_PICKS) {
        ctx->picks[ctx->numPicks++] = (uint8_t)s;
        return 1;
    }
    spchi_abort("iSPCH_AddSampleToValidPicks - ran out of pick space\n");
    return 0;
}

// The phrase's samples that match into picks[]: those not in the repeat
// queue, or else the one played longest ago. How many.
int32_t spchi_choose_samples(SpchPick *ctx, const SpchPickEntry *pair,
                             const uint8_t *ph, const uint32_t *parms)
{
    int32_t bi = pair->bank, best = -1, bq = 0, cnt = 0, n, s, q;
    uint8_t *b = gSpch.banks[bi];
    SpchSample rec;

    n = b[5];
    for (s = 0; s < n; s++) {
        if (!spchi_unpack_sample(b, (uint32_t)s, &rec))
            continue;
        if (!spchi_match_sample(bi, &rec, ph, parms))
            continue;
        if (!spchi_sample_exists(pair, b, s))
            continue;
        q = spchi_bank_get_sample_time_in_queue(b, (uint32_t)s);
        if (q > 0) {
            if (bq < q) {
                bq = q;
                best = s;
            }
        } else
            cnt += add_sample_to_valid_picks(ctx, s);
    }
    if (cnt == 0 && best != -1)
        cnt += add_sample_to_valid_picks(ctx, best);
    return cnt;
}

// Bytes of sample data into hundredths of a second.
int32_t spchi_convert_time(int32_t x)
{
    if (gSpch.dataRate == 0) {
        spchi_abort("ConvertTime - sample data rate not initialized.");
        return 0;
    }
    return x * 100 / gSpch.dataRate;
}

// The current picks' length, in hundredths of a second.
int32_t spchi_sentence_length(const uint8_t *sent, const SpchPick *ctx)
{
    int32_t nph = sent[3] >> 2, i, sum = 0;
    SpchSample rec;

    for (i = 0; i < nph; i++) {
        const SpchPickEntry *e = &ctx->e[i];

        if (spchi_unpack_sample(gSpch.banks[e->bank], ctx->picks[e->cur], &rec))
            sum += rec.size;
    }
    return spchi_convert_time(sum);
}

int32_t spchi_decode_weight(uint32_t b)
{
    static const int32_t multiple[8] = {
        1, 4, 16, 64, 256, 1024, 4096, 16384
    };

    return multiple[(b & 0xff) >> 5] * (int32_t)(b & 0x1f);
}

// The event's sentences in a random order by their weights, then those of
// weight 0 in theirs.
void spchi_order_sentences(const uint8_t *ev, uint8_t *order)
{
    int32_t n = ev[6], w[256], total = 0, c = 0, i, r, s;

    for (i = 0; i < n; i++) {
        w[i] = spchi_decode_weight(sentence_at(ev, i)[0]);
        total += w[i];
    }
    while (total > 0) {
        r = spchi_rand(total, -1);
        s = 0;
        if (n != 0) {
            r -= w[0];
            if (r >= 0)
                for (s = 1; s < n; s++) {
                    r -= w[s];
                    if (r < 0)
                        break;
                }
        }
        order[c++] = (uint8_t)s;
        total -= w[s];
        w[s] = 0;
    }
    for (i = 0; i < n; i++)
        if (spchi_decode_weight(sentence_at(ev, i)[0]) == 0)
            order[c++] = (uint8_t)i;
}

// Whether the event may play again: its repeat limit counts plays in a
// row on the channel.
int32_t spchi_repeat_event(const uint8_t *ev, int32_t channel)
{
    const SpchInGame *g = &gSpch.inGame[channel];

    if (spch_u16(ev) == (uint16_t)g->word && (int8_t)ev[8] > 0)
        return g->count < (int8_t)ev[8];
    return 1;
}

// The sentence's short rule against the filter: always, only when
// filtered hard (2), only when not, or never.
int32_t spchi_short_rule_status(const uint8_t *sent, int32_t mode)
{
    switch (sent[3] & 3) {
    case 0:
        return 1;
    case 1:
        return mode == 2;
    case 2:
        return mode != 2;
    }
    return 0;
}

// The bank's ID for its parameter `parm`: big-endian words after the
// samples' entries, the parameter in the top 3 bits.
int32_t spchi_get_bank_parm_id(int32_t handle, int32_t parm)
{
    const uint8_t *b = gSpch.banks[handle], *p;
    int32_t n = (b[4] & 0x70) >> 4, i;

    p = b + 12 + b[5] * ((b[4] & 0xf) + 2);
    for (i = 0; i < n; i++, p += 2) {
        uint32_t w = (uint32_t)(p[0] << 8) | p[1];

        if ((int32_t)(w >> 13) == parm)
            return (int32_t)(w & 0x1fff);
    }
    return -1;
}

// The sentence's rules, then each phrase's bank and samples into ctx.
// Retail's log messages ("Rejected by short rule.", "Failed sentence
// rules.", "bank not found for phrase %d", "no samples for phrase %d")
// are dropped.
int32_t spchi_sentence_get_choices(SpchPick *ctx, const uint8_t *sent,
                                   const uint32_t *req, uint32_t rs,
                                   uint32_t fb, int32_t mode)
{
    int32_t nph = sent[3] >> 2, i, c;

    if (nph >= SPCH_PICK_PHRASES + 1) {
        spchi_abort("Sentence has too many phrases.\n");
        return 0;
    }
    if (!spchi_short_rule_status(sent, mode))
        return 0;
    if (!spchi_check_sentence_rules(rs & 0xff, fb & 0xff, sent))
        return 0;
    ctx->nph = (uint8_t)nph;
    for (i = 0; i < nph; i++) {
        SpchPickEntry *e = &ctx->e[i];
        const uint8_t *ph = phrase_at(sent, i);

        e->start = ctx->numPicks;
        if (!spchi_get_phrase_bank(ph, req, e))
            return 0;
        c = spchi_choose_samples(ctx, e, ph, req);
        if (c == 0)
            return 0;
        e->cnt = (uint8_t)c;
    }
    return 1;
}

void spchi_randomize_phrase_picks(uint8_t *arr, int32_t n)
{
    int32_t i, j;
    uint8_t t;

    for (i = 0; i < n / 2; i++) {
        j = spchi_rand(n, n);
        t = arr[i];
        arr[i] = arr[j];
        arr[j] = t;
    }
}

void spchi_randomize_sentence_picks(const uint8_t *sent, SpchPick *ctx)
{
    int32_t nph = sent[3] >> 2, i, k, j;

    for (i = 0; i < nph; i++) {
        SpchPickEntry *e = &ctx->e[i];
        uint8_t *p = ctx->picks + e->start, t;

        for (k = 0; k < e->cnt >> 1; k++) {
            j = spchi_rand(e->cnt, e->bank);
            t = p[k];
            p[k] = p[j];
            p[j] = t;
        }
    }
}

// The next combination of picks, the last phrase fastest; 1 when they
// are all tried. Retail with no phrases steps the entry before ctx.
int32_t spchi_iterate_choice(const uint8_t *sent, SpchPick *ctx)
{
    int32_t i = (sent[3] >> 2) - 1;

    while (i >= 0) {
        SpchPickEntry *e = &ctx->e[i];

        e->cur++;
        if (e->cur < e->start + e->cnt)
            return 0;
        e->cur = e->start;
        i--;
    }
    return 1;
}

// The first combination shorter than maxLen; 0 if none is.
int32_t spchi_choose_short_sentence(const uint8_t *sent, SpchPick *ctx,
                                    int32_t maxLen)
{
    int32_t nph = sent[3] >> 2, i;

    for (i = 0; i < nph; i++)
        ctx->e[i].cur = ctx->e[i].start;
    for (;;) {
        if (spchi_sentence_length(sent, ctx) < maxLen)
            return 1;
        if (spchi_iterate_choice(sent, ctx) == 1)
            return 0;
    }
}

static uint32_t match_bit(const SpchSample *rec, int32_t t)
{
    uint32_t p = t < SPCH_SAMPLE_PARMS ? rec->parms[t] : 255;

    if (p == 255) {
        spchi_print("iSPCH_PickPhraseSample - match parm value = -1.\n");
        return 0;
    }
    return 1u << (p & 31);
}

// One of the phrase's picks. A rule referring 254 picks at random and
// sets the match parameter from it; one referring 255 takes a pick that
// matches it (the last, after shuffling); with neither, a random pick.
int32_t spchi_pick_phrase_sample(SpchPick *ctx, const uint8_t *ph,
                                 SpchPickEntry *e)
{
    const uint8_t *b = gSpch.banks[e->bank];
    int32_t nr = (int8_t)ph[4], t = 0, found = 0, any = 0, r, k, n, mv;
    SpchSample rec;

    while (t < nr && !found) {
        uint32_t ref = ph[8 + t], idx;

        if (ref == 254) {
            int32_t pid;

            any = 1;
            r = spchi_rand(e->cnt, e->bank);
            e->cur = (uint8_t)(e->start + r);
            idx = (e->start + r) & 0xff;
            pid = spchi_get_bank_parm_id(e->bank, t);
            if (spchi_unpack_sample(b, ctx->picks[idx], &rec))
                spchi_set_match_parm(pid, (int32_t)match_bit(&rec, t));
            found = 1;
        } else if (ref == 255) {
            any = 1;
            mv = spchi_get_match_parm(spchi_get_bank_parm_id(e->bank, t));
            n = e->cnt;
            if (n >= SPCH_PICKS + 1) {
                spchi_print("iSPCH_PickPhraseSample - numPicks out of range.");
                n = 0;
            }
            spchi_randomize_phrase_picks(ctx->picks + e->start, n);
            for (k = 0; k < n; k++) {
                idx = (e->start + k) & 0xff;
                if (!spchi_unpack_sample(b, ctx->picks[idx], &rec))
                    continue;
                if (match_bit(&rec, t) & (uint32_t)mv) {
                    e->cur = (uint8_t)idx;
                    found = 1;
                }
            }
            // "parm:%d matchValue:%d no matching sample found" went to
            // the log.
        }
        t++;
    }
    if (found)
        return 1;
    if (any)
        return 0;
    r = spchi_rand(e->cnt, e->bank);
    e->cur = (uint8_t)(e->start + r);
    return 1;
}

// A sample for each phrase: the shortest-fitting combination when
// filtered (mode 1), else by the phrases' rules.
int32_t spchi_sentence_make_choice(SpchPick *ctx, const uint8_t *sent,
                                   int32_t mode, int32_t maxLen)
{
    int32_t nph, i;

    spchi_clear_match_parm_value();
    if (mode == 1) {
        spchi_randomize_sentence_picks(sent, ctx);
        // "sentence failed event filter." went to the log.
        return spchi_choose_short_sentence(sent, ctx, maxLen);
    }
    nph = sent[3] >> 2;
    for (i = 0; i < nph; i++) {
        SpchPickEntry *e = &ctx->e[i];

        if (e->cnt == 0) {
            spchi_abort("iSPCH_SentenceMakeChoice - numPicks = 0\n");
            return 0;
        }
        if (!spchi_pick_phrase_sample(ctx, phrase_at(sent, i), e))
            return 0;
    }
    return 1;
}

// ---- playing the choice

// The phrases' constant rules, set from the chosen samples' parameters.
void spchi_constant_rule_set(uint32_t *event, const uint8_t *ev,
                             const uint8_t *sent, int32_t ps)
{
    int32_t nph = sent[3] >> 2, d = 0, i, j, rid;
    SpchSample rec;

    if (gSpch.ruleSet == NULL)
        return;
    spchi_get_dat_id((const uint8_t *)event, &d);
    for (i = 0; i < nph; i++) {
        const uint8_t *ph = phrase_at(sent, i);
        const SpchPart *part = &gSpch.choice.parts[i + ps];

        for (j = 0; j < 4; j++) {
            if (ph[12 + j] == 255)
                continue;
            rid = spchi_get_rule_id(ev, ph[12 + j]);
            if (spchi_unpack_sample(gSpch.banks[part->bank], part->sample, &rec))
                gSpch.ruleSet(event, rid,
                              (int32_t)(1u << (rec.parms[j] & 31)), d);
        }
    }
}

// Each chosen sample to the request callback and into its bank's repeat
// queue; the sentence's length in hundredths of a second. Retail leaves
// the dat's ID unset when the event's dat is gone; the port sends 0.
int32_t spchi_make_sample_requests(const uint8_t *sent, uint32_t *event,
                                   int32_t ps)
{
    int32_t nph = sent[3] >> 2, d = 0, ch = 0, total = 0, i;
    SpchSampleRequest req;
    SpchSample rec;

    if (gSpch.request == NULL) {
        spchi_abort("iSPCH_MakeSampleRequest - sample request callback not initialized.");
        return 0;
    }
    spchi_get_dat_id((const uint8_t *)event, &d);
    spchi_find_event_channel((const uint8_t *)event, &ch);
    for (i = 0; i < nph; i++) {
        const SpchPart *part = &gSpch.choice.parts[ps + i];
        uint8_t *b = gSpch.banks[part->bank];
        uint32_t s = part->sample;
        int32_t off;

        if ((b[4] & 0x80) && gSpch.clearCycle)
            spchi_clear_cycle_bit(b, (int32_t)s);
        if (!spchi_unpack_sample(b, s, &rec))
            continue;
        off = rec.offset;
        if (part->sub != -1)
            off += part->sub * (int32_t)(spch_u16(b + 8) * ((b[7] + 1) << 8));
        req.bank = part->bank;
        req.offset = off;
        req.size = rec.size;
        total += rec.size;
        req.event = *event;
        req.channel = ch;
        req.subBank = spch_u16(b + 2);
        req.datId = d;
        gSpch.request(&req);
        spchi_bank_add_to_queue(b, s);
    }
    return spchi_convert_time(total);
}

void spchi_init_sentence_pick_info(SpchPick *ctx)
{
    ctx->nph = 0;
    ctx->numPicks = 0;
}

void spchi_init_sentence_choice(void)
{
    SpchChoice *c = &gSpch.choice;
    int32_t i;

    c->channel = -1;
    c->numChosen = 0;
    c->numParts = 0;
    for (i = 0; i < SPCH_CHOSEN; i++) {
        c->chosen[i].ev = NULL;
        c->chosen[i].sent = NULL;
        c->chosen[i].sentIdx = 0;
        c->chosen[i].valid = 0;
        c->chosen[i].b11 = 0;
    }
    for (i = 0; i < SPCH_PARTS; i++) {
        c->parts[i].bank = -1;
        c->parts[i].sub = -1;
        c->parts[i].sample = 0;
        c->parts[i].pad = 0;
    }
}

// The sentence and its picks into the choice. Retail writes the parts
// past its 48 over the chosen sentences; the port refuses them.
void spchi_save_chosen_sentence(const SpchPick *ctx, int32_t channel,
                                const uint8_t *ev, const uint8_t *sent,
                                int32_t idx, const uint32_t *req)
{
    SpchChoice *c = &gSpch.choice;
    SpchChosen *s;
    int32_t t, nph = sent[3] >> 2, i;

    if (c->channel >= 0 && c->channel != channel) {
        spchi_abort("iSPCH_SaveChosenSentence - channel mismatch.");
        return;
    }
    t = c->numChosen++;
    if (t >= SPCH_CHOSEN) {
        spchi_abort("iSPCH_SaveChosenSentence - too many sentences.");
        return;
    }
    if (c->numParts + nph > SPCH_PARTS) {
        spchi_abort("iSPCH_SaveChosenSentence - too many phrases.");
        c->numChosen--;
        return;
    }
    c->channel = channel;
    s = &c->chosen[t];
    s->ev = ev;
    s->sent = sent;
    s->sentIdx = (uint8_t)idx;
    memcpy(s->parms, req, sizeof(s->parms));
    s->valid = 1;
    for (i = 0; i < nph; i++) {
        SpchPart *p = &c->parts[c->numParts + i];

        p->bank = ctx->e[i].bank;
        p->sub = ctx->e[i].sub;
        p->sample = ctx->picks[ctx->e[i].cur];
    }
    c->numParts += nph;
}

int32_t spchi_one_chosen(int32_t channel)
{
    return gSpch.choice.channel == channel && gSpch.choice.numChosen > 0;
}

// The chosen sentences' rules set and samples requested; the first one
// counts toward the channel's plays in a row. The number of samples.
// Retail goes on past eight sentences after the "too many" abort.
int32_t spchi_play_chosen(int32_t channel)
{
    SpchChoice *c = &gSpch.choice;
    int32_t n, i, ps = 0;

    if (!spchi_one_chosen(channel)) {
        spchi_init_sentence_choice();
        return 0;
    }
    n = c->numChosen;
    if (n > SPCH_CHOSEN)
        n = SPCH_CHOSEN;
    for (i = 0; i < n; i++) {
        const SpchChosen *s = &c->chosen[i];
        uint32_t w = s->parms[0];

        spchi_rule_set(&w, s->ev, s->sentIdx, s->parms);
        spchi_constant_rule_set(&w, s->ev, s->sent, ps);
        spchi_make_sample_requests(s->sent, &w, ps);
        ps += s->sent[3] >> 2;
        if (i == 0) {
            SpchInGame *g = &gSpch.inGame[channel];

            if ((uint16_t)w == (uint16_t)g->word)
                g->count++;
            else {
                g->word = w;
                g->count = 1;
            }
        }
    }
    spchi_init_sentence_choice();
    return ps;
}

// An exact-match mask's test of a parameter: set (1), not -1 (2), or
// never.
int32_t spchi_test_valid_parm(uint32_t mask, int32_t v, int32_t i)
{
    switch ((mask >> ((uint32_t)(2 * i) & 31)) & 3) {
    case 1:
        return v != 0;
    case 2:
        return v != -1;
    }
    return 0;
}

// A sentence for the event `req` names, into the choice: the sentences in
// their weighted order, the first whose rules, mask and phrases fit. 1 if
// one was chosen, 0 if none, -1 if the event has none.
int32_t spchi_choose_sentence(const uint32_t *req)
{
    uint32_t w = req[0], rs, valid = 0, bit;
    const uint8_t *ev, *mp = NULL;
    uint8_t order[512], fb = 0;
    int32_t ch, f, fl = 0, n, k, r = 0, i;
    SpchPick ctx;

    memset(&ctx, 0, sizeof(ctx));
    ev = spchi_find_event((const uint8_t *)&w);
    if (ev == NULL)
        return 0;
    if (!spchi_find_event_channel((const uint8_t *)&w, &ch))
        return 0;
    // "rejected by num in a row." went to the log.
    if (!spchi_repeat_event(ev, ch))
        return 0;
    f = gSpch.filter[ch];
    if (gSpch.queue.bumpFilter == 1 && ++f >= 3)
        f = 2;
    if (!(ev[10] & 1) && f == 1)
        f = 0;
    if (f)
        fl = spchi_get_filter_length((const uint8_t *)&w);
    rs = spchi_get_rule_settings(&w, ev, req, &fb);
    spchi_order_sentences(ev, order);
    n = ev[6];
    if (n <= 0)
        return -1;
    if (ev[10] & 8) {
        mp = ev + 12 + ((n * 2 + 3) & 0x3fc) + (((int8_t)ev[7] * 3 + 3) & ~3);
        // Retail tests all 19 parameters (and one past), but the bits
        // for the 16th on are 0.
        for (i = 0, bit = 1; i < 16; i++, bit <<= 1)
            if (spchi_test_valid_parm(spch_u32(mp), (int32_t)req[1 + i], i))
                valid |= bit;
    }
    for (k = 0; k < n && r == 0; k++) {
        int32_t s = order[k], g;
        const uint8_t *sent;

        if (s >= n) {
            spchi_abort("iSPCH_Event - invalid sentence num\n");
            return r;
        }
        sent = sentence_at(ev, s);
        if (mp != NULL && spch_u16(mp + 4 + 2 * s) != valid)
            continue;
        spchi_init_sentence_pick_info(&ctx);
        g = spchi_sentence_get_choices(&ctx, sent, req, rs, fb, f);
        if (g > 0) {
            r = spchi_sentence_make_choice(&ctx, sent, f, fl);
            if (r)
                spchi_save_chosen_sentence(&ctx, ch, ev, sent, s, req);
        } else if (g < 0)
            spchi_abort("iSPCH_ChooseSentence multibank error (see debug print message). sentence: %d, event ID %d\n",
                        s, (uint16_t)w);
    }
    return r;
}

// A sentence for queue slot i's event, asking the reparm callback to
// change its parameters while none fits.
int32_t spchi_choose_single_sentence(int32_t i)
{
    uint32_t *p = gSpch.queue.slot[i].parms;
    int32_t r = spchi_choose_sentence(p), k, s;

    if (r == 0 && gSpch.reparm != NULL)
        for (k = 0;; k++) {
            s = gSpch.reparm(k, p);
            if (s >= 0)
                r = spchi_choose_sentence(p);
            if (r != 0 || s <= 0)
                break;
        }
    return r > -1 ? r : 0;
}

void spch_set_pre_load_ticks(uint32_t ticks)
{
    gSpch.preLoadTicks = ticks;
}
