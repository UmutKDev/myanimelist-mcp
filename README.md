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

- **No OAuth code in this server.** The gateway performs the OAuth flow (PKCE, callback,
  token exchange, refresh, storage) and forwards `Authorization: Bearer <MAL access token>`
  with every MCP request.
- **Stateless.** Each tool call reads the token from the incoming request's header, uses it
  for the MAL API calls of that one invocation, and forgets it. Nothing is written to disk,
  no sessions are kept (`stateless_http=True`), so replicas can scale freely.
- **Rate-limit friendly.** The MAL rate limit is undocumented (community practice: ~1 req/s;
  abuse surfaces as HTTP 403 "DoS detected"). Every list-based tool fetches the user's whole
  library in a single paginated pass with an explicit `fields` parameter — there are no
  per-anime requests. 403/429 responses are retried with exponential backoff (1s/2s/4s).

## Tools

| Tool | Description |
|------|-------------|
| `get_my_anime_list(status_filter?, sort?, limit=100, offset=0)` | A page of the user's list (bounded; `has_more` + `offset` for paging): title, watch status, score, episode progress, genres, community mean, studios. |
| `get_user_stats()` | Locally computed summary: status/score/genre/media-type/decade distributions, total episodes, estimated watch time, user-vs-community score deviation, top studios. |
| `search_anime(query, limit=10)` | Public catalog search (compact results, truncated synopsis). |
| `get_anime_detail(anime_id)` | Full public detail incl. related anime, recommendations, statistics, and the user's own list entry if present. |
| `analyze_taste()` | Token-efficient raw export of the whole list (grouped by status, sorted by score) for the calling model to analyze — this tool itself performs **no** analysis. |

Aggregate tools (`get_user_stats`, `analyze_taste`) fetch the entire list in one paginated
pass (safety cap: 20,000 entries — beyond that a `truncated`/WARNING marker is included).
`paging.next` URLs are validated (https + `api.myanimelist.net`) before being followed, so
the bearer token can never be sent elsewhere.

All tools are read-only. Facts about the MAL API this server relies on (fields syntax,
pagination, limits, error shapes) are documented in [NOTES.md](NOTES.md).

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

In the same form, add an environment field so each user can paste their MAL token
(see "Getting the token to the server" below): key `MAL_ACCESS_TOKEN`, required, sensitive.

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
  - key: MAL_ACCESS_TOKEN
    name: MAL Access Token
    required: true
    sensitive: true
    description: MyAnimeList OAuth access token (obtained manually; see README)
```

### Getting the token to the server — current reality (read this)

This server just needs `Authorization: Bearer <MAL access token>` on each request; it does
not care who put it there. As of Obot v0.23.x there is a real incompatibility to be aware of:

- Obot's OAuth support ("Static OAuth") takes only a Client ID/Secret and **discovers**
  authorize/token endpoints via the MCP auth spec (401 + `WWW-Authenticate` → RFC 9728 →
  RFC 8414). MAL publishes no such metadata, **and** Obot's OAuth client hardcodes PKCE
  `S256` (verified in `nanobot` and `mcp-oauth-proxy` sources), while MAL supports only
  `plain`. **Obot's built-in OAuth flow therefore cannot drive MAL directly today.**

Working options, in order of practicality:

1. **User-supplied token (works today).** Give the server the token you obtained manually
   (below). For the **Containerized** runtime Obot passes user credentials as environment
   variables, so declare a `MAL_ACCESS_TOKEN` env field (required + sensitive) and paste the
   access token there — the server falls back to it whenever a request carries no
   `Authorization` header. For a **Remote** registration, a user-supplied `Authorization`
   header (`Bearer <token>`) works the same way and takes precedence over the env var.
   Downside: MAL access tokens last ~31 days in practice; re-paste a fresh token when it
   expires.
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

Use the `access_token` value as the Bearer token.

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
| `MAL_ACCESS_TOKEN` | *(unset)* | Fallback MAL access token, used only when a request carries no `Authorization` header (Obot containerized runtime delivers user credentials as env vars). Never written anywhere by the server. |

### Test with MCP Inspector

```bash
npx @modelcontextprotocol/inspector
```

In the Inspector UI: transport **Streamable HTTP**, URL `http://localhost:8000/mcp`, and add
a custom header `Authorization: Bearer <your MAL access token>`. `tools/list` should show
the five tools; `get_my_anime_list` / `get_user_stats` return your real data.

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
├── server.py       # FastMCP app, bearer-token helper, 5 tools, stats/format helpers
└── mal_client.py   # MAL API wrapper: fields, pagination (paging.next), retries, error mapping
tests/test_stats.py # unit tests for the pure helpers
NOTES.md            # verified MAL API / FastMCP / Obot facts (source for the choices above)
PLAN.md             # design plan
```
