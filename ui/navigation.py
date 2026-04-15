from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QPainter, QFont, QPen

from settings import SETTINGS

SCREEN_CAPTURE_SETTINGS = SETTINGS["screen_capture"]
JACKET_SETTINGS = SETTINGS["jacket_matcher"]

LOGO_X_START = float(SCREEN_CAPTURE_SETTINGS["logo_x_start"])
LOGO_X_END = float(SCREEN_CAPTURE_SETTINGS["logo_x_end"])
LOGO_Y_START = float(SCREEN_CAPTURE_SETTINGS["logo_y_start"])
LOGO_Y_END = float(SCREEN_CAPTURE_SETTINGS["logo_y_end"])
JACKET_X_START = float(JACKET_SETTINGS["jacket_x_start"])
JACKET_X_END   = float(JACKET_SETTINGS["jacket_x_end"])
JACKET_Y_START = float(JACKET_SETTINGS["jacket_y_start"])
JACKET_Y_END   = float(JACKET_SETTINGS["jacket_y_end"])

class RoiOverlayWindow(QWidget):
    """게임 화면 위에 OCR/검출 ROI를 선으로 표시하는 디버그 오버레이"""
    def __init__(self):
        super().__init__()
        self._enabled = False
        self._has_rect = False
        self._setup_window()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_game_rect(self, left: int, top: int, width: int, height: int):
        self._has_rect = width > 0 and height > 0
        if not self._has_rect:
            self.hide()
            return
        self.setGeometry(left, top, width, height)
        if self._enabled:
            self.show()
        self.update()

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        if enabled and self._has_rect:
            self.show()
            self.raise_()
        else:
            self.hide()
        self.update()

    def is_enabled(self) -> bool:
        return self._enabled

    def _ratio_rect(self, rx1: float, ry1: float, rx2: float, ry2: float) -> QRect:
        x = int(self.width() * rx1)
        y = int(self.height() * ry1)
        w = max(1, int(self.width() * (rx2 - rx1)))
        h = max(1, int(self.height() * (ry2 - ry1)))
        return QRect(x, y, w, h)

    def _draw_box(self, painter: QPainter, rect: QRect, color: QColor, label: str):
        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        painter.setPen(QPen(color, 1))
        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        painter.drawText(rect.left() + 4, max(12, rect.top() - 4), label)

    def paintEvent(self, event):
        if not self._enabled or not self._has_rect:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        self._draw_box(
            painter,
            self._ratio_rect(LOGO_X_START, LOGO_Y_START, LOGO_X_END, LOGO_Y_END),
            QColor("#CC66FF"),
            "LOGO (FREESTYLE)",
        )
        self._draw_box(
            painter,
            self._ratio_rect(JACKET_X_START, JACKET_Y_START, JACKET_X_END, JACKET_Y_END),
            QColor("#FF0000"),
            "JACKET",
        )

        # 버튼 모드 감지 영역 (80~84, 130~134)
        self._draw_box(
            painter,
            self._ratio_rect(80/1920, 130/1080, 85/1920, 135/1080),
            QColor("#00FF88"),
            "BTN MODE",
        )

        # 난이도 감지 위치 (NM 기준 위치1/위치2)
        for i, (diff, x_off) in enumerate({"NM": 0, "HD": 120, "MX": 240, "SC": 360}.items()):
            dx = x_off / 1920
            # 위치1
            rx1 = (97 / 1920) + dx
            ry1 = 487 / 1080
            self._draw_box(
                painter,
                self._ratio_rect(rx1 - 1/1920, ry1 - 1/1080, rx1 + 3/1920, ry1 + 3/1080),
                QColor("#FFAA00"),
                diff,
            )
