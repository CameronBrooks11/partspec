# spacer — the smallest honest contract

The example the front page inlines, and the one to read first. It exists to show
the *whole* loop on a part small enough to hold in your head: an OpenSCAD source,
a contract beside it, and a report that says which claims were proven.

```console
$ partspec check examples/spacer/spec.py:spacer
```

Every other exemplar teaches something extra. `bearing-block` runs the *shared*
claims against both engines — not one identical contract, which is the point: the
build123d leg adds the cited seat diameter, and the OpenSCAD leg omits it because
a 96-gon bore has no diameter to measure. `stepper-bracket` reduces a whole
mounting interface to one cited call, `nema17.mount(p)`. `enclosure` is one
factory with four members, three ordinary and one whose walls consume its own
height — `requires` disproves that member in the parameter phase, before a render
is attempted. This one teaches nothing extra on purpose.

## What it claims, and why each claim is here

| claim | what it catches |
|---|---|
| `requires("bore_d + 2 * wall <= plate_y")` | a bore that cannot leave the wall the design asks for — decided from the parameters, before any geometry exists |
| `requires("bore_d > 0")` | a degenerate bore, for the same price |
| `param("plate_z", min=1.0)` | a plate driven to zero or negative thickness by a caller |
| `envelope(max=PLATE)` | a part that grew past the space it has to live in |
| `watertight()` | a mesh that looks right and is not a solid |
| `solid_count(1)` | a boolean that quietly left two bodies |
| `genus(1)` | the bore stopped being a through-hole — a blind hole is genus 0, and a hole that reaches the edge is a notch (`docs/FAILURE-MODES.md` entry 3) |

The last two are the interesting pair. A spacer whose bore has drifted off the
edge is still watertight, still one solid, still inside its envelope, and no
longer a spacer. `genus` is the claim that notices.

## The point of the exercise

Read `spec.py` and note what is *not* in it: no assertion that the file exists,
no check that OpenSCAD ran, no test that the export is non-empty. `builds` is
implicit and always present, so those are the tool's job, not the author's. What
is left is engineering intent — the numbers a reviewer would ask about.

Then run `partspec measure examples/spacer/spec.py:spacer` and compare. `measure`
reports everything the tier can answer; the contract asserts the subset that is
*intent*. Deciding which numbers are intent is the whole skill, and
`skills/contract-authoring/SKILL.md` is the guide to it.
