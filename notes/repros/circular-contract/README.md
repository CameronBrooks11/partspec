# Repro: a circular contract passes green at any dimension

Run: `partspec check spec.py:circular --quiet; echo $?`

Edit `PY` in `spec.py` and re-run:

| plate_y | exit |
|---|---|
| 30.0 | **0 — pass** |
| 25.0 | **0 — pass** |
| 5.0  | 1 — fail |

Every bound in the contract is recomputed from the same constants the model is built
from, so the dimensional checks (`volume`, `envelope`) cannot fail: change the design
and the contract changes with it. An agent that shrinks the plate to make something
else fit gets a green run and no signal that the part no longer meets its purpose.

**The nuance that makes this useful.** It is not fully vacuous. At `plate_y=5.0` it
*does* fail — `bore_d=8` breaches the 5 mm plate, so `genus`/`solid_count`/`watertight`
catch it. That splits partspec's vocabulary cleanly:

- **Topological checks are naturally non-circular.** `genus(1)` is an absolute claim
  about the part's structure. It cannot be re-derived from the parameters, so it keeps
  working when the parameters move.
- **Dimensional checks are trivially circularizable.** `volume`, `envelope` and `param`
  are only as good as where their numbers came from, and nothing in partspec records
  where that was.

This is the *vacuous green* failure mode from `SPEC-report.md` §1.1 arriving through the
front door — not from an empty part, but from a contract that agrees with the model by
construction. It is what makes epic #5 (external reference values, e.g. the dogfood
`bearing_608` taking `OD = 22.0` from ISO 15 rather than from the `.scad`) the
anti-circularity mechanism rather than a convenience.
