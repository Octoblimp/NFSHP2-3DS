// aidriver -- AIDriver, the controller of a racer the AI drives: retail's
// AIDriver.obj, 0x0012ffc8 to 0x001308a0 (the demo's 0x0012e810 on).
//
// SetControlMode builds one for a car under AI_CONTROL. It is an
// AICarController (aicarcontroller.h) with a PsychoDriver (psychodriver.h)
// for its driver, and adds the racer's own choice of action: each think
// AICarController's Think asks the table's ChooseNewAction, which scores
// the actions in turn -- get unstuck, avoid a road block, react to a hit,
// avoid a car, recover from an accident, pass, or just drive -- and makes
// the first that scores no less than the action in hand. Two things are
// the racer's own: a car it has decided not to avoid it leaves alone for a
// second (ShouldWeAvoidThisCar, by the skill's CollisionAvoidanceChance),
// and a five-sample average of its progress, every 1.5 s, keeps a car that
// is stuck off the road in GetUnstuck for at least 1.6 s.
//
// DoSnapshot (0x00130108) is the replay's, since TASKS 72c.
// Written up in docs/formats/ai-driver.md; checked against retail by
// tools/aidriver_check.py.

#ifndef AIDRIVER_H
#define AIDRIVER_H

#include <stddef.h>
#include <stdint.h>

#include "aicarcontroller.h"
#include "average.h"
#include "timer.h"

struct Car;

// 736 bytes: AICarController's 720, then the demo stab's four fields
// (type#1382, which had them at 704 to 716). SetControlMode bMallocs 736
// for AIDriver and for TrafficDriver.
typedef struct AIDriver {
    AICarController  Base;                                  //   0
    struct Car      *CarToPurposefullyNotAvoid;             // 720
    Timer            StartTimeForPurposefullyNotAvoidingCar; // 724
    Timer            VeryStuckProgressTimer;                // 728
    Average         *pVeryStuckProgress;                    // 732
} AIDriver;                                                 // 736

#ifndef AIDRIVER_NO_ASSERT
typedef char aidriver_layout_check[
    (sizeof(void *) != 4
     || (offsetof(AIDriver, CarToPurposefullyNotAvoid) == 720
         && offsetof(AIDriver, StartTimeForPurposefullyNotAvoidingCar) == 724
         && offsetof(AIDriver, VeryStuckProgressTimer) == 728
         && offsetof(AIDriver, pVeryStuckProgress) == 732
         && sizeof(AIDriver) == 736)) ? 1 : -1];
#endif

// _vt$8AIDriver, retail 0x002ae328 (the demo's 0x00291fa8): seventeen
// entries, AICarController's but for the destructor (8), DoSnapshot (24),
// Think (32), GetRouteNumbersToUse (112) and ChooseNewAction (120).
#define AIDRIVER_VTABLE 0x002ae328u

// --------------------------------------------------------- the globals
//
// AIAction.obj's scores and lifetimes, retail .sdata from gp-18268 to
// gp-18152 (AIActionJustDriveScore, gp-18272, is aiaction.h's). Nothing in
// the image writes them. ChooseNewAction reads them; retail lays the scores
// out in another order than the demo's.

extern int32_t AIActionDraftScore;              // gp-18268  200
extern int32_t AIActionPassScore;               // gp-18264  300
extern int32_t AIActionNudgeCarScore;           // gp-18260  300
extern int32_t AIActionBlockScore;              // gp-18256  400
extern int32_t AIActionAvoidCarsScore;          // gp-18252  400
extern int32_t AIActionIJustGotHitScore;        // gp-18248  400
extern int32_t AIActionGetUnstuckScore;         // gp-18244  500
extern int32_t AIActionAccidentRecoveryScore;   // gp-18240  500
extern int32_t AIActionPullOverScore;           // gp-18236  600
extern int32_t AIActionAvoidRoadBlockScore;     // gp-18232  600

extern float AIActionPassLifetime;              // gp-18228  5
extern float AIActionDraftLifetime;             // gp-18224  0
extern float AIActionNudgeCarLifetime;          // gp-18220  5
extern float AIActionJustDriveLifetime;         // gp-18216  0
extern float AIActionBlockLifetime;             // gp-18212  5
extern float AIActionGetUnstuckLifetime;        // gp-18208  5
extern float AIActionPullOverLifetime;          // gp-18204  0
extern float AIActionAvoidCarsLifetime;         // gp-18200  0
extern float AIActionIJustGotHitLifetime;       // gp-18196  0
extern float AIActionAccidentRecoveryLifetime;  // gp-18192  0

// The pull-over's timeouts: a traffic car's (gp-18160, -999), one past the
// finish line (gp-18156, 15), and one stopped by the cops (gp-18152, 3),
// which is the one a forced action of no type of its own gets.
extern float AIActionPullOverTrafficCarTimeout;       // gp-18160
extern float AIActionPullOverCrossFinishLineTimeout;  // gp-18156
extern float AIActionPullOverStoppedByCopsTimeout;    // gp-18152

// AIDriverFrictionBoost (gp-23008, 1.0): the car's friction boost, set by
// the constructor and again each think.
extern float AIDriverFrictionBoost;

// ----------------------------------------------------------- the methods

// 0x0012ffc8. AICarController's constructor; the two Timers zeroed and the
// vptr; a PsychoDriver bMalloc'd (624 bytes, "PsychoDriver", pool 16) and
// built on the car; no current action and no car not to avoid; the driver
// stored; a five-sample Average ("Very Stuck Progress Average", 16 bytes,
// pool 16); VeryStuckProgressTimer 1.5 s; and the car's friction boost
// AIDriverFrictionBoost.
AIDriver *aidriver_init(AIDriver *d, struct Car *car);

// carmodes.h's gAIDriverCtorFn.
CarController *aidriver_construct(void *mem, struct Car *car);

// 0x00130090. The vptr; the driver destroyed through its table (flags 3)
// and the Average (flags 3), each if there is one; then ~AICarController
// with `flags`.
void aidriver_destroy(AIDriver *d, int32_t flags);

// 0x00130188, the table's Think. The friction boost again; every 1.5 s of
// VeryStuckProgressTimer the track's length times the lap's rate goes into
// the Average; then AICarController's Think, called directly.
void aidriver_think(AIDriver *d, float dt);

// 0x00130890. Routes 0 to 49.
void aidriver_get_route_numbers_to_use(AIDriver *d, int32_t *first,
                                       int32_t *last);

// 0x001307b0. Whether to avoid `car`. A car decided against is forgotten
// a second after; until then it is not avoided. Otherwise a draw under my
// skill's CollisionAvoidanceChance (a careful driver's -2 read as 0, and
// no other clamp) avoids it, and any other draw makes it the car not to
// avoid, from now. `secs` is not read.
int aidriver_should_we_avoid_this_car(AIDriver *d, struct Car *car,
                                      float secs);

// 0x00130238. With `type` an action's (not 11): that action, made from its
// score and lifetime globals; a PullOver with PullOverTimeout, which then
// goes back to 1e7; and for any type without its own case, a PullOver with
// AIActionPullOverStoppedByCopsTimeout. With 11: the first of GetUnstuck
// (6 s since the last action that wasn't), AvoidRoadBlock, IJustGotHit,
// AvoidCars, AccidentRecovery, Pass and JustDrive whose CalculateScore is
// 0 or more, skipping an action of the current one's type or whose score
// global is below the current one's score. A hit car or a car to avoid is
// honked at; a car to avoid or pass must also pass ShouldWeAvoidThisCar,
// and its choice becomes the controller's. AvoidCars gets the choice's
// `okay` as its seconds and `usedPreferred` as its okay, as retail passes
// them. Into `*out`; nothing when even JustDrive scores below 0.
void aidriver_choose_new_action(AIDriver *d, AIAction **out,
                                AIActionType type);

// 0x00130108, slot 24, the replay's, an "AIDriver" section: the
// AICarController, the car not to avoid by number, both timers and the
// stuck Average.
struct ReplaySnapshot;
void aidriver_do_snapshot(AIDriver *d, struct ReplaySnapshot *s);

void aidriver_install_vtables(void);

#endif /* AIDRIVER_H */
