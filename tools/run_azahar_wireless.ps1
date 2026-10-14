# Runs TASKS 37a's link soak (wirelesstest.h) between 2 to 8 Azahar
# instances in a room of their own, and reports what each one's log says.
#
# Azahar carries a game's local wireless over a multiplayer room, so this
# starts azahar-room.exe on this machine and -Consoles copies of Azahar, A
# to H, each in portable mode (a user folder beside its azahar.exe) so each
# has its own card and its own console ID: a room refuses a second member
# with the ID of one already in it, and the user's own Azahar folder is not
# touched. Each copy's config is the user's qt-config.ini with the room's
# address in it, and each card's nfshp2_config.txt says "WirelessTest 1"
# (A hosts) or "2" (the rest join), "WirelessTestConsoles" and "DebugLog
# 1". All boot the .3dsx, then each joins the room through Multiplayer >
# Direct Connect to Room, driven with UI Automation; the soak retries its
# hosting and its scans every 2 s, so it waits on the room.
#
# Usage:
#   powershell -File tools/run_azahar_wireless.ps1
#   powershell -File tools/run_azahar_wireless.ps1 -Seconds 300
#   powershell -File tools/run_azahar_wireless.ps1 -Consoles 8
#
# The copies live under %TEMP%\nfshp2_wl and are made again when the
# installed azahar.exe is newer. Exit code 0 when every one passed.

param(
    [int]$Seconds = 60,           # WirelessTestSeconds: how long each sends
    [ValidateRange(2, 8)]
    [int]$Consoles = 2,           # WirelessTestConsoles: the host and the rest
    [int]$RunSeconds = 0,         # hard ceiling; 0 is -Seconds + 60 + 20 a console
    [string]$AzaharDir = "C:\Program Files\Azahar",
    [string]$Target3dsx = "",
    [string]$WorkDir = "",
    [int]$Port = 24872
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($WorkDir -eq "") { $WorkDir = Join-Path $env:TEMP "nfshp2_wl" }
# The copies join the room one at a time; with 8 the last joins ~80 s in.
if ($RunSeconds -le 0) { $RunSeconds = $Seconds + 60 + 20 * $Consoles }
$azahar = Join-Path $AzaharDir "azahar.exe"
$roomExe = Join-Path $AzaharDir "azahar-room.exe"
foreach ($f in @($azahar, $roomExe, $Target3dsx)) {
    if (-not (Test-Path $f)) { throw "not found: $f" }
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
public class Hp2Wl {
    [DllImport("user32.dll")] public static extern IntPtr PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    public const uint WM_CLOSE = 0x0010;

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
}
"@ -ErrorAction SilentlyContinue
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

# The config savegame's blocks (3dbrew's Config Savegame): a u16 count,
# then 12 bytes each, u32 ID, u32 offset, u16 size, u16 flags. The user
# name's 0x1C bytes are ten UTF-16 characters and two u32s.
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

# One portable copy: the install, a config with the room in it, and a card
# with the soak's keys.
function Prepare([string]$name, [string]$nick, [int]$mode) {
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
    # A room's nickname is the console's own user name, which the Direct
    # Connect dialog will not change, and every copy starts as "AZAHAR";
    # the room takes one member of a name. The name is block 0x000A0000 of
    # the config savegame, which Azahar makes on its first start.
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
    Set-Content -Path (Join-Path $user "sdmc\nfshp2_config.txt") -Encoding ASCII `
        -Value @("DebugLog 1", "WirelessTest $mode", "WirelessTestSeconds $Seconds",
                 "WirelessTestConsoles $Consoles")
    $log = Join-Path $user "sdmc\nfshp2_debug.txt"
    Remove-Item $log -ErrorAction SilentlyContinue
    return [pscustomobject]@{ Name = $name; Nick = $nick; Exe = $exe; Log = $log;
                              Proc = $null; Joined = $false; Result = $null }
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
    Start-Sleep -Seconds 1
    $closed = [Hp2Wl]::DismissPopups([uint32]$side.Proc.Id, $side.Proc.MainWindowHandle)
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

# The status bar's room label, "Not Connected. ..." until a room takes it.
function RoomLabel($side) {
    $w = MainWindow $side
    if ($null -eq $w) { return "" }
    $l = Find $w "id" "QApplication.MainWindow.QStatusBar.ClickableLabel"
    if ($null -eq $l) { return "" }
    return $l.Current.Name
}

function Join($side) {
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
    # The nickname field is read-only: it shows the console's name.
    $fields = @{ "ip_container.ip" = "127.0.0.1"; "ip_container.port" = "$Port" }
    foreach ($k in $fields.Keys) {
        $e = Find $dlg "id" "QApplication.DirectConnect.$k"
        $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($fields[$k])
    }
    $nickField = Find $dlg "id" "QApplication.DirectConnect.nickname"
    $shown = $nickField.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
    if ($shown -ne $side.Nick) { Write-Host "  $($side.Name): the dialog's nickname is '$shown'" }
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
    return @(Select-String -Path $side.Log -Pattern $pattern | ForEach-Object { $_.Line })
}

$letters = "ABCDEFGH"
Write-Host "Preparing $Consoles copies"
$sides = @()
for ($i = 0; $i -lt $Consoles; $i++) {
    $nick = if ($i -eq 0) { "hp2host" } else { "hp2join$i" }
    $sides += Prepare $letters[$i] $nick $(if ($i -eq 0) { 1 } else { 2 })
}

Write-Host "Starting the room on port $Port"
$room = Start-Process -FilePath $roomExe -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $WorkDir "room_out.txt") `
    -RedirectStandardError (Join-Path $WorkDir "room_err.txt") `
    -ArgumentList "--room-name nfshp2-soak --port $Port --max_members $($Consoles + 2) --preferred-app NFSHP2 --preferred-app-id 0"
Start-Sleep -Seconds 2
$room.Refresh()
if ($room.HasExited) { throw "the room server exited: see $WorkDir\room_out.txt" }

$start = Get-Date
function Elapsed { ((Get-Date) - $start).TotalSeconds }
try {
    Write-Host "Launching $($sides[0].Name) (host) and $($Consoles - 1) to join, with $Target3dsx"
    foreach ($s in $sides) { Launch $s }
    foreach ($s in $sides) { Join $s }
    foreach ($s in $sides) { if (-not $s.Joined) { throw "$($s.Name) did not join the room" } }

    $resultPattern = "wltest: (PASS|FAIL|left with START)"
    $deadline = $start.AddSeconds($RunSeconds)
    $lastShown = 0
    while ((Get-Date) -lt $deadline) {
        foreach ($s in $sides) {
            if ($null -eq $s.Result) {
                $r = @(LogLines $s $resultPattern)
                if ($r.Count -gt 0) {
                    $s.Result = $r[-1]
                    Write-Host ("  [{0,5:N0}s] {1}: {2}" -f (Elapsed), $s.Name, ($s.Result -replace "^.*wltest: ", ""))
                } elseif (-not (Alive $s)) {
                    $s.Result = "Azahar exited"
                    Write-Host ("  [{0,5:N0}s] {1}: Azahar exited" -f (Elapsed), $s.Name)
                }
            }
        }
        if (@($sides | Where-Object { $null -eq $_.Result }).Count -eq 0) { break }
        if ((Elapsed) - $lastShown -ge 15) {
            $lastShown = Elapsed
            foreach ($s in $sides) {
                # Whole lines only: the log's last may be half written. The
                # host logs a line for each client each second.
                $n = if ($s -eq $sides[0]) { $Consoles - 1 } else { 1 }
                $t = @(LogLines $s "wltest: t .*strays \d+$")
                $t | Select-Object -Last $n | ForEach-Object {
                    Write-Host ("  [{0,5:N0}s] {1}: {2}" -f (Elapsed), $s.Name, ($_ -replace "^.*wltest: ", ""))
                }
            }
        }
        Start-Sleep -Seconds 1
    }
    # The log's lines land up to ~7 s after they are written (sector
    # batching), so the last of them, the result's whole line among them,
    # are waited for before Azahar is closed.
    Start-Sleep -Seconds 8
    foreach ($s in $sides) {
        $r = @(LogLines $s $resultPattern)
        if ($r.Count -gt 0) { $s.Result = $r[-1] }
    }
} finally {
    foreach ($s in $sides) {
        if ($s.Proc -and (Alive $s)) { $s.Proc | Stop-Process -Force }
    }
    if (-not $room.HasExited) { $room | Stop-Process -Force }
}

Write-Host ""
foreach ($s in $sides) {
    Write-Host "--- $($s.Name): $($s.Log) ---"
    LogLines $s "wireless:|wltest: (mode|node .* connected|FAULT|.*host\(s\))" | Select-Object -First 30 |
        ForEach-Object { Write-Host "  $_" }
    LogLines $s "wltest: node \d+ (done|lost|sending|ending|lingering):" | ForEach-Object { Write-Host "  $_" }
    if ($s.Result) { Write-Host "  $($s.Result)" }
}
$failed = @($sides | Where-Object { $_.Result -notmatch "wltest: PASS" })
Write-Host ""
if ($failed.Count -eq 0) {
    Write-Host "All $Consoles passed."
} else {
    foreach ($s in $failed) { Write-Host "Not passed: $($s.Name) '$($s.Result)'" }
    exit 1
}
