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


def member(bid, code, oven, start, end, gap):
    return ChainMember(
        batch_id=bid, code=code, oven_id=oven,
        start_min=start, end_min=end, max_gap_min=gap,
    )


def test_chain_single_member_ok():
    assert validate_chain_group("L1", [member(1, "A1", 1, 0, 60, 10)]) is None


def test_chain_valid_within_gap():
    members = [
        member(1, "A1", 1, 0, 60, 15),
        member(2, "A2", 1, 70, 130, 15),
        member(3, "A3", 1, 140, 200, 15),
    ]
    assert validate_chain_group("L1", members) is None


def test_chain_gap_exactly_max_ok():
    members = [member(1, "A1", 1, 0, 60, 15), member(2, "A2", 1, 75, 120, 15)]
    assert validate_chain_group("L1", members) is None


def test_chain_zero_gap_requires_touch():
    ok = [member(1, "A1", 1, 0, 60, 0), member(2, "A2", 1, 60, 120, 0)]
    assert validate_chain_group("L1", ok) is None
    late = [member(1, "A1", 1, 0, 60, 0), member(2, "A2", 1, 61, 121, 0)]
    v = validate_chain_group("L1", late)
    assert v is not None and v.kind == "空档"


def test_chain_cross_oven_rejected():
    members = [member(1, "A1", 1, 0, 60, 10), member(2, "A2", 2, 65, 120, 10)]
    v = validate_chain_group("L1", members)
    assert v is not None and v.kind == "跨炉"
    assert "跨炉" in v.detail
    assert "A1" in v.detail and "A2" in v.detail


def test_chain_gap_exceeded_reports_pair():
    members = [member(1, "A1", 1, 0, 60, 10), member(2, "A2", 1, 75, 120, 10)]
    v = validate_chain_group("L1", members)
    assert v is not None and v.kind == "空档"
    assert "空档" in v.detail
    assert "A1" in v.detail and "A2" in v.detail
    assert v.prev_code == "A1" and v.next_code == "A2"


def test_chain_overlap_is_gap_violation():
    members = [member(1, "A1", 1, 0, 60, 10), member(2, "A2", 1, 50, 110, 10)]
    v = validate_chain_group("L1", members)
    assert v is not None and v.kind == "空档"


def test_chain_members_sorted_by_start():
    # given out of order, validation still applies to the start-time sequence
    members = [
        member(3, "A3", 1, 130, 190, 10),
        member(1, "A1", 1, 0, 60, 10),
        member(2, "A2", 1, 65, 125, 10),
    ]
    assert validate_chain_group("L1", members) is None


def test_chain_uses_strictest_registered_gap():
    members = [member(1, "A1", 1, 0, 60, 30), member(2, "A2", 1, 80, 140, 10)]
    v = validate_chain_group("L1", members)
    assert v is not None and v.kind == "空档"  # 20 > min(30, 10)


def test_chain_insert_between_pair_validates_both_sides():
    members = [
        member(1, "A1", 1, 0, 60, 10),
        member(2, "A2", 1, 65, 125, 10),
        member(3, "A3", 1, 200, 260, 10),  # 75 > 10 after A2
    ]
    v = validate_chain_group("L1", members)
    assert v is not None and v.prev_code == "A2" and v.next_code == "A3"
