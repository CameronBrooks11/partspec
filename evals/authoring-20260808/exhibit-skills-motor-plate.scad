// Motor mounting plate: 42 x 42 x 4 mm, four Ø3.4 through-holes on a
// 31 mm square centred on the plate, one Ø22.3 pilot bore at the centre.

plate_w = 42;
plate_d = 42;
plate_t = 4;
mount_hole_d = 3.4;
mount_square = 31;   // side of the square the mounting holes sit on
pilot_bore_d = 22.3;
facets = 96;

// datum: plate centre in XY
cx = plate_w / 2;
cy = plate_d / 2;

module plate() {
    cube([plate_w, plate_d, plate_t]);
}

module hole(x, y, d) {
    translate([x, y, -1]) cylinder(d = d, h = plate_t + 2, $fn = facets);
}

difference() {
    plate();
    hole(cx, cy, pilot_bore_d);
    for (sx = [-1, 1], sy = [-1, 1])
        hole(cx + sx * mount_square / 2, cy + sy * mount_square / 2, mount_hole_d);
}
