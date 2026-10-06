#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Moves runtime data from platforms/ and gateway_clients/ into data/. Safe to
# rerun: paths already moved, or set in .env to somewhere else, are left alone.
# Run with the services stopped, as root or as the install's owner.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

INSTALL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$INSTALL_DIR/.env"
PYTHON="$INSTALL_DIR/venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3

# Env var, old default, new default (both relative to INSTALL_DIR).
MOVES=(
  "PLATFORMS_ADAPTERS_DIR platforms/adapters data/platforms/adapters"
  "PLATFORMS_ADAPTERS_VENV_DIR platforms/adapters_venv data/platforms/venvs"
  "PLATFORMS_ADAPTERS_ASSETS_DIR platforms/adapters_assets data/platforms/assets"
  "PLATFORMS_REGISTRY_FILE platforms/registry.json data/platforms/registry.json"
  "GATEWAY_CLIENTS_REGISTRY_FILE gateway_clients/registry.json data/gateway_clients/registry.json"
)

move_one() {
  local var="$1" old="$2" new="$3" value=""
  [ -f "$ENV_FILE" ] && value="$(read_env_var "$var" "$ENV_FILE")"
  # A custom location stays where it is.
  case "$value" in
  "" | "$old" | "$INSTALL_DIR/$old") ;;
  *) return ;;
  esac

  if [ -e "$INSTALL_DIR/$old" ] && [ ! -e "$INSTALL_DIR/$new" ]; then
    mkdir -p "$(dirname "$INSTALL_DIR/$new")"
    mv "$INSTALL_DIR/$old" "$INSTALL_DIR/$new"
    log "Moved $old to $new"
  fi

  if [ -n "$value" ]; then
    local new_value="$new"
    [[ "$value" = /* ]] && new_value="$INSTALL_DIR/$new"
    sed -i "s#^$var=.*#$var=$new_value#" "$ENV_FILE"
    log "Set $var=$new_value in .env"
  fi
}

# Old=new path pairs, absolute and relative, for every move that has happened.
moved_paths() {
  local entry var old new
  for entry in "${MOVES[@]}"; do
    read -r var old new <<<"$entry"
    [ -e "$INSTALL_DIR/$new" ] && [ ! -e "$INSTALL_DIR/$old" ] || continue
    echo "$INSTALL_DIR/$old=$INSTALL_DIR/$new"
    echo "$old=$new"
  done
}

# The adapter registry stores each adapter's paths; point them at the new dirs.
rewrite_registry() {
  local registry="$INSTALL_DIR/data/platforms/registry.json" renames
  [ -f "$registry" ] || return 0
  mapfile -t renames < <(moved_paths)
  "$PYTHON" - "$registry" "${renames[@]}" <<'EOF'
import json, sys

path, renames = sys.argv[1], [r.split("=", 1) for r in sys.argv[2:]]
with open(path) as f:
    registry = json.load(f)
changed = False
for manifest in registry.values():
    for field in ("path", "venv_path", "assets_path"):
        for old, new in renames:
            if manifest.get(field, "").startswith(old + "/"):
                manifest[field] = new + manifest[field][len(old):]
                changed = True
                break
if changed:
    with open(path, "w") as f:
        json.dump(registry, f)
    print("Updated adapter paths in the registry")
EOF
}

# venv scripts hardcode their venv's absolute path in the shebang.
rewrite_venv_scripts() {
  local venvs="$INSTALL_DIR/data/platforms/venvs" rename old new
  [ -d "$venvs" ] || return 0
  while read -r rename; do
    old="${rename%%=*}" new="${rename#*=}"
    [[ "$old" = /* ]] || continue
    { grep -rlIF "$old/" "$venvs" 2>/dev/null || true; } |
      while read -r file; do sed -i "s#$old/#$new/#g" "$file"; done
  done < <(moved_paths)
}

# The overrides file used to be tracked; keep any local entries, then restore
# the tracked copy so git pull can't conflict with it.
move_overrides() {
  local old="$INSTALL_DIR/gateway_clients/mcc_mnc_overrides.json"
  local new="$INSTALL_DIR/data/gateway_clients/mcc_mnc_overrides.json"
  [ -f "$old" ] && [ ! -e "$new" ] || return 0
  if [ "$(tr -d '[:space:]' <"$old")" != "[]" ]; then
    mkdir -p "$(dirname "$new")"
    cp -p "$old" "$new"
    log "Moved MCC/MNC overrides to data/gateway_clients/"
  fi
  git -C "$INSTALL_DIR" checkout -- gateway_clients/mcc_mnc_overrides.json 2>/dev/null || true
}

main() {
  local entry
  for entry in "${MOVES[@]}"; do
    # shellcheck disable=SC2086  # entries are space-separated fields
    move_one $entry
  done
  rewrite_registry
  rewrite_venv_scripts
  move_overrides
}

main "$@"
