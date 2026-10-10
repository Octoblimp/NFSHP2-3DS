// sedwedge -- cSEDWedge (retail 0x002056f0 .. 0x00206760,
// indep/src/speech/sedwedge.cpp), the bSegment it fills (0x002761d0 ..
// 0x00276538), and Sound.obj's three calls on it: the wedge's creation in
// InitializeSoundDriver (0x001ae754), LoadLocalizedSpeechFiles
// (0x001ae4d8) and UnLoadLocalizedSpeechFiles (0x001ae5e8).
//
// The wedge sits between the speech library (spch.h) and bSound. It
// loads EVENTS.EVT and a language's BAN.PCK into the library, and each
// update plays the best pending event on channel 0: SPCH_Choose and
// SPCH_Play hand each chosen clip back as a bank and an offset, which
// becomes a bSegment of <language>DAT.PCK, and PlaySentence hands the
// segments to the bSampleChain as one sentence (bsound.h).
//
// Its status: 1 idle, 2 a sentence playing, 32 the sentence's sample has
// stopped (its callback's event 8), cleaned up on the next update. Retail
// also tests for 8, which nothing sets.
//
// Not ported, because nothing calls them: the destructor (the wedge is
// never deleted), isPlaying and IsPlaying (0x00206720, 0x00206740, the
// same code), and bSegment's empty destructor.
//
// docs/formats/sedwedge.md has the rest; tools/sedwedge_check.py runs
// retail's code against this.

#ifndef SEDWEDGE_H
#define SEDWEDGE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "bfile.h"
#include "bsound.h"
#include "spch.h"

#define SEDWEDGE_SEGMENTS    10
#define SEDWEDGE_BANK_PTRS   2000
#define SEDWEDGE_EVLOG_SIZE  2048

enum {
    SEDWEDGE_IDLE    = 1,
    SEDWEDGE_PLAYING = 2,
    SEDWEDGE_PAUSED  = 8,           // retail's tests; nothing sets it
    SEDWEDGE_STOPPED = 32,
};

// bSegment, 276 bytes: one clip of the DAT file.
typedef struct BSegment {
    char     name[256];             //   0
    int32_t  initialized;           // 256
    uint32_t offset;                // 260 in the DAT file, its VAG header's
    uint32_t size;                  // 264 the clip's, header and all
    uint32_t field268;              // 268 always 0
    uint32_t flags;                 // 272 Initialize's last word, always 0
} BSegment;

// cSEDWedge, 2180 bytes on the PS2: the port has no vtable at 2176.
typedef struct SedWedge {
    int32_t      initialized;       //    0 m_pInitialized
    uint8_t     *bankFile;          //    4 m_pBankFile, BAN.PCK
    uint8_t     *speechBank;        //    8 m_SpeechBank, the same
    int32_t      bankCount;         //   12 m_nBankCount
    int32_t      gameNumber;        //   16 m_nGameNumber
    uint8_t    **bankMem;           //   20 m_pBankMem
    uint8_t     *eventData;         //   24 m_pEventData, EVENTS.EVT
    bFile       *dataPackFile;      //   28 m_fDataPackFile
    char         dataPackFileName[32];  // 32 m_DataPackFileName
    SpchExtVecs *extVecs;           //   64 m_pExtVecs
    BSegment    *segment[SEDWEDGE_SEGMENTS];    // 68 m_pSegment
    int32_t      segmentCount;      //  108 m_nSegmentCount
    BSample     *sentenceSample;    //  112 m_pSentenceSample, the chain
    void        *slot;              //  116 m_pSlot, never used
    int32_t      status;            //  120 m_nStatus
    uint8_t      evLogBuffer[SEDWEDGE_EVLOG_SIZE];  // 124 m_EvLogBuffer
    int32_t      pauseState;        // 2172 m_pauseState
} SedWedge;

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char sedwedge_layout_check[
    (offsetof(SedWedge, extVecs) == 64
     && offsetof(SedWedge, status) == 120
     && offsetof(SedWedge, pauseState) == 2172
     && sizeof(BSegment) == 276) ? 1 : -1];
#endif

// ---- bSegment

void     bsegment_construct(BSegment *s);                   // 0x002761d0
// 0x00276388. Retail asserts that the segment is not yet initialized.
void     bsegment_initialize(BSegment *s, const char *name, uint32_t offset,
                             uint32_t size, uint32_t flags);
void     bsegment_cleanup(BSegment *s);                     // 0x00276470
uint32_t bsegment_get_offset(const BSegment *s);            // 0x00276500
uint32_t bsegment_get_size(const BSegment *s);              // 0x00276538

// ---- cSEDWedge

// 0x00205888. Idle, nothing loaded; it becomes m_pInstance and the clock
// is zeroed.
void    sedwedge_construct(SedWedge *w);
// 0x002056f0. The whole file into a block of its own; 1, or 0 when the
// file will not open.
int32_t sedwedge_load_data_file(SedWedge *w, const char *path,
                                uint8_t **out);
// 0x002057d8. A chosen clip as the next segment: `offset` past the bank's
// base in the DAT file. A bank past the table is ignored.
void    sedwedge_add_sentence_part(SedWedge *w, int32_t bank,
                                   uint32_t offset, uint32_t size);
// 0x00205ae8. The library up on `events` (EVENTS.EVT), `ban` and `dat`;
// `hdr` is not read. 1, or 0 when the events will not load.
int32_t sedwedge_initialize(SedWedge *w, const char *events, const char *hdr,
                            const char *dat, const char *ban, void *slot);
// 0x00205da8. Stops a sentence, with SoundEnabled; the fade is ignored.
void    sedwedge_fade(SedWedge *w, float fade);
// 0x00205e00. Pauses or resumes a sentence; the state is kept either way.
void    sedwedge_mute(SedWedge *w, bool on);
// 0x00205e58. The library down and everything loaded freed.
void    sedwedge_cleanup(SedWedge *w);
int32_t sedwedge_get_event_pending(SedWedge *w, int32_t channel);  // 0x00205f48
// 0x00205f90. SPCH_Choose and SPCH_Play on the channel; 1 when loaded.
int32_t sedwedge_queue_sentence_event(SedWedge *w, int32_t channel);
// 0x00205fd8. The segments played as one sentence; 1 when loaded.
int32_t sedwedge_play_sentence(SedWedge *w, int32_t channel, float volume);
int32_t sedwedge_stop_sentence(SedWedge *w, int32_t channel);      // 0x00206140
// 0x00206190. The library's queue emptied and a sentence stopped.
int32_t sedwedge_clear_event_queue(SedWedge *w);
// 0x002061e8. The clock from RealTimeFrames; a stopped sentence cleaned
// up; then, idle, the next pending event on channel 0 played.
void    sedwedge_update(SedWedge *w);

// The callbacks Initialize hands the library and the chain (0x00205998 ..
// 0x00205ae0). The abort message goes to stderr, where retail's went to
// the debug channel; the print, the rule's set and the event log's write
// do nothing, and no rule passes the test.
void     sedwedge_abort_message(const char *msg);           // S_AbortMessage
void     sedwedge_debug_print(const char *msg);             // S_DebugPrint
// S_TimerGetTick: the clock Update keeps, in whole milliseconds.
uint32_t sedwedge_timer_get_tick(void);
int32_t  sedwedge_test_sentence_rule(uint32_t *event, int32_t rule,
                                     int32_t value, int32_t dat);
void     sedwedge_set_sentence_rule(uint32_t *event, int32_t rule,
                                    int32_t value, int32_t dat);
// S_SentencePartRequest: AddSentencePart on m_pInstance.
void     sedwedge_sentence_part_request(SpchSampleRequest *r);
// S_SampleCallback: event 4 plays the chain again, with SoundEnabled and
// the speech on, and sets its volume to 1 either way; event 8 marks the
// wedge's sentence stopped.
void     sedwedge_sample_callback(uint32_t event, void *sample, void *data);
void     sedwedge_write_evlog(char *buf, int32_t size);     // S_WriteEVLog

// ---- Sound.obj's

// InitializeSoundDriver's 0x001ae754: a new wedge, kept at gp-19016.
// NULL when there is no memory for it.
SedWedge *sedwedge_create(void);
// gp-19016: the wedge, or NULL before sedwedge_create.
SedWedge *sedwedge_sound_instance(void);
// 0x001ae4d8. With SoundEnabled and the speech on, the wedge initialized
// on language `lang`'s files (English, French, German, Italian, Spanish,
// then English again); a language past those loads nothing.
void sedwedge_load_localized_speech_files(int32_t lang);
// 0x001ae5e8. With SoundEnabled, the wedge cleaned up.
void sedwedge_unload_localized_speech_files(void);

#endif
