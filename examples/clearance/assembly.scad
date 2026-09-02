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
LID   = [40, 12, 3];   // spans the rail, 2.0 mm above the post
CRUSH = 0.2;           // designed interference, on the flank, per fit
CLEAR = 1.5;           // required standoff, lid to post, per fit

POST_AT = [30, 4, RAIL[2]];
LID_AT  = [0, 0, 13];

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
// across a face and share no volume at all. Deliberately NOT probed: a
// zero-thickness intersection is where the two pinned engines disagree, and
// the README measures how. Kept because it is the case an author has to be
// warned about, and a warning with no referent is one nobody checks.
module cover() {
    translate([2, 0, RAIL[2]]) cube(COVER);
}

module post() {
    translate(POST_AT) cube(POST);
}

// The post plus the standoff the fit requires around it. The clearance probe
// intersects the lid against THIS rather than against `post()`, so a lid closer
// than CLEAR by any margin leaves a solid of positive volume on every kernel
// instead of the zero-thickness result the kernels disagree about.
//
// LID_AT is 2.0 mm above the post against CLEAR = 1.5 for a reason: at a gap of
// EXACTLY CLEAR the probe is a zero-thickness sheet and the pinned engines split
// (2021.01 exit 1, 2026.08.01 exit 0). Growing moves that degeneracy to the
// boundary rather than removing it, so the design gap must clear CLEAR strictly.
// The grow is per-axis, so it measures Chebyshev and not Euclidean distance --
// safe in the FAIL direction only (SPEC-contract.md 9.1 rule 3).
module post_envelope() {
    translate(POST_AT - [CLEAR, CLEAR, CLEAR]) cube(POST + 2 * [CLEAR, CLEAR, CLEAR]);
}

// The lid the post has to clear.
module lid() {
    translate(LID_AT) cube(LID);
}
