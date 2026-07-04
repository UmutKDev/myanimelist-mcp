"""Optional self-renewing MAL access-token support.

When MAL_REFRESH_TOKEN and MAL_CLIENT_ID are set, the server mints and renews
access tokens itself via OAuth's refresh_token grant - a single POST to MAL's
token endpoint. There is still no login flow, no callback, and nothing is ever
written to disk: the current tokens live in memory only. MAL keeps previously
issued refresh tokens valid after rotation (verified empirically), so the
env-provided refresh token keeps working across container restarts.

Failure handling: tokens are renewed REFRESH_MARGIN_SECONDS before their real
expiry, and a refresh failure inside that margin serves the still-valid cached
token instead of failing the tool call. Failed refreshes back off for
REFRESH_RETRY_BACKOFF_SECONDS so MAL's token endpoint is never hammered.
"""

from __future__ import annotations

import asyncio
import os
import time

import httpx

MAL_TOKEN_URL = "https://myanimelist.net/v1/oauth2/token"
# Renew this long before expiry (MAL access tokens last ~31 days in practice).
REFRESH_MARGIN_SECONDS = 24 * 3600
# After a failed refresh, don't POST to the token endpoint again for this long.
REFRESH_RETRY_BACKOFF_SECONDS = 60.0
# Never serve a cached token this close to its hard expiry.
EXPIRY_SKEW_SECONDS = 60.0


class TokenRefreshError(Exception):
    """Refreshing the MAL access token failed; message is safe for the MCP client."""


class TokenManager:
    """Caches one MAL access token in memory and renews it before it expires."""

    def __init__(
        self,
        client_id: str,
        refresh_token: str,
        client_secret: str | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._timeout = timeout
        self._transport = transport
        self._access_token: str | None = None
        self._refresh_due_at = 0.0  # renew when now >= this (expiry minus margin)
        self._expires_at = 0.0  # hard expiry of the cached access token
        self._retry_after = 0.0  # no token-endpoint POSTs before this after a failure
        self._last_failure: TokenRefreshError | None = None
        self._lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> "TokenManager | None":
        """Build a manager from MAL_REFRESH_TOKEN / MAL_CLIENT_ID / MAL_CLIENT_SECRET."""
        refresh_token = os.getenv("MAL_REFRESH_TOKEN", "").strip()
        client_id = os.getenv("MAL_CLIENT_ID", "").strip()
        if not refresh_token or not client_id:
            return None
        return cls(
            client_id=client_id,
            refresh_token=refresh_token,
            client_secret=os.getenv("MAL_CLIENT_SECRET", "").strip() or None,
        )

    def invalidate(self, token: str | None = None) -> None:
        """Force the next get_token() to refresh (e.g. after MAL rejected the token).

        When ``token`` is given and it is no longer the cached one, this is a no-op:
        a concurrent call already replaced it, so the caller should simply pick up
        the fresh cached token instead of forcing a redundant refresh.
        """
        if token is not None and token != self._access_token:
            return
        self._refresh_due_at = 0.0
        self._expires_at = 0.0  # MAL rejected it: never serve it as a fallback
        self._retry_after = 0.0  # the forced refresh must not be delayed
        self._last_failure = None

    async def get_token(self) -> str:
        async with self._lock:
            now = time.time()
            if self._access_token is not None and now < self._refresh_due_at:
                return self._access_token

            cached_ok = (
                self._access_token is not None
                and now < self._expires_at - EXPIRY_SKEW_SECONDS
            )
            if now < self._retry_after:
                # Failure-backoff window: no new POST to MAL's token endpoint.
                if cached_ok:
                    assert self._access_token is not None
                    return self._access_token
                raise self._last_failure or TokenRefreshError(
                    "MAL token refresh is backing off after a recent failure; "
                    "try again shortly."
                )

            try:
                await self._refresh()
            except TokenRefreshError as exc:
                self._retry_after = now + REFRESH_RETRY_BACKOFF_SECONDS
                self._last_failure = exc
                if cached_ok:
                    # Soft-fail inside the early-renewal margin: the cached token is
                    # still valid at MAL, so serve it and retry the refresh later.
                    assert self._access_token is not None
                    return self._access_token
                raise

            assert self._access_token is not None
            return self._access_token

    async def _refresh(self) -> None:
        data = {
            "client_id": self._client_id,
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }
        if self._client_secret:
            data["client_secret"] = self._client_secret

        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            try:
                response = await client.post(MAL_TOKEN_URL, data=data)
            except httpx.HTTPError as exc:
                raise TokenRefreshError(
                    f"Could not reach the MAL token endpoint to refresh the access token "
                    f"({type(exc).__name__}). Try again shortly."
                ) from exc

        if response.status_code in (400, 401):
            raise TokenRefreshError(
                f"MAL rejected the refresh token (HTTP {response.status_code}). The "
                "MAL_REFRESH_TOKEN is most likely expired or revoked - obtain a fresh one "
                "(see the README's manual-token section) and update the environment."
            )
        if response.status_code != 200:
            raise TokenRefreshError(
                f"MAL's token endpoint temporarily refused the refresh "
                f"(HTTP {response.status_code}) - likely rate limiting or maintenance. "
                "It will be retried shortly."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise TokenRefreshError("MAL token endpoint returned a non-JSON response.") from exc

        access_token = payload.get("access_token")
        if not access_token:
            raise TokenRefreshError("MAL token endpoint returned no access_token.")

        now = time.time()
        expires_in = float(payload.get("expires_in") or 3600)
        self._access_token = access_token
        self._expires_at = now + expires_in
        # Renew early, but never so early that we'd refresh on every call.
        self._refresh_due_at = now + expires_in - min(
            REFRESH_MARGIN_SECONDS, expires_in / 2
        )
        self._retry_after = 0.0
        self._last_failure = None
        # MAL rotates refresh tokens; keep the newest (old ones stay valid on MAL's side,
        # so the env-provided token still works after a restart).
        self._refresh_token = payload.get("refresh_token") or self._refresh_token
