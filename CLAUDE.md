<!-- Prune test: keep a line only if removing it would cause Claude to make a mistake. Leave out what Claude can read from the code or config. -->

# Project Context

## Overview
LLM Gateway on Amazon Bedrock AgentCore Gateway in ap-northeast-2: one inference endpoint for Claude, GPT, and Kimi models. Every request goes to Bedrock Global CRIS first; Claude falls back to Claude Platform on AWS (1P, "CPonAWS") and GPT to Bedrock Mantle in us-east-1. Kimi has no fallback. Infrastructure is AWS CDK (TypeScript).

## Tech Stack
- AWS CDK in TypeScript, run through `tsx`; AgentCore resources are mostly L1 `Cfn*` because the L2 Gateway has no inference targets.
- Lambda: Python (REQUEST interceptor) and Node.js ESM (CPonAWS streaming proxy), deployed as plain source with no bundling or third-party dependencies.
- `scripts/*.py` declare their dependencies inline (PEP 723) and run with `uv run`.

## Project Structure
```text
bin/app.ts      CDK app: LlmGatewayStack, then LlmGatewayPolicyStack (Cedar)
lib/config.ts   the only place models, fallbacks, teams, and limits are declared
lib/            stacks and constructs (see lib/CLAUDE.md)
lambda/         interceptor and cponaws-proxy handlers (see lambda/CLAUDE.md)
scripts/        smoke_test.py (live E2E), set-cponaws-key.sh, gwlib.py; diagrams/ (diagram generator)
docs/           architecture.md, rendered diagrams (*.en/*.ko .svg/.png), reference/
```

## Conventions
- Add or change a model, route, team, or limit in `lib/config.ts` only; rules, IAM resources, rate-limit entries, interceptor maps, and the dashboard are derived from it. A Bedrock model published after the `bedrock` target was last synchronized also needs a target sync after deploying (lib/CLAUDE.md).
- The CPonAWS key secret `llm-gateway/anthropic-api-key` and the workspace ID parameter `/llm-gateway/anthropic-workspace-id` live outside the stacks and are set with `scripts/set-cponaws-key.sh`: the 1P target validates the key when created, and a stack-owned secret would be deleted on rollback. Never commit the workspace ID; the repository is public.
- Do not read secret values through the shell; this environment blocks `get-secret-value`. Pass `{{resolve:secretsmanager:<id>:SecretString:<key>}}` through the aws-core `asm-exec` wrapper instead.
- `npm run build` does not exercise routing, policies, or Lambda code. After changing those, deploy and run the matching `uv run scripts/smoke_test.py --only <check>`.
- Diagrams are generated, not hand-edited: change `scripts/diagrams/build.py`, then run `scripts/diagrams/export.sh`, which re-exports both languages (README embeds the `.en` and `.ko` images in its two halves) and fails on a sublabel overflow, a geometry finding, or a `·` in the SVGs. The Mermaid copies in README and `docs/architecture.md` are hand-edited and identical in both halves.

## Key Commands
```bash
npm install
npm run build                                  # typecheck (tsc --noEmit)
npx cdk synth --quiet                          # F3018 warnings on GatewayRule are expected (lib/CLAUDE.md)
npx cdk diff --all                             # review before every deploy
npx cdk deploy --all                           # core stack, then the policy stack (ap-northeast-2)
npx cdk deploy --all -c enable1p=false -c guardrail=off -c policyMode=OFF   # benchmark only: no 1P, guardrail, or Cedar; a plain deploy restores them
uv run --with pytest --with boto3 pytest -q tests/interceptor               # interceptor unit tests
uv run scripts/smoke_test.py                   # live E2E against the deployed gateway; needs AWS credentials, small cost
uv run scripts/smoke_test.py --only gpt routing-evidence
uv run scripts/smoke_test.py --only kimi quota-headroom routing-evidence
bash scripts/diagrams/export.sh                # rebuild, export, verify diagrams; set PLAYWRIGHT_CORE and CHROMIUM
bash tests/run-all.sh                          # harness tests
```

Verify a change: `npm run build`
Run it before reporting a change done. A syntax-only check, or a command that failed to start, does not count; if it cannot run here, say which check you skipped and why.

---

## Auto-Sync Rules

Claude applies these while working; nothing runs automatically. Docs change in the same commit as the code they describe, so a reviewer sees both.

- Update `docs/architecture.md` when components or data flows change.
- Add an ADR (`/add-adr`) when a choice would be expensive to reverse or a future reader would ask why it was made.
- Add a module `CLAUDE.md` (`/add-module`) only for a module with rules or gotchas the code does not show.
- Write a runbook (`/add-runbook`) for a procedure someone will repeat under pressure: a deploy, a rollback, a migration.
- Update this file when a command, convention, or structure it describes changes.

### ADR Numbering
Find the highest number in `docs/decisions/ADR-*.md` and increment by 1.
Format: `ADR-NNN-concise-title.md`

## Implementation References
<!-- AUTO-MANAGED:references -->
Layer-by-layer implementation guides in `docs/reference/`. See [INDEX](docs/reference/INDEX.md).
- [IaC](docs/reference/iac.md)
- [Security](docs/reference/security.md)
- [Agent · LLM](docs/reference/agent-llm.md)
<!-- /AUTO-MANAGED -->
