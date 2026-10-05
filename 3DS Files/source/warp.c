// warp -- a test run's start somewhere else on the track. See warp.h.

#include "warp.h"

#include <stdint.h>
#include <stdio.h>

#include <3ds.h>

#include "car.h"
#include "hangwatch.h"
#include "player.h"

static bool     s_racing;
static bool     s_armed;
static u64      s_start;
static float    s_seconds;
static bVector3 s_pos;
static unsigned s_angle;
static float    s_speed;

void warp_race(bool racing)
{
    FILE*  f;
    Car*   c;
    int    n;

    if (racing != s_racing) {
        s_racing = racing;
        s_armed  = false;
        if (!racing) {
            return;
        }
        f = fopen(WARP_FLAG, "r");
        if (f == NULL) {
            return;
        }
        n = fscanf(f, "%f %f %f %f %u %f", &s_seconds, &s_pos.x, &s_pos.y,
                   &s_pos.z, &s_angle, &s_speed);
        fclose(f);
        if (n != 6) {
            hangwatch_log("warp: %s has %d of its 6 numbers", WARP_FLAG, n);
            return;
        }
        s_pos.pad = 0.0f;
        s_armed   = true;
        s_start   = osGetTime();
        hangwatch_log("warp: armed, %.1f s in, to %.1f %.1f %.1f angle %u "
                      "speed %.1f", (double)s_seconds, (double)s_pos.x,
                      (double)s_pos.y, (double)s_pos.z, s_angle,
                      (double)s_speed);
    }
    if (!s_armed || (float)(osGetTime() - s_start) < s_seconds * 1000.0f) {
        return;
    }
    s_armed = false;
    if (PlayerNumPlayers < 1 || PlayerPlayersByIndex[0] == NULL
        || PlayerPlayersByIndex[0]->MyCar == NULL) {
        hangwatch_log("warp: no car");
        return;
    }
    c = PlayerPlayersByIndex[0]->MyCar;
    car_reset_to_position(c, &s_pos, s_speed, (uint16_t)s_angle);
    hangwatch_log("warp: car 0 to %.1f %.1f %.1f", (double)c->State.Position.x,
                  (double)c->State.Position.y, (double)c->State.Position.z);
}
