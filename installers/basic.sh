#!/usr/bin/env bash
# Basic Ubuntu build/network dependencies via APT.
# Docs: https://ubuntu.com/server/docs/package-management
sudo apt-get update
sudo apt-get install -y ca-certificates curl wget git gnupg build-essential make
