// A plate with a central bore.

plate_x = 30;
plate_y = 20;
plate_z = 6;
bore_d  = 50;
$fn = 64;

difference() {
    cylinder(h = plate_z, d = bore_d, center = true);
    cube([plate_x, plate_y, plate_z + 2], center = true);
}
