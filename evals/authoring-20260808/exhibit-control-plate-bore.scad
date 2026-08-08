// Mounting plate 40 x 30 x 4 mm with central Ø6 mm through-bore
difference() {
    cube([40, 30, 4], center = true);
    cylinder(h = 6, d = 6, center = true, $fn = 64);
}
