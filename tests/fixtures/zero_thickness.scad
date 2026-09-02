// Two cubes meeting exactly on one face. The intersection is a zero-thickness
// sheet: closed, consistently wound, area 480 mm2, volume 0.0 — and with no
// centre of mass, since that quantity divides by the volume (#365).
intersection() {
    cube([20, 12, 10]);
    translate([0, 0, 10]) cube([20, 12, 10]);
}
