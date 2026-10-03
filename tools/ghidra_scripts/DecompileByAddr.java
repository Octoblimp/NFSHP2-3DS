// Decompile functions of the stripped retail ELF (SLES_507.31) by address,
// after naming every function out/retail_syms.txt places (tools/retail_match.py
// carries the demo's names over), so calls read as names.
//
// Usage (from the repo root). Import once, with RetailSetGp as the pre-script:
//   analyzeHeadless <GhidraProjects> NFSHP2R -import "PS2 Files/Full Game/SLES_507.31" \
//     -processor "MIPS:LE:64:64-32addr" -cspec o32 -scriptPath tools/ghidra_scripts \
//     -preScript RetailSetGp.java
// Then, for each batch:
//   RETAIL_SYMS=out/retail_syms.txt DECOMPILE_OUT=<out file> DECOMPILE_ADDRS=001796b0,00178da0 \
//   analyzeHeadless <GhidraProjects> NFSHP2R -process SLES_507.31 -noanalysis \
//     -scriptPath tools/ghidra_scripts -postScript DecompileByAddr.java
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.FlowOverride;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.SourceType;
import java.io.BufferedReader;
import java.io.FileReader;
import java.io.PrintWriter;

public class DecompileByAddr extends GhidraScript {

    private Function ensureFunction(Address a) throws Exception {
        Function f = getFunctionAt(a);
        if (f != null) return f;
        if (getInstructionAt(a) == null) disassemble(a);
        return createFunction(a, null);
    }

    // Analysis stops at a call it once took for non-returning, so what
    // follows may be left as bytes. Disassemble the function's whole range
    // and let the body take it in.
    private void fillBody(Function f, long size) throws Exception {
        Address end = f.getEntryPoint().add(size);
        for (Address a = f.getEntryPoint(); a.compareTo(end) < 0; a = a.add(4)) {
            if (getInstructionContaining(a) == null) disassemble(a);
        }
        // and undo what it did to the calls: a call made to return, or its
        // fallthrough taken away
        for (Address a = f.getEntryPoint(); a.compareTo(end) < 0; a = a.add(4)) {
            Instruction in = getInstructionAt(a);
            if (in == null) continue;
            if (in.getFlowOverride() != FlowOverride.NONE) in.setFlowOverride(FlowOverride.NONE);
            if (in.isFallThroughOverridden()) in.clearFallThroughOverride();
        }
        CreateFunctionCmd.fixupFunctionBody(currentProgram, f, monitor);
    }

    @Override
    public void run() throws Exception {
        java.util.Map<Long, Long> sizes = new java.util.HashMap<>();
        String syms = System.getenv("RETAIL_SYMS");
        if (syms != null) {
            int named = 0;
            BufferedReader r = new BufferedReader(new FileReader(syms));
            for (String line; (line = r.readLine()) != null; ) {
                if (line.startsWith("#") || line.startsWith("-")) continue;
                String[] t = line.trim().split("\\s+");
                if (t.length < 7 || t[2].equals("new")) continue;
                Address a = toAddr(Long.parseLong(t[0], 16));
                sizes.put(Long.parseLong(t[0], 16), Long.parseLong(t[1]));
                Function f = ensureFunction(a);
                if (f == null) continue;
                // Analysis marks some callees non-returning (bStringHash
                // among them), which cuts the caller's decompile short.
                // Only the exits really are.
                String low = t[6].toLowerCase();
                if (f.hasNoReturn() && !low.contains("exit") && !low.contains("abort")) {
                    f.setNoReturn(false);
                }
                if (!f.getName().equals(t[6])) {
                    try {
                        f.setName(t[6], SourceType.USER_DEFINED);
                        named++;
                    } catch (Exception e) {
                        // a duplicate name: keep Ghidra's
                    }
                }
            }
            r.close();
            println("named " + named + " functions");
        }

        String outPath = System.getenv("DECOMPILE_OUT");
        if (outPath == null) outPath = "decompile_out.c";
        String addrs = System.getenv("DECOMPILE_ADDRS");
        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        PrintWriter out = new PrintWriter(outPath, "UTF-8");
        if (addrs != null) {
            for (String s : addrs.split(",")) {
                long at = Long.parseLong(s.trim(), 16);
                Address a = toAddr(at);
                Function f = ensureFunction(a);
                if (f == null) {
                    out.println("// no function at " + a);
                    continue;
                }
                if (sizes.containsKey(at)) fillBody(f, sizes.get(at));
                out.println("// ==== " + f.getEntryPoint() + " -> " + f.getName() + " ====");
                DecompileResults res = decomp.decompileFunction(f, 300, monitor);
                if (res != null && res.decompileCompleted()) {
                    out.println(res.getDecompiledFunction().getC());
                } else {
                    out.println("// decompile failed: " + (res != null ? res.getErrorMessage() : "null result"));
                }
                out.println();
            }
        }
        out.flush();
        out.close();
        println("Wrote " + outPath);
    }
}
