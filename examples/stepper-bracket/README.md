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
- **Three claims about SPACE**, which is the worked `keep_out` / `keep_in`
  example the tree had none of (#200):

  ```python
  from partspec import region
  from partspec.refs import nema17

  # The motor's locating boss must find nothing in its way.
  p.keep_out(
      region.cylinder(d=nema17.PILOT_BOSS, h=2.0, at=(0.0, 0.0, 34.0), axis="y"),
      shell=0.6,
      id="pilot-boss-clearance",
  )
  # The corner must carry material in BOTH members — two boxes, because one
  # cannot say it (see below).
  p.keep_in(region.box(min=(-26.0, 0.5, 0.5), max=(26.0, 4.5, 12.0)), shell=1.0,
            id="joint-web-plate")
  p.keep_in(region.box(min=(-26.0, 0.5, 0.5), max=(26.0, 12.0, 4.5)), shell=1.0,
            id="joint-web-base")
  ```

  **`axis` is a string** — `"x"`, `"y"` or `"z"`, never a vector; `(0, 0, 1)`
  is refused, and two fleet agents on different engines guessed it anyway.

  **One axis-aligned box cannot express the joint.** The members are
  perpendicular slabs (the plate is `y ∈ [0, 5]`, the base is `z ∈ [0, 5]`), so
  a box needing material from both would also span the concave quarter outside
  the L, which is air. Hence two, each leaving the shared corner into one
  member's own territory — and which one fails tells you which member lost
  material.

  **A region proves nothing about a member it never enters.** Both ways of
  getting that wrong were shipped in drafts of this example. The first box lay
  inside the plate's 5 mm thickness, so the plate alone satisfied it and it
  passed with the base cut to a third of its width. The second reached further
  into base-only material — *away* from the plate — so the base alone
  satisfied it and it passed on a bracket with **no plate at all**, while a
  93%-severed joint left the contract nine-of-nine green. Check a region by
  breaking the model and watching it fail; it is the only way to know.

  **A region covers exactly what it spans.** `±26` of a 56 mm joint is 93% of
  it; a sever confined to the last 2 mm at each end passes. Choose the number
  and say why.

  **`shell` is what stops a region passing vacuously — when it can.** An
  absent part has an empty region too, so `keep_out` pairs "no material here"
  with "material near here", and it does real work above: remove the pilot
  bore and the region fails, remove the plate and the *shell* fails. On these
  two `keep_in`s it is **inert**, though the API requires it. A keep-in's
  shell exists to fail a solid brick, by demanding some emptiness near the
  region; these are rooted 0.5 mm from the bracket's outer faces, so their
  shells escape into free space and are never entirely solid — for the L and
  for a brick alike. It earns its keep on the shape `keep_in`'s docstring
  describes, a boss or pin standing proud. Here the envelope and `solid_count`
  are what exclude the brick.

  The keep-out earns its place beside `nema17.mount`: that call declares the
  pilot *bore* through `hole_diameter`, a cylinder-precision claim the mesh
  tier refuses because a faceted bore has no diameter. The same requirement
  stated as space is a claim about volume, which both tiers answer. Note that
  a region's numbers do **not** reach `checks[].source` even when they come
  from `refs` — see #250.

```sh
partspec check spec.py:stepper_bracket
```

Exercised by `tests/test_examples.py`. See `docs/FAILURE-MODES.md` entry 4 for
why the envelope bound here is called a change-detector, not proof.
