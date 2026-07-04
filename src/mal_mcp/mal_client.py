"""Async client for the MyAnimeList API v2.

The access token is supplied by the caller on every use (it arrives with each MCP
request); nothing is cached or persisted here. All endpoints send an explicit
``fields`` parameter because the MAL API returns a near-empty payload without one.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

MAL_API_BASE = "https://api.myanimelist.net/v2"

# Node fields shared by every list-based tool, so the whole library is fetched once
# and reused (no per-anime requests - MAL rate limiting is aggressive and undocumented).
LIST_FIELDS = (
    "list_status,num_episodes,genres,mean,media_type,status,"
    "start_season,average_episode_duration,studios,rating"
)
SEARCH_FIELDS = "mean,genres,media_type,num_episodes,status,start_season,synopsis"
DETAIL_FIELDS = (
    "alternative_titles,synopsis,mean,rank,popularity,num_list_users,num_scoring_users,"
    "genres,media_type,status,num_episodes,start_season,start_date,end_date,source,"
    "average_episode_duration,rating,studios,my_list_status,related_anime,"
    "recommendations,statistics"
)

LIST_STATUSES = ("watching", "completed", "on_hold", "dropped", "plan_to_watch")
LIST_SORTS = ("list_score", "list_updated_at", "anime_title", "anime_start_date")

PAGE_LIMIT = 1000  # documented maximum for /users/{user_name}/animelist
MAX_PAGES = 20  # safety cap while following paging.next (20k entries)
MAX_RETRIES = 3  # extra attempts on 403/429, backed off 1s/2s/4s


class MALError(Exception):
    """Base MAL failure; the message is safe to surface to the MCP client."""


class MALTokenError(MALError):
    """MAL rejected the access token (expired or invalid)."""


class MALAPIError(MALError):
    """Any other MAL API failure (bad request, rate limit, network, ...)."""


def _parse_error_body(response: httpx.Response) -> tuple[str, str]:
    """Extract MAL's ``{"error": ..., "message": ...}`` body, tolerating non-JSON."""
    try:
        body = response.json()
    except ValueError:
        return "", response.text[:200]
    if not isinstance(body, dict):
        return "", str(body)[:200]
    return str(body.get("error") or ""), str(body.get("message") or "")


def _validated_paging_url(url: str) -> str:
    """Refuse to follow a paging.next URL that would leak the token off MAL.

    The Authorization header is attached to every request of this client, so a
    tampered/unexpected paging URL must never be fetched.
    """
    try:
        parsed = httpx.URL(url)
    except Exception as exc:
        raise MALAPIError("MAL returned an unparseable paging URL; aborting pagination.") from exc
    if parsed.scheme != "https" or parsed.host != "api.myanimelist.net":
        raise MALAPIError("MAL returned an unexpected paging URL; aborting pagination.")
    return url


class MALClient:
    """Thin wrapper over httpx for the MAL API v2, scoped to one bearer token."""

    def __init__(
        self,
        access_token: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=MAL_API_BASE,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> "MALClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._client.aclose()

    async def _request(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET ``url`` with rate-limit retries and MAL error mapping.

        ``url`` is either a path (resolved against the API base) or the absolute
        ``paging.next`` URL returned by MAL.
        """
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._client.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise MALAPIError("MAL API request timed out; try again shortly.") from exc
            except httpx.HTTPError as exc:
                # Only the exception type: httpx messages can embed request details.
                raise MALAPIError(
                    f"Could not reach the MAL API ({type(exc).__name__}); "
                    "check connectivity and try again."
                ) from exc

            if response.status_code < 400:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise MALAPIError("MAL API returned a non-JSON response.") from exc
                if not isinstance(payload, dict):
                    raise MALAPIError("MAL API returned an unexpected JSON shape.")
                return payload

            error_code, message = _parse_error_body(response)

            if response.status_code == 401:
                raise MALTokenError(
                    "MAL rejected the access token (401 invalid_token): the token is expired "
                    "or invalid. Renew the credential in use (gateway OAuth login, the "
                    "MAL_REFRESH_TOKEN setup, or the static MAL_ACCESS_TOKEN) and retry."
                )
            if response.status_code in (403, 429):
                # MAL reports rate-limit abuse as 403 ("DoS detected"), not only 429.
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2**attempt)
                    continue
                raise MALAPIError(
                    f"MAL API kept returning HTTP {response.status_code} "
                    f"({error_code or 'forbidden'}) after {MAX_RETRIES} retries - most likely "
                    f"rate limiting. Wait a minute before retrying. {message}".strip()
                )
            if response.status_code == 400:
                raise MALAPIError(
                    f"MAL API rejected the request (400 {error_code or 'bad_request'}): "
                    f"{message or 'invalid parameters'}"
                )
            if response.status_code == 404:
                raise MALAPIError(
                    "MAL API returned 404: the requested resource does not exist "
                    "(check the anime id / user)."
                )
            raise MALAPIError(
                f"MAL API request failed with HTTP {response.status_code}: "
                f"{error_code} {message}".strip()
            )

        raise MALAPIError("MAL API request failed after retries.")  # pragma: no cover

    async def get_anime_list(self) -> tuple[list[dict[str, Any]], bool]:
        """Fetch the authenticated user's full anime list.

        Follows ``paging.next`` until exhausted (capped at MAX_PAGES pages of
        PAGE_LIMIT entries) and returns ``(edges, truncated)`` where each edge is
        shaped ``{"node": {...}, "list_status": {...}}`` and ``truncated`` is True
        when the list was longer than the safety cap and got cut off.
        """
        entries: list[dict[str, Any]] = []
        params: dict[str, Any] | None = {"fields": LIST_FIELDS, "limit": PAGE_LIMIT, "offset": 0}
        url: str | None = "/users/@me/animelist"
        for _ in range(MAX_PAGES):
            if url is None:
                break
            page = await self._request(url, params=params)
            entries.extend(page.get("data") or [])
            next_url = (page.get("paging") or {}).get("next")
            url = _validated_paging_url(next_url) if next_url else None
            params = None  # paging.next is absolute and already carries all query params
        return entries, url is not None

    async def get_anime_list_page(
        self,
        status: str | None = None,
        sort: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Fetch one bounded page of the user's anime list.

        Returns ``(edges, has_more)``; ``has_more`` reflects ``paging.next``.
        """
        params: dict[str, Any] = {
            "fields": LIST_FIELDS,
            "limit": max(1, min(limit, PAGE_LIMIT)),
            "offset": max(0, offset),
        }
        if status:
            params["status"] = status
        if sort:
            params["sort"] = sort
        page = await self._request("/users/@me/animelist", params=params)
        return page.get("data") or [], bool((page.get("paging") or {}).get("next"))

    async def search_anime(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search anime by title. ``limit`` is clamped to MAL's documented max of 100."""
        params = {"q": query, "limit": max(1, min(limit, 100)), "fields": SEARCH_FIELDS}
        page = await self._request("/anime", params=params)
        return page.get("data") or []

    async def get_anime_detail(self, anime_id: int) -> dict[str, Any]:
        """Fetch full details for one anime, including my_list_status for the token's user."""
        return await self._request(f"/anime/{anime_id}", params={"fields": DETAIL_FIELDS})
