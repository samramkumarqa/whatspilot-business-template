"""
SSRF guard for every place the server fetches a URL a business owner
typed in (website indexing: site_discovery.py, crawler.py,
website_ingest.py, and add-time validation in api/website.py).

Without this, an owner could add http://127.0.0.1:PORT/, an RFC1918
address, or a cloud metadata address like http://169.254.169.254/ and the
server would fetch it from inside the deployment's network, then index
whatever came back into the AI's knowledge base.

assert_public_url() resolves the hostname and rejects the URL if ANY
resolved address is loopback, private, link-local, multicast, reserved or
unspecified. redirect_guard_hook() applies the same check to every hop of
a redirect chain (pass it as `hooks={"response": redirect_guard_hook}` to
requests.get), since a public URL can 302 to an internal one.

Known limit: the check resolves DNS separately from the connection, so a
hostname that changes its DNS answer between the check and the connect
(DNS rebinding) is not covered. Closing that fully needs pinning the
connection to the validated IP.
"""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    pass


def _is_blocked_ip(ip):
    return (
        ip.is_loopback or ip.is_private or ip.is_link_local
        or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def assert_public_url(url):
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError("Only http(s) URLs are allowed.")

    host = parsed.hostname

    if not host:
        raise UnsafeURLError("URL has no host.")

    try:
        infos = socket.getaddrinfo(host, parsed.port or 0, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise UnsafeURLError("Could not resolve that website address.")

    if not infos:
        raise UnsafeURLError("Could not resolve that website address.")

    for info in infos:
        # IPv6 scope ids ("fe80::1%eth0") are not parseable by ipaddress.
        addr = info[4][0].split("%")[0]
        ip = ipaddress.ip_address(addr)

        # An IPv4-mapped IPv6 address (::ffff:127.0.0.1) must be judged
        # as the IPv4 address it wraps.
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped

        if _is_blocked_ip(ip):
            raise UnsafeURLError(
                "That address points to a private or internal network "
                "and can't be indexed."
            )


def is_public_url(url):
    try:
        assert_public_url(url)
        return True
    except UnsafeURLError:
        return False


def redirect_guard_hook(response, *args, **kwargs):
    """requests response hook: re-validate every redirect target."""

    if response.is_redirect:
        location = response.headers.get("location", "")
        from urllib.parse import urljoin
        assert_public_url(urljoin(response.url, location))

    return response
