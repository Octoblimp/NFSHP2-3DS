# Boots NFSHP2-3DS.3dsx in Azahar with R held, which is the port's SkipFE
# switch, and reports how far the race start gets: StartSkipFEGame's
# drivers, the flow's states and the loads after them, from
# sdmc:/nfshp2_debug.txt, with a few captures along the way.
#
# The fourth of the run scripts, beside run_azahar_test.ps1 (the boot flow),
# run_azahar_geo.ps1 (one car at a time) and run_azahar_track.ps1 (the track
# viewer), and built the same way; the Add-Type block is the track script's,
# cut down. R is pressed again and again from the moment the window exists
# until the log says InitFred has run, since main reads the pad once, before
# InitFred, and Azahar drops a press made before its render window is up.
#
# Usage:
#   powershell -File tools/run_azahar_race.ps1
#   powershell -File tools/run_azahar_race.ps1 -WatchSeconds 60
#   powershell -File tools/run_azahar_race.ps1 -HoldKeys 65   # A, the gas
#   powershell -File tools/run_azahar_race.ps1 -HoldKeys 65,70 -ShotSeconds 1
#                                    # a circle to the left, a shot a second
#
# -HoldKeys are virtual-key codes in Azahar's default keyboard profile (A is
# 65, B 83, the D-pad's left and right F 70 and H 72), held from the moment
# the flow enters RACING until the run ends. They are posted again every
# 150 ms, as R is, so a press Azahar drops does not end the hold.

param(
    [int]$WatchSeconds = 30,      # after the race start, before the last shot
    [int]$RunSeconds = 180,       # hard ceiling on the whole run
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = "",
    [int[]]$HoldKeys = @(),
    [double]$ShotSeconds = 5      # between the shots while racing
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_race" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not (Test-Path $AzaharExe)) { throw "Azahar not found at $AzaharExe" }
if (-not (Test-Path $Target3dsx)) { throw "Target .3dsx not found at $Target3dsx" }

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Drawing;
public class Hp2Race {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern int PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern IntPtr PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    public struct RECT { public int Left, Top, Right, Bottom; }
    public const uint WM_KEYDOWN = 0x0100;
    public const uint WM_KEYUP = 0x0101;
    public const uint WM_CLOSE = 0x0010;
    public static void KeyDown(IntPtr h, int vk) { PostMessage(h, WM_KEYDOWN, (IntPtr)vk, IntPtr.Zero); }
    public static void KeyUp(IntPtr h, int vk) { PostMessage(h, WM_KEYUP, (IntPtr)vk, IntPtr.Zero); }

    // Azahar's launch dialogs; see run_azahar_track.ps1.
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
            PostMessage(h, WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
            sClosed++;
            return true;
        }, IntPtr.Zero);
        return sClosed;
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

[void][Hp2Race]::SetProcessDPIAware()

# Azahar's default keyboard profile: R is 'W'.
$VK_W = 87

$debugLog = Join-Path $env:APPDATA "Azahar\sdmc\nfshp2_debug.txt"
Remove-Item $debugLog -ErrorAction SilentlyContinue
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
[Hp2Race]::KeyDown($hwnd, $VK_W)
$closed = [Hp2Race]::DismissPopups([uint32]$proc.Id, $hwnd)
if ($closed -gt 0) {
    Write-Host "  dismissed $closed launch dialog(s)"
    [Hp2Race]::KeyDown($hwnd, $VK_W)
}

$start = Get-Date
function Elapsed { ((Get-Date) - $start).TotalSeconds }
function Alive { $proc.Refresh(); -not $proc.HasExited }

function Wait-ForLog([string]$pattern, [int]$timeoutSec) {
    $end = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $end) {
        if (-not (Alive)) { return $false }
        if (Test-Path $debugLog) {
            if (Select-String -Path $debugLog -Pattern $pattern -Quiet -ErrorAction SilentlyContinue) { return $true }
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
    [Hp2Race]::CaptureToFile($hwnd, $path)
    Write-Host ("  [{0,5:N1}s] {1}" -f (Elapsed), $path)
}

# A press posted before the render window takes the keyboard is dropped,
# so R goes in again every 150 ms until the log says InitFred has run.
Write-Host "Holding R through InitFred..."
$fred = $false
$holdEnd = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $holdEnd -and (Alive)) {
    [Hp2Race]::KeyDown($hwnd, $VK_W)
    if ((Test-Path $debugLog) -and (Select-String -Path $debugLog -Pattern "fred defaults" -Quiet -ErrorAction SilentlyContinue)) {
        $fred = $true
        break
    }
    Start-Sleep -Milliseconds 150
}
[Hp2Race]::KeyUp($hwnd, $VK_W)
Write-Host ("  InitFred: {0}" -f $fred)
if (-not $fred) { if (Alive) { $proc | Stop-Process -Force }; throw "never reached InitFred" }

$skip = Wait-ForLog "SkipFE: R held" 2
$race = Wait-ForLog "race start:" 30
$loop = Wait-ForLog "entering main loop" 60
Write-Host ("  SkipFE: {0}  race start: {1}  main loop: {2}" -f $skip, $race, $loop)
Shot "race-start"

if ($HoldKeys.Count -gt 0) {
    $racing = Wait-ForLog "flow state RACING" 60
    Write-Host ("  RACING: {0}; holding {1}" -f $racing, ($HoldKeys -join ","))
}

$end = (Get-Date).AddSeconds($WatchSeconds)
$n = 1
$nextShot = (Get-Date).AddSeconds($ShotSeconds)
while ((Get-Date) -lt $end -and (Alive)) {
    foreach ($k in $HoldKeys) { [Hp2Race]::KeyDown($hwnd, $k) }
    Start-Sleep -Milliseconds 150
    if ((Get-Date) -ge $nextShot) {
        $n++
        Shot ("race-{0}" -f $n)
        $nextShot = (Get-Date).AddSeconds($ShotSeconds)
    }
}
foreach ($k in $HoldKeys) { [Hp2Race]::KeyUp($hwnd, $k) }
if (Alive) { $proc | Stop-Process -Force }

Write-Host ""
Write-Host "Shots in $OutDir"
if (Test-Path $debugLog) {
    Write-Host "--- nfshp2_debug.txt (race lines) ---"
    Select-String -Path $debugLog -Pattern "SkipFE|race start|  driver|flow (want|state|begin|end|load)|carloader|resource|streamed|global chunks|abort|assert|fatal" |
        Select-Object -Last 80 |
        ForEach-Object { Write-Host ("  " + $_.Line) }
}
if (-not ($skip -and $race)) { exit 1 }
