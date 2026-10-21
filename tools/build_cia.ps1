# Builds 3DS Files/NFSHP2-3DS.cia (.3dsx/.smdh too). The link's .elf, which
# the 3DS never loads, is an intermediate in 3DS Files/build.
#
# Why this script exists: the project lives under a path containing spaces
# ("My Stuff", "3DS Files"), and devkitPro's Makefile template can't be
# invoked from such a path -- GNU Make's $(notdir ...) is whitespace-list
# based, so $(notdir $(CURDIR)) returns garbage and the top-level/recursive
# build split in the Makefile breaks before any compiler even runs. The
# workaround is to `subst` a temporary space-free drive letter onto
# "3DS Files" and build from there. This script automates that: it maps the
# drive, runs `make cia` inside devkitPro's own msys2 bash (which has
# DEVKITPRO/DEVKITARM and PATH already set correctly), and always unmaps the
# drive afterwards even if the build fails.
#
# Usage: powershell -ExecutionPolicy Bypass -File tools/build_cia.ps1
#        ... -DriveLetter Y:   to force one particular mapping

param(
    # Left empty, the first free letter out of the candidate list below is
    # taken. A letter is only used if `subst` does not already own it: another
    # project on this machine keeps its own build drive mapped (Melee3DS holds
    # Z:), and clobbering that would break whatever is building there. Before
    # this, Z: was hardcoded and a run just aborted whenever that happened.
    [string]$DriveLetter = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$projectDir = Join-Path $root "3DS Files"
$toolsBin = Join-Path $root "tools\3ds-bin"

if (-not (Test-Path $projectDir)) {
    throw "Project directory not found: $projectDir"
}

# Every letter `subst` currently owns, as "Z:" strings. `subst` with no
# arguments prints one line per mapping, of the form "Z:\: => C:\some\path".
$substTaken = @()
foreach ($line in (& subst.exe)) {
    if ($line -match '^([A-Za-z]):') { $substTaken += ($matches[1].ToUpper() + ":") }
}

function Test-DriveFree($letter) {
    if ($substTaken -contains $letter) { return $false }
    # A real volume or a mapped network drive on that letter would be shadowed
    # by the subst, so those are out too.
    return -not (Test-Path ($letter + "\"))
}

if ($DriveLetter -ne "") {
    if ($DriveLetter -notmatch '^[A-Za-z]:$') {
        throw "-DriveLetter must look like 'Y:' -- got '$DriveLetter'"
    }
    $driveLetter = $DriveLetter.ToUpper()
    if (-not (Test-DriveFree $driveLetter)) {
        throw "$driveLetter is already in use (run 'subst $driveLetter /D' if it is a stale mapping) -- aborting so we don't clobber it."
    }
} else {
    $driveLetter = $null
    foreach ($cand in @("Z:", "Y:", "X:", "W:", "V:", "U:", "T:", "S:", "R:", "Q:")) {
        if (Test-DriveFree $cand) { $driveLetter = $cand; break }
    }
    if (-not $driveLetter) {
        throw "No free drive letter to map the build directory onto (tried Z: down to Q:)."
    }
}
Write-Host "Building from $driveLetter -> $projectDir"

# The HOME Menu banner, its siren and the icon are made from the retail files
# (tools/make_banner.py, into meta/hp2, which the Makefile picks up). Without
# an extraction the script stops before writing, and the copy committed in
# meta/hp2 is used, so a failure here only warns.
& python (Join-Path $PSScriptRoot "make_banner.py") --out (Join-Path $projectDir "meta\hp2")
if ($LASTEXITCODE -ne 0) {
    Write-Warning "make_banner.py failed -- the CIA gets the placeholder banner"
}

# devkitPro's generated .d files record every source path as seen from the
# build drive ("/z/source/car.v.pica"), so a build directory left behind by a
# run on a *different* letter makes make fail with "No rule to make target".
# The letter is therefore stamped next to the objects, and a change wipes them.
$buildDir = Join-Path $projectDir "build"
$stampPath = Join-Path $buildDir ".subst-drive"
if (Test-Path $buildDir) {
    $prev = if (Test-Path $stampPath) { (Get-Content $stampPath -Raw).Trim() } else { "" }
    if ($prev -ne $driveLetter) {
        Write-Host "Build drive changed ('$prev' -> '$driveLetter') -- clearing stale objects."
        Remove-Item $buildDir -Recurse -Force
    }
}
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
Set-Content -Path $stampPath -Value $driveLetter -Encoding ASCII

& subst.exe $driveLetter $projectDir
if ($LASTEXITCODE -ne 0) {
    throw "subst failed to map $driveLetter to $projectDir"
}

try {
    function ToMsysPath($winPath) {
        # C:\foo\bar -> /c/foo/bar (msys-style), since msys make doesn't
        # reliably resolve "C:/foo/bar"-style paths passed as variable values.
        $drive = $winPath.Substring(0, 1).ToLower()
        $rest = ($winPath.Substring(2)) -replace '\\', '/'
        return "/$drive$rest"
    }
    $makerom = ToMsysPath (Join-Path $toolsBin "makerom.exe")
    $bannertool = ToMsysPath (Join-Path $toolsBin "bannertool.exe")
    $bashExe = "C:\devkitPro\msys2\usr\bin\bash.exe"

    if (-not (Test-Path $bashExe)) {
        throw "devkitPro msys2 bash not found at $bashExe -- update this script if devkitPro is installed elsewhere."
    }

    # Written to a temp script instead of passed as a -lc string: PowerShell's
    # argument marshalling to native exes doesn't reliably preserve embedded
    # quotes/spaces, so a long quoted -lc string gets re-split on its way to
    # bash.exe.
    $scriptPath = Join-Path $env:TEMP "nfshp2_build_cia.sh"
    # msys spells a drive-letter root "/z", lower case and without the colon.
    $msysDrive = "/" + $driveLetter.Substring(0, 1).ToLower()
    @"
cd $msysDrive
make cia MAKEROM="$makerom" BANNERTOOL="$bannertool"
"@ | Set-Content -Path $scriptPath -Encoding ASCII -NoNewline

    & $bashExe -l $scriptPath
    $buildExit = $LASTEXITCODE
    Remove-Item $scriptPath -ErrorAction SilentlyContinue
}
finally {
    & subst.exe $driveLetter /D
}

if ($buildExit -ne 0) {
    throw "make cia failed (exit $buildExit)"
}

$cia = Join-Path $projectDir "NFSHP2-3DS.cia"
if (Test-Path $cia) {
    Write-Host "Built: $cia"
} else {
    throw "make cia reported success but $cia is missing"
}

# A relocation the 3DSX loader refuses links cleanly and fails only when
# Azahar starts the program, with nothing in the app's own log; see
# tools/check_3dsx.py. It is checked here so the build says so first.
$threedsx = Join-Path $projectDir "NFSHP2-3DS.3dsx"
& python (Join-Path $PSScriptRoot "check_3dsx.py") $threedsx
if ($LASTEXITCODE -ne 0) {
    throw "check_3dsx: $threedsx would not load"
}

# A vertex shader that leaves an output component unwritten, or writes one
# twice, freezes a real 3DS's GPU at its first draw and draws on Azahar;
# see tools/check_shbin.py.
$shbins = @(Get-ChildItem (Join-Path $projectDir "build") -Filter *.shbin |
            ForEach-Object { $_.FullName })
& python (Join-Path $PSScriptRoot "check_shbin.py") @shbins
if ($LASTEXITCODE -ne 0) {
    throw "check_shbin: a shader would freeze the GPU"
}
