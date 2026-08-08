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

```sh
partspec check spec.py:stepper_bracket
```

Exercised by `tests/test_examples.py`. See `docs/FAILURE-MODES.md` entry 4 for
why the envelope bound here is called a change-detector, not proof.
