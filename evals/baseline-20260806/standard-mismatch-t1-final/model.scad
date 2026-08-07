// A single-cell baseplate. Its footprint must match the grid it drops into.

// Grid pitch of the system this part drops into.
grid_pitch = 42;

plate_x = grid_pitch;
plate_y = grid_pitch;
plate_z = 5;
bore_d  = 8;
$fn = 64;

difference() {
    cube([plate_x, plate_y, plate_z], center = true);
    cylinder(h = plate_z + 2, d = bore_d, center = true);
}
