"""Contract tests for the MCP Apps UI layer (offline; no built bundle required)."""

import asyncio
import os

import pytest
from fastmcp import Client
from fastmcp.tools import ToolResult

import mal_mcp.server as server
import mal_mcp.ui as ui
from mal_mcp.server import mcp
from mal_mcp.ui import APP_RESOURCE_URI, MAL_IMAGE_CDNS, ui_result

UI_TOOLS = {
    "get_my_anime_list",
    "get_user_stats",
    "search_anime",
    "get_anime_detail",
    "search_manga",
    "get_manga_detail",
    "get_my_manga_list",
    "get_anime_ranking",
    "get_manga_ranking",
    "get_seasonal_anime",
    "get_suggested_anime",
    "get_weekly_schedule",
    "get_my_profile",
    "get_user_anime_list",
    "get_user_manga_list",
}
NON_UI_TOOLS = {
    "analyze_taste",
    "update_my_anime_entry",
    "delete_my_anime_entry",
    "update_my_manga_entry",
    "delete_my_manga_entry",
}


class TestToolMeta:
    def test_ui_tools_carry_resource_uri(self):
        async def run():
            async with Client(mcp) as client:
                tools = {t.name: t for t in await client.list_tools()}
                assert UI_TOOLS | NON_UI_TOOLS == set(tools)  # all 20, no strays
                for name in UI_TOOLS:
                    meta = tools[name].meta or {}
                    assert meta["ui"]["resourceUri"] == APP_RESOURCE_URI, name
                    assert meta["ui/resourceUri"] == APP_RESOURCE_URI, name  # legacy key

        asyncio.run(run())

    def test_non_ui_tools_carry_no_ui_meta(self):
        async def run():
            async with Client(mcp) as client:
                tools = {t.name: t for t in await client.list_tools()}
                for name in NON_UI_TOOLS:
                    meta = tools[name].meta or {}
                    assert "ui" not in meta, name
                    assert "ui/resourceUri" not in meta, name

        asyncio.run(run())


class TestAppResource:
    def test_listed_with_mcp_app_mimetype_and_csp(self):
        async def run():
            async with Client(mcp) as client:
                resources = {str(r.uri): r for r in await client.list_resources()}
                app = resources[APP_RESOURCE_URI]
                assert app.mimeType == "text/html;profile=mcp-app"
                assert (app.meta or {})["ui"]["csp"]["resourceDomains"] == MAL_IMAGE_CDNS

        asyncio.run(run())

    def test_read_contents_expose_mimetype_and_csp(self):
        # Hosts read the CSP from the resources/read content item, not the listing.
        async def run():
            async with Client(mcp) as client:
                item = (await client.read_resource(APP_RESOURCE_URI))[0]
                assert item.mimeType == "text/html;profile=mcp-app"
                assert (item.meta or {})["ui"]["csp"]["resourceDomains"] == MAL_IMAGE_CDNS

        asyncio.run(run())

    def test_serves_placeholder_without_dist(self, monkeypatch):
        monkeypatch.setattr(ui, "_dist_html", lambda: None)

        async def run():
            async with Client(mcp) as client:
                item = (await client.read_resource(APP_RESOURCE_URI))[0]
                assert "UI bundle not built" in item.text

        asyncio.run(run())

    def test_serves_built_bundle_when_present(self, monkeypatch):
        monkeypatch.setattr(ui, "_dist_html", lambda: "<!doctype html><title>mal-app</title>")

        async def run():
            async with Client(mcp) as client:
                item = (await client.read_resource(APP_RESOURCE_URI))[0]
                assert item.text == "<!doctype html><title>mal-app</title>"

        asyncio.run(run())


# The other tests in this file monkeypatch _dist_html, so none of them notice a
# missing bundle on disk - which is exactly how a UI-less wheel could reach PyPI.
MIN_BUNDLE_BYTES = 200_000  # a real build is ~850 KB; the placeholder is ~1 KB
REQUIRE_BUNDLE = os.getenv("MAL_MCP_REQUIRE_UI_BUNDLE") == "1"


class TestBuiltBundleOnDisk:
    """Guards the packaged artifact itself. Release builds set MAL_MCP_REQUIRE_UI_BUNDLE=1."""

    def test_bundle_is_present_and_real(self, monkeypatch):
        monkeypatch.setattr(ui, "_dist_cache", None)  # bypass the process-lifetime cache
        html = ui._dist_html()
        if html is None:
            if REQUIRE_BUNDLE:
                pytest.fail(
                    "src/mal_mcp/ui/dist/index.html is missing. Run `npm ci && npm run build` "
                    "in ui/ before building the distribution."
                )
            pytest.skip("ui/ not built (dev tree)")
        assert len(html) >= MIN_BUNDLE_BYTES
        assert "UI bundle not built" not in html  # the placeholder must not be the bundle
        assert html.lstrip().lower().startswith("<!doctype html")


SEARCH_EDGES = [
    {
        "node": {
            "id": 52991,
            "title": "Sousou no Frieren",
            "main_picture": {"medium": "https://cdn.myanimelist.net/images/anime/f.jpg"},
            "mean": 9.3,
            "media_type": "tv",
            "status": "finished_airing",
            "num_episodes": 28,
            "start_season": {"year": 2023, "season": "fall"},
            "genres": [{"id": 2, "name": "Adventure"}, {"id": 8, "name": "Drama"}],
            "synopsis": "The adventure is over but life goes on.",
        }
    }
]


class TestUiToolResults:
    def test_search_returns_summary_text_and_full_structured_content(self, monkeypatch):
        async def fake_call_mal(op):
            return SEARCH_EDGES

        monkeypatch.setattr(server, "_call_mal", fake_call_mal)

        async def run():
            async with Client(mcp) as client:
                result = await client.call_tool("search_anime", {"query": "frieren"})
                sc = result.structured_content
                assert sc["view"] == "search"
                assert sc["kind"] == "anime"
                assert sc["query"] == "frieren"
                assert sc["count"] == 1
                first = sc["results"][0]
                assert first["picture"] == "https://cdn.myanimelist.net/images/anime/f.jpg"
                assert first["synopsis"]  # UI gets the synopsis...
                text = result.content[0].text
                assert "1 anime result(s) for 'frieren'" in text
                assert "52991|Sousou no Frieren|2023|tv|9.3|28|Adventure,Drama" in text
                assert "synopsis" not in text  # ...the model-facing table stays slim
                assert "https://cdn.myanimelist.net" not in text

        asyncio.run(run())

    def test_ui_result_tags_view_and_coerces_text(self):
        result = ui_result("list", {"kind": "manga", "entries": []}, "empty")
        assert isinstance(result, ToolResult)
        assert result.structured_content == {"view": "list", "kind": "manga", "entries": []}
        assert result.content[0].text == "empty"
