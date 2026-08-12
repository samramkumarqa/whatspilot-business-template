from unittest.mock import patch, MagicMock

import site_discovery


def _fake_response(text, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


URLSET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://www.solarrun.in/</loc></url>
    <url><loc>https://www.solarrun.in/products</loc></url>
    <url><loc>https://www.solarrun.in/about</loc></url>
    <url><loc>https://www.solarrun.in/contact</loc></url>
    <url><loc>https://www.solarrun.in/login</loc></url>
    <url><loc>https://www.solarrun.in/brochure.pdf</loc></url>
    <url><loc>https://other-domain.com/products</loc></url>
</urlset>
"""

SITEMAP_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>https://www.solarrun.in/sitemap-pages.xml</loc></sitemap>
    <sitemap><loc>https://www.solarrun.in/sitemap-posts.xml</loc></sitemap>
</sitemapindex>
"""

SUB_SITEMAP_PAGES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://www.solarrun.in/</loc></url>
    <url><loc>https://www.solarrun.in/products</loc></url>
</urlset>
"""

SUB_SITEMAP_POSTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://www.solarrun.in/blog/post-1</loc></url>
    <url><loc>https://www.solarrun.in/blog/post-2</loc></url>
</urlset>
"""


def test_is_content_url_blocks_known_bad_paths():
    assert site_discovery.is_content_url("https://example.com/products") is True
    assert site_discovery.is_content_url("https://example.com/login") is False
    assert site_discovery.is_content_url("https://example.com/cart") is False
    assert site_discovery.is_content_url("https://example.com/wp-admin/edit") is False
    assert site_discovery.is_content_url("https://example.com/search?q=x") is False
    assert site_discovery.is_content_url("https://example.com/brochure.pdf") is False
    assert site_discovery.is_content_url("https://example.com/logo.png") is False


def test_discover_via_sitemap_filters_offdomain_and_blocked():
    with patch("site_discovery.requests.get", return_value=_fake_response(URLSET_XML)):
        pages = site_discovery.discover_via_sitemap(
            "https://www.solarrun.in/", max_pages=25
        )

    # Normalized: trailing slash stripped (see normalize_page_url).
    assert "https://www.solarrun.in" in pages
    assert "https://www.solarrun.in/products" in pages
    assert "https://www.solarrun.in/about" in pages
    assert "https://www.solarrun.in/contact" in pages

    # Blocked: off-domain, login path, and a PDF asset.
    assert "https://other-domain.com/products" not in pages
    assert "https://www.solarrun.in/login" not in pages
    assert "https://www.solarrun.in/brochure.pdf" not in pages


def test_discover_via_sitemap_respects_max_pages_cap():
    with patch("site_discovery.requests.get", return_value=_fake_response(URLSET_XML)):
        pages = site_discovery.discover_via_sitemap(
            "https://www.solarrun.in/", max_pages=2
        )

    assert len(pages) == 2


def test_discover_via_sitemap_returns_empty_when_missing():
    with patch(
        "site_discovery.requests.get",
        return_value=_fake_response("", status_code=404),
    ):
        pages = site_discovery.discover_via_sitemap("https://www.solarrun.in/")

    assert pages == []


def test_discover_via_sitemap_follows_sitemap_index():

    def fake_get(url, timeout, headers):
        if url == "https://www.solarrun.in/sitemap.xml":
            return _fake_response(SITEMAP_INDEX_XML)
        if url == "https://www.solarrun.in/sitemap-pages.xml":
            return _fake_response(SUB_SITEMAP_PAGES_XML)
        if url == "https://www.solarrun.in/sitemap-posts.xml":
            return _fake_response(SUB_SITEMAP_POSTS_XML)
        return _fake_response("", status_code=404)

    with patch("site_discovery.requests.get", side_effect=fake_get):
        pages = site_discovery.discover_via_sitemap(
            "https://www.solarrun.in/", max_pages=25
        )

    assert "https://www.solarrun.in" in pages
    assert "https://www.solarrun.in/products" in pages
    assert "https://www.solarrun.in/blog/post-1" in pages
    assert "https://www.solarrun.in/blog/post-2" in pages


def test_discover_site_pages_uses_sitemap_when_available():
    with patch("site_discovery.requests.get", return_value=_fake_response(URLSET_XML)):
        pages = site_discovery.discover_site_pages(
            "https://www.solarrun.in/", max_pages=25
        )

    assert "https://www.solarrun.in/products" in pages
    assert "https://www.solarrun.in/login" not in pages


def test_discover_site_pages_falls_back_to_link_crawl_when_no_sitemap():
    crawled = [
        "https://www.solarrun.in/",
        "https://www.solarrun.in/products",
        "https://www.solarrun.in/login",  # should be filtered out
    ]

    with patch(
        "site_discovery.requests.get",
        return_value=_fake_response("", status_code=404),
    ), patch("site_discovery.discover_links", return_value=crawled) as mock_crawl:

        pages = site_discovery.discover_site_pages(
            "https://www.solarrun.in/", max_pages=25
        )

    mock_crawl.assert_called_once()
    assert "https://www.solarrun.in/products" in pages
    assert "https://www.solarrun.in/login" not in pages


def test_discover_site_pages_always_includes_root_url():
    # Sitemap doesn't happen to list the root url itself.
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://www.solarrun.in/products</loc></url>
    </urlset>
    """

    with patch("site_discovery.requests.get", return_value=_fake_response(xml)):
        pages = site_discovery.discover_site_pages(
            "https://www.solarrun.in/", max_pages=25
        )

    assert pages[0] == "https://www.solarrun.in"


def test_discover_site_pages_caps_total_results():
    with patch("site_discovery.requests.get", return_value=_fake_response(URLSET_XML)):
        pages = site_discovery.discover_site_pages(
            "https://www.solarrun.in/", max_pages=1
        )

    assert len(pages) == 1


def test_normalize_page_url_strips_trailing_slash_and_fragment():
    assert (
        site_discovery.normalize_page_url("https://www.solarrun.in/")
        == "https://www.solarrun.in"
    )
    assert (
        site_discovery.normalize_page_url("https://www.solarrun.in")
        == "https://www.solarrun.in"
    )
    assert (
        site_discovery.normalize_page_url("https://www.solarrun.in/products#top")
        == "https://www.solarrun.in/products"
    )


def test_discover_via_sitemap_dedupes_trailing_slash_variants():
    # A homepage listed both with and without a trailing slash (common in
    # real sitemaps) must collapse into a single entry, not two.
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://www.tatapower.com</loc></url>
        <url><loc>https://www.tatapower.com/</loc></url>
        <url><loc>https://www.tatapower.com/our-legacy</loc></url>
    </urlset>
    """

    with patch("site_discovery.requests.get", return_value=_fake_response(xml)):
        pages = site_discovery.discover_via_sitemap(
            "https://www.tatapower.com", max_pages=25
        )

    assert pages.count("https://www.tatapower.com") == 1
    assert len(pages) == 2


def test_discover_site_pages_dedupes_root_url_trailing_slash():
    # Root url configured with a trailing slash, sitemap lists the
    # homepage without one - these are the same page and must not both
    # end up in the result (and not both count against max_pages).
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://www.tatapower.com</loc></url>
        <url><loc>https://www.tatapower.com/our-legacy</loc></url>
    </urlset>
    """

    with patch("site_discovery.requests.get", return_value=_fake_response(xml)):
        pages = site_discovery.discover_site_pages(
            "https://www.tatapower.com/", max_pages=25
        )

    assert pages.count("https://www.tatapower.com") == 1
    assert pages[0] == "https://www.tatapower.com"
    assert len(pages) == 2
