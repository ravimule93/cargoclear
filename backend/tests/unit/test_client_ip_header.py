"""CLIENT_IP_HEADER: behind the UI's server-side proxy the socket peer is always the proxy, so without this setting every
user shares ONE rate-limit bucket. The proxy passes the end user's IP in a header; the (private) API keys on it.

Safety properties tested here: a missing or garbled header falls through to the next source (never to "exempt"), and the
header is ignored entirely unless the deployment says its sender is trusted (the setting is unset by default).
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.gateway.limits import client_key
from tests.helpers import asgi_call, asgi_scope

HEADER = "x-cargoclear-client-ip"
PROXY = ("10.8.0.2", 40000)  # the UI's server: the socket peer of EVERY request


def scope_with(peer, **headers):
    raw = [(name.replace("_", "-").encode(), value.encode()) for name, value in headers.items()]
    return asgi_scope("POST", "/api/v1/bundles", headers=raw, client=peer)


@pytest.fixture
def trusted_header(monkeypatch):
    monkeypatch.setattr(settings, "client_ip_header", HEADER)


def test_the_header_is_ignored_unless_configured() -> None:
    assert settings.client_ip_header is None
    assert client_key(scope_with(PROXY, x_cargoclear_client_ip="203.0.113.9")) == "10.8.0.2"


def test_the_configured_header_names_the_user(trusted_header) -> None:
    assert client_key(scope_with(PROXY, x_cargoclear_client_ip="203.0.113.9")) == "203.0.113.9"
    assert client_key(scope_with(PROXY, x_cargoclear_client_ip=" 2001:DB8:0:0:0:0:0:1 ")) == "2001:db8::1"


def test_a_missing_or_invalid_header_falls_back_to_the_peer(trusted_header) -> None:
    assert client_key(scope_with(PROXY)) == "10.8.0.2"
    assert client_key(scope_with(PROXY, x_cargoclear_client_ip="")) == "10.8.0.2"
    assert client_key(scope_with(PROXY, x_cargoclear_client_ip="not-an-ip")) == "10.8.0.2"
    assert client_key(scope_with(PROXY, x_cargoclear_client_ip="999.1.1.1")) == "10.8.0.2"
    assert client_key(scope_with(None)) == "unknown"


def test_the_header_wins_over_x_forwarded_for(trusted_header, monkeypatch) -> None:
    monkeypatch.setattr(settings, "trust_forwarded_for", True)

    both = scope_with(PROXY, x_cargoclear_client_ip="203.0.113.9", x_forwarded_for="6.6.6.6")
    assert client_key(both) == "203.0.113.9"
    # an unusable header does not disable the next source
    assert client_key(scope_with(PROXY, x_cargoclear_client_ip="junk", x_forwarded_for="6.6.6.6")) == "6.6.6.6"


async def post_bundle(**headers):
    return await asgi_call(
        "POST", "/api/v1/bundles", body=b"{}", client=PROXY,
        headers={"content-type": "application/json", **{k.replace("_", "-"): v for k, v in headers.items()}},
    )


@pytest.mark.asyncio
async def test_without_the_header_everyone_behind_the_proxy_shares_one_budget() -> None:
    for _ in range(60):
        await post_bundle(x_cargoclear_client_ip="203.0.113.1")

    # a different user, same proxy: refused, because the header is not trusted
    assert (await post_bundle(x_cargoclear_client_ip="203.0.113.2")).status == 429


@pytest.mark.asyncio
async def test_with_the_header_each_user_has_a_budget_of_their_own(trusted_header) -> None:
    for _ in range(60):
        assert (await post_bundle(x_cargoclear_client_ip="203.0.113.1")).status == 201

    assert (await post_bundle(x_cargoclear_client_ip="203.0.113.1")).status == 429    # the heavy user is limited ...
    assert (await post_bundle(x_cargoclear_client_ip="203.0.113.2")).status == 201    # ... another user is not
    assert (await post_bundle()).status == 201                                         # no header: the proxy's own bucket
