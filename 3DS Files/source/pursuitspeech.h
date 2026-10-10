// pursuitspeech -- tPursuit's speech (retail 0x0022aa20 .. 0x0022b990):
// what the cops on a chase say, raised on the speech manager
// (speechmgr.h). Each picks the speakers (the chase's or the cop
// manager's queue of four), what the cops can tell of the chased car
// (its name and its paint), and the supervisor's word: a supervisor is
// on the radio while tCopManager's fSupervisorTimer is within 0.001 of 0.
//
// Not ported: 0x0022b990 (the chased car's heading as a direction_t, no
// callers); ChangeChaseTarget's speech (0x0022cb30) is Be A Cop's, 12m.
//
// docs/formats/pursuit-speech.md has the rest; tools/pursuitspeech_check.py
// runs retail's code against this.

#ifndef PURSUITSPEECH_H
#define PURSUITSPEECH_H

#include <stdint.h>

#include "copmanager.h"

struct Car;

// GetExactDescription's "the cops cannot tell": -1.
#define PURSUIT_NO_DESCRIPTION  (-1)

// GetChasedCarColour, 0x0022aa20: the chased car's skin's PaintType
// (GetSkinInfo with the default), racerVehicleColor_t.
int32_t tpursuit_get_chased_car_colour(const tPursuit *p);

// GetExactDescription, 0x0022aa50: a cop car (its type's UsageType 1) is
// 0x10000000; types 15, 16 and 22 are -1, and so are 5, 6, 13, 14, 43
// and 44 in French and German (CurrLanguage 1 or 2); the rest
// Speech::ConvertCarType.
int32_t tpursuit_get_exact_description(const tPursuit *p);

// 0x0022aaf0, the supervisor's test (SupervisorActivate): the car can be
// told and the chase is at LEVEL2 or LEVEL3.
int32_t tpursuit_can_supervisor_initiate(tPursuit *p);

// RaiseBackupSpeech, 0x0022acc0, a player's chase only: backup asked for
// at the landmark, or with none.
void tpursuit_raise_backup_speech(tPursuit *p);

// DeclarePursuitSpeech, 0x0022ad30, with a player involved: a car the
// cops cannot tell gets the general description; otherwise bRandom(40)
// picks: 0 the repeated id, 1-16 the specific, 17-25 the general,
// 26-35 the avoidance and 36-39 no id.
void tpursuit_declare_pursuit_speech(tPursuit *p);

// BeginPursuitCollisionSpeech, 0x0022aef8, with the car the chased car
// hit. Retail's test is the wrong way round: with a landmark the general
// call; without one, the hit and run's, on landmark 0 -- a cop's (and the
// chase at LEVEL2) or the traffic's (and a LEVEL0 chase at LEVEL1).
void tpursuit_begin_pursuit_collision_speech(tPursuit *p, struct Car *hit);

// StartPursuitSpeech, 0x0022afb8, RequestPursuit's for a new chase. In Be
// A Cop the queue is flushed first. An AI car's chase (not in the AI or
// replay demos) gets its description from the manager's current speaker,
// which then moves on. A player's: a recent collision's speech; else with
// tickets, LEVEL1 and "again" 8 times in 10 for a car the cops can tell;
// else over 100 its speed 7 times in 10; else erratic or general. Be A
// Cop's: the description, from the chase's speaker.
void tpursuit_start_pursuit_speech(tPursuit *p);

// JoinPursuitSpeech, 0x0022b288, RequestPursuit's for a cop joining, a
// player's chase only. With no primary speaker one is reserved, who
// reports the suspect found at the landmark, or the car again, or the
// general call. Otherwise once (bAlreadyJoined) past LEVEL0: backup
// confirms, the secondary speaker reserved when there is none and one
// player, else the queue's current one, which moves on.
void tpursuit_join_pursuit_speech(tPursuit *p);

// RoadblockFailedSpeech, 0x0022b3f8, RoadBlockDefeated's, `through` its
// bool: a spike strip's failure (the helicopter's, attacking, one time in
// three), else through or around the roadblock. Then, outside Be A Cop,
// another roadblock asked for.
void tpursuit_roadblock_failed_speech(tPursuit *p, int32_t through);

// RoadBlockSetSpeech, 0x0022b5d0, CreateRoadBlock's: the landmark at the
// roadblock (0 for none), and bRandom(20): a spike strip set, 0-2 with
// no side, else on its side (nSpikeSide 2 the right); a roadblock
// "setting" for 0-2, else "set" at the landmark.
void tpursuit_road_block_set_speech(tPursuit *p);

// CopBackOffSpeech, 0x0022b788: the cop backs off, unless there are no
// cops, or the supervisor's on and three times in four calls it off.
void tpursuit_cop_back_off_speech(tPursuit *p);

// AITicketSpeech, 0x0022b840, CreatePullover's for an AI car (not in the
// AI or replay demos): Be A Cop's speaker, or the queue's current one
// (which moves on); the car stopped with its description, or one time in
// three (and for a car they cannot tell) the radio arrest.
void tpursuit_ai_ticket_speech(tPursuit *p);

// SuperInitiates, 0x0022b908, SupervisorActivate's: the speaker, speed,
// landmark, description and paint to the supervisor.
void tpursuit_super_initiates(tPursuit *p);

#endif
