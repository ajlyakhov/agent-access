from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_access.config import (
    AccessConfig,
    AgentAccessConfig,
    MasterAccessConfig,
    load_project_config,
    read_agent_pubkeys,
    resolve_agent_github_token,
    resolve_master_github_token,
)


def _nested_access(master: Path, pub: Path) -> dict[str, object]:
    return {
        "master": {"private_key_path": str(master)},
        "agent": {"github_name": "u", "pubkey_path": str(pub)},
    }


def test_load_structured_resources(keypair: tuple[Path, Path], tmp_path: Path) -> None:
    master, pub = keypair
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "proj": {
                    "access": {
                        "master": {
                            "private_key_path": str(master),
                        },
                        "agent": {
                            "github_name": "bot",
                            "pubkey_path": str(pub),
                        },
                    },
                    "resources": {
                        "servers": [
                            {
                                "name": "Web",
                                "description": "web tier",
                                "ssh": "ubuntu@10.0.0.1",
                            },
                        ],
                        "github": [
                            {
                                "name": "API",
                                "description": "api",
                                "repo": "acme/api",
                            },
                        ],
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    p = load_project_config(cfg, "proj")
    assert p.servers[0].name == "Web"
    assert p.servers[0].ssh == "ubuntu@10.0.0.1"
    assert p.github_repos[0].repo == "acme/api"


def test_access_master_github_token(keypair: tuple[Path, Path], tmp_path: Path) -> None:
    master, pub = keypair
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "proj": {
                    "access": {
                        "master": {
                            "private_key_path": str(master),
                            "github_token": " ghp_from_yaml ",
                        },
                        "agent": {
                            "github_name": "bot",
                            "pubkey_path": str(pub),
                        },
                    },
                    "resources": {"servers": [], "github": []},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    p = load_project_config(cfg, "proj")
    assert p.access.master.github_token == "ghp_from_yaml"


def test_access_agent_github_token_nested(
    keypair: tuple[Path, Path], tmp_path: Path
) -> None:
    master, pub = keypair
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "proj": {
                    "access": {
                        "master": {"private_key_path": str(master)},
                        "agent": {
                            "github_name": "bot",
                            "pubkey_path": str(pub),
                            "github_token": " ghp_agent_pat ",
                        },
                    },
                    "resources": {"servers": [], "github": []},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    p = load_project_config(cfg, "proj")
    assert p.access.agent.github_token == "ghp_agent_pat"


def test_flat_access_rejected(keypair: tuple[Path, Path], tmp_path: Path) -> None:
    master, pub = keypair
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "proj": {
                    "access": {
                        "master_key_path": str(master),
                        "agent_pubkey_path": str(pub),
                        "agent_github_name": "bot",
                    },
                    "resources": {"servers": [], "github": []},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="access.master must be a mapping"):
        load_project_config(cfg, "proj")


def test_resolve_agent_github_token_env_over_config(
    keypair: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master, pub = keypair
    monkeypatch.setenv("AGENT_GITHUB_TOKEN", "pat_env")
    acc = AccessConfig(
        master=MasterAccessConfig(private_key_path=master, github_token=None),
        agent=AgentAccessConfig(
            github_name="u",
            pubkey_path=pub,
            github_token="pat_yaml",
        ),
    )
    assert resolve_agent_github_token(acc) == "pat_env"


def test_resolve_master_github_token_env_over_config(
    keypair: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master, pub = keypair
    monkeypatch.delenv("AGENT_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "from_env")
    acc = AccessConfig(
        master=MasterAccessConfig(
            private_key_path=master,
            github_token="from_yaml",
        ),
        agent=AgentAccessConfig(github_name="u", pubkey_path=pub),
    )
    assert resolve_master_github_token(acc) == "from_env"


def test_resolve_master_github_token_config_when_env_empty(
    keypair: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master, pub = keypair
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_GITHUB_TOKEN", raising=False)
    acc = AccessConfig(
        master=MasterAccessConfig(
            private_key_path=master,
            github_token="from_yaml",
        ),
        agent=AgentAccessConfig(github_name="u", pubkey_path=pub),
    )
    assert resolve_master_github_token(acc) == "from_yaml"


def test_load_legacy_string_entries(keypair: tuple[Path, Path], tmp_path: Path) -> None:
    master, pub = keypair
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "p": {
                    "access": _nested_access(master, pub),
                    "resources": {
                        "servers": ["ec2-user@192.168.1.1:2222"],
                        "github": ["org/repo-one"],
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    p = load_project_config(cfg, "p")
    assert p.servers[0].ssh == "ec2-user@192.168.1.1:2222"
    assert p.servers[0].name == p.servers[0].ssh
    assert p.github_repos[0].repo == "org/repo-one"


def test_unknown_project(keypair: tuple[Path, Path], tmp_path: Path) -> None:
    master, pub = keypair
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "only": {
                    "access": _nested_access(master, pub),
                    "resources": {"servers": [], "github": []},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(KeyError, match="Unknown project"):
        load_project_config(cfg, "missing")


def test_invalid_github_repo_slug(keypair: tuple[Path, Path], tmp_path: Path) -> None:
    master, pub = keypair
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "p": {
                    "access": _nested_access(master, pub),
                    "resources": {"servers": [], "github": ["not-a-slash"]},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="owner/name"):
        load_project_config(cfg, "p")


def test_read_agent_pubkeys_empty(tmp_path: Path) -> None:
    pub = tmp_path / "empty.pub"
    pub.write_text("# only comments\n", encoding="utf-8")
    with pytest.raises(ValueError, match="No public keys"):
        read_agent_pubkeys(pub)
