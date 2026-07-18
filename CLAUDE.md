# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

**MyAnimeList MCP server**, distributed on PyPI and launched by MCP clients over **stdio**
(`uvx myanimelist-mcp`). A Python 3.12 + **FastMCP 3** backend exposes 20 tools, and a
**Vite/React/TypeScript** app (`ui/`) is embedded as a `ui://` MCP Apps resource. Managed
with **uv**.

The PyPI distribution is **`myanimelist-mcp`**; the import package stays **`mal_mcp`**.

CI is one tag-triggered workflow (`.github/workflows/publish.yml`): it builds the UI bundle,
runs the tests, builds the wheel, and publishes to PyPI via Trusted Publishing (OIDC). Day-to-day
development is still entirely local.

## Commands

- `uv sync` — install Python deps
- `uv run pytest` — run the offline unit tests (no network)
- `uv run myanimelist-mcp` — run the server over stdio (also `python -m mal_mcp`). It waits on
  stdin for JSON-RPC, so it never returns on its own — drive it with an MCP client, don't call it bare
- `cd ui && npm ci` then `npm run build` — build the UI bundle → `src/mal_mcp/ui/dist/index.html`
- `cd ui && npm run dev` — Vite dev server with fixtures (see `.claude/launch.json` `mal-ui-dev`, port 5199)
- `cd ui && npm run typecheck` — `tsc --noEmit`
- `uv build` — build sdist + wheel (build the UI **first**, or the bundle is missing)

There is **no Python linter/formatter/typechecker** configured (no ruff/black/mypy). Do not
invent lint/format commands. The only "typecheck" is the UI's `npm run typecheck`.

## Layout

- `src/mal_mcp/server.py` — FastMCP app, token resolution, all `@mcp.tool` definitions, pure stats/format helpers
- `src/mal_mcp/mal_client.py` — async MAL API v2 wrapper (`MALClient`), field sets, retries, error types
- `src/mal_mcp/token_manager.py` — self-renewing OAuth `refresh_token` grant (in-memory only)
- `src/mal_mcp/ui/__init__.py` — MCP Apps layer (`register_ui`, `ui_result`, `ui_tool_meta`); `ui/dist/` is the built bundle
- `src/mal_mcp/__main__.py` — `python -m mal_mcp` shim; `main()` itself lives at the bottom of `server.py`
- `tests/` — offline pytest suite; `ui/` — the React/Vite source for the embedded app
- `.github/workflows/publish.yml` — tag-triggered UI build + wheel build + PyPI Trusted Publishing

## House style

- `from __future__ import annotations` at the top of every module.
- Modern 3.12 type hints everywhere: `str | None`, `dict[str, Any]`, `Literal[...]` for enums,
  `Annotated[int, Field(ge=…, le=…, description=…)]` for tool params. Return types always annotated.
- Underscore-prefixed pure module helpers (`_compact_*`, `_summarize_*`, `_call_mal`, `_resolve_token`);
  unprefixed verb-named tools (`get_my_anime_list`, `update_my_anime_entry`); `UPPER_SNAKE` constants.
- Tool docstrings are **LLM-facing** — long, documenting `Args:` and the exact return shape (both the
  text summary and the structured keys). The model reads them.
- Error handling: custom hierarchy `MALError → MALTokenError / MALAPIError` (`mal_client.py`), funneled
  to `fastmcp.exceptions.ToolError` at the single choke point `_call_mal` (`server.py:105`). Error
  messages are user-actionable and scrubbed of internal detail.
- **No logging framework** — user feedback flows through `ToolError` messages.
- All I/O is async on `httpx.AsyncClient`; `MALClient` is an async context manager.
- **Never leak token material** in logs or errors (hard invariant). `_validated_paging_url` (rejects any
  `paging.next` that isn't `https` + `api.myanimelist.net`) and `_quote_user` (URL-escapes usernames)
  exist for this reason and have dedicated tests.

## MCP tool pattern

Every tool is `@mcp.tool(annotations={…hints…}, meta=ui_tool_meta())`, does MAL I/O via
`await _call_mal(lambda client: client.<method>(...))`, and returns `ui_result(view, data, summary)`
for read tools (slim text for the model + view-tagged structured payload for the UI). Write tools and
`analyze_taste` return a plain dict/str with **no** UI meta. Annotation hints follow MCP semantics:

- read → `readOnlyHint: True`
- write → `readOnlyHint: False` + `destructiveHint: True` + `idempotentHint` (True for update/PATCH, False for delete)

Canonical example: `get_my_anime_list` (`server.py:888`). To add a tool, use the `add-mcp-tool` skill.

## Footguns (repo-specific, non-obvious)

1. **The version has ONE source**: `__version__` in `src/mal_mcp/__init__.py`, read by
   `[tool.hatch.version]`. Because the version is dynamic, **`uv version` / `uv version --bump` do
   not work** ("cannot get or set dynamic project versions") — edit the dunder by hand, then run
   `uv sync --reinstall-package myanimelist-mcp` or `test_distribution_version_matches_dunder`
   fails on the stale editable `dist-info`. The release tag `vX.Y.Z` must match it; CI hard-fails
   otherwise. `ui/package.json` is decoupled — do not bump it. Use the `cut-a-release` skill.
2. **The UI bundle can go missing silently**: `src/mal_mcp/ui/dist/**` is gitignored but must ship in
   the distribution — declared under `[tool.hatch.build] artifacts` (`pyproject.toml:59`) so it lands
   in **both** sdist and wheel (bare `uv build` is sdist → wheel-from-sdist). `artifacts` can only
   include files that already exist; it cannot create them. So the UI must be built **before**
   `uv build`, and `_dist_html()` degrades to a placeholder rather than failing — which is why
   `publish.yml` guards the bundle three times and `tests/test_ui.py` checks it on disk under
   `MAL_MCP_REQUIRE_UI_BUNDLE=1`.
3. **Two names, and only one of them is free to change**: the PyPI distribution is
   `myanimelist-mcp`, the import package is `mal_mcp`. Never rename the import package —
   `ui://mal-mcp/app.html` and `files("mal_mcp")` depend on it. The `[project.scripts]` entry must
   stay named `myanimelist-mcp` too, or bare `uvx myanimelist-mcp` stops working.
4. **Never write to stdout.** The MCP client owns stdout for JSON-RPC framing; a single stray
   `print()` corrupts the stream. FastMCP's own logging and banner go to stderr, and `main()` passes
   `show_banner=False` (the banner otherwise blocks ~2s on a pypi.org version check per launch).
5. **`fields` is mandatory** on every MAL call, or MAL returns near-empty nodes and drops `list_status`.
   Each client method sends a hardcoded `*_FIELDS` constant.
6. **MAL rate-limit surfaces as HTTP 403** ("DoS detected"), not 429. `_request` retries both 403/429
   with backoff, but a 403 on another user's private list is short-circuited without retry.
7. **DELETE returns a non-dict body (`[]`) with 200**; redirects on API calls are treated as failures;
   an ~20,000-entry aggregate cap surfaces a `truncated` marker rather than paging forever.
8. **`get_weekly_schedule` defaults to JST** unless the `timezone` arg or `MAL_TIMEZONE` env is set;
   MAL's `25:00` late-night times normalize to next-day `01:00`.

## Testing conventions

- pytest, **no `pytest-asyncio`**: async tests use stdlib `asyncio.run()` with an inner `async def`.
- MAL is never hit over the network — inject `httpx.MockTransport` via the `transport=` constructor param
  on `MALClient`/`TokenManager`, or `monkeypatch` `server._call_mal`.
- Schedule/stats helpers take an injectable `now=` for determinism.
- **When adding a tool, register its name in `tests/test_ui.py`** (`UI_TOOLS` vs `NON_UI_TOOLS`).

## Reference docs

- `README.md` — install, usage, auth/token flow, env-var table
- `NOTES.md` — live-verified MAL API + FastMCP facts (the verified-facts log)
- `PLAN.md` — original design/architecture (historical: predates the stdio/PyPI move)

Env vars: `MAL_REFRESH_TOKEN` + `MAL_CLIENT_ID` (+ `MAL_CLIENT_SECRET`), `MAL_ACCESS_TOKEN`,
`MAL_TIMEZONE`. Users set these in the `"env"` block of their MCP client config.

## Commits

Imperative subject; release commits carry the version in the subject: `Area: summary (x.y.z)` or
`Release x.y.z: summary`. No CHANGELOG, no PRs — linear history on `main`.

**Tags are load-bearing now**: pushing `vX.Y.Z` triggers the PyPI publish. Never delete or
re-point a published tag — PyPI versions are immutable, so a botched release needs the next
patch version, not a re-tag.
