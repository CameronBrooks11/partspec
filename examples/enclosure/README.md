# enclosure — the parameter-phase exemplar

A sealed-cavity box as a parametric family. What it teaches:

- **A family is factories over one model.** `small`, `deep`, `thickwall` are
  parameterisations; one batch invocation checks them all. The fourth,
  `contradictory`, is deliberately impossible — its walls consume the height
  — and `requires` fails it before any engine runs.
- **No dimensional claims, and that is the honest position.** This box has no
  drawing and no standard to cite; asserting its envelope from the numbers it
  is built from would prove the model matches itself
  (`docs/FAILURE-MODES.md` entry 4). Its correctness is topological:
  `watertight`, `solid_count 1`, `genus 0` — sealed means exactly that, and
  nothing visual measures it (entry 3 is what a breached cavity looks like:
  fine). When a real requirement arrives, its numbers join as cited limits.

```sh
partspec check spec.py:small spec.py:deep spec.py:thickwall   # exit 0
partspec check spec.py:contradictory                          # exit 1, in milliseconds
```

Exercised by `tests/test_examples.py`.
