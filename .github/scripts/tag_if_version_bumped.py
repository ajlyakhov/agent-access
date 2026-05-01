#!/usr/bin/env python3
"""Create and push an annotated git tag when [project].version changes in pyproject.toml.

Expects agent_access/__init__.py __version__ to match. Intended for GitHub Actions on push to main.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir),
)


def run(cmd: list[str], **kwargs: object) -> None:
    subprocess.run(cmd, cwd=REPO_ROOT, check=True, text=True, **kwargs)


def version_from_pyproject_bytes(blob: bytes) -> str | None:
    try:
        data = tomllib.loads(blob.decode())
        v = data.get("project", {}).get("version")
        return str(v).strip() if v else None
    except Exception:
        return None


def version_from_parent_commit() -> str | None:
    try:
        blob = subprocess.check_output(
            ["git", "show", "HEAD~1:pyproject.toml"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
        )
        return version_from_pyproject_bytes(blob)
    except subprocess.CalledProcessError:
        return None


def read_pyproject_version() -> str:
    path = os.path.join(REPO_ROOT, "pyproject.toml")
    with open(path, "rb") as f:
        data = tomllib.load(f)
    v = data.get("project", {}).get("version")
    if not v:
        print("::error::Missing [project].version in pyproject.toml", file=sys.stderr)
        sys.exit(1)
    return str(v).strip()


def read_init_version() -> str | None:
    path = os.path.join(REPO_ROOT, "agent_access", "__init__.py")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    return m.group(1) if m else None


def remote_tag_exists(tag: str) -> bool:
    r = subprocess.run(
        ["git", "ls-remote", "origin", f"refs/tags/{tag}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return bool(r.stdout.strip())


def main() -> int:
    new_ver = read_pyproject_version()
    init_ver = read_init_version()
    if init_ver != new_ver:
        print(
            f"::error::Version mismatch: pyproject.toml has {new_ver!r}, "
            f"agent_access/__init__.py __version__ is {init_ver!r}",
            file=sys.stderr,
        )
        return 1

    old_ver = version_from_parent_commit()
    if old_ver == new_ver:
        print(f"No version bump (still {new_ver}); not tagging.")
        return 0

    if old_ver is not None:
        print(f"Version bump: {old_ver!r} -> {new_ver!r}")
    else:
        print(
            f"No pyproject.toml on HEAD~1 (new file or shallow history); "
            f"will tag if {new_ver!r} is not already on origin.",
        )

    tag = f"v{new_ver}"
    if remote_tag_exists(tag):
        print(f"Tag {tag} already exists on origin; skipping.")
        return 0

    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    run(["git", "tag", "-a", tag, "-m", f"chore(release): {tag}"])
    run(["git", "push", "origin", tag])
    print(f"Pushed annotated tag {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
