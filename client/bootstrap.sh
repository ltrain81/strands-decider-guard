#!/usr/bin/env bash
# Developer one-liner, served by the policy console's CloudFront as dev/install.sh (rendered by scripts/lib.sh
# publish_console, which fills in the @...@ values). Downloads the hook files from the same site and runs
# client/install.sh with this deployment's sign-in settings. No AWS access and no repository clone needed:
#
#   bash -c "$(curl -fsSL https://<console>/dev/install.sh)"                       # Claude Code + Codex
#   bash -c "$(curl -fsSL https://<console>/dev/install.sh)" -- --agents claude,codex,kiro --language ko
#   bash -c "$(curl -fsSL https://<console>/dev/install.sh)" -- --uninstall
set -euo pipefail
BASE="@BASE@"
for c in curl tar python3; do command -v "$c" >/dev/null || { echo "missing required tool: $c" >&2; exit 1; }; done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "python3 3.9+ is required" >&2; exit 1; }
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fsSL "$BASE/dev/client.tar.gz" | tar -xz -C "$tmp"
for a in "$@"; do
  if [ "$a" = --uninstall ]; then bash "$tmp/client/install.sh" --uninstall; exit; fi
done
# install.sh copies what it needs into ~/.decider-guard, so the temporary copy can go afterwards.
bash "$tmp/client/install.sh" --api-url "@API_URL@" --client-id "@CLIENT_ID@" @AUTH_ARGS@ "$@"
