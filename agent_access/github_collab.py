from __future__ import annotations

import os
from typing import Any

import requests

GITHUB_API = "https://api.github.com"


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN environment variable is not set")
    return token


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return s


def add_collaborator(owner: str, repo: str, username: str, permission: str) -> None:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/collaborators/{username}"
    session = _session()
    resp = session.put(url, json={"permission": permission}, timeout=60)
    if resp.status_code in (201, 204):
        return
    if resp.status_code == 422:
        # e.g. already a collaborator
        try:
            body: Any = resp.json()
            msg = body.get("message", resp.text)
        except Exception:
            msg = resp.text
        if "already" in str(msg).lower():
            return
    resp.raise_for_status()


def remove_collaborator(owner: str, repo: str, username: str) -> None:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/collaborators/{username}"
    session = _session()
    resp = session.delete(url, timeout=60)
    if resp.status_code in (204, 404):
        return
    resp.raise_for_status()


def split_owner_repo(full: str) -> tuple[str, str]:
    owner, repo = full.split("/", 1)
    return owner, repo


def github_user_exists(username: str) -> bool:
    """Return True if the login exists on GitHub."""
    session = _session()
    url = f"{GITHUB_API}/users/{username}"
    resp = session.get(url, timeout=60)
    if resp.status_code == 404:
        return False
    resp.raise_for_status()
    return True


def fetch_repo_for_token(owner: str, repo: str) -> dict[str, Any]:
    """GET repository as the authenticated token; body includes permissions for the token."""
    session = _session()
    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    resp = session.get(url, timeout=60)
    if resp.status_code == 404:
        raise RuntimeError(f"repository not found or no access: {owner}/{repo}")
    resp.raise_for_status()
    body: Any = resp.json()
    if not isinstance(body, dict):
        raise RuntimeError("unexpected GitHub API response")
    return body


def get_collaborator_permission(owner: str, repo: str, username: str) -> str | None:
    """
    Return GitHub permission role for username on repo, or None if not a collaborator.
    Role is typically: admin, maintain, write, read, triage, or none.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/collaborators/{username}/permission"
    session = _session()
    resp = session.get(url, timeout=60)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    body: Any = resp.json()
    perm = body.get("permission")
    if isinstance(perm, str):
        return perm
    return None
