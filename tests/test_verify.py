from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_access.config import load_project_config
from agent_access.verify import (
    VerifyCheck,
    format_verification_report,
    run_verification,
    verification_succeeded,
)
from tests.conftest import minimal_project_yaml, write_yaml


def test_verification_succeeded_all_ok() -> None:
    checks = [
        VerifyCheck("a", True, "ok"),
        VerifyCheck("b", True, "ok"),
    ]
    assert verification_succeeded(checks) is True


def test_verification_succeeded_one_fail() -> None:
    checks = [
        VerifyCheck("a", True, "ok"),
        VerifyCheck("b", False, "bad"),
    ]
    assert verification_succeeded(checks) is False


def test_format_verification_report() -> None:
    checks = [VerifyCheck("x", True, "fine"), VerifyCheck("y", False, "nope")]
    text = format_verification_report("demo", checks)
    assert "demo" in text
    assert "[OK] x:" in text
    assert "[FAIL] y:" in text
    assert "FAILED" in text


def test_run_verification_no_network_resources(
    keypair: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_GITHUB_TOKEN", raising=False)
    master, pub = keypair
    cfg_path = tmp_path / "c.yml"
    write_yaml(cfg_path, minimal_project_yaml(master, pub))
    cfg = load_project_config(cfg_path, "t")
    checks, pubkeys = run_verification(cfg)
    assert verification_succeeded(checks)
    assert pubkeys is not None and len(pubkeys) == 1
    labels = [c.label for c in checks]
    assert "Master SSH private key" in labels
    assert "Agent public key file" in labels
    assert any(c.label == "GitHub" and "no repositories" in c.detail for c in checks)


@patch("agent_access.verify.pending_repository_invitation_for_user", return_value=False)
@patch("agent_access.verify.is_repository_collaborator", return_value=True)
@patch("agent_access.verify._verify_ssh_server")
@patch("agent_access.verify.fetch_repo_for_token")
@patch("agent_access.verify.github_user_exists", return_value=True)
def test_run_verification_github_admin_ok(
    mock_user: MagicMock,
    mock_fetch: MagicMock,
    mock_ssh: MagicMock,
    mock_is_collab: MagicMock,
    mock_pending: MagicMock,
    keypair: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token-for-test")
    mock_fetch.return_value = {"permissions": {"admin": True}, "role_name": "admin"}
    master, pub = keypair
    cfg_path = tmp_path / "c.yml"
    write_yaml(
        cfg_path,
        minimal_project_yaml(
            master,
            pub,
            servers=[],
            github=[{"name": "Lib", "description": "d", "repo": "o/r"}],
        ),
    )
    cfg = load_project_config(cfg_path, "t")
    checks, _ = run_verification(cfg)
    assert verification_succeeded(checks)
    mock_ssh.assert_not_called()


@patch("agent_access.verify.pending_repository_invitation_for_user", return_value=False)
@patch("agent_access.verify.is_repository_collaborator", return_value=False)
@patch("agent_access.verify._verify_ssh_server")
@patch("agent_access.verify.fetch_repo_for_token")
@patch("agent_access.verify.github_user_exists", return_value=True)
def test_run_verification_github_token_from_config(
    mock_user: MagicMock,
    mock_fetch: MagicMock,
    mock_ssh: MagicMock,
    mock_is_collab: MagicMock,
    mock_pending: MagicMock,
    keypair: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_GITHUB_TOKEN", raising=False)
    mock_fetch.return_value = {"permissions": {"admin": True}, "role_name": "admin"}
    master, pub = keypair
    cfg_path = tmp_path / "c.yml"
    write_yaml(
        cfg_path,
        minimal_project_yaml(
            master,
            pub,
            servers=[],
            github=[{"name": "Lib", "description": "d", "repo": "o/r"}],
            master_github_token="fake-token-from-config",
        ),
    )
    cfg = load_project_config(cfg_path, "t")
    checks, _ = run_verification(cfg)
    assert verification_succeeded(checks)
    assert any(
        c.label == "GitHub token"
        and "access.master.github_token in config" in c.detail
        for c in checks
    )
    mock_ssh.assert_not_called()


@patch("agent_access.verify.fetch_authenticated_user_login", return_value="someuser")
@patch("agent_access.verify.pending_repository_invitation_for_user", return_value=False)
@patch("agent_access.verify.is_repository_collaborator", return_value=True)
@patch("agent_access.verify._verify_ssh_server")
@patch("agent_access.verify.fetch_repo_for_token")
@patch("agent_access.verify.github_user_exists", return_value=True)
def test_run_verification_github_agent_pat_ok(
    mock_user: MagicMock,
    mock_fetch: MagicMock,
    mock_ssh: MagicMock,
    mock_is_collab: MagicMock,
    mock_pending: MagicMock,
    mock_agent_login: MagicMock,
    keypair: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token-for-test")
    mock_fetch.return_value = {"permissions": {"admin": True}, "role_name": "admin"}
    master, pub = keypair
    cfg_path = tmp_path / "c.yml"
    write_yaml(
        cfg_path,
        minimal_project_yaml(
            master,
            pub,
            servers=[],
            github=[{"name": "Lib", "description": "d", "repo": "o/r"}],
            agent_github_token="ghp_agent_fake",
        ),
    )
    cfg = load_project_config(cfg_path, "t")
    checks, _ = run_verification(cfg)
    assert verification_succeeded(checks)
    assert any(c.label == "Agent GitHub token (invitee PAT)" and c.ok for c in checks)


@patch("agent_access.verify.fetch_repo_for_token")
@patch("agent_access.verify.github_user_exists", return_value=True)
def test_run_verification_github_not_admin(
    mock_user: MagicMock,
    mock_fetch: MagicMock,
    keypair: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token-for-test")
    mock_fetch.return_value = {"permissions": {"admin": False, "push": True}}
    master, pub = keypair
    cfg_path = tmp_path / "c.yml"
    write_yaml(
        cfg_path,
        minimal_project_yaml(
            master,
            pub,
            github=[{"name": "Lib", "description": "d", "repo": "o/r"}],
        ),
    )
    cfg = load_project_config(cfg_path, "t")
    checks, _ = run_verification(cfg)
    assert verification_succeeded(checks) is False
    assert any(not c.ok and "admin" in c.detail for c in checks)
