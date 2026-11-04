# Changelog

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Claude Code works through the gateway: the interceptor rewrites `metadata.user_id`, which Claude Code sends as a JSON string, into the character set and 256-character limit of Bedrock request metadata (it was rejected with 400)

### Added
- CloudWatch dashboard: fallbacks by model, interceptor denials by reason (new `Denied` EMF metric), Bedrock tokens per minute and throttles per primary model, and span tables from `aws/spans`; Active X-Ray tracing on the interceptor and CPonAWS proxy Lambdas
- Add an LLM gateway on Amazon Bedrock AgentCore Gateway in ap-northeast-2 with one `/inference` endpoint for the Anthropic, OpenAI, and Bedrock SDKs
- Add Bedrock Global CRIS primary routes for Claude 5.5 and GPT 6.x
- Add Claude fallback to Claude Platform on AWS through a streaming Lambda proxy
- Add GPT fallback to Bedrock Mantle in us-east-1
- Add Cognito team clients with per-team and per-model rate limits
- Add Cedar policies for the invoke scope, premium-only models, and output-token caps
- Add a Bedrock Guardrail applied by the REQUEST interceptor on every path
- Add aliases, the `claude-auto` dynamic route, a weighted A/B experiment, and failover drills
- Add vended logs and traces, fallback metric filters, a CloudWatch dashboard, and alarms
- Add live smoke tests and English and Korean diagrams: architecture, request flow, fallback sequence, and deploy order

### Security
- InvokeModel is limited to the premium scope: gateway token rate limits do not count it and Cedar cannot see its model ID. The interceptor fails closed on these paths: it URL-decodes the model ID, reduces an inference-profile ARN to the model it names, and refuses undeclared models and any `/model/` operation other than invoke
- Per-model TPM limits drop to at most 80% of the account's Global cross-Region TPM quotas (Sonnet, GPT 6.1 Sol, 6.1 Terra, 6 Astra, 6 Sol, 6 Luna), and the `quota-headroom` smoke check compares them with the live quotas
- The Claude Platform on AWS workspace ID moved out of the repository into the SSM parameter `/llm-gateway/anthropic-workspace-id`, which `scripts/set-cponaws-key.sh` writes and CloudFormation resolves at deploy time

---

<a id="korean"></a>

# 한국어

이 프로젝트의 모든 주요 변경 사항은 이 파일에 기록됩니다.
이 문서는 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)를 기반으로 하며,
[Semantic Versioning](https://semver.org/spec/v2.0.0.html)을 따릅니다.

## [Unreleased]

### Fixed
- Claude Code가 gateway를 거쳐 동작합니다. Claude Code는 `metadata.user_id`를 JSON 문자열로 보내는데, Bedrock request metadata의 허용 문자와 256자 제한에 걸려 400으로 거부되었습니다. 이제 interceptor가 이 값을 허용 형식으로 바꿉니다.

### Added
- CloudWatch 대시보드에 모델별 fallback, 사유별 interceptor 거부(새 `Denied` EMF 메트릭), primary 모델별 Bedrock 분당 토큰과 throttle, `aws/spans` 기반 span 표를 추가하고, interceptor와 CPonAWS proxy Lambda에 X-Ray Active tracing을 켰습니다.
- Anthropic, OpenAI, Bedrock SDK용 `/inference` 단일 엔드포인트를 갖춘 ap-northeast-2 Amazon Bedrock AgentCore Gateway 기반 LLM Gateway 추가
- Claude 5.5와 GPT 6.x의 Bedrock Global CRIS primary route 추가
- 스트리밍 Lambda 프록시를 거치는 Claude Platform on AWS Claude fallback 추가
- us-east-1 Bedrock Mantle GPT fallback 추가
- 팀별, 모델별 rate limit을 갖춘 Cognito 팀 client 추가
- invoke scope, premium 전용 모델, 출력 토큰 한도용 Cedar 정책 추가
- 모든 경로에 적용되는 REQUEST interceptor 기반 Bedrock Guardrail 추가
- Alias, `claude-auto` 동적 route, 가중치 A/B 실험, failover drill 추가
- Vended log와 trace, fallback metric filter, CloudWatch 대시보드, 알람 추가
- 실환경 smoke test와 영문, 한국어 다이어그램(아키텍처, 요청 흐름, fallback 시퀀스, 배포 순서) 추가

### Security
- InvokeModel을 premium scope에만 허용합니다. gateway token rate limit에 집계되지 않고 Cedar가 model ID를 볼 수 없기 때문입니다. 이 경로에서 interceptor는 fail-closed로 동작합니다. model ID를 URL 디코딩하고 inference-profile ARN은 가리키는 모델로 줄이며, 미등록 모델과 invoke 외의 `/model/` 경로는 거부합니다.
- 모델별 TPM 한도를 이 계정 Global cross-Region TPM quota의 80% 이하로 낮췄습니다(Sonnet, GPT 6.1 Sol, 6.1 Terra, 6 Astra, 6 Sol, 6 Luna). `quota-headroom` smoke 검사가 현재 quota와 비교합니다.
- Claude Platform on AWS workspace ID를 저장소에서 빼서 SSM 파라미터 `/llm-gateway/anthropic-workspace-id`로 옮겼습니다. `scripts/set-cponaws-key.sh`가 이 파라미터를 쓰고, CloudFormation이 배포할 때 값을 채웁니다.
