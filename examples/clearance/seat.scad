// Probe: the seated face between the cover and the rail. The parts touch and
// share no volume, so the result is a sheet with area and no thickness.
include <assembly.scad>

intersection() {
    rail();
    cover();
}
