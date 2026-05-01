from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_access.__main__ import main
from agent_access.verify import VerifyCheck
from tests.conftest import minimal_project_yaml, write_yaml


def test_cli_verify_ok_local_only(
    keypair: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    master, pub = keypair
    cfg_path = tmp_path / "c.yml"
    write_yaml(cfg_path, minimal_project_yaml(master, pub))
    assert main(["--config", str(cfg_path), "verify", "t"]) == 0


def test_cli_verify_fails_missing_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cfg_path = tmp_path / "c.yml"
    cfg_path.write_text(
        """
only:
  access:
    master:
      private_key_path: /nonexistent/master
    agent:
      github_name: u
      pubkey_path: /nonexistent/pub
  resources:
    servers: []
    github: []
""",
        encoding="utf-8",
    )
    assert main(["--config", str(cfg_path), "verify", "only"]) == 1


def test_cli_show_prints_file(tmp_path: Path) -> None:
    cfg_path = tmp_path / "c.yml"
    cfg_path.write_text("foo: bar\n", encoding="utf-8")
    import io
    import sys

    buf = io.StringIO()
    old = sys.stdout
    try:
        sys.stdout = buf
        assert main(["--config", str(cfg_path), "show"]) == 0
    finally:
        sys.stdout = old
    assert buf.getvalue() == "foo: bar\n"


def test_cli_show_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yml"
    assert main(["--config", str(missing), "show"]) == 1


@patch("agent_access.__main__.run_verification")
@patch("agent_access.__main__.load_project_config")
def test_enable_aborts_on_failed_verify(
    mock_load: MagicMock,
    mock_run: MagicMock,
    tmp_path: Path,
) -> None:
    mock_cfg = MagicMock()
    mock_cfg.name = "p"
    mock_load.return_value = mock_cfg
    mock_run.return_value = (
        [VerifyCheck("bad", False, "error")],
        ("ssh-rsa AAA",),
    )
    assert (
            main(
                [
                    "--config",
                    str(tmp_path / "x.yml"),
                    "enable",
                    "-y",
                    "p",
                ],
            )
        == 1
    )


@patch("agent_access.__main__.run_verification")
@patch("agent_access.__main__.load_project_config")
@patch("agent_access.__main__.ensure_authorized_keys")
@patch("agent_access.__main__._print_agent_context")
def test_enable_skips_ops_when_verify_fails_before_keys(
    mock_ctx: MagicMock,
    mock_ssh: MagicMock,
    mock_load: MagicMock,
    mock_run: MagicMock,
    tmp_path: Path,
) -> None:
    mock_cfg = MagicMock()
    mock_cfg.name = "p"
    mock_cfg.servers = []
    mock_cfg.github_repos = []
    mock_load.return_value = mock_cfg
    mock_run.return_value = (
        [VerifyCheck("bad", False, "error")],
        ("ssh-rsa AAA",),
    )
    main(["--config", str(tmp_path / "x.yml"), "enable", "-y", "p"])
    mock_ssh.assert_not_called()
    mock_ctx.assert_not_called()
