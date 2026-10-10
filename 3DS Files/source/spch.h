// spch -- EA's speech library, SPP2A380.A (retail 0x00290720 ..
// 0x00295afc): the event queue, the banks, the sentence choice, the rules,
// its random and the sample unpacking.
//
// The game adds events (a speech event's ID and up to 19 parameters) as
// things happen. SPCH_Play picks the best pending event on a channel,
// one of its sentences whose rules the parameters pass, and for each of
// the sentence's phrases a sample from the phrase's bank that matches.
// Each chosen sample goes to the request callback as an offset and a
// size in the bank data (ENGLISHDAT.PCK); cSEDWedge streams them.
//
// The data is SOUND/SPEECH/EVENTS.EVT (the events, sentences and
// phrases) and <language>BAN.PCK (the banks). Both are read in place, so
// they must stay put while the library runs. The banks' repeat queues and
// cycle bits are written into the bank data.
//
// The port's names are retail's in snake case: SPCH_AddEvent is
// spch_add_event and the library's internal iSPCH_ functions are
// spchi_ (spchi.h). SPCHLOG, the debug event log, is dropped: it writes
// only its own buffer. docs/formats/spch.md has the formats and the rest;
// tools/spch_check.py runs retail's code against this.

#ifndef SPCH_H
#define SPCH_H

#include <stddef.h>
#include <stdint.h>

#define SPCH_CHANNELS     8
#define SPCH_EVENT_PARMS  20     // the event word and 19 parameters
#define SPCH_EVENT_DATS   8

// SPCHType_SampleRequestData, 28 bytes: one sample of a chosen sentence.
typedef struct SpchSampleRequest {
    int32_t  bank;      //  0 the bank's handle (its index in the bank table)
    int32_t  offset;    //  4 in the bank's sample data
    int32_t  size;      //  8
    uint32_t event;     // 12 the event word: the ID, then the dat's IDs
    int32_t  channel;   // 16
    int32_t  subBank;   // 20 the bank's subbank ID
    int32_t  datId;     // 24
} SpchSampleRequest;

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char spch_request_layout_check[
    (offsetof(SpchSampleRequest, channel) == 16
     && sizeof(SpchSampleRequest) == 28) ? 1 : -1];
#endif

typedef void    (*SpchRequestFn)(SpchSampleRequest *r);
// A rule's test and its set: the event word, the rule's ID, the value and
// the dat's ID. A test answers 0 (fails), above 0 (passes) or below 0
// (fails, and marks the rule's bit as a fallback).
typedef int32_t (*SpchRuleTestFn)(uint32_t *event, int32_t rule,
                                  int32_t value, int32_t dat);
typedef void    (*SpchRuleSetFn)(uint32_t *event, int32_t rule,
                                 int32_t value, int32_t dat);
// Asked of the chosen event: 1 plays it, anything else drops it.
typedef int32_t (*SpchEventRuleFn)(uint32_t *event);
// Asked, k = 0, 1, ..., to change an event's parameters when none of its
// sentences fit: at or above 0 tries again, at or below 0 stops.
typedef int32_t (*SpchReparmFn)(int32_t k, uint32_t *parms);

// SPCH_GetExtVecs' three: the abort and the print get the message
// formatted; gettick is the clock the events' lifetimes run on.
typedef struct SpchExtVecs {
    void     (*abort)(const char *msg);
    void     (*print)(const char *msg);
    uint32_t (*gettick)(void);
} SpchExtVecs;

// ---- spchinit, spchrslv, sputil

// 0x00290a68. Everything cleared, the random seeded from `game`; always 1.
int32_t      spch_init(SpchRequestFn request, int32_t game, int32_t rate);
void         spch_deinit(void);                                  // 0x00290b48
// 0x00290920. The sample data's rate: rate * bits / 8, then / 10 for
// mode 1 and * 2 / 7 for mode 2.
int32_t      spch_get_sample_data_rate(int32_t rate, int32_t bits,
                                       int32_t mode);
void         spch_init_rule_callbacks(SpchRuleTestFn test,
                                      SpchRuleSetFn set);         // 0x002909a0
void         spch_init_reparm_callback(SpchReparmFn fn);          // 0x00290a08
void         spch_init_event_rule_callback(SpchEventRuleFn fn);
// 0x00290858. An EVENTS.EVT on a channel; 1 if taken.
int32_t      spch_add_event_db(const uint8_t *dat, uint32_t channel);
int32_t      spch_resolve_data(const uint8_t *dat);              // 0x002908a8
SpchExtVecs *spch_get_ext_vecs(void);                            // 0x002908c8

// ---- spchbank

int32_t  spch_get_bank_ptr_mem_size(int32_t n);                  // 0x00290bd8
void     spch_init_bank_mem(int32_t n, uint8_t **table);         // 0x00290be0
uint8_t *spch_get_bank_ptr(int32_t handle);                      // 0x00290c18
void     spch_free_bank(int32_t handle);                         // 0x00290e60
// 0x002910e8. A bank into the first free slot; its handle, or -1.
int32_t  spch_add_bank(uint8_t *bank);

// ---- spchevnt

// 0x002916d0. parms[0] is the event word; 1 if queued.
int32_t spch_add_event(const uint32_t *parms);
// 0x002919d0. The event `id` with `count` int parameters (at most 19).
int32_t spch_add_event_v(uint32_t id, int32_t count, ...);
void    spch_clear_event_queue(void);                            // 0x00291f08
int32_t spch_check_event_queue(int32_t channel);                 // 0x00291fc0
int32_t spch_play_last_event(int32_t channel);                   // 0x00292358
// 0x002923e0. The chosen sentence's samples requested, choosing one first
// if none is; the number of samples, or 0.
int32_t spch_play(int32_t channel);
int32_t spch_play_speech(void);                                  // 0x00292488
int32_t spch_choose(int32_t channel);                            // 0x00292490
int32_t spch_choose_speech(void);                                // 0x002925f0
void    spch_set_filter(int32_t setting, int32_t channel);       // 0x00292610
void    spch_get_event_dat_info(const uint8_t *dat, uint32_t *a,
                                uint32_t *b);                    // 0x00292678

// ---- spchpick, spchlog

void    spch_set_pre_load_ticks(uint32_t ticks);                 // 0x00294638
// 0x00294648. Retail's debug log; the port keeps only the check that
// spch_init came first (1, or 0 with an abort).
int32_t spch_init_evlog(void *buf, int32_t size, void (*write)(char *, int32_t));
void    spch_deinit_evlog(void);                                 // 0x002946d8
void    spch_save_evlog(void);                                   // 0x002946f0

#endif
