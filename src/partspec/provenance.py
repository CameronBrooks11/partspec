"""Referenced values: numbers that know where they came from.

The deepest dogfood finding (epic #5): every catch came from a *human* supplying
the external reference — ISO 15's 22 mm, the NEMA bolt pattern. A limit is only
as good as where its number came from, and until now nothing recorded where that
was. A `Referenced` value IS its number (a float subclass — it renders, compares
and serialises as one) and additionally carries the source that vouches for it;
a contract method receiving one records the source on the check, and the report
states not just what was claimed but on whose authority.

Two deliberate properties:

- **Arithmetic sheds the attribution.** `bearing(608).od + 0.1` is a plain
  float: the derived number is the author's, not the standard's, and carrying
  the source across an operation the standard never performed would launder
  authority. An author deriving a bound owns it — which is exactly what #50's
  attributed/unattributed axis measures.
- **Attribution is additive, never required.** A bare literal behaves exactly
  as before and simply carries nothing.

Spec: SPEC-contract.md 10.
"""

from __future__ import annotations

from typing import Any

__all__ = ["Referenced", "source_map"]


class Referenced(float):
    """A float carrying the provenance of its value.

    `source` is a small JSON-ready mapping, conventionally
    `{"standard": ..., "subject": ..., "field": ...}` — enough for a reader to
    find the number in the cited document, never a reproduction of it.
    """

    __slots__ = ("source",)

    source: dict[str, Any]

    def __new__(cls, value: float, source: dict[str, Any]) -> Referenced:
        self = super().__new__(cls, value)
        self.source = dict(source)
        return self

    def __repr__(self) -> str:  # float repr, so reports and errors stay plain
        return float.__repr__(self)

    def __getnewargs__(self) -> tuple[float, dict[str, Any]]:  # type: ignore[override]
        """Pickle and the copy protocols re-call __new__ with the original
        arguments; without this every deepcopy of a contract holding a
        referenced bound crashed with a message that named nothing."""
        return (float(self), self.source)


def source_map(**named_values: Any) -> dict[str, dict[str, Any]] | None:
    """Collect the sources of the referenced values among a check's inputs.

    Returns `{field_name: source}` for every input that is `Referenced` —
    descending one level into tuples with `name.i` keys, for vector bounds —
    or None when nothing carries attribution, so the report field is absent
    rather than empty.
    """
    out: dict[str, dict[str, Any]] = {}
    for name, value in named_values.items():
        if isinstance(value, Referenced):
            out[name] = value.source
        elif isinstance(value, tuple | list):
            for i, component in enumerate(value):
                if isinstance(component, Referenced):
                    out[f"{name}.{i}"] = component.source
    return out or None
