"""
screen_capture.py - 화면 캡처 및 OCR 모듈

동작 방식:
  매 프레임 (OCR_INTERVAL 마다):
  1. FREESTYLE 로고 OCR → 선곡화면 감지
  2. 재킷 이미지 매칭 → song_id
  3. 밝기 비교 → mode, diff  (OCR 없음)
  4. (song_id, mode, diff) 3종이 같은 프레임에서 N회 연속 동일 + 밝기 신뢰 → 안정  
  5. 안정 상태 확정 시 verified=True 콜백, 이후 쿨다운마다 Rate OCR 반복 수집
"""

import time
import threading
import asyncio
import re
import difflib
from collections import deque
import numpy as np
from typing import Optional, Callable
import mss
import cv2
from settings import SETTINGS

try:
    import winrt.windows.media.ocr as ocr
    import winrt.windows.graphics.imaging as imaging
    import winrt.windows.storage.streams as streams
    WINDOWS_OCR_AVAILABLE = True
except ImportError:
    WINDOWS_OCR_AVAILABLE = False

from window_tracker import WindowTracker, WindowRect
from image_db import ImageDB
from mode_diff_detector import detect_mode_and_difficulty
from game_state import GameSessionState

# ------------------------------------------------------------------
# 설정 상수 (비율 기반)
# ------------------------------------------------------------------
SCREEN_CAPTURE_SETTINGS = SETTINGS["screen_capture"]
JACKET_SETTINGS = SETTINGS["jacket_matcher"]

OCR_INTERVAL = float(SCREEN_CAPTURE_SETTINGS["ocr_interval_sec"])
IDLE_SLEEP_INTERVAL = float(SCREEN_CAPTURE_SETTINGS["idle_sleep_sec"])

# 선곡화면 로고(FREESTYLE) 감지 영역
LOGO_X_START = float(SCREEN_CAPTURE_SETTINGS["logo_x_start"])
LOGO_X_END   = float(SCREEN_CAPTURE_SETTINGS["logo_x_end"])
LOGO_Y_START = float(SCREEN_CAPTURE_SETTINGS["logo_y_start"])
LOGO_Y_END   = float(SCREEN_CAPTURE_SETTINGS["logo_y_end"])

LOGO_OCR_KEYWORD = str(SCREEN_CAPTURE_SETTINGS["logo_ocr_keyword"]).upper()
LOGO_OCR_COOLDOWN_SEC = float(SCREEN_CAPTURE_SETTINGS["logo_ocr_cooldown_sec"])
FREESTYLE_HISTORY_SIZE = int(SCREEN_CAPTURE_SETTINGS["freestyle_history_size"])
FREESTYLE_MAJORITY_RATIO = float(SCREEN_CAPTURE_SETTINGS["freestyle_majority_ratio"])
FREESTYLE_MIN_SAMPLES = int(SCREEN_CAPTURE_SETTINGS["freestyle_min_samples"])
FREESTYLE_ON_RATIO = float(SCREEN_CAPTURE_SETTINGS["freestyle_on_ratio"])
FREESTYLE_ON_MIN_SAMPLES = int(SCREEN_CAPTURE_SETTINGS["freestyle_on_min_samples"])
FREESTYLE_OFF_RATIO = float(SCREEN_CAPTURE_SETTINGS["freestyle_off_ratio"])
FREESTYLE_OFF_MIN_SAMPLES = int(SCREEN_CAPTURE_SETTINGS["freestyle_off_min_samples"])

# 재킷 ROI
JACKET_X_START = float(JACKET_SETTINGS["jacket_x_start"])
JACKET_X_END   = float(JACKET_SETTINGS["jacket_x_end"])
JACKET_Y_START = float(JACKET_SETTINGS["jacket_y_start"])
JACKET_Y_END   = float(JACKET_SETTINGS["jacket_y_end"])

# 재킷 매칭 관련
JACKET_MATCH_INTERVAL = float(JACKET_SETTINGS["match_interval_sec"])
JACKET_SIMILARITY_LOG = bool(JACKET_SETTINGS["log_similarity"])
JACKET_CHANGE_THRESHOLD = float(JACKET_SETTINGS["jacket_change_threshold"])
JACKET_FORCE_RECHECK_SEC = float(JACKET_SETTINGS["jacket_force_recheck_sec"])

# 모드/난이도 안정성 판정 기록 수
_MODE_DIFF_SETTINGS = SETTINGS.get("mode_diff_detector", {})
MODE_DIFF_HISTORY  = int(_MODE_DIFF_SETTINGS.get("history_size", 3))

# Rate OCR 관련 (1920x1080 기준 픽셀 좌표)
_RATE_X1, _RATE_Y1 = 176, 583
_RATE_X2, _RATE_Y2 = 270, 605
RATE_OCR_INTERVAL  = 1.5        # 같은 스냅샷 재OCR 최소 간격 (초)


class ScreenCapture:
    def __init__(
        self,
        tracker: WindowTracker,
        image_db: Optional[ImageDB] = None,
        record_db=None,   # RecordDB | None
    ):
        self.tracker = tracker
        self.image_db = image_db
        self.record_db = record_db

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_song_key = ""
        self._is_song_select = False

        # 콜백
        self.on_state_changed:     Optional[Callable[[GameSessionState], None]] = None
        self.on_screen_changed:    Optional[Callable[[bool], None]]           = None
        self.on_debug_log:         Optional[Callable[[str], None]]            = None
        self.on_record_updated:    Optional[Callable[[], None]]               = None

        # asyncio
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # 로고 OCR 캐시
        self._last_logo_ocr_ts = 0.0
        self._last_logo_ocr_ok = False
        self._freestyle_history = deque(maxlen=max(1, FREESTYLE_HISTORY_SIZE))

        # 재킷 매칭 상태
        self._current_song_id: Optional[int] = None
        self._last_jacket_ts = 0.0
        self._last_jacket_thumb: Optional[np.ndarray] = None
        self._last_jacket_match_ts = 0.0

        self._state_history: deque = deque(maxlen=max(1, MODE_DIFF_HISTORY))
        self._last_emitted_state: Optional[GameSessionState] = None

        # Rate OCR - 세션 내 이미 기록한 (song_id, mode, diff) 집합
        # 선곡화면 이탈(=게임플레이) 시 초기화되어 복귀 후 다시 읽음
        # Rate는 플레이해서 기록을 갱신하지 않으면 변하지 않으므로 세션당 1회면 충분
        self._recorded_states: set = set()
        self._last_rate_ocr_ts: float = 0.0  # OCR 실패 시 재시도 쿨다운

        # Windows OCR 엔진
        self.ocr_engine = None
        if WINDOWS_OCR_AVAILABLE:
            try:
                supported_langs = ocr.OcrEngine.available_recognizer_languages
                target_lang = next(
                    (l for l in supported_langs if "ko" in l.language_tag.lower()), None
                )
                if not target_lang and len(supported_langs) > 0:
                    target_lang = supported_langs[0]
                if target_lang:
                    self.ocr_engine = ocr.OcrEngine.try_create_from_language(target_lang)
                    self.log(f"OCR 엔진 언어: {target_lang.language_tag}")
                else:
                    self.ocr_engine = ocr.OcrEngine.try_create_from_user_profile_languages()
                    self.log("OCR 엔진: user profile 언어 사용")
            except Exception as e:
                self.log(f"OCR 엔진 초기화 실패: {e}")

    # ------------------------------------------------------------------
    # 로그
    # ------------------------------------------------------------------

    def log(self, msg: str):
        full = f"[ScreenCapture] {msg}"
        print(full)
        if self.on_debug_log:
            self.on_debug_log(full)

    # ------------------------------------------------------------------
    # 시작 / 종료
    # ------------------------------------------------------------------

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop_entry, daemon=True)
        self._thread.start()
        jacket_status = "활성" if (self.image_db and self.image_db.is_ready) else "비활성"
        record_status = "활성" if (self.record_db and self.record_db.is_ready) else "비활성"
        self.log(
            f"시작됨 (Windows OCR: {WINDOWS_OCR_AVAILABLE}, "
            f"재킷 매칭: {jacket_status}, 기록 수집: {record_status})"
        )

    def stop(self):
        self._running = False

    def _loop_entry(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_loop())
        finally:
            self._loop.close()

    # ------------------------------------------------------------------
    # 메인 루프
    # ------------------------------------------------------------------

    async def _async_loop(self):
        with mss.mss() as sct:
            while self._running:
                rect = self.tracker.rect
                if rect is None or not self.tracker.is_foreground():
                    await asyncio.sleep(IDLE_SLEEP_INTERVAL)
                    continue
                try:
                    await self._process_frame(sct, rect)
                except Exception as e:
                    self.log(f"프레임 처리 오류: {e}")
                await asyncio.sleep(OCR_INTERVAL)

    # ------------------------------------------------------------------
    # 프레임 처리
    # ------------------------------------------------------------------

    async def _process_frame(self, sct, rect: WindowRect):
        # 1. 선곡화면 감지
        is_song_select, is_leaving = await self._detect_song_select(sct, rect)

        if is_song_select != self._is_song_select:
            self._is_song_select = is_song_select
            self.log(f"화면 변경: {'선곡화면' if is_song_select else '기타화면'}")
            if self.on_screen_changed:
                self.on_screen_changed(is_song_select)

        if not is_song_select:
            # 화면 이탈(게임 플레이 등) 시 상태 전부 초기화
            self._state_history.clear()
            self._current_song_id = None
            self._last_emitted_state = None
            self._recorded_states.clear()
            return

        if is_leaving:
            self.log("선곡 판정 하락 중 - 인식 skip")
            return

        # 2. 전체 화면을 한 번만 캡처 (이 프레임의 모든 정보는 여기서 읽음)
        full_frame = np.array(sct.grab({
            "top":    rect.top,
            "left":   rect.left,
            "width":  rect.width,
            "height": rect.height,
        }))  # BGRA
        now = time.time()

        # 3. 재킷 매칭 → song_id
        h, w = full_frame.shape[:2]
        jacket_img = full_frame[
            int(h * JACKET_Y_START):int(h * JACKET_Y_END),
            int(w * JACKET_X_START):int(w * JACKET_X_END),
        ]
        if (
            self.image_db is not None
            and self.image_db.is_ready
            and self.image_db.song_count > 0
            and now - self._last_jacket_ts >= JACKET_MATCH_INTERVAL
        ):
            self._last_jacket_ts = now
            thumb = cv2.resize(
                cv2.cvtColor(jacket_img, cv2.COLOR_BGRA2GRAY),
                (32, 32), interpolation=cv2.INTER_AREA,
            )
            image_changed = True
            if self._last_jacket_thumb is not None:
                d = np.abs(thumb.astype(np.float32) - self._last_jacket_thumb.astype(np.float32))
                image_changed = float(np.mean(d)) >= JACKET_CHANGE_THRESHOLD
            force_recheck = (now - self._last_jacket_match_ts) >= JACKET_FORCE_RECHECK_SEC

            if image_changed or force_recheck:
                self._last_jacket_thumb = thumb
                self._last_jacket_match_ts = now

                if image_changed:
                    self._current_song_id = None

                result = self.image_db.search(jacket_img)
                if result:
                    sid, score = result
                    if JACKET_SIMILARITY_LOG:
                        self.log(f"재킷 매칭: '{sid}' (유사도 {score:.4f})")
                    if str(sid).isdigit():
                        self._current_song_id = int(sid)
                    else:
                        self._current_song_id = None
                else:
                    self._current_song_id = None

        # 4. 모드/난이도 감지 (밝기 기반, OCR 없음)
        mode, diff, is_confident = detect_mode_and_difficulty(full_frame)

        # 5. 안정성 판정: 같은 프레임에서 읽은 (song_id, mode, diff)가 N프레임 연속 동일 + is_confident
        song_id = self._current_song_id
        current = (song_id, mode, diff)
        valid = all(current) and is_confident
        self._state_history.append(current if valid else None)

        history = list(self._state_history)
        is_stable = (
            len(history) == self._state_history.maxlen
            and len(set(history)) == 1
            and history[0] is not None
        )

        # 6. 통합 상태 객체 생성 및 배포
        state = GameSessionState(
            song_id=song_id,
            mode=mode,
            diff=diff,
            is_stable=is_stable
        )

        if state != self._last_emitted_state:
            self._last_emitted_state = state
            if state.is_stable:
                self.log(f"상태 확정: {state}")
                self._last_rate_ocr_ts = 0.0  # 새 상태 확정 시 즉시 시도 허용
            else:
                self.log(f"상태 감지: {state}")
            
            if self.on_state_changed:
                self.on_state_changed(state)

        # 7. Rate OCR — 안정 상태일 때만 세션당 한 번 기록
        if is_stable and current not in self._recorded_states:
            if now - self._last_rate_ocr_ts >= RATE_OCR_INTERVAL:
                self._last_rate_ocr_ts = now
                success = await self._do_record_rate(full_frame, song_id, mode, diff)
                if success:
                    self._recorded_states.add(current)

    # ------------------------------------------------------------------
    # Rate OCR + RecordDB 저장
    # ------------------------------------------------------------------

    async def _do_record_rate(
        self,
        full_frame: np.ndarray,
        song_id: int,
        mode: str,
        diff: str,
    ) -> bool:
        """
        Rate 영역 OCR 수행 후 RecordDB에 저장.
        반환: True = 성공 (recorded_states에 추가 가능), False = 실패 (재시도 예정)
        """
        # Rate 영역 크롭 (해상도 대응)
        h, w = full_frame.shape[:2]
        sx, sy = w / 1920.0, h / 1080.0
        x1 = int(_RATE_X1 * sx)
        y1 = int(_RATE_Y1 * sy)
        x2 = int(_RATE_X2 * sx)
        y2 = int(_RATE_Y2 * sy)
        roi_bgra = full_frame[y1:y2, x1:x2]

        text = await self._ocr_windows(roi_bgra)
        rate = self._parse_rate(text)

        if rate is None:
            if not text:
                self.log(f"Rate OCR 빈 결과 ({song_id} {mode}/{diff}) - 이진화 재시도")
                text = await self._ocr_windows(roi_bgra, force_invert=True)
                rate = self._parse_rate(text)
            if rate is None:
                self.log(f"Rate OCR 파싱 실패: '{text}' ({song_id} {mode}/{diff})")
                return False

        self.log(f"Rate OCR: {song_id} {mode}/{diff} = {rate:.2f}% (raw='{text}')")

        if rate == 0.0:
            self.log("Rate 0.00% - 미플레이로 간주, 저장 skip")
            return True  # 미플레이도 '읽기 완료'로 처리 (재시도 불필요)

        if self.record_db is not None and self.record_db.is_ready:
            if self.record_db.upsert(song_id, mode, diff, rate):
                if self.on_record_updated:
                    self.on_record_updated()

        return True

    # ------------------------------------------------------------------
    # ROI 헬퍼
    # ------------------------------------------------------------------

    def _region_from_ratio(self, rect, x_start, x_end, y_start, y_end) -> dict:
        return {
            "top":    rect.top  + int(rect.height * y_start),
            "left":   rect.left + int(rect.width  * x_start),
            "width":  max(1, int(rect.width  * (x_end - x_start))),
            "height": max(1, int(rect.height * (y_end - y_start))),
        }

    def _parse_rate(self, text: str) -> Optional[float]:
        """OCR 텍스트에서 숫자만 추출하여 float(%) 로 변환"""
        if not text:
            return None
        # 숫자와 소수점만 남김 (Windows OCR은 종종 %를 9나 8로 오인할 수 있으므로 제거)
        cleaned = re.sub(r"[^0-9.]", "", text)
        try:
            # 여러 개의 점이 찍힌 경우 마지막 점 기준으로 처리하거나 첫 번째 점 사용
            if cleaned.count(".") > 1:
                parts = cleaned.split(".")
                cleaned = parts[0] + "." + "".join(parts[1:])
            
            val = float(cleaned)
            if 0.0 <= val <= 100.0:
                return val
        except:
            pass
        return None

    # ------------------------------------------------------------------
    # 선곡화면 감지
    # ------------------------------------------------------------------

    async def _detect_song_select(self, sct, rect: WindowRect) -> tuple[bool, bool]:
        logo_now = await self._detect_freestyle_logo(sct, rect)
        self._freestyle_history.append(logo_now)
        sample_count = len(self._freestyle_history)
        hit_count    = sum(1 for v in self._freestyle_history if v)
        ratio        = (hit_count / sample_count) if sample_count > 0 else 0.0

        if self._is_song_select:
            should_turn_off = (
                sample_count >= max(1, FREESTYLE_OFF_MIN_SAMPLES)
                and ratio <= FREESTYLE_OFF_RATIO
            )
            is_song_select = not should_turn_off
        else:
            is_song_select = (
                sample_count >= max(1, FREESTYLE_ON_MIN_SAMPLES)
                and ratio >= FREESTYLE_ON_RATIO
            )

        is_leaving = False
        if is_song_select and sample_count >= 4:
            half = sample_count // 2
            history_list = list(self._freestyle_history)
            first_half_ratio  = sum(history_list[:half]) / half
            second_half_ratio = sum(history_list[half:]) / (sample_count - half)
            if second_half_ratio < first_half_ratio:
                is_leaving = True

        self.log(
            f"선곡판정 버퍼: hit={hit_count}/{sample_count} "
            f"(ratio={ratio:.2f}) -> {'선곡' if is_song_select else '기타화면'}"
            + (f" [이탈중]" if is_leaving else "")
        )
        return is_song_select, is_leaving

    async def _detect_freestyle_logo(self, sct, rect: WindowRect) -> bool:
        logo_region = {
            "top":    rect.top  + int(rect.height * LOGO_Y_START),
            "left":   rect.left + int(rect.width  * LOGO_X_START),
            "width":  max(1, int(rect.width  * (LOGO_X_END - LOGO_X_START))),
            "height": max(1, int(rect.height * (LOGO_Y_END - LOGO_Y_START))),
        }
        logo_img = np.array(sct.grab(logo_region))
        now = time.time()
        if now - self._last_logo_ocr_ts >= LOGO_OCR_COOLDOWN_SEC:
            text       = await self._ocr_windows(logo_img)
            normalized = re.sub(r"[^A-Z0-9]", "", text.upper())
            keyword    = re.sub(r"[^A-Z0-9]", "", LOGO_OCR_KEYWORD.upper())
            is_detected = False

            if keyword and normalized:
                if keyword in normalized:
                    is_detected = True
                else:
                    min_partial_len = min(6, len(keyword))
                    for i in range(0, len(keyword) - min_partial_len + 1):
                        part = keyword[i : i + min_partial_len]
                        if part and part in normalized:
                            is_detected = True
                            break
                    if not is_detected:
                        ratio = difflib.SequenceMatcher(None, keyword, normalized).ratio()
                        is_detected = ratio >= 0.72

            self._last_logo_ocr_ok = is_detected
            self._last_logo_ocr_ts = now
            self.log(f"로고 OCR: '{text}' (norm='{normalized}') -> {self._last_logo_ocr_ok}")
        return self._last_logo_ocr_ok

    # ------------------------------------------------------------------
    # Windows OCR
    # ------------------------------------------------------------------

    async def _ocr_windows(self, img_bgra: np.ndarray, force_invert: bool = False) -> str:
        if not WINDOWS_OCR_AVAILABLE or self.ocr_engine is None:
            return ""
        try:
            h, w = img_bgra.shape[:2]
            if w == 0 or h == 0:
                return ""

            scale = 3
            upscaled = cv2.resize(
                img_bgra, (w * scale, h * scale),
                interpolation=cv2.INTER_CUBIC,
            )
            gray = cv2.cvtColor(upscaled, cv2.COLOR_BGRA2GRAY)

            bg_mean = float(gray.mean())
            normal_is_dark = bg_mean < 128
            use_invert = normal_is_dark if force_invert else not normal_is_dark
            if not use_invert:
                _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            else:
                _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

            padding = 10
            thresh = cv2.copyMakeBorder(
                thresh, padding, padding, padding, padding,
                cv2.BORDER_CONSTANT, value=0
            )

            success, encoded = cv2.imencode(".bmp", thresh)
            if not success:
                return ""

            stream = streams.InMemoryRandomAccessStream()
            data_writer = streams.DataWriter(stream)
            data_writer.write_bytes(encoded.tobytes())
            await data_writer.store_async()
            data_writer.detach_stream()
            stream.seek(0)

            decoder = await imaging.BitmapDecoder.create_async(stream)
            software_bitmap = await decoder.get_software_bitmap_async()
            result = await self.ocr_engine.recognize_async(software_bitmap)

            stream.close()

            return result.text.strip()
        except Exception as e:
            self.log(f"OCR 실행 오류: {e}")
            return ""