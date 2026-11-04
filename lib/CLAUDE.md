# lib (CDK stacks and constructs)

## Role
Both stacks and their constructs. `config.ts` declares every model route and limit; nothing else hardcodes a model ID.

## Invariants and gotchas
- Gateway rules are raw `CfnResource` in CloudFormation casing, because aws-cdk-lib's `CfnGatewayRule` lacks `MatchModels`, `Model`, and `Fallback` and silently drops them. Synth prints F3018 warnings for them; confirm a rule change with `ListGatewayRules` after deploying.
- Keep rule construct IDs stable (`Route-<key>`, `Route-failover-drill`): CloudFormation creates the replacement before deleting the old rule, and two rules cannot share a priority.
- Rules match the model as the client sent it, before the interceptor runs, so a name that needs the fallback chain belongs in a route's `aliases`, not in an interceptor rewrite.
- Gateway children (targets, rules, rate limits) are created one at a time through `chain()`; add new ones to the chain.
- A provider inference target calls `GET /v1/models` when it is created and fails on a bad credential or a missing required header. That is why the CPonAWS target goes through the proxy Lambda, and why its key is a deploy prerequisite.
- Cedar reads request fields as `context.input.<field>`, and each read needs a `has` guard; without it validation rejects the forbid as "Overly Restrictive". InvokeModel carries the model in the URI, which Cedar cannot see, so premium checks for that path live in the interceptor.
- The GuardrailVersion description hashes `stack.resolve(props)`. Hashing raw props would include `${Token[...]}` strings, whose numbers change when constructs are added, and publish a new version on every deploy.
- Inference traffic metrics are in the `ApplicationSignals` namespace (`Service` = gateway ID); `AWS/Bedrock-AgentCore` holds only policy and identity metrics. Fallback counts come from the metric filter on `body.routing.reason`.

## Entry point
`llm-gateway-stack.ts`; its numbered sections follow the request path.
