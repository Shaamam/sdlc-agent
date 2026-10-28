#!/usr/bin/env bash
# Install sdlc-agent (/ship) globally for Claude Code on macOS and Linux.
#
#   ./install.sh               install (symlinks: `git pull` here updates everyone)
#   ./install.sh --copy        install by copying instead of symlinking
#   ./install.sh --force       replace an existing skill/agent that wasn't installed by us
#   ./install.sh --uninstall   remove what we installed and our settings.json hook
#   ./install.sh --uninstall --purge   also delete run state in ~/.config/sdlc-agent
#
# Honors CLAUDE_CONFIG_DIR and SDLC_AGENT_HOME. Safe to run repeatedly.
set -euo pipefail

MODE=symlink
FORCE=0
ACTION=install
PURGE=0

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --copy) MODE=copy ;;
    --force) FORCE=1 ;;
    --uninstall) ACTION=uninstall ;;
    --purge) PURGE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
AGENT_HOME="${SDLC_AGENT_HOME:-$HOME/.config/sdlc-agent}"
MANIFEST="$AGENT_HOME/installed.txt"
SETTINGS="$CLAUDE_DIR/settings.json"

info() { printf '  %s\n' "$*"; }
pretty() { case "$1" in "$HOME"/*) printf '~%s' "${1#"$HOME"}" ;; *) printf '%s' "$1" ;; esac; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

find_python() {
  local c path
  for c in python3 python; do
    path="$(command -v "$c" 2>/dev/null)" || continue
    if "$path" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      printf '%s\n' "$path"
      return 0
    fi
  done
  return 1
}

in_claude_dir() {
  case "$1" in "$CLAUDE_DIR"/*) return 0 ;; *) return 1 ;; esac
}

is_ours() {
  local target="$1" link
  if [ -L "$target" ]; then
    link="$(readlink "$target")"
    case "$link" in "$REPO_DIR"/*) return 0 ;; esac
  fi
  [ -f "$MANIFEST" ] && grep -Fxq -- "$target" "$MANIFEST"
}

place() {
  local src="$1" target="$2"
  if [ -e "$target" ] || [ -L "$target" ]; then
    if ! is_ours "$target" && [ "$FORCE" -eq 0 ]; then
      die "$target already exists and wasn't installed by sdlc-agent. Re-run with --force to replace it."
    fi
    rm -rf "$target"
  fi
  mkdir -p "$(dirname "$target")"
  if [ "$MODE" = symlink ]; then
    ln -s "$src" "$target"
  else
    cp -R "$src" "$target"
  fi
  printf '%s\n' "$target" >> "$NEW_MANIFEST"
  info "$MODE  $(pretty "$target")"
}

targets() {
  printf '%s\n' "$CLAUDE_DIR/skills/ship" "$CLAUDE_DIR/hooks/sdlc-agent"
  local f
  for f in "$REPO_DIR"/agents/*.md; do
    [ -e "$f" ] && printf '%s\n' "$CLAUDE_DIR/agents/$(basename "$f")"
  done
}

do_install() {
  local py
  py="$(find_python)" || die "Python 3.9+ is required (python3 or python on PATH)."
  command -v git >/dev/null 2>&1 || die "git is required."

  echo "Installing sdlc-agent from $REPO_DIR"
  mkdir -p "$CLAUDE_DIR" "$AGENT_HOME"
  NEW_MANIFEST="$(mktemp)"
  trap 'rm -f "$NEW_MANIFEST"' EXIT

  place "$REPO_DIR/skills/ship" "$CLAUDE_DIR/skills/ship"
  local f
  for f in "$REPO_DIR"/agents/*.md; do
    place "$f" "$CLAUDE_DIR/agents/$(basename "$f")"
  done
  place "$REPO_DIR/hooks" "$CLAUDE_DIR/hooks/sdlc-agent"

  if [ -f "$MANIFEST" ]; then
    local old
    while IFS= read -r old; do
      [ -n "$old" ] || continue
      if ! grep -Fxq -- "$old" "$NEW_MANIFEST" && in_claude_dir "$old"; then
        rm -rf "$old"
        info "removed stale $(pretty "$old")"
      fi
    done < "$MANIFEST"
  fi
  cp "$NEW_MANIFEST" "$MANIFEST"

  "$py" "$REPO_DIR/installer/settings_merge.py" install \
    --settings "$SETTINGS" --python "$py" --hook "$CLAUDE_DIR/hooks/sdlc-agent/guard.py" \
    | sed 's/^/  /'

  echo "Checking tools"
  "$py" "$REPO_DIR/skills/ship/scripts/env_check.py" --no-auth --text \
    --write-userconfig --python-bin "$py" --repo-dir "$REPO_DIR" --mode "$MODE" || true

  cat <<EOF

Done. In any repo, start Claude Code and run:  /ship PROJ-123
First time on this machine? Log in once:  gh auth login   and   acli jira auth login
Restart any Claude Code sessions that are already open so they pick up the skill and hook.
EOF
}

do_uninstall() {
  echo "Uninstalling sdlc-agent"
  local t
  { [ -f "$MANIFEST" ] && cat "$MANIFEST"; targets; } | sort -u | while IFS= read -r t; do
    [ -n "$t" ] || continue
    if { [ -e "$t" ] || [ -L "$t" ]; } && in_claude_dir "$t" && is_ours "$t"; then
      rm -rf "$t"
      info "removed $(pretty "$t")"
    fi
  done
  rm -f "$MANIFEST"

  local py
  if py="$(find_python)"; then
    "$py" "$REPO_DIR/installer/settings_merge.py" uninstall --settings "$SETTINGS" | sed 's/^/  /'
  else
    info "Python not found: remove the hook containing 'hooks/sdlc-agent/guard.py' from $SETTINGS by hand."
  fi

  if [ "$PURGE" -eq 1 ]; then
    rm -rf "$AGENT_HOME"
    info "purged $(pretty "$AGENT_HOME")"
  else
    info "kept run state in $(pretty "$AGENT_HOME") (use --purge to delete it)"
  fi
  echo "Done."
}

if [ "$ACTION" = install ]; then do_install; else do_uninstall; fi
