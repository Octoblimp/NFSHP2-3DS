// drivingchoice -- DrivingChoice, which way round the traffic an AI car
// has chosen to go: one of the four driving lines, or one side of a car.
// Retail's DrivingChoice.hpp. Only the record is here so far, for
// DrivingInformation (nearbycar.h); its methods, 0x00241d40 ..
// 0x00245338, are step 11b.
#ifndef DRIVINGCHOICE_H
#define DRIVINGCHOICE_H

#include <stddef.h>
#include <stdint.h>

#include "car.h"

// 17DrivingChoiceType, type#1063, from the .mdebug.
typedef int32_t DrivingChoiceType;
#define CHOICE_NONE               ((DrivingChoiceType)0)
#define CHOICE_DRIVING_LINE_0     ((DrivingChoiceType)1)
#define CHOICE_DRIVING_LINE_1     ((DrivingChoiceType)2)
#define CHOICE_DRIVING_LINE_2     ((DrivingChoiceType)3)
#define CHOICE_DRIVING_LINE_3     ((DrivingChoiceType)4)
#define CHOICE_LEFT_SIDE_OF_CAR   ((DrivingChoiceType)5)
#define CHOICE_RIGHT_SIDE_OF_CAR  ((DrivingChoiceType)6)
#define NUM_DRIVING_CHOICE_TYPES  7

// 12 bytes, type#1071.
typedef struct DrivingChoice {
    DrivingChoiceType Type;                     // 0
    Car              *pCar;                     // 4
    int32_t           UseExtraLateralDistance;  // 8, a bool
} DrivingChoice;                                // 12

#ifndef DRIVINGCHOICE_NO_ASSERT
typedef char drivingchoice_layout_check[
    (offsetof(DrivingChoice, pCar) == sizeof(void *)
     && offsetof(DrivingChoice, UseExtraLateralDistance) == 2 * sizeof(void *)
     && sizeof(DrivingChoice) == 3 * sizeof(void *)) ? 1 : -1];
#endif

#endif /* DRIVINGCHOICE_H */
