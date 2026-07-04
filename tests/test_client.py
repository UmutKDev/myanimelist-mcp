"""Tests for MALClient pagination, paging-URL validation, and error mapping.

Uses httpx.MockTransport - no real network.
"""

import asyncio

import httpx
import pytest

from mal_mcp import mal_client
from mal_mcp.mal_client import (
    MAX_PAGES,
    MALAPIError,
    MALClient,
    MALTokenError,
)


def _edge(i: int) -> dict:
    return {"node": {"id": i, "title": f"A{i}"}, "list_status": {"score": 7}}


def _json_response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def _run(coro):
    return asyncio.run(coro)


async def _fetch_list_with(handler) -> tuple[list, bool]:
    async with MALClient("tok", transport=httpx.MockTransport(handler)) as client:
        return await client.get_anime_list()


class TestPagination:
    def test_merges_pages_and_reports_no_truncation(self):
        seen_urls = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            if "offset=1000" in str(request.url):
                return _json_response({"data": [_edge(2)], "paging": {}})
            return _json_response(
                {
                    "data": [_edge(1)],
                    "paging": {
                        "next": "https://api.myanimelist.net/v2/users/@me/animelist?offset=1000"
                    },
                }
            )

        entries, truncated = _run(_fetch_list_with(handler))
        assert [e["node"]["id"] for e in entries] == [1, 2]
        assert truncated is False
        assert len(seen_urls) == 2
        # first request must carry explicit fields + max page limit
        assert "fields=" in seen_urls[0] and "limit=1000" in seen_urls[0]

    def test_truncation_flag_set_when_cap_exceeded(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                {
                    "data": [_edge(1)],
                    "paging": {
                        "next": "https://api.myanimelist.net/v2/users/@me/animelist?offset=1"
                    },
                }
            )

        entries, truncated = _run(_fetch_list_with(handler))
        assert len(entries) == MAX_PAGES
        assert truncated is True

    @pytest.mark.parametrize(
        "evil_next",
        [
            "https://evil.example.com/v2/users/@me/animelist?offset=1000",
            "http://api.myanimelist.net/v2/users/@me/animelist?offset=1000",  # http downgrade
        ],
    )
    def test_foreign_or_insecure_paging_next_is_never_followed(self, evil_next):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return _json_response({"data": [_edge(1)], "paging": {"next": evil_next}})

        with pytest.raises(MALAPIError, match="unexpected paging URL"):
            _run(_fetch_list_with(handler))
        assert len(calls) == 1  # the poisoned URL was rejected before any request


class TestBoundedPage:
    def test_passes_params_and_reports_has_more(self):
        def handler(request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            assert params["limit"] == "50"
            assert params["offset"] == "10"
            assert params["status"] == "completed"
            assert params["sort"] == "list_score"
            assert "fields" in params
            return _json_response({"data": [_edge(1)], "paging": {"next": "x"}})

        async def go():
            async with MALClient("tok", transport=httpx.MockTransport(handler)) as client:
                return await client.get_anime_list_page(
                    status="completed", sort="list_score", limit=50, offset=10
                )

        edges, has_more = _run(go())
        assert len(edges) == 1
        assert has_more is True

    def test_no_paging_next_means_no_more(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"data": [], "paging": {}})

        async def go():
            async with MALClient("tok", transport=httpx.MockTransport(handler)) as client:
                return await client.get_anime_list_page()

        edges, has_more = _run(go())
        assert edges == []
        assert has_more is False


class TestErrorMapping:
    def test_401_raises_token_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"error": "invalid_token", "message": "token is invalid"}, 401)

        with pytest.raises(MALTokenError, match="expired or invalid"):
            _run(_fetch_list_with(handler))

    def test_403_retries_then_raises_rate_limit_error(self, monkeypatch):
        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr(mal_client.asyncio, "sleep", fake_sleep)
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return _json_response({"error": "forbidden", "message": ""}, 403)

        with pytest.raises(MALAPIError, match="rate limiting"):
            _run(_fetch_list_with(handler))
        assert len(calls) == 4  # initial + MAX_RETRIES
        assert sleeps == [1, 2, 4]

    def test_400_raises_with_mal_message(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"error": "bad_request", "message": "invalid q"}, 400)

        async def go():
            async with MALClient("tok", transport=httpx.MockTransport(handler)) as client:
                return await client.search_anime("ab")

        with pytest.raises(MALAPIError, match="invalid q"):
            _run(go())

    def test_timeout_maps_to_meaningful_error_without_token(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("boom")

        with pytest.raises(MALAPIError) as excinfo:
            _run(_fetch_list_with(handler))
        assert "tok" not in str(excinfo.value)  # never leak the bearer token

    def test_non_json_success_body_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>maintenance</html>")

        with pytest.raises(MALAPIError, match="non-JSON"):
            _run(_fetch_list_with(handler))


class TestRequestShape:
    def test_bearer_header_and_fields_sent_on_search_and_detail(self):
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return _json_response({"data": []} if "animelist" not in str(request.url) else {})

        async def go():
            async with MALClient("secret-token", transport=httpx.MockTransport(handler)) as c:
                await c.search_anime("monster", limit=5)
                await c.get_anime_detail(19)

        _run(go())
        search_req, detail_req = captured
        assert search_req.headers["Authorization"] == "Bearer secret-token"
        assert dict(search_req.url.params)["q"] == "monster"
        assert dict(search_req.url.params)["limit"] == "5"
        assert detail_req.url.path.endswith("/anime/19")
        assert "my_list_status" in dict(detail_req.url.params)["fields"]
