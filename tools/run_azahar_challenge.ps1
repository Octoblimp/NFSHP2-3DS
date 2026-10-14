# Boots NFSHP2-3DS.3dsx in Azahar and walks the Challenge screen and the
# four race setups it leads to (TASKS 37b-1, bsetup.c): World Racing,
# Challenge, then Setup with each race type in turn -- Single Race,
# Knockout, Lap Knockout, Free Run -- stepping the first rows of each and
# going back, and last A on Free Run Setup, which goes to car select. It
# captures each screen and reports the flow's lines. The capture and key
# methods are run_azahar_test.ps1's; see its header for why each is the
# way it is.
#
# sdmc:/nfshp2_config.txt must not set SkipFE: the run needs the frontend.
#
# Usage:
#   powershell -File tools/run_azahar_challenge.ps1
#   powershell -File tools/run_azahar_challenge.ps1 -CopsOn

param(
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = "",
    [switch]$CopsOn               # Hot Pursuit's Challenge, not World Racing's
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_challenge" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not (Test-Path $AzaharExe)) { throw "Azahar not found at $AzaharExe" }
if (-not (Test-Path $Target3dsx)) { throw "Target .3dsx not found at $Target3dsx" }
if ($Target3dsx -like "*.cia") {
    throw "Refusing to run a .cia: Azahar cannot boot one from a path. Pass the .3dsx."
}
$config = Join-Path $env:APPDATA "Azahar\sdmc\nfshp2_config.txt"
if ((Test-Path $config) -and (Select-String -Path $config -Pattern "^\s*SkipFE\s+[1-9]" -Quiet)) {
    throw "$config turns SkipFE on; this run needs the frontend"
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
    public static void KeyDown(IntPtr h, int vk) { PostMessage(h, WM_KEYDOWN, (IntPtr)vk, IntPtr.Zero); }
    public static void KeyUp(IntPtr h, int vk) { PostMessage(h, WM_KEYUP, (IntPtr)vk, IntPtr.Zero); }
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
# The boot as run_azahar_quickrace.ps1 has it, then World Racing (down, A)
# or Hot Pursuit (A), and Challenge, the Mode Select's next item down on
# World Racing and two down on Hot Pursuit. On Challenge, down to Setup and
# A; on each setup, a right on the first row and on the second, then B.
# Back on Challenge the menu is on Setup again, the item it was left on
# (FlailerScreen's SavedMenuItemNumber): up twice to Race Type, right for
# the next one, down twice to Setup (once for Free Run with the cops off,
# whose Skill Level is grayed), A.
#
# The debug log lands up to ~7 s late, and a second press is not harmless:
# START twice on the title is Hot Pursuit picked. So a press that changes
# screen is repeated only after 20 s with nothing, and the presses on a
# screen wait for its first HIGHLIGHT, counted, since Challenge is visited
# five times.

# How many lines of the app's log match $pattern now.
function LogCount([string]$pattern) {
    if (-not (Test-Path $debugLog)) { return 0 }
    return @(Select-String -Path $debugLog -Pattern $pattern -ErrorAction SilentlyContinue).Count
}

# Press $vk until $pattern has matched $count lines, waiting $waitSec
# after each press; $tries presses at most.
function Press-UntilCount([int]$vk, [string]$pattern, [int]$count,
                          [int]$tries, [int]$waitSec) {
    for ($i = 0; $i -lt $tries; $i++) {
        if (-not (Alive)) { return $false }
        [Hp2Cap]::PressKey($hwnd, $vk)
        if (Wait-ForLogCount $pattern $count $waitSec) { return $true }
    }
    return $false
}

# Press $vk to go to $screen, then wait for the screen's first HIGHLIGHT.
function Enter-Screen([int]$vk, [string]$screen) {
    $enter = "flow enter " + $screen + " [0-9a-f]{8}"
    $hl = "screen " + $screen + " [0-9a-f]{8} .* last HIGHLIGHT"
    $n = LogCount $enter
    $h = LogCount $hl
    if (-not (Press-UntilCount $vk $enter ($n + 1) 2 20)) { return $false }
    [void](Wait-ForLogCount $hl ($h + 1) 20)
    Start-Sleep -Milliseconds 1000
    return $true
}

function Press([int]$vk) {
    if (-not (Alive)) { return }
    [Hp2Cap]::PressKey($hwnd, $vk)
    Start-Sleep -Milliseconds 700
}

$loading = Wait-ForLog "global chunks loaded" 60
Write-Host ("  LOADING drawn: {0}" -f $loading)

Write-Host "Waiting for the main loop..."
$booted = Wait-ForLog "entering main loop" 60
Write-Host ("  main loop: {0}" -f $booted)

$atChallenge = $false
if ($booted) {
    $gotLang = Wait-ForLog "flow enter Language Options Pre FE" 30
    Write-Host ("  language screen: {0}" -f $gotLang)
    if ($gotLang) {
        Start-Sleep -Milliseconds 1500
        [void](Press-UntilCount $VK_A "flow leave Language Options Pre FE" 1 2 20)
    }

    $gotIntro = Wait-ForLog "^movie open MOVIES/INTRO/NFSINTRO" 40
    Write-Host ("  intro opened: {0}" -f $gotIntro)
    if ($gotIntro) {
        Start-Sleep -Seconds 2
        [void](Press-UntilCount $VK_M "flow title skip" 1 2 20)   # START
    } else {
        [void](Wait-ForLog "flow title idle" 20)
    }
    [void](Wait-ForLog "flow vis object b5761d00 b070dbc9 1" 15)
    Start-Sleep -Milliseconds 900

    $modeSelect = "Cops Off Mode Select"
    if ($CopsOn) { $modeSelect = "Cops On Mode Select" }
    if (Enter-Screen $VK_M "New Main Menu") {   # START
        $atMode = $false
        if ($CopsOn) {
            $atMode = Enter-Screen $VK_A $modeSelect
        } elseif (Press-UntilCount $VK_G "flow bracket 708a0bf1" 1 2 20) {
            # down, World Racing
            $atMode = Enter-Screen $VK_A $modeSelect
        }
        if ($atMode) {
            Press $VK_G                       # down, Challenge
            if ($CopsOn) { Press $VK_G }
            $atChallenge = Enter-Screen $VK_A "Challenge"
            Write-Host ("  Challenge: {0}" -f $atChallenge)
            if (-not $atChallenge) { Shot "challenge-missing" }
        } else {
            Shot "modeselect-missing"
        }
    } else {
        Shot "start-did-nothing"
    }
}

$setups = @("Single Race Setup", "Knockout Setup", "Lap Knockout Setup",
            "Free Run Setup")
$reached = @()
$atCarSel = $false
for ($i = 0; $atChallenge -and $i -lt $setups.Count; $i++) {
    $name = $setups[$i]
    if ($i -eq 0) {
        Shot "challenge"
        Press $VK_G; Press $VK_G; Press $VK_G       # down to Setup
    } else {
        Press $VK_T; Press $VK_T                    # up from Setup, Race Type
        Press $VK_H                                 # right, the next type
        Start-Sleep -Milliseconds 800
        Shot ("challenge-type{0}" -f $i)
        Press $VK_G                                 # down to Setup,
        # past Skill Level, which Free Run with the cops off grays and the
        # menu steps over
        if ($i -ne 3 -or $CopsOn) { Press $VK_G }
    }
    if (-not (Enter-Screen $VK_A $name)) {
        Shot ("{0}-missing" -f $i)
        break
    }
    $reached += $name
    Shot ("setup{0}" -f $i)
    Press $VK_H                                     # right, the first row
    Start-Sleep -Milliseconds 600
    Shot ("setup{0}-row1" -f $i)
    Press $VK_G                                     # down
    Press $VK_H                                     # right, the second row
    Start-Sleep -Milliseconds 600
    Shot ("setup{0}-row2" -f $i)
    if ($i -lt $setups.Count - 1) {
        if (-not (Enter-Screen $VK_S "Challenge")) {   # B
            Shot ("{0}-noback" -f $i)
            break
        }
    } else {
        $atCarSel = Enter-Screen $VK_A "Select Car"
        Write-Host ("  car select: {0}" -f $atCarSel)
        Start-Sleep -Milliseconds 1500
        Shot "carsel"
    }
}

$survived = Alive
if ($survived) { $proc | Stop-Process -Force }
Start-Sleep -Milliseconds 600

# --- the verdict ------------------------------------------------------------

$dbg = @(); if (Test-Path $debugLog)  { $dbg = Get-Content $debugLog }
$az  = @(); if (Test-Path $azaharLog) { $az  = Get-Content $azaharLog }

$crashSigs = @("PANIC", "segfault", "Unhandled exception", "svcBreak")
$crash = $az | Where-Object { $l = $_; $crashSigs | Where-Object { $l -match $_ } }
$unmapped = $az | Where-Object { $_ -match "unmapped (Read|Write)" }

$verdict = "UNKNOWN"
if (-not $booted)        { $verdict = "FAIL (never reached the main loop)" }
elseif ($crash)          { $verdict = "FAIL (crash: $($crash[0]))" }
elseif ($unmapped)       { $verdict = "FAIL ($(@($unmapped).Count) unmapped accesses, first: $(@($unmapped)[0]))" }
elseif (-not $atChallenge) { $verdict = "PARTIAL (never reached Challenge)" }
elseif ($reached.Count -lt $setups.Count) { $verdict = "PARTIAL (reached $($reached.Count) of the four setups)" }
elseif (-not $atCarSel)  { $verdict = "PARTIAL (Free Run Setup's A did not reach car select)" }
elseif (-not $survived)  { $verdict = "FAIL (reached car select, then died)" }
else                     { $verdict = "PASS (all four setups, then car select)" }

Write-Host ""
Write-Host "=== flow ==="
$dbg | Where-Object { $_ -match "flow (enter|leave|change|want|unregistered)|screen (Challenge|[A-Za-z ]+Setup) |fred race setup|not ported|abort|assert|fatal" } |
    Select-Object -Last 80 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== nfshp2_debug.txt (last 20) ==="
$dbg | Select-Object -Last 20 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== azahar_log.txt errors ==="
$az | Where-Object { $_ -match "Error|Critical|PANIC" } | Select-Object -Last 12 |
    ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== Result ==="
Write-Host ("Reached:    {0}" -f ($reached -join ", "))
Write-Host ("Verdict:    {0}" -f $verdict)
Write-Host ("Screenshots: {0} in {1}" -f $step, $OutDir)
