---
name: add-mcp-tool
description: Use when adding a new MCP tool to the MAL server — the lockstep checklist covering the MAL client method, server helpers, tool decorator/hints, UI view, and test registration.
---

# Add an MCP tool

Adding a tool touches several files in lockstep. Canonical read example: `get_my_anime_list`
(`server.py:888`). Skipping a step (especially test registration or the `fields` param) breaks
the tool or the test suite. Read the surrounding code before writing — match the house style.

## Checklist

1. **MAL client method** — add the endpoint call to `MALClient` in `mal_client.py`:
   - Define a `*_FIELDS` constant and pass it as `fields` (mandatory — without it MAL returns
     near-empty nodes and drops `list_status`). Nested selection uses brace syntax
     (e.g. `authors{first_name,last_name}`).
   - Clamp any `limit` to MAL's page cap; route through the existing `_request`/pagination path so
     403/429 retries and redirect-as-failure handling apply.
2. **Server helpers** — add pure `_compact_*` (slim the raw MAL JSON) and `_summarize_*` (model-facing
   text) helpers in `server.py`. Keep them pure and underscore-prefixed.
3. **Tool function** — add `@mcp.tool(annotations={…}, meta=ui_tool_meta())`:
   - Hints: read → `readOnlyHint: True`; write → `readOnlyHint: False` + `destructiveHint: True` +
     `idempotentHint` (True for update/PATCH, False for delete).
   - `async def`, params typed with `Annotated[..., Field(...)]` / `Literal`, long LLM-facing docstring
     documenting `Args:` and the return shape.
   - Do all MAL I/O via `await _call_mal(lambda client: client.<method>(...))` — never construct a client
     directly (this is the token-resolution + error-mapping + refresh-retry choke point).
4. **Return shape:**
   - Read tool → `return ui_result(view, data, summary)` with a `view` string the UI understands.
   - Write tool / `analyze_taste` → return a plain dict/str with **no** `meta=ui_tool_meta()`.
5. **UI view (only if `view` is new)** — add a view in `ui/src/views/`, wire it in `ui/src/mcp/bridge.ts`
   and `ui/src/mcp/types.ts`, then rebuild the bundle (see the `rebuild-ui-bundle` skill).
6. **Tests** — register the new tool name in `tests/test_ui.py` (`UI_TOOLS` for UI-backed tools,
   `NON_UI_TOOLS` otherwise), and add pure-helper unit tests (inject `httpx.MockTransport` for client
   behavior; `monkeypatch` `server._call_mal` for tool behavior).
7. **Verify:** `uv run pytest`.
