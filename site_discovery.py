"""
Decides which pages of a business's website actually get indexed.

A business only ever configures one root URL (see website_manager.py's
MAX_WEBSITES_PER_USER), but that root page is rarely the whole story - a
real site can have dozens or hundreds of pages. Indexing all of them isn't
practical (slow to crawl, slow to embed, and mostly noise), so this module
picks a bounded, relevant subset:

1. Try the site's sitemap.xml first - it's the site's own authoritative
   list of real pages, so it's both faster and more accurate than guessing
   from links on the homepage.
2. If there's no sitemap, fall back to crawling links from the homepage
   (crawler.discover_links).
3. Either way, cap the result at MAX_PAGES_PER_SITE and drop pages that
   are obviously not useful knowledge-base content (login, cart, search,
   admin, etc.) via is_content_url().

This intentionally runs at *ingest* time (see website_ingest.py), not at
add-website time - the business still only ever has one "website" entry in
website_manager, but every reindex re-discovers up to MAX_PAGES_PER_SITE
pages under that one root domain to actually extract text from.
"""

import logging
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests

from crawler import discover_links

logger = logging.getLogger(__name__)

# Hard cap on how many pages of one business's website we'll ever index.
# Keeps reindex time and vector store size bounded regardless of how large
# the actual site is.
MAX_PAGES_PER_SITE = 25

# How many sitemaps to open when a site uses a sitemap-index (a sitemap of
# sitemaps) rather than a single flat sitemap.xml.
MAX_SUB_SITEMAPS = 5

REQUEST_TIMEOUT = 10

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# Path fragments that mean "not real page content" for basically any
# business site - account/auth flows, e-commerce cart/checkout, admin
# panels, search results, and legal boilerplate. Shared between the
# sitemap path and crawler.py's link-crawl fallback so both discovery
# methods apply the same notion of "worth indexing".
BLOCKED_PATH_KEYWORDS = [
    "/login",
    "/logout",
    "/signup",
    "/register",
    "/cart",
    "/checkout",
    "/account",
    "/my-account",
    "/wp-admin",
    "/wp-json",
    "/admin",
    "/search",
    "/tag/",
    "/privacy",
    "/terms",
    "mailto:",
    "javascript:",
    "tel:",
]

# File extensions that are never worth fetching as page content.
BLOCKED_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".zip", ".rar", ".mp4", ".mp3", ".css", ".js", ".xml", ".json",
)


def is_content_url(url):
    """
    True if this url is plausibly a real, indexable page rather than an
    account/cart/admin/legal/asset URL.
    """

    lowered = url.lower()

    if any(keyword in lowered for keyword in BLOCKED_PATH_KEYWORDS):
        return False

    path = urlparse(url).path.lower()

    if path.endswith(BLOCKED_EXTENSIONS):
        return False

    return True


def _same_domain(url, domain):
    return urlparse(url).netloc == domain


def normalize_page_url(url):
    """
    Strips the fragment and a single trailing slash so that equivalent
    forms of the same page - e.g. a homepage listed as both
    "https://x.com" and "https://x.com/" in a sitemap, or reached via both
    forms from different links - collapse to one canonical URL instead of
    being fetched, embedded, and counted against MAX_PAGES_PER_SITE twice.
    Matches website_manager.normalize_url()'s existing convention for the
    root URL a business configures, applied here to every discovered page.
    """

    url = url.split("#")[0].strip()

    if url.endswith("/"):
        url = url[:-1]

    return url


def _dedupe_normalized(urls):

    seen = set()
    results = []

    for url in urls:

        normalized = normalize_page_url(url)

        if normalized in seen:
            continue

        seen.add(normalized)
        results.append(normalized)

    return results


def _fetch(url):

    try:

        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers=REQUEST_HEADERS,
        )

        if response.status_code != 200:
            return None

        return response.text

    except Exception as e:

        logger.info(f"site_discovery: fetch failed for {url}: {e}")

        return None


def _parse_sitemap_urls(xml_text):
    """
    Parses a sitemap.xml document, returning (page_urls, sub_sitemap_urls).

    A <urlset> sitemap only yields page_urls. A <sitemapindex> (a sitemap
    that just lists other sitemaps) only yields sub_sitemap_urls - the
    caller is responsible for fetching those and parsing them in turn.
    """

    page_urls = []
    sub_sitemap_urls = []

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return page_urls, sub_sitemap_urls

    # Sitemap XML uses a namespace, but the local tag name (stripping the
    # "{namespace}" prefix) is enough to tell urlset/sitemapindex apart
    # without needing the exact namespace URI.
    root_tag = root.tag.rsplit("}", 1)[-1]

    for child in root:

        child_tag = child.tag.rsplit("}", 1)[-1]

        if child_tag not in ("url", "sitemap"):
            continue

        loc_el = None

        for grandchild in child:
            if grandchild.tag.rsplit("}", 1)[-1] == "loc":
                loc_el = grandchild
                break

        if loc_el is None or not loc_el.text:
            continue

        loc = loc_el.text.strip()

        if root_tag == "sitemapindex" or child_tag == "sitemap":
            sub_sitemap_urls.append(loc)
        else:
            page_urls.append(loc)

    return page_urls, sub_sitemap_urls


def discover_via_sitemap(root_url, max_pages=MAX_PAGES_PER_SITE):
    """
    Returns up to max_pages same-domain, content page URLs found via the
    site's sitemap.xml, or [] if it has none / it couldn't be parsed.
    """

    parsed_root = urlparse(root_url)
    domain = parsed_root.netloc
    sitemap_url = f"{parsed_root.scheme}://{domain}/sitemap.xml"

    xml_text = _fetch(sitemap_url)

    if not xml_text:
        return []

    page_urls, sub_sitemap_urls = _parse_sitemap_urls(xml_text)

    # Sitemap-index: pull page URLs out of a bounded number of the
    # sub-sitemaps it lists, stopping early once we plausibly have enough
    # candidates (before filtering) to satisfy max_pages.
    for sub_url in sub_sitemap_urls[:MAX_SUB_SITEMAPS]:

        if len(page_urls) >= max_pages * 2:
            break

        sub_xml = _fetch(sub_url)

        if not sub_xml:
            continue

        sub_pages, _ = _parse_sitemap_urls(sub_xml)

        page_urls.extend(sub_pages)

    seen = set()
    results = []

    for url in page_urls:

        url = normalize_page_url(url)

        if url in seen:
            continue

        seen.add(url)

        if not _same_domain(url, domain):
            continue

        if not is_content_url(url):
            continue

        results.append(url)

        if len(results) >= max_pages:
            break

    return results


def discover_site_pages(root_url, max_pages=MAX_PAGES_PER_SITE):
    """
    The main entry point: figures out which pages of root_url's site to
    index, capped at max_pages. Tries the sitemap first, falls back to
    crawling links from the homepage, and always makes sure root_url
    itself is included.
    """

    pages = discover_via_sitemap(root_url, max_pages=max_pages)

    if not pages:

        logger.info(
            f"site_discovery: no usable sitemap for {root_url}, "
            f"falling back to link-crawl"
        )

        crawled = discover_links(root_url, max_pages=max_pages)
        pages = _dedupe_normalized(
            url for url in crawled if is_content_url(url)
        )

    root_url = normalize_page_url(root_url)

    if root_url not in pages:
        pages = [root_url] + pages
    else:
        # Keep the root page first regardless of where it landed in the
        # discovered order, since it's the one page we always guarantee.
        pages = [root_url] + [url for url in pages if url != root_url]

    return pages[:max_pages]
