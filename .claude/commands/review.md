---
description: Review the current changes for bugs, security issues, and CLAUDE.md convention violations. Use before committing or opening a PR.
allowed-tools: Read, Glob, Grep, Bash(git diff *), Bash(git log *), Bash(git status *), Bash(git show *)
argument-hint: "[files or git ref]"
---

Scope: $ARGUMENTS if given, otherwise everything since HEAD: `git diff HEAD` (staged and unstaged) plus the untracked files `git status --short` lists, which `git diff` does not show. If there is nothing to review, say so and stop.

For a multi-file change, delegate to the code-reviewer agent with that scope and return its report as-is. Review a small diff directly, using the report format in `.claude/agents/code-reviewer.md`, because starting a subagent costs more than such a review.

Report every finding with its severity and confidence; do not filter by confidence, because the reader decides what to act on.
