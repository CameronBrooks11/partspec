plate_w = 40;
plate_d = 30;
plate_t = 4;
bore_d = 6;
facets = 48;

module plate() {
    cube([plate_w, plate_d, plate_t]);
}

module bore(x, y) {
    translate([x, y, -1]) cylinder(d = bore_d, h = plate_t + 2, $fn = facets);
}

difference() {
    plate();
    bore(plate_w / 2, plate_d / 2);
}
