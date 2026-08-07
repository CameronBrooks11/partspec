**What changed and why:**

- The core stays exactly where the contract puts it — concentric, 10 mm, untouched. Shrinking it or shifting it into a surface pocket would have satisfied `solid_count` but broken the stated intent (`volume` is what fixes the core at 10 mm).
- A Ø3 mm bore runs from the core's top face (z = 5) out through the block's top face (z = 10), turning the enclosed cavity into an open one. Two shells become one.
- The bore overshoots both ends (spans z = 4 → 11) so no cut plane is coplanar with a retained face — the lower 1 mm is already inside the core and the upper 1 mm is outside the block, so neither contributes removed material.

**Expected effect on each check:**

| check | before | after |
|---|---|---|
| envelope | 20/20/20 ✓ | unchanged — the bore only pierces an existing face |
| volume | 7000.0 ✓ | 7000 − π·1.5²·5 ≈ **6964.7**, band is 6930–7070 (~35 mm³ of ~70 margin used) |
| watertight | true ✓ | still a closed manifold |
| solid_count | **2** ✗ | **1** |

The one real cost is that the vent consumes about half the available volume tolerance. If a bore is unacceptable for this part's function, the alternative is opening the core to a face as a blind pocket — same 1000 mm³ removed, zero tolerance spent — but that abandons "concentric," which the spec's docstring states explicitly, so I did not take it.
