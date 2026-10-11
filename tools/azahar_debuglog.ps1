# Dot-sourced by the run_azahar_*.ps1 scripts. The game writes
# sdmc:/nfshp2_debug.txt only when sdmc:/nfshp2_config.txt says "DebugLog 1"
# (configitems.h), and these runs read that log, so the emulator's card gets
# the line when it lacks it. A later line wins, so an earlier "DebugLog 0"
# is overridden.
$hp2Config = Join-Path $env:APPDATA "Azahar\sdmc\nfshp2_config.txt"
if (-not ((Test-Path $hp2Config) -and
          (Select-String -Path $hp2Config -Pattern "^\s*DebugLog\s+[1-9]" -Quiet))) {
    New-Item -ItemType Directory -Force -Path (Split-Path $hp2Config) | Out-Null
    Add-Content -Path $hp2Config -Value @("", "DebugLog 1") -Encoding ASCII
}
