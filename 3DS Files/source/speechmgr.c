#include "speechmgr.h"

#include "bmath.h"
#include "race.h"
#include "sedwedge.h"
#include "spch.h"
#include "speechnoise.h"

static SpeechMgr gInstance;                 // 0x00334418
static int32_t   gConstructed;              // gp-16416

static uint32_t gCopIdTable[4];             // 0x0031bc70, the voices
static uint32_t gFromIdTable[4];            // 0x0031bc60
static uint32_t gToIdTable[4];              // 0x0031bc50

// ------------------------------------------------------------ the machine

// The conditions on the transitions (condition_t's, 0x0020f720 ..).
enum {
    C_NULL,                 // nullCondition_t: always
    C_SUP_ACTIVE,           // isSupervisorActiveCondition_t
    C_SUP_NOT_ACTIVE,       // isSupervisorNotActiveCondition_t
    C_COP_LOCATION_SET,     // isCopLocationSetCondition_t
    C_COP_TARGET_ID_SET,    // isCopTargetIdSetCondition_t
};

// The actions, in nfsFsm's order (retail's offsets 840 ..), less the four
// no transition uses.
enum {
    A_NULL,
    A_AIRBORNE,
    A_BACKUP_CONFIRM,
    A_BACKUP_REQUEST,
    A_BACKUP_REQUEST_LOCATION,
    A_BEGIN_PURSUIT_COP_HIT_RUN,
    A_BEGIN_PURSUIT_GENERAL,
    A_BEGIN_PURSUIT_NO_ID,
    A_BEGIN_PURSUIT_HIT_RUN_TRAFFIC,
    A_BEGIN_PURSUIT_ID_GENERAL,
    A_BEGIN_PURSUIT_ID_SPECIFIC,
    A_BEGIN_PURSUIT_AGAIN,
    A_BEGIN_PURSUIT_RACING,
    A_BEGIN_PURSUIT_SPEED,
    A_BEGIN_PURSUIT_ERRATIC,
    A_BREAK_PURSUIT,
    A_CAR_STOPPED,
    A_CHATTER_TRAFFIC,
    A_CHATTER_GENERAL,
    A_COP_BACK_OFF,
    A_COP_PURSUIT_AVOIDANCE,
    A_CRASH,
    A_CRASH_TOW,
    A_CRASH_BACKUP,
    A_CURRENT_SPEED,
    A_DIRECTION,
    A_DISPATCH_BEGIN_PURSUIT_RACING,
    A_DISPATCH_BEGIN_PURSUIT_HIT_RUN_COP,
    A_DISPATCH_BEGIN_PURSUIT_HIT_RUN_TRAFFIC,
    A_DISPATCH_BEGIN_VEHICLE_ID_SPECIFIC,
    A_DISPATCH_ROAD_BLOCK_UPDATE,
    A_DISPATCH_SPIKE_STRIP_SET,
    A_DISPATCH_BEGIN_PURSUIT_SPEED,
    A_DISPATCH_CONFIRM,
    A_DISPATCH_ROTOR_DEPLOYED,
    A_DISPATCH_TERMINATE,
    A_DISPATCH_TOW_CONFIRM,
    A_DISPATCH_ID_REQUEST,
    A_FLAT_TIRE,
    A_PURSUIT_COP_HIT,
    A_PURSUIT_UPDATE_SPEED,
    A_PURSUIT_UPDATE_SUBJECT_LOCATION,
    A_PURSUIT_UPDATE_VEHICLE_ID_SPECIFIC,
    A_RACER_CAUGHT,
    A_RADIO_ARREST,
    A_REQUEST_ANOTHER_ROAD_BLOCK,
    A_ROAD_BLOCK_FAILURE_AVOID,
    A_ROAD_BLOCK_FAILURE_THROUGH,
    A_ROADBLOCK_REQUEST,
    A_ROAD_BLOCK_SET,
    A_ROAD_BLOCK_SETTING,
    A_ROTOR_REQUEST,
    A_ROTOR_LOCATION,
    A_ROTOR_CHATTER,
    A_ROTOR_TRAFFIC,
    A_ROTOR_SPIKE_FAILED,
    A_SPIKE_STRIP_FAILURE,
    A_SPIKE_STRIP_TIRE_BLOW,
    A_SPIKE_STRIP_REQUEST,
    A_SPIKE_STRIP_SET_LEFT,
    A_SPIKE_STRIP_SET_RIGHT,
    A_SPIKE_STRIP_SET,
    A_STAND_BY_FOR_SUPER,
    A_SUPER_BACK_OFF,
    A_SUPER_REQUEST,
    A_SUPER_TERMINATE,
    A_SUPERVISOR_CONFIRM,
    A_SUPERVISOR_INITIATES,
    A_SUPERVISOR_ROAD_BLOCK_OK,
    A_SUPERVISOR_ROTOR_OK,
    A_SUPERVISOR_SPIKE_STRIP_OK,
    A_SUSPECT_CRASH,
    A_SUSPECT_CRASH_TRAFFIC,
    A_SUSPECT_FOUND,
    A_SUSPECT_LOST,
    A_TACTIC_HIT_FORMAL,
    A_TACTIC_HIT_INFORMAL,
    A_TACTIC_DIVERT,
    A_TACTIC_CUTOFF,
    A_UPDATE_RECKLESS,
    A_DISPATCH_BE_ON_LOOKOUT,
    A_DISPATCH_ROAD_BLOCK_NA,
    A_DISPATCH_HELICOPTER_NA,
};

// A transition: on `event`, with `cond` true, `action`, then `dest`.
typedef struct SpeechTransition {
    uint8_t event;
    uint8_t dest;
    uint8_t cond;
    uint8_t action;
} SpeechTransition;

#define S(name) SPEECH_STATE_##name

// Each state's transitions in the order nfsFsm's constructor (0x0020c770)
// adds them; the first that matches is taken.
static const SpeechTransition kReady[] = {
    { 32, S(READY), C_NULL, A_RACER_CAUGHT },
    { 61, S(READY), C_NULL, A_AIRBORNE },
    { 16, S(READY), C_NULL, A_BACKUP_REQUEST_LOCATION },
    {  4, S(DISPATCH_CONFIRM), C_NULL, A_BEGIN_PURSUIT_ERRATIC },
    { 10, S(DISPATCH_CONFIRM), C_NULL, A_BEGIN_PURSUIT_NO_ID },
    { 19, S(READY), C_NULL, A_CHATTER_TRAFFIC },
    { 18, S(READY), C_NULL, A_CHATTER_GENERAL },
    { 20, S(DISPATCH_CONFIRM), C_NULL, A_COP_PURSUIT_AVOIDANCE },
    { 39, S(CRASH_BACKUP), C_NULL, A_CRASH },
    { 40, S(CRASH_BACKUP), C_NULL, A_FLAT_TIRE },
    { 35, S(DISPATCH_CONFIRM), C_NULL, A_RADIO_ARREST },
    { 36, S(DISPATCH_CONFIRM), C_NULL, A_CAR_STOPPED },
    { 47, S(READY), C_NULL, A_ROAD_BLOCK_FAILURE_AVOID },
    { 48, S(READY), C_NULL, A_ROAD_BLOCK_FAILURE_THROUGH },
    { 52, S(DISPATCH_OR_SUPER_CONFIRM), C_NULL, A_REQUEST_ANOTHER_ROAD_BLOCK },
    { 50, S(DISPATCH_ROAD_BLOCK_UPDATE), C_NULL, A_ROAD_BLOCK_SET },
    { 51, S(DISPATCH_ROAD_BLOCK_UPDATE), C_NULL, A_ROAD_BLOCK_SETTING },
    { 53, S(READY), C_NULL, A_SPIKE_STRIP_FAILURE },
    { 46, S(READY), C_NULL, A_ROTOR_SPIKE_FAILED },
    { 58, S(READY), C_NULL, A_SPIKE_STRIP_TIRE_BLOW },
    { 56, S(DISPATCH_SPIKE_STRIP_SET), C_NULL, A_SPIKE_STRIP_SET_LEFT },
    { 57, S(DISPATCH_SPIKE_STRIP_SET), C_NULL, A_SPIKE_STRIP_SET_RIGHT },
    { 55, S(DISPATCH_SPIKE_STRIP_SET), C_NULL, A_SPIKE_STRIP_SET },
    { 64, S(READY), C_NULL, A_SUSPECT_CRASH },
    { 67, S(READY), C_NULL, A_SUSPECT_CRASH_TRAFFIC },
    { 27, S(TACTIC_HIT_RESPONSE), C_NULL, A_TACTIC_HIT_FORMAL },
    { 29, S(READY), C_NULL, A_TACTIC_DIVERT },
    { 30, S(READY), C_NULL, A_TACTIC_CUTOFF },
    {  6, S(BEGIN_PURSUIT_HIT_RUN_TRAFFIC2), C_NULL, A_BEGIN_PURSUIT_HIT_RUN_TRAFFIC },
    { 13, S(BEGIN_PURSUIT_SPEED2), C_NULL, A_BEGIN_PURSUIT_SPEED },
    {  5, S(DISPATCH_CONFIRM), C_NULL, A_BEGIN_PURSUIT_GENERAL },
    {  2, S(DISPATCH_CONFIRM), C_NULL, A_PURSUIT_COP_HIT },
    { 49, S(ROADBLOCK_REQUEST2), C_NULL, A_ROADBLOCK_REQUEST },
    { 54, S(SPIKE_STRIP_REQUEST2), C_NULL, A_SPIKE_STRIP_REQUEST },
    { 15, S(READY), C_NULL, A_BACKUP_REQUEST },
    { 17, S(READY), C_NULL, A_BACKUP_CONFIRM },
    { 33, S(BREAKING_PURSUIT), C_NULL, A_SUPER_BACK_OFF },
    { 34, S(COP_BREAKING_PURSUIT), C_NULL, A_COP_BACK_OFF },
    { 38, S(CRASH_BACKUP), C_NULL, A_CRASH_TOW },
    { 62, S(DISPATCH_CONFIRM), C_NULL, A_CURRENT_SPEED },
    { 63, S(DISPATCH_CONFIRM), C_NULL, A_DIRECTION },
    { 31, S(UPDATE_RECKLESS2), C_NULL, A_UPDATE_RECKLESS },
    { 41, S(ROTOR_REQUEST2), C_NULL, A_ROTOR_REQUEST },
    { 42, S(READY), C_NULL, A_DISPATCH_ROTOR_DEPLOYED },
    { 45, S(READY), C_NULL, A_ROTOR_TRAFFIC },
    { 44, S(READY), C_NULL, A_ROTOR_CHATTER },
    { 43, S(READY), C_NULL, A_ROTOR_LOCATION },
    { 59, S(STAND_BY_FOR_SUPER), C_NULL, A_SUPER_REQUEST },
    { 60, S(INITIATE_RESPOND), C_NULL, A_SUPERVISOR_INITIATES },
    {  3, S(DISPATCH_BEGIN_PURSUIT_COP_HIT_RUN), C_NULL, A_BEGIN_PURSUIT_COP_HIT_RUN },
    {  7, S(DISPATCH_CONFIRM), C_NULL, A_BEGIN_PURSUIT_ID_GENERAL },
    {  8, S(DISPATCH_BEGIN_PURSUIT_ID_SPECIFIC), C_NULL, A_BEGIN_PURSUIT_ID_SPECIFIC },
    { 14, S(DISPATCH_BEGIN_PURSUIT_ID_SPECIFIC), C_NULL, A_BEGIN_PURSUIT_AGAIN },
    {  9, S(DISPATCH_REQUEST_REPEAT), C_NULL, A_BEGIN_PURSUIT_ID_SPECIFIC },
    { 11, S(BEGIN_PURSUIT_RACING), C_NULL, A_BEGIN_PURSUIT_RACING },
    { 21, S(DISPATCH_OR_SUPER_CONFIRM), C_NULL, A_PURSUIT_UPDATE_SPEED },
    { 22, S(DISPATCH_OR_SUPER_CONFIRM), C_NULL, A_PURSUIT_UPDATE_SUBJECT_LOCATION },
    { 24, S(DISPATCH_OR_SUPER_CONFIRM), C_NULL, A_PURSUIT_UPDATE_VEHICLE_ID_SPECIFIC },
    { 25, S(DISPATCH_OR_SUPER_CONFIRM), C_NULL, A_SUSPECT_FOUND },
    { 26, S(DISPATCH_OR_SUPER_CONFIRM), C_NULL, A_SUSPECT_LOST },
    { 68, S(READY), C_NULL, A_DISPATCH_BE_ON_LOOKOUT },
    { 69, S(READY), C_NULL, A_DISPATCH_ROAD_BLOCK_NA },
    { 70, S(READY), C_NULL, A_DISPATCH_HELICOPTER_NA },
};
static const SpeechTransition kDispatchConfirm[] = {
    {  1, S(READY), C_NULL, A_DISPATCH_CONFIRM },
};
static const SpeechTransition kDispatchOrSuperConfirm[] = {
    {  1, S(READY), C_SUP_ACTIVE, A_SUPERVISOR_CONFIRM },
    {  1, S(READY), C_SUP_NOT_ACTIVE, A_DISPATCH_CONFIRM },
};
static const SpeechTransition kDispatchBeginPursuitCopHitRun[] = {
    {  1, S(READY), C_NULL, A_DISPATCH_BEGIN_PURSUIT_HIT_RUN_COP },
};
static const SpeechTransition kDispatchBeginPursuitIdSpecific[] = {
    {  1, S(READY), C_NULL, A_DISPATCH_BEGIN_VEHICLE_ID_SPECIFIC },
};
static const SpeechTransition kDispatchRoadBlockUpdate[] = {
    {  1, S(READY), C_NULL, A_DISPATCH_ROAD_BLOCK_UPDATE },
};
static const SpeechTransition kDispatchRequestRepeat[] = {
    {  1, S(REPEAT_BEGIN_PURSUIT_ID_SPECIFIC), C_NULL, A_DISPATCH_ID_REQUEST },
};
static const SpeechTransition kDispatchSpikeStripSet[] = {
    {  1, S(READY), C_NULL, A_DISPATCH_SPIKE_STRIP_SET },
};
static const SpeechTransition kRepeatBeginPursuitIdSpecific[] = {
    {  1, S(DISPATCH_BEGIN_PURSUIT_ID_SPECIFIC), C_NULL, A_BEGIN_PURSUIT_ID_SPECIFIC },
};
static const SpeechTransition kBeginPursuitHitRunTraffic2[] = {
    {  1, S(READY), C_NULL, A_DISPATCH_BEGIN_PURSUIT_HIT_RUN_TRAFFIC },
};
static const SpeechTransition kBeginPursuitSpeed2[] = {
    {  1, S(READY), C_NULL, A_DISPATCH_BEGIN_PURSUIT_SPEED },
};
static const SpeechTransition kRoadblockRequest2[] = {
    {  1, S(READY), C_SUP_ACTIVE, A_SUPERVISOR_ROAD_BLOCK_OK },
    {  1, S(READY), C_SUP_NOT_ACTIVE, A_DISPATCH_CONFIRM },
};
static const SpeechTransition kSpikeStripRequest2[] = {
    {  1, S(READY), C_SUP_ACTIVE, A_SUPERVISOR_SPIKE_STRIP_OK },
    {  1, S(READY), C_SUP_NOT_ACTIVE, A_DISPATCH_CONFIRM },
};
static const SpeechTransition kCrashBackup[] = {
    {  1, S(READY), C_COP_TARGET_ID_SET, A_CRASH_BACKUP },
    {  1, S(READY), C_NULL, A_DISPATCH_TOW_CONFIRM },
};
static const SpeechTransition kUpdateReckless2[] = {
    {  1, S(READY), C_SUP_NOT_ACTIVE, A_DISPATCH_CONFIRM },
    {  1, S(READY), C_NULL, A_NULL },
};
static const SpeechTransition kInitiateRespond[] = {
    {  1, S(READY), C_COP_LOCATION_SET, A_PURSUIT_UPDATE_SUBJECT_LOCATION },
    {  1, S(READY), C_NULL, A_PURSUIT_UPDATE_VEHICLE_ID_SPECIFIC },
};
static const SpeechTransition kBeginPursuitRacing[] = {
    {  1, S(READY), C_NULL, A_DISPATCH_BEGIN_PURSUIT_RACING },
};
static const SpeechTransition kRotorRequest2[] = {
    {  1, S(READY), C_SUP_NOT_ACTIVE, A_DISPATCH_CONFIRM },
    {  1, S(READY), C_SUP_ACTIVE, A_SUPERVISOR_ROTOR_OK },
};
static const SpeechTransition kBreakingPursuit[] = {
    {  1, S(READY), C_NULL, A_BREAK_PURSUIT },
};
static const SpeechTransition kTacticHitResponse[] = {
    {  1, S(READY), C_NULL, A_TACTIC_HIT_INFORMAL },
};
static const SpeechTransition kCopBreakingPursuit[] = {
    {  1, S(READY), C_SUP_ACTIVE, A_SUPER_TERMINATE },
    {  1, S(READY), C_SUP_NOT_ACTIVE, A_DISPATCH_TERMINATE },
};
static const SpeechTransition kStandByForSuper[] = {
    {  1, S(READY), C_NULL, A_STAND_BY_FOR_SUPER },
};

#define T(tab) { tab, (int32_t)(sizeof(tab) / sizeof((tab)[0])) }

static const struct {
    const SpeechTransition *t;
    int32_t                 n;
} kStates[SPEECH_STATE_COUNT] = {
    [S(READY)]                          = T(kReady),
    [S(DISPATCH_CONFIRM)]               = T(kDispatchConfirm),
    [S(DISPATCH_OR_SUPER_CONFIRM)]      = T(kDispatchOrSuperConfirm),
    [S(DISPATCH_BEGIN_PURSUIT_COP_HIT_RUN)] = T(kDispatchBeginPursuitCopHitRun),
    [S(DISPATCH_BEGIN_PURSUIT_ID_SPECIFIC)] = T(kDispatchBeginPursuitIdSpecific),
    [S(DISPATCH_ROAD_BLOCK_UPDATE)]     = T(kDispatchRoadBlockUpdate),
    [S(DISPATCH_REQUEST_REPEAT)]        = T(kDispatchRequestRepeat),
    [S(DISPATCH_SPIKE_STRIP_SET)]       = T(kDispatchSpikeStripSet),
    [S(REPEAT_BEGIN_PURSUIT_ID_SPECIFIC)] = T(kRepeatBeginPursuitIdSpecific),
    [S(BEGIN_PURSUIT_HIT_RUN_TRAFFIC2)] = T(kBeginPursuitHitRunTraffic2),
    [S(BEGIN_PURSUIT_SPEED2)]           = T(kBeginPursuitSpeed2),
    [S(ROADBLOCK_REQUEST2)]             = T(kRoadblockRequest2),
    [S(SPIKE_STRIP_REQUEST2)]           = T(kSpikeStripRequest2),
    [S(CRASH_BACKUP)]                   = T(kCrashBackup),
    [S(UPDATE_RECKLESS2)]               = T(kUpdateReckless2),
    [S(INITIATE_RESPOND)]               = T(kInitiateRespond),
    [S(BEGIN_PURSUIT_RACING)]           = T(kBeginPursuitRacing),
    [S(ROTOR_REQUEST2)]                 = T(kRotorRequest2),
    [S(BREAKING_PURSUIT)]               = T(kBreakingPursuit),
    [S(TACTIC_HIT_RESPONSE)]            = T(kTacticHitResponse),
    [S(COP_BREAKING_PURSUIT)]           = T(kCopBreakingPursuit),
    [S(STAND_BY_FOR_SUPER)]             = T(kStandByForSuper),
};

static int32_t condition_is_true(int32_t cond, const SpeechContext *c)
{
    switch (cond) {
    case C_SUP_ACTIVE:
        return c->isSupervisorActive;
    case C_SUP_NOT_ACTIVE:
        return c->isSupervisorActive ^ 1;
    case C_COP_LOCATION_SET:
        return c->copUnitLocation != 0;
    case C_COP_TARGET_ID_SET:
        return speechcontext_get_target_to_id(c) != 0;
    default:
        return 1;
    }
}

// The getters the actions hand the library.
#define COP     speechcontext_get_cop_id(c)
#define TCOP    speechcontext_get_target_cop_id(c)
#define FROM    speechcontext_get_from_cop_id(c)
#define TFROM   speechcontext_get_target_from_cop_id(c)
#define TO      speechcontext_get_to_id(c)
#define TTO     speechcontext_get_target_to_id(c)
#define SUP     (c->isSupervisorActive != 0)
#define LOC     c->copUnitLocation
#define RBL     c->roadBlockLocation
#define ARREST  c->arrestType
#define EXACT   c->racerVehicleExactDescription
#define APPROX  c->racerVehicleApproximateDescription
#define COLOR   c->racerVehicleColor

// Each action's executeAction (0x0020daa0 .. 0x0020f710): one event to
// the library, its parameters from the context.
static void action_say(int32_t a, const SpeechContext *c)
{
    switch (a) {
    case A_AIRBORNE:
        spch_add_event_v(51, 3, FROM, COP, SUP);
        break;
    case A_BACKUP_CONFIRM:
        spch_add_event_v(19, 3, COP, FROM, TTO);
        break;
    case A_BACKUP_REQUEST:
        spch_add_event_v(41, 2, FROM, COP);
        break;
    case A_BACKUP_REQUEST_LOCATION:
        spch_add_event_v(42, 3, LOC, COP, FROM);
        break;
    case A_BEGIN_PURSUIT_COP_HIT_RUN:
        spch_add_event_v(11, 3, FROM, COP, LOC);
        break;
    case A_BEGIN_PURSUIT_GENERAL:
        spch_add_event_v(7, 2, FROM, COP);
        break;
    case A_BEGIN_PURSUIT_NO_ID:
        spch_add_event_v(9, 2, COP, FROM);
        break;
    case A_BEGIN_PURSUIT_HIT_RUN_TRAFFIC:
        spch_add_event_v(14, 3, FROM, COP, LOC);
        break;
    case A_BEGIN_PURSUIT_ID_GENERAL:
        spch_add_event_v(16, 4, FROM, COP, APPROX, COLOR);
        break;
    case A_BEGIN_PURSUIT_ID_SPECIFIC:
        spch_add_event_v(17, 5, FROM, COP, SUP, COLOR, EXACT);
        break;
    case A_BEGIN_PURSUIT_AGAIN:
        spch_add_event_v(199, 4, COP, FROM, EXACT, COLOR);
        break;
    case A_BEGIN_PURSUIT_RACING:
        spch_add_event_v(8, 4, FROM, COP, c->raceType, LOC);
        break;
    case A_BEGIN_PURSUIT_SPEED:
        spch_add_event_v(15, 3, FROM, COP, c->racerVehicleSpeed);
        break;
    case A_BEGIN_PURSUIT_ERRATIC:
        spch_add_event_v(6, 2, FROM, COP);
        break;
    case A_BREAK_PURSUIT:
        spch_add_event_v(43, 2, FROM, COP);
        break;
    case A_CAR_STOPPED:
        spch_add_event_v(188, 3, FROM, COP, EXACT);
        break;
    case A_CHATTER_TRAFFIC:
        spch_add_event_v(20, 1, COP);
        break;
    case A_CHATTER_GENERAL:
        spch_add_event_v(21, 1, COP);
        break;
    case A_COP_BACK_OFF:
        spch_add_event_v(187, 2, FROM, COP);
        break;
    case A_COP_PURSUIT_AVOIDANCE:
        spch_add_event_v(10, 2, FROM, COP);
        break;
    case A_CRASH:
        spch_add_event_v(44, 2, FROM, COP);
        break;
    case A_CRASH_TOW:
        spch_add_event_v(45, 2, COP, FROM);
        break;
    case A_CRASH_BACKUP:
        spch_add_event_v(198, 3, TFROM, TCOP, TO);
        break;
    case A_CURRENT_SPEED:
        spch_add_event_v(47, 3, FROM, COP, c->racerVehicleSpeed);
        break;
    case A_DIRECTION:
        spch_add_event_v(48, 3, FROM, COP, c->direction);
        break;
    case A_DISPATCH_BEGIN_PURSUIT_RACING:
        if (LOC != 0)
            spch_add_event_v(83, 1, LOC);
        break;
    case A_DISPATCH_BEGIN_PURSUIT_HIT_RUN_COP:
        spch_add_event_v(86, 1, TO);
        break;
    case A_DISPATCH_BEGIN_PURSUIT_HIT_RUN_TRAFFIC:
        spch_add_event_v(85, 1, TO);
        break;
    case A_DISPATCH_BEGIN_VEHICLE_ID_SPECIFIC:
        spch_add_event_v(92, 3, TO, COLOR, EXACT);
        break;
    case A_DISPATCH_ROAD_BLOCK_UPDATE:
        // Where, half the time it is known.
        if (RBL != 0 && bRandomI(2, &bDefaultSeed) == 0)
            spch_add_event_v(71, 1, RBL);
        else
            spch_add_event_v(171, 0);
        break;
    case A_DISPATCH_SPIKE_STRIP_SET:
        if (RBL != 0 && bRandomI(2, &bDefaultSeed) == 0)
            spch_add_event_v(170, 1, RBL);
        else
            spch_add_event_v(73, 0);
        break;
    case A_DISPATCH_BEGIN_PURSUIT_SPEED:
        spch_add_event_v(91, 1, TO);
        break;
    case A_DISPATCH_CONFIRM:
        spch_add_event_v(13, 1, TO);
        break;
    case A_DISPATCH_ROTOR_DEPLOYED:
        spch_add_event_v(72, 0);
        break;
    case A_DISPATCH_TERMINATE:
        spch_add_event_v(186, 0);
        break;
    case A_DISPATCH_TOW_CONFIRM:
        spch_add_event_v(81, 1, TO);
        break;
    case A_DISPATCH_ID_REQUEST:
        spch_add_event_v(67, 1, TO);
        break;
    case A_FLAT_TIRE:
        spch_add_event_v(177, 2, FROM, COP);
        break;
    case A_PURSUIT_COP_HIT:
        spch_add_event_v(22, 1, COP);
        break;
    case A_PURSUIT_UPDATE_SPEED:
        spch_add_event_v(54, 5, FROM, COP, SUP, c->racerVehicleSpeed, LOC);
        break;
    case A_PURSUIT_UPDATE_SUBJECT_LOCATION:
        spch_add_event_v(56, 4, FROM, COP, SUP, LOC);
        break;
    case A_PURSUIT_UPDATE_VEHICLE_ID_SPECIFIC:
        spch_add_event_v(65, 6, FROM, COP, 1, COLOR, EXACT, APPROX);
        break;
    case A_RACER_CAUGHT:
        if (c->arrestLevel == 1)
            spch_add_event_v(194, 1, COP);
        else if (c->arrestLevel == 2)
            spch_add_event_v(195, 1, COP);
        else
            spch_add_event_v(0, 2, ARREST, COP);
        break;
    case A_RADIO_ARREST:
        spch_add_event_v(178, 3, ARREST, FROM, COP);
        break;
    case A_REQUEST_ANOTHER_ROAD_BLOCK:
        spch_add_event_v(189, 3, SUP, FROM, COP);
        break;
    case A_ROAD_BLOCK_FAILURE_AVOID:
        spch_add_event_v(33, 3, TFROM, TCOP, SUP);
        break;
    case A_ROAD_BLOCK_FAILURE_THROUGH:
        spch_add_event_v(34, 3, TFROM, TCOP, SUP);
        break;
    case A_ROADBLOCK_REQUEST:
        spch_add_event_v(31, 3, SUP, FROM, COP);
        break;
    case A_ROAD_BLOCK_SET:
        if (RBL == 0)
            spch_add_event_v(172, 3, FROM, COP, SUP);
        else
            spch_add_event_v(35, 4, FROM, COP, SUP, RBL);
        break;
    case A_ROAD_BLOCK_SETTING:
        spch_add_event_v(52, 3, FROM, COP, TO);
        break;
    case A_ROTOR_REQUEST:
        spch_add_event_v(53, 3, FROM, COP, SUP);
        break;
    case A_ROTOR_LOCATION:
        spch_add_event_v(109, 1, LOC);
        break;
    case A_ROTOR_CHATTER:
        spch_add_event_v(112, 1, c->boolParam != 0 ? 128 : 4);
        break;
    case A_ROTOR_TRAFFIC:
        spch_add_event_v(121, 1, 1);
        break;
    case A_ROTOR_SPIKE_FAILED:
        spch_add_event_v(181, 0);
        break;
    case A_SPIKE_STRIP_FAILURE:
        spch_add_event_v(36, 3, TFROM, TCOP, SUP);
        break;
    case A_SPIKE_STRIP_TIRE_BLOW:
        spch_add_event_v(37, 3, FROM, COP, SUP);
        break;
    case A_SPIKE_STRIP_REQUEST:
        spch_add_event_v(32, 3, SUP, FROM, COP);
        break;
    case A_SPIKE_STRIP_SET_LEFT:
        if (RBL == 0)
            spch_add_event_v(174, 3, FROM, COP, SUP);
        else
            spch_add_event_v(38, 4, FROM, COP, SUP, RBL);
        break;
    case A_SPIKE_STRIP_SET_RIGHT:
        if (RBL == 0)
            spch_add_event_v(175, 3, FROM, COP, SUP);
        else
            spch_add_event_v(39, 4, FROM, COP, SUP, RBL);
        break;
    case A_SPIKE_STRIP_SET:
        if (RBL == 0)
            spch_add_event_v(173, 3, COP, SUP, FROM);
        else
            spch_add_event_v(40, 4, COP, SUP, FROM, RBL);
        break;
    case A_STAND_BY_FOR_SUPER:
        spch_add_event_v(185, 0);
        break;
    case A_SUPER_BACK_OFF:
        spch_add_event_v(100, 0);
        break;
    case A_SUPER_REQUEST:
        spch_add_event_v(57, 2, FROM, COP);
        break;
    case A_SUPER_TERMINATE:
        spch_add_event_v(179, 0);
        break;
    case A_SUPERVISOR_CONFIRM:
        spch_add_event_v(180, 1, TO);
        break;
    case A_SUPERVISOR_INITIATES:
        spch_add_event_v(101, 0);
        break;
    case A_SUPERVISOR_ROAD_BLOCK_OK:
        spch_add_event_v(97, 2, TO, 1);
        break;
    case A_SUPERVISOR_ROTOR_OK:
        spch_add_event_v(96, 0);
        break;
    case A_SUPERVISOR_SPIKE_STRIP_OK:
        spch_add_event_v(98, 2, TO, 1);
        break;
    case A_SUSPECT_CRASH:
        spch_add_event_v(58, 3, FROM, COP, SUP);
        break;
    case A_SUSPECT_CRASH_TRAFFIC:
        spch_add_event_v(61, 3, FROM, COP, SUP);
        break;
    case A_SUSPECT_FOUND:
        spch_add_event_v(62, 4, FROM, COP, SUP, LOC);
        break;
    case A_SUSPECT_LOST:
        spch_add_event_v(63, 3, FROM, COP, SUP);
        break;
    case A_TACTIC_HIT_FORMAL:
        spch_add_event_v(25, 3, FROM, COP, TTO);
        break;
    case A_TACTIC_HIT_INFORMAL:
        spch_add_event_v(28, 1, TCOP);
        break;
    case A_TACTIC_DIVERT:
        spch_add_event_v(24, 2, FROM, COP);
        break;
    case A_TACTIC_CUTOFF:
        spch_add_event_v(23, 2, FROM, COP);
        break;
    case A_UPDATE_RECKLESS:
        spch_add_event_v(50, 3, FROM, COP, SUP);
        break;
    case A_DISPATCH_BE_ON_LOOKOUT:
        spch_add_event_v(203, 2, 1, LOC);
        break;
    case A_DISPATCH_ROAD_BLOCK_NA:
        spch_add_event_v(201, 1, TO);
        break;
    case A_DISPATCH_HELICOPTER_NA:
        spch_add_event_v(202, 1, TO);
        break;
    default:                            // nullAction_t
        break;
    }
}

// action_t::execute (0x0020bdf8): the radio's squelch first. The
// helicopter's (actionHelicopter_t::execute, 0x0020be48) start its noise
// too.
static void action_execute(int32_t a, const SpeechContext *c)
{
    speechnoise_begin_squelch_noise(speechnoise_get_instance());
    if (a == A_ROTOR_LOCATION || a == A_ROTOR_CHATTER
        || a == A_ROTOR_TRAFFIC || a == A_ROTOR_SPIKE_FAILED)
        speechnoise_start_helicopter_noise(speechnoise_get_instance());
    action_say(a, c);
}

// fsm::handleEvent (0x0020bfb0) and state_t's (0x0020c100): the first
// transition on `event` whose condition holds, its action, and its
// state; with none, the state stays.
static void fsm_handle_event(SpeechMgr *m, int32_t event,
                             const SpeechContext *c)
{
    const SpeechTransition *t = kStates[m->state].t;
    int32_t n = kStates[m->state].n;
    int32_t i;

    for (i = 0; i < n; i++) {
        if (t[i].event == event && condition_is_true(t[i].cond, c) != 0) {
            action_execute(t[i].action, c);
            m->state = t[i].dest;
            return;
        }
    }
}

// --------------------------------------------------------- speech::mgr_t

SpeechMgr *speechmgr_get_instance(void)
{
    if (!gConstructed) {
        speechmgr_construct(&gInstance);
        gConstructed = 1;
    }
    return &gInstance;
}

void speechmgr_construct(SpeechMgr *m)
{
    // The machine's states, conditions and actions are tables here;
    // retail builds them (nfsFsm, 0x0020c770), then starts the machine.
    m->full = 0;
    m->read = 0;
    m->write = 0;
    m->previousSedPlaybackState = 0;
    m->state = SPEECH_STATE_READY;
    m->nextContext = 0;
}

// A replay, or the race over: no speech.
static int32_t speech_off(void)
{
    RaceCoordinator *rc = pRaceCoordinator;
    RCState s;

    if (rc == NULL)
        return 0;
    s = racecoordinator_get_current_state(rc);
    return s == RCSTATE_INSTANT_REPLAY || s == RCSTATE_POSTRACE
           || s == RCSTATE_AUTO_REPLAY
           || racecoordinator_is_replay_demo_mode(rc);
}

void speechmgr_update(SpeechMgr *m)
{
    SedWedge *w;
    int32_t   playing;

    if (speech_off())
        return;
    w = sedwedge_sound_instance();
    playing = w != NULL && w->status != SEDWEDGE_PAUSED
              && w->status != SEDWEDGE_IDLE;
    if (playing) {
        if (!speechnoise_is_radio_noise(speechnoise_get_instance()))
            speechnoise_start_radio_noise(speechnoise_get_instance());
        m->previousSedPlaybackState = 1;
        return;
    }
    if (speechnoise_is_radio_noise(speechnoise_get_instance())) {
        speechnoise_stop_radio_noise(speechnoise_get_instance());
        speechnoise_stop_helicopter_noise(speechnoise_get_instance());
    }
    if (m->state != SPEECH_STATE_READY) {
        fsm_handle_event(m, 1, &m->contexts[m->currContext]);
        m->previousSedPlaybackState = 1;
    } else if (!m->full && m->read == m->write) {
        m->previousSedPlaybackState = 0;
    } else {
        SpeechQueueEntry e = m->queue[m->read];

        m->read = m->read + 1 == SPEECHMGR_QUEUE ? 0 : m->read + 1;
        m->full = 0;
        m->currContext = e.contextNum;
        fsm_handle_event(m, e.event, &m->contexts[e.contextNum]);
        m->previousSedPlaybackState = 1;
    }
}

void speechmgr_flush_queue(SpeechMgr *m)
{
    SedWedge *w;

    m->state = SPEECH_STATE_READY;
    m->full = 0;
    m->write = m->read;
    speechnoise_stop_radio_noise(speechnoise_get_instance());
    speechnoise_stop_helicopter_noise(speechnoise_get_instance());
    w = sedwedge_sound_instance();
    if (w != NULL)
        sedwedge_clear_event_queue(w);
}

void speechmgr_allocate_voices(SpeechMgr *m)
{
    (void)m;
    speechcontext_shuffle_cop_ids();
}

void speechmgr_fade(SpeechMgr *m, float level)
{
    SedWedge *w = sedwedge_sound_instance();

    (void)m;
    if (w != NULL)
        sedwedge_fade(w, level);
}

void speechmgr_mute(SpeechMgr *m, int32_t on)
{
    SedWedge *w = sedwedge_sound_instance();

    (void)m;
    if (w != NULL)
        sedwedge_mute(w, on != 0);
}

SpeechContext *speechmgr_get_next_context(SpeechMgr *m)
{
    return &m->contexts[m->nextContext];
}

void speechmgr_push_speech_event(SpeechMgr *m, int32_t event)
{
    if (speech_off())
        return;
    if (m->full)
        return;
    m->queue[m->write].event = event;
    m->queue[m->write].contextNum = m->nextContext;
    m->write = m->write + 1 == SPEECHMGR_QUEUE ? 0 : m->write + 1;
    m->full = m->write == m->read;
    m->nextContext = m->nextContext + 1 == SPEECHMGR_CONTEXTS
                     ? 0 : m->nextContext + 1;
}

// ------------------------------------------------------------- the raises

#define NEXT SpeechContext *c = speechmgr_get_next_context(m)

void speechmgr_raise_pursuit_cop_hit(SpeechMgr *m, uint32_t speaker,
                                     int32_t location)
{
    NEXT;

    c->copUnitLocation = location;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 2);
}

void speechmgr_raise_begin_pursuit_cop_hit_run(SpeechMgr *m,
                                               uint32_t speaker,
                                               int32_t location)
{
    NEXT;

    c->copUnitLocation = location;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 3);
}

void speechmgr_raise_begin_pursuit_general(SpeechMgr *m, uint32_t speaker)
{
    NEXT;

    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 5);
}

void speechmgr_raise_begin_pursuit_erratic(SpeechMgr *m, uint32_t speaker)
{
    NEXT;

    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 4);
}

void speechmgr_raise_begin_pursuit_no_id(SpeechMgr *m, uint32_t speaker)
{
    NEXT;

    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 10);
}

void speechmgr_raise_begin_pursuit_hit_run_traffic(SpeechMgr *m,
                                                   uint32_t speaker,
                                                   int32_t location)
{
    NEXT;

    c->copUnitLocation = location;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 6);
}

void speechmgr_raise_begin_pursuit_id_general(SpeechMgr *m, uint32_t speaker,
                                              int32_t approx, int32_t color)
{
    NEXT;

    c->racerVehicleColor = color;
    c->copUnitId = speaker;
    c->racerVehicleApproximateDescription = approx;
    speechmgr_push_speech_event(m, 7);
}

void speechmgr_raise_begin_pursuit_id_specific(SpeechMgr *m,
                                               uint32_t speaker, int32_t b,
                                               int32_t exact, int32_t color)
{
    NEXT;

    c->racerVehicleColor = color;
    c->copUnitId = speaker;
    c->isSupervisorActive = b;
    c->racerVehicleExactDescription = exact;
    speechmgr_push_speech_event(m, 8);
}

void speechmgr_raise_begin_pursuit_again(SpeechMgr *m, uint32_t speaker,
                                         int32_t exact, int32_t color)
{
    NEXT;

    c->racerVehicleColor = color;
    c->copUnitId = speaker;
    c->racerVehicleExactDescription = exact;
    speechmgr_push_speech_event(m, 14);
}

void speechmgr_raise_begin_pursuit_id_repeated(SpeechMgr *m,
                                               uint32_t speaker, int32_t b,
                                               int32_t exact, int32_t color)
{
    NEXT;

    c->racerVehicleColor = color;
    c->copUnitId = speaker;
    c->isSupervisorActive = b;
    c->racerVehicleExactDescription = exact;
    speechmgr_push_speech_event(m, 9);
}

void speechmgr_raise_begin_pursuit_speed(SpeechMgr *m, uint32_t speaker,
                                         float speed)
{
    NEXT;

    c->copUnitId = speaker;
    c->racerVehicleSpeed = speech_convert_speed(speed);
    speechmgr_push_speech_event(m, 13);
}

void speechmgr_raise_backup_request(SpeechMgr *m, uint32_t speaker)
{
    NEXT;

    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 15);
}

void speechmgr_raise_backup_confirm(SpeechMgr *m, uint32_t speaker,
                                    uint32_t target)
{
    NEXT;

    c->copTargetUnitId = target;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 17);
}

void speechmgr_raise_backup_request_location(SpeechMgr *m, uint32_t speaker,
                                             int32_t location)
{
    NEXT;

    c->copUnitLocation = location;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 16);
}

void speechmgr_raise_crash(SpeechMgr *m, uint32_t speaker, uint32_t target)
{
    NEXT;

    c->copTargetUnitId = target;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 39);
}

void speechmgr_raise_flat_tire(SpeechMgr *m, uint32_t speaker,
                               uint32_t target)
{
    NEXT;

    c->copTargetUnitId = target;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 40);
}

void speechmgr_raise_crash_tow(SpeechMgr *m, uint32_t speaker,
                               uint32_t target)
{
    NEXT;

    c->copTargetUnitId = target;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 38);
}

void speechmgr_raise_cop_pursuit_avoidance(SpeechMgr *m, uint32_t speaker)
{
    NEXT;

    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 20);
}

void speechmgr_raise_pursuit_update_subject_location(SpeechMgr *m,
                                                     uint32_t speaker,
                                                     int32_t location,
                                                     int32_t b)
{
    NEXT;

    c->isSupervisorActive = b;
    c->copUnitId = speaker;
    c->copUnitLocation = location;
    speechmgr_push_speech_event(m, 22);
}

void speechmgr_raise_suspect_found(SpeechMgr *m, uint32_t speaker, int32_t b,
                                   int32_t location)
{
    NEXT;

    c->copUnitLocation = location;
    c->copUnitId = speaker;
    c->isSupervisorActive = b;
    speechmgr_push_speech_event(m, 25);
}

void speechmgr_raise_tactic_hit(SpeechMgr *m, uint32_t speaker,
                                uint32_t target)
{
    NEXT;

    c->copTargetUnitId = target;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 27);
}

void speechmgr_raise_tactic_divert(SpeechMgr *m, uint32_t speaker)
{
    NEXT;

    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 29);
}

void speechmgr_raise_tactic_cutoff(SpeechMgr *m, uint32_t speaker)
{
    NEXT;

    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 30);
}

void speechmgr_raise_update_reckless(SpeechMgr *m, uint32_t speaker,
                                     int32_t b)
{
    NEXT;

    (void)b;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 31);
}

void speechmgr_raise_racer_caught(SpeechMgr *m, uint32_t speaker,
                                  int32_t level, int32_t arrest)
{
    NEXT;

    c->arrestLevel = level;
    c->copUnitId = speaker;
    c->arrestType = arrest;
    speechmgr_push_speech_event(m, 32);
}

void speechmgr_raise_super_back_off(SpeechMgr *m)
{
    speechmgr_push_speech_event(m, 33);
}

void speechmgr_raise_cop_back_off(SpeechMgr *m, uint32_t speaker, int32_t b)
{
    NEXT;

    c->isSupervisorActive = b;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 34);
}

void speechmgr_raise_car_stopped(SpeechMgr *m, uint32_t speaker,
                                 int32_t exact)
{
    NEXT;

    c->racerVehicleExactDescription = exact;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 36);
}

void speechmgr_raise_radio_arrest(SpeechMgr *m, uint32_t speaker)
{
    NEXT;

    c->copUnitId = speaker;
    c->arrestType = SPEECH_ARREST_FORMAL;
    speechmgr_push_speech_event(m, 35);
}

void speechmgr_raise_rotor_request(SpeechMgr *m, uint32_t speaker, int32_t b)
{
    NEXT;

    c->isSupervisorActive = b;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 41);
}

void speechmgr_raise_rotor_confirm(SpeechMgr *m)
{
    speechmgr_push_speech_event(m, 42);
}

void speechmgr_raise_rotor_location(SpeechMgr *m, int32_t location)
{
    NEXT;

    c->copUnitLocation = location;
    speechmgr_push_speech_event(m, 43);
}

void speechmgr_raise_rotor_chatter(SpeechMgr *m, int32_t b)
{
    NEXT;

    c->boolParam = b;
    speechmgr_push_speech_event(m, 44);
}

void speechmgr_raise_rotor_spike_failed(SpeechMgr *m, uint32_t speaker,
                                        int32_t b)
{
    NEXT;

    c->isSupervisorActive = b;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 46);
}

void speechmgr_raise_rotor_traffic(SpeechMgr *m)
{
    speechmgr_push_speech_event(m, 45);
}

void speechmgr_raise_road_block_failure_avoid(SpeechMgr *m, uint32_t target,
                                              int32_t b, uint32_t speaker)
{
    NEXT;

    c->copUnitId = speaker;
    c->copTargetUnitId = target;
    c->isSupervisorActive = b;
    speechmgr_push_speech_event(m, 47);
}

void speechmgr_raise_road_block_failure_through(SpeechMgr *m,
                                                uint32_t target, int32_t b,
                                                uint32_t speaker)
{
    NEXT;

    c->copUnitId = speaker;
    c->copTargetUnitId = target;
    c->isSupervisorActive = b;
    speechmgr_push_speech_event(m, 48);
}

void speechmgr_raise_roadblock_request(SpeechMgr *m, uint32_t speaker,
                                       int32_t b)
{
    NEXT;

    c->isSupervisorActive = b;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 49);
}

void speechmgr_raise_request_another_roadblock(SpeechMgr *m,
                                               uint32_t speaker, int32_t b)
{
    NEXT;

    c->isSupervisorActive = b;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 52);
}

void speechmgr_raise_road_block_set(SpeechMgr *m, uint32_t speaker,
                                    int32_t b, int32_t location)
{
    NEXT;

    c->roadBlockLocation = location;
    c->copUnitId = speaker;
    c->isSupervisorActive = b;
    speechmgr_push_speech_event(m, 50);
}

void speechmgr_raise_road_block_setting(SpeechMgr *m, uint32_t speaker,
                                        int32_t b)
{
    NEXT;

    c->isSupervisorActive = b;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 51);
}

void speechmgr_raise_spike_strip_failure(SpeechMgr *m, uint32_t target,
                                         int32_t b, uint32_t speaker)
{
    NEXT;

    c->isSupervisorActive = b;
    c->copTargetUnitId = target;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 53);
}

void speechmgr_raise_spike_strip_request(SpeechMgr *m, uint32_t speaker,
                                         int32_t b)
{
    NEXT;

    c->isSupervisorActive = b;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 54);
}

void speechmgr_raise_spike_strip_set(SpeechMgr *m, uint32_t speaker,
                                     int32_t location, int32_t b)
{
    NEXT;

    c->roadBlockLocation = location;
    c->copUnitId = speaker;
    c->isSupervisorActive = b;
    speechmgr_push_speech_event(m, 55);
}

void speechmgr_raise_spike_strip_set_left(SpeechMgr *m, uint32_t speaker,
                                          int32_t location, int32_t b)
{
    NEXT;

    c->roadBlockLocation = location;
    c->copUnitId = speaker;
    c->isSupervisorActive = b;
    speechmgr_push_speech_event(m, 56);
}

void speechmgr_raise_spike_strip_set_right(SpeechMgr *m, uint32_t speaker,
                                           int32_t location, int32_t b)
{
    NEXT;

    c->roadBlockLocation = location;
    c->copUnitId = speaker;
    c->isSupervisorActive = b;
    speechmgr_push_speech_event(m, 57);
}

void speechmgr_raise_spike_strip_tire_blow(SpeechMgr *m, uint32_t speaker,
                                           int32_t b)
{
    NEXT;

    c->isSupervisorActive = b;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 58);
}

void speechmgr_raise_super_request(SpeechMgr *m, uint32_t speaker)
{
    NEXT;

    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 59);
}

void speechmgr_raise_super_initiate(SpeechMgr *m, uint32_t speaker,
                                    float speed, int32_t location,
                                    int32_t exact, int32_t color)
{
    NEXT;

    c->copTargetUnitId = speaker;
    c->copUnitId = speaker;
    c->racerVehicleSpeed = speech_convert_speed(speed);
    c->racerVehicleColor = color;
    c->copUnitLocation = location;
    c->racerVehicleExactDescription = exact;
    speechmgr_push_speech_event(m, 60);
}

void speechmgr_raise_current_speed(SpeechMgr *m, uint32_t speaker,
                                   float speed)
{
    NEXT;

    c->copUnitId = speaker;
    c->racerVehicleSpeed = speech_convert_speed(speed);
    speechmgr_push_speech_event(m, 62);
}

void speechmgr_raise_suspect_crash_traffic(SpeechMgr *m, uint32_t speaker,
                                           int32_t b)
{
    NEXT;

    c->isSupervisorActive = b;
    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 67);
}

void speechmgr_raise_dispatch_be_on_lookout(SpeechMgr *m, int32_t location)
{
    NEXT;

    c->copUnitLocation = location;
    speechmgr_push_speech_event(m, 68);
}

void speechmgr_raise_dispatch_road_block_na(SpeechMgr *m, uint32_t speaker)
{
    NEXT;

    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 69);
}

void speechmgr_raise_dispatch_helicopter_na(SpeechMgr *m, uint32_t speaker)
{
    NEXT;

    c->copUnitId = speaker;
    speechmgr_push_speech_event(m, 70);
}

// ------------------------------------------------------- speechContext_t

// ShuffleArray (0x0020f820): each place in turn swapped with one at
// random from it on.
static void shuffle_array(uint32_t *a, uint32_t n)
{
    while (n >= 2) {
        int32_t  r = bRandomI((int32_t)n, &bDefaultSeed);
        uint32_t t = a[0];

        a[0] = a[r];
        a[r] = t;
        n--;
        a++;
    }
}

void speechcontext_shuffle_cop_ids(void)
{
    uint32_t from[6] = { 1, 2, 4, 8, 16, 32 };
    int32_t  i;

    gCopIdTable[0] = 2;
    gCopIdTable[1] = 4;
    gCopIdTable[2] = 8;
    gCopIdTable[3] = 32;
    shuffle_array(gCopIdTable, 4);
    shuffle_array(from, 6);
    for (i = 0; i < 4; i++) {
        gFromIdTable[i] = from[i];
        gToIdTable[i] = from[i];
    }
}

static uint32_t id_of(const uint32_t *table, uint32_t unit)
{
    return unit < 4 ? table[unit] : 0;
}

uint32_t speechcontext_get_cop_id(const SpeechContext *c)
{
    return id_of(gCopIdTable, c->copUnitId);
}

uint32_t speechcontext_get_target_cop_id(const SpeechContext *c)
{
    return id_of(gCopIdTable, c->copTargetUnitId);
}

uint32_t speechcontext_get_from_cop_id(const SpeechContext *c)
{
    return id_of(gFromIdTable, c->copUnitId);
}

uint32_t speechcontext_get_target_from_cop_id(const SpeechContext *c)
{
    return id_of(gFromIdTable, c->copTargetUnitId);
}

uint32_t speechcontext_get_to_id(const SpeechContext *c)
{
    return id_of(gToIdTable, c->copUnitId);
}

uint32_t speechcontext_get_target_to_id(const SpeechContext *c)
{
    return id_of(gToIdTable, c->copTargetUnitId);
}

const uint32_t *speechcontext_id_table(int32_t which)
{
    return which == 0 ? gCopIdTable : which == 1 ? gFromIdTable : gToIdTable;
}

// ---------------------------------------------------------------- Speech

int32_t speech_convert_speed(float speed)
{
    float x;

    if (speed < 100.0f)
        return 0;
    if (340.0f < speed)
        return 4096;
    // fptoui; a NaN comes out 0.
    x = (speed - 100.0f) * 0.05f;
    if (x != x)
        return 1;
    return (int32_t)(1u << ((uint32_t)x & 31));
}
