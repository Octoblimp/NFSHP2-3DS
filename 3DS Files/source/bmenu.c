#include "bmenu.h"

#include <stdio.h>
#include <string.h>

#include "bchunk.h"

// HIGHLIGHT_BAR, the one object name the menu system hard-codes.
// bhash("HIGHLIGHT_BAR") == 0x27c5f4ab, the literal at 0x001654a4.
#define BMENU_HIGHLIGHT_BAR 0x27c5f4abu

// FlailerMenu's constructor formats "MENUITEM_%d" for n in 0..15 and keeps
// whichever ones the screen actually defines. It never breaks early, so a
// screen is free to define MENUITEM_1..3 and nothing else -- NEW_MAIN_MENU
// does exactly that.
bool bmenu_open(BMenu* m, BUI* ui, BUIScreen* screen,
                BMenuCallback callback, void* user)
{
    if (!m || !ui || !screen) return false;

    memset(m, 0, sizeof(*m));
    m->ui       = ui;
    m->screen   = screen;
    m->callback = callback;
    m->user     = user;
    m->current  = -1;

    // The shipped values of the gp globals. Nothing in the PS2 image writes
    // any of them except SetIgnoreJoystick, so these are not defaults in the
    // usual sense -- they are what the game runs with.
    m->filterPort     = -1;
    m->looping        = true;         // LoopingMenuScrollMode == 1
    m->ignoreJoystick = false;
    m->highlightColor = 128 | (64 << 8) | (0 << 16);
    m->grayedColor    = 24 | (24 << 8) | (24 << 16);

    for (int n = 0; n < BMENU_MAX_ITEMS; n++) {
        char name[16];
        snprintf(name, sizeof(name), "MENUITEM_%d", n);
        uint32_t hash = bchunk_hash(name);

        int32_t idx = bui_find_object(ui, screen, hash, BUI_TYPE_TEXT);
        if (idx < 0) continue;

        BUIObject obj;
        if (!bui_object(ui, (uint32_t)idx, &obj)) continue;

        BMenuItem* it = &m->items[m->numItems++];
        it->itemHash   = hash;
        it->itemID     = n;
        it->object     = (uint32_t)idx;
        it->state      = BMENU_ENABLED;   // the constructor's State = 1
        it->savedColor = obj.color;       // ResetSavedParameters
    }

    m->highlightBar = bui_find_object(ui, screen, BMENU_HIGHLIGHT_BAR,
                                      BUI_TYPE_BITMAP);
    if (m->numItems) m->current = 0;
    return true;
}

static void send(BMenu* m, BScreenMessage msg, BScreenCallbackData* data,
                 bool playSound)
{
    if (m->callback) m->callback(m, msg, data, m->user);
    if (playSound && m->sound) m->sound(data->noise, m->user);
}

// The data every callback receives: zeroed, then the current item's hash and
// the port. The engine memsets it each time and so does this.
static BScreenCallbackData item_data(const BMenu* m, int item, int port)
{
    BScreenCallbackData d;
    memset(&d, 0, sizeof(d));
    if (item >= 0 && item < m->numItems) d.itemHash = m->items[item].itemHash;
    d.port = port;
    return d;
}

// SetColor__16FlailerTextChunk, through bui_set_text_color so the alpha of
// the authored colour survives.
static void recolour(BMenu* m, const BMenuItem* it, uint32_t rgb)
{
    bui_set_text_color(m->ui, it->object, rgb);
}

// SetMenuItemState (0x00164fb8) reduced to what actually reaches the chunk.
// Its "both bits set" branch writes the grayed colour and is then
// overwritten by the highlight colour a few instructions later, so it is
// dead and is not reproduced.
static void set_state(BMenu* m, BMenuItem* it, uint32_t bits)
{
    if (bits & BMENU_HIGHLIGHTED)
        recolour(m, it, m->highlightColor);
    else if (bits & BMENU_ENABLED)
        recolour(m, it, it->savedColor);
    it->state |= bits;
}

// ClearMenuItemState (0x001650e8). Clearing ENABLED grays; clearing only
// HIGHLIGHTED puts the authored colour back.
static void clear_state(BMenu* m, BMenuItem* it, uint32_t bits)
{
    if (bits & BMENU_ENABLED)
        recolour(m, it, m->grayedColor);
    else if ((bits & BMENU_HIGHLIGHTED) && (it->state & BMENU_HIGHLIGHTED))
        recolour(m, it, it->savedColor);
    it->state &= ~bits;
}

static void highlight(BMenu* m, int item, int port)
{
    if (item < 0 || item >= m->numItems) return;
    set_state(m, &m->items[item], BMENU_HIGHLIGHTED);
    BScreenCallbackData d = item_data(m, item, port);
    send(m, BMSG_MENUITEM_HIGHLIGHT, &d, true);
}

static void unhighlight(BMenu* m, int item, int port)
{
    if (item < 0 || item >= m->numItems) return;
    clear_state(m, &m->items[item], BMENU_HIGHLIGHTED);
    BScreenCallbackData d = item_data(m, item, port);
    send(m, BMSG_MENUITEM_UNHIGHLIGHT, &d, true);
}

// MoveToNextItem / MoveToPrevItem (0x001659a8 / 0x00165a90). The engine
// walks a circular list whose sentinel is the menu object itself; with an
// array the sentinel is "one past the end", which is what the wrap below
// stands in for.
static int step(const BMenu* m, int from, int dir)
{
    if (m->numItems <= 0) return -1;

    if (!m->looping) {
        // Step once. Landing on the sentinel means the end of the list, and
        // the engine's movz leaves you where you were. Disabled items are
        // not skipped in this mode.
        int next = from + dir;
        if (next < 0 || next >= m->numItems) return from;
        return next;
    }

    int cur = from;
    for (int guard = 0; guard < m->numItems; guard++) {
        cur += dir;
        if (cur >= m->numItems) cur = 0;
        else if (cur < 0) cur = m->numItems - 1;
        if (cur == from) return from;                 // all the way round
        if (m->items[cur].state & BMENU_ENABLED) return cur;
    }
    return from;
}

static bool move(BMenu* m, int dir, int port)
{
    int next = step(m, m->current, dir);
    if (next == m->current || next < 0) return false;
    unhighlight(m, m->current, port);
    m->current = next;
    highlight(m, m->current, port);
    return true;
}

void bmenu_activate(BMenu* m, int startItem)
{
    if (!m || m->numItems <= 0) return;

    for (int i = 0; i < m->numItems; i++) {
        BScreenCallbackData d = item_data(m, i, m->filterPort);
        send(m, BMSG_MENUITEM_ACTIVATE, &d, false);
    }

    // SetCurrentItemNumber: bList::GetNode, falling back to the head.
    m->current = (startItem >= 0 && startItem < m->numItems) ? startItem : 0;

    // FlailerMenu::Activate then walks forward to the first enabled item.
    if (!(m->items[m->current].state & BMENU_ENABLED)) {
        int cur = m->current;
        for (int guard = 0; guard < m->numItems; guard++) {
            cur = (cur + 1) % m->numItems;
            if (cur == m->current) break;
            if (m->items[cur].state & BMENU_ENABLED) { m->current = cur; break; }
        }
    }
    highlight(m, m->current, m->filterPort);
}

void bmenu_unactivate(BMenu* m)
{
    if (!m || m->numItems <= 0) return;
    unhighlight(m, m->current, m->filterPort);
    for (int i = 0; i < m->numItems; i++) {
        BScreenCallbackData d = item_data(m, i, m->filterPort);
        send(m, BMSG_MENUITEM_UNACTIVATE, &d, false);
    }
}

// JoyHandler__15FlailerMenuItem (0x001651d8): a jump table on event-5.
// Everything not in it -- SELECT, CANCEL, BACK, HELP, L1/L2/R1/R2 -- falls
// out of the bottom untouched.
static bool item_joy(BMenu* m, int port, BJoyEvent ev)
{
    BScreenMessage msg;
    int            noise = BSND_NONE;

    switch (ev) {
        case BJOY_SCROLL_LEFT:
        case BJOY_ANALOG_LEFT:  msg = BMSG_MENUITEM_PAD_LEFT;  break;
        case BJOY_SCROLL_RIGHT:
        case BJOY_ANALOG_RIGHT: msg = BMSG_MENUITEM_PAD_RIGHT; break;
        case BJOY_START:
        case BJOY_MENU_SELECT:  msg = BMSG_MENUITEM_SELECT;
                                noise = BSND_MENU_SELECT;      break;
        case BJOY_MENU_SQUARE:  msg = BMSG_MENUITEM_SQUARE;    break;
        default: return false;
    }

    // Each case stores the event in Param (`sw s2,24(sp)`; retail's copy
    // is 0x00169d98), which is how a screen tells START's SELECT from the
    // select button's: the Starting Grid skips the fly-by on one only.
    BScreenCallbackData d = item_data(m, m->current, port);
    d.param = (int32_t)ev;
    d.noise = noise;
    send(m, msg, &d, true);
    return true;
}

// JoyHandler__11FlailerMenu (0x00165820). The callback runs first and can
// consume the event by writing param; only then does the selection move.
static bool menu_joy(BMenu* m, int port, BJoyEvent ev)
{
    int dir   = 0;
    int noise = BSND_NONE;
    BScreenMessage msg = BMSG_NONE;

    switch (ev) {
        case BJOY_SCROLL_UP:
        case BJOY_ANALOG_UP:
            msg = BMSG_MENUITEM_PAD_UP;   dir = -1; noise = BSND_MENU_UP;   break;
        case BJOY_SCROLL_DOWN:
        case BJOY_ANALOG_DOWN:
            msg = BMSG_MENUITEM_PAD_DOWN; dir = +1; noise = BSND_MENU_DOWN; break;
        default: break;
    }

    BScreenCallbackData d = item_data(m, m->current, port);
    d.noise = noise;
    if (msg != BMSG_NONE) {
        if (m->callback) m->callback(m, msg, &d, m->user);
        if (d.param != 0) return true;         // the callback ate it
        move(m, dir, port);
        if (m->sound) m->sound(d.noise, m->user);
        return true;
    }
    // Unhandled here, so the current item gets a look.
    return item_joy(m, port, ev);
}

// JoyHandler__13FlailerScreen (0x00165dc0), minus the TranslationEnable
// language-cycling debug path, which belongs to the viewer rather than to a
// menu. SCREEN_BACK_BUTTON is not here: the engine raises it one level up,
// in FlailerScreenList.
bool bmenu_joy(BMenu* m, int port, BJoyEvent ev, bool pressed)
{
    if (!m || m->ignoreJoystick || !pressed) return false;
    if (m->filterPort != -1 && m->filterPort != port) return false;

    if (ev == BJOY_START) {
        BScreenCallbackData d = item_data(m, m->current, port);
        send(m, BMSG_SCREEN_START_BUTTON, &d, true);
        if (d.param == 1) return true;         // consumed by the screen
    } else if (ev == BJOY_MENU_L1 || ev == BJOY_MENU_R1) {
        BScreenCallbackData d = item_data(m, m->current, port);
        send(m, ev == BJOY_MENU_L1 ? BMSG_SCREEN_L1 : BMSG_SCREEN_R1, &d, true);
    }

    return menu_joy(m, port, ev);
}

// FlailerMenu::SetActiveMenuItem (0x0016a3a8): FindItem, then nothing for
// no item, the current one, or one that is not ENABLED; otherwise the
// current item unhighlights and the new one highlights.
bool bmenu_set_active_item(BMenu* m, uint32_t itemHash)
{
    int i;
    if (!m) return false;
    for (i = 0; i < m->numItems && m->items[i].itemHash != itemHash; i++)
        ;
    if (i == m->numItems || i == m->current
        || !(m->items[i].state & BMENU_ENABLED))
        return false;
    unhighlight(m, m->current, m->filterPort);
    m->current = i;
    highlight(m, m->current, m->filterPort);
    return true;
}

bool bmenu_set_item_enabled(BMenu* m, int itemID, bool enabled)
{
    if (!m) return false;
    for (int i = 0; i < m->numItems; i++) {
        if (m->items[i].itemID != itemID) continue;
        if (enabled) set_state(m, &m->items[i], BMENU_ENABLED);
        else         clear_state(m, &m->items[i], BMENU_ENABLED);
        return true;
    }
    return false;
}

const BMenuItem* bmenu_current(const BMenu* m)
{
    if (!m || m->current < 0 || m->current >= m->numItems) return NULL;
    return &m->items[m->current];
}

const BMenuItem* bmenu_find(const BMenu* m, int itemID)
{
    if (!m) return NULL;
    for (int i = 0; i < m->numItems; i++)
        if (m->items[i].itemID == itemID) return &m->items[i];
    return NULL;
}

// AlignBar (0x00164e70). Both coordinates go through cvt.w.s and back, so
// the bar always lands on an integer pixel. The original also calls
// GetWidth() on the label and throws the result away; that call is omitted
// because it changes nothing.
bool bmenu_align_bar(BMenu* m)
{
    if (!m || !m->measure || m->highlightBar < 0) return false;
    const BMenuItem* it = bmenu_current(m);
    if (!it) return false;

    BUIObject label, bar;
    if (!bui_object(m->ui, it->object, &label)) return false;
    if (!bui_object(m->ui, (uint32_t)m->highlightBar, &bar)) return false;

    float labelW = 0.0f, labelH = 0.0f, barW = 0.0f, barH = 0.0f;
    if (!m->measure(m->measureUser, it->object, &labelW, &labelH)) return false;
    if (!m->measure(m->measureUser, (uint32_t)m->highlightBar, &barW, &barH))
        return false;

    float x = label.x - 2.0f;
    if (label.type == BUI_TYPE_TEXT && (label.format & BUI_FMT_CENTER))
        x = label.x - barW * 0.5f;
    float y = label.y + labelH * 0.5f - barH * 0.5f;

    return bui_set_object_pos(m->ui, (uint32_t)m->highlightBar,
                              (float)(int)x, (float)(int)y);
}
