---
description: Deploy by following the project's deploy runbook in docs/runbooks/. Only the user starts a deploy.
disable-model-invocation: true
allowed-tools: Read, Glob, Bash(git status *), Bash(git log *), Bash(git branch --show-current)
argument-hint: "[environment]"
---

Deploy by following `docs/runbooks/deploy-*.md` (the one for $ARGUMENTS when several exist) and report the result of each step.

If no deploy runbook exists, do not deploy. Report the detected deployment method (AWS CDK, `cdk.json`: `npx cdk deploy --all`) and offer to write the runbook first with `/add-runbook deploy-<environment>`: `/add-runbook deploy-$ARGUMENTS` when an environment was given, otherwise `/add-runbook deploy-production`. That name matches `docs/runbooks/deploy-*.md`; a runbook named plain `deploy.md` would not.

Run only the deploy, verification, and rollback commands the runbook lists. Pushes, tag deletions, and cloud deploys cannot be undone and differ per project, so an improvised step is riskier than stopping. Before the first step, show `git status --short` and the current branch; if the tree is dirty or the branch is not the one the runbook names, ask before continuing. If a step fails, stop, show its output, and quote the runbook's Rollback section; run a rollback step only after the user confirms it.
