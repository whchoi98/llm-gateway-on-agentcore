#!/bin/bash
# PostToolUse (Write|Edit): note when an edited file's module has no CLAUDE.md.
# project-init:module-coverage
# Coverage rule (project-scaffolder SKILL.md, "Module CLAUDE.md Coverage"): a directory is covered
# when it, or an ancestor at or below its source root, has a CLAUDE.md. The note names the
# first-level module directory, because a deeper CLAUDE.md is worth writing only for rules its
# ancestor does not cover.
# Input: the path as $1 (tests), else the event JSON on stdin (tool_input.file_path, session_id).
# Stdin is read only when no argument is given, so a test passing "" never blocks.
# The note is returned as hookSpecificOutput.additionalContext so Claude sees it, once per module
# per session. Registered with `2>/dev/null || true` (observational).

# Directories whose first-level subdirectories are modules. /init-project sets this to the
# project's layout (for example "src", or "packages apps" in a monorepo).
SOURCE_ROOTS="lib lambda"

ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
FILE_PATH="${1:-}"
SESSION_ID=""
if [ $# -eq 0 ] && [ ! -t 0 ]; then
    { IFS= read -r FILE_PATH; IFS= read -r SESSION_ID; } < <(python3 -c '
import json, sys
d = json.load(sys.stdin)
print(d.get("tool_input", {}).get("file_path", ""))
print(d.get("session_id", ""))' 2>/dev/null)
fi
[ -z "$FILE_PATH" ] && exit 0
# Most edits are outside every source root: leave before the git calls below. A linked worktree's
# path (.../.claude/worktrees/<name>/src/...) still matches.
IN_ROOT=false
for SRC in $SOURCE_ROOTS; do
    case "$FILE_PATH" in "$SRC"/*|*/"$SRC"/*) IN_ROOT=true; break ;; esac
done
$IN_ROOT || exit 0

# common_dir <dir>: the repository's shared git directory, the same for a linked worktree and its
# main checkout
common_dir() {
    (
        cd "$1" 2>/dev/null || exit 0
        top=$(git rev-parse --show-toplevel 2>/dev/null) && cd "$top" || exit 0
        dir=$(git rev-parse --git-common-dir 2>/dev/null) && cd "$dir" && pwd -P
    ) 2>/dev/null
}

# CLAUDE_PROJECT_DIR stays at the session's checkout while Claude edits in a linked worktree, so an
# absolute path is resolved against the edited file's own work tree when that tree belongs to this
# repository. git prints the relative path, so a symlinked checkout path makes no difference.
FILE_DIR=$(dirname "$FILE_PATH")
if [[ "$FILE_PATH" == /* ]] && TOP=$(git -C "$FILE_DIR" rev-parse --show-toplevel 2>/dev/null) &&
    [ "$(common_dir "$TOP")" = "$(common_dir "$ROOT")" ]; then
    PREFIX=$(git -C "$ROOT" rev-parse --show-prefix 2>/dev/null)   # the project may sit below its repo's top
    FILE_PATH="$(git -C "$FILE_DIR" rev-parse --show-prefix)${FILE_PATH##*/}"
    [[ "$FILE_PATH" == "$PREFIX"* ]] || exit 0   # outside this project
    FILE_PATH="${FILE_PATH#"$PREFIX"}"
    ROOT="$TOP${PREFIX:+/${PREFIX%/}}"
else
    FILE_PATH="${FILE_PATH#"$ROOT"/}"   # absolute -> project-relative
fi

for SRC in $SOURCE_ROOTS; do
    [[ "$FILE_PATH" == "$SRC"/*/* ]] || continue   # files directly in a source root belong to no module
    REL="${FILE_PATH#"$SRC"/}"
    MODULE="$SRC/${REL%%/*}"
    DIR=$(dirname "$FILE_PATH")
    while [ "$DIR" != "." ]; do
        [ -f "$ROOT/$DIR/CLAUDE.md" ] && exit 0
        [ "$DIR" = "$SRC" ] && break
        DIR=$(dirname "$DIR")
    done

    # Once per module per session. Calls with $1 (tests) carry no session and are not deduplicated.
    if [ -n "$SESSION_ID" ]; then
        SEEN="${TMPDIR:-/tmp}/claude-doc-sync-${SESSION_ID//[^A-Za-z0-9_-]/}"
        grep -qxF -- "$MODULE" "$SEEN" 2>/dev/null && exit 0
        printf '%s\n' "$MODULE" >> "$SEEN" 2>/dev/null
    fi
    MSG="[doc-sync] $MODULE/CLAUDE.md is missing. Add one with /add-module if this module has rules or gotchas the code does not show."
    python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": sys.argv[1]}}))' "$MSG"
    exit 0
done
