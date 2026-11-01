#!/usr/bin/env bash
if ! command -v docker >/dev/null 2>&1; then
    die 'Docker Engine must be installed before NVIDIA Container Toolkit.'
    return 1
fi
sudo apt-get install -y gnupg ca-certificates curl
sudo install -m 0755 -d /usr/share/keyrings
# Fetch to a temporary file before replacing a repository keyring; repeatable on re-runs.
( set -Eeuo pipefail
  temp="$(mktemp)"
  trap 'rm -f -- "$temp"' EXIT
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey -o "$temp"
  sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg "$temp"
)
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet docker; then
    sudo systemctl restart docker
elif command -v service >/dev/null 2>&1; then
    if ! sudo service docker restart; then
        warn 'Docker could not be restarted automatically; restart the daemon manually.'
    fi
else
    warn 'Restart Docker manually to apply the NVIDIA runtime configuration.'
fi
