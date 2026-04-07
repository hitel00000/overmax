# Overmax

DJMAX Respect V 선곡화면에 V-Archive 비공식 난이도를 실시간으로 오버레이하는 도구입니다.

게임 메모리를 읽거나 인젝션하지 않고, **창 추적 + 화면 캡처 + OCR** 방식으로만 동작합니다.

---

## 주요 기능

- 선곡화면 자동 감지 (`FREESTYLE` OCR 기반)
- 화면 상태 안정화 로직
  - 최근 프레임 다수결
  - 빠르게 ON / 느리게 OFF 히스테리시스
- 곡명 OCR
  - 좌측 패널 + 우측 리스트를 함께 읽고 후보 선택
- 작곡가 OCR
  - 동명이곡일 때 작곡가로 분기
- V-Archive 데이터 매칭
  - 정확 매칭 + 퍼지 매칭
- 디버그 창
  - 실시간 로그
  - ROI 표시 ON/OFF
- 오버레이 위치 저장/복원
  - 사용자가 옮긴 위치를 `overlay_position.json`에 저장

---

## 요구사항

- Windows 10 / 11 (64bit)
- DJMAX Respect V (Steam)
- Python 3.10+ (소스 실행 시)

---

## 실행

### 소스에서 실행

```bash
git clone https://github.com/yourname/overmax.git
cd overmax
pip install -r requirements.txt
python main.py
```

`songs.json`은 첫 실행 시 V-Archive API에서 다운로드되어 `cache/`에 저장됩니다.

### 빌드

```bat
build.bat
```

---

## 사용법

- 게임 창 감지 후 선곡화면이면 오버레이가 표시됩니다.
- 기본 단축키: `F9` (오버레이 표시/숨김)
- 오버레이를 드래그하면 위치가 저장되어 다음 실행에 복원됩니다.
- 디버그 창에서 `ROI 표시`를 켜면 OCR/검출 영역을 게임 화면 위에 선으로 확인할 수 있습니다.

---

## 설정

설정 파일:

- `settings.json` (실사용)
- `settings.py` (기본값)

중요 섹션:

- `screen_capture`
  - `logo_*`: 선곡화면 로고 OCR 영역
  - `freestyle_*`: 다수결/히스테리시스 파라미터
  - `left_title_*`, `right_title_*`: 곡명 OCR 영역
  - `left_composer_*`: 작곡가 OCR 영역
- `overlay`
  - `toggle_hotkey`
  - `position_file`

---

## 프로젝트 구조

```
overmax/
├── main.py             진입점
├── window_tracker.py   게임 창 위치/크기 추적
├── screen_capture.py   선곡 감지 + OCR
├── varchive.py         V-Archive 로드/캐시/검색
├── overlay.py          오버레이 UI + ROI 디버그 오버레이
├── debug_window.py     디버그 로그 창
├── settings.py         기본 설정
├── settings.json       사용자 설정
├── runtime_patch.py    패키징 런타임 경로 보정
├── overmax.spec
├── build.bat
└── CONTEXT.md
```

---

## 데이터 출처

- [V-Archive](https://v-archive.net)

---

## 라이선스

MIT
