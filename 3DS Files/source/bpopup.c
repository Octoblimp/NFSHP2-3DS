// tPopupMenu and FlailerScreenList's popups. See bpopup.h, and
// docs/formats/boot-flow.md for the decompilation -- every rule below names
// a retail address.

#include "bpopup.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "gameflow.h"

// ---------------------------------------------------------------- tracing

static void trace(BGameFlow* gf, const char* fmt, ...)
{
    char    line[320];
    va_list ap;
    if (!gf->hooks.trace) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    gf->hooks.trace(gf->hooks.user, line);
}

// The animation kit is the Flailer side, and it takes the flow's clock, as
// the title's bloom does: one RealTimer.
static BAnim* flailer(BGameFlow* gf)
{
    if (gf->anim)
        banim_set_clock(gf->anim, (int32_t)gf->realTimer, gf->realElapsed);
    return gf->anim;
}

#define AHOOK(a, fn) ((a) && (a)->hooks.fn)

// ------------------------------------------------------ the Flailer leaves
//
// Each is traced, then done. The traced line is what tools/bootflow_check.py
// prints from the same call in retail's code.

// SetFlailerScreenVisibility (0x0014cbf8). The original's enum is
// VISIBLE=0; the hook's `visible` is a bool, as gameflow.h's are.
static void screenVisible(BGameFlow* gf, uint32_t screen, int visible)
{
    trace(gf, "vis screen %08x %d", (unsigned)screen, visible);
    if (gf->hooks.setScreenVisible)
        gf->hooks.setScreenVisible(gf->hooks.user, screen, visible);
}

// MakeFrontendSound (0x0016e038). Silence is not a sound.
static void makeSound(BGameFlow* gf, int noise)
{
    if (noise == BSND_NONE) return;
    trace(gf, "sound %d", noise);
    if (gf->hooks.sound) gf->hooks.sound(gf->hooks.user, noise);
}

// FlailerSetColor (0x00143f88): the text object, if there is one.
static void setColor(BGameFlow* gf, uint32_t screen, uint32_t obj,
                     uint32_t color)
{
    BAnim* a = flailer(gf);
    trace(gf, "color %08x %08x %08x", (unsigned)screen, (unsigned)obj,
          (unsigned)color);
    if (AHOOK(a, setColor)) a->hooks.setColor(a->hooks.user, screen, obj, color);
}

// FlailerPrintf (0x00143e70) and FlailerTextChunk::SetString: the same
// write, so the same line.
static void setText(BGameFlow* gf, uint32_t screen, uint32_t obj,
                    const char* s)
{
    BAnim* a = flailer(gf);
    trace(gf, "text %08x %08x %s", (unsigned)screen, (unsigned)obj, s);
    if (AHOOK(a, printText)) a->hooks.printText(a->hooks.user, screen, obj, s);
}

// FlailerSetLanguageID (0x001449a8).
static void setLanguageID(BGameFlow* gf, uint32_t screen, uint32_t obj,
                          int id)
{
    BAnim* a = flailer(gf);
    trace(gf, "language id %08x %08x %d", (unsigned)screen, (unsigned)obj, id);
    if (AHOOK(a, setLanguageID))
        a->hooks.setLanguageID(a->hooks.user, screen, obj, id);
}

// FlailerObjectChunk::SetVisibility (0x00140728), and the raw store to
// Visibility (+41) that RenderTextIntoGroup does instead of calling it.
// Object polarity: 1 is visible.
static void setVisible(BGameFlow* gf, uint32_t screen, uint32_t obj,
                       int visible)
{
    BAnim* a = flailer(gf);
    trace(gf, "vis object %08x %08x %d", (unsigned)screen, (unsigned)obj,
          visible);
    if (AHOOK(a, setVisible))
        a->hooks.setVisible(a->hooks.user, screen, obj, visible);
}

// FlailerSetTopLeftY (0x00144458): the int, as a float, and X left alone.
static void setTopLeftY(BGameFlow* gf, uint32_t screen, uint32_t obj, int y)
{
    BAnim* a = flailer(gf);
    float  x = 0.0f, oldY = 0.0f;
    trace(gf, "pos y %08x %08x %d", (unsigned)screen, (unsigned)obj, y);
    if (!AHOOK(a, getTopLeft) || !AHOOK(a, setTopLeft)) return;
    if (AHOOK(a, objectExists)
        && !a->hooks.objectExists(a->hooks.user, screen, obj, BANIM_TYPE_ANY))
        return;
    a->hooks.getTopLeft(a->hooks.user, screen, obj, &x, &oldY);
    a->hooks.setTopLeft(a->hooks.user, screen, obj, x, (float)y);
}

static int objectExists(BGameFlow* gf, uint32_t screen, uint32_t obj,
                        int type)
{
    BAnim* a = flailer(gf);
    return AHOOK(a, objectExists)
           && a->hooks.objectExists(a->hooks.user, screen, obj, type);
}

// ------------------------------------------------------ RenderTextIntoGroup

#define RT_MAX_CHUNKS 32
#define RT_CHUNK_BUF  256

// 0x00144a68: a space, a tab, or the terminator.
static int rtIsSpace(char c)
{
    return c == ' ' || c == '\t' || c == '\0';
}

// WriteTextIntoChunk (0x00144ae8): [start, end) into a zeroed 256-byte
// buffer, the chunk made visible, then the string set.
static void rtWrite(BGameFlow* gf, uint32_t screen, uint32_t chunk,
                    const char* start, const char* end)
{
    char   buf[RT_CHUNK_BUF];
    size_t n = (size_t)(end - start);
    memset(buf, 0, sizeof(buf));
    // The original's memcpy has no bound. Nothing on the disc is that long.
    if (n > sizeof(buf) - 1) n = sizeof(buf) - 1;
    memcpy(buf, start, n);
    setVisible(gf, screen, chunk, 1);
    setText(gf, screen, chunk, buf);
}

static int rtMaxChars(BGameFlow* gf, uint32_t screen, uint32_t chunk)
{
    BAnim* a = flailer(gf);
    return AHOOK(a, textMaxChars)
               ? a->hooks.textMaxChars(a->hooks.user, screen, chunk)
               : 0;
}

int bpopup_render_text_into_group(BGameFlow* gf, uint32_t screen,
                                  uint32_t group, const char* str)
{
    BAnim*      a = flailer(gf);
    uint32_t    chunks[RT_MAX_CHUNKS];
    int         count = 0;
    int32_t     handle = -1;
    const char *p, *lineStart, *lastBreak, *end;
    int         brk = 0, n = 0, maxc, cur = 0, next = 1, i, y;
    uint32_t    last;
    float       top = 0.0f, x = 0.0f, height = 0.0f;

    // Every text object of the group, in file order. A zero in the array
    // is the end of it: the original stores the lookup's null too.
    memset(chunks, 0, sizeof(chunks));
    while (count < RT_MAX_CHUNKS && AHOOK(a, nextInGroup)) {
        uint32_t hash = 0;
        handle = a->hooks.nextInGroup(a->hooks.user, screen, group,
                                      BANIM_TYPE_TEXT, handle, &hash);
        if (handle < 0) break;
        chunks[count++] = hash;
    }
    if (count == 0) return 0;

    p = lineStart = lastBreak = str;
    end = str + strlen(str);
    maxc = rtMaxChars(gf, screen, chunks[0]);

    if (p < end && *p) {
        do {
            // A break point: a space, a tab or '@'. The line is cut at the
            // last one once it is too long -- and only then, so a word
            // longer than a line runs on past MaxChars.
            if (rtIsSpace(*p) || *p == '@') {
                lastBreak = p;
                brk = 1;
            }
            if (!brk) {
                n++;
            } else if (n < maxc - 2 && (n++, *p != '@')) {
                // room left, and not a forced break
            } else {
                n = 0;
                if (chunks[cur]) rtWrite(gf, screen, chunks[cur], lineStart,
                                         lastBreak);
                cur = next;
                // The next line starts after the break point, and the loop's
                // own step skips its first character unexamined: a break
                // there is not seen. "@ @" is a blank line because of it.
                p = lastBreak + 1;
                lineStart = p;
                if (!chunks[cur]) return 0;
                maxc = rtMaxChars(gf, screen, chunks[cur]);
                brk = 0;
                next = cur + 1;
            }
            p++;
        } while (p < end && *p);
    }
    rtWrite(gf, screen, chunks[cur], lineStart, p);

    // The bottom of the first line left over, or of the last line if every
    // one was used: TopLeftY plus GetScaledHeight, truncated. The popup puts
    // its buttons ten under it.
    last = (next < RT_MAX_CHUNKS && chunks[next]) ? chunks[next]
                                                  : chunks[next - 1];
    if (AHOOK(a, textScaledHeight))
        height = a->hooks.textScaledHeight(a->hooks.user, screen, last);
    if (AHOOK(a, getTopLeft))
        a->hooks.getTopLeft(a->hooks.user, screen, last, &x, &top);
    y = (int)(top + height);

    for (i = next; i < count; i++) setVisible(gf, screen, chunks[i], 0);
    return y;
}

// ------------------------------------------------------- FlailerMenuItem

// The two colours FlailerMenuItem recolours with, out of gp-21296..-21276:
// R, G and B are three separate ints there. The highlight carries 0x80 in
// the alpha byte, which SetColor then ignores.
#define ITEM_COLOR_GRAYED    0x00181818u
#define ITEM_COLOR_HIGHLIGHT 0x80004080u

// Set/ClearMenuItemState's tail (0x00169bd0, 0x00169cb0): State & 3 picks
// the colour -- the saved one enabled, the highlight enabled and
// highlighted, gray otherwise. Then the object's DirtyFlag, which the port
// has no use for: it redraws every frame.
static void itemRecolour(BGameFlow* gf, BPopupItem* it)
{
    uint32_t c;
    switch (it->state & 3u) {
        case 1u:  c = it->savedColor;          break;
        case 3u:  c = ITEM_COLOR_HIGHLIGHT;    break;
        default:  c = ITEM_COLOR_GRAYED;       break;
    }
    setColor(gf, it->screen, it->hash, c);
}

static void itemSetState(BGameFlow* gf, BPopupItem* it, uint32_t bits)
{
    it->state |= bits;
    itemRecolour(gf, it);
}

static void itemClearState(BGameFlow* gf, BPopupItem* it, uint32_t bits)
{
    it->state &= ~bits;
    itemRecolour(gf, it);
}

// ResetSavedParameters (0x00169818): the object's colour, if it is there.
static void itemResetSaved(BGameFlow* gf, BPopupItem* it)
{
    BAnim* a = flailer(gf);
    if (!objectExists(gf, it->screen, it->hash, BANIM_TYPE_TEXT)) return;
    it->savedColor = AHOOK(a, getColor)
                         ? a->hooks.getColor(a->hooks.user, it->screen,
                                             it->hash)
                         : 0;
}

// The constructor (0x00169740) with no menu: no screen yet, any pad.
static void itemInit(BGameFlow* gf, BPopupItem* it, uint32_t hash, int id)
{
    memset(it, 0, sizeof(*it));
    it->state   = BMENU_ENABLED;
    it->hash    = hash;
    it->id      = id;
    it->joyPort = -1;
    it->screen  = 0;
    itemResetSaved(gf, it);
}

// ------------------------------------------------------------ tPopupMenu

static int popupIndex(const BGameFlow* gf, const BPopup* p)
{
    return (int)(p - gf->popups);
}

// GetCurrentMenuItem (0x0016b5a8): the first button with none, otherwise
// the current one modulo the count, in unsigned arithmetic -- divu.
static BPopupItem* currentItem(BPopup* p)
{
    uint32_t n = (uint32_t)p->cfg.numButtons;
    if (n == 0) return &p->items[0];
    return &p->items[((p->current % n) + n) % n];
}

// HighlightCurrent (0x0016b618) only with buttons; UnHighlightCurrent
// (0x0016b5f0) either way.
static void highlightCurrent(BGameFlow* gf, BPopup* p)
{
    if (p->cfg.numButtons) itemSetState(gf, currentItem(p), BMENU_HIGHLIGHTED);
}

static void unhighlightCurrent(BGameFlow* gf, BPopup* p)
{
    itemClearState(gf, currentItem(p), BMENU_HIGHLIGHTED);
}

// The parent's callback, taken at Summon. The original calls it without a
// test at Summon and at Dismiss, and with one on a move.
static void popupSend(BGameFlow* gf, BPopup* p, BScreenMessage msg,
                      BScreenCallbackData* data)
{
    if (!p->callback) return;
    trace(gf, "msg %s %d", p->parentName ? p->parentName : "?", (int)msg);
    p->callback(gf, msg, data);
}

// tHighlightAnimation::SetCurrentMenuItem on the popup's bloom.
static void popupBloomItem(BGameFlow* gf, BPopup* p, uint32_t item)
{
    BAnim* a = flailer(gf);
    trace(gf, "popup %d bloom %08x %08x", popupIndex(gf, p),
          (unsigned)p->highlight.screen, (unsigned)item);
    if (a) banim_highlight_set_item(a, &p->highlight, item);
}

// The constructor, 0x0016b478: the bloom first, then the config cleared
// and the three buttons made.
static void popupInit(BGameFlow* gf, BPopup* p)
{
    BAnim  local;
    BAnim* a = flailer(gf);

    memset(p, 0, sizeof(*p));
    if (!a) {
        // bgf_init runs before the host hands the flow its kit. The bloom
        // only takes the clock from it.
        memset(&local, 0, sizeof(local));
        local.timer = (int32_t)gf->realTimer;
        a = &local;
    }
    banim_highlight_init(a, &p->highlight, 0, BPOPUP_OBJ_BLOOM,
                         (int32_t)BANIM_BLOOM_COLOR);
    p->active = 0;
    memset(&p->cfg, 0, sizeof(p->cfg));
    itemInit(gf, &p->items[0], BPOPUP_OBJ_BUTTON1, 0);
    itemInit(gf, &p->items[1], BPOPUP_OBJ_BUTTON2, 1);
    itemInit(gf, &p->items[2], BPOPUP_OBJ_BUTTON3, 2);
    p->callback      = NULL;
    p->current       = 0x80000000u;
    p->phase         = 0.0f;
    p->tracedAnimate = 1;
}

// Summon, 0x0016b660.
static void popupSummon(BGameFlow* gf, BPopup* p, const BPopupConfig* cfg)
{
    static const uint32_t kButtons[3] = {
        BPOPUP_OBJ_BUTTON1, BPOPUP_OBJ_BUTTON2, BPOPUP_OBJ_BUTTON3
    };
    BScreenCallbackData data;
    int                 i, y;

    trace(gf, "popup %d summon", popupIndex(gf, p));
    p->active     = 1;
    p->cfg        = *cfg;
    p->callback   = cfg->parent ? cfg->parent->callback : NULL;
    p->parentName = cfg->parent ? cfg->parent->name : NULL;

    // Off the screen they were last on, last button first.
    itemClearState(gf, &p->items[2], BMENU_HIGHLIGHTED);
    itemClearState(gf, &p->items[1], BMENU_HIGHLIGHTED);
    itemClearState(gf, &p->items[0], BMENU_HIGHLIGHTED);
    screenVisible(gf, p->cfg.screen, 1);

    memset(&data, 0, sizeof(data));
    data.port = -1;
    popupSend(gf, p, BMSG_POPUP_ACTIVE, &data);
    makeSound(gf, data.noise);

    p->current = (uint32_t)p->cfg.startButton;
    for (i = 0; i < 3; i++) {
        BPopupItem* it = &p->items[i];
        it->screen  = p->cfg.screen;
        it->joyPort = p->cfg.joyPort;
        itemResetSaved(gf, it);
        itemClearState(gf, it, BMENU_HIGHLIGHTED);
    }
    highlightCurrent(gf, p);

    y = bpopup_render_text_into_group(gf, p->cfg.screen, BPOPUP_GROUP_MESSAGE,
                                      p->cfg.message ? p->cfg.message : "")
        + 10;
    if (p->cfg.flags & BPOPUP_BUTTONS_BELOW)
        for (i = 0; i < 3; i++) setTopLeftY(gf, p->cfg.screen, kButtons[i], y);

    for (i = 0; i < 3; i++) setText(gf, p->cfg.screen, kButtons[i], "");
    setText(gf, p->cfg.screen, BPOPUP_OBJ_TITLE, "");
    for (i = 0; i < 3; i++)
        setLanguageID(gf, p->cfg.screen, kButtons[i],
                      p->cfg.numButtons == 0 ? 0 : p->cfg.button[i]);
    setLanguageID(gf, p->cfg.screen, BPOPUP_OBJ_TITLE, p->cfg.title);

    p->highlight.screen = p->cfg.screen;
    popupBloomItem(gf, p, currentItem(p)->hash);
    p->tracedAnimate = 0;
}

// Dismiss, 0x0016b9c0: the screen goes (unless the config keeps it), then
// the parent hears which button, with the select click it may silence.
static void popupDismiss(BGameFlow* gf, BPopup* p, int port, int param)
{
    BScreenCallbackData data;

    trace(gf, "popup %d dismiss %d %d", popupIndex(gf, p), port, param);
    if (!(p->cfg.flags & BPOPUP_KEEP_VISIBLE))
        screenVisible(gf, p->cfg.screen, 0);
    p->active = 0;
    memset(&data, 0, sizeof(data));
    data.port  = port;
    data.param = param;
    data.noise = BSND_MENU_SELECT;
    popupSend(gf, p, BMSG_POPUP_DISMISS, &data);
    makeSound(gf, data.noise);
}

// Tick, 0x0016ba50. The phase is bSin'd and the answer thrown away, so the
// port keeps the phase and skips the sine.
static void popupTick(BGameFlow* gf, BPopup* p)
{
    BAnim* a = flailer(gf);

    p->phase = p->phase + gf->realElapsed * 9.0f;
    if (6.283185f < p->phase) p->phase = p->phase - 6.283185f;
    if (!p->tracedAnimate)
        trace(gf, "popup %d animate", popupIndex(gf, p));
    p->tracedAnimate = 1;
    if (a) banim_highlight_animate(a, &p->highlight);
}

// A move of the highlight (the up and down arms of HandleJoy): the parent
// hears the button it moved to, and the bloom follows.
static void popupMoved(BGameFlow* gf, BPopup* p, int port, BScreenMessage msg,
                       int noise)
{
    if (p->callback) {
        BScreenCallbackData data;
        memset(&data, 0, sizeof(data));
        data.itemHash = currentItem(p)->hash;
        data.port     = port;
        data.noise    = noise;
        popupSend(gf, p, msg, &data);
        makeSound(gf, data.noise);
    }
    popupBloomItem(gf, p, currentItem(p)->hash);
}

// HandleJoy, 0x0016bac0. Takes everything: 1 whatever the event did.
static int popupJoy(BGameFlow* gf, BPopup* p, int port, int ev, int pressed)
{
    uint32_t n = (uint32_t)p->cfg.numButtons;
    int      param;

    if (pressed != 1) return 1;

    // A horizontal popup's left and right are its up and down, and its own
    // up and down do nothing. The analog stick's left/right count too.
    if (p->cfg.flags & BPOPUP_HORIZONTAL) {
        switch (ev) {
            case BJOY_SCROLL_UP:    ev = 0;                break;
            case BJOY_SCROLL_DOWN:  ev = 0;                break;
            case BJOY_SCROLL_LEFT:  ev = BJOY_SCROLL_UP;   break;
            case BJOY_SCROLL_RIGHT: ev = BJOY_SCROLL_DOWN; break;
            case BJOY_ANALOG_LEFT:  ev = BJOY_SCROLL_UP;   break;
            case BJOY_ANALOG_RIGHT: ev = BJOY_SCROLL_DOWN; break;
            default:                                       break;
        }
    } else if (ev == BJOY_SCROLL_LEFT || ev == BJOY_SCROLL_RIGHT) {
        ev = 0;
    }

    switch (ev) {
        case BJOY_SCROLL_UP:
            if ((int32_t)n < 2) break;
            unhighlightCurrent(gf, p);
            p->current--;
            if ((int32_t)p->current < 0) p->current = n - 1;
            highlightCurrent(gf, p);
            popupMoved(gf, p, port, BMSG_POPUP_NEXT, BSND_MENU_LEFT);
            break;

        case BJOY_SCROLL_DOWN:
            if ((int32_t)n < 2) break;
            unhighlightCurrent(gf, p);
            p->current++;
            if (!((int32_t)p->current < (int32_t)n)) p->current = 0;
            highlightCurrent(gf, p);
            popupMoved(gf, p, port, BMSG_POPUP_PREV, BSND_MENU_RIGHT);
            break;

        case BJOY_START:
        case BJOY_MENU_SELECT:
            param = p->cfg.buttonParam[0];
            if (n != 0) {
                uint32_t i = p->current % n;
                param = i == 0 ? p->cfg.buttonParam[0]
                      : i == 1 ? p->cfg.buttonParam[1]
                               : p->cfg.buttonParam[2];
            }
            if (!(p->cfg.flags & BPOPUP_NO_SELECT))
                popupDismiss(gf, p, port, param);
            else if (p->cfg.flags & BPOPUP_CANCELABLE)
                popupDismiss(gf, p, port, p->cfg.cancelParam);
            break;

        case BJOY_MENU_BACK:
            if (p->cfg.flags & BPOPUP_CANCELABLE)
                popupDismiss(gf, p, port, p->cfg.cancelParam);
            break;

        default:
            break;
    }
    return 1;
}

// ------------------------------------------------------- FlailerScreenList

void bpopup_init(BGameFlow* gf)
{
    for (int i = 0; i < BPOPUP_COUNT; i++) popupInit(gf, &gf->popups[i]);
}

int bpopup_summon(BGameFlow* gf, const BPopupConfig* cfg)
{
    for (int i = 0; i < BPOPUP_COUNT; i++) {
        if (gf->popups[i].active) continue;
        popupSummon(gf, &gf->popups[i], cfg);
        return i;
    }
    return -1;
}

void bpopup_dismiss(BGameFlow* gf, int i)
{
    BPopup* p;
    if ((unsigned)i >= BPOPUP_COUNT) return;
    p = &gf->popups[i];
    if (!p->active) return;
    popupDismiss(gf, p, p->cfg.joyPort, p->cfg.dismissParam);
}

int bpopup_any_active(const BGameFlow* gf)
{
    for (int i = 0; i < BPOPUP_COUNT; i++)
        if (gf->popups[i].active) return 1;
    return 0;
}

void bpopup_tick(BGameFlow* gf)
{
    for (int i = 0; i < BPOPUP_COUNT; i++) popupTick(gf, &gf->popups[i]);
}

int bpopup_joy(BGameFlow* gf, int port, int joyEvent, int pressed)
{
    int taken = 0;
    for (int i = 0; i < BPOPUP_COUNT; i++) {
        BPopup* p = &gf->popups[i];
        if (!p->active) continue;
        if (p->cfg.joyPort != port && p->cfg.joyPort != -1) continue;
        popupJoy(gf, p, port, joyEvent, pressed);
        taken = 1;
    }
    return taken;
}
