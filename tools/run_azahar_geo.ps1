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
using System.Drawing;
public class Hp2Geo {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern int PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern IntPtr PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    public struct RECT { public int Left, Top, Right, Bottom; }
    public const uint WM_KEYDOWN = 0x0100;
    public const uint WM_KEYUP = 0x0101;
    public static void PressKey(IntPtr h, int vk) {
        PostMessage(h, WM_KEYDOWN, (IntPtr)vk, IntPtr.Zero);
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
