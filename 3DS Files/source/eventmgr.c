// eventmgr -- see eventmgr.h.

#include "eventmgr.h"

#include <math.h>
#include <stdint.h>
#include <string.h>

#include "bchunk.h"
#include "bticker.h"

BSlotPool           *EventSlotPool;
BSlotPool           *EventHandlerSlotPool;
bNode                EmptyEventTriggerPackList = { &EmptyEventTriggerPackList,
                                                   &EmptyEventTriggerPackList };
bNode                EventTriggerPackList = { &EventTriggerPackList,
                                              &EventTriggerPackList };
bNode                EventHandlerList = { &EventHandlerList,
                                          &EventHandlerList };
bNode                MasterEventQueue = { &MasterEventQueue,
                                          &MasterEventQueue };
bNode               *CurrentEventQueue = &MasterEventQueue;
emEvent             *CurrentlyHandlingEvent;
emEventManagerStats  EventManagerStats;
emEvent             *TriggerEventArray[EM_MAX_TRIGGERED_EVENTS + 1];

// ------------------------------------------------------------- the lists

static uint8_t *align16(uint8_t *chunk)
{
    return (uint8_t *)(((uintptr_t)chunk + 23u) & ~(uintptr_t)15u);
}

static uint8_t *next_chunk(uint8_t *c)
{
    return c + 8 + bchunk_u32(c + 4);
}

static void add_tail(bNode *list, bNode *n)
{
    bNode *tail = list->prev;

    tail->next = n;
    list->prev = n;
    n->next = list;
    n->prev = tail;
}

static void unlink_node(bNode *n)
{
    n->prev->next = n->next;
    n->next->prev = n->prev;
}

// ------------------------------------------------------------ the module

void em_event_manager_init(void)
{
    EventSlotPool = bNewSlotPool((int)sizeof(emEvent), 60, "EventSlotPool",
                                 16);
    EventHandlerSlotPool = bNewSlotPool((int)sizeof(emEventHandler), 20,
                                        "EventHandlerSlotPool", 16);
}

void em_event_manager_close(void)
{
    if (EventSlotPool != NULL)
        bDeleteSlotPool(EventSlotPool);
    if (EventHandlerSlotPool != NULL)
        bDeleteSlotPool(EventHandlerSlotPool);
}

int loader_event_manager(uint8_t *c)
{
    EventTriggerPack *pack = NULL;
    uint8_t          *end, *g;

    if (bchunk_u32(c) != EVENT_MANAGER_ID)
        return 0;
    end = next_chunk(c);
    for (g = c + 8; g != end; g = next_chunk(g)) {
        uint32_t type = bchunk_u32(g);

        if (type == EVENT_TREE_ID) {
            if (pack != NULL) {
                vAABBTree *tree = (vAABBTree *)align16(g);

                pack->EventTree = tree;
                tree->NodeArray = (vAABB *)(tree + 1);
            }
        } else if (type == EVENT_PACK_HEADER_ID) {
            pack = (EventTriggerPack *)align16(g);
            if (pack->Version != 1)
                return 1;
        } else if (type == EVENT_TRIGGERS_ID) {
            if (pack != NULL)
                pack->EventTriggerArray = (EventTrigger *)align16(g);
        }
    }
    if (pack != NULL) {
        if (pack->NumEventTriggers != 0 && pack->EventTree != NULL
            && pack->EventTriggerArray != NULL)
            add_tail(&EventTriggerPackList, &pack->Node);
        else
            add_tail(&EmptyEventTriggerPackList, &pack->Node);
    }
    return 1;
}

int unloader_event_manager(uint8_t *c)
{
    uint8_t *g = c + 8;

    if (bchunk_u32(c) != EVENT_MANAGER_ID)
        return 0;
    if (g != next_chunk(c) && bchunk_u32(g) == EVENT_PACK_HEADER_ID) {
        EventTriggerPack *pack = (EventTriggerPack *)align16(g);

        if (pack->Version == 1)
            unlink_node(&pack->Node);
    }
    return 1;
}

int32_t em_add_handler(EmHandlerFn fn, uint32_t mask)
{
    emEventHandler *h;
    bNode          *n;

    if (fn == NULL || mask == 0)
        return 0;
    for (n = EventHandlerList.next; n != &EventHandlerList; n = n->next) {
        h = (emEventHandler *)n;
        if (h->HandlerFunction == fn) {
            h->ReferenceCount++;
            return 1;
        }
    }
    h = (emEventHandler *)bSlotOMalloc(EventHandlerSlotPool);
    if (h == NULL)
        return 0;
    h->StreamMask = mask;
    h->ReferenceCount = 1;
    add_tail(&EventHandlerList, &h->Node);
    h->HandlerFunction = fn;
    EventManagerStats.NumEventHandlers++;
    if (EventManagerStats.EventHandlersHighWaterMark
        < EventManagerStats.NumEventHandlers)
        EventManagerStats.EventHandlersHighWaterMark =
            EventManagerStats.NumEventHandlers;
    return 1;
}

void em_remove_handler(EmHandlerFn fn)
{
    bNode *n;

    for (n = EventHandlerList.next; n != &EventHandlerList; n = n->next) {
        emEventHandler *h = (emEventHandler *)n;

        if (h->HandlerFunction == fn) {
            if (--h->ReferenceCount == 0) {
                unlink_node(n);
                bSlotFree(EventHandlerSlotPool, h);
                EventManagerStats.NumEventHandlers--;
            }
            return;
        }
    }
}

emEvent *em_add_event(EVENT_ID id)
{
    emEvent *e = (emEvent *)bSlotOMalloc(EventSlotPool);

    if (e == NULL)
        return NULL;
    memset(e, 0, sizeof *e);
    e->ID = id;
    e->ReferenceCount = 0;
    add_tail(CurrentEventQueue, &e->Node);
    EventManagerStats.NumEvents++;
    return e;
}

void em_remove_event(emEvent *e)
{
    if (e == CurrentlyHandlingEvent)
        return;
    unlink_node(&e->Node);
    bSlotFree(EventSlotPool, e);
    EventManagerStats.NumEvents--;
}

void em_lock_event(emEvent *e)
{
    e->ReferenceCount++;
}

void em_unlock_event(emEvent *e)
{
    e->ReferenceCount--;
}

// The image's two bTList<emEvent> on the stack, and their destructors at
// the end, which find them empty.
static void move_all(bNode *from)
{
    while (from->next != from) {
        bNode *n = from->next;

        unlink_node(n);
        add_tail(&MasterEventQueue, n);
    }
}

void em_process_all_events(void)
{
    bNode  added, locked;
    bNode *n, *next;

    added.next = added.prev = &added;
    locked.next = locked.prev = &locked;
    CurrentEventQueue = &added;
    for (n = MasterEventQueue.next; n != &MasterEventQueue; n = next) {
        emEvent  *e = (emEvent *)n;
        EVENT_ID  id = e->ID;
        bNode    *hn;

        next = n->next;
        CurrentlyHandlingEvent = e;
        for (hn = EventHandlerList.next; hn != &EventHandlerList;
             hn = hn->next) {
            emEventHandler *h = (emEventHandler *)hn;

            if ((id & h->StreamMask) != 0) {
                uint32_t t0 = bGetTicker();

                h->HandlerFunction(e);
                h->TotalTime += bGetTickerDifference(t0, bGetTicker());
            }
        }
        unlink_node(n);
        CurrentlyHandlingEvent = NULL;
        if (e->ReferenceCount == 0)
            bSlotFree(EventSlotPool, e);
        else
            add_tail(&locked, n);
    }
    move_all(&locked);
    move_all(&added);
    CurrentEventQueue = &MasterEventQueue;
}

emEvent **em_trigger_events(const bVector3 *p)
{
    emEvent **out = TriggerEventArray;
    emEvent **limit = &TriggerEventArray[EM_MAX_TRIGGERED_EVENTS];
    float     x = p->x, y = p->y, z = p->z;
    bNode    *n;

    for (n = EventTriggerPackList.next;
         n != &EventTriggerPackList && out < limit; n = n->next) {
        EventTriggerPack *pack = (EventTriggerPack *)n;
        vAABB            *leaf = vaabbtree_query_leaf(pack->EventTree,
                                                      x, y, z);
        int32_t           count, i;

        if (leaf == NULL)
            continue;
        count = -leaf->NumChildren;
        for (i = 0; i < count && out < limit; i++) {
            const EventTrigger *t =
                &pack->EventTriggerArray[leaf->ChildrenIndicies[i]];
            float dx = fabsf(x - t->PositionX);
            float dy = fabsf(y - t->PositionY);
            float dz = fabsf(z - t->PositionZ);

            if ((dx * dx + dy * dy) + dz * dz < t->Radius * t->Radius) {
                emEvent *e = em_add_event(t->EventID);

                *out++ = e;
                if (e != NULL)
                    e->pEventTrigger = t;
            }
        }
    }
    if (out == TriggerEventArray)
        return NULL;
    *out = NULL;
    return TriggerEventArray;
}
