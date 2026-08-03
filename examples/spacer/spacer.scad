// A parametric mounting spacer: a plate with a central through-bore.
//
// Deliberately small, self-contained and authored here, so the example carries
// no third-party licensing surface. Real parts live in the dogfood workspace.

plate_x = 40;
plate_y = 30;
plate_z = 6;
bore_d = 8;
wall = 2;
$fn = 64;

difference() {
    cube([plate_x, plate_y, plate_z], center = true);
    cylinder(h = plate_z + 2, d = bore_d, center = true);
}
