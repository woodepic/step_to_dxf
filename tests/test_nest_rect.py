"""The rectangle nesting engine: maximal rectangles plus goal-driven search."""
from __future__ import annotations

import pytest

from plynest.nest_rect import (
    MaxRects,
    RULES,
    _prune,
    _split,
    lower_bound,
    RectItem,
    solve,
)


def rects_of(bins, sizes, kerf=0.0):
    """Actual (x, y, w, h) of each placement, kerf excluded."""
    out = []
    for placements in bins:
        sheet = []
        for p in placements:
            w, h = sizes[p.key]
            if p.rotated:
                w, h = h, w
            sheet.append((p.x, p.y, w, h))
        out.append(sheet)
    return out


def overlap(a, b, gap=0.0):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return (ax < bx + bw + gap - 1e-9 and bx < ax + aw + gap - 1e-9
            and ay < by + bh + gap - 1e-9 and by < ay + ah + gap - 1e-9)


# --- the invariants a cut file depends on -----------------------------------

def test_every_rectangle_is_placed_exactly_once():
    sizes = [(120 + i, 80 + (i % 7) * 13) for i in range(60)]
    bins, report = solve(sizes, 1000, 2000, kerf=5.0, effort=0.5)
    keys = [p.key for b in bins for p in b]
    assert sorted(keys) == list(range(len(sizes)))
    assert report.sheets == len(bins)


def test_nothing_overlaps_and_the_kerf_is_respected():
    sizes = [(150 + (i % 9) * 20, 110 + (i % 5) * 30) for i in range(70)]
    kerf = 6.35
    bins, _ = solve(sizes, 1000, 2000, kerf=kerf, effort=1.0)
    for sheet in rects_of(bins, sizes):
        for i in range(len(sheet)):
            for j in range(i + 1, len(sheet)):
                assert not overlap(sheet[i], sheet[j]), "parts overlap"
                # Separation on at least one axis must reach the kerf.
                ax, ay, aw, ah = sheet[i]
                bx, by, bw, bh = sheet[j]
                gap_x = max(bx - (ax + aw), ax - (bx + bw))
                gap_y = max(by - (ay + ah), ay - (by + bh))
                assert max(gap_x, gap_y) >= kerf - 1e-6


def test_everything_stays_on_the_sheet():
    sizes = [(200, 300)] * 40
    bins, _ = solve(sizes, 1000, 2000, kerf=5.0, effort=0.5)
    for sheet in rects_of(bins, sizes):
        for x, y, w, h in sheet:
            assert x >= -1e-9 and y >= -1e-9
            assert x + w <= 1000 + 1e-6 and y + h <= 2000 + 1e-6


def test_no_sheet_comes_back_empty():
    bins, _ = solve([(300, 400)] * 12, 1000, 2000, kerf=5.0, effort=0.5)
    assert all(b for b in bins)


# --- rotation ---------------------------------------------------------------

def test_rotation_can_be_forbidden():
    sizes = [(900, 150)] * 10
    bins, _ = solve(sizes, 1000, 2000, kerf=5.0, rotations=(False,), effort=0.3)
    assert not any(p.rotated for b in bins for p in b)


def test_rotation_is_used_when_it_helps():
    """A part that only fits turned must still be placed."""
    bins, _ = solve([(1900, 400)], 500, 2000, kerf=0.0, effort=0.1)
    assert bins is not None and len(bins) == 1
    assert bins[0][0].rotated


def test_a_part_too_big_for_any_orientation_is_refused():
    bins, _ = solve([(5000, 5000)], 1000, 2000, kerf=0.0, effort=0.1)
    assert bins is None


# --- search quality ---------------------------------------------------------

def test_search_never_does_worse_than_the_greedy_pass():
    sizes = [(180 + (i % 11) * 17, 240 + (i % 7) * 23) for i in range(120)]
    _, report = solve(sizes, 1168.4, 2387.6, kerf=6.35, effort=2.0)
    assert report.sheets <= report.improved_from


def test_a_perfect_grid_packs_with_no_waste():
    """Ten by four parts that tile the sheet exactly must use one sheet."""
    sizes = [(100.0, 100.0)] * 40
    bins, report = solve(sizes, 1000.0, 400.0, kerf=0.0, effort=0.5)
    assert len(bins) == 1
    assert report.optimal


def test_the_area_lower_bound_is_reported_and_respected():
    sizes = [(500.0, 500.0)] * 8
    bins, report = solve(sizes, 1000.0, 1000.0, kerf=0.0, effort=0.5)
    assert report.lower_bound == 2
    assert report.sheets >= report.lower_bound


def test_more_effort_is_never_worse():
    sizes = [(170 + (i % 13) * 21, 230 + (i % 5) * 41) for i in range(90)]
    quick, _ = solve(sizes, 1168.4, 2387.6, kerf=6.35, effort=0.0)
    slow, _ = solve(sizes, 1168.4, 2387.6, kerf=6.35, effort=3.0)
    assert len(slow) <= len(quick)


def test_the_same_seed_gives_the_same_layout():
    sizes = [(150 + i, 200 + (i % 9) * 15) for i in range(50)]
    a, _ = solve(sizes, 1000, 2000, kerf=5.0, effort=1.0, seed=99)
    b, _ = solve(sizes, 1000, 2000, kerf=5.0, effort=1.0, seed=99)
    assert [[(p.key, p.x, p.y, p.rotated) for p in s] for s in a] == \
           [[(p.key, p.x, p.y, p.rotated) for p in s] for s in b]


# --- degenerate input -------------------------------------------------------

def test_no_rectangles_at_all():
    bins, report = solve([], 1000, 2000, kerf=5.0)
    assert bins == [] and report.sheets == 0


def test_a_single_rectangle():
    bins, _ = solve([(100, 200)], 1000, 2000, kerf=5.0, effort=0.1)
    assert len(bins) == 1 and len(bins[0]) == 1


def test_zero_effort_still_returns_a_valid_layout():
    sizes = [(200, 300)] * 25
    bins, report = solve(sizes, 1000, 2000, kerf=5.0, effort=0.0)
    assert sorted(p.key for b in bins for p in b) == list(range(25))
    assert report.iterations == 0


def test_zero_kerf_allows_an_exact_tiling():
    """Eight 250x500 pieces are exactly one 1000x1000 sheet."""
    bins, report = solve([(250.0, 500.0)] * 8, 1000.0, 1000.0, kerf=0.0, effort=0.5)
    assert len(bins) == 1 and report.optimal


def test_kerf_costs_a_sheet_when_the_fit_was_exact():
    """The same pieces no longer tile once a saw kerf is between them."""
    bins, _ = solve([(250.0, 500.0)] * 8, 1000.0, 1000.0, kerf=5.0, effort=0.5)
    assert len(bins) == 2


# --- the free-space structure ----------------------------------------------

def test_splitting_a_free_rectangle_covers_what_is_left():
    pieces = _split((0.0, 0.0, 100.0, 100.0), 20.0, 30.0, 40.0, 50.0)
    assert len(pieces) == 4
    for x, y, w, h in pieces:
        assert w > 0 and h > 0
        assert 0 <= x and 0 <= y and x + w <= 100 and y + h <= 100


def test_a_free_rectangle_that_is_missed_is_left_alone():
    rect = (0.0, 0.0, 10.0, 10.0)
    assert _split(rect, 50.0, 50.0, 5.0, 5.0) == (rect,)


def test_pruning_drops_contained_rectangles():
    kept = _prune([(0, 0, 100, 100), (10, 10, 10, 10), (0, 0, 100, 50)])
    assert (0.0, 0.0, 100.0, 100.0) in kept
    assert len(kept) == 1


def test_free_space_shrinks_by_exactly_what_was_placed():
    sheet = MaxRects(100.0, 100.0)
    sheet.place(0.0, 0.0, 40.0, 30.0)
    assert sheet.used_area == pytest.approx(1200.0)
    assert sheet.fill() == pytest.approx(0.12)
    assert all(w > 0 and h > 0 for _, _, w, h in sheet.free)


def test_quick_reject_agrees_with_the_full_search():
    sheet = MaxRects(100.0, 100.0)
    sheet.place(0.0, 0.0, 90.0, 90.0)
    for w, h in [(5.0, 5.0), (95.0, 95.0), (100.0, 5.0), (8.0, 99.0)]:
        rejected = sheet.cannot_hold(w, h, (False, True))
        found = sheet.find(w, h, RULES["bssf"], (False, True))
        assert not (rejected and found is not None), "quick reject lost a real fit"


@pytest.mark.parametrize("rule", list(RULES))
def test_every_rule_produces_a_valid_layout(rule):
    sizes = [(120 + (i % 8) * 30, 90 + (i % 6) * 25) for i in range(40)]
    bins, _ = solve(sizes, 1000, 2000, kerf=4.0, effort=0.0)
    assert sorted(p.key for b in bins for p in b) == list(range(40))


def test_lower_bound_is_a_true_bound():
    items = [RectItem(i, 300.0, 400.0) for i in range(10)]
    assert lower_bound(items, 1000.0, 1000.0) == 2
    assert lower_bound([], 1000.0, 1000.0) == 1
