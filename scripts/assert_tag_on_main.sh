#!/usr/bin/env bash
# Refuse to publish a commit that main's `ok` gate never saw.
#
# `release.yml` runs no tests, deliberately: it verifies the artifact, and
# correctness is the gate's job on every commit that reaches main. That
# argument is only true if the tag is ON main. Before this script the
# workflow stated it in prose and enforced nothing, so
#
#     git tag v9.9.9 <any-commit> && git push --tags
#
# would have published code no gate ever ran against.
#
# A script rather than inline YAML because the workflow cannot be tested:
# a grep over release.yml proves a string is present, not that the gate
# blocks anything, and one-character edits (dropping the `!`, or `exit 0`)
# turn an inline gate into a no-op that still greps clean. This runs
# against throwaway repositories in the test suite.
#
# Usage: assert_tag_on_main.sh <commit-sha> [main-ref]
# Exit:  0 the commit is on main and may be published
#        1 it is not, or the question could not be answered
set -euo pipefail

commit="${1:?usage: assert_tag_on_main.sh <commit-sha> [main-ref]}"
main_ref="${2:-origin/main}"

if ! git rev-parse --verify --quiet "$main_ref" >/dev/null; then
  echo "::error::cannot resolve $main_ref, so the tag's ancestry cannot be established."
  echo "::error::Refusing to publish rather than assuming. A shallow checkout does this;"
  echo "::error::the release job needs fetch-depth: 0."
  exit 1
fi

# --is-ancestor peels annotated tag objects to their commit, so this holds
# whether GITHUB_SHA is a commit (what a tag push actually provides) or a
# tag object.
if git merge-base --is-ancestor "$commit" "$main_ref"; then
  echo "$commit is on $main_ref."
  exit 0
fi

echo "::error::$commit is not on $main_ref."
echo "::error::Nothing in the release workflow runs the test suite. The ok gate on"
echo "::error::main is the only thing between this commit and PyPI, and it never ran."
exit 1
