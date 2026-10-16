// helpmenu -- retail's tHelpMenu. See helpmenu.h.

#include "helpmenu.h"

#include <string.h>

#include "flailer.h"

// The fade's slope past x 320 (DAT_0032eab4): the backdrop is gone by 640.
#define FADE_FROM   320.0f
#define FADE_SLOPE  0.003125f

// The tCubic1D the constructor makes: half a second, landing at 1.
#define SLIDE_TIME  0.5f

void helpmenu_construct(HelpMenu *h, const HelpMenuHooks *hooks, BAnim *anim)
{
    memset(h, 0, sizeof(*h));
    if (hooks) h->hooks = *hooks;
    h->screen                 = HELPMENU_SCREEN;
    h->slide.val              = HELPMENU_X_OUT;
    h->slide.valDesired       = HELPMENU_X_OUT;
    h->slide.duration         = SLIDE_TIME;
    h->slide.arrivalThreshold = 1.0f;
    if (anim) {
        banim_alpha_init(anim, &h->fade, h->screen, HELPMENU_OBJ_BACKDROP);
        h->haveFade = 1;
    }
    h->summons = 0;
    // FlailerScreenList's constructor: no override, and gp-17344 is 1 on
    // the disc.
    h->override = NULL;
    h->enabled  = 1;
}

static int soundOn(const HelpMenu *h)
{
    return h->hooks.soundEnabled && h->hooks.soundEnabled(h->hooks.user);
}

static void playSelect(const HelpMenu *h)
{
    if (h->hooks.playSelect) h->hooks.playSelect(h->hooks.user);
}

// The tCubic1D's SetValDesired: a new seek only when it is not there.
static void seek(HelpMenu *h, float x)
{
    h->slide.valDesired = x;
    if (h->slide.val != x) h->slide.state = 2;
}

void helpmenu_summon(HelpMenu *h, const int32_t *lines)
{
    char buttons[HELPMENU_LINE];
    char text[HELPMENU_LINE];
    int  more = 1;
    int  i;

    if (!h->enabled) return;
    h->summons++;
    if (lines == NULL) return;
    if (soundOn(h)) playSelect(h);
    seek(h, HELPMENU_X_IN);
    for (i = 0; i < HELPMENU_ROWS; i++, lines++) {
        uint32_t textObj    = HELPMENU_OBJ_TEXT + (uint32_t)i;
        uint32_t buttonsObj = HELPMENU_OBJ_BUTTONS + (uint32_t)i;

        if (*lines == 0 || !more) {
            more = 0;
            flailer_set_visibility(h->screen, textObj,
                                   FLAILER_OBJECT_INVISIBLE);
            flailer_set_visibility(h->screen, buttonsObj,
                                   FLAILER_OBJECT_INVISIBLE);
            continue;
        }
        {
            const char *line = h->hooks.translate
                ? h->hooks.translate(h->hooks.user, *lines) : NULL;

            helpmenu_split(line ? line : "", buttons, text, HELPMENU_LINE);
        }
        flailer_printf(h->screen, buttonsObj, "%s", buttons);
        flailer_printf(h->screen, textObj, "%s", text);
        flailer_set_visibility(h->screen, textObj, FLAILER_OBJECT_VISIBLE);
        flailer_set_visibility(h->screen, buttonsObj, FLAILER_OBJECT_VISIBLE);
    }
}

void helpmenu_dismiss(HelpMenu *h)
{
    seek(h, HELPMENU_X_OUT);
    if (soundOn(h) && h->summons >= 1) playSelect(h);
}

void helpmenu_toggle(HelpMenu *h, const int32_t *lines)
{
    if (!helpmenu_is_active(h))
        helpmenu_summon(h, lines);
    else
        helpmenu_dismiss(h);
}

int helpmenu_is_active(const HelpMenu *h)
{
    return h->slide.valDesired < HELPMENU_X_SHOWN;
}

void helpmenu_tick(HelpMenu *h, float dt)
{
    int32_t                    shown = h->slide.val < HELPMENU_X_SHOWN;
    struct FlailerObjectChunk *anchor;

    if (h->shown != shown) {
        if (h->summons != 0 && h->hooks.setScreenVisibility)
            h->hooks.setScreenVisibility(h->hooks.user, h->screen,
                                         shown ? 0 : 1);
        h->shown = shown;
    }
    anchor = flailer_find_object(h->screen, HELPMENU_OBJ_ANCHOR,
                                 FLAILER_TYPE_ANY);
    if (anchor != NULL)
        flailer_set_group_position(h->screen, HELPMENU_GROUP,
                                   HELPMENU_OBJ_ANCHOR,
                                   (float)(int32_t)h->slide.val,
                                   (float)(int32_t)anchor->Y);
    if (h->haveFade) {
        BAnim *kit   = h->hooks.anim ? h->hooks.anim(h->hooks.user) : NULL;
        float  scale = 1.0f;

        if (h->slide.val >= FADE_FROM)
            scale = 1.0f - (h->slide.val - FADE_FROM) * FADE_SLOPE;
        if (kit) banim_alpha_set_scale(kit, &h->fade, scale);
    }
    bspline_seek(&h->slide, dt);
}

void helpmenu_set_override(HelpMenu *h, const int32_t *lines)
{
    h->override = lines;
    h->enabled  = 1;
}

void helpmenu_disable(HelpMenu *h)
{
    h->enabled = 0;
}

void helpmenu_reset(HelpMenu *h)
{
    (void)h;
}

const int32_t *helpmenu_lines(const HelpMenu *h, const int32_t *screenLines)
{
    return h->override ? h->override : screenLines;
}

int helpmenu_is_help_character(unsigned char c)
{
    return c >= 0x80 && c <= 0x9d && c != 0x92;
}

int helpmenu_is_help_space(int c)
{
    return c == ' ' || c == '\t' || c == '\0';
}

void helpmenu_split(const char *line, char *buttons, char *text, size_t n)
{
    const unsigned char *p = (const unsigned char *)line;
    size_t               len;
    size_t               b = 0;

    while (*p != '\0'
           && (helpmenu_is_help_character(*p) || helpmenu_is_help_space(*p)
               || *p == '+')) {
        // Retail has no bound here; a line's buttons are a handful.
        if (b + 4 <= n) {
            if (*p == '+') {
                buttons[b++] = ' ';
                buttons[b++] = '+';
                buttons[b++] = ' ';
            } else if (!helpmenu_is_help_space(*p)) {
                buttons[b++] = (char)*p;
            }
        }
        p++;
    }
    buttons[b] = '\0';
    for (len = 0; *p != '\0' && len + 2 < n; len++)
        *text++ = (char)*p++;
    *text = '\0';
}

// ------------------------------------------------- the screens' lines

// Retail's FlailerScreenConfig HelpMenuItems (+0x34), at 0x0031a438 on,
// for the screens the port registers.
static const int32_t kMainMenu[]    = { 800001, 800002, 0 };
static const int32_t kModeOn[]      = { 802225, 802226, 802227, 802231, 0 };
static const int32_t kModeOff[]     = { 802228, 802229, 802230, 802232, 0 };
static const int32_t kChallenge[]   = { 800003, 800004, 800005, 800006, 0 };
static const int32_t kSingleRace[]  = { 801002, 800007, 800008, 800009, 0 };
static const int32_t kKnockout[]    = { 800010, 800011, 800012, 800013, 0 };
static const int32_t kFreeRun[]     = { 800014, 800015, 800016, 800017, 0 };
static const int32_t kSelectCar[]   = { 800018, 800019, 800020, 800021,
                                        800022, 0 };
static const int32_t kBeACop[]      = { 800600, 800601, 800602, 800603, 0 };
static const int32_t kSelectTrack[] = { 800029, 800030, 800031, 800032,
                                        800090, 0 };
static const int32_t kOptions[]     = { 800057, 800058, 800059, 0 };
static const int32_t kAudio[]       = { 800060, 800061, 800500, 800063, 0 };
static const int32_t kJukebox[]     = { 802220, 802221, 802223, 802224, 0 };
static const int32_t kDisplay[]     = { 800067, 800068, 800311, 800069, 0 };
static const int32_t kCustomHud[]   = { 800067, 800068, 800312, 0 };
static const int32_t kLoadSave[]    = { 800070, 800071, 800072, 0 };
static const int32_t kNameEntry[]   = { 800073, 800074, 803010, 800075, 0 };
static const int32_t kLanguage[]    = { 800076, 800077, 800078, 0 };
static const int32_t kCredits[]     = { 800080, 800081, 800079, 0 };
static const int32_t kCreditsRoll[] = { 800082, 800083, 800084, 0 };
// Retail's are 802200 Select controller category, 802201 Adjust Vibration
// setting, 802202 and 802203. The port's page has one row and no rumble.
static const int32_t kPreConfig[]   = { 802202, 802203, 0 };

static const struct {
    const char    *name;
    const int32_t *lines;
} kScreenLines[] = {
    { "New Main Menu",        kMainMenu },
    { "Cops On Mode Select",  kModeOn },
    { "Cops Off Mode Select", kModeOff },
    { "Challenge",            kChallenge },
    { "ChallengeBeACop",      kChallenge },
    { "Single Race Setup",    kSingleRace },
    { "Knockout Setup",       kKnockout },
    { "Lap Knockout Setup",   kKnockout },
    { "Free Run Setup",       kFreeRun },
    { "Be The Cop Setup",     kBeACop },
    { "Select Car",           kSelectCar },
    { "Select Car2P",         kSelectCar },
    { "Select Track",         kSelectTrack },
    { "Options",              kOptions },
    { "Audio Options",        kAudio },
    { "JukeBox Music",        kJukebox },
    { "Display Options",      kDisplay },
    { "Customize P1 HUD",     kCustomHud },
    { "Phils Load Save",      kLoadSave },
    { "NameEntry",            kNameEntry },
    { "Language Options",     kLanguage },
    { "Credits",              kCredits },
    { "EACredits",            kCreditsRoll },
    { "BBGCredits",           kCreditsRoll },
    { "Joystick PreConfig",   kPreConfig },
};

const int32_t *helpmenu_screen_lines(const char *name)
{
    size_t i;

    if (name == NULL) return NULL;
    for (i = 0; i < sizeof(kScreenLines) / sizeof(kScreenLines[0]); i++)
        if (strcmp(kScreenLines[i].name, name) == 0)
            return kScreenLines[i].lines;
    return NULL;
}
