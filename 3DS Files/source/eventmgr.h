// eventmgr -- EventManager.obj, retail 0x001ba078 .. 0x001ba898: the
// track's event triggers (LoaderTable slot 7) and the event queue.
//
// A track's bundle holds one event pack (0x80036000): a header (0x36001),
// an AABB tree over the triggers (0x36002) and the triggers (0x36003), 32
// bytes each. A trigger is a sphere with an event id and a parameter.
// Retail's tracks hold two kinds: TRIGGER_EVENT_CAR_ON_FERN, from 5 to 909
// of them a track, whose parameter names a bush (its scenery section in the
// high half, the instance in the low), and TRIGGER_EVENT_VIEW_DRIVING_LINE,
// which shows the training line (the low byte the track direction, the
// next the seconds, the high half the line).
//
// Car::TriggerEvents (carevents.c) asks emTriggerEvents for the triggers
// a point a little ahead of the car is inside. Each one hit becomes an
// emEvent on the queue, and the array that comes back lists them.
// emProcessAllEvents, at the end of World::DoTimestep, hands each queued
// event to the handlers whose StreamMask shares a bit with its id, then
// frees it unless it is locked.
//
// Retail calls emEventManagerInit from InitializeEverything, between
// InitQueuedFiles and eMathInit, and never calls emEventManagerClose.
//
// Prototypes and globals here; the write-up is docs/formats/event-manager.md.
// Cross-check: tools/eventmgr_check.py.

#ifndef EVENTMGR_H
#define EVENTMGR_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bslotpool.h"
#include "bvector.h"
#include "elight.h"

struct Car;

// EVENT_ID, from the .mdebug enum (t259).
typedef uint32_t EVENT_ID;
#define TRIGGER_EVENT_CAR_ON_FERN       0x10003u
#define TRIGGER_EVENT_VIEW_DRIVING_LINE 0x10005u

// The chunk ids.
#define EVENT_MANAGER_ID      0x80036000u
#define EVENT_PACK_HEADER_ID  0x00036001u
#define EVENT_TREE_ID         0x00036002u
#define EVENT_TRIGGERS_ID     0x00036003u

// EventTrigger, 32 bytes (type#240).
typedef struct EventTrigger {
    uint32_t NameHash;                  //  0
    EVENT_ID EventID;                   //  4
    uint32_t Parameter;                 //  8
    uint32_t pad;                       // 12
    float    PositionX;                 // 16
    float    PositionY;                 // 20
    float    PositionZ;                 // 24
    float    Radius;                    // 28
} EventTrigger;

// EventTriggerPack, 24 bytes (type#263): the header chunk's payload. The
// loader fills the two pointers.
typedef struct EventTriggerPack {
    bNode         Node;                 //  0
    int32_t       Version;              //  8  1
    int32_t       NumEventTriggers;     // 12
    vAABBTree    *EventTree;            // 16
    EventTrigger *EventTriggerArray;    // 20
} EventTriggerPack;

// emEvent, 36 bytes (type#284). The queue's links, then what a handler
// reads. A locked event (ReferenceCount not 0) outlives the
// emProcessAllEvents that handles it.
typedef struct emEvent {
    bNode               Node;           //  0  bTNode<emEvent>
    int32_t             ReferenceCount; //  8
    EVENT_ID            ID;             // 12
    const EventTrigger *pEventTrigger;  // 16
    struct Car         *CarPtr;         // 20
    int32_t             Parameter0;     // 24
    int32_t             Parameter1;     // 28
    int32_t             Parameter2;     // 32
} emEvent;

typedef void (*EmHandlerFn)(emEvent *e);

// emEventHandler, 24 bytes (type#501). TotalTime sums the ticker's
// measure of every call; nothing reads it, and emAddHandler leaves it as
// the slot had it.
typedef struct emEventHandler {
    bNode       Node;                   //  0
    EmHandlerFn HandlerFunction;        //  8
    uint32_t    StreamMask;             // 12
    int32_t     ReferenceCount;         // 16
    float       TotalTime;              // 20
} emEventHandler;

// emEventManagerStats, 20 bytes (type#508). emProcessAllEvents frees an
// event without counting it off, and nothing sets PreviousProcessTime or
// EventQueueHighWaterMark.
typedef struct emEventManagerStats {
    int32_t NumEvents;                  //  0
    int32_t NumEventHandlers;           //  4
    float   PreviousProcessTime;        //  8
    int32_t EventQueueHighWaterMark;    // 12
    int32_t EventHandlersHighWaterMark; // 16
} emEventManagerStats;

#if UINTPTR_MAX == 0xffffffffu
typedef char eventmgr_layout_check[
    (sizeof(EventTrigger) == 32 && sizeof(EventTriggerPack) == 24
     && offsetof(EventTriggerPack, EventTree) == 16
     && sizeof(emEvent) == 36 && offsetof(emEvent, pEventTrigger) == 16
     && offsetof(emEvent, CarPtr) == 20
     && sizeof(emEventHandler) == 24
     && sizeof(emEventManagerStats) == 20) ? 1 : -1];
#endif

// The image's globals: gp-18624 .. gp-18580, then 0x00313fb0 and
// 0x00313fc8. The lists start empty, and CurrentEventQueue on the master
// queue. TriggerEventArray is emTriggerEvents' answer: at most 40 events
// and a NULL.
#define EM_MAX_TRIGGERED_EVENTS 40
extern BSlotPool           *EventSlotPool;              // 60 of 36 bytes
extern BSlotPool           *EventHandlerSlotPool;       // 20 of 24 bytes
extern bNode                EmptyEventTriggerPackList;
extern bNode                EventTriggerPackList;
extern bNode                EventHandlerList;
extern bNode                MasterEventQueue;
extern bNode               *CurrentEventQueue;
extern emEvent             *CurrentlyHandlingEvent;
extern emEventManagerStats  EventManagerStats;
extern emEvent             *TriggerEventArray[EM_MAX_TRIGGERED_EVENTS + 1];

// emEventManagerInit, 0x001ba078: the two pools, in pool 16.
void em_event_manager_init(void);

// emEventManagerClose, 0x001ba0c8: each pool deleted if there is one. The
// pointers are left as they were.
void em_event_manager_close(void);

// LoaderEventManager, 0x001ba100. Not the container: 0. Otherwise its
// children in order: the header makes the pack, and a pack whose Version
// is not 1 stops the walk there, unlinked, with 1; the tree (its nodes
// after it) and the triggers go in the pack, once there is one. A pack
// with triggers, a tree and an array goes on EventTriggerPackList's tail,
// one without on EmptyEventTriggerPackList's. 1.
int loader_event_manager(uint8_t *c);

// UnloaderEventManager, 0x001ba248. Not the container: 0. Otherwise a
// header as the first child, of Version 1, takes its pack off its list.
// 1. The image reads only the first child's type and never steps on from
// it: with anything else first it spins for ever. No disc has that; the
// port returns 1.
int unloader_event_manager(uint8_t *c);

// emAddHandler, 0x001ba2d0. 0 for no function or no mask. A function
// already on the list has its count raised, and keeps its mask: 1.
// Otherwise a handler from the pool, NULL being 0, with the mask and a
// count of 1 on the list's tail, counted: 1.
int32_t em_add_handler(EmHandlerFn fn, uint32_t mask);

// emRemoveHandler, 0x001ba3a8. The first handler with that function has
// its count lowered; at 0 it comes off the list, goes back to the pool and
// is counted off.
void em_remove_handler(EmHandlerFn fn);

// emAddEvent, 0x001ba430. An event from the pool, cleared, with the id, on
// CurrentEventQueue's tail, counted. NULL when the pool has none.
emEvent *em_add_event(EVENT_ID id);

// emRemoveEvent, 0x001ba4b8. Not the event being handled; any other off
// its queue, back to the pool and counted off.
void em_remove_event(emEvent *e);

// emLockEvent, 0x001ba500, and emUnlockEvent, 0x001ba510: the count up and
// down. Nothing in the image calls either.
void em_lock_event(emEvent *e);
void em_unlock_event(emEvent *e);

// emProcessAllEvents, 0x001ba520. New events go on a list of their own
// while it runs. Each event on the master queue, in order, the next read
// first: to every handler whose mask shares a bit with the id, the
// ticker's measure of the call added to the handler's TotalTime; then off
// the queue, and back to the pool if its count is 0 (not counted off),
// else on a second list. The second list, then the new events, go back
// on the master queue's tail, which is the queue again.
void em_process_all_events(void);

// emTriggerEvents(bVector3 *), 0x001ba6f8. For each pack on
// EventTriggerPackList, the first leaf of its tree holding the point
// (vAABBTree::QueryLeaf); each trigger the leaf lists whose sphere holds
// the point strictly ((|dx|^2 + |dy|^2) + |dz|^2 < r^2) becomes an event
// with the trigger's id and the trigger. Up to 40, then a NULL after them
// in TriggerEventArray, which comes back; NULL when none. The image
// stores the trigger through a NULL event when the pool runs out (into
// low RAM); the port keeps the NULL in the array and skips the store, and
// the array reads as ending there, as the image's does.
emEvent **em_trigger_events(const bVector3 *p);

#endif
