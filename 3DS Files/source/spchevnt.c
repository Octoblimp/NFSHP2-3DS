// spchevnt -- spchevnt.o of SPP2A380.A: the event dats' lookups, the
// event queue, the event choice and Play. See spch.h.

#include <stdarg.h>

#include "spchi.h"

// ---- the event dats

// The event `id` among the dat's events, or NULL.
const uint8_t *spchi_search_event_dat(const uint8_t *dat, uint32_t id)
{
    uint32_t n = spch_u16(dat + 16), k;

    for (k = 0; k < n; k++) {
        const uint8_t *ev = dat + spch_u16(dat + 24 + 2 * k) * 4;

        if (spch_u16(ev) == id)
            return ev;
    }
    return NULL;
}

// The dat an event word names: its third byte is the dat's byte 9, its
// fourth the dat's byte 8.
int32_t spchi_find_event_dat_info(const uint8_t *req, SpchEventDat **out)
{
    int32_t i;

    for (i = 0; i < SPCH_EVENT_DATS; i++) {
        const uint8_t *d = gSpch.eventDats[i].dat;

        if (d != NULL && d[9] == req[2] && d[8] == req[3]) {
            *out = &gSpch.eventDats[i];
            return 1;
        }
    }
    return 0;
}

const uint8_t *spchi_find_event(const uint8_t *req)
{
    SpchEventDat *e;

    if (!spchi_find_event_dat_info(req, &e))
        return NULL;
    return spchi_search_event_dat(e->dat, spch_u16(req));
}

int32_t spchi_find_event_channel(const uint8_t *req, int32_t *out)
{
    SpchEventDat *e;

    if (!spchi_find_event_dat_info(req, &e))
        return 0;
    *out = (int32_t)e->channel;
    return 1;
}

int32_t spchi_get_dat_id(const uint8_t *req, int32_t *out)
{
    SpchEventDat *e;

    if (!spchi_find_event_dat_info(req, &e))
        return 0;
    *out = e->dat[9];
    return 1;
}

void spchi_init_event_dat(void)
{
    int32_t i;

    for (i = 0; i < SPCH_EVENT_DATS; i++) {
        gSpch.eventDats[i].dat = NULL;
        gSpch.eventDats[i].channel = 0;
    }
}

int32_t spchi_get_filter_length(const uint8_t *req)
{
    SpchEventDat *e;

    if (!spchi_find_event_dat_info(req, &e))
        return 0;
    return spch_u16(e->dat + 20);
}

// ---- the queue

void spchi_init_event_queue(void)
{
    SpchQueue *q = &gSpch.queue;
    int32_t i, k;

    for (i = 0; i < SPCH_CHANNELS; i++) {
        q->numPending[i] = 0;
        q->lastAdded[i] = -1;
        q->lastHead[i] = -1;
    }
    q->bumpFilter = 0;
    // isAppend and next are left as they are.
    for (i = 0; i < SPCH_SLOTS; i++) {
        SpchSlot *s = &q->slot[i];

        s->active = 0;
        s->tick = 0;
        s->ev = NULL;
        s->channel = 255;
        s->subTick = 0;
        for (k = 0; k < SPCH_EVENT_PARMS; k++)
            s->parms[k] = 0;
    }
    gSpch.lastTick = 0;
    gSpch.lastSubTick = 0;
}

// A slot for a new event: a free one, else one whose event has lived
// out its life, else the first on the channel of no higher priority. An
// append event may not take its own start's.
int32_t spchi_find_event_slot(uint32_t pri, int32_t channel, int32_t append)
{
    SpchQueue *q = &gSpch.queue;
    int32_t i, start = -1;
    uint32_t now;

    for (i = 0; i < SPCH_SLOTS; i++)
        if (!q->slot[i].active)
            return i;
    if (append)
        start = q->lastHead[channel];
    now = spchi_gettick();
    for (i = 0; i < SPCH_SLOTS; i++) {
        const SpchSlot *s = &q->slot[i];
        uint32_t life = spch_u16(s->ev + 2);

        if (s->isAppend == 0 && life != 0 && life < now - s->tick
            && i != start) {
            spchi_clear_event(i);
            return i;
        }
    }
    for (i = 0; i < SPCH_SLOTS; i++) {
        SpchSlot *s = &q->slot[i];

        if (s->isAppend == 0 && pri >= spch_u16(s->ev + 4)
            && s->channel == channel && i != start) {
            s->active = 0;
            q->numPending[s->channel]--;
            return i;
        }
    }
    return -1;
}

int32_t spchi_check_last_event_index(int32_t channel)
{
    return (uint32_t)gSpch.queue.lastHead[channel] < SPCH_SLOTS
        && (uint32_t)gSpch.queue.lastAdded[channel] < SPCH_SLOTS;
}

int32_t spch_add_event(const uint32_t *parms)
{
    SpchQueue *q = &gSpch.queue;
    uint8_t word[4];
    const uint8_t *ev;
    int32_t ch, app, head = -1, last = -1, k, i;
    uint32_t pri, t;
    SpchSlot *s;

    if (gSpch.addEventStatus) {
        spchi_abort("Tried to re-enter SPCH_AddEvent");
        gSpch.addEventStatus = 0;
        return 0;
    }
    gSpch.addEventStatus = 1;
    memcpy(word, parms, 4);
    ev = spchi_find_event(word);
    if (ev == NULL || !spchi_find_event_channel(word, &ch)) {
        gSpch.addEventStatus = 0;
        return 0;
    }
    app = (ev[10] >> 5) & 1;
    if (app) {
        if (!spchi_check_last_event_index(ch)) {
            spchi_abort("SPCH_AddEvent - adding append event but last event invalid.\n");
            gSpch.addEventStatus = 0;
            return 0;
        }
        head = q->lastHead[ch];
        last = q->lastAdded[ch];
        pri = spch_u16(q->slot[head].ev + 4);
    } else {
        if ((int8_t)ev[9] < spchi_rand(100, -1)) {
            gSpch.addEventStatus = 0;
            return 0;
        }
        pri = spch_u16(ev + 4);
    }
    k = spchi_find_event_slot(pri, ch, app);
    if (k < 0) {
        if (app) {
            spchi_clear_event(head);
            spchi_abort("SPCH_AddEvent - no space for append event.  Start event removed\n");
        } else {
            spchi_abort("SPCH_AddEvent - iSPCH_FindEventSlot failed\n");
        }
        gSpch.addEventStatus = 0;
        return 0;
    }
    t = spchi_gettick();
    if (t == gSpch.lastTick)
        gSpch.lastSubTick++;
    else
        gSpch.lastSubTick = 0;
    gSpch.lastTick = t;
    s = &q->slot[k];
    s->ev = ev;
    s->channel = (uint8_t)ch;
    s->tick = t;
    s->next = -1;
    s->subTick = gSpch.lastSubTick;
    s->isAppend = (int16_t)app;
    if (app)
        q->slot[last].next = (int16_t)k;
    for (i = 0; i < SPCH_EVENT_PARMS; i++)
        s->parms[i] = parms[i];
    if (!app)
        q->numPending[ch]++;
    s->active = 1;
    q->lastAdded[ch] = k;
    if (!app)
        q->lastHead[ch] = k;
    gSpch.addEventStatus = 0;
    return 1;
}

// Retail copies `count` words off its varargs, past the buffer's end
// above 19, and leaves the rest of the 20 as its stack has them; the
// port takes at most 19 and zeroes the rest.
int32_t spch_add_event_v(uint32_t id, int32_t count, ...)
{
    uint32_t buf[SPCH_EVENT_PARMS] = { 0 };
    va_list ap;
    int32_t i;

    buf[0] = id;
    va_start(ap, count);
    for (i = 1; i <= count && i < SPCH_EVENT_PARMS; i++)
        buf[i] = (uint32_t)va_arg(ap, int);
    va_end(ap);
    return spch_add_event(buf);
}

// ---- the choice of event

void spchi_init_follow_data(SpchFollow *fd)
{
    fd->list = NULL;
    fd->count = 0;
}

// Retail goes on through NULL follow data, and through a NULL list.
int32_t spchi_event_in_follow_group(uint32_t id, const SpchFollow *fd)
{
    static const SpchFollow none;
    int32_t i;

    id &= 0xffff;
    if (fd == NULL) {
        spchi_abort("iSPCH_EventInFollowGroup - followData = 0");
        fd = &none;
    }
    if (fd->count <= 0)
        spchi_abort("iSPCH_EventInFollowGroup - followData->numEvents <= 0");
    if (fd->list == NULL) {
        spchi_abort("iSPCH_EventInFollowGroup - followData->ID = 0");
        return 0;
    }
    for (i = 0; i < fd->count; i++)
        if (spch_u16(fd->list + 2 * i) == id)
            return 1;
    return 0;
}

// The channel's best pending start event: the highest priority, then
// the youngest, then the later added. Events past their life are
// cleared on the way; with follow data, only its events count; with the
// filter at 1, a filterable event under the dat's priority is passed by.
int32_t spchi_choose_event_search(const SpchFollow *fd, int32_t channel)
{
    SpchQueue *q = &gSpch.queue;
    uint32_t now = spchi_gettick() + gSpch.preLoadTicks;
    uint32_t bestAge = 0xffffffffu, bestSub = 0;
    int32_t best = -1, bestPri = 0, i;

    for (i = 0; i < SPCH_SLOTS; i++) {
        const SpchSlot *s = &q->slot[i];
        const uint8_t *ev;
        int32_t inGroup = 1, expired = 0, filtered = 0, pri;
        uint32_t age, life;

        if (!s->active || s->channel != channel || s->isAppend != 0)
            continue;
        ev = s->ev;
        if (fd != NULL)
            inGroup = spchi_event_in_follow_group(spch_u16(ev), fd);
        age = now - s->tick;
        life = spch_u16(ev + 2);
        if (life != 0)
            expired = life < age;
        if (gSpch.filter[channel] == 1 && (ev[10] & 1)) {
            uint8_t word[4];
            SpchEventDat *e;

            memcpy(word, &s->parms[0], 4);
            if (spchi_find_event_dat_info(word, &e))
                filtered = spch_u16(ev + 4) < spch_u16(e->dat + 22);
        }
        if (expired) {
            spchi_clear_event(i);
            continue;
        }
        if (!inGroup || filtered)
            continue;
        pri = spch_u16(ev + 4);
        if (bestPri < pri) {
            best = i;
            bestPri = pri;
            bestAge = age;
            bestSub = s->subTick;
        } else if (pri == bestPri
                   && (age < bestAge
                       || (age == bestAge && bestSub < s->subTick))) {
            best = i;
            bestAge = age;
            bestSub = s->subTick;
        }
    }
    return best;
}

// An event's follow group: after its rules (and its mask, if it has
// one), a count byte and the u16 IDs from the third byte on.
int32_t spchi_choose_event(int32_t channel)
{
    SpchFollow fd;
    int32_t use = 0, r;

    spchi_init_follow_data(&fd);
    if ((gSpch.inGame[channel].word & 0xffff) != 0xffff) {
        uint8_t word[4];
        const uint8_t *ev;

        memcpy(word, &gSpch.inGame[channel].word, 4);
        ev = spchi_find_event(word);
        if (ev != NULL && (ev[10] & 0x10)) {
            int32_t n6 = ev[6], n7 = (int8_t)ev[7];
            const uint8_t *p = ev + 12 + ((n6 * 2 + 3) & ~3)
                + ((n7 * 3 + 3) & ~3);

            if (ev[10] & 8)
                p += (n6 * 2 + 7) & ~3;
            fd.count = p[0];
            fd.list = p + 2;
            use = 1;
        }
    }
    r = spchi_choose_event_search(use ? &fd : NULL, channel);
    if (use && r < 0)
        r = spchi_choose_event_search(NULL, channel);
    return r;
}

void spch_clear_event_queue(void)
{
    SpchQueue *q = &gSpch.queue;
    int32_t i;

    for (i = 0; i < SPCH_SLOTS; i++) {
        if (q->slot[i].active) {
            q->slot[i].active = 0;
            q->numPending[q->slot[i].channel]--;
        }
    }
    for (i = 0; i < SPCH_CHANNELS; i++) {
        if (q->numPending[i] != 0) {
            q->numPending[i] = 0;
            spchi_abort("SPCH_ClearEventQueue - found discrepancy in numPending");
        }
    }
    spchi_init_in_game();
}

int32_t spch_check_event_queue(int32_t channel)
{
    return gSpch.queue.numPending[channel];
}

// A start event and its append chain off the queue.
void spchi_clear_event(int32_t i)
{
    SpchQueue *q = &gSpch.queue;
    SpchSlot *s;
    int32_t ch, n;

    if ((uint32_t)i >= SPCH_SLOTS) {
        spchi_abort("iSPCH_ClearEvent - start event index out of bounds.\n");
        return;
    }
    s = &q->slot[i];
    if (s->isAppend) {
        spchi_abort("iSPCH_ClearEvent - should not be called for an append event.\n");
        return;
    }
    ch = s->channel;
    s->active = 0;
    if (q->lastHead[ch] == i)
        q->lastHead[ch] = -1;
    if (q->lastAdded[ch] == i)
        q->lastAdded[ch] = -1;
    for (n = s->next; n != -1;) {
        SpchSlot *a;

        if ((uint32_t)n >= SPCH_SLOTS) {
            spchi_abort("iSPCH_ClearEvent - append index out of bounds.\n");
            break;
        }
        a = &q->slot[n];
        if (a->isAppend == 0 || !a->active) {
            spchi_abort("iSPCH_ClearEvent - append index points to invalid event.\n");
            break;
        }
        if (q->lastAdded[ch] == n)
            q->lastAdded[ch] = -1;
        n = a->next;
        a->active = 0;
    }
    q->numPending[ch]--;
    if (q->numPending[ch] < 0) {
        q->numPending[ch] = 0;
        spchi_abort("iSPCH_ClearEvent - numPending < 0");
    }
}

// Before playing slot k: its channel's older start events go, but for
// those flagged to stay; a newer one that always plays (probability
// 100) bumps the filter.
void spchi_clear_old_events(int32_t k)
{
    SpchQueue *q = &gSpch.queue;
    int32_t ch = q->slot[k].channel, i;
    uint32_t sub0 = q->slot[k].subTick, t0 = q->slot[k].tick;

    q->bumpFilter = 0;
    for (i = 0; i < SPCH_SLOTS; i++) {
        const SpchSlot *s = &q->slot[i];

        if (i == k || !s->active || s->channel != ch || s->isAppend != 0)
            continue;
        if (s->tick < t0 || (s->tick == t0 && s->subTick < sub0)) {
            if (!(s->ev[10] & 4))
                spchi_clear_event(i);
        } else if ((int8_t)s->ev[9] == 100) {
            q->bumpFilter = 1;
        }
    }
}

int32_t spchi_callback_event_rule(uint32_t *event)
{
    if (gSpch.eventRule == NULL)
        return 1;
    return gSpch.eventRule(event);
}

// The channel's last start event, played now if one of its sentences
// fits. Without one, retail returns what ClearEvent leaves behind: the
// channel's pending count.
int32_t spch_play_last_event(int32_t channel)
{
    int32_t h, r;

    if (!spchi_check_last_event_index(channel))
        return 0;
    h = gSpch.queue.lastHead[channel];
    spchi_init_sentence_choice();
    r = spchi_choose_single_sentence(h);
    spchi_clear_event(h);
    if (r)
        return spchi_play_chosen(channel);
    return gSpch.queue.numPending[gSpch.queue.slot[h].channel];
}

int32_t spch_play(int32_t channel)
{
    int32_t r = 0;

    if (gSpch.playStatus) {
        spchi_abort("Tried to re-enter SPCH_Play.");
        gSpch.playStatus = 0;
        return 0;
    }
    gSpch.playStatus = 1;
    if (spchi_one_chosen(channel))
        r = spchi_play_chosen(channel);
    else if (spch_choose(channel))
        r = spchi_play_chosen(channel);
    gSpch.playStatus = 0;
    return r;
}

int32_t spch_play_speech(void)
{
    return spch_play(0);
}

// The channel's best event that the event rule lets through, and a
// sentence for it and its append chain.
int32_t spch_choose(int32_t channel)
{
    SpchQueue *q = &gSpch.queue;
    int32_t k, s, r;

    if (q->numPending[channel] == 0)
        return 0;
    for (;;) {
        uint32_t word;

        k = spchi_choose_event(channel);
        if (k < 0)
            return 0;
        word = q->slot[k].parms[0];
        if (spchi_callback_event_rule(&word) == 1)
            break;
        spchi_clear_event(k);
    }
    spchi_clear_old_events(k);
    spchi_init_sentence_choice();
    s = k;
    do {
        r = spchi_choose_single_sentence(s);
        s = q->slot[s].next;
    } while (s != -1 && r != 0);
    spchi_clear_event(k);
    return r;
}

int32_t spch_choose_speech(void)
{
    return spch_choose(0);
}

void spch_set_filter(int32_t setting, int32_t channel)
{
    gSpch.filter[channel] = setting;
}
