# Boots NFSHP2-3DS.3dsx in Azahar and plays a You're The Cop race from the
# frontend, as a player would (12m-5): Hot Pursuit, You're The Cop, A on
# Players, the first car with Automatic and its first handling, A on Select
# Track's first track. The race loads, the Pre Race Blurb comes up over the
# fly-by, and the run leaves it to end on its own; then the gas is held
# until the race is over, and A steps through the screens after it. It
# reports the flow, the race start, the chases and the race's end from
# sdmc:/nfshp2_debug.txt. The capture and key methods are
# run_azahar_test.ps1's; see its header for why each is the way it is.
#
# sdmc:/nfshp2_config.txt must not set SkipFE: the run needs the frontend.
#
# Usage:
#   powershell -File tools/run_azahar_coprace.ps1
#   powershell -File tools/run_azahar_coprace.ps1 -WatchSeconds 120
#   powershell -File tools/run_azahar_coprace.ps1 -SkipBlurb
#
# The user watches these runs: the gas only, never the brake (83), which
# stops the car and then reverses it. -HoldPlan is a list of holds,
# "key:seconds" each, run in turn once the fly-by is over and before the
# gas: "70:2,0:1" steers left for two seconds and then holds nothing for
# one. A key of 0 holds nothing.
#
# -Calls are single presses, "key:seconds" into the gas, each with a shot
# after it. The default is the horn (X, 90; the cop's target) at 6, 10
# and 14 seconds, so a chase is open for the calls: R (87, the helicopter)
# at 22 and L (81, the roadblock) at 40 (joyhid_cop_keys).

param(
    [int]$FlybySeconds = 60,      # the most from the track's attach to the race
    [int]$WatchSeconds = 420,     # the gas, until the race is over
    [int]$AfterSeconds = 60,      # the screens after the race
    [int]$RunSeconds = 900,       # hard ceiling on the whole run
    [double]$ShotSeconds = 10,    # between the shots while racing
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = "",
    [switch]$SkipBlurb,           # A on the Blurb, which skips the fly-by
    [switch]$CirclePad,           # down the menu with the Circle Pad, not the D-pad
    [string]$HoldPlan = "",
    [string]$Calls = "90:6,90:10,90:14,87:22,81:40"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_coprace" }
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

$VK_A = 65; $VK_S = 83; $VK_M = 77; $VK_N = 78; $VK_G = 71; $VK_H = 72; $VK_F = 70

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
function Alive { $proc.Refresh(); -not $proc.HasExited -and (Elapsed) -lt $RunSeconds }

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

function Seen([string]$pattern) {
    if (-not (Test-Path $debugLog)) { return $false }
    return [bool](Select-String -Path $debugLog -Pattern $pattern -Quiet -ErrorAction SilentlyContinue)
}

$step = 0
function Shot([string]$tag) {
    if (-not (Alive)) { return }
    $script:step++
    $path = Join-Path $OutDir ("{0:d2}_{1}.png" -f $script:step, $tag)
    [Hp2Cap]::CaptureToFile($hwnd, $path)
    Write-Host ("  [{0,5:N1}s] {1}" -f (Elapsed), $path)
}

# Press $vk until a line matching $pattern turns up, waiting $waitSec after
# each press; $tries presses at most.
function Press-Until([int]$vk, [string]$pattern, [int]$tries, [int]$waitSec) {
    # The game's log reaches the card in whole sectors, the part-sector
    # tail up to 5 s later (logwriter.c), so a line can come 7 s after
    # what it tells of. Pressing again any sooner presses twice: a second
    # A on Cops On Mode Select starts a quick race.
    if ($waitSec -lt 8) { $waitSec = 8 }
    for ($i = 0; $i -lt $tries; $i++) {
        if (-not (Alive)) { return $false }
        if ($vk -eq 40 -or $vk -eq 38) {
            # The Circle Pad: held longer, so a slow frontend frame sees it.
            [Hp2Cap]::KeyDown($hwnd, $vk)
            Start-Sleep -Milliseconds 400
            [Hp2Cap]::KeyUp($hwnd, $vk)
        } else {
            [Hp2Cap]::PressKey($hwnd, $vk)
        }
        if (Wait-ForLog $pattern $waitSec) { return $true }
    }
    return $false
}

# --- the script the run follows -------------------------------------------
# The boot and the way to car select as run_azahar_carsel.ps1 has them,
# then -Choose's popups to Select Track, and A there on its first track.

$loading = Wait-ForLog "global chunks loaded" 60
Write-Host ("  LOADING drawn: {0}" -f $loading)
$booted = Wait-ForLog "entering main loop" 60
Write-Host ("  main loop: {0}" -f $booted)

$atCarSel = $false
if ($booted) {
    if (Wait-ForLog "flow enter Language Options Pre FE" 30) {
        Start-Sleep -Milliseconds 1500
        [void](Press-Until $VK_A "flow leave Language Options Pre FE" 6 3)   # A, English
    }
    if (Wait-ForLog "^movie open MOVIES/INTRO/NFSINTRO" 40) {
        Start-Sleep -Seconds 2
        [void](Press-Until $VK_M "flow title skip" 6 3)   # START: stop the intro
    } else {
        [void](Wait-ForLog "flow title idle" 20)
    }
    [void](Wait-ForLog "flow vis object b5761d00 b070dbc9 1" 15)
    Start-Sleep -Milliseconds 900
    if (Press-Until $VK_M "flow enter New Main Menu" 6 3) {   # START
        Start-Sleep -Milliseconds 1200
        if (Press-Until $VK_A "flow enter Cops On Mode Select" 6 3) {   # A, Hot Pursuit
            # A press before the menu has its first item is dropped.
            [void](Wait-ForLog "screen Cops On Mode Select .* last HIGHLIGHT" 10)
            Start-Sleep -Milliseconds 2500
            # Down to You're The Cop, again until the menu shows item 2: a
            # dropped press here and A starts a Quick Race. The log reaches
            # the card from a thread of its own, seconds late at times, so
            # each press waits 10 s for its line.
            # Azahar's Circle Pad is the arrow keys (VK_DOWN 40, VK_UP 38).
            $downKey = if ($CirclePad) { 40 } else { $VK_G }
            $upKey = if ($CirclePad) { 38 } else { 84 }
            $onCop = Press-Until $downKey "screen Cops On Mode Select \S+ stack \d+ menu \d+ item 2 " 3 10
            # One press too many: back up to item 2.
            if (Seen "screen Cops On Mode Select \S+ stack \d+ menu \d+ item 3 ") {
                [void](Press-Until $upKey "^\b$" 1 1)
                Start-Sleep -Milliseconds 4000
                $onCop = $true
            }
            Start-Sleep -Milliseconds 500
            if ($onCop -and (Press-Until $VK_A "flow enter ChallengeBeACop" 3 4)) {
                Start-Sleep -Milliseconds 1200
                Shot "beacop"
                $atCarSel = Press-Until $VK_A "flow enter Select Car" 3 5   # A on Players
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
Write-Host ("  car select: {0}" -f $atCarSel)

$started = $false
if ($atCarSel) {
    Start-Sleep -Milliseconds 2500
    Shot "carsel"
    [Hp2Cap]::PressKey($hwnd, $VK_A)      # A, the transmission popup
    Start-Sleep -Milliseconds 1500
    [Hp2Cap]::PressKey($hwnd, $VK_A)      # A, Automatic
    Start-Sleep -Milliseconds 1500
    Shot "carsel-handling"
    $onTrack = Press-Until $VK_A "flow enter Select Track" 2 8   # A, the first handling
    Write-Host ("  Select Track: {0}" -f $onTrack)
    if ($onTrack) {
        Start-Sleep -Milliseconds 2500
        Shot "selecttrack"
        $started = Press-Until $VK_A "race start:" 3 8   # A, the first track
    }
}
Write-Host ("  race started: {0}" -f $started)

$racing = $false
if ($started) {
    Start-Sleep -Milliseconds 1500
    Shot "loading"
    $racing = Wait-ForLog "flow state RACING" 150
    Write-Host ("  RACING: {0}" -f $racing)
}

# The fly-by with the Blurb over it, untouched unless -SkipBlurb, from the
# track's attach (the flow is in RACING well before) until the race is in
# progress (the coordinator's stage 4), the countdown over.
if ($racing) {
    $attached = Wait-ForLog "^trackview: attached" 150
    Write-Host ("  track attached: {0}" -f $attached)
    $flyEnd = (Get-Date).AddSeconds($FlybySeconds)
    $nextShot = Get-Date
    $skipped = $false
    $n = 0
    while ((Get-Date) -lt $flyEnd -and (Alive) -and -not (Seen "^race: rc \d+, stage 4")) {
        if ((Get-Date) -ge $nextShot) {
            $n++
            Shot ("flyby-{0}" -f $n)
            $nextShot = (Get-Date).AddSeconds(3)
        }
        if ($SkipBlurb -and -not $skipped -and $n -ge 2) {
            [Hp2Cap]::PressKey($hwnd, $VK_A)
            Write-Host ("  [{0,5:N1}s] A on the Blurb" -f (Elapsed))
            $skipped = $true
        }
        Start-Sleep -Milliseconds 300
    }
}

# Holds, then the gas until the race is over. -Calls are presses at
# seconds into the gas: "90:6,87:22" is the horn at 6 s and R (the
# helicopter) at 22.
$over = $false
if ($racing) {
    foreach ($h in ($HoldPlan.Split(",") | Where-Object { $_ -ne "" })) {
        if (-not (Alive)) { break }
        $kv = $h.Split(":")
        $vk = [int]$kv[0]
        $holdEnd = (Get-Date).AddSeconds([double]$kv[1])
        Write-Host ("  [{0,5:N1}s] hold {1} for {2} s" -f (Elapsed), $vk, $kv[1])
        while ((Get-Date) -lt $holdEnd -and (Alive)) {
            if ($vk -ne 0) { [Hp2Cap]::KeyDown($hwnd, $vk) }
            Start-Sleep -Milliseconds 150
        }
        if ($vk -ne 0) { [Hp2Cap]::KeyUp($hwnd, $vk) }
    }
    # PowerShell's names ignore case: this list is not $Calls.
    $callList = @()
    foreach ($c in ($Calls.Split(",") | Where-Object { $_ -ne "" })) {
        $kv = $c.Split(":")
        $callList += [pscustomobject]@{ vk = [int]$kv[0]; at = [double]$kv[1]; done = $false }
    }
    $gasStart = Get-Date
    $end = $gasStart.AddSeconds($WatchSeconds)
    $nextShot = Get-Date
    $n = 0
    while ((Get-Date) -lt $end -and (Alive)) {
        [Hp2Cap]::KeyDown($hwnd, $VK_A)
        $t = ((Get-Date) - $gasStart).TotalSeconds
        foreach ($c in $callList) {
            if (-not $c.done -and $t -ge $c.at) {
                [Hp2Cap]::PressKey($hwnd, $c.vk)
                Write-Host ("  [{0,5:N1}s] call {1}" -f (Elapsed), $c.vk)
                $c.done = $true
                Start-Sleep -Milliseconds 1500
                $n++
                Shot ("call-{0}-{1}" -f $c.vk, $n)
            }
        }
        if ((Get-Date) -ge $nextShot) {
            $n++
            Shot ("race-{0}" -f $n)
            $nextShot = (Get-Date).AddSeconds($ShotSeconds)
            if (Seen "^race over:|flow enter (End Game|Race Results|Race Over)") {
                $over = $true
                break
            }
        }
        Start-Sleep -Milliseconds 150
    }
    [Hp2Cap]::KeyUp($hwnd, $VK_A)
    Write-Host ("  race over: {0}" -f $over)
}

# The screens after the race: a shot every three seconds, and A every nine.
if ($over) {
    $afterEnd = (Get-Date).AddSeconds($AfterSeconds)
    $n = 0
    while ((Get-Date) -lt $afterEnd -and (Alive)) {
        $n++
        Shot ("after-{0}" -f $n)
        if ($n % 3 -eq 0) {
            [Hp2Cap]::PressKey($hwnd, $VK_A)
            Write-Host ("  [{0,5:N1}s] A" -f (Elapsed))
        }
        Start-Sleep -Seconds 3
    }
}

$proc.Refresh()
$survived = -not $proc.HasExited
if ($survived) { $proc | Stop-Process -Force }
Start-Sleep -Milliseconds 600

# --- the verdict ------------------------------------------------------------

$dbg = @(); if (Test-Path $debugLog)  { $dbg = Get-Content $debugLog }
$az  = @(); if (Test-Path $azaharLog) { $az  = Get-Content $azaharLog }

$crashSigs = @("PANIC", "segfault", "Unhandled exception", "svcBreak")
$crash = $az | Where-Object { $l = $_; $crashSigs | Where-Object { $l -match $_ } }
# Azahar only logs a read of unmapped memory; the device takes a data abort.
$unmapped = $az | Where-Object { $_ -match "unmapped (Read|Write)" }

$verdict = "UNKNOWN"
if (-not $booted)       { $verdict = "FAIL (never reached the main loop)" }
elseif ($crash)         { $verdict = "FAIL (crash: $($crash[0]))" }
elseif ($unmapped)      { $verdict = "FAIL ($(@($unmapped).Count) unmapped accesses, first: $(@($unmapped)[0]))" }
elseif (-not $atCarSel) { $verdict = "PARTIAL (never reached Select Car)" }
elseif (-not $started)  { $verdict = "PARTIAL (Select Track never started the race)" }
elseif (-not $racing)   { $verdict = "PARTIAL (left the frontend, never reached RACING)" }
elseif (-not $survived) { $verdict = "FAIL (reached RACING, then died)" }
elseif (-not $over)     { $verdict = "PARTIAL (raced, but the race was not over in time)" }
else                    { $verdict = "PASS (a cop race from the frontend to its end)" }

Write-Host ""
Write-Host "=== race start and flow ==="
$dbg | Where-Object { $_ -match "race start|  driver|flow (want|state|enter|leave)|race over|popup|not ported|track detached|abort|assert|fatal" } |
    Select-Object -Last 70 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== chases, the helicopter's munitions and the player's NIS (changes) ==="
$lastChase = ""; $lastNis = ""; $lastMun = ""; $changes = @()
foreach ($l in ($dbg | Where-Object { $_ -match "^race: (chases|munitions|player NIS)" })) {
    if ($l -match "^race: chases") {
        $k = $l -replace "timer [-0-9.]+", "" -replace "at [-0-9. ]+, busy", "busy"
        if ($k -ne $lastChase) { $changes += $l; $lastChase = $k }
    } elseif ($l -match "^race: munitions") {
        if ($l -ne $lastMun) { $changes += $l; $lastMun = $l }
    } elseif ($l -ne $lastNis) {
        $changes += $l; $lastNis = $l
    }
}
$changes | Select-Object -Last 40 | ForEach-Object { Write-Host $_ }
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
