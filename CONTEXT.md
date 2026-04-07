# CONTEXT.md

Overmax 현재 구현 기준의 설계 메모입니다.

---

## 목표

- DJMAX Respect V 선곡화면에서 선택 곡 난이도 정보를 실시간 오버레이
- 메모리 접근/인젝션 없이 화면 캡처 + OCR만 사용

---

## 현재 아키텍처

`main.py`
- `WindowTracker` 스레드: 게임 창 탐지 및 위치/크기 변경 감지
- `ScreenCapture` 스레드: 선곡화면 판정 + 곡명/작곡가 OCR
- `OverlayController` (Qt 메인 스레드): 오버레이 UI, 트레이, ROI 디버그 오버레이
- `DebugController`: 로그 창 및 ROI 토글 버튼

스레드 간 UI 반영은 모두 Qt signal/slot 경유.

---

## 화면 판정 / OCR 로직

### 선곡화면 판정

- 로고 ROI OCR에서 `FREESTYLE` 키워드 인식
- 최근 프레임 버퍼 기반 다수결
- 히스테리시스 적용
  - ON은 빠르게
  - OFF는 느리게

주요 설정 키 (`screen_capture`):
- `logo_x_start/end`, `logo_y_start/end`
- `logo_ocr_keyword`, `logo_ocr_cooldown_sec`
- `freestyle_history_size`
- `freestyle_on_ratio`, `freestyle_on_min_samples`
- `freestyle_off_ratio`, `freestyle_off_min_samples`

### 곡명/작곡가 OCR

- 곡명: 좌측 패널 ROI + 우측 리스트 ROI를 동시에 OCR
- 후보 점수화 후 최종 곡명 선택
- 작곡가: 좌측 작곡가 ROI OCR
- 결과는 `(title, composer)` 형태로 전달

주요 설정 키:
- `left_title_*`
- `right_title_*`, `right_title_pad_px`
- `left_composer_*`

---

## DB 매칭 (varchive.py)

- 곡명 exact/fuzzy 검색
- 동명이곡은 composer 유사도로 분기
- 인덱스는 `title -> [song, ...]` 구조

---

## 오버레이/디버그

### 오버레이 위치

- 사용자가 드래그로 이동하면 위치 저장
- 다음 실행 시 복원
- 저장 파일: `overlay.position_file` (기본 `overlay_position.json`)

### ROI 표시

- 디버그 창 버튼으로 ON/OFF
- 게임 화면 위에 ROI 박스 라인 표시:
  - `LOGO`
  - `LEFT TITLE OCR`
  - `RIGHT TITLE OCR`
  - `COMPOSER OCR`

---

## 최근 변경 핵심

- `FREESTYLE` OCR 기반 선곡 판정으로 전환
- 프레임 버퍼 다수결 + 히스테리시스 추가
- 곡명 OCR 멀티 ROI(좌/우) + 작곡가 OCR 추가
- 동명이곡 composer 분기 추가
- ROI 디버그 오버레이 추가
- 오버레이 위치 저장/복원 추가
- 창 이동 시 ROI 오버레이 동기화 안정화 (UI 스레드 signal 경유)

---

## 남은 과제

- OCR 전처리 개선 (특수문자/다국어 혼합)
- 작곡가 OCR 오인식 보정 규칙
- 버튼 모드(4B/5B/6B/8B) 자동 감지
- 설정 UI 제공 (현재는 JSON 수동 편집)
