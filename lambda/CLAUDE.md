# lambda (gateway Lambdas)

## Role
`interceptor/` is the gateway REQUEST interceptor; `cponaws-proxy/` streams Claude fallback traffic to Claude Platform on AWS. Each directory is deployed as-is as a Lambda asset.

## Invariants and gotchas
- The interceptor runs after rule matching and before the Cedar policy. Its input is the `http` payload with a base64 body; it can change the body and headers but not the path or method, and returning `transformedGatewayResponse` answers without calling a target.
- The interceptor is the only control on InvokeModel paths: gateway token rate limits count only `/v1/messages`, `/v1/chat/completions` and `/v1/responses`, and Cedar cannot see a model ID in the URI. It therefore allows InvokeModel for the `premium` scope only and fails closed: it URL-decodes the model ID in `/model/{id}/...`, reduces an ARN to the model it names, refuses any `/model/` operation other than `invoke` and `invoke-with-response-stream`, and refuses a model missing from `MODEL_FAMILIES` on every dialect. A new rule-only alias (like `claude-experiment` or a failover drill) must be added to `MODEL_FAMILIES`, or the interceptor refuses it.
- The bedrock-runtime connector passes Anthropic `metadata.user_id` to Bedrock request metadata, which allows only `[A-Za-z0-9 :_@$#=/+,.-]` and 256 characters and otherwise answers 400. Claude Code sends a JSON string there, so the interceptor rewrites `user_id` on every Messages request; keep that rewrite or Claude Code stops working.
- Only `claude-auto` rewrites `model`, to a Bedrock ID that the auto route serves without a pinned model. Rewriting a static alias here would skip its rule and fallback chain.
- The gateway does not pass headers from a short-circuit response (such as `x-amzn-errortype`) to the caller, so Bedrock-dialect errors also put the error code in the body's `__type`, which AWS SDKs read.
- Guardrail errors follow `GUARDRAIL_FAIL_MODE` (default `open`, with an alarm); `closed` blocks every request while the guardrail is unavailable.
- The proxy exists only because CPonAWS needs `anthropic-workspace-id` on every request and a gateway target cannot add static headers. Keep its path allowlist; the Function URL uses `AWS_IAM`, so only the gateway role can call it.
- Keep responses streaming end to end: the proxy must not buffer, and the gateway has no RESPONSE interceptor because HTTP interceptors buffer the whole response.
