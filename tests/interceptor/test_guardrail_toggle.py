"""Interceptor guardrail switch (GUARDRAIL_ENABLED), used by the benchmark deploy flag `-c guardrail=off`.

Run: uv run --with pytest --with boto3 pytest -q tests/interceptor
"""
import importlib.util
import os
from pathlib import Path

import pytest

INDEX = Path(__file__).resolve().parents[2] / "lambda" / "interceptor" / "index.py"


def load_interceptor(monkeypatch, **env):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    monkeypatch.setenv("GUARDRAIL_ID", "gr-test")
    monkeypatch.setenv("GUARDRAIL_VERSION", "1")
    monkeypatch.delenv("GUARDRAIL_ENABLED", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("interceptor_index", INDEX)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingBedrock:
    def __init__(self):
        self.calls = 0

    def apply_guardrail(self, **_):
        self.calls += 1
        return {"action": "NONE"}


def test_disabled_guardrail_passes_without_calling_bedrock(monkeypatch):
    mod = load_interceptor(monkeypatch, GUARDRAIL_ENABLED="false")
    bedrock = RecordingBedrock()
    monkeypatch.setattr(mod, "_bedrock", bedrock)
    assert mod._apply_guardrail("내 주민등록번호는 900101-1234567 입니다") == (False, "", 0.0, False)
    assert bedrock.calls == 0


@pytest.mark.parametrize("env", [{}, {"GUARDRAIL_ENABLED": "true"}])
def test_guardrail_is_called_by_default_and_when_enabled(monkeypatch, env):
    mod = load_interceptor(monkeypatch, **env)
    bedrock = RecordingBedrock()
    monkeypatch.setattr(mod, "_bedrock", bedrock)
    blocked, _, _, error = mod._apply_guardrail("hello")
    assert (blocked, error) == (False, False)
    assert bedrock.calls == 1
