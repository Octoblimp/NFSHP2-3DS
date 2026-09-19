// NFSHP2-3DS -- bring-up stub.
//
// This is a placeholder entry point for Phase 0 (project scaffolding).
// It exists only to prove the copied build skeleton (Makefile, app.rsf,
// heapcfg.c, vp6/) actually compiles and boots on both Old3DS and New3DS
// before any real bWare/HP2 engine code is ported in. Real boot flow
// (kVideoStages[]-style logo/legal sequence) and frontend menu code lands
// in Phase 2 once the asset pipeline (Phase 1) can produce real movie/UI
// assets to drive it.

#include <3ds.h>
#include <citro2d.h>
#include <citro3d.h>
#include <stdio.h>
#include <string.h>

#include "heapcfg.h"

static void initPlatformPerf(void)
{
    bool isNew3DS = false;
    Result n3dsRes = APT_CheckNew3DS(&isNew3DS);
    if (R_SUCCEEDED(n3dsRes) && isNew3DS) {
        osSetSpeedupEnable(true);
    }
    APT_SetAppCpuTimeLimit(80);
}

int main(int argc, char** argv)
{
    gfxInitDefault();
    consoleInit(GFX_BOTTOM, NULL);

    initPlatformPerf();

    printf("NFSHP2-3DS bring-up stub\n");
    printf("Heap: asked=%luKB got=%luKB linear_got=%luKB\n",
           (unsigned long)(g_heapInfo.heapAsked / 1024),
           (unsigned long)(g_heapInfo.heapGot / 1024),
           (unsigned long)(g_heapInfo.linearGot / 1024));
    {
        bool isNew3DS = false;
        APT_CheckNew3DS(&isNew3DS);
        printf("New3DS: %s\n", isNew3DS ? "yes" : "no");
    }
    printf("\nPress START to exit.\n");

    while (aptMainLoop()) {
        hidScanInput();
        u32 kDown = hidKeysDown();
        if (kDown & KEY_START) break;

        gfxFlushBuffers();
        gfxSwapBuffers();
        gspWaitForVBlank();
    }

    gfxExit();
    return 0;
}
