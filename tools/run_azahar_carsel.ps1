# Boots NFSHP2-3DS.3dsx in Azahar and walks to car select (bcarsel.c, step
# 16): Hot Pursuit, You're The Cop, A on Players. It captures the screen at
# rest, after a car change, a colour change and the first popup, and
# reports the selector's own log lines. The capture and key methods are
# run_azahar_test.ps1's; see its header for why each is the way it is.
#
# Usage:
#   powershell -File tools/run_azahar_carsel.ps1
#   powershell -File tools/run_azahar_carsel.ps1 -OutDir C:\shots

param(
    [int]$BootSeconds = 12,       # before the first capture: bundles decode slowly
    [int]$RunSeconds = 90,        # hard ceiling on the whole run
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = "",
    [switch]$Choose               # through both popups to Select Track and back
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_carsel" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not (Test-Path $AzaharExe)) { throw "Azahar not found at $AzaharExe" }
if (-not (Test-Path $Target3dsx)) { throw "Target .3dsx not found at $Target3dsx" }
if ($Target3dsx -like "*.cia") {
    throw "Refusing to run a .cia: Azahar cannot boot one from a path. Pass the .3dsx."
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Drawing;
public class Hp2Cap {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    // Azahar's "Update Available" dialog takes the foreground on launch and
    // blocks the emulator window from acting on posted keys, so a run that
    // ignores it presses its way into a dialog and then reports that the
    // app never got anywhere. Anything owned by the process that is
    // visible, titled, and not titled "Azahar" is one of these; the
    // emulator window and its Qt helper windows are all either titled
    // "Azahar" or untitled. See docs/formats/camera.md.
    static uint sPid; static IntPtr sKeep; static int sClosed;
    public static int DismissPopups(uint pid, IntPtr keep) {
        sPid = pid; sKeep = keep; sClosed = 0;
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint q; GetWindowThreadProcessId(h, out q);
            if (q != sPid || h == sKeep || !IsWindowVisible(h)) { return true; }
            StringBuilder c = new StringBuilder(256); GetClassName(h, c, 256);
            if (!c.ToString().StartsWith("Qt")) { return true; }
            StringBuilder t = new StringBuilder(256); GetWindowText(h, t, 256);
            string title = t.ToString();
            if (title.Length == 0 || title.StartsWith("Azahar")) { return true; }
            PostMessage(h, 0x0010, IntPtr.Zero, IntPtr.Zero);   // WM_CLOSE
            sClosed++;
            return true;
        }, IntPtr.Zero);
        return sClosed;
    }
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

$VK_A = 65; $VK_S = 83; $VK_M = 77; $VK_N = 78; $VK_T = 84; $VK_G = 71; $VK_H = 72; $VK_F = 70

$debugLog  = Join-Path $env:APPDATA "Azahar\sdmc\nfshp2_debug.txt"
. (Join-Path $PSScriptRoot "azahar_debuglog.ps1")   # DebugLog 1
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
$closed = [Hp2Cap]::DismissPopups([uint32]$proc.Id, $hwnd)
if ($closed -gt 0) { Write-Host "  dismissed $closed launch dialog(s)" }

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

# Wait until $pattern has matched $count lines of the app's log.
function Wait-ForLogCount([string]$pattern, [int]$count, [int]$timeoutSec) {
    $end = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $end) {
        if (-not (Alive)) { return $false }
        if (Test-Path $debugLog) {
            $hits = @(Select-String -Path $debugLog -Pattern $pattern -ErrorAction SilentlyContinue)
            if ($hits.Count -ge $count) { return $true }
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
# The boot as run_azahar_test.ps1 has it, then Hot Pursuit, You're The Cop,
# and A on Players, which goes to Select Car. There: the screen at rest,
# right twice through the cars (locked ones, with the unlock box), left
# twice back to the first, down for the next colour, and A, which summons
# the first popup; B cancels it and B again goes back.

$loading = Wait-ForLog "global chunks loaded" 60
Write-Host ("  LOADING drawn: {0}" -f $loading)

Write-Host "Waiting for the main loop..."
$booted = Wait-ForLog "entering main loop" 60
Write-Host ("  main loop: {0}" -f $booted)

$atCarSel = $false
if ($booted) {
    $gotLang = Wait-ForLog "flow enter Language Options Pre FE" 30
    Write-Host ("  language screen: {0}" -f $gotLang)
    if ($gotLang) {
        Start-Sleep -Milliseconds 1500
        [Hp2Cap]::PressKey($hwnd, $VK_A)      # A, English
    }

    $gotIntro = Wait-ForLog "^movie open MOVIES/INTRO/NFSINTRO" 25
    Write-Host ("  intro opened: {0}" -f $gotIntro)
    if ($gotIntro) {
        Start-Sleep -Seconds 2
        [Hp2Cap]::PressKey($hwnd, $VK_M)      # START: stop the intro
        [void](Wait-ForLog "flow title skip" 10)
    } else {
        [void](Wait-ForLog "flow title idle" 20)
    }
    [void](Wait-ForLog "flow vis object b5761d00 b070dbc9 1" 15)
    Start-Sleep -Milliseconds 900
    [Hp2Cap]::PressKey($hwnd, $VK_M)          # START

    if (Wait-ForLog "flow enter New Main Menu" 10) {
        Start-Sleep -Milliseconds 1200
        [Hp2Cap]::PressKey($hwnd, $VK_A)      # A, Hot Pursuit
        if (Wait-ForLog "flow enter Cops On Mode Select" 10) {
            Start-Sleep -Milliseconds 900
            [Hp2Cap]::PressKey($hwnd, $VK_G)  # down, You're The Cop
            Start-Sleep -Milliseconds 500
            [Hp2Cap]::PressKey($hwnd, $VK_A)  # A
            if (Wait-ForLog "flow enter ChallengeBeACop" 10) {
                Start-Sleep -Milliseconds 1200
                Shot "beacop"
                [Hp2Cap]::PressKey($hwnd, $VK_A)  # A on Players
                $atCarSel = Wait-ForLog "flow enter Select Car" 15
                Write-Host ("  car select: {0}" -f $atCarSel)
            } else {
                Shot "beacop-missing"
            }
        } else {
            Shot "copson-missing"
        }
    } else {
        Shot "start-did-nothing"
    }
}

if ($atCarSel) {
    Start-Sleep -Milliseconds 800
    Shot "carsel-in"
    Start-Sleep -Milliseconds 2000
    Shot "carsel"
    [Hp2Cap]::PressKey($hwnd, $VK_H)          # right, the next car
    Start-Sleep -Milliseconds 1200
    Shot "carsel-right"
    [Hp2Cap]::PressKey($hwnd, $VK_H)          # right
    Start-Sleep -Milliseconds 1200
    Shot "carsel-right2"
    [Hp2Cap]::PressKey($hwnd, $VK_F)          # left, back one
    Start-Sleep -Milliseconds 1200
    Shot "carsel-left"
    # Back to the first car, the one unlocked: a locked car takes neither
    # a colour nor A.
    [Hp2Cap]::PressKey($hwnd, $VK_F)
    Start-Sleep -Milliseconds 2500
    Shot "carsel-first"
    [Hp2Cap]::PressKey($hwnd, $VK_G)          # down, the next colour
    Start-Sleep -Milliseconds 900
    Shot "carsel-skin"
    [Hp2Cap]::PressKey($hwnd, $VK_A)          # A, the first popup
    Start-Sleep -Milliseconds 1500
    Shot "carsel-popup"
    [Hp2Cap]::PressKey($hwnd, $VK_S)          # B, cancel it
    Start-Sleep -Milliseconds 1200
    Shot "carsel-cancel"
    if ($Choose) {
        # Through both popups: Automatic, then the handling, which goes on
        # to Select Track; B from there comes back to car select.
        [Hp2Cap]::PressKey($hwnd, $VK_A)      # A, the transmission again
        Start-Sleep -Milliseconds 1500
        [Hp2Cap]::PressKey($hwnd, $VK_A)      # A, Automatic
        Start-Sleep -Milliseconds 1500
        Shot "carsel-handling"
        [Hp2Cap]::PressKey($hwnd, $VK_A)      # A, the first handling
        $onTrack = Wait-ForLog "flow enter Select Track" 10
        Write-Host ("  on to Select Track: {0}" -f $onTrack)
        Start-Sleep -Milliseconds 1200
        Shot "selecttrack"
        [Hp2Cap]::PressKey($hwnd, $VK_S)      # B, back to car select
        Start-Sleep -Milliseconds 2500
        Shot "carsel-again"
    }
    [Hp2Cap]::PressKey($hwnd, $VK_S)          # B, back to You're The Cop
    Start-Sleep -Milliseconds 1500
    Shot "carsel-back"
}

if ($booted -and (Alive)) {
    [Hp2Cap]::PressKey($hwnd, $VK_N)          # SELECT -> screen viewer
    Start-Sleep -Milliseconds 700
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
$leftLoop = $dbg | Where-Object { $_ -match "^left main loop" }
$carsel   = $dbg | Where-Object { $_ -match "^(flow )?carsel " }
# Azahar only logs a read of unmapped memory; the device takes a data abort.
$unmapped = $az | Where-Object { $_ -match "unmapped (Read|Write)" }

$verdict = "UNKNOWN"
if (-not $booted)       { $verdict = "FAIL (never reached the main loop)" }
elseif ($crash)         { $verdict = "FAIL (crash: $($crash[0]))" }
elseif ($unmapped)      { $verdict = "FAIL ($(@($unmapped).Count) unmapped accesses, first: $(@($unmapped)[0]))" }
elseif (-not $atCarSel) { $verdict = "PARTIAL (never reached Select Car)" }
elseif (-not $carsel)   { $verdict = "PARTIAL (Select Car came up, but the selector logged nothing)" }
elseif ($leftLoop)      { $verdict = "PASS (car select walked, exited cleanly)" }
elseif (-not $survived) { $verdict = "FAIL (walked car select, then died without leaving the main loop)" }
else                    { $verdict = "PASS (car select walked)" }

Write-Host ""
Write-Host "=== carsel lines ==="
$carsel | Select-Object -Last 20 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== nfshp2_debug.txt (last 25) ==="
$dbg | Select-Object -Last 25 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== azahar_log.txt errors ==="
$az | Where-Object { $_ -match "Error|Critical|PANIC" } | Select-Object -Last 12 |
    ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== Result ==="
Write-Host ("Verdict:    {0}" -f $verdict)
Write-Host ("Screenshots: {0} in {1}" -f $step, $OutDir)
