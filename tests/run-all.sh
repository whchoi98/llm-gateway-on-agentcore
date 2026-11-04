#!/bin/bash
# Test runner for harness engineering tests.
# Usage: bash tests/run-all.sh [test-file-pattern]
# Example: bash tests/run-all.sh          # run all tests
#          bash tests/run-all.sh hooks     # run only hook tests

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

TOTAL=0
PASSED=0
FAILED=0
SKIPPED=0
FAILURES=()

export TEST_RUNNER_ACTIVE=1

pass() {
    TOTAL=$((TOTAL + 1))
    PASSED=$((PASSED + 1))
    echo -e "  ${GREEN}✓${NC} $1"
}

fail() {
    TOTAL=$((TOTAL + 1))
    FAILED=$((FAILED + 1))
    FAILURES+=("$1: $2")
    echo -e "  ${RED}✗${NC} $1"
    echo -e "    ${RED}→ $2${NC}"
}

skip() {
    TOTAL=$((TOTAL + 1))
    SKIPPED=$((SKIPPED + 1))
    echo -e "  ${YELLOW}○${NC} $1 (skipped: $2)"
}

assert_eq() {
    local desc="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then pass "$desc"; else fail "$desc" "expected '$expected', got '$actual'"; fi
}

# A glob match, not `echo | grep -q`: grep -q exits at the first match, and under pipefail the
# writer's SIGPIPE then fails the pipeline at random on long output.
assert_contains() {
    local desc="$1" haystack="$2" needle="$3"
    if [[ "$haystack" == *"$needle"* ]]; then pass "$desc"; else fail "$desc" "output does not contain '$needle'"; fi
}

assert_file_exists() {
    local desc="$1" filepath="$2"
    if [ -f "$filepath" ]; then pass "$desc"; else fail "$desc" "file not found: $filepath"; fi
}

assert_file_executable() {
    local desc="$1" filepath="$2"
    if [ -x "$filepath" ]; then pass "$desc"; else fail "$desc" "file not executable: $filepath"; fi
}

assert_json_valid() {
    local desc="$1" filepath="$2"
    if python3 -m json.tool "$filepath" > /dev/null 2>&1; then pass "$desc"; else fail "$desc" "invalid JSON: $filepath"; fi
}

assert_bash_syntax() {
    local desc="$1" filepath="$2"
    if bash -n "$filepath" 2>/dev/null; then pass "$desc"; else fail "$desc" "bash syntax error in: $filepath"; fi
}

export -f pass fail skip assert_eq assert_contains assert_file_exists
export -f assert_file_executable assert_json_valid assert_bash_syntax

FILTER="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Directories under tests/ whose test-*.sh files this runner sources. It sources them into its own
# shell, so list only harness test directories: a project's own shell tests (e2e, integration) may
# call exit or need their own setup, and would end the run early.
TEST_DIRS="hooks structure"

# A sourced test file that calls exit, or an unguarded failure under set -e, ends the run early.
# Report that as a failure, so a Stop gate or CI never reads a truncated run as green.
RUNALL_CURRENT="setup"
RUNALL_FINISHED=0
trap 'runall_rc=$?; if [ "$RUNALL_FINISHED" -eq 0 ]; then echo -e "${RED}run-all.sh stopped early in $RUNALL_CURRENT (exit $runall_rc): a sourced test file exited or hit an unguarded failure${NC}" >&2; exit 1; fi' EXIT

echo -e "${CYAN}=== Harness Test Suite ===${NC}"
echo ""

# One path per line, read on fd 3: paths may contain spaces, and a sourced test that reads stdin
# cannot swallow the rest of the list.
while IFS= read -r test_file <&3; do
    test_name=$(basename "$test_file" .sh)
    if [ -n "$FILTER" ] && ! grep -q -- "$FILTER" <<< "$test_name"; then
        continue
    fi
    RUNALL_CURRENT="$test_name"
    echo -e "${CYAN}▸ $test_name${NC}"
    source "$test_file"
    echo ""
done 3< <(for dir in $TEST_DIRS; do
    [ -d "$SCRIPT_DIR/$dir" ] && find "$SCRIPT_DIR/$dir" -name "test-*.sh"
done | sort)
RUNALL_FINISHED=1

echo -e "${CYAN}=== Results ===${NC}"
echo -e "  Total:   $TOTAL"
echo -e "  ${GREEN}Passed:  $PASSED${NC}"
[ "$FAILED" -gt 0 ] && echo -e "  ${RED}Failed:  $FAILED${NC}" || echo -e "  Failed:  0"
[ "$SKIPPED" -gt 0 ] && echo -e "  ${YELLOW}Skipped: $SKIPPED${NC}" || echo -e "  Skipped: 0"

if [ "$FAILED" -gt 0 ]; then
    echo ""
    echo -e "${RED}=== Failures ===${NC}"
    for f in "${FAILURES[@]}"; do
        echo -e "  ${RED}✗${NC} $f"
    done
    exit 1
fi
echo ""
echo -e "${GREEN}All tests passed.${NC}"
