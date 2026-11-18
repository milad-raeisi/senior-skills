#!/usr/bin/env bash
# Install senior-skills into the skills directory of one or more coding agents.
#
#   ./scripts/install.sh                          # Claude Code (~/.claude/skills)
#   ./scripts/install.sh --agent codex            # one agent
#   ./scripts/install.sh --agent all              # every supported agent
#   ./scripts/install.sh --dir ./.agents/skills   # any directory (e.g. project-level)
#   ./scripts/install.sh --link                   # symlink instead of copy (stays in sync with git pull)
#   ./scripts/install.sh --only bug-triage,ci-auditor
#
# Existing skills with the same name are skipped unless --force is given; with --force
# they are moved to ~/.senior-skills/backups/<timestamp>/ first (outside every skills
# folder, so agents never load them), never deleted.
#
# Works from a clone, or piped from curl (it then clones the repo into a temp directory):
#   curl -fsSL https://raw.githubusercontent.com/milad-raeisi/senior-skills/main/scripts/install.sh | bash -s -- --agent all

set -euo pipefail

REPO_URL="https://github.com/milad-raeisi/senior-skills.git"

usage() {
  sed -n '2,16p' "${BASH_SOURCE[0]:-/dev/null}" 2>/dev/null | sed 's/^# \{0,1\}//'
  cat <<'EOF'
Agents: claude, codex, cursor, gemini, copilot, opencode, windsurf, all
EOF
}

agent_dir() {
  case "$1" in
    claude) echo "$HOME/.claude/skills" ;;
    codex) echo "$HOME/.agents/skills" ;;
    cursor) echo "$HOME/.cursor/skills" ;;
    gemini) echo "$HOME/.gemini/skills" ;;
    copilot) echo "$HOME/.copilot/skills" ;;
    opencode) echo "$HOME/.config/opencode/skills" ;;
    windsurf) echo "$HOME/.codeium/windsurf/skills" ;;
    *) echo "unknown agent: $1" >&2; return 1 ;;
  esac
}

ALL_AGENTS=(claude codex cursor gemini copilot opencode windsurf)
agents=()
dirs=()
mode="copy"
force=0
only=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent)
      [[ $# -ge 2 ]] || { echo "--agent needs a value" >&2; exit 2; }
      if [[ "$2" == "all" ]]; then agents+=("${ALL_AGENTS[@]}"); else agents+=("$2"); fi
      shift 2 ;;
    --dir)
      [[ $# -ge 2 ]] || { echo "--dir needs a value" >&2; exit 2; }
      dirs+=("$2"); shift 2 ;;
    --link) mode="link"; shift ;;
    --force) force=1; shift ;;
    --only)
      [[ $# -ge 2 ]] || { echo "--only needs a value" >&2; exit 2; }
      only="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ ${#agents[@]} -eq 0 && ${#dirs[@]} -eq 0 ]]; then
  agents=(claude)
fi
if [[ ${#agents[@]} -gt 0 ]]; then
  for agent in "${agents[@]}"; do
    dirs+=("$(agent_dir "$agent")")
  done
fi

# Locate the skills: next to this script, or in a fresh shallow clone when piped from curl.
src_root=""
script_path="${BASH_SOURCE[0]:-}"
if [[ -n "$script_path" && -f "$script_path" ]]; then
  candidate="$(cd "$(dirname "$script_path")/.." && pwd)"
  [[ -d "$candidate/skills" ]] && src_root="$candidate"
fi
if [[ -z "$src_root" ]]; then
  if [[ "$mode" == "link" ]]; then
    echo "--link needs a local clone; run the script from inside the repository." >&2
    exit 2
  fi
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  echo "Cloning $REPO_URL ..."
  git clone --quiet --depth 1 "$REPO_URL" "$tmp/senior-skills"
  src_root="$tmp/senior-skills"
fi

skills=()
for path in "$src_root"/skills/*/; do
  name="$(basename "$path")"
  if [[ -n "$only" && ",$only," != *",$name,"* ]]; then continue; fi
  skills+=("$name")
done
if [[ ${#skills[@]} -eq 0 ]]; then
  echo "No skills matched." >&2
  exit 1
fi

stamp="$(date +%Y%m%d-%H%M%S)"
for dest in "${dirs[@]}"; do
  mkdir -p "$dest"
  installed=0 skipped=0
  for name in "${skills[@]}"; do
    target="$dest/$name"
    if [[ -e "$target" || -L "$target" ]]; then
      if [[ $force -eq 0 ]]; then
        echo "  skip  $name (already exists in $dest; use --force to replace it)"
        skipped=$((skipped + 1))
        continue
      fi
      backup="$HOME/.senior-skills/backups/$stamp/$(printf '%s' "${dest#"$HOME"/}" | tr -c 'A-Za-z0-9' '_')"
      mkdir -p "$backup"
      mv "$target" "$backup/$name"
      echo "  backed up existing $name to $backup/$name"
    fi
    if [[ "$mode" == "link" ]]; then
      ln -s "$src_root/skills/$name" "$target"
    else
      cp -R "$src_root/skills/$name" "$target"
    fi
    installed=$((installed + 1))
  done
  echo "$dest: $installed installed, $skipped skipped"
done

echo "Done. Restart your agent session to load the skills."
