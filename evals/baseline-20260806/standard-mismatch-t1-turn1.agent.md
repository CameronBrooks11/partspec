Changed the footprint from 40×40 to the 42 mm grid pitch.

- **Cause:** `envelope` measured `[40.0, 40.0, 5.0]` against a limit of `[41.9, 41.9, 4.9]`–`[42.1, 42.1, 5.1]`. The X/Y footprint was 2 mm undersized; Z was already in band.
- **Fix:** `model.scad` now defines `grid_pitch = 42` and drives `plate_x`/`plate_y` from it, so the footprint matches the grid the part seats into rather than a hardcoded 40.
- **Untouched:** `plate_z = 5` (already passing) and `bore_d = 8` — the through-bore is what gives genus 1, and the 42 mm plate still fully encloses it, so `watertight`, `solid_count`, and `genus` remain satisfied.

`spec.py` was not modified.
