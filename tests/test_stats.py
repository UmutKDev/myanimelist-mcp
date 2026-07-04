"""Unit tests for the pure helpers in mal_mcp.server (no network)."""

import pytest
from fastmcp.exceptions import ToolError

from mal_mcp.server import (
    _bearer_token,
    _compact_detail,
    _compact_entry,
    _compact_search_result,
    _compute_stats,
    _format_taste,
)

RAW_EDGE = {
    "node": {
        "id": 5114,
        "title": "Fullmetal Alchemist: Brotherhood",
        "main_picture": {"medium": "https://example/m.jpg", "large": "https://example/l.jpg"},
        "num_episodes": 64,
        "genres": [{"id": 1, "name": "Action"}, {"id": 2, "name": "Adventure"}],
        "mean": 9.1,
        "media_type": "tv",
        "status": "finished_airing",
        "start_season": {"year": 2009, "season": "spring"},
        "average_episode_duration": 1460,
        "studios": [{"id": 4, "name": "Bones"}],
        "rating": "r",
    },
    "list_status": {
        "status": "completed",
        "score": 9,
        "num_episodes_watched": 64,
        "is_rewatching": False,
        "updated_at": "2024-01-15T10:30:00+00:00",
    },
}


def _entry(**overrides):
    base = _compact_entry(RAW_EDGE)
    base.update(overrides)
    return base


class TestCompactEntry:
    def test_full_edge(self):
        e = _compact_entry(RAW_EDGE)
        assert e == {
            "id": 5114,
            "title": "Fullmetal Alchemist: Brotherhood",
            "year": 2009,
            "media_type": "tv",
            "airing_status": "finished_airing",
            "my_status": "completed",
            "my_score": 9,
            "episodes_watched": 64,
            "total_episodes": 64,
            "genres": ["Action", "Adventure"],
            "mal_mean": 9.1,
            "avg_episode_duration_sec": 1460,
            "studios": ["Bones"],
            "updated_at": "2024-01-15T10:30:00+00:00",
        }

    def test_minimal_edge_defaults(self):
        # Without an explicit `fields` param MAL returns only id/title/main_picture;
        # the compactor must survive missing node fields and a missing list_status.
        e = _compact_entry({"node": {"id": 1, "title": "X"}})
        assert e["id"] == 1
        assert e["my_score"] == 0
        assert e["episodes_watched"] == 0
        assert e["total_episodes"] == 0
        assert e["genres"] == []
        assert e["year"] is None
        assert e["my_status"] is None


class TestComputeStats:
    def test_empty_list(self):
        stats = _compute_stats([])
        assert stats["total_entries"] == 0
        assert stats["scores"]["scored_count"] == 0
        assert stats["scores"]["mean"] is None
        assert stats["episodes"]["total_episodes_watched"] == 0
        assert stats["top_genres"] == []

    def test_aggregations(self):
        entries = [
            _entry(),  # completed, score 9, 64 eps x 1460s, Action/Adventure, mean 9.1
            _entry(
                id=30,
                title="B",
                my_status="watching",
                my_score=7,
                episodes_watched=10,
                total_episodes=24,
                genres=["Action"],
                mal_mean=8.0,
                avg_episode_duration_sec=1200,
                studios=["Wit"],
                year=2019,
            ),
            _entry(
                id=31,
                title="C",
                my_status="plan_to_watch",
                my_score=0,
                episodes_watched=0,
                genres=["Drama"],
                mal_mean=None,
                avg_episode_duration_sec=0,
                studios=[],
                year=None,
            ),
        ]
        stats = _compute_stats(entries)
        assert stats["total_entries"] == 3
        assert stats["status_distribution"] == {
            "completed": 1,
            "watching": 1,
            "plan_to_watch": 1,
        }
        assert stats["scores"]["scored_count"] == 2
        assert stats["scores"]["mean"] == 8.0
        assert stats["scores"]["median"] == 8.0
        assert stats["scores"]["histogram_1_to_10"]["9"] == 1
        assert stats["scores"]["histogram_1_to_10"]["7"] == 1
        assert stats["episodes"]["total_episodes_watched"] == 74
        expected_seconds = 64 * 1460 + 10 * 1200
        assert stats["episodes"]["estimated_watch_hours"] == round(expected_seconds / 3600, 1)
        top_genres = {g["name"]: g for g in stats["top_genres"]}
        assert top_genres["Action"]["count"] == 2
        assert top_genres["Action"]["avg_my_score"] == 8.0
        assert top_genres["Drama"]["avg_my_score"] is None
        assert stats["media_type_distribution"] == {"tv": 3}
        assert stats["release_decades"] == {"2000s": 1, "2010s": 1}
        # (9 - 9.1) and (7 - 8.0) -> mean of -0.1 and -1.0 = -0.55
        assert stats["community_comparison"]["avg_my_score_minus_mal_mean"] == -0.55
        assert stats["community_comparison"]["compared_entries"] == 2

    def test_unknown_episode_duration_uses_fallback(self):
        entries = [_entry(avg_episode_duration_sec=0, episodes_watched=10)]
        stats = _compute_stats(entries)
        assert stats["episodes"]["estimated_watch_hours"] == round(10 * 1440 / 3600, 1)


class TestFormatTaste:
    def test_grouping_sorting_and_columns(self):
        entries = [
            _entry(title="Mid", my_score=6),
            _entry(id=2, title="Top", my_score=10, genres=["A", "B", "C", "D"]),
            _entry(
                id=3,
                title="Planned",
                my_status="plan_to_watch",
                my_score=0,
                episodes_watched=0,
                total_episodes=0,
                mal_mean=None,
            ),
        ]
        text = _format_taste(entries)
        lines = text.splitlines()
        assert lines[0].startswith("MAL list snapshot: 3 entries | 2 scored (avg 8)")
        assert "columns: my_score|title|year|type|watched/total_eps|genres|mal_mean" in lines[1]
        # completed group comes first and is sorted by score desc
        completed_idx = next(i for i, l in enumerate(lines) if l.startswith("[completed]"))
        ptw_idx = next(i for i, l in enumerate(lines) if l.startswith("[plan_to_watch]"))
        assert completed_idx < ptw_idx
        assert lines[completed_idx] == "[completed] n=2, avg 8"
        assert lines[completed_idx + 1].startswith("10|Top|2009|tv|64/64|A,B,C|")  # genres capped at 3
        assert lines[completed_idx + 2].startswith("6|Mid|")
        # unscored/unknown values render as '-' / '?'
        assert "-|Planned|2009|tv|0/?|" in text

    def test_unknown_status_group_still_rendered(self):
        text = _format_taste([_entry(my_status=None)])
        assert "[unknown] n=1" in text


class TestSearchAndDetailCompaction:
    def test_search_result_truncates_synopsis(self):
        node = {"id": 1, "title": "X", "synopsis": "s" * 400, "start_season": {"year": 2020}}
        result = _compact_search_result(node)
        assert len(result["synopsis"]) == 300
        assert result["synopsis"].endswith("...")
        assert result["year"] == 2020
        assert result["num_episodes"] == 0

    def test_detail_compaction(self):
        data = {
            "id": 1,
            "title": "X",
            "mean": 8.5,
            "status": "finished_airing",
            "start_season": {"year": 2020, "season": "fall"},
            "genres": [{"id": 1, "name": "Action"}],
            "studios": [{"id": 2, "name": "Bones"}],
            "related_anime": [
                {"node": {"id": 2, "title": "X 2nd Season"}, "relation_type": "sequel"}
            ],
            "recommendations": [
                {"node": {"id": i, "title": f"R{i}"}, "num_recommendations": i} for i in range(15)
            ],
            "my_list_status": {"status": "completed", "score": 8},
        }
        detail = _compact_detail(data)
        assert detail["airing_status"] == "finished_airing"
        assert detail["year"] == 2020
        assert detail["genres"] == ["Action"]
        assert detail["related_anime"] == [
            {"id": 2, "title": "X 2nd Season", "relation_type": "sequel"}
        ]
        assert len(detail["recommendations"]) == 10  # capped
        assert detail["my_list_status"] == {"status": "completed", "score": 8}

    def test_detail_omits_absent_my_list_status(self):
        assert "my_list_status" not in _compact_detail({"id": 1, "title": "X"})


class TestBearerToken:
    def test_missing_token_raises_actionable_error(self, monkeypatch):
        # Outside an HTTP request get_http_headers() returns {}; with no env fallback
        # either, this must surface as a clear ToolError.
        monkeypatch.delenv("MAL_ACCESS_TOKEN", raising=False)
        with pytest.raises(ToolError, match="No MAL access token"):
            _bearer_token()

    def test_env_fallback_used_when_no_header(self, monkeypatch):
        monkeypatch.setenv("MAL_ACCESS_TOKEN", "env-token-123")
        assert _bearer_token() == "env-token-123"

    def test_env_fallback_strips_bearer_prefix(self, monkeypatch):
        monkeypatch.setenv("MAL_ACCESS_TOKEN", "Bearer env-token-123")
        assert _bearer_token() == "env-token-123"
