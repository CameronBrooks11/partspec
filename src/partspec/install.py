"""How to phrase an install command for the environment that will read it.

Every hint naming an installer is read inside the environment the fault
happened in, and `pip` is not a given there: a `uv venv` ships none. Absent
would be the kind outcome. What actually happens on a distro that packages pip
is worse — the word still resolves, to `/usr/bin/pip`, which installs into the
*system* interpreter. So the remedy for an environment fault runs, reports
success, changes nothing the failing interpreter can see, and the next run
prints a byte-identical diagnosis.

That is the failure this tool exists to refuse, one level up: naming a problem
and handing over an answer that does nothing is a quieter version of naming a
problem and withholding the answer (SPEC-report §6.1). Found on the v0.7.3 cold
verify, in a `uv venv` — the install shape our own README documents.

Detection is `find_spec` and deliberately not `shutil.which`, because `which`
is precisely what finds the misleading system pip. The question a hint has to
answer is whether *this interpreter* can install, not whether the word resolves
to something on PATH.
"""

from __future__ import annotations

import importlib.util

__all__ = ["install_hint"]


def install_hint(pip: str, uv: str | None = None) -> str:
    """An install command spelled for the interpreter that will read it.

    `pip` is the argument tail as pip spells it. Pass `uv` where the two
    installers disagree on more than the prefix — reinstall does — and
    otherwise uv takes the same words behind its own.
    """
    if importlib.util.find_spec("pip") is not None:
        return f"pip install {pip}"
    return f"uv pip install {pip if uv is None else uv}"
