# Security

## The trust boundary

`partspec` **imports and executes** the contract module it is given, and the model files
that contract reaches — `exec()` in `target.py` for the contract and `pycad.py` for a
Python model, because running them is how the tool learns what you claimed and how the
part gets built. There is no sandbox and none is planned.

A contract is therefore code, with the privileges of the process running `partspec`.
Import-scope statements run before any validation, so they run even on a contract the tool
subsequently rejects. Read a contract you were handed before you run it, the same as any
other Python.

`requires` expressions are the one exception, and only in a narrow sense: they are
evaluated against the declared params with no imports, attribute access or calls
(`SPEC-contract.md` §5.1). That is a *legibility* boundary, not a security one — it exists
so the tool can print an expression's operands. The contract around it is unrestricted
Python.

Reports are data, not code. `report.json`, `render.json` and the lint payload are consumed
by parsing, never by evaluation.

## Reporting a vulnerability

Report privately through GitHub:
<https://github.com/CameronBrooks11/partspec/security/advisories/new>

Please do not open a public issue for a security report.

Since partspec executes what it is pointed at by design, "a contract can run arbitrary
code" is documented behaviour rather than a vulnerability. Reports that are in scope
include anything that executes code the user did **not** point the tool at — a path in a
report or lint payload that gets evaluated rather than parsed, a resolved `include`
escaping the closure it was declared in, or the MCP server running something the caller
never named.
