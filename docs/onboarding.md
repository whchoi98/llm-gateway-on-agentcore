# Developer Onboarding

## Quick Start

### 1. Prerequisites
- [ ] Node.js 22+ and npm (the CDK app runs through `tsx`)
- [ ] AWS CLI v2 with credentials for the target account; the stacks deploy to ap-northeast-2
- [ ] CDK bootstrap in ap-northeast-2 (`npx cdk bootstrap aws://<account-id>/ap-northeast-2`)
- [ ] `uv`, for `scripts/smoke_test.py`
- [ ] A Claude Platform on AWS API key and a Seoul workspace ID, for the Claude fallback
- [ ] Repository access granted
- [ ] Environment variables configured (see .env.example)

### 2. Setup
```bash
bash scripts/setup.sh                 # checks tools, runs npm install, installs the commit-msg hook
./scripts/set-cponaws-key.sh          # run in your own terminal: verifies the CPonAWS key, then stores it
npx cdk diff --all                    # review what will change
npx cdk deploy --all                  # core stack, then the Cedar policy stack
```

Without a CPonAWS key yet, deploy with `npx cdk deploy --all -c enable1p=false`, which leaves out the Claude fallback.

### 3. Verify
```bash
npm run build                         # typecheck
bash tests/run-all.sh                 # harness tests
uv run scripts/smoke_test.py          # live E2E against the deployed gateway
```

## Project Overview
- Read `CLAUDE.md` for project context and conventions
- Read `docs/architecture.md` for system design
- Review `docs/decisions/` for architectural decisions

## Development Workflow
- Add or change models, fallbacks, teams, and limits in `lib/config.ts`; the stacks derive everything else from it.
- Run `npx cdk diff --all` before every deploy.
- After a routing, policy, or Lambda change, deploy and run the matching check, for example `uv run scripts/smoke_test.py --only failover routing-evidence`.
- The commit-msg hook from `scripts/install-hooks.sh` removes Co-Authored-By lines.

## Key Concepts
- **3P / 1P**: 3P is Claude or GPT on Amazon Bedrock; 1P is Claude Platform on AWS (CPonAWS), Anthropic's API billed through AWS.
- **Primary and fallback**: each model has a Bedrock Global CRIS primary and one fallback destination (CPonAWS for Claude, Bedrock Mantle us-east-1 for GPT), declared in `lib/config.ts`.
- **Failover drills**: `claude-haiku-5-5-failover-drill` and `gpt-6-luna-failover-drill` always fail over, so they test the fallback path on demand.
- **Who served a request**: Claude responses with an `id` starting `msg_bdrk_` came from Bedrock; a GPT response `model` of `openai.*` came from Mantle. The gateway logs record every fallback as `body.routing.reason = servedViaFallbackHop:N`.

## Troubleshooting
- **The CPonAWS target fails with HTTP 401 or 400 during deploy**: the target lists models when it is created, so the key secret must already hold a working key. Run `./scripts/set-cponaws-key.sh` and deploy again.
- **Synth prints F3018 warnings for GatewayRule**: expected; see `lib/CLAUDE.md`.
- **OpenAI SDK requests for Claude, or Anthropic SDK requests for GPT, return 400**: Bedrock serves each family in one API schema; use the SDK the error message names.
- **Rate-limit tests pass more requests than the limit**: limits are token buckets, so a burst can exceed the per-minute number briefly.
- **Gateway routing logs arrive late**: vended logs take 20 to 80 seconds and are best effort; use them for trends, not per-request accounting.

## Resources
- `docs/architecture.html` (Korean) and `docs/architecture.en.html` (English): rendered architecture, request-flow, fallback-sequence, and deploy-order diagrams
- `docs/reference/INDEX.md`: implementation reference by layer
- Amazon Bedrock AgentCore Developer Guide: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/
- Claude Platform on AWS User Guide: https://docs.aws.amazon.com/claude-platform/latest/userguide/
