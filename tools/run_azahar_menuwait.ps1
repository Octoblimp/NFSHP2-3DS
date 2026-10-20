# Boots NFSHP2-3DS.3dsx in Azahar to the main menu and checks its wait for
# the attract demo: FlailerScreenList::JoyHandler sends the screen up
# ANY_BUTTON_PRESSED (message 24) for every button no popup takes, and the
# main menu restarts its 30-second wait on it. So the run presses D-Pad Down
# and Up in turn every -PressSeconds for -BusySeconds, longer than the wait,
# and no demo may start; then it presses nothing, and the demo must start
# about 30 s after the last press. Down and Up are no cheat code's. The
# capture and key methods are run_azahar_test.ps1's; see its header for why
# each is the way it is.
#
# sdmc:/nfshp2_config.txt must not set SkipFE: the run needs the frontend.
#
# Usage:
#   powershell -File tools/run_azahar_menuwait.ps1

param(
    [int]$BusySeconds = 50,       # pressing on the main menu, past the wait
    [int]$PressSeconds = 6,       # between those presses
    [int]$IdleSeconds = 60,       # the longest the idle demo may take
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_menuwait" }
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

$VK_A = 65; $VK_M = 77; $VK_T = 84; $VK_G = 71

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

function LogCount([string]$pattern) {
    if (-not (Test-Path $debugLog)) { return 0 }
    @(Select-String -Path $debugLog -Pattern $pattern -ErrorAction SilentlyContinue).Count
}

# Wait for a line matching $pattern in the app's own log, or give up.
function Wait-ForLog([string]$pattern, [int]$timeoutSec) {
    $end = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $end) {
        if (-not (Alive)) { return $false }
        if ((LogCount $pattern) -gt 0) { return $true }
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

# --- the script the run follows -------------------------------------------
# The boot as run_azahar_attract.ps1 has it, to the title with PRESS START
# up; START to the main menu; the presses; then nothing.

$booted = Wait-ForLog "entering main loop" 90
Write-Host ("  main loop: {0}" -f $booted)

$menu = $false; $busyDemo = $false; $presses = 0; $sent = 0
$idleDemo = $false; $idleAfter = -1.0
if ($booted) {
    $gotLang = Wait-ForLog "flow enter Language Options Pre FE" 30
    if ($gotLang) {
        Start-Sleep -Milliseconds 1500
        [void](Press-Until $VK_A "flow leave Language Options Pre FE" 4 8)   # A, English
    }
    $gotIntro = Wait-ForLog "^movie open MOVIES/INTRO/NFSINTRO" 40
    if ($gotIntro) {
        Start-Sleep -Seconds 2
        # The log runs up to 7 s behind: a second START too soon would go
        # past PRESS START to the main menu, which is where this run goes.
        [void](Press-Until $VK_M "flow title skip" 3 9)   # START: stop the intro
    }
    [void](Wait-ForLog "flow vis object b5761d00 b070dbc9 1" 15)
    Start-Sleep -Milliseconds 900
    $menu = Press-Until $VK_M "flow enter New Main Menu" 3 9   # START: the menu
    Write-Host ("  [{0,5:N1}s] on the main menu: {1}" -f (Elapsed), $menu)

    if ($menu) {
        Start-Sleep -Seconds 2
        Shot "mainmenu"
        $busyEnd = (Get-Date).AddSeconds($BusySeconds)
        $down = $true
        while ((Get-Date) -lt $busyEnd -and (Alive)) {
            $vk = if ($down) { $VK_G } else { $VK_T }
            [Hp2Cap]::PressKey($hwnd, $vk)
            $lastPress = Elapsed
            $presses++
            $down = -not $down
            Start-Sleep -Seconds $PressSeconds
        }
        Shot "busy-end"
        # The log is up to 7 s behind: a demo the presses let start is in
        # it by then.
        Start-Sleep -Seconds 8
        $busyDemo = (LogCount "flow demo mode") -gt 0
        $sent = LogCount "flow msg New Main Menu 24"
        Write-Host ("  [{0,5:N1}s] {1} presses, {2} message-24 lines, a demo while pressing: {3}" -f `
            (Elapsed), $presses, $sent, $busyDemo)

        if (-not $busyDemo) {
            $idleDemo = Wait-ForLog "flow demo mode" $IdleSeconds
            $idleAfter = (Elapsed) - $lastPress
            Write-Host ("  [{0,5:N1}s] the demo after pressing nothing: {1}, {2:N1} s after the last press (the log is up to 7 s late)" -f `
                (Elapsed), $idleDemo, $idleAfter)
            if ($idleDemo) { Start-Sleep -Seconds 4; Shot "idle-demo" }
        }
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
if (-not $booted)                  { $verdict = "FAIL (never reached the main loop)" }
elseif ($crash)                    { $verdict = "FAIL (crash: $($crash[0]))" }
elseif ($unmapped)                 { $verdict = "FAIL ($(@($unmapped).Count) unmapped accesses, first: $(@($unmapped)[0]))" }
elseif (-not $menu)                { $verdict = "FAIL (never reached the main menu)" }
elseif ($busyDemo)                 { $verdict = "FAIL (a demo started while the menu was pressed)" }
elseif ($sent -lt $presses)        { $verdict = "FAIL ($presses presses, $sent message-24 lines)" }
elseif (-not $idleDemo)            { $verdict = "FAIL (no demo once the presses stopped)" }
elseif ($idleAfter -lt 28)         { $verdict = "FAIL (the demo came $([int]$idleAfter) s after the last press, under the wait)" }
else                               { $verdict = "PASS (no demo while pressing for $BusySeconds s; one $([int]$idleAfter) s after the last press)" }

Write-Host ""
Write-Host "=== the main menu's flow ==="
$dbg | Where-Object { $_ -match "flow (demo|enter|leave|state|msg New Main Menu)|abort|assert|fatal" } |
    Select-Object -Last 60 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== azahar_log.txt errors ==="
$az | Where-Object { $_ -match "Error|Critical|PANIC" } | Select-Object -Last 12 |
    ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== Result ==="
Write-Host ("Verdict:    {0}" -f $verdict)
Write-Host ("Screenshots: {0} in {1}" -f $step, $OutDir)
