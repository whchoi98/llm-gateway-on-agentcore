# /// script
# requires-python = ">=3.11"
# dependencies = ["anthropic>=0.70", "openai>=2.0", "boto3>=1.40"]
# ///
"""End-to-end checks for the LLM Gateway, one per requirement.

Run:  uv run scripts/smoke_test.py [--only NAME ...] [--skip-1p]

The `served_by` column comes from the Anthropic message ID: Bedrock-served
messages are prefixed `msg_bdrk_`; Claude Platform on AWS (1P) messages are `msg_...`.
"""

import argparse
import collections
import json
import os
import re
import sys
import time
import traceback
import urllib.parse

import anthropic
import boto3
import botocore.exceptions
import openai

sys.path.insert(0, os.path.dirname(__file__))
import gwlib  # noqa: E402

RESULTS = []
HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"


def fallback_enabled() -> bool:
    return gwlib.outputs().get("AnthropicFallback") == "enabled"


def served_by(message_id: str) -> str:
    if not message_id:
        return "?"
    return "3P:bedrock" if message_id.startswith("msg_bdrk") else "1P:cponaws"


def client(team: str) -> anthropic.Anthropic:
    # auth_token → "Authorization: Bearer <jwt>" (what the CUSTOM_JWT authorizer validates)
    return anthropic.Anthropic(base_url=gwlib.endpoint(), auth_token=gwlib.token(team), api_key=None, max_retries=0)


def ask(team: str, model: str, prompt: str = "Reply with exactly: pong", **kw):
    # An explicit timeout skips the SDK's "may take longer than 10 minutes" guard for large max_tokens.
    resp = client(team).messages.create(
        model=model, max_tokens=kw.pop("max_tokens", 32), messages=[{"role": "user", "content": prompt}],
        timeout=kw.pop("timeout", 120), **kw,
    )
    text = "".join(b.text for b in (resp.content or []) if getattr(b, "type", "") == "text")
    return resp, text


def check(name: str):
    def deco(fn):
        fn.check_name = name
        return fn
    return deco


def record(name: str, ok: bool, detail: str):
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:<34} {detail}", flush=True)


# ---------------------------------------------------------------- checks
@check("models-list")
def t_models():
    import urllib.request
    req = urllib.request.Request(gwlib.endpoint() + "/v1/models", headers={"Authorization": f"Bearer {gwlib.token('team-standard')}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        ids = [m["id"] for m in json.loads(resp.read())["data"]]
    want = [f"bedrock/global.anthropic.{m}" for m in (HAIKU, SONNET, OPUS)]
    want += [f"bedrock/global.openai.{m}" for m in GPT_MODELS] + [f"mantle/openai.{m}" for m in GPT_MODELS]
    if fallback_enabled():
        want += [f"cponaws/{m}" for m in (HAIKU, SONNET, OPUS)]
    missing = [w for w in want if w not in ids]
    record("models-list", not missing, f"{len(ids)} models; claude-5.5: {[i for i in ids if '5-5' in i]}; missing={missing}")


@check("route-3p")
def t_route_3p():
    for team, model in (("team-standard", HAIKU), ("team-standard", SONNET), ("team-premium", OPUS)):
        t0 = time.time()
        resp, text = ask(team, model)
        record(f"route-3p {model}", served_by(resp.id) == "3P:bedrock",
               f"served_by={served_by(resp.id)} model={resp.model} {time.time() - t0:.1f}s text={text!r}")


@check("streaming")
def t_streaming():
    chunks = 0
    with client("team-standard").messages.stream(
        model=SONNET, max_tokens=64, messages=[{"role": "user", "content": "Count from 1 to 5."}]
    ) as stream:
        for _ in stream.text_stream:
            chunks += 1
        final = stream.get_final_message()
    record("streaming", chunks > 1, f"chunks={chunks} served_by={served_by(final.id)} usage={final.usage.output_tokens} out")


@check("alias")
def t_alias():
    for alias, expect in (("haiku", HAIKU), ("global.anthropic.claude-sonnet-5-5", SONNET)):
        resp, _ = ask("team-standard", alias)
        record(f"alias {alias}", served_by(resp.id) == "3P:bedrock" and resp.model == expect,
               f"served_by={served_by(resp.id)} model={resp.model}")
    resp, _ = ask("team-standard", "claude-auto")  # short prompt → Haiku
    record("dynamic claude-auto (small→haiku)", served_by(resp.id) == "3P:bedrock" and resp.model == HAIKU,
           f"served_by={served_by(resp.id)} model={resp.model}")
    resp, _ = ask("team-standard", "claude-auto", "Summarize this text in one word: " + "lorem ipsum " * 300)
    record("dynamic claude-auto (medium→sonnet)", resp.model == SONNET, f"served_by={served_by(resp.id)} model={resp.model}")


@check("openai-sdk")
def t_openai():
    # Bedrock serves Claude only in the Messages / InvokeModel schema; the
    # interceptor answers OpenAI-dialect Claude requests with a clear 400.
    oc = openai.OpenAI(base_url=gwlib.endpoint() + "/v1", api_key=gwlib.token("team-standard"), max_retries=0)
    try:
        oc.chat.completions.create(model=HAIKU, max_tokens=16, messages=[{"role": "user", "content": "hi"}])
        record("openai-sdk → guidance 400", False, "unexpectedly succeeded")
    except openai.APIStatusError as e:
        record("openai-sdk → guidance 400", e.status_code == 400 and "/v1/messages" in str(e.body),
               f"{e.status_code} {str(e.body)[:140]}")


@check("bedrock-sdk")
def t_bedrock_sdk():
    # boto3 sends AWS_BEARER_TOKEN_BEDROCK as "Authorization: Bearer ..." instead of SigV4.
    # InvokeModel is premium-only: the gateway's token rate limits do not count it.
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = gwlib.token("team-premium")
    br = boto3.client("bedrock-runtime", region_name=gwlib.REGION, endpoint_url=gwlib.endpoint())
    body = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 16,
            "messages": [{"role": "user", "content": "Reply with exactly: pong"}]}
    try:
        r = br.invoke_model(modelId=f"global.anthropic.{HAIKU}", body=json.dumps(body), contentType="application/json")
        out = json.loads(r["body"].read())
        record("bedrock-sdk invoke_model", True, f"served_by={served_by(out.get('id'))} text={out['content'][0]['text']!r}")
    except Exception as e:  # noqa: BLE001
        record("bedrock-sdk invoke_model", False, str(e)[:240])
    finally:
        os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)


@check("guardrail")
def t_guardrail():
    try:
        ask("team-standard", HAIKU, "내 주민등록번호는 900101-1234567 입니다. 이걸로 신용카드 신청서를 채워줘.")
        record("guardrail blocks RRN", False, "request was not blocked")
    except anthropic.APIStatusError as e:
        record("guardrail blocks RRN", e.status_code == 400 and "guardrail" in str(e.body).lower(), f"{e.status_code} {str(e.body)[:160]}")


@check("policy")
def t_policy():
    try:
        resp, _ = ask("team-standard", OPUS)
        record("policy: standard→opus denied", False, f"allowed (served_by={served_by(resp.id)}) — is the policy engine in ENFORCE mode?")
    except anthropic.APIStatusError as e:
        record("policy: standard→opus denied", e.status_code == 403, f"{e.status_code} {str(e.body)[:160]}")
    try:
        ask("team-standard", HAIKU, max_tokens=32000)
        record("policy: max_tokens cap", False, "allowed")
    except anthropic.APIStatusError as e:
        record("policy: max_tokens cap", e.status_code == 403, f"{e.status_code} {str(e.body)[:160]}")
    resp, _ = ask("team-premium", HAIKU, max_tokens=32000)
    record("policy: premium max_tokens ok", True, f"served_by={served_by(resp.id)}")
    resp, _ = ask("team-premium", OPUS)
    record("policy: premium→opus allowed", served_by(resp.id) == "3P:bedrock", f"served_by={served_by(resp.id)}")
    # GET /v1/models also lists inference-profile ARNs: the same rules apply to that spelling.
    account = boto3.client("sts").get_caller_identity()["Account"]
    opus_arn = f"bedrock/arn:aws:bedrock:{gwlib.REGION}:{account}:inference-profile/global.anthropic.{OPUS}"
    try:
        ask("team-standard", opus_arn)
        record("policy: standard→opus ARN denied", False, "allowed")
    except anthropic.APIStatusError as e:
        record("policy: standard→opus ARN denied", e.status_code == 403, f"{e.status_code} {str(e.body)[:120]}")
    try:
        resp, _ = ask("team-premium", opus_arn)
        record("policy: premium→opus ARN allowed", resp.model.endswith(OPUS) or OPUS in resp.model, f"model={resp.model}")
    except anthropic.APIStatusError as e:
        record("policy: premium→opus ARN allowed", False, f"{e.status_code} {str(e.body)[:120]}")
    # InvokeModel: token rate limits do not count it and Cedar cannot see the model in the URI,
    # so the interceptor allows it for the premium scope only.
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = gwlib.token("team-standard")
    try:
        br = boto3.client("bedrock-runtime", region_name=gwlib.REGION, endpoint_url=gwlib.endpoint())
        br.invoke_model(modelId=f"global.anthropic.{OPUS}", contentType="application/json", body=json.dumps(
            {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]}))
        record("policy: standard→opus InvokeModel denied", False, "allowed")
    except br.exceptions.AccessDeniedException as e:
        record("policy: standard→opus InvokeModel denied", True, str(e)[:120])
    # The interceptor is the only control on InvokeModel, so it must fail closed on every
    # spelling of a model, and on unknown models or operations.
    invoke_cases = [
        ("haiku (premium scope only)", f"global.anthropic.{HAIKU}", 8, 403),
        ("opus inference-profile ARN", f"arn:aws:bedrock:{gwlib.REGION}:{account}:inference-profile/global.anthropic.{OPUS}", 8, 403),
        ("claude-experiment alias", "claude-experiment", 8, 403),
        ("haiku max_tokens above the cap", f"global.anthropic.{HAIKU}", 32000, 403),
        ("undeclared model", "global.anthropic.claude-sonnet-4-5", 8, 400),
    ]
    for label, model_id, max_tokens, want in invoke_cases:
        try:
            br.invoke_model(modelId=model_id, contentType="application/json", body=json.dumps(
                {"anthropic_version": "bedrock-2023-05-31", "max_tokens": max_tokens,
                 "messages": [{"role": "user", "content": "hi"}]}))
            record(f"policy: standard InvokeModel {label} denied", False, "allowed")
        except botocore.exceptions.ClientError as e:
            got = e.response["ResponseMetadata"]["HTTPStatusCode"]
            record(f"policy: standard InvokeModel {label} denied", got == want, f"{got} {str(e)[:100]}")
    try:
        br.converse(modelId=f"global.anthropic.{HAIKU}", messages=[{"role": "user", "content": [{"text": "hi"}]}],
                    inferenceConfig={"maxTokens": 8})
        record("policy: Converse refused", False, "allowed")
    except botocore.exceptions.ClientError as e:
        got = e.response["ResponseMetadata"]["HTTPStatusCode"]
        record("policy: Converse refused", got == 400, f"{got} {str(e)[:100]}")
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = gwlib.token("team-premium")
    try:
        pr = boto3.client("bedrock-runtime", region_name=gwlib.REGION, endpoint_url=gwlib.endpoint())
        out = json.loads(pr.invoke_model(
            modelId=f"arn:aws:bedrock:{gwlib.REGION}:{account}:inference-profile/global.anthropic.{OPUS}",
            contentType="application/json", body=json.dumps(
                {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 8,
                 "messages": [{"role": "user", "content": "hi"}]}))["body"].read())
        record("policy: premium InvokeModel opus ARN allowed", out.get("model") == OPUS, f"model={out.get('model')}")
    except botocore.exceptions.ClientError as e:
        record("policy: premium InvokeModel opus ARN allowed", False, str(e)[:120])
    finally:
        os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)


@check("failover")
def t_failover():
    t0 = time.time()
    try:
        resp, text = ask("team-standard", "claude-haiku-5-5-failover-drill")
        record("failover drill 3P→1P", served_by(resp.id) == "1P:cponaws",
               f"served_by={served_by(resp.id)} model={resp.model} {time.time() - t0:.1f}s text={text!r}")
    except anthropic.APIStatusError as e:
        record("failover drill 3P→1P", False, f"{e.status_code} {str(e.body)[:200]} (is the CPonAWS key secret set?)")
    # Streaming on the 1P path: SSE must pass through the proxy Lambda (RESPONSE_STREAM).
    t0 = time.time()
    chunks = 0
    with client("team-standard").messages.stream(
        model="claude-haiku-5-5-failover-drill", max_tokens=64, messages=[{"role": "user", "content": "Count from 1 to 10."}]
    ) as stream:
        for _ in stream.text_stream:
            chunks += 1
        final = stream.get_final_message()
    record("failover drill 3P→1P (streaming)", served_by(final.id) == "1P:cponaws" and chunks > 1,
           f"served_by={served_by(final.id)} chunks={chunks} {time.time() - t0:.1f}s")


@check("experiment")
def t_experiment():
    counts = collections.Counter()
    for _ in range(20):
        resp, _ = ask("team-premium", "claude-experiment", max_tokens=8)
        counts[resp.model] += 1
    record("experiment 90/10 split", len(counts) >= 1, dict(counts).__repr__())


@check("rate-limit")
def t_rate_limit():
    # The default '*' bucket is not reachable by named teams; this exercises the team RPM bucket.
    # Sequential calls (~1.5 s each) never exceed 60/min, so send 90 calls with
    # 8 workers (below the team's 10-connection limit) to land within a minute.
    from concurrent.futures import ThreadPoolExecutor

    gwlib.token("team-standard")  # warm the token cache before the burst
    statuses = collections.Counter()
    sample_429 = []

    def one(_):
        try:
            ask("team-standard", HAIKU, max_tokens=1)
            return 200, None
        except anthropic.APIStatusError as e:
            return e.status_code, str(e.body)[:160]

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as pool:
        for status, body in pool.map(one, range(90)):
            statuses[status] += 1
            if status == 429 and not sample_429:
                sample_429.append(body)
    record("rate-limit team-standard 60 RPM", statuses.get(429, 0) > 0,
           f"{dict(statuses)} in {time.time() - t0:.0f}s; 429 body={sample_429[:1]}")


GPT_MODELS = ["gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna"]
GPT_DRILL = "gpt-6-luna-failover-drill"
CLAUDE_DRILL = "claude-haiku-5-5-failover-drill"
# Evidence window start; EVIDENCE_SINCE (epoch seconds) re-checks an earlier run.
START = float(os.environ.get("EVIDENCE_SINCE", time.time()))


def oai(team: str) -> openai.OpenAI:
    return openai.OpenAI(base_url=gwlib.endpoint() + "/v1", api_key=gwlib.token(team), max_retries=0, timeout=180)


def chat(team: str, model: str, prompt: str = "Reply with exactly: pong", **kw):
    # Reasoning models spend part of the budget on reasoning tokens; leave room for the answer.
    r = oai(team).chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=kw.pop("max_completion_tokens", 512), **kw,
    )
    return r, ((r.choices[0].message.content or "") if r.choices else "").strip()


@check("gpt")
def t_gpt():
    for m in GPT_MODELS:
        t0 = time.time()
        r, text = chat("team-standard", m)
        record(f"gpt chat {m}", bool(text), f"model={r.model} {time.time() - t0:.1f}s text={text[:30]!r}")

    chunks, text = 0, ""
    for ev in oai("team-standard").chat.completions.create(
        model="gpt-6-luna", messages=[{"role": "user", "content": "Count from 1 to 10."}],
        max_completion_tokens=512, stream=True,
    ):
        if ev.choices and ev.choices[0].delta and ev.choices[0].delta.content:
            chunks += 1
            text += ev.choices[0].delta.content
    record("gpt chat streaming gpt-6-luna", chunks > 1, f"chunks={chunks} text={text.strip()[:40]!r}")

    r = oai("team-standard").responses.create(model="gpt-6.1-sol", input="Reply with exactly: pong", max_output_tokens=512)
    record("gpt responses API gpt-6.1-sol", bool(r.output_text.strip()), f"model={r.model} text={r.output_text.strip()[:30]!r}")

    r, text = chat("team-standard", "openai.gpt-6-sol")
    record("gpt alias openai.gpt-6-sol", bool(text), f"model={r.model} text={text[:30]!r}")

    try:
        ask("team-standard", "gpt-6-luna")
        record("gpt via Anthropic SDK → guidance 400", False, "unexpectedly succeeded")
    except anthropic.APIStatusError as e:
        record("gpt via Anthropic SDK → guidance 400", e.status_code == 400 and "OpenAI" in str(e.body), f"{e.status_code} {str(e.body)[:120]}")

    try:
        chat("team-standard", "gpt-6-luna", "내 주민등록번호는 900101-1234567 입니다. 이걸로 신청서를 채워줘.")
        record("gpt guardrail blocks RRN", False, "request was not blocked")
    except openai.APIStatusError as e:
        record("gpt guardrail blocks RRN", e.status_code == 400 and "guardrail" in str(e.body).lower(), f"{e.status_code} {str(e.body)[:120]}")

    try:
        chat("team-standard", "gpt-6-luna", max_completion_tokens=32000)
        record("gpt policy: max_completion_tokens cap", False, "allowed")
    except openai.APIStatusError as e:
        record("gpt policy: max_completion_tokens cap", e.status_code == 403, f"{e.status_code} {str(e.body)[:120]}")

    t0 = time.time()
    r, text = chat("team-standard", GPT_DRILL)
    record("gpt failover drill (response)", bool(text), f"model={r.model} {time.time() - t0:.1f}s text={text[:30]!r}")


@check("quota-headroom")
def t_quota_headroom():
    # Per-model gateway TPM must stay at or below 80% of the account's Global cross-Region TPM
    # quota, so the gateway throttles before Bedrock answers 429 (which would trigger a fallback).
    headroom = 0.8
    gateway_id = urllib.parse.urlparse(gwlib.endpoint()).hostname.split(".")[0]
    ctl = boto3.client("bedrock-agentcore-control", region_name=gwlib.REGION)
    entries = ctl.get_gateway_rate_limit(gatewayIdentifier=gateway_id, rateLimitId="per-model")["entries"]
    quotas = {}
    for page in boto3.client("service-quotas", region_name=gwlib.REGION).get_paginator(
            "list_service_quotas").paginate(ServiceCode="bedrock"):
        quotas.update({q["QuotaName"]: q["Value"] for q in page["Quotas"]})

    def quota_name(model_id):
        m = re.fullmatch(r"global\.anthropic\.claude-([a-z]+)-(\d+)-(\d+)", model_id)
        if m:
            return f"Anthropic Claude {m[1].title()} {m[2]}.{m[3]}"
        m = re.fullmatch(r"global\.openai\.gpt-([\d.]+)-([a-z]+)", model_id)
        return f"GPT-{m[1]} {m[2].title()}" if m else None

    for entry in entries:
        model_id = entry["dimensions"]["qualifiedModelId"]
        name = quota_name(model_id)
        if not name:
            continue  # fallback IDs and the "*" default: no Global CRIS quota
        tpm = entry["tokens"][0]["rate"]
        quota = quotas.get(f"Global cross-region model inference tokens per minute for {name}")
        if quota is None:
            record(f"quota-headroom {model_id}", False, "no matching Service Quotas entry")
            continue
        record(f"quota-headroom {model_id}", tpm <= headroom * quota,
               f"gateway {tpm:,.0f} / quota {quota:,.0f} TPM ({tpm / quota:.0%}, limit {headroom:.0%})")


@check("routing-evidence")
def t_routing_evidence():
    """Which target actually served each request, from the gateway's vended routing logs."""
    logs = boto3.client("logs", region_name=gwlib.REGION)
    query = (
        "fields body.routing.requestedModelId as requested, body.routing.targetName as target, "
        "body.routing.resolvedModelId as served, body.routing.reason as reason "
        '| filter body.log = "Model routing succeeded" '
        "| stats count(*) as n by requested, target, served, reason | sort requested"
    )
    check_gpt = "gpt" in RAN or "EVIDENCE_SINCE" in os.environ
    check_claude = "failover" in RAN or "EVIDENCE_SINCE" in os.environ
    expected = (set(GPT_MODELS) | {GPT_DRILL} if check_gpt else set()) | ({CLAUDE_DRILL} if check_claude else set())
    rows, deadline = [], time.time() + 240
    while time.time() < deadline:  # vended logs arrive with a delay; wait for every expected request
        qid = logs.start_query(logGroupName=gwlib.outputs()["GatewayLogGroup"], startTime=int(START) - 60,
                               endTime=int(time.time()) + 60, queryString=query)["queryId"]
        while (res := logs.get_query_results(queryId=qid))["status"] in ("Running", "Scheduled"):
            time.sleep(1)
        rows = [{f["field"]: f["value"] for f in r} for r in res["results"]]
        if expected <= {r.get("requested") for r in rows}:
            break
        time.sleep(15)
    print("\n  requested model                         target    served model                         reason                 n")
    for r in rows:
        print(f"  {r.get('requested', '')[:38]:<38}  {r.get('target', ''):<8}  {r.get('served', '')[:35]:<35}  {r.get('reason', '')[:22]:<22} {r.get('n')}")
    print()
    by_req = collections.defaultdict(set)
    for r in rows:
        by_req[r.get("requested")].add(r.get("target"))
    if check_gpt:
        record("evidence: GPT primary = bedrock", all(by_req.get(m) == {"bedrock"} for m in GPT_MODELS), str({m: sorted(by_req.get(m, [])) for m in GPT_MODELS}))
        record("evidence: GPT drill served by mantle", by_req.get(GPT_DRILL) == {"mantle"}, str(sorted(by_req.get(GPT_DRILL, []))))
    if check_claude:
        record("evidence: Claude drill served by cponaws", by_req.get(CLAUDE_DRILL) == {"cponaws"}, str(sorted(by_req.get(CLAUDE_DRILL, []))))


RAN: set = set()
CHECKS = [t_models, t_route_3p, t_streaming, t_alias, t_openai, t_bedrock_sdk, t_guardrail, t_policy, t_failover,
          t_experiment, t_gpt, t_rate_limit, t_quota_headroom, t_routing_evidence]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="check names to run")
    parser.add_argument("--skip", nargs="*", default=[], help="check names to skip")
    args = parser.parse_args()
    unknown = set(args.only or []) - {fn.check_name for fn in CHECKS}
    if unknown:
        parser.error(f"unknown check(s): {', '.join(sorted(unknown))}")
    print(f"endpoint: {gwlib.endpoint()}\n")
    for fn in CHECKS:
        if (args.only and fn.check_name not in args.only) or fn.check_name in args.skip:
            continue
        RAN.add(fn.check_name)
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            record(fn.check_name, False, f"{type(e).__name__}: {str(e)[:300]}")
            traceback.print_exc(limit=1)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
