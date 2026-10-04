import socket
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import url_safety
from url_safety import assert_public_url, is_public_url, UnsafeURLError, redirect_guard_hook
from security_headers import SecurityHeadersMiddleware, SECURITY_HEADERS


def _resolve_to(*ips):
    def fake(host, port, proto=0):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]
    return fake


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost/", "http://10.0.0.5/", "http://192.168.1.1/",
    "http://172.16.0.1/", "http://169.254.169.254/latest/meta-data/", "http://0.0.0.0/",
    "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://[fe80::1]/",
])
def test_internal_addresses_are_blocked(url):
    # Real resolution on purpose - IP literals and localhost need no network.
    with pytest.raises(UnsafeURLError):
        assert_public_url(url)


@pytest.mark.parametrize("url", ["ftp://example.com/", "file:///etc/passwd", "gopher://x/", "javascript:alert(1)"])
def test_non_http_schemes_are_blocked(url):
    with pytest.raises(UnsafeURLError):
        assert_public_url(url)


def test_public_address_is_allowed():
    with patch("url_safety.socket.getaddrinfo", _resolve_to("93.184.216.34")):
        assert_public_url("https://example.com/page")
        assert is_public_url("https://example.com/")


def test_hostname_resolving_to_private_ip_is_blocked():
    # e.g. attacker-controlled DNS name pointing at an internal address
    with patch("url_safety.socket.getaddrinfo", _resolve_to("10.1.2.3")):
        assert not is_public_url("http://innocent-looking.example.com/")


def test_any_private_answer_blocks_even_with_public_ones():
    with patch("url_safety.socket.getaddrinfo", _resolve_to("93.184.216.34", "127.0.0.1")):
        assert not is_public_url("http://mixed.example.com/")


def test_unresolvable_host_is_blocked():
    with patch("url_safety.socket.getaddrinfo", side_effect=socket.gaierror):
        assert not is_public_url("http://does-not-exist.invalid/")


def test_redirect_to_internal_address_is_blocked():
    resp = MagicMock(is_redirect=True, url="https://public.example.com/a", headers={"location": "http://169.254.169.254/"})
    with pytest.raises(UnsafeURLError):
        redirect_guard_hook(resp)


def test_redirect_to_public_address_is_allowed():
    resp = MagicMock(is_redirect=True, url="https://public.example.com/a", headers={"location": "/b"})
    with patch("url_safety.socket.getaddrinfo", _resolve_to("93.184.216.34")):
        assert redirect_guard_hook(resp) is resp


def test_site_discovery_fetch_does_not_request_internal_url():
    import site_discovery
    with patch("site_discovery.requests.get") as mock_get:
        assert site_discovery._fetch("http://127.0.0.1:8080/sitemap.xml") is None
        mock_get.assert_not_called()


def test_security_headers_present_on_every_response():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/x")
    def x():
        return {"ok": True}

    client = TestClient(app)
    for path in ["/x", "/missing"]:
        r = client.get(path)
        for name, value in SECURITY_HEADERS.items():
            assert r.headers[name] == value
    assert "frame-ancestors 'none'" in SECURITY_HEADERS["Content-Security-Policy"]
    assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"


def _webhook_client():
    from api.webhook import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


FORM = {"From": "whatsapp:+15551234567", "To": "whatsapp:+14155238886", "Body": "hi"}


def test_webhook_without_signature_header_is_401_not_500(monkeypatch):
    import api.webhook as webhook
    monkeypatch.setattr(webhook, "DEBUG", False)
    r = _webhook_client().post("/webhook", data=FORM)
    assert r.status_code == 401


def test_webhook_with_bad_signature_is_401(monkeypatch):
    import api.webhook as webhook
    monkeypatch.setattr(webhook, "DEBUG", False)
    r = _webhook_client().post("/webhook", data=FORM, headers={"X-Twilio-Signature": "bogus"})
    assert r.status_code == 401
