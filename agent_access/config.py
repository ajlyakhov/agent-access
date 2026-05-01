from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")

VALID_GITHUB_PERMISSIONS = frozenset({"pull", "push", "maintain", "admin"})


@dataclass(frozen=True)
class AccessConfig:
    master_key_path: Path
    agent_pubkey_path: Path
    agent_github_name: str
    github_permission: str = "push"


@dataclass(frozen=True)
class ServerResource:
    """SSH target with human-readable metadata for agent context."""

    name: str
    description: str
    ssh: str  # user@host[:port]


@dataclass(frozen=True)
class GithubResource:
    """GitHub repo with human-readable metadata for agent context."""

    name: str
    description: str
    repo: str  # owner/name


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    access: AccessConfig
    servers: tuple[ServerResource, ...]
    github_repos: tuple[GithubResource, ...]


def _expand(path_str: str) -> Path:
    return Path(os.path.expanduser(path_str.strip())).resolve()


def _parse_user_host(entry: str) -> tuple[str, str, int]:
    """Parse user@host or user@host:port."""
    entry = entry.strip()
    if "@" not in entry:
        raise ValueError(f"Invalid server (expected user@host): {entry!r}")
    user, rest = entry.split("@", 1)
    user = user.strip()
    rest = rest.strip()
    if not user or not rest:
        raise ValueError(f"Invalid server: {entry!r}")
    port = 22
    if ":" in rest:
        host_part, port_s = rest.rsplit(":", 1)
        try:
            port = int(port_s)
        except ValueError as e:
            raise ValueError(f"Invalid port in {entry!r}") from e
        host = host_part.strip()
    else:
        host = rest
    if not host:
        raise ValueError(f"Invalid server: {entry!r}")
    return user, host, port


def load_project_config(config_path: Path, project: str) -> ProjectConfig:
    if not config_path.is_file():
        raise FileNotFoundError(f"Config not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a mapping (project names to definitions)")

    if project not in raw:
        known = ", ".join(sorted(raw.keys()))
        raise KeyError(f"Unknown project {project!r}. Known: {known or '(none)'}")

    block = raw[project]
    if not isinstance(block, dict):
        raise ValueError(f"Project {project!r}: expected a mapping")

    access_raw = block.get("access")
    if not isinstance(access_raw, dict):
        raise ValueError(f"Project {project!r}: missing or invalid 'access'")

    try:
        master_key_path = _expand(str(access_raw["master_key_path"]))
        agent_pubkey_path = _expand(str(access_raw["agent_pubkey_path"]))
        agent_github_name = str(access_raw["agent_github_name"]).strip()
    except KeyError as e:
        raise ValueError(f"Project {project!r}: access.{e.args[0]!r} is required") from e

    if not agent_github_name:
        raise ValueError(f"Project {project!r}: agent_github_name must be non-empty")

    perm_raw = access_raw.get("github_permission", "push")
    github_permission = str(perm_raw).strip().lower()
    if github_permission not in VALID_GITHUB_PERMISSIONS:
        raise ValueError(
            f"Project {project!r}: github_permission must be one of "
            f"{sorted(VALID_GITHUB_PERMISSIONS)}, got {github_permission!r}"
        )

    resources = block.get("resources") or {}
    if not isinstance(resources, dict):
        raise ValueError(f"Project {project!r}: 'resources' must be a mapping")

    servers_raw = resources.get("servers") or []
    if not isinstance(servers_raw, list):
        raise ValueError(f"Project {project!r}: resources.servers must be a list")
    servers: list[ServerResource] = []
    for i, s in enumerate(servers_raw):
        prefix = f"Project {project!r}: resources.servers[{i}]"
        if isinstance(s, str):
            ssh = s.strip()
            if not ssh:
                raise ValueError(f"{prefix}: invalid empty server string")
            _parse_user_host(ssh)
            servers.append(
                ServerResource(name=ssh, description="", ssh=ssh),
            )
            continue
        if not isinstance(s, dict):
            raise ValueError(f"{prefix}: must be a string (ssh) or a mapping with name, description, ssh")
        try:
            name = str(s["name"]).strip()
            description = str(s.get("description", "") or "")
            ssh = str(s["ssh"]).strip()
        except KeyError as e:
            raise ValueError(f"{prefix}: missing required key {e.args[0]!r}") from e
        if not name:
            raise ValueError(f"{prefix}: name must be non-empty")
        if not ssh:
            raise ValueError(f"{prefix}: ssh must be non-empty")
        _parse_user_host(ssh)
        servers.append(
            ServerResource(name=name, description=description, ssh=ssh),
        )

    gh_raw = resources.get("github") or []
    if not isinstance(gh_raw, list):
        raise ValueError(f"Project {project!r}: resources.github must be a list")
    repos: list[GithubResource] = []
    for i, r in enumerate(gh_raw):
        prefix = f"Project {project!r}: resources.github[{i}]"
        if isinstance(r, str):
            repo = r.strip()
            if not REPO_PATTERN.match(repo):
                raise ValueError(
                    f"{prefix}: repo must be owner/name, got {repo!r}",
                )
            repos.append(
                GithubResource(name=repo, description="", repo=repo),
            )
            continue
        if not isinstance(r, dict):
            raise ValueError(
                f"{prefix}: must be a string (owner/repo) or a mapping with name, description, repo",
            )
        try:
            name = str(r["name"]).strip()
            description = str(r.get("description", "") or "")
            repo = str(r["repo"]).strip()
        except KeyError as e:
            raise ValueError(f"{prefix}: missing required key {e.args[0]!r}") from e
        if not name:
            raise ValueError(f"{prefix}: name must be non-empty")
        if not REPO_PATTERN.match(repo):
            raise ValueError(
                f"{prefix}: repo must be owner/name, got {repo!r}",
            )
        repos.append(
            GithubResource(name=name, description=description, repo=repo),
        )

    access = AccessConfig(
        master_key_path=master_key_path,
        agent_pubkey_path=agent_pubkey_path,
        agent_github_name=agent_github_name,
        github_permission=github_permission,
    )

    return ProjectConfig(
        name=project,
        access=access,
        servers=tuple(servers),
        github_repos=tuple(repos),
    )


def read_agent_pubkeys(agent_pubkey_path: Path) -> tuple[str, ...]:
    if not agent_pubkey_path.is_file():
        raise FileNotFoundError(f"Agent public key file not found: {agent_pubkey_path}")
    lines: list[str] = []
    for line in agent_pubkey_path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    if not lines:
        raise ValueError(f"No public keys found in {agent_pubkey_path}")
    return tuple(lines)
