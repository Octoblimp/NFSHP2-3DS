// fred -- see fred.h.

#include "fred.h"

#include <string.h>

#include "cartypeinfo.h"
#include "configitems.h"
#include "edisplay.h"
#include "raceparams.h"
#include "track.h"

FrontendDatabase Fred;                          // retail 0x002fc050

void (*gFredAudioOptionsDefaultsFn)(uint8_t *ao);
const char *(*gFredTranslateFn)(int32_t id);
int32_t (*gIsCarUnlockedFn)(int32_t carType, int32_t gameType);

int32_t DisplayCalibrationOriginalX;            // gp-16896
int32_t DisplayCalibrationOriginalY;            // gp-16892

// The translated strings InitWithDefaults names the two players with.
#define FRED_PLAYER1_NAME_ID 0x27165
#define FRED_PLAYER2_NAME_ID 0x27166

// The FPI each player's settings name is bStrNCpy'd into, 11 bytes.
#define FRED_NAME_COPY 11

uint8_t *fred_bytes(void)
{
    return (uint8_t *)&Fred;
}

// bStrNCpy, 0x002535a0, as resource.c has it: up to n bytes, stopping
// after the terminator, and none when n runs out first.
static void b_strncpy(char *dst, const char *src, int32_t n)
{
    int32_t i;

    for (i = 0; i < n; i++) {
        dst[i] = src[i];
        if (src[i] == '\0')
            break;
    }
}

static const char *translate(int32_t id)
{
    const char *s = gFredTranslateFn != NULL ? gFredTranslateFn(id) : NULL;

    return s != NULL ? s : "NOT TRANSLATED PROPERLY";
}

static int32_t is_car_unlocked(int32_t type, int32_t gameType)
{
    return gIsCarUnlockedFn != NULL ? gIsCarUnlockedFn(type, gameType) : 0;
}

// ------------------------------------------------------- the constructor

// Retail 0x00187c58; the demo's _GLOBAL_$I$Fred is 0x0017fcd8.
void fred_static_init(void)
{
    FrontendDatabase *f = &Fred;
    int i, j, p;

    for (i = 0; i < 32; i++) {
        uint8_t *e = f->AudioOptionsScreenData + 28 + 4 * i;

        e[0] = 0;
        e[1] = 0;
        e[2] = 0;
    }
    f->AudioOptionsScreenData[175] = 0;
    for (i = 0; i < FRED_NUM_STATS; i++) {
        TransientStatsElement *s = &f->TransientStatsTable.Stats[i];

        s->RaceTime.PackedTime = 0;
        s->BestLapTime.PackedTime = 0;
        for (j = 0; j < 11; j++)
            s->LapTimes[j].PackedTime = 0;
    }
    for (i = 0; i < FRED_NUM_TOTAL_TIMES; i++)
        f->ChallengeHighScores.TotalTimesTable[i].Time.PackedTime = 0;
    for (i = 0; i < FRED_NUM_LAP_TIMES; i++)
        f->ChallengeHighScores.LapTimesTable[i].Time.PackedTime = 0;
    for (p = 0; p < 2; p++) {
        FrontendPlayerInfo *fpi = &f->FrontendPlayers[p];

        for (i = 0; i < FRED_NUM_CAR_TYPES; i++) {
            fpi->aCarStatus[i].nStatus = CAR_STATUS_HIDDEN;
            fpi->aCarStatus[i].nSkins = 0;
            fpi->aCarStatus[i].bDashAvailable = 0;
        }
        fpi->mPlayerSettings.BestLapTimeRecord.PackedTime = 0;
        fpi->mPlayerSettings.BestTotalTimeRecord.PackedTime = 0;
        for (i = 0; i < FRED_NUM_GAME_MODES; i++) {
            RideInfo *r = &fpi->RideInfoByGameMode[i];

            r->Type = -1;
            r->InstanceIndex = 0;
            r->SkinNumber = 0;
            r->HasDash = 0;
            r->CanBeVertexDamaged = 0;
        }
    }
}

// ------------------------------------------------- FrontendPlayerInfo

void fpi_set_character_info(FrontendPlayerInfo *p, const CharacterInfo *ci)
{
    if (ci != NULL)
        memcpy(&p->mCharacterInfo, ci, sizeof p->mCharacterInfo);
}

void fpi_set_character_info_index(FrontendPlayerInfo *p, int32_t i)
{
    fpi_set_character_info(p, get_character_info(i));
}

// 0x00187b08: every skin the car has, the first ten kept.
static void car_status_offer_all_skins(CarStatus *cs, const CarTypeInfo *ct)
{
    int32_t n = cartypeinfo_get_num_skins(ct);
    int32_t i;

    cs->nSkins = 0;
    for (i = 0; i < n; i++) {
        uint8_t s = (uint8_t)cartypeinfo_get_skin_number(ct, i);

        if (cs->nSkins < FRED_MAX_SKINS)
            cs->aSkins[cs->nSkins] = s;
        cs->nSkins++;
    }
}

void fpi_set_car_availability(FrontendPlayerInfo *p, int32_t status,
                              int32_t type, int32_t skin, int32_t dash)
{
    CarStatus *cs = &p->aCarStatus[type];

    cs->nStatus = status;
    cs->bDashAvailable = dash;
    cs->nSkins = 0;
    if (skin == -1) {
        car_status_offer_all_skins(cs, &CarTypeInfoArray[type]);
        return;
    }
    cs->aSkins[0] = (uint8_t)skin;
    cs->nSkins = 1;
}

int32_t fpi_get_car_status(const FrontendPlayerInfo *p, int32_t type)
{
    int32_t status;

    memcpy(&status, (const uint8_t *)p + type * (int32_t)sizeof(CarStatus),
           sizeof status);
    return status;
}

// 0x001879b8. The skin is looked for among those offered; with none
// offered, or not among them, the first is taken, and with a negative
// count the one asked for stands. The image reads the bytes from +4 for
// as many as nSkins counts, which can be more than the ten it keeps, so
// the search reads the record's bytes rather than past aSkins' end.
static void fpi_build_ride_info(FrontendPlayerInfo *p, RideInfo *ride,
                                int32_t type, uint32_t skin, int32_t dash)
{
    const CarStatus *cs = &p->aCarStatus[type];
    const uint8_t *skins = (const uint8_t *)cs + offsetof(CarStatus, aSkins);
    int32_t n = cs->nSkins;
    int32_t i = 0;
    int8_t hasDash = 0;

    if (n > 0) {
        while (i < n && skins[i] != skin)
            i++;
    }
    if (i == n)
        skin = cs->aSkins[0];
    if (dash != 0 && cs->bDashAvailable != 0)
        hasDash = CarTypeInfoArray[type].DashGeometryFilename[0] != 0;
    ride->Type = type;
    ride->SkinNumber = (int8_t)skin;
    ride->HasDash = hasDash;
    ride->CanBeVertexDamaged = 0;
    ride->InstanceIndex = 0;
}

void fpi_assign_car_of_type(FrontendPlayerInfo *p, int32_t mode,
                            int32_t type, uint32_t skin, int32_t dash)
{
    fpi_build_ride_info(p, &p->RideInfoByGameMode[mode], type, skin, dash);
}

void fpi_set_default_car_type(FrontendPlayerInfo *p, int32_t type,
                              uint32_t skin, int32_t dash)
{
    int32_t mode;

    for (mode = 0; mode < FRED_NUM_GAME_MODES; mode++)
        fpi_assign_car_of_type(p, mode, type, skin, dash);
}

// ------------------------------------------------------- the cars

// CarTypeInfo's GeometryFilename, `lb 64`: a type the disc has.
static int car_type_valid(const CarTypeInfo *ct)
{
    return ct->GeometryFilename[0] != 0;
}

void fred_make_challenge_cars_available(FrontendDatabase *f)
{
    int32_t type, p;

    if (f->GameType == GAME_TYPE_BE_A_COP) {
        for (type = 0; type < FRED_NUM_CAR_TYPES; type++) {
            const CarTypeInfo *ct = &CarTypeInfoArray[type];
            int32_t status;

            if (!car_type_valid(ct))
                continue;
            if (ct->UsageType != 1)
                status = CAR_STATUS_HIDDEN;
            else if (is_car_unlocked(type, f->GameType))
                status = CAR_STATUS_AVAILABLE;
            else
                status = ct->BeACopLockStatus;
            fpi_set_car_availability(&f->FrontendPlayers[0], status, type,
                                     -1, 0);
        }
        for (type = 0; type < FRED_NUM_CAR_TYPES; type++) {
            const CarTypeInfo *ct = &CarTypeInfoArray[type];
            int32_t status;

            if (!car_type_valid(ct))
                continue;
            if (ct->UsageType == 1)
                status = CAR_STATUS_HIDDEN;
            else if (is_car_unlocked(type, 3))
                status = CAR_STATUS_AVAILABLE;
            else if (bVersionE3 == 0)
                status = ct->InitialLockStatus;
            else
                status = ct->InitialLockStatus == CAR_STATUS_HIDDEN
                    ? CAR_STATUS_HIDDEN : CAR_STATUS_AVAILABLE;
            fpi_set_car_availability(&f->FrontendPlayers[1], status, type,
                                     -1, 0);
        }
        return;
    }
    for (p = 0; p < 2; p++) {
        for (type = 0; type < FRED_NUM_CAR_TYPES; type++) {
            const CarTypeInfo *ct = &CarTypeInfoArray[type];
            int32_t status;

            if (!car_type_valid(ct))
                continue;
            if (is_car_unlocked(type, f->GameType))
                status = CAR_STATUS_AVAILABLE;
            else if (bVersionE3 == 0)
                status = ct->InitialLockStatus;
            else if (ct->InitialLockStatus == CAR_STATUS_HIDDEN)
                status = CAR_STATUS_HIDDEN;
            else
                status = ct->UsageType == 1 ? CAR_STATUS_HIDDEN
                    : CAR_STATUS_AVAILABLE;
            fpi_set_car_availability(&f->FrontendPlayers[p], status, type,
                                     -1, 0);
        }
    }
}

// ------------------------------------------------------- the high scores

void high_score_table_init_stats_tables(HighScoreTable *t)
{
    int32_t i, k = 0;
    int32_t numbered = 1;
    int32_t next = 1;

    for (i = 1; i <= HighestTrackNumber; i++) {
        TrackInfo *ti = track_get_info(i);

        if (ti == NULL || !ti->IsValid
            || ti->TrackNumber != ti->SameAsTrackNumber)
            continue;
        ti->HighScoreIndex = numbered ? (int16_t)k : 0;
        k = next;
        numbered = next < 16;
        next++;
    }
    for (i = 1; i <= HighestTrackNumber; i++) {
        TrackInfo *ti = track_get_info(i);
        TrackInfo *twin;

        if (ti == NULL || !ti->IsValid
            || ti->TrackNumber == ti->SameAsTrackNumber)
            continue;
        // The image reads the twin's through NULL when there is none.
        twin = track_get_info(ti->SameAsTrackNumber);
        if (twin != NULL)
            ti->HighScoreIndex = twin->HighScoreIndex;
    }
    memset(t->TotalTimesTable, 0, sizeof t->TotalTimesTable);
    memset(t->LapTimesTable, 0, sizeof t->LapTimesTable);
    for (i = 0; i < FRED_NUM_TOTAL_TIMES; i++)
        t->TotalTimesTable[i].Time.PackedTime = 0x7fffffffu;
    for (i = 0; i < FRED_NUM_LAP_TIMES; i++)
        t->LapTimesTable[i].Time.PackedTime = 0x7fffffffu;
}

// ------------------------------------------------------- the setup data

void data_single_race_setup_defaults(int32_t *d)
{
    d[6] = 1;
    d[1] = 2;
    d[4] = 3;
    d[0] = 2;
    d[2] = 0;
    d[3] = 1;
    d[5] = 0;
}

void data_free_run_setup_defaults(int32_t *d)
{
    d[0] = 3;
    d[2] = 1;
    d[1] = 0;
}

void data_race_knockout_setup_defaults(int32_t *d)
{
    d[6] = 1;
    d[0] = 7;
    d[3] = 3;
    d[1] = 0;
    d[2] = 1;
    d[4] = 0;
    d[5] = 0;
}

void data_lap_knockout_setup_defaults(int32_t *d)
{
    d[5] = 1;
    d[0] = 4;
    d[3] = 3;
    d[1] = 0;
    d[2] = 1;
    d[4] = 0;
}

// The image reads track 11's TrackInfo with no test; without the table
// the port takes zeroes for its two fields.
void data_select_track_screen_defaults(int32_t *d)
{
    const TrackInfo *ti = track_get_info(11);

    d[1] = 2;
    d[0] = ti != NULL ? ti->SameAsTrackNumber : 0;
    d[2] = 0;
    d[3] = ti != NULL ? ti->TimeOfDay : 0;
}

void data_event_select_screen_defaults(int32_t *d)
{
    d[3] = 0;
    d[1] = 1;
    d[2] = 1;
    d[0] = 0;
}

void data_display_calibration_defaults(int32_t *d)
{
    eGetScreenDisplayOffsets(&DisplayCalibrationOriginalX,
                             &DisplayCalibrationOriginalY);
    eGetScreenDisplayOffsets(&d[0], &d[1]);
}

// ------------------------------------------------------- the defaults

void fred_init_with_defaults(FrontendDatabase *f)
{
    FrontendPlayerInfo *p0 = &f->FrontendPlayers[0];
    FrontendPlayerInfo *p1 = &f->FrontendPlayers[1];
    int32_t dash;
    int i;

    f->GameType = 0;
    for (i = 0; i < 2; i++)
        fpi_set_character_info_index(&f->FrontendPlayers[i], i);
    fred_make_challenge_cars_available(f);
    dash = config_skip_fe() != 0;
    fpi_set_car_availability(p0, CAR_STATUS_AVAILABLE, DefaultPlayer1CarType,
                             DefaultPlayer1SkinIndex, 1);
    fpi_set_car_availability(p1, CAR_STATUS_AVAILABLE, DefaultPlayer2CarType,
                             DefaultPlayer2SkinIndex, 1);
    fpi_set_default_car_type(p0, DefaultPlayer1CarType,
                             (uint32_t)DefaultPlayer1SkinIndex, dash);
    fpi_set_default_car_type(p1, DefaultPlayer2CarType,
                             (uint32_t)DefaultPlayer2SkinIndex, dash);
    player_settings_reset_to_defaults(&p0->mPlayerSettings);
    player_settings_reset_to_defaults(&p1->mPlayerSettings);
    p0->AccumulatedPoints = 0;
    p1->AccumulatedPoints = 0;
    f->NumPlayerCars = 1;
    f->Autosave = 0;
    f->SavedSizeofFred = (int32_t)sizeof(FrontendDatabase);
    // DataChallengeScreen (0x001b5e10) and DataBeTheCopSetup (0x001b93e0).
    f->ChallengeScreenData[0] = 1;
    f->ChallengeScreenData[1] = 3;
    f->ChallengeScreenData[2] = 1;
    f->ChallengeScreenData[3] = 1;
    f->ChallengeScreenData[4] = 0;
    data_single_race_setup_defaults(f->SingleRaceSetupData);
    data_free_run_setup_defaults(f->FreeRunSetupData);
    data_race_knockout_setup_defaults(f->RaceKnockoutSetupData);
    data_lap_knockout_setup_defaults(f->LapKnockoutSetupData);
    f->BeTheCopSetupData[0] = 2;
    f->BeTheCopSetupData[1] = 0;
    f->BeTheCopSetupData[2] = 1;
    f->BeTheCopSetupData[3] = 0;
    f->BeTheCopSetupData[4] = 1;
    data_select_track_screen_defaults(f->SelectTrackScreenData);
    data_event_select_screen_defaults(f->SelectedEventData);
    if (gFredAudioOptionsDefaultsFn != NULL)
        gFredAudioOptionsDefaultsFn(f->AudioOptionsScreenData);
    global_display_settings_init_with_defaults(&f->DisplayOptionsData);
    data_display_calibration_defaults(f->DisplayCalibrationData);
    f->MainMenuOpts[0] = 0;
    f->MainMenuOpts[1] = 1;
    f->DesiredControllerConfig[0] = 0;
    f->DesiredControllerConfig[1] = 0;
    f->nCurrentEvent = 0;
    memset(f->ChampionshipState, 0, sizeof f->ChampionshipState);
    memset(f->HotPursuitState, 0, sizeof f->HotPursuitState);
    f->pUltimateState = 0;
    high_score_table_init_stats_tables(&f->ChallengeHighScores);
    memset(f->HighScoreNameTable, 0, sizeof f->HighScoreNameTable);
    b_strncpy(p0->mPlayerSettings.PlayerName,
              translate(FRED_PLAYER1_NAME_ID), FRED_NAME_COPY);
    b_strncpy(p1->mPlayerSettings.PlayerName,
              translate(FRED_PLAYER2_NAME_ID), FRED_NAME_COPY);
    f->bRaceWasAborted = 0;
}

void init_fred(void)
{
    fred_init_with_defaults(&Fred);
}
