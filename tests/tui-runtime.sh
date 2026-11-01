#!/usr/bin/env bash
# Assert runtime selection without requiring real Python, pip or uv installations.
set -Eeuo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
export HOME="$tmp/home"
root="$HOME/.local/share/devbox-bootstrap"
mkdir -p "$root/bin" "$root/tui" "$tmp/minimal" "$tmp/with-uv" "$tmp/with-python"
cp "$repo_dir/bin/devbox" "$root/bin/devbox"
cp "$repo_dir/tui/requirements.txt" "$root/tui/requirements.txt"
export MOCK_RUNTIME_LOG="$tmp/runtime.log"

# Restrict PATH so a CI host's installed uv/python3 cannot affect the tests.
for command_name in readlink dirname mkdir chmod; do
    ln -s "$(command -v "$command_name")" "$tmp/minimal/$command_name"
done
ln -s /bin/bash "$tmp/minimal/bash"
for command_name in readlink dirname mkdir chmod; do
    ln -s "$tmp/minimal/$command_name" "$tmp/with-uv/$command_name"
    ln -s "$tmp/minimal/$command_name" "$tmp/with-python/$command_name"
done

cat > "$tmp/with-uv/uv" <<'MOCK'
#!/bin/bash
printf 'uv:%s\n' "$*" >> "$MOCK_RUNTIME_LOG"
case "$1" in
    venv)
        mkdir -p "$2/bin"
        printf '#!/bin/bash\nexit 0\n' > "$2/bin/python"
        chmod +x "$2/bin/python"
        ;;
    pip)
        [[ "$2" == install && "$3" == --python && "$5" == -r ]] || exit 4
        ;;
    *) exit 3 ;;
esac
MOCK
cat > "$tmp/with-uv/python3" <<'MOCK'
#!/bin/bash
echo 'python3 must not be invoked when uv exists' >> "$MOCK_RUNTIME_LOG"
exit 10
MOCK
chmod +x "$tmp/with-uv/uv" "$tmp/with-uv/python3"
out="$(PATH="$tmp/with-uv" /bin/bash "$root/bin/devbox" --setup-runtime)"
[[ "$out" == *'Using uv'* ]]
grep -Fq 'uv:venv ' "$MOCK_RUNTIME_LOG"
grep -Fq 'uv:pip install --python ' "$MOCK_RUNTIME_LOG"
if grep -Fq 'python3 must not' "$MOCK_RUNTIME_LOG"; then
    echo 'uv path incorrectly ran python3' >&2
    exit 1
fi

# With uv absent, python3 -m venv and the venv's pip are used.
rm -rf -- "$root/.venv"
: > "$MOCK_RUNTIME_LOG"
cat > "$tmp/with-python/python3" <<'MOCK'
#!/bin/bash
printf 'python3:%s\n' "$*" >> "$MOCK_RUNTIME_LOG"
[[ "$1" == -m && "$2" == venv ]] || exit 2
mkdir -p "$3/bin"
printf '#!/bin/bash\nprintf "venv-python:%%s\\n" "$*" >> "$MOCK_RUNTIME_LOG"\n' > "$3/bin/python"
chmod +x "$3/bin/python"
MOCK
chmod +x "$tmp/with-python/python3"
out="$(PATH="$tmp/with-python" /bin/bash "$root/bin/devbox" --setup-runtime)"
[[ "$out" == *'uv not found; using python3'* ]]
grep -Fq 'python3:-m venv ' "$MOCK_RUNTIME_LOG"
grep -Fq 'venv-python:-m pip --version' "$MOCK_RUNTIME_LOG"
grep -Fq 'venv-python:-m pip install' "$MOCK_RUNTIME_LOG"

# A missing uv and Python 3 interpreter fails clearly without invoking APT.
rm -rf -- "$root/.venv"
if out="$(PATH="$tmp/minimal" /bin/bash "$root/bin/devbox" --setup-runtime 2>&1)"; then
    echo 'Missing runtimes were accepted' >&2
    exit 1
fi
[[ "$out" == *'No uv or python3 available'* ]]

# A Python 3 executable alone is not sufficient without the venv module.
cat > "$tmp/with-python/python3" <<'MOCK'
#!/bin/bash
exit 1
MOCK
chmod +x "$tmp/with-python/python3"
if out="$(PATH="$tmp/with-python" /bin/bash "$root/bin/devbox" --setup-runtime 2>&1)"; then
    echo 'Broken Python venv was accepted' >&2
    exit 1
fi
[[ "$out" == *'Python venv is unavailable'* ]]

# Prefer a user-local uv even when ~/.local/bin is not yet on PATH.
mkdir -p "$HOME/.local/bin"
cp "$tmp/with-uv/uv" "$HOME/.local/bin/uv"
: > "$MOCK_RUNTIME_LOG"
out="$(PATH="$tmp/minimal" /bin/bash "$root/bin/devbox" --setup-runtime)"
[[ "$out" == *"$HOME/.local/bin/uv"* ]]
grep -Fq 'uv:venv ' "$MOCK_RUNTIME_LOG"

printf 'Devbox runtime selection tests passed.\n'
