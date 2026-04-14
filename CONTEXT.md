# CONTEXT.md

Overmax 현재 구현/운영 기준 메모입니다.

---

## 제품 목표

- DJMAX RESPECT V 선곡 화면에서 현재 곡의 V-Archive 기반 비공식 난이도 정보를 실시간 오버레이
- 메모리 접근/인젝션 없이 창 추적 + 화면 캡처 + 이미지 매칭/OCR 방식으로 동작

---

## 현재 아키텍처

`main.py`
- 단일 인스턴스 락 (Windows named mutex)
- `WindowTracker` → `ScreenCapture` → `OverlayController` (Qt 메인 스레드) 순으로 조립
- `DebugController`: 디버그 로그 창 (PyQt6 별도 창, OverlayController.run() 이후 생성)
- Steam 세션: 게임 창 발견 시 `get_most_recent_steam_id()`로 Steam ID를 RecordDB에 주입

`window_tracker.py`
- `GetClientRect` + `ClientToScreen` 으로 타이틀바/테두리 제외한 실제 게임 클라이언트 영역 추적
- 비율 기반 좌표 계산 (`WindowRect.abs`, `region`)

`screen_capture.py`
- asyncio 단일 이벤트 루프 (스레드 내)로 프레임 처리
- **선곡화면 감지**: `FREESTYLE` 로고 OCR + 히스토리 다수결/히스테리시스 (부분 인식 허용)
- **곡 감지**: 재킷 이미지 매칭 1순위, OCR fallback 2순위 (현재 OCR fallback은 비활성 상태)
- **버튼 모드 감지**: `mode_diff_detector.detect_button_mode` — 좌상단 픽셀 클러스터 색상 분류
- **난이도 감지**: `mode_diff_detector.detect_difficulty` — 각 난이도 패널 영역 평균 밝기 비교
- **난이도 검증**: 감지된 난이도를 Windows OCR로 확인 (정/역방향 이진화 2회 시도, 퍼지 매칭 적용)
- **Rate OCR**: song_id + mode + diff 모두 확정 & 검증 완료 시 Rate 영역 OCR → RecordDB 저장
- OCR 엔진: Windows OCR (winrt), 3배 업스케일 + Otsu 이진화 + 패딩

`mode_diff_detector.py`
- 1920x1080 기준 픽셀 좌표를 비율로 변환하여 해상도 독립적으로 동작
- 버튼 모드: (82, 132) 기준 5×5 영역 평균 BGR → 최근접 대표색 분류 (임계 거리 60)
- 난이도: NM 기준 ROI (102~204, 492~510)에 120px 오프셋으로 HD/MX/SC 확장, 가장 밝은 패널 선택
  - 밝기 45 미만 전체 → None (곡 전환 중 판단)

`image_db.py`
- SQLite 기반 재킷 이미지 특징 저장 (pHash/dHash/aHash + HOG + ORB)
- 모든 해시/특징량을 OpenCV + NumPy로 구현 (scikit-image, Pillow, ImageHash 의존 없음)
- `image_id(song_id)` UNIQUE 인덱스 + upsert 등록
- 검색: 해시 거리로 top-K 추리기 → HOG 거리로 재정렬 → ORB Lowe's ratio test로 최종 결정
  - 가중치: hash_sim 0.45 + hog_sim 0.35 + orb_sim 0.20
- `image_db_cli.py` (`python -m image_db`): 테이블 조회/단건 조회/단건 추가/폴더 일괄 추가/단건 삭제

`varchive.py`
- songs 데이터 로드/캐시(24h TTL)/API 다운로드 (`https://v-archive.net/db/v2/songs.json`)
- 곡명 exact + fuzzy 검색 (rapidfuzz → difflib fallback)
- 동명이곡: composer 기반 분기

`record_db.py`
- SQLite 기반 플레이 기록 로컬 캐시
- PK: `(steam_id, song_id, button_mode, difficulty)` → `rate REAL`
- upsert: 기존 rate보다 높을 때만 갱신 (`MAX(rate, excluded.rate)`)
- `get_rate_map`, `get_bulk` 등 bulk 조회 API 제공

`recommend.py`
- 현재 패턴의 floor 값 기준 ±floor_range 내 패턴 추천
- floorName 유무로 비공식/공식 체계 자동 분기 (SC ↔ NHM 그룹 분리)
- 정렬: 기록 있음(rate 낮은 순) → 기록 없음(floor 낮은 순)

`overlay.py`
- 투명 Always-on-top 오버레이 창 (FramelessWindowHint + WA_TranslucentBackground)
- 드래그로 위치 이동, 위치 저장/복원 (`cache/overlay_position.json`)
- 상태 램프: 검증 완료(파란불, #00D4FF) / 검증 중(빨간불, #FF4B4B)
- verified=True 일 때만 패턴 데이터 및 추천 목록 갱신 (검증 중 UI 고정)
- 시스템 트레이 아이콘 + 컨텍스트 메뉴

`debug_window.py`
- 모듈별 색상 필터, 일시정지/지우기, ROI 표시 토글, 라인 수 상한(500)

---

## 인식 파이프라인 (상세)

```
[프레임]
  │
  ├─ 선곡화면 감지
  │    └─ FREESTYLE 로고 OCR + history(7) 다수결/히스테리시스
  │         on:  ≥3 샘플, ratio ≥0.60
  │         off: ≥7 샘플, ratio ≤0.35
  │
  ├─ [선곡화면 아님] → 대기
  │
  ├─ 재킷 이미지 매칭 (0.8초 간격)
  │    ├─ thumb diff로 이미지 변경 감지 (임계 2.5)
  │    ├─ 2.0초 강제 재체크
  │    └─ 결과: song_id (ImageDB)
  │         └─ 실패 → OCR fallback (현재 비활성)
  │
  ├─ 버튼 모드 / 난이도 감지 (매 프레임, history 3 다수결)
  │    ├─ 변경 감지 시 verified=False 알림
  │    └─ verified=False → 비동기 OCR 검증 태스크 실행
  │         ├─ 성공: verified=True 알림, Rate OCR 허용
  │         └─ 실패: verified=False 유지, 재시도
  │
  └─ Rate OCR (song_id + mode + diff 확정 & verified=True 조건)
       ├─ 같은 조합은 1.5초 내 재시도 안 함
       └─ rate > 0 → RecordDB.upsert (더 높은 값만 저장)
```

---

## 설정 포인트 (핵심)

`screen_capture`
- `logo_*`: 선곡화면 로고 ROI
- `freestyle_*`: 히스토리 히스테리시스 파라미터

`jacket_matcher`
- `similarity_threshold`: 재킷 매칭 허용 최소 유사도
- `match_interval_sec`, `jacket_force_recheck_sec`: 매칭 주기
- `jacket_change_threshold`: 썸네일 diff 임계값
- `jacket_*_start/end`: 재킷 ROI 비율

`mode_diff_detector` (settings.json 에만 존재)
- `interval_sec`, `history_size`, `color_tolerance`, `btn_mode_max_dist`

`varchive`
- `fuzzy_threshold`: rapidfuzz WRatio 최소 점수 (기본 80)

---

## 남은 개발 과제

### 1. 현재 상태 인식 정확도 향상
- 버튼 모드 감지: 대표색 샘플 보강, 임계 거리 튜닝 필요
- 난이도 감지: 밝기 기반의 한계 (패널 디자인/해상도 변화에 취약), 색상 기반 추가 검토
- 난이도 OCR 검증: SC 오인식 변종 목록 지속 보강 필요
- 선곡화면 판정: 로고 OCR만 의존 중 → 보조 앵커 추가 검토

### 2. 기록 저장(동기화) 정확도 향상
- Rate OCR 파싱 실패 케이스 보강 (소수점 OCR 오인식)
- steam_id: 게임 창 발견 시 1회만 갱신 → 계정 전환 시 미갱신 문제
- Rate 영역 좌표(현재 고정 픽셀 기반)를 비율 기반으로 전환 필요
- verified 조건을 더 엄격히 (현재: 난이도 텍스트 OCR만) — mode OCR 검증 추가 검토

### 3. 이미지 DB 빌드 및 배포
- `image_db_cli.py` (폴더 일괄 추가)로 재킷 이미지 → DB 구축
- `image_index.db` 는 빌드에 번들하지 않고 별도 배포 (릴리즈 첨부 파일)
- DB 없이 실행 시 OCR fallback 모드 (현재 fallback 비활성 — 재활성화 필요 여부 검토)
- 재킷 이미지 수집 방법 정의 필요 (Steam 설치 경로 자동 탐색 가능성)

### 4. 최적화 및 경량화
- PyInstaller 빌드 결과물 크기 측정 후 불필요 패키지 정리
- OCR 업스케일 배수(현재 3×) 및 임계화 로직 성능 프로파일링
- asyncio.sleep 간격 재검토 (OCR_INTERVAL 0.35s, IDLE 0.5s)
- ImageDB 검색: 매 호출마다 전체 rows fetchall → 인메모리 캐시 도입 검토

---

## 리스크 / 메모

- 게임 업데이트로 UI 레이아웃 변경 시 비율 좌표 재캘리브레이션 필요
- HOG/Hash 알고리즘 변경(scikit-image → OpenCV) 이후 기존 DB와 점수 분포 불일치 가능 → 인덱스 재생성 권장
- winrt OCR 엔진은 Windows 10 1809+ 필요, 언어팩 설치 상태에 따라 인식률 차이 있음
- Rate 영역 좌표가 현재 1920×1080 고정 픽셀 기반 (sx/sy 스케일 적용은 있으나 검증 부족)
