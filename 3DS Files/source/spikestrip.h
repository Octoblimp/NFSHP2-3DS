// spikestrip -- the spike strips: tSpikeStrip and its belt pieces,
// retail's 0x00241308 .. 0x00241ae0, and the two tCopManager methods that
// lay them and watch them, AddSpikeStrip (0x002276d0) and MonitorSpikeBelts
// (0x00227758), which are copmgr.obj's but live here with what they drive.
//
// A roadblock with spikes (pursuit.c's CreateRoadBlock) calls AddSpikeStrip
// with the belt's two ends, its roadblock and how long it lasts. The strip
// lays up to twenty pieces of SPIKEBELT_00 along the road between the ends,
// each a WorldObject on WorldObjectList, and the manager's Think runs
// MonitorSpikeBelts each frame: the strip counts its life down and blinks
// out for two seconds when it ends, and a car near the strip whose wheels
// cross it this frame has those tires blown. A racer is then pulled over
// (CreatePullover, 12l), an AI racer slowed, and a player's camera given
// the short slow-motion zone; in Be A Cop the player scores, or is
// penalised for driving over the strip.
//
// copmanager.h has both layouts. The pieces are drawn with the other world
// objects, which is the renderer's (12j-2b). The default constructor
// (0x00241308) and DoSnapshot (0x00241898) are the replay's, and
// DroppedSpikes::MakeSpikeBelt (0x001bf188), AddSpikeStrip's other caller,
// is not reached.

#ifndef SPIKESTRIP_H
#define SPIKESTRIP_H

#include <stdint.h>

#include "bvector.h"
#include "copmanager.h"

// tSpikeStripRenderElement::tSpikeStripRenderElement, 0x002419f8:
// WorldObject(bStringHash("SPIKEBELT_00"), NULL, 0) -- so not Enabled, its
// matrix left as it was -- and the table.
tSpikeStripRenderElement *
tspikestriprenderelement_construct(tSpikeStripRenderElement *e);

// _$_24tSpikeStripRenderElement, 0x00241a48: the table, WorldObject's
// destructor with 0, and with bit 0 of `flags` the slot back to
// WorldObjectSlotPool (__dl__11WorldObject). The strip passes 0.
void tspikestriprenderelement_destruct(tSpikeStripRenderElement *e,
                                       int32_t flags);

// tSpikeStrip::tSpikeStrip(bVector2 const &, bVector2 const &, int, float),
// 0x00241378: the table, the twenty pieces built in order, then Init.
tSpikeStrip *tspikestrip_construct(tSpikeStrip *s, const bVector2 *a,
                                   const bVector2 *b, int32_t id,
                                   float lifetime);

// tSpikeStrip::Init, 0x002414e8. The id, the ends and the lifetime are
// stored, and each end put on the road (GetVectorOnTrack of the stored
// ends). The pieces run from 0.65 past the start towards the end, 0.65
// apart, one for each 0.65 of the length (`cvt.w.s` of the length x
// 0x3fc4ec4f, 20 / 13), at most twenty. Each enabled piece's matrix has
// rows the unit direction, up x direction normalised, and direction x
// that, all with w 0, and the point with w 1. bIsBlinking and fBlinkTimer
// are left as they were, and so are the pieces past the count.
void tspikestrip_init(tSpikeStrip *s, const bVector2 *a, const bVector2 *b,
                      int32_t id, float lifetime);

// tSpikeStrip::Update, 0x002417b8, nonzero when the strip is done. While
// blinking, fBlinkTimer counts down by WorldTimeElapsed, each piece below
// the count is turned on or off, and the strip is done once the timer is at
// or below 0. Otherwise a lifetime above 0 counts down, and the blink
// starts when it reaches 0 or below; the strip is not done.
int32_t tspikestrip_update(tSpikeStrip *s);

// tSpikeStrip::BlinkBlinkPoof, 0x00241880: bIsBlinking 1, fBlinkTimer 2.
void tspikestrip_blink_blink_poof(tSpikeStrip *s);

// _$_11tSpikeStrip, 0x00241430: the table, all twenty pieces' destructors
// through their tables with 0, last first, and with bit 0 of `flags` the
// slot back to SpikeStripSlotPool (__dl__11tSpikeStrip, 0x00241ad0).
void tspikestrip_destruct(tSpikeStrip *s, int32_t flags);

// tCopManager::AddSpikeStrip, 0x002276d0: a strip from SpikeStripSlotPool,
// built, at the head of SpikeStripList. The seam
// gCopManagerAddSpikeStripFn.
void copmanager_add_spike_strip(tCopManager *m, const bVector2 *a,
                                const bVector2 *b, int32_t id, float t);

// tCopManager::MonitorSpikeBelts, 0x00227758, the seam
// gCopManagerMonitorSpikeBeltsFn; pCurrentWorld's TotalNumCars is read
// once, first. Each strip is updated, and one that is done comes off the
// list and is destroyed with 3. For each other, each car of the world
// table within 250 of a player (World::GetDistanceToClosestPlayer's
// two-dimensional form), not blinking and within 40 of the strip's middle:
// each wheel on the ground whose point (WheelMatrix x the body's matrix
// and position, row 3) moves across the strip this frame (the velocity x
// WorldTimeElapsed, DoSegmentsIntersect) adds its bit. Unless the car's
// BlownTireBits hold all of those, the tires are blown
// (Car::TriggerTireBlowOut), and if the car had none blown before:
//   - an AI racer, outside Be A Cop, is forced to pull over within 3
//     seconds and its controller's ForceBoost given 0.4; in Be A Cop,
//     ForceBoost by the difficulty, 0.3, 0.4 or 0.5;
//   - another car with a player, above 20 forward, requests the short
//     slow-motion zone (4, unforced, with the sound, muffled);
//   - in Be A Cop: the player's own car is pulled over (CreatePullover)
//     and scores BLEW YOUR TIRES, and a racer being chased scores the
//     player BLEW THE TIRES;
//   - else a player's car or an AI racer not being chased is pulled over.
// CreatePullover is pursuit.h's seam, nothing while NULL (12l).
void copmanager_monitor_spike_belts(tCopManager *m);

// The two tables, 0x002be688 and 0x002be698, registered with vtable.c.
void spikestrip_install_vtables(void);

struct ReplaySnapshot;

// tSpikeStrip::DoSnapshot, 0x00241898 (copsnap.c), a section named
// "tSpikeStrip": the two ends, the roadblock (4 bytes) and the lifetime; a
// restore lays the strip again with Init; then bIsBlinking (a bool) and
// fBlinkTimer.
void tspikestrip_do_snapshot(tSpikeStrip *t, struct ReplaySnapshot *s);

#endif
