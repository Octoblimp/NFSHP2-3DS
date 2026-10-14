# Boots NFSHP2-3DS.3dsx in Azahar and walks Options' Player Names
# (TASKS 54, nameentry.h): A on Player 1's name opens the 3DS keyboard,
# which Azahar shows as a dialog of its own; a name typed there and OK
# lands on the screen, and Cancel keeps it. A gender switched, no Player 2
# rows to move to, B back to Options and in again with the name kept.
# The capture and key methods are run_azahar_test.ps1's; see its header
# for why each is the way it is. NFSHP2/SAVES/settings.db is put back
# after, in case autosave wrote it.
#
# Usage:
#   powershell -File tools/run_azahar_nameentry.ps1
#   powershell -File tools/run_azahar_nameentry.ps1 -OutDir C:\shots

param(
    [int]$BootSeconds = 12,       # before the first capture: bundles decode slowly
    [int]$RunSeconds = 150,       # hard ceiling on the whole run
    [string]$AzaharExe = "C:\Program Files\Azahar\azahar.exe",
    [string]$Target3dsx = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if ($Target3dsx -eq "") { $Target3dsx = Join-Path $root "3DS Files\NFSHP2-3DS.3dsx" }
if ($OutDir -eq "") { $OutDir = Join-Path $env:TEMP "nfshp2_nameentry" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not (Test-Path $AzaharExe)) { throw "Azahar not found at $AzaharExe" }
if (-not (Test-Path $Target3dsx)) { throw "Target .3dsx not found at $Target3dsx" }
if ($Target3dsx -like "*.cia") {
    throw "Refusing to run a .cia: Azahar cannot boot one from a path. Pass the .3dsx."
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Drawing;
public class Hp2Dbg {
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
    public static void KeyDown(IntPtr h, int vk) {
        PostMessage(h, WM_KEYDOWN, (IntPtr)vk, IntPtr.Zero);
    }
    public static void KeyUp(IntPtr h, int vk) {
        PostMessage(h, WM_KEYUP, (IntPtr)vk, IntPtr.Zero);
    }
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

[void][Hp2Dbg]::SetProcessDPIAware()

$VK_A = 65; $VK_S = 83; $VK_M = 77; $VK_N = 78; $VK_T = 84; $VK_G = 71; $VK_H = 72; $VK_F = 70
$VK_Q = 81; $VK_W = 87    # L and R

$debugLog  = Join-Path $env:APPDATA "Azahar\sdmc\nfshp2_debug.txt"
. (Join-Path $PSScriptRoot "azahar_debuglog.ps1")   # DebugLog 1
$azaharLog = Join-Path $env:APPDATA "Azahar\log\azahar_log.txt"
Remove-Item $debugLog  -ErrorAction SilentlyContinue
Remove-Item $azaharLog -ErrorAction SilentlyContinue
Get-ChildItem $OutDir -Filter *.png -ErrorAction SilentlyContinue | Remove-Item -Force

# The card's save as it was, or none: B saves when autosave is on.
$saveFile = Join-Path $env:APPDATA "Azahar\sdmc\NFSHP2\SAVES\settings.db"
$saveBefore = $null; $hadSave = Test-Path $saveFile
if ($hadSave) { $saveBefore = [System.IO.File]::ReadAllBytes($saveFile) }
$saveWritten = $false
function Restore-Config {
    if ($script:hadSave -and $null -ne $script:saveBefore) {
        $now = [System.IO.File]::ReadAllBytes($script:saveFile)
        $script:saveWritten = [Convert]::ToBase64String($now) -ne `
            [Convert]::ToBase64String($script:saveBefore)
        [System.IO.File]::WriteAllBytes($script:saveFile, $script:saveBefore)
        $script:saveBefore = $null
    } elseif (-not $script:hadSave -and (Test-Path $script:saveFile)) {
        $script:saveWritten = $true
        Remove-Item $script:saveFile -Force
    }
}
trap { Restore-Config; break }

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
$closed = [Hp2Dbg]::DismissPopups([uint32]$proc.Id, $hwnd)
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
    [Hp2Dbg]::CaptureToFile($hwnd, $path)
    Write-Host ("  [{0,5:N1}s] {1}" -f (Elapsed), $path)
}

function Press([int]$vk, [int]$waitMs = 700) {
    [Hp2Dbg]::PressKey($hwnd, $vk)
    Start-Sleep -Milliseconds $waitMs
}

# --- the keyboard -----------------------------------------------------------
# Azahar answers the swkbd applet with a Qt dialog of its own, "Software
# Keyboard": a line edit and the app's buttons (Cancel and OK here). It is
# driven through UI Automation, which reaches into Qt's widgets: the edit's
# value set, then a button invoked by its name. Posting keys to it would
# depend on which button Enter picks.
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$UIA = [System.Windows.Automation.AutomationElement]
$TS  = [System.Windows.Automation.TreeScope]
$CT  = [System.Windows.Automation.ControlType]

Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class Hp2Kb {
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    delegate bool EnumProc(IntPtr h, IntPtr p);
    // The process's visible top-level windows but `keep`, as "hwnd|title".
    public static string[] Others(uint pid, IntPtr keep) {
        List<string> found = new List<string>();
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            uint q; GetWindowThreadProcessId(h, out q);
            if (q != pid || h == keep || !IsWindowVisible(h)) { return true; }
            StringBuilder t = new StringBuilder(256); GetWindowText(h, t, 256);
            found.Add(h.ToInt64().ToString() + "|" + t.ToString());
            return true;
        }, IntPtr.Zero);
        return found.ToArray();
    }
}
"@

# The keyboard: a visible window of Azahar's, other than its main one and
# those up before the A (Others-Before), with a title. The title is logged.
function Others-Before {
    @([Hp2Kb]::Others([uint32]$proc.Id, $hwnd) | ForEach-Object { $_.Split("|", 2)[0] })
}
function Find-KeyboardWindow([int]$timeoutSec, $before) {
    $end = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $end) {
        if (-not (Alive)) { return $null }
        foreach ($w in [Hp2Kb]::Others([uint32]$proc.Id, $hwnd)) {
            $parts = $w.Split("|", 2)
            if ($parts[1] -eq "" -or $before -contains $parts[0]) { continue }
            Write-Host ("  window: '{0}'" -f $parts[1])
            return $UIA::FromHandle([IntPtr][long]$parts[0])
        }
        Start-Sleep -Milliseconds 300
    }
    return $null
}

function Find-Under($el, $type, [string]$name = "") {
    $c = New-Object System.Windows.Automation.PropertyCondition(
        $UIA::ControlTypeProperty, $type)
    foreach ($e in $el.FindAll($TS::Descendants, $c)) {
        if ($name -eq "" -or $e.Current.Name -eq $name) { return $e }
    }
    return $null
}

function List-Under($el) {
    foreach ($e in $el.FindAll($TS::Descendants, [System.Windows.Automation.Condition]::TrueCondition)) {
        Write-Host ("    {0} '{1}'" -f $e.Current.ControlType.ProgrammaticName, $e.Current.Name)
    }
}

# A on a name, and the keyboard's window. Azahar sometimes drops a key
# posted just after its dialog closed, so A goes again while none opens.
function Open-Keyboard {
    for ($try = 0; $try -lt 3; $try++) {
        $before = Others-Before
        [Hp2Dbg]::PressKey($hwnd, $VK_A)
        $kb = Find-KeyboardWindow 5 $before
        if ($null -ne $kb) { return $kb }
        Write-Host "  no keyboard yet, A again"
    }
    return $null
}

# Types `$text` (when not $null) and presses the button named `$button`.
function Use-Keyboard($kb, [string]$text, [string]$button) {
    if ($null -ne $text) {
        $edit = Find-Under $kb $CT::Edit
        if ($null -eq $edit) { Write-Host "  no edit in the keyboard"; List-Under $kb; return $false }
        $vp = $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
        Write-Host ("  keyboard's text was '{0}'" -f $vp.Current.Value)
        $vp.SetValue($text)
        Start-Sleep -Milliseconds 400
    }
    $b = Find-Under $kb $CT::Button $button
    if ($null -eq $b) { Write-Host "  no button '$button'"; List-Under $kb; return $false }
    $b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    return $true
}

# --- the script the run follows -------------------------------------------
# The boot as run_azahar_debugmenu.ps1 has it, to the main menu. Options is
# two down, and Player Names (MENUITEM_5) four down in it. A on Player 1's
# name opens the keyboard: "Racer7" and OK. A again: Cancel keeps it.
# Down to Player 1's gender and Right switches it. Down to Player 2's
# Down again lands on no Player 2 row: the port hides them. B back to
# Options, down to Player Names and in again: the name is still there.

$loading = Wait-ForLog "global chunks loaded" 60
Write-Host ("  LOADING drawn: {0}" -f $loading)
$booted = Wait-ForLog "entering main loop" 60
Write-Host ("  main loop: {0}" -f $booted)

$atNames = $false; $kbOpened = $false; $typed = $false; $cancelled = $false
$gender = $false; $p2Silent = $false; $back = $false; $kept = $false
$soundBack = $false; $asked = $false; $stayed = $false; $discarded = $false
if ($booted) {
    if (Wait-ForLog "flow enter Language Options Pre FE" 30) {
        Start-Sleep -Milliseconds 1500
        [Hp2Dbg]::PressKey($hwnd, $VK_A)      # A, English
    }
    if (Wait-ForLog "^movie open MOVIES/INTRO/NFSINTRO" 25) {
        Start-Sleep -Seconds 2
        [Hp2Dbg]::PressKey($hwnd, $VK_M)      # START: stop the intro
        [void](Wait-ForLog "flow title skip" 10)
    } else {
        [void](Wait-ForLog "flow title idle" 20)
    }
    [void](Wait-ForLog "flow vis object b5761d00 b070dbc9 1" 15)
    Start-Sleep -Milliseconds 900
    [Hp2Dbg]::PressKey($hwnd, $VK_M)          # START

    if (Wait-ForLog "flow enter New Main Menu" 12) {
        Start-Sleep -Milliseconds 2000
        Press $VK_G                           # Cops On
        Press $VK_G                           # Options
        Press $VK_A 300
        if (Wait-ForLog "flow enter Options" 10) {
            Start-Sleep -Milliseconds 1500
            for ($i = 0; $i -lt 4; $i++) { Press $VK_G 500 }   # Player Names
            Shot "options"
            Press $VK_A 300
            $atNames = Wait-ForLog "name entry: in:" 10
            Write-Host ("  Player Names: {0}" -f $atNames)
        }
    } else {
        Shot "no-main-menu"
    }
}

if ($atNames) {
    Start-Sleep -Milliseconds 1500
    Shot "names"
    $kb = Open-Keyboard
    $kbOpened = $null -ne $kb
    Write-Host ("  keyboard: {0}" -f $kbOpened)
    if ($kbOpened) {
        Write-Host ("  its window: '{0}'" -f $kb.Current.Name)
        Start-Sleep -Milliseconds 800
        Shot "keyboard"
        Start-Sleep -Seconds 6                # the sound held meanwhile
        if (Use-Keyboard $kb "Racer7" "OK") {
            $typed = Wait-ForLog 'name entry: keyboard: player 1 is "Racer7"' 12
        }
        Write-Host ("  typed: {0}" -f $typed)
        Start-Sleep -Milliseconds 1500
        Shot "typed"

        $kb = Open-Keyboard                   # A: the keyboard again
        if ($null -ne $kb) {
            Start-Sleep -Milliseconds 800
            if (Use-Keyboard $kb "Zzz" "Cancel") {
                $cancelled = Wait-ForLog 'name entry: keyboard: cancelled, "Racer7" kept' 12
            }
        }
        Write-Host ("  cancelled: {0}" -f $cancelled)
        Start-Sleep -Milliseconds 1200
    }
    Press $VK_G                               # Player 1's gender
    Press $VK_H                               # Right: switched
    $gender = Wait-ForLog "name entry: gender: player 1 is" 10
    Write-Host ("  gender: {0}" -f $gender)
    Shot "gender"
    Press $VK_G                               # Down: Player 2's are hidden
    Shot "down"
    Start-Sleep -Seconds 8                    # the log's lag
    $p2Silent = -not (Select-String -Path $debugLog -Quiet `
        -Pattern "screen NameEntry .* item [34] last")
    Write-Host ("  no Player 2 rows: {0}" -f $p2Silent)
    $soundBack = Wait-ForLogCount "audio: back after the applet" 2 10
    Write-Host ("  sound back after both keyboards: {0}" -f $soundBack)

    # B with changes: the save prompt. B on it stays; B again and Yes
    # (the popup opens on Yes) saves on the Autosave screen, which moves
    # back to Options.
    Press $VK_S 300                           # B
    $asked = Wait-ForLog "name entry: back: changed, asking to save" 10
    Write-Host ("  asked: {0}" -f $asked)
    Start-Sleep -Milliseconds 1500
    Shot "prompt"
    Press $VK_S 300                           # B on the popup: stay
    $stayed = Wait-ForLog "name entry: save: stay" 10
    Write-Host ("  stayed: {0}" -f $stayed)
    Start-Sleep -Milliseconds 1200
    Shot "stayed"
    Press $VK_S 300                           # B
    if (Wait-ForLogCount "name entry: back: changed, asking to save" 2 10) {
        Start-Sleep -Milliseconds 1200
        Press $VK_A 300                       # Yes
        $back = Wait-ForLog "name entry: save: yes" 10
    }
    Write-Host ("  yes: {0}" -f $back)
    # The Autosave screen's own question, with a save on the card: retail's
    # "overwrite?", opened on No (memcard.c, saverCheckIfCardOK). Its Yes
    # is the third popup's: two prompts came before it.
    if ($back -and (Wait-ForLogCount "flow language id 0ce3f7ce e0105663 150103" 3 15)) {
        Start-Sleep -Milliseconds 1500
        Shot "overwrite"
        Press $VK_F                           # Left: Yes
        Press $VK_A 300
    }
    if (Wait-ForLogCount "flow enter Options" 2 30) {
        Start-Sleep -Milliseconds 1500
        Shot "options-again"
        for ($i = 0; $i -lt 4; $i++) { Press $VK_G 500 }   # Player Names
        Press $VK_A 300                       # Player Names again
        $kept = Wait-ForLog 'name entry: in: "Racer7"' 12
        Write-Host ("  kept: {0}" -f $kept)
        Start-Sleep -Milliseconds 1500
        Shot "names-again"

        # A gender switched, B, and No: the gender as it was.
        $inLine = @(Get-Content $debugLog | Where-Object { $_ -match 'name entry: in: "Racer7" (\d+)' })[-1]
        $g = if ($inLine -match '"Racer7" (\d+)') { $Matches[1] } else { "?" }
        Press $VK_G                           # Player 1's gender
        Press $VK_H                           # Right: switched
        Press $VK_S 300                       # B
        if (Wait-ForLogCount "name entry: back: changed, asking to save" 3 10) {
            Start-Sleep -Milliseconds 1200
            Press $VK_H                       # Right: No
            Press $VK_A 300
            $discarded = Wait-ForLog ('name entry: save: no, back to "Racer7" ' + $g) 10
        }
        Write-Host ("  no puts the gender back ({0}): {1}" -f $g, $discarded)
        if (Wait-ForLogCount "flow enter Options" 3 15) {
            Start-Sleep -Milliseconds 1200
            Shot "options-last"
        }
    }
}
$raced = $true

while ((Elapsed) -lt $RunSeconds -and (Alive) -and -not $raced) { Start-Sleep -Milliseconds 300 }

$survived = Alive
if ($survived) { $proc | Stop-Process -Force }
Start-Sleep -Milliseconds 600
Restore-Config

# --- the verdict ------------------------------------------------------------

$dbg = @(); if (Test-Path $debugLog)  { $dbg = Get-Content $debugLog }
$az  = @(); if (Test-Path $azaharLog) { $az  = Get-Content $azaharLog }

$crashSigs = @("PANIC", "segfault", "Unhandled exception", "svcBreak")
$crash = $az | Where-Object { $l = $_; $crashSigs | Where-Object { $l -match $_ } }
$unmapped = $az | Where-Object { $_ -match "unmapped (Read|Write)" }
$lines = $dbg | Where-Object { $_ -match "name entry|NameEntry|Autosave|memcard: saved|audio: back" }

$verdict = "UNKNOWN"
if (-not $booted)        { $verdict = "FAIL (never reached the main loop)" }
elseif ($crash)          { $verdict = "FAIL (crash: $($crash[0]))" }
elseif ($unmapped)       { $verdict = "FAIL ($(@($unmapped).Count) unmapped accesses, first: $(@($unmapped)[0]))" }
elseif (-not $survived)  { $verdict = "FAIL (the app died)" }
elseif (-not $atNames)   { $verdict = "PARTIAL (never reached Player Names)" }
elseif (-not $kbOpened)  { $verdict = "PARTIAL (A opened no keyboard)" }
elseif (-not $typed)     { $verdict = "PARTIAL (the typed name did not land)" }
elseif (-not $cancelled) { $verdict = "PARTIAL (Cancel did not keep the name)" }
elseif (-not $gender)    { $verdict = "PARTIAL (Right did not switch the gender)" }
elseif (-not $p2Silent)  { $verdict = "PARTIAL (the menu moved onto a Player 2 row)" }
elseif (-not $soundBack) { $verdict = "PARTIAL (the sound was not let go after the keyboard)" }
elseif (-not $asked)     { $verdict = "PARTIAL (B with changes did not ask to save)" }
elseif (-not $stayed)    { $verdict = "PARTIAL (B on the save prompt did not stay)" }
elseif (-not $back)      { $verdict = "PARTIAL (Yes did not save)" }
elseif (-not $kept)      { $verdict = "PARTIAL (the name was gone on the way back in)" }
elseif (-not $discarded) { $verdict = "PARTIAL (No did not put the gender back)" }
else                     { $verdict = "PASS (keyboard, OK, Cancel, sound, prompt: stay, yes, no)" }

Write-Host ""
Write-Host "=== name entry lines ==="
$lines | Select-Object -Last 20 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== nfshp2_debug.txt (last 25) ==="
$dbg | Select-Object -Last 25 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== azahar_log.txt errors ==="
$az | Where-Object { $_ -match "Error|Critical|PANIC" } | Select-Object -Last 12 |
    ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "=== Result ==="
Write-Host ("Save written: {0} (put back)" -f $saveWritten)
Write-Host ("Verdict:    {0}" -f $verdict)
Write-Host ("Screenshots: {0} in {1}" -f $step, $OutDir)
