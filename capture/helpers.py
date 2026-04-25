"""Helper functions for screen_capture runtime pipeline."""

from typing import Optional

import cv2
import numpy as np


def crop_roi(frame: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    """ROI (x1, y1, x2, y2) 영역을 프레임에서 잘라낸다."""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = roi
    return frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]


def make_thumbnail(image_bgra: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image_bgra, cv2.COLOR_BGRA2GRAY)
    return cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)


def has_thumbnail_changed(current: np.ndarray, prev: Optional[np.ndarray], threshold: float) -> bool:
    if prev is None:
        return True
    diff = np.abs(current.astype(np.float32) - prev.astype(np.float32))
    return float(np.mean(diff)) >= threshold