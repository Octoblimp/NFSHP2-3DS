// engine -- Engine.obj (0x001823d8 .. 0x00183f70, in two runs).
//
// The engine is a one-state integrable: its whole state is the crankshaft
// angular velocity, in radians per second, and its derivative is
// (total torque) / (moment of inertia). Everything else here exists to
// work out that torque -- the torque curve, the engine-braking curve, the
// throttle, nitro, the rev limiter and the AI catch-up multiplier.
//
// Two things to keep straight. **State.w is rad/s, the curves are indexed
// in RPM**, and the object converts at every boundary with the two
// constants below. And **Engine's two curves are Tables over
// IdleRPM..MaxRPM**, so a table lookup below idle or above max is clamped
// rather than extrapolated -- see table.h.
//
// The functions are in two runs because the compiler split the object:
// the arithmetic at 0x001823d8..0x00182824 and the accessors at
// 0x00183e10..0x00183f70. DoSnapshot (0x001824d8) is not ported; it needs
// ReplaySnapshot, the same dependency that stopped CarState::DoSnapshot.
//
// Layout from .mdebug, `Engine (size=92)`, every offset re-derived from
// the listing. See docs/formats/car-engine.md.

#ifndef ENGINE_H
#define ENGINE_H

#include <stddef.h>
#include <stdint.h>

#include "table.h"

struct CarState;

// EngineInfo, 64 bytes, part of the car type data. Read-only to Engine.
typedef struct EngineInfo {
    float IdleRPM;                 //  0
    float RedLineRPM;              //  4
    float MaxRPM;                  //  8
    float MomentOfInertia;         // 12
    float TorqueCurveTable[9];     // 16
    float EngineBrakingTable[3];   // 52
} EngineInfo;

#ifndef ENGINE_NO_ASSERT
typedef char engineinfo_size_check[
    (sizeof(EngineInfo) == 64
     && offsetof(EngineInfo, MaxRPM)             ==  8
     && offsetof(EngineInfo, MomentOfInertia)    == 12
     && offsetof(EngineInfo, TorqueCurveTable)   == 16
     && offsetof(EngineInfo, EngineBrakingTable) == 52
     ) ? 1 : -1];
#endif

// Engine::EngineState, one float.
typedef struct EngineState {
    float w;                       // rad/s
} EngineState;

typedef struct Engine {
    uint8_t           _head[8];    //  0  PhysicsComponent's two list links
    uint32_t          _vtable;     //  8  ENGINE_VTABLE, from the ctor
    EngineState       State;       // 12
    const EngineInfo *EI;          // 16
    struct CarState  *pCarState;   // 20
    Table             TorqueCurve; // 24
    Table             EngineBraking;//44
    int32_t           IsHP;        // 64  bool, stored as a word
    float             Throttle;    // 68
    float             RoadTorque;  // 72
    float             ThrottleOverride; // 76
    int32_t           NitroFlag;   // 80  bool, stored as a word
    float             NitroBoostTimer;  // 84
    float             CatchupTorqueMultiplier; // 88
} Engine;

// CarState could carry its widening as a single CARSTATE_SLACK term because
// its pointers all sit at the front. Engine's do not -- EI and pCarState
// come after the state, and each Table carries one -- so on a 64-bit host
// the shift is no longer a constant times the pointer growth.
//
// So the PS2 layout is recorded as a mirror with every pointer narrowed to
// 32 bits. The mirror compiles to exactly the PS2 struct on any host, and
// the assert below checks all twelve offsets against it. What that proves
// is that the offsets claimed here are self-consistent and add up to 92 --
// it does NOT prove the live struct above matches, because the live struct
// is the one with real pointers. That half is established by the
// behavioural transcript in tools/engine_check.py, which walks every field.
typedef struct EnginePS2 {
    uint8_t  _head[8];
    uint32_t _vtable;
    float    State_w;
    uint32_t EI;
    uint32_t pCarState;
    uint32_t TorqueCurve[5];
    uint32_t EngineBraking[5];
    int32_t  IsHP;
    float    Throttle;
    float    RoadTorque;
    float    ThrottleOverride;
    int32_t  NitroFlag;
    float    NitroBoostTimer;
    float    CatchupTorqueMultiplier;
} EnginePS2;

#ifndef ENGINE_NO_ASSERT
typedef char engine_size_check[
    (sizeof(EnginePS2) == 92
     && offsetof(EnginePS2, _vtable)       ==  8
     && offsetof(EnginePS2, State_w)       == 12
     && offsetof(EnginePS2, EI)            == 16
     && offsetof(EnginePS2, pCarState)     == 20
     && offsetof(EnginePS2, TorqueCurve)   == 24
     && offsetof(EnginePS2, EngineBraking) == 44
     && offsetof(EnginePS2, IsHP)          == 64
     && offsetof(EnginePS2, Throttle)      == 68
     && offsetof(EnginePS2, RoadTorque)    == 72
     && offsetof(EnginePS2, ThrottleOverride) == 76
     && offsetof(EnginePS2, NitroFlag)     == 80
     && offsetof(EnginePS2, NitroBoostTimer) == 84
     && offsetof(EnginePS2, CatchupTorqueMultiplier) == 88
     && sizeof(EngineInfo) == 64
     ) ? 1 : -1];
#endif

// _vt$6Engine. The ctor builds it with `lui v0,0x29 ; addiu v0,v0,31352`
// (0x001823dc, 0x001823e4) and so does the destructor (0x0018247c); the
// entries are installed by physcomp.c.
#define ENGINE_VTABLE 0x00297a78u

// RPM <-> rad/s. 0x3dd67745 and 0x4118c9f3 in the constant pool; they are
// 2pi/60 and 60/2pi to the bit. The object holds *two* copies of the
// rad/s->RPM value (gp-30440 and gp-30436, both 0x4118c9f3); they are the
// same number, so one macro covers both uses.
#define ENGINE_RPM_TO_RADS  0.104719676f   // 0x3dd67745
#define ENGINE_RADS_TO_RPM  9.54930401f    // 0x4118c9f3

// Named globals from the constant pool, kept as the image names them.
#define ENGINE_TORQUE_HP_MULTIPLIER 1.04999995f  // TorqueHPMultiplier
#define ENGINE_MAX_RPM_EFFECT       15.0f        // MaxRPMEffect

// WorldTimer, the image's global tick counter (gp-20224), an int32 running
// at 4000 Hz -- DecrementNitro scales it by 0.00025 to get seconds. The
// clock object owns it (realtime.c). A harness that does not link the clock
// defines its own and drives it directly.
#include "realtime.h"

// 0x001823d8. Builds the two Tables over IdleRPM..MaxRPM, stores the two
// pointers, and sets ThrottleOverride and CatchupTorqueMultiplier to 1.
// Note what it does NOT set: Throttle and RoadTorque are left as they were.
void engine_init(Engine *e, const EngineInfo *ei, struct CarState *cs);

// 0x00182578. Clamps State.w into [IdleRPM, MaxRPM] (converted to rad/s)
// and clears RoadTorque, ready for the next timestep's ApplyTorque calls.
void engine_compute_auxiliaries(Engine *e);

// 0x001825c8. out[0] = (GetTotalEngineTorque() + RoadTorque) / MomentOfInertia.
// Returns 0 -- the integrator reads the count from GetSize instead.
int32_t engine_get_derivative(Engine *e, float *out);

// 0x00182618. The torque curve at the current RPM, times the catch-up
// multiplier, times TorqueHPMultiplier when IsHP, and negated and scaled by
// MaxRPMEffect once within 100 RPM of MaxRPM -- that last is the rev
// limiter, and it does not merely cut torque, it reverses it.
float engine_get_torque(Engine *e);

// 0x00182760. The same calculation at a caller-supplied RPM.
float engine_get_engine_torque(Engine *e, float rpm);

// 0x001826a0. GetTorque scaled by the effective throttle (tripled while
// nitro is lit), minus the engine-braking curve scaled by how far the
// throttle is from closed. A negative total is scaled by 0.4 for a
// player-driven car (CarState::DriverMode == 1) only.
float engine_get_total_engine_torque(Engine *e);

// 0x001827e0. Clears NitroFlag once four seconds of world time have passed
// since NitroBoostTimer.
void engine_decrement_nitro(Engine *e);

// 0x00183ee0 / 0x00183ec8. The acceleration GetDerivative would produce,
// and 1/MomentOfInertia.
float engine_get_angular_acceleration(Engine *e);
float engine_get_torque_response(const Engine *e);

// 0x00183e18. RoadTorque += t. The drivetrain's way in.
void  engine_apply_torque(Engine *e, float t);

// The accessors, 0x00183e10 .. 0x00183f70.
float engine_get_effective_throttle(const Engine *e);   // Throttle * Override
float engine_get_angular_velocity(const Engine *e);
const EngineInfo *engine_get_ei(const Engine *e);
float engine_get_idle_rpm(const Engine *e);
float engine_get_max_rpm(const Engine *e);
float engine_get_red_line_rpm(const Engine *e);
float engine_get_throttle(const Engine *e);
float engine_get_nitro_boost_timer(const Engine *e);
int32_t engine_get_nitro_flag(const Engine *e);
int32_t engine_get_size(const Engine *e);               // always 1
const EngineState *engine_get_state(const Engine *e);
void  engine_get_state_f(const Engine *e, float *out);
void  engine_set_state_f(Engine *e, const float *in);
void  engine_set_state(Engine *e, float w);
void  engine_set_throttle(Engine *e, float t);
void  engine_set_throttle_override(Engine *e, float t);
void  engine_set_is_hp(Engine *e, int32_t b);
void  engine_set_nitro_flag(Engine *e, int32_t b);
void  engine_set_nitro_boost_timer(Engine *e, float t);
void  engine_set_catchup_torque_multiplier(Engine *e, float m);

#endif
