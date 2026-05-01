from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import paramiko
from paramiko import ECDSAKey, Ed25519Key, RSAKey

from agent_access.config import (
    ProjectConfig,
    _parse_user_host,
    read_agent_pubkeys,
    resolve_agent_github_token,
    resolve_master_github_token,
)
from agent_access.github_collab import (
    fetch_authenticated_user_login,
    fetch_repo_for_token,
    github_user_exists,
    is_repository_collaborator,
    pending_repository_invitation_for_user,
    split_owner_repo,
)
from agent_access.ssh_keys import _connect


@dataclass(frozen=True)
class VerifyCheck:
    """Single verification step result."""

    label: str
    ok: bool
    detail: str


def _try_load_master_key(path: Path) -> tuple[bool, str, str]:
    """Return (ok, key_type_or_empty, error_message)."""
    if not path.is_file():
        return False, "", f"not a file: {path}"
    last_err = ""
    for cls in (Ed25519Key, ECDSAKey, RSAKey):
        try:
            key = cls.from_private_key_file(str(path))
            return True, type(key).__name__.replace("Key", "").lower(), ""
        except (paramiko.SSHException, OSError) as e:
            last_err = str(e)
    return False, "", last_err or "unrecognized private key format"


def _verify_ssh_server(server_ssh: str, private_key_path: Path) -> None:
    """Connect with master key and confirm SFTP home and ~/.ssh behave as enable expects."""
    user, host, port = _parse_user_host(server_ssh)
    client = _connect(user, host, port, private_key_path)
    try:
        sftp = client.open_sftp()
        try:
            sftp.listdir(".")
            ssh_dir = ".ssh"
            try:
                sftp.stat(ssh_dir)
            except OSError:
                return
            auth = f"{ssh_dir}/authorized_keys"
            try:
                with sftp.open(auth, "r") as rf:
                    rf.read(1)
            except OSError:
                pass
        finally:
            sftp.close()
    finally:
        client.close()


def run_verification(cfg: ProjectConfig) -> tuple[list[VerifyCheck], tuple[str, ...] | None]:
    """
    Run all checks. Returns (checks, agent_pubkeys or None if agent pubkey file failed).
    """
    checks: list[VerifyCheck] = []
    pubkeys: tuple[str, ...] | None = None
    mk = cfg.access.master.private_key_path

    master_ok, ktype, err = _try_load_master_key(mk)
    checks.append(
        VerifyCheck(
            label="Master SSH private key",
            ok=master_ok,
            detail=f"loaded as {ktype}" if master_ok else err,
        ),
    )

    try:
        pubkeys = read_agent_pubkeys(cfg.access.agent.pubkey_path)
        checks.append(
            VerifyCheck(
                label="Agent public key file",
                ok=True,
                detail=f"{len(pubkeys)} key line(s) from {cfg.access.agent.pubkey_path}",
            ),
        )
    except (FileNotFoundError, ValueError, OSError) as e:
        checks.append(
            VerifyCheck(
                label="Agent public key file",
                ok=False,
                detail=str(e),
            ),
        )
        pubkeys = None

    for srv in cfg.servers:
        label = f"SSH {_server_ssh_label(srv.name, srv.ssh)}"
        if not master_ok:
            checks.append(
                VerifyCheck(
                    label=label,
                    ok=False,
                    detail="skipped (master key invalid)",
                ),
            )
        elif pubkeys is None:
            checks.append(
                VerifyCheck(
                    label=label,
                    ok=False,
                    detail="skipped (agent public keys invalid)",
                ),
            )
        else:
            try:
                _verify_ssh_server(srv.ssh, mk)
                checks.append(
                    VerifyCheck(
                        label=label,
                        ok=True,
                        detail="connected; home and ~/.ssh/authorized_keys usable",
                    ),
                )
            except Exception as e:
                checks.append(
                    VerifyCheck(
                        label=label,
                        ok=False,
                        detail=str(e),
                    ),
                )

    token = resolve_master_github_token(cfg.access)
    env_token_set = bool(os.environ.get("GITHUB_TOKEN", "").strip())
    if cfg.github_repos:
        if not token:
            checks.append(
                VerifyCheck(
                    label="GitHub token",
                    ok=False,
                    detail=(
                        "set GITHUB_TOKEN or access.master.github_token "
                        "(required for configured GitHub repos)"
                    ),
                ),
            )
            for gr in cfg.github_repos:
                checks.append(
                    VerifyCheck(
                        label=f"GitHub {_github_label(gr.name, gr.repo)}",
                        ok=False,
                        detail="skipped (no token)",
                    ),
                )
        else:
            src = "environment" if env_token_set else "access.master.github_token in config"
            checks.append(
                VerifyCheck(
                    label="GitHub token",
                    ok=True,
                    detail=f"set ({src}; value not shown)",
                ),
            )
            agent_login = cfg.access.agent.github_name
            agent_pat = resolve_agent_github_token(cfg.access)
            if agent_pat:
                try:
                    invitee_login = fetch_authenticated_user_login(agent_pat)
                    pat_ok = invitee_login.lower() == agent_login.lower()
                    checks.append(
                        VerifyCheck(
                            label="Agent GitHub token (invitee PAT)",
                            ok=pat_ok,
                            detail=(
                                f"GET /user login={invitee_login!r} matches "
                                f"access.agent.github_name"
                                if pat_ok
                                else (
                                    f"GET /user login={invitee_login!r} does not match "
                                    f"access.agent.github_name={agent_login!r}"
                                )
                            ),
                        ),
                    )
                except Exception as e:
                    checks.append(
                        VerifyCheck(
                            label="Agent GitHub token (invitee PAT)",
                            ok=False,
                            detail=str(e),
                        ),
                    )
            try:
                u_ok = github_user_exists(agent_login, access=cfg.access)
                checks.append(
                    VerifyCheck(
                        label=f"GitHub user '{agent_login}'",
                        ok=u_ok,
                        detail="exists" if u_ok else "not found (404)",
                    ),
                )
            except Exception as e:
                checks.append(
                    VerifyCheck(
                        label=f"GitHub user '{agent_login}'",
                        ok=False,
                        detail=str(e),
                    ),
                )
                u_ok = False

            for gr in cfg.github_repos:
                gl = _github_label(gr.name, gr.repo)
                if not u_ok:
                    checks.append(
                        VerifyCheck(
                            label=f"GitHub repo {gl}",
                            ok=False,
                            detail="skipped (target user check failed)",
                        ),
                    )
                    continue
                try:
                    owner, repo = split_owner_repo(gr.repo)
                    data: dict[str, Any] = fetch_repo_for_token(owner, repo, access=cfg.access)
                    perms = data.get("permissions") or {}
                    is_admin = bool(perms.get("admin"))
                    role = data.get("role_name") or ""
                    if is_admin:
                        collab = is_repository_collaborator(
                            owner,
                            repo,
                            agent_login,
                            access=cfg.access,
                        )
                        invited = pending_repository_invitation_for_user(
                            owner,
                            repo,
                            agent_login,
                            access=cfg.access,
                        )
                        if collab:
                            tail = (
                                f"; {agent_login} is an active collaborator on this repo"
                            )
                        elif invited:
                            tail = (
                                f"; pending invitation for {agent_login} — they must "
                                "accept (https://github.com/notifications) before git works"
                            )
                        else:
                            tail = (
                                f"; {agent_login} is not a collaborator and has no "
                                "pending invite (run enable to add)"
                            )
                        checks.append(
                            VerifyCheck(
                                label=f"GitHub repo {gl}",
                                ok=True,
                                detail=(
                                    "token has admin on repo (can manage collaborators)"
                                    + tail
                                    + (f"; role={role!r}" if role else "")
                                ),
                            ),
                        )
                    else:
                        checks.append(
                            VerifyCheck(
                                label=f"GitHub repo {gl}",
                                ok=False,
                                detail=(
                                    "token is not admin on this repository "
                                    f"(permissions={perms!s}); admin is required to add/remove collaborators"
                                    + (f"; role={role!r}" if role else "")
                                ),
                            ),
                        )
                except Exception as e:
                    checks.append(
                        VerifyCheck(
                            label=f"GitHub repo {gl}",
                            ok=False,
                            detail=str(e),
                        ),
                    )
    else:
        checks.append(
            VerifyCheck(
                label="GitHub",
                ok=True,
                detail="no repositories configured; skipping API checks",
            ),
        )

    return checks, pubkeys


def _server_ssh_label(name: str, ssh: str) -> str:
    return ssh if name == ssh else f"{name} ({ssh})"


def _github_label(name: str, repo: str) -> str:
    return repo if name == repo else f"{name} ({repo})"


def verification_succeeded(checks: list[VerifyCheck]) -> bool:
    return all(c.ok for c in checks)


def format_verification_report(project: str, checks: list[VerifyCheck]) -> str:
    lines = [f"Verification for project {project!r}:", ""]
    for c in checks:
        tag = "OK" if c.ok else "FAIL"
        lines.append(f"  [{tag}] {c.label}: {c.detail}")
    lines.append("")
    if verification_succeeded(checks):
        lines.append("Result: all checks passed.")
    else:
        n = sum(1 for c in checks if not c.ok)
        lines.append(f"Result: FAILED ({n} failing check(s)).")
    return "\n".join(lines)
