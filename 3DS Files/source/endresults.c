// endresults -- the results a finished race shows; endresults.h has the
// map.

#include "endresults.h"

#include <stdio.h>
#include <string.h>

#include "bchunk.h"
#include "bmem.h"
#include "bprintf.h"
#include "car.h"
#include "cartypeinfo.h"
#include "characterinfo.h"
#include "eefpu.h"
#include "flailer.h"
#include "fred.h"
#include "fredend.h"
#include "fredrace.h"
#include "nfsrewards.h"
#include "player.h"
#include "race.h"
#include "realtime.h"
#include "startrace.h"
#include "world.h"

void (*gRenderTextIntoGroupFn)(uint32_t screen, uint32_t group,
                               const char *str);
void (*gRewardCarSpeechFn)(int32_t carType);
void (*gPointsScreenSpeechFn)(int32_t bonus);
int32_t (*gRaceEventRewardTypeFn)(int32_t i);
int32_t (*gRaceEventRewardEarnedFn)(int32_t i);

// Everything here is bMalloc'd in pool 16.
#define END_RESULTS_POOL 16

// FlailerTextFormatOption 64: the text right-aligned.
#define TEXT_RIGHT_ALIGN 64

// TransientStatsElement's FinishReason for a car the cops caught.
#define FINISH_REASON_ARRESTED 2
// RaceParameters' RaceType whose losers are all "Eliminated".
#define RACE_TYPE_KNOCKOUT 3
// The game type a task's reward is a You're The Cop car in.
#define GAME_TYPE_BE_THE_COP 7

// The fades: shown for 5 seconds, out over half a second, the next in over
// the next half second.
#define SHOW_SECONDS  5.0f
#define SWAP_SECONDS  5.5f
#define CYCLE_SECONDS 6.0f
// RealTimer's ticks, 4000 a second, into seconds (gp-28240, gp-28236).
#define TICKS_TO_SECONDS 0.00025f
#define FULL_ALPHA 128.0f

// mph and km/h from metres a second (gp-28256 .. gp-28244).
#define MPS_TO_MPH 2.237f
#define MPS_TO_KPH 3.6f

// The once-only speech flags on the screens' list (endgame.h).
#define POINTS_SPEECH_SAID(s) ((s)->Zeroed[0])
#define TASK_SPEECH_SAID(s)   ((s)->Zeroed[1])

// ------------------------------------------------------------- the seams

static void nothing(EndGameMenusBase *m, BScreenMessage msg,
                    BScreenCallbackData *data)
{
    (void)m;
    (void)msg;
    (void)data;
}

static const char *get_translated_string(int32_t id)
{
    const char *s = gStartRaceTranslateFn != NULL ? gStartRaceTranslateFn(id)
                                                  : NULL;

    return s != NULL ? s : "NOT TRANSLATED PROPERLY";
}

static const char *get_translated_string_by_name(const char *s)
{
    const char *t = gStartRaceTranslateStringFn != NULL
                        ? gStartRaceTranslateStringFn(s) : NULL;

    return t != NULL ? t : s;
}

// CarTypeInfo::GetShortName, 0x00187eb8, as startrace.c's.
static const char *car_type_info_get_short_name(const CarTypeInfo *ct)
{
    return get_translated_string(ct->pCarSpecs->FullName);
}

// DriverInfo::GetName, 0x00188770, as startrace.c's.
static const char *driver_info_get_name(const DriverInfo *d)
{
    if (d->pCharacterInfo == NULL)
        return "";
    return d->pCharacterInfo->CharacterName;
}

// SprintfAndHash, 0x001dc4d0, as startrace.c's.
static uint32_t sprintf_and_hash(const char *fmt, int32_t n)
{
    char buf[32];

    snprintf(buf, sizeof buf, fmt, (int)n);
    return bchunk_hash(buf);
}

static int32_t language(void)
{
    return gCurrLanguageFn != NULL ? gCurrLanguageFn() : 0;
}

static void render_text_into_group(uint32_t screen, uint32_t group,
                                   const char *str)
{
    if (gRenderTextIntoGroupFn != NULL)
        gRenderTextIntoGroupFn(screen, group, str);
}

static void reward_car_speech(int32_t carType)
{
    if (gRewardCarSpeechFn != NULL)
        gRewardCarSpeechFn(carType);
}

static void points_screen_speech(int32_t bonus)
{
    if (gPointsScreenSpeechFn != NULL)
        gPointsScreenSpeechFn(bonus);
}

static int32_t is_car_unlocked(int32_t carType, int32_t gameType)
{
    return gIsCarUnlockedFn != NULL ? gIsCarUnlockedFn(carType, gameType)
                                    : 0;
}

static int32_t race_event_reward_type(int32_t i)
{
    return gRaceEventRewardTypeFn != NULL ? gRaceEventRewardTypeFn(i) : 0;
}

static int32_t race_event_reward_earned(int32_t i)
{
    return gRaceEventRewardEarnedFn != NULL ? gRaceEventRewardEarnedFn(i)
                                            : 0;
}

// Seconds since `stamp`, a RealTimer reading.
static float seconds_since(int32_t stamp)
{
    return (float)(int32_t)((uint32_t)RealTimer - (uint32_t)stamp)
           * TICKS_TO_SECONDS;
}

// bTList::AddTail.
static void add_tail(bNode *list, bNode *n)
{
    bNode *last = list->prev;

    last->next = n;
    list->prev = n;
    n->prev = last;
    n->next = list;
}

// bTList's destructor: each node unlinked and given back, from the head.
static void free_nodes(bNode *list)
{
    while (list->next != list) {
        bNode *n = list->next;

        n->prev->next = n->next;
        n->next->prev = n->prev;
        bFree(n);
    }
}

// ------------------------------------------------------------ the timer

void end_game_print_timer(char *buf, Timer t, int32_t flags)
{
    timer_print_to_string(&t, buf, flags, language());
}

// ------------------------------------------------------------ the counts

int32_t nfs_get_num_points_rewards_earned(void)
{
    int32_t n = 0;
    int32_t i;

    for (i = 0; i < NFS_NUM_POINTS_REWARDS; i++)
        if (Fred.PointsRewardStates[NFSPointsRewardsArray[i].IndexIntoFred]
            != 0)
            n++;
    return n;
}

static const NFSTaskParameters *find_task(int32_t task)
{
    int32_t i;

    for (i = 0; i < NFS_NUM_TASKS; i++)
        if (NFSTasks[i].TaskNumber == task)
            return &NFSTasks[i];
    return NULL;
}

int32_t nfs_get_language_id_for_task_reward(int32_t task)
{
    const NFSTaskParameters *t = find_task(task);

    return t != NULL ? t->EndOfRaceUnlocked : 0;
}

int32_t nfs_get_reward_for_task(int32_t task)
{
    const NFSTaskParameters *t = find_task(task);

    return t != NULL ? t->Reward : -1;
}

int32_t nfs_get_unlocked_game_type_for_task(int32_t task)
{
    const NFSTaskParameters *t = find_task(task);

    return t != NULL ? t->UnlockedInGameType : -1;
}

// The car types, 64 of them. Retail skips a type whose record's address
// is NULL, which only the first of a NULL table's is; the port counts
// nothing then.
#define NUM_CAR_TYPES 64

// 0x0024b2a0: the cars of `usage` unlocked anywhere, or never locked.
static int32_t num_available_of_usage(int32_t usage)
{
    int32_t n = 0;
    int32_t i;

    if (CarTypeInfoArray == NULL)
        return 0;
    for (i = 0; i < NUM_CAR_TYPES; i++) {
        const CarTypeInfo *ct = cartypeinfo_get(i);
        int32_t lock;

        if (ct->UsageType != usage)
            continue;
        lock = ct->InitialLockStatus;
        if (is_car_unlocked(i, -1))
            n++;
        else if (lock == 0)
            n++;
    }
    return n;
}

int32_t end_reward_num_available_cars(void)
{
    int32_t cars = num_available_of_usage(0);
    int32_t cops = num_available_of_usage(1);
    int32_t n = TheRaceParameters.New784;
    int32_t i;

    if (fred_use_the_race_event(&Fred))
        for (i = 0; i < TheRaceEvent.nRewards; i++)
            if (race_event_reward_type(i) == 0
                && endgame_should_see_reward_menu()
                && race_event_reward_earned(i))
                n++;
    return cars + cops + n;
}

int32_t end_reward_num_cars_of_usage(int32_t usage)
{
    int32_t n = 0;
    int32_t i;

    if (CarTypeInfoArray == NULL)
        return 0;
    for (i = 0; i < NUM_CAR_TYPES; i++)
        if (cartypeinfo_get(i)->UsageType == usage)
            n++;
    return n;
}

int32_t end_reward_num_cop_cars_available(void)
{
    int32_t n = 0;
    int32_t i;

    if (CarTypeInfoArray == NULL)
        return 0;
    for (i = 0; i < NUM_CAR_TYPES; i++) {
        const CarTypeInfo *ct = cartypeinfo_get(i);
        int32_t lock;

        if (ct->UsageType != 1)
            continue;
        lock = ct->BeACopLockStatus;
        if (lock == 1 && is_car_unlocked(i, GAME_TYPE_BE_THE_COP))
            n++;
        else if (lock == 0)
            n++;
    }
    return n;
}

int32_t end_reward_num_cop_cars(void)
{
    return end_reward_num_cars_of_usage(1);
}

void end_reward_show_car_count(uint32_t hash, int32_t cop)
{
    char buf[256];
    int32_t have, of, id;

    if (!cop) {
        have = end_reward_num_available_cars();
        of = end_reward_num_cars_of_usage(0);
        of += end_reward_num_cars_of_usage(1);
        id = END_REWARD_LANG_COUNT;
    } else {
        have = end_reward_num_cop_cars_available();
        of = end_reward_num_cop_cars();
        id = END_REWARD_LANG_COUNT_COP;
    }
    b_snprintf(buf, sizeof buf, get_translated_string(id), (int)have,
               (int)of);
    render_text_into_group(hash, END_REWARD_GROUP_COUNT, buf);
}

void end_reward_clear_car_count(uint32_t hash)
{
    render_text_into_group(hash, END_REWARD_GROUP_COUNT, "");
}

// ------------------------------------------------------- the reward screens

const EndGameMenusVTable kPointsRewardsVTable = {
    nothing,
    endgame_menus_base_handle_event,
    nothing,
    nothing,
    endgame_menus_base_destroy,
};

const EndGameMenusVTable kTaskRewardsVTable = {
    nothing,
    endgame_menus_base_handle_event,
    nothing,
    nothing,
    endgame_menus_base_destroy,
};

// The reward's car in the blurb, the last line dropped once the last
// points reward is earned. The car's speech once.
EndGameMenusBase *points_rewards_construct(void *mem, uint32_t hash,
                                           BScreenCallbackData *data)
{
    EndGameMenusBase *m = (EndGameMenusBase *)mem;
    EndGameScreens *s;
    const CarTypeInfo *ct;
    const char *fmt;
    char buf[128];
    int32_t car;

    (void)data;
    endgame_menus_base_construct(m, hash);
    m->vt = &kPointsRewardsVTable;
    car = nfs_get_car_type_for_points_reward(
        Fred.TransientStatsTable.PointsRewardEarned);
    ct = cartypeinfo_get(car);
    if (nfs_get_num_points_rewards_earned() != NFS_NUM_POINTS_REWARDS)
        fmt = get_translated_string(END_REWARD_LANG_POINTS_BLURB);
    else
        fmt = get_translated_string(END_REWARD_LANG_POINTS_BLURB_LAST);
    b_snprintf(buf, sizeof buf, fmt,
               get_translated_string_by_name(
                   car_type_info_get_short_name(ct)));
    s = pEndGameScreens;
    if (s != NULL) {
        if (POINTS_SPEECH_SAID(s) == 0)
            reward_car_speech(car);
        POINTS_SPEECH_SAID(s) = 1;
    }
    render_text_into_group(m->ScreenHash, END_REWARD_GROUP_BLURB, buf);
    flailer_set_language_id(m->ScreenHash, END_REWARD_OBJ_TITLE,
                            END_REWARD_LANG_POINTS_TITLE);
    end_reward_show_car_count(m->ScreenHash, 0);
    return m;
}

// The task's blurb, the count of You're The Cop cars for a cop car's
// task. Retail prints the blurb with itself as the format and nothing
// else; no blurb in any language has a '%', so the port copies it. The
// car's speech once.
EndGameMenusBase *task_rewards_construct(void *mem, uint32_t hash,
                                         BScreenCallbackData *data)
{
    EndGameMenusBase *m = (EndGameMenusBase *)mem;
    EndGameScreens *s;
    char buf[128];
    int32_t task, id, cop;

    (void)data;
    endgame_menus_base_construct(m, hash);
    m->vt = &kTaskRewardsVTable;
    task = Fred.TransientStatsTable.TaskRewardEarned;
    id = nfs_get_language_id_for_task_reward(task);
    cop = nfs_get_unlocked_game_type_for_task(task) == GAME_TYPE_BE_THE_COP;
    b_snprintf(buf, sizeof buf, "%s", get_translated_string(id));
    render_text_into_group(m->ScreenHash, END_REWARD_GROUP_BLURB, buf);
    s = pEndGameScreens;
    if (s != NULL) {
        if (TASK_SPEECH_SAID(s) == 0)
            reward_car_speech(nfs_get_reward_for_task(task));
        TASK_SPEECH_SAID(s) = 1;
    }
    flailer_set_language_id(m->ScreenHash, END_REWARD_OBJ_TITLE,
                            END_REWARD_LANG_TASK_TITLE);
    end_reward_show_car_count(m->ScreenHash, cop);
    return m;
}

// ------------------------------------------------------------ the slideshow

// EventTournamentState::GetPointsForFinishPos's table (gp-16648): a
// tournament's points by place, from 0. Retail reads round it unchecked;
// the seven bytes before it and the 32 after are 0, as the port answers,
// so every place a race gives, 0 for none included, reads the same.
static const uint8_t kPointsForFinishPos[RACE_RESULTS_ROWS] = {
    10, 6, 4, 3, 2, 1, 0, 0,
};

static int32_t get_points_for_finish_pos(int32_t i)
{
    if (i < 0 || i >= RACE_RESULTS_ROWS)
        return 0;
    return kPointsForFinishPos[i];
}

static tStatsColumn *new_column(int32_t title)
{
    tStatsColumn *c = (tStatsColumn *)bMalloc(
        (int)sizeof(tStatsColumn), "tStatsColumn", 0, END_RESULTS_POOL);

    c->Title = title;
    return c;
}

// The rows a column has: TransientStats' count, at most the screen's 8.
// Retail writes past the column for more; TransientStats never has them.
static int32_t num_rows(int32_t n)
{
    return n < RACE_RESULTS_ROWS ? n : RACE_RESULTS_ROWS;
}

// Time: the winner's time, the others' gaps to it.
static tStatsColumn *totals_column(int32_t n)
{
    const TransientStats *ts = &Fred.TransientStatsTable;
    tStatsColumn *c = new_column(RR_LANG_TIME);
    int32_t knockout = TheRaceParameters.RaceType == RACE_TYPE_KNOCKOUT;
    uint32_t winner = ts->Stats[0].RaceTime.PackedTime;
    int32_t i;

    for (i = 0; i < num_rows(n); i++) {
        const TransientStatsElement *e = &ts->Stats[i];
        tStatsDatum *d = &c->Data[i];

        if (knockout && i != 0) {
            d->Value.Int = RR_LANG_ELIMINATED;
            d->Type = STATS_DATA_LANGUAGE;
        } else if (e->FinishReason == FINISH_REASON_ARRESTED) {
            d->Value.Int = RR_LANG_ARRESTED;
            d->Type = STATS_DATA_LANGUAGE;
        } else if (i == 0) {
            d->Type = STATS_DATA_TIMER;
            d->Value.Time = e->RaceTime;
        } else {
            d->Value.Time.PackedTime = e->RaceTime.PackedTime - winner;
            d->Type = STATS_DATA_TIMER_BEHIND;
        }
    }
    return c;
}

static float speed_scale(void)
{
    return Fred.DisplayOptionsData.Units == 0 ? MPS_TO_MPH : MPS_TO_KPH;
}

void slideshow_stats_construct(tSlideshowStats *s, uint32_t hash)
{
    const TransientStats *ts = &Fred.TransientStatsTable;
    const RaceParameters *rp = &TheRaceParameters;
    int32_t n = ts->NumStats;
    tStatsColumn *c;
    int32_t i;

    s->ScreenHash = hash;
    s->Columns.next = &s->Columns;
    s->AnimTimer = 0;
    s->Columns.prev = &s->Columns;

    add_tail(&s->Columns, &totals_column(n)->Node);
    if (endgame_should_see_tourney()) {
        c = new_column(RR_LANG_POINTS);
        for (i = 0; i < num_rows(n); i++) {
            c->Data[i].Value.Int =
                get_points_for_finish_pos(ts->Stats[i].FinishPosition - 1);
            c->Data[i].Type = STATS_DATA_INT;
        }
        add_tail(&s->Columns, &c->Node);
    }
    if (rp->nMaxCops > 0) {
        c = new_column(RR_LANG_TICKETS);
        for (i = 0; i < num_rows(n); i++) {
            c->Data[i].Type = STATS_DATA_INT;
            c->Data[i].Value.Int = ts->Stats[i].NumTickets;
        }
        add_tail(&s->Columns, &c->Node);
    }
    if (rp->Point2Point == 0 && rp->NumLapsInRace != 1) {
        c = new_column(RR_LANG_BEST_LAP);
        for (i = 0; i < num_rows(n); i++) {
            c->Data[i].Type = STATS_DATA_TIMER;
            c->Data[i].Value.Time = ts->Stats[i].BestLapTime;
        }
        add_tail(&s->Columns, &c->Node);
    }
    c = new_column(RR_LANG_AVG_SPEED);
    for (i = 0; i < num_rows(n); i++) {
        c->Data[i].Type = STATS_DATA_FLOAT;
        c->Data[i].Value.Float = ts->Stats[i].AverageSpeed * speed_scale();
    }
    add_tail(&s->Columns, &c->Node);
    c = new_column(RR_LANG_TOP_SPEED);
    for (i = 0; i < num_rows(n); i++) {
        c->Data[i].Type = STATS_DATA_FLOAT;
        c->Data[i].Value.Float = ts->Stats[i].TopSpeed * speed_scale();
    }
    add_tail(&s->Columns, &c->Node);

    s->CurrentColumn = (tStatsColumn *)s->Columns.next;
    s->AnimTimer = RealTimer;
    slideshow_stats_setup_dataset(s, s->CurrentColumn);
}

void slideshow_stats_destroy(tSlideshowStats *s, int32_t flags)
{
    free_nodes(&s->Columns);
    if (flags & 1)
        bFree(s);
}

void slideshow_stats_set_alpha_scale(tSlideshowStats *s, float f)
{
    int32_t k;

    for (k = 1; k <= RACE_RESULTS_ROWS; k++) {
        uint32_t h = sprintf_and_hash("BEHIND_%d", k);

        flailer_set_alpha(s->ScreenHash, h, ee_trunc_w(f * FULL_ALPHA));
    }
}

void slideshow_stats_setup_dataset(tSlideshowStats *s, tStatsColumn *col)
{
    uint32_t hash = s->ScreenHash;
    int32_t k;

    s->CurrentColumn = col;
    for (k = 1; k <= RACE_RESULTS_ROWS; k++) {
        uint32_t h = sprintf_and_hash("BEHIND_%d", k);
        const tStatsDatum *d = &s->CurrentColumn->Data[k - 1];
        char buf[64];

        switch (d->Type) {
        case STATS_DATA_INT:
            flailer_printf(hash, h, "%d", (int)d->Value.Int);
            flailer_set_text_format_option(hash, h, TEXT_RIGHT_ALIGN);
            break;
        case STATS_DATA_FLOAT:
            flailer_printf(hash, h, "%3.f", (double)d->Value.Float);
            flailer_set_text_format_option(hash, h, TEXT_RIGHT_ALIGN);
            break;
        case STATS_DATA_LANGUAGE:
            if (d->Value.Int != 0)
                flailer_set_language_id(hash, h, (uint32_t)d->Value.Int);
            else
                flailer_printf(hash, h, "");
            flailer_clear_text_format_option(hash, h, TEXT_RIGHT_ALIGN);
            break;
        case STATS_DATA_TIMER:
            if (timer_is_valid(&d->Value.Time)) {
                end_game_print_timer(buf, d->Value.Time, 0);
                flailer_printf(hash, h, "%s", buf);
                flailer_set_text_format_option(hash, h, TEXT_RIGHT_ALIGN);
            } else {
                flailer_printf(hash, h, "");
            }
            break;
        case STATS_DATA_TIMER_BEHIND:
            if (d->Value.Time.PackedTime != TIMER_UNSET) {
                end_game_print_timer(buf, d->Value.Time, TIMER_PRINT_MINUS);
                flailer_printf(hash, h, "%s", buf);
                flailer_set_text_format_option(hash, h, TEXT_RIGHT_ALIGN);
            } else {
                flailer_printf(hash, h, "");
            }
            break;
        default:
            break;
        }
    }
    flailer_set_language_id(hash, RACE_RESULTS_OBJ_STAT_TITLE,
                            (uint32_t)s->CurrentColumn->Title);
}

// The column after `col`, round the end.
static tStatsColumn *next_column(tSlideshowStats *s, tStatsColumn *col)
{
    bNode *n = col->Node.next;

    if (n == &s->Columns)
        n = s->Columns.next;
    return (tStatsColumn *)n;
}

// Shown for 5 seconds; then out over half a second, the next column put
// up once, and in over the next half; at 6 seconds the clock starts over.
// Refresh is cleared only while shown, so a first tick past 5.5 seconds
// reads what the constructor left there.
void slideshow_stats_tick(tSlideshowStats *s)
{
    float t = seconds_since(s->AnimTimer);

    if (!(SHOW_SECONDS < t)) {
        s->Refresh = 0;
        slideshow_stats_set_alpha_scale(s, 1.0f);
    } else if (t < SWAP_SECONDS) {
        float out = t - SHOW_SECONDS;

        slideshow_stats_set_alpha_scale(s, 1.0f - (out + out));
    } else if (t < CYCLE_SECONDS) {
        float in = t - SWAP_SECONDS;

        if (s->Refresh == 0) {
            slideshow_stats_setup_dataset(
                s, next_column(s, s->CurrentColumn));
            s->Refresh = 1;
        }
        slideshow_stats_set_alpha_scale(s, in + in);
    } else {
        s->AnimTimer = RealTimer;
    }
}

void slideshow_stats_change_stats(tSlideshowStats *s, int32_t dir)
{
    bNode *n = &s->CurrentColumn->Node;

    if (dir == 1) {
        n = n->next;
        if (n == &s->Columns)
            n = s->Columns.next;
    } else if (dir == -1) {
        n = n->prev;
        if (n == &s->Columns)
            n = n->prev;
    }
    slideshow_stats_setup_dataset(s, (tStatsColumn *)n);
    s->Refresh = 0;
    s->AnimTimer = RealTimer;
}

// ---------------------------------------------------------------- the tally

// 0x001dfe30: `points` with its thousands split, into `object`.
static void print_points(uint32_t hash, uint32_t object, int32_t points)
{
    char buf[64];

    nfs_format_points(buf, (int)sizeof buf, points, language());
    flailer_printf(hash, object, "%s", buf);
}

void points_results_construct(tPointsResults *p, uint32_t hash)
{
    p->Timer = 0;
    p->ScreenHash = hash;
    p->Lines.next = &p->Lines;
    p->Lines.prev = &p->Lines;
    p->Timer = RealTimer;
    p->TopLeftX = flailer_get_top_left_x(p->ScreenHash,
                                         RACE_RESULTS_OBJ_POINTS_LABEL);
    p->TopLeftY = flailer_get_top_left_y(p->ScreenHash,
                                         RACE_RESULTS_OBJ_POINTS_LABEL);
}

// 0x001dfe80: the current line's label and points up, the clock started.
static void show_line(tPointsResults *p)
{
    flailer_set_language_id(p->ScreenHash, RACE_RESULTS_OBJ_POINTS_LABEL,
                            (uint32_t)p->Current->Label);
    print_points(p->ScreenHash, RACE_RESULTS_OBJ_POINTS, p->Current->Points);
    p->Timer = RealTimer;
}

// The first line up. With no lines, retail shows its own list head as
// one; the port shows nothing.
void points_results_start(tPointsResults *p)
{
    if (p->Lines.next == &p->Lines)
        return;
    p->Current = (tPointsThingy *)p->Lines.next;
    show_line(p);
}

static int32_t count_lines(const tPointsResults *p)
{
    const bNode *n;
    int32_t c = 0;

    for (n = p->Lines.next; n != &p->Lines; n = n->next)
        c++;
    return c;
}

// With two lines or more: shown for 5 seconds, out over half a second,
// and past 5.5 the next line up at full strength.
void points_results_tick(tPointsResults *p)
{
    float t = seconds_since(p->Timer);

    if (!(SHOW_SECONDS < t))
        return;
    if (count_lines(p) < 2)
        return;
    if (SWAP_SECONDS < t) {
        bNode *n = p->Current->Node.next;

        if (n == &p->Lines)
            n = p->Lines.next;
        p->Current = (tPointsThingy *)n;
        show_line(p);
        flailer_set_group_alpha(p->ScreenHash, RACE_RESULTS_GROUP_TALLY,
                                ee_trunc_w(FULL_ALPHA));
    } else {
        float out = t - SHOW_SECONDS;

        flailer_set_group_alpha(p->ScreenHash, RACE_RESULTS_GROUP_TALLY,
                                ee_trunc_w((1.0f - (out + out))
                                           * FULL_ALPHA));
    }
}

void points_results_destroy(tPointsResults *p, int32_t flags)
{
    free_nodes(&p->Lines);
    if (flags & 1)
        bFree(p);
}

static void add_line(tPointsResults *p, int32_t label, int32_t points)
{
    tPointsThingy *l = (tPointsThingy *)bMalloc(
        (int)sizeof(tPointsThingy), "tPointsThingy", 0, END_RESULTS_POOL);

    l->Label = label;
    l->Points = points;
    add_tail(&p->Lines, &l->Node);
}

// The bonus's label by the place that earned it.
static int32_t bonus_label(int32_t place)
{
    switch (place) {
    case 1: return RR_LANG_1ST_BONUS;
    case 2: return RR_LANG_2ND_BONUS;
    case 3: return RR_LANG_3RD_BONUS;
    }
    return RR_LANG_NO_BONUS;
}

// Retail sets the speech flag before it tests it, so the points speech
// never plays from here.
void race_results_show_points(RaceResultsScreen *s)
{
    uint32_t hash = s->Base.ScreenHash;
    TransientStats *ts = &Fred.TransientStatsTable;
    EndGameScreens *egs = pEndGameScreens;
    int32_t np;

    if (!endgame_is_not_game_type_6()) {
        flailer_set_group_visibility(hash, RACE_RESULTS_GROUP_POINTS,
                                     FLAILER_OBJECT_INVISIBLE);
        flailer_set_group_visibility(hash, RACE_RESULTS_GROUP_TALLY,
                                     FLAILER_OBJECT_INVISIBLE);
        return;
    }
    flailer_set_group_visibility(hash, RACE_RESULTS_GROUP_POINTS,
                                 FLAILER_OBJECT_VISIBLE);
    flailer_set_group_visibility(hash, RACE_RESULTS_GROUP_TALLY,
                                 FLAILER_OBJECT_VISIBLE);
    np = Fred.NumPlayerCars;
    if (egs != NULL)
        POINTS_SPEECH_SAID(egs) = 1;
    if (np == 1) {
        const TransientStatsElement *r = transient_stats_get_driver(ts, 0);

        if (r != NULL) {
            add_line(&s->Points, RR_LANG_POINTS_EARNED, r->PointsThisRace);
            print_points(hash, RACE_RESULTS_OBJ_TOTAL, r->PointsTotal);
            if (r->FinishBonus != 0)
                add_line(&s->Points, bonus_label(r->FinishPosition),
                         r->FinishBonus);
            add_line(&s->Points, RR_LANG_TOTAL_EARNED,
                     r->FinishBonus + r->PointsThisRace);
            if (egs != NULL && POINTS_SPEECH_SAID(egs) == 0)
                points_screen_speech(r->FinishBonus != 0);
        }
        points_results_start(&s->Points);
    } else if (np == 2) {
        const TransientStatsElement *r0 = transient_stats_get_driver(ts, 0);
        const TransientStatsElement *r1 = transient_stats_get_driver(ts, 1);

        if (r0 != NULL) {
            flailer_set_language_id(hash, RACE_RESULTS_OBJ_POINTS_LABEL,
                                    RR_LANG_P1_POINTS);
            print_points(hash, RACE_RESULTS_OBJ_POINTS, r0->PointsThisRace);
            flailer_set_visibility(hash, RACE_RESULTS_OBJ_POINTS_LABEL,
                                   FLAILER_OBJECT_VISIBLE);
            flailer_set_visibility(hash, RACE_RESULTS_OBJ_POINTS,
                                   FLAILER_OBJECT_VISIBLE);
        } else {
            flailer_set_visibility(hash, RACE_RESULTS_OBJ_POINTS_LABEL,
                                   FLAILER_OBJECT_INVISIBLE);
            flailer_set_visibility(hash, RACE_RESULTS_OBJ_POINTS,
                                   FLAILER_OBJECT_INVISIBLE);
        }
        if (r1 != NULL) {
            flailer_set_language_id(hash, RACE_RESULTS_OBJ_P2_LABEL,
                                    RR_LANG_P2_POINTS);
            print_points(hash, RACE_RESULTS_OBJ_TOTAL, r1->PointsThisRace);
            flailer_set_visibility(hash, RACE_RESULTS_OBJ_P2_LABEL,
                                   FLAILER_OBJECT_VISIBLE);
            flailer_set_visibility(hash, RACE_RESULTS_OBJ_TOTAL,
                                   FLAILER_OBJECT_VISIBLE);
        } else {
            flailer_set_visibility(hash, RACE_RESULTS_OBJ_P2_LABEL,
                                   FLAILER_OBJECT_INVISIBLE);
            flailer_set_visibility(hash, RACE_RESULTS_OBJ_TOTAL,
                                   FLAILER_OBJECT_INVISIBLE);
        }
    }
}

// ------------------------------------------------------------ the screen

const EndGameMenusVTable kRaceResultsVTable = {
    race_results_scroll,
    endgame_menus_base_handle_event,
    race_results_tick,
    nothing,
    race_results_destroy,
};

// Row k's driver, car, place and time in the driver's colour; the stat
// column left to the slideshow. A row whose car is not in the world is
// left as it is; retail would read through NULL.
static void show_row(RaceResultsScreen *s, const TransientStatsElement *row,
                     int32_t k)
{
    uint32_t hash = s->Base.ScreenHash;
    uint32_t pos = sprintf_and_hash("POS_%d", k);
    uint32_t name = sprintf_and_hash("NAME_%d", k);
    uint32_t type = sprintf_and_hash("TYPE_%d", k);
    uint32_t time = sprintf_and_hash("TIME_%d", k);
    uint32_t behind = sprintf_and_hash("BEHIND_%d", k);
    const bVector4 *color = &DefaultTextColor;
    const struct Car *car;
    const DriverInfo *d;
    const CarTypeInfo *ct;

    car = world_get_car_by_number(pCurrentWorld, row->UniqueDriveNumber);
    if (car == NULL || car->MyDriver == NULL)
        return;
    d = car->MyDriver;
    ct = cartypeinfo_get(d->CurrentRideInfo.Type);
    flailer_set_visibility(hash, pos, FLAILER_OBJECT_VISIBLE);
    flailer_set_visibility(hash, name, FLAILER_OBJECT_VISIBLE);
    flailer_set_visibility(hash, type, FLAILER_OBJECT_VISIBLE);
    flailer_set_visibility(hash, time, FLAILER_OBJECT_VISIBLE);
    flailer_printf(hash, pos, "%2d", (int)row->FinishPosition);
    if (d->TheDriverType == DRIVER_TYPE_PLAYER) {
        const Player *p =
            world_get_car_by_driver_number(d->UniqueDriverNumber)->pPlayer;

        flailer_printf(hash, name, "%s", p->PlayerSettings.PlayerName);
        color = &PlayerTextColors[p->PlayerNumber];
    } else {
        flailer_printf(hash, name, "%s", driver_info_get_name(d));
    }
    flailer_set_object_color(hash, pos, color);
    flailer_set_object_color(hash, name, color);
    flailer_set_object_color(hash, type, color);
    flailer_set_object_color(hash, time, color);
    flailer_set_object_color(hash, behind, color);
    flailer_printf(hash, type, "%s",
                   get_translated_string_by_name(
                       car_type_info_get_short_name(ct)));
    flailer_set_text_format_option(hash, time, TEXT_RIGHT_ALIGN);
}

static void hide_row(uint32_t hash, int32_t k)
{
    uint32_t pos = sprintf_and_hash("POS_%d", k);
    uint32_t name = sprintf_and_hash("NAME_%d", k);
    uint32_t type = sprintf_and_hash("TYPE_%d", k);
    uint32_t time = sprintf_and_hash("TIME_%d", k);
    uint32_t behind = sprintf_and_hash("BEHIND_%d", k);

    flailer_set_visibility(hash, pos, FLAILER_OBJECT_INVISIBLE);
    flailer_set_visibility(hash, name, FLAILER_OBJECT_INVISIBLE);
    flailer_set_visibility(hash, type, FLAILER_OBJECT_INVISIBLE);
    flailer_set_visibility(hash, time, FLAILER_OBJECT_INVISIBLE);
    flailer_set_visibility(hash, behind, FLAILER_OBJECT_INVISIBLE);
}

EndGameMenusBase *race_results_construct(void *mem, uint32_t hash,
                                         BScreenCallbackData *data)
{
    RaceResultsScreen *s = (RaceResultsScreen *)mem;
    const TransientStats *ts = &Fred.TransientStatsTable;
    const EndGameScreens *egs;
    int32_t n, i, k;

    (void)data;
    endgame_menus_base_construct(&s->Base, hash);
    s->Base.vt = &kRaceResultsVTable;
    slideshow_stats_construct(&s->Stats, hash);
    points_results_construct(&s->Points, hash);
    n = ts->NumStats;
    set_track_name_and_race_number(s->Base.ScreenHash,
                                   RACE_RESULTS_OBJ_TRACK_NAME,
                                   RACE_RESULTS_OBJ_RACE_NUMBER, 0);
    if (fred_use_tree_event(&Fred))
        flailer_printf(s->Base.ScreenHash, RACE_RESULTS_OBJ_TITLE,
                       get_translated_string(RR_LANG_EVENT_RESULTS),
                       (int)TheRaceEvent.nNumber);
    else
        flailer_set_language_id(s->Base.ScreenHash, RACE_RESULTS_OBJ_TITLE,
                                RR_LANG_RACE_RESULTS);
    for (i = 0; i < num_rows(n); i++)
        show_row(s, &ts->Stats[i], i + 1);
    for (k = n + 1; k <= RACE_RESULTS_ROWS; k++)
        hide_row(s->Base.ScreenHash, k);
    race_results_show_points(s);
    egs = pEndGameScreens;
    flailer_set_visibility(s->Base.ScreenHash, END_GAME_OBJ_PREVIOUS,
                           egs == NULL || endgame_screens_at_root(egs)
                               ? FLAILER_OBJECT_INVISIBLE
                               : FLAILER_OBJECT_VISIBLE);
    return &s->Base;
}

void race_results_scroll(EndGameMenusBase *m, BScreenMessage msg,
                         BScreenCallbackData *data)
{
    RaceResultsScreen *s = (RaceResultsScreen *)m;

    (void)data;
    if (msg == BMSG_MENUITEM_PAD_LEFT)
        slideshow_stats_change_stats(&s->Stats, -1);
    else if (msg == BMSG_MENUITEM_PAD_RIGHT)
        slideshow_stats_change_stats(&s->Stats, 1);
}

void race_results_tick(EndGameMenusBase *m, BScreenMessage msg,
                       BScreenCallbackData *data)
{
    RaceResultsScreen *s = (RaceResultsScreen *)m;

    (void)msg;
    (void)data;
    slideshow_stats_tick(&s->Stats);
    points_results_tick(&s->Points);
}

void race_results_destroy(EndGameMenusBase *m, int32_t flags)
{
    RaceResultsScreen *s = (RaceResultsScreen *)m;

    m->vt = &kRaceResultsVTable;
    points_results_destroy(&s->Points, 2);
    slideshow_stats_destroy(&s->Stats, 2);
    endgame_menus_base_destroy(m, flags);
}
