// Dump the disassembly of one or more functions by exact .symtab name.
//
// The decompiler is the usual tool, but for MIPS code that hand-loads GS/DMA
// registers (the texture download path, the VU packet builders) Ghidra drops
// the register-passed arguments on the floor, so the raw instruction stream
// is the only way to see which constants go where.
//
// Usage (from repo root):
//   DISASM_OUT=<out file> DISASM_NAMES="name1,name2,..." \
//   support/analyzeHeadless.bat <project_dir> NFSHP2 -process NFSHP2.ELF \
//     -noanalysis -scriptPath <this dir> -postScript DisassembleByName.java
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import java.io.PrintWriter;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

public class DisassembleByName extends GhidraScript {

    @Override
    public void run() throws Exception {
        String outPath = System.getenv("DISASM_OUT");
        if (outPath == null) outPath = "disasm_out.txt";
        String namesEnv = System.getenv("DISASM_NAMES");
        if (namesEnv == null) namesEnv = "bStringHash__FPCc";
        Set<String> wanted = new HashSet<>(Arrays.asList(namesEnv.split(",")));

        PrintWriter out = new PrintWriter(outPath, "UTF-8");
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        int found = 0;
        while (it.hasNext()) {
            Function f = it.next();
            if (!wanted.contains(f.getName())) continue;
            found++;
            out.println("==== " + f.getEntryPoint() + " " + f.getName() + " ====");
            InstructionIterator ins =
                currentProgram.getListing().getInstructions(f.getBody(), true);
            while (ins.hasNext()) {
                Instruction i = ins.next();
                Address a = i.getAddress();
                out.printf("%s  %-40s %s%n", a, i.toString(),
                           getSymbolComment(i));
            }
            out.println();
        }
        out.flush();
        out.close();
        println("Matched " + found + "/" + wanted.size() + " requested names. Wrote " + outPath);
    }

    /** Names the call/branch target when there is one, so jal targets read as symbols. */
    private String getSymbolComment(Instruction i) {
        Address[] flows = i.getFlows();
        if (flows == null || flows.length == 0) return "";
        StringBuilder sb = new StringBuilder("-> ");
        for (Address a : flows) {
            ghidra.program.model.symbol.Symbol s =
                currentProgram.getSymbolTable().getPrimarySymbol(a);
            sb.append(s != null ? s.getName() : a.toString()).append(' ');
        }
        return sb.toString();
    }
}
