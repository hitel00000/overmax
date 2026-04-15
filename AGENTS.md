# Agent Overview

이 에이전트는 DJMAX RESPECT V 오버레이 기반 추천 시스템의
정확도 개선, 성능 최적화, 안정성 향상을 목표로 한다.

---

# Primary Goals

- 인식 정확도 향상 (song / mode / difficulty / rate)
- 인게임 성능 영향 최소화
- 안정적인 상태 전이 (verified pipeline 유지)

---

# Context Usage Policy

- context.md를 현재 시스템 상태의 단일 source of truth로 사용한다
- context.md에 명시된 제약 조건을 절대 위반하지 않는다
- context.md에 없는 시스템은 존재한다고 가정하지 않는다

---

# Decision Policy

## 성능 vs 정확도

- 인게임 성능 영향이 있는 경우:
  → 정확도보다 성능을 우선한다

- 선곡 화면에서만 실행되는 로직:
  → 정확도 우선

---

## 인식 로직 수정

- 기존 파이프라인 (verified flow)을 깨지 않는 선에서 개선
- 단일 프레임 판단보다 history 기반 접근 우선
- OCR은 fallback 또는 검증 용도로만 사용

---

## 추천 시스템

- 현재 구조 (floor 기반)는 유지
- 새로운 기준 추가 시:
  → 기존 정렬 기준을 깨지 않도록 보완 방식으로 적용

---

# Constraints

- 메모리 접근 / 인젝션 금지
- 화면 캡처 기반 유지
- Python + 현재 라이브러리 스택 유지
- 실시간 처리 성능 저하 금지

---

# Failure Handling

- 확실하지 않은 경우:
  → 결과를 보류하거나 verified=False 유지

- 복수 해석 가능:
  → 조건별로 분리해서 제시

- 정보 부족:
  → 최소 질문만 생성 (1~2개)

---

# Output Format

기술 제안 시 반드시 다음 구조를 따른다:

1. 문제 정의
2. 원인 분석
3. 해결 방법 (옵션별)
4. 트레이드오프
5. 추천안

---

# Prohibited Actions

- 근거 없는 성능 개선 주장 금지
- 전체 리팩토링 제안 금지 (요청 시 제외)
- 기존 파이프라인 무시 금지

---

# Code Philosophy

## 1. Size & Structure Constraints (Hard Rules)

- **Function length ≤ 50 lines**
  - 한 번에 이해 가능한 단위 유지

- **File size ≤ 500 lines**
  - 초과 시 반드시 분리

- **One primary class per file**
  - 보조 클래스/함수는 허용하되, “주 책임”은 하나만 유지

- **~10 functions per file (soft limit)**
  - 초과 시 구조 재검토

> These limits exist to reduce cognitive load and improve long-term maintainability.

---

## 2. Readability Standard (Core Principle)

코드는 다음 조건을 만족해야 한다:

- **훈련된 사람이 빠르게 스캔해서 이해 가능할 것**
- 함수 하나는 아래 질문에 즉시 답할 수 있어야 한다:
  - 무엇을 하는가?
  - 왜 존재하는가?

### Guidelines

- 네이밍만으로 의도를 설명할 수 있어야 한다
- 주석은 “무엇”이 아니라 **“왜”**를 설명할 때만 사용
- 코드 흐름은 위에서 아래로 자연스럽게 읽혀야 한다

---

## 3. Decomposition Rules

다음 조건 중 하나라도 만족하면 **반드시 분리**:

- 함수가 50줄 초과
- 서로 다른 추상화 레벨이 혼재됨  
  (예: 비즈니스 로직 + low-level 처리)
- 동일 패턴이 2회 이상 반복됨

### Heuristic

> “한 눈에 안 들어오면 이미 너무 크다”

---

## 4. Decomposition Guardrail (Important)

> **분해는 가독성을 개선할 때만 수행한다.**

다음은 금지한다:

- 단순히 줄 수를 줄이기 위한 함수 분리
- 흐름을 끊는 과도한 abstraction
- 의미 없는 wrapper/helper 함수 남발

목표는 “작게 나누는 것”이 아니라  
**“이해하기 쉽게 만드는 것”**이다.

---

## 5. Complexity Guidelines

- **Cyclomatic complexity ≤ 10 권장**
- 중첩 depth는 3 이상 지양

복잡도가 증가할 경우:

- early return 사용
- 조건문 분해
- 전략 패턴 또는 매핑 구조 고려

---

## 6. Exceptions (Explicitly Allowed)

다음 경우에는 규칙을 완화할 수 있다:

- 성능 최적화가 필요한 hot path
- 외부 API / 프로토콜과 1:1 대응되는 코드
- auto-generated 코드

단, 반드시:

- 이유를 주석으로 명시
- 영향 범위를 최소화

---

## 7. Review Criteria (Enforcement)

PR 리뷰 시 다음을 확인한다:

- [ ] 함수 길이 제한 준수 여부
- [ ] 파일 크기 제한 준수 여부
- [ ] 단일 책임 원칙 유지 여부
- [ ] 30초 내 이해 가능한가
- [ ] 과도한 분해 또는 부족한 분해 여부

---

## 8. Anti-Patterns

다음 패턴은 지양한다:

- “나중에 나눌 예정” 상태로 커밋
- 의미 없는 유틸 함수 분리
- 지나치게 generic한 abstraction
- 한 함수에서 여러 책임 수행
- 읽기 흐름을 끊는 과도한 함수 호출 체인

---

## 9. Philosophy Summary

- 작게 나누되, **의미 있게 나눈다**
- 규칙보다 중요한 것은 **읽는 경험**
- 코드는 작성하는 것이 아니라 **읽히는 것**
