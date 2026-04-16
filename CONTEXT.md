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
→ GameSessionState (verified)  
→ OverlayController  
→ OverlayWindow (PyQt6)

---

# Detection Pipeline

## Primary Signals

- 선곡화면 감지: FREESTYLE 로고 OCR + 히스토리/히스테리시스
- 곡 인식: 재킷 이미지 매칭 (ImageDB — perceptual hash + HOG + ORB)
- 버튼 모드: 픽셀 색상 기반 (5×5 평균 BGR vs 대표색)
- 난이도: 패널 영역 평균 밝기 비교 (4개 패널 중 최대 brightness)

## Secondary Signals

- OCR (Windows OCR):
  - FREESTYLE 로고 검증
  - Rate 수집 (RecordDB 저장용)
  - fallback은 현재 비활성

## State Handling

- hysteresis 기반 선곡화면 판정 (on/off 비율 별도 임계값)
- MODE_DIFF_HISTORY 연속 동일 프레임 기반 안정화
- verified flag 기반 commit 구조 (GameSessionState.is_stable)
- 이탈 감지: 후반 히스토리 비율 하락 시 skip

---

# Current State

- 전체 파이프라인 정상 동작
- 패키지 구조 정리 완료: `capture/`, `core/`, `data/`, `detection/`, `overlay/`
- verified 기반 상태 전이 안정적
- 추천 시스템 (floor 기반) 구현 완료
- Rate OCR → RecordDB 자동 수집 구현 완료
- OCR은 로고 감지 + Rate 수집 용도로만 사용
- 단일 인스턴스 보장 (Windows named mutex)
- 오버레이 위치 저장/복원 (`cache/overlay_position.json`)
- Steam ID 기반 사용자 식별 (로그인 세션 자동 감지)

---

# Problems

## 1. 인식 정확도

- 버튼 모드:
  - 대표색 고정 → 환경/감마 변화에 취약
  - 거리 임계값(60) 튜닝 필요

- 난이도:
  - 밝기 기반이라 UI 전환 중 오인식 가능
  - margin 임계값(15.0) 환경에 따라 불안정

- Rate OCR:
  - 1920×1080 고정 픽셀 좌표 사용 중 (비율 미전환)
  - 전처리 실패 시 force_invert 재시도 1회만

---

## 2. 성능 리스크

- OCR 호출 비용: 로고 + Rate 각 독립 호출
- ImageDB 검색: 전체 rows 순회 (인메모리 캐시 미도입)
- 추가 처리(녹화 등) 시 프레임 저하 가능성

---

## 3. 사용자 식별

- Steam ID: loginusers.vdf 파싱, 멀티 계정 전환 시 갱신 타이밍 불안정

---

# Failed Approaches

## OCR Hybrid (버튼 모드/난이도 검증)

- 목표: 픽셀 기반 감지 보조
- 결과: 런타임에서 인식 불안정 (빈번한 실패)
- 원인: 작은 텍스트, low contrast, anti-aliasing, 캡처 품질 차이
- 결론: primary signal 불가 → verifier/fallback 용도 제한
- 재검토 조건: ROI 정규화, 멀티프레임 처리 도입 후

---

# Tried Approaches

- 이미지 매칭 + OCR fallback 구조
- hysteresis 기반 상태 안정화 (on/off 비율 분리)
- OCR 전처리: upscale(×3), OTSU binarization, force_invert 재시도
- Rate 0.0 → 미플레이로 간주, DB 저장 skip

---

# Important Invariants

- verified=True (is_stable)일 때만 상태 commit
- detection → verification → commit 흐름 유지
- 단일 프레임 결과에 의존하지 않음
- 동일 (song_id, mode, diff) 조합 Rate 수집 중복 제한 (_recorded_states)
- Rate 0.0은 저장하지 않음

---

# Debug Strategy

- DebugController: 모듈별 색상 구분 로그, 필터/일시정지/지우기
- RoiOverlayWindow: 게임 화면 위 ROI 경계 실시간 표시 (디버그 창 연동)
- 런타임 OCR 입력 품질 검증 필요 (스틸샷 vs 런타임 차이)

---

# Next Focus

- Rate OCR 좌표 비율 기반으로 전환 (현재 1920×1080 픽셀 고정)
- 버튼 모드 샘플 보강 및 임계값 튜닝
- ImageDB 인메모리 캐시 도입
- DLC 필터링 기능 (예정)
- 빌드 결과물 크기 축소