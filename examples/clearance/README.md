# Clearance — part-versus-part interference, one part at a time

partspec's unit of verification is the single part, and stays that way through
v1.0 (D19). An assembly verb that takes N parts at their poses and reports
pairwise shared volume is a post-1.0 question (`SPEC-contract.md` §9).

This example is the pattern that does that work today: model
`intersection() { A; B; }` **at assembly pose** as a part of its own, and claim
the outcome the design intends.

## The two outcomes that are portable

Every pair of parts in an assembly is in exactly one of three states, and each
one grades on a different measurand. **Two of the three answer the same way on
every engine. This example declares those two**, and measures the third below
rather than recommending it:

| the two parts | the probe builds to | the claim | measured here |
|---|---|---|---|
| interpenetrate | a solid | `p.volume(min=, max=)` | 24.0 mm³ |
| share no space | nothing | `p.empty()` | pass |
| touch on a face | a sheet | `p.area(min=)` | **kernel-dependent — see below** |

Run them:

```
partspec check examples/clearance/spec.py:interference
partspec check examples/clearance/spec.py:clearance
```

## What the files are for

- **`assembly.scad`** — the parts, each at the pose it occupies in the product,
  and nothing else. Poses live here so that an interference number is the
  *assembly's* interference rather than a number about geometry sitting at the
  origin. Move a part by editing this file and every probe follows it.
- **`interference.scad`**, **`clearance.scad`** — one probe each, both of them
  two module calls inside an `intersection()`.
- **`spec.py`** — the two contracts.

## What will bite

**`empty` is for the probe that should be empty, and for nothing else.** On the
interference probe an empty build is the *loose joint* — the failure — so that
contract deliberately does not declare `empty` and fails its build if the
flanks ever stop touching. And declare `empty` alone: an empty part has no
mesh, so every other geometry check on it is skipped (§4.12).

## What the pattern costs

One extra source and one extra target per pair, the pair modelled at assembly
pose, and no automatic all-pairs sweep — you write the pairs you care about.
That is the whole of it; #236 is the issue that measured it.

## The third outcome, and why it is not here

**Face contact is not portable, and it is the only one of the three that is
not.** A probe of two parts that merely touch is a zero-thickness result, and
what an engine does with one is a property of its kernel rather than of the
design. `assembly.scad` still carries `cover()`, seated flat on the rail, so
the case has a referent — but no contract claims it.

Two pinned engines, one source, opposite answers. `intersection()` of two 10 mm
cubes at three offsets, exported with `--export-format binstl`, then the same
three sources through `partspec check` declaring `p.empty()`:

| probe | 2021.01 export | 2026.08.01 export | `check` 2021.01 | `check` 2026.08.01 |
|---|---|---|---|---|
| interpenetrate (offset 5) | rc 0, 684 B | rc 0, 684 B | exit 1 | exit 1 |
| **touch on a face (offset 10)** | rc 0, **284 B** | rc 1, **0 B** | **exit 1** | **exit 0** |
| share no space (offset 20) | rc 1, 0 B | rc 1, 0 B | exit 0 | exit 0 |

One source, two engines, opposite verdicts — [F13](../../docs/FAILURE-MODES.md),
on the very pattern this example teaches. And the older engine is the one that
is *wrong*: under the settled semantics of `empty` (#270) it means **no
positive-volume interference**, a zero-thickness contact has no positive volume,
and so it should pass. 2026.08.01 gives the semantically correct answer, which
is why the divergence cannot be resolved by preferring the richer result.

The seated face in **this** assembly diverges a third way, which is worse than
either: both engines write a 4-triangle sheet, and they do not agree on its
shape.

| | `rail() ∩ cover()` corners | `area` |
|---|---|---|
| 2021.01 | (2, 0), (18, 0), (18, 12), (2, 12) — the 16 × 12 rectangle | 384.0 mm² |
| 2026.08.01 | (2, 0), (18, 6.6), (18, 12), (2, 11.4) — a skewed quad | 268.8 mm² |

So the newer engine does not always *drop* a zero-thickness result; here it
retains a degenerate one and reports a number no reader would question. That is
the failure this project exists to refuse, arriving through the geometry rather
than through the contract.

**What would make face contact expressible.** #314 — recording whether the
kernel retains a zero-thickness result — is the enabler. Once a run can state
which behaviour was in force, an `area` claim over a contact patch means
something; before that it means whichever engine the CI image happens to
install. Until then, if you need bearing area, measure it on a part that has
thickness: give the seat a deliberate interference and grade the **volume**.

None of this narrows what #236 asked for. Its measured interferences — eight
numbers across six rows, 192,318 / 43,234 / 61,575 / 32,723 / 14,328 / 1,691 /
693 / 56.6 mm³ — are every one of them positive volume, and not one is face
contact. The two outcomes that ship portably cover every case that motivated
the report.
