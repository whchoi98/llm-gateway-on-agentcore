# Security / 보안 구현 상세

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

### 1. Overview
<!-- TODO: 1-3 sentences on what the security layer does and why it exists. -->

### 2. Components
| Component | Path | Purpose |
|---|---|---|
| Inbound auth | `lib/constructs/inbound-auth.ts` | Cognito user pool, per-team M2M clients, scopes |
| Cedar policies | `lib/policy-stack.ts` | invoke scope, premium-only models, output-token caps |
| Guardrail | `lib/constructs/guardrail-interceptor.ts` | Bedrock Guardrail (Standard tier) and interceptor IAM |
| 1P key setup | `scripts/set-cponaws-key.sh` | Verifies and stores the CPonAWS key outside the stack |
| Gateway IAM role | `lib/llm-gateway-stack.ts` | Least-privilege execution role (per-model ARNs) |

### 3. Key Decisions
<!-- TODO: list 3-5 decisions or link to docs/decisions/ADR-*.md -->

### 4. Code Pointers
<!-- TODO: 3-7 entries; paths must be valid (checked by /sync-docs) -->
- `lib/policy-stack.ts` -- Cedar statements with the required has guards
- `lambda/interceptor/index.py` -- guardrail call, dialect check, premium check for InvokeModel
- `lib/constructs/inbound-auth.ts` -- JWT issuer, scopes, and team credential secrets

### 5. Cross-references
<!-- TODO -->
- Related modules:
- Related ADRs:
- Related runbooks:

---

<a id="korean"></a>

# 한국어

### 1. 개요
<!-- TODO: 보안 계층이 무엇을 하는지, 왜 존재하는지 1-3 문장으로. -->

### 2. 구성요소
| 구성요소 | 경로 | 목적 |
|---|---|---|
| Inbound auth | `lib/constructs/inbound-auth.ts` | Cognito user pool, 팀별 M2M client, scope |
| Cedar policies | `lib/policy-stack.ts` | invoke scope, premium 전용 모델, 출력 토큰 한도 |
| Guardrail | `lib/constructs/guardrail-interceptor.ts` | Bedrock Guardrail(Standard tier)와 interceptor IAM |
| 1P key setup | `scripts/set-cponaws-key.sh` | CPonAWS 키를 검증해 스택 밖에 저장 |
| Gateway IAM role | `lib/llm-gateway-stack.ts` | 최소 권한 실행 role(모델별 ARN) |

### 3. 주요 결정
<!-- TODO: 3-5개 결정 나열 또는 docs/decisions/ADR-*.md 링크 -->

### 4. 코드 포인터
<!-- TODO: 3-7개 항목; 경로는 실재해야 함 (/sync-docs가 점검) -->
- `lib/policy-stack.ts` -- 필수 has 가드가 들어간 Cedar 문
- `lambda/interceptor/index.py` -- 가드레일 호출, dialect 검사, InvokeModel premium 검사
- `lib/constructs/inbound-auth.ts` -- JWT 발급자, scope, 팀 자격증명 secret

### 5. 상호 참조
<!-- TODO -->
- 관련 모듈:
- 관련 ADR:
- 관련 런북:
