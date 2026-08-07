// A single-cell baseplate. Its footprint must match the grid it drops into.

plate_x = 40;
plate_y = 40;
plate_z = 5;
bore_d  = 8;
$fn = 64;

difference() {
    cube([plate_x, plate_y, plate_z], center = true);
    cylinder(h = plate_z + 2, d = bore_d, center = true);
}
