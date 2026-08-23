# partspec documentation

This is where `pyproject.toml`'s `Documentation` URL and `partspec --help` both
point, so it is a router rather than a table of contents: which document answers
which question, and roughly what it costs to read.

## I want to drive the tool

**[AGENT-CONTRACT.md](AGENT-CONTRACT.md)** — read `report.json`, not the console.
What each exit code obliges you to do, the two cases where the exit and the
report disagree on purpose, and what never to do about a failure. The cheapest
and most load-bearing read here.

**[FAILURE-MODES.md](FAILURE-MODES.md)** — the observed ways a part is wrong
while every tool in the chain reports success. Read this before deciding a green
run means what you think it means.

## I want to write a contract

**[SPEC-contract.md](SPEC-contract.md)** — the check vocabulary and its grammar,
normatively. Long, and structured for lookup rather than a sitting.

The `skills/contract-authoring` skill in this repo is the worked version of the
same material, and `examples/` has three parts whose READMEs say what each is
meant to teach.

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

**[PLAN.md](PLAN.md)** — what v0 is and how it gets built.

## I am extending partspec

**[SPEC-backend.md](SPEC-backend.md)** — the geometry backend protocol: what a
backend must answer, and what it must refuse rather than guess.

**[LINT.md](LINT.md)** — the advisory source rules, their tiers, and the noise
each one owns.

---

The specs are normative and were written before the implementation. Where code
and spec disagree, that is a bug in one of them — say which, rather than
silently picking.
