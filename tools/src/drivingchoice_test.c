// Host harness for 3DS Files/source/drivingchoice.c, the choices an AI car
// makes about where to drive and the walk along the route that fills its
// drive target, and for Race::GracePeriodIsActive in racecore.c. Runs the
// op script tools/drivingchoice_check.py writes and prints the transcript
// it diffs against the retail image, run in mipsemu over the same script.
// The world, the stubs and the ops are drivingchoice_world.inc's, which
// says what the harness owns and stands in for.
#include "drivingchoice_world.inc"

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: drivingchoice_test SCRIPT\n");
        return 2;
    }
    dc_setup();
    return dc_run(argv[1], op);
}
