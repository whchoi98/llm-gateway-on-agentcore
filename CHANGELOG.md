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

### Added
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

---

<a id="korean"></a>

# 한국어

이 프로젝트의 모든 주요 변경 사항은 이 파일에 기록됩니다.
이 문서는 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)를 기반으로 하며,
[Semantic Versioning](https://semver.org/spec/v2.0.0.html)을 따릅니다.

## [Unreleased]

### Added
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
