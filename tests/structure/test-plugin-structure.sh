#!/bin/bash
# Tests for project structure: settings, Core files, scripts, commands, CLAUDE.md sections

# --- Settings and Core files ---
assert_json_valid "settings.json is valid JSON" ".claude/settings.json"
assert_json_valid ".mcp.json is valid JSON" ".mcp.json"
for core_file in CLAUDE.md README.md CHANGELOG.md docs/architecture.md docs/onboarding.md \
    docs/decisions/.template.md docs/runbooks/.template.md .env.example .editorconfig .gitignore; do
    assert_file_exists "$core_file exists" "$core_file"
done

# --- Scripts ---
for script in scripts/setup.sh scripts/install-hooks.sh; do
    assert_file_executable "$script is executable" "$script"
    assert_bash_syntax "$script valid bash" "$script"
done

# --- Command frontmatter (every generated command; /review, /test-all, /deploy depend on the tier choice) ---
for cmd_file in .claude/commands/*.md; do
    [ -f "$cmd_file" ] || continue
    CMD_CONTENT=$(cat "$cmd_file")
    assert_contains "$(basename "$cmd_file"): has description" "$CMD_CONTENT" "description:"
    assert_contains "$(basename "$cmd_file"): has allowed-tools" "$CMD_CONTENT" "allowed-tools:"
done

# --- Version consistency: uncomment when the project has a version file (package.json,
# pyproject.toml, Cargo.toml, ...), and point PROJECT_VER at it. It skips until CHANGELOG has a
# release, and a mismatch is reported, never fixed by adding a release or bumping a version. ---
PROJECT_VER=$(python3 -c "import json; print(json.load(open('package.json'))['version'])" 2>/dev/null || echo "missing")
CHANGELOG_VER=$(python3 -c "
import re
m = re.search(r'^## \[(\d+\.\d+\.\d+)\]', open('CHANGELOG.md', encoding='utf-8').read(), re.M)
print(m.group(1) if m else 'missing')" 2>/dev/null || echo "missing")
if [ "$PROJECT_VER" = "missing" ] || [ "$CHANGELOG_VER" = "missing" ]; then
    skip "Version sync: latest CHANGELOG release matches package.json" "no version file or no CHANGELOG release yet"
else
    assert_eq "Version sync: latest CHANGELOG release matches package.json" "$PROJECT_VER" "$CHANGELOG_VER"
fi

# --- CLAUDE.md content (grep -F: fixed strings) ---
for section in "Overview" "Tech Stack" "Project Structure" "Conventions" "Key Commands" "Auto-Sync Rules"; do
    if grep -qF "## $section" CLAUDE.md; then
        pass "CLAUDE.md: has $section"
    else
        fail "CLAUDE.md: has $section" "section '## $section' not found in CLAUDE.md"
    fi
done
