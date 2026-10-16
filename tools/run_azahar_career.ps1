# Boots NFSHP2-3DS.3dsx in Azahar and walks the career's event tree (TASKS
# 69, eventtreeview.c): World Racing's World Championship, or with -CopsOn
# Hot Pursuit's Ultimate Road Racer, to "View Event Tree"; then right,
# right, down, up and left twice on the tree, A for the details, SQUARE for
# the reward, B twice back to the tree, and A twice, which starts the event
# at car select. -Back goes back to the tree from car select. -Race
# instead races the event from car select: A picks the car, the race is
# finished -FinishSeconds after its start with the player in place
# -FinishPlace ("TestFinish" in sdmc:/nfshp2_config.txt, written for the
# run and taken out after it), and A goes through the end screens to the
# End Game Menu. There it takes Next Race while the event has one, and
# races again, and Quit after the last race, until the tree is back (TASKS
# 69f). Each autosave is answered Yes. A tournament or knockout saved
# between its races resumes at its next race, without car select.
# -LapSeconds gives the player that lap instead of the projected one, for
# a time trial's goal. -Path then picks the event first: D-pad steps on
# the tree ("down,right"), checked against -Event when it is given,
# instead of the tour. -OpenUltimates first takes the debug menu's Open
# the Ultimates ("DebugMenu 1" written for the run) and saves. The tree's
# popup that says the Ultimate is open is closed whenever it shows (TASKS
# 69g). It captures each step and reports the flow's and the view's
# lines. The capture and key methods are run_azahar_test.ps1's; see its
# header for why each is the way it is.
#
# sdmc:/nfshp2_config.txt must not set SkipFE: the run needs the frontend.
#
# Usage:
#   powershell -File tools/run_azahar_career.ps1
#   powershell -File tools/run_azahar_career.ps1 -CopsOn -Back
#   powershell -File tools/run_azahar_career.ps1 -Race -FinishPlace 1
#   powershell -File tools/run_azahar_career.ps1 -Race -Path down -Event 3
#   powershell -File tools/run_azahar_career.ps1 -Race -Event 2 -LapSeconds 120
#   powershell -File tools/run_azahar_career.ps1 -OpenUltimates -Path down,down

param(
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = "",
    [switch]$CopsOn,              # Ultimate Road Racer, not the Championship
    [switch]$Back,                # B from car select, back to the tree
    [switch]$Race,                # race the event, then back to the tree
    [int]$FinishSeconds = 20,     # -Race: the test's finish, after the start
    [int]$FinishPlace = 1,        # -Race: the player's place in it
    [int]$LapSeconds = 0,         # -Race: its lap instead of the projected one
    [string]$Path = "",           # D-pad steps on the tree to the event
    [int]$Event = 0,              # the event -Path must end on
    [switch]$OpenUltimates        # the debug menu's Open the Ultimates first
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_career" }
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
# SELECT on the main menu must not open the viewers without the debug menu
# (launch blocker 1). With "DebugMenu 1" on the card it may, so the check
# is skipped.
$debugMenuOn = (Test-Path $config) -and
    (Select-String -Path $config -Pattern "^\s*DebugMenu\s+[1-9]" -Quiet)
$addDebugMenu = $OpenUltimates -and -not $debugMenuOn
if ($OpenUltimates) { $debugMenuOn = $true }

# The config's lines without the test's finish, and with it for -Race.
function Set-TestFinish([bool]$on) {
    $lines = @()
    if (Test-Path $config) {
        $lines = @(Get-Content $config | Where-Object { $_ -notmatch "^\s*TestFinish" })
        if ($addDebugMenu) {
            $lines = @($lines | Where-Object { $_ -notmatch "^\s*DebugMenu" })
        }
    }
    if ($on -and $Race) {
        $lines += @("TestFinish $FinishSeconds", "TestFinishPlace $FinishPlace",
                    "TestFinishTime $LapSeconds")
    }
    if ($on -and $addDebugMenu) { $lines += @("DebugMenu 1") }
    New-Item -ItemType Directory -Force -Path (Split-Path $config) | Out-Null
    Set-Content -Path $config -Value $lines -Encoding ASCII
}
Set-TestFinish $true

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

$VK_A = 65; $VK_S = 83; $VK_M = 77; $VK_N = 78; $VK_T = 84; $VK_G = 71; $VK_H = 72; $VK_F = 70

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
    [Hp2Cap]::CaptureToFile($hwnd, $path)
    Write-Host ("  [{0,5:N1}s] {1}" -f (Elapsed), $path)
}

# --- the script the run follows -------------------------------------------
# The boot as run_azahar_challenge.ps1 has it. The debug log lands up to
# ~7 s late, so the steps on the tree are paced by time, and the verdict
# reads the help override lines each view logs.

# Whether a line of the app's log matches $pattern now.
function Seen([string]$pattern) {
    if (-not (Test-Path $debugLog)) { return $false }
    return [bool](Select-String -Path $debugLog -Pattern $pattern -Quiet -ErrorAction SilentlyContinue)
}

# How many lines of the app's log match $pattern now.
function LogCount([string]$pattern) {
    if (-not (Test-Path $debugLog)) { return 0 }
    return @(Select-String -Path $debugLog -Pattern $pattern -ErrorAction SilentlyContinue).Count
}

# Press $vk until $pattern has matched $count lines, waiting $waitSec
# after each press; $tries presses at most.
function Press-UntilCount([int]$vk, [string]$pattern, [int]$count,
                          [int]$tries, [int]$waitSec) {
    for ($i = 0; $i -lt $tries; $i++) {
        if (-not (Alive)) { return $false }
        [Hp2Cap]::PressKey($hwnd, $vk)
        if (Wait-ForLogCount $pattern $count $waitSec) { return $true }
    }
    return $false
}

# Press $vk to go to $screen, then wait for the screen's first HIGHLIGHT.
function Enter-Screen([int]$vk, [string]$screen) {
    $enter = "flow enter " + $screen + " [0-9a-f]{8}"
    $hl = "screen " + $screen + " [0-9a-f]{8} .* last HIGHLIGHT"
    $n = LogCount $enter
    $h = LogCount $hl
    if (-not (Press-UntilCount $vk $enter ($n + 1) 2 20)) { return $false }
    [void](Wait-ForLogCount $hl ($h + 1) 20)
    Start-Sleep -Milliseconds 1000
    return $true
}

function Press([int]$vk) {
    if (-not (Alive)) { return }
    [Hp2Cap]::PressKey($hwnd, $vk)
    Start-Sleep -Milliseconds 700
}

$loading = Wait-ForLog "global chunks loaded" 60
Write-Host ("  LOADING drawn: {0}" -f $loading)

Write-Host "Waiting for the main loop..."
$booted = Wait-ForLog "entering main loop" 60
Write-Host ("  main loop: {0}" -f $booted)

$VK_X = 88   # the 3DS Y on Azahar's default map: SQUARE
$VK_F = 70   # left

$atTree = $false
if ($booted) {
    $gotLang = Wait-ForLog "flow enter Language Options Pre FE" 30
    Write-Host ("  language screen: {0}" -f $gotLang)
    if ($gotLang) {
        Start-Sleep -Milliseconds 1500
        Shot "language"
        [void](Press-UntilCount $VK_A "flow leave Language Options Pre FE" 1 2 20)
    }

    $gotIntro = Wait-ForLog "^movie open MOVIES/INTRO/NFSINTRO" 40
    Write-Host ("  intro opened: {0}" -f $gotIntro)
    if ($gotIntro) {
        Start-Sleep -Seconds 2
        [void](Press-UntilCount $VK_M "flow title skip" 1 2 20)   # START
    } else {
        [void](Wait-ForLog "flow title idle" 20)
    }
    [void](Wait-ForLog "flow vis object b5761d00 b070dbc9 1" 15)
    Start-Sleep -Milliseconds 900

    $modeSelect = "Cops Off Mode Select"
    if ($CopsOn) { $modeSelect = "Cops On Mode Select" }
    if (Enter-Screen $VK_M "New Main Menu") {   # START
        Start-Sleep -Milliseconds 1500
        Shot "mainmenu"
        if (-not $debugMenuOn) {
            [Hp2Cap]::PressKey($hwnd, $VK_N)           # SELECT, nothing
            Start-Sleep -Milliseconds 1500
        }
        if ($OpenUltimates) {
            # Down four to the debug menu's item, the fifth (TASKS 68),
            # and down five to its sixth row. B asks to save: Yes, then
            # the card's own question, Left for its Yes.
            for ($i = 0; $i -lt 4; $i++) { Press $VK_G }
            if (Enter-Screen $VK_A "Port Debug Menu") {
                for ($i = 0; $i -lt 5; $i++) { Press $VK_G }
                Shot "debug-ultimates"
                $ultOpened = Press-UntilCount $VK_A "debug menu: ultimates open" 1 2 10
                Press $VK_S                            # B: the prompt
                [void](Wait-ForLog "debug menu: asking to save" 10)
                Start-Sleep -Milliseconds 1200
                Press $VK_A                            # Yes
                [void](Wait-ForLog "flow enter Autosave" 10)
                Start-Sleep -Milliseconds 3500
                Press $VK_F                            # to the card's Yes
                Press $VK_A
                $ultSaved = Wait-ForLog "memcard: saved" 15
                [void](Wait-ForLogCount "flow enter New Main Menu [0-9a-f]{8}" 2 15)
                Start-Sleep -Milliseconds 2000
            }
            Write-Host ("  Open the Ultimates: {0}, saved {1}" -f $ultOpened, $ultSaved)
        }
        $atMode = $false
        if ($CopsOn) {
            $atMode = Enter-Screen $VK_A $modeSelect
        } elseif (Press-UntilCount $VK_G "flow bracket 708a0bf1" ((LogCount "flow bracket 708a0bf1") + 1) 6 20) {
            # down, World Racing
            $atMode = Enter-Screen $VK_A $modeSelect
        }
        if ($atMode) {
            # down to World Championship (third) or Ultimate Road Racer
            # (fourth)
            Press $VK_G; Press $VK_G
            if ($CopsOn) { Press $VK_G }
            Start-Sleep -Milliseconds 900
            Shot "modeselect"
            $n = LogCount "etv open tree"
            [Hp2Cap]::PressKey($hwnd, $VK_A)
            $atTree = Wait-ForLogCount "etv open tree" ($n + 1) 30
            Write-Host ("  event tree: {0}" -f $atTree)
            if (-not $atTree) { Shot "tree-missing" }
        } else {
            Shot "modeselect-missing"
        }
    } else {
        Shot "start-did-nothing"
    }
}

$atDetails = $false
$atReward = $false
$atCarSel = $false
$resumed = $false
$onEvent = $true
if ($atTree) {
    Start-Sleep -Seconds 2
    Shot "tree"
    # The view opens on the popup (state 7) while an Ultimate is open
    # and not won, each time until the tree is saved after it; A
    # closes it.
    Start-Sleep -Seconds 6
    $open = @(Get-Content $debugLog | Where-Object { $_ -match "etv open tree" }) | Select-Object -Last 1
    $ultPopup = $open -match "state 7 "
    Write-Host ("  the Ultimate's popup: {0} ({1})" -f $ultPopup, $open)
    Shot "ultimate-popup"
    if ($ultPopup) {
        Press $VK_A; Start-Sleep -Milliseconds 1500
        Shot "popup-closed"
        # popupClosed (0x001faea8) goes back to the view the save kept:
        # the details, when the tree was left in them, where the D-pad
        # does nothing. Their help says so; B goes back to the tree.
        Start-Sleep -Seconds 8
        $help = @(Get-Content $debugLog | Where-Object { $_ -match "^help override" }) | Select-Object -Last 1
        if ($help -match "^help override (800037|800038|800049) ") {
            Press $VK_S; Start-Sleep -Milliseconds 1500
            Shot "popup-to-tree"
        }
    }
    if ($Path -ne "" -or $Event -gt 0) {
        # The save keeps the view (Fred.SelectedEventData[3]): a tree left
        # in the details opens in them, where the D-pad does nothing. B
        # first, back to the tree.
        Start-Sleep -Seconds 6
        $open = @(Get-Content $debugLog | Where-Object { $_ -match "etv open tree" }) | Select-Object -Last 1
        if ($open -match "state [1-6] ") {
            Press $VK_S; Start-Sleep -Milliseconds 1500
            Shot "tree-from-details"
        }
        $keys = @{ up = $VK_T; down = $VK_G; left = $VK_F; right = $VK_H }
        foreach ($k in ($Path -split "[,\s]+" | Where-Object { $_ -ne "" })) {
            Press $keys[$k.Trim()]; Start-Sleep -Milliseconds 900
            Shot ("tree-" + $k.Trim())
        }
        if ($Event -gt 0) {
            # The leaf the steps ended on, once the log has caught up.
            Start-Sleep -Seconds 8
            $last = @(Get-Content $debugLog | Where-Object {
                $_ -match "etv (open tree \d+ event|leaf) \d+" }) | Select-Object -Last 1
            $leaf = 0
            if ($last -match "etv (?:open tree \d+ event|leaf) (\d+)") { $leaf = [int]$Matches[1] }
            $onEvent = $leaf -eq $Event
            Write-Host ("  on event {0}: {1} (the leaf is {2})" -f $Event, $onEvent, $leaf)
        }
    } else {
        Press $VK_H; Start-Sleep -Milliseconds 900; Shot "tree-right"
        Press $VK_H; Start-Sleep -Milliseconds 900; Shot "tree-right2"
        Press $VK_G; Start-Sleep -Milliseconds 900; Shot "tree-down"
        Press $VK_T; Start-Sleep -Milliseconds 900; Shot "tree-up"
        Press $VK_F; Press $VK_F; Start-Sleep -Milliseconds 900; Shot "tree-left2"
    }
}
if ($atTree -and $onEvent) {
    [Hp2Cap]::PressKey($hwnd, $VK_A)                   # the details
    Start-Sleep -Seconds 2
    $atDetails = (LogCount "help override 800037|help override 800049|help override 800038") -gt 0
    Shot "details"
    [Hp2Cap]::PressKey($hwnd, $VK_X)                   # SQUARE, the reward
    Start-Sleep -Seconds 2
    $atReward = (LogCount "help override 800044|help override 800052") -gt 0
    Shot "reward"
    [Hp2Cap]::PressKey($hwnd, $VK_S)                   # back to the details
    Start-Sleep -Seconds 2
    Shot "details-again"
    [Hp2Cap]::PressKey($hwnd, $VK_S)                   # back to the tree
    Start-Sleep -Seconds 2
    Shot "tree-again"
    [Hp2Cap]::PressKey($hwnd, $VK_A)                   # the details
    Start-Sleep -Seconds 2
    # Start the event: Select Car, or, for a tournament or a knockout
    # saved between its races, straight to the next race's track.
    $begin = "flow enter Select Car [0-9a-f]{8}|etv resume event"
    $started = Press-UntilCount $VK_A $begin ((LogCount $begin) + 1) 2 20
    $resumed = $started -and ((LogCount "etv resume event") -gt 0)
    $atCarSel = $started -and -not $resumed
    if ($atCarSel) {
        [void](Wait-ForLogCount "screen Select Car [0-9a-f]{8} .* last HIGHLIGHT" 1 20)
        Start-Sleep -Milliseconds 1000
    }
    Write-Host ("  car select: {0}, resumed: {1}" -f $atCarSel, $resumed)
    Start-Sleep -Milliseconds 1500
    Shot "carsel"
    if ($atCarSel -and $Back) {
        [void](Enter-Screen $VK_S "View Event Tree")   # B, back to the tree
        Start-Sleep -Seconds 2
        Shot "tree-back"
    }
}

# -Race: A picks the car, and the flow leaves the frontend for the track.
# Each race: A goes past the event's Pre Race Blurb and Pre Race Stats
# (Be A Cop has only the Blurb),
# and the gas is held from then until the test's finish ends it, as
# run_azahar_coprace.ps1 does. A then goes
# through the end screens, one press each time the log has had its ~7 s
# to catch up, until the End Game Menu's line (main.c, raceTestMenuLog).
# Next Race is its first row while the event has another race: A, then
# Left for the popup's Yes and A. Otherwise Quit is its last row: Up once
# when it wraps, else Down to it. Both go through the Autosave, whose
# question (overwrite the save?) starts on No, as retail's does: Left for
# Yes, then A. After Quit the tree is entered again.
$left = $false; $racing = $false; $treeAgain = $false
$races = 0; $finishes = 0; $nexts = 0
function Popup-Yes {
    Start-Sleep -Milliseconds 1500
    [Hp2Cap]::PressKey($hwnd, $VK_A)                   # the row
    Start-Sleep -Milliseconds 1500
    [Hp2Cap]::PressKey($hwnd, $VK_F)                   # left, Yes
    Start-Sleep -Milliseconds 900
    [Hp2Cap]::PressKey($hwnd, $VK_A)
}
# The Autosave's question, once its screen is up: Left for Yes, then A.
$saves = 0
function Answer-Autosave {
    $enter = "flow enter Autosave "
    if (-not (Wait-ForLogCount $enter ($script:saves + 1) 30)) { return $false }
    $script:saves++
    $pop = "popup \d+ summon"
    $n = LogCount $pop
    # The popup may be logged before the screen's line lands: from the
    # Autosave's line on, any summon counts.
    $after = @(Get-Content $debugLog)
    $at = 0
    for ($i = $after.Count - 1; $i -ge 0; $i--) { if ($after[$i] -match $enter) { $at = $i; break } }
    $seen = @($after[$at..($after.Count - 1)] | Where-Object { $_ -match $pop }).Count
    if ($seen -eq 0 -and -not (Wait-ForLogCount $pop ($n + 1) 20)) { return $false }
    Start-Sleep -Milliseconds 1500
    Shot ("save-{0}-ask" -f $script:saves)
    [Hp2Cap]::PressKey($hwnd, $VK_F)                   # left, Yes
    Start-Sleep -Milliseconds 900
    [Hp2Cap]::PressKey($hwnd, $VK_A)
    return $true
}
if (($atCarSel -or $resumed) -and $Race) {
    $wantRace = "flow want (?!LOADING_FRONTEND|IN_FRONTEND)"
    if ($resumed) { $left = $true }
    else { $left = Press-UntilCount $VK_A $wantRace ((LogCount $wantRace) + 1) 3 9 }
    Write-Host ("  left the frontend: {0}" -f $left)
    if ($left) {
        $racing = Wait-ForLog "flow state RACING" 150
        Write-Host ("  RACING: {0}" -f $racing)
    }
    $more = $racing -and (Wait-ForLog "^trackview: attached" 150)
    $treeEnter = "flow enter View Event Tree"
    $treeN = LogCount $treeEnter
    $menuLine = "race: the test's end game menu"
    while ($more -and (Alive)) {
        $more = $false
        $races++
        Start-Sleep -Seconds 4
        Shot ("race{0}-blurb" -f $races)
        # A on the event's Pre Race Blurb, then on its Pre Race Stats,
        # until the last of them is left for the countdown: the flow's
        # change to no screen. Be A Cop has no Pre Race Stats (startrace.c,
        # start_race_need_to_see_pre_race_stats), so its Blurb is the last.
        # Counted from this race's Blurb on, whose line has all the earlier
        # ones landed before it. (The race's stage lines come every second,
        # so race 1's would count for the later ones.)
        [void](Wait-ForLogCount "flow enter Pre Race Blurb" $races 30)
        $toRace = "flow change \(null\)"
        $going = Press-UntilCount $VK_A $toRace ((LogCount $toRace) + 1) 10 12
        Write-Host ("  race {0} going: {1}" -f $races, $going)
        if (-not $going) { break }
        $end = (Get-Date).AddSeconds($FinishSeconds + 40)
        $shotAt = (Get-Date).AddSeconds(6)
        $fin = $false
        while ((Get-Date) -lt $end -and (Alive)) {
            [Hp2Cap]::KeyDown($hwnd, $VK_A)           # the gas, never the brake
            if ($shotAt -and (Get-Date) -ge $shotAt) { Shot ("race{0}-racing" -f $races); $shotAt = $null }
            if ((LogCount "race: the test's finish") -ge $races) { $fin = $true; break }
            Start-Sleep -Milliseconds 150
        }
        [Hp2Cap]::KeyUp($hwnd, $VK_A)
        Write-Host ("  race {0} test's finish: {1}" -f $races, $fin)
        if (-not $fin) { break }
        $finishes++
        Start-Sleep -Seconds 3
        Shot ("race{0}-finish" -f $races)
        $atMenu = $false
        for ($i = 1; $i -le 12 -and -not $atMenu; $i++) {
            if (-not (Alive)) { break }
            [Hp2Cap]::PressKey($hwnd, $VK_A)
            $atMenu = Wait-ForLogCount $menuLine $races 9
            Shot ("race{0}-end-{1}" -f $races, $i)
        }
        Write-Host ("  race {0} End Game Menu: {1}" -f $races, $atMenu)
        if (-not $atMenu) { break }
        $m = @(Get-Content $debugLog | Where-Object { $_ -match $menuLine }) | Select-Object -Last 1
        Write-Host ("  " + $m)
        $next = $m -match "next race 1"
        $rows = 0; $row = 0; $loop = $false
        if ($m -match "rows (\d+), row (\d+), loop (\d)") {
            $rows = [int]$Matches[1]; $row = [int]$Matches[2]; $loop = $Matches[3] -eq "1"
        }
        if ($next) {
            Popup-Yes                                  # Next Race
            $nexts++
            Write-Host ("  race {0} saved: {1}" -f $races, (Answer-Autosave))
            $more = $true
            continue
        }
        if ($loop -and $row -eq 0) {
            Press $VK_T                                # up, round to Quit
        } else {
            for ($k = $row; $k -lt $rows - 1; $k++) { Press $VK_G }
        }
        Shot ("race{0}-quit" -f $races)
        Popup-Yes                                      # Quit
        Write-Host ("  race {0} saved: {1}" -f $races, (Answer-Autosave))
        $treeAgain = Wait-ForLogCount $treeEnter ($treeN + 1) 40
        Shot ("race{0}-after-save" -f $races)
    }
    Write-Host ("  races {0}, finished {1}, Next Race {2}, back at the tree: {3}" -f $races, $finishes, $nexts, $treeAgain)
    if ($treeAgain) {
        Start-Sleep -Seconds 3
        Shot "tree-after-race"
    }
}

$survived = Alive
if ($survived) { $proc | Stop-Process -Force }
Start-Sleep -Milliseconds 600
Set-TestFinish $false

# --- the verdict ------------------------------------------------------------

$dbg = @(); if (Test-Path $debugLog)  { $dbg = Get-Content $debugLog }
$az  = @(); if (Test-Path $azaharLog) { $az  = Get-Content $azaharLog }

$crashSigs = @("PANIC", "segfault", "Unhandled exception", "svcBreak")
$crash = $az | Where-Object { $l = $_; $crashSigs | Where-Object { $l -match $_ } }
$unmapped = $az | Where-Object { $_ -match "unmapped (Read|Write)" }

# The log's lines land up to ~7 s late: what was not there while the run
# went on may be there now.
if (-not $atDetails) {
    $atDetails = @($dbg | Where-Object { $_ -match "help override (800037|800049|800038)" }).Count -gt 0
}
if (-not $atReward) {
    $atReward = @($dbg | Where-Object { $_ -match "help override (800044|800052)" }).Count -gt 0
}

$viewer = @($dbg | Where-Object { $_ -match "^mode [1-3]$|^geoview: entered|^trackview: entered" })

$verdict = "UNKNOWN"
if (-not $booted)        { $verdict = "FAIL (never reached the main loop)" }
elseif ($viewer.Count -gt 0 -and -not $debugMenuOn) {
    $verdict = "FAIL (SELECT opened a viewer without the debug menu: $($viewer[0]))"
}
elseif ($crash)          { $verdict = "FAIL (crash: $($crash[0]))" }
elseif ($unmapped)       { $verdict = "FAIL ($(@($unmapped).Count) unmapped accesses, first: $(@($unmapped)[0]))" }
elseif ($OpenUltimates -and -not ($ultOpened -and $ultSaved)) { $verdict = "PARTIAL (the debug menu's Open the Ultimates was not done and saved)" }
elseif (-not $atTree)    { $verdict = "PARTIAL (never reached the event tree)" }
elseif ($OpenUltimates -and -not $ultPopup) { $verdict = "PARTIAL (the tree opened without the Ultimate's popup)" }
elseif (-not $onEvent)   { $verdict = "PARTIAL (-Path did not end on event $Event)" }
elseif (-not $atDetails) { $verdict = "PARTIAL (A on the tree did not open the details)" }
elseif (-not $atReward -and -not $Race) { $verdict = "PARTIAL (SQUARE on the details did not open the reward)" }
elseif (-not $atCarSel -and -not $resumed) { $verdict = "PARTIAL (A on the details did not reach car select)" }
elseif ($Race -and -not $left)      { $verdict = "PARTIAL (A on car select did not leave the frontend)" }
elseif ($Race -and -not $racing)    { $verdict = "PARTIAL (left the frontend, never reached RACING)" }
elseif ($Race -and $finishes -lt 1) { $verdict = "PARTIAL (RACING, but the test's finish never came)" }
elseif ($Race -and -not $treeAgain) { $verdict = "PARTIAL ($finishes race(s) finished; the end screens never reached the tree)" }
elseif ($Race -and -not $survived)  { $verdict = "FAIL (back at the tree, then died)" }
elseif ($Race)           { $verdict = "PASS ($finishes race(s), Next Race $nexts time(s), and back at the tree)" }
elseif (-not $survived)  { $verdict = "FAIL (reached car select, then died)" }
else                     { $verdict = "PASS (tree, details, reward, then car select)" }

Write-Host ""
Write-Host "=== flow ==="
$dbg | Where-Object { $_ -match "flow (enter|leave|change|want|state RACING|unregistered)|etv |debug menu|fred race setup|race: the test|race: rc \d+, stage 4|event|save|popup \d+ (summon|dismiss)|memcard|not ported|abort|assert|fatal" } |
    Select-Object -Last 120 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== nfshp2_debug.txt (last 20) ==="
$dbg | Select-Object -Last 20 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== azahar_log.txt errors ==="
$az | Where-Object { $_ -match "Error|Critical|PANIC" } | Select-Object -Last 12 |
    ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== Result ==="
if ($debugMenuOn) { Write-Host "SELECT:     not checked (DebugMenu 1 on the card)" }
else { Write-Host ("SELECT:     {0} viewer line(s)" -f $viewer.Count) }
Write-Host ("Verdict:    {0}" -f $verdict)
Write-Host ("Screenshots: {0} in {1}" -f $step, $OutDir)
