"""Ball-level alignment of AUCB enrichment balls onto Cricsheet deliveries.

Each AUCB fixture is aligned against every Cricsheet candidate match (same
format family, dates within a day, >= 60% surname overlap). Within an innings
the balls of each over are aligned with a small Needleman-Wunsch alignment that
scores bowler, batter, runs off the bat, extras, wide/no-ball flags and
wickets. The candidate with the highest share of confidently aligned balls
wins. Two measures are kept per fixture:

- precision: share of the AUCB fixture's balls that aligned. A wrong match
  cannot reach a high precision, so acceptance is gated on it
  (``MIN_MATCH_PRECISION``), and the winner must beat the runner-up clearly.
- coverage: share of the Cricsheet match's deliveries that received
  enrichment. A partial AUCB record (e.g. a Test with days missing) has high
  precision but low coverage; its balls are still attached.

Why per over: over numbers agree between the feeds (AUCB is 1-based, Cricsheet
0-based), they keep each alignment tiny, and a missing AUCB delivery only
disturbs its own over.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

GAP = -1.0
ACCEPT_SCORE = 3.0
MIN_MATCH_PRECISION = 0.80
MIN_PRECISION_MARGIN = 0.20


@dataclass(frozen=True, slots=True)
class Ball:
    key: int  # source row key (enrichment seq or Cricsheet innings_delivery_seq)
    over: int  # 0-based
    batter: tuple[str, str] | None  # (surname, first initial)
    bowler: tuple[str, str] | None
    runs_bat: int | None  # None = unknown (blank source row)
    extras: int | None
    is_wide: bool
    is_noball: bool
    is_wicket: bool
    bowler_id: str | None = None  # Cricsheet identifier when known (alias-resolved for sources)


_NON_LETTERS = re.compile(r"[^a-z ]+")


def name_key(name: str | None) -> tuple[str, str] | None:
    """(surname, first initial) for a player name, accent- and case-folded."""
    if not name:
        return None
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    tokens = _NON_LETTERS.sub(" ", folded).split()  # hyphens split, as in the SQL surname rule
    if not tokens:
        return None
    return tokens[-1], tokens[0][0]


def _name_score(a: tuple[str, str] | None, c: tuple[str, str] | None, hit: float, miss: float) -> float:
    if a is None or c is None:
        return 0.0
    if a[0] != c[0]:
        return miss
    return hit + (1.0 if a[1] == c[1] else 0.0)


BOWLER_MISMATCH = -20.0


def ball_score(a: Ball, c: Ball) -> float:
    # The bowler is fixed for the whole over, so a bowler mismatch means a
    # different ball altogether: it can never be accepted. Identity is compared
    # by Cricsheet identifier when both sides know it (this handles name
    # variants such as "Mehidy Hasan" / "Mehedi Hasan Miraz"), else by surname.
    if a.bowler_id is not None and c.bowler_id is not None:
        if a.bowler_id != c.bowler_id:
            return BOWLER_MISMATCH
        score = 3.0
    elif a.bowler is not None and c.bowler is not None and a.bowler[0] != c.bowler[0]:
        return BOWLER_MISMATCH
    else:
        score = _name_score(a.bowler, c.bowler, 2.0, -4.0)
    score += _name_score(a.batter, c.batter, 2.0, -3.0)
    if a.runs_bat is not None and c.runs_bat is not None:
        score += 1.0 if a.runs_bat == c.runs_bat else -2.0
    if a.extras is not None and c.extras is not None:
        score += 1.0 if a.extras == c.extras else -1.0
    score += 1.0 if a.is_wide == c.is_wide else -2.0
    score += 1.0 if a.is_noball == c.is_noball else -2.0
    score += 1.0 if a.is_wicket == c.is_wicket else -2.0
    return score


def align_sequences(src: Sequence[Ball], cs: Sequence[Ball]) -> list[tuple[int, int, float]]:
    """Global alignment of two short ball sequences; returns accepted (i, j, score)."""
    n, m = len(src), len(cs)
    if n == 0 or m == 0:
        return []
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]  # 0 diag, 1 up (skip src), 2 left (skip cs)
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + GAP
        back[i][0] = 1
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + GAP
        back[0][j] = 2
    scores = [[ball_score(a, c) for c in cs] for a in src]
    for i in range(1, n + 1):
        row, prev, srow = dp[i], dp[i - 1], scores[i - 1]
        brow = back[i]
        for j in range(1, m + 1):
            diag = prev[j - 1] + srow[j - 1]
            up = prev[j] + GAP
            left = row[j - 1] + GAP
            if diag >= up and diag >= left:
                row[j], brow[j] = diag, 0
            elif up >= left:
                row[j], brow[j] = up, 1
            else:
                row[j], brow[j] = left, 2
    pairs: list[tuple[int, int, float]] = []
    i, j = n, m
    while i > 0 and j > 0:
        step = back[i][j]
        if step == 0:
            s = scores[i - 1][j - 1]
            if s >= ACCEPT_SCORE:
                pairs.append((i - 1, j - 1, s))
            i, j = i - 1, j - 1
        elif step == 1:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def _by_over(balls: Iterable[Ball]) -> dict[int, list[Ball]]:
    grouped: dict[int, list[Ball]] = defaultdict(list)
    for ball in balls:
        grouped[ball.over].append(ball)
    return grouped


@dataclass(slots=True)
class InningsAlignment:
    pairs: list[tuple[int, int, float]]  # (src key, cs key, score)
    src_balls: int
    cs_balls: int


OVER_OFFSETS = (0, 1, -1)


def _align_with_offset(src_overs: dict[int, list[Ball]], cs_overs: dict[int, list[Ball]], offset: int):
    pairs: list[tuple[int, int, float]] = []
    for over in sorted(src_overs):
        c = cs_overs.get(over + offset)
        if c:
            a = src_overs[over]
            pairs.extend((a[i].key, c[j].key, s) for i, j, s in align_sequences(a, c))
    return pairs


def align_innings(src: Sequence[Ball], cs: Sequence[Ball]) -> InningsAlignment:
    """Align one innings, trying small over-number offsets.

    Older odata fixtures number overs from 0 while AUCB numbers them from 1, so
    the offset that aligns the most balls is chosen per innings. Offset 0 is
    kept whenever it already aligns 90% of the shorter record.
    """
    src_overs, cs_overs = _by_over(src), _by_over(cs)
    shorter = min(len(src), len(cs)) or 1
    best: list[tuple[int, int, float]] = []
    for offset in OVER_OFFSETS:
        pairs = _align_with_offset(src_overs, cs_overs, offset)
        if len(pairs) > len(best):
            best = pairs
        if offset == 0 and len(pairs) >= 0.9 * shorter:
            break
    return InningsAlignment(pairs=best, src_balls=len(src), cs_balls=len(cs))


Innings = dict[int, list[Ball]]  # innings number -> balls


@dataclass(slots=True)
class MatchAlignment:
    match_id: str
    precision: float
    coverage: float
    innings_map: dict[int, int]  # src innings -> cs innings
    pairs: list[tuple[int, int, int, int, float]]  # (src innings, src key, cs innings, cs key, score)
    src_balls: int
    cs_balls: int


def align_match(match_id: str, src: Innings, cs: Innings) -> MatchAlignment:
    """Align each source innings to the same-numbered Cricsheet innings."""
    pairs: list = []
    innings_map: dict[int, int] = {}
    total_src = sum(len(v) for v in src.values())
    total_cs = sum(len(v) for v in cs.values())
    for inn, balls in src.items():
        if inn not in cs:
            continue
        result = align_innings(balls, cs[inn])
        if result.pairs:
            innings_map[inn] = inn
            pairs.extend((inn, s_key, inn, c_key, score) for s_key, c_key, score in result.pairs)
    return MatchAlignment(
        match_id=match_id,
        precision=len(pairs) / (total_src or 1),
        coverage=len(pairs) / (total_cs or 1),
        innings_map=innings_map,
        pairs=pairs,
        src_balls=total_src,
        cs_balls=total_cs,
    )


def best_alignment(src: Innings, candidates: dict[str, Innings]) -> tuple[MatchAlignment | None, dict[str, float]]:
    """Most precise candidate plus every candidate's precision (for audit)."""
    results = [align_match(mid, src, cs) for mid, cs in candidates.items()]
    if not results:
        return None, {}
    best = max(results, key=lambda r: (r.precision, r.coverage, r.match_id))
    return best, {r.match_id: r.precision for r in results}


def _worker(job: tuple[str, str, Innings, dict[str, Innings]]):
    src_name, fixture_id, src, candidates = job
    best, agreements = best_alignment(src, candidates)
    return src_name, fixture_id, best, agreements


def run_alignment(jobs: list[tuple[str, str, Innings, dict[str, Innings]]], workers: int = 8):
    with ProcessPoolExecutor(max_workers=workers) as pool:
        yield from pool.map(_worker, jobs, chunksize=16)
