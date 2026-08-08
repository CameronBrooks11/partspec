"""Reference data: real numbers from named sources, importable (epic #5).

Every table here is pure data with zero dependencies, and every value is a
`Referenced` float that carries its citation into the report.

Scope policy (SPEC-contract.md 10.1): **dimensional interface facts** that are
widely published and independently verifiable — boundary dimensions, bolt
patterns, envelope sizes. Never a reproduction of a standard's text, figures or
tolerancing tables: a citation points at the document; it does not replace it.
"""

from . import iso15, nema17

__all__ = ["iso15", "nema17"]
