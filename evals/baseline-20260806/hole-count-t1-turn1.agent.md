Added the missing fourth hole at `[+h, -h]` in `model.scad:17`.

The other four checks were already passing and this change doesn't disturb them: the hole is a through-cut (`plate_z + 2` tall, centered) fully inside the 60×60 footprint at ±20 mm, so the envelope stays 60×60×5, the plate remains a single watertight solid, and the genus goes from 3 to 4.
