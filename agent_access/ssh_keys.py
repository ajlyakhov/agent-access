from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import paramiko
from paramiko import ECDSAKey, Ed25519Key, RSAKey

from agent_access.config import _parse_user_host


def _load_private_key(private_key_path: Path) -> paramiko.PKey:
    last_err: Exception | None = None
    for cls in (Ed25519Key, ECDSAKey, RSAKey):
        try:
            return cls.from_private_key_file(str(private_key_path))
        except (paramiko.SSHException, OSError) as e:
            last_err = e
            continue
    raise paramiko.SSHException(
        f"Could not load private key {private_key_path}: {last_err}"
    ) from last_err


def _pubkey_fingerprint(line: str) -> str | None:
    """SHA256 fingerprint of OpenSSH public key line (standard ssh-keygen format)."""
    parts = line.split()
    if len(parts) < 2:
        return None
    key_type, b64_blob = parts[0], parts[1]
    try:
        raw = base64.b64decode(b64_blob)
    except (ValueError, OSError):
        return None
    digest = hashlib.sha256(raw).digest()
    blob_b64 = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{blob_b64}"


def _line_matches_pubkey_line(authorized_line: str, pubkey_line: str) -> bool:
    if authorized_line.strip() == pubkey_line.strip():
        return True
    fp_auth = _pubkey_fingerprint(authorized_line)
    fp_pub = _pubkey_fingerprint(pubkey_line)
    if fp_auth and fp_pub and fp_auth == fp_pub:
        return True
    return False


def _connect(
    user: str,
    host: str,
    port: int,
    private_key_path: Path,
) -> paramiko.SSHClient:
    if not private_key_path.is_file():
        raise FileNotFoundError(f"Master SSH private key not found: {private_key_path}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    key = _load_private_key(private_key_path)
    client.connect(
        hostname=host,
        port=port,
        username=user,
        pkey=key,
        look_for_keys=False,
        allow_agent=False,
        timeout=30,
    )
    return client


def ensure_authorized_keys(
    server: str,
    private_key_path: Path,
    pubkey_lines: tuple[str, ...],
) -> None:
    user, host, port = _parse_user_host(server)
    client = _connect(user, host, port, private_key_path)
    try:
        sftp = client.open_sftp()
        try:
            ssh_dir = ".ssh"
            auth_path = f"{ssh_dir}/authorized_keys"
            try:
                sftp.stat(ssh_dir)
            except OSError:
                sftp.mkdir(ssh_dir, 0o700)
            try:
                with sftp.open(auth_path, "r") as rf:
                    content = rf.read().decode("utf-8", errors="replace")
            except OSError:
                content = ""
            existing_lines = [ln for ln in content.splitlines() if ln.strip()]
            to_append: list[str] = []
            for pub in pubkey_lines:
                if any(_line_matches_pubkey_line(ex, pub) for ex in existing_lines):
                    continue
                to_append.append(pub)
            if to_append:
                mode = "a" if existing_lines or content else "w"
                with sftp.open(auth_path, mode) as wf:
                    prefix = "" if not content or content.endswith("\n") else "\n"
                    wf.write((prefix + "\n".join(to_append) + "\n").encode("utf-8"))
                sftp.chmod(auth_path, 0o600)
        finally:
            sftp.close()
    finally:
        client.close()


def pubkey_presence_on_server(
    server: str,
    private_key_path: Path,
    pubkey_lines: tuple[str, ...],
) -> tuple[bool, ...]:
    """Return whether each configured public key line is present on the remote authorized_keys."""
    user, host, port = _parse_user_host(server)
    client = _connect(user, host, port, private_key_path)
    try:
        sftp = client.open_sftp()
        try:
            auth_path = ".ssh/authorized_keys"
            try:
                with sftp.open(auth_path, "r") as rf:
                    content = rf.read().decode("utf-8", errors="replace")
            except OSError:
                content = ""
            existing_lines = [ln for ln in content.splitlines() if ln.strip()]
            return tuple(
                any(_line_matches_pubkey_line(ex, pub) for ex in existing_lines)
                for pub in pubkey_lines
            )
        finally:
            sftp.close()
    finally:
        client.close()


def remove_pubkeys_from_authorized_keys(
    server: str,
    private_key_path: Path,
    pubkey_lines: tuple[str, ...],
) -> None:
    user, host, port = _parse_user_host(server)
    client = _connect(user, host, port, private_key_path)
    try:
        sftp = client.open_sftp()
        try:
            auth_path = ".ssh/authorized_keys"
            try:
                with sftp.open(auth_path, "r") as rf:
                    content = rf.read().decode("utf-8", errors="replace")
            except OSError:
                return
            kept = [
                ln
                for ln in content.splitlines()
                if ln.strip()
                and not any(_line_matches_pubkey_line(ln, pub) for pub in pubkey_lines)
            ]
            new_body = ("\n".join(kept) + ("\n" if kept else "")).encode("utf-8")
            with sftp.open(auth_path, "w") as wf:
                wf.write(new_body)
            sftp.chmod(auth_path, 0o600)
        finally:
            sftp.close()
    finally:
        client.close()
