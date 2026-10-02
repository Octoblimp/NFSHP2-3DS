// player -- see player.h.

#include "player.h"

#include <stddef.h>

#include "cammover.h"

int32_t        PlayerNumPlayers;          // gp-20920
struct Player *PlayerPlayersByNumber[2];  // gp-20936
struct Player *PlayerPlayersByIndex[2];   // gp-20928

// The mover is read again after GetCameraInfo, as the image does.
int32_t player_is_camera_pov_in_car(const struct Player *p)
{
    CameraMover *m = p->pCameraMover;
    const POV *pov;

    if (m == NULL || m->Type != CM_DRIVE)
        return 0;
    if (m->vtbl->GetCameraInfo(m) == NULL)
        return 0;
    m = p->pCameraMover;
    if (!m->Enabled)
        return 0;
    pov = m->vtbl->GetPOV(m, p->PlayerSettings.DriveCameraPOVIndex);
    return pov != NULL && pov->Type == POV_INCAR;
}
