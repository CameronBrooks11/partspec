"""partspec — verify CAD-as-code parts against declared engineering intent.

Importing this package MUST NOT pull in a CAD engine. build123d, CadQuery,
trimesh, manifold3d and OCP are all imported lazily inside their backends, which
keeps the parameter phase fast and makes the rule structural rather than a
convention someone has to remember (SPEC-contract.md 1.1).
"""

from __future__ import annotations

from . import refs, region
from .backend import BuildError, GeometryBackend, Tier, Unsupported, Vec3
from .contract import CheckSpec, Part, Source, build123d, cadquery, openscad
from .provenance import Referenced
from .report import CheckResult, Report, write_placeholder

# Re-exported for the callers that already import it, but deliberately NOT in
# `__all__`: the stable surface is the report schema and the exit codes, and
# README has called `run()` internal since v0.1 while `__all__` said otherwise.
# The `as run` form is the explicit-re-export convention, so this is a decision
# rather than an import ruff would flag as unused.
from .runner import run as run
from .status import (
    ContractError,
    Limit,
    Measurement,
    Status,
    Verdict,
    adjudicate,
    epsilon,
    exit_code,
    verdict_of,
)

__all__ = [
    "BuildError",
    "CheckResult",
    "CheckSpec",
    "ContractError",
    "GeometryBackend",
    "Limit",
    "Measurement",
    "Part",
    "Referenced",
    "Report",
    "Source",
    "Status",
    "Tier",
    "Unsupported",
    "Vec3",
    "Verdict",
    "adjudicate",
    "build123d",
    "cadquery",
    "epsilon",
    "exit_code",
    "openscad",
    "refs",
    "region",
    "verdict_of",
    "write_placeholder",
]
