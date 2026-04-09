# Overmax

DJMAX RESPECT V 선곡 화면에서 V-Archive 기반 난이도 정보를 오버레이로 보여주는 도구입니다.

메모리 읽기/인젝션 없이 **창 추적 + 화면 캡처 + OCR/이미지 매칭** 방식으로 동작합니다.

---

## 현재 상태 (요약)

- 선곡 화면 감지: `FREESTYLE` 로고 OCR + 히스토리/히스테리시스
- 곡 감지 우선순위
  - 1) 재킷 이미지 매칭 (`image_db.py`)
  - 2) OCR fallback (곡명/작곡가)
- V-Archive 매칭: exact + fuzzy (`fuzzy_threshold` 단일 설정)
- 매칭 실패/OCR 실패 시 오버레이 UI를 초기 상태로 복귀
- 단일 인스턴스 실행 보장 (중복 실행 방지)
- 디버그 로그/ROI 오버레이
- 재킷 수동 등록 기능 제거 (사용자 입력 경로 부재)

---

## 요구사항

- Windows 10/11 (64bit)
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

- `songs.json`은 필요 시 V-Archive API에서 다운로드되어 `cache/`에 저장됩니다.
- 이미 앱이 실행 중이면 새 인스턴스는 종료됩니다.

### 빌드

```bat
build.bat
```

---

## Image DB 관리 CLI

`image_db.py`를 모듈로 실행하면 대화형 관리 도구가 실행됩니다.

```bash
python -m image_db
```

기능:
- 테이블 조회
- `song_id` 기준 단일 항목 조회
- 단일 이미지 추가 (`song_id` + 파일 경로)
- 폴더 일괄 추가 (파일명 stem을 `song_id`로 사용, 숫자만 허용)
- `song_id` 기준 단일 항목 삭제

참고:
- `image_id(song_id)`는 unique 인덱스로 관리됩니다.
- 같은 `song_id` 재등록 시 upsert(갱신)됩니다.

---

## 주요 설정

설정 파일:
- `settings.json` (실사용)
- `settings.py` (기본값)

중요 키:
- `screen_capture`
  - `logo_*`, `freestyle_*`: 선곡 화면 감지
  - `left_title_*`, `right_title_*`, `left_composer_*`: OCR ROI
- `jacket_matcher`
  - `similarity_threshold`, `match_interval_sec`, `jacket_*`
- `varchive`
  - `fuzzy_threshold`

---

## 프로젝트 구조

```text
overmax/
├── main.py
├── window_tracker.py
├── screen_capture.py
├── image_db.py
├── image_db_cli.py
├── varchive.py
├── overlay.py
├── debug_window.py
├── settings.py
├── settings.json
├── runtime_patch.py
├── overmax.spec
├── build.bat
└── CONTEXT.md
```

---

## 로드맵

다음 우선 기능:
- 현재 선택된 버튼 모드/난이도 감지
- 곡명 OCR 제거(재킷/직접 감지 기반으로 전환)
- 선택 패턴과 유사 난이도 추천
- 기능 안정화 후 경량화(의존성/패키지 크기/시작 속도)

---

## 데이터 출처

- [V-Archive](https://v-archive.net)

---

## 라이선스

MIT
