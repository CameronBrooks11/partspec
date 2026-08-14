// #208: this model's import target IS the name partspec derives for its own
// export — `<stem>.stl` — so a run whose output directory is the model's own
// directory writes the artifact over the input, and the next run measures the
// output of the last one. The cube keeps the export non-empty whether or not
// the import resolves, and the translate puts the imported solid outside it,
// so the bounding box says which of the two was measured.
union() {
    cube([5, 5, 5]);
    translate([5, 0, 0]) import("self_named_import.stl");
}
