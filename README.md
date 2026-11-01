# Devbox Bootstrap

A small, interactive bootstrap for **Ubuntu** developer machines and Ubuntu on WSL. Run it as your regular user; individual package steps request `sudo` as needed.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/truong51972/devbox-bootstrap/main/setup-ubuntu.sh | bash
```

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

Each optional component is prompted separately and defaults to **No**. Powerlevel10k is offered after installing Zsh; NVIDIA Container Toolkit is offered after Docker Engine. Configuration is written to the selected shell (`~/.zshrc` or `~/.bashrc`). The installer preserves an existing `~/.p10k.zsh` instead of overwriting it, and avoids repeating marked configuration blocks.

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
bash setup-ubuntu.sh --dry-run --only fzf,ripgrep,bat-fd,direnv
bash setup-ubuntu.sh --only fzf,ripgrep,bat-fd,direnv
bash setup-ubuntu.sh --only kubectl --kubectl-version v1.35.1
```

Without `--only`, optional components are prompted interactively and the basic
prerequisite packages are installed. With `--only`, **only the selected installers**
run (plus normal APT dependencies), without unrelated package upgrades.
`--dry-run` prints planned components and never executes installers;
`--preflight` only inspects the environment. Use `--help` for the full list.

Shell configuration changes to existing `~/.zshrc` or `~/.bashrc` create a
timestamped `.devbox-backup-YYYYMMDD-HHMMSS` copy before the first change in
each run. The installer preserves legacy configuration blocks and warns about
known obsolete aliases/auto-cd blocks; it **does not delete or migrate user edits**.

Every selected installer performs a lightweight post-install check for its binary
or expected artifact. This does **not** replace an end-to-end runtime test:
Docker daemon/GPU availability and Kubernetes cluster connectivity must be tested
separately.

## Validation

```bash
find . -type f -name '*.sh' -print0 | xargs -0 -r -n1 bash -n
bash tests/smoke.sh
bash tests/cli.sh
bash tests/config.sh
bash tests/docker.sh
```

CI also runs ShellCheck. Tests do not perform real package installations.
