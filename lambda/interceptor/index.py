"""AgentCore Gateway REQUEST interceptor for the LLM Gateway.

Ordering (verified on this gateway): routing rules match the `model` the client
sent, BEFORE this interceptor runs; a rewritten `model` is then what the
matched route dispatches when its primary does not pin a model. So static
aliases live in the rules' matchModels, and only dynamic routing happens here.

Responsibilities
1. Dynamic routing — `claude-auto` is rewritten to a Bedrock model chosen by
   prompt size (Opus only for premium callers).
2. Input guardrail — the latest user turn is checked with Bedrock
   ApplyGuardrail. Guardrails-in-Policy is not available in ap-northeast-2, and
   doing it here applies the same check to the 3P and the 1P path.
3. Guard rails the gateway cannot express:
   - OpenAI-dialect requests for Claude get a clear 400 (Bedrock serves Claude
     only in the Anthropic Messages / InvokeModel schema).
   - InvokeModel paths (`/model/{modelId}/invoke[-with-response-stream]`):
     premium-only models and the standard output-token cap. The model ID is in
     the URI, where Cedar `context.input` cannot see it, and no Cedar policy
     covers these actions, so this check is the only control and fails closed:
     the ID is URL-decoded and an ARN is reduced to the model it names, any
     other `/model/` operation is refused, and so is a model the gateway does
     not declare (on every dialect).
4. Per-team usage metrics — CloudWatch Embedded Metric Format (EMF) records.

Inference targets use the `http` interceptor payload: the body is a base64 string.
"""

import base64
import json
import logging
import os
import time
import urllib.parse

import boto3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

GUARDRAIL_ID = os.environ["GUARDRAIL_ID"]
GUARDRAIL_VERSION = os.environ["GUARDRAIL_VERSION"]
GUARDRAIL_FAIL_MODE = os.environ.get("GUARDRAIL_FAIL_MODE", "open")
GUARDRAIL_MAX_CHARS = int(os.environ.get("GUARDRAIL_MAX_CHARS", "20000"))
METRICS_NAMESPACE = os.environ.get("METRICS_NAMESPACE", "LlmGateway")
CANONICAL = json.loads(os.environ.get("CANONICAL_MODELS", "{}"))
FAMILIES = json.loads(os.environ.get("MODEL_FAMILIES", "{}"))
PREMIUM_MODELS = set(json.loads(os.environ.get("PREMIUM_MODELS", "[]")))
AUTO_ALIAS = os.environ.get("AUTO_MODEL_ALIAS", "claude-auto")
AUTO_MODELS = json.loads(os.environ.get("AUTO_MODELS", "{}"))
TEAM_CLIENTS = json.loads(os.environ.get("TEAM_CLIENTS", "{}"))
PREMIUM_SCOPE = os.environ.get("PREMIUM_SCOPE", "llm-gateway/premium")
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "16384"))
INVOKE_OPERATIONS = ("invoke", "invoke-with-response-stream")
TOKEN_FIELDS = ("max_tokens", "max_completion_tokens", "max_output_tokens")

# Fail fast: a slow guardrail call must not stall every LLM request.
_bedrock = boto3.client(
    "bedrock-runtime",
    config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 2, "mode": "standard"}),
)

PASS_THROUGH = {"interceptorOutputVersion": "1.0", "http": {}}


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
def _dialect(path: str) -> str:
    if path.endswith("/v1/messages"):
        return "anthropic"
    if path.endswith("/v1/chat/completions") or path.endswith("/v1/responses"):
        return "openai"
    if "/model/" in path:
        return "bedrock"  # every /model/ path is checked; _path_model refuses non-invoke operations
    return "other"


def _jwt_claims(headers: dict) -> dict:
    """Decode (without verifying) the bearer token's claims.

    The gateway's CUSTOM_JWT authorizer has already validated the signature
    before the interceptor runs; claims are only used for attribution.
    """
    auth = next((v for k, v in (headers or {}).items() if k.lower() == "authorization"), "")
    token = auth.split(" ", 1)[1] if auth.lower().startswith("bearer ") else auth
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError):
        return {}


def _text_of(content) -> str:
    """Flatten Anthropic/OpenAI content (string or list of blocks) to text."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict):
            if block.get("type") in ("text", "input_text") and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif block.get("type") == "tool_result":
                parts.append(_text_of(block.get("content")))
    return "\n".join(p for p in parts if p)


def _latest_user_text(body: dict) -> str:
    """Only the newest user turn is checked, so one flagged message earlier in a
    conversation does not block every later turn (and cost stays per-turn)."""
    # Messages / Chat Completions use `messages`; the Responses API uses `input`
    # (a string, or a list of items shaped like messages).
    turns = body.get("messages")
    if turns is None:
        turns = body.get("input")
    if isinstance(turns, str):
        return turns[:GUARDRAIL_MAX_CHARS]
    if isinstance(turns, list):
        for turn in reversed(turns):
            if isinstance(turn, dict) and turn.get("role") == "user":
                return _text_of(turn.get("content"))[:GUARDRAIL_MAX_CHARS]
    return ""


def _auto_model(body: dict, premium: bool) -> str:
    size = len(json.dumps(body.get("messages", body.get("input", ""))))
    if size >= 20_000 and premium:
        return AUTO_MODELS["large"]
    if size >= 2_000:
        return AUTO_MODELS["medium"]
    return AUTO_MODELS["small"]


def _path_model(path: str):
    """Model ID of `/model/{modelId}/{operation}`, or None when the operation is not InvokeModel.

    SDKs percent-encode the ID (an ARN becomes `arn%3Aaws%3A...%2F...`) and a client can
    encode it twice, so decode until it stops changing. An ARN is reduced to the ID after
    its last "/", so `...:inference-profile/global.anthropic.claude-opus-5-5` is checked as
    the Opus profile it names.
    """
    model_id, _, operation = path.split("/model/", 1)[1].rpartition("/")
    if operation not in INVOKE_OPERATIONS or not model_id:
        return None
    for _ in range(3):
        decoded = urllib.parse.unquote(model_id)
        if decoded == model_id:
            break
        model_id = decoded
    else:
        return None  # still changing after three passes
    return model_id.rsplit("/", 1)[-1] if model_id.startswith("arn:") else model_id


def _over_cap(value) -> bool:
    """True when an output-token field exceeds the standard cap or is not a plain number."""
    if value is None:
        return False
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return True
    return value > MAX_OUTPUT_TOKENS


def _parse_body(encoded):
    if not encoded:
        return None
    try:
        body = json.loads(base64.b64decode(encoded))
    except (ValueError, TypeError):
        return None
    return body if isinstance(body, dict) else None


def _canonical(model) -> str:
    if not isinstance(model, str):
        return "unknown"
    bare = model.split("/", 1)[1] if "/" in model else model  # strip a target prefix ("bedrock/", "cponaws/")
    if bare.startswith("arn:"):
        bare = bare.rsplit("/", 1)[-1]  # GET /v1/models also lists inference-profile ARNs
    return CANONICAL.get(bare, bare)


def _deny(dialect: str, status: int, kind: str, message: str) -> dict:
    """Short-circuit response in the caller's API dialect."""
    headers = {"x-llm-gateway-denied": kind}
    if dialect == "anthropic":
        etype = "permission_error" if status == 403 else "invalid_request_error"
        body = {"type": "error", "error": {"type": etype, "message": message}}
    elif dialect == "bedrock":
        # The gateway does not relay x-amzn-errortype from a short-circuit, so the
        # error code also goes in `__type`, which AWS SDKs read to raise typed errors.
        error_type = "AccessDeniedException" if status == 403 else "ValidationException"
        body = {"__type": error_type, "message": message}
        headers["x-amzn-errortype"] = error_type
    else:
        body = {"error": {"message": message, "type": "invalid_request_error", "code": kind}}
    return {
        "interceptorOutputVersion": "1.0",
        "http": {
            "transformedGatewayResponse": {
                "statusCode": status,
                "contentType": "application/json",
                "headers": headers,
                "body": base64.b64encode(json.dumps(body).encode()).decode(),
            }
        },
    }


# ---------------------------------------------------------------------------
# Guardrail
# ---------------------------------------------------------------------------
def _apply_guardrail(text: str):
    """Returns (blocked: bool, reason: str, latency_ms: float, error: bool)."""
    if not text.strip():
        return False, "", 0.0, False
    started = time.perf_counter()
    try:
        resp = _bedrock.apply_guardrail(
            guardrailIdentifier=GUARDRAIL_ID,
            guardrailVersion=GUARDRAIL_VERSION,
            source="INPUT",
            content=[{"text": {"text": text}}],
        )
    except Exception:  # noqa: BLE001 — fail mode decides, error is logged + metered
        logger.exception("ApplyGuardrail failed (fail mode: %s)", GUARDRAIL_FAIL_MODE)
        latency = (time.perf_counter() - started) * 1000
        return GUARDRAIL_FAIL_MODE == "closed", "guardrail unavailable", latency, True
    latency = (time.perf_counter() - started) * 1000
    if resp.get("action") != "GUARDRAIL_INTERVENED":
        return False, "", latency, False
    reasons = []
    for assessment in resp.get("assessments", []):
        for f in assessment.get("contentPolicy", {}).get("filters", []):
            if f.get("action") == "BLOCKED":
                reasons.append(f"content:{f.get('type')}")
        for e in assessment.get("sensitiveInformationPolicy", {}).get("piiEntities", []):
            if e.get("action") == "BLOCKED":
                reasons.append(f"pii:{e.get('type')}")
        for r in assessment.get("sensitiveInformationPolicy", {}).get("regexes", []):
            if r.get("action") == "BLOCKED":
                reasons.append(f"regex:{r.get('name')}")
    return True, ",".join(reasons) or "policy", latency, False


# ---------------------------------------------------------------------------
# Metrics (EMF)
# ---------------------------------------------------------------------------
def _emit(team: str, model: str, dialect: str, blocked: bool, guardrail_ms: float, guardrail_error: bool, extra: dict):
    record = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": METRICS_NAMESPACE,
                    "Dimensions": [["Team"], ["Model"], ["Team", "Model"]],
                    "Metrics": [
                        {"Name": "Requests", "Unit": "Count"},
                        {"Name": "GuardrailBlocked", "Unit": "Count"},
                        {"Name": "GuardrailErrors", "Unit": "Count"},
                        {"Name": "GuardrailLatency", "Unit": "Milliseconds"},
                    ],
                }
            ],
        },
        "Team": team,
        "Model": model or "unknown",
        "Dialect": dialect,
        "Requests": 1,
        "GuardrailBlocked": 1 if blocked else 0,
        "GuardrailErrors": 1 if guardrail_error else 0,
        "GuardrailLatency": round(guardrail_ms, 1),
        **extra,
    }
    print(json.dumps(record, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
def lambda_handler(event, context):
    request = (event.get("http") or {}).get("gatewayRequest") or {}
    path = request.get("path") or ""
    dialect = _dialect(path)
    if dialect == "other":
        return PASS_THROUGH  # e.g. GET /v1/models
    body = _parse_body(request.get("body"))
    fields = body or {}

    claims = _jwt_claims(request.get("headers") or {})
    client_id = claims.get("client_id", "unknown")
    team = TEAM_CLIENTS.get(client_id, client_id)
    premium = PREMIUM_SCOPE in str(claims.get("scope", ""))

    # InvokeModel carries the model in the URI path (read-only for interceptors).
    requested = _path_model(path) if dialect == "bedrock" else fields.get("model")
    dispatched = _auto_model(body, premium) if requested == AUTO_ALIAS and dialect != "bedrock" else requested
    model = _canonical(dispatched)

    request_id = ""
    if context is not None and getattr(context, "client_context", None) is not None:
        request_id = (context.client_context.custom or {}).get("REQUEST_ID", "")
    log_fields = {
        "requestedModel": requested,
        "path": path,
        "stream": bool(fields.get("stream")),
        "maxTokens": next((fields[f] for f in TOKEN_FIELDS if f in fields), None),
        "gatewayRequestId": request_id,
    }

    denial = None
    family = FAMILIES.get(model)
    if family is None:
        model = "unknown"  # never a caller-chosen string as a metric dimension
    if body is None:
        denial = (400, "invalid_request", "The request body must be a JSON object.")
    elif dialect == "bedrock" and requested is None:
        denial = (400, "unsupported_operation",
                  "Only InvokeModel and InvokeModelWithResponseStream "
                  "(POST /inference/model/{modelId}/invoke[-with-response-stream]) are served on this gateway.")
    elif dialect == "bedrock" and requested == AUTO_ALIAS:
        denial = (400, "unsupported_model",
                  f"{AUTO_ALIAS} is served through the Anthropic Messages API (POST /inference/v1/messages).")
    elif family is None:
        denial = (400, "unknown_model", f"Model {str(requested)[:120]!r} is not served by this gateway.")
    elif dialect == "openai" and family == "claude":
        denial = (400, "unsupported_dialect",
                  "Claude models are served through the Anthropic Messages API on this gateway "
                  "(POST /inference/v1/messages, e.g. the Anthropic SDK) or Bedrock InvokeModel. "
                  "Bedrock does not serve Claude in the OpenAI Chat Completions schema.")
    elif dialect == "anthropic" and family == "gpt":
        denial = (400, "unsupported_dialect",
                  "GPT models are served through the OpenAI APIs on this gateway "
                  "(POST /inference/v1/chat/completions or /inference/v1/responses, e.g. the OpenAI SDK) "
                  "or Bedrock InvokeModel with a Chat Completions body.")
    elif dialect == "bedrock" and model in PREMIUM_MODELS and not premium:
        denial = (403, "premium_required", f"{model} requires the {PREMIUM_SCOPE} scope.")
    elif dialect == "bedrock" and not premium and any(_over_cap(fields.get(f)) for f in TOKEN_FIELDS):
        denial = (403, "max_tokens_exceeded",
                  f"Output tokens above {MAX_OUTPUT_TOKENS} require the {PREMIUM_SCOPE} scope.")
    if denial:
        _emit(team, model, dialect, False, 0.0, False, {**log_fields, "denied": denial[1]})
        return _deny(dialect, *denial)

    blocked, reason, guardrail_ms, guardrail_error = _apply_guardrail(_latest_user_text(body))
    _emit(team, model, dialect, blocked, guardrail_ms, guardrail_error, {**log_fields, "guardrailReason": reason})
    if blocked:
        return _deny(dialect, 400, "content_policy_violation",
                     f"Request blocked by the LLM Gateway input guardrail ({reason}).")

    if dispatched != requested:
        body["model"] = dispatched
        return {
            "interceptorOutputVersion": "1.0",
            "http": {"transformedGatewayRequest": {"body": base64.b64encode(json.dumps(body).encode()).decode()}},
        }
    return PASS_THROUGH
