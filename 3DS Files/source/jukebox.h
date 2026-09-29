#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// The jukebox: EA's cJukeboxPlayer and cJukeboxCartridge (bJukebox.cpp in
// the asserts), the game's sound::jukebox wrapper round them, and the half of
// DataAudioOptionsScreen that is the playlist. Retail's code throughout; the
// file layout is docs/formats/jukebox.md.
//
// Like bsnd.c this is free of <3ds.h>: the sample it plays is a JBHost, so
// tools/jukebox_check.py can run it next to retail's image in mipsemu. The
// 3DS stream behind the host is jbstream.c.
//
// Where retail keeps things:
//   Jukebox                   0x003115d0   the one cJukeboxPlayer, 8868 bytes
//   SoundEnabled/MusicEnabled gp-23056/-23048, both 1
//   the one-shot picks        gp-18928/-18924/-18920/-18916, all 1
//   DelayedStart's timer      gp-19028
//   the saved volumes         0x00313878, five floats, all -1.0 in the image
//   Fred's DataAudioOptions   0x002fc0e4, Fred+148, 176 bytes

#define JB_MAX_CATEGORIES 16      // m_pCategory[16]
#define JB_MAX_TUNES      128     // m_pTune[128], and a category's index
#define JB_HEADER_SIZE    32      // m_FormHeader
#define JB_NAME_MAX       96      // an index entry is 96 bytes, name at +12
#define JB_PATH_MAX       64

// JUKEBOX_STATE, m_StatePlay.
enum {
    JB_NOTINUSE = 0, JB_LOADING, JB_PLAYING, JB_PAUSED,
    JB_DONE_PLAYING, JB_FADING, JB_DONE_FADING,
};

// What the sample tells SampleCallback (0x0027e1d8). The names are the
// bJukebox Info strings each case prints.
#define JB_EVENT_BUFFERED   4     // "first buffer just loaded"
#define JB_EVENT_PLAY_END   8     // "Got play end in callback"
#define JB_EVENT_FADE_END   32    // "Got fade end in callback"
#define JB_EVENT_BUFFERED2  64    // the same as 4
#define JB_EVENT_IGNORED    128

// The bSampleStream the player owns (m_pPlayingSample): new'd once by
// LoadCartridge and kept, deleted by Close. Each call is the bSample method
// named, on that one sample.
typedef struct {
    void* ctx;
    // __13bSampleStreamc(2), Initialize(SampleCallback, this),
    // SetSampleRate(GetSampleRate()): the three in a row.
    void (*create)(void* ctx, uint32_t rate);
    void (*destroy)(void* ctx);                   // the virtual destructor
    // Play__7bSamplePCcUiUi: the file, by name, and a byte range of it.
    void (*load)(void* ctx, const char* path, uint32_t offset, uint32_t size);
    // Play__7bSamplefff: start what load buffered.
    void (*play)(void* ctx, float volume, float a, float b);
    void (*stop)(void* ctx);                      // Stop__7bSample
    void (*pause)(void* ctx, bool on);            // Pause__7bSampleb
    void (*fade)(void* ctx, float to, uint32_t ms); // Fade__7bSamplefUi
    void (*cleanup)(void* ctx);                   // Cleanup__7bSample
    void (*set_category)(void* ctx, uint32_t cat);  // SetCategory__7bSampleUi
    void (*set_scale_volume)(void* ctx, float v);   // SetScaleVolume__7bSamplef
    // The cartridge file: bOpen, bRead, bClose.
    void* (*open)(void* ctx, const char* path);
    int   (*read)(void* ctx, void* file, void* buf, uint32_t n);
    void  (*close)(void* ctx, void* file);
    // bSound::GetStatus() == 1: the sound driver is up. LoadCartridge
    // does nothing without it.
    int   (*sound_up)(void* ctx);
    // bAssertFail. Retail's ends in bBreak, a `break`: the game stops.
    void  (*assert_fail)(void* ctx, int line);
} JBHost;

// tJukeboxTune, 24 bytes.
typedef struct {
    char     name[JB_NAME_MAX];   // szName, new'd
    uint32_t use;                 // bUse
    uint32_t size;                // nSize
    uint32_t offset;              // nOffset
    uint32_t syncSize;            // nSyncSize
    uint32_t id;                  // nID
} JBTune;

// tJukeboxCategory, 528 bytes.
typedef struct {
    char     name[JB_NAME_MAX];   // szName
    uint32_t numTunes;            // nNumTunes
    uint32_t use;                 // bUse
    uint32_t lastTunePlayed;      // nLastTunePlayed
    uint32_t tuneIndex[JB_MAX_TUNES];   // pTuneIndex
} JBCategory;

// cJukeboxPlayer, cJukeboxCartridge at its head. The two arrays hold what
// retail news, so a slot is live below its count and nothing past it is.
typedef struct {
    uint32_t   numCategories;               // +0
    JBCategory category[JB_MAX_CATEGORIES]; // +4, pointers
    uint32_t   numTunes;                    // +68
    JBTune     tune[JB_MAX_TUNES];          // +72, pointers
    bool       fileOpen;                    // +8776 m_pFile != 0
    void*      file;
    char       path[JB_PATH_MAX];           // the bFile's name, at its +8
    uint32_t   header[JB_HEADER_SIZE / 4];  // +8784 m_FormHeader
    bool       sample;                      // +8816 m_pPlayingSample != 0
    uint32_t   statePlay;                   // +8820
    uint32_t   keepPlaying;                 // +8824
    uint32_t   curCatNum;                   // +8836
    uint32_t   curTuneNum;                  // +8840
    uint32_t   on;                          // +8844
    uint32_t   soundCategory;               // +8848 m_nCategory, bSound's
    float      volume;                      // +8852
    uint32_t   trigger;                     // +8856 m_bCallbackTriggerPlaySample
    uint32_t   pauseBeforePlay;             // +8860, never set
    uint32_t   lastCategory;                // +8864
    const JBHost* host;
} JBPlayer;

// What sound::jukebox reads from the rest of the game.
typedef struct {
    void* ctx;
    // gp-21420, the GameFlowState ServiceGameFlow writes; 3 is IN_FRONTEND.
    int      (*game_state)(void* ctx);
    // TheRaceParameters.nMaxCops (0x0031aaf4): the race is a pursuit.
    int      (*max_cops)(void* ctx);
    // gp-19616, the VBlank count PSX2VBlank keeps.
    uint32_t (*vblank)(void* ctx);
    // IsGameFlowPaused, 0x001680b8.
    int      (*paused)(void* ctx);
} JBWorld;

#define JB_STATE_IN_FRONTEND 3

// bSound's categories, as the jukebox and the audio options name them.
// SetSelection's list is the racing music's in a race, the menu's in the
// frontend.
#define JB_CAT_SFX           0
#define JB_CAT_TIRES         1
#define JB_CAT_ENGINE        2
#define JB_CAT_MENU_SFX      3
#define JB_CAT_RACING_MUSIC  4
#define JB_CAT_MENU_MUSIC    5
#define JB_CAT_SPEECH        6

// The sound module's share: sound::jukebox's statics, bSound's category
// volumes (+12, sixteen floats, 1.0 from the constructor), and the saved
// volumes jukebox::Start reads instead of bSound's.
typedef struct {
    JBPlayer    jukebox;
    int         soundEnabled;         // gp-23056
    int         musicEnabled;         // gp-23048
    int         firstMenuTune;        // gp-18928: the menu's first is list 5
    int         firstPursuitTune;     // gp-18924: a pursuit's, list 14
    int         firstRaceTune;        // gp-18920: a race's, list 7
    int         firstAdvance;         // gp-18916: the one random skip
    float       delayedStart;         // gp-19028
    int         muted;                // gp-19040, sound::Mute's
    float       savedVolume[5];       // 0x00313878: categories 0,1,2,5,4
    float       savedSpeechVolume;    // gp-19024, -1.0 too
    float       categoryVolume[16];   // bSound+12
    int32_t     trackKey;             // gp-18912, -1
    char        trackName[JB_NAME_MAX];     // 0x003138a8
    const char* track[16];                  // 0x00334208
    const JBWorld* world;
} JBSound;

// ------------------------------------------------------------ the player

// _GLOBAL_$I$Jukebox, 0x001b0130: the static constructor's values.
void jb_player_init(JBPlayer* p, const JBHost* host);

bool     jb_is_cartridge_loaded(const JBPlayer* p);
// LoadCartridge (0x0027dac8): the 32-byte header, then the index of
// header[4] bytes, one tJukeboxCategory record (64 bytes: tune count, then
// name) and that many 96-byte tunes for each of header[3] categories.
void     jb_load_cartridge(JBPlayer* p, const char* path, bool arg);
void     jb_close(JBPlayer* p);                           // 0x0027de40
void     jb_start(JBPlayer* p, uint32_t keep);            // Start(Ui)
void     jb_start_tune(JBPlayer* p, uint32_t cat, uint32_t tune,
                       uint32_t keep);                    // Start(UiUiUi)
void     jb_stop(JBPlayer* p);                            // 0x0027d868
void     jb_fade_out(JBPlayer* p, uint32_t ms);           // 0x0027d8f8
void     jb_fade_out_advance(JBPlayer* p, uint32_t ms);   // 0x0027d9a0
void     jb_advance(JBPlayer* p);                         // 0x0027da30
void     jb_update(JBPlayer* p);                          // 0x0027dff8
void     jb_set_on(JBPlayer* p, uint32_t on);             // 0x0027e170
void     jb_sample_callback(JBPlayer* p, uint32_t event); // 0x0027e1d8
void     jb_stop_playing(JBPlayer* p);                    // 0x0027e340
void     jb_pause(JBPlayer* p, uint32_t on);              // 0x0027e3e8
void     jb_start_fading(JBPlayer* p, uint32_t ms);       // 0x0027e490
void     jb_start_playing_tune(JBPlayer* p, uint32_t cat, uint32_t tune);
void     jb_start_playing(JBPlayer* p);                   // 0x0027e6c8
void     jb_set_volume(JBPlayer* p, float v);             // 0x0027e768
void     jb_set_tune_on(JBPlayer* p, uint32_t cat, uint32_t tune);
void     jb_set_tune_off(JBPlayer* p, uint32_t cat, uint32_t tune);
bool     jb_get_tune_on(JBPlayer* p, uint32_t cat, uint32_t tune);
void     jb_set_category_on(JBPlayer* p, uint32_t cat);
void     jb_set_category_off(JBPlayer* p, uint32_t cat);
bool     jb_pick_next_tune(JBPlayer* p, uint32_t* cat, uint32_t* tune);
bool     jb_is_done_playing(const JBPlayer* p);
bool     jb_is_done_fading(const JBPlayer* p);
bool     jb_is_fading(JBPlayer* p);                       // runs Update
bool     jb_is_playing(JBPlayer* p);                      // runs Update
void     jb_set_category(JBPlayer* p, uint32_t cat);      // 0x001b01e0

// cJukeboxCartridge's getters. The tune is the category's nth.
const char* jb_tune_name(JBPlayer* p, uint32_t cat, uint32_t tune);
uint32_t    jb_tune_offset(JBPlayer* p, uint32_t cat, uint32_t tune);
uint32_t    jb_tune_size(JBPlayer* p, uint32_t cat, uint32_t tune);
uint32_t    jb_tune_id(JBPlayer* p, uint32_t cat, uint32_t tune);
int32_t     jb_add_category(JBPlayer* p, const char* name);
int32_t     jb_add_tune(JBPlayer* p, const char* cat, const char* name,
                        uint32_t offset, uint32_t size, uint32_t sync,
                        uint32_t id);

// ------------------------------------------------------- sound::jukebox

void jb_sound_init(JBSound* s, const JBHost* host, const JBWorld* world);

// bSound::GetCategoryVolume / SetCategoryVolume: 16 categories, 1.0 past
// the end on a read, a write past it dropped.
float jb_get_category_volume(const JBSound* s, uint32_t cat);
void  jb_set_category_volume(JBSound* s, uint32_t cat, float v);
// 0x001ae028: a saved volume, by category; 0 for 3 and past 5.
float jb_saved_volume(const JBSound* s, uint32_t cat);
void  jb_save_volumes_for_speech(JBSound* s);             // 0x001af7e0
// 0x001afab8: categories 0 to 6 to the volumes the game ships with, then
// saved for speech. InitializeSoundDriver ends with it.
void  jb_default_category_volumes(JBSound* s);

// jukebox::Start (0x001aeab0). The bool is not read.
void jb_music_start(JBSound* s, const uint8_t* fredAudio, int arg);
void jb_music_stop(JBSound* s);                           // 0x001aec90
void jb_music_delayed_start(JBSound* s, float seconds);   // 0x001aec88
bool jb_music_is_playing(JBSound* s);                     // 0x001aecb0
// SetSelection (0x001af050): the bSound category, then every tune on the
// list turned on or off by its status and genre.
void jb_music_set_selection(JBSound* s, const uint8_t* fredAudio, int cat);

// ExtractJukeboxTrackStrings (0x001aed90) and the five that read it: the
// tune's name cut at each '-' into artist-name-label-genre-status, as
// "Hot Action Cop-Fever for the Flava--Rock-4". -1 is the current one.
// NULL when MusicEnabled is 0 -- or for a field the name has not got.
#define JB_TRACK_ARTIST 0     // GetTrackArtist, "Hot Action Cop"
#define JB_TRACK_NAME   1     // GetTrackName, "Fever for the Flava"
#define JB_TRACK_LABEL  2
#define JB_TRACK_GENRE  3
#define JB_TRACK_STATUS 4     // GetTrackStatus reads it as a number
const char* jb_track_string(JBSound* s, int cat, int tune, int field);
int         jb_track_status(JBSound* s, int cat, int tune);
uint32_t    jb_current_track(const JBSound* s);           // 0x001af040

// The music's share of sound::Update (0x001af4c0), past its 8 ms gate:
// Jukebox's Update, then -- in a race that is neither paused nor muted --
// DelayedStart's count, by dt (gp-19560, the frame's seconds).
void jb_music_update(JBSound* s, const uint8_t* fredAudio, float dt);

// ------------------------------------------- DataAudioOptionsScreen

// Fred's DataAudioOptionsScreen, as bytes (the port's Fred is the image the
// memory card saves):
#define JB_AO_MENU_MUSIC       0     // floats, bSound category 5
#define JB_AO_RACING_MUSIC     4     // 4
#define JB_AO_SFX              8     // 0
#define JB_AO_SFX_TIRES        12    // 1
#define JB_AO_SFX_ENGINE       16    // 2
#define JB_AO_SFX_MENU         20    // 3
#define JB_AO_SPEECH           24    // 6
#define JB_AO_TUNE_LIST        28    // 32 x AudioPlaylistOnOff
#define JB_AO_NUM_TUNES        156
#define JB_AO_SELECTED_SONG    160
#define JB_AO_FE_FAVOURITE     164
#define JB_AO_INGAME_FAVOURITE 168
#define JB_AO_AUDIO_MODE       172   // int16
#define JB_AO_CURR_GENRE       174
#define JB_AO_GENRE_MASK       175
#define JB_AO_SIZE             176
#define JB_AO_MAX_TUNES        32
// AudioPlaylistOnOff: CatNum, TuneNum, Status, Genre, all int8.

// SetAudioDataFromSound (0x001eef60): the seven volumes from bSound and,
// if `tunes`, the list rebuilt from the cartridge. audioMode is
// sound::GetAudioMode's answer.
void jb_audio_from_sound(JBSound* s, uint8_t* ao, int tunes, int audioMode);
// InitWithDefaults (0x001ef1c8), and GenreMgr::Populate (0x001ef240) in it.
void jb_audio_init_with_defaults(JBSound* s, uint8_t* ao, int audioMode);
// 0x001ef120, the options applied: the seven volumes into bSound, the saved
// ones, SetSelection(5). Returns the int16 SetAudioMode is handed last.
int  jb_audio_apply(JBSound* s, const uint8_t* ao);
