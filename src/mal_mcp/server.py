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
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.tools import ToolResult
from pydantic import Field

from mal_mcp.mal_client import MALClient, MALError, MALTokenError
from mal_mcp.token_manager import TokenManager, TokenRefreshError
from mal_mcp.ui import register_ui, ui_result, ui_tool_meta

MangaStatusFilter = Literal["reading", "completed", "on_hold", "dropped", "plan_to_read"]
MangaSortOrder = Literal["list_score", "list_updated_at", "manga_title", "manga_start_date"]
AnimeRankingType = Literal[
    "all", "airing", "upcoming", "tv", "ova", "movie", "special", "bypopularity", "favorite"
]
MangaRankingType = Literal[
    "all", "manga", "novels", "oneshots", "doujin", "manhwa", "manhua", "bypopularity", "favorite"
]
Season = Literal["winter", "spring", "summer", "fall"]
SeasonalSort = Literal["anime_score", "anime_num_list_users"]

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


def _picture(data: dict[str, Any], size: str = "medium") -> str | None:
    """Cover URL from MAL's main_picture ({'medium': .., 'large': ..}), if present."""
    pic = data.get("main_picture") or {}
    return pic.get(size) or pic.get("medium")


def _compact_entry(edge: dict[str, Any]) -> dict[str, Any]:
    """Flatten one animelist edge ({'node': .., 'list_status': ..}) into a compact record."""
    node = edge.get("node") or {}
    ls = edge.get("list_status") or {}
    return {
        "id": node.get("id"),
        "title": node.get("title"),
        "picture": _picture(node),
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
        "picture": _picture(node),
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
        "picture": _picture(data),
        "picture_large": _picture(data, "large"),
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


def _authors(items: Any) -> list[str]:
    """Format MAL's authors array as ['First Last (role)']."""
    out: list[str] = []
    for author in items if isinstance(items, list) else []:
        if not isinstance(author, dict):
            continue
        node = author.get("node") or {}
        name = " ".join(p for p in (node.get("first_name"), node.get("last_name")) if p)
        role = author.get("role")
        if name and role:
            out.append(f"{name} ({role})")
        elif name or role:
            out.append(name or role)
    return out


def _year_from_date(value: Any) -> int | None:
    """MAL dates may be partial ('2017', '2017-10'); extract the year if present."""
    if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None


def _compact_manga_entry(edge: dict[str, Any]) -> dict[str, Any]:
    """Flatten one mangalist edge ({'node': .., 'list_status': ..}) into a compact record."""
    node = edge.get("node") or {}
    ls = edge.get("list_status") or {}
    return {
        "id": node.get("id"),
        "title": node.get("title"),
        "picture": _picture(node),
        "year": _year_from_date(node.get("start_date")),
        "media_type": node.get("media_type"),
        "publishing_status": node.get("status"),
        "my_status": ls.get("status"),
        "my_score": ls.get("score") or 0,  # 0 = not scored on MAL
        "chapters_read": ls.get("num_chapters_read") or 0,
        "volumes_read": ls.get("num_volumes_read") or 0,
        "total_chapters": node.get("num_chapters") or 0,  # 0 = unknown/ongoing
        "total_volumes": node.get("num_volumes") or 0,
        "genres": _names(node.get("genres")),
        "mal_mean": node.get("mean"),
        "authors": _authors(node.get("authors")),
        "updated_at": ls.get("updated_at"),
    }


def _compact_manga_search_result(node: dict[str, Any]) -> dict[str, Any]:
    synopsis = node.get("synopsis") or ""
    if len(synopsis) > 300:
        synopsis = synopsis[:297] + "..."
    return {
        "id": node.get("id"),
        "title": node.get("title"),
        "picture": _picture(node),
        "year": _year_from_date(node.get("start_date")),
        "media_type": node.get("media_type"),
        "publishing_status": node.get("status"),
        "mean": node.get("mean"),
        "num_chapters": node.get("num_chapters") or 0,
        "num_volumes": node.get("num_volumes") or 0,
        "genres": _names(node.get("genres")),
        "authors": _authors(node.get("authors")),
        "synopsis": synopsis,
    }


def _related_titles(items: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": (r.get("node") or {}).get("id"),
            "title": (r.get("node") or {}).get("title"),
            "relation_type": r.get("relation_type"),
        }
        for r in items or []
    ]


def _compact_manga_detail(data: dict[str, Any]) -> dict[str, Any]:
    detail = {
        "id": data.get("id"),
        "title": data.get("title"),
        "picture": _picture(data),
        "picture_large": _picture(data, "large"),
        "alternative_titles": data.get("alternative_titles"),
        "synopsis": data.get("synopsis"),
        "mean": data.get("mean"),
        "rank": data.get("rank"),
        "popularity": data.get("popularity"),
        "num_list_users": data.get("num_list_users"),
        "num_scoring_users": data.get("num_scoring_users"),
        "media_type": data.get("media_type"),
        "publishing_status": data.get("status"),
        "num_chapters": data.get("num_chapters") or 0,
        "num_volumes": data.get("num_volumes") or 0,
        "year": _year_from_date(data.get("start_date")),
        "start_date": data.get("start_date"),
        "end_date": data.get("end_date"),
        "genres": _names(data.get("genres")),
        "authors": _authors(data.get("authors")),
        "serialization": [
            (s.get("node") or {}).get("name")
            for s in data.get("serialization") or []
            if (s.get("node") or {}).get("name")
        ],
        "related_manga": _related_titles(data.get("related_manga")),
        "related_anime": _related_titles(data.get("related_anime")),
        "recommendations": [
            {
                "id": (r.get("node") or {}).get("id"),
                "title": (r.get("node") or {}).get("title"),
                "num_recommendations": r.get("num_recommendations"),
            }
            for r in (data.get("recommendations") or [])[:10]
        ],
    }
    if data.get("my_list_status"):
        detail["my_list_status"] = data["my_list_status"]
    return detail


def _compact_ranking_entry(item: dict[str, Any], kind: str) -> dict[str, Any]:
    """Flatten one ranking edge ({'node': .., 'ranking': ..}) for anime or manga."""
    node = item.get("node") or {}
    ranking = item.get("ranking") or {}
    entry: dict[str, Any] = {
        "rank": ranking.get("rank"),
        "previous_rank": ranking.get("previous_rank"),
        "id": node.get("id"),
        "title": node.get("title"),
        "picture": _picture(node),
        "media_type": node.get("media_type"),
        "mean": node.get("mean"),
        "num_list_users": node.get("num_list_users"),
        "genres": _names(node.get("genres")),
    }
    if kind == "anime":
        entry["year"] = (node.get("start_season") or {}).get("year")
        entry["num_episodes"] = node.get("num_episodes") or 0
        entry["airing_status"] = node.get("status")
    else:
        entry["year"] = _year_from_date(node.get("start_date"))
        entry["num_chapters"] = node.get("num_chapters") or 0
        entry["publishing_status"] = node.get("status")
        entry["authors"] = _authors(node.get("authors"))
    return entry


def _compact_profile(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "picture": data.get("picture"),
        "birthday": data.get("birthday"),
        "location": data.get("location"),
        "joined_at": data.get("joined_at"),
        "time_zone": data.get("time_zone"),
        "is_supporter": data.get("is_supporter"),
        "anime_statistics": data.get("anime_statistics"),
    }


def _build_changes(**kwargs: Any) -> dict[str, Any]:
    """Collect the non-None fields of a list-status update as MAL form values."""
    changes: dict[str, Any] = {}
    for key, value in kwargs.items():
        if value is None:
            continue
        if isinstance(value, bool):
            changes[key] = "true" if value else "false"
        elif isinstance(value, list):
            if any("," in str(v) for v in value):
                raise ToolError(
                    "MAL stores tags as a comma-separated string, so a tag cannot itself "
                    "contain a comma. Split it into separate tags."
                )
            changes[key] = ",".join(str(v) for v in value)
        else:
            changes[key] = value
    if not changes:
        raise ToolError(
            "Nothing to update: provide at least one field (e.g. status, score, progress)."
        )
    return changes


# ---------------------------------------------------------------------------
# Weekly schedule helpers (unit-tested in tests/test_schedule.py)
# ---------------------------------------------------------------------------

JST = ZoneInfo("Asia/Tokyo")  # MAL broadcast times are Japan Standard Time
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _resolve_timezone(name: str | None) -> ZoneInfo | None:
    """Resolve an IANA timezone name; None means 'keep MAL's native JST'."""
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ToolError(
            f"Unknown timezone '{name}'. Use an IANA name like 'Europe/Istanbul' or "
            "'America/New_York', or omit it to see MAL's native JST times."
        ) from exc


def _parse_hhmm(value: Any) -> tuple[int, int] | None:
    """Parse MAL's 'HH:MM' broadcast time; tolerates late-night hours like '25:00'."""
    if not isinstance(value, str) or ":" not in value:
        return None
    hh, _, mm = value.partition(":")
    if not (hh.strip().isdigit() and mm.strip().isdigit()):
        return None
    minute = int(mm)
    if minute >= 60:
        return None
    return int(hh), minute


def _convert_broadcast(
    day: Any, start_time: Any, target_tz: ZoneInfo | None, *, now: datetime
) -> tuple[str | None, str | None]:
    """Map a JST (weekday, 'HH:MM') broadcast slot into ``target_tz``.

    Returns ``(weekday, 'HH:MM')`` in the target zone, or the JST values when
    ``target_tz`` is None. ``now`` (a tz-aware datetime) anchors which week's
    occurrence is used, so late-night times that cross midnight land on the right
    day; it is injected for deterministic tests. Returns ``(None, None)`` when the
    slot cannot be placed (no/invalid weekday).
    """
    if day not in WEEKDAYS:
        return None, None
    parsed = _parse_hhmm(start_time)
    if parsed is None:
        return day, None  # known day, unknown time (rare)
    hour, minute = parsed
    extra_days, hour = divmod(hour, 24)  # normalize '25:00' -> +1 day, 01:00
    jst_now = now.astimezone(JST)
    delta = (WEEKDAYS.index(day) - jst_now.weekday()) % 7
    slot = jst_now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(
        days=delta + extra_days
    )
    local = slot if target_tz is None else slot.astimezone(target_tz)
    return WEEKDAYS[local.weekday()], f"{local.hour:02d}:{local.minute:02d}"


def _schedule_entry(
    edge: dict[str, Any], target_tz: ZoneInfo | None, *, now: datetime
) -> dict[str, Any] | None:
    """Build one schedule row from a watching-list edge, or None if not airing now."""
    node = edge.get("node") or {}
    if node.get("status") != "currently_airing":
        return None
    ls = edge.get("list_status") or {}
    broadcast = node.get("broadcast") or {}
    day, when = _convert_broadcast(
        broadcast.get("day_of_the_week"), broadcast.get("start_time"), target_tz, now=now
    )
    return {
        "id": node.get("id"),
        "title": node.get("title"),
        "picture": _picture(node),
        "media_type": node.get("media_type"),
        "airing_status": node.get("status"),
        "my_score": ls.get("score") or 0,
        "episodes_watched": ls.get("num_episodes_watched") or 0,
        "total_episodes": node.get("num_episodes") or 0,
        "broadcast_time": when,
        "day": day,  # None -> unscheduled bucket
    }


def _build_schedule(
    edges: list[dict[str, Any]], target_tz: ZoneInfo | None, *, now: datetime
) -> tuple[list[dict[str, Any]], int]:
    """Group currently-airing watching entries into Mon->Sun (+ 'unscheduled')."""
    buckets: dict[str, list[dict[str, Any]]] = {d: [] for d in WEEKDAYS}
    unscheduled: list[dict[str, Any]] = []
    for edge in edges:
        entry = _schedule_entry(edge, target_tz, now=now)
        if entry is None:
            continue
        day = entry.pop("day")
        if day in buckets:
            buckets[day].append(entry)
        else:
            entry["broadcast_time"] = None
            unscheduled.append(entry)

    def _key(row: dict[str, Any]) -> tuple[bool, str]:
        t = row["broadcast_time"]
        return (t is None, t or "")  # timed shows first, sorted by time

    days = [{"day": d, "entries": sorted(buckets[d], key=_key)} for d in WEEKDAYS]
    if unscheduled:
        days.append({"day": "unscheduled", "entries": unscheduled})
    total = sum(len(d["entries"]) for d in days)
    return days, total


# ---------------------------------------------------------------------------
# Model-facing summaries for UI tools (the full payload goes to the app as
# structuredContent; these keep the model's context slim - ids are preserved
# so the model can chain into detail/update tools).
# ---------------------------------------------------------------------------


def _paging_note(count: int, offset: int, has_more: bool) -> str:
    return f"{count} entries (offset {offset}, has_more={str(has_more).lower()})"


def _summarize_search(kind: str, results: list[dict[str, Any]], query: str | None) -> str:
    label = f" for '{query}'" if query else " (MAL personalized suggestions)"
    size_col = "eps" if kind == "anime" else "chapters"
    lines = [
        f"{len(results)} {kind} result(s){label}",
        f"columns: id|title|year|type|mean|{size_col}|genres",
    ]
    for r in results:
        size = r.get("num_episodes") if kind == "anime" else r.get("num_chapters")
        lines.append(
            f"{r['id']}|{r['title']}|{r['year'] or '?'}|{r['media_type'] or '?'}|"
            f"{r['mean'] or '-'}|{size or '?'}|{','.join(r['genres'][:3]) or '-'}"
        )
    return "\n".join(lines)


def _summarize_list(
    kind: str,
    entries: list[dict[str, Any]],
    offset: int,
    has_more: bool,
    user_name: str | None = None,
) -> str:
    owner = f"{user_name}'s" if user_name else "my"
    progress_col = "watched/total" if kind == "anime" else "read/total_ch"
    lines = [
        f"{owner} {kind} list: {_paging_note(len(entries), offset, has_more)}",
        f"columns: id|my_score|my_status|title|year|type|{progress_col}|genres",
    ]
    for e in entries:
        if kind == "anime":
            progress = f"{e['episodes_watched']}/{e['total_episodes'] or '?'}"
        else:
            progress = f"{e['chapters_read']}/{e['total_chapters'] or '?'}"
        lines.append(
            f"{e['id']}|{e['my_score'] or '-'}|{e['my_status'] or '-'}|{e['title']}|"
            f"{e['year'] or '?'}|{e['media_type'] or '?'}|{progress}|"
            f"{','.join(e['genres'][:3]) or '-'}"
        )
    return "\n".join(lines)


def _summarize_detail(d: dict[str, Any], kind: str) -> str:
    lines = [
        f"{d.get('title')} ({d.get('year') or '?'}, {d.get('media_type') or '?'}) - MAL id {d.get('id')}",
        f"mean {d.get('mean') or '-'} | rank #{d.get('rank') or '-'} | "
        f"popularity #{d.get('popularity') or '-'} | {d.get('num_list_users') or 0} list users",
    ]
    if kind == "anime":
        lines.append(
            f"{d.get('num_episodes') or '?'} eps ({d.get('airing_status') or '?'}) | "
            f"genres: {', '.join(d.get('genres') or []) or '-'} | "
            f"studios: {', '.join(d.get('studios') or []) or '-'}"
        )
    else:
        lines.append(
            f"{d.get('num_chapters') or '?'} ch / {d.get('num_volumes') or '?'} vol "
            f"({d.get('publishing_status') or '?'}) | "
            f"genres: {', '.join(d.get('genres') or []) or '-'} | "
            f"authors: {', '.join(d.get('authors') or []) or '-'}"
        )
    if d.get("my_list_status"):
        ls = d["my_list_status"]
        lines.append(f"my status: {ls.get('status') or '-'}, my score: {ls.get('score') or '-'}")
    if d.get("synopsis"):
        lines.append(f"synopsis: {d['synopsis']}")
    related = d.get("related_anime" if kind == "anime" else "related_manga") or []
    if related:
        lines.append(
            "related: "
            + "; ".join(f"{r['title']} ({r['relation_type']}, id {r['id']})" for r in related[:8])
        )
    recommendations = d.get("recommendations") or []
    if recommendations:
        lines.append(
            "recommendations: "
            + "; ".join(f"{r['title']} (id {r['id']})" for r in recommendations[:5])
        )
    return "\n".join(lines)


def _summarize_ranking(
    kind: str, ranking_type: str, entries: list[dict[str, Any]], offset: int, has_more: bool
) -> str:
    lines = [
        f"MAL {kind} ranking '{ranking_type}': {_paging_note(len(entries), offset, has_more)}",
        "columns: rank|id|title|year|type|mean|list_users",
    ]
    for e in entries:
        lines.append(
            f"{e.get('rank') or '-'}|{e['id']}|{e['title']}|{e.get('year') or '?'}|"
            f"{e.get('media_type') or '?'}|{e.get('mean') or '-'}|{e.get('num_list_users') or '-'}"
        )
    return "\n".join(lines)


def _summarize_seasonal(
    year: int, season: str, entries: list[dict[str, Any]], offset: int, has_more: bool
) -> str:
    lines = [
        f"{season} {year} seasonal anime: {_paging_note(len(entries), offset, has_more)}",
        "columns: id|title|type|mean|list_users|genres",
    ]
    for e in entries:
        lines.append(
            f"{e['id']}|{e['title']}|{e.get('media_type') or '?'}|{e.get('mean') or '-'}|"
            f"{e.get('num_list_users') or '-'}|{','.join((e.get('genres') or [])[:3]) or '-'}"
        )
    return "\n".join(lines)


def _summarize_stats(stats: dict[str, Any]) -> str:
    scores = stats["scores"]
    episodes = stats["episodes"]
    lines = [
        f"Anime list stats: {stats['total_entries']} entries | {scores['scored_count']} scored "
        f"(mean {scores['mean'] or '-'}, median {scores['median'] or '-'})",
        "status: " + (", ".join(f"{k} {v}" for k, v in stats["status_distribution"].items()) or "-"),
        f"episodes watched: {episodes['total_episodes_watched']} "
        f"(~{episodes['estimated_watch_hours']}h / {episodes['estimated_watch_days']}d)",
        "top genres: "
        + (", ".join(f"{g['name']} ({g['count']})" for g in stats["top_genres"][:8]) or "-"),
        "top studios: "
        + (", ".join(f"{s['name']} ({s['count']})" for s in stats["top_studios"][:5]) or "-"),
        "media types: "
        + (", ".join(f"{k} {v}" for k, v in stats["media_type_distribution"].items()) or "-"),
        "decades: " + (", ".join(f"{k} {v}" for k, v in stats["release_decades"].items()) or "-"),
    ]
    community = stats["community_comparison"]
    if community["avg_my_score_minus_mal_mean"] is not None:
        lines.append(
            f"vs community: my score - MAL mean = {community['avg_my_score_minus_mal_mean']} "
            f"(over {community['compared_entries']} entries)"
        )
    if stats.get("truncated"):
        lines.append(f"WARNING: {stats.get('warning', 'list truncated at the fetch cap')}")
    return "\n".join(lines)


def _summarize_schedule(
    days: list[dict[str, Any]], total: int, tz_label: str, today: str
) -> str:
    if total == 0:
        return (
            "Weekly airing schedule: no currently-airing anime on your watching list "
            "(nothing to broadcast this week)."
        )
    lines = [f"My weekly airing schedule - {total} show(s), times in {tz_label} (today: {today})"]
    for group in days:
        if not group["entries"]:
            continue
        marker = " <- today" if group["day"] == today else ""
        lines.append(f"[{group['day']}{marker}]")
        for e in group["entries"]:
            when = e["broadcast_time"] or "--:--"
            progress = f"{e['episodes_watched']}/{e['total_episodes'] or '?'}"
            lines.append(f"  {when} {e['title']} (ep {progress}, id {e['id']})")
    return "\n".join(lines)


def _summarize_profile(profile: dict[str, Any]) -> str:
    lines = [f"MAL profile: {profile.get('name')} (id {profile.get('id')})"]
    joined = profile.get("joined_at") or ""
    facts = [
        f"location: {profile['location']}" if profile.get("location") else None,
        f"joined: {joined[:10]}" if joined else None,
        f"time zone: {profile['time_zone']}" if profile.get("time_zone") else None,
        "MAL supporter" if profile.get("is_supporter") else None,
    ]
    facts = [f for f in facts if f]
    if facts:
        lines.append(" | ".join(facts))
    anime_stats = profile.get("anime_statistics") or {}
    if anime_stats:
        lines.append(
            f"anime: {anime_stats.get('num_items') or 0} items | "
            f"{anime_stats.get('num_episodes') or 0} episodes | "
            f"{anime_stats.get('num_days') or 0} days watched | "
            f"mean score {anime_stats.get('mean_score') or '-'}"
        )
    return "\n".join(lines)


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


async def _fetch_watching_edges() -> list[dict[str, Any]]:
    """Fetch every 'watching' entry (raw edges) - small lists page in one request."""

    async def op(client: MALClient) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        offset = 0
        for _ in range(20):  # defensive cap; a watching list never nears 20k entries
            page, has_more = await client.get_anime_list_page(
                status="watching", limit=1000, offset=offset
            )
            edges.extend(page)
            if not has_more:
                break
            offset += len(page)
        return edges

    return await _call_mal(op)


@mcp.tool(
    annotations={
        "title": "Get My Anime List",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
    meta=ui_tool_meta(),
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
) -> ToolResult:
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

    Returns a compact text table (id|my_score|my_status|title|year|type|watched/total|genres)
    plus structured content {"total_returned", "offset", "has_more", "entries"} where each
    entry has: id, title, picture, year, media_type, airing_status, my_status, my_score
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
    return ui_result(
        "list",
        {
            "kind": "anime",
            "editable": True,
            "total_returned": len(entries),
            "offset": offset,
            "has_more": has_more,
            "entries": entries,
        },
        _summarize_list("anime", entries, offset, has_more),
    )


@mcp.tool(
    annotations={
        "title": "Get User Stats",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
    meta=ui_tool_meta(),
)
async def get_user_stats() -> ToolResult:
    """Compute summary statistics over the authenticated user's entire anime list.

    Fetches the full list in one paginated pass and aggregates locally (no extra MAL calls).

    Returns a text digest plus structured content with: total_entries; status_distribution;
    scores (count/mean/median/1-10 histogram); episodes (total watched + estimated watch
    hours/days, using each show's average episode duration, ~24 min fallback); top_genres
    (top 15 with count and avg user score); media_type_distribution; release_decades;
    community_comparison (avg difference between the user's scores and MAL community means);
    top_studios (top 10). If the list exceeds the 20,000-entry fetch cap,
    "truncated": true and a warning are included.
    """
    entries, truncated = await _fetch_compact_list()
    stats = _compute_stats(entries)
    if truncated:
        stats["truncated"] = True
        stats["warning"] = (
            "The list exceeds the 20,000-entry fetch cap; statistics cover only the "
            "first 20,000 entries."
        )
    return ui_result("dashboard", {"stats": stats}, _summarize_stats(stats))


@mcp.tool(
    annotations={
        "title": "Search Anime",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
    meta=ui_tool_meta(),
)
async def search_anime(
    query: Annotated[str, Field(min_length=1, description="Title to search for (MAL needs ~3+ characters)")],
    limit: Annotated[int, Field(ge=1, le=50, description="Maximum results to return")] = 10,
) -> ToolResult:
    """Search MyAnimeList's public anime catalog by title.

    Returns a compact text table (id|title|year|type|mean|eps|genres) plus structured
    content {"count": int, "results": [...]} where each result has: id, title, picture,
    year, media_type, airing_status, mean (community score), num_episodes, genres, and a
    synopsis truncated to 300 characters. Use get_anime_detail for full information.
    """
    nodes = await _call_mal(lambda client: client.search_anime(query, limit=limit))
    results = [_compact_search_result(edge.get("node") or {}) for edge in nodes]
    return ui_result(
        "search",
        {"kind": "anime", "query": query, "count": len(results), "results": results},
        _summarize_search("anime", results, query),
    )


@mcp.tool(
    annotations={
        "title": "Get Anime Detail",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
    meta=ui_tool_meta(),
)
async def get_anime_detail(
    anime_id: Annotated[int, Field(ge=1, description="MAL anime id, e.g. from search results")],
) -> ToolResult:
    """Fetch full public details for one anime by its MAL id.

    Returns title(s), synopsis, community stats (mean, rank, popularity, list/scoring user
    counts, per-status statistics), airing info, source, rating, genres, studios,
    related_anime, and up to 10 community recommendations. If the anime is on the
    authenticated user's list, my_list_status (their status/score/progress) is included.
    """
    data = await _call_mal(lambda client: client.get_anime_detail(anime_id))
    detail = _compact_detail(data)
    return ui_result("detail", {"kind": "anime", **detail}, _summarize_detail(detail, "anime"))


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


# ---------------------------------------------------------------------------
# Manga tools
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={"title": "Search Manga", "readOnlyHint": True, "openWorldHint": True},
    meta=ui_tool_meta(),
)
async def search_manga(
    query: Annotated[str, Field(min_length=1, description="Title to search for (MAL needs ~3+ characters)")],
    limit: Annotated[int, Field(ge=1, le=50, description="Maximum results to return")] = 10,
) -> ToolResult:
    """Search MyAnimeList's public manga catalog by title.

    Returns a compact text table (id|title|year|type|mean|chapters|genres) plus structured
    content {"count": int, "results": [...]} where each result has: id, title, picture,
    year, media_type (manga/novel/one_shot/...), publishing_status, mean (community score),
    num_chapters/num_volumes (0 = unknown/ongoing), genres, authors, and a synopsis
    truncated to 300 characters. Use get_manga_detail for full information.
    """
    nodes = await _call_mal(lambda client: client.search_manga(query, limit=limit))
    results = [_compact_manga_search_result(edge.get("node") or {}) for edge in nodes]
    return ui_result(
        "search",
        {"kind": "manga", "query": query, "count": len(results), "results": results},
        _summarize_search("manga", results, query),
    )


@mcp.tool(
    annotations={"title": "Get Manga Detail", "readOnlyHint": True, "openWorldHint": True},
    meta=ui_tool_meta(),
)
async def get_manga_detail(
    manga_id: Annotated[int, Field(ge=1, description="MAL manga id, e.g. from search results")],
) -> ToolResult:
    """Fetch full public details for one manga by its MAL id.

    Returns title(s), synopsis, community stats (mean, rank, popularity), publication
    info, chapter/volume counts, genres, authors, serialization magazines,
    related_manga/related_anime, and up to 10 community recommendations. If the manga
    is on the authenticated user's list, my_list_status is included.
    """
    data = await _call_mal(lambda client: client.get_manga_detail(manga_id))
    detail = _compact_manga_detail(data)
    return ui_result("detail", {"kind": "manga", **detail}, _summarize_detail(detail, "manga"))


@mcp.tool(
    annotations={"title": "Get My Manga List", "readOnlyHint": True, "openWorldHint": True},
    meta=ui_tool_meta(),
)
async def get_my_manga_list(
    status_filter: MangaStatusFilter | None = None,
    sort: MangaSortOrder | None = None,
    limit: Annotated[int, Field(ge=1, le=1000, description="Maximum entries to return")] = 100,
    offset: Annotated[int, Field(ge=0, description="Entries to skip for paging")] = 0,
) -> ToolResult:
    """Fetch a page of the authenticated user's MyAnimeList manga list.

    Args:
        status_filter: reading, completed, on_hold, dropped, plan_to_read. Omit for all.
        sort: list_score (desc), list_updated_at (desc), manga_title (asc),
            manga_start_date (desc). Omit for MAL's default order.

    Returns a compact text table plus structured content {"total_returned", "offset",
    "has_more", "entries"}; each entry has: id, title, picture, year, media_type,
    publishing_status, my_status, my_score (0 = not scored), chapters_read/volumes_read,
    total_chapters/total_volumes (0 = unknown), genres, mal_mean, authors, updated_at.
    """
    edges, has_more = await _call_mal(
        lambda client: client.get_manga_list_page(
            status=status_filter, sort=sort, limit=limit, offset=offset
        )
    )
    entries = [_compact_manga_entry(edge) for edge in edges]
    return ui_result(
        "list",
        {
            "kind": "manga",
            "editable": True,
            "total_returned": len(entries),
            "offset": offset,
            "has_more": has_more,
            "entries": entries,
        },
        _summarize_list("manga", entries, offset, has_more),
    )


# ---------------------------------------------------------------------------
# Discovery tools
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={"title": "Get Anime Ranking", "readOnlyHint": True, "openWorldHint": True},
    meta=ui_tool_meta(),
)
async def get_anime_ranking(
    ranking_type: AnimeRankingType = "all",
    limit: Annotated[int, Field(ge=1, le=500, description="Maximum entries to return")] = 25,
    offset: Annotated[int, Field(ge=0, description="Entries to skip for paging")] = 0,
) -> ToolResult:
    """Fetch MAL's official anime rankings.

    ranking_type: all (top by score), airing, upcoming, tv, ova, movie, special,
    bypopularity, favorite. Returns a compact text table plus structured content
    {"ranking_type", "total_returned", "offset", "has_more", "entries"}; each entry:
    rank, previous_rank, id, title, picture, year, media_type, mean, num_list_users,
    num_episodes, airing_status, genres.
    """
    items, has_more = await _call_mal(
        lambda client: client.get_anime_ranking(ranking_type, limit=limit, offset=offset)
    )
    entries = [_compact_ranking_entry(item, "anime") for item in items]
    return ui_result(
        "ranking",
        {
            "kind": "anime",
            "ranking_type": ranking_type,
            "total_returned": len(entries),
            "offset": offset,
            "has_more": has_more,
            "entries": entries,
        },
        _summarize_ranking("anime", ranking_type, entries, offset, has_more),
    )


@mcp.tool(
    annotations={"title": "Get Manga Ranking", "readOnlyHint": True, "openWorldHint": True},
    meta=ui_tool_meta(),
)
async def get_manga_ranking(
    ranking_type: MangaRankingType = "all",
    limit: Annotated[int, Field(ge=1, le=500, description="Maximum entries to return")] = 25,
    offset: Annotated[int, Field(ge=0, description="Entries to skip for paging")] = 0,
) -> ToolResult:
    """Fetch MAL's official manga rankings.

    ranking_type: all, manga, novels, oneshots, doujin, manhwa, manhua, bypopularity,
    favorite. Returns the same paged shape as get_anime_ranking; each entry: rank,
    previous_rank, id, title, picture, year, media_type, mean, num_list_users,
    num_chapters, publishing_status, authors, genres.
    """
    items, has_more = await _call_mal(
        lambda client: client.get_manga_ranking(ranking_type, limit=limit, offset=offset)
    )
    entries = [_compact_ranking_entry(item, "manga") for item in items]
    return ui_result(
        "ranking",
        {
            "kind": "manga",
            "ranking_type": ranking_type,
            "total_returned": len(entries),
            "offset": offset,
            "has_more": has_more,
            "entries": entries,
        },
        _summarize_ranking("manga", ranking_type, entries, offset, has_more),
    )


@mcp.tool(
    annotations={"title": "Get Seasonal Anime", "readOnlyHint": True, "openWorldHint": True},
    meta=ui_tool_meta(),
)
async def get_seasonal_anime(
    year: Annotated[int, Field(ge=1917, le=2100, description="Broadcast year")],
    season: Season,
    sort: SeasonalSort | None = "anime_score",
    limit: Annotated[int, Field(ge=1, le=500, description="Maximum entries to return")] = 25,
    offset: Annotated[int, Field(ge=0, description="Entries to skip for paging")] = 0,
) -> ToolResult:
    """Fetch the anime that aired in one broadcast season (winter/spring/summer/fall).

    Seasons: winter = Jan-Mar, spring = Apr-Jun, summer = Jul-Sep, fall = Oct-Dec.
    sort: anime_score (desc) or anime_num_list_users (desc). Returns a compact text
    table plus structured content {"year", "season", "total_returned", "offset",
    "has_more", "entries"} with compact anime entries (including picture).
    """
    items, has_more = await _call_mal(
        lambda client: client.get_seasonal_anime(
            year, season, sort=sort, limit=limit, offset=offset
        )
    )
    entries = [_compact_ranking_entry(item, "anime") for item in items]
    for e in entries:
        e.pop("rank", None)
        e.pop("previous_rank", None)
    return ui_result(
        "seasonal",
        {
            "kind": "anime",
            "year": year,
            "season": season,
            "total_returned": len(entries),
            "offset": offset,
            "has_more": has_more,
            "entries": entries,
        },
        _summarize_seasonal(year, season, entries, offset, has_more),
    )


@mcp.tool(
    annotations={"title": "Get Suggested Anime", "readOnlyHint": True, "openWorldHint": True},
    meta=ui_tool_meta(),
)
async def get_suggested_anime(
    limit: Annotated[int, Field(ge=1, le=100, description="Maximum suggestions to return")] = 25,
    offset: Annotated[int, Field(ge=0, description="Entries to skip for paging")] = 0,
) -> ToolResult:
    """Fetch MyAnimeList's personalized anime suggestions for the authenticated user.

    These are MAL's own recommendations based on the user's list (empty for accounts
    without watch history). Returns a compact text table plus structured content
    {"total_returned", "offset", "has_more", "results"} with the same compact shape
    as search_anime.
    """
    items, has_more = await _call_mal(
        lambda client: client.get_suggested_anime(limit=limit, offset=offset)
    )
    results = [_compact_search_result(item.get("node") or {}) for item in items]
    return ui_result(
        "search",
        {
            "kind": "anime",
            "suggested": True,
            "total_returned": len(results),
            "offset": offset,
            "has_more": has_more,
            "results": results,
        },
        _summarize_search("anime", results, None),
    )


@mcp.tool(
    annotations={"title": "Get Weekly Schedule", "readOnlyHint": True, "openWorldHint": True},
    meta=ui_tool_meta(),
)
async def get_weekly_schedule(
    timezone: Annotated[
        str | None,
        Field(
            description="IANA timezone name (e.g. 'Europe/Istanbul', 'America/New_York'). "
            "Omit to show MAL's native JST broadcast times."
        ),
    ] = None,
) -> ToolResult:
    """Your personal weekly airing calendar: which anime on your 'watching' list
    broadcast on each day of the week.

    Fetches your watching list, keeps only currently-airing shows, and groups them by
    broadcast day. Times are MAL's native JST unless `timezone` is given, in which case
    both the time and the weekday are converted to that zone (a late-night JST slot can
    fall on a different local day). Shows MAL has no broadcast slot for go in an
    "unscheduled" group.

    Returns a per-day text digest plus structured content {"timezone", "today", "total",
    "days": [{"day", "entries": [...]}]}; each entry has id, title, picture, media_type,
    my_score, episodes_watched, total_episodes, broadcast_time.
    """
    target_tz = _resolve_timezone(timezone)
    now = datetime.now(JST)
    edges = await _fetch_watching_edges()
    days, total = _build_schedule(edges, target_tz, now=now)
    tz_label = timezone or "Asia/Tokyo"
    today = WEEKDAYS[now.astimezone(target_tz or JST).weekday()]
    return ui_result(
        "schedule",
        {"timezone": tz_label, "today": today, "total": total, "days": days},
        _summarize_schedule(days, total, tz_label, today),
    )


# ---------------------------------------------------------------------------
# User tools
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={"title": "Get My Profile", "readOnlyHint": True, "openWorldHint": True},
    meta=ui_tool_meta(),
)
async def get_my_profile() -> ToolResult:
    """Fetch the authenticated user's MAL profile and lifetime anime statistics.

    Returns id, name, picture, birthday, location, joined_at, time_zone, is_supporter,
    and anime_statistics (items/days per watch status, total episodes, rewatches,
    mean score). MAL only exposes this endpoint for the token's own account.
    """
    data = await _call_mal(lambda client: client.get_my_profile())
    profile = _compact_profile(data)
    return ui_result("dashboard", {"profile": profile}, _summarize_profile(profile))


@mcp.tool(
    annotations={"title": "Get User Anime List", "readOnlyHint": True, "openWorldHint": True},
    meta=ui_tool_meta(),
)
async def get_user_anime_list(
    user_name: Annotated[str, Field(min_length=1, description="MAL username (public list)")],
    status_filter: StatusFilter | None = None,
    sort: SortOrder | None = None,
    limit: Annotated[int, Field(ge=1, le=1000, description="Maximum entries to return")] = 100,
    offset: Annotated[int, Field(ge=0, description="Entries to skip for paging")] = 0,
) -> ToolResult:
    """Fetch a page of ANOTHER MAL user's anime list (works only for public lists).

    Same paged shape as get_my_anime_list, plus "user_name" echoed in the response.
    A 403 usually means the user's list is private or the username does not exist.
    """
    edges, has_more = await _call_mal(
        lambda client: client.get_anime_list_page(
            status=status_filter, sort=sort, limit=limit, offset=offset, user_name=user_name
        )
    )
    entries = [_compact_entry(edge) for edge in edges]
    for e in entries:
        e.pop("avg_episode_duration_sec", None)
    return ui_result(
        "list",
        {
            "kind": "anime",
            "editable": False,
            "user_name": user_name,
            "total_returned": len(entries),
            "offset": offset,
            "has_more": has_more,
            "entries": entries,
        },
        _summarize_list("anime", entries, offset, has_more, user_name=user_name),
    )


@mcp.tool(
    annotations={"title": "Get User Manga List", "readOnlyHint": True, "openWorldHint": True},
    meta=ui_tool_meta(),
)
async def get_user_manga_list(
    user_name: Annotated[str, Field(min_length=1, description="MAL username (public list)")],
    status_filter: MangaStatusFilter | None = None,
    sort: MangaSortOrder | None = None,
    limit: Annotated[int, Field(ge=1, le=1000, description="Maximum entries to return")] = 100,
    offset: Annotated[int, Field(ge=0, description="Entries to skip for paging")] = 0,
) -> ToolResult:
    """Fetch a page of ANOTHER MAL user's manga list (works only for public lists).

    Same paged shape as get_my_manga_list, plus "user_name" echoed in the response.
    A 403 usually means the user's list is private or the username does not exist.
    """
    edges, has_more = await _call_mal(
        lambda client: client.get_manga_list_page(
            status=status_filter, sort=sort, limit=limit, offset=offset, user_name=user_name
        )
    )
    entries = [_compact_manga_entry(edge) for edge in edges]
    return ui_result(
        "list",
        {
            "kind": "manga",
            "editable": False,
            "user_name": user_name,
            "total_returned": len(entries),
            "offset": offset,
            "has_more": has_more,
            "entries": entries,
        },
        _summarize_list("manga", entries, offset, has_more, user_name=user_name),
    )


# ---------------------------------------------------------------------------
# Write tools (modify the authenticated user's list)
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Update My Anime Entry",
        "readOnlyHint": False,
        # Overwrites existing values (an old score is lost) => destructive per MCP semantics.
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def update_my_anime_entry(
    anime_id: Annotated[int, Field(ge=1, description="MAL anime id")],
    status: StatusFilter | None = None,
    score: Annotated[int | None, Field(ge=0, le=10, description="0 removes the score")] = None,
    num_watched_episodes: Annotated[int | None, Field(ge=0)] = None,
    is_rewatching: bool | None = None,
    priority: Annotated[int | None, Field(ge=0, le=2)] = None,
    num_times_rewatched: Annotated[int | None, Field(ge=0)] = None,
    rewatch_value: Annotated[int | None, Field(ge=0, le=5)] = None,
    tags: Annotated[list[str] | None, Field(description="Replaces the entry's tag list")] = None,
    comments: str | None = None,
) -> dict[str, Any]:
    """Update the authenticated user's list entry for an anime (or ADD it to the list).

    Only the provided fields are changed; at least one is required. If the anime is not
    on the user's list yet, MAL creates the entry (e.g. pass status="plan_to_watch" to
    add something). Returns the updated my_list_status.
    """
    changes = _build_changes(
        status=status,
        score=score,
        num_watched_episodes=num_watched_episodes,
        is_rewatching=is_rewatching,
        priority=priority,
        num_times_rewatched=num_times_rewatched,
        rewatch_value=rewatch_value,
        tags=tags,
        comments=comments,
    )
    result = await _call_mal(
        lambda client: client.update_anime_list_status(anime_id, changes)
    )
    return {"anime_id": anime_id, "my_list_status": result}


@mcp.tool(
    annotations={
        "title": "Delete My Anime Entry",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
async def delete_my_anime_entry(
    anime_id: Annotated[int, Field(ge=1, description="MAL anime id")],
) -> dict[str, Any]:
    """PERMANENTLY remove an anime from the authenticated user's list.

    This deletes the entry's score, progress, dates, and tags on MAL - it cannot be
    undone. MAL treats the delete as idempotent in practice (removing an entry that is
    already absent still succeeds); a 404 for an unknown id returns a clear message.
    """
    await _call_mal(lambda client: client.delete_anime_list_status(anime_id))
    return {"deleted": True, "anime_id": anime_id}


@mcp.tool(
    annotations={
        "title": "Update My Manga Entry",
        "readOnlyHint": False,
        # Overwrites existing values (an old score is lost) => destructive per MCP semantics.
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def update_my_manga_entry(
    manga_id: Annotated[int, Field(ge=1, description="MAL manga id")],
    status: MangaStatusFilter | None = None,
    score: Annotated[int | None, Field(ge=0, le=10, description="0 removes the score")] = None,
    num_chapters_read: Annotated[int | None, Field(ge=0)] = None,
    num_volumes_read: Annotated[int | None, Field(ge=0)] = None,
    is_rereading: bool | None = None,
    priority: Annotated[int | None, Field(ge=0, le=2)] = None,
    num_times_reread: Annotated[int | None, Field(ge=0)] = None,
    reread_value: Annotated[int | None, Field(ge=0, le=5)] = None,
    tags: Annotated[list[str] | None, Field(description="Replaces the entry's tag list")] = None,
    comments: str | None = None,
) -> dict[str, Any]:
    """Update the authenticated user's list entry for a manga (or ADD it to the list).

    Only the provided fields are changed; at least one is required. If the manga is not
    on the user's list yet, MAL creates the entry (e.g. pass status="plan_to_read" to
    add something). Returns the updated my_list_status.
    """
    changes = _build_changes(
        status=status,
        score=score,
        num_chapters_read=num_chapters_read,
        num_volumes_read=num_volumes_read,
        is_rereading=is_rereading,
        priority=priority,
        num_times_reread=num_times_reread,
        reread_value=reread_value,
        tags=tags,
        comments=comments,
    )
    result = await _call_mal(
        lambda client: client.update_manga_list_status(manga_id, changes)
    )
    return {"manga_id": manga_id, "my_list_status": result}


@mcp.tool(
    annotations={
        "title": "Delete My Manga Entry",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
async def delete_my_manga_entry(
    manga_id: Annotated[int, Field(ge=1, description="MAL manga id")],
) -> dict[str, Any]:
    """PERMANENTLY remove a manga from the authenticated user's list.

    This deletes the entry's score, progress, dates, and tags on MAL - it cannot be
    undone. MAL treats the delete as idempotent in practice (removing an entry that is
    already absent still succeeds); a 404 for an unknown id returns a clear message.
    """
    await _call_mal(lambda client: client.delete_manga_list_status(manga_id))
    return {"deleted": True, "manga_id": manga_id}


register_ui(mcp)


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
