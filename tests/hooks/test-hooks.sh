#!/bin/bash
# Tests for .claude/hooks/*.sh
# Sourced by run-all.sh under `set -euo pipefail`: every command that may fail is guarded, and
# hooks are called with an argument or explicit stdin so none of them blocks on a read.
# Core hooks must exist; Optional hooks (session-context, notify, verify-on-stop) are tested when present.

HK_ROOT="$PWD"
HK_TMP=$(mktemp -d)

# --- Existence, permissions, syntax ---

for hook in check-doc-sync secret-scan; do
    assert_file_exists "$hook.sh exists" ".claude/hooks/$hook.sh"
done
for hook_file in .claude/hooks/*.sh; do
    [ -f "$hook_file" ] || continue
    assert_file_executable "$(basename "$hook_file") is executable" "$hook_file"
    assert_bash_syntax "$(basename "$hook_file") valid bash" "$hook_file"
done

# --- settings.json registration contract ---

assert_file_exists "settings.json exists" ".claude/settings.json"
assert_json_valid "settings.json is valid JSON" ".claude/settings.json"

# One line per registered command: <event> TAB <matcher> TAB <command>
HK_REGS=$(python3 -c '
import json
hooks = json.load(open(".claude/settings.json")).get("hooks", {})
for event, groups in hooks.items():
    for group in groups:
        for hook in group.get("hooks", []):
            print("%s\t%s\t%s" % (event, group.get("matcher", ""), hook.get("command", "")))
' 2>/dev/null || true)

# hk_check_reg <event> <matcher> <script> <gate|observational>
# A gate must be able to block, so nothing may follow the script path. Every command resolves the
# script through $CLAUDE_PROJECT_DIR, because a relative path exits 127 once Claude cds into a
# subdirectory, and a non-2 exit silently opens a gate.
hk_check_reg() {
    local event="$1" matcher="$2" script="$3" kind="$4" cmd desc
    desc="$event${matcher:+ ($matcher)} runs $script"
    cmd=$(awk -F'\t' -v e="$event" -v m="$matcher" -v s="$script" \
        '$1 == e && $2 == m && index($3, s) { print $3; exit }' <<< "$HK_REGS")
    if [ -z "$cmd" ]; then
        fail "$desc" "no matching registration in .claude/settings.json"
        return 0
    fi
    pass "$desc"
    assert_contains "$script registration resolves via \$CLAUDE_PROJECT_DIR" "$cmd" '"$CLAUDE_PROJECT_DIR"/.claude/hooks/'
    if [ "$kind" = gate ]; then
        if [[ "$cmd" == *"$script" ]]; then
            pass "$script gate registered without || true"
        else
            fail "$script gate registered without || true" "command must end at $script, got: $cmd"
        fi
    elif [[ "$cmd" == *" 2>/dev/null || true" ]]; then
        pass "$script observational registration ends with 2>/dev/null || true"
    else
        fail "$script observational registration ends with 2>/dev/null || true" "got: $cmd"
    fi
}
hk_check_reg PreToolUse Bash secret-scan.sh gate
hk_check_reg PostToolUse "Write|Edit" check-doc-sync.sh observational
if [ -f .claude/hooks/session-context.sh ]; then hk_check_reg SessionStart "" session-context.sh observational; fi
if [ -f .claude/hooks/notify.sh ]; then hk_check_reg Notification "" notify.sh observational; fi
if [ -f .claude/hooks/verify-on-stop.sh ]; then hk_check_reg Stop "" verify-on-stop.sh gate; fi

# --- check-doc-sync.sh: $1 and stdin JSON contract ---

hk_doc_sync() { CLAUDE_PROJECT_DIR="$HK_ROOT" TMPDIR="$HK_TMP" bash .claude/hooks/check-doc-sync.sh "$@" 2>&1 || true; }

OUTPUT=$(hk_doc_sync "")
assert_eq "check-doc-sync: empty path produces no output" "" "$OUTPUT"

# Probe a module that does not exist under the first SOURCE_ROOTS entry
HK_SRC=$(sed -n 's/^SOURCE_ROOTS="\([^" ]*\).*/\1/p' .claude/hooks/check-doc-sync.sh)
HK_SRC="${HK_SRC:-src}"
HK_PROBE="{\"tool_input\":{\"file_path\":\"$HK_SRC/__probe__/x.ts\"},\"session_id\":\"hk-test\"}"
OUTPUT=$(printf '%s' "$HK_PROBE" | hk_doc_sync)
if [ -f "$HK_SRC/CLAUDE.md" ]; then
    assert_eq "check-doc-sync: $HK_SRC/CLAUDE.md covers every module below it" "" "$OUTPUT"
else
    assert_contains "check-doc-sync: reads file_path from stdin JSON" "$OUTPUT" "additionalContext"
    assert_contains "check-doc-sync: names the uncovered module" "$OUTPUT" "$HK_SRC/__probe__/CLAUDE.md is missing"
    HK_JSON_OK=$(printf '%s' "$OUTPUT" | python3 -m json.tool >/dev/null 2>&1 && echo yes || echo no)
    assert_eq "check-doc-sync: output is valid JSON" "yes" "$HK_JSON_OK"
    OUTPUT=$(printf '%s' "$HK_PROBE" | hk_doc_sync)
    assert_eq "check-doc-sync: notes each module once per session" "" "$OUTPUT"
fi

# --- secret-scan.sh: commit gate ---

OUTPUT=$(echo '{"tool_input":{"command":"ls -la"}}' | bash .claude/hooks/secret-scan.sh 2>&1; echo "exit=$?")
assert_eq "secret-scan: non-commit command passes silently with exit 0" "exit=0" "$OUTPUT"

# Sample key built at runtime so this file never matches the scan itself
HK_AWS_ID="AKIA""IOSFODNN7EXAMPLE"

# hk_repo: print the path of a fresh repo whose only commit holds a clean cfg.py.
# It fails loudly rather than fall back to the current directory, which is the real repo.
hk_repo() {
    local dir
    dir=$(mktemp -d "$HK_TMP/repo.XXXXXX") && [ -d "$dir" ] || return 1
    (
        cd "$dir" && git init -q && printf 'x = 1\n' > cfg.py && git add cfg.py &&
            git -c user.name=test -c user.email=test@example.invalid -c commit.gpgsign=false \
                commit -q --no-verify -m init
    ) >/dev/null 2>&1 || true
    printf '%s\n' "$dir"
}
# hk_scan_rc <repo> <command>: exit code of secret-scan.sh for that Bash command, run from <repo>
# (`&& ... || echo $?` keeps the runner's `set -e` from aborting on the expected exit 2)
hk_scan_rc() {
    local json
    json=$(python3 -c 'import json,sys; print(json.dumps({"tool_input": {"command": sys.argv[1]}}))' "$2")
    ( cd "$1" && printf '%s' "$json" | bash "$HK_ROOT/.claude/hooks/secret-scan.sh" >/dev/null 2>&1 ) && echo 0 || echo $?
}

HK_REPO=$(hk_repo)
printf 'key = "%s"\n' "$HK_AWS_ID" > "$HK_REPO/cfg.py"
(cd "$HK_REPO" && git add cfg.py) || true
assert_eq "secret-scan: staged secret blocks commit with exit 2" "2" "$(hk_scan_rc "$HK_REPO" "git commit -m test")"
assert_eq "secret-scan: git -C . commit is gated too" "2" "$(hk_scan_rc "$HK_REPO" "git -C . commit -m x")"

HK_REPO=$(hk_repo)
printf 'key = "%s"\n' "$HK_AWS_ID" > "$HK_REPO/new.py"
assert_eq "secret-scan: chained git add && git commit is scanned" "2" "$(hk_scan_rc "$HK_REPO" "git add new.py && git commit -m x")"

HK_REPO=$(hk_repo)
printf 'key = "%s"\n' "$HK_AWS_ID" > "$HK_REPO/cfg.py"
assert_eq "secret-scan: commit -am scans modified tracked files" "2" "$(hk_scan_rc "$HK_REPO" "git commit -am x")"

HK_REPO=$(hk_repo)
mkdir -p "$HK_REPO/.claude/hooks"
cp .claude/hooks/secret-scan.sh "$HK_REPO/.claude/hooks/secret-scan.sh"
(cd "$HK_REPO" && git add .claude/hooks/secret-scan.sh) || true
assert_eq "secret-scan: its own pattern definitions do not block" "0" "$(hk_scan_rc "$HK_REPO" "git commit -m x")"

hk_commit() { git -c user.name=test -c user.email=test@example.invalid -c commit.gpgsign=false commit -q --no-verify "$@"; }

# renames are scanned (git reports R once the new file is mostly the old one)
HK_REPO=$(hk_repo)
(cd "$HK_REPO" && seq 1 40 > big.py && git add big.py && hk_commit -m big && git mv big.py moved.py &&
    printf 'key = "%s"\n' "$HK_AWS_ID" >> moved.py && git add moved.py) >/dev/null 2>&1 || true
assert_eq "secret-scan: a staged rename that adds a secret blocks" "2" "$(hk_scan_rc "$HK_REPO" "git commit -m x")"
HK_REPO=$(hk_repo)
(cd "$HK_REPO" && git mv cfg.py moved.py) >/dev/null 2>&1 || true
assert_eq "secret-scan: a clean rename passes" "0" "$(hk_scan_rc "$HK_REPO" "git commit -m x")"

# a quoted git option value still counts as a commit
HK_REPO=$(hk_repo)
printf 'key = "%s"\n' "$HK_AWS_ID" > "$HK_REPO/cfg.py"
(cd "$HK_REPO" && git add cfg.py) || true
assert_eq "secret-scan: git -c user.name=\"Claude Code\" commit is gated" "2" \
    "$(hk_scan_rc "$HK_REPO" 'git -c user.name="Claude Code" -c user.email=noreply@anthropic.com commit -m "init"')"

# a glob pathspec is matched by git; git add -f resolves its paths where that add runs; cd options
# (-P, --) are not the directory
HK_REPO=$(hk_repo)
printf 'key = "%s"\n' "$HK_AWS_ID" > "$HK_REPO/cfg.py"
assert_eq "secret-scan: git commit -- '*.py' (a glob) scans the matching files" "2" "$(hk_scan_rc "$HK_REPO" "git commit -m x -- '*.py'")"
HK_REPO=$(hk_repo)
mkdir -p "$HK_REPO/sub"
printf 'sub/.env\n' > "$HK_REPO/.gitignore"
printf 'KEY="%s"\n' "$HK_AWS_ID" > "$HK_REPO/sub/.env"
assert_eq "secret-scan: git -C sub add -f .env && git commit blocks" "2" "$(hk_scan_rc "$HK_REPO" 'git -C sub add -f .env && git commit -m x')"
assert_eq "secret-scan: cd -- sub && git add -f .env && git commit blocks" "2" \
    "$(hk_scan_rc "$HK_REPO" 'cd -- sub && git add -f .env && git commit -m x')"

# CLAUDE.md is scanned despite '*.md'; tests/fixtures is scanned beyond the two sample files
HK_REPO=$(hk_repo)
mkdir -p "$HK_REPO/docs"
printf 'key %s\n' "$HK_AWS_ID" > "$HK_REPO/docs/CLAUDE.md"
(cd "$HK_REPO" && git add docs) || true
assert_eq "secret-scan: a CLAUDE.md with a secret blocks" "2" "$(hk_scan_rc "$HK_REPO" "git commit -m x")"
HK_REPO=$(hk_repo)
mkdir -p "$HK_REPO/tests/fixtures"
printf 'Authorization: %s\n' "$HK_AWS_ID" > "$HK_REPO/tests/fixtures/cassette.yaml"
(cd "$HK_REPO" && git add tests) || true
assert_eq "secret-scan: other files under tests/fixtures are scanned" "2" "$(hk_scan_rc "$HK_REPO" "git commit -m x")"

# without python3 the commit goes through, with a warning the user (systemMessage) and Claude see
HK_REPO=$(hk_repo)
printf 'key = "%s"\n' "$HK_AWS_ID" > "$HK_REPO/cfg.py"
(cd "$HK_REPO" && git add cfg.py) || true
HK_NOPY="$HK_TMP/nopy-bin"
mkdir -p "$HK_NOPY"
for hk_tool in git cat tr; do
    ln -s "$(command -v "$hk_tool")" "$HK_NOPY/$hk_tool" 2>/dev/null || true
done
HK_OUT=$( (cd "$HK_REPO" && printf '%s' '{"tool_input":{"command":"git commit -m x"}}' |
    PATH="$HK_NOPY" "$BASH" "$HK_ROOT/.claude/hooks/secret-scan.sh" 2>/dev/null; echo "exit=$?") || true)
assert_contains "secret-scan: without python3 the commit goes through" "$HK_OUT" "exit=0"
assert_contains "secret-scan: without python3 the warning reaches the user" "$HK_OUT" '"systemMessage"'

# --- Linked worktrees: CLAUDE_PROJECT_DIR stays at the main checkout, the edited path is in the worktree ---

HK_REPO=$(hk_repo)
HK_WT="$HK_REPO/.claude/worktrees/wt1"
(cd "$HK_REPO" && git worktree add -q "$HK_WT") >/dev/null 2>&1 || true
mkdir -p "$HK_WT/$HK_SRC/__probe__"
HK_EVENT=$(python3 -c 'import json,sys; print(json.dumps({"tool_input": {"file_path": sys.argv[1]}}))' "$HK_WT/$HK_SRC/__probe__/x.ts")
OUTPUT=$(printf '%s' "$HK_EVENT" | CLAUDE_PROJECT_DIR="$HK_REPO" TMPDIR="$HK_TMP" bash .claude/hooks/check-doc-sync.sh 2>&1 || true)
assert_contains "check-doc-sync: a worktree edit is checked in that worktree" "$OUTPUT" "$HK_SRC/__probe__/CLAUDE.md is missing"

# --- scripts/install-hooks.sh: the commit-msg hook it installs ---

if [ -f scripts/install-hooks.sh ]; then
    # hk_git_env: only the repo's own config, so a global core.hooksPath cannot redirect the hooks
    hk_git_env() { HOME="$HK_TMP" XDG_CONFIG_HOME="$HK_TMP" GIT_CONFIG_NOSYSTEM=1 "$@"; }
    HK_REPO=$(hk_repo)
    HK_RC=$( (cd "$HK_REPO" && hk_git_env bash "$HK_ROOT/scripts/install-hooks.sh" >/dev/null 2>&1) && echo 0 || echo $?)
    assert_eq "install-hooks: installs the commit-msg hook in a fresh repository" "0" "$HK_RC"
    HK_SED_I=$(grep -v '^[[:space:]]*#' "$HK_REPO/.git/hooks/commit-msg" 2>/dev/null |
        grep -E "sed[[:space:]]+(-[A-Za-z]*[[:space:]]+)*-i([[:space:]\"']|$)" || true)
    assert_eq "install-hooks: commit-msg avoids a bare sed -i, which fails on macOS" "" "$HK_SED_I"
    ( cd "$HK_REPO" && printf 'z\n' > z.txt && git add z.txt &&
        printf 'subject\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n' | hk_git_env git -c user.name=test \
            -c user.email=test@example.invalid -c commit.gpgsign=false commit -q -F - ) >/dev/null 2>&1 || true
    assert_eq "install-hooks: commit-msg keeps the message and removes Co-Authored-By lines" "subject" \
        "$(git -C "$HK_REPO" log -1 --format=%B 2>/dev/null || true)"
    assert_eq "install-hooks: commit-msg runs with /bin/sh, since /bin/bash is missing on some systems" "#!/bin/sh" \
        "$(sed -n 1p "$HK_REPO/.git/hooks/commit-msg" 2>/dev/null || true)"
    HK_RC=$( (cd "$HK_REPO" && hk_git_env bash "$HK_ROOT/scripts/install-hooks.sh" >/dev/null 2>&1) && echo 0 || echo $?)
    assert_eq "install-hooks: a rerun replaces the hook it installed" "0" "$HK_RC"
    printf '#!/bin/sh\n# add Change-Id\nexit 0\n' > "$HK_REPO/.git/hooks/commit-msg" 2>/dev/null || true
    HK_RC=$( (cd "$HK_REPO" && hk_git_env bash "$HK_ROOT/scripts/install-hooks.sh" >/dev/null 2>&1) && echo 0 || echo $?)
    assert_eq "install-hooks: a commit-msg hook it did not install is left alone (exit 1)" "1" "$HK_RC"
fi

# --- Optional hooks ---

if [ -f .claude/hooks/session-context.sh ]; then
    HK_RC=$( (CLAUDE_PROJECT_DIR="$HK_ROOT" bash .claude/hooks/session-context.sh </dev/null >/dev/null 2>&1) && echo 0 || echo $?)
    assert_eq "session-context: exits 0 without reading stdin" "0" "$HK_RC"
    OUTPUT=$(CLAUDE_PROJECT_DIR="$HK_ROOT" bash .claude/hooks/session-context.sh </dev/null 2>&1 || true)
    HK_GIT_LINES=$(echo "$OUTPUT" | grep -E "^(Branch|Last commit|Uncommitted changes):" || true)
    assert_eq "session-context: leaves git state to Claude Code's own context" "" "$HK_GIT_LINES"
fi

if [ -f .claude/hooks/notify.sh ]; then
    OUTPUT=$(CLAUDE_NOTIFY_WEBHOOK="" bash .claude/hooks/notify.sh "test" "msg" 2>&1 || true)
    assert_eq "notify.sh: no webhook URL produces no output" "" "$OUTPUT"
fi

if [ -f .claude/hooks/verify-on-stop.sh ]; then
    # hk_stop_rc <repo> <stdin> <check>: exit code of verify-on-stop.sh with <check> as VERIFY_CMD
    hk_stop_rc() {
        ( cd "$1" && printf '%s' "$2" | CLAUDE_PROJECT_DIR="$1" TMPDIR="$HK_TMP" VERIFY_CMD="$3" \
            bash "$HK_ROOT/.claude/hooks/verify-on-stop.sh" >/dev/null 2>&1 ) && echo 0 || echo $?
    }
    HK_REPO=$(hk_repo)
    assert_eq "verify-on-stop: clean tree skips the check" "0" "$(hk_stop_rc "$HK_REPO" '{}' false)"
    printf 'y = 2\n' > "$HK_REPO/new.py"
    assert_eq "verify-on-stop: failing check on a changed tree blocks with exit 2" "2" "$(hk_stop_rc "$HK_REPO" '{}' false)"
    assert_eq "verify-on-stop: stop_hook_active on an unchanged tree lets the turn end" "0" \
        "$(hk_stop_rc "$HK_REPO" '{"stop_hook_active": true}' false)"
    assert_eq "verify-on-stop: an unchanged red tree is not blocked again" "0" "$(hk_stop_rc "$HK_REPO" '{}' false)"
    printf 'y = 3\n' > "$HK_REPO/new.py"
    assert_eq "verify-on-stop: stop_hook_active after a change runs the check again" "2" \
        "$(hk_stop_rc "$HK_REPO" '{"stop_hook_active": true}' false)"
    printf 'y = 4\n' > "$HK_REPO/new.py"
    assert_eq "verify-on-stop: passing check lets the turn end" "0" "$(hk_stop_rc "$HK_REPO" '{}' true)"
    HK_COUNTED="echo run >> '$HK_TMP/verify-runs'; true"   # a passing check that counts its runs
    hk_stop_rc "$HK_REPO" '{}' "$HK_COUNTED" >/dev/null
    hk_stop_rc "$HK_REPO" '{}' "$HK_COUNTED" >/dev/null
    assert_eq "verify-on-stop: unchanged tree after a green run is skipped" "1" "$( (wc -l < "$HK_TMP/verify-runs") 2>/dev/null | tr -d ' ')"

    # a nested repository (an untracked dir/ entry) does not end the fingerprint early
    HK_REPO=$(hk_repo)
    (cd "$HK_REPO" && mkdir -p vendor/lib && cd vendor/lib && git init -q) >/dev/null 2>&1 || true
    printf 'ok\n' > "$HK_REPO/zz.py"
    assert_eq "verify-on-stop: green run beside a nested repository" "0" "$(hk_stop_rc "$HK_REPO" '{}' 'grep -q ok zz.py')"
    printf 'bad\n' > "$HK_REPO/zz.py"
    assert_eq "verify-on-stop: an untracked file listed after a nested repository counts as a change" "2" \
        "$(hk_stop_rc "$HK_REPO" '{}' 'grep -q ok zz.py')"

    # the event's cwd follows Claude into a linked worktree
    HK_REPO=$(hk_repo)
    HK_WT="$HK_REPO/.claude/worktrees/wt1"
    (cd "$HK_REPO" && git worktree add -q "$HK_WT" && printf '.claude/worktrees/\n' >> .git/info/exclude) >/dev/null 2>&1 || true
    printf 'BROKEN\n' > "$HK_WT/new.py"
    HK_EVENT=$(python3 -c 'import json,sys; print(json.dumps({"cwd": sys.argv[1]}))' "$HK_WT")
    assert_eq "verify-on-stop: a red linked worktree (event cwd) blocks" "2" \
        "$(hk_stop_rc "$HK_REPO" "$HK_EVENT" '! grep -q BROKEN new.py')"

    # A run the hook timeout kills leaves "pending <fingerprint>" in the cache (simulated below): the
    # next Stop on that tree tells the user once, in systemMessage, and does not run the check again
    HK_REPO=$(hk_repo)
    printf 'y = 2\n' > "$HK_REPO/new.py"
    HK_KILL_TMP=$(mktemp -d "$HK_TMP/killed.XXXXXX")
    HK_KILL_CMD="echo run >> '$HK_TMP/killed-runs'; true"
    # hk_stop_out: stdout of verify-on-stop.sh with HK_KILL_CMD as the check, then "exit=<code>"
    hk_stop_out() {
        ( cd "$HK_REPO" && printf '{}' | CLAUDE_PROJECT_DIR="$HK_REPO" TMPDIR="$HK_KILL_TMP" VERIFY_CMD="$HK_KILL_CMD" \
            bash "$HK_ROOT/.claude/hooks/verify-on-stop.sh" 2>/dev/null; echo "exit=$?" ) || true
    }
    hk_stop_out >/dev/null
    for hk_f in "$HK_KILL_TMP"/claude-verify-on-stop-*; do
        if [ -f "$hk_f" ]; then printf 'pending %s\n' "$(cat "$hk_f")" > "$hk_f"; fi
    done
    rm -f "$HK_TMP/killed-runs"
    HK_OUT=$(hk_stop_out)
    HK_MSG=$(printf '%s' "${HK_OUT%exit=*}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["systemMessage"])' 2>/dev/null || echo "no JSON systemMessage")
    assert_contains "verify-on-stop: a killed run is reported to the user" "$HK_MSG" "did not finish"
    assert_contains "verify-on-stop: a killed run lets the turn end" "$HK_OUT" "exit=0"
    assert_eq "verify-on-stop: a killed run is not rerun on the same tree" "no" "$([ -f "$HK_TMP/killed-runs" ] && echo yes || echo no)"
    assert_eq "verify-on-stop: a killed run is reported once" "exit=0" "$(hk_stop_out)"
fi

rm -rf -- "$HK_TMP"   # -f: git objects are read-only, and rm would prompt on a terminal
