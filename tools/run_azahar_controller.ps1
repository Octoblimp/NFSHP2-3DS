# Boots NFSHP2-3DS.3dsx in Azahar and walks Options' Controller (TASKS
# 71d, joyconfig.h): the PreConfig page's one row, the Configuration page's
# two tables, the racer's HUD put on Y, the cop's e-brake refused A (the
# throttle would have no key), a wait stopped with START, X's defaults, the
# save prompt stayed and answered No (the keys put back, checked on the way
# in again) and Yes (settings.db and controls.bin written, controls.bin's
# bytes checked), then a second boot that reads controls.bin back. The
# capture and key methods are run_azahar_test.ps1's; see its header for
# why each is the way it is. NFSHP2/SAVES/settings.db and controls.bin are
# put back after.
#
# Usage:
#   powershell -File tools/run_azahar_controller.ps1
#   powershell -File tools/run_azahar_controller.ps1 -OutDir C:\shots

param(
    [int]$BootSeconds = 12,       # before the first capture: bundles decode slowly
    [int]$RunSeconds = 300,       # hard ceiling on the whole run
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_controller" }
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
$VK_Y = 88                # Y, the menus' help
$VK_X = 90                # X

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
# And the keys' file beside it, which this run writes.
$keysFile = Join-Path $env:APPDATA "Azahar\sdmc\NFSHP2\SAVES\controls.bin"
$keysBefore = $null; $hadKeys = Test-Path $keysFile
if ($hadKeys) { $keysBefore = [System.IO.File]::ReadAllBytes($keysFile) }
function Restore-Config {
    if ($script:hadKeys -and $null -ne $script:keysBefore) {
        [System.IO.File]::WriteAllBytes($script:keysFile, $script:keysBefore)
        $script:keysBefore = $null
    } elseif (-not $script:hadKeys -and (Test-Path $script:keysFile)) {
        Remove-Item $script:keysFile -Force
    }
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
# The boot as run_azahar_display.ps1 has it, to the main menu and Options;
# Controller is Options' second row.
#   Controller (PreConfig): Down stays (one row), A: the Configuration page,
#     on the table's name.
#   Right: the cop's keys; Left: the racer's.
#   Down x3: Throttle, Brake, HUD (the racer has no Speed Boost row); A, Y:
#     HUD on Y (the camera takes D-pad Up).
#   Up x3 to the name, Right: the cop's; Down, Right, Up: E-Brake (no key);
#     A, A: refused (the throttle would have none); A, START: the wait
#     stopped; X: the cop's defaults.
#   B: the save prompt; B on it stays; B again, Right and A: No, the keys
#     put back (the tables on the way in again match the first) and the
#     PreConfig page.
#   A: Configuration again; Down x3, A, Y: HUD on Y again; B, Yes: the
#     Autosave screen, its overwrite question Yes, controls.bin written.
# Then a second boot reads controls.bin back.

$loading = Wait-ForLog "global chunks loaded" 60
Write-Host ("  LOADING drawn: {0}" -f $loading)
$booted = Wait-ForLog "entering main loop" 60
Write-Host ("  main loop: {0}" -f $booted)

$atPre = $false; $atConfig = $false; $toCop = $false; $toRacer = $false
$waited = $false; $bound = $false; $refused = $false; $stopped = $false
$defaults = $false; $asked = $false; $stayed = $false; $no = $false
$preAgain = $false; $putBack = $false; $boundAgain = $false; $yes = $false
$saved = $false; $controlsSaved = $false; $fileOk = $false
$firstLoadNote = $false

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
        $firstLoadNote = Wait-ForLog "memcard: (no|loaded) .*controls.bin" 5
        Start-Sleep -Milliseconds 2000
        Press $VK_G                           # World Racing
        Press $VK_G                           # Local Wireless
        Press $VK_G                           # Options
        Press $VK_A 300
        if (Wait-ForLog "flow enter Options" 10) {
            Start-Sleep -Milliseconds 1500
            Press $VK_G 400                   # Controller
            Press $VK_A 300
            $atPre = Wait-ForLog "controller: in" 10
            Write-Host ("  Controller: {0}" -f $atPre)
        }
    } else {
        Shot "no-main-menu"
    }
}

if ($atPre) {
    Start-Sleep -Milliseconds 1500
    Shot "preconfig"
    Press $VK_G 500                           # Down: stays
    Press $VK_A 300
    $atConfig = Wait-ForLog "controller config: in" 10
    Write-Host ("  Configuration: {0}" -f $atConfig)
}

if ($atConfig) {
    Start-Sleep -Milliseconds 2000
    Shot "config-racer"
    Press $VK_H 600                           # Right: the cop's
    $toCop = Wait-ForLog "controller config: cop's keys" 10
    Start-Sleep -Milliseconds 800
    Shot "config-cop"
    Press $VK_F 600                           # Left: the racer's
    $toRacer = Wait-ForLog "controller config: racer's keys" 10
    Write-Host ("  cop: {0}, racer: {1}" -f $toCop, $toRacer)

    Press $VK_G 500; Press $VK_G 500; Press $VK_G 500   # Throttle, Brake, HUD
    Start-Sleep -Milliseconds 600
    Shot "on-hud"
    Press $VK_A 300
    $waited = Wait-ForLog "controller config: waiting for racer action 8" 10
    Start-Sleep -Milliseconds 900
    Shot "waiting"
    Press $VK_Y 600                           # Y
    $bound = Wait-ForLog "controller config: racer action 8 to key 3" 10
    Start-Sleep -Milliseconds 800
    Shot "hud-on-y"
    Write-Host ("  waiting: {0}, HUD on Y: {1}" -f $waited, $bound)

    Press $VK_T 500; Press $VK_T 500; Press $VK_T 500   # up to the name
    Press $VK_H 600                           # Right: the cop's
    [void](Wait-ForLogCount "controller config: cop's keys" 2 10)
    Press $VK_G 500                           # Throttle
    Press $VK_H 500                           # Right: Horn
    Press $VK_T 500                           # Up: E-Brake
    Press $VK_A 300
    [void](Wait-ForLog "controller config: waiting for cop action 2" 10)
    Press $VK_A 600                           # A: refused
    $refused = Wait-ForLog "controller config: cop action 2 to key 0 refused" 10
    Press $VK_A 300
    [void](Wait-ForLogCount "controller config: waiting for cop action 2" 2 10)
    Press $VK_M 600                           # START: stop the wait
    $stopped = Wait-ForLog "controller config: wait stopped" 10
    Press $VK_X 600                           # X: the cop's defaults
    $defaults = Wait-ForLog "controller config: cop's keys to the defaults" 10
    Start-Sleep -Milliseconds 800
    Shot "cop-ebrake"
    Write-Host ("  refused: {0}, stopped: {1}, defaults: {2}" -f $refused, $stopped, $defaults)

    Press $VK_S 300                           # B: the prompt
    $asked = Wait-ForLog "controller back: changed, asking to save" 10
    Start-Sleep -Milliseconds 1500
    Shot "prompt"
    Press $VK_S 300                           # B on the popup: stay
    $stayed = Wait-ForLog "controller save: stay" 10
    Start-Sleep -Milliseconds 1200
    Press $VK_S 300                           # B
    if (Wait-ForLogCount "controller back: changed, asking to save" 2 10) {
        Start-Sleep -Milliseconds 1200
        Press $VK_H                           # Right: No
        Press $VK_A 300
        $no = Wait-ForLog "controller save: no, keys put back" 10
    }
    $preAgain = Wait-ForLogCount "controller: in" 2 12
    Write-Host ("  asked: {0}, stayed: {1}, no: {2}, PreConfig: {3}" -f $asked, $stayed, $no, $preAgain)
}

if ($preAgain) {
    Start-Sleep -Milliseconds 1500
    Press $VK_A 300                           # Configuration
    if (Wait-ForLogCount "controller config: in" 2 12) {
        # The log lands in sectors, so the second line can be read cut short:
        # read again until its cop table is whole.
        $until = (Get-Date).AddSeconds(10)
        do {
            $ins = @(Get-Content $debugLog | Where-Object { $_ -match "controller config: in," })
            if ($ins.Count -ge 2 -and $ins[1] -match "cop [0-9a-f]{24}\s*$") { break }
            Start-Sleep -Milliseconds 500
        } while ((Get-Date) -lt $until)
        if ($ins.Count -ge 2) {
            $first = $ins[0] -replace "^.*controller config: in", ""
            $second = $ins[1] -replace "^.*controller config: in", ""
            $putBack = $first -eq $second
            Write-Host ("  put back: {0} ({1} / {2})" -f $putBack, $first, $second)
        }
        Start-Sleep -Milliseconds 1500
        Press $VK_G 500; Press $VK_G 500; Press $VK_G 500   # HUD
        Press $VK_A 300
        [void](Wait-ForLogCount "controller config: waiting for racer action 8" 2 10)
        Press $VK_Y 600
        $boundAgain = Wait-ForLogCount "controller config: racer action 8 to key 3" 2 10
        Start-Sleep -Milliseconds 800
        Press $VK_S 300                       # B
        if (Wait-ForLogCount "controller back: changed, asking to save" 3 10) {
            Start-Sleep -Milliseconds 1200
            Press $VK_A 300                   # Yes
            $yes = Wait-ForLog "controller save: yes" 10
        }
        Write-Host ("  HUD on Y again: {0}, yes: {1}" -f $boundAgain, $yes)
        # The Autosave screen's overwrite question, opened on No.
        if ($yes -and (Wait-ForLog "flow language id 0ce3f7ce e0105663 150103" 15)) {
            Start-Sleep -Milliseconds 1500
            Shot "overwrite"
            Press $VK_F                       # Left: Yes
            Press $VK_A 300
            $saved = Wait-ForLog "memcard: saved .*settings.db" 20
            $controlsSaved = Wait-ForLog "memcard: saved .*controls.bin" 10
        }
        Start-Sleep -Milliseconds 2500
        Shot "after-save"
    }
}

$survived = Alive
if ($survived) { $proc | Stop-Process -Force }
Start-Sleep -Milliseconds 600

# What the save wrote: "HP2K", 1, 12, then the racer's HUD (8) on Y (3)
# and the camera (4) on D-pad Up (8).
$controlsFile = Join-Path $env:APPDATA "Azahar\sdmc\NFSHP2\SAVES\controls.bin"
$secondLoad = $false
if (Test-Path $controlsFile) {
    $cb = [System.IO.File]::ReadAllBytes($controlsFile)
    $fileOk = $cb.Count -eq 30 -and $cb[0] -eq 72 -and $cb[1] -eq 80 -and `
              $cb[2] -eq 50 -and $cb[3] -eq 75 -and $cb[4] -eq 1 -and `
              $cb[5] -eq 12 -and $cb[6 + 8] -eq 3 -and $cb[6 + 4] -eq 8
    Write-Host ("  controls.bin: {0} bytes, ok {1}" -f $cb.Count, $fileOk)

    # A second boot: the keys come back with the save's load.
    Remove-Item $debugLog -ErrorAction SilentlyContinue
    $proc = Start-Process -FilePath $AzaharExe -ArgumentList "`"$Target3dsx`"" -PassThru
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        $proc.Refresh()
        if ($proc.HasExited -or $proc.MainWindowHandle -ne 0) { break }
        Start-Sleep -Milliseconds 250
    }
    $hwnd = $proc.MainWindowHandle
    if ($hwnd -ne 0) {
        [void][Hp2Dbg]::DismissPopups([uint32]$proc.Id, $hwnd)
        if (Wait-ForLog "flow enter Language Options Pre FE" 60) {
            Start-Sleep -Milliseconds 1500
            [Hp2Dbg]::PressKey($hwnd, $VK_A)
        }
        $secondLoad = Wait-ForLog "memcard: loaded .*controls.bin" 60
    }
    Write-Host ("  second boot loaded controls.bin: {0}" -f $secondLoad)
    if (Alive) { $proc | Stop-Process -Force }
    Start-Sleep -Milliseconds 600
}
Restore-Config

# --- the verdict ------------------------------------------------------------

$dbg = @(); if (Test-Path $debugLog)  { $dbg = Get-Content $debugLog }
$az  = @(); if (Test-Path $azaharLog) { $az  = Get-Content $azaharLog }

$crashSigs = @("PANIC", "segfault", "Unhandled exception", "svcBreak")
$crash = $az | Where-Object { $l = $_; $crashSigs | Where-Object { $l -match $_ } }
$unmapped = $az | Where-Object { $_ -match "unmapped (Read|Write)" }

$verdict = "UNKNOWN"
if (-not $booted)          { $verdict = "FAIL (never reached the main loop)" }
elseif ($crash)            { $verdict = "FAIL (crash: $($crash[0]))" }
elseif ($unmapped)         { $verdict = "FAIL ($(@($unmapped).Count) unmapped accesses, first: $(@($unmapped)[0]))" }
elseif (-not $survived)    { $verdict = "FAIL (the app died)" }
elseif (-not $atPre)       { $verdict = "PARTIAL (never reached Controller)" }
elseif (-not $atConfig)    { $verdict = "PARTIAL (never reached Configuration)" }
elseif (-not ($toCop -and $toRacer)) { $verdict = "PARTIAL (Left/Right did not switch tables)" }
elseif (-not ($waited -and $bound)) { $verdict = "PARTIAL (HUD did not go on Y)" }
elseif (-not $refused)     { $verdict = "PARTIAL (the throttle's key was not kept)" }
elseif (-not $stopped)     { $verdict = "PARTIAL (START did not stop the wait)" }
elseif (-not $defaults)    { $verdict = "PARTIAL (X did not put the defaults back)" }
elseif (-not $asked)       { $verdict = "PARTIAL (B with changes did not ask)" }
elseif (-not $stayed)      { $verdict = "PARTIAL (B on the prompt did not stay)" }
elseif (-not $no)          { $verdict = "PARTIAL (No did not put the keys back)" }
elseif (-not $preAgain)    { $verdict = "PARTIAL (No did not go back)" }
elseif (-not $putBack)     { $verdict = "PARTIAL (No left the keys changed)" }
elseif (-not ($boundAgain -and $yes)) { $verdict = "PARTIAL (Yes did not save)" }
elseif (-not $controlsSaved) { $verdict = "PARTIAL (controls.bin was not written)" }
elseif (-not $fileOk)      { $verdict = "PARTIAL (controls.bin is wrong)" }
elseif (-not $secondLoad)  { $verdict = "PARTIAL (the second boot did not load controls.bin)" }
else                       { $verdict = "PASS (tables, rebind, guard, wait stop, defaults, prompt stay/No/Yes, controls.bin saved and loaded)" }

Write-Host ""
Write-Host ("first boot noted controls.bin: {0}" -f $firstLoadNote)
Write-Host "=== azahar_log.txt errors ==="
$az | Where-Object { $_ -match "Error|Critical|PANIC" } | Select-Object -Last 12 |
    ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== Result ==="
Write-Host ("Save written: {0} (put back)" -f $saveWritten)
Write-Host ("Verdict:    {0}" -f $verdict)
Write-Host ("Screenshots: {0} in {1}" -f $step, $OutDir)
