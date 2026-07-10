"""Unit tests for the weekly-schedule helpers (pure, no network)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastmcp.exceptions import ToolError

from mal_mcp.server import (
    _build_schedule,
    _convert_broadcast,
    _resolve_timezone,
    _summarize_schedule,
)

# A fixed anchor so day/time math is deterministic. This is a Wednesday in JST.
NOW = datetime(2026, 7, 8, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
IST = ZoneInfo("Europe/Istanbul")  # JST-6h in summer


def _edge(status="currently_airing", day="friday", start="23:00", **node):
    base = {
        "id": 1,
        "title": "Show",
        "status": status,
        "num_episodes": 12,
        "broadcast": {"day_of_the_week": day, "start_time": start} if day or start else {},
    }
    base.update(node)
    return {"node": base, "list_status": {"score": 8, "num_episodes_watched": 3}}


class TestResolveTimezone:
    def test_none_means_jst(self):
        assert _resolve_timezone(None) is None
        assert _resolve_timezone("") is None

    def test_valid_iana(self):
        assert _resolve_timezone("Europe/Istanbul") == IST

    def test_invalid_raises_actionable_error(self):
        with pytest.raises(ToolError, match="Unknown timezone"):
            _resolve_timezone("Mars/Olympus")


class TestConvertBroadcast:
    def test_jst_passthrough(self):
        assert _convert_broadcast("friday", "23:00", None, now=NOW) == ("friday", "23:00")

    def test_convert_shifts_time_and_day(self):
        # Friday 23:00 JST is Friday 17:00 in Istanbul (same day here).
        assert _convert_broadcast("friday", "23:00", IST, now=NOW) == ("friday", "17:00")

    def test_early_jst_hour_can_move_to_previous_local_day(self):
        # Monday 02:00 JST -> Sunday 20:00 in Istanbul (JST-6h crosses midnight back).
        assert _convert_broadcast("monday", "02:00", IST, now=NOW) == ("sunday", "20:00")

    def test_late_night_hour_normalizes(self):
        # MAL sometimes encodes 1am as '25:00' (Friday) -> Saturday 01:00 JST.
        assert _convert_broadcast("friday", "25:00", None, now=NOW) == ("saturday", "01:00")

    def test_missing_time_keeps_day_drops_time(self):
        assert _convert_broadcast("friday", None, IST, now=NOW) == ("friday", None)

    def test_missing_day_is_unplaceable(self):
        assert _convert_broadcast(None, "23:00", IST, now=NOW) == (None, None)


class TestBuildSchedule:
    def test_groups_by_day_and_excludes_non_airing(self):
        edges = [
            _edge(day="friday", start="23:00", id=1, title="Fri A"),
            _edge(day="friday", start="22:00", id=2, title="Fri B"),
            _edge(day="monday", start="18:00", id=3, title="Mon"),
            _edge(status="finished_airing", id=4, title="Done"),  # excluded
        ]
        days, total = _build_schedule(edges, None, now=NOW)
        assert total == 3
        by_day = {d["day"]: d["entries"] for d in days}
        assert [e["title"] for e in by_day["friday"]] == ["Fri B", "Fri A"]  # sorted by time
        assert [e["title"] for e in by_day["monday"]] == ["Mon"]
        assert all(d["entries"] == [] for d in days if d["day"] in {"tuesday", "sunday"})

    def test_airing_without_broadcast_goes_unscheduled(self):
        edges = [_edge(day=None, start=None, id=9, title="No slot")]
        days, total = _build_schedule(edges, None, now=NOW)
        assert total == 1
        unscheduled = next(d for d in days if d["day"] == "unscheduled")
        assert unscheduled["entries"][0]["title"] == "No slot"
        assert unscheduled["entries"][0]["broadcast_time"] is None

    def test_entry_shape_carries_progress_and_picture(self):
        edge = _edge(id=5, title="X", main_picture={"medium": "https://cdn/x.jpg"})
        days, _ = _build_schedule([edge], None, now=NOW)
        entry = next(e for d in days for e in d["entries"])
        assert entry["id"] == 5
        assert entry["picture"] == "https://cdn/x.jpg"
        assert entry["episodes_watched"] == 3
        assert entry["total_episodes"] == 12
        assert entry["my_score"] == 8
        assert "day" not in entry  # internal grouping key is popped


class TestSummarizeSchedule:
    def test_empty(self):
        text = _summarize_schedule([{"day": d, "entries": []} for d in ("monday",)], 0, "Asia/Tokyo", "monday")
        assert "no currently-airing anime" in text

    def test_marks_today_and_lists_times(self):
        days, total = _build_schedule([_edge(day="friday", start="23:00", title="Frieren")], None, now=NOW)
        text = _summarize_schedule(days, total, "Asia/Tokyo", "friday")
        assert "friday <- today" in text
        assert "23:00 Frieren" in text
