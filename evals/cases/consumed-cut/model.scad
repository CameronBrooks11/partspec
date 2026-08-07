// A cored block: a cube with a smaller concentric cube removed.

body = 20;
core = 30;

difference() {
    cube([body, body, body], center = true);
    cube([core, core, core], center = true);
}
