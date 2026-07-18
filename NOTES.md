# NOTES — verified facts (Faz 0)

Verified on 2026-07-04 against the official MAL API reference (the OpenAPI 3 spec embedded
at https://myanimelist.net/apiconfig/references/api/v2), the official authorization doc, and
fastmcp 3.4.2 source code. The FastMCP / MCP Apps sections were re-verified 2026-07-18 during
the move to stdio + PyPI.

## MAL API v2

- **Base URL**: `https://api.myanimelist.net/v2` (single entry in the spec's `servers` array).
- **Auth**: `Authorization: Bearer <token>` (user OAuth) or `X-MAL-CLIENT-ID` header (public data
  only). `GET /users/@me/animelist` requires a user OAuth token. This server always forwards the
  Bearer token it receives; it never uses `X-MAL-CLIENT-ID`.
- **Error body**: `{"error": "<code>", "message": "<text>"}`. Live-verified: 403 no-auth returns
  `{"message":"","error":"forbidden"}`. Status codes: 400 invalid params, 401 `invalid_token`
  (expired/invalid token), 403 forbidden ("DoS detected etc."), 404 not found.
- **Rate limits**: officially undocumented. Community practice: ≤ ~1 req/s. Abuse can surface as
  **403** ("DoS detected"), not necessarily 429 — the client retries both with backoff.

### GET /users/{user_name}/animelist  (`@me`)

- Params: `status`, `sort`, `limit` (default 100, **max 1000**), `offset`, `fields`.
- `status` values: `watching | completed | on_hold | dropped | plan_to_watch`; omit for all.
- `sort` values: `list_score | list_updated_at | anime_title | anime_start_date`
  (`anime_id` exists but is marked "Under Development" — not used).
- **`fields` is mandatory in practice**: without it, `node` contains only `id, title, main_picture`
  and `list_status` is absent. Node fields are requested top-level (no `node.` prefix), e.g.
  `fields=list_status,num_episodes,genres,mean,media_type,status,start_season,average_episode_duration,studios,rating`.
  Nested selection syntax exists: `list_status{score,...}`.
- `list_status` fields: `status, score (0-10), num_episodes_watched, is_rewatching, start_date,
  finish_date, priority, num_times_rewatched, rewatch_value, tags, comments, updated_at`.
  Spec note: `comments` "cannot be contained in a list" (list responses).
- Response: `{"data": [{"node": {...}, "list_status": {...}}], "paging": {"previous": url, "next": url}}`.
  `paging.next` is a **complete absolute URL**; absent on the last page.
- Docs quirk: an official example shows `num_watched_episodes`; the schema (and real API) use
  `num_episodes_watched`.

### GET /anime (search) and GET /anime/{anime_id}

- Search params: `q`, `limit` (default 100, **max 100**), `offset`, `fields`. Minimum `q` length
  ~3 chars (community finding, not official; shorter may yield 400 `invalid q`).
- Detail-only fields (rejected/ignored on list endpoints): `pictures, background, related_anime,
  related_manga, recommendations, statistics`.
- `my_list_status` on detail is returned only with a user OAuth token and only if requested via
  `fields`; otherwise silently omitted.
- Enums: `media_type`: unknown|tv|ova|movie|special|ona|music; airing `status`:
  finished_airing|currently_airing|not_yet_aired; `rating`: g|pg|pg_13|r|r+|rx.
- `average_episode_duration` is in **seconds**; `num_episodes` is 0 when unknown; `mean`, `rank`,
  `popularity` are nullable. Dates may be partial ("2017", "2017-10").

### Manga, discovery, users, writes (verified 2026-07-05, official OpenAPI spec + live tests)

- `GET /manga?q=` — limit max **100**; fields incl. `num_chapters`, `num_volumes` (0 = unknown/
  ongoing), `authors{first_name,last_name}` (nested-fields syntax; response shape
  `[{node:{id,first_name,last_name}, role}]`), `media_type`, `status`
  (finished|currently_publishing), `mean`, `genres`.
- `GET /manga/{id}` — detail-only extras: `pictures, background, related_anime, related_manga,
  recommendations, serialization{name}`; `my_list_status` with user token + fields.
- `GET /users/{user_name}/mangalist` — status `reading|completed|on_hold|dropped|plan_to_read`;
  sort `list_score|list_updated_at|manga_title|manga_start_date`; limit max **1000**;
  list_status: `num_chapters_read`, `num_volumes_read`, `is_rereading`, `num_times_reread`,
  `reread_value`, plus the shared fields. Arbitrary usernames = public lists (live-verified).
- `GET /users/{user_name}/animelist` also accepts arbitrary usernames (live-verified with a
  public account). 403 can mean private list or unknown user — error message says so.
- `GET /anime/ranking` — ranking_type `all|airing|upcoming|tv|ova|movie|special|bypopularity|
  favorite`; limit max **500**; items are `{node, ranking:{rank, previous_rank?}}`.
- `GET /manga/ranking` — ranking_type `all|manga|novels|oneshots|doujin|manhwa|manhua|
  bypopularity|favorite`; limit max **500**.
- `GET /anime/season/{year}/{season}` — season `winter|spring|summer|fall`; sort
  `anime_score|anime_num_list_users`; limit max **500**.
- `GET /anime/suggestions` — limit max **100**; user OAuth token ONLY.
- `GET /users/@me` — user token only; official docs allow only `@me` here. `fields=
  anime_statistics,time_zone,is_supporter` adds stats (num_items_*, num_days_*, num_episodes,
  num_times_rewatched, mean_score) to the default id/name/picture/birthday/location/joined_at.
- **Writes** (user token only): `PATCH /anime/{id}/my_list_status` and
  `PATCH /manga/{id}/my_list_status`, body form-encoded; only sent fields change; **creates the
  entry when absent** (live-verified). Params: status, score 0-10, priority 0-2,
  num_watched_episodes / num_chapters_read+num_volumes_read, is_rewatching/is_rereading,
  num_times_rewatched/num_times_reread, rewatch_value/reread_value 0-5, tags, comments.
- `DELETE .../my_list_status` — live-observed: 200 with body `[]` (not an object!), and
  **idempotent in practice** (deleting an absent entry also returns 200, despite docs saying
  404); 404 does occur for unknown ids. Client treats non-dict 2xx bodies on non-GET as success.

## MAL OAuth2 (for the README/token-setup side — no interactive login flow in this server)

- Authorize: `https://myanimelist.net/v1/oauth2/authorize`
- Token: `https://myanimelist.net/v1/oauth2/token` (also used for `grant_type=refresh_token`)
- **PKCE: only `plain` is supported** (official doc: "Currently, only the plain method is
  supported"), i.e. `code_challenge == code_verifier`, 43-128 chars. S256 is NOT supported.
- No OAuth scopes; a token grants the full API surface for that user.
- Token lifetimes: docs say access = 1 hour, refresh = 1 month; in practice the API returns
  `expires_in=2678400` (31 days) for access tokens (well-known docs/behavior discrepancy).
- Refresh grant behavior (verified live 2026-07-05): `grant_type=refresh_token` returns a
  fresh 31-day access token AND a new (rotated) refresh token; **previously issued refresh
  tokens remain valid after rotation** — using the same old token twice works.
  ⚠️ **This fact is load-bearing for the stdio distribution.** Every client launch is a cold
  start that re-submits the *same* `MAL_REFRESH_TOKEN` from the env; `TokenManager` never
  persists the rotated one. If MAL ever makes refresh tokens single-use, the documented setup
  breaks on the second session. Re-verify with the `verify-mal-api-fact` skill before releases.
- App registration: https://myanimelist.net/apiconfig — App Type **Web** receives a Client Secret;
  Android/iOS/Other are public clients (no secret).

## FastMCP (server framework)

- Using standalone `fastmcp` **3.4.2** (pinned `>=3.4,<4`), Python ≥ 3.12 here.
- `Transport = Literal["stdio", "http", "sse", "streamable-http"]`; **stdio is the default**
  (`fastmcp/settings.py:257`), so a bare `mcp.run()` is already a stdio server.
- **`run()` forwards `**transport_kwargs` verbatim**, and `run_stdio_async()` accepts only
  `show_banner` / `log_level` / `stateless`. Passing `host`, `port`, `path`, `stateless_http`
  or `json_response` alongside `transport="stdio"` is a `TypeError` at launch — verified in
  `fastmcp/server/mixins/transport.py:185-190`.
- **Banner goes to stderr** (`Console(stderr=True)`, `fastmcp/utilities/cli.py:246`), as does all
  FastMCP logging — so stdout stays pure JSON-RPC. But `log_server_banner()` calls
  `check_for_newer_version()`, a **blocking 2s `httpx.get` to pypi.org** on every start
  (`utilities/version_check.py:69`). Hence `show_banner=False` in `main()`.
- **`get_http_headers()` never raises** and returns `{}` when there is no HTTP request context
  (`server/dependencies.py:456-464`), i.e. always under stdio. Verified live. It also strips
  `authorization` by default in 3.x unless re-included — irrelevant here now, but that is why
  the old HTTP passthrough needed `include={"authorization"}`.
- `fastmcp.exceptions.ToolError` messages are always forwarded to the client — used for all
  user-facing tool errors.
- The dependency must remain the `fastmcp` metapackage: `fastmcp.server.dependencies` imports
  starlette + `mcp` at module scope, which only arrive via the `[client,server]` extras.
  Switching to `fastmcp-slim` is an `ImportError` at import time, not a graceful degrade.

## Time zones (learned the hard way in 0.5.0)

- **`tzdata` must stay a hard dependency.** CPython's `zoneinfo` reads the *system* IANA
  database (`/usr/share/zoneinfo`, …) and only falls back to the `tzdata` PyPI package when
  that is absent. macOS and the GitHub `ubuntu-latest` runners both ship system tz data, so a
  missing `tzdata` is **invisible in local and CI testing** — 0.5.0 shipped without it, passed
  everything, and then crash-looped in a slim container (`ZoneInfoNotFoundError: 'No time zone
  found with key Asia/Tokyo'`, exit status 1, every restart).
- Reproduce that environment anywhere with **`PYTHONTZPATH=""`**, which empties zoneinfo's
  search path and forces the packaged fallback. The release workflow runs its stdio smoke test
  under exactly that setting.
- Resolve zones **lazily**, never at module import: `JST` used to be a module-level constant,
  so one missing database took down all 20 tools instead of just `get_weekly_schedule`. It is
  now `_jst()` (`@lru_cache`), raising an actionable `ToolError`.

## MCP Apps over stdio

- SEP-1865 is **Final**, and `ui://` resources are transport-independent — the app↔host channel
  is `postMessage`, not the MCP transport. Verified live: the full 833 KB single-file bundle is
  served intact through a real stdio subprocess with `mimeType: text/html;profile=mcp-app`.
- Which hosts actually *render* it varies; see
  https://modelcontextprotocol.io/extensions/client-matrix. The README should not promise any
  specific client — only that the resource is served and spec-conformant.
