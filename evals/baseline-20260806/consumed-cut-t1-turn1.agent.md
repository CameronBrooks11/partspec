One-line change in `model.scad:4`: `core = 30` → `core = 10`.

How that lines up with the contract:

- **builds** — the cut no longer consumes the body, so the difference yields real geometry instead of an empty result.
- **envelope** — outer cube is untouched at 20 mm on each axis, inside the ±0.1 band.
- **volume** — 20³ − 10³ = 7000 mm³, exactly `VOLUME`.
- **watertight** — the core is strictly interior, so the outer shell and the cavity shell are both closed.
- **solid_count** — one connected body containing an enclosed void.

One thing worth flagging: the resulting part has a fully sealed internal cavity with no opening. That is what the contract specifies (a 10 mm concentric core, nothing pinning an access path), and it's what the volume figure requires, but it is unprintable as-is on a subtractive or FDM process without a drain/access feature. If that void was meant to be reachable, the contract would need a change — which is outside what I can touch here.

I did not run `partspec`.
