#!/bin/bash
# Prepare the controller on the new Mac. This does not apply host configuration.
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin ]]; then
  echo 'Bootstrap is for macOS. Contributors can use uv sync --locked on Linux.' >&2
  exit 1
fi
if [[ "$EUID" -eq 0 ]]; then
  echo 'Run bootstrap as your normal administrator account, without sudo.' >&2
  exit 1
fi
if ! xcode-select -p >/dev/null 2>&1; then
  echo 'Install Command Line Tools with xcode-select --install, then rerun bootstrap.' >&2
  exit 1
fi
case "$(uname -m)" in
  arm64) brew_bin=/opt/homebrew/bin/brew ;;
  x86_64) brew_bin=/usr/local/bin/brew ;;
  *) echo 'Unsupported architecture' >&2; exit 1 ;;
esac
if [[ ! -x "$brew_bin" ]]; then
  echo 'Install Homebrew using the official instructions at https://brew.sh, then rerun.' >&2
  exit 1
fi
"$brew_bin" install uv python@3.13
uv_bin="$(dirname "$brew_bin")/uv"
"$uv_bin" sync --locked
"$uv_bin" run python scripts/build_cli.py
"$uv_bin" run ansible-galaxy collection install -r requirements.yml
if [[ ! -f inventory/local.yml ]]; then
  cp inventory/example.yml inventory/local.yml
  chmod 600 inventory/local.yml
fi
echo 'Bootstrap complete. Edit inventory/local.yml, then run make plan. See docs/first-boot.md.'
