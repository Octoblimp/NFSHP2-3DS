// spchi -- the SPCH library's state and its internal (iSPCH_) functions,
// shared by spch*.c and tools/src/spch_test.c. See spch.h.
//
// The data's layouts (docs/formats/spch.md has them in full):
// - an event: u16 ID, u16 life (ticks, 0 for none), u16 priority, u8
//   sentences, s8 rules, s8 repeat limit, s8 probability (0..100), u8
//   flags, a byte, then the sentences' u16 word offsets, the rules
//   ({ID, parameter, type} each) and the optional mask and follow group;
// - a sentence: a weight byte, the rule mask and values, (phrases << 2)
//   | the short rule, then the phrases' byte word offsets;
// - a phrase: u16 bank ID, the subbank's parameter, the bank type, s8
//   rules, three bytes, four rule references, four constant rules and
//   four u32 rule masks;
// - a bank: u16 ID, u16 subbank ID, flags, samples, the repeat queue's
//   length, the size unit less 1 (in 256 bytes), u16 end, u16 subbanks,
//   then the samples' entries (a big-endian u16 offset, then a byte a
//   parameter), the parameter IDs, the cycle bits, the repeat queue and
//   the template bits.

#ifndef SPCHI_H
#define SPCHI_H

#include <stdint.h>
#include <string.h>

#include "spch.h"

#define SPCH_MAGIC       0x1789a34u
#define SPCH_SLOTS       16
#define SPCH_PARTS       48
#define SPCH_CHOSEN      8
#define SPCH_PICK_PHRASES 12
#define SPCH_PICKS       100
#define SPCH_SAMPLE_PARMS 4
#define SPCH_RAND_QUEUE  32

static inline uint16_t spch_u16(const uint8_t *p)
{
    return (uint16_t)(p[0] | (p[1] << 8));
}

static inline uint32_t spch_u32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16)
        | ((uint32_t)p[3] << 24);
}

// A bank's parts: the samples' entries at 12, then the parameter IDs,
// the cycle part (its length, then a bit a sample), the repeat queue (its
// index, then a byte a slot) and the template bits.
static inline uint8_t *spch_bank_cycle(const uint8_t *b)
{
    uint32_t es = (b[4] & 0xfu) + 2;

    return (uint8_t *)b + 12 + b[5] * es + ((b[4] & 0x70u) >> 3);
}

static inline uint8_t *spch_bank_queue(const uint8_t *b)
{
    uint8_t *c = spch_bank_cycle(b);

    return (b[4] & 0x80) ? c + ((b[5] + 7) >> 3) + 1 : c;
}

// ---- the records

// An event queue slot, 96 bytes.
typedef struct SpchSlot {
    uint32_t       tick;                    //  0
    uint16_t       subTick;                 //  4
    uint8_t        active;                  //  6
    uint8_t        channel;                 //  7
    int16_t        isAppend;                //  8
    int16_t        next;                    // 10 the append chain, or -1
    const uint8_t *ev;                      // 12
    uint32_t       parms[SPCH_EVENT_PARMS]; // 16
} SpchSlot;

// The event queue, 0x0032b7a8.
typedef struct SpchQueue {
    int32_t  numPending[SPCH_CHANNELS];     //  0
    int32_t  lastAdded[SPCH_CHANNELS];      // 32
    int32_t  lastHead[SPCH_CHANNELS];       // 64
    int32_t  bumpFilter;                    // 96
    SpchSlot slot[SPCH_SLOTS];              // 100
} SpchQueue;

// A chosen sample: the bank's handle, the subbank (or -1) and the sample.
typedef struct SpchPart {
    int16_t  bank;
    int16_t  sub;
    uint16_t sample;
    uint16_t pad;
} SpchPart;

typedef struct SpchChosen {
    const uint8_t *ev;                      //  0
    const uint8_t *sent;                    //  4
    uint8_t        sentIdx;                 //  8
    uint8_t        valid;                   //  9
    uint8_t        b10, b11;                // 10
    uint32_t       parms[SPCH_EVENT_PARMS]; // 12
} SpchChosen;                               // 92

// The choice, 0x0032b290.
typedef struct SpchChoice {
    int32_t    channel;                     //   0
    int32_t    numChosen;                   //   4
    int32_t    numParts;                    //   8
    SpchPart   parts[SPCH_PARTS];           //  12
    SpchChosen chosen[SPCH_CHOSEN];         // 396
} SpchChoice;

// A phrase's picks: its bank and subbank (as GetPhraseBank finds them),
// where its samples start in picks[], how many and the current one.
typedef struct SpchPickEntry {
    int16_t bank;
    int16_t sub;
    uint8_t start;
    uint8_t cnt;
    uint8_t cur;
    uint8_t pad;
} SpchPickEntry;

typedef struct SpchPick {
    SpchPickEntry e[SPCH_PICK_PHRASES];     //  0
    uint8_t       nph;                      // 96
    uint8_t       numPicks;                 // 97
    uint8_t       picks[SPCH_PICKS];        // 98
} SpchPick;

// UnPackSample's record.
typedef struct SpchSample {
    int32_t size;
    int32_t offset;
    int32_t numParms;
    uint8_t parms[SPCH_SAMPLE_PARMS];
} SpchSample;

typedef struct SpchEventDat {
    const uint8_t *dat;
    uint32_t       channel;
} SpchEventDat;

// The event last played on a channel and how many times in a row.
typedef struct SpchInGame {
    uint32_t word;                          // its u16 ID first
    int32_t  count;
} SpchInGame;

typedef struct SpchFollow {
    int32_t        count;
    const uint8_t *list;                    // u16 event IDs
} SpchFollow;

typedef struct SpchRandEntry {
    uint16_t val;
    uint16_t key;
} SpchRandEntry;

// Retail's globals (0x0032b240 .. 0x0032bf28).
typedef struct SpchState {
    int32_t       addEventStatus;           // 0x0032b240
    int32_t       playStatus;               // 0x0032b244
    int32_t       lastMatchParmId;          // 0x0032b700
    int32_t       lastMatchParmValue;       // 0x0032b704
    uint32_t      initialized;              // 0x0032b720, SPCH_MAGIC
    uint8_t     **banks;                    // 0x0032b724
    int32_t       numBanks;                 // 0x0032b728
    int32_t       clearCycle;               // 0x0032b730
    SpchRequestFn request;                  // 0x0032b740 gCallbacks[0..4]
    SpchRuleTestFn ruleTest;
    SpchRuleSetFn ruleSet;
    SpchEventRuleFn eventRule;
    SpchReparmFn  reparm;
    SpchExtVecs   ext;                      // 0x0032b758
    SpchEventDat  eventDats[SPCH_EVENT_DATS];   // 0x0032b768
    SpchInGame    inGame[SPCH_CHANNELS];    // 0x0032be10
    int32_t       gameNum;                  // 0x0032be50
    int32_t       dataRate;                 // 0x0032be54
    int32_t       filter[SPCH_CHANNELS];    // 0x0032be58
    uint32_t      preLoadTicks;             // 0x0032be78
    uint32_t      lastTick;                 // 0x0032be7c
    uint16_t      lastSubTick;              // 0x0032be80
    uint32_t      seed[6];                  // 0x0032be88
    int32_t       randIndex;                // 0x0032bea0
    SpchRandEntry randArr[SPCH_RAND_QUEUE]; // 0x0032bea8
    SpchQueue     queue;                    // 0x0032b7a8
    SpchChoice    choice;                   // 0x0032b290
} SpchState;

extern SpchState gSpch;

// ---- spdprint, spabort, sptick

void     spchi_print(const char *fmt, ...);          // 0x00294f18 SPCHDBG_print
void     spchi_abort(const char *fmt, ...);          // 0x00294fa8 SPCHDBG_abortmessage
uint32_t spchi_gettick(void);                        // 0x00295ab0 SPCHEXT_gettick

// ---- spchinit, spchrslv

int32_t spchi_bind_data(const uint8_t *dat, uint32_t channel);   // 0x00290720
void    spchi_init_in_game(void);                    // 0x002908d8
void    spchi_init_ext_vecs(void);                   // 0x002909d8
void    spchi_init_callbacks(void);                  // 0x002909f0

// ---- spchbank

void    spchi_init_banks(void);                      // 0x00290ba8
void    spchi_dispose_banks(void);                   // 0x00290bc0
int32_t spchi_get_free_bank(void);                   // 0x00290c58
int32_t spchi_find_bank(uint32_t id);                // 0x00290cc8
int32_t spchi_find_sub_bank(uint32_t id, uint32_t sub);          // 0x00290d58
int32_t spchi_test_sub_bank_bounds(int32_t handle, uint32_t v);  // 0x00290df8
void    spchi_bank_add_to_queue(uint8_t *b, uint32_t sample);    // 0x00290e90
int32_t spchi_bank_get_sample_time_in_queue(const uint8_t *b,
                                            uint32_t sample);    // 0x00290f58
void    spchi_set_cycle_bits(uint8_t *b);            // 0x00291018

// ---- spchevnt

const uint8_t *spchi_search_event_dat(const uint8_t *dat, uint32_t id);  // 0x00291250
int32_t spchi_find_event_dat_info(const uint8_t *req, SpchEventDat **out); // 0x00291290
const uint8_t *spchi_find_event(const uint8_t *req); // 0x002912f0
int32_t spchi_find_event_channel(const uint8_t *req, int32_t *out);     // 0x00291340
int32_t spchi_get_dat_id(const uint8_t *req, int32_t *out);             // 0x00291390
void    spchi_init_event_dat(void);                  // 0x002913e0
int32_t spchi_get_filter_length(const uint8_t *req); // 0x00291410
void    spchi_init_event_queue(void);                // 0x00291450
int32_t spchi_find_event_slot(uint32_t pri, int32_t channel,
                              int32_t append);       // 0x00291518
int32_t spchi_check_last_event_index(int32_t channel);  // 0x002916a0
void    spchi_init_follow_data(SpchFollow *fd);      // 0x00291a40
int32_t spchi_event_in_follow_group(uint32_t id, const SpchFollow *fd); // 0x00291a50
int32_t spchi_choose_event_search(const SpchFollow *fd, int32_t channel); // 0x00291b18
int32_t spchi_choose_event(int32_t channel);         // 0x00291dd8
void    spchi_clear_event(int32_t i);                // 0x00291fd8
void    spchi_clear_old_events(int32_t k);           // 0x00292188
int32_t spchi_callback_event_rule(uint32_t *event);  // 0x00292328

// ---- spchpick

void    spchi_set_match_parm(int32_t id, int32_t v); // 0x00292738
int32_t spchi_get_match_parm(int32_t id);            // 0x00292750
void    spchi_clear_match_parm_value(void);          // 0x002927b0
int32_t spchi_match_sample(int32_t handle, const SpchSample *rec,
                           const uint8_t *ph, const uint32_t *parms); // 0x002927c8
int32_t spchi_get_phrase_bank(const uint8_t *ph, const uint32_t *parms,
                              SpchPickEntry *out);   // 0x002928d0
void    spchi_clear_cycle_bit(uint8_t *b, int32_t i);  // 0x00292a08
uint32_t spchi_test_bit(const uint8_t *p, int32_t i);  // 0x00292a70
uint32_t spchi_check_template_sample(const SpchPickEntry *pair,
                                     const uint8_t *b, int32_t idx); // 0x00292aa8
uint32_t spchi_sample_exists(const SpchPickEntry *pair, const uint8_t *b,
                             int32_t idx);           // 0x00292b70
int32_t spchi_choose_samples(SpchPick *ctx, const SpchPickEntry *pair,
                             const uint8_t *ph, const uint32_t *parms); // 0x00292c38
int32_t spchi_convert_time(int32_t x);               // 0x00292e08
int32_t spchi_sentence_length(const uint8_t *sent, const SpchPick *ctx); // 0x00292e70
int32_t spchi_decode_weight(uint32_t b);             // 0x00292f18
void    spchi_order_sentences(const uint8_t *ev, uint8_t *order); // 0x00292f40
int32_t spchi_repeat_event(const uint8_t *ev, int32_t channel);   // 0x002930b0
int32_t spchi_short_rule_status(const uint8_t *sent, int32_t mode); // 0x002930f8
int32_t spchi_get_bank_parm_id(int32_t handle, int32_t parm);     // 0x00293140
int32_t spchi_sentence_get_choices(SpchPick *ctx, const uint8_t *sent,
                                   const uint32_t *req, uint32_t rs,
                                   uint32_t fb, int32_t mode); // 0x002931e0
void    spchi_randomize_phrase_picks(uint8_t *arr, int32_t n);     // 0x002933d0
void    spchi_randomize_sentence_picks(const uint8_t *sent, SpchPick *ctx); // 0x00293450
int32_t spchi_iterate_choice(const uint8_t *sent, SpchPick *ctx);  // 0x00293520
int32_t spchi_choose_short_sentence(const uint8_t *sent, SpchPick *ctx,
                                    int32_t maxLen); // 0x002935a8
int32_t spchi_pick_phrase_sample(SpchPick *ctx, const uint8_t *ph,
                                 SpchPickEntry *e);  // 0x00293668
int32_t spchi_sentence_make_choice(SpchPick *ctx, const uint8_t *sent,
                                   int32_t mode, int32_t maxLen); // 0x00293950
void    spchi_constant_rule_set(uint32_t *event, const uint8_t *ev,
                                const uint8_t *sent, int32_t ps); // 0x00293a70
int32_t spchi_make_sample_requests(const uint8_t *sent, uint32_t *event,
                                   int32_t ps);      // 0x00293c00
void    spchi_init_sentence_pick_info(SpchPick *ctx);  // 0x00293dd8
void    spchi_init_sentence_choice(void);            // 0x00293de8
void    spchi_save_chosen_sentence(const SpchPick *ctx, int32_t channel,
                                   const uint8_t *ev, const uint8_t *sent,
                                   int32_t idx, const uint32_t *req); // 0x00293e70
int32_t spchi_one_chosen(int32_t channel);           // 0x00293f90
int32_t spchi_play_chosen(int32_t channel);          // 0x00293fb8
int32_t spchi_test_valid_parm(uint32_t mask, int32_t v, int32_t i); // 0x00294128
int32_t spchi_choose_sentence(const uint32_t *req);  // 0x00294178
int32_t spchi_choose_single_sentence(int32_t i);     // 0x00294570

// ---- spchrule

int32_t spchi_sentence_uses_parm(const uint8_t *sent, uint32_t p);  // 0x002950a0
int32_t spchi_get_rule_id(const uint8_t *ev, uint32_t i);           // 0x00295138
void    spchi_rule_set(uint32_t *event, const uint8_t *ev, int32_t si,
                       const uint32_t *parms);       // 0x002951b8
uint32_t spchi_get_rule_settings(uint32_t *event, const uint8_t *ev,
                                 const uint32_t *req, uint8_t *outFb); // 0x00295310
int32_t spchi_check_sentence_rules(uint32_t a, uint32_t b,
                                   const uint8_t *sent);  // 0x002954f8

// ---- spchrand

uint32_t spchi_eac_random(void);                     // 0x00295520
void     spchi_eac_seed_random(uint32_t x);          // 0x00295610
int32_t  spchi_find_rand_in_queue(uint32_t val, int32_t n, uint32_t key); // 0x00295680
void     spchi_add_rand_to_queue(uint32_t v, uint32_t key);  // 0x00295728
void     spchi_init_random(int32_t game);            // 0x00295770
int32_t  spchi_rand(int32_t range, int32_t key);     // 0x002957b0

// ---- spchsamp

void    spchi_init_sample(SpchSample *r);            // 0x002958c8
int32_t spchi_unpack_sample(const uint8_t *b, uint32_t idx, SpchSample *r); // 0x002958f0

#endif
