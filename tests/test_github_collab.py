from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_access.github_collab import (
    fetch_repo_for_token,
    get_collaborator_permission,
    github_user_exists,
)


@pytest.fixture
def mock_session() -> MagicMock:
    with patch("agent_access.github_collab._session") as m:
        sess = MagicMock()
        m.return_value = sess
        yield sess


def test_github_user_exists_true(mock_session: MagicMock) -> None:
    r = MagicMock()
    r.status_code = 200
    mock_session.get.return_value = r
    assert github_user_exists("octocat") is True


def test_github_user_exists_false(mock_session: MagicMock) -> None:
    r = MagicMock()
    r.status_code = 404
    mock_session.get.return_value = r
    assert github_user_exists("nope_nope") is False


def test_fetch_repo_for_token_ok(mock_session: MagicMock) -> None:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"full_name": "o/r", "permissions": {"admin": True}}
    mock_session.get.return_value = r
    data = fetch_repo_for_token("o", "r")
    assert data["full_name"] == "o/r"
    assert data["permissions"]["admin"] is True


def test_fetch_repo_for_token_not_found(mock_session: MagicMock) -> None:
    r = MagicMock()
    r.status_code = 404
    mock_session.get.return_value = r
    with pytest.raises(RuntimeError, match="not found"):
        fetch_repo_for_token("o", "missing")


def test_get_collaborator_permission_none(mock_session: MagicMock) -> None:
    r = MagicMock()
    r.status_code = 404
    mock_session.get.return_value = r
    assert get_collaborator_permission("o", "r", "u") is None


def test_get_collaborator_permission_write(mock_session: MagicMock) -> None:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"permission": "write"}
    mock_session.get.return_value = r
    assert get_collaborator_permission("o", "r", "u") == "write"
