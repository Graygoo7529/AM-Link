from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True, slots=True)
class TemporalHint:
    expression: str
    start: str | None
    end: str | None
    precision: str

    def as_dict(self) -> dict[str, str | None]:
        return {
            "expression": self.expression,
            "start": self.start,
            "end": self.end,
            "precision": self.precision,
        }


_ENGLISH_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_CHINESE_WEEKDAYS = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}


def extract_temporal_hint(
    text: str, *, anchor_time: str | None = None
) -> TemporalHint | None:
    anchor = _anchor_date(anchor_time)

    match = re.search(
        r"(?<!\d)(?P<year>19\d{2}|20\d{2})[-/.年]"
        r"(?P<month>0?[1-9]|1[0-2])[-/.月]"
        r"(?P<day>0?[1-9]|[12]\d|3[01])日?(?!\d)",
        text,
    )
    if match:
        value = _safe_date(match["year"], match["month"], match["day"])
        if value is not None:
            return _day_hint(match.group(0), value)

    match = re.search(
        r"(?<!\d)(?P<year>19\d{2}|20\d{2})[-/.年]"
        r"(?P<month>0?[1-9]|1[0-2])月?(?![-/.月\d])",
        text,
    )
    if match:
        year = int(match["year"])
        month = int(match["month"])
        return _month_hint(match.group(0), year, month)

    relative_days = (
        (r"\bday after tomorrow\b|后天", 2),
        (r"\bday before yesterday\b|前天", -2),
        (r"\btomorrow\b|明天", 1),
        (r"\byesterday\b|昨天", -1),
        (r"\btoday\b|今天", 0),
    )
    for pattern, offset in relative_days:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            if anchor is None:
                return TemporalHint(match.group(0), None, None, "relative-day")
            return _day_hint(match.group(0), anchor + timedelta(days=offset))

    match = re.search(
        r"\b(?P<scope>next|last|this)\s+"
        r"(?P<weekday>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        if anchor is None:
            return TemporalHint(match.group(0), None, None, "relative-day")
        scope_offset = {"last": -1, "this": 0, "next": 1}[
            match["scope"].lower()
        ]
        value = _week_date(
            anchor,
            _ENGLISH_WEEKDAYS[match["weekday"].lower()],
            scope_offset,
        )
        return _day_hint(match.group(0), value)

    match = re.search(r"(?P<scope>上|本|这|下)周(?P<weekday>[一二三四五六日天])", text)
    if match:
        if anchor is None:
            return TemporalHint(match.group(0), None, None, "relative-day")
        scope_offset = {"上": -1, "本": 0, "这": 0, "下": 1}[match["scope"]]
        value = _week_date(
            anchor,
            _CHINESE_WEEKDAYS[match["weekday"]],
            scope_offset,
        )
        return _day_hint(match.group(0), value)

    relative_months = (
        (r"\bnext month\b|下个月", 1),
        (r"\blast month\b|上个月", -1),
        (r"\bthis month\b|本月|这个月", 0),
    )
    for pattern, offset in relative_months:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            if anchor is None:
                return TemporalHint(match.group(0), None, None, "relative-month")
            year, month = _shift_month(anchor.year, anchor.month, offset)
            return _month_hint(match.group(0), year, month)

    return None


def ranges_overlap(
    left_start: str | None,
    left_end: str | None,
    right_start: str | None,
    right_end: str | None,
) -> bool:
    if not left_start or not right_start:
        return False
    normalized_left_end = left_end or _next_day(left_start)
    normalized_right_end = right_end or _next_day(right_start)
    return left_start < normalized_right_end and right_start < normalized_left_end


def _anchor_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def _safe_date(year: str, month: str, day: str) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _day_hint(expression: str, value: date) -> TemporalHint:
    return TemporalHint(
        expression=expression,
        start=value.isoformat(),
        end=(value + timedelta(days=1)).isoformat(),
        precision="day",
    )


def _month_hint(expression: str, year: int, month: int) -> TemporalHint:
    start = date(year, month, 1)
    end_year, end_month = _shift_month(year, month, 1)
    return TemporalHint(
        expression=expression,
        start=start.isoformat(),
        end=date(end_year, end_month, 1).isoformat(),
        precision="month",
    )


def _week_date(anchor: date, weekday: int, week_offset: int) -> date:
    monday = anchor - timedelta(days=anchor.weekday())
    return monday + timedelta(days=weekday, weeks=week_offset)


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    shifted = year * 12 + month - 1 + offset
    return shifted // 12, shifted % 12 + 1


def _next_day(value: str) -> str:
    try:
        return (date.fromisoformat(value[:10]) + timedelta(days=1)).isoformat()
    except ValueError:
        return value
