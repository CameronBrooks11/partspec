# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.4] - 2026-08-13

**A remedy that cannot be run is not a remedy.** One fix, found the way the last
release was: by installing the published artifact the way a stranger would and
following its own instructions literally.

Measured at this tag, five environments, no failures anywhere:

| environment | passed | skipped |
| --- | ---: | ---: |
| `uv sync --all-extras` (`just test`) | 800 | 0 |
| base install, no extras | 466 | 260 |
| `[mesh]` only | 586 | 152 |
| `[occt]` only | 665 | 126 |
| `[cadquery]` only | 671 | 120 |

### Fixed

- **Every hint that named an installer named `pip`, which a `uv venv` does not
  have.** Absent would have been the kind outcome: on a distro that packages
  pip the word still resolves — to `/usr/bin/pip`, bound to the system
  interpreter — so `pip install --force-reinstall --no-deps cadquery-ocp`, the
  entire answer to the two-provider clobber, was refused outright under PEP 668
  with advice to "create a virtual environment" the reader was already standing
  in, and its suggested `--break-system-packages` override would have installed
  OCP into a Python that could never satisfy the failing one. Either way the
  next run printed a byte-identical diagnosis. Hints are now phrased for the
  interpreter that will read them (`install.py`), detected with `find_spec` and
  deliberately not `shutil.which` — `which` is exactly what finds the wrong
  pip. Verified end to end in a pip-less two-provider venv: the printed command,
  run verbatim, takes the run from `ERROR: 3 skipped` to `PASS: 3 pass`. Found
  on the v0.7.3 cold verify, in the install shape the README documents.

## [0.7.3] - 2026-08-13

**The first release cut from an adoption measurement rather than from review.**
A fresh agent was dropped on a cold PyPI install of 0.7.2 with a real
objective — evaluate the community CadQuery library `cq-gridfinity` against
the published Gridfinity standard — and no other context: no access to this
checkout, no worked example, nothing but the installed tool. Roughly **40% of
its effort went to discovering the contract API**, and every fix below is one
of the reasons why.

The measurement paid for itself twice over. It also produced the thing it was
pointed at: `cq-gridfinity`'s stacking lip is 0.6 mm shorter than the standard
at both sizes tested — `GR_LIP_PROFILE`'s final segment is 1.3 mm where the
reference implementation has 1.9 — found by an `envelope` bound sourced from
the standard rather than from the library, which is the whole argument for
attribution.

**What this release does not change:** `pip install 'partspec[cadquery]'` still
lands two OCP providers and still needs the re-assert the README documents.
That was confirmed on a clean ancestor chain with `--no-config`, so it is the
default outcome and not a local artefact. The extra cannot fix it — the
override that does is a workspace setting wheel metadata cannot carry — so what
changed is that the tool now prints the remedy instead of only recording it.

Measured at this tag, five environments, no failures anywhere:

| environment | passed | skipped |
| --- | ---: | ---: |
| `uv sync --all-extras` (`just test`) | 798 | 0 |
| base install, no extras | 464 | 260 |
| `[mesh]` only | 584 | 152 |
| `[occt]` only | 663 | 126 |
| `[cadquery]` only | 669 | 120 |

### Fixed

- **`check` named the fault and withheld the remedy.** `BuildError` carries a
  message and a hint; `measure` and `render` have always printed both, and
  `check` — the verb people actually run — printed only the message, leaving
  the hint in `report.json`. On a cold `partspec[cadquery]` install, which
  lands two OCP providers so that CadQuery cannot import at all, the console
  named the clobber precisely, twice, and never said
  `pip install --force-reinstall --no-deps cadquery-ocp`. The same agent lost
  time to this twice more in one session: `available: <names>` on a mistyped
  factory, and the claims-pin mismatch hint, were withheld identically. Every
  path that sets `report.hint` is one where nothing was proven about the part,
  so the rule is now simply that a hint is printed. The console is still a
  courtesy and `report.json` is still ground truth; the courtesy just stopped
  naming a problem and hiding its answer.
- **A run-level fault was stated once per check.** An environment-origin build
  failure skips every declared check carrying the same sentence as its detail,
  so a ten-check contract printed an identical forty-word packaging diagnosis
  ten times — and `report.error`, the thing that actually happened, not once.
  The console now elides a detail that merely echoes the run-level error and
  states the error a single time. The artifact is untouched: a per-check
  consumer still reads `detail` on every check.
- **Both Python engine factories were undocumented.** `openscad` had a
  docstring; `build123d` and `cadquery` had none, and they are the entry point
  for both Python engines. What they did not say is what bites: partspec calls
  a *named callable*, defaulting to `make_part`, with the contract's params as
  keyword arguments. The agent assumed CQGI's module-level `result` — the
  convention `cq-gridfinity`'s own shims use — and learned otherwise only by
  failing. `Source.path` now also records that a relative path resolves against
  the contract's directory rather than the working directory.
- **Diagnostics cited specs an installed user cannot reach.** Messages name
  `SPEC-report.md 7.1` and `SPEC-contract.md 10`; the wheel ships the package
  and nothing else, deliberately. `--help` now says where the documents are.
  The wheel still ships no docs.
- **The unattributed-limit advisory named the problem and not the way out.**
  `partspec.refs` carries `iso15` and `nema17`, so an author citing anything
  else was told their bound proves the model matches itself and not how to fix
  that. It now names `partspec.Referenced`, which the agent found by reading
  `dir(partspec)`.
- **The README's front-page transcript quoted output the tool had stopped
  printing** — one commit after the commit that changed it. Neither existing
  guard reads what a transcript *says*: one compares the contract's call shape,
  the other counts `ok` lines and the tally. The transcript is recaptured and
  now executed, so every non-path line it quotes must appear in a real run.
  The OCP error block one section down was never captured at all — it was
  assembled from `BuildError`'s fields, and showed a `hint:` line `check` did
  not then emit. That is the third block of "captured" output in this README
  found not to have been captured.
- **`--out` meant two different things and said so nowhere.** On `measure` it
  is the engine's build directory — an `.stl` on OpenSCAD, nothing at all on
  the OCCT tier, which builds in memory — because `measure` writes no report by
  design (SPEC-report scope: the payload is stdout). It had no help text, while
  `check --out` is documented as "report directory", so it read as a report
  flag that silently did nothing. Behaviour is unchanged; the flag now says
  what it controls. `check --out`'s own layout is documented too:
  `DIR/report.json` for one target, `DIR/<part-slug>/report.json` for several.

## [0.7.2] - 2026-08-12

**A retraction.** For ten days, across three releases, this project told uv
users that `uv pip install 'partspec[occt]'` does not work and named an
upstream cause. Both halves were wrong, and the cause was one line of this
repo's own configuration. Eight files carried the explanation — the README,
`AGENTS.md`, `docs/FAILURE-MODES.md`, the justfile, CI's workflow, this file,
the error message itself and the test that pinned its wording — and the single
change inside `partspec/` is that error message. Everything else is
documentation, recipes and gates that repeated it.

Measured at this tag, five environments, no failures anywhere:

| environment | passed | skipped |
| --- | ---: | ---: |
| `uv sync --all-extras` (`just test`) | 791 | 0 |
| base install, no extras | 466 | 251 |
| `[mesh]` only | 585 | 144 |
| `[occt]` only | 665 | 117 |
| `[cadquery]` only | 671 | 111 |

### Fixed

- **`uv pip install 'partspec[occt]'` was never broken, and #109 was ours.**
  For ten days the README told uv users the command does not work and to fall
  back to plain `pip`; the issue recorded an upstream cause — that build123d's
  `cadquery-ocp-proxy` picks a real OCP wheel with an install-time hook uv's
  installer skips — and the error message, its test, two justfile recipes and
  `AGENTS.md` all repeated it. None of it was true. `cadquery-ocp-proxy` ships
  no OCP and has no dependencies at all; every build123d release ever published
  hard-depends on a concrete provider (`cadquery-ocp` through 0.10.0,
  `cadquery-ocp-novtk` from 0.11.0), so there was no hook to run and nothing
  for uv to skip. The strand was this repo's own
  `[tool.uv] override-dependencies = ["cadquery-ocp-novtk ; sys_platform == 'never'"]`,
  which uv finds by walking up from the working directory and applies to
  whatever it is installing. Measured four ways against
  `partspec[occt]==0.7.1` on Python 3.13: outside the repo it installs OCP;
  inside the repo it does not; inside the repo with `--no-config` it does;
  and in an empty directory holding nothing but a pyproject.toml carrying that
  one override, it does not. `partspec[occt]==0.4.0`, the version of the
  original report, installs cleanly from outside the repo today — and the
  override predates that report by six days, so it was in scope for every
  measurement the issue was ever built on.

  Fixed in what the tool says and in what the gates measure. The README
  paragraph is replaced with the correction rather than deleted, since the
  wrong version shipped in three releases. `_engine_import_error` no longer
  blames uv's installer: the state it detects is now stated as what it is — no
  OCP provider installed, the proxy present as a breadcrumb — and it names the
  distribution to install instead of advising a switch of installer. Its test
  asserts those invariants rather than the phrasing, which is how the fiction
  survived: the test pinned the words. All five throwaway-environment recipes
  pass `uv pip install --no-config`, which lets `test-occt-only` and
  `test-cadquery-only` drop the seeded-venv-plus-plain-pip workaround they
  carried for a cause that did not exist, and `test_packaging.py` fails any
  future recipe that omits the flag — a recipe measuring what a consumer gets
  cannot read config no consumer has.

- **The dual-engine install's second line is not optional advice, and the
  recipe that was supposed to prove it was living on luck.** `cadquery-ocp` and
  `cadquery-ocp-novtk` own the same top-level `OCP/` and whichever lands last
  wins; `just test-cadquery-only` was green for a month on plain pip, which
  happened to land `cadquery-ocp` last, and failed on its first CI run under
  `uv pip`, which landed novtk last — `ImportError: cannot import name
  'IVtkOCC_Shape' from 'OCP.IVtkOCC'`, CadQuery unable to import at all. pip's
  order was never a guarantee either. The recipe now runs the re-assert step
  the README documents, so it verifies those instructions rather than hoping a
  resolver agrees with them, and the README carries the `uv` form of the
  two-step beside the `pip` form.

- **The guard against #109 did not cover the release.** Its first version read
  the justfile, because that is where the recipes it was written for live. The
  install it therefore missed is the last one to touch an artifact before PyPI:
  `release.yml`'s cold smoke-test of the built wheel, whose stated purpose is
  to reproduce "the environment every `pip install partspec` user starts
  from". It runs in the checkout, so it read the override like everything
  else. Harmless in fact — core depends on no OCP provider, so there was
  nothing for the override to drop — but the claim it makes is exactly the one
  #109 falsified, and this is the release path. It passes `--no-config` now,
  and the guard searches every file that runs a `uv pip install`, comments
  excluded, rather than one file by name. Found by the pre-tag audit for this
  release, in the workflow that publishes it.

- The comment above CI's two OCCT-tier jobs still gave the retracted cause —
  that `uv pip install .[occt]` "lands `cadquery-ocp-proxy` and NO `OCP`
  module ... still reproducing on 2026-08-12", and that plain pip in a seeded
  venv is the way around it. The recipes it describes had already moved back
  to plain `uv pip` with `--no-config` in the same change that retracted the
  cause; the prose above them had not. Nothing executed it, which is how it
  survived — the repeat defect of this project, recorded in `AGENTS.md`.

- 0.7.1's release entry says the published wheel differs from 0.7.0's in "the
  version string, and the README it embeds". Comparing the two wheels *as
  published* — which is only possible after the fact — there is a third:
  `WHEEL` carries `Generator: hatchling 1.31.0` against `1.32.0`, the build
  backend CI resolved on the day. The containing claim holds and was verified
  against the published artifacts (29 package files, same set, none differing;
  every difference inside `.dist-info`), but the enumeration was two of three.
  Recorded here rather than edited into the released section, per the rule in
  `AGENTS.md`: a released entry takes form-only edits, and a changed claim
  goes in a new entry.

- **The suite the sdist ships still hid tests from the install it ships to.**
  0.7.1 made `tests/` *pass* in a base install; it did not make it *run*. Ten
  module-level `pytest.importorskip` gates collapsed their files to a single
  skip line each, so a base install collected 588 of the suite's 788 tests and
  ran 451. Gating is per test, and at the commit that changed it 714 collected
  there and 463 passed — 717 and 466 at this tag, per the table above. And
  `pip install partspec[mesh]` — which reported four whole files as
  `4 skipped` — runs the four `the mesh tier refuses with the tier named`
  tests, the only executed evidence that the mesh tier refuses honestly in
  the one install where the mesh tier is the only tier. No code in
  `partspec/` changed (#165).

- **The shipped suite failed one test under `pip install partspec[cadquery]`.**
  That extra names `cadquery-ocp` explicitly while build123d hard-depends on
  `cadquery-ocp-novtk` — so pip installs both providers of the same top-level
  `OCP/` package and neither notices.
  partspec's own guard detects exactly this and says so, which is what broke
  the test: it pinned the wording of a different branch. It now asserts what
  every branch owes a reader — the environment's fault, the module named, a
  next step given — and the three wordings are pinned individually, including
  the two-provider one, which had no test and is the only branch reachable
  without monkeypatching. Measured after the fix: `[cadquery]` 670 passed,
  `[occt]` 664 passed, no failures in either — 671 and 665 at this tag, per the
  table above. Again no code in `partspec/` changed.

## [0.7.1] - 2026-08-11

**No code changed.** `src/` is byte-identical to 0.7.0, and so is every one of
the 29 files inside the installed `partspec/` package — verified by SHA-256
against a wheel rebuilt from the v0.7.0 tag. The only differences in the wheel
are its `.dist-info` metadata: the version string, and the README it embeds as
the long description. No verb, check kind, exit code or engine behaviour
differs; nothing in the installed package changes.

What did change is the **source distribution** and the repository's own gates.
Two things a consumer gets: the test suite the sdist ships now passes in a base
install, and the documents it ships no longer cite files the tarball does not
contain.

### Fixed

- **The sdist shipped a test suite that did not pass.** `pyproject.toml`
  argues `tests/` ships "because a downstream packager runs the suite from an
  sdist, and that claim only holds if the suite actually passes there... The
  claim is ZERO FAILURES." At v0.7.0 a base install — `pip install partspec`,
  no extras, OpenSCAD binary present — the shipped suite reported **23 failed
  / 314 passed**. It is **451 passed / 137 skipped / 0 failed** now, and from
  the unpacked tarball itself, 439 passed / 149 skipped.

  Two causes. An OpenSCAD part is measured *through* the mesh tier, so tests
  marked `needs_openscad` alone ran and errored instead of skipping when
  `trimesh` was absent; `needs_scad_tier` names that coupling. And a
  module-level `importorskip` raises at import, collapsing a whole file to one
  skip line — `test_diff.py` reported `1 skipped` for 34 tests, 32 of which
  need no engine at all. Eight such gates are gone.

  No CI job could have caught either: `check` and `test` install every extra,
  and `mesh-only`/`mcp-only` each ran a single module, so no job ran the whole
  suite anywhere an extra was missing. `just test-no-extras` does now, in a job
  the path filter cannot skip.
- **17 citations across ten shipped documents** named files under `notes/` and
  `evals/`, neither of which has shipped in the sdist since #150 — so they
  dangled for every reader who arrived from PyPI rather than a checkout. They
  are `blob/main` links now, and three tests hold them: every linked path is
  tracked, every backticked path is tracked, and no shipped document may cite
  a non-shipping file as a bare path. The last is the one that matters — the
  other two ask "is this tracked?", and `notes/` is tracked *and* excluded,
  which is why `AGENTS.md` passed both while being unopenable.
- The `[0.7.0]` heading in this file had no link definition, so it rendered as
  literal text between neighbours that were links — on the document
  `pyproject.toml` advertises as the project's Changelog URL. `[Unreleased]`
  also still compared from `v0.6.0`, a range spanning all of 0.7.0. A test
  holds both, and a second refuses two `### Fixed` sections in one release.
- `ok`, the branch-protection gate, listed its upstream jobs by hand and
  nothing checked the list. A job missing from it still runs and still goes
  red, while the merge button turns green because the one required check never
  waited for it — a job that cannot fail the gate reads as success.
- The eval harness told the agent its report was at
  `outputs/spec-<part id>/report.json`, but partspec derives that directory
  from the contract's filename and factory, not the part id. No eval case has
  the two equal, so the path was dead in every archived repair turn — four
  lines below partspec's own output naming the real one. `run_check` already
  found the true path and discarded it; it returns it now. (`evals/` does not
  ship; this affects contributors only.)

### Changed

- `tests/test_mesh_backend.py` was nearly half coverage of
  `engines/openscad.py` under a filename naming a different module (#153) —
  37 of its 75 tests, 496 of its 1100 lines, now
  `tests/test_openscad_engine.py`. Not only tidiness: the old file binds
  `trimesh` at import, so tests that never measure a mesh could not run
  without the mesh extra. The split alone accounts for 44 of this release's
  base-install gain.
- `just test-mesh-only` ran a single module, so nothing covered the ground
  between "no extras" and "all extras". It runs the whole suite now — which
  caught a regression mid-release: a module gated on a *proxy* dependency
  (`numpy`, which arrives with `trimesh`) rather than the one its tests use
  collected on `pip install partspec[mesh]` and failed, with every other gate
  in the repo still green.
- `tests/test_cli.py` carried a private `_contract()` byte-identical in output
  to `support.scad_target()`; proved equivalent, deleted, and its 15 call
  sites moved. `support.py` gains `py_target`, the build123d counterpart,
  written for #153 and then deleted unused because a helper nothing calls is
  the slop that slice was removing — it returns with 16 callers.
- `_write_json` already wrote atomically, and **that is unchanged**; what was
  missing is that nothing held it there. Replacing the tempfile-and-rename
  with a direct truncating open left the whole suite green. Two properties are
  pinned now: a failed write leaves the previous report byte-identical, and a
  successful one replaces the file by rename rather than writing in place —
  checked by inode, because a writer that copies a temp file over the
  destination satisfies the first and still lets a reader observe a
  half-written report.

## [0.7.0] - 2026-08-11

### Fixed

- `cavities` certified exactly one sealed void in a shape with no material
  (OCCT, #147). The same report said `solid_count: 0`, and the mesh tier
  answered `0` — a number contradicted by its own neighbour and by the other
  tier. Gated now.
- `diff` compared every claim field except the one that says what a check IS
  (#147). Swapping `genus` for `cavities` under one id reported `identical`,
  exit 0. `CLAIM_FIELDS` is public and held in step with `SPEC-diff.md`;
  `NON_CLAIM_FIELDS` enumerates the rest, and every `CheckResult` field is
  classified into one or the other, so a field added later cannot fall through
  both.
- `diff` returned `identical` when both inputs' source closures were absent —
  "nothing we looked at changed" reported as "nothing changed" (#147). And
  `counts` was asserted only to sum, so a tally claiming every check passed
  while the verdict said fail was a self-inconsistent report the comparator
  accepted.
- An empty `Compound()` escaped as an `AssertionError` traceback with empty
  stdout (#133). All three verbs now name it — `model returned a shape
  containing no geometry (an empty Compound with no underlying handle)` — and
  `measure`/`render` still emit the identity artifact so a consumer learns
  which file and revision it was talking about.
- `check --render` built the model twice (#133): doubled side effects, a
  `--timeout N` that bounded each build separately rather than the run, and
  renders that could disagree with the geometry measured beside them. One
  build now.
- The release workflow's safety argument is enforced rather than stated
  (#149). It runs no tests by design — correctness is the `ok` gate's job on
  main — and that reasoning holds only if the tag is ON main, which nothing
  checked. `scripts/assert_tag_on_main.sh` refuses a tag that is not an
  ancestor of `origin/main`, in a script because an inline gate can only be
  grepped, not tested. The publish action is SHA-pinned.
- A missing mesh wheel is an environment fault, not a traceback. `pip install
  partspec` then running an OpenSCAD part raised `ModuleNotFoundError` with a
  hint blaming "a native segfault/OOM in the CAD kernel"; it now reports
  `build_origin: environment` with `pip install 'partspec[mesh]'`. The OCCT
  tier has classified this correctly since v0.4.0.
- An OpenSCAD binary rejecting an option partspec passed is an environment
  fault. `backend="CGAL"` on 2021.01 — what Debian and Ubuntu ship — reported
  `build_origin: "model"`, sending an agent to fix a source that was fine.
- `scad-magic-number` exempted the line, not the statement: a named constant
  wrapped across lines drew three findings that the same constant on one line
  did not.

- `partspec diff` refuses a report carrying two checks under one `id`, exit 64
  (#148). SPEC-report §7.1 already made uniqueness a MUST NOT; nothing checked
  it on the consuming side, and the comparator joins on `id`, so the second
  occurrence silently replaced the first and two unrelated claims were compared
  as one. Measured before the fix: a `genus` check aliased onto a `param_range`
  check reported `limit_changed` from `{"kind": "param_range"}` to
  `{"kind": "genus"}` at exit 1, with the displaced claim absent from the output
  entirely — a confident wrong answer, not a lost check. `counts.total` cannot
  catch it, because such a report carries exactly the number of checks it
  claims. `Part._add` already refuses an id clash at authoring time, so
  `partspec` never emitted one; this binds `diff`, which consumes reports it did
  not produce. Two neighbouring refusals share the precondition: a check with no
  `id`, and an `id` that is not a string (§7.1 types it as one — comparing ids
  any other way lets `1` and `1.0` pass a uniqueness check and then collapse
  onto one another in the join).
- `Part._add` refuses a check `id=` that is not a string. `CheckResult.id: str`
  was an annotation, not an enforcement, so `p.param("wall", min=2.0, id=3)`
  was accepted and `check` wrote `"id": 3` — which the new `diff` guard would
  then refuse at exit 64, blaming the artifact for a contract error made two
  commands earlier. **Behaviour change**: a contract passing a non-string `id=`
  now raises `ContractError` (verdict `error`, exit 4) where it previously ran.
  `id=None` is untouched — it is the default and means "derive the id".

### Changed

- `Part._add` refuses `id="builds"` — reserved for the runner's own build
  check, which a contract could previously shadow, putting two same-id checks
  in one report and once letting a passing parameter check impersonate a
  failed build to `check --render`'s gate (#135). The gate keys on `kind` now.
  **Behaviour change**: such a contract raises `ContractError`, verdict
  `error`, exit 4.
- The package ships a type marker (`py.typed`, #149). It is fully annotated
  and pyright-clean and shipped no marker, so a downstream consumer got not
  weaker type checking but **none**, silently.

- The sdist no longer ships `notes/` or `evals/` (#150). They were carried
  because tests read them — an inverted dependency that put 310 KB of archived
  agent transcripts in front of every PyPI consumer so a test could assert a
  phrase appeared in prose. Those tests are deleted rather than skip-guarded, so
  nothing reads those trees and the question does not arise. The tarball loses
  105 KiB. (A delta, not a share: the share depends on which tarball is the
  denominator and moves as prose is added to the repo, which is how the
  figure this replaces came to be wrong.) `tests/`, `docs/`, `examples/`, `skills/` and
  `.github/` still ship, and the suite still passes from an unpacked sdist.
- The mechanical enumerations in the specs are **generated** from the code
  (`scripts/gen_docs.py`, run by `just fmt`, gated by `just check`): the §4.1/§4.2
  vocabulary tables, SPEC-report §2.2's unit table, `DIMENSIONAL_KINDS`,
  SPEC-backend §3's protocol block and the README's exit codes. Six tests used to
  hold those second copies in step and report drift after it happened; there is
  one copy now. Consequence for readers: §4.2 gains the `id=` parameter it never
  documented on any of its eighteen rows, and §2.2's unit column now names the
  kinds that emit each unit. Prose is untouched and stays normative.

### Added

- `p.min_wall(min=)` — every wall thick enough within a declared measurand,
  OCCT tier (#140): kernel-exact face-pair minima and certified diametric
  self-spans bound the wall from below; a witnessed crossing bounds it from
  above — an inward normal ray, or a diametric chord certified material end
  to end by exact boolean, which is what makes every closed analytic family
  exact and answers a frustum whose every normal exits through an adjacent
  cap (#145). One consequence to know: a fillet band on a CLOSED
  (full-revolution) edge is a closed analytic face, so the chord witness
  collapses the upper end onto twice the fillet radius — a rounded Ø20 boss
  that used to report `[1.414, 20.0]` and shrug at a `min=3` claim now reports
  `[1.414, 2.0]` and fails it. A fillet along a straight edge is an open strip
  with no diametric certificate and still straddles, including §4.11's
  knife-edge-on-a-wedge example (`[0.599255, 1.167914]`, `approximate`). A crossing thinner than the bound refuses the check as
  self-contradictory, and a straddling limit adjudicates `approximate` —
  the first genuine exercise of the interval machinery, closing POST-V0's
  outstanding obligation. Gap-limited claims straddle honestly (never
  falsely tight); edge-sharing webs, single-face folds and step/counterbore
  ledges are recorded escapes with fixtures, not silent green; the wedge
  policy is structural. The mesh
  tier's refusal stands with the research's executed evidence recorded.
  SPEC-contract 4.11.
- `p.step_roundtrip(tol=)` — the part survives its own exchange format,
  OCCT tier (#139): written to STEP and read back, volume/area within a
  calibrated relative tolerance (default 1e-6: most families measure below
  4e-13, threaded parts ~6e-9 on build123d 0.11.1 / cadquery-ocp 7.9.3.1.1 —
  the figure moves with the kernel, so it is named with its toolchain — and
  the executed degrader loses everything)
  and topology counts unchanged at any tolerance. Plain membership — the
  tol is never epsilon-widened. The writer schema rides on the check
  (`checks[].step.schema`). SPEC-contract 4.10.
- `p.self_intersection_free()` — the shape does not cross itself, OCCT tier
  (#138): the kernel's own pairwise interference analysis, exact, with the
  faults inventoried in the failure detail. The recorded limit is pinned
  by tests in both directions: an analytic single-surface self-intersection
  (spindle torus) escapes, while a self-overlapping swept face is caught as
  a pair-less fault. Listed by `measure`. SPEC-contract 4.9.
- `p.draft_angle(min=, direction=)` — every face's draft at least `min`
  for a declared pull axis, OCCT tier (#137). Deliberately no `max=`: an
  every-face maximum is unsatisfiable under the two-half convention (caps
  measure 90), and a bound held to fewer faces would pass silently. Exact on planes, cylinders and
  cones at any orientation (closed-form wrap extremes, no sampling); a
  freeform face refuses the whole check with the face named, never a subset
  pass. The two-half parting convention makes tops measure 90 and pass a min
  naturally, and the pull axis is recorded in the check
  (`checks[].direction`). SPEC-contract 4.8.

### Removed

- `partspec.BBox` — a dataclass never constructed anywhere in the repo, on the
  public export list since v0.1. `Vec3` stays; nothing else changes.
- `partspec.run` leaves `__all__`. README has called it internal since v0.1
  while the export said otherwise; it remains importable (`from partspec
  import run` still works, and `partspec.runner.run` is the honest path), but
  it is not part of the stable surface and its signature may change without a
  major bump. The stable surface is the report schema and the exit codes.
- `CheckResult.part_refs` — set on three of the construction sites, never
  serialised by `to_json`, and therefore unreadable from any artifact, while
  four claim sites across three documents said every check recorded it. Forward-compat for
  assemblies that cost coherence now and could not be collected later anyway:
  SPEC-report §7.1 makes an added field non-breaking, so assemblies can
  introduce it for real.
- `partspec.csg.read_csg` and `partspec.csg.contains_strings`. Neither had a
  production caller; `contains_strings` was the superseded tree-walking half
  of a guard that `lint.lint_scad_tier2` performs on the raw export bytes,
  because the tree version was bypassable by hiding the string in a %-dropped
  statement. `csg` is not a documented surface, but `contains_strings` was in
  `csg.__all__`, so it is recorded here.
- The mesh tier no longer declares the `raycast` capability. It needs
  `rtree`, which the `mesh` extra does not carry, so the declaration was a
  promise the backend could not keep — the one thing SPEC-backend §3.2 says
  capabilities exist to prevent. The method remains and now returns
  `Unsupported` instead of raising when the ray engine is absent.

## [0.6.0] - 2026-08-08

An agent can see the part it made (epic #2): renders on every engine, section
cuts, a visual diff — plus the lint tier that reads the geometry.

### Added

- `render` and `check --render` accept build123d and CadQuery parts (#18): the
  part builds through the same backend `check` uses and the canonical views are
  rasterized from its tessellation — deterministic (identical geometry renders
  byte-identical), headless, no new dependency. Framing is the OpenSCAD path's,
  measured and verified cross-tier to the pixel. OCCT payloads and reports carry
  `render_tessellation` (`{tolerance_mm, triangles}`) beside `renders` (D15).
- `render` payloads carry the report's identity prefix, and a render failure is
  a JSON artifact with `error`/`hint` at exit 4 instead of a bare stderr line
  (#103); the MCP `render` tool returns the whole payload as `rendered`.
- `partspec vdiff old new` compares two runs' renders visually (#21):
  per-view changed-pixel fractions with grey-plus-magenta diff images, a
  reproducible scalar magnitude, and refusals for everything that would let
  noise read as change — differing image sizes (never rescaled), engine
  versions (7.68% renderer noise), part ids or view sets. Pure scale is
  pixel-invisible by construction, so every render now records its framing
  bbox (`render_bbox`) and the render verb leaves `render.json` on disk;
  a bbox delta with identical pixels reads as change, referred to `measure`.
  Exposed over MCP as `vdiff`.
- `render --section xy|xz|yz[:offset]` cuts through a named plane and renders
  the cut with exposed material in a distinct colour, on both tiers (#19):
  OpenSCAD subtracts a half-space from its exported STL (kernel-capped), the
  OCCT tier booleans the shape, and the shared rasterizer draws both. The
  payload records the resolved plane, offset and cut-facet count; a plane
  that misses the part is refused with its span.
- `partspec lint` tier 2 — the geometry rules, over OpenSCAD's constant-folded
  `.csg` export via a hand-rolled stdlib reader (`csg.py`; sca2d is GPLv3 and
  geometry-blind, FreeCAD's importer LGPL and welded to its document model):
  `csg-coincident-face` (exact plane coincidence of cutter and minuend — zero
  epsilon, the literals are folded) and `csg-difference-order` (analytic
  upper-bound volumes, convention stated in the finding). Requires the engine;
  a missing engine, failed export, unmodelled node (`hull()` and kin on a
  rule's evaluation path) or string-carrying export produces per-rule
  `unsupported` entries — a rule that could not run is an entry, never an
  absence. Tier-2 findings carry line 0: the folded tree has no source lines
  (#118, #125).

### Changed

- Lint payload schema 2: per-file `{file, digest, findings[, unsupported]}`
  blocks — a clean file is a visible entry with the sha256 of the linted
  bytes, and duplicate arguments are deduped. A breaking reshape of the
  schema-1 payload that shipped in 0.5.0, versioned honestly (#120, #124).

### Fixed

- Module eviction covers every CLI exit path: contract-sibling imports are
  recorded and evicted on failed resolves and on the error paths of `check`,
  `measure` and `render` (record-in-finally), closing the remaining
  cross-directory stale-module windows (#114, #124).
- A stranded `cadquery-ocp-proxy` (proxy installed, no OCP — the observed
  `uv pip` outcome at the time) is named as the environment state with a
  plain-pip hint, instead of the circular "pip install partspec[occt]"
  (#109, #124).

## [0.5.0] - 2026-08-08

The repo teaches the craft it verifies (epic #3): skills, exemplars, the failure
catalogue, a source linter, and a recorded before/after on agent output.

### Added

- **`partspec lint`** — tier-1 advisory source lint over `.scad`/`.py` models, in the
  wheel and engine-free: five rules with exact predicates (`docs/LINT.md`), findings
  as data at exit 0 — advisory and never a verdict on the part — with 64 reserved for
  unlintable input. The `-1`/`+2` overshoot idiom is exempt by design; tier 2
  (geometry-dependent rules over the `.csg` tree) is deferred to #118 behind its
  prior-art survey (#119).
- **Three authoring skills** (repo content, not wheel content): `contract-authoring`
  (the decision table, the limit-provenance ladder, the retrofit path),
  `openscad-authoring`, and `build123d-authoring` — every executable claim in them is
  executed by the test suite, and several were corrected by exactly that discipline
  before shipping (#115, #116, #117).
- **Three worked exemplars** under `examples/`: a NEMA 17 bracket whose interface is
  one cited `nema17.mount` call, a bearing-seat family in OpenSCAD **and** build123d
  with shared claims stated once and the ISO 15 designations cited, and a
  sealed-cavity enclosure whose sealedness claim is `cavities(1)` — because an open
  tray is also watertight, one solid, genus 0 (#112).
- **`docs/FAILURE-MODES.md`** — the eight observed CAD-as-code failure modes from the
  dogfood corpus, each with symptom, root cause, detection, and what it looks like
  when green; raw record frozen at [`notes/dogfood-results.md`][dogfood-results] (#111).
- **The authoring before/after, recorded** ([`evals/AUTHORING.md`][authoring-evals]): guidance-present vs
  absent arms over exemplar-shaped tasks, 12 trials. Pass rate saturated (6/6 both
  arms); on the transfer tasks the guidance moved source quality from mixed to
  uniformly lint-clean (6 → 0 findings) while LoC rose — the added lines are the
  parameterisation. One task's treatment output was a line-for-line copy of a skill's
  own worked block; it is scored separately as retrieval and kept as the
  contamination exhibit (#121).
- **`notes/`** — the analysis the tracker cites (gap inventory, W1–W10 findings, the
  audit synthesis, as-filed tracker scripts) is tracked and visible to clones, with
  per-item dispositions recorded (#110).

### Fixed

- **`measure` reports `cavities`** — the number distinguishing a sealed enclosure
  from an open tray was absent from the verb whose job is showing every claimable
  number (#113, landed with #115).
- **A contract's sibling imports no longer cross directories** — a shared `claims.py`
  cached from directory A silently supplied directory B's checks in one process; the
  module-cache registry now covers resolve-time additions for every engine (#112).

## [0.4.0] - 2026-08-08

The loop can be trusted unattended (epic #4's remnant): a run that cannot hang, a
contract that cannot shrink silently, and the rules an agent follows written down.

### Added

- **Bounded builds.** `--timeout SECONDS` on `check`, `measure` and `render`
  (default 300 s, then `PARTSPEC_TIMEOUT`; `0` explicitly waives), recorded in
  `invocation.timeout_s`. A blown budget is `error` exit 4 with
  `build_origin: "environment"` naming the elapsed time and the budget — never a
  failing `builds` check: a stopwatch disproves nothing about the part. The Python
  tier gets a real SIGALRM bound that records it fired — a model whose mundane
  `except Exception` swallows the alarm still has its over-budget result discarded —
  and re-fires past `except Exception`; the residual ceilings (C-kernel hangs,
  signal-owning models, leaked threads) are stated in `SPEC-backend.md`, not hidden
  (#100).
- **Multi-target `check`.** One process, one report per part at its deterministic
  path, exit by highest-precedence verdict (`error > empty > fail > incomplete >
  pass`, SPEC-report §6.2); an unresolvable target exits 64 with the remaining
  targets still evaluated; placeholders for every target go down before any runs;
  colliding slugs under one `--out` are refused rather than silently overwritten.
  The `sys.modules` model cache is invalidated after every Python-engine build —
  a second contract importing an edited helper used to get the previous version, a
  stale build reported as fresh (POST-V0 §8) (#104).
- **The claims pin.** `check --pin LOCK` writes the declared claim set;
  `check --expect LOCK` fails before the engine starts unless the set matches
  exactly — removed, added, and changed claims named with both slugs, stripped
  `source` citations included, verdict `error` exit 4 with every check skipped and
  the adjudication in the artifact as `expectation`. A pinned part no target
  produced fails too. This closes silent contract weakening with **no baseline in
  hand**; `diff` remains the comparison half (#105).
- **`measure` is as identifiable as a report.** Its payload opens with the report's
  exact identity prefix (`schema_version`, `tool`, `part` with digests and closure,
  `engine`, `params`, `geometry`), built by the same code, and any failure after
  the target resolves emits that identity plus `error`/`hint` as JSON on stdout
  (#102).
- **`docs/AGENT-CONTRACT.md`** — the agent contract: a bounded 5-attempt repair
  loop with failure fed forward, an action map keyed on (exit, verdict, report
  fields), the greppable `HUMAN_REVIEW:` escalation format with its parse rule,
  and the out-of-bounds section naming the guards that watch every weakening move.
  A drift-guard test file holds the document's executable claims to the code (#106).

### Fixed

- **A missing third-party package at model import read as a disproven design.**
  Found live: a `uv sync` dropped a wheel and the batch reported the part as
  failing. Now `origin: "environment"`, exit 4, package named in the hint; a
  broken local import chain stays the part's fault (#101).
- **Stale bytecode could answer for an edited file.** CPython validates a `.pyc`
  by (mtime seconds, size), so a same-length edit within one second re-executed
  the OLD contract under the NEW `contract_digest` — precisely an agent's rapid
  edit-loop shape, and precisely what would blind the claims pin. Contract and
  model entry files now compile from source, never from the bytecode cache (#105).

## [0.3.0] - 2026-08-08

Reference data with provenance — limits that know where their numbers came from (epic #5).

### Added

- **`partspec.refs`** — reference tables shipped in the wheel, importable with no engine
  installed: ISO 15 deep-groove bearing boundary dimensions (`iso15`, 22 designations) and
  the NEMA 17 mounting interface (`nema17`, exact conversions of the standard's own inch
  figures, with the inch figure in every note) (#95, #96).
- **`Referenced` values.** A bound taken from a reference table carries its citation into
  the report as `checks[].source` (`{standard, subject, field}`). Arithmetic sheds the
  attribution — a derived number is the author's, and a fragment must never launder the
  designer's numbers into a standard's (#95).
- **Contract fragments.** `nema17.mount(p)` and `iso15.seat(p, 608)` declare an interface
  standard's checks in one call, with namespaced ids (`nema17:pilot`,
  `nema17:left:bolt_circle`) and atomic failure — an invalid argument lands no checks. The
  bolt pattern carries the standard's citation; the clearance diameters are the designer's
  arguments and deliberately carry none (#96).
- **The report says when it proved nothing external.** A run-level
  `attribution: {dimensional, attributed}` block, and a CLI warning when every dimensional
  limit is unattributed — bounds derived from the model's own numbers prove only that the
  model matches itself (#97). The signal lives in the artifact, not just on stderr, because
  the MCP tools run `--quiet`.

### Changed

- `partspec diff` treats a check's `source` as part of the claim: stripping a citation
  reports as `limit_changed`, so quietly de-attributing a limit is visible on comparison
  (#95).

### Fixed

- The first version of the NEMA 17 table cited the catalogue's 31 mm hole square to the
  standard and derived the pitch circle from it — exactly backwards: NEMA ICS 16 states the
  pitch circle (1.725 in) directly. Caught in review against the standard's own text before
  release; the corrected derivation is recorded in `SPEC-contract.md` §11 as the cautionary
  example (#96).

## [0.2.0] - 2026-08-08

A part proven against mechanical intent (epic #6): the check vocabulary reaches drawing
callouts, and reports become comparable.

### Added

- **`keep_out` / `keep_in`** — spatial claims over declared regions, each with a mandatory
  weak-form verification shell so a region check can never pass vacuously; the region
  materializes tier-identically as a circumscribed prism (#85, `SPEC-contract.md` §4.4).
- **`checks[].components`** — a vector check names the failing axis: per-axis statuses whose
  worst is exactly the check's own, one adjudication rendered two ways (#86).
- **`hole_diameter`** — the first drawing dimension: count claims over detected bores, OCCT
  tier only; the mesh tier refuses rather than approximating a cylinder from triangles
  (#87, §4.5).
- **`partspec diff`** — two reports compared semantically (`SPEC-diff.md`): `removed` /
  `added` / `regressed` / `fixed` / `drifted` / `limit_changed`, exit 0 identical / 1
  different / 2 indeterminate / 64 usage. A partial or missing source closure blocks only
  the `identical` claim, and every indeterminate entry carries a machine-readable code.
  This closes the silent-contract-weakening gap on comparison (#88).
- **`bolt_circle`** — the mounting-interface callout as one check: the pattern circle is
  least-squares fitted, adjudication is strict against the fitted centre, and `tol > d` is
  refused at declaration (#89, §4.6).
- **`fillet_radius`** — every cylindrical blend within bounds; a part with no detected
  blends FAILS rather than passing vacuously, and the message names the detection gap
  (toroidal/spherical blends) rather than claiming none exist (#90, §4.7).

### Changed

- Usage errors exit 64 CLI-wide — argparse's exit 2 is remapped, because 2 belongs to
  `incomplete` (#88).

## [0.1.0] - 2026-08-07

### Added

- The report/status seam (P0), specified before implementation because it — not the CLI
  verbs — is the product contract.
  - `status.py`: five check statuses, verdict precedence, exit-code mapping, and interval
    adjudication. A relative comparison epsilon, `1e-6 + 1e-7·|limit|`, because binary STL
    stores float32 and a flat `1e-6` fails a geometrically perfect part above ~16.8 mm.
  - `report.py`: the JSON artifact, fixed field order, atomic writes, and an `error`
    placeholder written *before* the engine runs, since a `try/finally` cannot survive an
    OCP segfault.
  - `backend.py`: the `GeometryBackend` protocol and value types. `Unsupported` is a return
    value rather than an exception.
- Specs and decision log under `docs/`, promoted from the design survey.
- A conformance test asserting the schema example in `docs/SPEC-report.md` satisfies its own
  stated rules — that example is the contract, so it should be executable.
- `just ocp-guard`, asserting exactly one OCP provider is installed. `cadquery-ocp` and
  `cadquery-ocp-novtk` both own the top-level `OCP/` package and pip does not detect the
  conflict.

- **P1 — the mesh backend.** OpenSCAD → binary STL → trimesh/manifold3d, never
  `--summary` (D13). Implements bbox, volume, area, centre of mass, watertightness, solid
  count, genus, min distance, intersect volume and raycast; refuses topology counts.
  - Verified against closed-form geometry rather than against its own output: a 30x20x10
    block with a 6x6 square through-hole checks out on volume, area, bbox, genus and centre
    of mass, and a `$fn=16` cylinder matches the **16-gon prism** volume, not `pi*r^2*h` —
    which is D15 in one assertion.
  - `solid_count` via `manifold3d.decompose()` and `distinct_normals` by face-normal
    counting, both because trimesh's equivalents need `scipy`/`networkx` (D16).
  - `genus` is refused for multi-body parts: manifold3d reports the genus of the whole
    complex (two disjoint boxes give -1), which answers a question nobody asked.

- **P2 — the contract API.** `Part` with the closed v0 check vocabulary, engine-declaring
  source constructors, target resolution (`<module>[:<factory>]`, where the error message
  lists the available factories rather than saying "ambiguous"), and a `requires` evaluator
  that records the operands it read.
  - Phase ordering with short-circuiting: a failing parameter check stops the engine from
    running, and the geometry checks are reported `skipped` naming the blocker rather than
    quietly omitted.
  - `check` and `measure` subcommands. `measure` emits nothing that would be unsupported
    and produces no verdict — it is the adoption path, and partspec deliberately will not
    auto-generate checks from it.
  - A worked example under `examples/spacer/`.

### Fixed

- **A contract declaring no checks exited 0.** The implicit `builds` check satisfied the
  emptiness test, so the tool defeated its own vacuous-green guard. `Report.verdict` now
  excludes implicit kinds; a contract that asserts nothing is `EMPTY` with exit 3, as
  `SPEC-contract.md` §6 had already specified.
- **Relative source paths resolved against the CWD**, so a contract worked or failed
  depending on the shell's history. They now anchor to the contract file's directory.
- **`operands_of` returned names in `ast.walk` order**, which is breadth-first: `z + a*z + m`
  came back as `(z, m, a)`. Now sorted by source position, since the order reaches a report
  that gets diffed.

- **P4 — the OCCT backend.** One implementation serving build123d *and* CadQuery, with
  adoption at the front door (`adopted_via: "wrapped"` records it). Answers
  `topology_counts`, which the mesh tier refuses — that asymmetry is the point of tiers.
  - `genus` via the Euler-Poincare form `G = S - (V - E + 2F - W)/2`. The naive
    `V - E + F` is wrong on a BREP and quietly so: OCCT faces carry inner wires, so it
    reports a through-hole as genus 0 and a *blind* hole as genus -1. Verified on a box,
    one and two through-holes, a blind hole, a tube, and a real pillow block (genus 5).
  - `engines/pycad.py` builds from either Python engine. Adoption dispatches on
    `ShapeType()`, because `build123d.Shape.cast` returns `None` in 0.11.1 and
    `Compound(topods_solid)` constructs happily while reporting volume 0.
  - Models are called as `method(**params)` — no signature inspection, no guessing. A
    differently-shaped model gets an explicit adapter in the contract.

### Fixed

- **`is_valid` was called as a method** on the OCCT backend, raising
  `TypeError: 'bool' object is not callable`. build123d exposes it as a property —
  the exact divergence `SPEC-backend.md` §4 documents as the reason the adopt shim exists.
- **CadQuery could not import at all** after adding the OCCT extras.
  `cadquery-ocp` and `cadquery-ocp-novtk` both install a top-level `OCP/` package (326 vs
  322 files) with no conflict detection, and novtk landed last, stripping the VTK modules.
  Fixed with a `[tool.uv] override-dependencies` marker that drops novtk from resolution.

- **P5 — the differential test.** One contract, the same specified part in OpenSCAD and
  CadQuery, reports compared field-by-field. No tool feature was needed: the contract is
  Python, so sharing claims across implementations is a function.
- **`openscad(..., backend=...)`** selects the render backend, recorded as
  `engine.render_backend`. It changes the *artifact*, not just the speed — measured, the
  default Manifold backend produced 4 non-manifold edges on a community gridfinity bin
  where CGAL produced a clean mesh from identical source.
- **`watertight` now says why it failed** — boundary edges (a hole) versus non-manifold
  edges (surfaces touching). trimesh's `is_watertight` conflates them, and they have
  different causes and different fixes.

- **`part.source_closure`** — a digest over *every* file an OpenSCAD render reads, not just
  the entry point. `source_digest` covers one file, and on real libraries that is a small
  fraction of the build: the gridfinity bin in the dogfood corpus is one file of sixteen, so
  editing a helper three levels down changes the part while the entry hash does not. That is
  F13's failure class arriving in the provenance layer, and `diff` would have inherited it.
  - Digested over sorted **content** hashes rather than paths, so a CI run and a laptop run
    of the same tree agree.
  - Reports what it could not cover: `unresolved` includes, and `reads_external_data` when
    `import()`/`surface()` name files whose paths may be computed at render time. Either
    sets `partial`, stated positively so absence cannot be read as a guarantee.
  - Python engines emit none — a claim withheld rather than one made. **(Historical note, corrected 2026-08-09: this was already untrue at the tag. The Python closure shipped in `83f1119`, inside v0.1.0, emitting `scope: "model_directory", partial: true`; SPEC-report §8.3 records the reversal two days before the tag and this entry was written from the superseded plan.)**. `environment.packages`
    already covers installed deps; local helper modules beside a model are a recorded gap.

- **`p.topology(faces=, edges=, vertices=)`** — modelled face/edge/vertex counts, and the
  first v0 check that a tier cannot answer. On build123d or CadQuery it compares real
  topology; on OpenSCAD it reports `unsupported` with `requires: "occt"`, because a triangle
  mesh has no modelled faces and returning a triangle count is the PartCAD failure. That
  path was previously unreachable from any contract — every other kind resolved to a
  primitive both backends declare — so `requires` had never appeared in a real report.
  Any subset of the three may be constrained; `p.topology()` with none is a `ContractError`.

- **`PARTSPEC_OPENSCAD`** pins the OpenSCAD binary. The engine version changes the
  artifact: 2021.01 honours the removed `assign()` construct and 2026.08.01 ignores it, so
  a gear library's teeth silently vanish and the part comes out 35% smaller in every planar
  dimension — both versions exiting 0 with clean watertight meshes. An environment variable
  rather than a contract field, because which binary is installed is a property of the
  machine, not of the design.

### Changed

- `geometry.facets` is now `geometry.distinct_normals` (D16), named for what it measures
  rather than borrowing CGAL's vocabulary for a different quantity.
- `GeometryBackend.provenance()` takes the artifact rather than reading instance state.
- `just setup` installs **all** extras, matching CI exactly; `just setup-mesh` is the
  lighter OpenSCAD-only path and is explicitly not what the gate runs.
- `measure` now also reports `is_valid` and, on the OCCT tier, `topology_counts` — a
  deliberate superset of the check vocabulary. `is_valid` is not a check kind because it
  means different things per tier (an open shell is valid on OCCT, invalid on mesh), and a
  kind whose meaning moves with the backend breaks the one-contract property.
- A vector limit may now leave components unconstrained — `equals=(6, None, None)` claims a
  face count and nothing else. Those axes are skipped rather than adjudicated; previously
  they raised, because a per-component `Limit` of three `None`s trips its own validation.
  A limit that constrains *no* component is a `ContractError`, since folding zero components
  would return `pass`.
- `volume`, `center_of_mass`, `solid_count` and `genus` may now return `Unsupported`. The
  protocol signatures widened to match; `bbox`, `area` and `watertight` stay total.

### Fixed

- **The mesh tier answered questions it could not answer** (dogfood F14) — the second of
  the three failure modes `docs/SPEC-report.md` §1.1 names, in the tool built to prevent
  it. A contract declaring `volume`, `solid_count` and `genus` but not `watertight` scored
  four green checks and exit 0 on a community gridfinity bin that partspec itself knew
  carried 4 non-manifold edges. Reduced: a cube missing one face reported `volume 500.0`
  (against 1000.0 closed), `genus 1` and a centre of mass outside the material — all
  flagged `exact`.

  Each quantity now declares its precondition (`docs/SPEC-backend.md` §5.1.1) and refuses
  with the defect named rather than returning a number. Deliberately narrow: `solid_count`
  is refused only for non-manifold edges, since an *open* mesh still determines its own
  component count and over-refusal is its own way of not answering.

- **A dependency's error status was discarded.** Handed an open mesh, manifold3d returns an
  object reporting `Error.NotManifold`, `is_empty()` and zero triangles — on which
  `.decompose()` still returns a one-element list and `.genus()` still returns 1. Both were
  read without checking `status()`. Now checked.

- **Two libraries were measuring two different solids into one report.** `volume` came from
  trimesh and `genus`/`solid_count` from manifold3d, which rebuilds its input: on the clean
  CGAL gridfinity render — same 5,330 vertices, none displaced — it retriangulated 55 of
  10,688 triangles and moved the enclosed volume by 25.31 mm³ (0.078 %). An independent
  divergence-theorem sum agrees with trimesh, not manifold3d. Body count and genus are now
  computed over the exported triangles, which is what D15 requires. Verified equivalent to
  manifold3d on sound meshes.

- **`same-source` OCCT gap closed too:** `volume` and `center_of_mass` refuse for a shape
  bounding no solid. An open shell reports `volume 0.0` with `is_valid` True, so
  `volume(max=…)` would have passed on a shape containing no material.

### Notes

- The `approximate` machinery ships dormant. As v0 is scoped no check can produce it, so it
  is covered by direct unit tests rather than by use — see `docs/SPEC-report.md` §10.
- `just test-mesh-only` runs the mesh tests against a throwaway `partspec[mesh]` install.
  Because `just setup` takes all extras and scipy arrives only via build123d/cadquery, a
  mesh-tier dependency on scipy would otherwise pass both locally and in CI while breaking
  every mesh-only user.

- `PARTSPEC_REQUIRE_ENGINES` turns a missing engine from a skipped test into a hard failure.
  CI reported 195 passed / 23 skipped because no runner had an OpenSCAD binary, and the 23
  were the entire end-to-end path. The gate was green because the tests were absent.
- CI runs the mesh tier across **two OpenSCAD versions** — apt 2021.01 and a pinned
  2026.08.01 snapshot — because F13 found the same source builds a different part on each,
  and one version leaves that an anecdote. A step asserts each leg got the engine it
  declares, so an apt bump cannot collapse the matrix while still reporting two green checks.
  `just test-mesh-only` becomes a CI job; it guards a failure mode defined as "passes
  locally and in CI" and had been running only locally.
- `tests/test_cli.py` — the verbs had no tests at all, on a design whose D5 makes the exit
  code half the product contract. Every verdict now round-trips through `main` on a real
  render.

### Fixed

- **`measure` went silent exactly where it became most useful.** It dropped every
  `Unsupported` result, which was honest while a refusal only meant "this tier cannot answer
  this quantity". Since D17 it also means "this part is broken, and here is the defect", and
  the two arrived identically: absent. On a cube missing one face, `measure` printed area,
  bbox and solid_count with no volume, centre of mass or genus — in the verb that exists so
  somebody can see the numbers before deciding which are intent. `refused` now carries the
  reason per quantity and `unavailable` lists tier gaps separately.
- **A contract that raises exited 1** — this tool's code for *the part failed its contract*.
  A mistyped keyword argument raised `TypeError` out of `resolve()` and the traceback escaped
  `main`, so a malformed question was reported as a wrong answer about the design. Now exit
  4, for the same reason a `ContractError` during a run is.
- **The engine was resolved from a hardcoded path in `$HOME`.** `find_executable` preferred
  `~/Applications/openscad/OpenSCAD-nightly.AppImage` ahead of `PATH`, so `which openscad`
  said 2021.01 while every render used 2026.08.01 — on a tool whose own F13 says the version
  changes the part. The dogfood write-up claimed the wrong engine for two days as a result;
  the reports never did. The rule is now the pin, then `PATH`.
- **OpenSCAD's own diagnosis was discarded** unless it contained `ERROR` or `WARNING`, so
  `unrecognised option '--backend=CGAL'` — what 2021.01 says to a contract written against a
  newer engine — became `openscad exited 1` with no hint.
- **A mistyped `PARTSPEC_OPENSCAD` raised `FileNotFoundError` out of `run()`**, escaping the
  report machinery entirely: no artifact, no verdict, no exit code. Now a `BuildError`.
- **The Python tier recorded one file as the whole build input.** `engines/pycad.py` puts the
  model's directory on `sys.path` so a model can import helpers beside it, which makes those
  helpers build inputs by design — and editing one changed the part while `source_digest`
  stayed identical. `part.source_closure` now covers them, read from `sys.modules` after the
  build, with `partial` unconditional. `SPEC-report.md` §8.3 previously specified emitting
  nothing here; the reversal and its reasoning are recorded in place.

### Added

- **P6 — the product surface for agents.** `partspec-mcp`, an MCP server exposing `check`,
  `measure` and `render` as stateless tools — every call a fresh subprocess returning the
  same artifact the CLI writes, per the D18 boundary (#63, #66). `partspec render` emits
  canonical multi-view PNGs on the mesh tier, and the report references the renders it
  produced (#64, #65).
- **The convergence eval, run and recorded** ([`evals/CONVERGENCE.md`][convergence-evals]): 15/15 trials across
  five defect classes, an agent taking a broken part to green with exactly one edit each and
  zero contract-weakening attempts (#67).
- Tagged releases publish to PyPI via trusted publishing: tag/version assertion, build,
  `twine check`, cold-wheel smoke test, then OIDC upload (#60).

### Fixed

- The two pre-tag adversarial audits (#56, #57) and the eight-defect close: measurements
  that lied, failures that blamed the part instead of the machine, and one rename the audit
  itself got backwards.
- Release-window fixes (#70–#77): a failed build's hint is the diagnosis rather than a
  cache statistic; comparison operators slug to distinct check ids; the report records the
  invoked callable and how parameters applied; `engine.render_backend` is always present;
  `measure` and `render` carry the same engine provenance as `check`; the OpenSCAD method
  scratch moved out of the source tree.

[authoring-evals]: https://github.com/CameronBrooks11/partspec/blob/main/evals/AUTHORING.md
[convergence-evals]: https://github.com/CameronBrooks11/partspec/blob/main/evals/CONVERGENCE.md
[dogfood-results]: https://github.com/CameronBrooks11/partspec/blob/main/notes/dogfood-results.md

[Unreleased]: https://github.com/CameronBrooks11/partspec/compare/v0.7.4...HEAD
[0.7.4]: https://github.com/CameronBrooks11/partspec/compare/v0.7.3...v0.7.4
[0.7.3]: https://github.com/CameronBrooks11/partspec/compare/v0.7.2...v0.7.3
[0.7.2]: https://github.com/CameronBrooks11/partspec/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/CameronBrooks11/partspec/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/CameronBrooks11/partspec/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/CameronBrooks11/partspec/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/CameronBrooks11/partspec/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/CameronBrooks11/partspec/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/CameronBrooks11/partspec/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/CameronBrooks11/partspec/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/CameronBrooks11/partspec/releases/tag/v0.1.0
