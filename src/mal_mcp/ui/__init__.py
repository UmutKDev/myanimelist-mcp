"""MCP Apps (SEP-1865) UI layer.

Serves the single-file HTML app (built from ui/ by Vite into src/mal_mcp/ui/dist/)
as a ``ui://`` resource and provides the helpers that link tools to it:

- ``ui_tool_meta()``   -> tool ``_meta`` pointing hosts at the app resource
- ``ui_result(...)``   -> ToolResult with slim text for the model and the full,
  view-tagged payload in structuredContent for the app
- ``register_ui(mcp)`` -> registers the app resource (with the CSP needed to load
  MAL cover art inside the sandboxed iframe)

The resource always registers; when the bundle has not been built the resource
serves a small placeholder page instead, so the server (and pytest) never
depend on a Node toolchain.
"""

from __future__ import annotations

from importlib.resources import files
from typing import Any

from fastmcp import FastMCP
from fastmcp.apps import AppConfig, ResourceCSP
from fastmcp.tools import ToolResult

APP_RESOURCE_URI = "ui://mal-mcp/app.html"

# Every external origin the iframe touches must be declared here (host-enforced CSP).
# MAL serves main_picture URLs from both of these; everything else is bundled inline.
MAL_IMAGE_CDNS = ["https://cdn.myanimelist.net", "https://api-cdn.myanimelist.net"]

_PLACEHOLDER_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<style>
  html, body { margin: 0; height: 100%; }
  body {
    display: flex; align-items: center; justify-content: center;
    background: #efe7d5; color: #211d15;
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  .card { text-align: center; padding: 40px; }
  h1 {
    font-size: 22px; font-weight: 600; margin: 0 0 8px;
    font-family: "Shippori Mincho", "Hiragino Mincho ProN", "Yu Mincho", Georgia, serif;
    color: #c33a25;
  }
  p { margin: 0; font-size: 13px; opacity: 0.7; }
  code { font-family: ui-monospace, monospace; }
</style>
</head>
<body>
  <div class="card">
    <h1>MyAnimeList App</h1>
    <p>UI bundle not built &mdash; run <code>npm ci &amp;&amp; npm run build</code> in <code>ui/</code>.</p>
  </div>
</body>
</html>
"""


_dist_cache: str | None = None


def _dist_html() -> str | None:
    """The built single-file app, or None when ui/ has not been built.

    A successful read is cached for the process lifetime (the bundle is immutable
    in the container); a miss is NOT cached, so building ui/ while a dev server is
    running takes effect on the next read.
    """
    global _dist_cache
    if _dist_cache is None:
        try:
            _dist_cache = (files("mal_mcp") / "ui" / "dist" / "index.html").read_text(
                encoding="utf-8"
            )
        except (FileNotFoundError, ModuleNotFoundError, NotADirectoryError, OSError):
            return None
    return _dist_cache


def ui_tool_meta() -> dict[str, Any]:
    """Tool ``_meta`` that tells MCP Apps hosts to render results in the app."""
    return {
        "ui": {"resourceUri": APP_RESOURCE_URI},
        "ui/resourceUri": APP_RESOURCE_URI,  # legacy flat key still read by older hosts
    }


def ui_result(view: str, data: dict[str, Any], summary: str) -> ToolResult:
    """Slim text for the model's context; the full view-tagged payload for the app."""
    return ToolResult(content=summary, structured_content={"view": view, **data})


def register_ui(mcp: FastMCP) -> None:
    """Register the app HTML as a ui:// resource (call once, after the tools)."""

    @mcp.resource(
        APP_RESOURCE_URI,
        name="mal_app",
        title="MyAnimeList App",
        description="Interactive UI for the MyAnimeList tools (MCP Apps).",
        # mime_type resolves to text/html;profile=mcp-app automatically for ui:// URIs.
        app=AppConfig(csp=ResourceCSP(resource_domains=MAL_IMAGE_CDNS)),
    )
    def mal_app() -> str:
        return _dist_html() or _PLACEHOLDER_HTML
