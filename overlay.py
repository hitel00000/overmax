"""
PyQt6 투명 오버레이 창
- Always-on-top, 클릭 투과
- 선곡화면에서만 표시
- 현재 선택 곡의 버튼 모드별 난이도 표시
- 감지된 버튼 모드 패널 및 선택 난이도 카드 하이라이트
"""

import sys
import threading
import json
from typing import Optional
from settings import SETTINGS
import runtime_patch

try:
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
        QFrame, QGraphicsOpacityEffect, QSystemTrayIcon, QMenu, QStyle,
        QScrollArea
    )
    from PyQt6.QtCore import (
        Qt, QTimer, pyqtSignal, QObject, QPoint, QRect
    )
    from PyQt6.QtGui import (
        QColor, QPainter, QFont, QFontMetrics, QPen, QBrush,
        QLinearGradient, QKeySequence, QIcon, QAction
    )
    PYQT_AVAILABLE = True
except ImportError:
    print("[Overlay] PyQt6 없음")
    PYQT_AVAILABLE = False

from varchive import VArchiveDB, BUTTON_MODES, DIFFICULTIES, DIFF_COLORS
from recommend import Recommender, RecommendEntry
from record_db import RecordDB
from game_state import GameSessionState

from ui.pattern_view import ButtonModePanel
from ui.recommend_view import PatternRow
from ui.navigation import RoiOverlayWindow

OVERLAY_SETTINGS = SETTINGS["overlay"]
TOGGLE_HOTKEY = str(OVERLAY_SETTINGS["toggle_hotkey"])
TRAY_TOOLTIP = str(OVERLAY_SETTINGS["tray_tooltip"])
HINT_LABEL = str(OVERLAY_SETTINGS["hint_label"])
OVERLAY_POSITION_FILE = str(OVERLAY_SETTINGS["position_file"])

# ------------------------------------------------------------------
# 시그널 브릿지 (다른 스레드 → Qt 메인스레드)
# ------------------------------------------------------------------

class OverlaySignals(QObject):
    song_changed = pyqtSignal(str, list)          # (곡명, 패턴 정보 리스트)
    screen_changed = pyqtSignal(bool)             # 선곡화면 여부
    position_changed = pyqtSignal(int, int, int, int)   # 창 위치
    roi_enabled_changed = pyqtSignal(bool)        # ROI 표시 on/off
    mode_diff_changed = pyqtSignal(str, str, bool)      # (button_mode, difficulty, verified)
    recommend_ready = pyqtSignal(list, str, bool) # (entries, pivot_str, no_selection)


# UI 컴포넌트들은 ui/ 폴더로 분리됨


# ------------------------------------------------------------------
# 메인 오버레이 창
# ------------------------------------------------------------------

class OverlayWindow(QWidget):
    def __init__(self, db: VArchiveDB, signals: OverlaySignals):
        super().__init__()
        self.db = db
        self.signals = signals
        self._current_mode: Optional[str] = None
        self._current_diff: Optional[str] = None
        self._patterns_cache: dict[str, list] = {}  # mode -> patterns list
        self._pattern_panel: Optional[ButtonModePanel] = None
        self._song_label: Optional[QLabel] = None
        self._mode_indicator: Optional[QLabel] = None
        self._dragging = False
        self._drag_pos = QPoint()
        self._manual_position = False
        self._user_move_cb = None

        self._setup_window()
        self._setup_ui()
        self._connect_signals()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(330)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # 헤더 (곡명 + 드래그 핸들)
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background: rgba(15, 15, 25, 180);
                border-radius: 8px;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 10, 6)

        badge = QLabel("Overmax")
        badge.setStyleSheet("color: #7B68EE; font-size: 10px; font-weight: bold;")
        header_layout.addWidget(badge)

        # 상태 램프 (검증 여부 표시)
        self._status_lamp = QLabel()
        self._status_lamp.setFixedSize(8, 8)
        self._status_lamp.setStyleSheet("""
            background-color: #FF4B4B; 
            border-radius: 4px;
        """)
        self._status_lamp.setToolTip("인식 검증 중...")
        header_layout.addWidget(self._status_lamp)

        self._song_label = QLabel("곡을 선택하세요")
        self._song_label.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: bold;")
        self._song_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self._song_label, 1)

        hint = QLabel("드래그")
        hint.setStyleSheet("color: #555555; font-size: 9px;")
        header_layout.addWidget(hint)

        main_layout.addWidget(header)

        # 현재 모드/난이도 인디케이터
        self._mode_indicator = QLabel("— / —")
        self._mode_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mode_indicator.setStyleSheet(
            "color: rgba(200,200,255,160); font-size: 10px; font-weight: bold;"
        )
        main_layout.addWidget(self._mode_indicator)

        # 버튼 모드 패널 (단일)
        self._pattern_panel = ButtonModePanel()
        main_layout.addWidget(self._pattern_panel)

        # ----------------------------------------------------------
        # 유사 난이도 추천 섹션
        # ----------------------------------------------------------
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: rgba(255,255,255,15);")
        main_layout.addWidget(line)

        rec_header = QHBoxLayout()
        rec_title = QLabel("유사 난이도 추천")
        rec_title.setStyleSheet("color: #7B68EE; font-size: 10px; font-weight: bold;")
        rec_header.addWidget(rec_title)
        rec_header.addStretch()
        self._rec_count_label = QLabel("")
        self._rec_count_label.setStyleSheet("color: #555555; font-size: 8px;")
        rec_header.addWidget(self._rec_count_label)
        main_layout.addLayout(rec_header)

        self._rec_scroll = QScrollArea()
        self._rec_scroll.setWidgetResizable(True)
        self._rec_scroll.setFixedHeight(186)  # 34px * 5개 + 4px * 4개 (간격)
        self._rec_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rec_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rec_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rec_scroll.setStyleSheet("""
            QScrollArea { background: transparent; }
            QScrollBar:vertical {
                background: transparent;
                width: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(123, 104, 238, 80);
                border-radius: 2px;
            }
        """)

        self._rec_widget = QWidget()
        self._rec_widget.setStyleSheet("background: transparent;")
        self._rec_layout = QVBoxLayout(self._rec_widget)
        self._rec_layout.setContentsMargins(0, 0, 4, 0)
        self._rec_layout.setSpacing(4)
        
        self._rec_scroll.setWidget(self._rec_widget)
        main_layout.addWidget(self._rec_scroll)

        self.adjustSize()

    def _connect_signals(self):
        self.signals.song_changed.connect(self._on_song_changed)
        self.signals.screen_changed.connect(self._on_screen_changed)
        self.signals.position_changed.connect(self._on_game_window_moved)
        self.signals.mode_diff_changed.connect(self._on_mode_diff_changed)
        self.signals.recommend_ready.connect(self._on_recommend_ready)

    def _on_recommend_ready(self, entries: list[RecommendEntry], pivot_str: str, no_selection: bool):
        """추천 목록 UI 갱신"""
        try:
            # 기존 목록 청소
            while self._rec_layout.count() > 0:
                item = self._rec_layout.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()

            if no_selection or not entries:
                empty = QLabel("추천 결과 없음" if not no_selection else "패턴을 감지하는 중...")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                empty.setStyleSheet("color: #444444; font-size: 10px; padding: 20px;")
                self._rec_layout.addWidget(empty)
                self._rec_layout.addStretch()
                self._rec_count_label.setText("")
                return

            for entry in entries:
                row = PatternRow(entry)
                self._rec_layout.addWidget(row)
            self._rec_layout.addStretch()

            played = sum(1 for e in entries if e.is_played)
            self._rec_count_label.setText(f"{len(entries)}개 결과 (기록 {played})")
            
        except Exception as e:
            print(f"[Overlay] _on_recommend_ready 오류: {e}")

    # ------------------------------------------------------------------
    # 슬롯
    # ------------------------------------------------------------------

    def _on_song_changed(self, title: str, all_patterns: list):
        """
        all_patterns: 모든 버튼 모드의 패턴 정보
        형식: [{"mode": "4B", "patterns": [...]}, ...]
        """
        self._song_label.setText(title)
        # 모든 모드 데이터를 캐싱
        self._patterns_cache = {item["mode"]: item["patterns"] for item in all_patterns}
        # 현재 선택된 모드 혹은 기본 모드(4B)로 갱신
        self._apply_mode_diff_highlight()

    def _on_screen_changed(self, is_song_select: bool):
        if is_song_select:
            self.show()
        else:
            self.hide()

    def _on_game_window_moved(self, left, top, width, height):
        if self._manual_position:
            return
        ox = left + width + 10
        oy = top + height - self.height() - 40
        screen = QApplication.primaryScreen().geometry()
        if ox + self.width() > screen.width():
            ox = left - self.width() - 10
        self.move(ox, max(oy, top))

    def _on_mode_diff_changed(self, mode: str, diff: str, verified: bool):
        """버튼 모드 / 난이도 변경 시 하이라이트 혹은 램프만 갱신."""
        
        # 상태 램프 업데이트 (즉시 반영)
        if verified:
            # 파란불 (#00D4FF)
            self._status_lamp.setStyleSheet("background-color: #00D4FF; border-radius: 4px;")
            self._status_lamp.setToolTip("인식 완료")
            
            # 모든게 안정이 됐을 때만 UI 실질 데이터 갱신
            self._current_mode = mode if mode else None
            self._current_diff = diff if diff else None
            self._apply_mode_diff_highlight()
        else:
            # 빨간불
            self._status_lamp.setStyleSheet("background-color: #FF4B4B; border-radius: 4px;")
            self._status_lamp.setToolTip("인식 검증 중...")
            # 검증 중일 때는 데이터 갱신을 생략하여 UI를 고정함 (사용자 요청)

    def _apply_mode_diff_highlight(self):
        """단일 패널에 현재 모드 데이터 적용 및 하이라이트."""
        # 감지된 모드가 없으면 기본으로 4B를 표시하거나, 필요 시 빈 상태 유지
        display_mode = self._current_mode or "4B"
        patterns = self._patterns_cache.get(display_mode, [])
        
        if self._pattern_panel:
            self._pattern_panel.update_patterns(patterns)
            self._pattern_panel.set_selected_diff(self._current_diff)

        # 인디케이터 텍스트 갱신
        mode_str = self._current_mode or "—"
        diff_str = self._current_diff or "—"
        self._mode_indicator.setText(f"현재: {mode_str}  /  {diff_str}")

        # 창 크기 재조정
        self.adjustSize()

    def set_user_move_callback(self, callback):
        self._user_move_cb = callback

    def apply_saved_position(self, x: int, y: int):
        self._manual_position = True
        self.move(x, y)

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()

    # ------------------------------------------------------------------
    # 드래그로 위치 이동
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self._manual_position = True
            if self._user_move_cb is not None:
                self._user_move_cb(self.x(), self.y())
        else:
            self._dragging = False

    # ------------------------------------------------------------------
    # 배경 그리기
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor(0, 0, 0, 0)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(self.rect())


# ------------------------------------------------------------------
# 오버레이 컨트롤러 (스레드 → Qt 브릿지)
# ------------------------------------------------------------------

class OverlayController:
    def __init__(self, db: VArchiveDB, record_db: RecordDB):
        self.db = db
        self.record_db = record_db
        self.recommender = Recommender(db, record_db)
        self.signals = OverlaySignals()
        self._app: Optional[QApplication] = None
        self._window: Optional[OverlayWindow] = None
        self._roi_window: Optional[RoiOverlayWindow] = None
        self._tray_icon: Optional[QSystemTrayIcon] = None
        self._debug_log_cb = None
        self._debug_toggle_cb = None

        self._song_id: Optional[int] = None
        self._current_mode: Optional[str] = None
        self._current_diff: Optional[str] = None

        self._last_window_rect: Optional[tuple[int, int, int, int]] = None
        self._position_path = runtime_patch.get_data_dir() / OVERLAY_POSITION_FILE

    def _emit_initial_state(self):
        all_patterns = [{"mode": mode, "patterns": []} for mode in BUTTON_MODES]
        self.signals.song_changed.emit("곡을 선택하세요", all_patterns)

    def notify_screen(self, is_song_select: bool):
        self.log(f"화면 알림: {'선곡화면' if is_song_select else '기타화면'}")
        self.signals.screen_changed.emit(is_song_select)

    def notify_window_pos(self, left, top, width, height):
        self.log(f"창 위치: ({left},{top}) {width}x{height}")
        self._last_window_rect = (left, top, width, height)
        self.signals.position_changed.emit(left, top, width, height)

    def notify_window_lost(self):
        self.log("게임 창 소실 알림 수신: 오버레이 숨김 + ROI OFF")
        self._last_window_rect = None
        self.signals.screen_changed.emit(False)
        self.signals.roi_enabled_changed.emit(False)
        self.signals.position_changed.emit(0, 0, 0, 0)

    def notify_state(self, state: GameSessionState):
        """ScreenCapture에서 온 통합 상태 알림 처리"""
        mode = state.mode
        diff = state.diff
        verified = state.is_stable
        song_id = state.song_id

        # 1. 모드/난이도 처리
        if (
            self._current_mode != mode 
            or self._current_diff != diff 
            or getattr(self, "_last_verified", None) != verified
        ):
            self._current_mode = mode
            self._current_diff = diff
            self._last_verified = verified
            self.signals.mode_diff_changed.emit(mode or "", diff or "", verified)

        # 2. 곡 정보 처리
        if self._song_id != song_id:
            self._song_id = song_id
            if not song_id:
                self.log("곡 ID 없음: UI 초기화")
                self._emit_initial_state()
            else:
                song = self.db.search_by_id(song_id)
                if not song:
                    self.log(f"ID={song_id}를 DB에서 찾을 수 없음")
                    self._emit_initial_state()
                else:
                    self.log(f"곡 확정: {song['name']} (ID={song_id})")
                    all_patterns = []
                    for m in BUTTON_MODES:
                        patterns = self.db.format_pattern_info(song, m)
                        all_patterns.append({"mode": m, "patterns": patterns})
                    self.signals.song_changed.emit(song["name"], all_patterns)

        # 3. 추천 갱신 (안정 상태인 경우에만)
        if verified:
            self._refresh_recommendations()

    def notify_record_updated(self):
        """새 기록 저장 알림 → 추천 리스트 갱신"""
        self._refresh_recommendations()

    def _refresh_recommendations(self):
        if not self._song_id or not self._current_mode or not self._current_diff:
            self.signals.recommend_ready.emit([], "", True)
            return

        entries = self.recommender.recommend(
            song_id=self._song_id,
            button_mode=self._current_mode,
            difficulty=self._current_diff
        )
        pivot = f"{self._current_mode} {self._current_diff}"
        self.signals.recommend_ready.emit(entries, pivot, False)

    def set_roi_overlay_enabled(self, enabled: bool):
        if self._roi_window is None:
            return
        self._roi_window.set_enabled(enabled)
        state = "ON" if enabled else "OFF"
        self.log(f"ROI 영역 표시: {state}")
        if enabled and self._last_window_rect is not None:
            left, top, width, height = self._last_window_rect
            self._roi_window.set_game_rect(left, top, width, height)

    def toggle_roi_overlay(self):
        if self._roi_window is None:
            return False
        new_state = not self._roi_window.is_enabled()
        self.set_roi_overlay_enabled(new_state)
        return new_state

    def log(self, msg: str):
        full = f"[Overlay] {msg}"
        print(full)
        if self._debug_log_cb:
            self._debug_log_cb(full)

    def _load_overlay_position(self) -> Optional[tuple[int, int]]:
        try:
            if not self._position_path.exists():
                return None
            with open(self._position_path, encoding="utf-8") as f:
                data = json.load(f)
            x = int(data.get("x"))
            y = int(data.get("y"))
            return (x, y)
        except Exception as e:
            self.log(f"오버레이 위치 로드 실패: {e}")
            return None

    def _save_overlay_position(self, x: int, y: int):
        try:
            self._position_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._position_path, "w", encoding="utf-8") as f:
                json.dump({"x": int(x), "y": int(y)}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"오버레이 위치 저장 실패: {e}")

    def _on_overlay_user_moved(self, x: int, y: int):
        self._save_overlay_position(x, y)
        self.log(f"오버레이 위치 저장: ({x},{y})")

    def toggle_visibility(self):
        if self._window is not None:
            self._window.toggle_visibility()

    def run(self, debug_ctrl=None, recommend_ctrl=None):
        """Qt 이벤트 루프 실행 (메인 스레드에서 호출)"""
        if not PYQT_AVAILABLE:
            print("[Overlay] PyQt6 없음, 콘솔 모드로 실행")
            import time
            while True:
                time.sleep(1)
            return

        self._app = QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)
        self._window = OverlayWindow(self.db, self.signals)
        self._window.hide()
        self._window.set_user_move_callback(self._on_overlay_user_moved)
        self._roi_window = RoiOverlayWindow()
        self._roi_window.hide()
        self.signals.position_changed.connect(self._roi_window.set_game_rect)
        self.signals.roi_enabled_changed.connect(self._roi_window.set_enabled)

        saved_pos = self._load_overlay_position()
        if saved_pos is not None:
            sx, sy = saved_pos
            screen = self._app.primaryScreen().geometry()
            sx = max(0, min(sx, max(0, screen.width() - self._window.width())))
            sy = max(0, min(sy, max(0, screen.height() - self._window.height())))
            self._window.apply_saved_position(sx, sy)
            self.log(f"오버레이 위치 복원: ({sx},{sy})")

        # 디버그 창 생성 (QApplication 생성 후)
        if debug_ctrl is not None:
            debug_ctrl.create_window()
            debug_ctrl.set_roi_toggle_callback(self.set_roi_overlay_enabled)
            self._debug_toggle_cb = debug_ctrl.toggle_window
        else:
            self._debug_toggle_cb = None

        if recommend_ctrl is not None:
            # recommend_overlay는 더 이상 개별 창으로 사용하지 않음
            pass

        # 트레이 아이콘 설정
        self._setup_tray_icon()

        self._app.exec()

    def _setup_tray_icon(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("[Overlay] 시스템 트레이를 사용할 수 없음")
            return

        self._tray_icon = QSystemTrayIcon(self._app)
        self._tray_icon.setIcon(self._app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self._tray_icon.setToolTip(TRAY_TOOLTIP)

        tray_menu = QMenu()

        toggle_action = QAction(f"오버레이 표시/숨김 ({TOGGLE_HOTKEY})", self._app)
        toggle_action.triggered.connect(self._window.toggle_visibility)
        tray_menu.addAction(toggle_action)

        if self._debug_toggle_cb is not None:
            debug_action = QAction("디버그 창 표시/숨김", self._app)
            debug_action.triggered.connect(self._debug_toggle_cb)
            tray_menu.addAction(debug_action)

        tray_menu.addSeparator()

        quit_action = QAction("종료", self._app)
        quit_action.triggered.connect(self._app.quit)
        tray_menu.addAction(quit_action)

        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.show()

        self._tray_icon.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._window.toggle_visibility()
