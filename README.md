# Devbox Bootstrap

A small, interactive bootstrap for **Ubuntu** developer machines and Ubuntu on WSL. Run it as your regular user; individual package steps request `sudo` as needed.

## Recommended: install the interactive TUI

Install with one command (Git is required to fetch the repository):

```bash
curl -fsSL https://raw.githubusercontent.com/truong51972/devbox-bootstrap/main/install-devbox.sh | bash
```

The launcher detects the available runtime in this order:

1. **uv available:** create `.venv` via `uv venv` and install TUI dependencies with `uv pip install`. uv can also download a managed Python interpreter if the system does not have one.
2. **No uv:** use an existing `python3` with `venv` and the virtual environment's `pip`.
3. **Neither works:** stop with a clear error and installation advice. Devbox does not automatically invoke APT to install Python.

`uv` is the preferred, optional runtime manager. Dependencies are recorded once in `tui/requirements.txt` for **both** uv and pip, with no global Python packages installed. The isolated environment lives at `~/.local/share/devbox-bootstrap/.venv`; the command symlink is `~/.local/bin/devbox`.

If a prerequisite is missing, install `uv` (recommended) or `python3 python3-venv` manually.


```bash
devbox                  # Open the interactive terminal UI
devbox --update         # Fast-forward Devbox's source code from GitHub
devbox --doctor         # Read-only system health check
devbox --upgrade        # Update installed development tools (not Devbox code)
devbox --help
```

If `~/.local/bin` is not in your `PATH`, use `~/.local/bin/devbox` directly.
`devbox --update` verifies the expected GitHub origin and branch and refuses
to overwrite tracked local edits or diverged Git history. Restart the TUI
after updating source code.

The keyboard-first TUI starts at a **minimal grouped menu**. Install/Upgrade
opens a sectioned component list with a contextual details panel, then a
compact confirmation, execution progress, and result screen. The layout adapts
to wide and narrow terminals (with `i` for details in compact mode). Doctor,
Preflight, Update Devbox and Logs & History remain separate choices.
Mouse input is deliberately disabled. No new TUI dependencies are required.

| Key | Context | Action |
| --- | --- | --- |
| Up/Down or j/k, Enter | Main menu | Navigate / open |
| Space | Components / confirmation | Toggle selection |
| A / N | Components | Select filtered / clear all |
| / | Components, History | Search/filter the visible list |
| I | Components | Full details (useful in narrow terminals) |
| T | Main menu | Toggle minimal color / monochrome theme |
| D | Confirmation | Toggle dry-run |
| Esc | Idle screens | Back (or clear active filter) |
| L | Execution, Results | Expand live log / open saved log |
| O | Log viewer | Open external pager (if installed) |
| ? | Most screens | Show keyboard help |
| Q | Main menu | Quit |

The default theme uses ANSI terminal colors. For monochrome terminals, set
`DEVBOX_THEME=mono devbox`; `t` toggles themes for the current session.

Only one job can run at a time. While it runs, the TUI keeps the log and
progress visible and disables quitting/detaching. Sudo authentication is shown
in the terminal before privileged operations.

Optional confirmations are **OFF by default** and made on the confirmation
screen: changing the default login shell to Zsh, joining the Docker group
(root-equivalent permissions), and creating a new Ed25519 SSH key. The key
generated through the TUI has **no passphrase**; consider generating a
passphrase-protected key manually instead. Unknown unattended confirmation
requests are denied. The original interactive Bash CLI is unchanged.

Full output is saved under
`~/.local/state/devbox-bootstrap/logs/`, and a small separate event stream
feeds the per-component status display. The UI shows a bounded log preview.
A running task must finish before closing the interface; this version does
**not** detach jobs to continue after you exit.

You can still use the original command-line bootstrap, standalone Doctor and
update commands below.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/truong51972/devbox-bootstrap/main/setup-ubuntu.sh | bash
```

### Quick Doctor (no installation)

Check your current developer environment without cloning the repo manually:

```bash
curl -fsSL https://raw.githubusercontent.com/truong51972/devbox-bootstrap/main/setup-ubuntu.sh | bash -s -- --doctor
```

This downloads the bootstrap and uses a temporary checkout to run the read-only Doctor. It does **not** install packages, change shell configuration, or pull Docker images. It requires Git and network access; the command may exit nonzero when installed components have functional issues. As with any `curl | bash` command, only run code from a source you trust.

### Upgrade existing tools (explicit opt-in)

Update **only installed** Devbox components without upgrading the full Ubuntu system:

```bash
curl -fsSL https://raw.githubusercontent.com/truong51972/devbox-bootstrap/main/setup-ubuntu.sh | bash -s -- --upgrade
```

Preview or restrict the upgrade to particular tools:

```bash
bash setup-ubuntu.sh --upgrade --dry-run
bash setup-ubuntu.sh --upgrade --only fzf,ripgrep,bat-fd,direnv
curl -fsSL https://raw.githubusercontent.com/truong51972/devbox-bootstrap/main/setup-ubuntu.sh | bash -s -- --upgrade --only uv,fzf
```

- APT-managed tools are updated to the **newest version available in configured APT repositories**, using `apt-get install --only-upgrade` (never `apt upgrade` for the whole machine). `sudo` may ask for a password; Docker package updates may restart its service.
- Standalone `uv` uses `uv self update` with shell-profile modification disabled. Other uv distributions (pip, pipx, Cargo) must be updated using their original manager.
- Devbox-managed Powerlevel10k, Oh My Zsh and autosuggestions Git checkouts update only when their tracked files are clean and their remotes match the expected upstream. Existing personal shell configuration is preserved.
- Devbox-managed `kubectl` and `minikube` binaries under `/usr/local/bin` can upgrade to newer versions only after SHA-256 verification; externally managed versions are preserved. For Kubernetes clusters, pin Devbox-managed `kubectl` with `--kubectl-version vMAJOR.MINOR.PATCH` to respect client/server version compatibility; this pinning option is not supported for APT-managed kubectl.
- `--doctor` remains **read-only**; `--upgrade` must be explicitly requested. Missing tools are **skipped**, not installed. `--dry-run` previews checks without fetching package indexes, releases or changing files.

Alternatively, review the scripts locally before running them:

```bash
git clone https://github.com/truong51972/devbox-bootstrap.git
cd devbox-bootstrap
bash setup-ubuntu.sh
```

Requires Ubuntu, Bash, an interactive terminal, network access, and `sudo` privileges. The bootstrap installs Git if needed. **Do not use `sudo bash setup-ubuntu.sh`**; this would modify root's shell configuration. Running `curl | bash` executes code fetched from the network; review and pin to a trusted commit if appropriate.

## Components

- Base packages (interactive full setup only): compiler/build tools, Git, curl, wget, CA certificates, and GnuPG. No automatic full-system `apt upgrade`.
- Optional: Zsh + Oh My Zsh, syntax highlighting, autosuggestions, Powerlevel10k; uv; SSH keychain; zoxide; **fzf, ripgrep, bat + fd, direnv**; Docker Engine; NVIDIA Container Toolkit; kubectl; and Minikube.
- Optional at the end: apt cleanup and reboot.

Each optional component is prompted separately and defaults to **No**. Powerlevel10k is offered only when Zsh is available; NVIDIA Toolkit only when Docker is available. Minikube is a separate optional installer. Configuration is written to the selected shell (`~/.zshrc` or `~/.bashrc`). The installer preserves an existing `~/.p10k.zsh` instead of overwriting it, and avoids repeating marked configuration blocks.

## CLI tools

Optional tools: `fzf` (interactive selection), `ripgrep` (search file contents), `bat + fd` (view/find files) and `direnv` (per-project environment). Their installer scripts contain short explanations and upstream links in the header comments.

On Ubuntu, `bat`/`fd` can be installed as `batcat`/`fdfind`; local symlinks are created only when the command names are free.

## Notes

- The NVIDIA Container Toolkit step configures the Docker runtime and restarts Docker. It requires a working NVIDIA driver on the host; WSL and rootless Docker may require additional configuration.
- Docker's `docker` group provides root-equivalent access. Joining it is an explicit opt-in and requires logging out and back in.
- kubectl is downloaded for `amd64` or `arm64` and verified against its published SHA-256 checksum. Existing kubectl installations are preserved by default; a pinned version requires confirmation before replacing a different version.
- Installing Powerlevel10k requires a terminal with Nerd Font glyph support, such as [MesloLGS NF](https://github.com/romkatv/powerlevel10k#fonts). Existing themes/configuration are not migrated automatically.
- The script is intended for personal developer workstations, **not** for fully unattended CI/provisioning. You can rerun it, but review prompts and changes before accepting; system-level installs and third-party installer scripts can still change your environment.

## Inspect, preview, and select installs

The bootstrap supports a read-only **preflight** report (OS, architecture, WSL, Docker,
NVIDIA, free disk space and installed CLIs) and targeted non-interactive installs:

```bash
bash setup-ubuntu.sh --preflight
bash setup-ubuntu.sh --doctor
bash setup-ubuntu.sh --dry-run --only fzf,ripgrep,bat-fd,direnv
bash setup-ubuntu.sh --only fzf,ripgrep,bat-fd,direnv
bash setup-ubuntu.sh --only kubectl --kubectl-version v1.35.1
```

Without `--only`, optional components are prompted interactively and the basic
prerequisite packages are installed. With `--only`, **only the selected installers**
run (plus normal APT dependencies), without unrelated package upgrades. `--only` skips component-selection prompts but `sudo` may still require authentication. Other optional confirmations are skipped or rejected without a terminal.
`--dry-run` prints planned components and never executes installers;
`--preflight` only inspects the environment. `--doctor` checks configured shell hooks, Docker daemon, Compose and NVIDIA runtime without installing anything or pulling container images. Use `--help` for the full list.

Shell configuration changes to existing `~/.zshrc` or `~/.bashrc` create a
timestamped `.devbox-backup-YYYYMMDD-HHMMSS` copy before the first change in
each run. Zsh configuration respects `$ZDOTDIR` when provided. The installer preserves legacy configuration blocks and warns about
known obsolete aliases/auto-cd blocks; it **does not delete or migrate user edits**.

Every selected installer performs a lightweight post-install check for its binary
or expected artifact. This does **not** replace an end-to-end runtime test:
Docker daemon/GPU availability and Kubernetes cluster connectivity must be tested
separately. The final summary distinguishes `INSTALLED`, `CONFIGURED`, `SKIPPED` and `FAILED`. Minikube downloads are SHA-256 verified.

## Validation

```bash
find . -type f -name '*.sh' -print0 | xargs -0 -r -n1 bash -n
bash tests/smoke.sh
bash tests/cli.sh
bash tests/config.sh
bash tests/docker.sh
bash tests/hardening.sh
bash tests/upgrade.sh
bash tests/upgrade-binary.sh
```

CI also runs ShellCheck. Tests do not perform real package installations.
