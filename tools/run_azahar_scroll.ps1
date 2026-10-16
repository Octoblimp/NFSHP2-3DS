# Boots NFSHP2-3DS.3dsx in Azahar, walks into the screen viewer, and captures
# a UV-scrolling texture in motion.
#
# Nothing on the disc points a Flailer bitmap at a scrolling texture --
# ROADLINES and SCREEN_LINES each occur exactly once in the whole of
# extracted/, in their own TextureInfo record -- so the frontend can render
# perfectly and still say nothing about whether texpack_scroll() is right.
# main.c's B key repoints the biggest visible bitmap on the current screen at
# each in turn, and this captures three frames a second apart of each. Three
# frames is the point: one frame proves the texture is bound, three prove it
# is moving, and moving in the right direction.
#
# ROADLINES scrolls S at +0.78125/s and SCREEN_LINES steps T at -0.015625
# every 0.04 s, so across a second ROADLINES should have travelled most of
# its width to the right and SCREEN_LINES should have crawled upward.
#
# The three things tools/run_azahar_test.ps1 explains apply here too: pass
# the .3dsx not the .cia, capture with PW_RENDERFULLCONTENT, and call
# SetProcessDPIAware first.
#
# Usage: powershell -File tools/run_azahar_scroll.ps1

param(
    [int]$Screen = 0,             # how many R presses before starting
    [int]$RunSeconds = 400,
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_scroll" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not (Test-Path $AzaharExe)) { throw "Azahar not found at $AzaharExe" }
if (-not (Test-Path $Target3dsx)) { throw "Target .3dsx not found at $Target3dsx" }

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Drawing;
public class Hp2Scroll {
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
    public static void PressKey(IntPtr h, int vk) { Press(h, vk, 140); }
    // The boot flow idles into its attract loop, which logs two lines a
    // frame; the SD writes slow the emulated app down far enough that a
    // 140 ms hold can fall inside one emulated frame and never be scanned.
    // SELECT is held long enough to survive that.
    public static void Press(IntPtr h, int vk, int holdMs) {
        PostMessage(h, WM_KEYDOWN, (IntPtr)vk, IntPtr.Zero);
        System.Threading.Thread.Sleep(holdMs);
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

[void][Hp2Scroll]::SetProcessDPIAware()

# Azahar's default keyboard profile, from qt-config.ini. B is 'S' and the
# X/Y pair is the one worth double-checking: button_x is 90 ('Z') and
# button_y is 88 ('X').
$VK_A = 65; $VK_S = 83; $VK_M = 77; $VK_N = 78; $VK_W = 87

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
$closed = [Hp2Scroll]::DismissPopups([uint32]$proc.Id, $hwnd)
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
    [Hp2Scroll]::CaptureToFile($hwnd, $path)
    Write-Host ("  [{0,5:N1}s] {1}" -f (Elapsed), $path)
}

Write-Host "Waiting for the main loop..."
if (-not (Wait-ForLog "entering main loop" 90)) {
    if (Alive) { $proc | Stop-Process -Force }
    throw "never reached the main loop"
}

# One SELECT: flow -> screen viewer. Confirmed in the log rather than waited
# out, for the reason tools/run_azahar_geo.ps1 gives at length.
$mode = $false
# Pressed again and again rather than once and waited out. Once the boot
# flow's idle timer expires the title screen calls StartDemoMode every frame,
# each call writing a line to the SD log, and the emulated app slows down far
# enough that most key presses fall inside a single frame and are never
# scanned. Eventually one lands; this is patient rather than clever.
for ($try = 1; $try -le 40 -and -not $mode; $try++) {
    [Hp2Scroll]::Press($hwnd, $VK_N, 500)
    $mode = Wait-ForLog "mode 1" 5
}
if (-not $mode) {
    if (Alive) { $proc | Stop-Process -Force }
    throw "never reached the screen viewer"
}
Write-Host ("  screen viewer: {0:N1}s" -f (Elapsed))
Start-Sleep -Milliseconds 1200

for ($i = 0; $i -lt $Screen; $i++) {
    [Hp2Scroll]::PressKey($hwnd, $VK_W)      # R -> next screen
    Start-Sleep -Milliseconds 600
}
Shot "before"

foreach ($tex in @("roadlines", "screenlines")) {
    if (-not (Alive)) { break }
    [Hp2Scroll]::PressKey($hwnd, $VK_S)      # B -> next demo texture
    Start-Sleep -Milliseconds 500
    for ($f = 1; $f -le 3; $f++) {
        Shot ("{0}-t{1}" -f $tex, $f)
        Start-Sleep -Seconds 1
    }
}

# Back to the screen's own texture, so the last shot shows the demo undone.
if (Alive) {
    [Hp2Scroll]::PressKey($hwnd, $VK_S)
    Start-Sleep -Milliseconds 700
    Shot "restored"
    [Hp2Scroll]::PressKey($hwnd, $VK_M)      # START leaves the main loop
    Start-Sleep -Milliseconds 1500
}

while ((Elapsed) -lt $RunSeconds -and (Alive)) { Start-Sleep -Milliseconds 300 }
if (Alive) { $proc | Stop-Process -Force }
