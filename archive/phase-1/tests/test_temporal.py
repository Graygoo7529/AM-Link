from __future__ import annotations

from aml_memory.temporal import extract_temporal_hint, ranges_overlap


def test_temporal_hint_resolves_relative_week_and_month() -> None:
    monday = extract_temporal_hint(
        "next Monday", anchor_time="2026-08-05T12:00:00Z"
    )
    chinese = extract_temporal_hint(
        "\u4e0b\u5468\u4e00", anchor_time="2026-08-05T12:00:00Z"
    )
    month = extract_temporal_hint(
        "last month", anchor_time="2026-08-05T12:00:00Z"
    )

    assert monday is not None
    assert (monday.start, monday.end, monday.precision) == (
        "2026-08-10",
        "2026-08-11",
        "day",
    )
    assert chinese is not None and chinese.start == monday.start
    assert month is not None
    assert (month.start, month.end, month.precision) == (
        "2026-07-01",
        "2026-08-01",
        "month",
    )


def test_temporal_hint_preserves_unanchored_relative_expression() -> None:
    hint = extract_temporal_hint("tomorrow")
    assert hint is not None
    assert (hint.expression, hint.start, hint.end) == ("tomorrow", None, None)


def test_temporal_ranges_use_end_exclusive_overlap() -> None:
    assert ranges_overlap("2026-08-10", "2026-08-11", "2026-08-10", "2026-08-11")
    assert not ranges_overlap(
        "2026-08-10", "2026-08-11", "2026-08-11", "2026-08-12"
    )
