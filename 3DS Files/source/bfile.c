// bfile -- see bfile.h. Port-only: the SD card's files through stdio.

#include "bfile.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "gamedata.h"

struct bFile {
    FILE   *fp;
    int32_t size;
    int32_t reads;    // reads whose callback has not run yet
    int32_t closed;
};

// One read is in flight at a time under QueuedFile; this is room to spare.
#define BFILE_MAX_DONE 16

static struct {
    bFile        *f;
    bFileCallback cb;
    intptr_t      param;
} done[BFILE_MAX_DONE];
static int ndone;

static int full_path(const char *name, char *out)
{
    char rel[GAMEDATA_MAX_PATH];
    int  i;

    for (i = 0; name[i] != '\0' && i + 1 < GAMEDATA_MAX_PATH; i++)
        rel[i] = name[i] == '\\' ? '/' : name[i];
    rel[i] = '\0';
    return name[i] == '\0'
           && gamedata_path(rel, out, GAMEDATA_MAX_PATH) != NULL;
}

// The card holds the disc's big .LZC bundles expanded, under .BUN (the
// tracks' TRACKB<n>), and ResourceFile loads a file with no COMP header as
// it is. So a .LZC that is not there is looked for as the .BUN.
static FILE *open_on_card(const char *name)
{
    char   path[GAMEDATA_MAX_PATH];
    char   alt[GAMEDATA_MAX_PATH];
    FILE  *fp;
    size_t n = strlen(name);

    if (full_path(name, path) && (fp = fopen(path, "rb")) != NULL)
        return fp;
    if (n < 4 || n >= sizeof alt || strcmp(name + n - 4, ".LZC") != 0)
        return NULL;
    memcpy(alt, name, n - 4);
    memcpy(alt + n - 4, ".BUN", 5);
    if (!full_path(alt, path))
        return NULL;
    return fopen(path, "rb");
}

bFile *bOpen(const char *name)
{
    FILE  *fp;
    bFile *f;
    long   len;

    if ((fp = open_on_card(name)) == NULL)
        return NULL;
    fseek(fp, 0, SEEK_END);
    len = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    f = (bFile *)malloc(sizeof *f);
    if (f == NULL) {
        fclose(fp);
        return NULL;
    }
    f->fp = fp;
    f->size = len < 0 ? 0 : (int32_t)len;
    f->reads = 0;
    f->closed = 0;
    return f;
}

void bClose(bFile *f)
{
    if (f == NULL)
        return;
    if (f->fp != NULL) {
        fclose(f->fp);
        f->fp = NULL;
    }
    f->closed = 1;
    if (f->reads == 0)
        free(f);
}

int32_t bFileSize(bFile *f)
{
    return f->size;
}

int bFileIsExpanded(const char *name)
{
    char  path[GAMEDATA_MAX_PATH];
    FILE *fp;

    if (full_path(name, path) && (fp = fopen(path, "rb")) != NULL) {
        fclose(fp);
        return 0;
    }
    if ((fp = open_on_card(name)) == NULL)
        return 0;
    fclose(fp);
    return 1;
}

int32_t bFileSizeName(const char *name)
{
    bFile  *f = bOpen(name);
    int32_t size;

    if (f == NULL)
        return -1;
    size = f->size;
    bClose(f);
    return size;
}

void bSeek(bFile *f, int32_t pos, int32_t whence)
{
    if (f->fp != NULL)
        fseek(f->fp, pos, whence);
}

void bReadAsync(bFile *f, void *buf, int32_t n, bFileCallback cb,
                intptr_t param)
{
    if (f->fp != NULL && n > 0)
        (void)fread(buf, 1, (size_t)n, f->fp);
    if (cb == NULL)
        return;
    if (ndone == BFILE_MAX_DONE) {
        // Never with one read at a time; the read is in, so say so.
        cb(f, param);
        return;
    }
    f->reads++;
    done[ndone].f = f;
    done[ndone].cb = cb;
    done[ndone].param = param;
    ndone++;
}

void bRead(bFile *f, void *buf, int32_t n)
{
    bReadAsync(f, buf, n, NULL, 0);
}

void bServiceFileSystem(void)
{
    int n = ndone;
    int i;

    for (i = 0; i < n; i++) {
        bFile *f = done[i].f;

        done[i].cb(f, done[i].param);
        if (--f->reads == 0 && f->closed)
            free(f);
    }
    // A callback that started a read put it after the n just run.
    for (i = n; i < ndone; i++)
        done[i - n] = done[i];
    ndone -= n;
}

void *bGetFile(const char *name, int32_t *size, int32_t pool)
{
    bFile *f = bOpen(name);
    void  *buf;

    if (f == NULL) {
        fprintf(stderr, "bGetFile: %s is not on the card\n", name);
        abort();
    }
    if (size != NULL)
        *size = bFileSize(f);
    buf = bMalloc(bFileSize(f), name, 0, pool | 0x40);
    bRead(f, buf, bFileSize(f));
    bClose(f);
    return buf;
}
