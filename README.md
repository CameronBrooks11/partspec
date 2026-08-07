# partspec

Verify CAD-as-code parts against declared engineering intent.

> **Status: pre-alpha, and unreleased.** It runs end to end — `check` and `measure`, across
> all three engines — and is being dogfooded on real parts. The check vocabulary is
> deliberately small; [`docs/POST-V0.md`](docs/POST-V0.md) records what is withheld and why.
> Expect the API to move.

## What it is for

You already write down what a part has to be true of — a minimum wall, a bolt circle, a
bore that has to clear an 8 mm shaft. Usually it lives in a README, a comment, or your
head, and nothing checks it. `partspec` lets you declare it next to the model and enforce
it in CI.

This is [`examples/spacer/spec.py`](examples/spacer/spec.py) — the whole contract, less its
docstring:

```python
from partspec import Part, openscad

PLATE = (40.0, 30.0, 6.0)
BORE_D = 8.0
WALL_MIN = 2.0


def spacer() -> Part:
    p = Part("example-spacer", openscad(
        "spacer.scad",
        plate_x=PLATE[0], plate_y=PLATE[1], plate_z=PLATE[2],
        bore_d=BORE_D, wall=WALL_MIN,
    ))

    # Parameter phase — arithmetic over the inputs, no engine needed.
    p.requires("bore_d + 2 * wall <= plate_y")
    p.requires("bore_d > 0")
    p.param("plate_z", min=1.0)

    # Geometry phase.
    p.envelope(max=PLATE)
    p.watertight()
    p.solid_count(1)
    p.genus(1)  # one bore straight through

    return p
```

```console
$ partspec check examples/spacer/spec.py:spacer
  ok   bore_d_2_wall_plate_y
  ok   bore_d_0
  ok   param:plate_z
  ok   builds
  ok   envelope
  ok   watertight
  ok   solid_count
  ok   genus

PASS: 8 pass
  examples/spacer/outputs/spec-spacer/report.json
```

The JSON report is the actual product surface; the console summary is a courtesy. Exit
codes: `0` pass, `1` fail, `2` incomplete, `3` empty, `4` error, `64` bad usage.

Writing a contract for a part you did not model? `partspec measure` dumps every quantity
the backend can honestly produce, with no verdict — so you can see the numbers before
deciding which of them are *intent*. It will not write the checks for you: a check the tool
wrote is a check nobody decided.

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

It also matters on broken output. A CAD engine will happily exit `0` having written a mesh
that is open or non-manifold, and most measurement libraries will then hand you a volume
for it — a number that is not a bad estimate, but not a volume at all. Every measurement
here states its precondition and refuses when it fails, naming the defect:

```console
n/a  volume — volume is the integral over a closed surface; this mesh has 4 non-manifold edge(s)
```

Refusal is kept as narrow as the mathematics allows. An *open* mesh still determines its own
body count, so `solid_count` still answers there; only a non-manifold junction, where
counting through and counting across disagree, makes it refuse. An unnecessary
`unsupported` is its own way of failing to answer an answerable question.

## Engines

| engine | tier | notes |
|---|---|---|
| OpenSCAD | mesh | via binary STL, measured with trimesh |
| build123d | OCCT | native |
| CadQuery | OCCT | adopted into the build123d backend via `.wrapped` — same kernel, no conversion |

One contract, evaluated identically wherever it can be, with honest degradation where it
cannot.

## Install

Not on PyPI yet. From a clone:

```sh
uv sync --all-extras     # or: just setup
uv run partspec check examples/spacer/spec.py:spacer
```

Engines are optional extras — `mesh`, `occt`, `cadquery` — so `uv sync --extra mesh` is
enough for OpenSCAD-only work. The `openscad` binary itself is a system dependency;
`PARTSPEC_OPENSCAD` pins which one is used, and the version is recorded in every report
because it changes the artifact.

**Installing both Python engines with plain `pip`** needs one extra step:

```sh
pip install 'partspec[occt,cadquery]'
pip install --force-reinstall --no-deps cadquery-ocp   # re-assert the VTK build
```

build123d wants `cadquery-ocp-novtk` and CadQuery wants `cadquery-ocp`. Both wheels install
the same top-level `OCP/` package, neither pip nor uv detects the conflict, and whichever
lands last wins — when novtk wins, CadQuery cannot import at all. This repo drops novtk with
a `[tool.uv]` override, but that is a workspace setting and is not carried in wheel
metadata, so a `pip` install has no override in scope. If you skip the second line, partspec
tells you so: the clobber is reported as an environment fault with that command as the hint,
not as a failing part.

## Documentation

The specs are normative and were written before the implementation:

- [`docs/SPEC-report.md`](docs/SPEC-report.md) — the report schema and exit codes. This is
  the actual contract; the CLI verbs are not.
- [`docs/SPEC-contract.md`](docs/SPEC-contract.md) — the Python contract API and check
  vocabulary.
- [`docs/SPEC-backend.md`](docs/SPEC-backend.md) — the geometry backend protocol.
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — every design decision, with its reasoning.
- [`docs/PLAN.md`](docs/PLAN.md) — what v0 is and how it gets built.
- [`docs/POST-V0.md`](docs/POST-V0.md) — what is deliberately not here yet, and why.

## Prior art

`partspec` owes its assertion model to [cad-khana](https://github.com/cyberchitta/cad-khana)
(Apache-2.0), which arrived at declaring claims alongside the model, tri-state results, and
a diagnostics-first CLI independently and first.
[PartCAD](https://github.com/partcad/partcad) is the reference for engine-neutral part
packaging, and its `-D` parameter-passing approach is adopted directly.
[build123d-mcp](https://github.com/pzfreo/build123d-mcp) is the complement on the authoring
side — a stateful interactive session an agent designs *in*; `partspec` is the stateless
gate the result must pass, and deliberately does not own that loop
([D18](docs/DECISIONS.md)).

## License

Apache-2.0.
