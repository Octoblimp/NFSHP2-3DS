// speechmgr -- speech::mgr_t (retail 0x00209ef0 .. 0x0020b868, and its
// constructor 0x0020b868), the nfsFsm it drives (0x0020c770, with fsm,
// state_t and transition, 0x0020bf00 .. 0x0020c750), the conditions and
// actions on its transitions (0x0020daa0 .. 0x0020f7c0), speechContext_t
// (0x0020f7f8 .. 0x0020fac8) and Speech::ConvertSpeed (0x00223528).
//
// The game's code raises a speech event (raise*): the event's details go
// into the next of four contexts, and the event and the context's number
// into a queue of two; a third is dropped. Each update, while no sentence
// plays, either takes the next event off the queue or, with the machine
// in the middle of an exchange, raises event 1 ("go on"); the machine's
// transition on it adds one sentence to the speech library
// (SPCH_AddEventV), which the wedge (sedwedge.h) plays. An exchange --
// the officer's call and dispatch's answer, say -- is two or three
// sentences, one per update once the last has played.
//
// Every action squelches the radio first (SpeechNoise::BeginSquelchNoise);
// the helicopter's four also start its noise. The radio's static is on
// while a sentence plays and off, with the helicopter's, once none does.
//
// The cop ids: AllocateVoices shuffles four voices ({2, 4, 8, 32}) over
// the four speakers, and six "from" ids ({1, 2, 4, 8, 16, 32}), the
// first four of which are both the speakers' from and to ids.
//
// Not ported:
//   - maybeSayDebugPhrase (0x0020a1f0), a tweaker's debug event (168);
//     the tweaker's flag (gp-16420) is never set in a retail build.
//   - fsm::stop and the destructor (the manager is static), isSpeaking
//     (0x0020bdd8, no callers; previousSedPlaybackState is read directly,
//     as retail's sound and cop manager do), test (empty) and fsm's other
//     accessors.
//   - randomCondition_t (no transition uses it), and the four actions no
//     transition uses: beginPursuitReckless, crashAmbulance,
//     dispatchAmbulanceConfirm and dispatchBeginPursuitReckless.
//   - The raise functions nothing calls: BeginPursuitReckless,
//     BeginPursuitRacing, ChatterGeneral, ChatterTraffic, CrashAmbulance,
//     PursuitUpdateSpeed, PursuitUpdateVehicleIdSpecific, SuspectLost,
//     Airborne, Direction, SuspectCrash, SuspectCrashAmbulance and
//     SuspectCrashTow. The machine still answers their events, which
//     nothing raises.
//
// docs/formats/speechmgr.md has the rest; tools/speechmgr_check.py runs
// retail's code against this.

#ifndef SPEECHMGR_H
#define SPEECHMGR_H

#include <stddef.h>
#include <stdint.h>

#define SPEECHMGR_QUEUE     2
#define SPEECHMGR_CONTEXTS  4

// speechContext_t, 56 bytes: what an event says. The ids are 0 to 3, the
// speakers; the rest are the speech library's bit values (location_t,
// racerVehicleColor_t and so on; docs/formats/speechmgr.md).
typedef struct SpeechContext {
    uint32_t copUnitId;                         //  0 the speaker
    uint32_t copTargetUnitId;                   //  4 whom it speaks to
    int32_t  copUnitLocation;                   //  8 location_t
    int32_t  arrestType;                        // 12 1 formal, 2 informal
    int32_t  arrestLevel;                       // 16
    int32_t  isSupervisorActive;                // 20
    int32_t  racerVehicleApproximateDescription;    // 24
    int32_t  racerVehicleExactDescription;      // 28
    int32_t  racerVehicleColor;                 // 32
    int32_t  racerVehicleSpeed;                 // 36 ConvertSpeed's
    int32_t  raceType;                          // 40
    int32_t  direction;                         // 44
    int32_t  roadBlockLocation;                 // 48 location_t
    int32_t  boolParam;                         // 52
} SpeechContext;

typedef struct SpeechQueueEntry {
    int32_t event;
    int32_t contextNum;
} SpeechQueueEntry;

// speech::mgr_t, 1464 bytes on the PS2. Retail's nfsFsm (0 .. 1192) is
// the state's number here; its states, conditions and actions are
// speechmgr.c's tables.
typedef struct SpeechMgr {
    int32_t          state;                     // SPEECH_STATE_*, the fsm's current
    SpeechQueueEntry queue[SPEECHMGR_QUEUE];    // 1192 speechQueue
    int32_t          read;                      // 1208
    int32_t          write;                     // 1212
    int32_t          full;                      // 1216
    int32_t          nextContext;               // 1220
    int32_t          currContext;               // 1224, unset until the first event
    SpeechContext    contexts[SPEECHMGR_CONTEXTS];  // 1228
    int32_t          previousSedPlaybackState;  // 1452 a sentence was playing, or due
} SpeechMgr;

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char speechmgr_layout_check[
    (sizeof(SpeechContext) == 56
     && offsetof(SpeechContext, roadBlockLocation) == 48
     && offsetof(SpeechMgr, contexts) - offsetof(SpeechMgr, queue)
        == 1228 - 1192) ? 1 : -1];
#endif

// nfsFsm's states, in their order in the machine (retail's offset 16 +
// 32 * n). 3, 17 and 24 have no transitions and no way in.
enum {
    SPEECH_STATE_READY = 0,
    SPEECH_STATE_DISPATCH_CONFIRM,
    SPEECH_STATE_DISPATCH_OR_SUPER_CONFIRM,
    SPEECH_STATE_DISPATCH_BEGIN_PURSUIT_RECKLESS,
    SPEECH_STATE_DISPATCH_BEGIN_PURSUIT_COP_HIT_RUN,
    SPEECH_STATE_DISPATCH_BEGIN_PURSUIT_ID_SPECIFIC,
    SPEECH_STATE_DISPATCH_ROAD_BLOCK_UPDATE,
    SPEECH_STATE_DISPATCH_REQUEST_REPEAT,
    SPEECH_STATE_DISPATCH_SPIKE_STRIP_SET,
    SPEECH_STATE_REPEAT_BEGIN_PURSUIT_ID_SPECIFIC,
    SPEECH_STATE_BEGIN_PURSUIT_HIT_RUN_TRAFFIC2,
    SPEECH_STATE_BEGIN_PURSUIT_SPEED2,
    SPEECH_STATE_ROADBLOCK_REQUEST2,
    SPEECH_STATE_SPIKE_STRIP_REQUEST2,
    SPEECH_STATE_CRASH_BACKUP,
    SPEECH_STATE_UPDATE_RECKLESS2,
    SPEECH_STATE_INITIATE_RESPOND,
    SPEECH_STATE_SECONDARY_RESPOND,
    SPEECH_STATE_BEGIN_PURSUIT_RACING,
    SPEECH_STATE_ROTOR_REQUEST2,
    SPEECH_STATE_BREAKING_PURSUIT,
    SPEECH_STATE_TACTIC_HIT_RESPONSE,
    SPEECH_STATE_COP_BREAKING_PURSUIT,
    SPEECH_STATE_STAND_BY_FOR_SUPER,
    SPEECH_STATE_REQUEST_ANOTHER_ROAD_BLOCK,
    SPEECH_STATE_COUNT
};

// The arrest types (arrestType_t).
enum {
    SPEECH_ARREST_FORMAL   = 1,
    SPEECH_ARREST_INFORMAL = 2,
};

// ---- speech::mgr_t

// 0x00209ef0. The one manager, constructed on the first call.
SpeechMgr *speechmgr_get_instance(void);
// 0x0020b868. An empty queue, the first context next, and the machine
// ready; the contexts and currContext are left as they are.
void speechmgr_construct(SpeechMgr *m);

// 0x00209ff8. Nothing during a replay (the race coordinator's states 4,
// 5 and 7, or its replay demo). With the wedge playing a sentence, the
// radio's static on; otherwise the static and the helicopter's noise
// off, and then event 1 in the middle of an exchange, or the queue's
// next event. previousSedPlaybackState: 0 only when nothing was done.
void speechmgr_update(SpeechMgr *m);
// 0x0020a230. The machine ready, the queue emptied (read stays), the
// noises off and the wedge's queue cleared.
void speechmgr_flush_queue(SpeechMgr *m);
// 0x0020a288, tCopManager's constructor: ShuffleCopIds (0x0020f888).
void speechmgr_allocate_voices(SpeechMgr *m);
void speechmgr_fade(SpeechMgr *m, float level);     // 0x0020a290, the wedge's
void speechmgr_mute(SpeechMgr *m, int32_t on);      // 0x0020a2b0, the wedge's
// 0x0020a2e8. `event` with the next context, unless the queue is full
// or a replay runs; the context moves on either way, unless full.
void speechmgr_push_speech_event(SpeechMgr *m, int32_t event);
// 0x0020a2d0. The context the next event fills.
SpeechContext *speechmgr_get_next_context(SpeechMgr *m);

// The raise functions (0x0020a3e0 ..), each the event's details into the
// next context, written even when the event is then dropped, and the
// event pushed. `speaker` and `target` are cop ids, 0 to 3; `b` is a
// bool, kept as the word it is handed. The event's number follows each.
void speechmgr_raise_pursuit_cop_hit(SpeechMgr *m, uint32_t speaker,
                                     int32_t location);             // 2
void speechmgr_raise_begin_pursuit_cop_hit_run(SpeechMgr *m,
                                               uint32_t speaker,
                                               int32_t location);   // 3
void speechmgr_raise_begin_pursuit_general(SpeechMgr *m, uint32_t speaker);  // 5
void speechmgr_raise_begin_pursuit_erratic(SpeechMgr *m, uint32_t speaker);  // 4
void speechmgr_raise_begin_pursuit_no_id(SpeechMgr *m, uint32_t speaker);    // 10
void speechmgr_raise_begin_pursuit_hit_run_traffic(SpeechMgr *m,
                                                   uint32_t speaker,
                                                   int32_t location);   // 6
void speechmgr_raise_begin_pursuit_id_general(SpeechMgr *m, uint32_t speaker,
                                              int32_t approx,
                                              int32_t color);       // 7
void speechmgr_raise_begin_pursuit_id_specific(SpeechMgr *m,
                                               uint32_t speaker, int32_t b,
                                               int32_t exact,
                                               int32_t color);      // 8
void speechmgr_raise_begin_pursuit_again(SpeechMgr *m, uint32_t speaker,
                                         int32_t exact, int32_t color); // 14
void speechmgr_raise_begin_pursuit_id_repeated(SpeechMgr *m,
                                               uint32_t speaker, int32_t b,
                                               int32_t exact,
                                               int32_t color);      // 9
// The speed in ConvertSpeed's bits.
void speechmgr_raise_begin_pursuit_speed(SpeechMgr *m, uint32_t speaker,
                                         float speed);              // 13
void speechmgr_raise_backup_request(SpeechMgr *m, uint32_t speaker);  // 15
void speechmgr_raise_backup_confirm(SpeechMgr *m, uint32_t speaker,
                                    uint32_t target);               // 17
void speechmgr_raise_backup_request_location(SpeechMgr *m, uint32_t speaker,
                                             int32_t location);     // 16
void speechmgr_raise_crash(SpeechMgr *m, uint32_t speaker,
                           uint32_t target);                        // 39
void speechmgr_raise_flat_tire(SpeechMgr *m, uint32_t speaker,
                               uint32_t target);                    // 40
void speechmgr_raise_crash_tow(SpeechMgr *m, uint32_t speaker,
                               uint32_t target);                    // 38
void speechmgr_raise_cop_pursuit_avoidance(SpeechMgr *m, uint32_t speaker);  // 20
void speechmgr_raise_pursuit_update_subject_location(SpeechMgr *m,
                                                     uint32_t speaker,
                                                     int32_t location,
                                                     int32_t b);    // 22
// Retail's declaration is (speaker, b), and its callers hand the
// location in the next register, which it keeps.
void speechmgr_raise_suspect_found(SpeechMgr *m, uint32_t speaker, int32_t b,
                                   int32_t location);               // 25
void speechmgr_raise_tactic_hit(SpeechMgr *m, uint32_t speaker,
                                uint32_t target);                   // 27
void speechmgr_raise_tactic_divert(SpeechMgr *m, uint32_t speaker);  // 29
void speechmgr_raise_tactic_cutoff(SpeechMgr *m, uint32_t speaker);  // 30
// `b` is not kept.
void speechmgr_raise_update_reckless(SpeechMgr *m, uint32_t speaker,
                                     int32_t b);                    // 31
void speechmgr_raise_racer_caught(SpeechMgr *m, uint32_t speaker,
                                  int32_t level, int32_t arrest);   // 32
void speechmgr_raise_super_back_off(SpeechMgr *m);                  // 33
void speechmgr_raise_cop_back_off(SpeechMgr *m, uint32_t speaker,
                                  int32_t b);                       // 34
void speechmgr_raise_car_stopped(SpeechMgr *m, uint32_t speaker,
                                 int32_t exact);                    // 36
// The arrest formal.
void speechmgr_raise_radio_arrest(SpeechMgr *m, uint32_t speaker);  // 35
void speechmgr_raise_rotor_request(SpeechMgr *m, uint32_t speaker,
                                   int32_t b);                      // 41
void speechmgr_raise_rotor_confirm(SpeechMgr *m);                   // 42
void speechmgr_raise_rotor_location(SpeechMgr *m, int32_t location);  // 43
void speechmgr_raise_rotor_chatter(SpeechMgr *m, int32_t b);        // 44
void speechmgr_raise_rotor_spike_failed(SpeechMgr *m, uint32_t speaker,
                                        int32_t b);                 // 46
void speechmgr_raise_rotor_traffic(SpeechMgr *m);                   // 45
// The failures' `target` is the context's target, `speaker` its speaker.
void speechmgr_raise_road_block_failure_avoid(SpeechMgr *m, uint32_t target,
                                              int32_t b,
                                              uint32_t speaker);    // 47
void speechmgr_raise_road_block_failure_through(SpeechMgr *m,
                                                uint32_t target, int32_t b,
                                                uint32_t speaker);  // 48
void speechmgr_raise_roadblock_request(SpeechMgr *m, uint32_t speaker,
                                       int32_t b);                  // 49
void speechmgr_raise_request_another_roadblock(SpeechMgr *m,
                                               uint32_t speaker,
                                               int32_t b);          // 52
void speechmgr_raise_road_block_set(SpeechMgr *m, uint32_t speaker,
                                    int32_t b, int32_t location);   // 50
void speechmgr_raise_road_block_setting(SpeechMgr *m, uint32_t speaker,
                                        int32_t b);                 // 51
void speechmgr_raise_spike_strip_failure(SpeechMgr *m, uint32_t target,
                                         int32_t b,
                                         uint32_t speaker);         // 53
void speechmgr_raise_spike_strip_request(SpeechMgr *m, uint32_t speaker,
                                         int32_t b);                // 54
void speechmgr_raise_spike_strip_set(SpeechMgr *m, uint32_t speaker,
                                     int32_t location, int32_t b);  // 55
void speechmgr_raise_spike_strip_set_left(SpeechMgr *m, uint32_t speaker,
                                          int32_t location,
                                          int32_t b);               // 56
void speechmgr_raise_spike_strip_set_right(SpeechMgr *m, uint32_t speaker,
                                           int32_t location,
                                           int32_t b);              // 57
void speechmgr_raise_spike_strip_tire_blow(SpeechMgr *m, uint32_t speaker,
                                           int32_t b);              // 58
void speechmgr_raise_super_request(SpeechMgr *m, uint32_t speaker);  // 59
// The speaker as its own target.
void speechmgr_raise_super_initiate(SpeechMgr *m, uint32_t speaker,
                                    float speed, int32_t location,
                                    int32_t exact, int32_t color);  // 60
void speechmgr_raise_current_speed(SpeechMgr *m, uint32_t speaker,
                                   float speed);                    // 62
void speechmgr_raise_suspect_crash_traffic(SpeechMgr *m, uint32_t speaker,
                                           int32_t b);              // 67
void speechmgr_raise_dispatch_be_on_lookout(SpeechMgr *m,
                                            int32_t location);      // 68
void speechmgr_raise_dispatch_road_block_na(SpeechMgr *m,
                                            uint32_t speaker);      // 69
void speechmgr_raise_dispatch_helicopter_na(SpeechMgr *m,
                                            uint32_t speaker);      // 70

// ---- speechContext_t

// 0x0020f888. The voices and the from and to ids shuffled (bRandom).
void     speechcontext_shuffle_cop_ids(void);
// The ids by speaker, 0 past the four.
uint32_t speechcontext_get_cop_id(const SpeechContext *c);          // 0x0020f970
uint32_t speechcontext_get_target_cop_id(const SpeechContext *c);   // 0x0020f9a0
uint32_t speechcontext_get_from_cop_id(const SpeechContext *c);     // 0x0020f9d0
uint32_t speechcontext_get_target_from_cop_id(const SpeechContext *c);  // 0x0020fa00
uint32_t speechcontext_get_to_id(const SpeechContext *c);           // 0x0020fa30
uint32_t speechcontext_get_target_to_id(const SpeechContext *c);    // 0x0020fa60
// The tables themselves (copIdTable, fromIdTable, toIdTable), 4 each.
const uint32_t *speechcontext_id_table(int32_t which);

// ---- Speech

// 0x00223528. A speed as racerVehicleSpeed_t: 0 under 100, 4096 (340+)
// over 340, else 1 << (speed - 100) / 20.
int32_t speech_convert_speed(float speed);

#endif
