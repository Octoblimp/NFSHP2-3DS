# Dot-sourced by the run_azahar_*.ps1 scripts that press SELECT. The
# frontend's viewers (screens, geometry, track) are developer tools, and
# SELECT reaches them only with the debug menu on: "DebugMenu 1" in
# sdmc:/nfshp2_config.txt (configitems.h) or the main menu's L + R + D-Pad
# Up. So the emulator's card gets the line when it lacks it. A later line
# wins, so an earlier "DebugMenu 0" is overridden. The line also shows the
# main menu's Debug Menu row, last, under Options.
$hp2Config = Join-Path $env:APPDATA "Azahar\sdmc\nfshp2_config.txt"
if (-not ((Test-Path $hp2Config) -and
          (Select-String -Path $hp2Config -Pattern "^\s*DebugMenu\s+[1-9]" -Quiet))) {
    New-Item -ItemType Directory -Force -Path (Split-Path $hp2Config) | Out-Null
    Add-Content -Path $hp2Config -Value @("", "DebugMenu 1") -Encoding ASCII
}
