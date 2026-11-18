#!/usr/bin/env bash
# RTK - https://github.com/rtk-ai/rtk
# Requires explicit agent targets to change agent hook configuration.
# Keep pre-existing installations untouched; only newly installed binaries are owned by Devbox.
rtk_state="$HOME/.local/state/devbox-bootstrap/managed"
rtk_receipt="$rtk_state/rtk.sha256"
# Validate agent availability before downloading the executable.
for agent in "${DEVBOX_AGENT_TARGETS_ARRAY[@]}"; do
    command -v "$agent" >/dev/null 2>&1 || {
        die "Cannot configure RTK for $agent: CLI is not on PATH."; return 1;
    }
done
rtk_exe="$(command -v rtk || true)"
if [[ -z "$rtk_exe" && -x "$HOME/.local/bin/rtk" ]]; then
    rtk_exe="$HOME/.local/bin/rtk"
fi
if [[ -n "$rtk_exe" ]]; then
    "$rtk_exe" gain >/dev/null 2>&1 || {
        die "Found $rtk_exe but it is not the rtk-ai token optimizer (rtk gain failed)."
        return 1
    }
    log "RTK already installed: $rtk_exe (preserving existing binary)"
else
    command -v curl >/dev/null 2>&1 || { die 'RTK installation requires curl.'; return 1; }
    tmp_dir="$(mktemp -d)"
    if ! curl -fsSL --retry 3 --connect-timeout 10 \
        https://raw.githubusercontent.com/rtk-ai/rtk/master/install.sh -o "$tmp_dir/install.sh"; then
        rm -rf -- "$tmp_dir"
        die 'Unable to download the official RTK installer.'; return 1
    fi
    # Upstream verifies the release tarball against published SHA-256 checksums.
    if ! RTK_SKIP_CHECKSUM=0 RTK_INSTALL_DIR="$HOME/.local/bin" sh "$tmp_dir/install.sh"; then
        rm -rf -- "$tmp_dir"
        die 'RTK installation failed.'; return 1
    fi
    rm -rf -- "$tmp_dir"
    rtk_exe="$HOME/.local/bin/rtk"
    "$rtk_exe" gain >/dev/null 2>&1 || { die 'RTK post-install identity check failed.'; return 1; }
    mkdir -p "$rtk_state"
    sha256sum "$rtk_exe" | awk '{print $1}' > "$rtk_receipt"
    chmod 600 "$rtk_receipt"
fi

for agent in "${DEVBOX_AGENT_TARGETS_ARRAY[@]}"; do
    case "$agent" in
        claude) agent_bin=claude; init_args=(-g --auto-patch) ;;
        codex) agent_bin=codex; init_args=(-g --codex) ;;
        copilot) agent_bin=copilot; init_args=(-g --copilot) ;;
        opencode) agent_bin=opencode; init_args=(-g --opencode) ;;
        gemini) agent_bin=gemini; init_args=(-g --gemini) ;;
        *) die "Unsupported RTK target: $agent"; return 1 ;;
    esac
    log "Configuring RTK upstream integration for $agent"
    "$rtk_exe" init "${init_args[@]}"
done
