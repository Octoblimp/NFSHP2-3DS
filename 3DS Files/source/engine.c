// engine -- see engine.h.

#include "engine.h"
#include "carstate.h"

// gp-30428, 0x3983126f. Seconds per WorldTimer tick.
#define WORLD_TICK_SECONDS 0.000250000012f

// gp-30432, 0x3ecccccd. Applied to a negative total torque, player only.
#define NEGATIVE_TORQUE_SCALE 0.400000006f

// 0x40400000 in GetTotalEngineTorque, 0x40800000 in DecrementNitro.
#define NITRO_TORQUE_SCALE 3.0f
#define NITRO_SECONDS      4.0f

// 0x42c8_0000 -- the rev limiter bites this far below MaxRPM.
#define REV_LIMITER_MARGIN 100.0f

// CarState::DriverMode == 1 is the player. The engine is the only object in
// this group that branches on it.
#define DRIVER_MODE_PLAYER 1


void engine_init(Engine *e, const EngineInfo *ei, struct CarState *cs)
{
    // `sw v0,8(s0)` at 0x00182404, before anything else is written. The
    // port kept a zero here until PhysicsSystem started dispatching
    // through component vptrs.
    e->_vtable = ENGINE_VTABLE;

    table_init(&e->TorqueCurve,   ei->TorqueCurveTable,   9,
               ei->IdleRPM, ei->MaxRPM);
    table_init(&e->EngineBraking, ei->EngineBrakingTable, 3,
               ei->IdleRPM, ei->MaxRPM);

    e->EI        = ei;
    e->pCarState = cs;

    e->CatchupTorqueMultiplier = 1.0f;
    e->IsHP                    = 0;
    e->NitroFlag               = 0;
    e->NitroBoostTimer         = 0.0f;
    e->ThrottleOverride        = 1.0f;

    // Throttle and RoadTorque are deliberately absent: the constructor does
    // not initialise them, so a freshly built Engine inherits whatever was
    // in the allocation until the first SetThrottle and ComputeAuxiliaries.
}

void engine_compute_auxiliaries(Engine *e)
{
    float lo = e->EI->IdleRPM * ENGINE_RPM_TO_RADS;
    float hi;

    if (e->State.w < lo)
        e->State.w = lo;

    hi = e->EI->MaxRPM * ENGINE_RPM_TO_RADS;

    if (hi < e->State.w)
        e->State.w = hi;

    e->RoadTorque = 0.0f;
}

int32_t engine_get_derivative(Engine *e, float *out)
{
    out[0] = (engine_get_total_engine_torque(e) + e->RoadTorque)
           / e->EI->MomentOfInertia;
    return 0;
}

float engine_get_torque(Engine *e)
{
    float rpm = e->State.w * ENGINE_RADS_TO_RPM;
    float t   = table_get_value(&e->TorqueCurve, rpm)
              * e->CatchupTorqueMultiplier;

    if (e->IsHP)
        t *= ENGINE_TORQUE_HP_MULTIPLIER;

    // Not a cut -- a reversal. Past the limiter the crank is pushed back.
    if (!(rpm < e->EI->MaxRPM - REV_LIMITER_MARGIN))
        t = -ENGINE_MAX_RPM_EFFECT * t;

    return t;
}

float engine_get_engine_torque(Engine *e, float rpm)
{
    float t = table_get_value(&e->TorqueCurve, rpm)
            * e->CatchupTorqueMultiplier;

    if (e->IsHP)
        t *= ENGINE_TORQUE_HP_MULTIPLIER;

    // Spelled as (MaxRPM - margin) <= rpm in the listing, where GetTorque
    // spells the same test as !(rpm < MaxRPM - margin). Both are the same
    // comparison; the multiply is ordered the other way round, though --
    // t * -MaxRPMEffect here against -MaxRPMEffect * t there -- and that is
    // kept because float multiply is commutative but the listing is what it
    // is.
    if (e->EI->MaxRPM - REV_LIMITER_MARGIN <= rpm)
        t = t * -ENGINE_MAX_RPM_EFFECT;

    return t;
}

float engine_get_total_engine_torque(Engine *e)
{
    float eff = e->Throttle * e->ThrottleOverride;
    float drive, braking, total;

    drive = engine_get_torque(e) * eff;

    if (e->NitroFlag)
        drive *= NITRO_TORQUE_SCALE;

    // Engine braking is indexed in RPM like the torque curve, and is scaled
    // by how far the throttle is from open rather than by the throttle.
    braking = table_get_value(&e->EngineBraking,
                              e->State.w * ENGINE_RADS_TO_RPM);

    total = drive + -braking * (1.0f - eff);

    // Only the player's car gets its negative torque softened. An AI car
    // takes the full engine braking.
    if (e->pCarState->DriverMode == DRIVER_MODE_PLAYER) {
        if (total < 0.0f)
            total *= NEGATIVE_TORQUE_SCALE;
    }

    return total;
}

void engine_decrement_nitro(Engine *e)
{
    if (!e->NitroFlag)
        return;

    // lwc1 then cvt.s.w: WorldTimer is loaded as an integer and converted,
    // not reinterpreted.
    if (e->NitroBoostTimer + NITRO_SECONDS
            < (float)WorldTimer * WORLD_TICK_SECONDS)
        e->NitroFlag = 0;
}

float engine_get_angular_acceleration(Engine *e)
{
    return (engine_get_total_engine_torque(e) + e->RoadTorque)
         / e->EI->MomentOfInertia;
}

float engine_get_torque_response(const Engine *e)
{
    return 1.0f / e->EI->MomentOfInertia;
}

void engine_apply_torque(Engine *e, float t)
{
    e->RoadTorque += t;
}

float engine_get_effective_throttle(const Engine *e)
{
    return e->Throttle * e->ThrottleOverride;
}

float engine_get_angular_velocity(const Engine *e) { return e->State.w; }
const EngineInfo *engine_get_ei(const Engine *e)   { return e->EI; }
float engine_get_idle_rpm(const Engine *e)      { return e->EI->IdleRPM; }
float engine_get_max_rpm(const Engine *e)       { return e->EI->MaxRPM; }
float engine_get_red_line_rpm(const Engine *e)  { return e->EI->RedLineRPM; }
float engine_get_throttle(const Engine *e)      { return e->Throttle; }
float engine_get_nitro_boost_timer(const Engine *e) { return e->NitroBoostTimer; }
int32_t engine_get_nitro_flag(const Engine *e)  { return e->NitroFlag; }
int32_t engine_get_size(const Engine *e)        { (void)e; return 1; }

const EngineState *engine_get_state(const Engine *e) { return &e->State; }
void engine_get_state_f(const Engine *e, float *out) { out[0] = e->State.w; }
void engine_set_state_f(Engine *e, const float *in)  { e->State.w = in[0]; }
void engine_set_state(Engine *e, float w)            { e->State.w = w; }

void engine_set_throttle(Engine *e, float t)          { e->Throttle = t; }
void engine_set_throttle_override(Engine *e, float t) { e->ThrottleOverride = t; }
void engine_set_is_hp(Engine *e, int32_t b)           { e->IsHP = b; }
void engine_set_nitro_flag(Engine *e, int32_t b)      { e->NitroFlag = b; }
void engine_set_nitro_boost_timer(Engine *e, float t) { e->NitroBoostTimer = t; }
void engine_set_catchup_torque_multiplier(Engine *e, float m)
{
    e->CatchupTorqueMultiplier = m;
}
