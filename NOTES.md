# NOTES — verified facts (Faz 0)

Verified on 2026-07-04 against the official MAL API reference (the OpenAPI 3 spec embedded
at https://myanimelist.net/apiconfig/references/api/v2), the official authorization doc,
fastmcp 3.4.2 source code, and Obot docs + source (obot, nanobot, mcp-catalog, mcp-oauth-proxy).

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

## MAL OAuth2 (for the Obot/README side only — no OAuth code in this server)

- Authorize: `https://myanimelist.net/v1/oauth2/authorize`
- Token: `https://myanimelist.net/v1/oauth2/token` (also used for `grant_type=refresh_token`)
- **PKCE: only `plain` is supported** (official doc: "Currently, only the plain method is
  supported"), i.e. `code_challenge == code_verifier`, 43-128 chars. S256 is NOT supported.
- No OAuth scopes; a token grants the full API surface for that user.
- Token lifetimes: docs say access = 1 hour, refresh = 1 month; in practice the API returns
  `expires_in=2678400` (31 days) for access tokens (well-known docs/behavior discrepancy).
- Refresh grant behavior (verified live 2026-07-05): `grant_type=refresh_token` returns a
  fresh 31-day access token AND a new (rotated) refresh token; **previously issued refresh
  tokens remain valid after rotation** — using the same old token twice works. This makes an
  env-provisioned refresh token safe across container restarts without any persistence.
- App registration: https://myanimelist.net/apiconfig — App Type **Web** receives a Client Secret;
  Android/iOS/Other are public clients (no secret).

## FastMCP (server framework)

- Using standalone `fastmcp` **3.4.2** (pinned `>=3.4,<4`), Python ≥ 3.12 here.
- Streamable HTTP: `mcp.run(transport="http", host="0.0.0.0", port=..., path="/mcp",
  stateless_http=True)`. Stateless mode is the recommended setup behind gateways/load balancers.
- **Gotcha (verified in installed source)**: `fastmcp.server.dependencies.get_http_headers()`
  strips `authorization` by default in 3.x (it did NOT in 2.x). Use
  `get_http_headers(include={"authorization"})` to receive it. It never raises and returns
  lowercased header names.
- No `auth=` is passed to `FastMCP()` and `FASTMCP_SERVER_AUTH` must stay unset — any auth
  provider would intercept/validate the Authorization header instead of passing it through.
- `fastmcp.exceptions.ToolError` messages are always forwarded to the client — used for all
  user-facing tool errors.

## Obot gateway — compatibility finding (important)

- Containerized server registration: catalog entry `runtime: containerized` with
  `containerizedConfig: {image, port, path}` (port + path required). This server: port **8000**,
  path **`/mcp`**. UI: MCP Management → MCP Servers → Add MCP Server → Containerized.
- Obot "Static OAuth": admin enters only Client ID + Secret. Authorize/token endpoints are NOT
  configurable — Obot discovers them via the MCP auth spec (401 + `WWW-Authenticate` → RFC 9728
  protected-resource metadata → RFC 8414 AS metadata). Callback:
  `https://<obot-host>/oauth/mcp/callback`. Tokens are forwarded as `Authorization: Bearer` and
  refreshed automatically.
- ⚠️ **Obot hardcodes PKCE S256** (verified in nanobot `pkg/mcp/oauth.go` and mcp-oauth-proxy):
  there is no way to select `plain` or disable PKCE. Since MAL supports only `plain` and offers no
  well-known metadata, **Obot's built-in OAuth flow cannot drive MAL directly today.**
- Practical consequence: the server design (stateless Bearer passthrough) is unaffected; the
  working deployment today is a user-supplied `Authorization` header in Obot. See README for the
  options and setup.
