// A bearing seat block: a square block with a through-bore sized for a
// deep-groove bearing's outside diameter. The same nominal part exists in
// build123d (block.py); claims.py states the shared requirements once.
//
// $fn is pinned in the parameters partspec passes, never left to a viewer
// default: under D15 the resolution is part of the question.

bore_d = 22.0;   // bearing OD the seat holds — the contract cites ISO 15 for it
wall = 8.0;      // designer's choice
depth = 12.0;    // designer's choice
$fn = 96;

w = bore_d + 2 * wall;

difference() {
    cube([w, depth, w]);
    translate([w / 2, -1, w / 2])
        rotate([-90, 0, 0])
            cylinder(d = bore_d, h = depth + 2);
}
