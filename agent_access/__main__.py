from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from agent_access import __version__
from agent_access.config import (
    GithubResource,
    ServerResource,
    load_project_config,
    read_agent_pubkeys,
    resolve_agent_github_token,
    resolve_master_github_token,
)
from agent_access.github_collab import (
    accept_repository_invitations_for_repositories,
    add_collaborator,
    get_collaborator_permission,
    pending_repository_invitation_for_user,
    remove_collaborator,
    split_owner_repo,
)
from agent_access.ssh_keys import (
    ensure_authorized_keys,
    pubkey_presence_on_server,
    remove_pubkeys_from_authorized_keys,
)
from agent_access.verify import (
    format_verification_report,
    run_verification,
    verification_succeeded,
)


def _default_config_path() -> Path:
    return Path.home() / ".agent-access" / "config.yml"


def _server_log_label(srv: ServerResource) -> str:
    if srv.name == srv.ssh:
        return srv.ssh
    return f"{srv.name} ({srv.ssh})"


def _github_log_label(gr: GithubResource) -> str:
    if gr.name == gr.repo:
        return gr.repo
    return f"{gr.name} ({gr.repo})"


def _one_line(s: str) -> str:
    return " ".join(s.split())


def _print_agent_context(
    *,
    project: str,
    servers: tuple[ServerResource, ...],
    github_repos: tuple[GithubResource, ...],
    agent_github_name: str,
    private_key_path: Path,
    pubkey_path: Path,
    github_permission: str,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "--- AGENT_ACCESS_CONTEXT_BEGIN",
        f"project: {project}",
        f"enabled_at_utc: {now}",
        f"github_user: {agent_github_name}",
        f"github_collaborator_permission: {github_permission}",
        "",
        "ssh:",
        "  Use the agent private key that matches access.agent.pubkey_path below; paths only, no key material.",
    ]
    for srv in servers:
        lines.append(f"  - name: {srv.name}")
        lines.append(f"    description: {_one_line(srv.description)}")
        lines.append(f"    connection: {srv.ssh}")
    lines.extend(
        [
            "",
            "github_repositories:",
        ]
    )
    for gr in github_repos:
        lines.append(f"  - name: {gr.name}")
        lines.append(f"    description: {_one_line(gr.description)}")
        lines.append(f"    repo: {gr.repo}")
    lines.extend(
        [
            "",
            "local_paths_operator_machine_only:",
            f"  private_key_path: {private_key_path}",
            f"  pubkey_path: {pubkey_path}",
            "",
            "Save this block in the agent context window so the agent knows scope of access.",
            "--- AGENT_ACCESS_CONTEXT_END",
        ]
    )
    print("\n".join(lines))


def _confirm(action: str, project: str) -> bool:
    if sys.stdin.isatty():
        r = input(f"Proceed with {action} for project {project!r}? [y/N]: ").strip().lower()
        return r in ("y", "yes")
    print(
        "Not a TTY; use --yes / -y to confirm without prompting.",
        file=sys.stderr,
    )
    return False


def cmd_verify(config_path: Path, project: str) -> int:
    cfg = load_project_config(config_path, project)
    checks, _pubkeys = run_verification(cfg)
    print(format_verification_report(cfg.name, checks))
    return 0 if verification_succeeded(checks) else 1


def cmd_enable(
    config_path: Path,
    project: str,
    *,
    auto_confirm: bool,
) -> int:
    cfg = load_project_config(config_path, project)
    checks, pubkeys = run_verification(cfg)
    print(format_verification_report(cfg.name, checks), file=sys.stderr)
    if not verification_succeeded(checks):
        print("Enable aborted: fix verification failures first.", file=sys.stderr)
        return 1
    if pubkeys is None:
        print("Enable aborted: no agent public keys loaded.", file=sys.stderr)
        return 1
    if not auto_confirm and not _confirm("enable", project):
        print("Enable aborted.", file=sys.stderr)
        return 2

    errors: list[str] = []

    for srv in cfg.servers:
        label = _server_log_label(srv)
        try:
            ensure_authorized_keys(srv.ssh, cfg.access.master.private_key_path, pubkeys)
            print(f"SSH OK: {label}", file=sys.stderr)
        except Exception as e:
            errors.append(f"SSH {label}: {e}")
            print(f"SSH FAIL: {label}: {e}", file=sys.stderr)

    for gr in cfg.github_repos:
        owner, name = split_owner_repo(gr.repo)
        label = _github_log_label(gr)
        try:
            outcome = add_collaborator(
                owner,
                name,
                cfg.access.agent.github_name,
                cfg.access.agent.github_permission,
                access=cfg.access,
            )
            agent_pat = resolve_agent_github_token(cfg.access)
            if outcome == "invited" and agent_pat:
                accepted = accept_repository_invitations_for_repositories(
                    {gr.repo},
                    bearer=agent_pat,
                )
                if accepted:
                    print(
                        f"GitHub OK: {label} (invitation auto-accepted)",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"GitHub INVITE: {label} — invitation not found yet for "
                        f"{cfg.access.agent.github_name}; accept at "
                        "https://github.com/notifications or retry enable",
                        file=sys.stderr,
                    )
            elif outcome == "invited":
                print(
                    f"GitHub INVITE: {label} — {cfg.access.agent.github_name} must "
                    "accept the repository invitation (https://github.com/notifications "
                    "or email) before git/push access works; or set "
                    "AGENT_GITHUB_TOKEN / access.agent.github_token",
                    file=sys.stderr,
                )
            else:
                print(f"GitHub OK: {label}", file=sys.stderr)
        except Exception as e:
            errors.append(f"GitHub {label}: {e}")
            print(f"GitHub FAIL: {label}: {e}", file=sys.stderr)

    if errors:
        print("\nSome steps failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    _print_agent_context(
        project=cfg.name,
        servers=cfg.servers,
        github_repos=cfg.github_repos,
        agent_github_name=cfg.access.agent.github_name,
        private_key_path=cfg.access.master.private_key_path,
        pubkey_path=cfg.access.agent.pubkey_path,
        github_permission=cfg.access.agent.github_permission,
    )
    return 0


def cmd_disable(
    config_path: Path,
    project: str,
    *,
    auto_confirm: bool,
) -> int:
    cfg = load_project_config(config_path, project)
    checks, pubkeys = run_verification(cfg)
    print(format_verification_report(cfg.name, checks), file=sys.stderr)
    if not verification_succeeded(checks):
        print("Disable aborted: fix verification failures first.", file=sys.stderr)
        return 1
    if pubkeys is None:
        print("Disable aborted: no agent public keys loaded.", file=sys.stderr)
        return 1
    if not auto_confirm and not _confirm("disable", project):
        print("Disable aborted.", file=sys.stderr)
        return 2

    errors: list[str] = []

    for srv in cfg.servers:
        label = _server_log_label(srv)
        try:
            remove_pubkeys_from_authorized_keys(
                srv.ssh, cfg.access.master.private_key_path, pubkeys
            )
            print(f"SSH OK: {label}", file=sys.stderr)
        except Exception as e:
            errors.append(f"SSH {label}: {e}")
            print(f"SSH FAIL: {label}: {e}", file=sys.stderr)

    for gr in cfg.github_repos:
        owner, name = split_owner_repo(gr.repo)
        label = _github_log_label(gr)
        try:
            remove_collaborator(owner, name, cfg.access.agent.github_name, access=cfg.access)
            print(f"GitHub OK: {label}", file=sys.stderr)
        except Exception as e:
            errors.append(f"GitHub {label}: {e}")
            print(f"GitHub FAIL: {label}: {e}", file=sys.stderr)

    if errors:
        print("\nSome steps failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("Disable completed successfully.", file=sys.stderr)
    return 0


def cmd_status(config_path: Path, project: str) -> int:
    cfg = load_project_config(config_path, project)
    pubkeys = read_agent_pubkeys(cfg.access.agent.pubkey_path)
    errors: list[str] = []
    github_ok = bool(resolve_master_github_token(cfg.access))

    lines_out: list[str] = [
        f"project: {cfg.name}",
        f"github_user: {cfg.access.agent.github_name}",
        f"config_github_permission: {cfg.access.agent.github_permission}",
        "",
        "SSH (agent public keys on remote authorized_keys):",
    ]

    for srv in cfg.servers:
        label = _server_log_label(srv)
        try:
            present = pubkey_presence_on_server(
                srv.ssh, cfg.access.master.private_key_path, pubkeys
            )
            n = sum(1 for p in present if p)
            total = len(present)
            if total == 0:
                state = "no keys configured"
            elif n == total:
                state = f"enabled ({n}/{total} keys)"
            elif n == 0:
                state = f"disabled ({n}/{total} keys)"
            else:
                state = f"partial ({n}/{total} keys)"
            lines_out.append(
                f"  {label}: {state}"
                + (f" — {srv.description}" if srv.description else "")
            )
        except Exception as e:
            errors.append(f"SSH {label}: {e}")
            lines_out.append(f"  {label}: error — {e}")

    lines_out.append("")
    lines_out.append("GitHub:")
    if not github_ok:
        lines_out.append(
            "  (skipped — set GITHUB_TOKEN or access.master.github_token to check collaborator permission)"
        )
    for gr in cfg.github_repos:
        label = _github_log_label(gr)
        if not github_ok:
            lines_out.append(f"  {label}: unknown")
            continue
        owner, name = split_owner_repo(gr.repo)
        try:
            perm = get_collaborator_permission(
                owner, name, cfg.access.agent.github_name, access=cfg.access,
            )
            if perm is None:
                if pending_repository_invitation_for_user(
                    owner,
                    name,
                    cfg.access.agent.github_name,
                    access=cfg.access,
                ):
                    lines_out.append(
                        f"  {label}: invitation pending (accept at "
                        f"github.com/notifications)"
                        + (f" — {gr.description}" if gr.description else "")
                    )
                    continue
                lines_out.append(
                    f"  {label}: not a collaborator"
                    + (f" — {gr.description}" if gr.description else "")
                )
                continue
            lines_out.append(
                f"  {label}: collaborator ({perm})"
                + (f" — {gr.description}" if gr.description else "")
            )
        except Exception as e:
            errors.append(f"GitHub {label}: {e}")
            lines_out.append(f"  {label}: error — {e}")

    print("\n".join(lines_out))

    if errors:
        print("", file=sys.stderr)
        print("Status checks had failures:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    return 0


def cmd_show(config_path: Path) -> int:
    if not config_path.is_file():
        raise FileNotFoundError(f"Config not found: {config_path}")
    text = config_path.read_text(encoding="utf-8")
    sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-access",
        description="Enable, disable, inspect, or print agent SSH + GitHub collaborator config.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_config_path(),
        help="Path to config.yml (default: ~/.agent-access/config.yml)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_en = sub.add_parser("enable", help="Grant access (SSH keys + GitHub collaborator)")
    p_en.add_argument("project", help="Top-level project key in config.yml")
    p_en.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip interactive confirmation after verification",
    )

    p_dis = sub.add_parser("disable", help="Revoke access")
    p_dis.add_argument("project", help="Top-level project key in config.yml")
    p_dis.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip interactive confirmation after verification",
    )

    p_vf = sub.add_parser(
        "verify",
        help="Validate keys/config and connectivity to all configured resources",
    )
    p_vf.add_argument("project", help="Top-level project key in config.yml")

    p_st = sub.add_parser(
        "status",
        help="Show whether agent SSH keys and GitHub collaborator access are present",
    )
    p_st.add_argument("project", help="Top-level project key in config.yml")

    p_sh = sub.add_parser(
        "show",
        help="Print the raw config file to stdout",
    )

    args = parser.parse_args(argv)

    try:
        if args.command == "enable":
            return cmd_enable(
                args.config, args.project, auto_confirm=args.yes,
            )
        if args.command == "disable":
            return cmd_disable(
                args.config, args.project, auto_confirm=args.yes,
            )
        if args.command == "verify":
            return cmd_verify(args.config, args.project)
        if args.command == "status":
            return cmd_status(args.config, args.project)
        if args.command == "show":
            return cmd_show(args.config)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except (FileNotFoundError, KeyError, RuntimeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
