# Base prerequisites

**Script:** `installers/basic.sh`

**Official sources:** Ubuntu APT documentation: https://ubuntu.com/server/docs/package-management

**What it does:** APT packages: build-essential, Git, curl, wget, CA certificates, GnuPG and make.

**Verification:**

```bash
git --version
curl --version
```

**Notes and safety:** Runs only in interactive full setup, never a full apt upgrade. An --only run skips this base set.

**Rollback:** The bootstrap does not uninstall packages or delete previous user configuration. Use the relevant upstream documentation to remove packages safely; for shell settings, restore the timestamped `.devbox-backup-*` created before edits.
