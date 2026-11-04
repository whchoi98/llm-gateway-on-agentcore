# Agent · LLM / Agent · LLM 구현 상세

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

### 1. Overview
<!-- TODO: 1-3 sentences on what the agent · LLM layer does and why it exists. -->

### 2. Components
| Component | Path | Purpose |
|---|---|---|
| Interceptor | `lambda/interceptor/index.py` | claude-auto routing, guardrail, per-team EMF metrics |
| CPonAWS proxy | `lambda/cponaws-proxy/index.mjs` | Streams Claude fallback traffic, adds the workspace header |
| Model routes | `lib/config.ts` | Claude and GPT routes, aliases, first-byte timeouts |
| Observability | `lib/constructs/observability.ts` | Routing-log metric filters, dashboard, alarms |
| Smoke tests | `scripts/smoke_test.py` | Live E2E checks, including failover drills and routing evidence |

### 3. Key Decisions
<!-- TODO: list 3-5 decisions or link to docs/decisions/ADR-*.md -->

### 4. Code Pointers
<!-- TODO: 3-7 entries; paths must be valid (checked by /sync-docs) -->
- `lib/config.ts` -- claude() and gpt() route factories and FAILOVER_DRILLS
- `lambda/interceptor/index.py` -- the request contract: base64 body, short-circuit responses
- `scripts/smoke_test.py` -- served-by checks and the routing-evidence query

### 5. Cross-references
<!-- TODO -->
- Related modules:
- Related ADRs:
- Related runbooks:

---

<a id="korean"></a>

# 한국어

### 1. 개요
<!-- TODO: Agent · LLM 계층이 무엇을 하는지, 왜 존재하는지 1-3 문장으로. -->

### 2. 구성요소
| 구성요소 | 경로 | 목적 |
|---|---|---|
| Interceptor | `lambda/interceptor/index.py` | claude-auto 라우팅, 가드레일, 팀별 EMF 메트릭 |
| CPonAWS proxy | `lambda/cponaws-proxy/index.mjs` | Claude fallback 트래픽 스트리밍, workspace 헤더 추가 |
| Model routes | `lib/config.ts` | Claude와 GPT route, alias, first-byte timeout |
| Observability | `lib/constructs/observability.ts` | 라우팅 로그 metric filter, 대시보드, 알람 |
| Smoke tests | `scripts/smoke_test.py` | failover drill과 라우팅 근거를 포함한 실환경 E2E 검사 |

### 3. 주요 결정
<!-- TODO: 3-5개 결정 나열 또는 docs/decisions/ADR-*.md 링크 -->

### 4. 코드 포인터
<!-- TODO: 3-7개 항목; 경로는 실재해야 함 (/sync-docs가 점검) -->
- `lib/config.ts` -- claude(), gpt() route 팩토리와 FAILOVER_DRILLS
- `lambda/interceptor/index.py` -- 요청 계약: base64 body, short-circuit 응답
- `scripts/smoke_test.py` -- 응답 주체 확인과 routing-evidence 쿼리

### 5. 상호 참조
<!-- TODO -->
- 관련 모듈:
- 관련 ADR:
- 관련 런북:
