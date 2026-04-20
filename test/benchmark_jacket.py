"""
benchmark_jacket.py - 재킷 매칭 파이프라인 baseline 측정 도구

사용법:
    python benchmark_jacket.py --jacket-dir <재킷 이미지 폴더> [옵션]

재킷 이미지 폴더 구조:
    <song_id>.png  (파일명 stem이 song_id여야 함, 숫자)

측정 항목:
    1. 전체 top-1 정답률
    2. feature별 단독 정답률 (hash / HOG / ORB)
    3. 오매칭 상위 케이스
    4. 유사도 점수 분포 (정답 vs 오답)
    5. ORB keypoint 수 분포
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# ------------------------------------------------------------------
# image_db 모듈에서 순수 함수 재사용
# detection/ 패키지가 있는 프로젝트 루트에서 실행 가정
# ------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))

from detection.image_db import (
    _CachedEntry,
    _compute_hashes,
    _compute_hog,
    _compute_orb,
    _hash_distance,
    _orb_match_score,
    _row_to_entry,
    _to_gray,
)

SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


# ------------------------------------------------------------------
# 데이터
# ------------------------------------------------------------------

@dataclass
class MatchResult:
    song_id: str           # 정답 song_id
    predicted: str         # 예측 song_id
    correct: bool
    score_combined: float  # 현재 파이프라인 최종 점수
    score_hash: float
    score_hog: float
    score_orb: float
    orb_keypoints: int     # query 이미지의 keypoint 수


@dataclass
class BenchmarkStats:
    total: int = 0
    correct: int = 0
    results: list[MatchResult] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total > 0 else 0.0


# ------------------------------------------------------------------
# DB 로드
# ------------------------------------------------------------------

def load_cache(db_path: str) -> list[_CachedEntry]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT image_id, phash, dhash, ahash, hog, orb FROM images"
        ).fetchall()
    return [_row_to_entry(r) for r in rows]


# ------------------------------------------------------------------
# 유사도 계산 (image_db.py의 search 로직을 분해해서 재현)
# ------------------------------------------------------------------

def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def score_hash(q_ph, q_dh, q_ah, entry: _CachedEntry) -> float:
    raw = (
        0.5 * _hash_distance(q_ph, entry.phash)
        + 0.3 * _hash_distance(q_dh, entry.dhash)
        + 0.2 * _hash_distance(q_ah, entry.ahash)
    )
    return max(0.0, 1.0 - min(raw / 64.0, 1.0))


def score_hog_l2(q_hog: np.ndarray, entry: _CachedEntry) -> float:
    h = float(np.linalg.norm(q_hog - entry.hog))
    return max(0.0, 1.0 - min(h / 30.0, 1.0))


def score_hog_cosine(q_hog: np.ndarray, entry: _CachedEntry) -> float:
    return _cosine_sim(q_hog, entry.hog)


def score_orb(q_orb: Optional[np.ndarray], entry: _CachedEntry) -> float:
    matches = _orb_match_score(q_orb, entry.orb)
    return min(matches / 20.0, 1.0)


def combined_score(h: float, hog: float, orb: float) -> float:
    return 0.45 * h + 0.35 * hog + 0.20 * orb


# ------------------------------------------------------------------
# 단일 이미지 평가
# ------------------------------------------------------------------

def evaluate_one(
    img: np.ndarray,
    truth_id: str,
    cache: list[_CachedEntry],
    use_cosine_hog: bool = False,
) -> MatchResult:
    gray = _to_gray(img)
    assert gray is not None

    q_ph, q_dh, q_ah = _compute_hashes(gray)
    q_hog = _compute_hog(gray)
    q_orb = _compute_orb(gray)
    orb_kp_count = len(q_orb) if q_orb is not None else 0

    hog_fn = score_hog_cosine if use_cosine_hog else score_hog_l2

    best: Optional[tuple[str, float, float, float, float]] = None  # (id, combined, hash, hog, orb)
    for entry in cache:
        if entry.image_id == truth_id:
            continue  # self-match 제외

        sh = score_hash(q_ph, q_dh, q_ah, entry)
        shog = hog_fn(q_hog, entry)
        sorb = score_orb(q_orb, entry)
        sc = combined_score(sh, shog, sorb)

        if best is None or sc > best[1]:
            best = (entry.image_id, sc, sh, shog, sorb)

    # 정답 entry의 점수도 계산
    truth_entry = next((e for e in cache if e.image_id == truth_id), None)
    if truth_entry is None:
        # DB에 없는 song_id
        return MatchResult(
            song_id=truth_id, predicted="(not in db)", correct=False,
            score_combined=0.0, score_hash=0.0, score_hog=0.0, score_orb=0.0,
            orb_keypoints=orb_kp_count,
        )

    truth_sh   = score_hash(q_ph, q_dh, q_ah, truth_entry)
    truth_shog = hog_fn(q_hog, truth_entry)
    truth_sorb = score_orb(q_orb, truth_entry)
    truth_sc   = combined_score(truth_sh, truth_shog, truth_sorb)

    if best is None or truth_sc >= best[1]:
        return MatchResult(
            song_id=truth_id, predicted=truth_id, correct=True,
            score_combined=truth_sc, score_hash=truth_sh,
            score_hog=truth_shog, score_orb=truth_sorb,
            orb_keypoints=orb_kp_count,
        )
    else:
        return MatchResult(
            song_id=truth_id, predicted=best[0], correct=False,
            score_combined=best[1], score_hash=best[2],
            score_hog=best[3], score_orb=best[4],
            orb_keypoints=orb_kp_count,
        )


# ------------------------------------------------------------------
# 단독 feature 정답률 측정
# ------------------------------------------------------------------

def accuracy_hash_only(cache: list[_CachedEntry], test_set: list[tuple[np.ndarray, str]]) -> float:
    correct = 0
    for img, truth_id in test_set:
        gray = _to_gray(img)
        q_ph, q_dh, q_ah = _compute_hashes(gray)
        best_id, best_score = None, -1.0
        for entry in cache:
            if entry.image_id == truth_id:
                continue
            s = score_hash(q_ph, q_dh, q_ah, entry)
            if s > best_score:
                best_score, best_id = s, entry.image_id
        truth_entry = next((e for e in cache if e.image_id == truth_id), None)
        if truth_entry:
            truth_s = score_hash(q_ph, q_dh, q_ah, truth_entry)
            if truth_s >= best_score:
                correct += 1
    return correct / len(test_set) if test_set else 0.0


def accuracy_hog_only(cache: list[_CachedEntry], test_set: list[tuple[np.ndarray, str]], cosine: bool) -> float:
    correct = 0
    hog_fn = score_hog_cosine if cosine else score_hog_l2
    for img, truth_id in test_set:
        gray = _to_gray(img)
        q_hog = _compute_hog(gray)
        best_id, best_score = None, -1.0
        for entry in cache:
            if entry.image_id == truth_id:
                continue
            s = hog_fn(q_hog, entry)
            if s > best_score:
                best_score, best_id = s, entry.image_id
        truth_entry = next((e for e in cache if e.image_id == truth_id), None)
        if truth_entry:
            truth_s = hog_fn(q_hog, truth_entry)
            if truth_s >= best_score:
                correct += 1
    return correct / len(test_set) if test_set else 0.0


def accuracy_orb_only(cache: list[_CachedEntry], test_set: list[tuple[np.ndarray, str]]) -> float:
    correct = 0
    for img, truth_id in test_set:
        gray = _to_gray(img)
        q_orb = _compute_orb(gray)
        best_id, best_score = None, -1.0
        for entry in cache:
            if entry.image_id == truth_id:
                continue
            s = score_orb(q_orb, entry)
            if s > best_score:
                best_score, best_id = s, entry.image_id
        truth_entry = next((e for e in cache if e.image_id == truth_id), None)
        if truth_entry:
            truth_s = score_orb(q_orb, truth_entry)
            if truth_s >= best_score:
                correct += 1
    return correct / len(test_set) if test_set else 0.0


# ------------------------------------------------------------------
# 리포트 출력
# ------------------------------------------------------------------

def print_report(stats: BenchmarkStats, label: str = "현재 파이프라인"):
    results = stats.results
    correct = [r for r in results if r.correct]
    wrong   = [r for r in results if not r.correct]

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  정답률:  {stats.accuracy*100:.1f}%  ({stats.correct}/{stats.total})")

    if not results:
        return

    scores = [r.score_combined for r in results]
    correct_scores = [r.score_combined for r in correct]
    wrong_scores   = [r.score_combined for r in wrong]

    print(f"\n  [점수 분포]")
    print(f"  전체   평균={np.mean(scores):.3f}  min={np.min(scores):.3f}  max={np.max(scores):.3f}")
    if correct_scores:
        print(f"  정답   평균={np.mean(correct_scores):.3f}  min={np.min(correct_scores):.3f}")
    if wrong_scores:
        print(f"  오답   평균={np.mean(wrong_scores):.3f}  max={np.max(wrong_scores):.3f}")

    # ORB keypoint 분포
    kp_counts = [r.orb_keypoints for r in results]
    low_kp = sum(1 for k in kp_counts if k < 20)
    print(f"\n  [ORB Keypoint]")
    print(f"  평균={np.mean(kp_counts):.1f}  min={np.min(kp_counts)}  max={np.max(kp_counts)}")
    print(f"  20개 미만: {low_kp}/{len(kp_counts)} ({low_kp/len(kp_counts)*100:.1f}%)")

    # 오매칭 상위 10개
    if wrong:
        print(f"\n  [오매칭 케이스 상위 10개] (점수 높은 순)")
        wrong_sorted = sorted(wrong, key=lambda r: r.score_combined, reverse=True)
        for r in wrong_sorted[:10]:
            print(
                f"  truth={r.song_id:>6} → pred={r.predicted:>6}  "
                f"combined={r.score_combined:.3f}  "
                f"hash={r.score_hash:.3f}  hog={r.score_hog:.3f}  orb={r.score_orb:.3f}  "
                f"kp={r.orb_keypoints}"
            )


# ------------------------------------------------------------------
# 메인
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="재킷 매칭 benchmark")
    parser.add_argument("--jacket-dir", required=True, help="재킷 이미지 폴더 경로")
    parser.add_argument("--db", default="cache/image_index.db", help="image_index.db 경로")
    parser.add_argument("--limit", type=int, default=0, help="테스트 수 제한 (0=전체)")
    parser.add_argument("--cosine", action="store_true", help="HOG 코사인 유사도 비교도 함께 측정")
    args = parser.parse_args()

    jacket_dir = Path(args.jacket_dir)
    if not jacket_dir.is_dir():
        print(f"[ERROR] 폴더 없음: {jacket_dir}")
        sys.exit(1)

    print(f"[benchmark] DB 로드 중: {args.db}")
    t0 = time.time()
    cache = load_cache(args.db)
    print(f"[benchmark] {len(cache)}곡 로드 완료 ({time.time()-t0:.2f}s)")

    # 테스트셋 구성: DB에 있는 song_id만
    db_ids = {e.image_id for e in cache}
    files = [
        f for f in jacket_dir.iterdir()
        if f.suffix.lower() in SUPPORTED_EXT and f.stem.isdigit() and f.stem in db_ids
    ]

    if args.limit > 0:
        files = files[:args.limit]

    if not files:
        print("[ERROR] DB에 매칭되는 이미지 파일이 없음")
        sys.exit(1)

    print(f"[benchmark] 테스트 이미지: {len(files)}개\n")

    # 이미지 로드
    test_set: list[tuple[np.ndarray, str]] = []
    for f in files:
        img = cv2.imread(str(f), cv2.IMREAD_UNCHANGED)
        if img is not None:
            test_set.append((img, f.stem))

    # ------------------------------------------------------------------
    # 1. 현재 파이프라인 (L2 HOG)
    # ------------------------------------------------------------------
    stats = BenchmarkStats()
    t0 = time.time()
    for img, truth_id in test_set:
        r = evaluate_one(img, truth_id, cache, use_cosine_hog=False)
        stats.total += 1
        if r.correct:
            stats.correct += 1
        stats.results.append(r)
    elapsed = time.time() - t0
    print_report(stats, label="현재 파이프라인 (HOG L2)")
    print(f"  측정 시간: {elapsed:.2f}s ({elapsed/len(test_set)*1000:.1f}ms/곡)")

    # ------------------------------------------------------------------
    # 2. HOG 코사인 버전 비교 (--cosine 옵션)
    # ------------------------------------------------------------------
    if args.cosine:
        stats_cos = BenchmarkStats()
        for img, truth_id in test_set:
            r = evaluate_one(img, truth_id, cache, use_cosine_hog=True)
            stats_cos.total += 1
            if r.correct:
                stats_cos.correct += 1
            stats_cos.results.append(r)
        print_report(stats_cos, label="HOG 코사인 버전")

    # ------------------------------------------------------------------
    # 3. feature별 단독 정답률
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print("  feature별 단독 정답률")
    print(f"{'='*60}")

    t0 = time.time()
    acc_hash = accuracy_hash_only(cache, test_set)
    print(f"  Hash only (pHash+dHash+aHash): {acc_hash*100:.1f}%  ({time.time()-t0:.2f}s)")

    t0 = time.time()
    acc_hog_l2 = accuracy_hog_only(cache, test_set, cosine=False)
    print(f"  HOG only  (L2):                {acc_hog_l2*100:.1f}%  ({time.time()-t0:.2f}s)")

    t0 = time.time()
    acc_hog_cos = accuracy_hog_only(cache, test_set, cosine=True)
    print(f"  HOG only  (cosine):            {acc_hog_cos*100:.1f}%  ({time.time()-t0:.2f}s)")

    t0 = time.time()
    acc_orb = accuracy_orb_only(cache, test_set)
    print(f"  ORB only:                      {acc_orb*100:.1f}%  ({time.time()-t0:.2f}s)")

    print()


if __name__ == "__main__":
    main()
