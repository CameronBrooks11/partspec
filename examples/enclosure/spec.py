"""Contract for the enclosure family — the parameter-phase exemplar.

What to imitate here:

- **One model, a family of parts.** Each factory is a parameterisation; the
  batch verb checks them all in one process. The invalid member exists on
  purpose: `requires` proves a wall-vs-cavity contradiction in milliseconds,
  before any engine runs.
- **A contract with no dimensional claims at all.** Every bound here is
  topological (`watertight`, `solid_count`, `genus`) or parametric
  (`requires`, `param`). That is the honest retrofit position for a part with
  no external drawing to cite: asserting the envelope from the same numbers
  the model is built from would only prove the model matches itself
  (`docs/FAILURE-MODES.md` entry 4). When a real requirement arrives — the
  PCB it must hold, the rail it must clip — its numbers join as cited limits.
- **Topology is the claim visual review is worst at** (`docs/FAILURE-MODES.md`
  entry 3): a cavity breached by one wall going thin is invisible in a render
  and a one-word change in the genus.
"""

from partspec import Part, openscad


def _enclosure(name: str, w: float, d: float, h: float, wall: float) -> Part:
    p = Part(name, openscad("enclosure.scad", w=w, d=d, h=h, wall=wall))

    # Parameter phase: a cavity must exist, with printable walls around it.
    p.requires("2 * wall < w")
    p.requires("2 * wall < d")
    p.requires("2 * wall < h")
    p.param("wall", min=0.8)

    # Geometry phase: sealed means exactly this, and nothing else measures it.
    p.watertight()
    p.solid_count(1)
    p.genus(0)
    return p


def small() -> Part:
    return _enclosure("enclosure-small", 60, 40, 25, 2.4)


def deep() -> Part:
    return _enclosure("enclosure-deep", 60, 40, 60, 2.4)


def thickwall() -> Part:
    return _enclosure("enclosure-thickwall", 60, 40, 25, 4.0)


def contradictory() -> Part:
    """Deliberately impossible: the walls consume the height. `requires`
    fails it before a render is attempted — run it to see the parameter
    phase earn its keep."""
    return _enclosure("enclosure-contradictory", 60, 40, 8, 4.0)
