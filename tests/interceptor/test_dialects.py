"""Interceptor dialect checks: which API shape each model family is served on.

Run: uv run --with pytest --with boto3 pytest -q tests/interceptor
"""
import base64
import importlib.util
import json
from pathlib import Path

import pytest

INDEX = Path(__file__).resolve().parents[2] / "lambda" / "interceptor" / "index.py"

# Shaped like the maps lib/constructs/guardrail-interceptor.ts derives from lib/config.ts.
FAMILIES = {"claude-sonnet-5-5": "claude", "gpt-6-luna": "gpt", "kimi-k3.1": "kimi"}
CANONICAL = {
    "claude-sonnet-5-5": "claude-sonnet-5-5",
    "gpt-6-luna": "gpt-6-luna",
    "kimi-k3.1": "kimi-k3.1",
    "global.moonshotai.kimi-k3.1": "kimi-k3.1",
    "moonshotai.kimi-k3.1": "kimi-k3.1",
}


@pytest.fixture
def interceptor(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    monkeypatch.setenv("GUARDRAIL_ID", "gr-test")
    monkeypatch.setenv("GUARDRAIL_VERSION", "1")
    monkeypatch.setenv("GUARDRAIL_ENABLED", "false")  # no ApplyGuardrail call from unit tests
    monkeypatch.setenv("MODEL_FAMILIES", json.dumps(FAMILIES))
    monkeypatch.setenv("CANONICAL_MODELS", json.dumps(CANONICAL))
    spec = importlib.util.spec_from_file_location("interceptor_index", INDEX)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call(mod, path: str, body: dict) -> dict:
    event = {"http": {"gatewayRequest": {
        "path": path, "headers": {}, "body": base64.b64encode(json.dumps(body).encode()).decode(),
    }}}
    return mod.lambda_handler(event, None)


def denial(resp: dict):
    """(status, denial kind, decoded body) of a short-circuit response, or None when it passes."""
    short = resp["http"].get("transformedGatewayResponse")
    if not short:
        return None
    return short["statusCode"], short["headers"]["x-llm-gateway-denied"], json.loads(base64.b64decode(short["body"]))


MESSAGES = [{"role": "user", "content": "hi"}]


@pytest.mark.parametrize("model", ["kimi-k3.1", "global.moonshotai.kimi-k3.1", "bedrock/moonshotai.kimi-k3.1"])
def test_kimi_on_messages_api_gets_openai_guidance(interceptor, model):
    status, kind, body = denial(call(interceptor, "/inference/v1/messages", {"model": model, "max_tokens": 16, "messages": MESSAGES}))
    assert (status, kind) == (400, "unsupported_dialect")
    assert "kimi-k3.1" in body["error"]["message"] and "OpenAI" in body["error"]["message"]


@pytest.mark.parametrize("path, body", [
    ("/inference/v1/chat/completions", {"model": "kimi-k3.1", "messages": MESSAGES}),
    ("/inference/v1/responses", {"model": "global.moonshotai.kimi-k3.1", "input": "hi"}),
])
def test_kimi_on_openai_apis_passes(interceptor, path, body):
    assert denial(call(interceptor, path, body)) is None


def test_gpt_on_messages_api_still_denied(interceptor):
    status, kind, _ = denial(call(interceptor, "/inference/v1/messages", {"model": "gpt-6-luna", "max_tokens": 16, "messages": MESSAGES}))
    assert (status, kind) == (400, "unsupported_dialect")


def test_claude_on_chat_completions_still_denied(interceptor):
    status, kind, body = denial(call(interceptor, "/inference/v1/chat/completions", {"model": "claude-sonnet-5-5", "messages": MESSAGES}))
    assert (status, kind) == (400, "unsupported_dialect")
    assert "Anthropic Messages" in body["error"]["message"]


def test_claude_on_messages_api_passes(interceptor):
    assert denial(call(interceptor, "/inference/v1/messages", {"model": "claude-sonnet-5-5", "max_tokens": 16, "messages": MESSAGES})) is None
