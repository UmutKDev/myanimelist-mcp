# mal-mcp

A **stateless** MCP (Model Context Protocol) server that exposes a user's personal
[MyAnimeList](https://myanimelist.net) data — watch list, scores, watch status, episode
progress — as MCP tools, so an AI assistant (e.g. Claude) can analyze taste, build
statistics, and make recommendations.

Built with Python 3.12, [FastMCP 3](https://gofastmcp.com) (streamable-http transport) and
httpx. Designed to run as a container behind an [Obot](https://obot.ai) MCP gateway.

## Architecture

```
MCP client (Claude) ──> Obot gateway ──> mal-mcp (this server) ──> MAL API v2
                         │                │
                         │ OAuth flow,    │ reads Authorization: Bearer <token>
                         │ token storage/ │ from each request and forwards it
                         │ refresh        │ to api.myanimelist.net — nothing stored
```

- **No OAuth login flow in this server.** The gateway performs the interactive OAuth flow
  (PKCE, callback, token exchange) and forwards `Authorization: Bearer <MAL access token>`
  with every MCP request. Alternatively — because Obot cannot drive MAL's `plain`-PKCE flow
  today (see below) — the server can renew its own access token from a provisioned
  `MAL_REFRESH_TOKEN` via the standard `refresh_token` grant: a single POST, no login flow,
  tokens held in memory only.
- **Stateless.** Each tool call resolves the token (request header first), uses it for the
  MAL API calls of that one invocation, and persists nothing to disk. No sessions are kept
  (`stateless_http=True`), so replicas can scale freely.
- **Rate-limit friendly.** The MAL rate limit is undocumented (community practice: ~1 req/s;
  abuse surfaces as HTTP 403 "DoS detected"). Every list-based tool fetches the user's whole
  library in a single paginated pass with an explicit `fields` parameter — there are no
  per-anime requests. 403/429 responses are retried with exponential backoff (1s/2s/4s).

## Tools

**Anime**

| Tool | Description |
|------|-------------|
| `get_my_anime_list(status_filter?, sort?, limit=100, offset=0)` | A page of the user's list (bounded; `has_more` + `offset` for paging): title, watch status, score, episode progress, genres, community mean, studios. |
| `get_user_stats()` | Locally computed summary: status/score/genre/media-type/decade distributions, total episodes, estimated watch time, user-vs-community score deviation, top studios. |
| `search_anime(query, limit=10)` | Public catalog search (compact results, truncated synopsis). |
| `get_anime_detail(anime_id)` | Full public detail incl. related anime, recommendations, statistics, and the user's own list entry if present. |
| `analyze_taste()` | Token-efficient raw export of the whole list (grouped by status, sorted by score) for the calling model to analyze — this tool itself performs **no** analysis. |

**Manga**

| Tool | Description |
|------|-------------|
| `search_manga(query, limit=10)` | Public manga catalog search (chapters/volumes, authors, genres). |
| `get_manga_detail(manga_id)` | Full manga detail incl. authors, serialization magazines, related works, recommendations, and the user's own entry if present. |
| `get_my_manga_list(status_filter?, sort?, limit=100, offset=0)` | A page of the user's manga list with chapter/volume progress. |

**Discovery**

| Tool | Description |
|------|-------------|
| `get_anime_ranking(ranking_type, limit=25)` | MAL's official rankings: all, airing, upcoming, tv, ova, movie, special, bypopularity, favorite. |
| `get_manga_ranking(ranking_type, limit=25)` | Manga rankings: all, manga, novels, oneshots, doujin, manhwa, manhua, bypopularity, favorite. |
| `get_seasonal_anime(year, season, sort?, limit=25)` | Anime of one broadcast season (winter/spring/summer/fall). |
| `get_suggested_anime(limit=25)` | MAL's personalized suggestions for the authenticated user. |

**Users**

| Tool | Description |
|------|-------------|
| `get_my_profile()` | The authenticated user's profile + lifetime anime statistics. MAL exposes this only for `@me`. |
| `get_user_anime_list(user_name, ...)` | Another user's **public** anime list (403 usually = private list or unknown user). |
| `get_user_manga_list(user_name, ...)` | Another user's **public** manga list. |

**Write tools — these modify the user's MAL list**

| Tool | Description |
|------|-------------|
| `update_my_anime_entry(anime_id, ...)` | Update score/status/episode progress/tags of a list entry — or add the anime to the list (MAL creates the entry if absent). Only provided fields change. |
| `delete_my_anime_entry(anime_id)` | **Permanently** remove an anime from the list (score/progress/tags are lost; cannot be undone). |
| `update_my_manga_entry(manga_id, ...)` | Same as the anime variant, with chapter/volume progress. |
| `delete_my_manga_entry(manga_id)` | **Permanently** remove a manga from the list. |

Aggregate tools (`get_user_stats`, `analyze_taste`) fetch the entire list in one paginated
pass (safety cap: 20,000 entries — beyond that a `truncated`/WARNING marker is included).
`paging.next` URLs are validated (https + `api.myanimelist.net`) before being followed, so
the bearer token can never be sent elsewhere.

Every tool except the four write tools above is read-only. Facts about the MAL API this
server relies on (fields syntax, pagination, limits, error shapes) are documented in
[NOTES.md](NOTES.md).

## MCP Apps UI

The 14 read tools double as interactive views via
[MCP Apps (SEP-1865)](https://github.com/modelcontextprotocol/ext-apps): on hosts that
support the extension, tool results render as a dark-cinematic anime UI inside the chat —
cover-art grids, a detail hero page with inline list editing (status/score/progress saved
through `update_my_*_entry`), a filterable list browser, rankings with movement
indicators, seasonal grids, and a statistics dashboard. On hosts without MCP Apps
support nothing changes — the same tools return their text summaries.

- **How it works:** each UI tool carries `_meta.ui.resourceUri` pointing at the
  `ui://mal-mcp/app.html` resource (a single self-contained HTML bundle served by the
  server). The model sees a compact text table; the full payload travels as
  `structuredContent` to the iframe. UI-initiated actions (edits, load-more, detail
  navigation) go through `callServerTool`, i.e. normal `tools/call` requests — the
  stateless token handling applies unchanged.
- **CSP:** cover art is loaded from `cdn.myanimelist.net` / `api-cdn.myanimelist.net`,
  declared in the resource's `_meta.ui.csp.resourceDomains`. Everything else is inlined.
- **Host support:** Claude (claude.ai / Desktop), ChatGPT, VS Code, Goose, Postman,
  MCPJam, and other SEP-1865 hosts.

### Building the UI

```bash
cd ui
npm ci
npm run build   # emits src/mal_mcp/ui/dist/index.html (single file)
```

The bundle is gitignored; the Docker build produces it in a `node:22` stage, and the
wheel ships it via hatchling `artifacts`. Without a built bundle the server still runs —
the resource serves a small placeholder page instead.

For hostless UI development: `npm run dev` inside `ui/` renders every view with fixture
data and a view switcher (tool calls resolve from fixtures too).

## MAL application registration

1. Go to <https://myanimelist.net/apiconfig> → **Create ID**.
2. **App Type: `Web`** — this is what makes MAL issue a Client Secret (Android/iOS/Other
   types are public clients without a secret).
3. **App Redirect URL**: the callback of whatever performs the OAuth flow. For Obot's
   built-in flow that is `https://<your-obot-host>/oauth/mcp/callback`; if you obtain tokens
   manually (see below), a localhost URL such as `http://localhost:8080/callback` works.
4. Note the **Client ID** (32 chars) and **Client Secret** (64 chars). Never bake them into
   this server or its image — they belong to the gateway/flow side only.

### MAL OAuth2 reference (for the gateway configuration)

| Item | Value |
|------|-------|
| Authorize URL | `https://myanimelist.net/v1/oauth2/authorize` |
| Token URL | `https://myanimelist.net/v1/oauth2/token` |
| PKCE | **`plain` only** — MAL does *not* support `S256`. `code_challenge` must equal `code_verifier` (43–128 chars). |
| Scopes | None (a token grants the full API surface for that user). |
| Token usage | `Authorization: Bearer <access_token>` |
| Lifetimes | Docs say access = 1 hour, refresh = 1 month; in practice MAL returns `expires_in=2678400` (31 days) for access tokens. |

> ⚠️ **The `plain`-PKCE constraint matters.** Any OAuth client that hardcodes `S256`
> (most modern ones, including Obot today — see below) cannot complete MAL's flow.

## Deploying behind Obot

### Register the server (Containerized runtime)

Build and push the image (see [Docker](#docker) below), then in the Obot admin UI:
**MCP Management → MCP Servers → Add MCP Server**, runtime **Containerized**:

| Field | Value |
|-------|-------|
| Image | `ghcr.io/umutkdev/myanimelist-mcp:latest` |
| Port  | `8000` |
| Path  | `/mcp` |

In the same form, add environment fields for the token setup you chose (see "Getting the
token to the server" below) — recommended: `MAL_REFRESH_TOKEN`, `MAL_CLIENT_ID`,
`MAL_CLIENT_SECRET` (all sensitive).

Or as a catalog entry:

```yaml
name: MyAnimeList
serverUserType: multiUser
runtime: containerized
containerizedConfig:
  image: ghcr.io/umutkdev/myanimelist-mcp:latest
  port: 8000
  path: /mcp
env:
  - key: MAL_REFRESH_TOKEN
    name: MAL Refresh Token
    required: true
    sensitive: true
    description: MyAnimeList OAuth refresh token (obtained once; see README)
  - key: MAL_CLIENT_ID
    name: MAL Client ID
    required: true
    sensitive: false
    description: MyAnimeList API app Client ID
  - key: MAL_CLIENT_SECRET
    name: MAL Client Secret
    required: false
    sensitive: true
    description: MyAnimeList API app Client Secret (Web app type only)
```

> ⚠️ **Env-provisioned tokens mean ONE shared MAL account.** With
> `serverUserType: multiUser` the admin configures the env values once and every user of
> this registration talks to the token owner's private MAL list (scores, watch history,
> plan_to_watch/dropped) and shares that account's rate limit. Use env tokens only for a
> personal / single-operator gateway. For a multi-person gateway, register the server as
> single-user so each user supplies their own `MAL_REFRESH_TOKEN`, or use a Remote
> registration where each user sends their own `Authorization` header (which always takes
> precedence over env tokens).

### Getting the token to the server — current reality (read this)

This server just needs `Authorization: Bearer <MAL access token>` on each request; it does
not care who put it there. As of Obot v0.23.x there is a real incompatibility to be aware of:

- Obot's OAuth support ("Static OAuth") takes only a Client ID/Secret and **discovers**
  authorize/token endpoints via the MCP auth spec (401 + `WWW-Authenticate` → RFC 9728 →
  RFC 8414). MAL publishes no such metadata, **and** Obot's OAuth client hardcodes PKCE
  `S256` (verified in `nanobot` and `mcp-oauth-proxy` sources), while MAL supports only
  `plain`. **Obot's built-in OAuth flow therefore cannot drive MAL directly today.**

Working options, in order of practicality:

1. **Self-renewing refresh token (recommended — set up once).** Run the manual flow below
   ONCE and keep the `refresh_token` from its output. Provision three env fields on the
   containerized server: `MAL_REFRESH_TOKEN`, `MAL_CLIENT_ID`, and `MAL_CLIENT_SECRET`
   (omit the secret for non-Web public clients). The server then mints and renews access
   tokens itself before they expire — no monthly re-pasting. Rotated tokens live in memory
   only; MAL keeps previously issued refresh tokens valid after rotation (verified
   empirically), so the env value keeps working across container restarts.
2. **Static access token (quick test).** Set `MAL_ACCESS_TOKEN` instead — simplest possible
   wiring, but MAL access tokens last ~31 days in practice, after which you must paste a
   fresh one. For a **Remote** registration, a user-supplied `Authorization` header
   (`Bearer <token>`) works too and always takes precedence over env-based tokens.
2. **A bridging OAuth proxy** in front of this server that speaks the MCP auth spec toward
   Obot and `plain` PKCE toward MAL. Out of scope for this repository.
3. **Static OAuth, later.** If Obot gains configurable/`plain` PKCE (or MAL gains `S256` +
   metadata discovery), switch to Static OAuth with the MAL Client ID/Secret and callback
   `https://<obot-host>/oauth/mcp/callback` — no changes needed in this server.

### Obtaining a MAL access token manually (documentation only — not part of the server)

Because MAL uses `plain` PKCE, the verifier and challenge are the same string:

```bash
# 1) Generate a code verifier (43-128 chars)
VERIFIER=$(python3 -c "import secrets; print(secrets.token_urlsafe(64)[:100])")

# 2) Open this in a browser, log in, and approve (redirect_uri is required in practice —
#    MAL can answer "400 Bad Request" when it is omitted, even with a single registered URL;
#    the value must exactly match the App Redirect URL and be URL-encoded):
#    https://myanimelist.net/v1/oauth2/authorize?response_type=code&client_id=<CLIENT_ID>&code_challenge=$VERIFIER&code_challenge_method=plain&state=x&redirect_uri=<URL_ENCODED_REDIRECT_URL>
#    You'll be redirected to your registered redirect URL with ?code=<CODE>

# 3) Exchange the code for tokens:
curl -s https://myanimelist.net/v1/oauth2/token \
  -d client_id=<CLIENT_ID> -d client_secret=<CLIENT_SECRET> \
  -d grant_type=authorization_code -d code=<CODE> \
  -d code_verifier=$VERIFIER -d redirect_uri=<REDIRECT_URL>
# → {"token_type":"Bearer","expires_in":2678400,"access_token":"...","refresh_token":"..."}
```

Keep the **`refresh_token`** — that is what goes into `MAL_REFRESH_TOKEN` for the
set-up-once option; the `access_token` is what you'd use for the static/header options.

## Running locally

```bash
uv sync                          # install dependencies
uv run pytest                    # unit tests (pure helpers, no network)
uv run python -m mal_mcp.server  # serves http://0.0.0.0:8000/mcp (streamable-http)
```

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `8000` | HTTP listen port |
| `HOST` | `0.0.0.0` | Bind address |
| `MAL_REFRESH_TOKEN` | *(unset)* | Enables self-renewing tokens: the server mints/renews access tokens via the `refresh_token` grant (requires `MAL_CLIENT_ID`). In-memory only. |
| `MAL_CLIENT_ID` | *(unset)* | MAL app Client ID, needed for the refresh grant. |
| `MAL_CLIENT_SECRET` | *(unset)* | MAL app Client Secret — required for "Web"-type apps, omit for public clients. |
| `MAL_ACCESS_TOKEN` | *(unset)* | Static fallback access token (expires ~31 days). Used only when no `Authorization` header arrives and no refresh setup exists. |

Token precedence per request: `Authorization` header → refresh-token manager → `MAL_ACCESS_TOKEN`.
The server never writes any of these anywhere.

### Test with MCP Inspector

```bash
npx @modelcontextprotocol/inspector
```

In the Inspector UI: transport **Streamable HTTP**, URL `http://localhost:8000/mcp`, and add
a custom header `Authorization: Bearer <your MAL access token>`. `tools/list` should show
all 19 tools; `get_my_anime_list` / `get_user_stats` return your real data.

### Quick smoke test with curl

```bash
# List tools (stateless mode: no session handshake needed)
curl -s -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Call a tool with your token
curl -s -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $MAL_TOKEN" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_user_stats","arguments":{}}}'
```

Calls without an `Authorization` header return an actionable error; an expired/invalid
token surfaces MAL's 401 as *"MAL rejected the access token…"*.

## Docker

Prebuilt multi-arch image:

```bash
docker run --rm -p 8000:8000 ghcr.io/umutkdev/myanimelist-mcp:latest
```

Or build locally:

```bash
docker build -t mal-mcp .
docker run --rm -p 8000:8000 mal-mcp
```

The image is `python:3.12-slim` + uv, runs as a non-root user, exposes port 8000, and
serves the MCP endpoint at `/mcp`.

## Project layout

```
src/mal_mcp/
├── server.py       # FastMCP app, bearer-token helper, 19 tools, stats/format/summary helpers
├── mal_client.py   # MAL API wrapper: fields, pagination (paging.next), retries, error mapping
├── token_manager.py# self-renewing OAuth refresh_token grant (in-memory)
└── ui/             # MCP Apps layer: ui:// resource + meta/ToolResult helpers
    └── dist/       # built single-file HTML bundle (gitignored; built from ui/)
ui/                 # Vite + React + TypeScript app (motion animations, 6 views)
tests/              # offline unit tests (pure helpers, token manager, UI contract)
NOTES.md            # verified MAL API / FastMCP / Obot facts (source for the choices above)
PLAN.md             # design plan
```
