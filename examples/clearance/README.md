# Clearance — part-versus-part interference, one part at a time

partspec's unit of verification is the single part, and stays that way through
v1.0 (D19). An assembly verb that takes N parts at their poses and reports
pairwise shared volume is a post-1.0 question (`SPEC-contract.md` §9).

This example is the pattern that does that work today: model
`intersection() { A; B; }` **at assembly pose** as a part of its own, and claim
the outcome the design intends.

## The three outcomes

Every pair of parts in an assembly is in exactly one of three states, and each
one grades on a different measurand:

| the two parts | the probe builds to | the claim | measured here |
|---|---|---|---|
| interpenetrate | a solid | `p.volume(min=, max=)` | 24.0 mm³ |
| touch on a face | a sheet | `p.area(min=)` | 384.0 mm² |
| share no space | nothing | `p.empty()` | pass |

Run them:

```
partspec check examples/clearance/spec.py:interference
partspec check examples/clearance/spec.py:seat
partspec check examples/clearance/spec.py:clearance
```

## What the files are for

- **`assembly.scad`** — the parts, each at the pose it occupies in the product,
  and nothing else. Poses live here so that an interference number is the
  *assembly's* interference rather than a number about geometry sitting at the
  origin. Move a part by editing this file and every probe follows it.
- **`interference.scad`**, **`seat.scad`**, **`clearance.scad`** — one probe
  each, every one of them two module calls inside an `intersection()`.
- **`spec.py`** — the three contracts.

## Two things that will bite

**A sheet has two sides and `area` counts both.** The seated face is 16 × 12 =
192 mm², and the probe measures **384**. The claim doubles the bearing area it
wants rather than being written as if the sheet were a face
(`SPEC-contract.md` §4.2).

**`empty` is for the probe that should be empty, and for nothing else.** On the
interference probe an empty build is the *loose joint* — the failure — so that
contract deliberately does not declare `empty` and fails its build if the
flanks ever stop touching. And declare `empty` alone: an empty part has no
mesh, so every other geometry check on it is skipped (§4.12).

## What the pattern costs

One extra source and one extra target per pair, the pair modelled at assembly
pose, and no automatic all-pairs sweep — you write the pairs you care about.
That is the whole of it; #236 is the issue that measured it.
