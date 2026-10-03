// Pre-analysis script for the stripped retail ELF (SLES_507.31): set gp to
// retail's _gp (0x003358f0, tools/retail_model.py's RETAIL_GP) over every
// executable block, so analysis resolves gp-relative loads and stores.
//
// Usage: see DecompileByAddr.java.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.lang.Register;
import ghidra.program.model.mem.MemoryBlock;
import java.math.BigInteger;

public class RetailSetGp extends GhidraScript {

    @Override
    public void run() throws Exception {
        Register gp = currentProgram.getRegister("gp");
        for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
            if (!b.isExecute()) continue;
            currentProgram.getProgramContext().setValue(gp, b.getStart(), b.getEnd(),
                BigInteger.valueOf(0x003358f0L));
            println("gp set over " + b.getName());
        }
    }
}
