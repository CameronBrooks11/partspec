// The deprecated spelling of `import()`, which OpenSCAD 2021.01 still runs.
// `reads_external_data` missed it until an adversarial review of #187, so the
// closure called itself complete and `measure --out input.stl` overwrote the
// file this reads. The cube keeps the export non-empty either way.
union() {
    cube([2, 2, 2]);
    translate([20, 0, 0]) import_stl("input.stl");
}
