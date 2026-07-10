---
name: verify-mal-api-fact
description: Use before coding against a MyAnimeList API behavior that isn't already recorded in NOTES.md — check the verified-facts log first, confirm against the live API, then record the observation.
---

# Verify a MAL API fact

This repo has a strong culture of recording **live-verified** MAL API / FastMCP / Obot behavior in
`NOTES.md` before coding against it. Don't guess at API shape — verify, then write it down.

## Steps

1. **Check `NOTES.md` first** — it is the verified-facts log. If the behavior is already recorded, use it.
2. **If unknown/uncertain, verify against the live API** — a `curl` with a valid token, or a throwaway
   async script using `MALClient`. Observe the actual response shape/status, not the docs (MAL's docs
   are frequently wrong).
3. **Record the concrete observation in `NOTES.md`** — the endpoint, what you sent, what came back, and
   the date — before writing code that depends on it.

## Known landmines (already in NOTES.md)

- **`fields` is mandatory** — omit it and MAL returns near-empty nodes and drops `list_status`.
- **Rate-limit = HTTP 403** ("DoS detected"), not 429.
- **PKCE is `plain`-only** — MAL does not support S256, which is why Obot's built-in OAuth can't drive
  MAL directly and the `TokenManager` / `MAL_ACCESS_TOKEN` paths exist.
- **DELETE returns `[]`** (non-dict body) with 200 and is idempotent in practice despite docs claiming 404.
- **Redirects are treated as failures** on API calls (following one could fake empty/success results).
