"""Unit tests for the manga/ranking/profile compaction helpers (no network)."""

from mal_mcp.server import (
    _authors,
    _build_changes,
    _compact_manga_detail,
    _compact_manga_entry,
    _compact_manga_search_result,
    _compact_profile,
    _compact_ranking_entry,
    _year_from_date,
)

import pytest
from fastmcp.exceptions import ToolError

MANGA_EDGE = {
    "node": {
        "id": 2,
        "title": "Berserk",
        "start_date": "1989-08-25",
        "media_type": "manga",
        "status": "currently_publishing",
        "num_chapters": 0,
        "num_volumes": 0,
        "genres": [{"id": 1, "name": "Action"}, {"id": 2, "name": "Horror"}],
        "mean": 9.47,
        "authors": [
            {"node": {"id": 1868, "first_name": "Kentarou", "last_name": "Miura"}, "role": "Story & Art"}
        ],
    },
    "list_status": {
        "status": "reading",
        "score": 10,
        "num_chapters_read": 370,
        "num_volumes_read": 41,
        "is_rereading": False,
        "updated_at": "2025-11-01T10:00:00+00:00",
    },
}


class TestYearFromDate:
    def test_full_partial_and_bad_dates(self):
        assert _year_from_date("1989-08-25") == 1989
        assert _year_from_date("2017-10") == 2017
        assert _year_from_date("2017") == 2017
        assert _year_from_date(None) is None
        assert _year_from_date("") is None
        assert _year_from_date("abc") is None


class TestAuthors:
    def test_formats_name_and_role(self):
        assert _authors(MANGA_EDGE["node"]["authors"]) == ["Kentarou Miura (Story & Art)"]

    def test_partial_author_data(self):
        assert _authors([{"node": {"first_name": "Solo"}, "role": None}]) == ["Solo"]
        assert _authors([{"node": {}, "role": "Art"}]) == ["Art"]
        assert _authors(None) == []


class TestCompactManga:
    def test_entry(self):
        e = _compact_manga_entry(MANGA_EDGE)
        assert e["id"] == 2
        assert e["year"] == 1989
        assert e["publishing_status"] == "currently_publishing"
        assert e["my_status"] == "reading"
        assert e["my_score"] == 10
        assert e["chapters_read"] == 370
        assert e["volumes_read"] == 41
        assert e["total_chapters"] == 0  # unknown/ongoing
        assert e["genres"] == ["Action", "Horror"]
        assert e["authors"] == ["Kentarou Miura (Story & Art)"]

    def test_search_result_truncates_synopsis(self):
        node = dict(MANGA_EDGE["node"], synopsis="x" * 400)
        r = _compact_manga_search_result(node)
        assert len(r["synopsis"]) == 300 and r["synopsis"].endswith("...")
        assert r["num_chapters"] == 0
        assert r["authors"] == ["Kentarou Miura (Story & Art)"]

    def test_detail(self):
        data = dict(
            MANGA_EDGE["node"],
            serialization=[{"node": {"name": "Young Animal"}}],
            related_manga=[{"node": {"id": 9, "title": "Berserk: Prototype"}, "relation_type": "side_story"}],
            recommendations=[
                {"node": {"id": i, "title": f"R{i}"}, "num_recommendations": i} for i in range(12)
            ],
            my_list_status={"status": "reading", "score": 10},
        )
        d = _compact_manga_detail(data)
        assert d["serialization"] == ["Young Animal"]
        assert d["related_manga"][0]["relation_type"] == "side_story"
        assert len(d["recommendations"]) == 10
        assert d["my_list_status"]["score"] == 10

    def test_detail_omits_absent_my_list_status(self):
        assert "my_list_status" not in _compact_manga_detail({"id": 1, "title": "X"})


class TestCompactRanking:
    def test_anime_entry(self):
        item = {
            "node": {
                "id": 5114,
                "title": "FMA:B",
                "mean": 9.1,
                "media_type": "tv",
                "status": "finished_airing",
                "start_season": {"year": 2009},
                "num_episodes": 64,
                "num_list_users": 3000000,
                "genres": [{"id": 1, "name": "Action"}],
            },
            "ranking": {"rank": 1, "previous_rank": 2},
        }
        e = _compact_ranking_entry(item, "anime")
        assert e["rank"] == 1 and e["previous_rank"] == 2
        assert e["year"] == 2009 and e["num_episodes"] == 64
        assert e["airing_status"] == "finished_airing"

    def test_manga_entry(self):
        e = _compact_ranking_entry(
            {"node": MANGA_EDGE["node"], "ranking": {"rank": 3}}, "manga"
        )
        assert e["rank"] == 3 and e["previous_rank"] is None
        assert e["year"] == 1989
        assert e["publishing_status"] == "currently_publishing"
        assert e["authors"] == ["Kentarou Miura (Story & Art)"]


class TestProfileAndChanges:
    def test_profile_passthrough(self):
        data = {
            "id": 1,
            "name": "zbabew",
            "picture": "https://x/y.jpg",
            "joined_at": "2020-01-01T00:00:00+00:00",
            "time_zone": "Europe/Istanbul",
            "is_supporter": False,
            "anime_statistics": {"num_items": 419, "mean_score": 8.14},
            "unrelated_field": "dropped",
        }
        p = _compact_profile(data)
        assert p["name"] == "zbabew"
        assert p["anime_statistics"]["num_items"] == 419
        assert "unrelated_field" not in p

    def test_build_changes_filters_and_converts(self):
        changes = _build_changes(
            status="watching",
            score=None,
            num_watched_episodes=5,
            is_rewatching=False,
            tags=["favorite", "2026"],
            comments=None,
        )
        assert changes == {
            "status": "watching",
            "num_watched_episodes": 5,
            "is_rewatching": "false",
            "tags": "favorite,2026",
        }

    def test_build_changes_requires_at_least_one_field(self):
        with pytest.raises(ToolError, match="at least one field"):
            _build_changes(status=None, score=None)

    def test_build_changes_rejects_tags_containing_commas(self):
        with pytest.raises(ToolError, match="comma"):
            _build_changes(tags=["good", "bad,tag"])

    def test_build_changes_keeps_zero_values(self):
        # score=0 (remove score) and progress 0 are meaningful and must be sent.
        changes = _build_changes(score=0, num_watched_episodes=0)
        assert changes == {"score": 0, "num_watched_episodes": 0}
