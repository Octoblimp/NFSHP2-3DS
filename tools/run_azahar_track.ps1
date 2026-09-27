# Boots NFSHP2-3DS.3dsx in Azahar, walks into the track viewer, and
# captures the top screen from several places along TRACKB12.
#
# The third of the run scripts, beside run_azahar_test.ps1 (the boot flow)
# and run_azahar_geo.ps1 (one car at a time), and built the same way; the
# Add-Type block is the geometry script's. What this one answers is whether
# the ported cull and StuffScenery put the scenery where it belongs -- a
# checker proves the port and the ELF agree about the numbers, and only a
# picture says the numbers make a road.
#
# The shots are compared as well as saved: two captures a camera move apart
# that come out the same mean the camera or the cull is not listening.
#
# Usage:
#   powershell -File tools/run_azahar_track.ps1
#   powershell -File tools/run_azahar_track.ps1 -Stops 10

param(
    [int]$Stops = 6,              # route stops to jump through after the first
    [int]$RunSeconds = 300,       # hard ceiling on the whole run
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_track" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not (Test-Path $AzaharExe)) { throw "Azahar not found at $AzaharExe" }
if (-not (Test-Path $Target3dsx)) { throw "Target .3dsx not found at $Target3dsx" }

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Drawing;
public class Hp2Track {
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
    public static void PressKey(IntPtr h, int vk) {
        PostMessage(h, WM_KEYDOWN, (IntPtr)vk, IntPtr.Zero);
        System.Threading.Thread.Sleep(140);
        PostMessage(h, WM_KEYUP, (IntPtr)vk, IntPtr.Zero);
    }
    // Held keys, so a shot can be taken while the button is still down.
    // The zoom on the disc is a held button and the pad is a held
    // direction; a 140ms tap is one frame of either at this frame rate.
    public static void KeyDown(IntPtr h, int vk) { PostMessage(h, WM_KEYDOWN, (IntPtr)vk, IntPtr.Zero); }
    public static void KeyUp(IntPtr h, int vk) { PostMessage(h, WM_KEYUP, (IntPtr)vk, IntPtr.Zero); }

    // Azahar's "Update Available" dialog takes the foreground on launch and
    // blocks the emulator window from acting on posted keys, so a run that
    // ignores it presses SELECT eight times into a dialog and then reports
    // that the geometry viewer was never reached. Anything owned by the
    // process that is visible, titled, and not titled "Azahar" is one of
    // these; the emulator window and its Qt helper windows are all either
    // titled "Azahar" or untitled.
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
    // Mean absolute channel difference between two captures, 0..255. The
    // creep test below needs a number: two dark shots of the same car look
    // the same to a reader whatever the radius did between them.
    public static double MeanDiff(string a, string b) {
        using (Bitmap x = new Bitmap(a))
        using (Bitmap y = new Bitmap(b)) {
            if (x.Width != y.Width || x.Height != y.Height) { return 255.0; }
            double sum = 0; int n = 0;
            for (int j = 0; j < x.Height; j += 3) {
                for (int i = 0; i < x.Width; i += 3) {
                    Color p = x.GetPixel(i, j), q = y.GetPixel(i, j);
                    sum += Math.Abs(p.R - q.R) + Math.Abs(p.G - q.G) + Math.Abs(p.B - q.B);
                    n += 3;
                }
            }
            return n == 0 ? 255.0 : sum / n;
        }
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

[void][Hp2Track]::SetProcessDPIAware()

# Azahar's default keyboard profile; see run_azahar_geo.ps1 for the X/Y
# trap. A is 'A', B 'S', X 'Z', Y 'X', START 'M', SELECT 'N', L 'Q', R 'W',
# the D-pad T/G/F/H and the circle pad the arrow keys.
$VK_A = 65; $VK_S = 83; $VK_Z = 90; $VK_X = 88
$VK_M = 77; $VK_N = 78
$VK_T = 84; $VK_G = 71; $VK_F = 70; $VK_H = 72
$VK_Q = 81; $VK_W = 87
$VK_LEFT = 37; $VK_UP = 38; $VK_RIGHT = 39; $VK_DOWN = 40

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
$closed = [Hp2Track]::DismissPopups([uint32]$proc.Id, $hwnd)
if ($closed -gt 0) { Write-Host "  dismissed $closed launch dialog(s)" }

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
$last = ""
function Shot([string]$tag) {
    if (-not (Alive)) { return }
    $script:step++
    $path = Join-Path $OutDir ("{0:d2}_{1}.png" -f $script:step, $tag)
    [Hp2Track]::CaptureToFile($hwnd, $path)
    $note = ""
    if ($script:last -ne "") {
        $d = [Hp2Track]::MeanDiff($script:last, $path)
        $note = ("  diff {0:N2}" -f $d)
    }
    $script:last = $path
    Write-Host ("  [{0,5:N1}s] {1}{2}" -f (Elapsed), $path, $note)
}

function Hold([int]$vk, [int]$ms) {
    [Hp2Track]::KeyDown($hwnd, $vk)
    Start-Sleep -Milliseconds $ms
    [Hp2Track]::KeyUp($hwnd, $vk)
}

Write-Host "Waiting for the main loop..."
$booted = Wait-ForLog "entering main loop" 90
Write-Host ("  main loop: {0}" -f $booted)
if (-not $booted) { $proc | Stop-Process -Force; throw "never reached the main loop" }

# Three SELECTs: flow -> screens -> geometry -> track. Each is confirmed in
# the log before the next goes in, for the reason run_azahar_geo.ps1 gives,
# and the last waits long: the track is read and baked on the way in, and
# the main loop does not run while it is.
function Advance([string]$pattern, [int]$timeoutSec) {
    for ($try = 1; $try -le 6; $try++) {
        [void][Hp2Track]::DismissPopups([uint32]$proc.Id, $hwnd)
        [Hp2Track]::PressKey($hwnd, $VK_N)
        if (Wait-ForLog $pattern $timeoutSec) { return $true }
        if (-not (Alive)) { return $false }
    }
    return $false
}
$ok = (Advance "mode 1[^0-9]*$" 8) -and (Advance "geoview: entered" 20) -and (Advance "trackview: entered" 150)
if (-not $ok) {
    if (Alive) { $proc | Stop-Process -Force }
    throw "never reached the track viewer"
}
Write-Host ("  track viewer: {0:N1}s" -f (Elapsed))
Start-Sleep -Milliseconds 1500
Shot "track-stop1"

# Forward along the view, then a turn each way, then up and a look down:
# every one of these moves the camera, so every shot should differ from the
# one before it.
Hold $VK_UP 1500
Start-Sleep -Milliseconds 500
Shot "track-forward"
Hold $VK_A 700
Start-Sleep -Milliseconds 400
Shot "track-yaw-right"
Hold $VK_X 1400
Start-Sleep -Milliseconds 400
Shot "track-yaw-left"
Hold $VK_W 1200
Hold $VK_S 500
Start-Sleep -Milliseconds 400
Shot "track-up-look-down"

# The stops along route 1, each on the road looking along it.
for ($i = 1; $i -le $Stops; $i++) {
    if (-not (Alive)) { break }
    [Hp2Track]::PressKey($hwnd, $VK_H)
    Start-Sleep -Milliseconds 1200
    Shot ("track-stop{0}" -f ($i + 1))
}

# Back to the first stop and a look up, at TRACKB12's sun: it is in the
# frame's width there, 42 pixels above its top. X is Z on the keyboard.
if (Alive) {
    for ($i = 1; $i -le $Stops; $i++) {
        [Hp2Track]::PressKey($hwnd, $VK_F)
        Start-Sleep -Milliseconds 150
    }
    Start-Sleep -Milliseconds 800
    Hold $VK_Z 260
    Start-Sleep -Milliseconds 600
    Shot "track-sun"
}

if (Alive) {
    [Hp2Track]::PressKey($hwnd, $VK_M)          # START leaves the main loop
    Start-Sleep -Milliseconds 2000
}

while ((Elapsed) -lt $RunSeconds -and (Alive)) {
    if (Select-String -Path $debugLog -Pattern "left main loop" -Quiet -ErrorAction SilentlyContinue) { break }
    Start-Sleep -Milliseconds 300
}
Start-Sleep -Milliseconds 1000
if (Alive) { $proc | Stop-Process -Force }

Write-Host ""
Write-Host "Shots in $OutDir"
if (Test-Path $debugLog) {
    Write-Host "--- nfshp2_debug.txt (track lines) ---"
    Select-String -Path $debugLog -Pattern "trackview|^.*track |left main loop|abort|assert" |
        Select-Object -Last 60 |
        ForEach-Object { Write-Host ("  " + $_.Line) }
}
