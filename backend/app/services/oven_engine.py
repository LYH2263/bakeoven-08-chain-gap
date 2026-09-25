"""Oven scheduling with half-open ferment+bake intervals and next free window."""

from __future__ import annotations

from dataclasses import dataclass


def fmt_hhmm(minutes: int) -> str:
    """Minutes from day origin -> HH:MM for conflict messages."""
    sign = "-" if minutes < 0 else ""
    m = abs(minutes)
    return f"{sign}{m // 60:02d}:{m % 60:02d}"


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
    """One batch inside a same-oven chain-bake group (连烤组)."""

    batch_id: int
    code: str
    oven_id: int
    oven_label: str
    start_min: int  # occupancy start (ferment start)
    end_min: int  # occupancy end (bake end, exclusive)


def validate_chain_group(
    members: list[ChainMember],
    max_gap_min: int,
    group_name: str = "",
) -> str | None:
    """Validate a chain-bake group; return a Chinese conflict detail or None.

    Rules, members ordered by occupancy start (early -> late):
    - every member must sit on the same oven (跨炉 -> reject);
    - each next occupancy start must land in
      [prev occupancy end, prev occupancy end + max_gap_min] (空档 -> reject).
      max_gap_min == 0 therefore forces a tight back-to-back chain.
    A single-member (or empty) group is always valid.
    """
    if len(members) < 2:
        return None
    ordered = sorted(members, key=lambda m: (m.start_min, m.batch_id))
    label = f"连烤组「{group_name}」" if group_name else "连烤组"
    for prev, nxt in zip(ordered, ordered[1:]):
        if prev.oven_id != nxt.oven_id:
            return (
                f"{label}跨炉：{prev.code}（{prev.oven_label}）与 "
                f"{nxt.code}（{nxt.oven_label}）不在同一座炉，整组拒绝"
            )
    for prev, nxt in zip(ordered, ordered[1:]):
        gap = nxt.start_min - prev.end_min
        if gap < 0:
            return (
                f"{label}空档不足：{nxt.code} 开工 {fmt_hhmm(nxt.start_min)} "
                f"早于 {prev.code} 收炉 {fmt_hhmm(prev.end_min)}"
                f"（空档 {gap} 分钟，须 ≥0），整组拒绝"
            )
        if gap > max_gap_min:
            return (
                f"{label}空档超限：{prev.code} 收炉 {fmt_hhmm(prev.end_min)}，"
                f"{nxt.code} 开工 {fmt_hhmm(nxt.start_min)}，"
                f"空档 {gap} 分钟超过上限 {max_gap_min} 分钟，整组拒绝"
            )
    return None
