# PLAN — mal-mcp

Stateless MCP server exposing a user's MyAnimeList data as MCP tools. Runs as streamable-http
behind an Obot MCP gateway; the OAuth flow lives entirely in the gateway. Every request must carry
`Authorization: Bearer <MAL access token>`, which the server forwards verbatim to the MAL API.
No token storage, no refresh, no OAuth code here. See NOTES.md for the verified API facts.

## File structure

```
.
├── pyproject.toml           # uv project; deps: fastmcp>=3.4,<4, httpx
├── uv.lock
├── .python-version          # 3.12
├── src/mal_mcp/
│   ├── __init__.py
│   ├── server.py            # FastMCP app, bearer-token helper, 5 tools, __main__ runner
│   └── mal_client.py        # MALClient: httpx wrapper, fields, pagination, retry, error mapping
├── tests/test_stats.py      # pure helpers (compaction / stats / taste format)
├── Dockerfile               # python:3.12-slim + uv, port 8000, path /mcp
├── NOTES.md                 # Faz 0 findings
└── README.md                # Obot setup, OAuth reality, local testing
```

## Tools

All tools are read-only (`readOnlyHint: true`) and take the MAL token from the request's
`Authorization` header. List-based tools share ONE paginated fetch (no per-anime requests).

### `get_my_anime_list(status_filter?, sort?, limit=100, offset=0)`
- `status_filter`: `watching | completed | on_hold | dropped | plan_to_watch` (omit = all)
- `sort`: `list_score | list_updated_at | anime_title | anime_start_date` (omit = MAL default)
- `limit` 1-1000 / `offset`: bounded paging so a huge list can't blow up the caller's context.
- Returns `{total_returned, offset, has_more, entries: [CompactEntry]}` where CompactEntry =
  `{id, title, year, media_type, airing_status, my_status, my_score, episodes_watched,
    total_episodes, genres: [str], mal_mean, studios: [str], updated_at}`.

### `get_user_stats()`
- Fetches the full list once, computes locally and returns:
  status distribution; scored count / mean / median / 1-10 histogram; genre distribution
  (top 15: count + avg user score); media-type distribution; total episodes watched; estimated
  watch time (Σ episodes_watched × average_episode_duration → hours/days); release-decade
  distribution; user-score vs MAL community mean deviation; top studios.

### `search_anime(query, limit=10)`
- Public search (`GET /anime`), limit 1-50. Returns compact results:
  `{id, title, year, media_type, mean, num_episodes, airing_status, genres, synopsis≤300ch}`.

### `get_anime_detail(anime_id)`
- `GET /anime/{id}` with rich fields, incl. `my_list_status` (present only for the token's user),
  `related_anime`, `recommendations` (top 10), `statistics`.

### `analyze_taste()`
- NO AI analysis — returns the raw list in a token-efficient text block for Claude to interpret:
  small summary header + entries grouped by status, sorted by user score, one pipe-separated line
  each: `my_score|title|year|type|watched/total|genres|mal_mean`.

### v0.3.0 additions (14 tools; same patterns, see README for the full table)
- Manga: `search_manga`, `get_manga_detail`, `get_my_manga_list` (chapter/volume progress,
  authors, serialization).
- Discovery: `get_anime_ranking`, `get_manga_ranking`, `get_seasonal_anime`,
  `get_suggested_anime` (MAL's personalized suggestions; user token only).
- Users: `get_my_profile` (@me only per MAL), `get_user_anime_list` / `get_user_manga_list`
  (public lists of arbitrary usernames; usernames path-quoted).
- Writes (user token only): `update_my_anime_entry` / `update_my_manga_entry` (PATCH, only
  provided fields, creates entry when absent) and `delete_my_anime_entry` /
  `delete_my_manga_entry` (destructiveHint: true; MAL delete is idempotent in practice).

## mal_client.py

- `MALError` → base; `MALTokenError` (401), `MALAPIError` (everything else).
- `async with MALClient(token)` holds one `httpx.AsyncClient` (base_url, Bearer header, 30s timeout).
- `_request()`: central GET + error mapping; 429/403 → exponential backoff (1s/2s/4s, max 3
  retries — MAL signals rate-limit abuse as 403); 401 → MALTokenError; meaningful messages.
- `get_anime_list()`: `limit=1000` pages, follows `paging.next` absolute URLs, merges all pages
  (safety cap 20 pages → returns a `truncated` flag the tools surface), always sends the full
  `fields` list. `paging.next` is validated (https + api.myanimelist.net) before following, so
  the bearer token can never be sent to another host.
- `get_anime_list_page(status, sort, limit, offset)`: single bounded request for the
  `get_my_anime_list` tool; returns `(edges, has_more)`.
- `search_anime()`, `get_anime_detail()`: single requests with explicit `fields`.

## server.py

- `FastMCP("mal_mcp")`, no `auth=`.
- `_bearer_token()`: `get_http_headers(include={"authorization"})` → strip `Bearer ` → `ToolError`
  with actionable message if missing.
- Pure helpers (unit-tested): `_compact_entry`, `_compute_stats`, `_format_taste`.
- `__main__`: `mcp.run(transport="http", host="0.0.0.0", port=$PORT|8000, path="/mcp",
  stateless_http=True)`.

## Delivery phases

- A: project scaffold + deps + NOTES/PLAN ✅
- B: `mal_client.py` + pure helpers + tests
- C: `server.py` (5 tools)
- D: local verification (JSON-RPC smoke test, header error paths, optional real-token test)
- E: Dockerfile + build check
- F: README
