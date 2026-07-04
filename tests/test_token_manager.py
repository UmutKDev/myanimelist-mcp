"""Tests for the self-renewing TokenManager and the _call_mal retry path."""

import asyncio
import urllib.parse

import httpx
import pytest
from fastmcp.exceptions import ToolError

import mal_mcp.server as server
from mal_mcp.mal_client import MALTokenError
from mal_mcp.token_manager import TokenManager, TokenRefreshError


def _run(coro):
    return asyncio.run(coro)


def _token_response(n: int, expires_in: int = 2678400) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "token_type": "Bearer",
            "expires_in": expires_in,
            "access_token": f"access-{n}",
            "refresh_token": f"refresh-{n}",
        },
    )


class TestTokenManager:
    def test_refreshes_once_then_caches(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(dict(urllib.parse.parse_qsl(request.content.decode())))
            return _token_response(len(calls))

        mgr = TokenManager(
            "cid", "refresh-0", client_secret="sec", transport=httpx.MockTransport(handler)
        )

        async def go():
            first = await mgr.get_token()
            second = await mgr.get_token()  # must be served from cache
            return first, second

        first, second = _run(go())
        assert first == second == "access-1"
        assert len(calls) == 1
        assert calls[0]["grant_type"] == "refresh_token"
        assert calls[0]["refresh_token"] == "refresh-0"
        assert calls[0]["client_secret"] == "sec"

    def test_public_client_omits_secret(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(urllib.parse.parse_qsl(request.content.decode()))
            return _token_response(1)

        mgr = TokenManager("cid", "refresh-0", transport=httpx.MockTransport(handler))
        _run(mgr.get_token())
        assert "client_secret" not in seen

    def test_invalidate_forces_refresh_and_rotates_refresh_token(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(dict(urllib.parse.parse_qsl(request.content.decode())))
            return _token_response(len(calls))

        mgr = TokenManager("cid", "refresh-0", transport=httpx.MockTransport(handler))

        async def go():
            await mgr.get_token()
            mgr.invalidate()
            return await mgr.get_token()

        token = _run(go())
        assert token == "access-2"
        # The second refresh must use the rotated refresh token from the first response.
        assert calls[1]["refresh_token"] == "refresh-1"

    def test_expired_refresh_token_raises_actionable_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "invalid_grant"})

        mgr = TokenManager("cid", "refresh-0", transport=httpx.MockTransport(handler))
        with pytest.raises(TokenRefreshError, match="MAL_REFRESH_TOKEN"):
            _run(mgr.get_token())

    def test_short_lived_token_not_refreshed_on_every_call(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return _token_response(len(calls), expires_in=3600)  # shorter than the margin

        mgr = TokenManager("cid", "refresh-0", transport=httpx.MockTransport(handler))

        async def go():
            await mgr.get_token()
            await mgr.get_token()

        _run(go())
        assert len(calls) == 1

    def test_from_env(self, monkeypatch):
        for var in ("MAL_REFRESH_TOKEN", "MAL_CLIENT_ID", "MAL_CLIENT_SECRET"):
            monkeypatch.delenv(var, raising=False)
        assert TokenManager.from_env() is None
        monkeypatch.setenv("MAL_REFRESH_TOKEN", "rt")
        assert TokenManager.from_env() is None  # client id still missing
        monkeypatch.setenv("MAL_CLIENT_ID", "cid")
        assert TokenManager.from_env() is not None


class TestRefreshFailureResilience:
    def _flaky_manager(self, fail_after: int):
        """Manager whose token endpoint starts failing after `fail_after` requests."""
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) > fail_after:
                return httpx.Response(503, text="maintenance")
            return _token_response(len(calls))

        return TokenManager("cid", "refresh-0", transport=httpx.MockTransport(handler)), calls

    def test_soft_fail_serves_cached_token_inside_margin(self):
        mgr, calls = self._flaky_manager(fail_after=1)

        async def go():
            first = await mgr.get_token()  # successful refresh
            mgr._refresh_due_at = 0.0  # simulate: renewal window opened, token still valid
            second = await mgr.get_token()  # refresh fails -> cached token served
            third = await mgr.get_token()  # inside backoff window -> no new POST
            return first, second, third

        first, second, third = _run(go())
        assert first == second == third == "access-1"
        assert len(calls) == 2  # exactly one failed re-POST, then backoff

    def test_hard_failure_when_no_cached_token(self):
        mgr, calls = self._flaky_manager(fail_after=0)
        with pytest.raises(TokenRefreshError, match="temporarily refused"):
            _run(mgr.get_token())
        # Within the backoff window the cached failure is re-raised without a POST.
        with pytest.raises(TokenRefreshError, match="temporarily refused"):
            _run(mgr.get_token())
        assert len(calls) == 1

    def test_invalidate_disqualifies_cached_token_as_fallback(self):
        mgr, calls = self._flaky_manager(fail_after=1)

        async def go():
            await mgr.get_token()
            mgr.invalidate("access-1")  # MAL rejected it mid-lifetime
            await mgr.get_token()  # refresh fails and MUST NOT re-serve access-1

        with pytest.raises(TokenRefreshError):
            _run(go())

    def test_token_aware_invalidate_ignores_replaced_token(self):
        mgr, calls = self._flaky_manager(fail_after=10)

        async def go():
            current = await mgr.get_token()
            mgr.invalidate("some-older-token")  # no-op: not the cached token
            again = await mgr.get_token()
            return current, again

        current, again = _run(go())
        assert current == again == "access-1"
        assert len(calls) == 1  # no redundant refresh

    def test_invalid_grant_message_blames_refresh_token(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "invalid_grant"})

        mgr = TokenManager("cid", "refresh-0", transport=httpx.MockTransport(handler))
        with pytest.raises(TokenRefreshError, match="MAL_REFRESH_TOKEN"):
            _run(mgr.get_token())


class _RetryManager:
    """get_token returns 'stale' first, then 'fresh' after invalidate()."""

    def __init__(self):
        self.invalidated = 0

    async def get_token(self):
        return "fresh" if self.invalidated else "stale"

    def invalidate(self, token=None):
        self.invalidated += 1


class _FakeMALClient:
    """Stands in for MALClient inside _call_mal; fails for the stale token."""

    def __init__(self, token, timeout=30.0, transport=None):
        self._token = token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def op(self):
        if self._token == "stale":
            raise MALTokenError("MAL rejected the access token")
        return {"ok": self._token}


class TestCallMalRetry:
    def test_manager_token_rejected_once_then_retried(self, monkeypatch):
        for var in ("MAL_ACCESS_TOKEN",):
            monkeypatch.delenv(var, raising=False)
        manager = _RetryManager()
        monkeypatch.setattr(server, "_TOKEN_MANAGER", manager)
        monkeypatch.setattr(server, "MALClient", _FakeMALClient)

        result = _run(server._call_mal(lambda client: client.op()))
        assert result == {"ok": "fresh"}
        assert manager.invalidated == 1

    def test_header_style_token_failure_not_retried(self, monkeypatch):
        # With a static env token (no manager) a MAL 401 surfaces immediately.
        monkeypatch.setattr(server, "_TOKEN_MANAGER", None)
        monkeypatch.setenv("MAL_ACCESS_TOKEN", "stale")
        monkeypatch.delenv("MAL_REFRESH_TOKEN", raising=False)
        monkeypatch.delenv("MAL_CLIENT_ID", raising=False)
        monkeypatch.setattr(server, "MALClient", _FakeMALClient)

        with pytest.raises(ToolError, match="rejected the access token"):
            _run(server._call_mal(lambda client: client.op()))
