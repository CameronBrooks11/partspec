# partspec documentation

This is where `pyproject.toml`'s `Documentation` URL and `partspec --help` both
point, so it is a router rather than a table of contents: which document answers
which question, and roughly what it costs to read.

## I want to drive the tool

**[AGENT-CONTRACT.md](AGENT-CONTRACT.md)** — read `report.json`, not the console.
What each exit code obliges you to do, the two cases where the exit and the
report disagree on purpose, and what never to do about a failure. At 260 lines
it is a fraction of the specs, and start here rather than with them.

**[FAILURE-MODES.md](FAILURE-MODES.md)** — the observed ways a part is wrong
while every tool in the chain reports success. Read this before deciding a green
run means what you think it means.

## I want to write a contract

**[SPEC-contract.md](SPEC-contract.md)** — the check vocabulary and its grammar,
normatively. Long, and structured for lookup rather than a sitting.

The `skills/contract-authoring` skill is the worked version of the same
material, and
[`examples/`](https://github.com/CameronBrooks11/partspec/tree/main/examples)
has four parts whose READMEs say what each is meant to teach.

## I want to read what the tool produced

**[SPEC-report.md](SPEC-report.md)** — the report schema and the exit codes.
**This is the actual contract; the CLI verbs are not.** Also long, also for
lookup.

**[SPEC-diff.md](SPEC-diff.md)** — how two reports are compared, and why
"no differences found" is a positive claim rather than a fallthrough.

## I want to know why it behaves this way

**[DECISIONS.md](DECISIONS.md)** — every design decision with the reasoning that
produced it, D1 onward. If something here looks arbitrary, it is probably
numbered.

**[POST-V0.md](POST-V0.md)** — what is deliberately not built yet, and why.

**[PLAN.md](PLAN.md)** — **historical.** How v0 was built and what was known
while building it, which is not the current feature set: its own status line
says most of what it lists as "deliberately not in v0" has since shipped. Read
it for the reasoning of that period, not for what the tool does.

## I am extending partspec

**[SPEC-backend.md](SPEC-backend.md)** — the geometry backend protocol: what a
backend must answer, and what it must refuse rather than guess.

**[LINT.md](LINT.md)** — the eight advisory source rules and their two tiers.
Four of them document the false positives they knowingly accept; findings are
data about the source and never a verdict on the part.

---

**Where these files are.** `partspec --docs` prints the directory that every
repo-relative path above — into `docs/` or into `skills/` — resolves against:
the repository root in a checkout, and a bundled copy inside the package in an install, because the
wheel carries both trees (#349). What it does **not** carry is the rest of the
repository, so a citation naming `examples/`, `tests/` or the source tree is a
pointer into the repository rather than a path an install can open.

The specs are normative and were written before the implementation. Where code
and spec disagree, that is a bug in one of them — say which, rather than
silently picking.
