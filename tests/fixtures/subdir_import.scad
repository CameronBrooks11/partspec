// #208's residue, in fixture form: the import sits in a SUBDIRECTORY, so
// `--out sub` derives exactly this path for the export while the guard — which
// refuses only the model's own directory — does not fire. Same shape as
// `self_named_import.scad` otherwise: the bounding box says whether the
// imported solid was read.
union() {
    cube([5, 5, 5]);
    translate([5, 0, 0]) import("sub/subdir_import.stl");
}
