# Current Goal

- DJMAX RESPECT V 선곡 화면에서  
  V-Archive 기반 난이도 및 추천 정보를 실시간 오버레이로 제공

---

# Core Constraints

- 메모리 접근 / 프로세스 인젝션 금지
- 화면 캡처 기반 처리 유지
- Python 환경 유지
- 인게임 성능 영향 최소화 (최우선)

---

# Current Architecture (Simplified)

Pipeline:

WindowTracker  
→ ScreenCapture  
→ Detection Pipeline  
→ Verification  
→ Overlay

---

# Detection Pipeline

## Primary Signals

- 곡 인식: 이미지 매칭 (primary)
- 버튼 모드: 픽셀 색상 기반
- 난이도: 밝기 기반 (현재)

## Secondary Signals

- OCR:
  - verification 용도로 사용
  - 일부 fallback 용도 (제한적)

## State Handling

- hysteresis 기반 상태 안정화
- verified flag 기반 commit 구조

---

# Current State

- 전체 파이프라인 정상 동작
- verified 기반 상태 전이 안정적
- 추천 시스템 (floor 기반) 구현 완료
- OCR은 일부 verification에만 제한적으로 사용 중

---

# Problems

## 1. 인식 정확도

- 버튼 모드:
  - 색상 샘플 부족
  - 환경 변화에 취약

- 난이도:
  - 밝기 기반이라 UI 변화에 취약

- OCR:
  - 특정 문자열(SC 등) 인식 불안정

---

## 2. 성능 리스크

- OCR 호출 비용 부담
- 추가 처리(녹화 등) 시 프레임 저하 가능성

---

## 3. 사용자 식별

- Steam ID 기반 식별 불안정 가능성

---

# Failed Approaches

## OCR Hybrid (Windows OCR, SC 문자열)

- 목표:
  난이도/모드 판별 정확도 개선을 위해 OCR 결합 시도

- 결과:
  런타임 환경에서 OCR 결과가 불안정 (인식 실패 빈번)

- 관찰된 문제:
  - 동일 조건에서도 인식 성공/실패가 불규칙하게 발생
  - 일부 프레임에서 텍스트가 전혀 인식되지 않음

- 원인 가설:
  - Windows OCR의 작은 텍스트 처리 한계
  - low contrast / anti-aliasing 영향
  - 프레임 캡처 품질 차이 (scaling / compression)
  - 스틸샷 기반 검증과 실제 OCR 입력 간 불일치

- 검증 한계:
  - 전처리 결과를 스틸 이미지로만 확인
  - 실제 OCR 입력 이미지와 동일성 보장 불가

- 결론:
  Windows OCR은 현재 조건에서 primary signal로 사용하기 어려움  
  → verifier / fallback 용도로 제한

- 향후 재검토 조건:
  - ROI 정규화
  - 입력 이미지 안정성 확보
  - multi-frame 기반 처리 도입

---

# Tried Approaches

- 이미지 매칭 + OCR fallback 구조
- hysteresis 기반 상태 안정화
- OCR 전처리:
  - upscale
  - binarization

---

# Important Invariants

- verified=True일 때만 상태 commit
- detection → verification → commit 흐름 유지
- 단일 프레임 결과에 의존하지 않음
- 동일 조합(rate 등) 중복 처리 제한

---

# Debug Strategy

- OCR 입력 이미지 실시간 overlay 표시
- OCR ROI 이미지 dump (샘플 수집)
- OCR 결과 로그 및 성공률 기록
- 스틸샷 vs 런타임 입력 비교 검증

---

# Next Focus

- 난이도 감지 개선 (brightness → color / hybrid)
- 버튼 모드 분류 정확도 향상
- OCR 호출 최소화 및 안정화 전략
- 런타임 이미지 입력 품질 검증
