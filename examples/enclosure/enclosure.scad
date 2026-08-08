// A sealed-cavity enclosure: an outer box with a fully enclosed internal
// void. The simplest part whose correctness is TOPOLOGICAL — watertight,
// one solid, genus 0 — which is exactly what a slicer or a reviewer cannot
// see from the outside and what a mesh measures without feature recognition.

w = 60;      // outer width  (x)
d = 40;      // outer depth  (y)
h = 25;      // outer height (z)
wall = 2.4;  // uniform wall

difference() {
    cube([w, d, h]);
    translate([wall, wall, wall])
        cube([w - 2 * wall, d - 2 * wall, h - 2 * wall]);
}
