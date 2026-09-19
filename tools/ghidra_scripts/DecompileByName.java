// Decompile one or more functions by (exact) symbol name, matched against
// NFSHP2.ELF's real .symtab names (unlike NFSU2-3DS's stripped PC binary,
// this ELF has real names, so no address-hardcoding or pattern-matching is
// needed here -- just look the name up).
//
// Usage (from repo root, after the Ghidra project + NFSHP2.ELF have been
// imported and analyzed -- see HANDOFF.md):
//   DECOMPILE_OUT=<out file> DECOMPILE_NAMES="name1,name2,..." \
//   support/analyzeHeadless.bat <project_dir> NFSHP2 -process NFSHP2.ELF \
//     -noanalysis -scriptPath <this dir> -postScript DecompileByName.java
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import java.io.PrintWriter;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

public class DecompileByName extends GhidraScript {

    @Override
    public void run() throws Exception {
        String outPath = System.getenv("DECOMPILE_OUT");
        if (outPath == null) outPath = "decompile_out.c";
        String namesEnv = System.getenv("DECOMPILE_NAMES");
        if (namesEnv == null) namesEnv = "bStringHash__FPCc";
        Set<String> wanted = new HashSet<>(Arrays.asList(namesEnv.split(",")));

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);

        PrintWriter out = new PrintWriter(outPath, "UTF-8");
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        int found = 0;
        while (it.hasNext()) {
            Function f = it.next();
            if (!wanted.contains(f.getName())) continue;
            found++;
            out.println("// ==== " + f.getEntryPoint() + " -> " + f.getName() + " ====");
            DecompileResults res = decomp.decompileFunction(f, 60, monitor);
            if (res != null && res.decompileCompleted()) {
                out.println(res.getDecompiledFunction().getC());
            } else {
                out.println("// decompile failed: " + (res != null ? res.getErrorMessage() : "null result"));
            }
            out.println();
        }
        out.flush();
        out.close();
        println("Matched " + found + "/" + wanted.size() + " requested names. Wrote " + outPath);
    }
}
