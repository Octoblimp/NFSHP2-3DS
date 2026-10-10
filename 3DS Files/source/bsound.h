#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "bsnd.h"

// bSound -- EA's sample library over the bSnd driver: bSample, bRegion,
// bSound and bVoiceMgr, retail's src/bSample.cpp and src/bSound.cpp
// (0x002716f8-0x0027c730). The game's sounds -- engines, sirens, horns,
// tyres, collisions, the world, speech -- are all bSamples: a named patch
// in a named bank with its own volume, pan, pitch, fade and category, which
// takes a voice when it plays and gives it back when it stops.
//
//   bRegion::bRegion(const char*)        0x002716f8   328 bytes
//   bRegion::~bRegion                    0x00271840   284 bytes
//   bRegion::Sample(char*)               0x002719b8   272 bytes
//   bRegion::SetName                     0x00272c40   164 bytes
//   bSample::bSample / bSample(char)     0x00272ff0 / 0x00273098
//   bSample::~bSample                    0x00273148   112 bytes
//   bSample::Initialize (three)          0x00273210 / 0x00273280 / 0x002732c0
//   bSample::LockVoice                   0x00273388   268 bytes
//   bSample::SetName / SetBankName       0x00273498 / 0x00273520
//   bSample::SetPan / CalcPan            0x00273648 / 0x002736c8
//   bSample::SetPitch / CalcPitch        0x00273738 / 0x00273850
//   bSample::SetScaleVolume              0x00273be8   152 bytes
//   bSample::GetScaledVolume             0x00273c80   204 bytes
//   bSample::SetVolume / CalcVolume      0x00273d50 / 0x00273ed8
//   bSample::SetAzimuth / GetVolume      0x00273e70 / 0x00273f58
//   bSample::Play(char*, Ui, Ui)         0x00273ff8   136 bytes
//   bSample::Play(float, float, float)   0x00274080   908 bytes
//   bSample::IsPlaying / Pause / Stop    0x00274410 / 0x00274488 / 0x00274618
//   bSample::Mute / Fade / GetChannels   0x002747a0 / 0x00274868 / 0x00274960
//   bSample::Update                      0x00274a98   376 bytes
//   bSound::bSound / Initialize          0x002776c0 / 0x00277820
//   bSound::Update                       0x002778f8   136 bytes
//   bSound::Region / LoadRegion          0x00277a18 / 0x00277b00
//   bSound::UnloadRegion                 0x00277c00   176 bytes
//   bSound::Set/GetCategoryVolume        0x00277cb0 / 0x00277dc0
//   bSound::SetPath / SetMode            0x00277e38 / 0x00278190
//   bSound::updatePendingRegions         0x00277f38   336 bytes
//   bVoiceMgr::Initialize / GetVoice     0x0027ac80 / 0x0027ad00
//   bVoiceMgr::ReleaseVoice / Update     0x0027af48 / 0x0027b2f0
//
// The library is -O0 code and the port follows it statement by statement,
// its quirks with it: GetPitch answers the current volume, CalcPitch's
// table is read one step high, a fade's near-end poll only runs while a fade
// is in progress. Each is noted where it happens. Its debug output
// (bSound::Printf, PrintVoiceAllocsAndReleases, the asserts) is left out.
//
// Not ported, because nothing calls them: bSample's GetPan (which reads the
// near-end flag), GetSampleVolume (which reads the callback), GetFlags and
// IsLooping. bSampleStream and bSampleChain, the speech's subclasses, come
// with the speech.
//
// Written up in docs/formats/bsound.md; checked on retail's image by
// tools/bsound_check.py.

typedef struct BSample BSample;
typedef struct BRegion BRegion;
typedef struct BSound BSound;

// The callback bSound's client and each bSample take: retail's
// void (*)(unsigned, unsigned, unsigned) -- the event, the bSample or the
// bRegion it is about, and the word registered with the callback.
typedef void (*BSoundCallback)(uint32_t event, void* what, void* data);

// The events, as bSound::notifyClient and the bSample callbacks raise them.
enum {
    BSOUND_REGION_LOADED = 2,   // updatePendingRegions: `what` is the bRegion
    BSOUND_SAMPLE_NEAR_END = 4, // bSample::Update, a stream nearing its end
    BSOUND_SAMPLE_STOPPED = 8,  // bSample::Stop
};

// bVoice, 8 bytes: a channel number and the bSample holding it. The voice
// manager's 48 of them are 0x00327c88.
typedef struct BVoice {
    uint16_t id;
    BSample* sample;
} BVoice;

#define BVOICE_COUNT 48

// bFragmentedVector<T*>: in retail a list of fragments, each a block of
// slots that never moves, the vector growing by adding one more; here one
// block, reallocated when it grows, which nothing outside can tell apart.
// What can be told: slots past the count keep what was last in them, and
// find looks at every slot there is (bsound.c).
typedef struct BPtrVec {
    void**  items;
    int32_t count;
    int32_t capacity;
} BPtrVec;

// bSample, 188 bytes from a slot pool of 255 ("bSoundSamples"), which
// clears each slot on the way out. Retail's offsets in the comments.
struct BSample {
    uint32_t rate;             // 0   the rate CalcPitch scales when Type != 0
    int32_t  nearEndNotified;  // 4
    int32_t  field8;           // 8   cleared by the constructors, never read
    BVoice*  voice;            // 12  m_pVoice
    uint32_t offset;           // 16  m_Offset
    uint32_t size;             // 20  m_Size
    float    currentVolume;    // 24  m_fCurrentVolume
    float    scaleVolume;      // 28  m_fScaleVolume
    float    fadeTarget;       // 32  m_fFadeTargetVolume
    float    fadeAdjust;       // 36  m_fFadeUpdateAdjust, per Update
    float    currentPan;       // 40  m_fCurrentPan
    float    currentPitch;     // 44  m_fCurrentPitch
    BSoundCallback callback;   // 48  m_CallbackFcn
    void*    callbackData;     // 52  m_CallbackData
    char     name[32];         // 56  m_Name
    char     bankName[32];     // 88  m_BankName
    uint16_t volumeBeforeMuting; // 120
    int32_t  muted;            // 124
    int32_t  paused;           // 128
    uint32_t category;         // 132 0..15, bSound's category volumes
    int8_t   type;             // 136 0: a bank's patch; else `rate` and full volume
    int32_t  voiceLock;        // 140 LockVoice's: keep the voice when stopped
    int32_t  voiceLockPlaying; // 144
    uint16_t sampleId;         // 148 bSnd_GetPatchID's, 0xfffa when none
    char     defaultName[32];  // 152 never written by this library
};

// bRegion, 64 bytes from a slot pool of 32 ("bSoundRegions"): a loaded
// bank and one bSample per patch in it, in the bank's order.
struct BRegion {
    char    name[33];          // 0
    BPtrVec samples;           // 40  bFragmentedVector<bSample*>
};

// bSound, 456 bytes, the one instance (0x00332370 points at it).
struct BSound {
    BRegion* common;           // 4   the region named "common"
    int32_t  status;           // 8   1 once Initialize has run
    float    categoryVolume[16]; // 12
    BSoundCallback client;     // 76
    void*    clientData;       // 80
    char     pending[1][256];  // 84  the region being loaded; only one at once
    int32_t  pendingCount;     // 340
    BPtrVec  regions;          // 344 bFragmentedVector<bRegion*>
    // 368, bFragmentedVector<bCategory>, is constructed and destroyed and
    // nothing else: the category volumes above are what the code uses.
    char     path[64];         // 392 SetPath's, 63 characters of it
    BsndDriver* driver;        // the port's: what retail's bSnd_* globals are
};

// -- bSound --------------------------------------------------------------------

// The constructor and Initialize together: the client's callback, the
// slot pools, the voice manager, room for 16 regions, every category at
// 1.0 and status 1. With no driver the status stays 0, and LoadRegion and
// Update do nothing, as retail's do before Initialize. Makes `s` the
// instance bsound_get returns, which every bSample reaches.
void bsound_init(BSound* s, BsndDriver* d, BSoundCallback client,
                 void* clientData);
BSound* bsound_get(void);

// 0x002778f8. With status 1: the driver's update, a pending region made
// once its bank is in, and the voice manager's update.
void bsound_update(BSound* s);

BRegion* bsound_common_region(const BSound* s);           // 0x002779e0
BRegion* bsound_region(const BSound* s, const char* name); // 0x00277a18
// 0x00277b00. Starts the bank's load and makes it pending: 0 without
// status 1, when the load fails, or when a region is already pending.
// The bRegion is made by the next bsound_update.
int32_t bsound_load_region(BSound* s, const char* name);
void bsound_unload_region(BSound* s, const char* name);   // 0x00277c00
// 0x00277cb0: every playing sample of the category takes its volume again.
void bsound_set_category_volume(BSound* s, uint32_t category, float v);
float bsound_get_category_volume(const BSound* s, uint32_t category);
void bsound_set_path(BSound* s, const char* path);        // 0x00277e38
int32_t bsound_get_status(const BSound* s);               // 0x00277ea0
// 0x00278190: 0 mono, 1 stereo, 2 Prologic; anything else is ignored.
void bsound_set_mode(BSound* s, int32_t mode);

int32_t bsound_region_count(const BSound* s);
BRegion* bsound_region_at(const BSound* s, int32_t i);

// The voice manager's records, and the two slot pools, for the checker.
const BVoice* bsound_voices(void);
struct BSlotPool* bsound_sample_pool(void);
struct BSlotPool* bsound_region_pool(void);

// -- bRegion -------------------------------------------------------------------

// new bRegion(name): a bSample for each of the bank's patches.
BRegion* bregion_new(const char* name);
// delete: its samples deleted, front first, then the bank unloaded.
void bregion_delete(BRegion* r);
// 0x002719b8: the first sample whose name matches without regard to case.
BSample* bregion_sample(const BRegion* r, const char* name);
const char* bregion_name(const BRegion* r);
int32_t bregion_sample_count(const BRegion* r);
BSample* bregion_sample_at(const BRegion* r, int32_t i);

// -- bSample -------------------------------------------------------------------

// The two constructors, on storage the caller owns (a class that holds a
// bSample by value), and new/delete, which take a slot of the pool.
void bsample_construct(BSample* s, int8_t type);
void bsample_destruct(BSample* s);
BSample* bsample_new(int8_t type);
void bsample_delete(BSample* s);

void bsample_initialize_copy(BSample* s, const BSample* other);
void bsample_initialize_callback(BSample* s, BSoundCallback cb, void* data);
void bsample_initialize(BSample* s, const char* name, const char* bank);

void bsample_lock_voice(BSample* s);
void bsample_set_name(BSample* s, const char* name);
void bsample_set_bank_name(BSample* s, const char* bank);
const char* bsample_get_name(const BSample* s);
const char* bsample_get_bank_name(const BSample* s);
void bsample_set_category(BSample* s, uint32_t category);

// Pan is -0.5..0.5 (CalcPan scales by 255), pitch is in octaves, volume
// is 0..1 of the patch's own.
void bsample_set_pan(BSample* s, float pan);
int8_t bsample_calc_pan(const BSample* s, float pan);
// The voice's channel, or 9999 without a voice.
int32_t bsample_set_pitch(BSample* s, float pitch);
uint32_t bsample_calc_pitch(const BSample* s, float pitch);
void bsample_set_scale_volume(BSample* s, float scale);
float bsample_get_scaled_volume(const BSample* s);
void bsample_set_volume(BSample* s, float volume);
uint16_t bsample_calc_volume(const BSample* s, float volume);
void bsample_set_azimuth(BSample* s, uint16_t azimuth);
float bsample_get_volume(const BSample* s);

// 0x00273ff8: the name, offset and size set, then played at the current
// volume, centred, at pitch 0.
BVoice* bsample_play_named(BSample* s, const char* name, uint32_t offset,
                           uint32_t size);
// 0x00274080. Stops what the voice was playing, takes a voice if it has
// none, and plays. NULL when there was no voice to be had.
BVoice* bsample_play(BSample* s, float volume, float pan, float pitch);
bool bsample_is_playing(const BSample* s);
void bsample_pause(BSample* s, bool pause);
void bsample_stop(BSample* s);
void bsample_mute(BSample* s, bool mute);
// 0x00274868. Under 33 ms the volume is simply set; otherwise Update steps
// it towards `volume` of the scaled volume, a step each 1/60 s.
void bsample_fade(BSample* s, float volume, uint32_t ms);
uint32_t bsample_get_channels(const BSample* s);
void bsample_update(BSample* s);

int8_t bsample_get_type(const BSample* s);
int32_t bsample_is_voice_locked_playing(const BSample* s);
int32_t bsample_is_voice_locked(const BSample* s);
void bsample_release_voice(BSample* s);
uint32_t bsample_get_category(const BSample* s);
int32_t bsample_is_paused(const BSample* s);
// GetPitch, 0x00275de0, which reads m_fCurrentVolume and not the pitch.
// SetCategoryVolume relies on it doing so.
float bsample_get_pitch(const BSample* s);
void bsample_set_callback(BSample* s, BSoundCallback cb, void* data);
