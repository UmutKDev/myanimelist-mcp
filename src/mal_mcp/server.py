"""MyAnimeList MCP server (streamable-http, stateless).

Token handling, in precedence order:

1. Per-request ``Authorization: Bearer <MAL access token>`` header (e.g. an MCP
   gateway such as Obot performing the OAuth flow) - forwarded as-is, never stored.
2. Self-renewing mode: when MAL_REFRESH_TOKEN and MAL_CLIENT_ID (optionally
   MAL_CLIENT_SECRET) are set, the server mints and renews access tokens itself
   via OAuth's refresh_token grant. The current tokens are held in process memory
   only - nothing is written to disk, and no token material appears in logs or
   error messages. There is still no interactive OAuth login flow here.
3. Static MAL_ACCESS_TOKEN env var - forwarded as-is.
"""

from __future__ import annotations

import os
import statistics
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from pydantic import Field

from mal_mcp.mal_client import MALClient, MALError, MALTokenError
from mal_mcp.token_manager import TokenManager, TokenRefreshError

mcp = FastMCP("mal_mcp")

# Fallback when MAL reports no average_episode_duration (seconds; ~a typical TV episode).
DEFAULT_EPISODE_SECONDS = 1440
STATUS_ORDER = ("completed", "watching", "on_hold", "dropped", "plan_to_watch")

StatusFilter = Literal["watching", "completed", "on_hold", "dropped", "plan_to_watch"]
SortOrder = Literal["list_score", "list_updated_at", "anime_title", "anime_start_date"]


_TOKEN_MANAGER: TokenManager | None = None


def _token_manager() -> TokenManager | None:
    """Lazy singleton so the manager (and its in-memory token cache) persists."""
    global _TOKEN_MANAGER
    if _TOKEN_MANAGER is None:
        _TOKEN_MANAGER = TokenManager.from_env()
    return _TOKEN_MANAGER


def _strip_bearer(value: str) -> str:
    value = value.strip()
    if value.lower() == "bearer":  # scheme without a credential
        return ""
    if value.lower().startswith("bearer "):
        value = value[len("bearer ") :].strip()
    return value


async def _resolve_token() -> tuple[str, TokenManager | None]:
    """Pick the MAL token: Authorization header > refresh-token manager > static env.

    Returns (token, manager); manager is non-None only when the token came from the
    self-renewing TokenManager, so callers can invalidate + retry on a MAL 401.
    """
    # fastmcp 3.x strips 'authorization' from get_http_headers() unless re-included.
    headers = get_http_headers(include={"authorization"})
    header_token = _strip_bearer(headers.get("authorization", ""))
    if header_token:
        return header_token, None

    # Obot's containerized runtime delivers user credentials as env vars, not headers.
    manager = _token_manager()
    if manager is not None:
        try:
            return await manager.get_token(), manager
        except TokenRefreshError as exc:
            raise ToolError(str(exc)) from exc

    env_token = _strip_bearer(os.getenv("MAL_ACCESS_TOKEN", ""))
    if env_token:
        return env_token, None

    raise ToolError(
        "No MAL access token. Provide one of: an 'Authorization: Bearer <token>' request "
        "header (gateway OAuth), MAL_REFRESH_TOKEN + MAL_CLIENT_ID env vars (self-renewing, "
        "recommended), or a static MAL_ACCESS_TOKEN env var. See the README."
    )


async def _call_mal(op: Callable[[MALClient], Awaitable[Any]]) -> Any:
    """Run one MAL operation with a resolved token, mapping MALError to ToolError.

    When the token came from the TokenManager and MAL rejects it mid-lifetime
    (revoked, clock skew), force one refresh and retry once.
    """
    token, manager = await _resolve_token()
    try:
        async with MALClient(token) as client:
            return await op(client)
    except MALTokenError as exc:
        if manager is None:
            raise ToolError(str(exc)) from exc
        # Token-aware: a no-op when a concurrent call already replaced this token,
        # so staggered 401s don't force N redundant refreshes.
        manager.invalidate(token)
        try:
            fresh = await manager.get_token()
        except TokenRefreshError as refresh_exc:
            raise ToolError(str(refresh_exc)) from refresh_exc
        try:
            async with MALClient(fresh) as client:
                return await op(client)
        except MALError as retry_exc:
            raise ToolError(str(retry_exc)) from retry_exc
    except MALError as exc:
        raise ToolError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested in tests/test_stats.py)
# ---------------------------------------------------------------------------


def _names(items: Any) -> list[str]:
    """Extract 'name' values from MAL's [{'id': .., 'name': ..}] shapes."""
    if not isinstance(items, list):
        return []
    return [i["name"] for i in items if isinstance(i, dict) and i.get("name")]


def _compact_entry(edge: dict[str, Any]) -> dict[str, Any]:
    """Flatten one animelist edge ({'node': .., 'list_status': ..}) into a compact record."""
    node = edge.get("node") or {}
    ls = edge.get("list_status") or {}
    return {
        "id": node.get("id"),
        "title": node.get("title"),
        "year": (node.get("start_season") or {}).get("year"),
        "media_type": node.get("media_type"),
        "airing_status": node.get("status"),
        "my_status": ls.get("status"),
        "my_score": ls.get("score") or 0,  # 0 = not scored on MAL
        "episodes_watched": ls.get("num_episodes_watched") or 0,
        "total_episodes": node.get("num_episodes") or 0,  # 0 = unknown on MAL
        "genres": _names(node.get("genres")),
        "mal_mean": node.get("mean"),
        "avg_episode_duration_sec": node.get("average_episode_duration") or 0,
        "studios": _names(node.get("studios")),
        "updated_at": ls.get("updated_at"),
    }


def _compute_stats(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a compact-entry list into taste/consumption statistics."""
    scores = [e["my_score"] for e in entries if e["my_score"]]
    histogram = {str(i): 0 for i in range(1, 11)}
    for s in scores:
        if 1 <= s <= 10:
            histogram[str(s)] += 1

    genre_counts: Counter[str] = Counter()
    genre_scores: dict[str, list[int]] = defaultdict(list)
    studio_counts: Counter[str] = Counter()
    studio_scores: dict[str, list[int]] = defaultdict(list)
    for e in entries:
        for g in e["genres"]:
            genre_counts[g] += 1
            if e["my_score"]:
                genre_scores[g].append(e["my_score"])
        for s in e["studios"]:
            studio_counts[s] += 1
            if e["my_score"]:
                studio_scores[s].append(e["my_score"])

    def _ranked(counts: Counter[str], per_scores: dict[str, list[int]], top: int) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "count": count,
                "avg_my_score": round(statistics.mean(per_scores[name]), 2) if per_scores.get(name) else None,
            }
            for name, count in counts.most_common(top)
        ]

    watch_seconds = sum(
        e["episodes_watched"] * (e["avg_episode_duration_sec"] or DEFAULT_EPISODE_SECONDS)
        for e in entries
    )

    diffs = [
        e["my_score"] - e["mal_mean"] for e in entries if e["my_score"] and e["mal_mean"]
    ]

    decades: Counter[str] = Counter()
    for e in entries:
        if e["year"]:
            decades[f"{e['year'] // 10 * 10}s"] += 1

    return {
        "total_entries": len(entries),
        "status_distribution": dict(Counter(e["my_status"] or "unknown" for e in entries)),
        "scores": {
            "scored_count": len(scores),
            "mean": round(statistics.mean(scores), 2) if scores else None,
            "median": statistics.median(scores) if scores else None,
            "histogram_1_to_10": histogram,
        },
        "episodes": {
            "total_episodes_watched": sum(e["episodes_watched"] for e in entries),
            "estimated_watch_hours": round(watch_seconds / 3600, 1),
            "estimated_watch_days": round(watch_seconds / 86400, 1),
        },
        "top_genres": _ranked(genre_counts, genre_scores, 15),
        "media_type_distribution": dict(Counter(e["media_type"] or "unknown" for e in entries)),
        "release_decades": dict(sorted(decades.items())),
        "community_comparison": {
            "avg_my_score_minus_mal_mean": round(statistics.mean(diffs), 2) if diffs else None,
            "compared_entries": len(diffs),
        },
        "top_studios": _ranked(studio_counts, studio_scores, 10),
    }


def _format_taste(entries: list[dict[str, Any]]) -> str:
    """Render the list as a compact, token-efficient text block (no analysis)."""
    scores = [e["my_score"] for e in entries if e["my_score"]]
    avg = round(statistics.mean(scores), 2) if scores else "-"
    total_eps = sum(e["episodes_watched"] for e in entries)
    lines = [
        f"MAL list snapshot: {len(entries)} entries | {len(scores)} scored (avg {avg}) | "
        f"{total_eps} episodes watched",
        "columns: my_score|title|year|type|watched/total_eps|genres|mal_mean",
    ]

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in entries:
        groups[e["my_status"] or "unknown"].append(e)

    ordered = [s for s in STATUS_ORDER if s in groups]
    ordered += [s for s in groups if s not in STATUS_ORDER]
    for status in ordered:
        group = groups[status]
        group_scores = [e["my_score"] for e in group if e["my_score"]]
        group_avg = f", avg {round(statistics.mean(group_scores), 2)}" if group_scores else ""
        lines.append(f"\n[{status}] n={len(group)}{group_avg}")
        for e in sorted(group, key=lambda x: (-x["my_score"], x["title"] or "")):
            eps = f"{e['episodes_watched']}/{e['total_episodes'] or '?'}"
            lines.append(
                f"{e['my_score'] or '-'}|{e['title']}|{e['year'] or '?'}|"
                f"{e['media_type'] or '?'}|{eps}|{','.join(e['genres'][:3]) or '-'}|"
                f"{e['mal_mean'] or '-'}"
            )
    return "\n".join(lines)


def _compact_search_result(node: dict[str, Any]) -> dict[str, Any]:
    synopsis = node.get("synopsis") or ""
    if len(synopsis) > 300:
        synopsis = synopsis[:297] + "..."
    return {
        "id": node.get("id"),
        "title": node.get("title"),
        "year": (node.get("start_season") or {}).get("year"),
        "media_type": node.get("media_type"),
        "airing_status": node.get("status"),
        "mean": node.get("mean"),
        "num_episodes": node.get("num_episodes") or 0,
        "genres": _names(node.get("genres")),
        "synopsis": synopsis,
    }


def _compact_detail(data: dict[str, Any]) -> dict[str, Any]:
    related = [
        {
            "id": (r.get("node") or {}).get("id"),
            "title": (r.get("node") or {}).get("title"),
            "relation_type": r.get("relation_type"),
        }
        for r in data.get("related_anime") or []
    ]
    recommendations = [
        {
            "id": (r.get("node") or {}).get("id"),
            "title": (r.get("node") or {}).get("title"),
            "num_recommendations": r.get("num_recommendations"),
        }
        for r in (data.get("recommendations") or [])[:10]
    ]
    detail = {
        "id": data.get("id"),
        "title": data.get("title"),
        "alternative_titles": data.get("alternative_titles"),
        "synopsis": data.get("synopsis"),
        "mean": data.get("mean"),
        "rank": data.get("rank"),
        "popularity": data.get("popularity"),
        "num_list_users": data.get("num_list_users"),
        "num_scoring_users": data.get("num_scoring_users"),
        "media_type": data.get("media_type"),
        "airing_status": data.get("status"),
        "num_episodes": data.get("num_episodes") or 0,
        "year": (data.get("start_season") or {}).get("year"),
        "start_date": data.get("start_date"),
        "end_date": data.get("end_date"),
        "source": data.get("source"),
        "average_episode_duration_sec": data.get("average_episode_duration"),
        "rating": data.get("rating"),
        "genres": _names(data.get("genres")),
        "studios": _names(data.get("studios")),
        "related_anime": related,
        "recommendations": recommendations,
        "statistics": data.get("statistics"),
    }
    if data.get("my_list_status"):
        detail["my_list_status"] = data["my_list_status"]
    return detail


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


async def _fetch_compact_list() -> tuple[list[dict[str, Any]], bool]:
    """Fetch the user's full (paginated) list once and compact every entry.

    Returns ``(entries, truncated)``; ``truncated`` is True when the list exceeded
    the 20,000-entry safety cap and the tail was dropped.
    """
    edges, truncated = await _call_mal(lambda client: client.get_anime_list())
    return [_compact_entry(edge) for edge in edges], truncated


@mcp.tool(
    annotations={
        "title": "Get My Anime List",
        "readOnlyHint": True,
        "openWorldHint": True,
    }
)
async def get_my_anime_list(
    status_filter: StatusFilter | None = None,
    sort: SortOrder | None = None,
    limit: Annotated[
        int, Field(ge=1, le=1000, description="Maximum entries to return in this call")
    ] = 100,
    offset: Annotated[
        int, Field(ge=0, description="Entries to skip; increase to page through large lists")
    ] = 0,
) -> dict[str, Any]:
    """Fetch a page of the authenticated user's MyAnimeList anime list.

    Results are paged to keep responses bounded: use `limit`/`offset` (and `has_more` in
    the response) to fetch further pages. For the complete list in one compact blob use
    analyze_taste; for aggregates use get_user_stats.

    Args:
        status_filter: Only return entries with this watch status
            (watching, completed, on_hold, dropped, plan_to_watch). Omit for the full list.
        sort: MAL server-side ordering: list_score (desc), list_updated_at (desc),
            anime_title (asc), anime_start_date (desc). Omit for MAL's default order.
        limit: Maximum entries to return (1-1000, default 100).
        offset: Entries to skip for paging (default 0).

    Returns:
        {"total_returned": int, "offset": int, "has_more": bool, "entries": [...]} where each
        entry has: id, title, year, media_type, airing_status, my_status, my_score
        (0 = not scored), episodes_watched, total_episodes (0 = unknown), genres,
        mal_mean (community score), studios, updated_at.
    """
    edges, has_more = await _call_mal(
        lambda client: client.get_anime_list_page(
            status=status_filter, sort=sort, limit=limit, offset=offset
        )
    )
    entries = [_compact_entry(edge) for edge in edges]
    for e in entries:
        e.pop("avg_episode_duration_sec", None)  # internal detail used only by stats
    return {
        "total_returned": len(entries),
        "offset": offset,
        "has_more": has_more,
        "entries": entries,
    }


@mcp.tool(
    annotations={
        "title": "Get User Stats",
        "readOnlyHint": True,
        "openWorldHint": True,
    }
)
async def get_user_stats() -> dict[str, Any]:
    """Compute summary statistics over the authenticated user's entire anime list.

    Fetches the full list in one paginated pass and aggregates locally (no extra MAL calls).

    Returns a dict with: total_entries; status_distribution; scores (count/mean/median/
    1-10 histogram); episodes (total watched + estimated watch hours/days, using each show's
    average episode duration, ~24 min fallback); top_genres (top 15 with count and avg user
    score); media_type_distribution; release_decades; community_comparison (avg difference
    between the user's scores and MAL community means); top_studios (top 10). If the list
    exceeds the 20,000-entry fetch cap, "truncated": true and a warning are included.
    """
    entries, truncated = await _fetch_compact_list()
    stats = _compute_stats(entries)
    if truncated:
        stats["truncated"] = True
        stats["warning"] = (
            "The list exceeds the 20,000-entry fetch cap; statistics cover only the "
            "first 20,000 entries."
        )
    return stats


@mcp.tool(
    annotations={
        "title": "Search Anime",
        "readOnlyHint": True,
        "openWorldHint": True,
    }
)
async def search_anime(
    query: Annotated[str, Field(min_length=1, description="Title to search for (MAL needs ~3+ characters)")],
    limit: Annotated[int, Field(ge=1, le=50, description="Maximum results to return")] = 10,
) -> dict[str, Any]:
    """Search MyAnimeList's public anime catalog by title.

    Returns {"count": int, "results": [...]} where each result has: id, title, year,
    media_type, airing_status, mean (community score), num_episodes, genres, and a
    synopsis truncated to 300 characters. Use get_anime_detail for full information.
    """
    nodes = await _call_mal(lambda client: client.search_anime(query, limit=limit))
    results = [_compact_search_result(edge.get("node") or {}) for edge in nodes]
    return {"count": len(results), "results": results}


@mcp.tool(
    annotations={
        "title": "Get Anime Detail",
        "readOnlyHint": True,
        "openWorldHint": True,
    }
)
async def get_anime_detail(
    anime_id: Annotated[int, Field(ge=1, description="MAL anime id, e.g. from search results")],
) -> dict[str, Any]:
    """Fetch full public details for one anime by its MAL id.

    Returns title(s), synopsis, community stats (mean, rank, popularity, list/scoring user
    counts, per-status statistics), airing info, source, rating, genres, studios,
    related_anime, and up to 10 community recommendations. If the anime is on the
    authenticated user's list, my_list_status (their status/score/progress) is included.
    """
    data = await _call_mal(lambda client: client.get_anime_detail(anime_id))
    return _compact_detail(data)


@mcp.tool(
    # A plain-text export: suppress the auto output schema so the payload isn't
    # duplicated into structuredContent as {"result": "<entire text>"}.
    output_schema=None,
    annotations={
        "title": "Analyze Taste (raw data export)",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
async def analyze_taste() -> str:
    """Return the user's entire anime list in a compact, token-efficient text format.

    This tool performs NO analysis - it exports the raw data (grouped by watch status,
    sorted by the user's score) so the calling model can analyze taste, spot patterns,
    and craft recommendations. Line format: my_score|title|year|type|watched/total_eps|
    genres|mal_mean ('-' = not scored / unknown). Lists longer than the 20,000-entry
    fetch cap are exported partially, with a leading WARNING line.
    """
    entries, truncated = await _fetch_compact_list()
    if not entries:
        return "MAL list snapshot: 0 entries (the user's anime list is empty)."
    text = _format_taste(entries)
    if truncated:
        text = (
            "WARNING: only the first 20,000 entries were fetched (list exceeds the safety "
            "cap); the data below is partial.\n" + text
        )
    return text


def main() -> None:
    mcp.run(
        transport="http",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        path="/mcp",
        stateless_http=True,
        # Plain JSON bodies instead of SSE frames: this server never emits
        # notifications, and JSON survives gateways that rewrite Accept headers.
        json_response=True,
    )


if __name__ == "__main__":
    main()
