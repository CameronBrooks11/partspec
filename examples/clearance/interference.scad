// Probe: the crush ribbon between the foot and the rail. This is the material
// that has to yield for the fit to close, and it must exist — an empty result
// here means the joint is loose.
include <assembly.scad>

intersection() {
    rail();
    foot();
}
