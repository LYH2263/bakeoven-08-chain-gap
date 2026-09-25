"""Oven scheduling with half-open ferment+bake intervals and next free window.

Also validates 同炉连烤 chain groups: batches sharing a chain group number
must sit on one oven and chain within the group's registered max gap.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Interval:
    start: int  # minutes from day origin
    end: int  # exclusive

    def overlaps(self, other: "Interval") -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True)
class RecipeDurations:
    ferment_min: int
    bake_min: int

    @property
    def total(self) -> int:
        return self.ferment_min + self.bake_min


@dataclass(frozen=True)
class Occupancy:
    oven_id: int
    interval: Interval
    phase: str  # ferment | bake
    batch_id: int


def build_occupancies(
    oven_id: int,
    batch_id: int,
    start_min: int,
    recipe: RecipeDurations,
) -> list[Occupancy]:
    ferment = Interval(start_min, start_min + recipe.ferment_min)
    bake = Interval(ferment.end, ferment.end + recipe.bake_min)
    return [
        Occupancy(oven_id, ferment, "ferment", batch_id),
        Occupancy(oven_id, bake, "bake", batch_id),
    ]


def find_conflicts(existing: list[Occupancy], candidates: list[Occupancy]) -> list[tuple[Occupancy, Occupancy]]:
    hits: list[tuple[Occupancy, Occupancy]] = []
    for cand in candidates:
        for ex in existing:
            if ex.oven_id != cand.oven_id:
                continue
            if ex.interval.overlaps(cand.interval):
                hits.append((ex, cand))
    return hits


def next_free_window(
    existing: list[Occupancy],
    oven_id: int,
    duration: int,
    search_from: int = 0,
    search_to: int = 24 * 60,
) -> Interval | None:
    """Find earliest half-open [start, start+duration) free on oven."""
    if duration <= 0:
        return None
    busy = sorted(
        [o.interval for o in existing if o.oven_id == oven_id],
        key=lambda i: i.start,
    )
    cursor = search_from
    for iv in busy:
        if iv.end <= cursor:
            continue
        if iv.start >= cursor + duration:
            end = cursor + duration
            if end <= search_to:
                return Interval(cursor, end)
            return None
        cursor = max(cursor, iv.end)
    if cursor + duration <= search_to:
        return Interval(cursor, cursor + duration)
    return None


@dataclass(frozen=True)
class ChainMember:
    """One batch's occupancy as a member of a same-oven chain group."""

    batch_id: int
    code: str
    oven_id: int
    start_min: int  # occupancy start
    end_min: int  # occupancy end (exclusive)
    max_gap_min: int  # max idle gap this member registered for the group


@dataclass(frozen=True)
class ChainViolation:
    kind: str  # "跨炉" | "空档"
    prev_id: int
    prev_code: str
    next_id: int
    next_code: str
    detail: str


def validate_chain_group(group: str, members: list[ChainMember]) -> ChainViolation | None:
    """Return the first chain-group violation, or None when the group is valid.

    Members are ordered by occupancy start. Every member must sit on the same
    oven (跨炉), and for each consecutive pair the later batch's start must land
    in [prev.end, prev.end + max_gap] (空档). The group's max gap is the
    strictest value registered by its members, so 0 forces back-to-back
    placement exactly on the previous batch's occupancy end.
    """
    ordered = sorted(members, key=lambda m: (m.start_min, m.batch_id))
    for prev, nxt in zip(ordered, ordered[1:]):
        if prev.oven_id != nxt.oven_id:
            detail = (
                f"连烤组「{group}」跨炉：前批 #{prev.batch_id}({prev.code}) 在炉#{prev.oven_id}，"
                f"后批 #{nxt.batch_id}({nxt.code}) 在炉#{nxt.oven_id}，同组须同炉"
            )
            return ChainViolation("跨炉", prev.batch_id, prev.code, nxt.batch_id, nxt.code, detail)
    if len(ordered) < 2:
        return None
    max_gap = min(m.max_gap_min for m in ordered)
    for prev, nxt in zip(ordered, ordered[1:]):
        gap = nxt.start_min - prev.end_min
        if gap < 0:
            detail = (
                f"连烤组「{group}」空档冲突：后批 #{nxt.batch_id}({nxt.code}) 开工 {nxt.start_min} "
                f"早于前批 #{prev.batch_id}({prev.code}) 占炉结束 {prev.end_min}"
            )
            return ChainViolation("空档", prev.batch_id, prev.code, nxt.batch_id, nxt.code, detail)
        if gap > max_gap:
            detail = (
                f"连烤组「{group}」空档超限：前批 #{prev.batch_id}({prev.code}) 占炉结束 {prev.end_min}，"
                f"后批 #{nxt.batch_id}({nxt.code}) 开工 {nxt.start_min}，"
                f"空档 {gap} 分钟 > 最大 {max_gap} 分钟"
            )
            return ChainViolation("空档", prev.batch_id, prev.code, nxt.batch_id, nxt.code, detail)
    return None
