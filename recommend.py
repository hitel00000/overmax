"""
recommend.py - 유사 난이도 패턴 추천

현재 선택된 패턴의 floor 값을 기준으로
±floor_range 범위 내 패턴을 찾고,
RecordDB의 rate를 붙여 정렬해 반환한다.

정렬 우선순위:
  1. 기록 있음(rate > 0) → rate 낮은 순  (약한 패턴 우선)
  2. 기록 없음(미탐색)   → floor 오름차순
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from varchive import VArchiveDB, BUTTON_MODES, DIFFICULTIES, DIFF_COLORS
from record_db import RecordDB


@dataclass
class RecommendEntry:
    song_id:     int
    song_name:   str
    composer:    str
    button_mode: str
    difficulty:  str
    level:       Optional[int]
    floor:       Optional[float]   # 비공식 난이도 수치 (floorName 파싱)
    floor_name:  Optional[str]     # 표시용 문자열 ex) "15.2"
    rate:        Optional[float]   # None = 미탐색
    color:       str

    @property
    def has_record(self) -> bool:
        return self.rate is not None

    @property
    def is_played(self) -> bool:
        return self.rate is not None and self.rate > 0.0

    @property
    def is_perfect(self) -> bool:
        return self.rate is not None and self.rate >= 100.0


def _parse_floor_value(floor_name: Optional[str]) -> Optional[float]:
    """'15.2' → 15.2, None → None"""
    if not floor_name:
        return None
    try:
        return float(floor_name)
    except ValueError:
        return None


class Recommender:
    def __init__(self, varchive_db: VArchiveDB, record_db: RecordDB):
        self.vdb = varchive_db
        self.rdb = record_db

    def recommend(
        self,
        song_id: int,
        button_mode: str,
        difficulty: str,
        floor_range: float = 1.0,
        max_results: int = 30,
        same_mode_only: bool = False,
    ) -> list[RecommendEntry]:
        """
        현재 패턴과 floor가 유사한 패턴 목록 반환.

        Args:
            song_id:       현재 곡 ID
            button_mode:   현재 버튼 모드 ex) "4B"
            difficulty:    현재 난이도   ex) "SC"
            floor_range:   ±이 범위 안의 floor만 포함 (기본 ±1.0)
            max_results:   최대 반환 수
            same_mode_only: True면 같은 button_mode 패턴만
        Returns:
            RecommendEntry 리스트 (정렬 완료)
        """
        # 1. 현재 패턴의 floor 파악
        current_song = self.vdb.search_by_id(song_id)
        if not current_song:
            return []

        current_pattern = (
            current_song.get("patterns", {})
            .get(button_mode, {})
            .get(difficulty)
        )
        if not current_pattern:
            return []

        ref_floor = _parse_floor_value(current_pattern.get("floorName"))
        if ref_floor is None:
            # floorName 없으면 공식 level을 기준으로 fallback
            ref_floor = float(current_pattern.get("level", 0))

        # 2. 전체 곡/패턴 순회하며 후보 수집
        modes_to_check = [button_mode] if same_mode_only else BUTTON_MODES
        candidates: list[RecommendEntry] = []

        for song in self.vdb.songs:
            try:
                sid = int(song.get("title", 0))
            except (ValueError, TypeError):
                continue
            patterns = song.get("patterns", {})

            for mode in modes_to_check:
                mode_patterns = patterns.get(mode, {})
                for diff in DIFFICULTIES:
                    p = mode_patterns.get(diff)
                    if not p:
                        continue

                    floor_val = _parse_floor_value(p.get("floorName"))
                    if floor_val is None:
                        floor_val = float(p.get("level", 0))

                    # floor 범위 필터
                    if abs(floor_val - ref_floor) > floor_range:
                        continue

                    # 현재 패턴 자신은 제외
                    if sid == song_id and mode == button_mode and diff == difficulty:
                        continue

                    candidates.append(RecommendEntry(
                        song_id=sid,
                        song_name=song.get("name", ""),
                        composer=song.get("composer", ""),
                        button_mode=mode,
                        difficulty=diff,
                        level=p.get("level"),
                        floor=floor_val,
                        floor_name=p.get("floorName"),
                        rate=None,
                        color=DIFF_COLORS.get(diff, "#FFFFFF"),
                    ))

        if not candidates:
            return []

        # 3. RecordDB bulk 조회
        all_ids = list({c.song_id for c in candidates})
        # mode/diff 조합이 다양하므로 개별 조회 대신 song_id 세트로 전체 pull
        rate_map: dict[tuple[int, str, str], float] = {}
        if self.rdb.is_ready:
            try:
                import sqlite3
                placeholders = ",".join("?" * len(all_ids))
                with sqlite3.connect(self.rdb.db_path) as conn:
                    rows = conn.execute(f"""
                        SELECT song_id, button_mode, difficulty, rate
                        FROM records
                        WHERE song_id IN ({placeholders})
                    """, [str(s) for s in all_ids]).fetchall()
                for r in rows:
                    rate_map[(int(r[0]), r[1], r[2])] = float(r[3])
            except Exception as e:
                print(f"[Recommender] rate 조회 실패: {e}")

        for entry in candidates:
            key = (entry.song_id, entry.button_mode, entry.difficulty)
            if key in rate_map:
                entry.rate = rate_map[key]

        # 4. 정렬
        #   - 기록 있고 rate > 0 → rate 낮은 순 (약한 패턴 우선)
        #   - rate == 0 (미플레이) → floor 오름차순
        #   - 미탐색(None) → floor 오름차순, 마지막
        def sort_key(e: RecommendEntry):
            if e.is_played:
                return (0, e.rate, e.floor or 0)
            elif e.has_record:   # rate == 0.0 (미플레이)
                return (1, e.floor or 0, 0)
            else:                # 미탐색
                return (2, e.floor or 0, 0)

        candidates.sort(key=sort_key)
        return candidates[:max_results]
