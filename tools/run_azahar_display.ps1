# Boots NFSHP2-3DS.3dsx in Azahar and walks Options' Display (TASKS 71c,
# displayoptions.h): every Display Options row changed with Right, the
# track map back with Left, Down past Customize P1 HUD (the hidden P2 and
# Calibrate rows stop it), Customize P1 HUD's seven rows changed, B back;
# then B with the save prompt, stayed and answered No (the settings put
# back, checked on the way in again), and the track map with Yes (saved on
# the Autosave screen). The capture and key methods are
# run_azahar_test.ps1's; see its header for why each is the way it is.
# NFSHP2/SAVES/settings.db is put back after.
#
# Usage:
#   powershell -File tools/run_azahar_display.ps1
#   powershell -File tools/run_azahar_display.ps1 -OutDir C:\shots

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
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_display" }
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
# The boot as run_azahar_credits.ps1 has it, to the main menu and Options;
# Display is Options' third row.
#   Track Map Right, then Left back; Down and Right on the mirror, units,
#     leaderboard, jump cams and Zone cams; Down to Customize P1 HUD, Down
#     once more (it stays: the rows below are hidden), A.
#   Customize P1 HUD: Right on each of the seven rows; B: Display Options.
#   B: the save prompt; B on it stays; B again, Right and A: No, the
#     settings put back and Options.
#   Display again (on the row it was left on): Up to the top, Track Map
#     Right, B, Yes: the Autosave screen, its overwrite question Yes, and
#     Options.

$loading = Wait-ForLog "global chunks loaded" 60
Write-Host ("  LOADING drawn: {0}" -f $loading)
$booted = Wait-ForLog "entering main loop" 60
Write-Host ("  main loop: {0}" -f $booted)

$atDisplay = $false; $map = $false; $mapBack = $false; $mirror = $false
$units = $false; $board = $false; $jump = $false; $zone = $false
$hud = $false; $hudRows = $false; $hudOut = $false; $displayAgain = $false
$asked = $false; $stayed = $false; $no = $false; $optionsAfterNo = $false
$putBack = $false; $yesMap = $false; $yes = $false; $saved = $false
$optionsAfterYes = $false

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
            Press $VK_G 400                   # Controller
            Press $VK_G 400                   # Display
            Press $VK_A 300
            $atDisplay = Wait-ForLog "display options: in" 10
            Write-Host ("  Display Options: {0}" -f $atDisplay)
        }
    } else {
        Shot "no-main-menu"
    }
}

if ($atDisplay) {
    Start-Sleep -Milliseconds 1500
    Shot "display"
    Press $VK_H 600                           # Right: the track map
    $map = Wait-ForLog "display: track map " 10
    Start-Sleep -Milliseconds 800
    Shot "track-map"
    Press $VK_F 600                           # Left: back
    $mapBack = Wait-ForLogCount "display: track map " 2 10
    Write-Host ("  track map: {0}, back: {1}" -f $map, $mapBack)
    Press $VK_G 500; Press $VK_H 600          # the mirror
    $mirror = Wait-ForLog "display: mirror " 10
    Press $VK_G 500; Press $VK_H 600          # the units
    $units = Wait-ForLog "display: units " 10
    Press $VK_G 500; Press $VK_H 600          # the leaderboard
    $board = Wait-ForLog "display: leaderboard " 10
    Press $VK_G 500; Press $VK_H 600          # the jump cams
    $jump = Wait-ForLog "display: jump cams " 10
    Press $VK_G 500; Press $VK_H 600          # the Zone cams
    $zone = Wait-ForLog "display: zone cams " 10
    Write-Host ("  mirror: {0}, units: {1}, board: {2}, jump: {3}, zone: {4}" -f $mirror, $units, $board, $jump, $zone)
    Start-Sleep -Milliseconds 800
    Shot "changed"
    Press $VK_G 500                           # Customize P1 HUD
    Press $VK_G 500                           # Down: stays
    Start-Sleep -Milliseconds 800
    Shot "last-row"
    Press $VK_A 300
    $hud = Wait-ForLog "customize hud: in" 12
    Write-Host ("  Customize P1 HUD: {0}" -f $hud)
}

if ($hud) {
    Start-Sleep -Milliseconds 2000
    Shot "hud"
    Press $VK_H 600                           # Right: the lookback
    for ($i = 0; $i -lt 6; $i++) {
        Press $VK_G 500                       # Down
        Press $VK_H 600                       # Right
    }
    $hudRows = Wait-ForLogCount "customize hud: row " 7 12
    Write-Host ("  HUD rows changed: {0}" -f $hudRows)
    Start-Sleep -Milliseconds 800
    Shot "hud-changed"
    Press $VK_S 300                           # B
    $hudOut = Wait-ForLog "customize hud: out" 10
    $displayAgain = Wait-ForLogCount "display options: in" 2 12
    Write-Host ("  out: {0}, Display Options again: {1}" -f $hudOut, $displayAgain)
}

if ($displayAgain) {
    Start-Sleep -Milliseconds 1500
    Shot "display-again"
    Press $VK_S 300                           # B: the prompt
    $asked = Wait-ForLog "display back: changed, asking to save" 10
    Start-Sleep -Milliseconds 1500
    Shot "prompt"
    Press $VK_S 300                           # B on the popup: stay
    $stayed = Wait-ForLog "display save: stay" 10
    Start-Sleep -Milliseconds 1200
    Shot "stayed"
    Press $VK_S 300                           # B
    if (Wait-ForLogCount "display back: changed, asking to save" 2 10) {
        Start-Sleep -Milliseconds 1200
        Press $VK_H                           # Right: No
        Press $VK_A 300
        $no = Wait-ForLog "display save: no, settings put back" 10
    }
    $optionsAfterNo = Wait-ForLogCount "flow enter Options" 2 12
    Write-Host ("  asked: {0}, stayed: {1}, no: {2}, Options: {3}" -f $asked, $stayed, $no, $optionsAfterNo)
}

if ($optionsAfterNo) {
    Start-Sleep -Milliseconds 1500
    Press $VK_A 300                           # Display
    if (Wait-ForLogCount "display options: in" 3 12) {
        # No put back what the first way in found.
        $ins = @(Get-Content $debugLog | Where-Object { $_ -match "display options: in," })
        if ($ins.Count -ge 3) {
            $first = $ins[0] -replace "^.*display options: in", ""
            $third = $ins[2] -replace "^.*display options: in", ""
            $putBack = $first -eq $third
            Write-Host ("  put back: {0} ({1} / {2})" -f $putBack, $first, $third)
        }
        Start-Sleep -Milliseconds 1500
        # The menu comes back on the row it was left on (Customize P1 HUD):
        # Up to the top first, then Track Map Right.
        for ($i = 0; $i -lt 7; $i++) { Press $VK_T 400 }
        Press $VK_H 600                       # Right
        $yesMap = Wait-ForLogCount "display: track map " 3 10
        Start-Sleep -Milliseconds 800
        Press $VK_S 300                       # B
        if (Wait-ForLogCount "display back: changed, asking to save" 3 10) {
            Start-Sleep -Milliseconds 1200
            Press $VK_A 300                   # Yes
            $yes = Wait-ForLog "display save: yes" 10
        }
        Write-Host ("  track map: {0}, yes: {1}" -f $yesMap, $yes)
        # The Autosave screen's overwrite question, opened on No: the
        # fourth popup with a Yes.
        if ($yes -and (Wait-ForLogCount "flow language id 0ce3f7ce e0105663 150103" 4 15)) {
            Start-Sleep -Milliseconds 1500
            Shot "overwrite"
            Press $VK_F                       # Left: Yes
            Press $VK_A 300
            $saved = Wait-ForLog "memcard: saved" 20
        }
        $optionsAfterYes = Wait-ForLogCount "flow enter Options" 3 30
        Start-Sleep -Milliseconds 1500
        Shot "options-last"
    }
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
$lines = $dbg | Where-Object { $_ -match "display|customize hud|flow enter|memcard: saved" }

$verdict = "UNKNOWN"
if (-not $booted)          { $verdict = "FAIL (never reached the main loop)" }
elseif ($crash)            { $verdict = "FAIL (crash: $($crash[0]))" }
elseif ($unmapped)         { $verdict = "FAIL ($(@($unmapped).Count) unmapped accesses, first: $(@($unmapped)[0]))" }
elseif (-not $survived)    { $verdict = "FAIL (the app died)" }
elseif (-not $atDisplay)   { $verdict = "PARTIAL (never reached Display Options)" }
elseif (-not $mapBack)     { $verdict = "PARTIAL (the track map did not change and back)" }
elseif (-not ($mirror -and $units -and $board -and $jump -and $zone)) { $verdict = "PARTIAL (a Display Options row did not change)" }
elseif (-not $hud)         { $verdict = "PARTIAL (never reached Customize P1 HUD)" }
elseif (-not $hudRows)     { $verdict = "PARTIAL (not every HUD row changed)" }
elseif (-not $displayAgain) { $verdict = "PARTIAL (B did not go back to Display Options)" }
elseif (-not $asked)       { $verdict = "PARTIAL (B with changes did not ask)" }
elseif (-not $stayed)      { $verdict = "PARTIAL (B on the prompt did not stay)" }
elseif (-not $no)          { $verdict = "PARTIAL (No did not put the settings back)" }
elseif (-not $optionsAfterNo) { $verdict = "PARTIAL (No did not go back to Options)" }
elseif (-not $putBack)     { $verdict = "PARTIAL (No left the settings changed)" }
elseif (-not $yesMap)      { $verdict = "PARTIAL (the track map did not change the second time)" }
elseif (-not $yes)         { $verdict = "PARTIAL (Yes did not save)" }
elseif (-not $optionsAfterYes) { $verdict = "PARTIAL (the save did not end on Options)" }
else                       { $verdict = "PASS (six rows, HUD seven rows, prompt stay/No put back/Yes, saved $saved)" }

Write-Host ""
Write-Host "=== display lines ==="
$lines | Select-Object -Last 60 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== azahar_log.txt errors ==="
$az | Where-Object { $_ -match "Error|Critical|PANIC" } | Select-Object -Last 12 |
    ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== Result ==="
Write-Host ("Save written: {0} (put back)" -f $saveWritten)
Write-Host ("Verdict:    {0}" -f $verdict)
Write-Host ("Screenshots: {0} in {1}" -f $step, $OutDir)
