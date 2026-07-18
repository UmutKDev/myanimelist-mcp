"""Entry-point contract: stdio transport, console script, version parity."""

import importlib.metadata

import mal_mcp
from mal_mcp import server


class TestMain:
    def test_runs_stdio_without_http_kwargs(self, monkeypatch):
        # run_stdio_async() accepts only show_banner/log_level/stateless; run()
        # forwards **transport_kwargs verbatim, so host/port/path/stateless_http/
        # json_response would raise TypeError the moment a client launches us.
        captured: dict = {}
        monkeypatch.setattr(server.mcp, "run", lambda **kwargs: captured.update(kwargs))
        server.main()
        assert captured["transport"] == "stdio"
        # The banner otherwise blocks ~2s on a pypi.org version check per cold start.
        assert captured["show_banner"] is False
        for forbidden in ("host", "port", "path", "stateless_http", "json_response"):
            assert forbidden not in captured

    def test_console_script_resolves_to_main(self):
        entry_points = importlib.metadata.entry_points(group="console_scripts")
        assert entry_points["myanimelist-mcp"].load() is server.main

    def test_distribution_version_matches_dunder(self):
        # pyproject.toml reads __version__ via [tool.hatch.version]; a mismatch here
        # means the installed metadata drifted from the single source.
        assert importlib.metadata.version("myanimelist-mcp") == mal_mcp.__version__
