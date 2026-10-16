# Boots NFSHP2-3DS.3dsx in Azahar, walks into the geometry viewer, and
# captures the top screen for several cars and several solids.
#
# tools/run_azahar_test.ps1 does the same for the boot flow and the screen
# viewer; this is the geometry half, kept separate so that a change here
# cannot break the milestone test. The three things that took NFSU2-3DS
# several sessions to get right apply to both and are explained there:
# pass the .3dsx not the .cia, capture with PW_RENDERFULLCONTENT, and call
# SetProcessDPIAware first.
#
# A cross-check proves two decoders agree about what the bytes mean. It
# cannot prove a car looks like a car, and that is the only question this
# answers -- so every run leaves PNGs behind to look at.
#
# Usage:
#   powershell -File tools/run_azahar_geo.ps1
#   powershell -File tools/run_azahar_geo.ps1 -Cars 4 -Solids 6

param(
    [int]$Cars = 3,               # how many cars to step through
    [int]$Solids = 4,             # solids to step through on the first car
    [int]$RunSeconds = 240,       # hard ceiling on the whole run
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_geo" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not (Test-Path $AzaharExe)) { throw "Azahar not found at $AzaharExe" }
if (-not (Test-Path $Target3dsx)) { throw "Target .3dsx not found at $Target3dsx" }

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Drawing;
public class Hp2Geo {
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

[void][Hp2Geo]::SetProcessDPIAware()

# Azahar's default keyboard profile.
# Azahar's default keyboard profile, from qt-config.ini: button_x is code
# 90 ('Z') and button_y is code 88 ('X'). The two are easy to swap, and
# swapping them here is silent -- the run still captures a shot, it is just
# a shot of the wrong thing. The first pass of this script pressed 'X' for
# "textures off" and captured a textured car with the spin stopped.
$VK_A = 65; $VK_S = 83; $VK_Z = 90; $VK_X = 88
$VK_M = 77; $VK_N = 78
$VK_T = 84; $VK_G = 71; $VK_F = 70; $VK_H = 72
$VK_Q = 81; $VK_W = 87    # L and R
# The circle pad is analog_from_button on the arrow keys: Qt 16777234..7
# in qt-config.ini, which is Left/Up/Right/Down.
$VK_LEFT = 37; $VK_UP = 38; $VK_RIGHT = 39; $VK_DOWN = 40

$debugLog = Join-Path $env:APPDATA "Azahar\sdmc\nfshp2_debug.txt"
. (Join-Path $PSScriptRoot "azahar_debuglog.ps1")   # DebugLog 1
. (Join-Path $PSScriptRoot "azahar_viewers.ps1")    # DebugMenu 1, for SELECT
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
$closed = [Hp2Geo]::DismissPopups([uint32]$proc.Id, $hwnd)
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
function Shot([string]$tag) {
    if (-not (Alive)) { return }
    $script:step++
    $path = Join-Path $OutDir ("{0:d2}_{1}.png" -f $script:step, $tag)
    [Hp2Geo]::CaptureToFile($hwnd, $path)
    Write-Host ("  [{0,5:N1}s] {1}" -f (Elapsed), $path)
}

Write-Host "Waiting for the main loop..."
$booted = Wait-ForLog "entering main loop" 90
Write-Host ("  main loop: {0}" -f $booted)
if (-not $booted) { $proc | Stop-Process -Force; throw "never reached the main loop" }

# The geometry viewer is two SELECTs along: flow -> screens -> geometry. The
# first car is read off the card on the way in, which is half a megabyte of
# geometry plus its texture uploads.
#
# Each SELECT is confirmed in the log rather than waited out: the keypress
# goes in as soon as the boot marker appears, and on a fast boot the frontend
# is not yet consuming input when it lands. A run that assumed it had
# arrived captured the title screen and reported it as the first car.
# SELECT cycles flow -> screens -> geometry -> flow, so pressing it until
# the app says it arrived is correct whether a press was dropped or two of
# them landed. Checking after every press is what stops it cycling past.
$mode = $false
for ($try = 1; $try -le 8 -and -not $mode; $try++) {
    [void][Hp2Geo]::DismissPopups([uint32]$proc.Id, $hwnd)
    [Hp2Geo]::PressKey($hwnd, $VK_N)
    $mode = Wait-ForLog "geoview: entered" 20
}
if (-not $mode) {
    if (Alive) { $proc | Stop-Process -Force }
    throw "never reached the geometry viewer"
}
Write-Host ("  geometry viewer: {0:N1}s" -f (Elapsed))
Start-Sleep -Milliseconds 800
Shot "geo-first-car"

# The spin is on by default, so two shots a second apart are two angles of
# the same solid -- which is what shows whether the winding and the normals
# hold up all the way round.
Start-Sleep -Milliseconds 1400
Shot "geo-first-car-turned"

# Textures off: vertex colour alone. A car that looks right textured and
# wrong untextured means the ST are carrying the shape, which they are not
# supposed to be.
[Hp2Geo]::PressKey($hwnd, $VK_Z)     # X button
Start-Sleep -Milliseconds 700
Shot "geo-untextured"
[Hp2Geo]::PressKey($hwnd, $VK_Z)
Start-Sleep -Milliseconds 500

# ---- the camera (task 23).
#
# The viewer's own spherical orbit is gone: what frames the car now is the
# ported Camera driven by a real CM_ORBIT_CAR CameraMover, so these shots
# are the only place the boom's behaviour can be seen rather than asserted.
# camera_check.py proves the port and an independent model of the ELF agree
# about 1200 lines of numbers; it cannot say whether the view matrix handed
# to the PICA200 points the right way, and the first thing a transposed or
# unnegated one does is look correct from behind and inside-out from the
# side.
#
# Zoom first, because it is the cheapest thing to be wrong: it is a HELD
# button on the disc (RadiusMultiplier compounds 1% a frame while it is
# down and must snap back to exactly 1.0 on release), so a tap proves
# nothing and a stuck multiplier shows up as a car that keeps creeping
# after the key is up.
#
# The idle spin comes off first: two shots of a spinning car differ
# whatever the radius did, and the creep test below is a comparison.
#
# The hold is short because the emulator runs the app at two and a half
# times hardware speed here -- 1% a frame compounds about fourfold in a
# second at 139 FPS, which puts the eye inside the bodyshell. The disc
# compounds per frame too; that is the mover, not the harness.
[Hp2Geo]::PressKey($hwnd, $VK_X)             # Y button -> spin off
Start-Sleep -Milliseconds 600
Shot "cam-still"
[Hp2Geo]::KeyDown($hwnd, $VK_T)              # D-pad up -> zoom in
Start-Sleep -Milliseconds 260
[Hp2Geo]::KeyUp($hwnd, $VK_T)
Start-Sleep -Milliseconds 700
Shot "cam-zoom-in"
Start-Sleep -Milliseconds 1500
Shot "cam-zoom-settled"
$creep = [Hp2Geo]::MeanDiff((Join-Path $OutDir ("{0:d2}_cam-zoom-in.png" -f ($script:step - 1))),
                            (Join-Path $OutDir ("{0:d2}_cam-zoom-settled.png" -f $script:step)))
Write-Host ("  zoom creep after release: mean diff {0:N3}/255 -- {1}" -f $creep,
            $(if ($creep -lt 0.5) { "PASS, the multiplier went back to 1.0" } else { "FAIL, still moving" }))
[Hp2Geo]::KeyDown($hwnd, $VK_G)              # D-pad down -> zoom out
Start-Sleep -Milliseconds 700
[Hp2Geo]::KeyUp($hwnd, $VK_G)
Start-Sleep -Milliseconds 500
Shot "cam-zoom-out"

# The pad asks for a rotation SPEED and the mover ramps to it at
# MaxRotationAccel, 24 BAMs per frame per frame. A shot as the key goes
# down and another a second later are the acceleration limiter; if the
# first one has already swung, the limiter is not in the loop.
[Hp2Geo]::KeyDown($hwnd, $VK_LEFT)
Start-Sleep -Milliseconds 150
Shot "cam-orbit-start"
Start-Sleep -Milliseconds 1300
Shot "cam-orbit-held"
[Hp2Geo]::KeyUp($hwnd, $VK_LEFT)
Start-Sleep -Milliseconds 400

# Elevation is clamped to 280..350 BAM degrees, so holding up should stop
# short of overhead instead of tumbling over the top and inverting.
[Hp2Geo]::KeyDown($hwnd, $VK_UP)
Start-Sleep -Milliseconds 1800
Shot "cam-elev-clamped"
[Hp2Geo]::KeyUp($hwnd, $VK_UP)
Start-Sleep -Milliseconds 400
[Hp2Geo]::PressKey($hwnd, $VK_S)             # B -> the mover ctor's angles
Start-Sleep -Milliseconds 900
Shot "cam-reset"
[Hp2Geo]::PressKey($hwnd, $VK_X)             # Y -> spin back on
Start-Sleep -Milliseconds 300

# Every solid in the file, one at a time: body LODs, wheels, brakes, mirrors,
# wipers, the scuff decals.
for ($i = 1; $i -le $Solids; $i++) {
    if (-not (Alive)) { break }
    [Hp2Geo]::PressKey($hwnd, $VK_H)          # D-pad right -> next solid
    Start-Sleep -Milliseconds 900
    Shot ("geo-solid{0}" -f $i)
}

# Everything at once. Parts are in their own local space, so this piles the
# wheels up in the middle of the car -- it is a completeness check, not a
# picture of a car.
[Hp2Geo]::PressKey($hwnd, $VK_A)
Start-Sleep -Milliseconds 1200
Shot "geo-all-solids"
[Hp2Geo]::PressKey($hwnd, $VK_A)
Start-Sleep -Milliseconds 500

# Then the next few cars, to catch anything that is true of one model only.
for ($i = 1; $i -lt $Cars; $i++) {
    if (-not (Alive)) { break }
    [Hp2Geo]::PressKey($hwnd, $VK_W)          # R -> next car
    Start-Sleep -Seconds 4
    Shot ("geo-car{0}" -f ($i + 1))
}

if (Alive) {
    [Hp2Geo]::PressKey($hwnd, $VK_M)          # START leaves the main loop
    Start-Sleep -Milliseconds 1500
}

while ((Elapsed) -lt $RunSeconds -and (Alive)) { Start-Sleep -Milliseconds 300 }
if (Alive) { $proc | Stop-Process -Force }

Write-Host ""
Write-Host "Shots in $OutDir"
if (Test-Path $debugLog) {
    Write-Host "--- nfshp2_debug.txt (geoview lines) ---"
    Select-String -Path $debugLog -Pattern "geoview|georender|left main loop" |
        ForEach-Object { Write-Host ("  " + $_.Line) }
}
