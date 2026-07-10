# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

Stateless **MyAnimeList MCP server**. A Python 3.12 + **FastMCP 3** backend serves a
streamable-HTTP MCP endpoint at `/mcp` on port 8000 (stateless, JSON responses), and a
**Vite/React/TypeScript** app (`ui/`) is embedded as a `ui://` MCP Apps resource. Managed
with **uv**. No CI — everything is local and manual.

## Commands

- `uv sync` — install Python deps
- `uv run pytest` — run the offline unit tests (no network)
- `uv run python -m mal_mcp.server` — run the server (`http://0.0.0.0:8000/mcp`)
- `cd ui && npm ci` then `npm run build` — build the UI bundle → `src/mal_mcp/ui/dist/index.html`
- `cd ui && npm run dev` — Vite dev server with fixtures (see `.claude/launch.json` `mal-ui-dev`, port 5199)
- `cd ui && npm run typecheck` — `tsc --noEmit`
- `docker build -t mal-mcp .` / `docker run --rm -p 8000:8000 mal-mcp`

There is **no Python linter/formatter/typechecker** configured (no ruff/black/mypy). Do not
invent lint/format commands. The only "typecheck" is the UI's `npm run typecheck`.

## Layout

- `src/mal_mcp/server.py` — FastMCP app, token resolution, all `@mcp.tool` definitions, pure stats/format helpers
- `src/mal_mcp/mal_client.py` — async MAL API v2 wrapper (`MALClient`), field sets, retries, error types
- `src/mal_mcp/token_manager.py` — self-renewing OAuth `refresh_token` grant (in-memory only)
- `src/mal_mcp/ui/__init__.py` — MCP Apps layer (`register_ui`, `ui_result`, `ui_tool_meta`); `ui/dist/` is the built bundle
- `tests/` — offline pytest suite; `ui/` — the React/Vite source for the embedded app

## House style

- `from __future__ import annotations` at the top of every module.
- Modern 3.12 type hints everywhere: `str | None`, `dict[str, Any]`, `Literal[...]` for enums,
  `Annotated[int, Field(ge=…, le=…, description=…)]` for tool params. Return types always annotated.
- Underscore-prefixed pure module helpers (`_compact_*`, `_summarize_*`, `_call_mal`, `_resolve_token`);
  unprefixed verb-named tools (`get_my_anime_list`, `update_my_anime_entry`); `UPPER_SNAKE` constants.
- Tool docstrings are **LLM-facing** — long, documenting `Args:` and the exact return shape (both the
  text summary and the structured keys). The model reads them.
- Error handling: custom hierarchy `MALError → MALTokenError / MALAPIError` (`mal_client.py`), funneled
  to `fastmcp.exceptions.ToolError` at the single choke point `_call_mal` (`server.py:107`). Error
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

Canonical example: `get_my_anime_list` (`server.py:882`). To add a tool, use the `add-mcp-tool` skill.

## Footguns (repo-specific, non-obvious)

1. **Version lives in TWO files that must match**: `pyproject.toml` `version` and
   `src/mal_mcp/__init__.py` `__version__`. `ui/package.json` version is intentionally decoupled — do
   not bump it. Use the `cut-a-release` skill.
2. **Hatchling UI-bundle trick**: `src/mal_mcp/ui/dist/**` is gitignored but must ship in the wheel —
   declared under `[tool.hatch.build] artifacts` (`pyproject.toml:23`) so it lands in **both** sdist and
   wheel. The Dockerfile must `COPY README.md` before `uv sync` (hatchling reads readme metadata).
3. **FastMCP 3 strips the `Authorization` header**: read it with
   `get_http_headers(include={"authorization"})` (`server.py:83`). Keep `FASTMCP_SERVER_AUTH` unset and
   pass no `auth=` to `FastMCP()`, or the token passthrough silently breaks.
4. **`fields` is mandatory** on every MAL call, or MAL returns near-empty nodes and drops `list_status`.
   Each client method sends a hardcoded `*_FIELDS` constant.
5. **MAL rate-limit surfaces as HTTP 403** ("DoS detected"), not 429. `_request` retries both 403/429
   with backoff, but a 403 on another user's private list is short-circuited without retry.
6. **DELETE returns a non-dict body (`[]`) with 200**; redirects on API calls are treated as failures;
   an ~20,000-entry aggregate cap surfaces a `truncated` marker rather than paging forever.
7. **`get_weekly_schedule` defaults to JST** unless the `timezone` arg or `MAL_TIMEZONE` env is set;
   MAL's `25:00` late-night times normalize to next-day `01:00`.

## Testing conventions

- pytest, **no `pytest-asyncio`**: async tests use stdlib `asyncio.run()` with an inner `async def`.
- MAL is never hit over the network — inject `httpx.MockTransport` via the `transport=` constructor param
  on `MALClient`/`TokenManager`, or `monkeypatch` `server._call_mal`.
- Schedule/stats helpers take an injectable `now=` for determinism.
- **When adding a tool, register its name in `tests/test_ui.py`** (`UI_TOOLS` vs `NON_UI_TOOLS`).

## Reference docs

- `README.md` — setup, usage, auth/token flow, env-var table
- `NOTES.md` — live-verified MAL API + FastMCP + Obot facts (the verified-facts log)
- `PLAN.md` — original design/architecture

Env vars: `PORT`, `HOST`, `MAL_REFRESH_TOKEN` + `MAL_CLIENT_ID` (+ `MAL_CLIENT_SECRET`),
`MAL_ACCESS_TOKEN`, `MAL_TIMEZONE`.

## Commits

Imperative subject; release commits carry the version in the subject: `Area: summary (x.y.z)` or
`Release x.y.z: summary`. No CHANGELOG, no tags, no PRs — linear history on `main`.
