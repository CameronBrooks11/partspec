// The parts of one assembly, each at the pose it occupies in the product.
//
// Poses live here and nowhere else. Every probe beside this file intersects
// two of these modules AS PLACED, so an interference number is the assembly's
// interference and not a number about geometry sitting at the origin. Move a
// part by editing this file and every probe follows it.

RAIL  = [40, 12, 8];   // extruded rail, front lower corner at the origin
FOOT  = [20, 10, 6];   // clips onto the rail's far flank
COVER = [16, 12, 3];   // lies flat on the rail's top face
POST  = [6, 4, 3];     // the tallest thing standing on the rail
CRUSH = 0.2;           // designed interference, on the flank, per fit

module rail() {
    cube(RAIL);
}

// Clipped on from +y and deliberately proud by CRUSH, so the flanks overlap.
// That overlap IS the design: too little and the joint rattles, too much and
// the assembly will not close.
module foot() {
    translate([10, RAIL[1] - CRUSH, 0]) cube(FOOT);
}

// Seated on the rail rather than fastened into it, so the two parts touch
// across a face and share no volume at all.
module cover() {
    translate([2, 0, RAIL[2]]) cube(COVER);
}

module post() {
    translate([30, 4, RAIL[2]]) cube(POST);
}

// The lid the post has to clear.
module lid() {
    translate([0, 0, 20]) cube([40, 12, 3]);
}
