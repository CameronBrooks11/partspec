**What was wrong:** two things, both visible in the report's `envelope: [50, 50, 6]`.

1. **Boolean operands reversed.** The model did `difference() { cylinder; cube; }` — a Ø50 disc with a rectangular slot cut out of it. That's why `watertight`, `solid_count` and `genus` all passed (a disc with one through-hole is still genus 1) while envelope and volume failed: the outer shape was the *bore* and the cut was the *plate*.
2. **Parameters swapped to match the inversion.** `plate_x/plate_y` were 30×20 (the cutter) and `bore_d` was 50 (the outer body).

**The fix:** plate is now the base solid at 40×30×6 and the Ø8 cylinder is the cut. The cylinder height is `plate_z + 2` (centered) so the bore extends past both faces — a cutter flush with the faces leaves coplanar surfaces that can produce degenerate geometry rather than a clean through-hole.

Expected measurements: envelope 40×30×6; volume 7200 − ~301 = ~6899 mm³, inside the ±2% band of [6760, 7036]. The `$fn = 64` polygonal bore under-removes by ~0.5 mm³ versus the ideal circle, far inside tolerance. Genus, solid count, and watertightness are unaffected.
