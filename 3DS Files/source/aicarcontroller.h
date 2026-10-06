// aicarcontroller -- AICarController, the controller of a car the AI
// drives, and the AIAction it is carrying out: retail's
// AICarController.hpp and AIAction.hpp, as far as step 11 has needed
// them.
//
// Only the record's head is here so far, for DrivingChoice (step 11b),
// which reads and writes the controller of the car it is choosing for and
// of the cars it is choosing around: the location and choice the
// controller drives by, the car it leaves out of the collision prediction,
// and the type of its current action. The methods, and the record from
// LastRoutePointLookaheadSwitch on, are step 11e's. AIAction is in
// aiaction.h (11c).
//
// The offsets are retail's, which agree with the demo's stab (type#1344,
// 704 bytes) up to pDeltaLineSpeed at 676 (retail 692, docs/retail_layout
// .txt): retail's record is 720 bytes.
#ifndef AICARCONTROLLER_H
#define AICARCONTROLLER_H

#include <stddef.h>
#include <stdint.h>

#include "aiaction.h"
#include "car.h"
#include "carcontroller.h"
#include "nearbycar.h"

// The head of retail's 720 bytes. Offsets are the console's; the asserts
// allow for a host's wider pointers as carcontroller.h's do.
typedef struct AICarController {
    CarController       Base;                               //   0
    DrivingInformation  MyCurrentDrivingInformation;        //  12
    DrivingLocation    *CurrentDrivingLocation;             // 504
    DrivingChoice      *CurrentDrivingChoice;               // 508
    NearbyCarList      *CurrentNearbyCarList;               // 512
    Car                *CarToExcludeFromCollisionPrediction;// 516
    int8_t              LastTrackRouteNumber;               // 520
    float               SecondsBeforeNextActionEvaluation;  // 524
    AIActionType        ForceCurrentAction;                 // 528
    AIAction           *CurrentAction;                      // 532
    // LastRoutePointLookaheadSwitch (536) to vPreviousLinePoint (704,
    // retail's 720 in all) are step 11e's.
} AICarController;

#ifndef AICARCONTROLLER_NO_ASSERT
typedef char aicarcontroller_layout_check[
    (sizeof(void *) != 4
     || (offsetof(AICarController, MyCurrentDrivingInformation) == 12
         && offsetof(AICarController, CurrentDrivingLocation) == 504
         && offsetof(AICarController, CurrentDrivingChoice) == 508
         && offsetof(AICarController, CurrentNearbyCarList) == 512
         && offsetof(AICarController,
                     CarToExcludeFromCollisionPrediction) == 516
         && offsetof(AICarController, LastTrackRouteNumber) == 520
         && offsetof(AICarController,
                     SecondsBeforeNextActionEvaluation) == 524
         && offsetof(AICarController, ForceCurrentAction) == 528
         && offsetof(AICarController, CurrentAction) == 532)) ? 1 : -1];
#endif

// A car's controller as an AI one. Only for a car under AI control:
// nothing checks.
static inline AICarController *car_ai_controller(Car *c)
{
    return (AICarController *)(void *)c->pCarController;
}

#endif /* AICARCONTROLLER_H */
