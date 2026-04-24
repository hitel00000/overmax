"""
varchive_uploader.py - V-Archive 기록 등록 API 클라이언트

account.txt 파싱 및 POST /client/open/{userNo}/score 호출.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

_BASE_URL = "https://v-archive.net/client/open/{user_no}/score"
_TIMEOUT = 10.0

# overmax 내부 난이도 코드 → V-Archive API 패턴 명
_PATTERN_MAP = {
    "NM": "NORMAL",
    "HD": "HARD",
    "MX": "MAXIMUM",
    "SC": "SC",
}

# overmax 버튼 모드 문자열 → API button 숫자
_BUTTON_MAP = {
    "4B": 4,
    "5B": 5,
    "6B": 6,
    "8B": 8,
}


@dataclass
class AccountInfo:
    user_no: int
    token: str


@dataclass
class UploadResult:
    success: bool
    updated: bool        # API update=true 인 경우
    error_code: Optional[int] = None
    message: str = ""


def parse_account_file(path: str | Path) -> Optional[AccountInfo]:
    """
    account.txt 파싱. 형식: "{userNo} {token}"
    실패 시 None 반환.
    """
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
        parts = text.split()
        if len(parts) < 2:
            return None
        return AccountInfo(user_no=int(parts[0]), token=parts[1])
    except Exception:
        return None


def upload_score(
    account: AccountInfo,
    song_name: str,
    button_mode: str,
    difficulty: str,
    score: float,
    is_max_combo: bool,
    composer: str = "",
) -> UploadResult:
    """
    V-Archive에 기록 1건을 등록한다.

    Args:
        account:      AccountInfo (user_no, token)
        song_name:    곡 제목
        button_mode:  "4B" / "5B" / "6B" / "8B"
        difficulty:   "NM" / "HD" / "MX" / "SC"
        score:        정확도 (0.0 ~ 100.0)
        is_max_combo: 맥스 콤보 여부
        composer:     작곡가명 (동명이곡 구분용, 선택)
    """
    pattern = _PATTERN_MAP.get(difficulty)
    button = _BUTTON_MAP.get(button_mode)
    if pattern is None or button is None:
        return UploadResult(success=False, updated=False, message=f"지원하지 않는 모드/난이도: {button_mode}/{difficulty}")

    url = _BASE_URL.format(user_no=account.user_no)
    headers = {
        "Authorization": account.token,
        "Content-Type": "application/json",
    }
    body: dict = {
        "name": song_name,
        "button": button,
        "pattern": pattern,
        "score": score,
        "maxCombo": 1 if is_max_combo else 0,
    }
    if composer:
        body["composer"] = composer

    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=_TIMEOUT)
        data = resp.json()
    except Exception as e:
        return UploadResult(success=False, updated=False, message=str(e))

    if resp.status_code == 200:
        return UploadResult(
            success=True,
            updated=bool(data.get("update", False)),
        )

    return UploadResult(
        success=False,
        updated=False,
        error_code=data.get("errorCode"),
        message=data.get("message", f"HTTP {resp.status_code}"),
    )
