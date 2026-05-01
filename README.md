# agent-access

CLI to **grant or revoke** agent access to servers (via `authorized_keys`) and GitHub repos (via collaborator API), driven by a per-project YAML config. It can **verify** keys and connectivity before changes, print an **agent context** block after a successful `enable`, and show **status** of current access.

**Repository:** [github.com/ajlyakhov/agent-access](https://github.com/ajlyakhov/agent-access)

## Requirements

- Python **3.10+**
- A **master** SSH private key that can sign in as each configured Linux user and manage `~/.ssh/authorized_keys`
- A **public** key file for the agent (one or more lines) to install on servers
- **`GITHUB_TOKEN`** (for projects with `resources.github`) with **admin** on those repositories if you need to add/remove collaborators

Host key policy uses Paramiko’s `AutoAddPolicy` (equivalent to blindly accepting new hosts). For production use, prime `known_hosts` or adjust the code if you need stricter SSH host verification.

## Install

### Install from Git (no clone)

```bash
pip install "git+https://github.com/ajlyakhov/agent-access.git"
```

### From PyPI (after publish)

```bash
pip install agent-access
```

### From a local folder (this repo on disk)

`pip` treats a directory as a source tree if it contains `pyproject.toml`. Use the project root (the folder that has `pyproject.toml`).

**Normal install** (copies the package into your environment):

```bash
cd /path/to/agent-control
pip install .
```

You can also pass the path without `cd`:

```bash
pip install /path/to/agent-control
```

**Editable install** (code changes apply immediately; best while hacking on the tool):

```bash
cd /path/to/agent-control
pip install -e .
```

**With dev dependencies** (e.g. `pytest`, `build`):

```bash
pip install -e ".[dev]"
```

After any of these, the **`agent-access`** command should be on your `PATH` for that Python environment. You can also run **`python -m agent_access`** from any directory.

### From a built wheel or sdist

After `python -m build`, install the file under `dist/`:

```bash
pip install dist/agent_access-0.1.0-py3-none-any.whl
# or
pip install dist/agent_access-0.1.0.tar.gz
```

## Config

Copy [`config.example.yml`](config.example.yml) into **`~/.agent-access/config.yml`** (create the directory if needed) and edit. The **top-level key** is the **project** name you pass on the CLI.

Each **server** has `name`, `description`, and `ssh` (`user@host` or `user@host:port`). Each **GitHub** entry has `name`, `description`, and `repo` (`owner/name`). You can still use legacy plain strings for servers (SSH target only) and repos (`owner/repo`).

Paths under `access` support `~`.

Global CLI option **`--config PATH`** defaults to **`~/.agent-access/config.yml`**. It must appear **before** the subcommand:

```bash
agent-access --config /path/to/config.yml verify myproject
```

## Environment

| Variable | Purpose |
|----------|---------|
| `GITHUB_TOKEN` | Required for `enable` / `disable` when repos are listed; required for `verify` / `status` GitHub checks when repos are listed |

Use a classic PAT with `repo` scope (or another token that yields **`permissions.admin: true`** on `GET /repos/{owner}/{repo}` for those repositories).

## Commands

### `verify`

Validates master and agent key files, SSH to each server (if any), and GitHub token/user/repo admin (if any repos listed). Prints a report to **stdout**; exit code **0** if all checks pass, **1** otherwise.

```bash
# Uses ~/.agent-access/config.yml when --config is omitted
agent-access verify myproject
agent-access --config /path/to/other.yml verify myproject
```

### `show`

Prints the **entire** resolved config file to **stdout** (raw bytes as UTF-8 text). Uses the same **`--config`** default as other commands.

```bash
agent-access show
agent-access --config /path/to/other.yml show
```

### `enable`

Runs the same checks as `verify` (report on **stderr**), then prompts:

`Proceed with enable for project '…'? [y/N]:`

Use **`-y` / `--yes`** on the **`enable`** or **`disable`** subcommand (after the verb) to skip the confirmation prompt (required in non-interactive environments). Then installs agent public keys and adds the GitHub user as a collaborator. On full success, prints the **`AGENT_ACCESS_CONTEXT`** block on **stdout** for pasting into the agent.

```bash
agent-access enable myproject
agent-access enable -y myproject
```

### `disable`

Same verification and confirmation flow as `enable`, then removes keys and removes the collaborator.

```bash
agent-access disable myproject -y
```

### `status`

Shows whether agent keys appear in each host’s `authorized_keys` and collaborator permission on each repo (GitHub skipped if `GITHUB_TOKEN` unset).

```bash
agent-access status myproject
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error or verification / operation failure |
| 2 | User cancelled `enable` / `disable` at the confirmation prompt |
| 130 | Interrupted (e.g. Ctrl+C) |

## Development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

## Build & publish (maintainers)

### Version tag (automated)

Pushes to **`main`** that touch **`pyproject.toml`** or **`agent_access/__init__.py`** run [.github/workflows/tag-on-version-bump.yml](.github/workflows/tag-on-version-bump.yml), which executes [.github/scripts/tag_if_version_bumped.py](.github/scripts/tag_if_version_bumped.py):

- **`[project].version`** must match **`agent_access/__init__.py`** `__version__` (otherwise the job fails).
- If that version **differs** from **`HEAD~1`**’s `pyproject.toml` and **`v{version}`** is not already on **`origin`**, the workflow creates an **annotated tag** and **`git push`**es it.

### PyPI upload (automated)

On **published GitHub Releases**, [.github/workflows/publish-pypi.yml](.github/workflows/publish-pypi.yml) builds with `python -m build` and uploads to PyPI via **trusted publishing (OIDC)** — no long-lived `PYPI_API_TOKEN` in repo secrets.

1. In [PyPI → your project → Settings → Publishing](https://docs.pypi.org/trusted-publishers/), add a pending **GitHub** publisher: owner **`ajlyakhov`**, repository **`agent-access`**, workflow **`publish-pypi.yml`** (environment name empty unless you add a GitHub Environment and match it on PyPI).
2. Bump **`version`** in **both** `pyproject.toml` and `agent_access/__init__.py` (`__version__`) in one commit, push to **`main`** — wait for the **Tag on version bump** workflow to push **`v{x.y.z}`** (or create the tag manually if it already exists).
3. In GitHub **Releases**, create a **release** from that tag and publish it to run the PyPI workflow.

Details: [PyPI trusted publishers](https://docs.pypi.org/trusted-publishers/), [pypa/gh-action-pypi-publish](https://github.com/pypa/gh-action-pypi-publish).

### Manual PyPI

```bash
pip install build twine
python -m build
twine check dist/*
twine upload dist/*
```

## License

MIT — see [LICENSE](LICENSE).
