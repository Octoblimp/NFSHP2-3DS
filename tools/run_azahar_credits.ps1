# Boots NFSHP2-3DS.3dsx in Azahar and walks Options' Credits (TASKS 71a,
# credits.h): Electronic Arts' names rolling over the slideshow, paused
# and let go; Black Box Games' logo movie going on to its names; the intro
# and the making-of played from the menu; the reward movie when both
# Ultimates are won. The capture and key methods are run_azahar_test.ps1's;
# see its header for why each is the way it is. NFSHP2/SAVES/settings.db
# is put back after.
#
# Usage:
#   powershell -File tools/run_azahar_credits.ps1
#   powershell -File tools/run_azahar_credits.ps1 -OutDir C:\shots

param(
    [int]$BootSeconds = 12,       # before the first capture: bundles decode slowly
    [int]$RunSeconds = 240,       # hard ceiling on the whole run
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_credits" }
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
public class Hp2Dbg {
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
    public static void KeyDown(IntPtr h, int vk) {
        PostMessage(h, WM_KEYDOWN, (IntPtr)vk, IntPtr.Zero);
    }
    public static void KeyUp(IntPtr h, int vk) {
        PostMessage(h, WM_KEYUP, (IntPtr)vk, IntPtr.Zero);
    }
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

[void][Hp2Dbg]::SetProcessDPIAware()

$VK_A = 65; $VK_S = 83; $VK_M = 77; $VK_N = 78; $VK_T = 84; $VK_G = 71; $VK_H = 72; $VK_F = 70
$VK_Q = 81; $VK_W = 87    # L and R
$VK_Y = 88                # Y, the menus' SQUARE

$debugLog  = Join-Path $env:APPDATA "Azahar\sdmc\nfshp2_debug.txt"
. (Join-Path $PSScriptRoot "azahar_debuglog.ps1")   # DebugLog 1
$azaharLog = Join-Path $env:APPDATA "Azahar\log\azahar_log.txt"
Remove-Item $debugLog  -ErrorAction SilentlyContinue
Remove-Item $azaharLog -ErrorAction SilentlyContinue
Get-ChildItem $OutDir -Filter *.png -ErrorAction SilentlyContinue | Remove-Item -Force

# The card's save as it was, or none, in case anything writes it.
$saveFile = Join-Path $env:APPDATA "Azahar\sdmc\NFSHP2\SAVES\settings.db"
$saveBefore = $null; $hadSave = Test-Path $saveFile
if ($hadSave) { $saveBefore = [System.IO.File]::ReadAllBytes($saveFile) }
$saveWritten = $false
function Restore-Config {
    if ($script:hadSave -and $null -ne $script:saveBefore) {
        $now = [System.IO.File]::ReadAllBytes($script:saveFile)
        $script:saveWritten = [Convert]::ToBase64String($now) -ne `
            [Convert]::ToBase64String($script:saveBefore)
        [System.IO.File]::WriteAllBytes($script:saveFile, $script:saveBefore)
        $script:saveBefore = $null
    } elseif (-not $script:hadSave -and (Test-Path $script:saveFile)) {
        $script:saveWritten = $true
        Remove-Item $script:saveFile -Force
    }
}
trap { Restore-Config; break }

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
$closed = [Hp2Dbg]::DismissPopups([uint32]$proc.Id, $hwnd)
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
    [Hp2Dbg]::CaptureToFile($hwnd, $path)
    Write-Host ("  [{0,5:N1}s] {1}" -f (Elapsed), $path)
}

function Press([int]$vk, [int]$waitMs = 700) {
    [Hp2Dbg]::PressKey($hwnd, $vk)
    Start-Sleep -Milliseconds $waitMs
}

# --- the script the run follows -------------------------------------------
# The boot as run_azahar_nameentry.ps1 has it, to the main menu. Options is
# three down, and Credits (MENUITEM_6) five down in it. Back on the Credits
# menu the row last picked is still highlighted, so each step is one down.
#   Electronic Arts: the names roll up over the slideshow; Y pauses them
#     and Y again lets them go; B back.
#   Black Box Games: its logo movie, then its names on their own; B back.
#   View Intro Movie: A ends it.
#   The Making of HP2: B leaves it.
#   View Reward Movie only if both Ultimates are won on this save.
#   B back to Options.

$loading = Wait-ForLog "global chunks loaded" 60
Write-Host ("  LOADING drawn: {0}" -f $loading)
$booted = Wait-ForLog "entering main loop" 60
Write-Host ("  main loop: {0}" -f $booted)

$atCredits = $false; $ea = $false; $paused = $false; $rolled = $false
$eaBack = $false; $bbgLogo = $false; $bbgNames = $false; $bbgBack = $false
$intro = $false; $introBack = $false; $makeOf = $false; $makeOfBack = $false
$reward = "?"; $rewardPlayed = $false; $options = $false
function Menu-Count { @(Select-String -Path $debugLog -Pattern "credits ctor" -ErrorAction SilentlyContinue).Count }

if ($booted) {
    if (Wait-ForLog "flow enter Language Options Pre FE" 30) {
        Start-Sleep -Milliseconds 1500
        [Hp2Dbg]::PressKey($hwnd, $VK_A)      # A, English
    }
    if (Wait-ForLog "^movie open MOVIES/INTRO/NFSINTRO" 25) {
        Start-Sleep -Seconds 2
        [Hp2Dbg]::PressKey($hwnd, $VK_M)      # START: stop the intro
        [void](Wait-ForLog "flow title skip" 10)
    } else {
        [void](Wait-ForLog "flow title idle" 20)
    }
    [void](Wait-ForLog "flow vis object b5761d00 b070dbc9 1" 15)
    Start-Sleep -Milliseconds 900
    [Hp2Dbg]::PressKey($hwnd, $VK_M)          # START

    if (Wait-ForLog "flow enter New Main Menu" 12) {
        Start-Sleep -Milliseconds 2000
        Press $VK_G                           # World Racing
        Press $VK_G                           # Local Wireless
        Press $VK_G                           # Options
        Press $VK_A 300
        if (Wait-ForLog "flow enter Options" 10) {
            Start-Sleep -Milliseconds 1500
            for ($i = 0; $i -lt 5; $i++) { Press $VK_G 500 }   # Credits
            Shot "options"
            Press $VK_A 300
            $atCredits = Wait-ForLog "credits ctor" 10
            Write-Host ("  Credits: {0}" -f $atCredits)
        }
    } else {
        Shot "no-main-menu"
    }
}

if ($atCredits) {
    Start-Sleep -Milliseconds 1500
    Shot "credits"
    $line = Select-String -Path $debugLog -Pattern "credits ctor .*reward (\w+)" |
        Select-Object -Last 1
    if ($line -and $line.Line -match "reward (\w+)") { $reward = $Matches[1] }
    Write-Host ("  reward row: {0}" -f $reward)

    # Electronic Arts.
    Press $VK_A 300
    $ea = Wait-ForLog "credits build 0: \d+ lines, ids 501000\.\.501614" 10
    Write-Host ("  EA names: {0}" -f $ea)
    Start-Sleep -Seconds 2
    Shot "ea-start"
    Start-Sleep -Seconds 5
    Shot "ea-7s"
    Start-Sleep -Seconds 4
    Shot "ea-11s"
    Press $VK_Y 300                           # Y: SQUARE, pause
    $paused = Wait-ForLog "credits paused" 10
    Start-Sleep -Milliseconds 1500
    Shot "ea-paused"
    Start-Sleep -Milliseconds 2000
    Shot "ea-still-paused"
    Press $VK_Y 300                           # Y: rolling again
    $rolled = Wait-ForLog "credits rolling" 10
    Write-Host ("  pause: {0}, again: {1}" -f $paused, $rolled)
    Press $VK_G 400                           # a nudge
    Press $VK_S 300                           # B
    $eaBack = Wait-ForLogCount "credits ctor" 2 12
    Write-Host ("  back from EA: {0}" -f $eaBack)

    # Black Box Games: the logo, then its names.
    if ($eaBack) {
        Start-Sleep -Milliseconds 1500
        Press $VK_G                           # Black Box Games
        Press $VK_A 300
        $bbgLogo = Wait-ForLog "credits movie .*BBGLOGO_EN\.AVI open, then BBGCredits" 10
        Write-Host ("  BBG logo: {0}" -f $bbgLogo)
        Start-Sleep -Seconds 4
        Shot "bbg-logo"
        $bbgNames = Wait-ForLog "credits build 1: \d+ lines, ids 601000\.\.601226" 30
        Write-Host ("  BBG names: {0}" -f $bbgNames)
        Start-Sleep -Seconds 4
        Shot "bbg-names"
        Press $VK_S 300                       # B
        $bbgBack = Wait-ForLogCount "credits ctor" 3 12
        Write-Host ("  back from BBG: {0}" -f $bbgBack)
    }

    # View Intro Movie, ended with A.
    if ($bbgBack) {
        Start-Sleep -Milliseconds 1500
        Press $VK_G                           # View Intro Movie
        Press $VK_A 300
        $intro = Wait-ForLog "credits movie .*NFSINTRO_EN\.AVI open, then back" 10
        Write-Host ("  intro: {0}" -f $intro)
        Start-Sleep -Seconds 6
        Shot "intro"
        Press $VK_A 300                       # A: done
        $introBack = Wait-ForLogCount "credits ctor" 4 12
        Write-Host ("  back from the intro: {0}" -f $introBack)
    }

    # The Making of HP2, left with B.
    if ($introBack) {
        Start-Sleep -Milliseconds 1500
        Press $VK_G                           # The Making of HP2
        Press $VK_A 300
        $makeOf = Wait-ForLog "credits movie .*MAKEOF_EN\.AVI open, then back" 10
        Write-Host ("  making-of: {0}" -f $makeOf)
        Start-Sleep -Seconds 6
        Shot "making-of"
        Press $VK_S 300                       # B
        $makeOfBack = Wait-ForLogCount "credits ctor" 5 12
        Write-Host ("  back from the making-of: {0}" -f $makeOfBack)
    }

    # View Reward Movie, when its row is there.
    if ($makeOfBack -and $reward -eq "open") {
        Start-Sleep -Milliseconds 1500
        Press $VK_G                           # View Reward Movie
        Press $VK_A 300
        $rewardPlayed = Wait-ForLog "credits movie .*REWARD_EN\.AVI open, then back" 10
        Start-Sleep -Seconds 5
        Shot "reward"
        Press $VK_A 300
        [void](Wait-ForLogCount "credits ctor" 6 12)
    }

    Start-Sleep -Milliseconds 1500
    Press $VK_S 300                           # B: Options
    $options = Wait-ForLogCount "flow enter Options" 2 12
    Start-Sleep -Milliseconds 1500
    Shot "options-again"
}
$raced = $true

while ((Elapsed) -lt $RunSeconds -and (Alive) -and -not $raced) { Start-Sleep -Milliseconds 300 }

$survived = Alive
if ($survived) { $proc | Stop-Process -Force }
Start-Sleep -Milliseconds 600
Restore-Config

# --- the verdict ------------------------------------------------------------

$dbg = @(); if (Test-Path $debugLog)  { $dbg = Get-Content $debugLog }
$az  = @(); if (Test-Path $azaharLog) { $az  = Get-Content $azaharLog }

$crashSigs = @("PANIC", "segfault", "Unhandled exception", "svcBreak")
$crash = $az | Where-Object { $l = $_; $crashSigs | Where-Object { $l -match $_ } }
$unmapped = $az | Where-Object { $_ -match "unmapped (Read|Write)" }
$lines = $dbg | Where-Object { $_ -match "credits|movie (open|close|missing)|flow enter" }

$verdict = "UNKNOWN"
if (-not $booted)          { $verdict = "FAIL (never reached the main loop)" }
elseif ($crash)            { $verdict = "FAIL (crash: $($crash[0]))" }
elseif ($unmapped)         { $verdict = "FAIL ($(@($unmapped).Count) unmapped accesses, first: $(@($unmapped)[0]))" }
elseif (-not $survived)    { $verdict = "FAIL (the app died)" }
elseif (-not $atCredits)   { $verdict = "PARTIAL (never reached Credits)" }
elseif (-not $ea)          { $verdict = "PARTIAL (Electronic Arts built no names)" }
elseif (-not $paused)      { $verdict = "PARTIAL (Y did not pause the names)" }
elseif (-not $rolled)      { $verdict = "PARTIAL (Y again did not let them go)" }
elseif (-not $eaBack)      { $verdict = "PARTIAL (B did not come back from Electronic Arts)" }
elseif (-not $bbgLogo)     { $verdict = "PARTIAL (Black Box Games played no logo)" }
elseif (-not $bbgNames)    { $verdict = "PARTIAL (the logo did not go on to Black Box's names)" }
elseif (-not $bbgBack)     { $verdict = "PARTIAL (B did not come back from Black Box's names)" }
elseif (-not $intro)       { $verdict = "PARTIAL (View Intro Movie played nothing)" }
elseif (-not $introBack)   { $verdict = "PARTIAL (A did not end the intro)" }
elseif (-not $makeOf)      { $verdict = "PARTIAL (The Making of HP2 played nothing)" }
elseif (-not $makeOfBack)  { $verdict = "PARTIAL (B did not leave the making-of)" }
elseif ($reward -eq "open" -and -not $rewardPlayed) { $verdict = "PARTIAL (the reward movie did not play)" }
elseif (-not $options)     { $verdict = "PARTIAL (B did not go back to Options)" }
else                       { $verdict = "PASS (EA, pause, BBG logo and names, intro, making-of, reward $reward)" }

Write-Host ""
Write-Host "=== credits lines ==="
$lines | Select-Object -Last 40 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== azahar_log.txt errors ==="
$az | Where-Object { $_ -match "Error|Critical|PANIC" } | Select-Object -Last 12 |
    ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== Result ==="
Write-Host ("Save written: {0} (put back)" -f $saveWritten)
Write-Host ("Verdict:    {0}" -f $verdict)
Write-Host ("Screenshots: {0} in {1}" -f $step, $OutDir)
