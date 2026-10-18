// Host test for replaybar.c: replaybar_retouch on the images and sheets
// tools/replaybar_check.py writes. argv[1] is a script, a case a line:
//
//     case <w> <h> <image file | -> <sheet file | -> <sheet size>
//
// An image file holds w * h * 4 bytes and a sheet file `sheet size`; "-"
// passes NULL. Each case prints "case N ret R", then each row's CRC-32 of
// the image after the call ("row y crc"), and "faults 0" ends the run.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "replaybar.h"

static uint32_t crc_table[256];

static void crc_init(void)
{
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;

        for (int k = 0; k < 8; k++)
            c = (c & 1) ? 0xedb88320u ^ (c >> 1) : c >> 1;
        crc_table[i] = c;
    }
}

static uint32_t crc32(const uint8_t *p, size_t n)
{
    uint32_t c = 0xffffffffu;

    while (n--)
        c = crc_table[(c ^ *p++) & 0xff] ^ (c >> 8);
    return c ^ 0xffffffffu;
}

// The file's bytes in a buffer of `n`, or NULL for "-". Exits on a short
// file: the script is the checker's own.
static uint8_t *load(const char *path, size_t n)
{
    uint8_t *buf;
    FILE *f;

    if (strcmp(path, "-") == 0)
        return NULL;
    buf = malloc(n ? n : 1);
    f = fopen(path, "rb");
    if (buf == NULL || f == NULL || fread(buf, 1, n, f) != n) {
        printf("cannot read %s\n", path);
        exit(2);
    }
    fclose(f);
    return buf;
}

int main(int argc, char **argv)
{
    char line[1024], image[512], sheet[512];
    unsigned w, h;
    unsigned long sheetSize;
    int n = 0;
    FILE *script;

    if (argc != 2 || (script = fopen(argv[1], "r")) == NULL) {
        printf("usage: replaybar_test <script>\n");
        return 2;
    }
    crc_init();
    while (fgets(line, sizeof line, script) != NULL) {
        uint8_t *img, *sh;
        int32_t ret;

        if (sscanf(line, "case %u %u %511s %511s %lu", &w, &h, image, sheet,
                   &sheetSize) != 5)
            continue;
        img = load(image, (size_t)w * h * 4);
        sh = load(sheet, sheetSize);
        ret = replaybar_retouch(img, w, h, sh, sheetSize);
        printf("case %d ret %d\n", n++, (int)ret);
        if (img != NULL)
            for (unsigned y = 0; y < h; y++)
                printf("row %u %08x\n", y,
                       (unsigned)crc32(img + (size_t)y * w * 4,
                                       (size_t)w * 4));
        free(img);
        free(sh);
    }
    fclose(script);
    printf("faults 0\n");
    return 0;
}
