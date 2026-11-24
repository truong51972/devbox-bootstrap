#!/usr/bin/env bash
# Explicit legacy compatibility alias; never remove installed packages.
warn "Legacy clean component: use devbox --clean --only apt-cache --yes."
sudo apt-get clean
