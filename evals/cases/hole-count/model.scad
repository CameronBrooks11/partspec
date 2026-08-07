// A plate with a four-hole bolt pattern on a 40 mm square.

plate_x = 60;
plate_y = 60;
plate_z = 5;
hole_d  = 5;
pitch   = 40;
$fn = 64;

h = pitch / 2;

difference() {
    cube([plate_x, plate_y, plate_z], center = true);
    translate([ h,  h, 0]) cylinder(h = plate_z + 2, d = hole_d, center = true);
    translate([-h,  h, 0]) cylinder(h = plate_z + 2, d = hole_d, center = true);
    translate([-h, -h, 0]) cylinder(h = plate_z + 2, d = hole_d, center = true);
}
