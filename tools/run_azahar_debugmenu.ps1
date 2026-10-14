# Boots NFSHP2-3DS.3dsx in Azahar and walks the port's debug menu (TASKS
# 53, debugmenu.h): L, R and D-Pad Up together on the main menu, A on the
# item it shows, the points and Set Save to 100%, the save prompt on B,
# Debug Race's rows changed and scrolled, and Start Race, whose prompt is
# answered No. It captures each step and the race's start. The capture and
# key methods are run_azahar_test.ps1's; see its header for why each is
# the way it is.
#
# -Cop instead boots with "DebugMenu 1" in the card's config, goes down to
# the item with no chord, unlocks everything, picks Be The Cop and leaves
# with B: Yes saves on the Autosave screen. Then in again and Be The Cop
# starts. The config and NFSHP2/SAVES/settings.db are put back after.
#
# Usage:
#   powershell -File tools/run_azahar_debugmenu.ps1
#   powershell -File tools/run_azahar_debugmenu.ps1 -Cop
#   powershell -File tools/run_azahar_debugmenu.ps1 -OutDir C:\shots

param(
    [int]$BootSeconds = 12,       # before the first capture: bundles decode slowly
    [int]$RunSeconds = 150,       # hard ceiling on the whole run
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = "",
    [switch]$Cop
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_debugmenu" }
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

$debugLog  = Join-Path $env:APPDATA "Azahar\sdmc\nfshp2_debug.txt"
. (Join-Path $PSScriptRoot "azahar_debuglog.ps1")   # DebugLog 1
$azaharLog = Join-Path $env:APPDATA "Azahar\log\azahar_log.txt"
Remove-Item $debugLog  -ErrorAction SilentlyContinue
Remove-Item $azaharLog -ErrorAction SilentlyContinue
Get-ChildItem $OutDir -Filter *.png -ErrorAction SilentlyContinue | Remove-Item -Force

# -Cop: the config line for this run only. azahar_debuglog.ps1 has made
# sure the file is there.
$configBefore = $null
if ($Cop) {
    $configBefore = [System.IO.File]::ReadAllBytes($hp2Config)
    Add-Content -Path $hp2Config -Value @("", "DebugMenu 1") -Encoding ASCII
}
# -Cop saves: the card's save as it was, or none.
$saveFile = Join-Path $env:APPDATA "Azahar\sdmc\NFSHP2\SAVES\settings.db"
$saveBefore = $null; $hadSave = Test-Path $saveFile
if ($Cop -and $hadSave) { $saveBefore = [System.IO.File]::ReadAllBytes($saveFile) }
$saveWritten = $false
function Restore-Config {
    if ($null -ne $script:configBefore) {
        [System.IO.File]::WriteAllBytes($hp2Config, $script:configBefore)
        $script:configBefore = $null
    }
    if ($Cop) {
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
# The boot as run_azahar_carsel.ps1 has it, to the main menu. There L, R
# and D-Pad Up together show the debug menu's item, and A goes in. NFS
# Points up by 10,000 and Set Save to 100%, then B: the save prompt, and B
# again stays. Up to Start Debug Race and in: down through the rows with a
# change on a few, past the seventh to scroll, on to the last and round to
# Start Race. A asks again, No puts the save back and starts the race. Its
# grid and countdown are captured; nothing is pressed in the race.
#
# -Cop: down to the item, Unlock Everything, Debug Race's Mode to Be The
# Cop, B twice to the prompt, Yes and the card's own overwrite Yes: the
# Autosave screen saves and moves back to the main menu. In again, up from
# Car to Start Race, which with nothing changed starts the race at once.

$loading = Wait-ForLog "global chunks loaded" 60
Write-Host ("  LOADING drawn: {0}" -f $loading)
$booted = Wait-ForLog "entering main loop" 60
Write-Host ("  main loop: {0}" -f $booted)

$shown = $false; $atDebug = $false; $raced = $false
$asked = $false; $answered = $false
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
        Shot "mainmenu"
        if ($Cop) {
            # The config showed the item at boot: down three to it.
            for ($i = 0; $i -lt 3; $i++) { Press $VK_G }
            $shown = $true
            Shot "fourth-item"
        } else {
            # L and R held, then Up.
            [Hp2Dbg]::KeyDown($hwnd, $VK_Q)
            [Hp2Dbg]::KeyDown($hwnd, $VK_W)
            Start-Sleep -Milliseconds 250
            [Hp2Dbg]::PressKey($hwnd, $VK_T)
            Start-Sleep -Milliseconds 250
            [Hp2Dbg]::KeyUp($hwnd, $VK_W)
            [Hp2Dbg]::KeyUp($hwnd, $VK_Q)
            $shown = Wait-ForLog "debug menu shown" 12
            Write-Host ("  item shown: {0}" -f $shown)
            Start-Sleep -Milliseconds 1500
            Shot "revealed"
        }
        if ($shown) {
            Press $VK_A 300                   # A, Debug Menu
            $atDebug = Wait-ForLog "flow enter Port Debug Menu" 12
            Write-Host ("  debug screen: {0}" -f $atDebug)
        }
    } else {
        Shot "no-main-menu"
    }
}

function Start-AndWatch {
    $script:raced = Wait-ForLog "race start: track" 20
    Write-Host ("  race started: {0}" -f $script:raced)
    if ($script:raced) {
        Start-Sleep -Seconds 12
        Shot "race"
        Start-Sleep -Seconds 8
        Shot "race-later"
    }
}

if ($atDebug -and $Cop) {
    Start-Sleep -Milliseconds 1500
    Shot "debug"
    for ($i = 0; $i -lt 3; $i++) { Press $VK_G 500 }   # Unlock Everything
    Press $VK_A                               # A
    $unlocked = Wait-ForLog "debug menu: unlocked" 10
    Write-Host ("  unlocked: {0}" -f $unlocked)
    Shot "unlocked"
    for ($i = 0; $i -lt 3; $i++) { Press $VK_T 500 }   # Start Debug Race
    Press $VK_A 300
    $page = Wait-ForLog "flow enter Port Debug Race" 10
    Write-Host ("  race page: {0}" -f $page)
    Start-Sleep -Milliseconds 1200
    Press $VK_G                               # Mode
    Press $VK_F                               # round to Be The Cop
    Press $VK_G                               # Track
    Press $VK_G                               # Time Of Day
    Press $VK_G                               # Direction
    Press $VK_G                               # Car: the cop cars
    Shot "cop-car"
    Press $VK_S 1200                          # B, Debug Menu
    Press $VK_S 300                           # B: the prompt
    $asked = Wait-ForLog "debug menu: asking to save" 10
    Start-Sleep -Milliseconds 1200
    Shot "ask"
    Press $VK_A 300                           # Yes
    $answered = Wait-ForLog "debug menu: save: yes" 10
    $autosave = Wait-ForLog "flow enter Autosave" 10
    Write-Host ("  asked {0}, yes {1}, Autosave {2}" -f $asked, $answered, $autosave)
    # The card's own question after a second of Checking: overwrite the
    # file, or make one. Both start on No.
    Start-Sleep -Milliseconds 3500
    Shot "card-asks"
    Press $VK_F 400                           # to Yes
    Press $VK_A 300
    $saved = Wait-ForLog "memcard: saved" 15
    Write-Host ("  saved: {0}" -f $saved)
    Start-Sleep -Milliseconds 1500
    Shot "saved"
    $back = Wait-ForLogCount "flow enter New Main Menu" 2 15
    Write-Host ("  back at the main menu: {0}" -f $back)
    if ($back) {
        Start-Sleep -Milliseconds 2000
        Shot "main-again"
        for ($i = 0; $i -lt 3; $i++) { Press $VK_G }
        Press $VK_A 300
        [void](Wait-ForLogCount "flow enter Port Debug Menu" 3 10)
        Start-Sleep -Milliseconds 1200
        Press $VK_A 300                       # Start Debug Race
        [void](Wait-ForLogCount "flow enter Port Debug Race" 2 10)
        Start-Sleep -Milliseconds 1200
        Shot "race-page-again"
        # The page opens on the row it was left on, Car: up five.
        for ($i = 0; $i -lt 5; $i++) { Press $VK_T 500 }
        [Hp2Dbg]::PressKey($hwnd, $VK_A)      # A: nothing to save
        Start-AndWatch
    }
} elseif ($atDebug) {
    Start-Sleep -Milliseconds 1500
    Shot "debug"
    Press $VK_G                               # NFS Points
    Press $VK_H                               # +10,000
    Shot "points"
    Press $VK_G                               # Set Save to 100%
    Press $VK_A
    $full = Wait-ForLog "debug menu: save set to 100%" 10
    Write-Host ("  100%: {0}" -f $full)
    Shot "full"
    Press $VK_S 300                           # B: the prompt
    $asked = Wait-ForLog "debug menu: asking to save" 10
    Start-Sleep -Milliseconds 1200
    Shot "ask"
    Press $VK_S 300                           # B: stay
    $stayed = Wait-ForLog "debug menu: save: stay" 10
    Write-Host ("  asked {0}, stayed {1}" -f $asked, $stayed)
    Start-Sleep -Milliseconds 1000
    Shot "stayed"
    Press $VK_T                               # NFS Points
    Press $VK_T                               # Start Debug Race
    Press $VK_A 300
    $page = Wait-ForLog "flow enter Port Debug Race" 10
    Write-Host ("  race page: {0}" -f $page)
    Start-Sleep -Milliseconds 1500
    Shot "race-page"
    Press $VK_G                               # Mode
    Press $VK_H                               # Single Race
    Shot "mode-single"
    Press $VK_F                               # back to Hot Pursuit
    Press $VK_G                               # Track
    Press $VK_H                               # the next track
    Shot "track"
    Press $VK_G                               # Time Of Day
    Press $VK_H
    Press $VK_G                               # Direction
    Press $VK_G                               # Car
    Press $VK_H                               # the next car
    Shot "car"
    Press $VK_G                               # Colour, the seventh row
    Press $VK_G                               # Opponents: a scroll
    Shot "scrolled"
    for ($i = 0; $i -lt 4; $i++) { Press $VK_G 500 }   # Gearbox
    Shot "last"
    Press $VK_G                               # round to Start Race
    Shot "wrapped"
    Press $VK_A 300                           # A: the prompt again
    $asked = Wait-ForLogCount "debug menu: asking to save" 2 10
    Start-Sleep -Milliseconds 1200
    Shot "ask-race"
    Press $VK_H 400                           # to No
    [Hp2Dbg]::PressKey($hwnd, $VK_A)
    $answered = Wait-ForLog "debug menu: save: no" 10
    Write-Host ("  asked again {0}, no {1}" -f $asked, $answered)
    Start-AndWatch
}

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
$lines = $dbg | Where-Object { $_ -match "debug menu|Port Debug|Autosave|memcard: saved|race start|  driver " }

$verdict = "UNKNOWN"
if (-not $booted)       { $verdict = "FAIL (never reached the main loop)" }
elseif ($crash)         { $verdict = "FAIL (crash: $($crash[0]))" }
elseif ($unmapped)      { $verdict = "FAIL ($(@($unmapped).Count) unmapped accesses, first: $(@($unmapped)[0]))" }
elseif (-not $shown)    { $verdict = "PARTIAL (the chord showed nothing)" }
elseif (-not $atDebug)  { $verdict = "PARTIAL (never entered the debug screen)" }
elseif (-not $asked)    { $verdict = "PARTIAL (no save prompt)" }
elseif (-not $answered) { $verdict = "PARTIAL (the prompt's answer went nowhere)" }
elseif ($Cop -and -not $saveWritten) { $verdict = "PARTIAL (Yes wrote no save)" }
elseif (-not $raced)    { $verdict = "PARTIAL (Start Race started nothing)" }
elseif (-not $survived) { $verdict = "FAIL (the race started, then the app died)" }
elseif ($Cop)           { $verdict = "PASS (config, unlock, prompt, save, Be The Cop race)" }
else                    { $verdict = "PASS (chord, 100%, prompt, Debug Race, No, race)" }

Write-Host ""
Write-Host "=== debug menu lines ==="
$lines | Select-Object -Last 20 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== nfshp2_debug.txt (last 25) ==="
$dbg | Select-Object -Last 25 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== azahar_log.txt errors ==="
$az | Where-Object { $_ -match "Error|Critical|PANIC" } | Select-Object -Last 12 |
    ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== Result ==="
if ($Cop) { Write-Host ("Save written: {0} (put back)" -f $saveWritten) }
Write-Host ("Verdict:    {0}" -f $verdict)
Write-Host ("Screenshots: {0} in {1}" -f $step, $OutDir)
