#!/usr/bin/env python3
"""Fail if more than one OCP provider is installed.

`cadquery-ocp` and `cadquery-ocp-novtk` both install a top-level `OCP/` package,
and pip/uv do NOT detect the conflict — both install and one silently clobbers
the other. build123d depends on the novtk variant while CadQuery wants the
VTK-enabled one, so a project supporting both engines walks straight into it.

PartCAD hits this in production and works around it by re-asserting the
VTK-enabled OCP last, after build123d. Our own spike installed both and worked
only because the resolved versions happened to match — luck, not design.

Run by `just ocp-guard`. Cheap, and the failure it catches is silent.
"""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, distribution

PROVIDERS = ("cadquery-ocp", "cadquery-ocp-novtk")


def main() -> int:
    found: dict[str, str] = {}
    for name in PROVIDERS:
        try:
            found[name] = distribution(name).version
        except PackageNotFoundError:
            continue

    if not found:
        print("no OCP provider installed (fine — the OCCT extra is not in use)")
        return 0

    for name, ver in sorted(found.items()):
        print(f"  {name} {ver}")

    if len(found) > 1:
        print(
            "\nERROR: multiple OCP providers installed. Both own the top-level "
            "OCP/ package, so one has silently clobbered the other.\n"
            "Pin exactly one in pyproject.toml and re-lock.",
            file=sys.stderr,
        )
        return 1

    print("exactly one OCP provider — ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
