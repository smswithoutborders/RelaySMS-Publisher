#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Builds the manual in docs/ into book/ with pinned mdbook and mdbook-mermaid
# releases, downloaded once into .mdbook/.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOLS_DIR="$ROOT_DIR/.mdbook"
SERVE=false

MDBOOK_VERSION=0.5.3
MERMAID_VERSION=0.17.1
declare -A SHA256=(
  ["mdbook-x86_64"]=dfb86d8e20a3fed91bf549aa450b9d7f46a275b700292e050cdfd3171732e7fd
  ["mdbook-aarch64"]=428c91cf73fec7494cbefe6e170e12508c9d45d9d096104b7c62d47ff43911c2
  ["mdbook-mermaid-x86_64"]=42aca57eea8521971cc595fe4bb853c5b8b7d9f7138a2ec9f14a0a72c210922d
  ["mdbook-mermaid-aarch64"]=b1782ecaf775bfbe069dead6cdd8ac7cc739d5e62d138bd0e800efec6467cf3a
)

usage() {
  cat <<'EOF'
Usage: build-book.sh [OPTIONS]

  --serve     Serve the manual on http://localhost:3000 and rebuild on changes
  -h, --help  Show this help and exit
EOF
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
    --serve)
      SERVE=true
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      error "Unknown option: $1"
      ;;
    esac
  done
}

# $1=tool $2=version $3=GitHub repo
fetch_tool() {
  local tool="$1" version="$2" repo="$3" dir="$TOOLS_DIR/$1-$2" key tarball
  [ -x "$dir/$tool" ] && return
  key="$tool-$(uname -m)"
  [ -n "${SHA256[$key]:-}" ] || error "No $tool release for $(uname -m)"
  tarball="$(mktemp)"
  curl -fsSL -o "$tarball" \
    "https://github.com/$repo/releases/download/v$version/$tool-v$version-$(uname -m)-unknown-linux-musl.tar.gz"
  echo "${SHA256[$key]}  $tarball" | sha256sum --check --quiet || {
    rm -f "$tarball"
    error "$tool v$version download doesn't match its sha256"
  }
  mkdir -p "$dir"
  tar -xzf "$tarball" -C "$dir" "$tool"
  rm -f "$tarball"
  log "Installed $tool v$version"
}

main() {
  parse_args "$@"
  fetch_tool mdbook "$MDBOOK_VERSION" rust-lang/mdBook
  fetch_tool mdbook-mermaid "$MERMAID_VERSION" badboy/mdbook-mermaid
  export PATH="$TOOLS_DIR/mdbook-$MDBOOK_VERSION:$TOOLS_DIR/mdbook-mermaid-$MERMAID_VERSION:$PATH"

  cd "$ROOT_DIR"
  # Writes mermaid.min.js and mermaid-init.js from the pinned release.
  RUST_LOG=warn mdbook-mermaid install . >/dev/null
  if [ "$SERVE" = true ]; then
    mdbook serve
  else
    mdbook build
  fi
}

main "$@"
