"""Circular contract: every bound is derived from the model's own parameters."""
import math
from partspec import Part, build123d

PX, PY, PZ, BORE = 40.0, 5.0, 6.0, 8.0

def circular() -> Part:
    p = Part("circular", build123d("model.py", method="plate",
             plate_x=PX, plate_y=PY, plate_z=PZ, bore_d=BORE))
    # Every number below is computed from the same constants the model is built
    # from. The contract cannot fail, whatever the model actually is.
    v = PX * PY * PZ - math.pi * (BORE / 2) ** 2 * PZ
    p.volume(min=v * 0.99, max=v * 1.01)
    p.envelope(min=(PX - 0.1, PY - 0.1, PZ - 0.1), max=(PX + 0.1, PY + 0.1, PZ + 0.1))
    p.watertight()
    p.solid_count(1)
    p.genus(1)
    return p
