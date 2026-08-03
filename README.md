# partspec

Verify CAD-as-code parts against declared engineering intent.

> **Status: pre-alpha.** The report/status seam is implemented. The contract API and the
> geometry backends are not. There is nothing useful to run yet.

## What it is for

You already write down what a part has to be true of — a minimum wall, a bolt circle, a
bore that has to clear an 8 mm shaft. Usually it lives in a README, a comment, or your
head, and nothing checks it. `partspec` lets you declare it next to the model and enforce
it in CI.

```python
from partspec import Part, openscad

def lock() -> Part:
    p = Part("bayonet-lock-pin", openscad(
        "bayonet_lock.scad",
        half="lock", interface_radius=8, allowance=0.2,
        part_height=8, shell_thickness=2.5, pin_radius=1.0,
    ))
    p.requires("pin_radius + allowance/2 <= shell_thickness")
    p.envelope(max=(40, 40, 15))
    p.watertight()
    return p
```

```console
$ partspec check parts/bayonet:lock
```

## The idea it is built around

A verification tool that reports a green result it has not earned is worse than no tool,
because it converts an open question into a false assurance. So `partspec` has five check
statuses and **only one of them is green**:

| status | meaning |
|---|---|
| `pass` | evaluated and satisfied, conclusively |
| `fail` | evaluated and violated, conclusively |
| `approximate` | evaluated, but the error interval straddles the limit — indeterminate |
| `unsupported` | this backend cannot evaluate this check on this geometry at all |
| `skipped` | not evaluated |

A part whose checks were mostly unavailable exits `2`, not `0`. A contract that asserts
nothing exits `3`. Neither is a pass, because neither established anything.

This matters most across engines. OpenSCAD emits a triangle mesh, which has no cylindrical
faces — so a hole diameter is genuinely unanswerable there, and `partspec` says so instead
of fitting a circle to the facets and reporting a confident wrong number. (An OpenSCAD
`cylinder($fn=16)` is a real 16-sided prism: fitting recovers Ø10.000 for a bore that
actually clears Ø9.808, and the error is always in the unsafe direction.)

## Engines

| engine | tier | notes |
|---|---|---|
| OpenSCAD | mesh | via binary STL + trimesh/manifold3d |
| build123d | OCCT | native |
| CadQuery | OCCT | adopted into the build123d backend via `.wrapped` — same kernel, no conversion |

One contract, evaluated identically wherever it can be, with honest degradation where it
cannot.

## Documentation

The specs are normative and were written before the implementation:

- [`docs/SPEC-report.md`](docs/SPEC-report.md) — the report schema and exit codes. This is
  the actual contract; the CLI verbs are not.
- [`docs/SPEC-contract.md`](docs/SPEC-contract.md) — the Python contract API and check
  vocabulary.
- [`docs/SPEC-backend.md`](docs/SPEC-backend.md) — the geometry backend protocol.
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — every design decision, with its reasoning.
- [`docs/PLAN.md`](docs/PLAN.md) — what v0 is and how it gets built.

## Prior art

`partspec` owes its assertion model to [cad-khana](https://github.com/cyberchitta/cad-khana)
(Apache-2.0), which arrived at declaring claims alongside the model, tri-state results, and
a diagnostics-first CLI independently and first.
[PartCAD](https://github.com/partcad/partcad) is the reference for engine-neutral part
packaging, and its `-D` parameter-passing approach is adopted directly.

## License

Apache-2.0.
