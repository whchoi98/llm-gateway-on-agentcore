# AgentCore LLM Gateway

[![Version](https://img.shields.io/badge/Version-0.1.0-green.svg)](CHANGELOG.md)
<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

One endpoint for Claude and GPT on Amazon Bedrock AgentCore Gateway in Seoul. Bedrock Global CRIS first, automatic fallback | 서울 리전 Amazon Bedrock AgentCore Gateway의 Claude, GPT 단일 엔드포인트. Bedrock Global CRIS를 먼저 시도하고 실패하면 자동으로 fallback

---

<a id="english"></a>

# English

## Overview

An LLM gateway built on Amazon Bedrock AgentCore Gateway in ap-northeast-2 (Seoul). Clients call one endpoint for Claude 5.5 (Opus, Sonnet, Haiku) and GPT 6.x (6.1 Sol, 6.1 Terra, 6 Astra, 6 Sol, 6 Luna).

Every request goes to Bedrock Global CRIS first. When it fails, the gateway falls back by model family: Claude to Claude Platform on AWS (1P, CPonAWS), GPT to Bedrock Mantle in us-east-1. Mantle uses in-Region model IDs and has its own capacity and quotas.

<!-- TODO: add a demo image or GIF -->

## Features

- Each model family has its own fallback. Bedrock Global CRIS is the primary for every model. A 429, 5XX, 408, or 403, a connection error, or a first-byte timeout triggers the fallback. Claude then moves to Claude Platform on AWS, and GPT to Bedrock Mantle in us-east-1. A circuit breaker skips a primary that keeps failing.
- One endpoint, `/inference`, accepts Anthropic Messages, OpenAI Chat Completions and Responses, and Bedrock InvokeModel. Clients need only a Cognito JWT.
- Each team has its own RPM, TPM, and concurrent-connection limits. Cedar policies set the premium models and the output-token cap, and a Bedrock Guardrail checks requests on every path.
- Routing supports aliases, `claude-auto` (the interceptor picks a model by prompt size), and a 90/10 A/B experiment. Failover drills exercise each fallback on demand.
- Vended routing logs and traces record which destination served each request. Metric filters count fallbacks for a CloudWatch dashboard and alarms.

## Architecture

![AgentCore LLM Gateway architecture](docs/architecture.en.png)

![LLM Gateway request flow](docs/request-flow.en.png)

The sequence below shows the same fallback over time. With the circuit breaker closed, the gateway tries Bedrock first and moves on when a trigger fires. With the breaker open, it skips the primary.

![Fallback over time](docs/fallback-sequence.en.png)

The Mermaid chart below summarizes the request flow, with the zones and colors of the diagrams above.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 400, "subGraphTitleMargin": {"top": 4, "bottom": 16}}}}%%
flowchart LR
  Req(["Client request"])
  S1["1: Inbound auth, rate limits<br/>Cognito JWT, per-team, per-model<br/>reject 401 / 429"]
  S2["2: Rule match<br/>model as sent → primary + fallback"]
  S3["3: Interceptor Lambda<br/>guardrail, claude-auto, dialect<br/>reject 400 / 403"]
  S4["4: Cedar policy<br/>invoke scope, premium, max tokens<br/>reject 403"]
  S5["5: Amazon Bedrock<br/>Global CRIS, Seoul<br/>fails over on 429, 5XX, 408, 403, timeout"]
  D{"6: Fallback?"}
  F1["Claude Platform on AWS<br/>via proxy λ, claude-*-5-5"]
  F2["Bedrock Mantle<br/>us-east-1, openai.gpt-6*"]
  Resp(["Response<br/>SSE stream or JSON"])

  Req --> S1 --> S2 --> S3 --> S4
  S4 -- allowed --> S5 --> D
  D -- no --> Resp
  D -- "yes, Claude" --> F1
  D -- "yes, GPT" --> F2
  F1 --> Resp
  F2 --> Resp

  classDef security fill:#ffffff,stroke:#DD344C,stroke-width:2px,color:#232F3E
  classDef step fill:#ffffff,stroke:#232F3E,stroke-width:1.5px,color:#232F3E
  classDef compute fill:#ffffff,stroke:#ED7100,stroke-width:2px,color:#232F3E
  classDef ai fill:#ffffff,stroke:#01A88D,stroke-width:2px,color:#232F3E
  classDef focal fill:#FFF4E5,stroke:#EC7211,stroke-width:2px,color:#232F3E
  classDef external fill:#F7F8F8,stroke:#879196,stroke-dasharray:4 4,color:#232F3E
  classDef io fill:#F2F3F3,stroke:#7D8998,color:#232F3E
  class S1 security
  class S2,S4 step
  class S3 compute
  class S5,F2 ai
  class D focal
  class F1 external
  class Req,Resp io
  linkStyle 0 stroke:#0972D3,stroke-width:1.5px
  linkStyle 1,2,3,4,5 stroke:#232F3E,stroke-width:1.5px
  linkStyle 6,9,10 stroke:#545B64
  linkStyle 7,8 stroke:#EC7211,stroke-width:2px
```

[docs/architecture.md](docs/architecture.md) describes each component. The diagrams are also available as SVG: [architecture](docs/architecture.en.svg), [request flow](docs/request-flow.en.svg), [fallback sequence](docs/fallback-sequence.en.svg), and [deploy order](docs/deploy-order.en.svg). [docs/architecture.en.html](docs/architecture.en.html) shows all four on one page.

| Model the client sends | API | Primary | Fallback |
|---|---|---|---|
| `claude-opus-5-5`, `opus`, `anthropic.claude-opus-5-5`, `global.anthropic.claude-opus-5-5` | Messages | bedrock / `global.anthropic.claude-opus-5-5` | cponaws / `claude-opus-5-5` |
| `claude-sonnet-5-5`, `sonnet`, ... | Messages | bedrock / `global.anthropic.claude-sonnet-5-5` | cponaws / `claude-sonnet-5-5` |
| `claude-haiku-5-5`, `haiku`, ... | Messages | bedrock / `global.anthropic.claude-haiku-5-5` | cponaws / `claude-haiku-5-5` |
| `gpt-6.1-sol`, `openai.gpt-6.1-sol`, `global.openai.gpt-6.1-sol` | Chat Completions, Responses | bedrock / `global.openai.gpt-6.1-sol` | mantle / `openai.gpt-6.1-sol` |
| `gpt-6.1-terra`, `gpt-6-astra`, `gpt-6-sol`, `gpt-6-luna` (same forms) | Chat Completions, Responses | bedrock / `global.openai.<model>` | mantle / `openai.<model>` |
| `claude-auto` | Messages | interceptor picks a Bedrock Claude model by prompt size | cponaws / `claude-sonnet-5-5` |
| `claude-experiment` | Messages | Sonnet 90%, Opus 10% (`weightedRoute`) | each leg's fallback |
| `claude-haiku-5-5-failover-drill` | Messages | primary with a 50 ms first-byte timeout (always stalls) | cponaws / `claude-haiku-5-5` |
| `gpt-6-luna-failover-drill` | Chat Completions, Responses | primary with a 50 ms first-byte timeout (always stalls) | mantle / `openai.gpt-6-luna` |

| Requirement | Implementation | Where |
|---|---|---|
| One endpoint, SDK compatibility | Gateway `/inference` | `lib/llm-gateway-stack.ts` |
| Multiple providers | `bedrock-runtime` connector target, CPonAWS and Mantle provider targets | `lib/llm-gateway-stack.ts` |
| Credential abstraction | Clients hold only a Cognito JWT; the gateway role signs to Bedrock, Mantle, and the CPonAWS proxy, and only the proxy reads the CPonAWS key | `lib/constructs/cponaws-proxy.ts` |
| Model routing and fallback | `matchModels` rules with `staticRoute.model` and a `fallback` chain | `lib/config.ts` |
| A/B testing | `weightedRoute` 90/10 | `lib/config.ts` |
| Team quotas | RPM, TPM, and connections per `$.context.jwt.client_id`; TPM per `qualifiedModelId` | `lib/llm-gateway-stack.ts` |
| RBAC and token caps | Cedar policies; on InvokeModel paths the interceptor enforces premium models and the token cap, and refuses unknown models | `lib/policy-stack.ts`, `lambda/interceptor/index.py` |
| Guardrail | Bedrock Guardrail (Standard tier, APAC profile) | `lib/constructs/guardrail-interceptor.ts` |
| Dynamic routing | `claude-auto` in the interceptor | `lambda/interceptor/index.py` |
| Model catalog | `GET /inference/v1/models` | built in |
| Observability | Vended logs and traces, dashboard, alarms, saved queries | `lib/constructs/observability.ts` |

## Prerequisites

- Node.js 22+ and npm
- AWS CLI v2 with credentials for the target account, and CDK bootstrap in ap-northeast-2
- `uv`, for `scripts/smoke_test.py`
- A Claude Platform on AWS API key and a Seoul workspace ID, for the Claude fallback

## Installation

![Deploy order](docs/deploy-order.en.png)

```bash
# Clone the repository
git clone https://github.com/whchoi98/llm-gateway-on-agentcore.git
cd llm-gateway-on-agentcore

# Check tools, install dependencies, and install the commit-msg hook
bash scripts/setup.sh

# Prerequisite: verify and store the CPonAWS key (run in your own terminal; input is hidden)
./scripts/set-cponaws-key.sh

# Deploy the core stack, then the Cedar policy stack
npx cdk diff --all
npx cdk deploy --all
```

- The CPonAWS target lists models when it is created and fails if the key is wrong. That is why the key secret is a prerequisite outside the stacks.
- Without a key yet, deploy with `-c enable1p=false`. Claude then runs without a fallback.
- `-c policyMode=LOG_ONLY` records Cedar decisions without denying requests.
- `-c alarmEmail=you@example.com` subscribes an e-mail address to the alarms.

## Usage

Each team's secret `llm-gateway/clients/<team>` holds the `client_id`, `client_secret`, and `token_url` for an access token. `token()` in `scripts/gwlib.py` shows the request.

```python
import anthropic
client = anthropic.Anthropic(base_url=INFERENCE_ENDPOINT, auth_token=ACCESS_TOKEN)  # auth_token, not api_key
client.messages.create(model="claude-sonnet-5-5", max_tokens=1024,
                       messages=[{"role": "user", "content": "Hello"}])
```

```python
from openai import OpenAI
client = OpenAI(base_url=f"{INFERENCE_ENDPOINT}/v1", api_key=ACCESS_TOKEN)
client.chat.completions.create(model="gpt-6.1-sol", max_completion_tokens=1024,
                               messages=[{"role": "user", "content": "Hello"}])
client.responses.create(model="gpt-6-luna", input="Hello", max_output_tokens=1024)
```

```python
import os, boto3
os.environ["AWS_BEARER_TOKEN_BEDROCK"] = ACCESS_TOKEN      # Bedrock SDK: a bearer token instead of SigV4
br = boto3.client("bedrock-runtime", region_name="ap-northeast-2", endpoint_url=INFERENCE_ENDPOINT)
br.invoke_model(modelId="global.anthropic.claude-haiku-5-5", contentType="application/json", body=...)
```

The response shows which destination served it. A Claude `id` that starts with `msg_bdrk_` came from Bedrock, and any other `msg_` ID from CPonAWS. A GPT `model` of `global.openai.*` came from Bedrock Global CRIS, and `openai.*` from Mantle.

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_PROFILE` | AWS credentials profile used by the CDK CLI, the AWS CLI, and the scripts | default credential chain |
| `LLM_GATEWAY_ENDPOINT` | Inference endpoint the scripts call | `InferenceEndpoint` from `cdk-outputs.json` |
| `ANTHROPIC_API_KEY` | CPonAWS key read by `scripts/set-cponaws-key.sh` | prompted |
| `ANTHROPIC_WORKSPACE_ID` | Seoul workspace ID for `scripts/set-cponaws-key.sh`, stored in the SSM parameter `/llm-gateway/anthropic-workspace-id` | the existing parameter, else a prompt |
| `EVIDENCE_SINCE` | Epoch seconds from which `smoke_test.py --only routing-evidence` reads routing logs | start of the run |

Models, fallbacks, teams, and limits are declared in `lib/config.ts`. Workspaces are region-bound, so use a Seoul workspace. Its ID is kept out of the repository in an SSM parameter, which CloudFormation resolves at deploy time.

## Project Structure

```text
bin/            # CDK app entry point
lib/            # Stacks, constructs, and config.ts
lambda/         # Interceptor and CPonAWS proxy handlers
scripts/        # Smoke tests, key setup, setup and hook scripts; diagrams/ generator
tests/          # Harness tests
docs/           # Architecture, diagrams, reference docs, ADR and runbook templates
```

## Testing

```bash
# Typecheck
npm run build

# Harness tests (hooks, secret patterns, project structure)
bash tests/run-all.sh

# Live E2E against the deployed gateway (AWS credentials required; small cost)
uv run scripts/smoke_test.py

# Selected checks
uv run scripts/smoke_test.py --only gpt failover routing-evidence
```

## API Documentation

The base URL is `https://<gateway-id>.gateway.bedrock-agentcore.ap-northeast-2.amazonaws.com/inference`. Every request needs `Authorization: Bearer <Cognito access token>`.

| Path | API | Models |
|---|---|---|
| `POST /v1/messages` | Anthropic Messages | Claude |
| `POST /v1/chat/completions` | OpenAI Chat Completions | GPT |
| `POST /v1/responses` | OpenAI Responses | GPT |
| `POST /model/{model}/invoke`, `/invoke-with-response-stream` | Bedrock InvokeModel | Claude, GPT |
| `GET /v1/models` | Model catalog | all targets |

## Contributing

1. Create a branch (`git checkout -b feat/<name>`)
2. Change `lib/config.ts` for model or limit changes; keep docs in the same commit
3. Run `npm run build` and `bash tests/run-all.sh`. After a routing, policy, or Lambda change, also deploy and run the matching `smoke_test.py` check
4. Commit (`git commit -m 'feat: <change>'`) and open a pull request

## License

<!-- TODO: add a LICENSE file and name the license here -->
No license file yet.

## Contact

- Maintainer: [whchoi98](https://github.com/whchoi98)
- Issues: https://github.com/whchoi98/llm-gateway-on-agentcore/issues

## Verified Behavior

- Rules match the model as the client sent it, before the interceptor runs. Static aliases therefore belong in a rule's `matchModels`. An interceptor rewrite takes effect only on a route whose primary pins no model, such as `claude-auto`.
- Bedrock serves each model family in one API schema. Claude is served only through Messages or InvokeModel, and GPT only through the OpenAI schemas. A mismatched request gets a 400 that names the right SDK.
- Claude 5.5 Global CRIS is offered only on `bedrock-runtime`, and the GPT 6.x in-Region IDs only on Mantle us-east-1 under `/openai/v1`.
- A provider target calls `GET /v1/models` when it is created and fails on a bad credential. That makes the CPonAWS key a deploy prerequisite.
- CPonAWS needs `anthropic-workspace-id` on every request. A gateway target cannot add static headers, and the discovery call at creation time bypasses interceptors. A streaming Lambda proxy therefore adds the header.
- Cedar reads `context.input.<field>` only behind a `has` guard. Without the guard, validation rejects the forbid as "Overly Restrictive".
- InvokeModel carries the model ID in the URI, where Cedar cannot see it. The interceptor enforces premium models and the token cap on that path, after URL-decoding the ID and reducing an ARN to the model it names.
- Guardrails in Policy is not offered in ap-northeast-2, so the interceptor calls `ApplyGuardrail`. `GUARDRAIL_FAIL_MODE` defaults to `open`, with an alarm.
- An unservable model ID can return HTTP 200 with an error body (from Seoul, the bare `anthropic.claude-haiku-5-5`). That response is not fallback-eligible, so the drills use a 50 ms first-byte timeout instead.
- Vended routing logs are best effort. They arrive 20 to 80 seconds late and out of order, and one line in the tests never arrived. Use them for trends, not per-request accounting.
- Inference metrics are in the `ApplicationSignals` namespace. `AWS/Bedrock-AgentCore` holds only the Cedar and identity metrics.
- aws-cdk-lib's `CfnGatewayRule` lacks `MatchModels`, `Model`, and `Fallback` and drops them silently. The rules are therefore raw `CfnResource`, and synth prints F3018 warnings for them.

## Operational Notes

- First-byte timeouts are 180 s for Opus and GPT, 120 s for Sonnet and GPT 6 Luna, and 60 s for Haiku. A non-streaming response sends its first byte only when generation ends, so a client that streams lets the gateway detect a stall sooner.
- The gateway cannot fall back after a stream has started. If a stream fails after the first byte, the client must retry.
- Each fallback attempt is billed as a gateway invocation. An open circuit breaker skips a failing primary.
- During a GPT fallback, data goes to us-east-1.
- Rate limits are token buckets, so a burst can briefly exceed the per-minute number.
- `matchPrincipals` conditions match IAM principals only, so this JWT-based gateway does not use them.

## Cleanup

```bash
npx cdk destroy --all
aws secretsmanager delete-secret --secret-id llm-gateway/anthropic-api-key --region ap-northeast-2   # the prerequisite secret
```

---

<a id="korean"></a>

# 한국어

## 개요

ap-northeast-2(서울)의 Amazon Bedrock AgentCore Gateway로 만든 LLM Gateway입니다. 클라이언트는 엔드포인트 하나로 Claude 5.5(Opus, Sonnet, Haiku)와 GPT 6.x(6.1 Sol, 6.1 Terra, 6 Astra, 6 Sol, 6 Luna)를 호출합니다.

모든 요청은 Bedrock Global CRIS로 먼저 갑니다. 실패하면 모델 계열에 따라 자동으로 fallback합니다. Claude는 Claude Platform on AWS(1P, CPonAWS)로, GPT는 us-east-1의 Bedrock Mantle로 넘어갑니다. Mantle은 리전 내 모델 ID를 사용하며 용량과 quota가 따로 있습니다.

<!-- TODO: 데모 이미지 또는 GIF 추가 -->

## 주요 기능

- 모델 계열마다 fallback 대상이 다릅니다. 모든 모델의 primary는 Bedrock Global CRIS입니다. 429, 5XX, 408, 403, 연결 오류, first-byte timeout이 나면 fallback합니다. Claude는 Claude Platform on AWS로, GPT는 us-east-1의 Bedrock Mantle로 넘어갑니다. 실패가 이어지는 primary는 회로 차단기(circuit breaker)가 건너뜁니다.
- 엔드포인트 `/inference` 하나에서 Anthropic Messages, OpenAI Chat Completions와 Responses, Bedrock InvokeModel을 모두 받습니다. 클라이언트에게는 Cognito JWT만 있으면 됩니다.
- 팀마다 RPM, TPM, 동시 연결 한도가 따로 있습니다. premium 모델과 출력 토큰 한도는 Cedar 정책으로 정합니다. 모든 경로의 요청은 Bedrock Guardrail이 검사합니다.
- 라우팅은 alias, interceptor가 프롬프트 크기로 모델을 고르는 `claude-auto`, 90/10 A/B 실험을 지원합니다. failover drill로 각 fallback 경로를 언제든 시험할 수 있습니다.
- AgentCore가 내보내는 라우팅 로그(vended log)와 trace에 어느 대상이 응답했는지 남습니다. fallback 건수는 metric filter가 세어 CloudWatch 대시보드와 알람에 보냅니다.

## 아키텍처

![AgentCore LLM Gateway 아키텍처](docs/architecture.ko.png)

![LLM Gateway 요청 흐름](docs/request-flow.ko.png)

아래 시퀀스는 같은 fallback을 시간 순서로 보여 줍니다. 회로 차단기가 닫혀 있으면 Gateway가 Bedrock을 먼저 시도하고 trigger가 생길 때 다음 대상으로 넘어갑니다. 차단기가 열려 있으면 primary를 건너뜁니다.

![시간 순서로 본 fallback](docs/fallback-sequence.ko.png)

아래 Mermaid 그림은 같은 요청 흐름을 요약합니다. 구역과 색은 위 다이어그램과 같습니다.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 400, "subGraphTitleMargin": {"top": 4, "bottom": 16}}}}%%
flowchart LR
  Req(["Client request"])
  S1["1: Inbound auth, rate limits<br/>Cognito JWT, per-team, per-model<br/>reject 401 / 429"]
  S2["2: Rule match<br/>model as sent → primary + fallback"]
  S3["3: Interceptor Lambda<br/>guardrail, claude-auto, dialect<br/>reject 400 / 403"]
  S4["4: Cedar policy<br/>invoke scope, premium, max tokens<br/>reject 403"]
  S5["5: Amazon Bedrock<br/>Global CRIS, Seoul<br/>fails over on 429, 5XX, 408, 403, timeout"]
  D{"6: Fallback?"}
  F1["Claude Platform on AWS<br/>via proxy λ, claude-*-5-5"]
  F2["Bedrock Mantle<br/>us-east-1, openai.gpt-6*"]
  Resp(["Response<br/>SSE stream or JSON"])

  Req --> S1 --> S2 --> S3 --> S4
  S4 -- allowed --> S5 --> D
  D -- no --> Resp
  D -- "yes, Claude" --> F1
  D -- "yes, GPT" --> F2
  F1 --> Resp
  F2 --> Resp

  classDef security fill:#ffffff,stroke:#DD344C,stroke-width:2px,color:#232F3E
  classDef step fill:#ffffff,stroke:#232F3E,stroke-width:1.5px,color:#232F3E
  classDef compute fill:#ffffff,stroke:#ED7100,stroke-width:2px,color:#232F3E
  classDef ai fill:#ffffff,stroke:#01A88D,stroke-width:2px,color:#232F3E
  classDef focal fill:#FFF4E5,stroke:#EC7211,stroke-width:2px,color:#232F3E
  classDef external fill:#F7F8F8,stroke:#879196,stroke-dasharray:4 4,color:#232F3E
  classDef io fill:#F2F3F3,stroke:#7D8998,color:#232F3E
  class S1 security
  class S2,S4 step
  class S3 compute
  class S5,F2 ai
  class D focal
  class F1 external
  class Req,Resp io
  linkStyle 0 stroke:#0972D3,stroke-width:1.5px
  linkStyle 1,2,3,4,5 stroke:#232F3E,stroke-width:1.5px
  linkStyle 6,9,10 stroke:#545B64
  linkStyle 7,8 stroke:#EC7211,stroke-width:2px
```

구성 요소별 설명은 [docs/architecture.md](docs/architecture.md)에 있습니다. 다이어그램의 SVG 파일은 [아키텍처](docs/architecture.ko.svg), [요청 흐름](docs/request-flow.ko.svg), [fallback 시퀀스](docs/fallback-sequence.ko.svg), [배포 순서](docs/deploy-order.ko.svg)입니다. [docs/architecture.html](docs/architecture.html)에서는 네 그림을 한 페이지로 볼 수 있습니다.

| 클라이언트가 보내는 model | API | Primary | Fallback |
|---|---|---|---|
| `claude-opus-5-5`, `opus`, `anthropic.claude-opus-5-5`, `global.anthropic.claude-opus-5-5` | Messages | bedrock / `global.anthropic.claude-opus-5-5` | cponaws / `claude-opus-5-5` |
| `claude-sonnet-5-5`, `sonnet`, ... | Messages | bedrock / `global.anthropic.claude-sonnet-5-5` | cponaws / `claude-sonnet-5-5` |
| `claude-haiku-5-5`, `haiku`, ... | Messages | bedrock / `global.anthropic.claude-haiku-5-5` | cponaws / `claude-haiku-5-5` |
| `gpt-6.1-sol`, `openai.gpt-6.1-sol`, `global.openai.gpt-6.1-sol` | Chat Completions, Responses | bedrock / `global.openai.gpt-6.1-sol` | mantle / `openai.gpt-6.1-sol` |
| `gpt-6.1-terra`, `gpt-6-astra`, `gpt-6-sol`, `gpt-6-luna` (같은 형식) | Chat Completions, Responses | bedrock / `global.openai.<model>` | mantle / `openai.<model>` |
| `claude-auto` | Messages | interceptor가 프롬프트 크기로 Bedrock Claude 모델 선택 | cponaws / `claude-sonnet-5-5` |
| `claude-experiment` | Messages | Sonnet 90%, Opus 10% (`weightedRoute`) | 각 leg의 fallback |
| `claude-haiku-5-5-failover-drill` | Messages | first-byte timeout 50ms인 primary(항상 지연) | cponaws / `claude-haiku-5-5` |
| `gpt-6-luna-failover-drill` | Chat Completions, Responses | first-byte timeout 50ms인 primary(항상 지연) | mantle / `openai.gpt-6-luna` |

| 요구사항 | 구현 | 위치 |
|---|---|---|
| 단일 엔드포인트, SDK 호환 | Gateway `/inference` | `lib/llm-gateway-stack.ts` |
| 멀티 프로바이더 | `bedrock-runtime` connector target, CPonAWS와 Mantle provider target | `lib/llm-gateway-stack.ts` |
| 자격증명 추상화 | 클라이언트는 Cognito JWT만 갖습니다. Gateway role이 Bedrock, Mantle, CPonAWS 프록시에 서명하고, CPonAWS 키는 프록시만 읽습니다 | `lib/constructs/cponaws-proxy.ts` |
| 모델 라우팅과 fallback | `staticRoute.model`과 `fallback` chain을 가진 `matchModels` rule | `lib/config.ts` |
| A/B 테스트 | `weightedRoute` 90/10 | `lib/config.ts` |
| 팀별 쿼터 | `$.context.jwt.client_id` 기준 RPM, TPM, 동시 연결과 `qualifiedModelId` 기준 TPM | `lib/llm-gateway-stack.ts` |
| RBAC과 토큰 한도 | Cedar 정책. InvokeModel 경로에서는 interceptor가 premium 모델과 토큰 한도를 검사하고 미등록 모델을 거부 | `lib/policy-stack.ts`, `lambda/interceptor/index.py` |
| 가드레일 | Bedrock Guardrail(Standard tier, APAC 프로필) | `lib/constructs/guardrail-interceptor.ts` |
| 동적 라우팅 | interceptor의 `claude-auto` | `lambda/interceptor/index.py` |
| 모델 카탈로그 | `GET /inference/v1/models` | 내장 |
| 관측성 | Vended log와 trace, 대시보드, 알람, 저장 쿼리 | `lib/constructs/observability.ts` |

## 사전 요구 사항

- Node.js 22 이상과 npm
- 대상 계정 자격증명이 설정된 AWS CLI v2, ap-northeast-2의 CDK bootstrap
- `scripts/smoke_test.py`를 실행할 `uv`
- Claude fallback용 Claude Platform on AWS API 키와 서울 workspace ID

## 설치 방법

![배포 순서](docs/deploy-order.ko.png)

```bash
# 저장소 복제
git clone https://github.com/whchoi98/llm-gateway-on-agentcore.git
cd llm-gateway-on-agentcore

# 도구 확인, 의존성 설치, commit-msg hook 설치
bash scripts/setup.sh

# 사전 조건: CPonAWS 키 검증 후 저장 (직접 연 터미널에서 실행, 입력은 표시되지 않음)
./scripts/set-cponaws-key.sh

# Core 스택 다음 Cedar 정책 스택 배포
npx cdk diff --all
npx cdk deploy --all
```

- CPonAWS target은 생성될 때 모델 목록을 조회하고 키가 틀리면 실패합니다. 그래서 키 Secret은 스택 밖의 사전 조건으로 둡니다.
- 아직 키가 없으면 `-c enable1p=false`로 배포합니다. 이때 Claude에는 fallback이 없습니다.
- `-c policyMode=LOG_ONLY`는 Cedar 결정을 기록만 하고 요청을 거부하지 않습니다.
- `-c alarmEmail=you@example.com`을 지정하면 알람이 그 주소로 메일을 보냅니다.

## 사용법

팀별 Secret `llm-gateway/clients/<team>`에 든 `client_id`, `client_secret`, `token_url`로 access token을 받습니다. 요청 방법은 `scripts/gwlib.py`의 `token()`에 있습니다.

```python
import anthropic
client = anthropic.Anthropic(base_url=INFERENCE_ENDPOINT, auth_token=ACCESS_TOKEN)  # api_key가 아니라 auth_token
client.messages.create(model="claude-sonnet-5-5", max_tokens=1024,
                       messages=[{"role": "user", "content": "Hello"}])
```

```python
from openai import OpenAI
client = OpenAI(base_url=f"{INFERENCE_ENDPOINT}/v1", api_key=ACCESS_TOKEN)
client.chat.completions.create(model="gpt-6.1-sol", max_completion_tokens=1024,
                               messages=[{"role": "user", "content": "Hello"}])
client.responses.create(model="gpt-6-luna", input="Hello", max_output_tokens=1024)
```

```python
import os, boto3
os.environ["AWS_BEARER_TOKEN_BEDROCK"] = ACCESS_TOKEN      # Bedrock SDK: SigV4 대신 bearer token 사용
br = boto3.client("bedrock-runtime", region_name="ap-northeast-2", endpoint_url=INFERENCE_ENDPOINT)
br.invoke_model(modelId="global.anthropic.claude-haiku-5-5", contentType="application/json", body=...)
```

어느 대상이 응답했는지는 응답 값으로 알 수 있습니다. Claude 응답의 `id`가 `msg_bdrk_`로 시작하면 Bedrock이, 그 밖의 `msg_` ID면 CPonAWS가 응답했습니다. GPT 응답의 `model`이 `global.openai.*`이면 Bedrock Global CRIS, `openai.*`이면 Mantle입니다.

## 환경 설정

| 변수 | 설명 | 기본값 |
|----------|-------------|---------|
| `AWS_PROFILE` | CDK CLI, AWS CLI, 스크립트가 사용하는 AWS 자격증명 프로필 | 기본 자격증명 체인 |
| `LLM_GATEWAY_ENDPOINT` | 스크립트가 호출하는 inference 엔드포인트 | `cdk-outputs.json`의 `InferenceEndpoint` |
| `ANTHROPIC_API_KEY` | `scripts/set-cponaws-key.sh`가 읽는 CPonAWS 키 | 입력 프롬프트 |
| `ANTHROPIC_WORKSPACE_ID` | `scripts/set-cponaws-key.sh`가 SSM 파라미터 `/llm-gateway/anthropic-workspace-id`에 저장하는 서울 workspace ID | 기존 파라미터, 없으면 입력 |
| `EVIDENCE_SINCE` | `smoke_test.py --only routing-evidence`가 라우팅 로그를 읽기 시작할 epoch 초 | 실행 시작 시각 |

모델, fallback, 팀, 한도는 `lib/config.ts`에서 정의합니다. Workspace는 리전마다 따로 있으므로 서울 workspace ID를 사용해야 합니다. 이 ID는 저장소에 두지 않고 SSM 파라미터에 저장하며 CloudFormation이 배포할 때 값을 채웁니다.

## 프로젝트 구조

```text
bin/            # CDK 앱 진입점
lib/            # 스택, construct, config.ts
lambda/         # Interceptor와 CPonAWS 프록시 핸들러
scripts/        # Smoke test, 키 설정, setup과 hook 스크립트, diagrams/ 생성기
tests/          # Harness 테스트
docs/           # 아키텍처, 다이어그램, 참조 문서, ADR과 runbook 템플릿
```

## 테스트

```bash
# 타입 검사
npm run build

# Harness 테스트 (hook, secret 패턴, 프로젝트 구조)
bash tests/run-all.sh

# 배포된 gateway 대상 실환경 E2E (AWS 자격증명 필요, 소량 과금)
uv run scripts/smoke_test.py

# 일부 검사만 실행
uv run scripts/smoke_test.py --only gpt failover routing-evidence
```

## API 문서

기준 URL은 `https://<gateway-id>.gateway.bedrock-agentcore.ap-northeast-2.amazonaws.com/inference`입니다. 모든 요청에 `Authorization: Bearer <Cognito access token>` 헤더가 필요합니다.

| 경로 | API | 모델 |
|---|---|---|
| `POST /v1/messages` | Anthropic Messages | Claude |
| `POST /v1/chat/completions` | OpenAI Chat Completions | GPT |
| `POST /v1/responses` | OpenAI Responses | GPT |
| `POST /model/{model}/invoke`, `/invoke-with-response-stream` | Bedrock InvokeModel | Claude, GPT |
| `GET /v1/models` | 모델 카탈로그 | 모든 target |

## 기여 방법

1. 브랜치를 만듭니다(`git checkout -b feat/<name>`)
2. 모델이나 한도는 `lib/config.ts`에서 바꾸고 문서도 같은 커밋에서 수정합니다
3. `npm run build`와 `bash tests/run-all.sh`를 실행합니다. 라우팅, 정책, Lambda를 바꿨다면 배포 후 해당하는 `smoke_test.py` 검사를 실행합니다
4. 커밋(`git commit -m 'feat: <change>'`)하고 pull request를 엽니다

## 라이선스

<!-- TODO: LICENSE 파일을 추가하고 라이선스 이름을 적습니다 -->
아직 라이선스 파일이 없습니다.

## 연락처

- Maintainer: [whchoi98](https://github.com/whchoi98)
- Issues: https://github.com/whchoi98/llm-gateway-on-agentcore/issues

## 검증하면서 알게 된 동작

- Rule은 interceptor가 실행되기 전에 클라이언트가 보낸 model 값으로 매칭됩니다. 그래서 정적 alias는 rule의 `matchModels`에 둡니다. interceptor가 바꾼 model은 primary에 모델을 고정하지 않은 route(`claude-auto`)에서만 효과가 있습니다.
- Bedrock은 모델 계열마다 API 스키마가 하나입니다. Claude는 Messages나 InvokeModel로만, GPT는 OpenAI 스키마로만 서빙됩니다. 맞지 않는 요청에는 올바른 SDK를 알려 주는 400을 반환합니다.
- Claude 5.5 Global CRIS는 `bedrock-runtime`에서만, GPT 6.x의 리전 내 ID는 Mantle us-east-1의 `/openai/v1`에서만 제공됩니다.
- Provider target은 생성될 때 `GET /v1/models`를 호출하고 자격증명이 틀리면 실패합니다. CPonAWS 키를 배포 전에 준비해야 하는 이유입니다.
- CPonAWS는 모든 요청에 `anthropic-workspace-id` 헤더를 요구합니다. Gateway target은 고정 헤더를 넣을 수 없고 생성 시점의 discovery 호출은 interceptor를 거치지 않습니다. 그래서 스트리밍 Lambda 프록시가 이 헤더를 추가합니다.
- Cedar는 `context.input.<field>`를 `has` 가드 뒤에서만 읽을 수 있습니다. 가드가 없으면 검증 단계에서 forbid가 "Overly Restrictive"로 거부됩니다.
- InvokeModel은 모델 ID를 URI에 담으므로 Cedar가 볼 수 없습니다. 이 경로의 premium 모델 제한과 토큰 한도는 interceptor가 맡습니다. interceptor는 ID를 URL 디코딩하고 ARN은 가리키는 모델로 줄인 뒤 검사합니다.
- ap-northeast-2에서는 Guardrails in Policy를 제공하지 않으므로 interceptor가 `ApplyGuardrail`을 호출합니다. `GUARDRAIL_FAIL_MODE` 기본값은 `open`이며 알람이 걸려 있습니다.
- 서빙할 수 없는 모델 ID가 HTTP 200과 오류 본문을 돌려줄 수 있습니다(서울에서 접두어 없는 `anthropic.claude-haiku-5-5`). 이 응답은 fallback 대상이 아니므로 drill에는 first-byte timeout 50ms를 사용합니다.
- Vended 라우팅 로그는 전달을 보장하지 않습니다(best effort). 20~80초 늦게 순서 없이 도착하며 테스트 중 1건은 끝내 도착하지 않았습니다. 추세 분석에는 사용하되 건별 집계에는 사용하지 않습니다.
- Inference 메트릭은 `ApplicationSignals` namespace에 있습니다. `AWS/Bedrock-AgentCore`에는 Cedar와 identity 메트릭만 있습니다.
- aws-cdk-lib의 `CfnGatewayRule`에는 `MatchModels`, `Model`, `Fallback`이 없어서 이 속성이 조용히 빠집니다. rule을 raw `CfnResource`로 작성한 이유이며, synth 때 F3018 경고가 나옵니다.

## 운영 시 주의

- First-byte timeout은 Opus와 GPT가 180초, Sonnet과 GPT 6 Luna가 120초, Haiku가 60초입니다. 비스트리밍 응답은 생성이 끝나야 첫 바이트가 나가므로 클라이언트가 스트리밍을 사용하면 지연을 더 빨리 감지합니다.
- 스트림이 시작된 뒤에는 fallback하지 않습니다. 첫 바이트 이후에 실패하면 클라이언트가 다시 요청해야 합니다.
- Fallback 시도마다 gateway 호출(invocation)로 과금됩니다. 회로 차단기가 열리면 장애 중인 primary를 건너뜁니다.
- GPT가 fallback하는 동안에는 데이터가 us-east-1로 갑니다.
- Rate limit은 token bucket 방식이라 순간적으로 분당 한도를 넘는 요청이 통과할 수 있습니다.
- `matchPrincipals` 조건은 IAM principal만 매칭하므로 JWT 기반인 이 gateway에서는 사용하지 않습니다.

## 정리

```bash
npx cdk destroy --all
aws secretsmanager delete-secret --secret-id llm-gateway/anthropic-api-key --region ap-northeast-2   # 사전 조건 secret
```
