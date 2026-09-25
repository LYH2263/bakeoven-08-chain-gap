from app.services.oven_engine import (
    ChainMember,
    Interval,
    Occupancy,
    RecipeDurations,
    build_occupancies,
    find_conflicts,
    next_free_window,
    validate_chain_group,
)


def test_half_open_no_touch_conflict():
    a = Occupancy(1, Interval(0, 30), "bake", 1)
    b = Occupancy(1, Interval(30, 60), "bake", 2)
    assert find_conflicts([a], [b]) == []


def test_overlap_detected():
    recipe = RecipeDurations(20, 30)
    cand = build_occupancies(1, 9, 10, recipe)
    existing = [Occupancy(1, Interval(25, 40), "bake", 1)]
    assert find_conflicts(existing, cand)


def test_next_free_window_after_busy():
    existing = [
        Occupancy(1, Interval(0, 40), "ferment", 1),
        Occupancy(1, Interval(40, 70), "bake", 1),
    ]
    w = next_free_window(existing, 1, duration=30, search_from=0)
    assert w == Interval(70, 100)


def test_next_free_in_gap():
    existing = [
        Occupancy(1, Interval(0, 20), "bake", 1),
        Occupancy(1, Interval(80, 100), "bake", 2),
    ]
    w = next_free_window(existing, 1, duration=30, search_from=0)
    assert w == Interval(20, 50)


def _member(bid: int, code: str, oven_id: int, start: int, end: int) -> ChainMember:
    return ChainMember(bid, code, oven_id, f"炉{oven_id}", start, end)


def test_chain_group_single_member_valid():
    m = _member(1, "B1", 1, 0, 60)
    assert validate_chain_group([m], 0) is None


def test_chain_group_tight_back_to_back_gap_zero():
    members = [
        _member(1, "B1", 1, 0, 60),
        _member(2, "B2", 1, 60, 100),
        _member(3, "B3", 1, 100, 150),
    ]
    assert validate_chain_group(members, 0, "G1") is None


def test_chain_group_orders_by_start_before_checking():
    members = [
        _member(2, "B2", 1, 60, 100),
        _member(1, "B1", 1, 0, 60),
    ]
    assert validate_chain_group(members, 0) is None


def test_chain_group_gap_within_limit():
    members = [
        _member(1, "B1", 1, 0, 60),
        _member(2, "B2", 1, 75, 100),
    ]
    assert validate_chain_group(members, 15) is None


def test_chain_group_gap_over_limit():
    members = [
        _member(1, "B1", 1, 0, 60),
        _member(2, "B2", 1, 80, 100),
    ]
    detail = validate_chain_group(members, 15, "G1")
    assert detail is not None
    assert "空档超限" in detail
    assert "B1" in detail and "B2" in detail
    assert "20" in detail and "15" in detail


def test_chain_group_gap_zero_starts_one_minute_late():
    members = [
        _member(1, "B1", 1, 0, 60),
        _member(2, "B2", 1, 61, 100),
    ]
    detail = validate_chain_group(members, 0)
    assert detail is not None
    assert "空档超限" in detail
    assert "B1" in detail and "B2" in detail


def test_chain_group_negative_gap_rejected():
    members = [
        _member(1, "B1", 1, 0, 60),
        _member(2, "B2", 1, 55, 100),
    ]
    detail = validate_chain_group(members, 10)
    assert detail is not None
    assert "空档不足" in detail
    assert "B1" in detail and "B2" in detail


def test_chain_group_cross_oven_rejected_first():
    members = [
        _member(1, "B1", 1, 0, 60),
        _member(2, "B2", 2, 60, 100),
    ]
    detail = validate_chain_group(members, 0, "G1")
    assert detail is not None
    assert "跨炉" in detail
    assert "B1" in detail and "B2" in detail
    assert "炉1" in detail and "炉2" in detail


def test_chain_group_cross_oven_detected_even_when_gap_also_bad():
    # different oven AND over-gap: cross-oven is the reported reason
    members = [
        _member(1, "B1", 1, 0, 60),
        _member(2, "B2", 2, 200, 240),
    ]
    detail = validate_chain_group(members, 5)
    assert detail is not None
    assert "跨炉" in detail


def test_chain_group_three_members_failure_names_adjacent_pair():
    members = [
        _member(1, "B1", 1, 0, 60),
        _member(2, "B2", 1, 60, 100),
        _member(3, "B3", 1, 130, 180),
    ]
    detail = validate_chain_group(members, 10, "G9")
    assert detail is not None
    assert "B2" in detail and "B3" in detail
    assert "G9" in detail
