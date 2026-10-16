# Boots NFSHP2-3DS.3dsx in Azahar and summons the HELP panel (TASKS 48,
# helpmenu.h) with Y on the main menu, Hot Pursuit's Mode Select and
# Options, and checks that A does nothing while it is up. The capture and
# key methods are run_azahar_test.ps1's; see its header for why each is the
# way it is. NFSHP2/SAVES/settings.db and controls.bin are put back after.
#
# Usage:
#   powershell -File tools/run_azahar_help.ps1
#   powershell -File tools/run_azahar_help.ps1 -OutDir C:\shots

param(
    [int]$BootSeconds = 12,       # before the first capture: bundles decode slowly
    [int]$RunSeconds = 180,       # hard ceiling on the whole run
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_help" }
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
# And the keys' file beside it.
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
# The boot as run_azahar_controller.ps1 has it, to the main menu.
#   Y: the HELP panel in (help shown); A on it: nothing, the menu hears no
#     key while it is up; Y: out again (help hidden).
#   A: Hot Pursuit's Mode Select; Y: its four lines, the last "L1 + Cross
#     Manual Transmission", drawn L + A; Y: out. B: the main menu.
#   Down x3, A: Options; Y: its three lines; Y: out.

$loading = Wait-ForLog "global chunks loaded" 60
Write-Host ("  LOADING drawn: {0}" -f $loading)
$booted = Wait-ForLog "entering main loop" 60
Write-Host ("  main loop: {0}" -f $booted)

$atMain = $false; $mainIn = $false; $swallowed = $false; $mainOut = $false
$atMode = $false; $modeIn = $false; $modeOut = $false
$atOptions = $false; $optionsIn = $false; $optionsOut = $false
$backdrop = $false

if ($booted) {
    $backdrop = Wait-ForLog "help: backdrop found" 5
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
    $atMain = Wait-ForLog "flow enter New Main Menu" 12
    if (-not $atMain) { Shot "no-main-menu" }
}

if ($atMain) {
    Start-Sleep -Milliseconds 2500
    Shot "main-menu"
    Press $VK_Y 300                           # Y: the panel in
    $mainIn = Wait-ForLog "help shown" 10
    Start-Sleep -Milliseconds 1500
    Shot "main-help"
    Press $VK_A 2500                          # A: nothing while it is up
    $swallowed = -not (Select-String -Path $debugLog -Pattern "flow enter Cops On Mode Select" -Quiet -ErrorAction SilentlyContinue)
    Shot "main-help-after-a"
    Press $VK_Y 300                           # Y: out
    $mainOut = Wait-ForLog "help hidden" 10
    Start-Sleep -Milliseconds 1200
    Shot "main-help-gone"
    Write-Host ("  main menu: in {0}, A swallowed {1}, out {2}" -f $mainIn, $swallowed, $mainOut)

    Press $VK_A 300                           # Hot Pursuit
    $atMode = Wait-ForLog "flow enter Cops On Mode Select" 10
    if ($atMode) {
        Start-Sleep -Milliseconds 2000
        Press $VK_Y 300
        $modeIn = Wait-ForLogCount "help shown" 2 10
        Start-Sleep -Milliseconds 1500
        Shot "mode-help"
        Press $VK_Y 300
        $modeOut = Wait-ForLogCount "help hidden" 2 10
        Start-Sleep -Milliseconds 1200
        Press $VK_S 300                       # B: the main menu
        [void](Wait-ForLogCount "flow enter New Main Menu" 2 10)
        Start-Sleep -Milliseconds 2000
    }
    Write-Host ("  Mode Select: {0}, in {1}, out {2}" -f $atMode, $modeIn, $modeOut)

    Press $VK_G                               # World Racing
    Press $VK_G                               # Local Wireless
    Press $VK_G                               # Options
    Press $VK_A 300
    $atOptions = Wait-ForLog "flow enter Options" 10
    if ($atOptions) {
        Start-Sleep -Milliseconds 2000
        Press $VK_Y 300
        $optionsIn = Wait-ForLogCount "help shown" 3 10
        Start-Sleep -Milliseconds 1500
        Shot "options-help"
        Press $VK_Y 300
        $optionsOut = Wait-ForLogCount "help hidden" 3 10
        Start-Sleep -Milliseconds 1200
        Shot "options-help-gone"
    }
    Write-Host ("  Options: {0}, in {1}, out {2}" -f $atOptions, $optionsIn, $optionsOut)
}

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

$verdict = "UNKNOWN"
if (-not $booted)          { $verdict = "FAIL (never reached the main loop)" }
elseif ($crash)            { $verdict = "FAIL (crash: $($crash[0]))" }
elseif ($unmapped)         { $verdict = "FAIL ($(@($unmapped).Count) unmapped accesses, first: $(@($unmapped)[0]))" }
elseif (-not $survived)    { $verdict = "FAIL (the app died)" }
elseif (-not $backdrop)    { $verdict = "PARTIAL (the help screen's backdrop was not found)" }
elseif (-not $atMain)      { $verdict = "PARTIAL (never reached the main menu)" }
elseif (-not ($mainIn -and $mainOut)) { $verdict = "PARTIAL (Y did not toggle the panel on the main menu)" }
elseif (-not $swallowed)   { $verdict = "PARTIAL (A reached the menu under the panel)" }
elseif (-not ($atMode -and $modeIn -and $modeOut)) { $verdict = "PARTIAL (the Mode Select's panel)" }
elseif (-not ($atOptions -and $optionsIn -and $optionsOut)) { $verdict = "PARTIAL (Options' panel)" }
else                       { $verdict = "PASS (Y in and out on the main menu, Mode Select and Options; A swallowed under it)" }

Write-Host ""
Write-Host "=== azahar_log.txt errors ==="
$az | Where-Object { $_ -match "Error|Critical|PANIC" } | Select-Object -Last 12 |
    ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== Result ==="
Write-Host ("Save written: {0} (put back)" -f $saveWritten)
Write-Host ("Verdict:    {0}" -f $verdict)
Write-Host ("Screenshots: {0} in {1}" -f $step, $OutDir)
