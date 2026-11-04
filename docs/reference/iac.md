# Infrastructure as Code / IaC 구현 상세

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

### 1. Overview
<!-- TODO: 1-3 sentences on what the IaC layer does and why it exists. -->

### 2. Components
| Component | Path | Purpose |
|---|---|---|
| CDK app | `bin/app.ts` | Entry point: LlmGatewayStack and LlmGatewayPolicyStack in ap-northeast-2 |
| Configuration | `lib/config.ts` | Single source of truth for models, fallbacks, teams, and limits |
| Core stack | `lib/llm-gateway-stack.ts` | Gateway, targets, routing rules, rate limits, outputs |
| Policy stack | `lib/policy-stack.ts` | Cedar policies, deployed after the core stack |
| CDK settings | `cdk.json` | App command and feature flags |

### 3. Key Decisions
<!-- TODO: list 3-5 decisions or link to docs/decisions/ADR-*.md -->

### 4. Code Pointers
<!-- TODO: 3-7 entries; paths must be valid (checked by /sync-docs) -->
- `lib/llm-gateway-stack.ts` -- rules emitted as raw CfnResource, and the chain() creation order
- `lib/config.ts` -- the MODELS list that every rule, IAM statement, and rate-limit entry derives from
- `bin/app.ts` -- context flags policyMode, enable1p, alarmEmail

### 5. Cross-references
<!-- TODO -->
- Related modules:
- Related ADRs:
- Related runbooks:

---

<a id="korean"></a>

# 한국어

### 1. 개요
<!-- TODO: IaC 계층이 무엇을 하는지, 왜 존재하는지 1-3 문장으로. -->

### 2. 구성요소
| 구성요소 | 경로 | 목적 |
|---|---|---|
| CDK app | `bin/app.ts` | 진입점: ap-northeast-2의 LlmGatewayStack과 LlmGatewayPolicyStack |
| Configuration | `lib/config.ts` | 모델, fallback, 팀, 한도의 단일 정의 위치 |
| Core stack | `lib/llm-gateway-stack.ts` | Gateway, target, 라우팅 rule, rate limit, 출력값 |
| Policy stack | `lib/policy-stack.ts` | Core 스택 다음에 배포되는 Cedar 정책 |
| CDK settings | `cdk.json` | 앱 실행 명령과 feature flag |

### 3. 주요 결정
<!-- TODO: 3-5개 결정 나열 또는 docs/decisions/ADR-*.md 링크 -->

### 4. 코드 포인터
<!-- TODO: 3-7개 항목; 경로는 실재해야 함 (/sync-docs가 점검) -->
- `lib/llm-gateway-stack.ts` -- raw CfnResource로 만든 rule과 chain() 생성 순서
- `lib/config.ts` -- 모든 rule, IAM 문, rate limit 항목이 파생되는 MODELS 목록
- `bin/app.ts` -- context 플래그 policyMode, enable1p, alarmEmail

### 5. 상호 참조
<!-- TODO -->
- 관련 모듈:
- 관련 ADR:
- 관련 런북:
