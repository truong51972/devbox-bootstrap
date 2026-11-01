# SSH authentication keychain

**Script:** `installers/keychain.sh`

**Official sources:** Upstream: https://github.com/funtoo/keychain ; Ubuntu package: https://packages.ubuntu.com/search?keywords=keychain

**What it does:** APT installs keychain. Prefer existing ~/.ssh/git or ~/.ssh/id_ed25519; otherwise optionally generate an Ed25519 key.

**Verification:**

```bash
keychain --version
```

**Notes and safety:** Never overwrite existing SSH private keys. No empty passphrase is forced. Shell profile is modified only for a selected key.

**Rollback:** The bootstrap does not uninstall packages or delete previous user configuration. Use the relevant upstream documentation to remove packages safely; for shell settings, restore the timestamped `.devbox-backup-*` created before edits.
