#!/usr/bin/env python3
"""After a PR merges into main, bump [project].version if the PR has a release label.

Labels (exactly one bump tier is enough; if several are present, the strongest wins):
  release:patch  -> Z+1 in X.Y.Z
  release:minor  -> Y+1, Z=0
  release:major  -> X+1, Y=Z=0

Skips (exit 0) when:
  - PR is not merged (should not run)
  - No release:* label on the PR
  - pyproject [project].version already differs between merge commit and first parent
    (version was changed in the PR — manual bump; Tag workflow will still run on that merge)

After this script commits and pushes, Tag on version bump creates v{x.y.z}.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir),
)

RELEASE_LABEL_RANK = {
    "release:patch": 0,
    "release:minor": 1,
    "release:major": 2,
}


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=REPO_ROOT, check=True, text=True)


def parse_semver_triple(v: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", v.strip())
    if not m:
        raise ValueError(f"Expected semver X.Y.Z, got {v!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def format_version(parts: tuple[int, int, int]) -> str:
    return f"{parts[0]}.{parts[1]}.{parts[2]}"


def bump_version(current: str, rank: int) -> str:
    x, y, z = parse_semver_triple(current)
    if rank == 2:
        return format_version((x + 1, 0, 0))
    if rank == 1:
        return format_version((x, y + 1, 0))
    return format_version((x, y, z + 1))


def version_from_pyproject_bytes(blob: bytes) -> str:
    data = tomllib.loads(blob.decode())
    v = data.get("project", {}).get("version")
    if not v:
        raise ValueError("No [project].version in pyproject.toml")
    return str(v).strip()


def git_show(path_in_repo: str) -> bytes:
    return subprocess.check_output(["git", "show", path_in_repo], cwd=REPO_ROOT)


def choose_bump_rank(label_names: list[str]) -> int | None:
    ranks = [RELEASE_LABEL_RANK[n] for n in label_names if n in RELEASE_LABEL_RANK]
    if not ranks:
        return None
    return max(ranks)


def replace_pyproject_version(text: str, new_ver: str) -> str:
    def repl(m: re.Match[str]) -> str:
        q = m.group(1)
        return f'version = {q}{new_ver}{q}'

    out, n = re.subn(
        r'^version\s*=\s*(["\'])([^"\']*)\1\s*$',
        repl,
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n != 1:
        raise ValueError("Could not find project version line in pyproject.toml")
    return out


def replace_init_version(text: str, new_ver: str) -> str:
    out, n = re.subn(
        r'^(__version__\s*=\s*)(["\'])([^"\']*)\2',
        lambda m: f"{m.group(1)}{m.group(2)}{new_ver}{m.group(2)}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n != 1:
        raise ValueError("Could not find __version__ in agent_access/__init__.py")
    return out


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not os.path.isfile(event_path):
        print("::error::GITHUB_EVENT_PATH missing", file=sys.stderr)
        return 1

    with open(event_path, encoding="utf-8") as f:
        event = json.load(f)

    pr = event.get("pull_request") or {}
    if not pr.get("merged"):
        print("PR not merged; skipping.")
        return 0

    merge_sha = pr.get("merge_commit_sha") or ""
    if not merge_sha:
        print("::error::No merge_commit_sha on event", file=sys.stderr)
        return 1

    labels = [str(l.get("name", "")) for l in pr.get("labels", [])]
    rank = choose_bump_rank(labels)
    if rank is None:
        print("No release:patch / release:minor / release:major label; skipping version bump.")
        return 0

    bump_name = [k for k, v in RELEASE_LABEL_RANK.items() if v == rank][0]
    pr_num = pr.get("number", "?")

    try:
        at_merge = version_from_pyproject_bytes(git_show(f"{merge_sha}:pyproject.toml"))
        at_parent = version_from_pyproject_bytes(git_show(f"{merge_sha}^1:pyproject.toml"))
    except subprocess.CalledProcessError as e:
        print(f"::error::git show failed: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1

    if at_merge != at_parent:
        print(
            f"[project].version changed in the merge ({at_parent!r} -> {at_merge!r}); "
            "skipping automated bump (manual release).",
        )
        return 0

    current = at_merge
    next_ver = bump_version(current, rank)
    if next_ver == current:
        print(f"::warning::Bump produced same version {current!r}; skipping.")
        return 0

    pp_path = os.path.join(REPO_ROOT, "pyproject.toml")
    init_path = os.path.join(REPO_ROOT, "agent_access", "__init__.py")
    with open(pp_path, encoding="utf-8") as f:
        pp_text = f.read()
    with open(init_path, encoding="utf-8") as f:
        init_text = f.read()

    new_pp = replace_pyproject_version(pp_text, next_ver)
    new_init = replace_init_version(init_text, next_ver)

    with open(pp_path, "w", encoding="utf-8") as f:
        f.write(new_pp)
    with open(init_path, "w", encoding="utf-8") as f:
        f.write(new_init)

    body = f"Automated bump from merged PR #{pr_num} (label: {bump_name})."
    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    run(["git", "add", "pyproject.toml", "agent_access/__init__.py"])
    run(
        [
            "git",
            "commit",
            "-m",
            f"chore(release): {next_ver}\n\n{body}",
        ],
    )
    run(["git", "push", "origin", "HEAD:main"])
    print(f"Pushed version bump {current!r} -> {next_ver!r} ({bump_name}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())