// A mounting spacer: a plate with a central through-bore.

plate_x = 40;
plate_y = 30;
plate_z = 6;
bore_d  = 20;  // must stay under plate_y so the bore does not break out the sides
$fn = 64;

difference() {
    cube([plate_x, plate_y, plate_z], center = true);
    cylinder(h = plate_z + 2, d = bore_d, center = true);
}
