// playerzone -- see playerzone.h.

#include "playerzone.h"

#include <stddef.h>

#include "bmem.h"
#include "car.h"
#include "player.h"
#include "playerinit.h"
#include "previewroute.h"
#include "track.h"

// The allocation's file name, as retail's bMalloc gives it.
#define PLAYER_CPP "..\\indep\\src\\player.cpp"

// gp-30472 and the lui 0xc45d beside it.
const bVector2 PlayerNoJumpCamPlace = { 1646.0f, -884.0f };

int32_t player_is_jump_cam_available(struct Player *p)
{
    struct Car *car;
    void *mem;

    player_clean_up_jump_cam(p);
    car = p->MyCar;
    if (CurrentTrackInfo->SameAsTrackNumber == PLAYER_NO_JUMP_CAM_TRACK
        && bEqual2((const bVector2 *)&car->State.Position,
                   &PlayerNoJumpCamPlace, PLAYER_NO_JUMP_CAM_RADIUS))
        return 0;
    mem = bMalloc((int)sizeof(PreviewRoute), PLAYER_CPP, 1245, 16);
    p->pJumpCamRoute = preview_route_init((PreviewRoute *)mem, car, 50.0f,
                                          75.0f);
    if (p->pJumpCamRoute->nPoints < 5) {
        player_clean_up_jump_cam(p);
        return 0;
    }
    return 1;
}
