# Runs the Local Wireless lobby (TASKS 37b, lobby.h) between 2 to 8 Azahar
# instances in a room of their own. Each boots the game to the main menu
# and selects Local Wireless, its fourth row (TASKS 63). A hosts: World
# Racing on the mode question (Hot Pursuit with -CopsOn), then the
# Challenge, its Players reading Local Wireless, selected as it stands,
# back to the lobby. The rest search, find A's race and join it, and A
# starts once every one is on its list. Every copy must then reach Select
# Car, each joiner told its place of how many and the host's mode.
#
# Where the race setup has CPU racers to choose (TASKS 37c-2, a last line
# on the host's list), the host moves to CPU Racers and counts to -Cpu
# (2 unless said; -1 leaves the count shown), then back to Start; the race
# must start with that many.
#
# The copies are run_azahar_wireless.ps1's: portable Azahars under
# %TEMP%\nfshp2_wl, each with its own console name and card, joined to the
# room through Multiplayer > Direct Connect to Room. Each card gets the
# retail data the user's own card has, a junction per folder of
# sdmc:/NFSHP2, a copy of its SAVES (never a junction: a save on one copy
# is not another's), so every copy starts from the same profile, and the
# DSP firmware (sdmc:/3ds/dspfirm.cdc), so every copy has its sound. Each
# copy walks on its own clock, driven by its own debug log ("DebugLog
# 1"), which lands up to ~7 s late: a press that changes screen is
# repeated only after 20 s with nothing, and a press on the lobby's popups
# never is.
#
# With -Race (TASKS 37c, netrace.h) each copy goes on: its car, which a
# client sends to the host and waits on "Wireless Race"; the host's first
# track, which builds the race once every car is in; the setup taken on
# each client, every copy's load held until the host's GO, and the race on
# one seed, with as many drivers as consoles and CPU racers. Each copy
# picks its own car: the host the profile's, Automatic; copy i the first
# unlocked car (the unlocked come first, and left stops there), then
# (i - 1) mod (u - 1) + 1 to the right of the u unlocked; Manual where i is
# odd, Automatic where even; the first handling. Each client's car and
# transmission must reach the host as it chose them.
#
# With -Race the race runs in lockstep (TASKS 37d, netstep.h): once every
# copy is racing, each holds A, the gas, for -Drive seconds (30 unless
# said; never the brake), a shot of each every 10 s, and every copy must
# log the lockstep's start and its frames flowing.
#
# 37e: each copy logs the world's checksum in parts (lockhash.h) every 150
# frames, and the parts and draws of the 16 frames up to the first frame
# whose checksum differs. The verdict compares every copy's parts with the
# host's frame by frame, and fails a copy at the first that differs, naming
# the parts and showing both copies' draws on bDefaultSeed there (map the
# addresses with arm-none-eabi-addr2line on the .elf), the clocks if they
# differ, and each car slot that differs with the pieces it differs in
# (lockhash's "cars" and "fields" lines, Session 108). With -CopsOn the
# host hosts Hot Pursuit, so the race has cops, and every joiner must be
# told so; with -Steer each copy also steers, left and right on the
# D-pad by turns, its own period each (2 s for the host, 3 s for B, ...), so
# the cars hit walls and each other.
#
# With -Quit (TASKS 37f; -Race), once the driving is done the host pauses,
# moves down to Quit Race (the item the log says is highlighted) and says
# OK. The pause runs in lockstep, its screens on the host's pad, so every
# copy quits on the same frame: each must log the lockstep's stop on the
# host's frame, the race over and its way back to the lobby, and the host
# every client's stop. The host then waits for every console's word that
# it is back and starts again, and every copy must reach Select Car a
# second time.
#
# With -Restart (TASKS 37f-2; -Race), once the driving is done the host
# pauses, moves down to Restart (the pause's second item) and says OK.
# The race restarts in place on every copy, still in lockstep: each must
# show the race's start again and race on, and the gas is held for
# -Drive seconds more. No copy may stop its lockstep, and every copy's
# parts must stay the host's through both.
#
# With -PauseBy 1 (TASKS 37f-3; -Quit or -Restart) B pauses instead of
# the host, and B's pad drives the pause's screens on every copy. Before B
# moves, the host presses Down and START on B's pause: each press reaches
# every copy on the host's port (the log's "lockstep: frame N, port 0's
# presses"), and the pause must stay up on Resume Race, as retail's split
# screen hears only the pad that paused (SetScreenFilterPort). Every copy
# must log the pause on B's port on the same frame, and the host's presses
# on the same frames. With -PauseBy 0 (the default) B makes those presses
# on the host's pause.
#
# With -NextRace (TASKS 37f-2; -Race) the host hosts Knockout (Race Type,
# right of Single Race, on the Challenge), and each copy's config has
# "WirelessTestFinish -Finish", so every copy finishes the race on that
# lockstep frame (the gas alone never finishes one). -Finish is 1800
# unless said, and must come after the driving: about 30 frames a
# second. The host says A through the results to the End Game Menu, then
# Next Race and OK, all in lockstep up to the save's question, where
# every copy stops on the same frame. Each says Yes to its own save,
# loads the event's next race and holds, and the host's GO starts them
# all again on one seed: every copy must log race 2 loaded, a second GO
# on the host's seed and a second lockstep start, and race on for -Drive
# seconds more, its parts the host's in each race.
#
# With -NoDsp the copies' cards have no DSP firmware, so ndsp fails and the
# game must run silent: each copy has to log "Sound: ndsp unavailable", and
# still pass with no unmapped read (a driver call through NULL). With
# -SilentClients only the host has sound (37e): cop speech waits for each
# console's own audio, so a race of a loud and a silent console must still
# have every part the same.
#
# With -WirelessOff (TASKS 62) each card's config has "WirelessOff 1", the
# console's wireless communication taken as off (Azahar's never is): the
# host presses Host and the rest Join, and each must say so ("lobby:
# wireless communication off", a shot of the line), go back to the
# question on OK, and never start UDS (no "wireless: up").
#
# With -Lose N (TASKS 37g-1; -Race) each card's config has
# "WirelessHoldSeconds -HoldSeconds" (10 unless said), and once the
# driving is done copy N (0 the host, 1 B, ...) is closed. The rest keep
# the gas held for the hold and 25 s more, a shot of each every 2 s: the
# race holds with the box of the lost console's name and the time left,
# then goes on, its car the CPU's. A lost client: the host must log it
# lost, then gone, and every copy left hand its car to the CPU on the
# same lockstep frame. The host lost: each client must log it lost, then
# gone, and race alone, its car the CPU's.
#
# With -Drop N (TASKS 37g-2; -Race) each card's config has the hold (30 s
# unless -HoldSeconds says), and copy N's "WirelessTestDropFrame
# -DropFrame" and "WirelessTestDropMs -DropMs": from that lockstep frame
# its wireless hears and sends nothing for that long, as a console out of
# range. Every copy drives on for the hold and 30 s more, a shot of each
# every 3 s. The links lost at both ends, the race holds; then the
# dropped copy finds its host again and is taken back. A dropped client:
# it must log the host lost, back on the host's network and the host
# back; the host the place lost, the node back in its place and the place
# back. The host dropped: each client and the host, so, for each link.
# None says a place gone, no car goes to the CPU, and every copy's parts
# stay the host's to the end.
#
# Usage:
#   powershell -File tools/run_azahar_lobby.ps1
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 4
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 2 -Race
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 2 -Race -NoDsp
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 3 -Race -Cpu 0
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 2 -WirelessOff
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 2 -Race -CopsOn -Steer -Drive 120
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 2 -Race -CopsOn -Steer -SilentClients
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 2 -Race -Quit
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 2 -Race -Restart
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 2 -Race -Quit -PauseBy 1
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 2 -Race -NextRace
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 2 -Race -Lose 1
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 2 -Race -Lose 0
#   powershell -File tools/run_azahar_lobby.ps1 -Consoles 2 -Race -Drop 1
#
# Screenshots of each copy go to %TEMP%\nfshp2_lobby. Exit code 0 when
# every copy reached Select Car from the lobby (with -Race: racing, every
# copy's GO on the host's seed; with -Quit: back in the lobby from the
# race and on to Select Car again; with -Restart: racing again after the
# restart; with -NextRace: racing in the event's next race; with -Lose:
# the lost copy's car the CPU's on every other; with -Drop: the dropped
# copy back in the race on every copy).

param(
    [ValidateRange(2, 8)]
    [int]$Consoles = 2,           # the host and the rest
    [switch]$Race,                # on to a loaded race (37c)
    [switch]$NoDsp,               # no DSP firmware on the cards: silent
    [switch]$SilentClients,       # the host with sound, the rest silent
    [switch]$WirelessOff,         # each console's wireless taken as off (62)
    [switch]$CopsOn,              # the host hosts Hot Pursuit: a race with cops
    [switch]$Steer,               # -Race: steer by turns while driving
    [switch]$Quit,                # -Race: the host's pause and Quit, all back to the lobby (37f)
    [switch]$Restart,             # -Race: the host's pause and Restart, the race again in lockstep (37f-2)
    [switch]$NextRace,            # -Race: Knockout, finished on -Finish's frame, Next Race in lockstep (37f-2)
    [ValidateRange(0, 1)]
    [int]$PauseBy = 0,            # -Quit, -Restart: the copy whose pad pauses, 0 the host or 1 B (37f-3)
    [ValidateRange(-1, 7)]
    [int]$Lose = -1,              # -Race: the copy closed once the driving is done, 0 the host (37g-1)
    [ValidateRange(1, 255)]
    [int]$HoldSeconds = 10,       # -Lose, -Drop: the hold, the cards' WirelessHoldSeconds (-Drop's 30)
    [ValidateRange(-1, 7)]
    [int]$Drop = -1,              # -Race: the copy whose wireless goes deaf mid-race, 0 the host (37g-2)
    [int]$DropFrame = 300,        # -Drop: the lockstep frame it goes deaf on
    [int]$DropMs = 5000,          # -Drop: for how long
    [ValidateRange(-1, 7)]
    [int]$Cpu = 2,                # the host's CPU racers; -1 as shown
    [int]$Drive = 30,             # -Race: seconds of gas once all race
    [int]$Finish = 1800,          # -NextRace: the lockstep frame every copy finishes the race on
    [int]$RunSeconds = 0,         # the walk's ceiling; 0 is 240 + 30 a console, + 300 with -Race
    [string]$AzaharDir = "C:\Program Files\Azahar",
    [string]$Target3dsx = "",
    [string]$WorkDir = "",
    [string]$OutDir = "",
    [int]$Port = 24873
)

$ErrorActionPreference = "Stop"
if ($WirelessOff -and $Race) { throw "-WirelessOff stops in the lobby: no -Race with it" }
if ($Quit -and -not $Race) { throw "-Quit quits a race: it needs -Race" }
if (($Restart -or $NextRace) -and -not $Race) { throw "-Restart and -NextRace go on from a race: they need -Race" }
if ([int][bool]$Quit + [int][bool]$Restart + [int][bool]$NextRace -gt 1) {
    throw "one of -Quit, -Restart and -NextRace at a time"
}
if ($NextRace -and $CopsOn) { throw "-NextRace hosts World Racing's Knockout: no -CopsOn with it" }
if ($PauseBy -gt 0 -and -not ($Quit -or $Restart)) { throw "-PauseBy says who pauses for -Quit or -Restart" }
if ($Lose -ge 0 -and -not $Race) { throw "-Lose closes a copy mid-race: it needs -Race" }
if ($Lose -ge 0 -and ($Quit -or $Restart -or $NextRace)) { throw "-Lose ends the run: no -Quit, -Restart or -NextRace with it" }
if ($Lose -ge $Consoles) { throw "-Lose ${Lose}: there are only $Consoles copies" }
if ($Drop -ge 0 -and -not $Race) { throw "-Drop deafens a copy mid-race: it needs -Race" }
if ($Drop -ge 0 -and ($Quit -or $Restart -or $NextRace -or $Lose -ge 0)) {
    throw "-Drop ends the run: no -Quit, -Restart, -NextRace or -Lose with it"
}
if ($Drop -ge $Consoles) { throw "-Drop ${Drop}: there are only $Consoles copies" }
if ($Drop -ge 0 -and -not $PSBoundParameters.ContainsKey("HoldSeconds")) { $HoldSeconds = 30 }

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
    // A key held: posted again every 150 ms by the caller, as
    // run_azahar_race.ps1's are, so a press Azahar drops does not end it.
    public static void KeyDown(IntPtr h, int vk) {
        PostMessage(h, 0x0100, (IntPtr)vk, IntPtr.Zero);   // WM_KEYDOWN
    }
    public static void KeyUp(IntPtr h, int vk) {
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

# The user's key map: A, B, START, and the D-pad's down, right, left and up.
$VK_A = 65; $VK_B = 83; $VK_START = 77; $VK_DOWN = 71; $VK_RIGHT = 72; $VK_LEFT = 70; $VK_UP = 84

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
function LinkData([string]$user, [bool]$silent) {
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
    # runs silent ("Sound: ndsp unavailable"), which -NoDsp asks for.
    $dspDir = Join-Path $user "sdmc\3ds"
    $dspCopy = Join-Path $dspDir "dspfirm.cdc"
    if ($silent) {
        if (Test-Path $dspCopy) {
            if (IsJunction $dspDir) { throw "$dspDir is a junction; it must be the copy's own" }
            Remove-Item -Path $dspCopy -Force
        }
        return
    }
    $dsp = Join-Path $env:APPDATA "Azahar\sdmc\3ds\dspfirm.cdc"
    if (-not (Test-Path $dsp)) { throw "no $dsp to give the copies their sound" }
    New-Item -ItemType Directory -Force -Path $dspDir | Out-Null
    Copy-Item -Path $dsp -Destination $dspCopy -Force
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
    $lines = @("DebugLog 1")
    if ($WirelessOff) { $lines += "WirelessOff 1" }
    if ($NextRace) { $lines += "WirelessTestFinish $Finish" }
    if ($Lose -ge 0 -or $Drop -ge 0) { $lines += "WirelessHoldSeconds $HoldSeconds" }
    if ($Drop -ge 0 -and $name -eq $letters[$Drop]) {
        $lines += "WirelessTestDropFrame $DropFrame"
        $lines += "WirelessTestDropMs $DropMs"
    }
    Set-Content -Path (Join-Path $user "sdmc\nfshp2_config.txt") -Encoding ASCII -Value $lines
    LinkData $user ($NoDsp -or ($SilentClients -and -not $isHost))
    $log = Join-Path $user "sdmc\nfshp2_debug.txt"
    Remove-Item $log -ErrorAction SilentlyContinue
    $azLog = Join-Path $user "log\azahar_log.txt"
    Remove-Item $azLog -ErrorAction SilentlyContinue
    return [pscustomobject]@{
        Name = $name; Nick = $nick; IsHost = $isHost; Exe = $exe; Log = $log;
        AzLog = $azLog; Proc = $null; Hwnd = [IntPtr]::Zero; Joined = $false;
        Steps = $null; Step = 0; Phase = "start"; Mark = 0; Tries = 0;
        Deadline = $null; SettleUntil = $null; Seen = @{}; Failed = $null;
        Done = $false; Shots = 0; Lost = $false
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
    # The menu's items can come late after a busy start: open it again, up
    # to three times, each with 2 s for the item.
    $item = $null
    for ($try = 0; $try -lt 3 -and $null -eq $item; $try++) {
        $w = MainWindow $side
        if ($null -eq $w) { Start-Sleep -Milliseconds 1000; continue }
        $menu = Find $w "name" "Multiplayer"
        if ($null -ne $menu) {
            $menu.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern).Expand()
        }
        $deadline = (Get-Date).AddSeconds(2)
        while ($null -eq $item -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 250
            $item = Find $w "name" "Direct Connect to Room"
        }
    }
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

$cops = if ($CopsOn) { "on" } else { "off" }
$gameType = if ($NextRace) { "4" } else { "\d+" }
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
    # Local Wireless, the fourth row: down past World Racing and Options,
    # each move seen in its brackets (MI_2_MASK, MI_3_MASK, MI_4_MASK).
    Step "to world racing" @{ Key = $VK_DOWN; Pattern = "flow bracket 708a0bf1"; Tries = 2 }
    Step "to options" @{ Key = $VK_DOWN; Pattern = "flow bracket 72df3492"; Tries = 2 }
    Step "to wireless" @{ Key = $VK_DOWN; Pattern = "flow bracket 75345d33"; Tries = 2; Settle = 1000;
                         Shot = "main-menu" }
    Step "lobby" @{ Key = $VK_A; Pattern = "lobby: ask"; Wait = 30; Settle = 1000; Shot = "ask" }
)

# The host's list: "Waiting for players:", a name for each console, and
# the CPU racers' line where there is a choice (37c-2).
function ListFull($side) {
    $l = @(LogLines $side "lobby: list ")
    if ($l.Count -eq 0) { return $false }
    return @(($l[-1] -split "@") | Where-Object { $_ -match "^hp2(host|join\d)$" }).Count -ge $Consoles
}

# The CPU racers the host's last list shows, -1 with no line.
function ListCpu($side) {
    $l = @(LogLines $side "lobby: list ")
    if ($l.Count -eq 0) { return -1 }
    $last = ($l[-1] -split "@")[-1]
    if ($last -match "^hp2(host|join\d)$") { return -1 }
    $m = [regex]::Match($last, "(\d+)$")
    if (-not $m.Success) { return -1 }
    return [int]$m.Groups[1].Value
}

# The count CPU Racers last set, -1 with none.
function LastCpu($side) {
    $l = @(LogLines $side "lobby: cpu \d+")
    if ($l.Count -eq 0) { return -1 }
    return [int]([regex]::Match($l[-1], "cpu (\d+)")).Groups[1].Value
}

# A on CPU Racers counts one more (none again past the room), one press a
# try with a wait past the log's lag, until the count is -Cpu.
$cpuToSet = { param($s) $Cpu -ge 0 -and (ListCpu $s) -ge 0 -and (ListCpu $s) -ne $Cpu }
$cpuMoved = { param($s) $s.Seen["to cpu"] }
$hostSteps = $boot + @(
    # Host asks the mode, Hot Pursuit highlighted; then the Challenge, its
    # select back to the lobby, which hosts.
    Step "host" @{ Key = $VK_A; Pattern = "lobby: mode"; Settle = 1000; Shot = "mode" }
    Step "world racing" @{ Key = $VK_RIGHT; Settle = 1000; When = { -not $CopsOn } }
    Step "mode" @{ Key = $VK_A; Pattern = "lobby: setup, cops $cops" }
    Step "challenge" @{ Pattern = "flow enter Challenge [0-9a-f]{8}"; Wait = 30 }
    Step "challenge up" @{ Pattern = "screen Challenge [0-9a-f]{8} .* last HIGHLIGHT"; Optional = $true; Settle = 1500;
                        Shot = "challenge" }
    # -NextRace: Knockout, right of Single Race on Race Type, the second
    # row; then up to Players, the first, which reads Local Wireless.
    Step "to race type" @{ Key = $VK_DOWN; Pattern = "screen Challenge [0-9a-f]{8} .* item 2 last HIGHLIGHT";
                          Wait = 30; Settle = 1000; When = { $NextRace } }
    Step "knockout" @{ Key = $VK_RIGHT; Settle = 2000; Shot = "knockout"; When = { $NextRace } }
    Step "to players" @{ Key = $VK_UP; Pattern = "screen Challenge [0-9a-f]{8} .* item 1 last HIGHLIGHT";
                        Wait = 30; Settle = 1000; When = { $NextRace } }
    Step "set up" @{ Key = $VK_A; Pattern = "lobby: hosting"; Tries = 2; Settle = 500; Shot = "hosting" }
    Step "all in" @{ Check = { param($s) ListFull $s }; Wait = $RunSeconds; Settle = 1500; Shot = "list" }
    Step "to cpu" @{ Key = $VK_RIGHT; Settle = 1000; When = $cpuToSet }
    Step "cpu" @{ Key = $VK_A; Check = { param($s) (LastCpu $s) -eq $Cpu }; Wait = 10; Tries = 20;
                  Settle = 1500; Shot = "cpu"; When = $cpuMoved }
    Step "to start" @{ Key = $VK_LEFT; Settle = 1000; When = $cpuMoved }
    Step "start" @{ Key = $VK_A; Pattern = "lobby: start, $Consoles consoles" }
    Step "car select" @{ Pattern = "flow enter Select Car [0-9a-f]{8}"; Wait = 30; Settle = 2000; Shot = "carsel" }
)
$joinBase = $boot + @(
    Step "join pick" @{ Key = $VK_RIGHT; Settle = 700 }
    Step "search" @{ Key = $VK_A; Pattern = "lobby: searching"; Settle = 500; Shot = "searching" }
    Step "found" @{ Pattern = "lobby: found 1 of \d+, hp2host"; Wait = 90; Settle = 1000; Shot = "found" }
    Step "join" @{ Key = $VK_A; Pattern = "lobby: joined hp2host"; Settle = 500; Shot = "joined" }
    Step "started" @{ Pattern = "lobby: started by hp2host, place \d+ of $Consoles"; Wait = $RunSeconds }
    Step "the host's mode" @{ Pattern = "lobby: the host's game type $gameType, cops $cops"; Wait = 15 }
    Step "car select" @{ Pattern = "flow enter Select Car [0-9a-f]{8}"; Wait = 30; Settle = 2000; Shot = "carsel" }
)

# -WirelessOff: Host, or Join, says the console's wireless is off; OK
# asks again.
if ($WirelessOff) {
    $offEnd = @(
        Step "ok" @{ Key = $VK_A; Pattern = "lobby: ask"; Settle = 1500; Shot = "ask-again" }
    )
    $hostSteps = $boot + @(
        Step "host off" @{ Key = $VK_A; Pattern = "lobby: wireless communication off"; Settle = 1500;
                          Shot = "off-host" }
    ) + $offEnd
    $joinBase = $boot + @(
        Step "join pick" @{ Key = $VK_RIGHT; Settle = 700 }
        Step "join off" @{ Key = $VK_A; Pattern = "lobby: wireless communication off"; Settle = 1500;
                          Shot = "off-join" }
    ) + $offEnd
}

# -Race: the car (see run_azahar_coprace.ps1), then the host's track and
# each client's wait, the load, GO and the race.
$joinRace = @()
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
    $joinRace = @(
        Step "car sent" @{ Key = $VK_A; Pattern = "netrace: car sent"; Tries = 2; Settle = 1500;
                          Shot = "client-wait" }
        Step "taken" @{ Pattern = "netrace: setup taken"; Wait = $RunSeconds; Settle = 1500; Shot = "loading" }
    ) + $raceEnd
}

# The unlocked cars car select counts ("carsel player p on ...: n cars, u
# unlocked"), 0 before its line.
function Unlocked($side) {
    $l = @(LogLines $side "carsel player \d+ on [0-9a-f]+: \d+ cars, \d+ unlocked")
    if ($l.Count -eq 0) { return 0 }
    return [int]([regex]::Match($l[-1], "(\d+) unlocked")).Groups[1].Value
}

# Copy i's steps: with -Race the first unlocked car (left as far as it
# goes; the list does not wrap), then car (i - 1) mod (u - 1) + 1 of the u
# unlocked, so no two clients share one while there are cars enough, and,
# where i is odd, Manual (right of Automatic on the transmission popup).
# The presses past the count are passed over (a When made as text, so it
# holds k and i).
function JoinSteps([int]$i) {
    $steps = $joinBase
    if (-not $Race) { return $steps }
    $steps += Step "car list" @{ Pattern = "carsel player \d+ on [0-9a-f]+: \d+ cars, \d+ unlocked"; Wait = 30 }
    for ($k = 0; $k -lt 8; $k++) {
        $steps += Step "car home" @{ Key = $VK_LEFT; Settle = 800;
                                     When = [scriptblock]::Create("param(`$s) $k -lt (Unlocked `$s) - 1") }
    }
    for ($k = 0; $k -lt 8; $k++) {
        $steps += Step "car right" @{ Key = $VK_RIGHT; Settle = 1200;
                                      When = [scriptblock]::Create(
                                          "param(`$s) `$u = Unlocked `$s; `$u -gt 1 -and $k -lt (($i - 1) % (`$u - 1)) + 1") }
    }
    $steps += Step "transmission" @{ Key = $VK_A; Settle = 1500 }
    if ($i % 2) { $steps += Step "manual" @{ Key = $VK_RIGHT; Settle = 1000 } }
    $steps += Step "gearbox" @{ Key = $VK_A; Settle = 1500; Shot = "handling" }
    return $steps + $joinRace
}

# -Quit (37f): the host's pause, Quit Race and OK, which every copy takes
# on the same lockstep frame; then each back in the lobby, the host's
# Start once every console is back, and Select Car again. Quit Race is
# the pause menu's MENUITEM_7 (PAUSE_MENU_ITEM_QUIT); the menu loops, so
# down reaches it past whatever is grayed or hidden. The Quit popup opens
# on Cancel, OK to its left: its bloom on BUTTON1 (e0105663) is OK.
function PauseOn($side, [int]$item) {
    $l = @(LogLines $side "flow state .* screen Pause Menu [0-9a-f]{8} .* item -?\d+ ")
    if ($l.Count -eq 0) { return $false }
    return [int]([regex]::Match($l[-1], " item (-?\d+) ")).Groups[1].Value -eq $item
}
$againEnd = @(
    Step "car select again" @{ Pattern = "flow enter Select Car [0-9a-f]{8}"; Wait = 30; Settle = 2000;
                              Shot = "carsel-again" }
)

# The pause (37f-3): copy $PauseBy's pad pauses, and the other of the
# first two (the prober) presses Down, then START, on that pause before
# the pauser moves. Each press reaches every copy on the prober's port,
# the place it races in (the host's 0, B's 1), and the pause's screens,
# given the pauser's port, must not hear it: the first flow state the
# copy logs after the press is still the Pause Menu on Resume Race
# (MENUITEM_1). Copies past B wait for the pause and go on with the rest.
$prober = 1 - $PauseBy
$PAUSE_HASH = "605d2bf1"
$probePresses = "lockstep: frame \d+, port $prober's presses [0-9a-f]+, screen $PAUSE_HASH"
function AfterProbe($side) {
    if (-not (Test-Path $side.Log)) { return $null }
    $p = @(Select-String -Path $side.Log -Pattern $probePresses -ErrorAction SilentlyContinue |
           Select-Object -Last 1)
    if ($p.Count -eq 0) { return $null }
    $f = @(Select-String -Path $side.Log -Pattern "^flow state " -ErrorAction SilentlyContinue |
           Where-Object { $_.LineNumber -gt $p[0].LineNumber } | Select-Object -First 1)
    if ($f.Count -eq 0) { return $null }
    return $f[0].Line
}
$heldOnResume = { param($s) $l = AfterProbe $s; $null -ne $l -and $l -match " screen Pause Menu [0-9a-f]{8} .* item 1 " }
function PauseFirst {
    return @(
        Step "pause" @{ Key = $VK_START; Pattern = "flow enter Pause Menu"; Wait = 12; Settle = 1500; Shot = "pause" }
        Step "probed" @{ Check = { param($s) $sides[$prober].Seen["start held"] }; Wait = 90 }
    )
}
function PauseSeen {
    return @(Step "paused" @{ Pattern = "flow enter Pause Menu"; Wait = 30; Settle = 1500; Shot = "paused" })
}
function Probe {
    return @(
        Step "probe down" @{ Key = $VK_DOWN; Pattern = $probePresses; Wait = 12; Tries = 2; Settle = 1000 }
        Step "down held" @{ Check = $heldOnResume; Wait = 12; Settle = 1000; Shot = "probe-down" }
        Step "probe start" @{ Key = $VK_START; Pattern = $probePresses; Wait = 12; Tries = 2; Settle = 1000 }
        Step "start held" @{ Check = $heldOnResume; Wait = 12; Settle = 1000; Shot = "probe-start" }
    )
}
# The pause's way in for copy $i, then $rest if it is the pauser.
function PauseSteps([int]$i, $rest) {
    if ($i -eq $PauseBy) { return @(PauseFirst) + $rest }
    if ($i -eq $prober) { return @(PauseSeen) + @(Probe) }
    return @(PauseSeen)
}

# -Quit (37f, 37f-3): the pauser's Quit Race and OK, which every copy
# takes on the same lockstep frame; then each back in the lobby, the
# host's Start once every console is back, and Select Car again.
$quitPauser = @(
    Step "to quit" @{ Key = $VK_DOWN; Check = { param($s) PauseOn $s 7 }; Wait = 9; Tries = 8; Settle = 1000;
                     Shot = "pause-quit" }
    Step "quit" @{ Key = $VK_A; Pattern = "flow popup \d+ summon"; Wait = 12; Settle = 1500; Shot = "quit-popup" }
    Step "to ok" @{ Key = $VK_LEFT; Pattern = "flow popup \d+ bloom [0-9a-f]{8} e0105663"; Wait = 12;
                   Settle = 1000; Shot = "quit-ok" }
    Step "quit ok" @{ Key = $VK_A; Pattern = "flow popup \d+ dismiss"; Wait = 12 }
)
$quitHostEnd = @(
    Step "race over" @{ Pattern = "netrace: the race is over"; Wait = 120 }
    Step "back" @{ Pattern = "lobby: back from the race, hosting"; Wait = 120; Settle = 1000; Shot = "back-host" }
    Step "every back" @{ Pattern = "lobby: every console back"; Wait = 120; Settle = 2000; Shot = "back-list" }
    Step "start again" @{ Key = $VK_A; Pattern = "lobby: start, $Consoles consoles"; Tries = 2 }
) + $againEnd
$quitJoinEnd = @(
    Step "race over" @{ Pattern = "netrace: the race is over"; Wait = 120 }
    Step "back" @{ Pattern = "lobby: back from the race, waiting for hp2host"; Wait = 120; Settle = 1000;
                  Shot = "back-join" }
    Step "started again" @{ Pattern = "lobby: started by hp2host, place \d+ of $Consoles"; Wait = 240 }
) + $againEnd
function QuitSteps([int]$i) {
    $end = if ($i -eq 0) { $quitHostEnd } else { $quitJoinEnd }
    return @(PauseSteps $i $quitPauser) + $end
}

# -Restart (37f-2, 37f-3): the pauser's Restart (MENUITEM_2) and OK, which
# every copy takes on the same lockstep frame; the race's start again on
# each (the race's stage, logged each second, below racing), then racing.
$restartAll = @(
    Step "restarted" @{ Pattern = "race: rc \d+, stage [0-3], "; Wait = 60 }
    Step "racing again" @{ Pattern = "race: rc \d+, stage 4, "; Wait = 90; Settle = 3000; Shot = "race-again" }
)
$restartPauser = @(
    Step "to restart" @{ Key = $VK_DOWN; Check = { param($s) PauseOn $s 2 }; Wait = 9; Tries = 8; Settle = 1000;
                        Shot = "pause-restart" }
    Step "restart" @{ Key = $VK_A; Pattern = "flow popup \d+ summon"; Wait = 12; Settle = 1500; Shot = "restart-popup" }
    Step "to ok" @{ Key = $VK_LEFT; Pattern = "flow popup \d+ bloom [0-9a-f]{8} e0105663"; Wait = 12;
                   Settle = 1000; Shot = "restart-ok" }
    Step "restart ok" @{ Key = $VK_A; Pattern = "flow popup \d+ dismiss"; Wait = 12 }
)
function RestartSteps([int]$i) { return @(PauseSteps $i $restartPauser) + $restartAll }

# -NextRace (37f-2): the finish on -Finish's frame, the results, each
# passed with the host's A (every copy on the host's pads), to the End
# Game Menu, Next Race (MENUITEM_1, its first item) and OK, which ends
# lockstep at the save's question. Each copy then answers its own save:
# the question opens on No (BUTTON2, e0105664), as retail's
# DisplayYesNoMessage does, so left to Yes (BUTTON1, e0105663) and A, to
# the copy's own card. Then the event's next race, its hold, GO and
# racing.
function EndMenuOn($side, [int]$item) {
    $l = @(LogLines $side "flow state .* screen End Game Menu [0-9a-f]{8} .* item -?\d+ ")
    if ($l.Count -eq 0) { return $false }
    return [int]([regex]::Match($l[-1], " item (-?\d+) ")).Groups[1].Value -eq $item
}
$nextAll = @(
    Step "autosave" @{ Pattern = "flow enter Autosave"; Wait = 60; Settle = 3000; Shot = "autosave" }
    Step "save ask" @{ Pattern = "flow popup \d+ bloom [0-9a-f]{8} e0105664"; Wait = 30; Settle = 1500;
                      Shot = "save-ask" }
    Step "to yes" @{ Key = $VK_LEFT; Pattern = "flow popup \d+ bloom [0-9a-f]{8} e0105663"; Wait = 12;
                    Settle = 1000; Shot = "save-yes" }
    Step "save yes" @{ Key = $VK_A; Pattern = "memcard: saved"; Wait = 20; Tries = 2 }
    Step "race 2" @{ Pattern = "netrace: race 2 loaded"; Wait = 240 }
    Step "go again" @{ Pattern = "netrace: go, seed"; Wait = 240 }
    Step "racing again" @{ Pattern = "race: rc \d+, stage 4, "; Wait = 180; Settle = 2000; Shot = "race-2" }
)
$finished = Step "finished" @{ Pattern = "lockstep: frame \d+, the test's finish"; Wait = 300 }
$nextHost = @(
    $finished
    Step "results" @{ Pattern = "flow enter (Points Rewards|Race Results|Tourney Standings|Best Lap Times|Best Total Times|End Game Menu)";
                     Wait = 60; Settle = 3000; Shot = "results" }
    Step "to the menu" @{ Key = $VK_A; Pattern = "flow enter End Game Menu"; Wait = 12; Tries = 12; Settle = 2000;
                         Shot = "end-menu" }
    Step "on next race" @{ Check = { param($s) EndMenuOn $s 1 }; Wait = 15 }
    Step "next race" @{ Key = $VK_A; Pattern = "flow popup \d+ summon"; Wait = 12; Settle = 1500; Shot = "next-popup" }
    Step "to ok" @{ Key = $VK_LEFT; Pattern = "flow popup \d+ bloom [0-9a-f]{8} e0105663"; Wait = 12;
                   Settle = 1000; Shot = "next-ok" }
    Step "next ok" @{ Key = $VK_A; Pattern = "flow popup \d+ dismiss"; Wait = 12 }
) + $nextAll
$nextJoin = @($finished) + $nextAll

$start = Get-Date
function Elapsed { ((Get-Date) - $start).TotalSeconds }
function NoneFailed { @($sides | Where-Object { $_.Failed }).Count -eq 0 }
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
                if ($step.Name -match "^(lobby|host|mode|challenge|set up|the host's mode|search|found|join|started|car select|all in|start|track select|host start|built|car sent|taken|go|racing|race on|host off|join off|ok|pause|paused|probed|probe down|down held|probe start|start held|to quit|quit|to ok|quit ok|race over|back|every back|start again|started again|car select again|to race type|to players|to restart|restart|restart ok|restarted|racing again|finished|results|to the menu|on next race|next race|next ok|autosave|save ask|to yes|save yes|race 2|go again)$") {
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
    $s.Steps = if ($i -eq 0) { $hostSteps } else { JoinSteps $i }
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

# The gas on every copy at once for -Drive seconds (or $seconds), a shot
# of each every 10 s (or $every) named for the tag.
function DriveAll([string]$tag, [int]$seconds = 0, [int]$every = 10) {
    if ($seconds -le 0) { $seconds = $Drive }
    Write-Host ("  [{0,5:N0}s] driving: A held on every copy for {1} s" -f (Elapsed), $seconds)
    $driveStart = Get-Date
    $driveEnd = $driveStart.AddSeconds($seconds)
    $nextShot = (Get-Date).AddSeconds($every)
    $n = 0
    while ((Get-Date) -lt $driveEnd) {
        foreach ($s in $sides) { if (Alive $s) { [Hp2Lb]::KeyDown($s.Hwnd, $VK_A) } }
        # -Steer: copy k by turns straight, left, straight, right, each
        # for 2 + k seconds.
        if ($Steer) {
            $t = ((Get-Date) - $driveStart).TotalSeconds
            for ($k = 0; $k -lt $sides.Count; $k++) {
                $s = $sides[$k]
                if (-not (Alive $s)) { continue }
                $phase = [int][math]::Floor($t / (2 + $k)) % 4
                if ($phase -eq 1) {
                    [Hp2Lb]::KeyUp($s.Hwnd, $VK_RIGHT); [Hp2Lb]::KeyDown($s.Hwnd, $VK_LEFT)
                } elseif ($phase -eq 3) {
                    [Hp2Lb]::KeyUp($s.Hwnd, $VK_LEFT); [Hp2Lb]::KeyDown($s.Hwnd, $VK_RIGHT)
                } else {
                    [Hp2Lb]::KeyUp($s.Hwnd, $VK_LEFT); [Hp2Lb]::KeyUp($s.Hwnd, $VK_RIGHT)
                }
            }
        }
        if ((Get-Date) -ge $nextShot) {
            $n++
            foreach ($s in $sides) { if (-not $s.Lost) { Shot $s "$tag-$n" } }
            $nextShot = $nextShot.AddSeconds($every)
        }
        Start-Sleep -Milliseconds 150
    }
    foreach ($s in $sides) {
        if (Alive $s) {
            [Hp2Lb]::KeyUp($s.Hwnd, $VK_A)
            [Hp2Lb]::KeyUp($s.Hwnd, $VK_LEFT); [Hp2Lb]::KeyUp($s.Hwnd, $VK_RIGHT)
        }
    }
    foreach ($s in $sides) {
        if (-not $s.Lost -and -not (Alive $s) -and -not $s.Failed) { $s.Failed = "Azahar exited while driving" }
    }
}

# Every copy on to its next steps (the host's or a client's), each on its
# own clock, for up to $seconds.
function WalkPhase($hostPhase, $joinPhase, [int]$seconds, [string]$tag) {
    WalkEach ({ param($i) if ($i -eq 0) { $hostPhase } else { $joinPhase } }.GetNewClosure()) $seconds $tag
}

# The same, copy i's steps from $phaseOf.
function WalkEach([scriptblock]$phaseOf, [int]$seconds, [string]$tag) {
    for ($i = 0; $i -lt $sides.Count; $i++) {
        $s = $sides[$i]
        $s.Steps = @(& $phaseOf $i)
        $s.Step = 0; $s.Phase = "start"; $s.Done = $false
        $s.Mark = LogLength $s
    }
    $end = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $end) {
        foreach ($s in $sides) { Advance $s }
        if (@($sides | Where-Object { -not $_.Done -and -not $_.Failed }).Count -eq 0) { break }
        Start-Sleep -Milliseconds 250
    }
    foreach ($s in $sides) {
        if (-not $s.Done -and -not $s.Failed) {
            $s.Failed = "out of time on '$($s.Steps[$s.Step].Name)'"
            Shot $s "timeout-$tag"
        }
    }
}

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
    # -Race: the gas on every copy at once, the race in lockstep.
    if ($Race -and $Drive -gt 0 -and (NoneFailed)) { DriveAll "drive" }
    # -Lose (37g-1): a copy closed mid-race, the rest driving on through
    # the hold and past it.
    if ($Lose -ge 0 -and (NoneFailed)) {
        $lostSide = $sides[$Lose]
        Write-Host ("  [{0,5:N0}s] closing {1} mid-race, the hold {2} s" -f (Elapsed), $lostSide.Name, $HoldSeconds)
        [Hp2Lb]::KeyUp($lostSide.Hwnd, $VK_A)
        $lostSide.Lost = $true
        $lostSide.Proc | Stop-Process -Force
        DriveAll "held" ($HoldSeconds + 25) 2
    }
    # -Drop (37g-2): a copy deaf mid-race, every copy driving on through
    # the hold, the rejoin and past it.
    if ($Drop -ge 0 -and (NoneFailed)) {
        Write-Host ("  [{0,5:N0}s] driving on: {1} deaf from frame {2} for {3} ms, the hold {4} s" -f (Elapsed), $sides[$Drop].Name, $DropFrame, $DropMs, $HoldSeconds)
        DriveAll "dropped" ($HoldSeconds + 30) 3
    }
    # -Quit: the pauser's pause and Quit, every copy back to the lobby and
    # on to Select Car again, each on its own clock as before.
    $pauser = $sides[$PauseBy].Name
    if ($Quit -and (NoneFailed)) {
        Write-Host ("  [{0,5:N0}s] quitting: {1}'s pause, the other's presses, Quit Race, OK" -f (Elapsed), $pauser)
        WalkEach { param($i) QuitSteps $i } 420 "quit"
    }
    # -Restart (37f-2): the pauser's pause and Restart, the race again on
    # every copy in lockstep, and the gas again.
    if ($Restart -and (NoneFailed)) {
        Write-Host ("  [{0,5:N0}s] restarting: {1}'s pause, the other's presses, Restart, OK" -f (Elapsed), $pauser)
        WalkEach { param($i) RestartSteps $i } 300 "restart"
        if ($Drive -gt 0 -and (NoneFailed)) { DriveAll "drive2" }
    }
    # -NextRace (37f-2): the finish, the results, Next Race, each copy's
    # save, the event's next race in lockstep, and the gas again.
    if ($NextRace -and (NoneFailed)) {
        Write-Host ("  [{0,5:N0}s] to the finish on frame {1}, the results and Next Race" -f (Elapsed), $Finish)
        WalkPhase $nextHost $nextJoin 600 "next"
        if ($Drive -gt 0 -and (NoneFailed)) { DriveAll "drive2" }
    }
    # The log's last lines land up to ~7 s late.
    Start-Sleep -Seconds 8
} finally {
    foreach ($s in $sides) {
        if ($s.Proc -and -not $s.Lost -and (Alive $s)) { $s.Proc | Stop-Process -Force }
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
    $silent = @(LogLines $s "^Sound: ndsp unavailable").Count -gt 0
    if ($NoDsp -or ($SilentClients -and $s -ne $sides[0])) {
        if (-not $silent -and -not $s.Failed) { $s.Failed = "sound up on a silent card" }
    } elseif ($silent -and -not $s.Failed) {
        $s.Failed = "no sound: ndsp unavailable"
    }
    if ($WirelessOff -and @(LogLines $s "^wireless: up").Count -gt 0 -and -not $s.Failed) {
        $s.Failed = "UDS started with the wireless off"
    }
    if (Test-Path $s.AzLog) {
        $crash = @(Select-String -Path $s.AzLog -Pattern $crashSigs | Select-Object -First 3)
        foreach ($c in $crash) {
            Write-Host "  azahar: $($c.Line)"
            if (-not $s.Failed) { $s.Failed = "Azahar: $($c.Line)" }
        }
    }
}
# -Race: every copy's GO on the host's seed (with -NextRace, each race's).
$races = if ($NextRace) { 2 } else { 1 }
if ($Race) {
    $hostSeeds = $null
    foreach ($s in $sides) {
        $go = @(LogLines $s "netrace: go, seed ([0-9a-f]{8})")
        if ($go.Count -ne $races) {
            if (-not $s.Failed) { $s.Failed = "$($go.Count) GO lines" }
            continue
        }
        $seeds = @($go | ForEach-Object { ([regex]::Match($_, "seed ([0-9a-f]{8})")).Groups[1].Value })
        if ($null -eq $hostSeeds) { $hostSeeds = $seeds; continue }
        for ($k = 0; $k -lt $races; $k++) {
            if ($seeds[$k] -ne $hostSeeds[$k] -and -not $s.Failed) {
                $s.Failed = "GO $($k + 1) on $($seeds[$k]), the host's $($hostSeeds[$k])"
            }
        }
    }
    $hostSeed = if ($hostSeeds) { $hostSeeds -join ", " } else { $null }

    # The CPU racers the host started with, and as many more drivers.
    $h = $sides[0]
    $cpuRun = 0
    $st = @(LogLines $h "lobby: start, \d+ consoles")
    if ($st.Count -gt 0) {
        $m = [regex]::Match($st[-1], ", (\d+) CPU racers")
        if ($m.Success) { $cpuRun = [int]$m.Groups[1].Value }
    }
    if ($h.Seen["to cpu"] -and $cpuRun -ne $Cpu -and -not $h.Failed) {
        $h.Failed = "started with $cpuRun CPU racers, not $Cpu"
    }
    # The racers: the players and AI of race start's line (with -CopsOn the
    # drivers also count the cops and traffic).
    $built = @(LogLines $h "netrace: built, track \d+, \d+ drivers")
    $start = @(LogLines $h "race start: .* \d+ player, \d+ AI")
    if ($built.Count -eq 1 -and $start.Count -ge 1) {
        $n = [int]([regex]::Match($built[0], ", (\d+) drivers")).Groups[1].Value
        # The first race's: a knockout's next has one fewer.
        $m = [regex]::Match($start[0], " (\d+) player, (\d+) AI")
        $racers = [int]$m.Groups[1].Value + [int]$m.Groups[2].Value
        Write-Host "Host: $cpuRun CPU racers, $racers racers, $n drivers"
        if ($racers -ne $Consoles + $cpuRun -and -not $h.Failed) {
            $h.Failed = "$racers racers for $Consoles consoles and $cpuRun CPU racers"
        }
    }

    # The lockstep (37d): started and flowing on every copy.
    foreach ($s in $sides) {
        Write-Host "--- $($s.Name) netstep ---"
        $ns = @(LogLines $s "netstep: |clocks at GO")
        $ns | Select-Object -First 24 | ForEach-Object { Write-Host "  $_" }
        if ($ns.Count -gt 24) { Write-Host "  ... $($ns.Count - 24) more" }
        $differ = @($ns | Where-Object { $_ -match "differs from place" }).Count
        if ($differ -gt 0) { Write-Host "  $differ checksum differences" }
        if (@($ns | Where-Object { $_ -match "netstep: start, place" }).Count -ne $races -and -not $s.Failed) {
            $s.Failed = "not $races lockstep starts"
        } elseif ($Drive -gt 0 -and @($ns | Where-Object { $_ -match "netstep: frames flow" }).Count -eq 0 -and -not $s.Failed) {
            $s.Failed = "lockstep frames never flowed"
        }
    }

    # 37e: every copy's parts, frame by frame, against the host's: the
    # logged ones every 150 frames and the window's at a difference. Each
    # is keyed race/frame, the race counted by the lockstep's starts.
    $partNames = @("time", "seeds", "players", "racers", "cops", "traffic", "race")
    function Parts($side) {
        $m = @{}
        $race = 0
        foreach ($l in (LogLines $side "netstep: start, place|lockhash: (frame|parts) \d+ ")) {
            if ($l -match "netstep: start, place") { $race++; continue }
            $x = [regex]::Match($l, "lockhash: (?:frame|parts) (\d+) time (\w+) seeds (\w+) players (\w+) racers (\w+) cops (\w+) traffic (\w+) race (\w+)")
            if ($x.Success) {
                $m["$race/$([int]$x.Groups[1].Value)"] = @(2..8 | ForEach-Object { $x.Groups[$_].Value })
            }
        }
        return $m
    }
    function Draws($side, [int]$f) {
        return @(LogLines $side "lockhash: (draws|at) $($f):")
    }
    # The window's cars: "race/frame" to the clocks and a word for each
    # slot, and "race/frame/slot" to that car's pieces at the frame.
    $pieceNames = @("modes", "place", "motion", "body", "spin", "wheelmats", "wheels", "drive", "rel", "driver")
    function Cars($side) {
        $m = @{}
        $race = 0
        foreach ($l in (LogLines $side "netstep: start, place|lockhash: (cars|fields) \d+ ")) {
            if ($l -match "netstep: start, place") { $race++; continue }
            $x = [regex]::Match($l, "lockhash: cars (\d+) timer (\w+) loop (\w+):((?: \w+)+)")
            if ($x.Success) {
                $m["$race/$([int]$x.Groups[1].Value)"] = @{
                    Clock = "timer $($x.Groups[2].Value) loop $($x.Groups[3].Value)"
                    Slots = @($x.Groups[4].Value.Trim() -split " ")
                }
                continue
            }
            $x = [regex]::Match($l, "lockhash: fields (\d+) (\d+):((?: \w+)+)")
            if ($x.Success) {
                $m["$race/$([int]$x.Groups[1].Value)/$([int]$x.Groups[2].Value)"] = @($x.Groups[3].Value.Trim() -split " ")
            }
        }
        return $m
    }
    function CarsDiffer($hc, $mc, $f, $name) {
        if (-not $hc.ContainsKey($f) -or -not $mc.ContainsKey($f)) {
            Write-Host "  no cars line at $f on both"
            return
        }
        if ($hc[$f].Clock -ne $mc[$f].Clock) {
            Write-Host "  clocks: host's $($hc[$f].Clock), $($name)'s $($mc[$f].Clock)"
        }
        for ($k = 0; $k -lt $hc[$f].Slots.Count; $k++) {
            if ($hc[$f].Slots[$k] -eq $mc[$f].Slots[$k]) { continue }
            $hp = $hc["$f/$k"]; $mp = $mc["$f/$k"]
            if ($null -eq $hp -or $null -eq $mp) {
                Write-Host "  slot $($k): differs (pieces on one side only)"
                continue
            }
            $bad = @()
            for ($j = 0; $j -lt $pieceNames.Count; $j++) {
                if ($hp[$j] -ne $mp[$j]) { $bad += $pieceNames[$j] }
            }
            Write-Host "  slot $($k): differs in $($bad -join ', ')"
            # The window's words fold the driver too: the first frame
            # the slot's word differs is where it went.
            $rf = $f -split "/"
            for ($g = [int]$rf[1] - 15; $g -le [int]$rf[1]; $g++) {
                $wk = "$($rf[0])/$g"
                if (-not $hc.ContainsKey($wk) -or -not $mc.ContainsKey($wk)) { continue }
                if ($hc[$wk].Slots[$k] -ne $mc[$wk].Slots[$k]) {
                    Write-Host "  slot $($k): its word first differs at frame $g"
                    break
                }
            }
        }
    }
    $hostParts = Parts $h
    Write-Host "Host: parts of $($hostParts.Count) frames"
    for ($i = 1; $i -lt $sides.Count; $i++) {
        $s = $sides[$i]
        $mine = Parts $s
        $same = 0
        $first = $null
        foreach ($f in ($mine.Keys | Sort-Object { [int]($_ -split "/")[0] }, { [int]($_ -split "/")[1] })) {
            if (-not $hostParts.ContainsKey($f)) { continue }
            $bad = @()
            for ($k = 0; $k -lt 7; $k++) {
                if ($mine[$f][$k] -ne $hostParts[$f][$k]) { $bad += $partNames[$k] }
            }
            if ($bad.Count -eq 0) { $same++; continue }
            $first = $f
            Write-Host "$($s.Name): race/frame $f differs from the host's in $($bad -join ', ') ($same frames the same before)"
            Write-Host "  host: $($hostParts[$f] -join ' ')"
            Write-Host "  $($s.Name):    $($mine[$f] -join ' ')"
            Write-Host "  host's draws:"
            Draws $h ([int]($f -split "/")[1]) | ForEach-Object { Write-Host "    $_" }
            Write-Host "  $($s.Name)'s draws:"
            Draws $s ([int]($f -split "/")[1]) | ForEach-Object { Write-Host "    $_" }
            CarsDiffer (Cars $h) (Cars $s) $f $s.Name
            if (-not $s.Failed) { $s.Failed = "race/frame $f differs in $($bad -join ', ')" }
            break
        }
        if ($null -eq $first) { Write-Host "$($s.Name): $same frames' parts the same as the host's" }
        if ($Drive -gt 0 -and $same -eq 0 -and $null -eq $first -and -not $s.Failed) {
            $s.Failed = "no parts compared with the host's"
        }
    }

    # Each copy's car and transmission, the clients' as the host got them.
    $hs = @(LogLines $h "netrace: the host's start, type \d+ skin \d+, transmission \d+")
    $hostType = $null
    if ($hs.Count -gt 0) {
        $m = [regex]::Match($hs[-1], "type (\d+) skin (\d+), transmission (\d+)")
        $hostType = $m.Groups[1].Value
        Write-Host "Host's car: type $hostType skin $($m.Groups[2].Value), transmission $($m.Groups[3].Value)"
    }
    for ($i = 1; $i -lt $sides.Count; $i++) {
        $s = $sides[$i]
        $sent = @(LogLines $s "netrace: car sent, type \d+ skin \d+, transmission \d+")
        if ($sent.Count -eq 0) { continue }
        $m = [regex]::Match($sent[-1], "type (\d+) skin (\d+), transmission (\d+)")
        $type = $m.Groups[1].Value; $skin = $m.Groups[2].Value; $gear = [int]$m.Groups[3].Value
        Write-Host "$($s.Name)'s car: type $type skin $skin, transmission $gear"
        if ($gear -ne ($i % 2) -and -not $s.Failed) { $s.Failed = "transmission $gear, not $($i % 2)" }
        $got = @(LogLines $h "netrace: place \d+'s car, type $type skin $skin, transmission $gear")
        if ($got.Count -eq 0 -and -not $h.Failed) { $h.Failed = "$($s.Name)'s car not as sent" }
        if ($type -eq $hostType) { Write-Host "  (the same car as the host's)" }
    }

    # -Lose (37g-1): the lost copy held for, then gone, and its car the
    # CPU's on every copy left: a client's on one lockstep frame, the
    # host's on each client alone.
    if ($Lose -ge 0) {
        $lostSide = $sides[$Lose]
        $handFrame = $null
        foreach ($s in $sides) {
            if ($s.Lost) { continue }
            Write-Host "--- $($s.Name) the hold ---"
            LogLines $s "netstep: (place \d+ (lost|is gone|was gone)|the host (lost|is gone))|lockstep: frame \d+, (places|place \d+'s car|the pause)" |
                ForEach-Object { Write-Host "  $_" }
            $saysLost = if ($Lose -eq 0) { "netstep: the host lost at frame \d+; held for $($HoldSeconds * 1000) ms" }
                        elseif ($s.IsHost) { "netstep: place $Lose lost at frame \d+; held for $($HoldSeconds * 1000) ms" }
                        else { $null }
            $saysGone = if ($Lose -eq 0) { "netstep: the host is gone, from frame \d+; racing alone" }
                        elseif ($s.IsHost) { "netstep: place $Lose is gone, from frame \d+; its car to the CPU" }
                        else { $null }
            foreach ($say in @($saysLost, $saysGone)) {
                if ($null -eq $say) { continue }
                $n = @(LogLines $s $say).Count
                if ($n -ne 1 -and -not $s.Failed) { $s.Failed = "'$say' $n times" }
            }
            $hand = @(LogLines $s "lockstep: frame \d+, place $Lose's car \(driver \d+\) to the CPU")
            if ($hand.Count -ne 1) {
                if (-not $s.Failed) { $s.Failed = "$($lostSide.Name)'s car to the CPU $($hand.Count) times" }
                continue
            }
            $f = [int]([regex]::Match($hand[0], "frame (\d+)")).Groups[1].Value
            if ($Lose -eq 0) { continue }
            if ($null -eq $handFrame) { $handFrame = $f }
            elseif ($f -ne $handFrame -and -not $s.Failed) {
                $s.Failed = "$($lostSide.Name)'s car to the CPU on frame $f, the first copy's on $handFrame"
            }
        }
    }

    # -Drop (37g-2): the dropped copy's links lost at both ends, then
    # re-peered and back, on each; no place gone, no car the CPU's.
    if ($Drop -ge 0) {
        $dropSide = $sides[$Drop]
        $hold = $HoldSeconds * 1000
        foreach ($s in $sides) {
            Write-Host "--- $($s.Name) the drop ---"
            LogLines $s "netstep: (place \d+ (lost|back|is gone)|the host (lost|back|is gone))|wireless: (deaf|hears again|looking for|back on|node \d+ .*(back in place|sent away|timed out|left|never heard)|the host|open to|closed to|udsConnectNetwork|udsScanBeacons)|lockstep: frame \d+, (places|place \d+'s car|deaf)" |
                ForEach-Object { Write-Host "  $_" }
            $says = @()
            if ($s -eq $dropSide) { $says += "wireless: deaf for $DropMs ms" }
            if ($Drop -eq 0 -and -not $s.IsHost) {
                $says += "netstep: the host lost at frame \d+; held for $hold ms"
                $says += "wireless: back on "".*""'s network"
                $says += "netstep: the host back at frame \d+, after \d+ ms"
            } elseif ($Drop -gt 0 -and $s -eq $dropSide) {
                $says += "netstep: the host lost at frame \d+; held for $hold ms"
                $says += "wireless: back on "".*""'s network"
                $says += "netstep: the host back at frame \d+, after \d+ ms"
            }
            if ($s.IsHost) {
                $places = if ($Drop -eq 0) { 1..($Consoles - 1) } else { @($Drop) }
                foreach ($pl in $places) {
                    $says += "netstep: place $pl lost at frame \d+; held for $hold ms"
                    $says += "netstep: place $pl back at frame \d+, after \d+ ms"
                }
                $n = @(LogLines $s "wireless: node \d+ \(.*\) back in place \d+").Count
                if ($n -ne $places.Count -and -not $s.Failed) { $s.Failed = "$n nodes back in place, not $($places.Count)" }
            }
            foreach ($say in $says) {
                $n = @(LogLines $s $say).Count
                if ($n -ne 1 -and -not $s.Failed) { $s.Failed = "'$say' $n times" }
            }
            foreach ($bad in @("netstep: place \d+ is gone", "netstep: the host is gone", "lockstep: frame \d+, place \d+'s car")) {
                $n = @(LogLines $s $bad).Count
                if ($n -ne 0 -and -not $s.Failed) { $s.Failed = "'$bad' $n times" }
            }
        }
    }

    # -Quit (37f) and -NextRace (37f-2): every copy's lockstep stopped once,
    # on the host's frame, and the host heard every client's stop.
    if ($Quit -or $NextRace) {
        $hostStop = $null
        foreach ($s in $sides) {
            Write-Host "--- $($s.Name) the race's end ---"
            LogLines $s "netstep: (stop at|every client|place \d+ (stopped|never|left|is gone|has gone)|the host (stopped|is gone))|netrace: the race is over|lobby: (back|every console|started by|start, |\S+ is back)|flow enter (Pause Menu|Select Car)" |
                ForEach-Object { Write-Host "  $_" }
            $stops = @(LogLines $s "netstep: stop at frame \d+")
            if ($stops.Count -ne 1) {
                if (-not $s.Failed) { $s.Failed = "$($stops.Count) lockstep stops" }
                continue
            }
            $f = [int]([regex]::Match($stops[0], "frame (\d+)")).Groups[1].Value
            if ($null -eq $hostStop) { $hostStop = $f }
            elseif ($f -ne $hostStop -and -not $s.Failed) {
                $s.Failed = "lockstep stopped at frame $f, the host at $hostStop"
            }
        }
        if (@(LogLines $h "netstep: every client stopped").Count -eq 0 -and -not $h.Failed) {
            $h.Failed = "no word of every client's stop"
        }
    }
    # -NextRace: every copy finished on the same frame, and loaded the
    # event's next race.
    if ($NextRace) {
        $hostFinish = $null
        foreach ($s in $sides) {
            Write-Host "--- $($s.Name) the next race ---"
            LogLines $s "lockstep: frame \d+, the test's finish|flow enter (Points Rewards|Race Results|Tourney Standings|Best Lap Times|Best Total Times|End Game Menu|Autosave)|memcard: saved|netrace: (race \d+ loaded|loaded, holding|place \d+ loaded|go, seed)" |
                ForEach-Object { Write-Host "  $_" }
            $fin = @(LogLines $s "lockstep: frame \d+, the test's finish")
            if ($fin.Count -ne 1) {
                if (-not $s.Failed) { $s.Failed = "$($fin.Count) finishes" }
                continue
            }
            $f = [int]([regex]::Match($fin[0], "frame (\d+)")).Groups[1].Value
            if ($null -eq $hostFinish) { $hostFinish = $f }
            elseif ($f -ne $hostFinish -and -not $s.Failed) {
                $s.Failed = "finished on frame $f, the host on $hostFinish"
            }
        }
    }
    # -Restart: the lockstep never stopped.
    if ($Restart) {
        foreach ($s in $sides) {
            $stops = @(LogLines $s "netstep: stop at frame \d+")
            if ($stops.Count -ne 0 -and -not $s.Failed) { $s.Failed = "lockstep stopped on the restart" }
        }
    }
    # -Quit, -Restart (37f-3): every copy paused once, on the pauser's
    # port and the host's frame, and ran the prober's presses on the pause
    # on the host's frames (each held on Resume Race, checked as it went).
    if ($Quit -or $Restart) {
        $hostPause = $null
        $hostProbe = $null
        foreach ($s in $sides) {
            Write-Host "--- $($s.Name) the pause ---"
            LogLines $s "^pause: port|$probePresses" | ForEach-Object { Write-Host "  $_" }
            $p = @(LogLines $s "^pause: port \d+, frame \d+")
            if ($p.Count -ne 1) {
                if (-not $s.Failed) { $s.Failed = "$($p.Count) pauses" }
                continue
            }
            $m = [regex]::Match($p[0], "port (\d+), frame (\d+)")
            if ([int]$m.Groups[1].Value -ne $PauseBy -and -not $s.Failed) {
                $s.Failed = "paused on port $($m.Groups[1].Value), not $PauseBy"
            }
            $f = [int]$m.Groups[2].Value
            if ($null -eq $hostPause) { $hostPause = $f }
            elseif ($f -ne $hostPause -and -not $s.Failed) {
                $s.Failed = "paused on frame $f, the host on $hostPause"
            }
            $probes = @(LogLines $s $probePresses |
                        ForEach-Object { [regex]::Match($_, "frame (\d+)").Groups[1].Value }) -join ","
            if ($probes -eq "") {
                if (-not $s.Failed) { $s.Failed = "no presses of port $prober's on the pause" }
            } elseif ($null -eq $hostProbe) {
                $hostProbe = $probes
            } elseif ($probes -ne $hostProbe -and -not $s.Failed) {
                $s.Failed = "port $prober's presses on frames $probes, the host's on $hostProbe"
            }
        }
    }
}
Write-Host ""
$failed = @($sides | Where-Object { -not $_.Done -or $_.Failed })
$goal = if ($WirelessOff) { "the wireless-off line, then the question" }
        elseif ($Quit) { "racing, quit, back in the lobby, Select Car again" }
        elseif ($Restart) { "racing, restarted in lockstep, racing again" }
        elseif ($NextRace) { "racing, the results, Next Race, racing again in lockstep" }
        elseif ($Lose -ge 0) { "racing, a copy closed, held for, its car the CPU's" }
        elseif ($Drop -ge 0) { "racing, a copy deaf, held for, back in lockstep" }
        elseif ($Race) { "racing" } else { "Select Car" }
foreach ($s in $sides) {
    $g = if ($s.Lost) { "racing, then closed" } else { $goal }
    $v = if ($s.Done -and -not $s.Failed) { "PASS ($g)" } else { "FAIL ($($s.Failed))" }
    Write-Host ("{0} {1,-9} {2}" -f $s.Name, $s.Nick, $v)
}
Write-Host "Screenshots in $OutDir"
if ($failed.Count -eq 0) {
    if ($WirelessOff) { Write-Host "All $Consoles said the wireless is off, and asked again." }
    elseif ($Quit) { Write-Host "All $Consoles raced on seed $hostSeed, paused by $pauser on frame $hostPause (port $prober's presses on $hostProbe not heard), quit on frame $hostStop, back in the lobby and on to Select Car again." }
    elseif ($Restart) { Write-Host "All $Consoles raced on seed $hostSeed, paused by $pauser on frame $hostPause (port $prober's presses on $hostProbe not heard), restarted in lockstep and raced again." }
    elseif ($NextRace) { Write-Host "All $Consoles finished on frame $hostFinish, stopped on $hostStop, and raced the next on seeds $hostSeed." }
    elseif ($Lose -gt 0) { Write-Host "All $Consoles raced on seed $hostSeed; $($sides[$Lose].Name) closed, held for $HoldSeconds s, its car the CPU's on frame $handFrame on every copy left." }
    elseif ($Lose -ge 0) { Write-Host "All $Consoles raced on seed $hostSeed; the host closed, held for $HoldSeconds s, then every client raced alone, its car the CPU's." }
    elseif ($Drop -ge 0) { Write-Host "All $Consoles raced on seed $hostSeed; $($sides[$Drop].Name) deaf from frame $DropFrame for $DropMs ms, held for, found its host again and raced on in lockstep." }
    elseif ($Race) { Write-Host "All $Consoles racing from the lobby, GO on seed $hostSeed." }
    else { Write-Host "All $Consoles reached Select Car from the lobby." }
} else {
    exit 1
}
