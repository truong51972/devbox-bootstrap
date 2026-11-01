#!/usr/bin/env bash
# Optional APT cleanup of unused packages and package caches.
# Docs: https://ubuntu.com/server/docs/package-management
sudo apt-get autoremove -y
sudo apt-get autoclean -y
