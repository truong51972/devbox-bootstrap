# Devbox — Developer Convenience Toolkit

A local-first, keyboard-first developer convenience toolkit for Linux and WSL. Installation/upgrade providers currently target **Ubuntu**; read-only utilities use native Linux commands when present.

## Daily toolkit

Open `devbox` and choose a category or press Ctrl+K from the home screen/catalog. Each action explains when to use it, example input, expected output and limitations. Press ? for module/action help; F1 opens help while typing. Enter submits single-line forms, Tab moves between host/port fields or input/output, and Ctrl+S runs a multiline transform. Tables support / filter, s sort, i details, r refresh, a related actions, and v native output where available. Use `devbox net tcp --help` for CLI action help. Query inputs and outputs are not written to Devbox history. Install, Upgrade, Cleaner and source update still use their guarded execution paths.

```bash
devbox actions
devbox net ports
devbox net port 8000
devbox net dns example.com
devbox sys gpu
devbox sys processes python
devbox storage usage
devbox storage largest .
devbox storage caches
devbox storage cache-sizes
devbox storage files .
devbox docker ps
devbox docker logs api
devbox docker restart api        # preview only
devbox agent integrations
devbox agent skills global
devbox agent integrate rtk codex opencode  # preview only
devbox agent integrate ponytail agy       # independent targets
devbox project detect
devbox health check
devbox health json
devbox env list
devbox env install tmux btop gh jq
printf '{"x":1}' | devbox util json format
devbox util uuid7
devbox run gpu-watch --yes
```

Docker operations are local Unix endpoint only. Process termination requires a user-owned process, matching PID identity and pidfd support; explicitly add --yes to execute CLI mutations. No automatic deletion, remote Docker mutation or project-config execution is performed. Container logs and text transforms may contain secrets; they are displayed but not stored by Devbox. Pass secrets via stdin, not CLI arguments that may be exposed to shell history or other processes.

User workflows are explicitly registered in `$XDG_CONFIG_HOME/devbox-bootstrap/actions.json` (default `~/.config/devbox-bootstrap/actions.json`), e.g. `[{"id":"gpu-status","command":["nvidia-smi"]}]`. Preview with `devbox run gpu-status`, then explicitly launch with `--yes`. Commands are argv arrays, not interpolated shell strings. Workflows can execute arbitrary user-approved commands; review them before launching.

Preview desired state with `devbox env profile profile.json`, e.g. `{"tools":["uv","tmux"],"integrations":{"rtk":["codex"],"ponytail":["agy"]}}`. This creates no changes. Use the regular installer for applying individual tool and integration actions.

Run Devbox as your regular user; individual package steps request sudo as needed.

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
to overwrite tracked local edits or diverged Git history.

On every interactive launch, Devbox checks upstream main in the background.
If new commits can be fast-forwarded, the TUI shows the installed and latest
revisions and asks Yes/No (No is the default; y/n and Esc are supported).
Offline or unsupported checkouts do not block the menu. If you are using
another view, the prompt waits until you return to the main menu.
Both startup Yes and **Update Devbox source** exit the TUI only after source
and runtime update succeed. The terminal shows the outcome and log path;
run devbox again to load the new revision. Failures remain in the Result view.
Set DEVBOX_CHECK_UPDATES=0 to disable the startup check. Startup confirmation pins the offered revision; if upstream changes, reopen Devbox and review again. The runtime dependency fingerprint is checked on launch and repaired if stale. If source updates but runtime setup fails, run `devbox --setup-runtime` to recover (no destructive Git reset). Mutating Devbox operations share a nonblocking per-user lock across CLI and TUI; read-only discovery remains available. The lock does not coordinate unrelated external Docker/APT commands.

The keyboard-first TUI starts at a **minimal grouped menu**. Install/Upgrade
opens a sectioned component list with a contextual details panel, then a
compact confirmation, execution progress, and result screen. Cleaner uses the same
confirmation controls and displays only relevant consent/options. The layout adapts
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
| D | Confirmation | Toggle dry-run (off by default; not supported for source update) |
| Tab | Confirmation | Switch between scrollable plan and options, when present |
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
- Devbox-managed `kubectl` and `minikube` binaries under `/usr/local/bin` can upgrade to newer versions only with a matching ownership receipt and SHA-256 verification; externally managed versions and older installations without receipts are preserved. Legacy binaries are not automatically adopted. For Kubernetes clusters, pin Devbox-managed `kubectl` with `--kubectl-version vMAJOR.MINOR.PATCH` to respect client/server version compatibility; this pinning option is not supported for APT-managed kubectl.
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
- Optional at the end: reboot. Use Cleaner for APT download cache cleanup. The legacy explicit `--only clean` alias only runs `apt-get clean`, never autoremove.

Each optional component is prompted separately and defaults to **No**. Powerlevel10k is offered only when Zsh is available; NVIDIA Toolkit only when Docker is available. Minikube is a separate optional installer. Configuration is written to the selected shell (`~/.zshrc` or `~/.bashrc`). The installer preserves an existing `~/.p10k.zsh` instead of overwriting it, and avoids repeating marked configuration blocks.

## AI agent extensions (P0)

Devbox offers three optional, **user-scoped** components: **RTK** (rtk-ai token
optimizer), **Skills CLI** (Vercel Labs `skills` manager), and **Ponytail**
(DietrichGebert upstream plugins). No agent hooks or plugins are enabled
unless you explicitly select targets in the TUI confirmation screen or pass
`--agents` from the Bash CLI.

```bash
# Select components and target agents interactively in the TUI:
devbox

# Scripted examples:
devbox --only rtk,skills-cli,ponytail --agents codex,claude
devbox --only rtk --agents codex,opencode
devbox --only skills-cli
devbox --dry-run --only rtk,ponytail --agents codex

# Read-only diagnostics / upgrades:
devbox --doctor
devbox --upgrade --only rtk,skills-cli

# Manage actual agent skills with the official manager:
skills add vercel-labs/agent-skills -g -a codex
skills list
skills check
```

Supported target identifiers: `claude`, `codex`, `copilot`, `opencode`,
`gemini`, `agy` (Antigravity CLI). The TUI only offers targets whose CLI is discoverable in the
current environment. `--agents` requires an RTK or Ponytail install; Ponytail
requires at least one selected target. With both selected, the same target
set is applied to both. RTK **without** targets installs only the binary.

**Prerequisites and trust:** Skills CLI requires Node.js >= 22.20 and npm.
Ponytail's Claude and Codex plugin hooks need Node.js. These dependencies
are checked, not silently installed. Claude Code plugin installation from the
non-interactive TUI uses the documented `claude plugin install ... --yes` CLI
form after adding the marketplace. RTK is installed with its official
download script into `~/.local/bin`, and its upstream release checksum check
must succeed; Devbox also verifies `rtk gain` to avoid confusing it with
an unrelated `rtk` package. Skills CLI is installed through npm under
`~/.local` (without sudo). Ponytail uses the agent's official marketplace
or extension commands; those can execute upstream lifecycle hooks. Review
the upstream repository and plugin permissions before installing.

For Antigravity CLI (`agy`), Devbox uses `rtk init -g --agent antigravity` and `agy plugin install https://github.com/DietrichGebert/ponytail`. A recent RTK release with global Antigravity plugin support and an AGY version supporting `plugin list --json` are required. Gemini CLI remains a separate target.

**Activation and maintenance:** Restart the targeted agents afterward. In
Codex, open `/hooks`, review and trust Ponytail's lifecycle hooks yourself.
Devbox stores an install receipt under
`~/.local/state/devbox-bootstrap/agent-extensions/`, but the TUI **does not**
require that receipt to inspect a plugin. It discovers all supported coding-agent
CLIs available on `PATH`, including those installed or configured outside
Devbox, and shows each agent's Ponytail status. An absent agent CLI is marked
`Unavailable`; an available agent without Ponytail is `Missing`. A CLI that
does not support the query or times out reports `Unverified`, not `Missing`.
`Installed` means all detected agents report Ponytail enabled; `Partial`
means some but not all. The aggregate can also be `Checking` while results are
arriving. These checks run **asynchronously** only when the Components screen
opens, with a short cache (60 seconds); the TUI does not wait on a CLI to start.
Press `r` in Components to refresh the plugin inventory manually. The details
panel lists every supported agent with its individual status. The Doctor
continues to report only installation receipts; it is not a live integration
check. `--doctor` is read-only and cannot validate all
third-party plugin states. `--upgrade` only updates Devbox-owned RTK and
Skills CLI installations **with ownership receipts**; any pre-existing
user-local binaries are preserved and remain externally managed. Ponytail
updates remain under the agent's own
plugin manager. This P0 release intentionally does not provide automatic
uninstall or rollback of agent-owned configuration. Do not assume Devbox
will remove any external hooks when uninstalling the binary.

Official sources: https://github.com/rtk-ai/rtk ,
https://github.com/vercel-labs/skills ,
https://github.com/DietrichGebert/ponytail .

## Developer Cleaner

Open **Cleaner** in the TUI to scan installed tools and known cache locations.
Rows appear immediately, with independent read-only probes (up to four concurrently)
and live progress. Slow/unavailable items do not block navigation or selection of
ready items. Esc cancels the scan when returning home; r starts a new scan after
completion. Press **a/A (All safe)** to select all available safe cleaners, even
when a filter is active or scanning is still in progress. Late safe results are
added automatically; Enter waits for the remaining safe checks before opening
confirmation. Unavailable safe items are listed with their reasons. All clears
any previous manual selection. Space or n/N cancels automatic selection; Space
can select a manual item individually. Unknown size alone does not disable a
verified cache or local Docker daemon.
Like Install and Upgrade, confirmation defaults to applying the selected changes;
Enter confirms, d switches to dry-run (no changes). Manual items
require a separate acknowledgement. No cleanup runs merely by opening Cleaner.

```bash
devbox --clean                         # read-only inventory
devbox --clean --scan --json           # machine-readable inventory
devbox --clean --all                   # safe policy preview
devbox --clean --all --yes             # explicitly apply safe policy
devbox --clean --only docker-build-cache,pip-cache --yes
devbox --clean --scan --json          # inspect exact resource tokens
# Then --only docker-unused-images or docker-volumes --resource TOKEN --yes --allow-risky
devbox --clean --help
```

Safe means regenerable caches (rebuilds/downloads may take time): Docker dangling
images (all ages), all unused Engine build cache (7 days), pip/npm downloads and APT archives.
Unused tagged Docker images, unused local Docker volumes (including named
volumes), uv prune/full clean and Devbox logs/events older than 30 days are manual-only.
Both Docker resource groups require explicit individual resource tokens; no bulk prune or forced rm.
In the TUI, select the Manual category, then choose exact resources and acknowledge risk in confirmation.
Volume tokens bind the inspected metadata to the endpoint and protected/non-local/driver-option volumes are excluded. Individual volume sizes are shown when the Docker CLI reports them; manual inventory runs separately from safe probes.
The Engine daemon is explicitly scoped; custom Buildx builders are not inventoried or pruned.
The uv prune operation remains manual because existing symlink-mode environments cannot be ruled out globally.
Result states distinguish actual reported cleanup, zero reported reclaim, unknown measurement, skipped and failed.
WSL compaction is a separate manual Windows operation.
Volume deletion is irreversible; back up first. Volumes labeled
`devbox.protect=true` are excluded. No stopped-container removal, broad system
prune, arbitrary directory deletion, or model-weight deletion is performed.
Docker commands refuse non-Unix endpoints and rely on Docker's native
reference checks; don't run cleanup concurrently with other Docker/build jobs.
The preview describes a policy, not a frozen list of resources; eligibility
is evaluated at execution. Docker estimates are category-wide and may overlap.
Free-space change is measured on root/home filesystems, not attributed exactly
to each cleaner. WSL VHDX compaction is intentionally not automated.

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

### Structured run history

New TUI runs save a versioned JSON summary next to the raw log, including action, duration, exit code, dry-run, per-component states and reported cleaner details. Old logs remain readable. Result distinguishes preview, partial, failed and successful execution; disk-footprint changes are not summed as guaranteed physical storage reclaimed. Background discovery tasks are owned and cancelled on exit, and the existing view layout lives in a separate presentation module. No additional dependencies are required.

The compatibility job runs Python tests on Ubuntu 22.04 and 24.04; the main job runs shell and Python checks. Local Git integration uses disposable repositories and does not contact the network. UI tests check that construction and repeated detail rendering never invoke external commands. Ownership metadata is loaded in the existing background inventory scan; an unknown manager is not assumed to be Devbox-owned. Native operation cancellation is intentionally not exposed while package transactions run. Actual WSL and Docker cleanup measurements remain manual validation steps.

## AI Agents setup

Open **AI Agents → Setup AI agents & skills**. The recommended preset (press `a`) selects Codex, RTK, Ponytail, Skills CLI, and the six current Coding Kit skills. Other coding agent CLIs are optional and never selected by the preset. Space toggles items, Enter reviews the exact plan, and Yes applies it. Dependencies are included automatically. Integrations and skill installs target Codex globally; use the existing per-agent integration actions for other agents. Existing executable installations are preserved. Antigravity remains discoverable and configurable when installed externally.

```bash
devbox agent setup                            # preview preset
devbox agent setup --yes                      # apply preset
devbox agent setup codex skill:context-management # preview subset
devbox agent setup copilot --yes              # optional CLI only
```

Node.js and npm are prerequisites (Skills CLI needs Node.js >=22.20). The installer does not log in, configure authentication, automatically enable optional Coding Kit hooks, or upgrade existing CLIs. Packages and skills are downloaded from their upstream sources when explicitly confirmed. The preset uses explicit skill names and `-a codex`, never upstream `--all`.


### Unified resource workspaces

Open **Development Tools** or **AI Agents** directly from Home. Space selects resources, A selects recommended missing/incomplete resources, U adds all verified safe updates, N clears, R refreshes, I shows details, E opens advanced actions, and Enter reviews the mixed plan. Dry run shows commands without executing them. Ctrl+K opens the command palette (including Favorites). Updates use verified ownership and available versions, not just executable presence. Unknown or external managers are not automatically updated; use Advanced for per-agent integration targets, profile preview and skill checks. APT availability reflects local indexes; the existing upgrade backend refreshes them during execution.

Ponytail update detection verifies the enabled official unpinned Codex marketplace and active plugin version against the upstream manifest. U refreshes only that marketplace and plugin; restart Codex and review `/hooks` afterwards. Coding Kit update detection compares each installed global Skills CLI lockfile tree SHA to the official repository tree (one request); U invokes `skills update <name> -g -y` for only the selected names. Shared global skill directories can affect other agents using the same skill. External/pinned/untracked sources, missing metadata, and ambiguous versions remain Update unknown, not auto-updated. Other Ponytail agent targets remain available through Advanced.


Resource status distinguishes `Manual update` (new release, no automatic ownership), `Check failed` (upstream query failed), and `Update unknown` (insufficient metadata). `M` on an eligible legacy kubectl/Minikube opens a separate confirmed adoption plan. Adoption verifies the exact official release SHA-256 for the installed version and architecture and records ownership without replacing the binary; `U` only selects verified automatic updates. APT checks resolve aliases and merged-/usr paths. Zsh checks the framework and autosuggestions Git upstream as well as APT.


Reviewed resource batches use the same fullscreen Execution, Result, and Activity history as other managed operations. Sudo authentication alone may temporarily use the terminal. Optional privileged install actions are off by default; Tab cycles review, plan and options. Mixed batches retain a single operation lock, stop on failure and record per-resource outcomes. Enter/Esc from Result returns to the originating workspace and refreshes inventory. Home also exposes Update Devbox source directly; successful self-update still exits.

Installed resources with verified update providers can be selected even if current or an upstream check failed. U selects available updates and retryable checks, not current tools. Devbox resolves user-writable npm global installs (including custom/nvm prefixes), supported native agents, pipx uv and official Git-installed Cargo RTK. Legacy Kubernetes binaries are checksum-adopted during the reviewed Update plan. Unsupported or unwritable providers remain blocked; no blind replacement or package-manager switching.

Home groups Development Tools and AI Agents under Manage. The dedicated Update Devbox source row shows Up to date, Update available, Checking, Update blocked, Check failed or Not checked. Highlight it to inspect the last checked installed/upstream revision, commit count and UTC check time. Press R on Home for a fresh check (even when startup checks are disabled); the existing confirmation and exit-on-success behavior is unchanged.
