from __future__ import annotations

from typing import Any, Literal

import requests

from agent_access.config import AccessConfig, resolve_master_github_token

GITHUB_API = "https://api.github.com"

GithubInviteOutcome = Literal["invited", "active"]


def _session(access: AccessConfig | None = None) -> requests.Session:
    token = resolve_master_github_token(access)
    if not token:
        raise RuntimeError(
            "GitHub token not set: set GITHUB_TOKEN or access.master.github_token in config",
        )
    s = requests.Session()
    s.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return s


def _http_error_detail(resp: requests.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = data.get("message")
            errs = data.get("errors")
            if isinstance(msg, str):
                if errs is not None:
                    return f"{msg} ({errs!r})"
                return msg
    except Exception:
        pass
    text = (resp.text or "").strip()
    return text[:800] if text else "(empty body)"


def _raise_github(resp: requests.Response, action: str) -> None:
    raise RuntimeError(
        f"GitHub {action} failed: HTTP {resp.status_code}: {_http_error_detail(resp)}",
    )


def _session_with_bearer(bearer: str) -> requests.Session:
    token = bearer.strip()
    if not token:
        raise RuntimeError("bearer token is empty")
    s = requests.Session()
    s.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return s


def add_collaborator(
    owner: str,
    repo: str,
    username: str,
    permission: str,
    *,
    access: AccessConfig | None = None,
) -> GithubInviteOutcome:
    """
    Invite or update collaborator. Returns 'invited' when GitHub created a new invitation
    (HTTP 201); the invitee must accept before they have git/push access.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/collaborators/{username}"
    session = _session(access)
    resp = session.put(url, json={"permission": permission}, timeout=60)
    if resp.status_code == 201:
        return "invited"
    if resp.status_code == 204:
        return "active"
    if resp.status_code == 422:
        try:
            body: Any = resp.json()
            msg = body.get("message", resp.text)
        except Exception:
            msg = resp.text
        if "already" in str(msg).lower():
            return "active"
        _raise_github(resp, "add collaborator")
    _raise_github(resp, "add collaborator")


def _cancel_pending_invitations(
    session: requests.Session,
    owner: str,
    repo: str,
    username: str,
) -> None:
    """Revoke open repo invitations for username (login match)."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/invitations"
    resp = session.get(url, timeout=60)
    if resp.status_code != 200:
        return
    raw: Any = resp.json()
    if not isinstance(raw, list):
        return
    want = username.lower()
    for inv in raw:
        if not isinstance(inv, dict):
            continue
        invitee = inv.get("invitee")
        if not isinstance(invitee, dict):
            continue
        login = str(invitee.get("login", "")).lower()
        if login != want:
            continue
        iid = inv.get("id")
        if not isinstance(iid, int):
            continue
        del_url = f"{GITHUB_API}/repos/{owner}/{repo}/invitations/{iid}"
        dr = session.delete(del_url, timeout=60)
        if dr.status_code not in (204, 404):
            _raise_github(dr, "cancel invitation")


def remove_collaborator(
    owner: str,
    repo: str,
    username: str,
    *,
    access: AccessConfig | None = None,
) -> None:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/collaborators/{username}"
    session = _session(access)
    resp = session.delete(url, timeout=60)
    if resp.status_code == 204:
        return
    if resp.status_code == 404:
        _cancel_pending_invitations(session, owner, repo, username)
        return
    _raise_github(resp, "remove collaborator")


def pending_repository_invitation_for_user(
    owner: str,
    repo: str,
    username: str,
    *,
    access: AccessConfig | None = None,
) -> bool:
    """True if there is an open repo invitation for this login."""
    session = _session(access)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/invitations"
    resp = session.get(url, timeout=60)
    if resp.status_code != 200:
        return False
    raw: Any = resp.json()
    if not isinstance(raw, list):
        return False
    want = username.lower()
    for inv in raw:
        if not isinstance(inv, dict):
            continue
        invitee = inv.get("invitee")
        if not isinstance(invitee, dict):
            continue
        if str(invitee.get("login", "")).lower() == want:
            return True
    return False


def is_repository_collaborator(
    owner: str,
    repo: str,
    username: str,
    *,
    access: AccessConfig | None = None,
) -> bool:
    """True if username is already an accepted collaborator (not merely invited)."""
    session = _session(access)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/collaborators/{username}"
    resp = session.get(url, timeout=60)
    if resp.status_code == 204:
        return True
    if resp.status_code == 404:
        return False
    _raise_github(resp, "check collaborator membership")


def split_owner_repo(full: str) -> tuple[str, str]:
    owner, repo = full.split("/", 1)
    return owner, repo


def github_user_exists(username: str, *, access: AccessConfig | None = None) -> bool:
    """Return True if the login exists on GitHub."""
    session = _session(access)
    url = f"{GITHUB_API}/users/{username}"
    resp = session.get(url, timeout=60)
    if resp.status_code == 404:
        return False
    resp.raise_for_status()
    return True


def fetch_repo_for_token(
    owner: str,
    repo: str,
    *,
    access: AccessConfig | None = None,
) -> dict[str, Any]:
    """GET repository as the authenticated token; body includes permissions for the token."""
    session = _session(access)
    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    resp = session.get(url, timeout=60)
    if resp.status_code == 404:
        raise RuntimeError(f"repository not found or no access: {owner}/{repo}")
    resp.raise_for_status()
    body: Any = resp.json()
    if not isinstance(body, dict):
        raise RuntimeError("unexpected GitHub API response")
    return body


def get_collaborator_permission(
    owner: str,
    repo: str,
    username: str,
    *,
    access: AccessConfig | None = None,
) -> str | None:
    """
    Return GitHub permission role for username on repo, or None if not a collaborator.
    Role is typically: admin, maintain, write, read, triage, or none.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/collaborators/{username}/permission"
    session = _session(access)
    resp = session.get(url, timeout=60)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    body: Any = resp.json()
    perm = body.get("permission")
    if isinstance(perm, str):
        return perm
    return None


def fetch_authenticated_user_login(bearer: str) -> str:
    """Login for the token used in Authorization (must be access.agent.github_token)."""
    session = _session_with_bearer(bearer)
    resp = session.get(f"{GITHUB_API}/user", timeout=60)
    if resp.status_code != 200:
        _raise_github(resp, "GET /user (invitee PAT)")
    body: Any = resp.json()
    if not isinstance(body, dict):
        raise RuntimeError("unexpected GET /user response")
    login = body.get("login")
    if not isinstance(login, str) or not login.strip():
        raise RuntimeError("GET /user: missing login")
    return login.strip()


def accept_repository_invitations_for_repositories(
    repo_full_names: set[str],
    *,
    bearer: str,
) -> int:
    """
    Accept pending repository invitations for the authenticated (invitee) user
    whose repository full_name (owner/repo) is in repo_full_names. Matching is
    case-insensitive. Returns the number of invitations accepted.
    """
    want = {n.strip().lower() for n in repo_full_names if n.strip()}
    if not want:
        return 0
    session = _session_with_bearer(bearer)
    accepted = 0
    page = 1
    while True:
        resp = session.get(
            f"{GITHUB_API}/user/repository_invitations",
            params={"per_page": 100, "page": page},
            timeout=60,
        )
        if resp.status_code != 200:
            _raise_github(resp, "list user repository invitations")
        raw: Any = resp.json()
        if not isinstance(raw, list):
            raise RuntimeError("unexpected invitations list response")
        if not raw:
            break
        for inv in raw:
            if not isinstance(inv, dict):
                continue
            repo = inv.get("repository")
            fn: str | None = None
            if isinstance(repo, dict):
                full = repo.get("full_name")
                if isinstance(full, str):
                    fn = full
            if fn is None or fn.lower() not in want:
                continue
            iid = inv.get("id")
            if not isinstance(iid, int):
                continue
            acc = session.patch(
                f"{GITHUB_API}/user/repository_invitations/{iid}",
                timeout=60,
            )
            if acc.status_code not in (200, 204):
                _raise_github(acc, "accept repository invitation")
            accepted += 1
        if len(raw) < 100:
            break
        page += 1
    return accepted
