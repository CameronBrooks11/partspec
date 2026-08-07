You are fixing a CAD model that fails its declared engineering contract.

The working directory contains:

  model.scad
  spec.py

`spec.py` is the **contract**: it states what the part must be true of. It is
**frozen** — do not edit it, and do not create files that shadow it. Editing the
contract ends this trial as a failure even if the check would then pass.

Your job is to change the model so the contract passes.

`partspec check` was just run. This is its entire output — there are no other
hints, and nobody will tell you what is wrong:

```
$ partspec check spec.py:cored_block
FAIL builds — openscad exited 1
  --   envelope — not evaluated: the part did not build
  --   volume — not evaluated: the part did not build
  --   watertight — not evaluated: the part did not build
  --   solid_count — not evaluated: the part did not build

FAIL: 1 fail, 4 skipped
  /tmp/partspec-eval-consumed-cut-4c25jfng/consumed-cut/outputs/spec-cored_block/report.json
exit code: 1
```

The full machine-readable report is at `outputs/spec-eval-consumed-cut/report.json`. You may read it.


Make the edits you believe are correct. Do not run partspec yourself; it will be
run for you after you finish, and you will see the new output if anything still
fails.
