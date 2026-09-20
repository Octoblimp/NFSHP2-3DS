#include "gamedata.h"

#include <stdio.h>
#include <string.h>

static char s_root[GAMEDATA_MAX_PATH];
static bool s_ready;

static const char* const kDefaults[] = {
    "sdmc:/3ds/NFSHP2-3DS/data",
    "sdmc:/NFSHP2",
};

static const char* const kConfigDirs[] = {
    "",                        // next to the executable
    "sdmc:/3ds/NFSHP2-3DS/",
};

static void set_root(const char* path)
{
    size_t n = strlen(path);
    while (n > 0 && (path[n - 1] == '/' || path[n - 1] == '\\')) n--;
    if (n >= sizeof(s_root)) n = sizeof(s_root) - 1;
    memcpy(s_root, path, n);
    s_root[n] = '\0';
}

static bool file_exists(const char* path)
{
    FILE* f = fopen(path, "rb");
    if (!f) return false;
    fclose(f);
    return true;
}

// A candidate counts only if the sentinel is in it, so a stale config file
// falls through to a default rather than leaving the game pointed at nothing.
static bool candidate_ok(const char* dir)
{
    char path[GAMEDATA_MAX_PATH];
    set_root(dir);
    if (!gamedata_path(GAMEDATA_SENTINEL, path, sizeof(path))) return false;
    return file_exists(path);
}

// The config file's first non-empty, non-comment line, trimmed.
static bool read_config(const char* dir, char* out, size_t cap)
{
    char path[GAMEDATA_MAX_PATH];
    if (snprintf(path, sizeof(path), "%s%s", dir, GAMEDATA_CONFIG)
        >= (int)sizeof(path))
        return false;

    FILE* f = fopen(path, "r");
    if (!f) return false;

    char line[GAMEDATA_MAX_PATH];
    bool got = false;
    while (fgets(line, sizeof(line), f)) {
        char* p = line;
        while (*p == ' ' || *p == '\t') p++;
        if (*p == '#' || *p == '\r' || *p == '\n' || *p == '\0') continue;
        char* end = p + strlen(p);
        while (end > p && (end[-1] == '\r' || end[-1] == '\n'
                           || end[-1] == ' ' || end[-1] == '\t')) end--;
        *end = '\0';
        // A bare relative path in the config means somewhere under the SD
        // card root; anything with a drive prefix is taken as written.
        if (strchr(p, ':') == NULL)
            got = snprintf(out, cap, "sdmc:/%s", p) < (int)cap;
        else
            got = snprintf(out, cap, "%s", p) < (int)cap;
        break;
    }
    fclose(f);
    return got;
}

bool gamedata_init(void)
{
    if (s_ready) return true;

    char configured[GAMEDATA_MAX_PATH];
    for (size_t i = 0; i < sizeof(kConfigDirs) / sizeof(kConfigDirs[0]); i++) {
        if (!read_config(kConfigDirs[i], configured, sizeof(configured)))
            continue;
        if (candidate_ok(configured)) { s_ready = true; return true; }
    }
    for (size_t i = 0; i < sizeof(kDefaults) / sizeof(kDefaults[0]); i++)
        if (candidate_ok(kDefaults[i])) { s_ready = true; return true; }

    // s_root holds the last candidate tried, which is what an error message
    // wants to show.
    return false;
}

const char* gamedata_root(void)
{
    return s_root;
}

char* gamedata_path(const char* rel, char* out, size_t cap)
{
    while (*rel == '/') rel++;
    int n = snprintf(out, cap, "%s/%s", s_root, rel);
    if (n < 0 || (size_t)n >= cap) return NULL;
    return out;
}

bool gamedata_exists(const char* rel)
{
    char path[GAMEDATA_MAX_PATH];
    if (!gamedata_path(rel, path, sizeof(path))) return false;
    return file_exists(path);
}
