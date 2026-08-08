# partspec

Verify CAD-as-code parts against declared engineering intent.

> **Status: pre-alpha; v0.4.0 is on PyPI.** It runs end to end — `check` and `measure`
> across all three engines, `diff` on the reports they produce, `render` on the mesh tier — and is dogfooded on real
> parts. The vocabulary covers real mechanical intent: keep-out/keep-in regions,
> `hole_diameter`, `bolt_circle` and `fillet_radius` on the OCCT tier. The loop is built
> to run unattended: every build is bounded (`--timeout`), `check` takes many targets in
> one process, a committed claims pin (`--pin`/`--expect`) catches a contract that shrank
> with no baseline in hand, and the rules an agent follows are
> [`docs/AGENT-CONTRACT.md`](https://github.com/CameronBrooks11/partspec/blob/main/docs/AGENT-CONTRACT.md).
> [`docs/POST-V0.md`](https://github.com/CameronBrooks11/partspec/blob/main/docs/POST-V0.md) records what is still withheld and why.
> Expect the Python API to move: the stable surface is the report schema plus the exit
> codes, and `partspec.run()` is internal.

## What it is for

You already write down what a part has to be true of — a minimum wall, a bolt circle, a
bore that has to clear an 8 mm shaft. Usually it lives in a README, a comment, or your
head, and nothing checks it. `partspec` lets you declare it next to the model and enforce
it in CI.

This is [`examples/spacer/spec.py`](https://github.com/CameronBrooks11/partspec/blob/main/examples/spacer/spec.py) — the whole contract, less its
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
  ok   bore_d_2_wall_le_plate_y
  ok   bore_d_gt_0
  ok   param:plate_z
  ok   builds
  ok   envelope
  ok   watertight
  ok   solid_count
  ok   genus

PASS: 8 pass
  every dimensional limit on 'example-spacer' is unattributed: bounds derived from the model's own numbers prove the model matches itself (partspec.refs carries cited values; SPEC-contract.md 10)
  /home/user/partspec/examples/spacer/outputs/spec-spacer/report.json
```

The JSON report is the actual product surface; the console summary is a courtesy. Exit
codes: `0` pass, `1` fail, `2` incomplete, `3` empty, `4` error, `64` bad usage
(`130` is the SIGINT convention, not a verdict).

That last warning line is the tool being honest about its own example: every bound above
is derived from the same constants the model is built from, so this contract proves the
model matches itself — real external footing looks like
`p.hole_diameter(iso15.bearing(608).od)`, where the number arrives from `partspec.refs`
with its citation recorded in the report.

`partspec lint` gives advisory findings about the source itself — magic numbers,
unused parameters, oversize modules — before a render is ever attempted; the rules and
their exact predicates are
[`docs/LINT.md`](https://github.com/CameronBrooks11/partspec/blob/main/docs/LINT.md).
How to write a contract that proves something — check selection, limit provenance, the
retrofit path — is
[`skills/contract-authoring/`](https://github.com/CameronBrooks11/partspec/tree/main/skills/contract-authoring).
Worked exemplars beyond the spacer live in
[`examples/`](https://github.com/CameronBrooks11/partspec/tree/main/examples) — a cited
NEMA 17 bracket, a two-engine bearing-seat family, a sealed enclosure — each with a README
saying what to imitate and why.

Writing a contract for a part you did not model? `partspec measure` dumps every quantity
the backend can honestly produce, with no verdict — so you can see the numbers before
deciding which of them are *intent*. It will not write the checks for you: a check the tool
wrote is a check nobody decided.

**If the author is an AI agent, `partspec` is the gate at the end of its loop.** The
authoring session owns making the part; `partspec` proves the result against intent the
model does not contain, and persists the proof — that boundary is
[D18](https://github.com/CameronBrooks11/partspec/blob/main/docs/DECISIONS.md). The `mcp`
extra puts the gate in the agent's tool list: `check` returns the same report the CLI
writes, `measure` and `render` the same output as their verbs, every call a fresh stateless
evaluation. And the loop is measured, not assumed: in the seeded-defect eval suite
([`evals/`](https://github.com/CameronBrooks11/partspec/tree/main/evals)), an agent shown
only the report — no shell, no hints, contract frozen — repaired all five defect classes in
a single edit each, without once weakening its contract. The rules of that loop — bounded
attempts, what each exit code instructs, greppable escalation, and the guards watching the
weakening moves — are
[`docs/AGENT-CONTRACT.md`](https://github.com/CameronBrooks11/partspec/blob/main/docs/AGENT-CONTRACT.md).

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

```sh
pip install 'partspec[mesh]'      # OpenSCAD parts — the smallest useful install
```

Or for development, from a clone:

```sh
uv sync --all-extras     # or: just setup
uv run partspec check examples/spacer/spec.py:spacer
```

Engines are optional extras — `mesh`, `occt`, `cadquery` — so `uv sync --extra mesh` is
enough for OpenSCAD-only work. The `mcp` extra adds `partspec-mcp`, a stdio MCP server
exposing `check`, `measure` and `render` as stateless tools: each call runs the CLI in a
fresh subprocess and returns its artifact, per the boundary in [D18](https://github.com/CameronBrooks11/partspec/blob/main/docs/DECISIONS.md). The `openscad` binary itself is a system dependency;
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

- [`docs/SPEC-report.md`](https://github.com/CameronBrooks11/partspec/blob/main/docs/SPEC-report.md) — the report schema and exit codes. This is
  the actual contract; the CLI verbs are not.
- [`docs/SPEC-contract.md`](https://github.com/CameronBrooks11/partspec/blob/main/docs/SPEC-contract.md) — the Python contract API and check
  vocabulary.
- [`docs/SPEC-backend.md`](https://github.com/CameronBrooks11/partspec/blob/main/docs/SPEC-backend.md) — the geometry backend protocol.
- [`docs/DECISIONS.md`](https://github.com/CameronBrooks11/partspec/blob/main/docs/DECISIONS.md) — every design decision, with its reasoning.
- [`docs/PLAN.md`](https://github.com/CameronBrooks11/partspec/blob/main/docs/PLAN.md) — what v0 is and how it gets built.
- [`docs/POST-V0.md`](https://github.com/CameronBrooks11/partspec/blob/main/docs/POST-V0.md) — what is deliberately not here yet, and why.

## Prior art

`partspec` owes its assertion model to [cad-khana](https://github.com/cyberchitta/cad-khana)
(Apache-2.0), which arrived at declaring claims alongside the model, tri-state results, and
a diagnostics-first CLI independently and first.
[PartCAD](https://github.com/partcad/partcad) is the reference for engine-neutral part
packaging, and its `-D` parameter-passing approach is adopted directly.
[build123d-mcp](https://github.com/pzfreo/build123d-mcp) is the complement on the authoring
side — a stateful interactive session an agent designs *in*; `partspec` is the stateless
gate the result must pass, and deliberately does not own that loop
([D18](https://github.com/CameronBrooks11/partspec/blob/main/docs/DECISIONS.md)).

## License

Apache-2.0.
