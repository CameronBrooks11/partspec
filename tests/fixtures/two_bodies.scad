// Two disjoint cubes. Exercises solid_count, and the refusal of genus on a
// multi-body part.
size = 5;
gap = 20;

translate([-gap / 2, 0, 0]) cube(size, center = true);
translate([ gap / 2, 0, 0]) cube(size, center = true);
