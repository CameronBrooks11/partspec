// A block with a square through-hole: genus 1, all-planar, analytically exact.
// Square rather than round so every quantity has a closed form and the test
// asserts real numbers rather than whatever the tool happened to produce.
block = [30, 20, 10];
hole = 6;

difference() {
    cube(block, center = true);
    cube([hole, hole, block[2] + 2], center = true);
}
