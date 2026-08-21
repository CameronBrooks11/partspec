// Probe: the lid over the tallest component. These two must share no space at
// all, which is exactly what an empty build states.
include <assembly.scad>

intersection() {
    lid();
    post();
}
