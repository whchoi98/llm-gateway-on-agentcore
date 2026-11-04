# lambda (gateway Lambdas)

## Role
`interceptor/` is the gateway REQUEST interceptor; `cponaws-proxy/` streams Claude fallback traffic to Claude Platform on AWS. Each directory is deployed as-is as a Lambda asset.

## Invariants and gotchas
- The interceptor runs after rule matching and before the Cedar policy. Its input is the `http` payload with a base64 body; it can change the body and headers but not the path or method, and returning `transformedGatewayResponse` answers without calling a target.
- Only `claude-auto` rewrites `model`, to a Bedrock ID that the auto route serves without a pinned model. Rewriting a static alias here would skip its rule and fallback chain.
- The gateway does not pass headers from a short-circuit response (such as `x-amzn-errortype`) to the caller, so Bedrock-dialect errors also put the error code in the body's `__type`, which AWS SDKs read.
- Guardrail errors follow `GUARDRAIL_FAIL_MODE` (default `open`, with an alarm); `closed` blocks every request while the guardrail is unavailable.
- The proxy exists only because CPonAWS needs `anthropic-workspace-id` on every request and a gateway target cannot add static headers. Keep its path allowlist; the Function URL uses `AWS_IAM`, so only the gateway role can call it.
- Keep responses streaming end to end: the proxy must not buffer, and the gateway has no RESPONSE interceptor because HTTP interceptors buffer the whole response.
