"""Async client for the MyAnimeList API v2.

The access token is supplied by the caller on every use (it arrives with each MCP
request); nothing is cached or persisted here. All endpoints send an explicit
``fields`` parameter because the MAL API returns a near-empty payload without one.
"""

from __future__ import annotations

import asyncio
import urllib.parse
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
MANGA_LIST_FIELDS = (
    "list_status,num_chapters,num_volumes,genres,mean,media_type,status,"
    "start_date,authors{first_name,last_name}"
)
MANGA_SEARCH_FIELDS = (
    "mean,genres,media_type,num_chapters,num_volumes,status,start_date,synopsis,"
    "authors{first_name,last_name}"
)
MANGA_DETAIL_FIELDS = (
    "alternative_titles,synopsis,mean,rank,popularity,num_list_users,num_scoring_users,"
    "genres,media_type,status,num_chapters,num_volumes,start_date,end_date,"
    "authors{first_name,last_name},serialization{name},my_list_status,related_anime,"
    "related_manga,recommendations"
)
RANKING_ANIME_FIELDS = "mean,genres,media_type,num_episodes,status,start_season,num_list_users"
RANKING_MANGA_FIELDS = (
    "mean,genres,media_type,num_chapters,num_volumes,status,start_date,num_list_users,"
    "authors{first_name,last_name}"
)
PROFILE_FIELDS = "anime_statistics,time_zone,is_supporter"

LIST_STATUSES = ("watching", "completed", "on_hold", "dropped", "plan_to_watch")
LIST_SORTS = ("list_score", "list_updated_at", "anime_title", "anime_start_date")
MANGA_LIST_STATUSES = ("reading", "completed", "on_hold", "dropped", "plan_to_read")
MANGA_LIST_SORTS = ("list_score", "list_updated_at", "manga_title", "manga_start_date")
ANIME_RANKING_TYPES = (
    "all", "airing", "upcoming", "tv", "ova", "movie", "special", "bypopularity", "favorite",
)
MANGA_RANKING_TYPES = (
    "all", "manga", "novels", "oneshots", "doujin", "manhwa", "manhua", "bypopularity", "favorite",
)
SEASONS = ("winter", "spring", "summer", "fall")

PAGE_LIMIT = 1000  # documented maximum for /users/{user_name}/animelist and /mangalist
RANKING_LIMIT = 500  # documented maximum for ranking/seasonal endpoints
SEARCH_LIMIT = 100  # documented maximum for /anime, /manga and /anime/suggestions
MAX_PAGES = 20  # safety cap while following paging.next (20k entries)
MAX_RETRIES = 3  # extra attempts on 403/429, backed off 1s/2s/4s

PRIVATE_LIST_HINT = (
    "When fetching another user's list, a 403 can also mean that user's list is private "
    "or the username does not exist."
)


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


def _quote_user(user_name: str) -> str:
    """URL-escape a username for path use ('@me' stays intact); guards path injection."""
    user_name = user_name.strip()
    if not user_name:
        raise MALAPIError("Username must not be empty.")
    return urllib.parse.quote(user_name, safe="@")


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

    async def _request(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        forbidden_hint: str | None = None,
        not_found_hint: str | None = None,
    ) -> dict[str, Any]:
        """Send one request with rate-limit retries and MAL error mapping.

        ``url`` is either a path (resolved against the API base) or the absolute
        ``paging.next`` URL returned by MAL. ``data`` is form-encoded (used by the
        PATCH list-status endpoints). A 2xx with an empty/null body (DELETE) yields {}.
        """
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._client.request(method, url, params=params, data=data)
            except httpx.TimeoutException as exc:
                raise MALAPIError("MAL API request timed out; try again shortly.") from exc
            except httpx.HTTPError as exc:
                # Only the exception type: httpx messages can embed request details.
                raise MALAPIError(
                    f"Could not reach the MAL API ({type(exc).__name__}); "
                    "check connectivity and try again."
                ) from exc

            if 300 <= response.status_code < 400:
                # MAL should never redirect API calls; treating one as success would
                # fake empty results (or a bogus write success), so fail loudly.
                raise MALAPIError(
                    f"MAL API answered with an unexpected redirect "
                    f"(HTTP {response.status_code}); not following it."
                )
            if response.status_code < 300:
                if not response.content:
                    return {}
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise MALAPIError("MAL API returned a non-JSON response.") from exc
                if payload is None:
                    return {}
                if not isinstance(payload, dict):
                    # DELETE answers 200 with a non-object body (observed live: []).
                    if method != "GET":
                        return {}
                    raise MALAPIError("MAL API returned an unexpected JSON shape.")
                return payload

            error_code, message = _parse_error_body(response)

            if response.status_code == 401:
                raise MALTokenError(
                    "MAL rejected the access token (401 invalid_token): the token is expired "
                    "or invalid. Renew the credential in use (gateway OAuth login, the "
                    "MAL_REFRESH_TOKEN setup, or the static MAL_ACCESS_TOKEN) and retry."
                )
            if response.status_code == 403 and forbidden_hint:
                # On another user's list a 403 deterministically means "private list /
                # unknown user" - retrying would just burn ~7s against a fixed answer.
                raise MALAPIError(
                    f"MAL API returned 403 (forbidden). {forbidden_hint} "
                    "(It can also be rate limiting - if the user definitely exists and "
                    "is public, wait a minute and retry.)"
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
                    not_found_hint
                    or "MAL API returned 404: the requested resource does not exist "
                    "(check the anime/manga id or username)."
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

    async def _list_page(
        self,
        path: str,
        fields: str,
        status: str | None,
        sort: str | None,
        limit: int,
        offset: int,
        forbidden_hint: str | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        params: dict[str, Any] = {
            "fields": fields,
            "limit": max(1, min(limit, PAGE_LIMIT)),
            "offset": max(0, offset),
        }
        if status:
            params["status"] = status
        if sort:
            params["sort"] = sort
        page = await self._request(path, params=params, forbidden_hint=forbidden_hint)
        return page.get("data") or [], bool((page.get("paging") or {}).get("next"))

    async def get_anime_list_page(
        self,
        status: str | None = None,
        sort: str | None = None,
        limit: int = 100,
        offset: int = 0,
        user_name: str = "@me",
    ) -> tuple[list[dict[str, Any]], bool]:
        """Fetch one bounded page of a user's anime list ('@me' or a public list).

        Returns ``(edges, has_more)``; ``has_more`` reflects ``paging.next``.
        """
        return await self._list_page(
            f"/users/{_quote_user(user_name)}/animelist",
            LIST_FIELDS,
            status,
            sort,
            limit,
            offset,
            forbidden_hint=PRIVATE_LIST_HINT if user_name != "@me" else None,
        )

    async def get_manga_list_page(
        self,
        status: str | None = None,
        sort: str | None = None,
        limit: int = 100,
        offset: int = 0,
        user_name: str = "@me",
    ) -> tuple[list[dict[str, Any]], bool]:
        """Fetch one bounded page of a user's manga list ('@me' or a public list)."""
        return await self._list_page(
            f"/users/{_quote_user(user_name)}/mangalist",
            MANGA_LIST_FIELDS,
            status,
            sort,
            limit,
            offset,
            forbidden_hint=PRIVATE_LIST_HINT if user_name != "@me" else None,
        )

    async def search_anime(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search anime by title. ``limit`` is clamped to MAL's documented max of 100."""
        params = {"q": query, "limit": max(1, min(limit, 100)), "fields": SEARCH_FIELDS}
        page = await self._request("/anime", params=params)
        return page.get("data") or []

    async def get_anime_detail(self, anime_id: int) -> dict[str, Any]:
        """Fetch full details for one anime, including my_list_status for the token's user."""
        return await self._request(f"/anime/{anime_id}", params={"fields": DETAIL_FIELDS})

    async def search_manga(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search manga by title. ``limit`` is clamped to MAL's documented max of 100."""
        params = {
            "q": query,
            "limit": max(1, min(limit, SEARCH_LIMIT)),
            "fields": MANGA_SEARCH_FIELDS,
        }
        page = await self._request("/manga", params=params)
        return page.get("data") or []

    async def get_manga_detail(self, manga_id: int) -> dict[str, Any]:
        """Fetch full details for one manga, including my_list_status for the token's user."""
        return await self._request(f"/manga/{manga_id}", params={"fields": MANGA_DETAIL_FIELDS})

    async def _offset_page(
        self, path: str, params: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], bool]:
        page = await self._request(path, params=params)
        return page.get("data") or [], bool((page.get("paging") or {}).get("next"))

    async def get_anime_ranking(
        self, ranking_type: str, limit: int = 25, offset: int = 0
    ) -> tuple[list[dict[str, Any]], bool]:
        """Fetch MAL's anime rankings; items are {'node': ..., 'ranking': {'rank': ...}}."""
        return await self._offset_page(
            "/anime/ranking",
            {
                "ranking_type": ranking_type,
                "limit": max(1, min(limit, RANKING_LIMIT)),
                "offset": max(0, offset),
                "fields": RANKING_ANIME_FIELDS,
            },
        )

    async def get_manga_ranking(
        self, ranking_type: str, limit: int = 25, offset: int = 0
    ) -> tuple[list[dict[str, Any]], bool]:
        """Fetch MAL's manga rankings; items are {'node': ..., 'ranking': {'rank': ...}}."""
        return await self._offset_page(
            "/manga/ranking",
            {
                "ranking_type": ranking_type,
                "limit": max(1, min(limit, RANKING_LIMIT)),
                "offset": max(0, offset),
                "fields": RANKING_MANGA_FIELDS,
            },
        )

    async def get_seasonal_anime(
        self,
        year: int,
        season: str,
        sort: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Fetch the anime of one broadcast season."""
        params: dict[str, Any] = {
            "limit": max(1, min(limit, RANKING_LIMIT)),
            "offset": max(0, offset),
            "fields": RANKING_ANIME_FIELDS,
        }
        if sort:
            params["sort"] = sort
        return await self._offset_page(f"/anime/season/{year}/{season}", params)

    async def get_suggested_anime(
        self, limit: int = 25, offset: int = 0
    ) -> tuple[list[dict[str, Any]], bool]:
        """Fetch MAL's personalized anime suggestions for the token's user."""
        return await self._offset_page(
            "/anime/suggestions",
            {
                "limit": max(1, min(limit, SEARCH_LIMIT)),
                "offset": max(0, offset),
                "fields": SEARCH_FIELDS,
            },
        )

    async def get_my_profile(self) -> dict[str, Any]:
        """Fetch the authenticated user's profile (MAL supports only '@me' here)."""
        return await self._request("/users/@me", params={"fields": PROFILE_FIELDS})

    async def update_anime_list_status(
        self, anime_id: int, changes: dict[str, Any]
    ) -> dict[str, Any]:
        """PATCH the user's list entry for an anime (creates it if absent)."""
        return await self._request(
            f"/anime/{anime_id}/my_list_status",
            method="PATCH",
            data=changes,
            not_found_hint=f"MAL returned 404: no anime with id {anime_id} exists.",
        )

    async def delete_anime_list_status(self, anime_id: int) -> None:
        """Remove an anime from the user's list; 404 when it is not on the list."""
        await self._request(
            f"/anime/{anime_id}/my_list_status",
            method="DELETE",
            not_found_hint=(
                f"MAL returned 404: anime {anime_id} is not on the user's list "
                "(or the id does not exist), so there was nothing to delete."
            ),
        )

    async def update_manga_list_status(
        self, manga_id: int, changes: dict[str, Any]
    ) -> dict[str, Any]:
        """PATCH the user's list entry for a manga (creates it if absent)."""
        return await self._request(
            f"/manga/{manga_id}/my_list_status",
            method="PATCH",
            data=changes,
            not_found_hint=f"MAL returned 404: no manga with id {manga_id} exists.",
        )

    async def delete_manga_list_status(self, manga_id: int) -> None:
        """Remove a manga from the user's list; 404 when it is not on the list."""
        await self._request(
            f"/manga/{manga_id}/my_list_status",
            method="DELETE",
            not_found_hint=(
                f"MAL returned 404: manga {manga_id} is not on the user's list "
                "(or the id does not exist), so there was nothing to delete."
            ),
        )
