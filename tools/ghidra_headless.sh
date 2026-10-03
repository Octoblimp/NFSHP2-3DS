#!/bin/bash
# Run Ghidra's AnalyzeHeadless through java directly (no .bat, no cmd).
# Ghidra is $GHIDRA_DIR, or else the "ghidra" folder beside the repository.
G="${GHIDRA_DIR:-$(cd "$(dirname "$0")/../.." && pwd)/ghidra}"
mapfile -t VM < <(java -cp "$G/support/LaunchSupport.jar" LaunchSupport "$G" -vmargs | tr -d '\r')
exec java "${VM[@]}" -Xmx6G -Djava.awt.headless=true \
    -cp "$G/Ghidra/Framework/Utility/lib/Utility.jar" ghidra.Ghidra \
    ghidra.app.util.headless.AnalyzeHeadless "$@"
