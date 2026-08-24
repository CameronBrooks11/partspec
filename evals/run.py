#!/usr/bin/env python3
"""Does an agent converge on a broken part, given only partspec's output?

See evals/README.md. The three properties that make the answer mean something:
the contract is frozen, the prompt carries no hints, and every trial runs in a
throwaway copy of the case.

    uv run python evals/run.py --list
    uv run python evals/run.py --case bore-breach --trials 3
    uv run python evals/run.py               # every case, one trial each

Through `uv run`, because `--partspec` defaults to whatever `partspec` PATH
resolves to and nothing else here puts `.venv/bin` on it (#304).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "cases"
AUTHORING_CASES = ROOT / "cases-authoring"
RESULTS = ROOT / "results"
SKILLS = ROOT.parent / "skills"

# Tools are restricted to file access on purpose: withholding Bash is what makes
# "the agent does not run partspec itself" a property of the harness rather than
# an instruction the agent may ignore.
DEFAULT_AGENT = (
    "claude -p --permission-mode bypassPermissions --allowedTools Read,Edit,Write,Glob,Grep"
)
AGENT_TIMEOUT_S = 900
CHECK_TIMEOUT_S = 900

# Verdict severity, worst first. Used only to detect a turn that made things
# worse; it is NOT the batch-verdict precedence of SPEC-report.md 6.2.
SEVERITY = ["error", "empty", "fail", "incomplete", "pass"]

PROMPT = """\
You are fixing a CAD model that fails its declared engineering contract.

The working directory contains:

{tree}

`{contract}` is the **contract**: it states what the part must be true of. It is
**frozen** — do not edit it, and do not create files that shadow it. Editing the
contract ends this trial as a failure even if the check would then pass.

Your job is to change the model so the contract passes.

`partspec check` was just run. This is its entire output — there are no other
hints, and nobody will tell you what is wrong:

```
$ partspec check {target}
{output}
exit code: {code}
```

{report_note}
Make the edits you believe are correct. Do not run partspec yourself; it will be
run for you after you finish, and you will see the new output if anything still
fails.
"""

REPORT_NOTE = """\
The full machine-readable report is at `{path}`. You may read it.

"""

AUTHORING_PROMPT = """\
You are authoring a CAD model from scratch.

The working directory contains:

{tree}

`TASK.md` states what to build. `{contract}` is the **contract** the part must
satisfy; it is **frozen** — do not edit it. Write `{model}` (OpenSCAD) so the
contract passes. Nobody will tell you more than the task and the contract say.
{guidance_note}
Do not run partspec yourself; it will be run for you after you finish, and you
will see its output if anything fails.
"""

GUIDANCE_NOTE = """\
The directory `skills/` contains this project's authoring guidance
(`openscad-authoring/SKILL.md`, `contract-authoring/SKILL.md`). Read it and
follow it.
"""


@dataclass
class Turn:
    n: int
    exit_code: int
    verdict: str | None
    summary: str
    agent_ok: bool = True
    agent_note: str = ""


@dataclass
class Trial:
    case: str
    trial: int
    arm: str = "control"
    outcome: str = "error"
    turns_to_converge: int | None = None
    turns: list[Turn] = field(default_factory=list)
    note: str = ""
    loc: int | None = None
    lint_findings: int | None = None
    lint_unsupported: int | None = None
    lint_outcome: str | None = None


def digests(root: Path, names: list[str]) -> dict[str, str]:
    out = {}
    for n in names:
        p = root / n
        out[n] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "MISSING"
    return out


def tree_of(root: Path) -> str:
    names = sorted(p.name for p in root.iterdir() if p.is_file())
    return "\n".join(f"  {n}" for n in names)


def relative_to_work(path: Path, work: Path) -> str:
    """`path` as the agent would name it, given that it runs with `cwd=work`.

    Both sides are resolved first: `work` comes from `tempfile`, which on macOS
    hands back `/var/...` while the tool prints the `/private/var/...` it
    resolved to. Falls back to the absolute path, which is still correct — just
    longer than the prompt wants.
    """
    try:
        return str(path.resolve().relative_to(work.resolve()))
    except ValueError:
        return str(path)


def run_check(work: Path, target: str, partspec: str) -> tuple[int, str, dict | None, Path | None]:
    """Run `partspec check` and return `(code, output, report, report_path)`.

    The path is returned rather than recomputed by the caller. partspec derives
    the report directory as `<contract dir>/outputs/<stem>-<factory>`, so the
    only reliable source for it is the line the tool prints — which this
    function already has to find in order to parse the report at all.
    """
    proc = subprocess.run(
        [partspec, "check", target],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=CHECK_TIMEOUT_S,
    )
    out = (proc.stdout + proc.stderr).strip()
    report = None
    report_path = None
    for line in out.splitlines():
        cand = line.strip()
        if cand.endswith("report.json"):
            p = (work / cand) if not Path(cand).is_absolute() else Path(cand)
            if p.exists():
                report_path = p
                try:
                    report = json.loads(p.read_text())
                except json.JSONDecodeError:
                    report = None
            break
    return proc.returncode, out, report, report_path


def call_agent(cmd: str, work: Path, prompt: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=work,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=AGENT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False, f"agent timed out after {AGENT_TIMEOUT_S}s"
    if proc.returncode != 0:
        return False, f"agent exited {proc.returncode}: {proc.stderr.strip()[:400]}"
    return True, proc.stdout.strip()


def source_loc(path: Path) -> int:
    """Non-blank, non-comment lines — the LoC the issue asks to record."""
    count = 0
    in_block = False
    for line in path.read_text(errors="replace").splitlines():
        text = line.strip()
        if in_block:
            if "*/" in text:
                in_block = False
            continue
        if not text or text.startswith("//"):
            continue
        if text.startswith("/*"):
            in_block = "*/" not in text
            continue
        count += 1
    return count


def lint_counts(work: Path, model: str, partspec: str) -> tuple[int | None, int | None]:
    """`(findings, unsupported)` from one `partspec lint` run.

    Both, because `findings` alone cannot tell the two apart. `.get` on the
    second: it is an additive key (#316), so a partspec that predates it
    answers `None` — which is "not known", not zero, and is not folded into
    a clean result by `lint_outcome`.
    """
    proc = subprocess.run(
        [partspec, "lint", model], cwd=work, capture_output=True, text=True, timeout=120
    )
    try:
        counts = json.loads(proc.stdout)["counts"]
        return counts["findings"], counts.get("unsupported")
    except (json.JSONDecodeError, KeyError):
        return None, None


def lint_outcome(findings: int | None, unsupported: int | None) -> str:
    """What the lint actually established — three answers, not two.

    The harness branched on `counts.findings` alone and the write-up called
    the result "lint-clean", which is the blind loop `docs/LINT.md` names:
    a `findings: 0` with `unsupported: 3` is not a clean file, it is a file
    three rules never looked at (#118, #288, #317).

    Wholeness is decided FIRST, on purpose: nothing can be concluded from a
    findings count taken over a partial pass, so a run that refused a rule is
    `incomplete` whatever its findings count says. Only a run where every rule
    ran and found nothing earns the word `clean`.
    """
    if findings is None:
        return "unknown"
    if unsupported is None or unsupported > 0:
        return "incomplete"
    return "clean" if findings == 0 else "findings"


LINT_OUTCOMES = ("clean", "findings", "incomplete", "unknown")


def provenance(partspec: str) -> dict[str, str | None]:
    """Which build this run measured, for the header of `results.json`.

    The payload recorded `when` and `agent` and nothing at all about the tool
    under test, while `report.json` — the artifact this project ships — carries
    `tool_version`, and `diff` refuses a comparison that cannot say what
    produced each side. A baseline that costs real agent calls to take and
    cannot name its own build cannot be compared to a later one (#304).

    `harness_commit` describes the checkout `run.py` ran from, which is NOT
    necessarily the build above it: `--partspec` may be an installed wheel from
    anywhere. The absolute path and the version are what identify the binary;
    the commit identifies the cases, the prompts and this driver.

    A bare `HEAD` from a modified checkout names a commit that is not what ran,
    which is the very claim this function exists to refuse, so the state of the
    working tree is carried **in the value** — `<sha>-dirty`, or `<sha>-unknown`
    when git could not be asked. A sibling boolean would be dropped the first
    time someone quoted the commit on its own; a suffix cannot be read without
    it (PR #331 review, F7c).
    """

    def captured(cmd: list[str]) -> str | None:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        return (proc.stdout.strip() or None) if proc.returncode == 0 else None

    def modified() -> bool | None:
        """Whether the checkout has uncommitted changes. `None` = cannot tell.

        Its own runner, not `captured`: a clean tree prints nothing, and
        `captured` maps empty output and a failed command to the same `None`.
        """
        try:
            proc = subprocess.run(
                ["git", "-C", str(ROOT), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return bool(proc.stdout.strip()) if proc.returncode == 0 else None

    commit = captured(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    if commit is not None:
        dirty = modified()
        commit += "-dirty" if dirty else "" if dirty is False else "-unknown"

    return {
        "partspec": partspec,
        "partspec_version": captured([partspec, "--version"]),
        "harness_commit": commit,
    }


def run_trial(
    case_dir: Path, cfg: dict, trial_n: int, agent: str, partspec: str, out_dir: Path, arm: str
) -> Trial:
    t = Trial(case=cfg["id"], trial=trial_n, arm=arm)
    target = cfg["target"]
    frozen = cfg.get("frozen", ["spec.py"])
    max_turns = cfg.get("max_turns", 6)
    authoring = cfg.get("mode") == "authoring"

    with tempfile.TemporaryDirectory(prefix=f"partspec-eval-{cfg['id']}-") as tmp:
        work = Path(tmp) / cfg["id"]
        shutil.copytree(
            case_dir, work, ignore=shutil.ignore_patterns("outputs", "__pycache__", "case.toml")
        )
        if arm == "skills" and authoring:
            # Gated on authoring: a skills copy the repair prompt never
            # mentions would be an arm label describing no treatment.
            shutil.copytree(SKILLS, work / "skills")
        baseline = digests(work, frozen)
        prev_sev = len(SEVERITY)

        if authoring:
            prompt = AUTHORING_PROMPT.format(
                tree=tree_of(work),
                contract=frozen[0],
                model=cfg["model"],
                guidance_note=GUIDANCE_NOTE if arm == "skills" else "",
            )
            ok, note = call_agent(agent, work, prompt)
            (out_dir / f"{cfg['id']}-{arm}-t{trial_n}-author.prompt.md").write_text(prompt)
            (out_dir / f"{cfg['id']}-{arm}-t{trial_n}-author.agent.md").write_text(note)
            if not ok:
                t.outcome, t.note = "error", note
                return t

        for turn in range(1, max_turns + 1):
            code, output, report, report_path = run_check(work, target, partspec)
            verdict = (report or {}).get("verdict")
            summary = output.splitlines()[-2] if len(output.splitlines()) > 1 else output

            # Contract integrity is checked BEFORE convergence: a green run on a
            # weakened contract is the failure this harness exists to catch.
            if digests(work, frozen) != baseline:
                t.turns.append(Turn(turn, code, verdict, summary))
                t.outcome, t.note = "gamed", "the agent modified a frozen contract file"
                break

            t.turns.append(Turn(turn, code, verdict, summary))

            if code == 0:
                t.outcome = "converged"
                t.turns_to_converge = turn if authoring else turn - 1
                break

            sev = SEVERITY.index(verdict) if verdict in SEVERITY else 0
            if sev < prev_sev and turn > 1:
                t.note = f"turn {turn}: verdict worsened to {verdict}"
            prev_sev = sev

            if turn == max_turns:
                t.outcome = "failed"
                t.note = t.note or f"budget of {max_turns} turns exhausted"
                break

            report_note = ""
            if report is not None and report_path is not None:
                report_note = REPORT_NOTE.format(path=relative_to_work(report_path, work))

            prompt = PROMPT.format(
                tree=tree_of(work),
                contract=frozen[0],
                target=target,
                output=output,
                code=code,
                report_note=report_note,
            )
            ok, note = call_agent(agent, work, prompt)
            (out_dir / f"{cfg['id']}-{arm}-t{trial_n}-turn{turn}.prompt.md").write_text(prompt)
            (out_dir / f"{cfg['id']}-{arm}-t{trial_n}-turn{turn}.agent.md").write_text(note)
            if not ok:
                t.turns[-1].agent_ok = False
                t.turns[-1].agent_note = note
                t.outcome, t.note = "error", note
                break

        model_file = work / cfg.get("model", "model.scad")
        if model_file.exists():
            t.loc = source_loc(model_file)
            t.lint_findings, t.lint_unsupported = lint_counts(
                work, cfg.get("model", "model.scad"), partspec
            )
            t.lint_outcome = lint_outcome(t.lint_findings, t.lint_unsupported)

        # Preserve whatever the agent left behind, for post-hoc reading.
        keep = out_dir / f"{cfg['id']}-{arm}-t{trial_n}-final"
        shutil.copytree(
            work, keep, ignore=shutil.ignore_patterns("outputs", "__pycache__", "skills")
        )

    return t


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--case", action="append", help="case id (repeatable); default all")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--agent", default=os.environ.get("PARTSPEC_EVAL_AGENT", DEFAULT_AGENT))
    ap.add_argument("--partspec", default=os.environ.get("PARTSPEC_BIN", "partspec"))
    ap.add_argument("--list", action="store_true")
    ap.add_argument(
        "--arm",
        choices=["control", "skills"],
        default="control",
        help="authoring guidance absent (control) or present (skills) — #53",
    )
    args = ap.parse_args()

    cases = []
    for parent in (CASES, AUTHORING_CASES):
        if not parent.is_dir():
            continue
        for d in sorted(parent.iterdir()):
            if (d / "case.toml").exists():
                cases.append((d, tomllib.loads((d / "case.toml").read_text())))

    if args.list:
        for _d, cfg in cases:
            print(
                f"{cfg['id']:<20} {cfg['target']:<24} "
                f"{cfg.get('defect', {}).get('description', '')}"
            )
        return 0

    if args.case:
        cases = [(d, c) for d, c in cases if c["id"] in args.case]
        if not cases:
            print(f"no case matched {args.case}", file=sys.stderr)
            return 64

    if args.arm == "skills":
        skipped = [c["id"] for _d, c in cases if c.get("mode") != "authoring"]
        cases = [(d, c) for d, c in cases if c.get("mode") == "authoring"]
        if skipped:
            print(f"--arm skills applies to authoring cases only; skipping: {', '.join(skipped)}")
        if not cases:
            print("no authoring cases to run under --arm skills", file=sys.stderr)
            return 64

    # ONE executable, resolved here and passed down resolved and ABSOLUTE.
    # `run_check` uses this whole string as argv[0], so the earlier
    # `.split()[0]` guard let PARTSPEC_BIN="uv run partspec" pass and then fail
    # in the first trial, after the run had started (#304).
    #
    # `shutil.which` closes only half of that. Given a path with a separator it
    # returns the string UNCHANGED when it is executable relative to the CWD —
    # so `PARTSPEC_BIN=.venv/bin/partspec`, the natural thing to type from the
    # repo root, cleared the guard, printed a reassuring version in the header
    # (`provenance` runs with no `cwd`), and then died in every trial, because
    # `run_check` runs with `cwd=work`, a temp copy. Absolute here, once, while
    # the CWD the user typed it against is still the CWD (PR #331 review, F1).
    resolved = shutil.which(args.partspec)
    if resolved is None:
        # `.exists()`, not `.is_file()`: a DIRECTORY exists, and `is_file`
        # sent it down the "no such file" branch to be told it was not there.
        # `shutil.which` refuses a directory correctly either way, so this is
        # the sentence and not the behaviour — a false sentence shipped to a
        # user is still shipped (PR #331 review, R2-1).
        candidate = Path(args.partspec)
        why = (
            "it exists but is not executable"
            if candidate.exists()
            else "no such file, and no such name on PATH"
        )
        print(
            f"partspec not usable: {args.partspec!r} — {why}. Set PARTSPEC_BIN "
            "to ONE executable: a path, or a name on PATH; not a multi-word command.",
            file=sys.stderr,
        )
        return 64
    partspec = str(Path(resolved).resolve())

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = RESULTS / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    provenance_of_run = provenance(partspec)
    print(
        f"agent:    {args.agent}\n"
        f"partspec: {provenance_of_run['partspec_version']}  ({partspec})\n"
        f"commit:   {provenance_of_run['harness_commit']}\n"
        f"results:  {out_dir}\n"
    )

    trials: list[Trial] = []
    for d, cfg in cases:
        for n in range(1, args.trials + 1):
            print(f"-- {cfg['id']} trial {n}/{args.trials}", flush=True)
            try:
                t = run_trial(d, cfg, n, args.agent, partspec, out_dir, args.arm)
            except Exception as exc:  # noqa: BLE001 - a harness fault is data, not a crash
                t = Trial(
                    case=cfg["id"], trial=n, outcome="error", note=f"{type(exc).__name__}: {exc}"
                )
            trials.append(t)
            turns = f"{len(t.turns)} turn(s)"
            print(f"   {t.outcome.upper():<10} {turns}  {t.note}", flush=True)

    payload = {
        "when": stamp,
        "agent": args.agent,
        "arm": args.arm,
        **provenance_of_run,
        "trials": [asdict(t) for t in trials],
        "summary": {
            o: sum(1 for t in trials if t.outcome == o)
            for o in ("converged", "failed", "gamed", "regressed", "error")
        },
        # Reported per bucket rather than as one "lint-clean" tally, because
        # the tally cannot say which of the three a trial was (#317).
        "lint": {o: sum(1 for t in trials if t.lint_outcome == o) for o in LINT_OUTCOMES},
    }
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2))

    print("\n" + "=" * 62)
    for o, n in payload["summary"].items():
        if n:
            print(f"  {o:<12} {n}")
    if any(payload["lint"].values()):
        print("  lint:        " + "  ".join(f"{o} {n}" for o, n in payload["lint"].items() if n))
    conv = [t.turns_to_converge for t in trials if t.turns_to_converge is not None]
    if conv:
        print(f"  turns to converge: {conv}  (mean {sum(conv) / len(conv):.1f})")
    print(f"\n  {out_dir / 'results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
