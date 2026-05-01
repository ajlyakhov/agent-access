from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from paramiko import RSAKey


def write_rsa_keypair(tmp_path: Path) -> tuple[Path, Path]:
    master = RSAKey.generate(2048)
    agent = RSAKey.generate(2048)
    priv = tmp_path / "id_master"
    pub = tmp_path / "agent.pub"
    master.write_private_key_file(str(priv))
    pub.write_text(f"{agent.get_name()} {agent.get_base64()} agent\n")
    return priv, pub


@pytest.fixture
def keypair(tmp_path: Path) -> tuple[Path, Path]:
    return write_rsa_keypair(tmp_path)


def minimal_project_yaml(
    master: Path,
    pub: Path,
    *,
    servers: list[Any] | None = None,
    github: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "t": {
            "access": {
                "master_key_path": str(master.resolve()),
                "agent_pubkey_path": str(pub.resolve()),
                "agent_github_name": "someuser",
                "github_permission": "push",
            },
            "resources": {
                "servers": [] if servers is None else servers,
                "github": [] if github is None else github,
            },
        }
    }


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
