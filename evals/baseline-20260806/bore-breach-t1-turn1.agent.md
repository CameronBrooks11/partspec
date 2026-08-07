Set `bore_d = 20`, leaving a 5 mm wall on each Y side.

Expected effect on the contract:
- `envelope` — unchanged at exactly 40×30×6 (plate dimensions untouched), still within max.
- `watertight` — unchanged.
- `solid_count` — the plate is now continuous around the bore, so 1 solid.
- `genus` — becomes evaluable, and a single through-bore in one body gives genus 1.

I left the plate size, thickness, and the through-cut (`h = plate_z + 2`, centered) alone since only the bore diameter was out of bounds.
