# Boots NFSHP2-3DS.3dsx in Azahar and leaves the title screen alone, to
# see attract mode (TASKS 72h-2b): half a minute at rest, and
# ConsiderStartDemoMode finds no replay to launch ("DemoReplays 0", the
# default), so StartDemoMode sets up the AI race: four AI cars and no
# player for two minutes, in AI_DEMO_MODE with the Demo overlay. When it
# times out the game goes back to the title. Then,
# with -Skip, the run waits for the next demo and presses A in it, which
# goes to the main menu, and waits there for a third, which starts from
# the main menu. A shot every -ShotSeconds while a demo plays. The
# capture and key methods are run_azahar_test.ps1's; see its header for
# why each is the way it is.
#
# -Replays sets "DemoReplays 1" for the run (the card's config is put
# back after): ConsiderLaunching loads one of TheDemoModeReplay's files
# from sdmc:/NFSHP2/REPLAY/JUL23, and the replay's own race goes over the
# AI's, in REPLAY_DEMO_MODE. A PS2 replay drifts on the 3DS, so its
# checksum misses end it at once and the game goes to the main menu, which
# the run takes as the demo's end. -Replays is run without -Skip.
#
# -Drift N (with -Replays) sets "DemoReplayDrift N": the replay plays on
# past its misses, and the log counts them (configitems.h, 72h-2c). At 2,
# the world's steps round toward zero, as the EE's do.
#
# sdmc:/nfshp2_config.txt must not set SkipFE: the run needs the frontend.
# The run presses nothing in a race but -Skip's A.
#
# Usage:
#   powershell -File tools/run_azahar_attract.ps1
#   powershell -File tools/run_azahar_attract.ps1 -Skip
#   powershell -File tools/run_azahar_attract.ps1 -Replays
#   powershell -File tools/run_azahar_attract.ps1 -Replays -Drift 2

param(
    [int]$DemoSeconds = 240,      # the longest a demo may take to run out
    [int]$RunSeconds = 600,       # hard ceiling on the whole run
    [double]$ShotSeconds = 10,    # between the shots while a demo plays
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = "",
    [switch]$Skip,                # the second demo skipped with A
    [switch]$Replays,             # "DemoReplays 1": the disc's replays
    [int]$Drift = 0               # "DemoReplayDrift": play on past misses
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_attract" }
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
# DemoReplays for this run; a later line wins, and the file goes back as
# it was once the run is over.
$configBefore = [System.IO.File]::ReadAllBytes($hp2Config)
Add-Content -Path $hp2Config -Value @("", ("DemoReplays {0}" -f [int][bool]$Replays),
    ("DemoReplayDrift {0}" -f $Drift)) -Encoding ASCII
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
# The boot as run_azahar_quickrace.ps1 has it, to the title at rest with
# PRESS START up; then nothing, and the demo starts by itself.

# Press $vk until a line matching $pattern turns up, waiting $waitSec after
# each press; $tries presses at most.
function Press-Until([int]$vk, [string]$pattern, [int]$tries, [int]$waitSec) {
    for ($i = 0; $i -lt $tries; $i++) {
        if (-not (Alive)) { return $false }
        [Hp2Cap]::PressKey($hwnd, $vk)
        if (Wait-ForLog $pattern $waitSec) { return $true }
    }
    return $false
}

$loading = Wait-ForLog "global chunks loaded" 60
Write-Host ("  LOADING drawn: {0}" -f $loading)

Write-Host "Waiting for the main loop..."
$booted = Wait-ForLog "entering main loop" 60
Write-Host ("  main loop: {0}" -f $booted)

function LogCount([string]$pattern) {
    @(Select-String -Path $debugLog -Pattern $pattern -ErrorAction SilentlyContinue).Count
}

# Wait for the next demo to start and reach RACING. $n is how many demos
# the log has had before it. A replay's is "replay launch" and "demo
# replay"; the AI's has neither.
function Wait-Demo([int]$n) {
    $r = @{}
    $r.start = Wait-ForLogCount "flow demo mode" ($n + 1) 150
    if ($r.start -and $Replays) {
        [void](Wait-ForLogCount "demo replay: file" ($n + 1) 15)
    } elseif ($r.start) {
        [void](Wait-ForLogCount "race start:" ($n + 1) 15)
    }
    $r.replay = (LogCount "demo replay: file") -ge ($n + 1)
    $r.launch = (LogCount "flow replay launch") -ge ($n + 1)
    $r.racing = Wait-ForLogCount "flow state RACING" ($n + 1) 120
    Write-Host ("  [{0,5:N1}s] demo {1}: start {2}, launch {3}, replay {4}, RACING {5}" -f `
        (Elapsed), ($n + 1), $r.start, $r.launch, $r.replay, $r.racing)
    return $r
}

# Shots every -ShotSeconds until the title is entered for the $count'th
# time, or -DemoSeconds go by. With -Replays, the main menu entered ends
# it too, as a skipped demo's end.
$endedToMenu = $false
function Watch-Demo([string]$tag, [int]$count) {
    $end = (Get-Date).AddSeconds($DemoSeconds)
    $nextShot = Get-Date
    $k = 0
    while ((Get-Date) -lt $end -and (Alive)) {
        if ((Get-Date) -ge $nextShot) {
            $k++
            Shot ("{0}-{1}" -f $tag, $k)
            $nextShot = (Get-Date).AddSeconds($ShotSeconds)
        }
        $hits = @(Select-String -Path $debugLog -Pattern "flow enter Title Screen" -ErrorAction SilentlyContinue)
        if ($hits.Count -ge $count) { return $true }
        if ($Replays -and (LogCount "flow enter New Main Menu") -ge 1) {
            $script:endedToMenu = $true
            return $true
        }
        Start-Sleep -Milliseconds 300
    }
    return $false
}

$demo1 = $null; $back = $false; $demo2 = $null; $skipped = $false
$demo3 = $null
if ($booted) {
    $gotLang = Wait-ForLog "flow enter Language Options Pre FE" 30
    Write-Host ("  language screen: {0}" -f $gotLang)
    if ($gotLang) {
        Start-Sleep -Milliseconds 1500
        $lang = Press-Until $VK_A "flow leave Language Options Pre FE" 4 8   # A, English
        Write-Host ("  language chosen: {0}" -f $lang)
    }

    $gotIntro = Wait-ForLog "^movie open MOVIES/INTRO/NFSINTRO" 40
    Write-Host ("  intro opened: {0}" -f $gotIntro)
    if ($gotIntro) {
        Start-Sleep -Seconds 2
        # The log runs up to 7 s behind: a second START too soon would go
        # past PRESS START to the main menu.
        [void](Press-Until $VK_M "flow title skip" 3 9)   # START: stop the intro
    } else {
        [void](Wait-ForLog "flow title idle" 20)
    }
    [void](Wait-ForLog "flow vis object b5761d00 b070dbc9 1" 15)
    Start-Sleep -Milliseconds 900
    Shot "title"
    Write-Host ("  [{0,5:N1}s] at rest on the title, pressing nothing" -f (Elapsed))

    $demo1 = Wait-Demo 0
    if ($demo1.racing) {
        Start-Sleep -Seconds 2
        $back = Watch-Demo "demo" 2
        $where = if ($endedToMenu) { "on the main menu" } else { "back on the title" }
        Write-Host ("  [{0,5:N1}s] {1}: {2}" -f (Elapsed), $where, $back)
        if ($back) {
            Start-Sleep -Seconds 3
            Shot "title-again"
        }
    }

    if ($Skip -and $back) {
        $demo2 = Wait-Demo 1
        if ($demo2.racing) {
            Start-Sleep -Seconds 8
            Shot "skip-before"
            $skipped = Press-Until $VK_A "flow enter New Main Menu" 4 15   # A: skip
            Write-Host ("  [{0,5:N1}s] skipped to the main menu: {1}" -f (Elapsed), $skipped)
            if ($skipped) {
                Start-Sleep -Seconds 3
                Shot "mainmenu"
                Write-Host ("  [{0,5:N1}s] on the main menu, pressing nothing" -f (Elapsed))
                $demo3 = Wait-Demo 2
                if ($demo3.racing) {
                    Start-Sleep -Seconds 8
                    Shot "menu-demo"
                }
            }
        }
    }
}

$survived = Alive
if ($survived) { $proc | Stop-Process -Force }
Start-Sleep -Milliseconds 600
[System.IO.File]::WriteAllBytes($hp2Config, $configBefore)

# --- the verdict ------------------------------------------------------------

$dbg = @(); if (Test-Path $debugLog)  { $dbg = Get-Content $debugLog }
$az  = @(); if (Test-Path $azaharLog) { $az  = Get-Content $azaharLog }

$crashSigs = @("PANIC", "segfault", "Unhandled exception", "svcBreak")
$crash = $az | Where-Object { $l = $_; $crashSigs | Where-Object { $l -match $_ } }
# Azahar only logs a read of unmapped memory; the device takes a data abort.
$unmapped = $az | Where-Object { $_ -match "unmapped (Read|Write)" }

$verdict = "UNKNOWN"
if (-not $booted)                         { $verdict = "FAIL (never reached the main loop)" }
elseif ($crash)                           { $verdict = "FAIL (crash: $($crash[0]))" }
elseif ($unmapped)                        { $verdict = "FAIL ($(@($unmapped).Count) unmapped accesses, first: $(@($unmapped)[0]))" }
elseif (-not $demo1 -or -not $demo1.start) { $verdict = "FAIL (no demo started from the title)" }
elseif (-not $Replays -and $demo1.replay) { $verdict = "FAIL (a replay played without -Replays)" }
elseif ($Replays -and -not $demo1.replay) { $verdict = "FAIL (the demo was not a replay)" }
elseif (-not $demo1.racing)               { $verdict = "FAIL (the demo never reached RACING)" }
elseif (-not $back)                       { $verdict = "FAIL (the demo never went back to the title)" }
elseif ($Replays -and $endedToMenu)       { $verdict = "PASS (a replay restored and played, and ended to the main menu)" }
elseif ($Skip -and -not $skipped)         { $verdict = "FAIL (A did not skip the second demo to the main menu)" }
elseif ($Skip -and -not $demo3.racing)    { $verdict = "FAIL (no demo from the main menu)" }
elseif (-not $survived)                   { $verdict = "FAIL (died)" }
elseif ($Skip)                            { $verdict = "PASS (a demo ran out to the title, the next was skipped to the main menu, and one started there)" }
else                                      { $verdict = "PASS (a demo ran out and went back to the title)" }

Write-Host ""
Write-Host "=== attract mode and flow ==="
$dbg | Where-Object { $_ -match "flow (replay|demo|enter|leave|state)|demo replay|race start|  driver|rc state|not ported|abort|assert|fatal" } |
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
Write-Host ("Verdict:    {0}" -f $verdict)
Write-Host ("Screenshots: {0} in {1}" -f $step, $OutDir)
