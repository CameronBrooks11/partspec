"""partspec — verify CAD-as-code parts against declared engineering intent.

Importing this package MUST NOT pull in a CAD engine. build123d, CadQuery,
trimesh, manifold3d and OCP are all imported lazily inside their backends, which
keeps the parameter phase and `--list` fast and makes the rule structural rather
than a convention someone has to remember (SPEC-contract.md 1.1).
"""

from __future__ import annotations

from .backend import BBox, BuildError, GeometryBackend, Tier, Unsupported, Vec3
from .report import CheckResult, Report, write_placeholder
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
    "BBox",
    "BuildError",
    "CheckResult",
    "ContractError",
    "GeometryBackend",
    "Limit",
    "Measurement",
    "Report",
    "Status",
    "Tier",
    "Unsupported",
    "Vec3",
    "Verdict",
    "adjudicate",
    "epsilon",
    "exit_code",
    "verdict_of",
    "write_placeholder",
]
