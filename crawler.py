from bs4 import BeautifulSoup
import requests

from urllib.parse import (
    urljoin,
    urlparse
)


def is_valid_url(url):
    """
    True if this looks like a real page worth crawling - not a login/
    cart/admin/search/legal URL or a non-HTML asset. Delegates to
    site_discovery.is_content_url() so the link-crawl fallback and the
    sitemap path agree on what counts as "content" for a general business
    site (this used to have its own narrower, docs-site-specific list -
    see site_discovery.py for why that was replaced).
    """

    from site_discovery import is_content_url

    return is_content_url(url)


def discover_links(
    start_url,
    max_pages=50,
    max_depth=3
):

    visited = set()

    # (url, depth)
    queue = [
        (
            start_url,
            0
        )
    ]

    domain = urlparse(
        start_url
    ).netloc

    while queue and len(visited) < max_pages:

        url, depth = queue.pop(0)

        if depth > max_depth:
            continue

        if url in visited:
            continue

        try:

            print(
                f"🌐 Crawling "
                f"(depth={depth}) "
                f"{url}"
            )

            response = requests.get(
                url,
                timeout=10,
                headers={
                    "User-Agent":
                    "Mozilla/5.0"
                }
            )

            if response.status_code != 200:
                continue

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            visited.add(url)

            for link in soup.find_all(
                "a",
                href=True
            ):

                href = urljoin(
                    url,
                    link["href"]
                )

                # Remove fragments
                href = href.split("#")[0]

                # Remove query params
                href = href.split("?")[0]

                parsed = urlparse(
                    href
                )

                # Domain lock
                if parsed.netloc != domain:
                    continue

                # Metadata filtering (login/cart/admin/search/legal/
                # asset URLs - see site_discovery.is_content_url)
                if not is_valid_url(href):
                    continue

                if (
                    href not in visited
                    and (href, depth + 1)
                    not in queue
                ):
                    queue.append(
                        (
                            href,
                            depth + 1
                        )
                    )

        except Exception as e:

            print(
                f"❌ Crawl failed: "
                f"{url}"
            )

            print(e)

    return sorted(
        list(visited)
    )