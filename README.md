# Overmax

DJMAX RESPECT V 선곡 화면에서 V-Archive 기반 비공식 난이도 정보를 오버레이로 보여주는 도구입니다.

메모리 읽기/인젝션 없이 **창 추적 + 화면 캡처 + 이미지 매칭/OCR** 방식으로 동작합니다.

---

## 현재 상태

| 기능 | 상태 |
|---|---|
| 선곡화면 감지 | `FREESTYLE` 로고 OCR + 히스토리/히스테리시스 |
| 곡 감지 | 재킷 이미지 매칭 (ImageDB — perceptual hash + HOG + ORB) |
| 버튼 모드 감지 | 픽셀 색상 분류 (4B/5B/6B/8B) |
| 난이도 감지 | 패널 밝기 비교 |
| Rate 자동 수집 | Windows OCR → RecordDB (SQLite) 저장 |
| 유사 난이도 추천 | floor 기준 ±0 범위, rate 포함 정렬 |
| 단일 인스턴스 | Windows named mutex |
| 오버레이 위치 저장 | `cache/overlay_position.json` |
| Steam ID 감지 | loginusers.vdf 파싱, 창 발견 시 자동 갱신 |
| 디버그 창 | 모듈별 색상 로그, ROI 표시 토글 |

---

## 요구사항

- Windows 10 1809 이상 (64bit) — Windows OCR 필수
- DJMAX RESPECT V (Steam)
- Python 3.10+ (소스 실행 시)

---

## 실행

### 소스 실행

```bash
git clone https://github.com/yourname/overmax.git
cd overmax
pip install -r requirements.txt
python main.py
```

- `songs.json`은 없으면 V-Archive API에서 자동 다운로드됩니다 (`cache/` 저장).
- 이미 실행 중인 인스턴스가 있으면 새 인스턴스는 즉시 종료됩니다.

### 빌드

```bat
build.bat
```

디버그 빌드(콘솔 창 표시):

```bat
build.bat --debug
```

빌드 결과물: `dist\overmax\` 폴더 전체를 배포합니다.

---

## 이미지 DB 구축 및 배포

재킷 이미지 매칭을 위한 `image_index.db`는 빌드에 번들되지 않으며 별도로 배포됩니다.

### DB 직접 구축 (개발자)

```bash
python -m detection.image_db
```

대화형 CLI에서:
- **폴더 일괄 추가**: 재킷 이미지 폴더 지정 → 파일명 stem을 `song_id`로 사용 (숫자 파일명만 허용)
- **단일 이미지 추가**: `song_id` + 파일 경로 직접 지정
- 같은 `song_id` 재등록 시 upsert(갱신)

구축된 `cache/image_index.db`를 릴리즈에 첨부합니다.

### 사용자 배치

배포된 `image_index.db`를 `<실행파일 위치>/cache/image_index.db`에 넣으면 됩니다.

DB 없이 실행하면 이미지 매칭 없이 동작합니다 (인식 불가).

---

## 주요 설정

설정 파일: `settings.json` (없으면 `settings.py` 기본값 사용)

| 섹션 | 키 | 설명 |
|---|---|---|
| `screen_capture` | `logo_*` | 선곡화면 로고 ROI |
| | `freestyle_on/off_ratio` | 히스테리시스 on/off 임계값 |
| | `freestyle_on/off_min_samples` | 판정 최소 샘플 수 |
| `jacket_matcher` | `similarity_threshold` | 재킷 매칭 최소 유사도 |
| | `jacket_*_start/end` | 재킷 ROI 비율 좌표 |
| `mode_diff_detector` | `history_size` | 모드/난이도 다수결 샘플 수 |
| `varchive` | `fuzzy_threshold` | 퍼지 곡명 매칭 최소 점수 |

---

## 단축키

| 키 | 동작 |
|---|---|
| `F3` | 오버레이 표시/숨김 |

트레이 아이콘 더블클릭으로도 오버레이를 토글할 수 있습니다.  
트레이 우클릭 메뉴에서 디버그 창을 열 수 있습니다.

---

## 프로젝트 구조

```
overmax/
├── main.py                      # 진입점, 컴포넌트 조립
├── settings.py                  # 설정 로더 (기본값 + settings.json 병합)
├── settings.json                # 사용자 설정
├── constants.py                 # 중앙 상수 관리
├── runtime_patch.py             # PyInstaller 환경 경로 패치
│
├── capture/
│   ├── window_tracker.py        # 게임 창 위치/크기 추적
│   ├── screen_capture.py        # 캡처, OCR, 인식 파이프라인
│   └── helpers.py               # 캡처 파이프라인 공용 함수
│
├── core/
│   ├── game_state.py            # GameSessionState (공유 상태 모델)
│   └── global_hotkey.py         # Windows 전역 단축키 (RegisterHotKey)
│
├── data/
│   ├── varchive.py              # V-Archive 데이터 로드/검색
│   ├── record_db.py             # 플레이 기록 로컬 캐시 (SQLite)
│   ├── recommend.py             # 유사 난이도 추천
│   └── steam_session.py         # Steam ID 조회
│
├── detection/
│   ├── image_db.py              # 재킷 이미지 특징 DB
│   ├── image_db_cli.py          # ImageDB 관리 CLI
│   └── mode_diff.py             # 버튼 모드 / 난이도 감지
│
├── overlay/
│   ├── controller.py            # 오버레이 컨트롤러 (이벤트 → Qt 시그널)
│   ├── window.py                # PyQt6 오버레이 메인 창
│   ├── debug_window.py          # 디버그 로그 창
│   └── ui/
│       ├── pattern_view.py      # 난이도 카드 위젯 (DiffCard, ButtonModePanel)
│       ├── recommend_view.py    # 추천 패턴 행 위젯 (PatternRow)
│       └── navigation.py        # ROI 디버그 오버레이 (RoiOverlayWindow)
│
├── test/
│   └── overlay_tester.py        # 게임 영상 재생 테스트 도구
│
├── overmax.spec                 # PyInstaller 스펙
├── build.bat                    # 빌드 스크립트
├── version_info.txt             # EXE 버전 정보
├── CONTEXT.md                   # 개발자 컨텍스트 메모
└── AGENTS.md                    # 에이전트 행동 원칙
```

---

## 남은 개발 과제

1. **인식 정확도 향상**
   - 버튼 모드 색상 샘플 보강 및 임계값 튜닝
   - Rate OCR 좌표를 비율 기반으로 전환 (현재 1920×1080 픽셀 고정)
   - Steam 계정 전환 시 steam_id 갱신 안정화

2. **성능 최적화**
   - ImageDB 인메모리 캐시 도입
   - 빌드 결과물 크기 축소
   - OCR 업스케일/이진화 성능 프로파일링

3. **기능 추가**
   - DLC 필터링
   - 이미지 DB 빌드 파이프라인 자동화 (릴리즈 첨부)

---

## 데이터 출처

- [V-Archive](https://v-archive.net)

---

## 라이선스

MIT