// chopperfire -- the helicopter's salvos (retail 0x001ea8c0 ..), 12k-6's.
//
// FireSalvo turns each of the run's munitions out by its spread
// (RotateVector, World::Random) and launches it (0x001eab70), which
// registers a replay event. Until 12k-6 ports them the helicopter fires
// nothing; BombRunLogic (12k-3b) still counts its salvos.

#include "chopper.h"

// 0x001ea8c0.
void chopper_fire_salvo(struct Chopper *h)
{
    (void)h;
}
