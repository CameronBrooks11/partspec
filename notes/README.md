# notes/ — working analysis, tracked

Non-normative. The normative documents live in `docs/`; what lives here is the
**analysis the tracker cites** — issue bodies reference these files by path
(`notes/audit-synthesis.md`, `notes/GAPS.md`), and until #51 the whole directory
was excluded through `.git/info/exclude`, a mechanism no clone, reviewer, or CI
run can see. Original analysis reachable only from an invisible path is the same
loss class the failure catalogue's issue (#24) exists to prevent, one directory
over.

Per-item disposition (#51's acceptance — decided, not defaulted):

| artifact | disposition |
|---|---|
| `GAPS.md` | **tracked** — the capability-gap inventory the six epics were cut from |
| `FINDINGS.md` | **tracked** — W1–W10 dogfood findings, source of issues #8–#16 |
| `RESEARCH.md` | **tracked** — external research: agent CAD benchmarks, prior art |
| `audit-synthesis.md` | **tracked** — the 2026-08-06 tracker audit (120 agents, 45 upheld findings); cited by many issue bodies |
| ~~`file_issues.py`, `file_audit_issues.py`, `revise_audit_issues.py`~~ | **removed 2026-08-10** (v0.7.0 sweep). One-shot `gh` REST drivers. Their output — the 64 issues filed 2026-08-06/07, all since closed — lives on GitHub, which is a more durable and queryable store than the scripts: `file_issues.py`'s own docstring says it "does not re-run safely", and `file_audit_issues.py` is only "idempotent-ish" (it refuses a duplicate title and nothing more). The pre-filing text is recoverable with `git show <sha>:notes/file_issues.py`; the revision history is already visible in the issue bodies, because `revise_audit_issues.py` appended auditable sections rather than rewriting. Nothing outside this directory ever referenced them. |
| `dogfood-results.md` | **tracked** — the dogfood record (F1–F18), copied verbatim from the scratch workspace when #24 shipped its distillation (`docs/FAILURE-MODES.md`); the F-number citations there resolve to this file |
| `repros/circular-contract/` | **tracked** — the #50 repro; its promoted twin lives in `tests/fixtures/circular/` (kept here because this copy carries the original README narrative; `outputs/` stays ignored) |
| `audit-journal.jsonl`, `audit-run1-raw.json` | **ignored** (committed `.gitignore` rule) — raw audit transcript and output; the synthesis above is the load-bearing artifact |
| `issues-snapshot-*`, `issues-final-*` | **ignored** — tracker snapshots, regenerable with `gh issue list` |
| `upstream/` | **ignored** — vendored reference clones (`build123d-mcp`, `cadgenbench`), each carrying its own `.git`; vendoring them into history would nest repositories |

Transcripts and paths inside these files are verbatim as captured — including
local absolute paths — because their value is provenance; they are frozen, not
maintained, and statements inside them describe the repo as of their date.

The dogfood workspace (`~/repos/partspec-dogfood`, still not a git repository) is
deliberately **not** this issue's box: #24 owns promoting its `results.md` into
`docs/FAILURE-MODES.md` and resolving that workspace's status.
