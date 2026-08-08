// Motor mounting plate: 42 x 42 x 4 mm, four M3 clearance holes on a
// 31 mm square, central 22.3 mm pilot bore. All holes through.

$fn = 64;

size = 42;
thickness = 4;
hole_pitch = 31;
hole_d = 3.4;
bore_d = 22.3;

difference() {
    cube([size, size, thickness], center = true);
    cylinder(h = thickness + 2, d = bore_d, center = true);
    for (x = [-1, 1], y = [-1, 1])
        translate([x * hole_pitch / 2, y * hole_pitch / 2, 0])
            cylinder(h = thickness + 2, d = hole_d, center = true);
}
