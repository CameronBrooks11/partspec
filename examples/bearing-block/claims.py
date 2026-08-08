"""The shared claims — stated once, imported by both engines' contracts.

The rule this module exemplifies is `docs/FAILURE-MODES.md` entry 6: shared
claims assert only what the *requirement* fixes, and only what both tiers
answer exactly. The block's envelope, its single-solid topology, and the one
through-bore (genus 1) hold identically for a 96-gon bore and a true cylinder.
The bore's *diameter* does not — it is a cylinder-precision claim, so
`iso15.seat` is declared only on the OCCT engine's contract, cited.
"""

from partspec import Part


def shared_claims(p: Part, *, bore_d: float, wall: float = 8.0, depth: float = 12.0) -> Part:
    w = bore_d + 2 * wall
    # Parameter phase: provable before any engine runs, on either engine.
    p.requires("wall >= 5.0")
    p.requires("depth >= 8.0")
    # Geometry both tiers answer exactly: the box is the box, the bore is
    # inside it, and one through-hole is genus 1 whatever its cross-section.
    p.envelope(max=(w, depth, w))
    p.watertight()
    p.solid_count(1)
    p.genus(1)
    return p
