# Boots NFSHP2-3DS.3dsx in Azahar, drives the boot sequence with real key
# presses, captures the window at each step, and reports a verdict from
# sdmc:/nfshp2_debug.txt. This is the only way the milestone gets checked
# without a person watching the emulator: a cross-check proves two
# implementations agree, and a clean log does not mean the screen is right, so
# every run also leaves PNGs to look at.
#
# The method is lifted from NFSU2-3DS/tools/run_azahar_test*.ps1, including the
# three things that took that project several sessions to get right:
#
#   * Pass the .3dsx, never the .cia. Azahar cannot boot a CIA from a path
#     argument -- it starts, silently loads nothing, and the run looks like an
#     app crash.
#   * Capture with PrintWindow(hWnd, hdc, PW_RENDERFULLCONTENT). A BitBlt or
#     CopyFromScreen of a GPU-composited window comes back black.
#   * Call SetProcessDPIAware() first. On a scaled display GetWindowRect
#     otherwise returns the logical rect, and the capture is silently cropped
#     to the top-left -- losing exactly the bottom screen, and looking fine.
#
# Input goes in with PostMessage(WM_KEYDOWN/WM_KEYUP), never SendKeys: Azahar
# must never be dragged into the foreground. Azahar's default keyboard profile
# is A='A', B='S', X='Z', Y='X', START='M', SELECT='N', D-pad = T/G/F/H.
#
# Usage:
#   powershell -File tools/run_azahar_test.ps1
#   powershell -File tools/run_azahar_test.ps1 -RunSeconds 30 -OutDir C:\shots

param(
    [int]$BootSeconds = 12,       # before the first capture: bundles decode slowly
    [int]$RunSeconds = 40,        # hard ceiling on the whole run
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_azahar" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not (Test-Path $AzaharExe)) { throw "Azahar not found at $AzaharExe" }
if (-not (Test-Path $Target3dsx)) { throw "Target .3dsx not found at $Target3dsx" }
if ($Target3dsx -like "*.cia") {
    throw "Refusing to run a .cia: Azahar cannot boot one from a path. Pass the .3dsx."
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Drawing;
public class Hp2Cap {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern int PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern IntPtr PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    public struct RECT { public int Left, Top, Right, Bottom; }
    public const uint WM_KEYDOWN = 0x0100;
    public const uint WM_KEYUP = 0x0101;
    public static void PressKey(IntPtr h, int vk) {
        PostMessage(h, WM_KEYDOWN, (IntPtr)vk, IntPtr.Zero);
        // Azahar runs well under 60 fps while texture packs decode; a shorter
        // hold lands inside one emulated frame and hidScanInput never sees it.
        System.Threading.Thread.Sleep(140);
        PostMessage(h, WM_KEYUP, (IntPtr)vk, IntPtr.Zero);
    }
    public static void CaptureToFile(IntPtr h, string path) {
        RECT r; GetWindowRect(h, out r);
        int w = r.Right - r.Left, ht = r.Bottom - r.Top;
        using (Bitmap bmp = new Bitmap(w, ht))
        using (Graphics g = Graphics.FromImage(bmp)) {
            IntPtr hdc = g.GetHdc();
            PrintWindow(h, hdc, 2);   // PW_RENDERFULLCONTENT
            g.ReleaseHdc(hdc);
            bmp.Save(path, System.Drawing.Imaging.ImageFormat.Png);
        }
    }
}
"@ -ReferencedAssemblies System.Drawing -ErrorAction SilentlyContinue

[void][Hp2Cap]::SetProcessDPIAware()

$VK_A = 65; $VK_S = 83; $VK_M = 77; $VK_N = 78; $VK_T = 84; $VK_G = 71

$debugLog  = Join-Path $env:APPDATA "Azahar\sdmc\nfshp2_debug.txt"
$azaharLog = Join-Path $env:APPDATA "Azahar\log\azahar_log.txt"
Remove-Item $debugLog  -ErrorAction SilentlyContinue
Remove-Item $azaharLog -ErrorAction SilentlyContinue
Get-ChildItem $OutDir -Filter *.png -ErrorAction SilentlyContinue | Remove-Item -Force

Write-Host "Launching Azahar with $Target3dsx"
$proc = Start-Process -FilePath $AzaharExe -ArgumentList "`"$Target3dsx`"" -PassThru

$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    $proc.Refresh()
    if ($proc.HasExited) { throw "Azahar exited before opening a window" }
    if ($proc.MainWindowHandle -ne 0) { break }
    Start-Sleep -Milliseconds 250
}
$hwnd = $proc.MainWindowHandle
if ($hwnd -eq 0) { $proc | Stop-Process -Force; throw "no Azahar window" }

$start = Get-Date
function Elapsed { ((Get-Date) - $start).TotalSeconds }
function Alive { $proc.Refresh(); -not $proc.HasExited }

# Wait for a line matching $pattern in the app's own log, or give up.
function Wait-ForLog([string]$pattern, [int]$timeoutSec) {
    $end = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $end) {
        if (-not (Alive)) { return $false }
        if (Test-Path $debugLog) {
            $hit = Select-String -Path $debugLog -Pattern $pattern -Quiet -ErrorAction SilentlyContinue
            if ($hit) { return $true }
        }
        Start-Sleep -Milliseconds 300
    }
    return $false
}

$step = 0
function Shot([string]$tag) {
    if (-not (Alive)) { return }
    $script:step++
    $path = Join-Path $OutDir ("{0:d2}_{1}.png" -f $script:step, $tag)
    [Hp2Cap]::CaptureToFile($hwnd, $path)
    Write-Host ("  [{0,5:N1}s] {1}" -f (Elapsed), $path)
}

# --- the script the run follows -------------------------------------------
# BootAutoload pops on its first tick, the title screen opens EALOGO_EN.M3V,
# the movie runs three seconds, PRESS START comes up, START goes to the main
# menu, and the D-pad walks it.

Write-Host "Waiting for the main loop..."
$booted = Wait-ForLog "entering main loop" 60
Write-Host ("  main loop: {0}" -f $booted)

if ($booted) {
    $gotMovie = Wait-ForLog "^movie open " 20
    Write-Host ("  movie opened: {0}" -f $gotMovie)
    Start-Sleep -Milliseconds 1200
    Shot "movie-early"
    Start-Sleep -Seconds 2
    Shot "movie-late"

    # The title screen only shows PRESS START once every entry in
    # TitleMoviesToPlay has been stepped through.
    [void](Wait-ForLog "flow title idle" 20)
    Start-Sleep -Milliseconds 800
    Shot "title"

    [Hp2Cap]::PressKey($hwnd, $VK_M)          # START
    if (Wait-ForLog "flow enter New Main Menu" 10) {
        Start-Sleep -Milliseconds 900
        Shot "mainmenu"
        [Hp2Cap]::PressKey($hwnd, $VK_G)      # D-pad down
        Start-Sleep -Milliseconds 500
        Shot "mainmenu-down"
        [Hp2Cap]::PressKey($hwnd, $VK_G)
        Start-Sleep -Milliseconds 500
        Shot "mainmenu-down2"
        # MENUITEM_3 is Options. The flow has no Options screen registered,
        # so this is where it goes when asked for one it does not know.
        [Hp2Cap]::PressKey($hwnd, $VK_A)      # A, select
        Start-Sleep -Milliseconds 1200
        Shot "options"
        [Hp2Cap]::PressKey($hwnd, $VK_S)      # B, back out of the dead end
        Start-Sleep -Milliseconds 900
        Shot "back-to-menu"
    } else {
        Shot "start-did-nothing"
    }
}

# Ask the app to leave its main loop rather than killing it: SELECT switches
# to the screen viewer, where START breaks out. That is the only path that
# reaches the "left main loop" line, and it carries the texture-cache tally.
if ($booted -and (Alive)) {
    [Hp2Cap]::PressKey($hwnd, $VK_N)          # SELECT -> screen viewer
    Start-Sleep -Milliseconds 700
    Shot "viewer"
    [Hp2Cap]::PressKey($hwnd, $VK_M)          # START  -> leave the main loop
    Start-Sleep -Milliseconds 1500
}

while ((Elapsed) -lt $RunSeconds -and (Alive)) { Start-Sleep -Milliseconds 300 }

$survived = Alive
if ($survived) { $proc | Stop-Process -Force }
Start-Sleep -Milliseconds 600

# --- the verdict ------------------------------------------------------------

$dbg = @(); if (Test-Path $debugLog)  { $dbg = Get-Content $debugLog }
$az  = @(); if (Test-Path $azaharLog) { $az  = Get-Content $azaharLog }

$crashSigs = @("PANIC", "segfault", "Unhandled exception", "svcBreak")
$crash = $az | Where-Object { $l = $_; $crashSigs | Where-Object { $l -match $_ } }

$reached   = $dbg | Where-Object { $_ -match "entering main loop" }
$movieOpen = $dbg | Where-Object { $_ -match "^movie open " }
$movieDone = $dbg | Where-Object { $_ -match "^movie close after (\d+)/" }
$atMenu    = $dbg | Where-Object { $_ -match "flow enter New Main Menu" }
$leftLoop  = $dbg | Where-Object { $_ -match "^left main loop" }

$verdict = "UNKNOWN"
if (-not $reached)      { $verdict = "FAIL (never reached the main loop)" }
elseif ($crash)         { $verdict = "FAIL (crash: $($crash[0]))" }
elseif (-not $movieOpen){ $verdict = "FAIL (title screen never opened a movie)" }
elseif (-not $atMenu)   { $verdict = "PARTIAL (movie played, never reached the main menu)" }
elseif ($leftLoop)      { $verdict = "PASS (booted, movie played, reached the main menu, exited cleanly)" }
elseif (-not $survived) { $verdict = "FAIL (reached the menu, then died without leaving the main loop)" }
else                    { $verdict = "PASS (booted, movie played, reached the main menu)" }

Write-Host ""
Write-Host "=== nfshp2_debug.txt (last 30) ==="
$dbg | Select-Object -Last 30 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== azahar_log.txt errors ==="
$az | Where-Object { $_ -match "Error|Critical|PANIC" } | Select-Object -Last 12 |
    ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== Result ==="
Write-Host ("Verdict:    {0}" -f $verdict)
if ($movieOpen) { Write-Host ("Movie:      {0}" -f ($movieOpen | Select-Object -First 1)) } else { Write-Host "Movie:      (none opened)" }
if ($movieDone) { Write-Host ("Frames:     {0}" -f ($movieDone | Select-Object -First 1)) }
if ($leftLoop)  { Write-Host ("Textures:   {0}" -f ($leftLoop  | Select-Object -Last 1)) }
Write-Host ("Screenshots: {0} in {1}" -f $step, $OutDir)
