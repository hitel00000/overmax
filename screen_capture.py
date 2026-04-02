import time
import threading
import asyncio
import numpy as np
from typing import Optional, Callable
import mss
import cv2

# Windows OCR 관련 임포트
try:
    import winrt.windows.media.ocr as ocr
    import winrt.windows.graphics.imaging as imaging
    import winrt.windows.storage.streams as streams
    WINDOWS_OCR_AVAILABLE = True
except ImportError:
    WINDOWS_OCR_AVAILABLE = False

from window_tracker import WindowTracker, WindowRect

# ------------------------------------------------------------------
# 설정 상수 (비율 기반)
# ------------------------------------------------------------------

# 1. 앵커 포인트 (픽셀 방식): 하단 힌트바 특정 지점의 RGB 체크
# [Y비율, X비율, 목표RGB(BGR순서)]
ANCHOR_POINTS = [
    (0.985, 0.900, (255, 255, 255)), # 하단 텍스트 흰색 영역
    (0.985, 0.100, (180, 180, 180))  # 하단 가이드 바 배경
]
ANCHOR_TOLERANCE = 30 # 색상 오차 허용 범위

# 2. 하이라이트 행 탐색 (수직 샘플링용 X 위치)
# 리스트 영역 내에서 주황/보라색이 가장 잘 드러나는 X 좌표 비율
SAMPLING_X_RATIO = 0.20 

# 3. 곡명 OCR 영역 (하이라이트 행 기준 상대적 X 범위)
TITLE_X_START = 0.22
TITLE_X_END = 0.50

# 4. 하이라이트 색상 (HSV)
HIGHLIGHT_HUE_RANGES = [(15, 35), (130, 150)] # 주황, 보라
HIGHLIGHT_SAT_MIN = 120
HIGHLIGHT_VAL_MIN = 180

OCR_INTERVAL = 0.3 # Windows OCR은 빠르므로 주기를 약간 당겨도 무방합니다.

class ScreenCapture:
    def __init__(self, tracker: WindowTracker):
        self.tracker = tracker
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_title = ""
        self._is_song_select = False
        
        # Windows OCR 엔진 초기화
        self.ocr_engine = None
        if WINDOWS_OCR_AVAILABLE:
            try:
                # 사용 가능한 언어 목록 확인
                supported_langs = ocr.OcrEngine.available_recognizer_languages
                
                # 1. 한국어 우선 검색
                target_lang = next((l for l in supported_langs if "ko" in l.language_tag.lower()), None)
                
                # 2. 한국어가 없으면 첫 번째 사용 가능한 언어 선택
                if not target_lang and len(supported_langs) > 0:
                    target_lang = supported_langs[0]
                
                if target_lang:
                    self.ocr_engine = ocr.OcrEngine.try_create_from_language(target_lang)
                    print(f"[ScreenCapture] OCR 엔진 시작 언어: {target_lang.language_tag}")
                else:
                    # 3. 최후의 수단: 유저 프로필 기준 생성
                    self.ocr_engine = ocr.OcrEngine.try_create_from_user_profile_languages()
            except Exception as e:
                print(f"[ScreenCapture] 엔진 초기화 실패: {e}")
        
        self.on_song_changed: Optional[Callable[[str], None]] = None
        self.on_screen_changed: Optional[Callable[[bool], None]] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"[ScreenCapture] 시작됨 (Windows OCR: {WINDOWS_OCR_AVAILABLE})")

    def stop(self):
        self._running = False

    def _loop(self):
        with mss.mss() as sct:
            while self._running:
                rect = self.tracker.rect
                if rect is None or not self.tracker.is_foreground():
                    time.sleep(0.5)
                    continue

                try:
                    self._process_frame(sct, rect)
                except Exception as e:
                    print(f"[ScreenCapture] 오류: {e}")

                time.sleep(OCR_INTERVAL)

    def _process_frame(self, sct, rect: WindowRect):
        # 1. 앵커 포인트 체크 (가장 빠름)
        is_song_select = self._check_anchors(sct, rect)

        if is_song_select != self._is_song_select:
            self._is_song_select = is_song_select
            if self.on_screen_changed:
                self.on_screen_changed(is_song_select)

        if not is_song_select:
            return

        # 2. 수직 샘플링으로 선택된 행 찾기
        target_y_range = self._find_highlight_row_y(sct, rect)
        
        if target_y_range:
            y_start, y_end = target_y_range
            # 3. 곡 제목 영역만 정밀 크롭
            title_region = {
                "top": rect.top + y_start,
                "left": rect.left + int(rect.width * TITLE_X_START),
                "width": int(rect.width * (TITLE_X_END - TITLE_X_START)),
                "height": y_end - y_start
            }
            img = np.array(sct.grab(title_region))
            
            # 4. Windows OCR 실행 (비동기 함수를 동기적으로 호출)
            title = asyncio.run(self._ocr_windows(img))
            
            if title and title != self._last_title:
                self._last_title = title
                if self.on_song_changed:
                    self.on_song_changed(title)

    def _check_anchors(self, sct, rect: WindowRect) -> bool:
        """특정 좌표의 색상을 검사하여 선곡 화면인지 판별"""
        for y_rat, x_rat, target_rgb in ANCHOR_POINTS:
            px_region = {
                "top": rect.top + int(rect.height * y_rat),
                "left": rect.left + int(rect.width * x_rat),
                "width": 1, "height": 1
            }
            px = np.array(sct.grab(px_region))[0][0][:3] # BGR
            # BGR -> RGB 순서 고려하여 거리 계산
            dist = np.linalg.norm(px - np.array(target_rgb[::-1]))
            if dist > ANCHOR_TOLERANCE:
                return False
        return True

    def _find_highlight_row_y(self, sct, rect: WindowRect) -> Optional[tuple]:
        """수직 샘플링(X축 한 줄 스캔)으로 하이라이트 행의 Y 시작/끝 좌표 반환"""
        sample_region = {
            "top": rect.top,
            "left": rect.left + int(rect.width * SAMPLING_X_RATIO),
            "width": 1,
            "height": rect.height
        }
        # 한 줄(Column)만 가져와서 HSV 변환
        line_img = np.array(sct.grab(sample_region))
        line_hsv = cv2.cvtColor(line_img, cv2.COLOR_BGRA2BGR)
        line_hsv = cv2.cvtColor(line_hsv, cv2.COLOR_BGR2HSV)

        # 하이라이트 색상 마스크 (주황/보라)
        mask = np.zeros(line_hsv.shape[:2], dtype=np.uint8)
        for h_min, h_max in HIGHLIGHT_HUE_RANGES:
            m = cv2.inRange(line_hsv, (h_min, HIGHLIGHT_SAT_MIN, HIGHLIGHT_VAL_MIN), (h_max, 255, 255))
            mask = cv2.bitwise_or(mask, m)

        indices = np.where(mask > 0)[0]
        if len(indices) < 20: # 너무 적은 픽셀은 무시
            return None
            
        return (int(indices.min()), int(indices.max()))

async def _ocr_windows(self, img_bgra: np.ndarray) -> str:
        """Windows.Media.Ocr 엔진을 사용한 고속 인식"""
        if not WINDOWS_OCR_AVAILABLE or self.ocr_engine is None:
            return ""

        try:
            height, width, _ = img_bgra.shape
            
            # 전처리: 흑백 전환 및 이진화 (글자 강조)
            gray = cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2GRAY)
            _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
            
            # OpenCV 이미지를 Windows Stream으로 변환
            success, encoded_img = cv2.imencode('.bmp', thresh)
            if not success: return ""
            
            data_writer = streams.DataWriter()
            data_writer.write_bytes(encoded_img.tobytes())
            
            stream = streams.InMemoryRandomAccessStream()
            await data_writer.store_async(stream)
            data_writer.detach_stream()
            stream.seek(0)
            
            decoder = await imaging.BitmapDecoder.create_async(stream)
            software_bitmap = await decoder.get_software_bitmap_async()
            
            # OCR 실행
            result = await self.ocr_engine.recognize_async(software_bitmap)
            return result.text.strip()
        except Exception as e:
            print(f"[ScreenCapture] OCR 실행 오류: {e}")
            return ""