// What copmgr.c calls besides LoaderCops, for tools/loadertable_check.py.
// The table's slot 15 is copmgr.c's loader and unloader, and the file
// links whole; nothing the check runs reaches past the cop container's
// walk, so each of these exits if it is ever called. The same for
// soundscape.c, slot 21's: its loader reads records and calls nothing,
// and its unloader deletes only samples an update made. eventtree.c,
// slot 24's, deals its trees' state out of Fred and reads the rest only
// for the questions the check never asks.

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "airoute.h"
#include "bsound.h"
#include "car.h"
#include "carinit.h"
#include "collision.h"
#include "collisionbody.h"
#include "configitems.h"
#include "coputil.h"
#include "drivetarget.h"
#include "drivetargetrenderer.h"
#include "fred.h"
#include "raceinit.h"
#include "raceparams.h"
#include "racesplit.h"
#include "realdriver.h"
#include "sound.h"
#include "sound3d.h"
#include "trackgraph.h"
#include "trackmap.h"
#include "world.h"

World              *pCurrentWorld;
tTrackGraph        *TheTrackGraph;
DriveTargetRenderer TheDriveTargetRenderer;
float               SkipFETimeUntilCopsAppear = 1.0f;
int32_t             CameraFollowThisCarInstead = -1;
FrontendDatabase    Fred;
const char       *(*gFredTranslateFn)(int32_t id);
EggIsOnFn           gEggIsOnFn;
int32_t             bVersionE3;

static void unreached(const char *f)
{
    fprintf(stderr, "loadertable_test: %s reached\n", f);
    exit(3);
}

void drivetarget_clear(DriveTarget *t, Car *car, float speed)
{
    (void)t, (void)car, (void)speed;
    unreached("drivetarget_clear");
}

void drivetarget_add_point3(DriveTarget *t, const bVector3 *p, int8_t route,
                            int16_t rpn, int8_t dl, int check, Car *car)
{
    (void)t, (void)p, (void)route, (void)rpn, (void)dl, (void)check;
    (void)car;
    unreached("drivetarget_add_point3");
}

void drivetargetrenderer_set_target_to_render(DriveTargetRenderer *r,
                                              DriveTarget *t)
{
    (void)r, (void)t;
    unreached("drivetargetrenderer_set_target_to_render");
}

void car_set_movement_mode(Car *c, MovementMode mode)
{
    (void)c, (void)mode;
    unreached("car_set_movement_mode");
}

void car_set_control_mode(Car *c, ControlMode mode)
{
    (void)c, (void)mode;
    unreached("car_set_control_mode");
}

TrackRoute *car_get_route(Car *c, int find)
{
    (void)c, (void)find;
    unreached("car_get_route");
    return NULL;
}

TrackRoutePoint *car_get_route_point(Car *c, int find)
{
    (void)c, (void)find;
    unreached("car_get_route_point");
    return NULL;
}

void car_reset_to_position(Car *c, const bVector3 *pos, float speed,
                           uint16_t angle)
{
    (void)c, (void)pos, (void)speed, (void)angle;
    unreached("car_reset_to_position");
}

Car *car_construct(Car *c, DriverInfo *driver, const bVector3 *pos,
                   uint16_t angle, float dist)
{
    (void)c, (void)driver, (void)pos, (void)angle, (void)dist;
    unreached("car_construct");
    return NULL;
}

float world_get_distance_to_closest_player_2d(const World *w,
                                              const bVector2 *p)
{
    (void)w, (void)p;
    unreached("world_get_distance_to_closest_player_2d");
    return 0.0f;
}

int32_t world_random_i(World *w, int32_t range)
{
    (void)w, (void)range;
    unreached("world_random_i");
    return 0;
}

float world_random_f(World *w, float f)
{
    (void)w, (void)f;
    unreached("world_random_f");
    return 0.0f;
}

int ai_get_nearest_route_point(NearestRoutePointInfo *info,
                               const bVector2 *pos, RoutesToSearch which,
                               int flags, float distanceAround)
{
    (void)info, (void)pos, (void)which, (void)flags, (void)distanceAround;
    unreached("ai_get_nearest_route_point");
    return 0;
}

void ai_get_next_route_point(NearestRoutePointInfo *info)
{
    (void)info;
    unreached("ai_get_next_route_point");
}

int32_t did_these_cars_collide(struct Car *a, struct Car *b)
{
    (void)a, (void)b;
    unreached("did_these_cars_collide");
    return 0;
}

struct Car *car_caused_recent_collision(struct Car *car)
{
    (void)car;
    unreached("car_caused_recent_collision");
    return NULL;
}

int32_t can_teleport(struct Car *car, const bVector2 *dest)
{
    (void)car, (void)dest;
    unreached("can_teleport");
    return 0;
}

int32_t is_teleport_location_clear(const bVector2 *p)
{
    (void)p;
    unreached("is_teleport_location_clear");
    return 0;
}

int32_t is_point_in_poly(const bVector2 *p, const bVector2 *poly, int32_t n)
{
    (void)p, (void)poly, (void)n;
    unreached("is_point_in_poly");
    return 0;
}

void trackgraph_uncloak_all_edges(tTrackGraph *g)
{
    (void)g;
    unreached("trackgraph_uncloak_all_edges");
}

struct tSpeedTrap *trackgraph_find_speed_trap(tTrackGraph *g,
                                              struct Car *car, float fMin,
                                              float fMax, int32_t forward)
{
    (void)g, (void)car, (void)fMin, (void)fMax, (void)forward;
    unreached("trackgraph_find_speed_trap");
    return NULL;
}

void realdriver_force_ebrake_stop(RealDriver *d, float t)
{
    (void)d, (void)t;
    unreached("realdriver_force_ebrake_stop");
}

int32_t race_parameters_is_free_run(const RaceParameters *rp)
{
    (void)rp;
    unreached("race_parameters_is_free_run");
    return 0;
}

void race_calculate_split_time(Race *r, Timer *out, struct RacingCar *a,
                               struct RacingCar *b)
{
    (void)r, (void)out, (void)a, (void)b;
    unreached("race_calculate_split_time");
}

int32_t config_skip_fe(void)
{
    unreached("config_skip_fe");
    return 0;
}

struct Collision *collisionbody_get_collision(CollisionBody *b, int32_t i)
{
    (void)b, (void)i;
    unreached("collisionbody_get_collision");
    return NULL;
}

void collisionbody_enable_collisions(CollisionBody *b)
{
    (void)b;
    unreached("collisionbody_enable_collisions");
}

void collisionbody_disable_collisions(CollisionBody *b)
{
    (void)b;
    unreached("collisionbody_disable_collisions");
}

int32_t collision_is_two_car_collision(Collision *c)
{
    (void)c;
    unreached("collision_is_two_car_collision");
    return 0;
}

// ---------------------------------------------------------- soundscape.c

int32_t SoundEnabled = 1;

BSound *bsound_get(void)
{
    unreached("bsound_get");
    return NULL;
}

BRegion *bsound_region(const BSound *s, const char *name)
{
    (void)s, (void)name;
    unreached("bsound_region");
    return NULL;
}

BSample *bregion_sample(const BRegion *r, const char *name)
{
    (void)r, (void)name;
    unreached("bregion_sample");
    return NULL;
}

void bsample_construct(BSample *s, int8_t type)
{
    (void)s, (void)type;
    unreached("bsample_construct");
}

BSample *bsample_new(int8_t type)
{
    (void)type;
    unreached("bsample_new");
    return NULL;
}

void bsample_delete(BSample *s)
{
    (void)s;
    unreached("bsample_delete");
}

void bsample_initialize_copy(BSample *s, const BSample *other)
{
    (void)s, (void)other;
    unreached("bsample_initialize_copy");
}

void bsample_set_category(BSample *s, uint32_t category)
{
    (void)s, (void)category;
    unreached("bsample_set_category");
}

int32_t bsample_set_pitch(BSample *s, float pitch)
{
    (void)s, (void)pitch;
    unreached("bsample_set_pitch");
    return 0;
}

void bsample_set_volume(BSample *s, float volume)
{
    (void)s, (void)volume;
    unreached("bsample_set_volume");
}

void bsample_set_azimuth(BSample *s, uint16_t azimuth)
{
    (void)s, (void)azimuth;
    unreached("bsample_set_azimuth");
}

float bsample_get_volume(const BSample *s)
{
    (void)s;
    unreached("bsample_get_volume");
    return 0.0f;
}

BVoice *bsample_play(BSample *s, float volume, float pan, float pitch)
{
    (void)s, (void)volume, (void)pan, (void)pitch;
    unreached("bsample_play");
    return NULL;
}

bool bsample_is_playing(const BSample *s)
{
    (void)s;
    unreached("bsample_is_playing");
    return false;
}

void bsample_pause(BSample *s, bool pause)
{
    (void)s, (void)pause;
    unreached("bsample_pause");
}

void bsample_stop(BSample *s)
{
    (void)s;
    unreached("bsample_stop");
}

void bsample_mute(BSample *s, bool mute)
{
    (void)s, (void)mute;
    unreached("bsample_mute");
}

void bsample_fade(BSample *s, float volume, uint32_t ms)
{
    (void)s, (void)volume, (void)ms;
    unreached("bsample_fade");
}

SoundModule *sound_get(void)
{
    unreached("sound_get");
    return NULL;
}

int32_t sound_random_int(SoundModule *m, int32_t range)
{
    (void)m, (void)range;
    unreached("sound_random_int");
    return 0;
}

float sound_random_float(SoundModule *m, float range)
{
    (void)m, (void)range;
    unreached("sound_random_float");
    return 0.0f;
}

struct Camera **get_active_cameras(void)
{
    unreached("get_active_cameras");
    return NULL;
}

void basecarsound_scale_road_noise(BaseCarSound *s, float f)
{
    (void)s, (void)f;
    unreached("basecarsound_scale_road_noise");
}
