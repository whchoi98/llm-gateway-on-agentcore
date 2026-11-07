# lib (CDK stacks and constructs)

## Role
Both stacks and their constructs. `config.ts` declares every model route and limit; nothing else hardcodes a model ID.

## Invariants and gotchas
- Gateway rules are raw `CfnResource` in CloudFormation casing, because aws-cdk-lib's `CfnGatewayRule` lacks `MatchModels`, `Model`, and `Fallback` and silently drops them. Synth prints F3018 warnings for them; confirm a rule change with `ListGatewayRules` after deploying.
- Keep rule construct IDs stable (`Route-<key>`, `Route-failover-drill`): CloudFormation creates the replacement before deleting the old rule, and two rules cannot share a priority.
- Rules match the model as the client sent it, before the interceptor runs, so a name that needs the fallback chain belongs in a route's `aliases`, not in an interceptor rewrite.
- Gateway children (targets, rules, rate limits) are created one at a time through `chain()`; add new ones to the chain.
- A rate-limit `*` entry gives each dimension value its own bucket, and a dimension the request does not carry skips the whole limit (`targetName` comes from the path, which `/inference` lacks). A bucket shared by all traffic therefore needs a claim with one value on every token, such as `$.context.jwt.token_use` (`access`; verified). Two rate limits cannot share the same dimension keys.
- Rate limits are enforced after the REQUEST interceptor (measured 2026-11-05): a request rejected with 429 `Rate limit exceeded` has already invoked the Lambda and ApplyGuardrail. No rate limit can therefore shield the interceptor or the ApplyGuardrail quota; a gateway-wide cap below the Cedar throttle (about 40/s) was tried and reverted for this reason.
- The `bedrock-runtime` connector's model catalog is a snapshot taken when the target is created or synchronized, and `cdk deploy` does not refresh it while the target's properties are unchanged. A Bedrock model published after that (Kimi K3.1, 2026-11-07) is missing from `GET /v1/models` and answers HTTP 200 with an `UnknownOperationException` body, which is not fallback-eligible. After adding such a model, run `aws bedrock-agentcore-control synchronize-gateway-targets --gateway-identifier <gateway-id> --target-id-list <bedrock target id>` and confirm with `uv run scripts/smoke_test.py --only models-list`.
- A provider inference target calls `GET /v1/models` when it is created and fails on a bad credential or a missing required header. That is why the CPonAWS target goes through the proxy Lambda, and why its key is a deploy prerequisite.
- Cedar reads request fields as `context.input.<field>`, and each read needs a `has` guard; without it validation rejects the forbid as "Overly Restrictive". InvokeModel carries the model in the URI, which Cedar cannot see, no policy covers the InvokeModel actions, and token rate limits do not count InvokeModel traffic, so the interceptor limits InvokeModel to the premium scope and must fail closed (see lambda/CLAUDE.md).
- Per-model `tpm` stays at or below 80% of the account's Global cross-Region TPM quota for the primary; `uv run scripts/smoke_test.py --only quota-headroom` checks the deployed limits against the live quotas. A first-byte timeout has no service default (none is enforced when unset), so every route with a fallback sets one. The rule schema keeps the timeout inside the fallback block, which needs a fallback target, so a route without a fallback (Kimi) has no timeout; `fallback` is optional in `ModelRoute` for that case, and the auto route and drills require one (`fallbackOf`).
- The GuardrailVersion description hashes `stack.resolve(props)`. Hashing raw props would include `${Token[...]}` strings, whose numbers change when constructs are added, and publish a new version on every deploy.
- Inference traffic metrics are in the `ApplicationSignals` namespace (`Service` = gateway ID); `AWS/Bedrock-AgentCore` holds only policy and identity metrics. Fallback counts come from the metric filter on `body.routing.reason`.

## Entry point
`llm-gateway-stack.ts`; its numbered sections follow the request path.
