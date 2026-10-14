# Runs the Local Wireless lobby (TASKS 37b, lobby.h) between 2 to 8 Azahar
# instances in a room of their own. Each boots the game to World Racing's
# Challenge, sets Players to Local Wireless and selects it; A hosts, the
# rest search, find A's race and join it, and A starts once every one is on
# its list. Every copy must then reach Select Car, each joiner told its
# place of how many.
#
# The copies are run_azahar_wireless.ps1's: portable Azahars under
# %TEMP%\nfshp2_wl, each with its own console name and card, joined to the
# room through Multiplayer > Direct Connect to Room. Each card gets the
# retail data the user's own card has, a junction per folder of
# sdmc:/NFSHP2, a copy of its SAVES (never a junction: a save on one copy
# is not another's), so every copy starts from the same profile, and the
# DSP firmware (sdmc:/3ds/dspfirm.cdc), so every copy has its sound. The
# walk to Challenge is run_azahar_challenge.ps1's, each copy on its own
# clock and driven by its own debug log ("DebugLog 1"), which lands up to
# ~7 s late: a press that changes screen is repeated only after 20 s with
# nothing, and a press on the lobby's popups never is.
#
# With -Race (TASKS 37c, netrace.h) each copy goes on: its car (A on the
# transmission, Automatic and the first handling), which a client sends to
# the host and waits on "Wireless Race"; the host's first track, which
# builds the race once every car is in; the setup taken on each client,
# every copy's load held until the host's GO, and the race on one seed.
#
# Usage:
#   powershell -File tools/run_azahar_lobby.ps1
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 4
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 2 -Race
#
# Screenshots of each copy go to %TEMP%\nfshp2_lobby. Exit code 0 when
# every copy reached Select Car from the lobby (with -Race: racing, every
# copy's GO on the host's seed).

param(
    [ValidateRange(2, 8)]
    [int]$Consoles = 2,           # the host and the rest
    [switch]$Race,                # on to a loaded race (37c)
    [int]$RunSeconds = 0,         # hard ceiling; 0 is 240 + 30 a console, + 300 with -Race
    [string]$AzaharDir = "C:\Program Files\Azahar",
    [string]$Target3dsx = "",
    [string]$WorkDir = "",
    [string]$OutDir = "",
    [int]$Port = 24873
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($WorkDir -eq "") { $WorkDir = Join-Path $env:TEMP "nfshp2_wl" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_lobby" }
if ($RunSeconds -le 0) { $RunSeconds = 240 + 30 * $Consoles + $(if ($Race) { 300 } else { 0 }) }
$azahar = Join-Path $AzaharDir "azahar.exe"
$roomExe = Join-Path $AzaharDir "azahar-room.exe"
$dataRoot = Join-Path $env:APPDATA "Azahar\sdmc\NFSHP2"
foreach ($f in @($azahar, $roomExe, $Target3dsx, $dataRoot)) {
    if (-not (Test-Path $f)) { throw "not found: $f" }
}
if ($Target3dsx -like "*.cia") {
    throw "Refusing to run a .cia: Azahar cannot boot one from a path. Pass the .3dsx."
}

# Emulators on battery run slow (38% speed unplugged, 2026-10-08).
$battery = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue
if ($battery -and $battery.BatteryStatus -eq 1) {
    throw "on battery: plug in before an Azahar run"
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Drawing;
public class Hp2Lb {
    [DllImport("user32.dll")] public static extern IntPtr PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern int PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    public struct RECT { public int Left, Top, Right, Bottom; }

    // Azahar's launch dialogs; see run_azahar_challenge.ps1.
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
    // Held 140 ms, so one emulated frame's hidScanInput sees it; see
    // run_azahar_challenge.ps1.
    public static void PressKey(IntPtr h, int vk) {
        PostMessage(h, 0x0100, (IntPtr)vk, IntPtr.Zero);   // WM_KEYDOWN
        System.Threading.Thread.Sleep(140);
        PostMessage(h, 0x0101, (IntPtr)vk, IntPtr.Zero);   // WM_KEYUP
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
[void][Hp2Lb]::SetProcessDPIAware()
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]

# The user's key map: A, B, START, and the D-pad's down and right.
$VK_A = 65; $VK_B = 83; $VK_START = 77; $VK_DOWN = 71; $VK_RIGHT = 72

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Get-ChildItem $OutDir -Filter *.png -ErrorAction SilentlyContinue | Remove-Item -Force

# --- the copies ---------------------------------------------------------------

# The config savegame's user name block; see run_azahar_wireless.ps1.
function SetConsoleName([string]$path, [string]$nick) {
    $b = [System.IO.File]::ReadAllBytes($path)
    $n = [BitConverter]::ToUInt16($b, 0)
    for ($i = 0; $i -lt $n; $i++) {
        $e = 4 + 12 * $i
        if ([BitConverter]::ToUInt32($b, $e) -ne 0x000A0000) { continue }
        $off = [BitConverter]::ToUInt32($b, $e + 4)
        $u = [System.Text.Encoding]::Unicode.GetBytes($nick)
        for ($j = 0; $j -lt 20; $j++) {
            $b[$off + $j] = if ($j -lt $u.Length) { $u[$j] } else { 0 }
        }
        [System.IO.File]::WriteAllBytes($path, $b)
        return
    }
    throw "no user name block in $path"
}

function IsJunction([string]$path) {
    return [bool]((Get-Item $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)
}

# The card's sdmc:/NFSHP2: a junction to each of the user's data folders,
# and SAVES a folder of its own with the user's saves copied in.
function LinkData([string]$user) {
    $nfs = Join-Path $user "sdmc\NFSHP2"
    New-Item -ItemType Directory -Force -Path $nfs | Out-Null
    foreach ($d in Get-ChildItem -Directory $dataRoot) {
        if ($d.Name -eq "SAVES") { continue }
        $link = Join-Path $nfs $d.Name
        if (Test-Path $link) {
            if (-not (IsJunction $link)) { throw "$link is a folder, not a junction to $($d.FullName)" }
            continue
        }
        New-Item -ItemType Junction -Path $link -Target $d.FullName | Out-Null
    }
    $saves = Join-Path $nfs "SAVES"
    if (Test-Path $saves) {
        if (IsJunction $saves) { throw "$saves is a junction; it must be the copy's own" }
        Get-ChildItem -Path $saves -File -Recurse | Remove-Item -Force
    } else {
        New-Item -ItemType Directory -Path $saves | Out-Null
    }
    $src = Join-Path $dataRoot "SAVES"
    if (Test-Path $src) {
        Copy-Item -Path (Join-Path $src "*") -Destination $saves -Recurse -Force
    }
    # ndsp's DSP firmware, where libctru looks for it; without it the game
    # runs silent ("Sound: ndsp unavailable").
    $dsp = Join-Path $env:APPDATA "Azahar\sdmc\3ds\dspfirm.cdc"
    if (-not (Test-Path $dsp)) { throw "no $dsp to give the copies their sound" }
    New-Item -ItemType Directory -Force -Path (Join-Path $user "sdmc\3ds") | Out-Null
    Copy-Item -Path $dsp -Destination (Join-Path $user "sdmc\3ds\dspfirm.cdc") -Force
}

# One portable copy: the install, a config with the room in it, its name,
# the data and a card that logs.
function Prepare([string]$name, [string]$nick, [bool]$isHost) {
    $dir = Join-Path $WorkDir $name
    $exe = Join-Path $dir "azahar.exe"
    if (-not (Test-Path $exe) -or
        (Get-Item $azahar).LastWriteTime -gt (Get-Item $exe).LastWriteTime) {
        Write-Host "  copying Azahar to $dir"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Copy-Item -Path (Join-Path $AzaharDir "*") -Destination $dir -Recurse -Force
    }
    $user = Join-Path $dir "user"
    foreach ($d in @("config", "sdmc")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $user $d) | Out-Null
    }
    $set = @{ "Multiplayer\nickname" = $nick; "Multiplayer\ip" = "127.0.0.1";
              "Multiplayer\port" = "$Port" }
    $ini = Get-Content (Join-Path $env:APPDATA "Azahar\config\qt-config.ini")
    $out = foreach ($line in $ini) {
        $done = $false
        foreach ($k in $set.Keys) {
            if ($line -eq "$k\default=true") { "$k\default=false"; $done = $true; break }
            if ($line.StartsWith("$k=")) { "$k=$($set[$k])"; $done = $true; break }
        }
        if (-not $done) { $line }
    }
    Set-Content -Path (Join-Path $user "config\qt-config.ini") -Value $out -Encoding ASCII
    $cfg = Join-Path $user "nand\data\00000000000000000000000000000000\sysdata\00010017\00000000\config"
    if (-not (Test-Path $cfg)) {
        Write-Host "  $($name): first start, for the config savegame"
        $p = Start-Process -FilePath $exe -PassThru
        $deadline = (Get-Date).AddSeconds(30)
        while (-not (Test-Path $cfg) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
        Start-Sleep -Seconds 1
        $p | Stop-Process -Force
        if (-not (Test-Path $cfg)) { throw "$($name): no config savegame at $cfg" }
    }
    SetConsoleName $cfg $nick
    # The frontend, not the soak: no WirelessTest and no SkipFE.
    Set-Content -Path (Join-Path $user "sdmc\nfshp2_config.txt") -Encoding ASCII -Value @("DebugLog 1")
    LinkData $user
    $log = Join-Path $user "sdmc\nfshp2_debug.txt"
    Remove-Item $log -ErrorAction SilentlyContinue
    $azLog = Join-Path $user "log\azahar_log.txt"
    Remove-Item $azLog -ErrorAction SilentlyContinue
    return [pscustomobject]@{
        Name = $name; Nick = $nick; IsHost = $isHost; Exe = $exe; Log = $log;
        AzLog = $azLog; Proc = $null; Hwnd = [IntPtr]::Zero; Joined = $false;
        Steps = $null; Step = 0; Phase = "start"; Mark = 0; Tries = 0;
        Deadline = $null; SettleUntil = $null; Seen = @{}; Failed = $null;
        Done = $false; Shots = 0
    }
}

function Launch($side) {
    $side.Proc = Start-Process -FilePath $side.Exe -ArgumentList "`"$Target3dsx`"" -PassThru
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        $side.Proc.Refresh()
        if ($side.Proc.HasExited) { throw "$($side.Name): Azahar exited before opening a window" }
        if ($side.Proc.MainWindowHandle -ne 0) { break }
        Start-Sleep -Milliseconds 250
    }
    if ($side.Proc.MainWindowHandle -eq 0) { throw "$($side.Name): no Azahar window" }
    $side.Hwnd = $side.Proc.MainWindowHandle
    Start-Sleep -Seconds 1
    $closed = [Hp2Lb]::DismissPopups([uint32]$side.Proc.Id, $side.Hwnd)
    if ($closed -gt 0) { Write-Host "  $($side.Name): dismissed $closed launch dialog(s)" }
}

function Find($scope, [string]$prop, [string]$value) {
    $p = switch ($prop) { "name" { $AE::NameProperty } "id" { $AE::AutomationIdProperty } }
    $c = New-Object System.Windows.Automation.PropertyCondition($p, $value)
    return $scope.FindFirst($TS::Descendants, $c)
}

function MainWindow($side) {
    $c = New-Object System.Windows.Automation.PropertyCondition($AE::ProcessIdProperty, $side.Proc.Id)
    return $AE::RootElement.FindFirst($TS::Children, $c)
}

function RoomLabel($side) {
    $w = MainWindow $side
    if ($null -eq $w) { return "" }
    $l = Find $w "id" "QApplication.MainWindow.QStatusBar.ClickableLabel"
    if ($null -eq $l) { return "" }
    return $l.Current.Name
}

# Multiplayer > Direct Connect to Room; see run_azahar_wireless.ps1.
function JoinRoom($side) {
    $w = MainWindow $side
    $menu = Find $w "name" "Multiplayer"
    $menu.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern).Expand()
    Start-Sleep -Milliseconds 500
    $item = Find $w "name" "Direct Connect to Room"
    if ($null -eq $item) { throw "$($side.Name): no Direct Connect item" }
    $item.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    $dlg = $null
    $deadline = (Get-Date).AddSeconds(10)
    while ($null -eq $dlg -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
        $dlg = Find (MainWindow $side) "id" "QApplication.DirectConnect"
    }
    if ($null -eq $dlg) { throw "$($side.Name): no Direct Connect dialog" }
    $fields = @{ "ip_container.ip" = "127.0.0.1"; "ip_container.port" = "$Port" }
    foreach ($k in $fields.Keys) {
        $e = Find $dlg "id" "QApplication.DirectConnect.$k"
        $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($fields[$k])
    }
    $btn = Find $dlg "id" "QApplication.DirectConnect.connect"
    $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $label = RoomLabel $side
        if ($label -ne "" -and -not $label.StartsWith("Not Connected")) {
            $side.Joined = $true
            Write-Host "  $($side.Name): in the room ($label)"
            return
        }
    }
    Write-Host "  $($side.Name): not in the room after 15 s ('$(RoomLabel $side)')"
}

function Alive($side) { $side.Proc.Refresh(); -not $side.Proc.HasExited }

function LogLines($side, [string]$pattern) {
    if (-not (Test-Path $side.Log)) { return @() }
    return @(Select-String -Path $side.Log -Pattern $pattern -ErrorAction SilentlyContinue |
             ForEach-Object { $_.Line })
}

# How many of the log's lines past line $after match $pattern.
function LogCount($side, [string]$pattern, [int]$after) {
    if (-not (Test-Path $side.Log)) { return 0 }
    return @(Select-String -Path $side.Log -Pattern $pattern -ErrorAction SilentlyContinue |
             Where-Object { $_.LineNumber -gt $after }).Count
}

# How many lines the log has so far.
function LogLength($side) {
    if (-not (Test-Path $side.Log)) { return 0 }
    $last = Select-String -Path $side.Log -Pattern "^" -ErrorAction SilentlyContinue | Select-Object -Last 1
    if ($null -eq $last) { return 0 }
    return $last.LineNumber
}

function Shot($side, [string]$tag) {
    if (-not (Alive $side)) { return }
    $side.Shots++
    $path = Join-Path $OutDir ("{0}_{1:d2}_{2}.png" -f $side.Name, $side.Shots, $tag)
    [Hp2Lb]::CaptureToFile($side.Hwnd, $path)
}

# --- the walk ----------------------------------------------------------------
# Each copy follows its own list of steps. A step presses Key (if any) and
# waits up to Wait s for Pattern to match Need lines of the copy's log past
# the last press (its own, or the last step's that pressed: a line can land
# before the step that waits for it begins), or for Check to say so; with
# Tries above 1 the press is made again after each Wait with nothing. A step whose When says no is
# passed over; an Optional one that fails is passed over too. Settle is the
# ms waited after it, and Shot a screenshot's name.

function Step([string]$name, [hashtable]$h) {
    $s = @{ Name = $name; Key = 0; Pattern = $null; Check = $null; Need = 1;
            Wait = 20; Tries = 1; Optional = $false; When = $null;
            Settle = 0; Shot = $null }
    foreach ($k in $h.Keys) { $s[$k] = $h[$k] }
    return $s
}

$boot = @(
    Step "main loop" @{ Pattern = "entering main loop"; Wait = 120 }
    Step "language" @{ Pattern = "flow enter Language Options Pre FE"; Wait = 30; Optional = $true; Settle = 1500 }
    Step "language A" @{ Key = $VK_A; Pattern = "flow leave Language Options Pre FE"; Tries = 2;
                      When = { param($s) $s.Seen["language"] } }
    Step "intro" @{ Pattern = "^movie open MOVIES/INTRO/NFSINTRO"; Wait = 40; Optional = $true; Settle = 2000 }
    Step "intro skip" @{ Key = $VK_START; Pattern = "flow title skip"; Tries = 2;
                      When = { param($s) $s.Seen["intro"] } }
    Step "title idle" @{ Pattern = "flow title idle"; Optional = $true;
                      When = { param($s) -not $s.Seen["intro"] } }
    Step "title" @{ Pattern = "flow vis object b5761d00 b070dbc9 1"; Wait = 15; Optional = $true; Settle = 900 }
    Step "main menu" @{ Key = $VK_START; Pattern = "flow enter New Main Menu [0-9a-f]{8}"; Tries = 2 }
    Step "main menu up" @{ Pattern = "screen New Main Menu [0-9a-f]{8} .* last HIGHLIGHT"; Optional = $true; Settle = 1000 }
    Step "world racing" @{ Key = $VK_DOWN; Pattern = "flow bracket 708a0bf1"; Tries = 2 }
    Step "mode select" @{ Key = $VK_A; Pattern = "flow enter Cops Off Mode Select [0-9a-f]{8}"; Tries = 2 }
    Step "mode select up" @{ Pattern = "screen Cops Off Mode Select [0-9a-f]{8} .* last HIGHLIGHT"; Optional = $true; Settle = 1000 }
    Step "to challenge" @{ Key = $VK_DOWN; Settle = 700 }
    Step "challenge" @{ Key = $VK_A; Pattern = "flow enter Challenge [0-9a-f]{8}"; Tries = 2 }
    Step "challenge up" @{ Pattern = "screen Challenge [0-9a-f]{8} .* last HIGHLIGHT"; Optional = $true; Settle = 1000;
                        Shot = "challenge" }
    # Players, the first row: right from 1 to Local Wireless, and A.
    Step "players" @{ Key = $VK_RIGHT; Settle = 1200; Shot = "players" }
    Step "lobby" @{ Key = $VK_A; Pattern = "lobby: ask"; Wait = 30; Settle = 1000; Shot = "ask" }
)

# The host's list: "Waiting for players:" and a name for each console.
function ListFull($side) {
    $l = @(LogLines $side "lobby: list ")
    if ($l.Count -eq 0) { return $false }
    return (($l[-1] -split "@").Count - 1) -ge $Consoles
}

$hostSteps = $boot + @(
    Step "host" @{ Key = $VK_A; Pattern = "lobby: hosting"; Settle = 500; Shot = "hosting" }
    Step "all in" @{ Check = { param($s) ListFull $s }; Wait = $RunSeconds; Settle = 1500; Shot = "list" }
    Step "start" @{ Key = $VK_A; Pattern = "lobby: start, $Consoles consoles" }
    Step "car select" @{ Pattern = "flow enter Select Car [0-9a-f]{8}"; Wait = 30; Settle = 2000; Shot = "carsel" }
)
$joinSteps = $boot + @(
    Step "join pick" @{ Key = $VK_RIGHT; Settle = 700 }
    Step "search" @{ Key = $VK_A; Pattern = "lobby: searching"; Settle = 500; Shot = "searching" }
    Step "found" @{ Pattern = "lobby: found 1 of \d+, hp2host"; Wait = 90; Settle = 1000; Shot = "found" }
    Step "join" @{ Key = $VK_A; Pattern = "lobby: joined hp2host"; Settle = 500; Shot = "joined" }
    Step "started" @{ Pattern = "lobby: started by hp2host, place \d+ of $Consoles"; Wait = $RunSeconds }
    Step "car select" @{ Pattern = "flow enter Select Car [0-9a-f]{8}"; Wait = 30; Settle = 2000; Shot = "carsel" }
)

# -Race: the car (see run_azahar_coprace.ps1), then the host's track and
# each client's wait, the load, GO and the race.
if ($Race) {
    $car = @(
        Step "transmission" @{ Key = $VK_A; Settle = 1500 }
        Step "automatic" @{ Key = $VK_A; Settle = 1500; Shot = "handling" }
    )
    $raceEnd = @(
        Step "go" @{ Pattern = "netrace: go, seed"; Wait = 240 }
        Step "racing" @{ Pattern = "flow state RACING"; Wait = 60; Settle = 6000; Shot = "race" }
        Step "race on" @{ Pattern = "^trackview: attached"; Wait = 90; Optional = $true; Settle = 8000;
                         Shot = "race-on" }
    )
    $hostSteps += $car + @(
        Step "track select" @{ Key = $VK_A; Pattern = "flow enter Select Track"; Tries = 2; Settle = 2500;
                              Shot = "track" }
        Step "host start" @{ Key = $VK_A; Pattern = "netrace: the host's start"; Tries = 2; Settle = 1500;
                            Shot = "host-wait" }
        Step "built" @{ Pattern = "netrace: built"; Wait = $RunSeconds; Settle = 1500; Shot = "loading" }
    ) + $raceEnd
    $joinSteps += $car + @(
        Step "car sent" @{ Key = $VK_A; Pattern = "netrace: car sent"; Tries = 2; Settle = 1500;
                          Shot = "client-wait" }
        Step "taken" @{ Pattern = "netrace: setup taken"; Wait = $RunSeconds; Settle = 1500; Shot = "loading" }
    ) + $raceEnd
}

$start = Get-Date
function Elapsed { ((Get-Date) - $start).TotalSeconds }
function Say($side, [string]$what) {
    Write-Host ("  [{0,5:N0}s] {1}: {2}" -f (Elapsed), $side.Name, $what)
}

function StepDone($side, $step) {
    if ($step.Check) { return [bool](& $step.Check $side) }
    if (-not $step.Pattern) { return $true }
    return (LogCount $side $step.Pattern $side.Mark) -ge $step.Need
}

# One look at a copy: begin its step, see whether it is done, press again,
# or move on.
function Advance($side) {
    if ($side.Done -or $side.Failed) { return }
    if (-not (Alive $side)) { $side.Failed = "Azahar exited"; Say $side "Azahar exited"; return }
    $step = $side.Steps[$side.Step]
    $now = Get-Date
    switch ($side.Phase) {
        "start" {
            if ($step.When -and -not (& $step.When $side)) { NextStep $side; return }
            if ($step.Key) {
                $side.Mark = LogLength $side
                [Hp2Lb]::PressKey($side.Hwnd, $step.Key)
            }
            $side.Tries = 1
            $side.Deadline = $now.AddSeconds($step.Wait)
            $side.Phase = "wait"
        }
        "wait" {
            if (StepDone $side $step) {
                $side.Seen[$step.Name] = $true
                $side.SettleUntil = $now.AddMilliseconds($step.Settle)
                $side.Phase = "settle"
                if ($step.Name -match "^(lobby|host|search|found|join|started|car select|all in|start|track select|host start|built|car sent|taken|go|racing|race on)$") {
                    Say $side $step.Name
                }
            } elseif ($now -gt $side.Deadline) {
                if ($step.Key -and $side.Tries -lt $step.Tries) {
                    [Hp2Lb]::PressKey($side.Hwnd, $step.Key)
                    $side.Tries++
                    $side.Deadline = $now.AddSeconds($step.Wait)
                } elseif ($step.Optional) {
                    NextStep $side
                } else {
                    $side.Failed = "no '$($step.Name)' after $($side.Tries) x $($step.Wait) s"
                    Say $side $side.Failed
                    Shot $side ("stuck-" + ($step.Name -replace " ", "-"))
                }
            }
        }
        "settle" {
            if ($now -ge $side.SettleUntil) {
                if ($step.Shot) { Shot $side $step.Shot }
                NextStep $side
            }
        }
    }
}

function NextStep($side) {
    $side.Step++
    $side.Phase = "start"
    if ($side.Step -ge $side.Steps.Count) { $side.Done = $true }
}

# --- the run -------------------------------------------------------------------

$letters = "ABCDEFGH"
Write-Host "Preparing $Consoles copies"
$sides = @()
for ($i = 0; $i -lt $Consoles; $i++) {
    $nick = if ($i -eq 0) { "hp2host" } else { "hp2join$i" }
    $s = Prepare $letters[$i] $nick ($i -eq 0)
    $s.Steps = if ($i -eq 0) { $hostSteps } else { $joinSteps }
    $sides += $s
}

Write-Host "Starting the room on port $Port"
$room = Start-Process -FilePath $roomExe -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $WorkDir "room_out.txt") `
    -RedirectStandardError (Join-Path $WorkDir "room_err.txt") `
    -ArgumentList "--room-name nfshp2-lobby --port $Port --max_members $($Consoles + 2) --preferred-app NFSHP2 --preferred-app-id 0"
Start-Sleep -Seconds 2
$room.Refresh()
if ($room.HasExited) { throw "the room server exited: see $WorkDir\room_out.txt" }

try {
    Write-Host "Launching $($sides[0].Name) (host) and $($Consoles - 1) to join, with $Target3dsx"
    foreach ($s in $sides) { Launch $s }
    foreach ($s in $sides) { JoinRoom $s }
    foreach ($s in $sides) { if (-not $s.Joined) { throw "$($s.Name) did not join the room" } }

    $deadline = $start.AddSeconds($RunSeconds)
    while ((Get-Date) -lt $deadline) {
        foreach ($s in $sides) { Advance $s }
        if (@($sides | Where-Object { -not $_.Done -and -not $_.Failed }).Count -eq 0) { break }
        Start-Sleep -Milliseconds 250
    }
    foreach ($s in $sides) {
        if (-not $s.Done -and -not $s.Failed) {
            $s.Failed = "out of time on '$($s.Steps[$s.Step].Name)'"
            Shot $s "timeout"
        }
    }
    # The log's last lines land up to ~7 s late.
    Start-Sleep -Seconds 8
} finally {
    foreach ($s in $sides) {
        if ($s.Proc -and (Alive $s)) { $s.Proc | Stop-Process -Force }
    }
    if (-not $room.HasExited) { $room | Stop-Process -Force }
}

# --- the verdict ---------------------------------------------------------------

$crashSigs = "PANIC|segfault|Unhandled exception|svcBreak|unmapped (Read|Write)"
Write-Host ""
foreach ($s in $sides) {
    Write-Host "--- $($s.Name) ($($s.Nick)): $($s.Log) ---"
    LogLines $s "lobby: |netrace: |race start:|flow state RACING|flow enter (Challenge|Local Wireless|Select Car|Select Track|Wireless Race)|wireless:" |
        Select-Object -First 80 | ForEach-Object { Write-Host "  $_" }
    if (@(LogLines $s "^Sound: ndsp unavailable").Count -gt 0 -and -not $s.Failed) {
        $s.Failed = "no sound: ndsp unavailable"
    }
    if (Test-Path $s.AzLog) {
        $crash = @(Select-String -Path $s.AzLog -Pattern $crashSigs | Select-Object -First 3)
        foreach ($c in $crash) {
            Write-Host "  azahar: $($c.Line)"
            if (-not $s.Failed) { $s.Failed = "Azahar: $($c.Line)" }
        }
    }
}
# -Race: every copy's GO on the host's seed.
if ($Race) {
    $hostSeed = $null
    foreach ($s in $sides) {
        $go = @(LogLines $s "netrace: go, seed ([0-9a-f]{8})")
        if ($go.Count -ne 1) {
            if (-not $s.Failed) { $s.Failed = "$($go.Count) GO lines" }
            continue
        }
        $seed = ([regex]::Match($go[0], "seed ([0-9a-f]{8})")).Groups[1].Value
        if ($null -eq $hostSeed) { $hostSeed = $seed }
        elseif ($seed -ne $hostSeed -and -not $s.Failed) { $s.Failed = "GO on $seed, the host's $hostSeed" }
    }
}
Write-Host ""
$failed = @($sides | Where-Object { -not $_.Done -or $_.Failed })
$goal = if ($Race) { "racing" } else { "Select Car" }
foreach ($s in $sides) {
    $v = if ($s.Done -and -not $s.Failed) { "PASS ($goal)" } else { "FAIL ($($s.Failed))" }
    Write-Host ("{0} {1,-9} {2}" -f $s.Name, $s.Nick, $v)
}
Write-Host "Screenshots in $OutDir"
if ($failed.Count -eq 0) {
    if ($Race) { Write-Host "All $Consoles racing from the lobby, GO on seed $hostSeed." }
    else { Write-Host "All $Consoles reached Select Car from the lobby." }
} else {
    exit 1
}
