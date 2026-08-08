# bearing-block — one part, two engines, a cited family

A bearing-seat block that exists in OpenSCAD (`block.scad`) and build123d
(`block.py`), with the shared requirements stated once (`claims.py`) and a
parametric family over ISO 15 designations on the OCCT leg. What it teaches:

- **Shared claims assert what both tiers answer exactly** — envelope,
  watertightness, solid count, genus — and only what the requirement fixes
  (`docs/FAILURE-MODES.md` entry 6). The bore's diameter is deliberately NOT
  shared: a 96-gon bore has no cylinder diameter (D15), so `iso15.seat`
  lives on the build123d contract alone, cited.
- **The family follows the standard, not a constant.** Each factory sizes
  the block from `iso15.bearing(n).od`; deriving the width sheds the
  attribution (arithmetic makes it the designer's number), and the seat
  claim is where the standard speaks.
- **The scad leg warns, on purpose.** Its only dimensional bound is the
  derived envelope, so the console prints the unattributed-limits
  disclosure. That warning is correct — this leg alone proves size against
  the design's own numbers — and the cited half of the story is the OCCT
  leg. An exemplar that hid the warning would teach that warnings are
  ignorable.

Fit intent, stated so a machinist does not have to ask: the bore is modelled
at the bearing's **nominal** OD — never with a press/slip allowance baked into
the constant (`docs/FAILURE-MODES.md` entry 4); the real fit is a tolerance
decision made at manufacture. The seat is a plain through-bore, deeper than
the bearing's ISO 15 width (asserted via `requires`); axial retention
(shoulder, circlip) is out of this exemplar's scope on purpose.

```sh
partspec check spec_scad.py:seat_608 spec_py.py:seat_608 spec_py.py:seat_6000 spec_py.py:seat_6200
```

Engine parity between the two legs is asserted by `tests/test_differential.py`;
the family is exercised by `tests/test_examples.py`.
