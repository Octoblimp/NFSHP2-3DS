# Boots NFSHP2-3DS.3dsx in Azahar and walks Options' Audio (TASKS 71b,
# audiooptions.h): a slider stepped, the audio mode changed and back, the
# list scrolled to JukeBox Music, a genre picked, a tune picked and played,
# its status changed, the genre turned off and on with L; then B with the
# save prompt, stayed and answered No (the options put back), and Default
# Volumes with Yes (saved on the Autosave screen). The capture and key
# methods are run_azahar_test.ps1's; see its header for why each is the way
# it is. NFSHP2/SAVES/settings.db is put back after.
#
# Usage:
#   powershell -File tools/run_azahar_audio.ps1
#   powershell -File tools/run_azahar_audio.ps1 -OutDir C:\shots

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
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_audio" }
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
# Audio is Options' first row.
#   Menu Music: Right twice and Left once.
#   Down seven to Audio Mode (the list scrolls): Right, then Left back.
#   Down to Jukebox, A: JukeBox Music. Right to the next genre and Left
#     back; Down into the list, Down to the second tune (it plays half a
#     second later), Right to set when it plays; L turns the genre off
#     (out of the list), L again on.
#   B: Audio Options again. B: the save prompt; B on it stays; B again,
#     Right and A: No, the options put back and Options.
#   Audio again (on the row it was left on): Up to the top, Menu Music
#     Right, Audio Mode Right, Default Volumes, B, Yes: the Autosave screen,
#     its overwrite question Yes, and Options.

$loading = Wait-ForLog "global chunks loaded" 60
Write-Host ("  LOADING drawn: {0}" -f $loading)
$booted = Wait-ForLog "entering main loop" 60
Write-Host ("  main loop: {0}" -f $booted)

$atAudio = $false; $slid = $false; $mode = $false; $modeBack = $false
$juke = $false; $genre = $false; $played = $false; $status = $false
$off = $false; $on = $false; $jukeBack = $false; $audioAgain = $false
$asked = $false; $stayed = $false; $no = $false; $optionsAfterNo = $false
$defaults = $false; $yes = $false; $saved = $false; $optionsAfterYes = $false

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
            Shot "options"
            Press $VK_A 300                   # Audio
            $atAudio = Wait-ForLog "audio options: in" 10
            Write-Host ("  Audio Options: {0}" -f $atAudio)
        }
    } else {
        Shot "no-main-menu"
    }
}

if ($atAudio) {
    Start-Sleep -Milliseconds 1500
    Shot "audio"
    Press $VK_H 500                           # Right
    Press $VK_H 500                           # Right
    Press $VK_F 500                           # Left
    $slid = Wait-ForLogCount "slider 5: " 3 10
    Write-Host ("  menu music slider: {0}" -f $slid)
    Start-Sleep -Milliseconds 800
    Shot "slider"
    for ($i = 0; $i -lt 7; $i++) { Press $VK_G 500 }   # Audio Mode
    Start-Sleep -Milliseconds 1200
    Shot "scrolled"
    Press $VK_H 600                           # Right
    $mode = Wait-ForLog "audio mode " 10
    Start-Sleep -Milliseconds 800
    Shot "mode"
    Press $VK_F 600                           # Left
    $modeBack = Wait-ForLogCount "audio mode " 2 10
    Write-Host ("  mode: {0}, back: {1}" -f $mode, $modeBack)
    Press $VK_G 600                           # Jukebox
    Press $VK_A 300
    $juke = Wait-ForLog "jukebox: in" 12
    Write-Host ("  JukeBox Music: {0}" -f $juke)
}

if ($juke) {
    Start-Sleep -Milliseconds 2000
    Shot "jukebox"
    Press $VK_H 600                           # Right: the next genre
    $genre = Wait-ForLog "jukebox: genre \d+$" 10
    Start-Sleep -Milliseconds 800
    Shot "genre"
    Press $VK_F 600                           # Left: back
    Press $VK_G 600                           # Down: into the list
    Press $VK_G 600                           # Down: the second tune
    $played = Wait-ForLogCount "jukebox: playing" 2 12
    Write-Host ("  genre: {0}, tunes played: {1}" -f $genre, $played)
    Start-Sleep -Milliseconds 1000
    Shot "list"
    Press $VK_H 600                           # Right: when it plays
    $status = Wait-ForLog "jukebox: tune \d+ status" 10
    Start-Sleep -Milliseconds 800
    Shot "status"
    Press $VK_Q 600                           # L: the genre off
    $off = Wait-ForLog "jukebox: genre \d+ off" 10
    Start-Sleep -Milliseconds 800
    Shot "genre-off"
    Press $VK_Q 600                           # L: on again
    $on = Wait-ForLog "jukebox: genre \d+ on" 10
    Write-Host ("  status: {0}, off: {1}, on: {2}" -f $status, $off, $on)
    Start-Sleep -Milliseconds 800
    Press $VK_S 300                           # B
    $jukeBack = Wait-ForLog "jukebox back: " 10
    $audioAgain = Wait-ForLogCount "audio options: in" 2 12
    Write-Host ("  back: {0}, Audio Options again: {1}" -f $jukeBack, $audioAgain)
}

if ($audioAgain) {
    Start-Sleep -Milliseconds 1500
    Shot "audio-again"
    Press $VK_S 300                           # B: the prompt
    $asked = Wait-ForLog "audio back: changed, asking to save" 10
    Start-Sleep -Milliseconds 1500
    Shot "prompt"
    Press $VK_S 300                           # B on the popup: stay
    $stayed = Wait-ForLog "audio save: stay" 10
    Start-Sleep -Milliseconds 1200
    Shot "stayed"
    Press $VK_S 300                           # B
    if (Wait-ForLogCount "audio back: changed, asking to save" 2 10) {
        Start-Sleep -Milliseconds 1200
        Press $VK_H                           # Right: No
        Press $VK_A 300
        $no = Wait-ForLog "audio save: no, options put back" 10
    }
    $optionsAfterNo = Wait-ForLogCount "flow enter Options" 2 12
    Write-Host ("  asked: {0}, stayed: {1}, no: {2}, Options: {3}" -f $asked, $stayed, $no, $optionsAfterNo)
}

if ($optionsAfterNo) {
    Start-Sleep -Milliseconds 1500
    Press $VK_A 300                           # Audio
    if (Wait-ForLogCount "audio options: in" 3 12) {
        Start-Sleep -Milliseconds 1500
        # The menu comes back on the row it was left on (Jukebox): Up to
        # the top first, then Menu Music Right, Audio Mode Right (a change
        # Default Volumes leaves alone, so B asks) and Default Volumes.
        for ($i = 0; $i -lt 11; $i++) { Press $VK_T 400 }
        Press $VK_H 500                       # Right: Menu Music
        for ($i = 0; $i -lt 7; $i++) { Press $VK_G 500 }   # Audio Mode
        Press $VK_H 600                       # Right
        Press $VK_G 500                       # Jukebox
        Press $VK_G 500                       # Default Volumes
        Press $VK_A 300
        $defaults = Wait-ForLog "audio: default volumes" 10
        Start-Sleep -Milliseconds 1000
        Shot "defaults"
        Press $VK_S 300                       # B
        if (Wait-ForLogCount "audio back: changed, asking to save" 3 10) {
            Start-Sleep -Milliseconds 1200
            Press $VK_A 300                   # Yes
            $yes = Wait-ForLog "audio save: yes" 10
        } elseif (Wait-ForLogCount "audio back: unchanged" 1 5) {
            $yes = "unchanged"
        }
        Write-Host ("  defaults: {0}, yes: {1}" -f $defaults, $yes)
        # The Autosave screen's overwrite question, opened on No: the
        # fourth popup with a Yes.
        if ($yes -eq $true -and (Wait-ForLogCount "flow language id 0ce3f7ce e0105663 150103" 4 15)) {
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
$lines = $dbg | Where-Object { $_ -match "audio|slider|jukebox|flow enter|memcard: saved" }

$verdict = "UNKNOWN"
if (-not $booted)          { $verdict = "FAIL (never reached the main loop)" }
elseif ($crash)            { $verdict = "FAIL (crash: $($crash[0]))" }
elseif ($unmapped)         { $verdict = "FAIL ($(@($unmapped).Count) unmapped accesses, first: $(@($unmapped)[0]))" }
elseif (-not $survived)    { $verdict = "FAIL (the app died)" }
elseif (-not $atAudio)     { $verdict = "PARTIAL (never reached Audio Options)" }
elseif (-not $slid)        { $verdict = "PARTIAL (the menu music slider did not move)" }
elseif (-not $modeBack)    { $verdict = "PARTIAL (the audio mode did not change and back)" }
elseif (-not $juke)        { $verdict = "PARTIAL (never reached JukeBox Music)" }
elseif (-not $genre)       { $verdict = "PARTIAL (Right did not change the genre)" }
elseif (-not $played)      { $verdict = "PARTIAL (picking tunes played nothing)" }
elseif (-not $status)      { $verdict = "PARTIAL (Right did not change the tune's status)" }
elseif (-not ($off -and $on)) { $verdict = "PARTIAL (L did not turn the genre off and on)" }
elseif (-not $audioAgain)  { $verdict = "PARTIAL (B did not go back to Audio Options)" }
elseif (-not $asked)       { $verdict = "PARTIAL (B with changes did not ask)" }
elseif (-not $stayed)      { $verdict = "PARTIAL (B on the prompt did not stay)" }
elseif (-not $no)          { $verdict = "PARTIAL (No did not put the options back)" }
elseif (-not $optionsAfterNo) { $verdict = "PARTIAL (No did not go back to Options)" }
elseif (-not $defaults)    { $verdict = "PARTIAL (Default Volumes did nothing)" }
elseif ($yes -ne $true -and $yes -ne "unchanged") { $verdict = "PARTIAL (Yes did not save)" }
elseif (-not $optionsAfterYes) { $verdict = "PARTIAL (the save did not end on Options)" }
else                       { $verdict = "PASS (slider, mode, jukebox genre/tune/status/L, prompt stay/No/Yes $yes, saved $saved)" }

Write-Host ""
Write-Host "=== audio lines ==="
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
