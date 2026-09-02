// Probe: the standoff between the lid and the tallest component. The lid is
// intersected against the post GROWN BY CLEAR, so this is empty only while the
// gap is at least CLEAR — a bare `lid() ∩ post()` would be empty for any gap at
// all, including none (SPEC-contract.md §9.1).
include <assembly.scad>

intersection() {
    lid();
    post_envelope();
}
