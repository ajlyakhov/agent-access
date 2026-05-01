"""Unit tests for .github/scripts/release_bump_from_merged_pr.py logic."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "scripts"
    / "release_bump_from_merged_pr.py"
)


@pytest.fixture(scope="module")
def rb_mod():
    spec = importlib.util.spec_from_file_location("release_bump", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bump_patch(rb_mod) -> None:
    assert rb_mod.bump_version("0.1.0", 0) == "0.1.1"


def test_bump_minor(rb_mod) -> None:
    assert rb_mod.bump_version("0.1.9", 1) == "0.2.0"


def test_bump_major(rb_mod) -> None:
    assert rb_mod.bump_version("0.2.0", 2) == "1.0.0"


def test_choose_rank(rb_mod) -> None:
    assert rb_mod.choose_bump_rank(["release:patch"]) == 0
    assert rb_mod.choose_bump_rank(["release:minor", "release:patch"]) == 1
    assert rb_mod.choose_bump_rank(["release:patch", "release:major"]) == 2
    assert rb_mod.choose_bump_rank(["unrelated"]) is None


def test_replace_pyproject_version(rb_mod) -> None:
    s = 'other = "x"\nversion = "1.0.0"\n'
    assert "1.2.3" in rb_mod.replace_pyproject_version(s, "1.2.3")
