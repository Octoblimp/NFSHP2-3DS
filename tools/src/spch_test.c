// Harness for tools/spch_check.py: runs the checker's script on the SPCH
// library (spch.c, spchbank.c, spchevnt.c, spchpick.c, spchrule.c) and
// prints what the model prints for retail's SPP2A380.A. The callbacks
// (the sample request, the rule test and set, the event rule, the
// reparm, the abort, the print and the clock) are logging fakes, the
// same fakes the checker gives retail's code. See the checker's
// docstring.
//
//     spch_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "spchi.h"

// ---------------------------------------------------------------- the data

#define MAXBLOB 256

static struct {
    char     nm[32];
    uint8_t *p;
    size_t   n;
} blobs[MAXBLOB];
static int nblobs;

static uint8_t **table;
static int32_t   tableN;

static SpchPick      ctx;
static SpchPickEntry pair;
static uint32_t      parms[SPCH_EVENT_PARMS];
static uint32_t      w;

static uint32_t clk;
static int32_t  rtRet[256];
static uint32_t rtMod, rsMod;
static int32_t  erQ[64], nEr, atEr;
static int32_t  rpQ[64][3], nRp, atRp;

static int hexval(int c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    return c - 'A' + 10;
}

static int blob_index(const char *nm)
{
    int i;

    for (i = 0; i < nblobs; i++)
        if (!strcmp(blobs[i].nm, nm))
            return i;
    printf("  no blob %s\n", nm);
    exit(3);
}

static uint8_t *blob_at(const char *nm, const char *off)
{
    return blobs[blob_index(nm)].p + strtoul(off, NULL, 0);
}

static void add_blob(const char *nm, uint8_t *p, size_t n)
{
    strncpy(blobs[nblobs].nm, nm, 31);
    blobs[nblobs].p = p;
    blobs[nblobs].n = n;
    nblobs++;
}

// A pointer as blob+offset, "0" or "?".
static const char *pname(const void *v)
{
    static char buf[4][48];
    static int k;
    const uint8_t *p = v;
    char *b = buf[k++ & 3];
    int i;

    if (p == NULL)
        return "0";
    for (i = 0; i < nblobs; i++) {
        if (p >= blobs[i].p && p < blobs[i].p + blobs[i].n) {
            snprintf(b, 48, "%s+%x", blobs[i].nm, (unsigned)(p - blobs[i].p));
            return b;
        }
    }
    return "?";
}

static void escaped(const char *s)
{
    for (; *s; s++) {
        if (*s == '\n')
            fputs("\\n", stdout);
        else
            putchar(*s);
    }
}

// ----------------------------------------------------------- the callbacks

static void cb_request(SpchSampleRequest *r)
{
    printf("  req bank=%d off=%d size=%d ev=%08x ch=%d sub=%d dat=%d\n",
           (int)r->bank, (int)r->offset, (int)r->size, (unsigned)r->event,
           (int)r->channel, (int)r->subBank, (int)r->datId);
}

static int32_t cb_rule_test(uint32_t *event, int32_t rule, int32_t value,
                            int32_t dat)
{
    int32_t v = rtRet[rule & 0xff];

    printf("  rtest ev=%08x rule=%d val=%d dat=%d -> %d\n", (unsigned)*event,
           (int)rule, (int)value, (int)dat, (int)v);
    *event ^= rtMod;
    return v;
}

static void cb_rule_set(uint32_t *event, int32_t rule, int32_t value,
                        int32_t dat)
{
    printf("  rset ev=%08x rule=%d val=%d dat=%d\n", (unsigned)*event,
           (int)rule, (int)value, (int)dat);
    *event ^= rsMod;
}

static int32_t cb_event_rule(uint32_t *event)
{
    int32_t v = atEr < nEr ? erQ[atEr++] : 1;

    printf("  erule ev=%08x -> %d\n", (unsigned)*event, (int)v);
    return v;
}

static int32_t cb_reparm(int32_t k, uint32_t *p)
{
    int32_t v = -1, i;

    printf("  reparm k=%d p=", (int)k);
    for (i = 0; i < SPCH_EVENT_PARMS; i++)
        printf(i ? ",%x" : "%x", (unsigned)p[i]);
    if (atRp < nRp) {
        v = rpQ[atRp][0];
        if (rpQ[atRp][1] >= 0)
            p[rpQ[atRp][1]] = (uint32_t)rpQ[atRp][2];
        atRp++;
    }
    printf(" -> %d\n", (int)v);
    return v;
}

static void cb_abort(const char *msg)
{
    fputs("  abort: ", stdout);
    escaped(msg);
    putchar('\n');
}

static void cb_print(const char *msg)
{
    fputs("  print: ", stdout);
    escaped(msg);
    putchar('\n');
}

static uint32_t cb_tick(void)
{
    return clk;
}

static void set_vecs(void)
{
    SpchExtVecs *v = spch_get_ext_vecs();

    v->abort = cb_abort;
    v->print = cb_print;
}

// --------------------------------------------------------------- the dumps

static void dump_state(void)
{
    SpchState *g = &gSpch;
    int i;

    printf("  st init=%d aes=%d ps=%d mp=%d,%d banks=%s nb=%d cc=%d game=%d"
           " rate=%d pre=%u lt=%u lst=%u\n",
           g->initialized == SPCH_MAGIC, (int)g->addEventStatus,
           (int)g->playStatus, (int)g->lastMatchParmId,
           (int)g->lastMatchParmValue,
           g->banks == NULL ? "0" : g->banks == table ? "table" : "?",
           (int)g->numBanks, (int)g->clearCycle, (int)g->gameNum,
           (int)g->dataRate, (unsigned)g->preLoadTicks,
           (unsigned)g->lastTick, (unsigned)g->lastSubTick);
    printf("  cb req=%d test=%d set=%d erule=%d reparm=%d tick=%d\n",
           g->request != NULL, g->ruleTest != NULL, g->ruleSet != NULL,
           g->eventRule != NULL, g->reparm != NULL, g->ext.gettick != NULL);
    printf("  dats");
    for (i = 0; i < SPCH_EVENT_DATS; i++)
        printf(" %s:%u", pname(g->eventDats[i].dat),
               (unsigned)g->eventDats[i].channel);
    printf("\n  ingame");
    for (i = 0; i < SPCH_CHANNELS; i++)
        printf(" %08x:%d", (unsigned)g->inGame[i].word, (int)g->inGame[i].count);
    printf("\n  filter");
    for (i = 0; i < SPCH_CHANNELS; i++)
        printf(" %d", (int)g->filter[i]);
    printf("\n  seed");
    for (i = 0; i < 6; i++)
        printf(" %08x", (unsigned)g->seed[i]);
    printf(" ri=%d\n  rq", (int)g->randIndex);
    for (i = 0; i < SPCH_RAND_QUEUE; i++)
        printf(" %04x:%04x", g->randArr[i].val, g->randArr[i].key);
    printf("\n");
}

static void dump_queue(void)
{
    SpchQueue *q = &gSpch.queue;
    int i, k;

    printf("  q np=");
    for (i = 0; i < SPCH_CHANNELS; i++)
        printf(i ? ",%d" : "%d", (int)q->numPending[i]);
    printf(" la=");
    for (i = 0; i < SPCH_CHANNELS; i++)
        printf(i ? ",%d" : "%d", (int)q->lastAdded[i]);
    printf(" lh=");
    for (i = 0; i < SPCH_CHANNELS; i++)
        printf(i ? ",%d" : "%d", (int)q->lastHead[i]);
    printf(" bump=%d\n", (int)q->bumpFilter);
    for (i = 0; i < SPCH_SLOTS; i++) {
        SpchSlot *s = &q->slot[i];

        printf("  slot %d t=%u st=%u a=%d ch=%d app=%d nx=%d ev=%s p=", i,
               (unsigned)s->tick, s->subTick, s->active, s->channel,
               s->isAppend, s->next, pname(s->ev));
        for (k = 0; k < SPCH_EVENT_PARMS; k++)
            printf(k ? ",%x" : "%x", (unsigned)s->parms[k]);
        printf("\n");
    }
}

static void dump_choice(void)
{
    SpchChoice *c = &gSpch.choice;
    int i, k;

    printf("  ch c=%d n=%d np=%d\n", (int)c->channel, (int)c->numChosen,
           (int)c->numParts);
    for (i = 0; i < SPCH_PARTS; i++) {
        SpchPart *p = &c->parts[i];

        if (p->bank != -1 || p->sub != -1 || p->sample || p->pad)
            printf("  part %d b=%d s=%d smp=%d pad=%d\n", i, p->bank, p->sub,
                   p->sample, p->pad);
    }
    for (i = 0; i < SPCH_CHOSEN; i++) {
        SpchChosen *s = &c->chosen[i];
        int any = s->ev || s->sent || s->sentIdx || s->valid || s->b10
            || s->b11;

        for (k = 0; k < SPCH_EVENT_PARMS; k++)
            any |= s->parms[k] != 0;
        if (!any)
            continue;
        printf("  chosen %d ev=%s sent=%s si=%d v=%d b10=%d b11=%d p=", i,
               pname(s->ev), pname(s->sent), s->sentIdx, s->valid, s->b10,
               s->b11);
        for (k = 0; k < SPCH_EVENT_PARMS; k++)
            printf(k ? ",%x" : "%x", (unsigned)s->parms[k]);
        printf("\n");
    }
}

static void dump_ctx(void)
{
    int i;

    printf("  ctx nph=%d np=%d e=", ctx.nph, ctx.numPicks);
    for (i = 0; i < SPCH_PICK_PHRASES; i++)
        printf(i ? ",%d/%d/%d/%d/%d/%d" : "%d/%d/%d/%d/%d/%d", ctx.e[i].bank,
               ctx.e[i].sub, ctx.e[i].start, ctx.e[i].cnt, ctx.e[i].cur,
               ctx.e[i].pad);
    printf(" p=");
    for (i = 0; i < SPCH_PICKS; i++)
        printf("%02x", ctx.picks[i]);
    printf("\n");
}

static void dump_table(void)
{
    uint32_t sum = 0;
    int i, n = 0;

    for (i = 0; i < tableN; i++) {
        const char *nm;

        if (table[i] == NULL)
            continue;
        n++;
        nm = pname(table[i]);
        if (!strncmp(nm, "pck+", 4))
            sum += (uint32_t)(i + 1) * (uint32_t)strtoul(nm + 4, NULL, 16);
        else
            printf("  btab %d=%s\n", i, nm);
    }
    printf("  btab n=%d pck=%08x\n", n, (unsigned)sum);
}

static void hex(const uint8_t *p, int n)
{
    int i;

    for (i = 0; i < n; i++)
        printf("%02x", p[i]);
}

// A bank's written parts: its cycle bits and its repeat queue.
static void dump_bank(int h)
{
    const uint8_t *b = gSpch.banks[h];
    const uint8_t *c = spch_bank_cycle(b);

    printf("  bank %d %s cyc=", h, pname(b));
    if (b[4] & 0x80)
        hex(c, 1 + ((b[5] + 7) >> 3));
    printf(" q=");
    if (b[6])
        hex(spch_bank_queue(b), 1 + b[6]);
    printf("\n");
}

// ------------------------------------------------------------------ the ops

static void set_parms(char **f, int nf, int from, uint32_t *p)
{
    int i;

    for (i = 0; i < SPCH_EVENT_PARMS; i++)
        p[i] = from + i < nf ? (uint32_t)strtoll(f[from + i], NULL, 0) : 0;
}

static void op(char **f, int nf)
{
#define I(k) ((k) < nf ? (int32_t)strtoll(f[k], NULL, 0) : 0)
#define U(k) ((k) < nf ? (uint32_t)strtoll(f[k], NULL, 0) : 0u)
#define B(k) blob_at(f[k], f[(k) + 1])
    const char *o = f[0];

    if (!strcmp(o, "blob")) {
        size_t n = strlen(f[2]) / 2, i;
        uint8_t *p = calloc(n + 64, 1);

        for (i = 0; i < n; i++)
            p[i] = (uint8_t)(hexval(f[2][2 * i]) * 16 + hexval(f[2][2 * i + 1]));
        add_blob(f[1], p, n);
    } else if (!strcmp(o, "file")) {
        FILE *fh = fopen(f[2], "rb");
        long n;
        uint8_t *p;

        if (fh == NULL) {
            printf("  no file %s\n", f[2]);
            exit(3);
        }
        fseek(fh, 0, SEEK_END);
        n = ftell(fh);
        fseek(fh, 0, SEEK_SET);
        p = calloc((size_t)n + 64, 1);
        if (fread(p, 1, (size_t)n, fh) != (size_t)n)
            exit(3);
        fclose(fh);
        add_blob(f[1], p, (size_t)n);
    } else if (!strcmp(o, "init")) {
        SpchExtVecs *v;

        printf("  = %d\n", (int)spch_init(I(1) ? cb_request : NULL, I(2), I(3)));
        v = spch_get_ext_vecs();
        printf("  vecs abort=%d print=%d\n", v->abort != NULL,
               v->print != NULL);
        set_vecs();
    } else if (!strcmp(o, "vecs")) {
        spch_get_ext_vecs()->gettick = I(1) ? cb_tick : NULL;
    } else if (!strcmp(o, "rulecb")) {
        spch_init_rule_callbacks(I(1) ? cb_rule_test : NULL,
                                 I(2) ? cb_rule_set : NULL);
    } else if (!strcmp(o, "reparmcb")) {
        spch_init_reparm_callback(I(1) ? cb_reparm : NULL);
    } else if (!strcmp(o, "erulecb")) {
        spch_init_event_rule_callback(I(1) ? cb_event_rule : NULL);
    } else if (!strcmp(o, "bankmem")) {
        tableN = I(1);
        table = calloc((size_t)tableN + 1, sizeof(*table));
        memset(table, 0xa5, ((size_t)tableN + 1) * sizeof(*table));
        printf("  size=%d\n", (int)(spch_get_bank_ptr_mem_size(tableN)
                                    / (int32_t)sizeof(*table)));
        spch_init_bank_mem(tableN, table);
    } else if (!strcmp(o, "addbank")) {
        printf("  = %d\n", (int)spch_add_bank(B(1)));
    } else if (!strcmp(o, "pckput")) {
        uint8_t *p = blobs[blob_index(f[1])].p;
        int32_t i;

        for (i = 0; i < I(2); i++)
            table[i] = p + spch_u32(p + 16 * i + 4);
    } else if (!strcmp(o, "pckadd")) {
        uint8_t *p = blobs[blob_index(f[1])].p;
        int32_t i;

        for (i = I(2); i < I(2) + I(3); i++)
            printf("  %d = %d\n", (int)i,
                   (int)spch_add_bank(p + spch_u32(p + 16 * i + 4)));
    } else if (!strcmp(o, "put")) {
        table[I(1)] = B(2);
    } else if (!strcmp(o, "freebank")) {
        spch_free_bank(I(1));
    } else if (!strcmp(o, "bankptr")) {
        printf("  = %s\n", pname(spch_get_bank_ptr(I(1))));
    } else if (!strcmp(o, "adddb")) {
        printf("  = %d\n", (int)spch_add_event_db(B(1), U(3)));
    } else if (!strcmp(o, "resolve")) {
        printf("  = %d\n", (int)spch_resolve_data(B(1)));
    } else if (!strcmp(o, "datinfo")) {
        uint32_t a = 0, b = 0;

        spch_get_event_dat_info(B(1), &a, &b);
        printf("  = %u %u\n", (unsigned)a, (unsigned)b);
    } else if (!strcmp(o, "rate")) {
        printf("  = %d\n", (int)spch_get_sample_data_rate(I(1), I(2), I(3)));
    } else if (!strcmp(o, "deinit")) {
        spch_deinit();
    } else if (!strcmp(o, "evlog")) {
        printf("  = %d\n", (int)spch_init_evlog(NULL, 0, NULL));
    } else if (!strcmp(o, "deevlog")) {
        spch_deinit_evlog();
    } else if (!strcmp(o, "saveevlog")) {
        spch_save_evlog();
    } else if (!strcmp(o, "tick")) {
        clk = U(1);
    } else if (!strcmp(o, "rt")) {
        rtRet[I(1) & 0xff] = I(2);
    } else if (!strcmp(o, "rtdef")) {
        int i;

        for (i = 0; i < 256; i++)
            rtRet[i] = I(1);
    } else if (!strcmp(o, "rtmod")) {
        rtMod = U(1);
    } else if (!strcmp(o, "rsmod")) {
        rsMod = U(1);
    } else if (!strcmp(o, "er")) {
        erQ[nEr++] = I(1);
    } else if (!strcmp(o, "rp")) {
        rpQ[nRp][0] = I(1);
        rpQ[nRp][1] = I(2);
        rpQ[nRp][2] = I(3);
        nRp++;
    } else if (!strcmp(o, "event")) {
        uint32_t p[SPCH_EVENT_PARMS];

        set_parms(f, nf, 1, p);
        printf("  = %d\n", (int)spch_add_event(p));
    } else if (!strcmp(o, "eventv")) {
        printf("  = %d\n", (int)spch_add_event_v(U(1), I(2), I(3), I(4), I(5),
                                                 I(6), I(7), I(8), I(9), I(10),
                                                 I(11), I(12), I(13), I(14),
                                                 I(15), I(16), I(17), I(18),
                                                 I(19), I(20), I(21)));
    } else if (!strcmp(o, "clearq")) {
        spch_clear_event_queue();
    } else if (!strcmp(o, "checkq")) {
        printf("  = %d\n", (int)spch_check_event_queue(I(1)));
    } else if (!strcmp(o, "playlast")) {
        printf("  = %d\n", (int)spch_play_last_event(I(1)));
    } else if (!strcmp(o, "play")) {
        printf("  = %d\n", (int)spch_play(I(1)));
    } else if (!strcmp(o, "playsp")) {
        printf("  = %d\n", (int)spch_play_speech());
    } else if (!strcmp(o, "choose")) {
        printf("  = %d\n", (int)spch_choose(I(1)));
    } else if (!strcmp(o, "choosesp")) {
        printf("  = %d\n", (int)spch_choose_speech());
    } else if (!strcmp(o, "filter")) {
        spch_set_filter(I(1), I(2));
    } else if (!strcmp(o, "preload")) {
        spch_set_pre_load_ticks(U(1));
    } else if (!strcmp(o, "slot")) {
        printf("  = %d\n", (int)spchi_find_event_slot(U(1), I(2), I(3)));
    } else if (!strcmp(o, "clrev")) {
        spchi_clear_event(I(1));
    } else if (!strcmp(o, "clrold")) {
        spchi_clear_old_events(I(1));
    } else if (!strcmp(o, "chev")) {
        printf("  = %d\n", (int)spchi_choose_event(I(1)));
    } else if (!strcmp(o, "chkl")) {
        printf("  = %d\n", (int)spchi_check_last_event_index(I(1)));
    } else if (!strcmp(o, "cs1")) {
        printf("  = %d\n", (int)spchi_choose_single_sentence(I(1)));
    } else if (!strcmp(o, "csent")) {
        printf("  = %d\n", (int)spchi_choose_sentence(parms));
    } else if (!strcmp(o, "erulecall")) {
        printf("  = %d\n", (int)spchi_callback_event_rule(&w));
        printf("  w=%08x\n", (unsigned)w);
    } else if (!strcmp(o, "parms")) {
        set_parms(f, nf, 1, parms);
    } else if (!strcmp(o, "w")) {
        w = U(1);
    } else if (!strcmp(o, "ctx0")) {
        memset(&ctx, 0, sizeof(ctx));
    } else if (!strcmp(o, "ctxe")) {
        SpchPickEntry *e = &ctx.e[I(1)];

        e->bank = (int16_t)I(2);
        e->sub = (int16_t)I(3);
        e->start = (uint8_t)I(4);
        e->cnt = (uint8_t)I(5);
        e->cur = (uint8_t)I(6);
    } else if (!strcmp(o, "ctxp")) {
        int i;

        for (i = 2; i < nf; i++)
            ctx.picks[I(1) + i - 2] = (uint8_t)I(i);
    } else if (!strcmp(o, "ctxn")) {
        ctx.nph = (uint8_t)I(1);
        ctx.numPicks = (uint8_t)I(2);
    } else if (!strcmp(o, "ctxd")) {
        dump_ctx();
    } else if (!strcmp(o, "pair")) {
        pair.bank = (int16_t)I(1);
        pair.sub = (int16_t)I(2);
        pair.start = (uint8_t)I(3);
        pair.cnt = (uint8_t)I(4);
        pair.cur = (uint8_t)I(5);
    } else if (!strcmp(o, "ms")) {
        SpchSample rec;
        int32_t u = spchi_unpack_sample(gSpch.banks[I(1)], U(2), &rec);

        printf("  = %d %d\n", (int)u,
               (int)spchi_match_sample(I(1), &rec, B(3), parms));
    } else if (!strcmp(o, "gpb")) {
        printf("  = %d\n", (int)spchi_get_phrase_bank(B(1), parms, &pair));
        printf("  pair %d %d\n", pair.bank, pair.sub);
    } else if (!strcmp(o, "ctb")) {
        printf("  = %u\n", (unsigned)spchi_check_template_sample(
                   &pair, gSpch.banks[I(1)], I(2)));
    } else if (!strcmp(o, "se")) {
        printf("  = %u\n", (unsigned)spchi_sample_exists(
                   &pair, gSpch.banks[I(1)], I(2)));
    } else if (!strcmp(o, "csm")) {
        printf("  = %d\n", (int)spchi_choose_samples(&ctx, &pair, B(1), parms));
    } else if (!strcmp(o, "convt")) {
        printf("  = %d\n", (int)spchi_convert_time(I(1)));
    } else if (!strcmp(o, "slen")) {
        printf("  = %d\n", (int)spchi_sentence_length(B(1), &ctx));
    } else if (!strcmp(o, "decw")) {
        printf("  = %d\n", (int)spchi_decode_weight(U(1)));
    } else if (!strcmp(o, "order")) {
        uint8_t order[512];
        const uint8_t *ev = B(1);
        int i;

        memset(order, 0xee, sizeof(order));
        spchi_order_sentences(ev, order);
        printf("  =");
        for (i = 0; i < ev[6]; i++)
            printf(" %d", order[i]);
        printf("\n");
    } else if (!strcmp(o, "repeat")) {
        printf("  = %d\n", (int)spchi_repeat_event(B(1), I(3)));
    } else if (!strcmp(o, "srs")) {
        printf("  = %d\n", (int)spchi_short_rule_status(B(1), I(3)));
    } else if (!strcmp(o, "bpid")) {
        printf("  = %d\n", (int)spchi_get_bank_parm_id(I(1), I(2)));
    } else if (!strcmp(o, "sgc")) {
        printf("  = %d\n", (int)spchi_sentence_get_choices(&ctx, B(1), parms,
                                                           U(3), U(4), I(5)));
    } else if (!strcmp(o, "rpp")) {
        spchi_randomize_phrase_picks(ctx.picks + I(1), I(2));
    } else if (!strcmp(o, "rsp")) {
        spchi_randomize_sentence_picks(B(1), &ctx);
    } else if (!strcmp(o, "itc")) {
        printf("  = %d\n", (int)spchi_iterate_choice(B(1), &ctx));
    } else if (!strcmp(o, "css")) {
        printf("  = %d\n", (int)spchi_choose_short_sentence(B(1), &ctx, I(3)));
    } else if (!strcmp(o, "pps")) {
        printf("  = %d\n", (int)spchi_pick_phrase_sample(&ctx, B(1),
                                                         &ctx.e[I(3)]));
    } else if (!strcmp(o, "smc")) {
        printf("  = %d\n", (int)spchi_sentence_make_choice(&ctx, B(1), I(3),
                                                           I(4)));
    } else if (!strcmp(o, "crs")) {
        spchi_constant_rule_set(&w, B(1), blob_at(f[1], f[3]), I(4));
        printf("  w=%08x\n", (unsigned)w);
    } else if (!strcmp(o, "msr")) {
        printf("  = %d\n", (int)spchi_make_sample_requests(B(1), &w, I(3)));
    } else if (!strcmp(o, "initspi")) {
        spchi_init_sentence_pick_info(&ctx);
    } else if (!strcmp(o, "initch")) {
        spchi_init_sentence_choice();
    } else if (!strcmp(o, "save")) {
        spchi_save_chosen_sentence(&ctx, I(1), B(2), blob_at(f[2], f[4]),
                                   I(5), parms);
    } else if (!strcmp(o, "onech")) {
        printf("  = %d\n", (int)spchi_one_chosen(I(1)));
    } else if (!strcmp(o, "playch")) {
        printf("  = %d\n", (int)spchi_play_chosen(I(1)));
    } else if (!strcmp(o, "tvp")) {
        printf("  = %d\n", (int)spchi_test_valid_parm(U(1), I(2), I(3)));
    } else if (!strcmp(o, "matchp")) {
        spchi_set_match_parm(I(1), I(2));
    } else if (!strcmp(o, "getmp")) {
        printf("  = %d\n", (int)spchi_get_match_parm(I(1)));
    } else if (!strcmp(o, "clrmp")) {
        spchi_clear_match_parm_value();
    } else if (!strcmp(o, "sue")) {
        printf("  = %d\n", (int)spchi_sentence_uses_parm(B(1), U(3)));
    } else if (!strcmp(o, "ruleid")) {
        printf("  = %d\n", (int)spchi_get_rule_id(B(1), U(3)));
    } else if (!strcmp(o, "rset")) {
        spchi_rule_set(&w, B(1), I(3), parms);
        printf("  w=%08x\n", (unsigned)w);
    } else if (!strcmp(o, "grs")) {
        uint8_t fb = 0xee;
        uint32_t rs = spchi_get_rule_settings(&w, B(1), parms, &fb);

        printf("  = %u %u w=%08x\n", (unsigned)rs, fb, (unsigned)w);
    } else if (!strcmp(o, "csr")) {
        printf("  = %d\n", (int)spchi_check_sentence_rules(U(1), U(2), B(3)));
    } else if (!strcmp(o, "rand")) {
        printf("  = %d\n", (int)spchi_rand(I(1), I(2)));
    } else if (!strcmp(o, "eacr")) {
        printf("  = %08x\n", (unsigned)spchi_eac_random());
    } else if (!strcmp(o, "seedr")) {
        spchi_eac_seed_random(U(1));
    } else if (!strcmp(o, "seed")) {
        int i;

        for (i = 0; i < 6; i++)
            gSpch.seed[i] = U(1 + i);
    } else if (!strcmp(o, "findrand")) {
        printf("  = %d\n", (int)spchi_find_rand_in_queue(U(1), I(2), U(3)));
    } else if (!strcmp(o, "addrand")) {
        spchi_add_rand_to_queue(U(1), U(2));
    } else if (!strcmp(o, "initrand")) {
        spchi_init_random(I(1));
    } else if (!strcmp(o, "unpack")) {
        SpchSample rec;
        int32_t r = spchi_unpack_sample(gSpch.banks[I(1)], U(2), &rec);

        printf("  = %d size=%d off=%d np=%d p=%d,%d,%d,%d\n", (int)r,
               (int)rec.size, (int)rec.offset, (int)rec.numParms,
               rec.parms[0], rec.parms[1], rec.parms[2], rec.parms[3]);
    } else if (!strcmp(o, "testbit")) {
        printf("  = %u\n", (unsigned)spchi_test_bit(B(1), I(3)));
    } else if (!strcmp(o, "ccb")) {
        spchi_clear_cycle_bit(gSpch.banks[I(1)], I(2));
    } else if (!strcmp(o, "setcyc")) {
        spchi_set_cycle_bits(gSpch.banks[I(1)]);
    } else if (!strcmp(o, "bqadd")) {
        spchi_bank_add_to_queue(gSpch.banks[I(1)], U(2));
    } else if (!strcmp(o, "bqtime")) {
        printf("  = %d\n", (int)spchi_bank_get_sample_time_in_queue(
                   gSpch.banks[I(1)], U(2)));
    } else if (!strcmp(o, "findbank")) {
        printf("  = %d\n", (int)spchi_find_bank(U(1)));
    } else if (!strcmp(o, "findsub")) {
        printf("  = %d\n", (int)spchi_find_sub_bank(U(1), U(2)));
    } else if (!strcmp(o, "tsbb")) {
        printf("  = %d\n", (int)spchi_test_sub_bank_bounds(I(1), U(2)));
    } else if (!strcmp(o, "poke")) {
        const char *k = f[1];

        if (!strcmp(k, "aes"))
            gSpch.addEventStatus = I(2);
        else if (!strcmp(k, "ps"))
            gSpch.playStatus = I(2);
        else if (!strcmp(k, "la"))
            gSpch.queue.lastAdded[I(2)] = I(3);
        else if (!strcmp(k, "lh"))
            gSpch.queue.lastHead[I(2)] = I(3);
        else if (!strcmp(k, "bump"))
            gSpch.queue.bumpFilter = I(2);
        else if (!strcmp(k, "cc"))
            gSpch.clearCycle = I(2);
        else if (!strcmp(k, "rate"))
            gSpch.dataRate = I(2);
        else if (!strcmp(k, "game"))
            gSpch.gameNum = I(2);
        else if (!strcmp(k, "lt"))
            gSpch.lastTick = U(2);
        else if (!strcmp(k, "lst"))
            gSpch.lastSubTick = (uint16_t)I(2);
        else if (!strcmp(k, "ingame")) {
            gSpch.inGame[I(2)].word = U(3);
            gSpch.inGame[I(2)].count = I(4);
        } else
            printf("  unknown poke %s\n", k);
    } else if (!strcmp(o, "pokenext")) {
        gSpch.queue.slot[I(1)].next = (int16_t)I(2);
    } else if (!strcmp(o, "ifg")) {
        static uint8_t list[128];
        SpchFollow fd;
        int k;

        fd.count = I(2);
        for (k = 0; k < fd.count && k < 64; k++) {
            list[2 * k] = (uint8_t)I(3 + k);
            list[2 * k + 1] = (uint8_t)(I(3 + k) >> 8);
        }
        fd.list = list;
        printf("  = %d\n", (int)spchi_event_in_follow_group(U(1), &fd));
    } else if (!strcmp(o, "state")) {
        dump_state();
    } else if (!strcmp(o, "q")) {
        dump_queue();
    } else if (!strcmp(o, "chd")) {
        dump_choice();
    } else if (!strcmp(o, "btab")) {
        dump_table();
    } else if (!strcmp(o, "bank")) {
        dump_bank(I(1));
    } else if (!strcmp(o, "hexb")) {
        printf("  ");
        hex(B(1), I(3));
        printf("\n");
    } else {
        printf("  unknown op %s\n", o);
    }
#undef I
#undef U
#undef B
}

int main(int argc, char **argv)
{
    static char line[1 << 20];
    FILE *fh;
    int i;

    if (argc < 2) {
        fprintf(stderr, "usage: spch_test script.txt\n");
        return 2;
    }
    fh = fopen(argv[1], "r");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
    for (i = 0; i < 256; i++)
        rtRet[i] = 1;
    set_vecs();
    while (fgets(line, sizeof(line), fh)) {
        char *f[64];
        int nf = 0;
        char *p;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        if (!strncmp(line, "blob|", 5)) {
            char *q = strchr(line + 5, '|');

            printf("> blob|%.*s\n", q ? (int)(q - line - 5) : 0, line + 5);
        } else
            printf("> %s\n", line);
        p = line;
        f[nf++] = p;
        while ((p = strchr(p, '|')) != NULL && nf < 64) {
            *p++ = 0;
            f[nf++] = p;
        }
        op(f, nf);
        fflush(stdout);
    }
    fclose(fh);
    return 0;
}
