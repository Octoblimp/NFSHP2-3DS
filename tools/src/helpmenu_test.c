// Host test for helpmenu.c, retail's tHelpMenu: SplitHelp, the summon and
// dismiss, the slide and its screen, and the screens' lines.
// tools/helpmenu_check.py builds and runs it.
//
// The Flailer calls helpmenu.c makes are stubbed here: each row's printed
// text and visibility, the help screen's anchor and the group's place are
// recorded, so the test reads what retail's Summon and Tick would have
// drawn.

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "flailer.h"
#include "helpmenu.h"

static int failures;

static void expect(int ok, const char *what)
{
    if (!ok) {
        printf("FAIL %s\n", what);
        failures++;
    }
}

// ------------------------------------------------------------ the stubs

#define NOBJ 16

static char      sPrinted[NOBJ][128];
static int       sVisible[NOBJ];
static float     sGroupX = -1.0f, sGroupY = -1.0f;
static struct FlailerObjectChunk sAnchor;
static int       sScreenVis = -1;   // retail's enum: 0 visible
static int       sScreenCalls;
static int       sSounds;
static int       sSoundOn = 1;

static int slot(uint32_t object)
{
    if (object >= HELPMENU_OBJ_BUTTONS
        && object < HELPMENU_OBJ_BUTTONS + HELPMENU_ROWS)
        return (int)(object - HELPMENU_OBJ_BUTTONS);
    if (object >= HELPMENU_OBJ_TEXT
        && object < HELPMENU_OBJ_TEXT + HELPMENU_ROWS)
        return HELPMENU_ROWS + (int)(object - HELPMENU_OBJ_TEXT);
    return -1;
}

int32_t flailer_printf(uint32_t screen, uint32_t object, const char *fmt,
                       ...)
{
    va_list ap;
    int     i = slot(object);

    if (screen != HELPMENU_SCREEN || i < 0) return 0;
    va_start(ap, fmt);
    vsnprintf(sPrinted[i], sizeof sPrinted[i], fmt, ap);
    va_end(ap);
    return 1;
}

void flailer_set_visibility(uint32_t screen, uint32_t object, int32_t v)
{
    int i = slot(object);

    if (screen == HELPMENU_SCREEN && i >= 0) sVisible[i] = v;
}

struct FlailerObjectChunk *flailer_find_object(uint32_t screen,
                                               uint32_t object,
                                               int32_t type)
{
    (void)type;
    if (screen == HELPMENU_SCREEN && object == HELPMENU_OBJ_ANCHOR)
        return &sAnchor;
    return NULL;
}

void flailer_set_group_position(uint32_t screen, uint32_t group,
                                uint32_t anchor, float x, float y)
{
    if (screen != HELPMENU_SCREEN || group != HELPMENU_GROUP
        || anchor != HELPMENU_OBJ_ANCHOR)
        return;
    sGroupX = x;
    sGroupY = y;
}

static const char *translate(void *user, int32_t id)
{
    (void)user;
    switch (id) {
    case 1: return "\x82 \x83 Select game mode";
    case 2: return "\x86 \x80 Enter game mode";
    case 3: return "\x8a + \x86 Manual Transmission in Quick Race";
    case 4: return "\x87 Back to Main Menu";
    default: return NULL;
    }
}

static int soundEnabled(void *user)
{
    (void)user;
    return sSoundOn;
}

static void playSelect(void *user)
{
    (void)user;
    sSounds++;
}

static void screenVisibility(void *user, uint32_t screen, int32_t v)
{
    (void)user;
    if (screen != HELPMENU_SCREEN) return;
    sScreenVis = v;
    sScreenCalls++;
}

static const HelpMenuHooks kHooks = {
    .user                = NULL,
    .translate           = translate,
    .soundEnabled        = soundEnabled,
    .playSelect          = playSelect,
    .setScreenVisibility = screenVisibility,
    .anim                = NULL,
};

// ------------------------------------------------------------ the tests

static void split(void)
{
    char b[HELPMENU_LINE], t[HELPMENU_LINE];

    helpmenu_split("\x82 \x83 Select game mode", b, t, sizeof b);
    expect(strcmp(b, "\x82\x83") == 0, "split: the D-pad's two, no space");
    expect(strcmp(t, "Select game mode") == 0, "split: the text");

    helpmenu_split("\x8a + \x86 Manual", b, t, sizeof b);
    expect(strcmp(b, "\x8a + \x86") == 0, "split: '+' as \" + \"");
    expect(strcmp(t, "Manual") == 0, "split: the text after a '+'");

    // 0x92 is the apostrophe, not a button.
    helpmenu_split("\x92s", b, t, sizeof b);
    expect(b[0] == '\0' && strcmp(t, "\x92s") == 0, "split: 0x92 is text");

    // A line of buttons alone stops at its end.
    helpmenu_split("\x86 \x80", b, t, sizeof b);
    expect(strcmp(b, "\x86\x80") == 0 && t[0] == '\0',
           "split: buttons alone");

    // The text takes n - 2 characters at most.
    helpmenu_split("\x86 abcdefgh", b, t, 6);
    expect(strcmp(t, "abcd") == 0, "split: n - 2 of the text");

    expect(helpmenu_is_help_character(0x80) && helpmenu_is_help_character(0x9d)
           && !helpmenu_is_help_character(0x92)
           && !helpmenu_is_help_character(0x9e)
           && !helpmenu_is_help_character('a'),
           "IsHelpCharacter: 0x80..0x9d but 0x92");
    expect(helpmenu_is_help_space(' ') && helpmenu_is_help_space('\t')
           && helpmenu_is_help_space('\0') && !helpmenu_is_help_space('+'),
           "IsHelpSpace: space, tab, the terminator");
}

static void run(HelpMenu *h, int frames)
{
    for (int i = 0; i < frames; i++)
        helpmenu_tick(h, 1.0f / 30.0f);
}

static void summon(void)
{
    static const int32_t lines[] = { 1, 2, 3, 4, 0, 1, 1, 1 };
    HelpMenu h;

    helpmenu_construct(&h, &kHooks, NULL);
    sAnchor.Y = 120.0f;
    expect(!helpmenu_is_active(&h), "constructed: not active");
    expect(h.slide.val == 650.0f && h.slide.valDesired == 650.0f,
           "constructed: out at 650");

    // Nothing summoned yet: the screen is left as it is.
    run(&h, 2);
    expect(sScreenCalls == 0, "tick before a summon: the screen untouched");
    expect(sGroupX == 650.0f && sGroupY == 120.0f,
           "tick: the group at the slide's x and the anchor's y");

    memset(sVisible, -1, sizeof sVisible);
    helpmenu_summon(&h, lines);
    expect(h.summons == 1 && sSounds == 1, "summon: counted, MenuSelect");
    expect(helpmenu_is_active(&h), "summon: active at once");
    expect(h.slide.valDesired == 53.0f && h.slide.state == 2,
           "summon: the slide sent to 53");
    expect(strcmp(sPrinted[0], "\x82\x83") == 0
           && strcmp(sPrinted[HELPMENU_ROWS + 0], "Select game mode") == 0,
           "summon: row 1 split into its two columns");
    expect(strcmp(sPrinted[2], "\x8a + \x86") == 0,
           "summon: row 3's buttons");
    expect(sVisible[3] == FLAILER_OBJECT_VISIBLE
           && sVisible[HELPMENU_ROWS + 3] == FLAILER_OBJECT_VISIBLE,
           "summon: row 4 shown");
    {
        int hidden = 1;
        for (int i = 4; i < HELPMENU_ROWS; i++)
            if (sVisible[i] != FLAILER_OBJECT_INVISIBLE
                || sVisible[HELPMENU_ROWS + i] != FLAILER_OBJECT_INVISIBLE)
                hidden = 0;
        expect(hidden, "summon: every row from the first 0 on hidden");
    }

    // The slide: half a second in, the screen shown on the tick after it
    // crosses 640 (Tick tests before it steps). The curve is slow to
    // start: 642 after one 30th, 621 after two.
    run(&h, 2);
    expect(sScreenCalls == 0, "slide in: still hidden at 642");
    run(&h, 1);
    expect(sScreenCalls == 1 && sScreenVis == 0,
           "slide in: the screen shown once under 640");
    run(&h, 20);
    expect(h.slide.val == 53.0f && h.slide.state == 0,
           "slide in: landed at 53 within half a second");
    expect(sGroupX == 53.0f, "slide in: the group at 53");

    helpmenu_toggle(&h, lines);
    expect(!helpmenu_is_active(&h), "toggle: dismissed");
    expect(sSounds == 2, "dismiss: MenuSelect, something was summoned");
    run(&h, 20);
    expect(h.slide.val == 650.0f && sScreenVis == 1 && sScreenCalls == 2,
           "slide out: the screen hidden past 640");

    helpmenu_toggle(&h, lines);
    expect(helpmenu_is_active(&h) && h.summons == 2, "toggle: summoned");

    // No lines: counted, nothing else.
    helpmenu_construct(&h, &kHooks, NULL);
    sSounds = 0;
    helpmenu_summon(&h, NULL);
    expect(h.summons == 1 && sSounds == 0 && !helpmenu_is_active(&h),
           "summon(NULL): counted only");
    // A dismiss with nothing summoned makes no sound.
    helpmenu_construct(&h, &kHooks, NULL);
    helpmenu_dismiss(&h);
    expect(sSounds == 0, "dismiss: silent with no summons");

    // Sound off: no MenuSelect.
    sSoundOn = 0;
    helpmenu_summon(&h, lines);
    expect(sSounds == 0 && helpmenu_is_active(&h), "summon: sound off");
    sSoundOn = 1;
}

static void overrides(void)
{
    static const int32_t own[]   = { 3, 0 };
    static const int32_t mine[]  = { 4, 0 };
    HelpMenu h;

    helpmenu_construct(&h, &kHooks, NULL);
    expect(helpmenu_lines(&h, own) == own, "no override: the screen's");
    helpmenu_set_override(&h, mine);
    expect(helpmenu_lines(&h, own) == mine, "override: its lines");
    helpmenu_set_override(&h, NULL);
    expect(helpmenu_lines(&h, own) == own, "override off: the screen's");

    // 0x001e3dd0: the help off, a summon does nothing, not even count.
    helpmenu_disable(&h);
    helpmenu_summon(&h, own);
    expect(h.summons == 0 && !helpmenu_is_active(&h), "disabled: nothing");
    helpmenu_set_override(&h, mine);
    helpmenu_summon(&h, helpmenu_lines(&h, own));
    expect(h.summons == 1 && helpmenu_is_active(&h),
           "an override turns it on again");
}

static void screens(void)
{
    const int32_t *l;

    l = helpmenu_screen_lines("New Main Menu");
    expect(l && l[0] == 800001 && l[1] == 800002 && l[2] == 0,
           "New Main Menu's lines");
    l = helpmenu_screen_lines("Cops On Mode Select");
    expect(l && l[3] == 802231 && l[4] == 0, "Cops On Mode Select's lines");
    l = helpmenu_screen_lines("Select Car2P");
    expect(l && l[2] == 800020 && l[5] == 0, "Select Car2P's lines");
    l = helpmenu_screen_lines("Joystick PreConfig");
    expect(l && l[0] == 802202 && l[1] == 802203 && l[2] == 0,
           "Joystick PreConfig: the port's one row");
    expect(helpmenu_screen_lines("Joystick Config Port1") == NULL,
           "Joystick Config Port1: none");
    expect(helpmenu_screen_lines("Pause Menu") == NULL, "Pause Menu: none");
    expect(helpmenu_screen_lines(NULL) == NULL, "no screen: none");
}

int main(void)
{
    split();
    summon();
    overrides();
    screens();
    if (failures) {
        printf("helpmenu: %d failed\n", failures);
        return 1;
    }
    printf("helpmenu: ok\n");
    return 0;
}
