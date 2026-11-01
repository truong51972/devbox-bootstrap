# uv Python environment manager

**Script:** `installers/python.sh`

**Official sources:** Official: https://docs.astral.sh/uv/ ; repository: https://github.com/astral-sh/uv

**What it does:** Fetch and execute the official uv installer only if uv is absent.

**Verification:**

```bash
uv --version
```

**Notes and safety:** No custom Python shell aliases are installed. The upstream installer executes downloaded code: review it if needed.

**Rollback:** The bootstrap does not uninstall packages or delete previous user configuration. Use the relevant upstream documentation to remove packages safely; for shell settings, restore the timestamped `.devbox-backup-*` created before edits.
