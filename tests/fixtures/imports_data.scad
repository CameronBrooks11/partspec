// A model that reads an external data file, which `include_closure` records
// as `reads_external_data` (SPEC-report 8.3). The cube keeps the export
// non-empty whether or not the import resolves — what is under test is the
// closure's signal, not the imported geometry.
union() {
    cube([5, 5, 5]);
    import("input.stl");
}
