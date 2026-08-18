# stepper-bracket — the citation exemplar

An L-bracket mounting a NEMA 17 stepper, in build123d. What it teaches:

- **The interface is one cited call.** `nema17.mount(p)` declares the pilot
  bore and the Ø43.815 bolt circle with NEMA ICS 16's own numbers; the report
  carries the citation (`checks[].source`) and `attribution` shows a limit
  with external footing. The clearance diameters (Ø3.4, Ø22.3) stay the
  designer's — a fragment never launders your numbers into a standard's.
- **Model structure**: parameterised factory (`bracket(**params)`), features
  decomposed into named functions, holes located off one datum (the motor
  face centre) rather than accumulated offsets. A part written this way is a
  part whose contract is obvious to write.
- **`requires` before geometry**: the motor-face-fits arithmetic fails in
  milliseconds on a bracket too short to carry it.
- **Two claims about SPACE**, which is the worked `keep_out` / `keep_in`
  example the tree had none of (#200):

  ```python
  from partspec import region

  # The motor's locating boss must find nothing in its way.
  p.keep_out(
      region.cylinder(d=nema17.PILOT_BOSS, h=2.0, at=(0.0, 0.0, 34.0), axis="y"),
      shell=0.6,
      id="pilot-boss-clearance",
  )
  # The L's inside corner must be solid where the plate becomes the base.
  p.keep_in(
      region.box(min=(-20.0, 0.5, 0.5), max=(20.0, 12.0, 4.5)),
      shell=1.0,
      id="plate-base-joint",
  )
  ```

  Three things to take from it. **`axis` is a string** — `"x"`, `"y"` or
  `"z"`, never a vector; `(0, 0, 1)` is refused, and two fleet agents on
  different engines guessed it anyway. **`shell` is what stops the check
  passing vacuously**: an absent part has an empty region too, so `keep_out`
  pairs "no material here" with "material near here", and `keep_in` pairs
  "all material here" with "not all material just outside". And **a region
  has to reach where the claim is** — the first draft of the joint box sat
  inside the plate's own 5 mm thickness, so the plate alone satisfied it and
  it passed with the base cut to a third of its width. Reaching to y = 12
  puts most of it where only the base can supply material.

  The keep-out earns its place beside `nema17.mount`: that call declares the
  pilot *bore* through `hole_diameter`, a cylinder-precision claim the mesh
  tier refuses because a faceted bore has no diameter. The same requirement
  stated as space is a claim about volume, which both tiers answer.

```sh
partspec check spec.py:stepper_bracket
```

Exercised by `tests/test_examples.py`. See `docs/FAILURE-MODES.md` entry 4 for
why the envelope bound here is called a change-detector, not proof.
