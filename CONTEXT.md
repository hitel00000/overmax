# CONTEXT.md

Overmax 현재 구현/운영 기준 메모입니다.

---

## 제품 목표

- DJMAX RESPECT V 선곡 화면에서 현재 곡 난이도 정보를 실시간 오버레이
- 메모리 접근/인젝션 없이 화면 기반 인식으로 동작

---

## 현재 아키텍처

`main.py`
- 단일 인스턴스 락 (Windows named mutex)
- `WindowTracker`: 게임 창 탐지/위치 추적
- `ScreenCapture`: 선곡 판정 + 재킷 매칭 + OCR fallback
- `OverlayController` (Qt 메인 스레드): 오버레이 UI/트레이/ROI
- `DebugController`: 로그 창

`image_db.py`
- 재킷 이미지 인덱스 DB (SQLite)
- 특징: pHash/dHash/aHash(OpenCV/NumPy 구현), HOG(OpenCV), ORB
- `image_id(song_id)` unique 인덱스 + upsert 등록

`image_db_cli.py`
- DB 조회/추가/삭제 대화형 관리 도구

`varchive.py`
- songs 데이터 로드/캐시/API 다운로드
- 곡명 exact + fuzzy 검색
- 동명이곡 composer 기반 분기

---

## 인식 파이프라인

1. 선곡 화면 판정
- 로고 OCR(`FREESTYLE`) + 히스토리 다수결/히스테리시스
- 부분 인식(`REESTYLE`, `EESTYL` 등) 허용 로직 적용

2. 곡 감지
- 1순위: 재킷 이미지 매칭 (`ImageDB.search`)
- 2순위: OCR fallback (title/composer)

3. V-Archive 매칭
- `search_by_id` 또는 `search(title, composer)`
- 실패 시 오버레이 UI 초기화(스테일 정보 제거)

---

## UI/상태 처리

- 오버레이는 선곡 화면에서만 표시
- 오버레이 위치 저장/복원 (`overlay.position_file`)
- 매칭 실패/빈 OCR 시 기본 상태(`곡을 선택하세요`)로 복귀
- ROI 오버레이는 디버그 용도로 토글

---

## 설정 포인트 (핵심)

- `screen_capture`
  - `logo_*`, `freestyle_*`
  - `left_title_*`, `right_title_*`, `left_composer_*`
- `jacket_matcher`
  - `similarity_threshold`, `match_interval_sec`, `jacket_*`
- `varchive`
  - `fuzzy_threshold` (단일 fuzzy 제어값)

---

## 최근 반영된 변경

- 재킷 매칭 성공 상태 유지로 불필요한 OCR fallback 감소
- 로고 OCR 부분 인식 허용으로 선곡 판정 안정화
- `song_id` 기준 ImageDB 조회/삭제, unique 인덱스 도입
- `image_db.py` 실행 시 대화형 CLI 진입
- HOG/Hash 구현을 OpenCV+NumPy로 정리
  - `scikit-image`, `Pillow`, `ImageHash` 의존 제거
- PyInstaller spec/requirements 정리
- 단일 인스턴스 실행 보장
- 재킷 수동 등록(F10) 기능 제거 (일반 사용자 입력 경로 부재)

---

## 다음 개발 우선순위

1. 현재 선택된 버튼 모드/난이도 감지
2. 곡명 OCR 제거(재킷/직접 선택 감지 기반으로 전환)
3. 선택 패턴과 유사 난이도 추천
4. 기능 안정화 후 경량화
- 패키지 크기
- 시작 시간
- 런타임 메모리/CPU

---

## 리스크/메모

- 인식 알고리즘 변경(HOG/Hash) 이후 기존 재킷 인덱스와 점수 분포 차이가 있을 수 있음
- 필요 시 인덱스 재생성 권장
