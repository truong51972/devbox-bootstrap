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

- Base packages (always): compiler/build tools, Git, curl, wget, CA certificates, and GnuPG. No automatic full-system `apt upgrade`.
- Optional: Zsh + Oh My Zsh, syntax highlighting, autosuggestions, Powerlevel10k; uv; SSH keychain; zoxide; Docker Engine; NVIDIA Container Toolkit; kubectl; and Minikube.
- Optional at the end: apt cleanup and reboot.

Each optional component is prompted separately and defaults to **No**. Powerlevel10k is offered after installing Zsh; NVIDIA Container Toolkit is offered after Docker Engine. Configuration is written to the selected shell (`~/.zshrc` or `~/.bashrc`). The installer preserves an existing `~/.p10k.zsh` instead of overwriting it, and avoids repeating marked configuration blocks.

## Notes

- The NVIDIA Container Toolkit step configures the Docker runtime and restarts Docker. It requires a working NVIDIA driver on the host; WSL and rootless Docker may require additional configuration.
- Docker's `docker` group provides root-equivalent access. Joining it is an explicit opt-in and requires logging out and back in.
- kubectl is downloaded for `amd64` or `arm64` and verified against its published SHA-256 checksum. Existing kubectl installations are left untouched.
- Installing Powerlevel10k requires a terminal with Nerd Font glyph support, such as [MesloLGS NF](https://github.com/romkatv/powerlevel10k#fonts). Existing themes/configuration are not migrated automatically.
- The script is intended for personal developer workstations, **not** for fully unattended CI/provisioning. You can rerun it, but review prompts and changes before accepting; system-level installs and third-party installer scripts can still change your environment.

## Validation

```bash
find . -type f -name '*.sh' -print0 | xargs -0 -r -n1 bash -n
bash tests/smoke.sh
```

CI also runs ShellCheck. Tests do not perform real package installations.
