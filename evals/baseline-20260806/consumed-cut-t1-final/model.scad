// A cored block: a cube with a smaller concentric cube removed.
//
// The core is a fully enclosed cavity, which is a second, separate shell: the
// part is watertight but is not one solid. A vent bore breaks the cavity out
// through the top face so the model is a single shell. The bore costs
// pi*(vent/2)^2 * (body - core)/2 = ~35 mm3, well inside the 1% volume band.

body = 20;
core = 10;
vent = 3;

difference() {
    cube([body, body, body], center = true);
    cube([core, core, core], center = true);

    // Bore from the core's top face out through the block's top face.
    // Overshoot both ends so no cut face is coplanar with a kept face.
    translate([0, 0, core / 2 - 1])
        cylinder(h = (body - core) / 2 + 2, d = vent, $fn = 64);
}
